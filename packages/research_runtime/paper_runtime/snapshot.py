"""Cheap, control-plane-based identifiers for local SQLite data snapshots."""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import sqlite3
import stat
import tempfile
from datetime import datetime, timezone
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import quote
from uuid import uuid4

from data_contracts.coverage import (
    POLICY_VERSION as COVERAGE_POLICY_VERSION,
    all_coverage_contracts,
)
from data_contracts.jsda import JSDA_CONTRACT_VERSION
from data_contracts.loader import SCHEMA_VERSION as DATASET_CONTRACT_VERSION
from paper_runtime.snapshot_coverage_proof import (
    _coverage_v2_proof,
    _verify_coverage_v2_manifest,
)
from paper_runtime.snapshot_persist import (
    _atomic_json,
    _copy_sqlite,
)
from paper_runtime.snapshot_publish_policy import (
    _evaluate_publication_gate,
    _transition_policy,
)


DATA_SNAPSHOT_FORMAT = "paper-data-snapshot/v1"
LOCAL_SNAPSHOT_MANIFEST_FORMAT = "local-snapshot-manifest/v1"
RESEARCH_SNAPSHOT_MANIFEST_FORMAT = "research-snapshot-manifest/v2"
QUALITY_POLICY_VERSION = "b0+phase35-daily+coverage/v2"
SNAPSHOT_STATES = frozenset(
    {"BUILDING", "SYNCED", "VALIDATING", "READY", "REJECTED"}
)
_SNAPSHOT_ID_RE = re.compile(r"sha256:[0-9a-f]{64}\Z")

_WATERMARK_COLUMNS = (
    "dataset",
    "last_event_date",
    "last_ingested_at",
)
_VALIDATION_LATEST_COLUMNS = (
    "id",
    "run_id",
    "dataset",
    "started_at",
    "finished_at",
    "status",
    "rows_seen",
    "rows_inserted",
    "rows_revisions",
    "available_at_min",
    "available_at_max",
)
_VALIDATION_SUM_COLUMNS = (
    "rows_seen",
    "rows_inserted",
    "rows_revisions",
)


class SnapshotRejected(RuntimeError):
    """Raised when a staging DB cannot pass the publication gate."""


@dataclass(frozen=True)
class ReadySnapshot:
    """A verified, content-addressed READY snapshot artifact."""

    snapshot_id: str
    db_path: Path
    manifest_path: Path
    manifest: dict[str, Any]

    @property
    def committed_at(self) -> str:
        return str(self.manifest["committed_at"])


def _connect_readonly(path: Path) -> sqlite3.Connection:
    uri = "file:" + quote(str(path.resolve())) + "?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def _quote_identifier(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


