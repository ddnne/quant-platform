"""Cheap, control-plane-based identifiers for local SQLite data snapshots."""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import sqlite3
import tempfile
from datetime import datetime, timezone
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping
from urllib.parse import quote
from uuid import uuid4

from data_contracts.coverage import (
    all_coverage_contracts,
    coverage_policy_set_binding,
)
from data_contracts.jsda import JSDA_CONTRACT_VERSION
from data_contracts.loader import SCHEMA_VERSION as DATASET_CONTRACT_VERSION
from paper_runtime.snapshot_coverage_proof import (
    _coverage_proof,
    _verify_coverage_manifest,
)
from paper_runtime.snapshot_persist import (
    _atomic_json,
    _copy_sqlite,
    _persist_building_publication,
    _persist_synced_policy,
    _persist_synced_publication,
    begin_snapshot_sync,
)
from paper_runtime.snapshot_publish_policy import (
    READY_MANIFEST_SCHEMA,
    evaluate_ready_publication,
    _transition_policy,
)
from paper_runtime.snapshot_read import (
    _describe_fixture_snapshot,
    describe_snapshot,
    latest_ready_snapshot,
    list_ready_snapshots,
    open_ready_snapshot,
)


DATA_SNAPSHOT_FORMAT = "paper-data-snapshot/v1"
LOCAL_SNAPSHOT_MANIFEST_FORMAT = "local-snapshot-manifest/v1"
RESEARCH_SNAPSHOT_MANIFEST_FORMAT = "research-snapshot-manifest/v2"
RESEARCH_SNAPSHOT_PUBLICATION_FORMAT = "research-snapshot-publication/v1"
QUALITY_POLICY_VERSION = "b0+phase35-daily+coverage-set/v1"
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


def _connect_readonly(
    path: Path, *, immutable: bool = False
) -> sqlite3.Connection:
    # Published snapshots are content-addressed immutable artifacts, where
    # SQLite must not create ``-wal``/``-shm`` sidecars.  Mutable current DBs,
    # however, may have committed data only in an uncheckpointed WAL; treating
    # those as immutable would silently read stale state.
    query = "?mode=ro&immutable=1" if immutable else "?mode=ro"
    uri = "file:" + quote(str(path.resolve())) + query
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


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


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
    _persist_synced_policy(conn)
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
    identity.pop("created_at", None)
    identity.pop("committed_at", None)
    identity.pop("manifest_digest", None)
    # ReadyManifest binds to snapshot_id and is therefore appended after the
    # non-circular research snapshot identity has been calculated.
    identity.pop("ready_manifest", None)
    # A repeated validation of the same immutable source state must resolve to
    # the same content address. Keep the retained observation time in the full
    # manifest, but exclude that volatile clock reading from snapshot identity.
    ready_evidence = identity.get("ready_evidence")
    if isinstance(ready_evidence, Mapping):
        stable_evidence = dict(ready_evidence)
        stable_items: list[Any] = []
        for raw_item in ready_evidence.get("items", []):
            if not isinstance(raw_item, Mapping):
                stable_items.append(raw_item)
                continue
            item = dict(raw_item)
            detail = item.get("detail")
            if isinstance(detail, Mapping):
                stable_detail = dict(detail)
                stable_detail.pop("evaluated_at", None)
                item["detail"] = stable_detail
            stable_items.append(item)
        stable_evidence["items"] = stable_items
        identity["ready_evidence"] = stable_evidence
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
    # JSDA has no D1 watermark; current governed Coverage observed_end is the bound.
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
                "derived_from": "governed_coverage_receipts",
            })
            present.add(dataset)
    watermarks.sort(key=lambda row: str(row["dataset"]))
    missing = sorted(set(required) - present)
    if missing:
        raise SnapshotRejected(f"required dataset watermarks missing: {missing}")
    return watermarks


def _publish_ready_snapshot(
    staging_db: str | Path,
    snapshot_dir: str | Path,
    *,
    required_datasets: Iterable[str],
    _profile_coverage_evidence: Mapping[str, Any] | None = None,
    _dependency_scope_evidence: Mapping[str, Any] | None = None,
    _ready_manifest_builder: (
        Callable[[Mapping[str, Any]], Mapping[str, Any]] | None
    ) = None,
    _ready_attestation_builder: Callable[[ReadySnapshot], Path | None] | None = None,
) -> ReadySnapshot:
    """Production-only profile/plan-bound snapshot publication boundary."""
    return _publish_ready_snapshot_impl(
        staging_db,
        snapshot_dir,
        required_datasets=required_datasets,
        _profile_coverage_evidence=_profile_coverage_evidence,
        _dependency_scope_evidence=_dependency_scope_evidence,
        _ready_manifest_builder=_ready_manifest_builder,
        _ready_attestation_builder=_ready_attestation_builder,
        publication_gate=evaluate_ready_publication,
        fixture_compatibility=False,
    )


