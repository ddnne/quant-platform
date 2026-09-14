"""READY ledger and snapshot-publication session on one market DB.

Owns staging open/commit/rollback/close and remaining market SQL for READY
publication, coherence facts, and pinned artifact reads. Runtime policy
converts these facts into PASS/FAIL; this module does not decide READY and
does not import paper_runtime.
"""

from __future__ import annotations

import json
import shutil
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator, Sequence
from urllib.parse import quote
from uuid import uuid4

from storage.coverage_proof import (
    CoverageProofVerificationError,
    VerifiedCoverageProof,
    persist_coverage_proof,
    require_persisted_coverage_proof,
    _coverage_proof,
    _validation_cutoff_for_build,
)
from storage.sqlite_store import SqliteStore

from .read_clock import write_publisher_owned_snapshot_observation_clock
from .sqlite_identity import (
    RESEARCH_SNAPSHOT_MANIFEST_FORMAT,
    _data_snapshot_id_from_open_connection,
)

_READY_ARTIFACT_MAX_BYTES = 64 * 1024 * 1024 * 1024
_READY_COPY_FREE_SPACE_MARGIN_BYTES = 64 * 1024 * 1024
_READY_COPY_BUDGET_SECONDS = 15 * 60


class LedgerTableMissing(Exception):
    """A required READY ledger table is absent."""

    def __init__(self, table: str) -> None:
        super().__init__(table)
        self.table = table