def _stable_value(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else {"float": repr(value)}
    if isinstance(value, bytes):
        return {"bytes_hex": value.hex()}
    return {"type": type(value).__name__, "repr": repr(value)}


def _table_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    quoted = _quote_identifier(table)
    return {
        str(row["name"])
        for row in conn.execute(f"PRAGMA table_info({quoted})")
    }


def _schema_state(conn: sqlite3.Connection) -> dict[str, Any]:
    user_version = int(conn.execute("PRAGMA user_version").fetchone()[0])
    schema_version = int(conn.execute("PRAGMA schema_version").fetchone()[0])
    definitions = [
        {
            "type": str(row["type"]),
            "name": str(row["name"]),
            "table": str(row["tbl_name"]),
            "sql": None if row["sql"] is None else str(row["sql"]),
        }
        for row in conn.execute(
            "SELECT type, name, tbl_name, sql FROM sqlite_schema "
            "ORDER BY type, name, tbl_name"
        )
    ]
    return {
        "user_version": user_version,
        "schema_version": schema_version,
        "definitions": definitions,
    }


def _watermark_state(
    conn: sqlite3.Connection,
    tables: set[str],
) -> list[dict[str, Any]]:
    if "ingestion_watermarks" not in tables:
        return []
    available = _table_columns(conn, "ingestion_watermarks")
    if "dataset" not in available:
        return []
    selected = [column for column in _WATERMARK_COLUMNS if column in available]
    if not ({"last_event_date", "last_ingested_at"} & set(selected)):
        return []
    projection = ", ".join(_quote_identifier(column) for column in selected)
    rows = conn.execute(
        f"SELECT {projection} FROM ingestion_watermarks ORDER BY dataset"
    )
    return [
        {column: _stable_value(row[column]) for column in selected}
        for row in rows
    ]


def _validation_state(
    conn: sqlite3.Connection,
    tables: set[str],
) -> list[dict[str, Any]]:
    if "ingestion_validation" not in tables:
        return []
    available = _table_columns(conn, "ingestion_validation")
    if "dataset" not in available:
        return []

    dataset_sql = _quote_identifier("dataset")
    sums = [column for column in _VALIDATION_SUM_COLUMNS if column in available]
    aggregate_parts = ["COUNT(*) AS row_count"]
    aggregate_parts.extend(
        f"COALESCE(SUM({_quote_identifier(column)}), 0) AS "
        f"{_quote_identifier('sum_' + column)}"
        for column in sums
    )
    for column in ("id", "started_at", "finished_at"):
        if column in available:
            aggregate_parts.append(
                f"MAX({_quote_identifier(column)}) AS "
                f"{_quote_identifier('max_' + column)}"
            )
    aggregate_sql = ", ".join(aggregate_parts)
    aggregates: dict[Any, dict[str, Any]] = {}
    for row in conn.execute(
        f"SELECT {dataset_sql} AS dataset, {aggregate_sql} "
        "FROM ingestion_validation GROUP BY dataset ORDER BY dataset"
    ):
        dataset = row["dataset"]
        aggregates[dataset] = {
            key: _stable_value(row[key])
            for key in row.keys()
            if key != "dataset"
        }

    if "status" in available:
        for row in conn.execute(
            "SELECT dataset, status, COUNT(*) AS status_count "
            "FROM ingestion_validation "
            "GROUP BY dataset, status ORDER BY dataset, status"
        ):
            status_counts = aggregates[row["dataset"]].setdefault(
                "status_counts", []
            )
            status_counts.append(
                {
                    "status": _stable_value(row["status"]),
                    "count": int(row["status_count"]),
                }
            )

    latest_columns = [
        column for column in _VALIDATION_LATEST_COLUMNS if column in available
    ]
    order_columns = [
        column
        for column in ("finished_at", "started_at", "id")
        if column in available
    ]
    if latest_columns and order_columns:
        projection = ", ".join(
            _quote_identifier(column) for column in latest_columns
        )
        ordering = ", ".join(
            f"{_quote_identifier(column)} DESC" for column in order_columns
        )
        latest_sql = (
            f"SELECT {projection} FROM ("
            f"SELECT {projection}, ROW_NUMBER() OVER ("
            f"PARTITION BY {dataset_sql} ORDER BY {ordering}"
            ") AS snapshot_rank FROM ingestion_validation"
            ") WHERE snapshot_rank = 1 ORDER BY dataset"
        )
        for row in conn.execute(latest_sql):
            aggregates[row["dataset"]]["latest"] = {
                column: _stable_value(row[column]) for column in latest_columns
            }

    return [
        {
            "dataset": _stable_value(dataset),
            **aggregate,
        }
        for dataset, aggregate in sorted(
            aggregates.items(), key=lambda item: str(item[0])
        )
    ]


def _fact_table_state(
    conn: sqlite3.Connection,
    tables: set[str],
) -> list[dict[str, Any]]:
    """PIT fact-table counts for the no-watermark fallback path."""
    summaries: list[dict[str, Any]] = []
    for table in sorted(tables):
        if table.startswith("sqlite_") or table.startswith("ingestion_"):
            continue
        if "ingested_at" not in _table_columns(conn, table):
            continue
        quoted = _quote_identifier(table)
        row = conn.execute(
            f"SELECT COUNT(*) AS row_count, "
            f"MAX({_quote_identifier('ingested_at')}) AS max_ingested_at "
            f"FROM {quoted}"
        ).fetchone()
        summaries.append(
            {
                "table": table,
                "row_count": int(row["row_count"]),
                "max_ingested_at": _stable_value(row["max_ingested_at"]),
            }
        )
    return summaries


def _main_file_state(path: Path) -> dict[str, int]:
    stat = path.stat()
    return {"size": int(stat.st_size), "mtime_ns": int(stat.st_mtime_ns)}


def _canonical_digest(value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def begin_snapshot_sync(conn: sqlite3.Connection, *, started_at: str) -> str:
    """Invalidate research access and enter BUILDING before any write."""
    build_id = "build-" + uuid4().hex
    conn.execute(
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
    conn.commit()
    return build_id


def fail_snapshot_sync(conn: sqlite3.Connection, error: str) -> None:
    """Keep a partial local DB unavailable to paper research."""
    conn.execute(
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
    conn.commit()


def _latest_complete_run(
    conn: sqlite3.Connection, required: tuple[str, ...]
) -> tuple[int, dict[str, Any], list[dict[str, Any]]]:
    run = conn.execute(
        "SELECT id, status, detail FROM ingestion_run_log "
        "WHERE source='jquants' ORDER BY id DESC LIMIT 1"
    ).fetchone()
    if run is None:
        raise RuntimeError("no ingestion run is available for snapshot commit")
    status = str(run["status"] if isinstance(run, sqlite3.Row) else run[1])
    run_id = int(run["id"] if isinstance(run, sqlite3.Row) else run[0])
    detail_raw = run["detail"] if isinstance(run, sqlite3.Row) else run[2]
    try:
        detail = json.loads(detail_raw or "{}")
    except (TypeError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"ingestion run {run_id} has invalid detail JSON") from exc
    if not isinstance(detail, dict):
        raise RuntimeError(f"ingestion run {run_id} detail is not an object")
    if status != "pass":
        raise RuntimeError(
            f"latest ingestion run {run_id} is {status!r}, not a complete pass"
        )
    expected = len(required)
    if (
        int(detail.get("datasetCount", -1)) != expected
        or int(detail.get("passed", -1)) != expected
        or int(detail.get("failed", -1)) != 0
    ):
        raise RuntimeError(
            f"ingestion run {run_id} is not the complete {expected}-dataset run"
        )

    rows = conn.execute(
        "SELECT dataset, status, finished_at, rows_seen, rows_inserted, "
        "rows_revisions FROM ingestion_validation WHERE run_id = ? "
        "ORDER BY dataset, id",
        (run_id,),
    ).fetchall()
    latest: dict[str, dict[str, Any]] = {}
    for row in rows:
        item = dict(row) if isinstance(row, sqlite3.Row) else {
            "dataset": row[0], "status": row[1], "finished_at": row[2],
            "rows_seen": row[3], "rows_inserted": row[4],
            "rows_revisions": row[5],
        }
        latest[str(item["dataset"])] = item
    missing = sorted(set(required) - set(latest))
    failed = sorted(
        dataset for dataset in required
        if dataset in latest and latest[dataset].get("status") != "pass"
    )
    if missing or failed:
        raise RuntimeError(
            f"ingestion run {run_id} validation incomplete: "
            f"missing={missing}, failed={failed}"
        )
    return run_id, detail, [latest[dataset] for dataset in required]


def commit_snapshot_manifest(
    conn: sqlite3.Connection,
    *,
    required_datasets: Iterable[str],
) -> str:
    """Legacy in-place manifest for compatibility fixtures (not production READY)."""
    required = tuple(sorted(set(str(item) for item in required_datasets)))
    if not required:
        raise ValueError("required_datasets must not be empty")
    conn.execute(
        "UPDATE local_snapshot_policy SET publication_state='SYNCED' "
        "WHERE singleton=1"
    )
    conn.execute(
        "UPDATE local_snapshot_policy SET publication_state='VALIDATING' "
        "WHERE singleton=1"
    )
    conn.commit()
    run_id, detail, validations = _latest_complete_run(conn, required)

    placeholders = ",".join("?" for _ in required)
    rows = conn.execute(
        "SELECT dataset, last_event_date, last_ingested_at "
        "FROM ingestion_watermarks "
        f"WHERE dataset IN ({placeholders}) ORDER BY dataset",
        required,
    ).fetchall()
    watermarks = [dict(row) for row in rows]
    present = {str(row["dataset"]) for row in watermarks}
    missing = sorted(set(required) - present)
    if missing:
        raise RuntimeError(f"required dataset watermarks missing: {missing}")
    change = conn.execute(
        "SELECT last_applied_change_seq FROM sync_change_state "
        "WHERE feed = 'jquants_records'"
    ).fetchone()
    change_seq = int(change[0]) if change is not None else 0
    committed_at = datetime.now(timezone.utc).isoformat()
    manifest = {
        "format": LOCAL_SNAPSHOT_MANIFEST_FORMAT,
        "committed_at": committed_at,
        "source_run": {
            "id": run_id,
            "started_at": detail.get("startedAt"),
            "finished_at": detail.get("finishedAt"),
        },
        "required_datasets": list(required),
        "change_seq": change_seq,
        "dataset_watermarks": watermarks,
        "validations": validations,
    }
    snapshot_id = _canonical_digest(manifest)
    manifest_json = json.dumps(
        manifest, ensure_ascii=True, sort_keys=True, separators=(",", ":"),
        allow_nan=False,
    )
    try:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            """
            INSERT OR IGNORE INTO local_snapshot_manifests
                (snapshot_id, format, committed_at, source_run_id, change_seq,
                 manifest_json)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                snapshot_id, LOCAL_SNAPSHOT_MANIFEST_FORMAT, committed_at,
                run_id, change_seq, manifest_json,
            ),
        )
        conn.execute(
            "UPDATE local_snapshot_policy SET snapshot_ready = 1, "
            "last_error = NULL, publication_state='READY', "
            "active_snapshot_id=? WHERE singleton = 1",
            (snapshot_id,),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return snapshot_id


def _research_manifest_id(manifest: dict[str, Any]) -> str:
    identity = dict(manifest)
    identity.pop("snapshot_id", None)
    identity.pop("artifact", None)
    identity.pop("committed_at", None)
    identity.pop("manifest_digest", None)
    return _canonical_digest(identity)


def _research_manifest_digest(manifest: dict[str, Any]) -> str:
    document = dict(manifest)
    document.pop("manifest_digest", None)
    return _canonical_digest(document)


def _artifact_stem(snapshot_id: str) -> str:
    if not _SNAPSHOT_ID_RE.fullmatch(snapshot_id):
        raise ValueError(f"invalid snapshot_id: {snapshot_id!r}")
    return snapshot_id.replace(":", "_", 1)


def _watermarks_for(
    conn: sqlite3.Connection,
    required: tuple[str, ...],
    coverage_rows: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    placeholders = ",".join("?" for _ in required)
    rows = conn.execute(
        "SELECT dataset, last_event_date, last_ingested_at "
        "FROM ingestion_watermarks "
        f"WHERE dataset IN ({placeholders}) ORDER BY dataset",
        required,
    ).fetchall()
    watermarks = [dict(row) for row in rows]
    present = {str(row["dataset"]) for row in watermarks}
    coverage = {
        str(row["dataset"]): row for row in (coverage_rows or [])
    }
    # JSDA has no D1 watermark; COMPLETE Coverage V2 observed_end is the bound.
    for dataset in sorted(set(required) - present):
        row = coverage.get(dataset)
        if (
            row is not None
            and row.get("status") == "COMPLETE"
            and row.get("observed_end")
            and row.get("evaluated_at")
        ):
            watermarks.append({
                "dataset": dataset,
                "last_event_date": row["observed_end"],
                "last_ingested_at": row["evaluated_at"],
                "derived_from": "coverage_v2_receipts",
            })
            present.add(dataset)
    watermarks.sort(key=lambda row: str(row["dataset"]))
    missing = sorted(set(required) - present)
    if missing:
        raise SnapshotRejected(f"required dataset watermarks missing: {missing}")
    return watermarks


def publish_ready_snapshot(
    staging_db: str | Path,
    snapshot_dir: str | Path,
    *,
    required_datasets: Iterable[str],
) -> ReadySnapshot:
    """Gate a staging DB and atomically publish a read-only READY copy."""
    staging_path = Path(staging_db).resolve()
    if not staging_path.is_file():
        raise FileNotFoundError(f"staging database does not exist: {staging_path}")
    required = tuple(sorted(set(str(item) for item in required_datasets)))
    if not required:
        raise ValueError("required_datasets must not be empty")
    policies = {policy.dataset_id: policy for policy in all_coverage_contracts()}
    governed = {
        dataset_id for dataset_id, policy in policies.items()
        if policy.governance_tier == "governed"
    }
    required_set = set(required)
    if not governed <= required_set or not required_set <= set(policies):
        raise SnapshotRejected(
            "READY publication must cover every governed dataset and only "
            "contracted datasets: "
            f"missing={sorted(governed - required_set)}, "
            f"unknown={sorted(required_set - set(policies))}"
        )
    destination = Path(snapshot_dir).resolve()
    destination.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(str(staging_path))
    conn.row_factory = sqlite3.Row
    build_id = "build-" + uuid4().hex
    created_at = datetime.now(timezone.utc).isoformat()
    contract = f"jquants-premium-core/v{DATASET_CONTRACT_VERSION}"
    coverage_policy_version = COVERAGE_POLICY_VERSION
    quality_policy_version = QUALITY_POLICY_VERSION
    published_ready: ReadySnapshot | None = None
    try:
        conn.execute(
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
        conn.execute(
            """
            INSERT INTO snapshot_publications
                (build_id, state, staging_path, contract_version,
                 coverage_policy_version, quality_policy_version, created_at)
            VALUES (?, 'BUILDING', ?, ?, ?, ?, ?)
            """,
            (
                build_id, str(staging_path), contract,
                coverage_policy_version, quality_policy_version, created_at,
            ),
        )
        conn.commit()
        _transition_policy(conn, "SYNCED")
        conn.execute(
            "UPDATE snapshot_publications SET state='SYNCED' WHERE build_id=?",
            (build_id,),
        )
        conn.commit()
        _transition_policy(conn, "VALIDATING")
        conn.execute(
            "UPDATE snapshot_publications SET state='VALIDATING' WHERE build_id=?",
            (build_id,),
        )
        conn.commit()

        try:
            (
                run_id, run_detail, validations, coverage_rows,
                quality_summary, quality_failures, raw_manifests,
                coverage_proof,
            ) = _evaluate_publication_gate(
                conn, staging_path, build_id=build_id, required=required
            )
            watermarks = _watermarks_for(conn, required, coverage_rows)
            from paper_runtime.ready_policy import ReadyPublicationPolicy

            # raw_manifests already validated; None avoids a second shape fail.
            policy = ReadyPublicationPolicy()
            bundle = policy.evaluate(
                conn,
                staging_path,
                required,
                run_id=run_id,
                coverage_proof=coverage_proof if isinstance(coverage_proof, dict) else None,
                quality_status="PASS",
                raw_manifest_ok=None,
            )
            if not bundle.passed:
                detail = "; ".join(
                    f"{i.name}: {i.reason}" for i in bundle.failures()
                )
                raise SnapshotRejected(
                    f"READY publication policy failed: {detail}"
                )
        except Exception as exc:
            reason = str(exc)[:4000]
            conn.execute(
                "UPDATE snapshot_publications SET state='REJECTED', "
                "rejection_reason=? WHERE build_id=?",
                (reason, build_id),
            )
            conn.commit()
            _transition_policy(conn, "REJECTED", error=reason)
            if isinstance(exc, SnapshotRejected):
                raise
            raise SnapshotRejected(reason) from exc

        change = conn.execute(
            "SELECT last_applied_change_seq FROM sync_change_state "
            "WHERE feed='jquants_records'"
        ).fetchone()
        change_seq = int(change[0]) if change is not None else 0
        committed_at = datetime.now(timezone.utc).isoformat()
        manifest: dict[str, Any] = {
            "format": RESEARCH_SNAPSHOT_MANIFEST_FORMAT,
            "state": "READY",
            "contract_version": contract,
            "source_contract_versions": {
                "jquants": contract,
                "jsda": JSDA_CONTRACT_VERSION,
            },
            "source_run": {
                "id": run_id,
                "started_at": run_detail.get("startedAt"),
                "finished_at": run_detail.get("finishedAt"),
            },
            "change_seq": change_seq,
            "coverage_policy_version": coverage_policy_version,
            "quality_policy_version": quality_policy_version,
            "required_datasets": list(required),
            "dataset_watermarks": watermarks,
            "coverage": [
                {
                    key: row[key]
                    for key in (
                        "dataset", "status", "history_target_start",
                        "history_target_end_rule", "coverage_mode",
                        "expected_frequency", "universe_rule",
                        "governance_tier", "observed_start", "observed_end",
                        "row_count",
                    )
                }
                for row in coverage_rows
            ],
            "coverage_v2_proof": coverage_proof,
            "quality": {
                "status": "PASS",
                "summary": quality_summary,
                "failures": quality_failures,
            },
            "raw_manifests": raw_manifests,
            "validations": validations,
            "committed_at": committed_at,
        }
        snapshot_id = _research_manifest_id(manifest)
        manifest["snapshot_id"] = snapshot_id
        stem = _artifact_stem(snapshot_id)
        artifact_path = destination / f"{stem}.sqlite"
        manifest_path = destination / f"{stem}.manifest.json"
        manifest["artifact"] = artifact_path.name
        manifest["manifest_digest"] = _research_manifest_digest(manifest)

        fd, raw_temp = tempfile.mkstemp(
            prefix=f".{stem}.", suffix=".sqlite.tmp", dir=destination
        )
        os.close(fd)
        temp_db = Path(raw_temp)
        try:
            _copy_sqlite(conn, temp_db)
            embedded = sqlite3.connect(str(temp_db))
            embedded.row_factory = sqlite3.Row
            try:
                manifest_json = json.dumps(
                    manifest, ensure_ascii=True, sort_keys=True,
                    separators=(",", ":"), allow_nan=False,
                )
                embedded.execute(
                    """
                    INSERT OR REPLACE INTO local_snapshot_manifests
                        (snapshot_id, format, committed_at, source_run_id,
                         change_seq, manifest_json)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        snapshot_id, RESEARCH_SNAPSHOT_MANIFEST_FORMAT,
                        committed_at, run_id, change_seq, manifest_json,
                    ),
                )
                embedded.execute(
                    "UPDATE local_snapshot_policy SET snapshot_ready=1, "
                    "publication_state='READY', active_snapshot_id=?, "
                    "last_error=NULL WHERE singleton=1",
                    (snapshot_id,),
                )
                embedded.execute(
                    "UPDATE snapshot_publications SET snapshot_id=?, state='READY', "
                    "artifact_path=?, manifest_path=?, source_run_id=?, change_seq=?, "
                    "committed_at=?, rejection_reason=NULL, manifest_json=? "
                    "WHERE build_id=?",
                    (
                        snapshot_id, str(artifact_path), str(manifest_path),
                        run_id, change_seq, committed_at, manifest_json, build_id,
                    ),
                )
                embedded.commit()
                integrity = embedded.execute("PRAGMA integrity_check").fetchone()[0]
                if integrity != "ok":
                    raise RuntimeError(f"snapshot integrity check failed: {integrity}")
                embedded.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            finally:
                embedded.close()
            os.chmod(temp_db, 0o444)
            if artifact_path.exists():
                existing = describe_snapshot(destination, snapshot_id)
                temp_db.unlink(missing_ok=True)
                ready = existing
                manifest = existing.manifest
                manifest_path = existing.manifest_path
                artifact_path = existing.db_path
                committed_at = existing.committed_at
            else:
                os.replace(temp_db, artifact_path)
                _atomic_json(manifest_path, manifest, mode=0o444)
                ready = ReadySnapshot(
                    snapshot_id, artifact_path, manifest_path, manifest
                )
            published_ready = ready
            try:
                _atomic_json(
                    destination / "latest-ready.json",
                    {
                        "format": "research-snapshot-pointer/v1",
                        "snapshot_id": snapshot_id,
                        "manifest": manifest_path.name,
                        "committed_at": committed_at,
                    },
                    mode=0o644,
                )
            except OSError:
                pass
        except Exception:
            temp_db.unlink(missing_ok=True)
            raise

        conn.execute(
            "UPDATE snapshot_publications SET snapshot_id=?, state='READY', "
            "artifact_path=?, manifest_path=?, source_run_id=?, change_seq=?, "
            "committed_at=?, rejection_reason=NULL, manifest_json=? "
            "WHERE build_id=?",
            (
                snapshot_id, str(artifact_path), str(manifest_path), run_id,
                change_seq, committed_at,
                json.dumps(manifest, sort_keys=True, separators=(",", ":")),
                build_id,
            ),
        )
        conn.execute(
            "UPDATE local_snapshot_policy SET snapshot_ready=0, "
            "publication_state='READY', active_snapshot_id=?, last_error=NULL "
            "WHERE singleton=1",
            (snapshot_id,),
        )
        conn.commit()
        return ready
    except Exception as exc:
        if published_ready is not None:
            return published_ready
        try:
            conn.rollback()
            conn.execute(
                "UPDATE snapshot_publications SET state='REJECTED', "
                "rejection_reason=? WHERE build_id=? AND state!='READY'",
                (str(exc)[:4000], build_id),
            )
            conn.execute(
                "UPDATE local_snapshot_policy SET snapshot_ready=0, "
                "publication_state='REJECTED', active_snapshot_id=NULL, "
                "last_error=? WHERE singleton=1",
                (str(exc)[:4000],),
            )
            conn.commit()
        except sqlite3.Error:
            conn.rollback()
        raise
    finally:
        conn.close()


def describe_snapshot(
    snapshot_dir: str | Path, snapshot_id: str
) -> ReadySnapshot:
    """Verify sidecar, immutable artifact, and embedded manifest."""
    directory = Path(snapshot_dir).resolve()
    stem = _artifact_stem(snapshot_id)
    manifest_path = directory / f"{stem}.manifest.json"
    if not manifest_path.is_file():
        raise FileNotFoundError(f"snapshot manifest does not exist: {manifest_path}")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"invalid snapshot manifest: {manifest_path}") from exc
    if manifest.get("format") != RESEARCH_SNAPSHOT_MANIFEST_FORMAT:
        raise RuntimeError("unsupported research snapshot manifest format")
    if manifest.get("state") != "READY" or manifest.get("snapshot_id") != snapshot_id:
        raise RuntimeError("snapshot manifest is not the requested READY snapshot")
    if _research_manifest_id(manifest) != snapshot_id:
        raise RuntimeError("research snapshot manifest checksum mismatch")
    if manifest.get("manifest_digest") != _research_manifest_digest(manifest):
        raise RuntimeError("research snapshot full-manifest checksum mismatch")
    artifact_name = manifest.get("artifact")
    if artifact_name != f"{stem}.sqlite":
        raise RuntimeError("research snapshot artifact name mismatch")
    artifact_path = directory / artifact_name
    if not artifact_path.is_file():
        raise FileNotFoundError(f"snapshot artifact does not exist: {artifact_path}")
    mode = artifact_path.stat().st_mode
    if mode & (stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH):
        raise RuntimeError("READY snapshot artifact is writable")
    if manifest_path.stat().st_mode & (stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH):
        raise RuntimeError("READY snapshot manifest is writable")
    if data_snapshot_id(artifact_path) != snapshot_id:
        raise RuntimeError("embedded snapshot manifest does not match sidecar")
    return ReadySnapshot(snapshot_id, artifact_path, manifest_path, manifest)


def list_ready_snapshots(snapshot_dir: str | Path) -> list[ReadySnapshot]:
    directory = Path(snapshot_dir).resolve()
    if not directory.is_dir():
        return []
    snapshots: list[ReadySnapshot] = []
    for path in directory.glob("sha256_*.manifest.json"):
        token = path.name.removesuffix(".manifest.json").replace("_", ":", 1)
        try:
            snapshots.append(describe_snapshot(directory, token))
        except (FileNotFoundError, RuntimeError, ValueError):
            continue
    return sorted(
        snapshots, key=lambda item: (item.committed_at, item.snapshot_id),
        reverse=True,
    )


def latest_ready_snapshot(snapshot_dir: str | Path) -> ReadySnapshot:
    """Latest verified READY snapshot; never return a BUILDING artifact."""
    directory = Path(snapshot_dir).resolve()
    ready = list_ready_snapshots(directory)
    if not ready:
        raise FileNotFoundError(f"no READY research snapshot under {directory}")
    return ready[0]


def open_ready_snapshot(
    snapshot_dir: str | Path, snapshot_id: str | None = None
) -> sqlite3.Connection:
    """Open a verified READY artifact with immutable SQLite URI flags."""
    ready = (
        latest_ready_snapshot(snapshot_dir)
        if snapshot_id is None
        else describe_snapshot(snapshot_dir, snapshot_id)
    )
    uri = "file:" + quote(str(ready.db_path)) + "?mode=ro&immutable=1"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def _manifest_snapshot_state(
    conn: sqlite3.Connection, tables: set[str]
) -> dict[str, Any] | None:
    if not {"local_snapshot_policy", "local_snapshot_manifests"} <= tables:
        return None
    policy = conn.execute(
        "SELECT require_manifest, snapshot_ready, last_error "
        "FROM local_snapshot_policy WHERE singleton = 1"
    ).fetchone()
    if policy is None or not bool(policy["require_manifest"]):
        return None
    if not bool(policy["snapshot_ready"]):
        detail = str(policy["last_error"] or "sync is incomplete")
        raise RuntimeError(
            "local paper snapshot is not committed and validated: " + detail
        )
    row = conn.execute(
        "SELECT snapshot_id, format, manifest_json FROM local_snapshot_manifests "
        "ORDER BY committed_at DESC, rowid DESC LIMIT 1"
    ).fetchone()
    if row is None:
        raise RuntimeError("local paper snapshot policy requires a manifest")
    try:
        manifest = json.loads(row["manifest_json"])
    except json.JSONDecodeError as exc:
        raise RuntimeError("latest local snapshot manifest is invalid JSON") from exc
    if row["format"] == RESEARCH_SNAPSHOT_MANIFEST_FORMAT:
        expected_id = _research_manifest_id(manifest)
        if manifest.get("manifest_digest") != _research_manifest_digest(manifest):
            raise RuntimeError("latest local snapshot full-manifest checksum mismatch")
        _verify_coverage_v2_manifest(conn, manifest)
    else:
        expected_id = _canonical_digest(manifest)
    if expected_id != row["snapshot_id"]:
        raise RuntimeError("latest local snapshot manifest checksum mismatch")
    if manifest.get("state", "READY") != "READY":
        raise RuntimeError("latest local snapshot manifest is not READY")
    current_watermarks = _watermark_state(conn, tables)
    expected = manifest.get("dataset_watermarks")
    if current_watermarks != expected:
        raise RuntimeError(
            "local ingestion watermarks no longer match the committed snapshot"
        )
    return {
        "format": DATA_SNAPSHOT_FORMAT,
        "manifest_id": row["snapshot_id"],
        "manifest": manifest,
        "watermarks": current_watermarks,
    }


def data_snapshot_id(db_path: str | Path) -> str:
    """Logical snapshot id from watermarks/validation (not a byte hash)."""
    path = Path(db_path)
    if not path.is_file():
        raise FileNotFoundError(f"paper database does not exist: {path}")

    conn = _connect_readonly(path)
    try:
        conn.execute("BEGIN")
        tables = {
            str(row["name"])
            for row in conn.execute(
                "SELECT name FROM sqlite_schema WHERE type = 'table'"
            )
        }
        manifest_state = _manifest_snapshot_state(conn, tables)
        if manifest_state is not None:
            return str(manifest_state["manifest_id"])
        else:
            watermarks = _watermark_state(conn, tables)
            state = {
                "format": DATA_SNAPSHOT_FORMAT,
                "schema": _schema_state(conn),
                "watermarks": watermarks,
                "validation": _validation_state(conn, tables),
            }
            if not watermarks:
                state["fallback"] = {
                    "fact_tables": _fact_table_state(conn, tables),
                    "main_file": _main_file_state(path),
                }
    finally:
        conn.close()

    return _canonical_digest(state)


__all__ = [
    "DATA_SNAPSHOT_FORMAT",
    "LOCAL_SNAPSHOT_MANIFEST_FORMAT",
    "QUALITY_POLICY_VERSION",
    "RESEARCH_SNAPSHOT_MANIFEST_FORMAT",
    "SNAPSHOT_STATES",
    "ReadySnapshot",
    "SnapshotRejected",
    "begin_snapshot_sync",
    "commit_snapshot_manifest",
    "data_snapshot_id",
    "describe_snapshot",
    "fail_snapshot_sync",
    "latest_ready_snapshot",
    "list_ready_snapshots",
    "open_ready_snapshot",
    "publish_ready_snapshot",
]