def _publish_ready_snapshot_impl(
    staging_db: str | Path,
    snapshot_dir: str | Path,
    *,
    required_datasets: Iterable[str],
    _profile_coverage_evidence: Mapping[str, Any] | None = None,
    _dependency_scope_evidence: Mapping[str, Any] | None = None,
    _ready_manifest_builder: (
        Callable[[Mapping[str, Any]], Mapping[str, Any]] | None
    ) = None,
    _ready_attestation_builder: Callable[[ReadySnapshot], Path | None] | None = None,
    publication_gate: Callable[..., tuple[Any, ...]],
    fixture_compatibility: bool,
) -> ReadySnapshot:
    """Gate a staging DB and atomically publish a read-only snapshot.

    The product-owned READY(P) bridge may supply retained profile evidence and
    a closed ReadyManifest builder. Both must be present together.
    """
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
    profile_bound = _ready_manifest_builder is not None
    if profile_bound != (_profile_coverage_evidence is not None):
        raise SnapshotRejected(
            "profile coverage evidence and ReadyManifest builder must be supplied together"
        )
    if _ready_attestation_builder is not None and not profile_bound:
        raise SnapshotRejected(
            "READY attestation builder requires a profile-bound ReadyManifest"
        )
    if _dependency_scope_evidence is not None and not profile_bound:
        raise SnapshotRejected(
            "dependency scope evidence requires a profile-bound ReadyManifest"
        )
    if not profile_bound and not fixture_compatibility:
        raise SnapshotRejected(
            "production READY requires a profile/plan-bound ReadyManifest publisher"
        )
    if (
        profile_bound
        and not fixture_compatibility
        and _ready_attestation_builder is None
    ):
        raise SnapshotRejected(
            "production READY requires an atomic signed readiness attestation"
        )
    if (
        profile_bound
        and not fixture_compatibility
        and not isinstance(_dependency_scope_evidence, Mapping)
    ):
        raise SnapshotRejected(
            "production READY requires publisher-owned dependency scope evidence"
        )
    if not profile_bound and (
        not governed <= required_set or not required_set <= set(policies)
    ):
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
    governed_required = [
        dataset_id
        for dataset_id in required
        if policies[dataset_id].governance_tier == "governed"
    ]
    coverage_policy = coverage_policy_set_binding(governed_required)
    coverage_policy_version = str(coverage_policy["policy_version"])
    coverage_policy_digest = str(coverage_policy["policy_digest"])
    quality_policy_version = QUALITY_POLICY_VERSION
    readiness_sidecar_path: Path | None = None
    artifact_path: Path | None = None
    manifest_path: Path | None = None
    publication_marker_path: Path | None = None
    artifact_created = False
    manifest_attempted = False
    pointer_attempted = False
    publication_marker_attempted = False
    try:
        _persist_building_publication(
            conn,
            build_id=build_id,
            created_at=created_at,
            staging_path=str(staging_path),
            contract_version=contract,
            coverage_policy_version=coverage_policy_version,
            quality_policy_version=quality_policy_version,
        )
        _transition_policy(conn, "SYNCED")
        _persist_synced_publication(conn, build_id)
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
                coverage_proof, coverage_proof_id, ready_evidence,
            ) = publication_gate(
                conn,
                staging_path,
                build_id=build_id,
                required=required,
            )
            watermarks = _watermarks_for(conn, required, coverage_rows)
            if READY_MANIFEST_SCHEMA.get("$id") != "ready-manifest/v1":
                raise SnapshotRejected("ReadyManifest schema is not the publish gate")
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

        sync_items = [
            item
            for item in ready_evidence.get("items", [])
            if isinstance(item, Mapping)
            and item.get("name") == "SyncGenerationEvidence"
        ]
        if len(sync_items) != 1 or not isinstance(
            sync_items[0].get("detail"), Mapping
        ):
            raise SnapshotRejected("production READY sync evidence is missing")
        try:
            change_seq = int(
                sync_items[0]["detail"]["applied_sync_generation"]
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise SnapshotRejected(
                "production READY applied generation is malformed"
            ) from exc
        if change_seq <= 0:
            raise SnapshotRejected("production READY applied generation is null")
        quality_row = conn.execute(
            "SELECT results_json FROM snapshot_quality_results WHERE build_id=?",
            (build_id,),
        ).fetchone()
        if quality_row is None:
            raise SnapshotRejected("production READY quality result ledger is missing")
        try:
            quality_results = json.loads(str(quality_row[0]))
        except (TypeError, json.JSONDecodeError) as exc:
            raise SnapshotRejected(
                "production READY quality result ledger is malformed"
            ) from exc
        if not isinstance(quality_results, list) or not quality_results:
            raise SnapshotRejected("production READY quality results are empty")
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
            "coverage_policy_digest": coverage_policy_digest,
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
            "coverage_proof": coverage_proof,
            "coverage_proof_id": coverage_proof_id,
            "quality": {
                "status": "PASS",
                "summary": quality_summary,
                "failures": quality_failures,
                "results": quality_results,
            },
            "ready_evidence": ready_evidence,
            "raw_manifests": raw_manifests,
            "validations": validations,
            "created_at": created_at,
            "committed_at": committed_at,
        }
        if profile_bound:
            manifest["profile_coverage_evidence"] = {
                str(dataset_id): dict(row)
                for dataset_id, row in _profile_coverage_evidence.items()
            }
        if _dependency_scope_evidence is not None:
            manifest["dependency_scope_evidence"] = dict(
                _dependency_scope_evidence
            )
        snapshot_id = _research_manifest_id(manifest)
        manifest["snapshot_id"] = snapshot_id
        if profile_bound:
            nested = _ready_manifest_builder(manifest)
            if not isinstance(nested, Mapping):
                raise SnapshotRejected("ReadyManifest builder did not return an object")
            manifest["ready_manifest"] = dict(nested)
        stem = _artifact_stem(snapshot_id)
        artifact_path = destination / f"{stem}.sqlite"
        manifest_path = destination / f"{stem}.manifest.json"
        publication_marker_path = destination / f"{stem}.publication.json"
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
                existing = (
                    _describe_fixture_snapshot(destination, snapshot_id)
                    if fixture_compatibility
                    else describe_snapshot(destination, snapshot_id)
                )
                temp_db.unlink(missing_ok=True)
                ready = existing
                manifest = existing.manifest
                manifest_path = existing.manifest_path
                artifact_path = existing.db_path
                committed_at = existing.committed_at
            else:
                os.replace(temp_db, artifact_path)
                artifact_created = True
                manifest_attempted = True
                _atomic_json(manifest_path, manifest, mode=0o444)
                ready = ReadySnapshot(
                    snapshot_id, artifact_path, manifest_path, manifest
                )
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

        # Signing is deliberately after the authoritative source transaction:
        # a failed READY commit must never leave a usable signed capability.
        # If pointer finalization later fails, the returned sidecar path is
        # removed by the rejection handler below before control escapes.
        if _ready_attestation_builder is not None:
            readiness_sidecar_path = _ready_attestation_builder(ready)
            if (
                readiness_sidecar_path is None
                or not readiness_sidecar_path.is_file()
            ):
                raise SnapshotRejected(
                    "READY attestation builder did not publish an artifact"
                )
        artifact_digest = _file_sha256(artifact_path)
        publication_body: dict[str, Any] = {
            "format": RESEARCH_SNAPSHOT_PUBLICATION_FORMAT,
            "snapshot_id": snapshot_id,
            "manifest_digest": manifest["manifest_digest"],
            "committed_at": committed_at,
            "change_seq": change_seq,
            "artifact_digest": artifact_digest,
            "publication_scope": (
                "FIXTURE" if fixture_compatibility else "PRODUCTION"
            ),
            "readiness_attestation": (
                readiness_sidecar_path.name
                if readiness_sidecar_path is not None
                else None
            ),
            "readiness_attestation_digest": (
                _file_sha256(readiness_sidecar_path)
                if readiness_sidecar_path is not None
                else None
            ),
        }
        publication = {
            **publication_body,
            "publication_digest": _canonical_digest(publication_body),
        }
        # The mutable convenience pointer binds the complete marker and its
        # monotonic source generation.  The marker is written last, so a
        # pointer failure cannot leave a directly discoverable publication.
        pointer_attempted = True
        _atomic_json(
            destination / "latest-ready.json",
            {
                "format": "research-snapshot-pointer/v1",
                "snapshot_id": snapshot_id,
                "manifest": manifest_path.name,
                "committed_at": committed_at,
                "change_seq": change_seq,
                "publication_digest": publication["publication_digest"],
            },
            mode=0o444,
        )
        publication_marker_attempted = True
        _atomic_json(publication_marker_path, publication, mode=0o444)
        return ready
    except Exception as exc:
        original_exc = exc
        # A replace-last helper can be wrapped by a filesystem layer that
        # reports failure after the destination appeared.  Remove discovery
        # documents for every attempted finalization before cleaning signed
        # sidecars or quarantining immutable evidence.
        if publication_marker_attempted and publication_marker_path is not None:
            try:
                publication_marker_path.unlink(missing_ok=True)
            except OSError:
                pass
        if pointer_attempted:
            try:
                (destination / "latest-ready.json").unlink(missing_ok=True)
            except OSError:
                pass
        if readiness_sidecar_path is not None:
            try:
                readiness_sidecar_path.unlink(missing_ok=True)
            except OSError:
                # A retained signed capability would be unsafe even though the
                # source publication is rejected. Surface that cleanup failure
                # rather than reporting the original finalization error alone.
                exc = SnapshotRejected(
                    "READY publication rejected but readiness sidecar cleanup "
                    f"failed: {readiness_sidecar_path}"
                )
        created_paths = [
            path
            for path, created in (
                (artifact_path, artifact_created),
                (manifest_path, manifest_attempted),
            )
            if created and path is not None and path.exists()
        ]
        if created_paths:
            quarantine_path = destination / "rejected" / build_id
            try:
                quarantine_path.mkdir(parents=True, exist_ok=False)
                for path in created_paths:
                    os.replace(path, quarantine_path / path.name)
                exc = SnapshotRejected(
                    "READY publication finalization failed; rejected immutable "
                    f"evidence quarantined at {quarantine_path}: {exc}"
                )
            except OSError as cleanup_exc:
                # No publication marker exists, so even a failed quarantine is
                # outside every public READY read path. Surface the cleanup
                # problem for an operator rather than treating it as success.
                exc = SnapshotRejected(
                    "READY publication failed and rejected evidence quarantine "
                    f"failed: {cleanup_exc}; original error: {exc}"
                )
        try:
            conn.rollback()
            conn.execute(
                "UPDATE snapshot_publications SET state='REJECTED', "
                "rejection_reason=? WHERE build_id=?",
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
        if exc is not original_exc:
            raise exc from original_exc
        raise
    finally:
        conn.close()


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
        _verify_coverage_manifest(conn, manifest)
    else:
        expected_id = _canonical_digest(manifest)
    if expected_id != row["snapshot_id"]:
        raise RuntimeError("latest local snapshot manifest checksum mismatch")
    if manifest.get("state", "READY") != "READY":
        raise RuntimeError("latest local snapshot manifest is not READY")
    current_watermarks = _watermark_state(conn, tables)
    expected = manifest.get("dataset_watermarks")
    if isinstance(manifest.get("ready_manifest"), Mapping):
        required = manifest.get("required_datasets")
        if not isinstance(required, list):
            raise RuntimeError("profile-bound snapshot datasets are malformed")
        required_set = set(required)
        current_watermarks = [
            row for row in current_watermarks if row.get("dataset") in required_set
        ]
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


def _data_snapshot_id(db_path: str | Path, *, immutable: bool) -> str:
    """Logical snapshot id with an explicit mutable/immutable read contract."""
    path = Path(db_path)
    if not path.is_file():
        raise FileNotFoundError(f"paper database does not exist: {path}")

    conn = _connect_readonly(path, immutable=immutable)
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


def data_snapshot_id(db_path: str | Path) -> str:
    """Logical id for a current DB, including committed WAL state."""
    return _data_snapshot_id(db_path, immutable=False)


def _immutable_data_snapshot_id(db_path: str | Path) -> str:
    """Logical id for a checkpointed content-addressed snapshot artifact."""
    return _data_snapshot_id(db_path, immutable=True)


__all__ = [
    "DATA_SNAPSHOT_FORMAT",
    "LOCAL_SNAPSHOT_MANIFEST_FORMAT",
    "QUALITY_POLICY_VERSION",
    "READY_MANIFEST_SCHEMA",
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
]