class ReadyLedgerSession:
    """Purpose-specific READY market session. Not a Connection API."""

    __slots__ = ("_conn",)

    def __init__(self, conn: sqlite3.Connection) -> None:
        if type(conn) is not sqlite3.Connection:
            raise TypeError("ready ledger session requires sqlite3.Connection")
        self._conn = conn

    def require_persisted_coverage_proof(
        self,
        required_datasets: Sequence[str],
        proof_id: object,
        *,
        build_id: object,
    ) -> VerifiedCoverageProof:
        return require_persisted_coverage_proof(
            self._conn,
            required_datasets,
            proof_id,
            build_id=build_id,
        )

    def raw_retention_rows(
        self, run_id: int, required: tuple[str, ...]
    ) -> tuple[tuple[str, str], ...] | None:
        try:
            placeholders = ",".join("?" for _ in required)
            rows = self._conn.execute(
                "SELECT dataset, completeness FROM raw_retention_manifests "
                f"WHERE run_id=? AND dataset IN ({placeholders})",
                (run_id, *required),
            ).fetchall()
        except sqlite3.Error:
            return None
        return tuple((str(row[0]), str(row[1])) for row in rows)

    def validation_rows(
        self, run_id: int, required: tuple[str, ...]
    ) -> tuple[tuple[str, str], ...] | None:
        try:
            placeholders = ",".join("?" for _ in required)
            rows = self._conn.execute(
                "SELECT dataset, status FROM ingestion_validation "
                f"WHERE run_id=? AND dataset IN ({placeholders})",
                (run_id, *required),
            ).fetchall()
        except sqlite3.Error:
            return None
        return tuple((str(row[0]), str(row[1])) for row in rows)

    def latest_natural_key_state(self) -> str | None:
        try:
            row = self._conn.execute(
                "SELECT state FROM natural_key_migrations "
                "ORDER BY rowid DESC LIMIT 1"
            ).fetchone()
        except sqlite3.Error:
            return None
        if row:
            return str(row[0])
        return None

    def quality_rows(
        self, build_id: str
    ) -> tuple[tuple[str, str], ...] | None:
        try:
            rows = self._conn.execute(
                "SELECT status, results_json FROM snapshot_quality_results "
                "WHERE build_id=?",
                (build_id,),
            ).fetchall()
        except sqlite3.Error:
            return None
        return tuple((str(row[0]), str(row[1])) for row in rows)

    def max_change_seq(self) -> int | None:
        try:
            row = self._conn.execute(
                "SELECT COALESCE(MAX(change_seq), 0) FROM ingestion_change_log"
            ).fetchone()
        except sqlite3.Error:
            return None
        return int(row[0]) if row else 0

    def last_applied_change_seq(self) -> int | None:
        try:
            row = self._conn.execute(
                "SELECT last_applied_change_seq FROM sync_change_state "
                "WHERE feed='jquants_records'"
            ).fetchone()
        except sqlite3.Error:
            return None
        return int(row[0]) if row else 0

    def commit(self) -> None:
        self._conn.commit()

    def rollback(self) -> None:
        self._conn.rollback()

    def coverage_segments(self) -> tuple[dict[str, Any], ...]:
        try:
            rows = self._conn.execute("SELECT * FROM coverage_segments").fetchall()
        except sqlite3.OperationalError as exc:
            raise LedgerTableMissing("coverage_segments") from exc
        return tuple(dict(row) for row in rows)

    def complete_coverage_segments(self) -> tuple[dict[str, Any], ...]:
        try:
            rows = self._conn.execute(
                "SELECT * FROM coverage_segments WHERE status=?",
                ("COMPLETE",),
            ).fetchall()
        except sqlite3.OperationalError as exc:
            raise LedgerTableMissing("coverage_segments") from exc
        return tuple(dict(row) for row in rows)

    def collection_receipts_for_dataset(
        self, dataset: str
    ) -> tuple[dict[str, Any], ...]:
        try:
            rows = self._conn.execute(
                "SELECT * FROM collection_receipts WHERE dataset=? "
                "ORDER BY checked_at DESC, run_id DESC",
                (dataset,),
            ).fetchall()
        except sqlite3.OperationalError as exc:
            raise LedgerTableMissing("collection_receipts") from exc
        return tuple(dict(row) for row in rows)

    def ingestion_validation_status_rows(
        self, run_id: int
    ) -> tuple[tuple[str, str], ...]:
        try:
            rows = self._conn.execute(
                "SELECT dataset, status FROM ingestion_validation WHERE run_id = ?",
                (run_id,),
            ).fetchall()
        except sqlite3.OperationalError as exc:
            raise LedgerTableMissing("ingestion_validation") from exc
        return tuple((str(row[0]), str(row[1])) for row in rows)

    def max_ingestion_validation_run_id(self) -> int | None:
        try:
            row = self._conn.execute(
                "SELECT MAX(run_id) AS max_run_id FROM ingestion_validation"
            ).fetchone()
        except sqlite3.OperationalError as exc:
            raise LedgerTableMissing("ingestion_validation") from exc
        if row is None:
            return None
        value = row["max_run_id"] if "max_run_id" in row.keys() else row[0]
        if value is None:
            return None
        return int(value)

    def natural_key_migration_probe(self) -> tuple[str, str] | None:
        for sql, table in (
            (
                "SELECT state FROM natural_key_migrations ORDER BY rowid DESC LIMIT 1",
                "natural_key_migrations",
            ),
            (
                "SELECT state FROM natural_key_migration ORDER BY id DESC LIMIT 1",
                "natural_key_migration",
            ),
        ):
            try:
                row = self._conn.execute(sql).fetchone()
            except sqlite3.OperationalError:
                continue
            if row is None:
                continue
            state = row["state"] if "state" in row.keys() else row[0]
            return str(state), table
        return None

    def latest_snapshot_quality(self) -> dict[str, Any] | None:
        try:
            row = self._conn.execute(
                """SELECT status, summary_json, evaluated_at
                   FROM snapshot_quality_results
                   ORDER BY evaluated_at DESC
                   LIMIT 1"""
            ).fetchone()
        except sqlite3.OperationalError as exc:
            raise LedgerTableMissing("snapshot_quality_results") from exc
        if row is None:
            return None
        return {
            "status": row["status"] if "status" in row.keys() else row[0],
            "summary": row["summary_json"] if "summary_json" in row.keys() else row[1],
            "evaluated_at": (
                row["evaluated_at"] if "evaluated_at" in row.keys() else row[2]
            ),
        }

    def change_sequence_maxima(self) -> tuple[int, ...]:
        candidates = [
            (
                "SELECT MAX(last_applied_change_seq) AS max_seq "
                "FROM sync_change_state"
            ),
            "SELECT MAX(change_seq) AS max_seq FROM ingestion_change_log",
            "SELECT MAX(change_seq) AS max_seq FROM change_log",
        ]
        found: list[int] = []
        for sql in candidates:
            try:
                row = self._conn.execute(sql).fetchone()
            except sqlite3.OperationalError:
                continue
            if row is None:
                continue
            max_seq = row["max_seq"] if "max_seq" in row.keys() else row[0]
            if max_seq is None:
                continue
            found.append(int(max_seq))
        return tuple(found)

    def latest_jquants_ingestion_run(self) -> dict[str, Any] | None:
        run = self._conn.execute(
            "SELECT id, status, detail FROM ingestion_run_log "
            "WHERE source='jquants' ORDER BY id DESC LIMIT 1"
        ).fetchone()
        if run is None:
            return None
        return dict(run) if isinstance(run, sqlite3.Row) else {
            "id": run[0],
            "status": run[1],
            "detail": run[2],
        }

    def ingestion_validation_run_rows(
        self, run_id: int
    ) -> tuple[dict[str, Any], ...]:
        rows = self._conn.execute(
            "SELECT dataset, status, finished_at, rows_seen, rows_inserted, "
            "rows_revisions FROM ingestion_validation WHERE run_id = ? "
            "ORDER BY dataset, id",
            (run_id,),
        ).fetchall()
        return tuple(
            dict(row) if isinstance(row, sqlite3.Row) else {
                "dataset": row[0],
                "status": row[1],
                "finished_at": row[2],
                "rows_seen": row[3],
                "rows_inserted": row[4],
                "rows_revisions": row[5],
            }
            for row in rows
        )

    def watermark_rows(
        self, required: tuple[str, ...]
    ) -> tuple[dict[str, Any], ...]:
        placeholders = ",".join("?" for _ in required)
        rows = self._conn.execute(
            "SELECT dataset, last_event_date, last_ingested_at "
            "FROM ingestion_watermarks "
            f"WHERE dataset IN ({placeholders}) ORDER BY dataset",
            required,
        ).fetchall()
        return tuple(dict(row) for row in rows)

    def raw_retention_manifest_rows(
        self, run_id: int, required: tuple[str, ...]
    ) -> tuple[dict[str, Any], ...] | None:
        table = self._conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' "
            "AND name='raw_retention_manifests'"
        ).fetchone()
        if table is None:
            return None
        placeholders = ",".join("?" for _ in required)
        rows = self._conn.execute(
            "SELECT dataset, run_id, manifest_key, page_count, row_count, "
            "raw_bytes, data_digest, completeness, created_at "
            "FROM raw_retention_manifests WHERE run_id=? "
            f"AND dataset IN ({placeholders}) ORDER BY dataset",
            (run_id, *required),
        ).fetchall()
        return tuple(dict(row) for row in rows)

    def quality_results_json(self, build_id: str) -> str | None:
        row = self._conn.execute(
            "SELECT results_json FROM snapshot_quality_results WHERE build_id=?",
            (build_id,),
        ).fetchone()
        if row is None:
            return None
        return str(row[0])

    def validation_cutoff_for_build(self, build_id: str) -> str:
        return _validation_cutoff_for_build(self._conn, build_id)

    def refresh_coverage_ledger(
        self,
        staging_path: Path,
        *,
        datasets: tuple[str, ...],
        today: str,
        build_id: str,
    ) -> list[dict[str, Any]]:
        from storage.coverage_ledger import refresh_coverage_ledger as refresh

        return refresh(
            self._conn,
            staging_path,
            datasets=datasets,
            today=today,
            index_text=None,
            _publication_build_id=build_id,
        )

    def build_coverage_proof(
        self,
        required: tuple[str, ...],
        coverage_rows: list[dict[str, Any]],
        *,
        publication_cutoff: str,
    ) -> dict[str, Any]:
        return _coverage_proof(
            self._conn,
            required,
            coverage_rows,
            publication_cutoff=publication_cutoff,
        )

    def persist_coverage_proof(
        self, required: tuple[str, ...], *, build_id: str
    ) -> str:
        return persist_coverage_proof(self._conn, required, build_id=build_id)

    def persist_quality_results(
        self,
        *,
        build_id: str,
        status: str,
        policy_version: str,
        evaluated_at: str,
        summary_json: str,
        results_json: str,
    ) -> None:
        self._conn.execute(
            """
            INSERT INTO snapshot_quality_results
                (build_id, status, policy_version, evaluated_at, summary_json,
                 results_json)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(build_id) DO UPDATE SET
                status=excluded.status,
                policy_version=excluded.policy_version,
                evaluated_at=excluded.evaluated_at,
                summary_json=excluded.summary_json,
                results_json=excluded.results_json
            """,
            (
                build_id,
                status,
                policy_version,
                evaluated_at,
                summary_json,
                results_json,
            ),
        )
        self._conn.commit()

    def begin_sync(self, *, started_at: str) -> str:
        build_id = "build-" + uuid4().hex
        self._conn.execute(
            """
            INSERT INTO local_snapshot_policy
                (singleton, require_manifest, snapshot_ready, sync_started_at,
                 last_error, publication_state, active_build_id,
                 active_snapshot_id)
            VALUES (1, 1, 0, ?, NULL, 'BUILDING', ?, NULL)
            ON CONFLICT(singleton) DO UPDATE SET
                require_manifest = 1,
                snapshot_ready = 0,
                sync_started_at = excluded.sync_started_at,
                last_error = NULL,
                publication_state = 'BUILDING',
                active_build_id = excluded.active_build_id,
                active_snapshot_id = NULL
            """,
            (started_at, build_id),
        )
        self._conn.commit()
        return build_id

    def fail_sync(self, error: str) -> None:
        self._conn.execute(
            """
            INSERT INTO local_snapshot_policy
                (singleton, require_manifest, snapshot_ready, last_error,
                 publication_state, active_snapshot_id)
            VALUES (1, 1, 0, ?, 'REJECTED', NULL)
            ON CONFLICT(singleton) DO UPDATE SET
                require_manifest = 1,
                snapshot_ready = 0,
                last_error = excluded.last_error,
                publication_state = 'REJECTED',
                active_snapshot_id = NULL
            """,
            (error[:2000],),
        )
        self._conn.commit()

    def persist_building_publication(
        self,
        *,
        build_id: str,
        created_at: str,
        staging_path: str,
        contract_version: str,
        coverage_policy_version: str,
        quality_policy_version: str,
    ) -> None:
        self._conn.execute(
            """
            INSERT INTO local_snapshot_policy
                (singleton, require_manifest, snapshot_ready, sync_started_at,
                 last_error, publication_state, active_build_id,
                 active_snapshot_id)
            VALUES (1, 1, 0, ?, NULL, 'BUILDING', ?, NULL)
            ON CONFLICT(singleton) DO UPDATE SET
                require_manifest=1, snapshot_ready=0, last_error=NULL,
                publication_state='BUILDING', active_build_id=excluded.active_build_id,
                active_snapshot_id=NULL
            """,
            (created_at, build_id),
        )
        self._conn.execute(
            """
            INSERT INTO snapshot_publications
                (build_id, state, staging_path, contract_version,
                 coverage_policy_version, quality_policy_version, created_at)
            VALUES (?, 'BUILDING', ?, ?, ?, ?, ?)
            """,
            (
                build_id,
                staging_path,
                contract_version,
                coverage_policy_version,
                quality_policy_version,
                created_at,
            ),
        )
        self._conn.commit()

    def persist_synced_publication(self, build_id: str) -> None:
        self._conn.execute(
            "UPDATE snapshot_publications SET state='SYNCED' WHERE build_id=?",
            (build_id,),
        )
        self._conn.commit()

    def persist_synced_policy_row(self) -> None:
        self._conn.execute(
            "UPDATE local_snapshot_policy SET publication_state='SYNCED' "
            "WHERE singleton=1"
        )

    def mark_publication_validating(self, build_id: str) -> None:
        self._conn.execute(
            "UPDATE snapshot_publications SET state='VALIDATING' WHERE build_id=?",
            (build_id,),
        )
        self._conn.commit()

    def mark_publication_rejected(self, build_id: str, reason: str) -> None:
        self._conn.execute(
            "UPDATE snapshot_publications SET state='REJECTED', "
            "rejection_reason=? WHERE build_id=?",
            (reason, build_id),
        )
        self._conn.commit()

    def update_local_snapshot_policy(
        self,
        *,
        publication_state: str,
        snapshot_ready: bool,
        last_error: str | None,
        active_snapshot_id: str | None,
    ) -> None:
        self._conn.execute(
            "UPDATE local_snapshot_policy SET publication_state=?, "
            "snapshot_ready=?, last_error=?, active_snapshot_id=? "
            "WHERE singleton=1",
            (
                publication_state,
                int(snapshot_ready),
                last_error,
                active_snapshot_id,
            ),
        )
        self._conn.commit()

    def persist_ready_on_staging(
        self,
        *,
        build_id: str,
        snapshot_id: str,
        artifact_path: str,
        manifest_path: str,
        run_id: int,
        change_seq: int,
        committed_at: str,
        manifest_json: str,
    ) -> None:
        self._conn.execute(
            "UPDATE snapshot_publications SET snapshot_id=?, state='READY', "
            "artifact_path=?, manifest_path=?, source_run_id=?, change_seq=?, "
            "committed_at=?, rejection_reason=NULL, manifest_json=? "
            "WHERE build_id=?",
            (
                snapshot_id,
                artifact_path,
                manifest_path,
                run_id,
                change_seq,
                committed_at,
                manifest_json,
                build_id,
            ),
        )
        self._conn.execute(
            "UPDATE local_snapshot_policy SET snapshot_ready=0, "
            "publication_state='READY', active_snapshot_id=?, last_error=NULL "
            "WHERE singleton=1",
            (snapshot_id,),
        )
        self._conn.commit()

    def reject_publication_after_failure(self, build_id: str, error: str) -> None:
        try:
            self._conn.rollback()
            self._conn.execute(
                "UPDATE snapshot_publications SET state='REJECTED', "
                "rejection_reason=? WHERE build_id=?",
                (error, build_id),
            )
            self._conn.execute(
                "UPDATE local_snapshot_policy SET snapshot_ready=0, "
                "publication_state='REJECTED', active_snapshot_id=NULL, "
                "last_error=? WHERE singleton=1",
                (error,),
            )
            self._conn.commit()
        except sqlite3.Error:
            self._conn.rollback()

    def backup_sqlite(self, target_path: Path) -> None:
        page_count = int(self._conn.execute("PRAGMA page_count").fetchone()[0])
        page_size = int(self._conn.execute("PRAGMA page_size").fetchone()[0])
        expected_bytes = page_count * page_size
        if expected_bytes <= 0 or expected_bytes > _READY_ARTIFACT_MAX_BYTES:
            raise RuntimeError("READY SQLite source exceeds the fixed artifact bound")
        free = shutil.disk_usage(target_path.parent).free
        if free < expected_bytes + _READY_COPY_FREE_SPACE_MARGIN_BYTES:
            raise RuntimeError("READY snapshot destination has insufficient free space")
        deadline = time.monotonic() + _READY_COPY_BUDGET_SECONDS

        def require_copy_budget(
            _status: int,
            _remaining: int,
            _total: int,
        ) -> None:
            if time.monotonic() >= deadline:
                raise TimeoutError("READY SQLite copy deadline exceeded")

        target = sqlite3.connect(str(target_path))
        try:
            self._conn.backup(
                target,
                pages=1024,
                progress=require_copy_budget,
                sleep=0.0,
            )
        finally:
            target.close()

    def write_observation_clock(self, observed_through: str) -> str:
        return write_publisher_owned_snapshot_observation_clock(
            self._conn, observed_through
        )

    def embed_ready_manifest(
        self,
        *,
        snapshot_id: str,
        committed_at: str,
        run_id: int,
        change_seq: int,
        manifest_json: str,
        artifact_path: str,
        manifest_path: str,
        build_id: str,
    ) -> None:
        self._conn.execute(
            """
            INSERT OR REPLACE INTO local_snapshot_manifests
                (snapshot_id, format, committed_at, source_run_id,
                 change_seq, manifest_json)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                snapshot_id,
                RESEARCH_SNAPSHOT_MANIFEST_FORMAT,
                committed_at,
                run_id,
                change_seq,
                manifest_json,
            ),
        )
        self._conn.execute(
            "UPDATE local_snapshot_policy SET snapshot_ready=1, "
            "publication_state='READY', active_snapshot_id=?, "
            "last_error=NULL WHERE singleton=1",
            (snapshot_id,),
        )
        self._conn.execute(
            "UPDATE snapshot_publications SET snapshot_id=?, state='READY', "
            "artifact_path=?, manifest_path=?, source_run_id=?, change_seq=?, "
            "committed_at=?, rejection_reason=NULL, manifest_json=? "
            "WHERE build_id=?",
            (
                snapshot_id,
                artifact_path,
                manifest_path,
                run_id,
                change_seq,
                committed_at,
                manifest_json,
                build_id,
            ),
        )
        self._conn.commit()

    def integrity_check(self) -> str:
        return str(self._conn.execute("PRAGMA integrity_check").fetchone()[0])

    def wal_checkpoint_truncate(self) -> None:
        self._conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")


def ready_ledger_session_from_store(store: object) -> ReadyLedgerSession:
    if type(store) is not SqliteStore:
        raise TypeError("snapshot sync requires the governed SqliteStore")
    return ReadyLedgerSession(store._conn)  # noqa: SLF001 — data-plane store lifetime


@contextmanager
def ready_publication_session(
    db_path: str | Path,
) -> Iterator[ReadyLedgerSession]:
    """Own one staging market connection for READY publication."""

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        yield ReadyLedgerSession(conn)
    finally:
        conn.close()


def begin_snapshot_sync(store: object, *, started_at: str) -> str:
    return ready_ledger_session_from_store(store).begin_sync(started_at=started_at)


def fail_snapshot_sync(store: object, error: str) -> None:
    ready_ledger_session_from_store(store).fail_sync(error)


def open_sqlite_from_pinned_fd(fd: int) -> sqlite3.Connection:
    descriptor_paths = (
        Path(f"/dev/fd/{fd}"),
        Path(f"/proc/self/fd/{fd}"),
    )
    descriptor_path = next(
        (candidate for candidate in descriptor_paths if candidate.exists()),
        None,
    )
    if descriptor_path is None:
        raise RuntimeError("READY descriptor-backed SQLite access is unavailable")
    uri = "file:" + quote(str(descriptor_path)) + "?mode=ro&immutable=1"
    try:
        conn = sqlite3.connect(uri, uri=True)
    except sqlite3.Error as exc:
        raise RuntimeError("READY descriptor-backed SQLite open failed") from exc
    conn.row_factory = sqlite3.Row
    return conn


def _embedded_research_manifest(
    conn: sqlite3.Connection,
    snapshot_id: str,
    *,
    expected_format: str,
) -> dict[str, object]:
    try:
        rows = conn.execute(
            "SELECT format, manifest_json FROM local_snapshot_manifests "
            "WHERE snapshot_id=?",
            (snapshot_id,),
        ).fetchall()
    except sqlite3.Error as exc:
        raise RuntimeError(
            "READY snapshot has no readable embedded research manifest"
        ) from exc
    if len(rows) != 1 or rows[0][0] != expected_format:
        raise RuntimeError(
            "READY snapshot embedded research manifest identity is invalid"
        )
    try:
        embedded = json.loads(rows[0][1])
    except (TypeError, json.JSONDecodeError) as exc:
        raise RuntimeError(
            "READY snapshot embedded research manifest is invalid JSON"
        ) from exc
    if not isinstance(embedded, dict):
        raise RuntimeError(
            "READY snapshot embedded research manifest is not an object"
        )
    return embedded


def read_pinned_ready_artifact_facts(
    fd: int,
    *,
    snapshot_id: str,
    expected_format: str,
    require_data_snapshot_id: bool,
) -> tuple[dict[str, object], str | None]:
    conn = open_sqlite_from_pinned_fd(fd)
    try:
        embedded = _embedded_research_manifest(
            conn, snapshot_id, expected_format=expected_format
        )
        identity = None
        if require_data_snapshot_id:
            identity = _data_snapshot_id_from_open_connection(conn)
        return embedded, identity
    finally:
        conn.close()


__all__ = [
    "CoverageProofVerificationError",
    "LedgerTableMissing",
    "ReadyLedgerSession",
    "begin_snapshot_sync",
    "fail_snapshot_sync",
    "open_sqlite_from_pinned_fd",
    "read_pinned_ready_artifact_facts",
    "ready_publication_session",
]
