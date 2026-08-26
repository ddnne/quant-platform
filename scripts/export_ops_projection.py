#!/usr/bin/env python3
"""Build one immutable, generation-scoped Ops Projection D1 import.

The source database is an ingestion/local-sync control database.  The target is
the dedicated ``quant-ops-projection`` database; it is never the ingestion D1.
Every projected row is tagged with a new generation. Existing generations are
left untouched. A generation is created OPEN, populated, content-addressed,
sealed only after all expected row counts are present, and exposed by the
singleton active pointer as the final SQL statement.
"""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
from datetime import date, datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import stat
import subprocess
import sys
from types import MappingProxyType
from typing import Any, Iterable, Mapping, Sequence
from urllib.parse import quote
from uuid import uuid4

_HERE = Path(__file__).resolve().parent
for _directory in (_HERE, _HERE.parent):
    if (_directory / "_bootstrap.py").is_file():
        if str(_directory) not in sys.path:
            sys.path.insert(0, str(_directory))
        break
else:  # pragma: no cover - repository layout invariant
    raise RuntimeError("scripts/_bootstrap.py not found")

from _bootstrap import ensure_repo_root  # noqa: E402

ROOT = ensure_repo_root()

from ops.projection_content import build_projection_content_manifest  # noqa: E402
from ops.d1_sync_signing import d1_sync_digest  # noqa: E402
from ops.projection_candidate import (  # noqa: E402
    UNSIGNED_CANDIDATE_SCHEMA,
    UnsignedOpsProjectionCandidate,
    _freeze_unsigned_projection_candidate,
)

PROJECTION_VERSION = "ops_projection/v4"
DEFAULT_MAX_AGE_SECONDS = 86_400
CANONICAL_APPLY_FEED = "jquants_records"

DATASET_COVERAGE_COLUMNS = (
    "dataset", "status", "policy_version", "collection_scope",
    "history_target_start", "history_target_end_rule", "coverage_mode",
    "expected_frequency", "universe_rule", "raw_retention_required",
    "structured_reconciliation_required", "governance_tier",
    "observed_start", "observed_end", "row_count", "source_run_id",
    "evaluated_at", "detail_json",
)
COVERAGE_SEGMENT_COLUMNS = (
    "source", "dataset", "segment_id", "policy_version", "segment_start",
    "segment_end", "expected_scope", "expected_items", "status",
    "receipt_run_id", "evaluated_at", "detail_json",
)


@dataclass(frozen=True)
class ProjectionBundle:
    sql: str
    generation_id: str
    source_db_digest: str
    content_digest: str
    row_counts: Mapping[str, int]
    complete_coverage_segments: int | None
    metadata: Mapping[str, Any]
    envelope: Mapping[str, Any]
    signed_envelope: Mapping[str, Any] | None
    activation_included: bool


@dataclass(frozen=True, slots=True)
class _ConnectionSnapshotDescriptor:
    descriptor_path: str
    device: int
    inode: int
    size: int
    mtime_ns: int
    schema_version: int
    data_version: int
    total_changes: int


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sql_literal(value: Any) -> str:
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, (int, float)):
        return str(value)
    return "'" + str(value).replace("'", "''") + "'"


def _insert_sql(
    table: str,
    columns: Sequence[str],
    rows: Iterable[Mapping[str, Any]],
) -> list[str]:
    names = ",".join(columns)
    return [
        f"INSERT INTO {table} ({names}) VALUES ("
        + ",".join(_sql_literal(row.get(column)) for column in columns)
        + ");"
        for row in rows
    ]


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone() is not None


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    if not _table_exists(conn, table):
        return set()
    return {str(row[1]) for row in conn.execute(f"PRAGMA table_info({table})")}


def _rows(
    conn: sqlite3.Connection,
    table: str,
    columns: Sequence[str],
    *,
    order_by: str,
    required: bool = False,
) -> list[dict[str, Any]]:
    available = _columns(conn, table)
    missing = set(columns) - available
    if not available:
        if required:
            raise RuntimeError(f"required source table is missing: {table}")
        return []
    if missing:
        raise RuntimeError(f"{table} is missing projection columns: {sorted(missing)}")
    conn.row_factory = sqlite3.Row
    return [
        dict(row)
        for row in conn.execute(
            f"SELECT {','.join(columns)} FROM {table} ORDER BY {order_by}"
        ).fetchall()
    ]


def _safe_count(
    conn: sqlite3.Connection, table: str, where: str = "", binds: Sequence[Any] = ()
) -> int | None:
    if not _table_exists(conn, table):
        return None
    row = conn.execute(f"SELECT COUNT(*) FROM {table}{where}", tuple(binds)).fetchone()
    return int(row[0]) if row is not None else 0


def _safe_scalar(
    conn: sqlite3.Connection, table: str, sql: str, binds: Sequence[Any] = ()
) -> Any:
    if not _table_exists(conn, table):
        return None
    row = conn.execute(sql, tuple(binds)).fetchone()
    return row[0] if row is not None else None


def coerce_applied_seq(value: Any) -> int | None:
    """Missing remains missing; zero is a genuine cursor."""
    if value is None or value == "":
        return None
    return int(value)


def sync_dataset_state(
    *,
    exported: int | None,
    applied: int | None,
    lag: int | None,
    change_log_rows: int = 0,
) -> str:
    if exported is None:
        return "CHANGE_LOG_EMPTY" if change_log_rows == 0 else "EXPORT_CURSOR_NULL"
    if applied is None:
        if lag == 0:
            return "EXPORT_CURRENT_APPLY_UNPINNED"
        if lag is not None and lag > 0:
            return "LAGGING_APPLY_UNPINNED"
        return "APPLY_UNPINNED"
    if lag == 0 and applied == exported:
        return "CURRENT"
    if lag is not None and lag > 0:
        return "LAGGING"
    return "UNKNOWN"


def _git_sha(explicit: str | None) -> str:
    if explicit:
        return explicit
    try:
        value = subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=ROOT,
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except (OSError, subprocess.SubprocessError) as exc:
        raise RuntimeError("producer_commit_sha is required") from exc
    if not value:
        raise RuntimeError("producer_commit_sha is required")
    return value


def _digest_files(paths: Iterable[Path]) -> str:
    digest = hashlib.sha256()
    found = False
    for path in sorted({p.resolve() for p in paths}, key=str):
        if not path.is_file():
            continue
        found = True
        digest.update(str(path.relative_to(ROOT)).encode())
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    if not found:
        raise RuntimeError("projection contract digest has no source files")
    return "sha256:" + digest.hexdigest()


def _contract_digests() -> tuple[str, str]:
    package = ROOT / "packages" / "data_plane" / "data_contracts"
    registry = _digest_files((package / "canonical_datasets.json",))
    contract = _digest_files(
        (
            package / "collection_coverage.json",
            *sorted((package / "source_capability_contracts").glob("*.json")),
            ROOT / "specs" / "receipts" / "signed_receipt_claims.schema.json",
            ROOT / "specs" / "ops_projection" / "signed_envelope.schema.json",
        )
    )
    return contract, registry


def _source_inventory() -> list[dict[str, Any]]:
    from data_contracts.canonical import CANONICAL_REGISTRY_PATH, all_canonical_datasets
    from data_contracts.source_capability import source_capability_contract_or_none

    document = json.loads(CANONICAL_REGISTRY_PATH.read_text(encoding="utf-8"))
    raw_by_id = {row["dataset_id"]: row for row in document.get("datasets", [])}
    inventory: list[dict[str, Any]] = []
    for contract in all_canonical_datasets():
        raw = raw_by_id.get(contract.dataset_id, {})
        capability = source_capability_contract_or_none(contract.dataset_id)
        sla = dict(raw.get("sla") or {})
        upstream = None
        collection_window = None
        available_at_json = None
        historical_start = raw.get("historical_start")
        expected_frequency = raw.get("expected_frequency") or "unknown"
        coverage_granularity = raw.get("coverage_segment_granularity") or "none"
        research_eligible = False
        has_coverage_contract = True
        try:
            historical_start = contract.historical_start
            expected_frequency = contract.expected_frequency
            coverage_granularity = contract.coverage_segment_granularity
            research_eligible = bool(contract.research_eligible)
        except ValueError:
            # Experimental/unverified inventory members intentionally have no
            # governed Coverage contract.  Keep them visible but ineligible.
            has_coverage_contract = False
        inventory_status = raw.get(
            "inventory_status",
            "GOVERNED"
            if contract.governance_tier == "governed"
            else "EXPERIMENTAL",
        )
        if capability is None or not has_coverage_contract:
            # Absence is a capability fact, not a reason to copy a legacy date
            # or eligibility flag from the meta-index.
            inventory_status = "UNVERIFIED_ENDPOINT"
        if capability is not None:
            upstream = capability.upstream_locator
            collection_window = capability.collection_window.grain
            historical_start = capability.earliest_official_availability
            sla.update(
                {
                    "expected_after": capability.freshness_sla.expected_after,
                    "usable_by": capability.freshness_sla.usable_by,
                    "timezone": capability.freshness_sla.timezone,
                    "freshness_policy": capability.freshness_sla.rule,
                    "official_evidence_url": capability.official_evidence_url,
                }
            )
            available_at_json = json.dumps(
                asdict(capability.available_at),
                sort_keys=True,
                separators=(",", ":"),
            )
        inventory.append(
            {
                "dataset_id": contract.dataset_id,
                "display_name": contract.display_name,
                "source": contract.source,
                "governance_tier": contract.governance_tier,
                "inventory_status": inventory_status,
                "upstream_locator": upstream,
                "collection_window": collection_window,
                "expected_frequency": expected_frequency,
                "coverage_segment_granularity": coverage_granularity,
                "research_eligible": research_eligible,
                "enabled": bool(raw.get("enabled", True)),
                "sla": json.dumps(sla, sort_keys=True, separators=(",", ":")),
                "historical_start": historical_start,
                "available_at_json": available_at_json,
            }
        )
    return inventory


def _read_b0(conn: sqlite3.Connection, generation_id: str, now: str) -> dict[str, Any]:
    if _table_exists(conn, "snapshot_quality_results"):
        conn.row_factory = sqlite3.Row
        results_select = (
            "results_json"
            if "results_json" in _columns(conn, "snapshot_quality_results")
            else "'[]' AS results_json"
        )
        row = conn.execute(
            "SELECT build_id,status,policy_version,evaluated_at,summary_json,"
            f"{results_select} "
            "FROM snapshot_quality_results ORDER BY evaluated_at DESC LIMIT 1"
        ).fetchone()
        if row is not None:
            return {
                "projection_generation_id": generation_id,
                "singleton": 1,
                "status": row["status"],
                "policy_version": row["policy_version"],
                "evaluated_at": row["evaluated_at"],
                "summary_json": row["summary_json"],
                "results_json": row["results_json"],
                "source_build_id": row["build_id"],
            }
    return {
        "projection_generation_id": generation_id,
        "singleton": 1,
        "status": "UNKNOWN",
        "policy_version": "not-projected",
        "evaluated_at": now,
        "summary_json": json.dumps(
            {"reason": "snapshot_quality_results is missing or empty"},
            separators=(",", ":"),
            sort_keys=True,
        ),
        "results_json": "[]",
        "source_build_id": "not-projected",
    }


def _b4_evidence(b0: Mapping[str, Any]) -> dict[str, Any]:
    try:
        document = json.loads(str(b0.get("results_json") or "[]"))
    except json.JSONDecodeError:
        document = []
    results = (
        [
            dict(row)
            for row in document
            if isinstance(row, Mapping) and row.get("check_id") == "B4"
        ]
        if isinstance(document, list)
        else []
    )
    if not results:
        status = "UNKNOWN"
    elif any(str(row.get("status")).lower() != "pass" for row in results):
        status = "FAIL"
    else:
        status = "PASS"
    return {"status": status, "results": results}


def _read_ready(
    snapshot_dir: str | Path | None,
    generation_id: str,
    now: str,
) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    state = {
        "projection_generation_id": generation_id,
        "status": "NOT_READY",
        "snapshot_id": None,
        "reason": "no profile/plan/closure-bound READY snapshot was supplied",
        "evaluated_at": now,
    }
    if snapshot_dir is None:
        return state, [], []
    try:
        from paper_runtime import latest_ready_snapshot

        snapshot = latest_ready_snapshot(snapshot_dir)
    except FileNotFoundError:
        return state, [], []
    manifest = dict(snapshot.manifest)
    required = (
        "profile_id",
        "profile_version",
        "profile_digest",
        "plan_set_digest",
        "dependency_closure_digest",
        "coverage_proof_digest",
        "source_generation",
        "export_cursor",
        "applied_cursor",
    )
    missing = [name for name in required if not manifest.get(name)]
    if missing:
        state["reason"] = "READY manifest missing governed bindings: " + ",".join(missing)
        return state, [], []
    snapshot_id = str(snapshot.snapshot_id)
    committed_at = str(manifest.get("committed_at") or now)
    source_run = manifest.get("source_run") or {}
    ready = {
        "projection_generation_id": generation_id,
        "snapshot_id": snapshot_id,
        "state": "READY",
        "committed_at": committed_at,
        "source_run_id": source_run.get("id") or manifest.get("source_run_id"),
        "change_seq": int(manifest.get("change_seq") or 0),
        "coverage_policy_version": str(
            manifest.get("coverage_policy_version") or "unknown"
        ),
        "quality_policy_version": str(
            manifest.get("quality_policy_version") or "unknown"
        ),
        "coverage_proof_digest": str(manifest["coverage_proof_digest"]),
        "manifest_json": json.dumps(manifest, sort_keys=True, separators=(",", ":")),
    }
    quality_doc = manifest.get("quality") or {}
    quality = {
        "projection_generation_id": generation_id,
        "snapshot_id": snapshot_id,
        "status": str(quality_doc.get("status") or "UNKNOWN"),
        "policy_version": ready["quality_policy_version"],
        "evaluated_at": str(quality_doc.get("evaluated_at") or committed_at),
        "summary_json": json.dumps(
            quality_doc.get("summary") or {}, sort_keys=True, separators=(",", ":")
        ),
    }
    state.update(
        {
            "status": "READY",
            "snapshot_id": snapshot_id,
            "reason": "profile/plan/closure-bound immutable READY is projected",
        }
    )
    return state, [ready], [quality]


def _read_latest_runs(conn: sqlite3.Connection, generation_id: str) -> list[dict[str, Any]]:
    required = ("id", "ran_at", "source", "runtime", "status", "detail")
    if not set(required) <= _columns(conn, "ingestion_run_log"):
        return []
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT id,ran_at,source,runtime,status,detail FROM ingestion_run_log "
        "ORDER BY id DESC LIMIT 100"
    ).fetchall()
    return [
        {"projection_generation_id": generation_id, **dict(row)} for row in rows
    ]


def _read_latest_validation(
    conn: sqlite3.Connection, generation_id: str
) -> list[dict[str, Any]]:
    needed = {
        "run_id", "dataset", "status", "rows_seen", "rows_inserted",
        "rows_revisions", "detail",
    }
    if not needed <= _columns(conn, "ingestion_validation"):
        return []
    latest = _safe_scalar(
        conn,
        "ingestion_validation",
        "SELECT MAX(run_id) FROM ingestion_validation",
    )
    if latest is None:
        return []
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT run_id,dataset,status,rows_seen,rows_inserted,rows_revisions,detail "
        "FROM ingestion_validation WHERE run_id=? ORDER BY dataset",
        (latest,),
    ).fetchall()
    return [
        {"projection_generation_id": generation_id, **dict(row)} for row in rows
    ]


def _read_watermarks(conn: sqlite3.Connection, generation_id: str) -> list[dict[str, Any]]:
    columns = (
        "dataset", "last_event_date", "last_ingested_at", "last_export_cursor"
    )
    if not set(columns) <= _columns(conn, "ingestion_watermarks"):
        return []
    conn.row_factory = sqlite3.Row
    return [
        {"projection_generation_id": generation_id, **dict(row)}
        for row in conn.execute(
            "SELECT dataset,last_event_date,last_ingested_at,last_export_cursor "
            "FROM ingestion_watermarks ORDER BY dataset"
        ).fetchall()
    ]


def _read_applied_cursor(conn: sqlite3.Connection) -> tuple[int | None, str | None]:
    if not {"feed", "last_applied_change_seq", "updated_at"} <= _columns(
        conn, "sync_change_state"
    ):
        return None, None
    row = conn.execute(
        "SELECT last_applied_change_seq,updated_at FROM sync_change_state "
        "WHERE feed=? LIMIT 1",
        (CANONICAL_APPLY_FEED,),
    ).fetchone()
    if row is None:
        return None, None
    return coerce_applied_seq(row[0]), row[1]


def _read_authoritative_raw_segments(
    conn: sqlite3.Connection, generation_id: str
) -> list[dict[str, Any]]:
    receipt_columns = {
        "source", "dataset", "segment_id", "run_id", "status", "error",
        "checked_at",
    }
    if not receipt_columns <= _columns(conn, "collection_receipts"):
        return []
    raw_columns = {
        "dataset", "run_id", "manifest_key", "page_count", "row_count",
        "raw_bytes", "data_digest", "completeness", "created_at",
    }
    has_raw = raw_columns <= _columns(conn, "raw_retention_manifests")
    join = (
        "LEFT JOIN raw_retention_manifests m "
        "ON m.dataset=r.dataset AND m.run_id=r.run_id"
        if has_raw
        else ""
    )
    raw_select = (
        "m.manifest_key,m.page_count,m.row_count,m.raw_bytes,m.data_digest,"
        "m.completeness AS raw_completeness,m.created_at"
        if has_raw
        else "NULL,NULL,NULL,NULL,NULL,NULL,NULL"
    )
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        f"""
        WITH ranked AS (
          SELECT source,dataset,segment_id,run_id,status,error,checked_at,
                 ROW_NUMBER() OVER (
                   PARTITION BY source,dataset,segment_id
                   ORDER BY checked_at DESC,run_id DESC
                 ) AS rank_no
            FROM collection_receipts
        )
        SELECT r.source,r.dataset,r.segment_id,r.run_id,r.status,r.error,r.checked_at,
               {raw_select}
          FROM ranked r {join}
         WHERE r.rank_no=1
         ORDER BY r.dataset,r.segment_id
        """
    ).fetchall()
    projected: list[dict[str, Any]] = []
    for row in rows:
        value = dict(row)
        receipt_ok = str(value["status"]).upper() == "SUCCESS"
        completeness = value.pop("raw_completeness")
        if not receipt_ok:
            completeness = "FAILED"
            reason = value.get("error") or "latest authoritative receipt failed"
        elif completeness is None:
            completeness = "NOT_CAPTURED"
            reason = "latest successful receipt has no raw retention manifest"
        else:
            reason = "latest authoritative segment receipt"
        projected.append(
            {
                "projection_generation_id": generation_id,
                "source": value["source"],
                "dataset": value["dataset"],
                "segment_id": value["segment_id"],
                "run_id": value["run_id"],
                "manifest_key": value.get("manifest_key"),
                "page_count": value.get("page_count"),
                "row_count": value.get("row_count"),
                "raw_bytes": value.get("raw_bytes"),
                "data_digest": value.get("data_digest"),
                "completeness": completeness,
                "created_at": value.get("created_at") or value.get("checked_at"),
                "reason": reason,
            }
        )
    return projected


def _read_sla_rows(
    conn: sqlite3.Connection,
    inventory: Sequence[Mapping[str, Any]],
    watermarks: Sequence[Mapping[str, Any]],
    generation_id: str,
    generated_at: str,
    projection_status: str,
) -> list[dict[str, Any]]:
    watermark = {
        str(row["dataset"]): row.get("last_event_date") for row in watermarks
    }
    local: dict[str, Mapping[str, Any]] = {}
    columns = (
        "dataset_id", "expected_after", "usable_by", "freshness_policy",
        "timezone", "current_state", "state_reason", "state_since",
        "last_event_date", "last_checked_at",
    )
    if set(columns) <= _columns(conn, "collection_sla_status"):
        conn.row_factory = sqlite3.Row
        local = {
            str(row["dataset_id"]): dict(row)
            for row in conn.execute(
                f"SELECT {','.join(columns)} FROM collection_sla_status"
            ).fetchall()
        }
    rows: list[dict[str, Any]] = []
    for entry in inventory:
        dataset = str(entry["dataset_id"])
        if dataset in local:
            row = dict(local[dataset])
        else:
            sla = json.loads(str(entry.get("sla") or "{}"))
            stale = projection_status != "FRESH"
            row = {
                "dataset_id": dataset,
                "expected_after": sla.get("expected_after"),
                "usable_by": sla.get("usable_by"),
                "freshness_policy": sla.get("freshness_policy") or "unknown",
                "timezone": sla.get("timezone") or "Asia/Tokyo",
                "current_state": "PROJECTION_STALE" if stale else "UNKNOWN",
                "state_reason": (
                    "ops_projection_stale"
                    if stale
                    else "authoritative SLA observation was not projected"
                ),
                "state_since": None,
                "last_event_date": watermark.get(dataset),
                "last_checked_at": generated_at,
            }
        row["projection_generation_id"] = generation_id
        rows.append(row)
    return rows


def _storage_payload(
    conn: sqlite3.Connection,
    *,
    generation_id: str,
    generated_at: str,
    source_db_digest: str,
    coverage: Sequence[Mapping[str, Any]],
    hot_cutoff: str | None,
) -> dict[str, Any]:
    counts = {
        "jquants_records_total": _safe_count(conn, "jquants_records"),
        "ingestion_change_log_rows": _safe_count(conn, "ingestion_change_log"),
        "complete_segments": _safe_count(
            conn, "coverage_segments", " WHERE status='COMPLETE'"
        ),
        "jsda_otc_rows": _safe_count(conn, "jsda_otc_bond_reference_prices"),
        "jsda_corporate_rows": _safe_count(
            conn, "jsda_corporate_bond_transactions"
        ),
        "jsda_tokyo_repo_rows": _safe_count(conn, "jsda_repo_rates"),
        "legacy_bars_rows": _safe_count(conn, "jquants_daily_bars"),
        "legacy_master_rows": _safe_count(conn, "jquants_listed_info"),
        "legacy_calendar_rows": _safe_count(conn, "jquants_market_calendar"),
        "nk_primary_stage_rows": _safe_count(
            conn, "jquants_records_nk_v2_primary_stage"
        ),
        "nk_revisions_stage_rows": _safe_count(
            conn, "jquants_records_nk_v2_revisions_stage"
        ),
        "nk_versions_stage_rows": _safe_count(
            conn, "jquants_records_nk_v2_versions_stage"
        ),
        "nk_change_stage_rows": _safe_count(
            conn, "ingestion_change_log_nk_v2_stage"
        ),
    }
    hot_window: dict[str, Any]
    if hot_cutoff is None:
        hot_window = {
            "status": "NOT_PROJECTED",
            "cutoff": None,
            "reason": "publisher did not receive an explicit storage hot cutoff",
        }
    else:
        date.fromisoformat(hot_cutoff)
        if _table_exists(conn, "jquants_records"):
            hot_window = {
                "status": "MATERIALIZED",
                "cutoff": hot_cutoff,
                "bars_hot": _safe_count(
                    conn,
                    "jquants_records",
                    " WHERE dataset='equities_bars_daily' AND substr(event_time,1,10)>=?",
                    (hot_cutoff,),
                ),
                "bars_cold": _safe_count(
                    conn,
                    "jquants_records",
                    " WHERE dataset='equities_bars_daily' AND substr(event_time,1,10)<?",
                    (hot_cutoff,),
                ),
                "master_hot": _safe_count(
                    conn,
                    "jquants_records",
                    " WHERE dataset='equities_master' AND substr(event_time,1,10)>=?",
                    (hot_cutoff,),
                ),
            }
        else:
            hot_window = {
                "status": "NOT_PROJECTED",
                "cutoff": hot_cutoff,
                "reason": "jquants_records source table is missing",
            }
    coverage_by_dataset = {
        str(row["dataset"]): {
            "status": row.get("status"),
            "row_count": row.get("row_count"),
            "observed_start": row.get("observed_start"),
            "observed_end": row.get("observed_end"),
        }
        for row in coverage
        if str(row.get("dataset") or "").startswith("jsda_")
    }
    return {
        "schema": "ops_storage_plane_status/v1",
        "plane": "ops_projection",
        "generation": generation_id,
        "materialized_at": generated_at,
        "source_db_digest": source_db_digest,
        "counts": counts,
        "hot_window": hot_window,
        "jsda_coverage": coverage_by_dataset,
        "missing_source_tables": sorted(
            key for key, value in counts.items() if value is None
        ),
        "p0_claims": {
            "mass_research": "NO-GO",
            "ready": None,
            "honesty_note": (
                "Publisher-materialized counts only. This payload is not READY "
                "and never queries ingestion facts from the MCP Worker."
            ),
        },
    }


def _alerts(
    generation_id: str,
    now: str,
    *,
    projection_status: str,
    applied_cursor: int | None,
    b0: Mapping[str, Any],
    ready_state: Mapping[str, Any],
) -> list[dict[str, Any]]:
    candidates = []
    if projection_status != "FRESH":
        candidates.append(("projection-stale", "critical", projection_status))
    if applied_cursor is None:
        candidates.append(("applied-cursor-null", "critical", "apply pin is null"))
    if b0.get("status") != "PASS":
        candidates.append(("b0-not-pass", "critical", str(b0.get("status"))))
    if ready_state.get("status") != "READY":
        candidates.append(("ready-not-published", "critical", str(ready_state.get("reason"))))
    return [
        {
            "projection_generation_id": generation_id,
            "alert_key": key,
            "severity": severity,
            "status": "OPEN",
            "reason": reason,
            "observed_at": now,
            "detail_json": "{}",
        }
        for key, severity, reason in candidates
    ]


def _content_digest(payload: Mapping[str, Any]) -> str:
    body = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return "sha256:" + hashlib.sha256(body.encode()).hexdigest()


def _tag(rows: Iterable[Mapping[str, Any]], generation_id: str) -> list[dict[str, Any]]:
    return [
        {"projection_generation_id": generation_id, **dict(row)} for row in rows
    ]


def _render_projection_bundle(
    source: str | Path | sqlite3.Connection,
    *,
    snapshot_dir: str | Path | None = None,
    max_age_seconds: int = DEFAULT_MAX_AGE_SECONDS,
    use_sql_transaction: bool = True,
    generation_id: str | None = None,
    producer_commit_sha: str | None = None,
    refresh_status: str | None = None,
    refresh_error: str | None = None,
    last_refresh_attempt_at: str | None = None,
    last_success_at: str | None = None,
    source_cursor: int | None = None,
    export_cursor: int | None = None,
    storage_hot_cutoff: str | None = None,
    _generated_at: str | None = None,
    _seal_and_activate: bool = True,
) -> ProjectionBundle:
    """Canonical renderer over one SQLite read connection/snapshot.

    Path callers are compatibility-only: this function opens one read-only
    connection and then uses the same connection-owned query path.  The C4
    candidate boundary passes the already-authenticated connection directly.
    """
    from data_contracts.coverage import (
        all_coverage_contracts,
        coverage_policy_binding,
        coverage_policy_set_binding,
    )
    from ops.projection_meta import _build_projection_metadata_from_connection

    gen = generation_id or "projgen-" + uuid4().hex
    commit_sha = _git_sha(producer_commit_sha)
    contract_digest, registry_digest = _contract_digests()
    generated_at = _generated_at or _now()
    owns_connection = type(source) is not sqlite3.Connection
    if owns_connection:
        path = Path(source).resolve()
        if not path.is_file():
            raise FileNotFoundError(path)
        conn = sqlite3.connect(
            "file:" + quote(str(path)) + "?mode=ro",
            uri=True,
        )
        conn.execute("PRAGMA query_only=ON")
    else:
        conn = source
        if type(conn) is not sqlite3.Connection:
            raise TypeError("projection source must be one exact SQLite connection")
        if not conn.in_transaction:
            raise RuntimeError(
                "caller-owned projection connection requires an active snapshot"
            )
    original_row_factory = conn.row_factory
    conn.row_factory = sqlite3.Row
    started_transaction = False
    try:
        # Freeze every source query (coverage, receipts, cursors, READY and
        # evidence digests) to one SQLite read snapshot.
        if owns_connection:
            conn.execute("BEGIN")
            started_transaction = True
        else:
            query_only = conn.execute("PRAGMA query_only").fetchone()
            if query_only is None or tuple(query_only) != (1,):
                raise RuntimeError(
                    "caller-owned projection connection must already be read-only"
                )
        coverage = _rows(
            conn,
            "dataset_coverage",
            DATASET_COVERAGE_COLUMNS,
            order_by="dataset",
            required=True,
        )
        segments = _rows(
            conn,
            "coverage_segments",
            COVERAGE_SEGMENT_COLUMNS,
            order_by="dataset,segment_start,segment_id",
            required=True,
        )
        inventory = _source_inventory()
        runs = _read_latest_runs(conn, gen)
        validation = _read_latest_validation(conn, gen)
        watermarks = _read_watermarks(conn, gen)
        raw_segments = _read_authoritative_raw_segments(conn, gen)
        applied_cursor, applied_updated_at = _read_applied_cursor(conn)
        if source_cursor is None:
            source_cursor = coerce_applied_seq(
                _safe_scalar(
                    conn,
                    "ingestion_change_log",
                    "SELECT MAX(change_seq) FROM ingestion_change_log",
                )
            )
        change_rows = _safe_count(conn, "ingestion_change_log")
        b0 = _read_b0(conn, gen, generated_at)
        b4 = _b4_evidence(b0)
        ready_state, ready_rows, quality_rows = _read_ready(
            snapshot_dir, gen, generated_at
        )

        expected_coverage_ids = {
            contract.dataset_id for contract in all_coverage_contracts()
        }
        observed_coverage_ids = {str(row["dataset"]) for row in coverage}
        if observed_coverage_ids != expected_coverage_ids:
            raise RuntimeError(
                "dataset_coverage does not exactly match the governed catalog: "
                f"missing={sorted(expected_coverage_ids - observed_coverage_ids)}, "
                f"extra={sorted(observed_coverage_ids - expected_coverage_ids)}"
            )
        policy_set = coverage_policy_set_binding(sorted(observed_coverage_ids))
        coverage_policy_version = str(policy_set["policy_version"])
        coverage_policy_digest = str(policy_set["policy_digest"])
        for row in coverage:
            expected_policy = coverage_policy_binding(str(row["dataset"]))
            if row.get("policy_version") != expected_policy["policy_version"]:
                raise RuntimeError(
                    "dataset_coverage policy drift for "
                    f"{row['dataset']}: observed={row.get('policy_version')!r}, "
                    f"expected={expected_policy['policy_version']!r}"
                )

        metadata = _build_projection_metadata_from_connection(
            conn,
            generated_at=generated_at,
            max_age_seconds=max_age_seconds,
            refresh_status=refresh_status,
            refresh_error=refresh_error,
            last_refresh_attempt_at=last_refresh_attempt_at,
            last_success_at=last_success_at,
            publisher="scripts/export_ops_projection.py",
            generation_id=gen,
            producer_commit_sha=commit_sha,
            contract_digest=contract_digest,
            registry_digest=registry_digest,
            request_now=datetime.fromisoformat(
                generated_at.replace("Z", "+00:00")
            ),
        )
        status = str(metadata.get("status") or "UNKNOWN")
        if status not in {"FRESH", "STALE", "FAILED", "UNKNOWN"}:
            status = "FAILED" if status == "DEGRADED_REFRESH_FAILED" else "STALE"

        tagged_coverage = _tag(coverage, gen)
        tagged_segments = _tag(segments, gen)
        tagged_inventory = _tag(inventory, gen)
        sla_rows = _read_sla_rows(
            conn,
            tagged_inventory,
            watermarks,
            gen,
            generated_at,
            status,
        )

        provisional = {
            "coverage": tagged_coverage,
            "segments": tagged_segments,
            "inventory": tagged_inventory,
            "runs": runs,
            "validation": validation,
            "raw_segments": raw_segments,
            "watermarks": watermarks,
            "b0": b0,
            "ready_state": ready_state,
            "ready": ready_rows,
            "quality": quality_rows,
            "source_cursor": source_cursor,
            "export_cursor": export_cursor,
            "applied_cursor": applied_cursor,
            "contract_digest": contract_digest,
            "registry_digest": registry_digest,
        }
        source_db_digest = _content_digest(provisional)
        storage = _storage_payload(
            conn,
            generation_id=gen,
            generated_at=generated_at,
            source_db_digest=source_db_digest,
            coverage=tagged_coverage,
            hot_cutoff=storage_hot_cutoff,
        )
    finally:
        if owns_connection:
            if started_transaction and conn.in_transaction:
                conn.rollback()
            conn.close()
        else:
            conn.row_factory = original_row_factory

    lag = (
        None
        if source_cursor is None or export_cursor is None
        else max(0, source_cursor - export_cursor)
    )
    sync_feed = {
        "projection_generation_id": gen,
        "feed": CANONICAL_APPLY_FEED,
        "latest_source_change_seq": source_cursor,
        "change_log_row_count": change_rows,
        "exported_cursor": export_cursor,
        "applied_cursor": applied_cursor,
        "updated_at": applied_updated_at,
    }
    detail = json.loads(str(metadata.get("detail_json") or "{}"))
    detail.update(
        {
            "refresh_status": refresh_status,
            "active_generation": gen,
            "source_db_digest": source_db_digest,
            "source_cursor": source_cursor,
            "export_cursor": export_cursor,
            "applied_cursor": applied_cursor,
            "sync_state": sync_dataset_state(
                exported=export_cursor,
                applied=applied_cursor,
                lag=lag,
                change_log_rows=0 if change_rows is None else change_rows,
            ),
        }
    )
    metadata_row = {
        "projection_generation_id": gen,
        "generated_at": metadata.get("generated_at") or generated_at,
        "source_generation": metadata.get("source_generation"),
        "source_cursor": source_cursor,
        "export_cursor": export_cursor,
        "applied_cursor": applied_cursor,
        "age_seconds": metadata.get("age_seconds"),
        "status": status,
        "projection_version": PROJECTION_VERSION,
        "refresh_attempt_at": metadata.get("last_refresh_attempt_at"),
        "refresh_success_at": metadata.get("last_success_at"),
        "refresh_error": refresh_error,
        "detail_json": json.dumps(detail, sort_keys=True, separators=(",", ":")),
    }
    alert_rows = _alerts(
        gen,
        generated_at,
        projection_status=status,
        applied_cursor=applied_cursor,
        b0=b0,
        ready_state=ready_state,
    )
    storage_row = {
        "projection_generation_id": gen,
        "materialized_at": generated_at,
        "payload_json": json.dumps(storage, sort_keys=True, separators=(",", ":")),
    }

    tables: list[tuple[str, tuple[str, ...], list[dict[str, Any]]]] = [
        ("dataset_coverage", ("projection_generation_id",) + DATASET_COVERAGE_COLUMNS, tagged_coverage),
        ("coverage_segments", ("projection_generation_id",) + COVERAGE_SEGMENT_COLUMNS, tagged_segments),
        ("endpoint_inventory", (
            "projection_generation_id", "dataset_id", "display_name", "source",
            "governance_tier", "inventory_status", "upstream_locator",
            "collection_window", "expected_frequency",
            "coverage_segment_granularity", "research_eligible", "enabled",
            "sla", "historical_start", "available_at_json",
        ), tagged_inventory),
        ("collection_sla_status", (
            "projection_generation_id", "dataset_id", "expected_after", "usable_by",
            "freshness_policy", "timezone", "current_state", "state_reason",
            "state_since", "last_event_date", "last_checked_at",
        ), sla_rows),
        ("ingestion_run_log", (
            "projection_generation_id", "id", "ran_at", "source", "runtime",
            "status", "detail",
        ), runs),
        ("ingestion_validation", (
            "projection_generation_id", "run_id", "dataset", "status",
            "rows_seen", "rows_inserted", "rows_revisions", "detail",
        ), validation),
        ("raw_retention_manifests", (
            "projection_generation_id", "source", "dataset", "segment_id", "run_id",
            "manifest_key", "page_count", "row_count", "raw_bytes", "data_digest",
            "completeness", "created_at", "reason",
        ), raw_segments),
        ("ingestion_watermarks", (
            "projection_generation_id", "dataset", "last_event_date",
            "last_ingested_at", "last_export_cursor",
        ), watermarks),
        ("ops_sync_feed", (
            "projection_generation_id", "feed", "latest_source_change_seq",
            "change_log_row_count", "exported_cursor", "applied_cursor", "updated_at",
        ), [sync_feed]),
        ("ops_projection_metadata", tuple(metadata_row), [metadata_row]),
        ("ops_b0_status", tuple(b0), [b0]),
        ("ops_ready_state", tuple(ready_state), [ready_state]),
        ("ops_ready_snapshots", (
            "projection_generation_id", "snapshot_id", "state", "committed_at",
            "source_run_id", "change_seq", "coverage_policy_version",
            "quality_policy_version", "coverage_proof_digest", "manifest_json",
        ), ready_rows),
        ("ops_snapshot_quality", (
            "projection_generation_id", "snapshot_id", "status", "policy_version",
            "evaluated_at", "summary_json",
        ), quality_rows),
        ("ops_storage_plane_status", tuple(storage_row), [storage_row]),
        ("ops_alerts", (
            "projection_generation_id", "alert_key", "severity", "status",
            "reason", "observed_at", "detail_json",
        ), alert_rows),
    ]
    row_counts = {table: len(rows) for table, _columns_, rows in tables}
    generated = str(metadata_row["generated_at"])
    content_manifest, content_digest = build_projection_content_manifest(
        {table: rows for table, _columns_, rows in tables}
    )
    coverage_digest = _content_digest(
        {"dataset_coverage": tagged_coverage, "coverage_segments": tagged_segments}
    )
    b0_digest = _content_digest({"ops_b0_status": b0})
    b4_digest = _content_digest({"b4": b4})
    evidence_digests = {
        "coverage": coverage_digest,
        "raw_retention": _content_digest({"raw_retention": raw_segments}),
        "validation": _content_digest({"validation": validation}),
        "ready": _content_digest(
            {"state": ready_state, "snapshots": ready_rows, "quality": quality_rows}
        ),
        "sync": _content_digest(
            {"feed": sync_feed, "watermarks": watermarks, "metadata": metadata_row}
        ),
        "storage": _content_digest({"storage": storage_row}),
    }
    dataset_coverage_evidence = {
        str(row["dataset"]): {
            "status": row.get("status"),
            "coverage_mode": row.get("coverage_mode"),
            **dict(coverage_policy_binding(str(row["dataset"]))),
            "collection_scope": row.get("collection_scope"),
            "observed_start": row.get("observed_start"),
            "observed_end": row.get("observed_end"),
        }
        for row in tagged_coverage
    }
    envelope = {
        "schema_version": "ops-projection-envelope/v1",
        "generation_id": gen,
        "content_digest": content_digest,
        "source_db_digest": source_db_digest,
        "generated_at": generated,
        "producer_commit_sha": commit_sha,
        "contract_digest": contract_digest,
        "registry_digest": registry_digest,
        "coverage_policy_version": coverage_policy_version,
        "coverage_policy_digest": coverage_policy_digest,
        "projection_status": status,
        "source_generation": source_cursor,
        "source_snapshot_generation": metadata_row.get("source_generation"),
        "source_cursor": source_cursor,
        "export_cursor": export_cursor,
        "applied_cursor": applied_cursor,
        "coverage_status_digest": coverage_digest,
        "dataset_coverage": dataset_coverage_evidence,
        "b0_status": str(b0.get("status") or "UNKNOWN"),
        "b0_evidence_digest": b0_digest,
        "b4_status": b4["status"],
        "b4_evidence_digest": b4_digest,
        "evidence_digests": evidence_digests,
        "content_manifest": content_manifest,
        "row_counts": row_counts,
    }
    # Diagnostic/product rendering is strictly unsigned.  A future dedicated
    # authority must derive and sign from an authenticated full-source handle;
    # this exporter intentionally accepts no signer or pre-authored envelope.
    signed_envelope = None
    signed_envelope_json = None
    issuer_key_id = None
    signature = None

    statements = ["BEGIN TRANSACTION;"] if use_sql_transaction else []
    statements.append(
        "INSERT INTO ops_projection_generation "
        "(generation_id,status,source_db_digest,content_digest,generated_at,"
        "producer_commit_sha,contract_digest,registry_digest,coverage_policy_version,"
        "sealed_at,signed_envelope_json,issuer_key_id,signature,detail_json) "
        "VALUES ("
        f"{_sql_literal(gen)},'OPEN',{_sql_literal(source_db_digest)},"
        f"{_sql_literal(content_digest)},"
        f"{_sql_literal(generated)},{_sql_literal(commit_sha)},"
        f"{_sql_literal(contract_digest)},{_sql_literal(registry_digest)},"
        f"{_sql_literal(coverage_policy_version)},NULL,"
        f"{_sql_literal(signed_envelope_json)},{_sql_literal(issuer_key_id)},"
        f"{_sql_literal(signature)},'{{}}');"
    )
    for table, columns, rows in tables:
        statements.extend(_insert_sql(table, columns, rows))

    required_counts = (
        "dataset_coverage", "coverage_segments", "endpoint_inventory",
        "collection_sla_status", "ingestion_run_log", "ingestion_validation",
        "raw_retention_manifests", "ingestion_watermarks", "ops_sync_feed",
        "ops_projection_metadata", "ops_b0_status", "ops_ready_state",
        "ops_ready_snapshots", "ops_snapshot_quality",
        "ops_storage_plane_status", "ops_alerts",
    )
    guard = " AND ".join(
        f"(SELECT COUNT(*) FROM {table} WHERE projection_generation_id="
        f"{_sql_literal(gen)})={row_counts[table]}"
        for table in required_counts
    )
    cursor_guard = "1=1"
    exact_current_cursor = (
        not isinstance(source_cursor, bool)
        and isinstance(source_cursor, int)
        and source_cursor > 0
        and export_cursor == source_cursor
        and applied_cursor == source_cursor
    )
    if exact_current_cursor:
        cursor_guard = (
            "(NOT EXISTS (SELECT 1 FROM ops_projection_active current "
            "WHERE current.singleton=1) OR EXISTS ("
            "SELECT 1 FROM ops_projection_active current "
            "JOIN ops_projection_metadata current_meta "
            "ON current_meta.projection_generation_id=current.generation_id "
            "WHERE current.singleton=1 "
            "AND current_meta.source_cursor IS NOT NULL "
            "AND current_meta.export_cursor IS NOT NULL "
            "AND current_meta.applied_cursor IS NOT NULL "
            "AND current_meta.source_cursor=current_meta.export_cursor "
            "AND current_meta.export_cursor=current_meta.applied_cursor "
            f"AND current_meta.applied_cursor<={source_cursor}))"
        )
    if _seal_and_activate:
        statements.append(
            "UPDATE ops_projection_generation "
            f"SET status='SEALED',sealed_at={_sql_literal(generated)} "
            f"WHERE generation_id={_sql_literal(gen)} AND status='OPEN' AND {guard};"
        )
        # Deliberately last: partial imports leave an unreferenced OPEN generation
        # but cannot seal it or make it visible to an MCP query.
        statements.append(
            "INSERT INTO ops_projection_active (singleton,generation_id,activated_at) "
            f"SELECT 1,{_sql_literal(gen)},{_sql_literal(generated)} "
            "FROM ops_projection_generation "
            f"WHERE generation_id={_sql_literal(gen)} AND status='SEALED' "
            f"AND {guard} AND {cursor_guard} "
            "ON CONFLICT(singleton) DO UPDATE SET "
            "generation_id=excluded.generation_id,activated_at=excluded.activated_at "
            f"WHERE {cursor_guard};"
        )
    if use_sql_transaction:
        statements.append("COMMIT;")
    return ProjectionBundle(
        sql="\n".join(statements) + "\n",
        generation_id=gen,
        source_db_digest=source_db_digest,
        content_digest=content_digest,
        row_counts=row_counts,
        complete_coverage_segments=storage["counts"]["complete_segments"],
        metadata=metadata_row,
        envelope=envelope,
        signed_envelope=signed_envelope,
        activation_included=_seal_and_activate,
    )


def render_projection_bundle(
    db_path: str | Path,
    *,
    snapshot_dir: str | Path | None = None,
    max_age_seconds: int = DEFAULT_MAX_AGE_SECONDS,
    use_sql_transaction: bool = True,
    generation_id: str | None = None,
    producer_commit_sha: str | None = None,
    refresh_status: str | None = None,
    refresh_error: str | None = None,
    last_refresh_attempt_at: str | None = None,
    last_success_at: str | None = None,
    storage_hot_cutoff: str | None = None,
) -> ProjectionBundle:
    """Render an unsigned diagnostic projection from a caller-selected DB.

    Production cursor pins and signing authority are intentionally absent from
    this public API.  Publication remains fail-closed until the private trusted
    entrypoint has a separately provisioned C4 signing authority.
    """
    return _render_projection_bundle(
        db_path,
        snapshot_dir=snapshot_dir,
        max_age_seconds=max_age_seconds,
        use_sql_transaction=use_sql_transaction,
        generation_id=generation_id,
        producer_commit_sha=producer_commit_sha,
        refresh_status=refresh_status,
        refresh_error=refresh_error,
        last_refresh_attempt_at=last_refresh_attempt_at,
        last_success_at=last_success_at,
        storage_hot_cutoff=storage_hot_cutoff,
    )


_SYNC_IDENTITY_FIELDS = frozenset(
    {
        "audit_digest",
        "issuer_key_id",
        "export_digest",
        "source_change_seq",
        "applied_change_seq",
        "source_content_digest",
        "local_content_digest",
        "source_schema_digest",
        "schema_digest",
        "table_counts",
    }
)


def _freeze_authenticated_sync_identity(
    identity: Mapping[str, object],
) -> dict[str, Any]:
    """Copy the closed, immutable identity supplied by the mirror authority."""

    if type(identity) is not MappingProxyType or set(identity) != _SYNC_IDENTITY_FIELDS:
        raise RuntimeError("Ops Projection sync identity is not authority-frozen")
    source_cursor = identity.get("source_change_seq")
    applied_cursor = identity.get("applied_change_seq")
    if (
        type(source_cursor) is not int
        or source_cursor <= 0
        or type(applied_cursor) is not int
        or applied_cursor != source_cursor
    ):
        raise RuntimeError("Ops Projection sync cursor identity is invalid")
    digest_fields = (
        "audit_digest",
        "export_digest",
        "source_content_digest",
        "local_content_digest",
        "source_schema_digest",
        "schema_digest",
    )
    for field in digest_fields:
        value = identity.get(field)
        if (
            type(value) is not str
            or len(value) != 71
            or not value.startswith("sha256:")
            or any(character not in "0123456789abcdef" for character in value[7:])
        ):
            raise RuntimeError(f"Ops Projection sync {field} is invalid")
    if identity["source_content_digest"] != identity["local_content_digest"]:
        raise RuntimeError("Ops Projection source/local sync content differs")
    issuer_key_id = identity.get("issuer_key_id")
    if type(issuer_key_id) is not str or not issuer_key_id:
        raise RuntimeError("Ops Projection sync issuer is invalid")
    counts = identity.get("table_counts")
    if type(counts) is not MappingProxyType or not counts:
        raise RuntimeError("Ops Projection sync inventory is not authority-frozen")
    if any(
        type(table) is not str
        or not table
        or type(count) is not int
        or count < 0
        for table, count in counts.items()
    ):
        raise RuntimeError("Ops Projection sync inventory is invalid")
    return {
        "audit_digest": identity["audit_digest"],
        "issuer_key_id": issuer_key_id,
        "export_digest": identity["export_digest"],
        "source_change_seq": source_cursor,
        "applied_change_seq": applied_cursor,
        "source_content_digest": identity["source_content_digest"],
        "local_content_digest": identity["local_content_digest"],
        "source_schema_digest": identity["source_schema_digest"],
        "schema_digest": identity["schema_digest"],
        "table_counts": dict(counts),
    }


def _measure_connection_snapshot(
    conn: sqlite3.Connection,
) -> _ConnectionSnapshotDescriptor:
    """Prove the renderer still owns one descriptor-bound read snapshot."""

    if type(conn) is not sqlite3.Connection:
        raise RuntimeError("Ops Projection requires one exact SQLite connection")
    if not conn.in_transaction:
        raise RuntimeError("Ops Projection cannot hold one SQLite read snapshot")
    query_only = conn.execute("PRAGMA query_only").fetchone()
    if query_only is None or tuple(query_only) != (1,):
        raise RuntimeError("Ops Projection source connection is writable")
    journal_mode = conn.execute("PRAGMA journal_mode").fetchone()
    if journal_mode is None or tuple(journal_mode) != ("delete",):
        raise RuntimeError("Ops Projection source connection is not frozen")
    databases = [tuple(row) for row in conn.execute("PRAGMA database_list")]
    main_rows = [row for row in databases if len(row) == 3 and row[1] == "main"]
    other_rows = [row for row in databases if row not in main_rows]
    if len(main_rows) != 1 or other_rows not in ([], [(1, "temp", "")]):
        raise RuntimeError("Ops Projection source connection is not descriptor-bound")
    descriptor_path = main_rows[0][2]
    descriptor_roots = ("/dev/fd/", "/proc/self/fd/")
    if (
        type(descriptor_path) is not str
        or not any(descriptor_path.startswith(root) for root in descriptor_roots)
        or not descriptor_path.rsplit("/", 1)[-1].isdigit()
    ):
        raise RuntimeError("Ops Projection source connection is not descriptor-bound")
    try:
        descriptor_stat = os.stat(descriptor_path)
    except OSError as exc:
        raise RuntimeError("Ops Projection source descriptor disappeared") from exc
    if not stat.S_ISREG(descriptor_stat.st_mode):
        raise RuntimeError("Ops Projection source descriptor is not a regular file")
    schema_row = conn.execute("PRAGMA main.schema_version").fetchone()
    data_row = conn.execute("PRAGMA main.data_version").fetchone()
    if schema_row is None or data_row is None:
        raise RuntimeError("Ops Projection source snapshot identity is unavailable")
    return _ConnectionSnapshotDescriptor(
        descriptor_path=descriptor_path,
        device=int(descriptor_stat.st_dev),
        inode=int(descriptor_stat.st_ino),
        size=int(descriptor_stat.st_size),
        mtime_ns=int(descriptor_stat.st_mtime_ns),
        schema_version=int(schema_row[0]),
        data_version=int(data_row[0]),
        total_changes=int(conn.total_changes),
    )


def _render_projection_candidate_from_connection(
    conn: sqlite3.Connection,
    sync_identity: Mapping[str, object],
) -> UnsignedOpsProjectionCandidate:
    """Render one unsigned candidate from an authority-owned source snapshot.

    There is intentionally no path, signer, envelope, count, digest, cursor,
    clock, generation, READY directory, or activation argument on this API.
    """

    initial_snapshot = _measure_connection_snapshot(conn)
    frozen_sync_identity = _freeze_authenticated_sync_identity(sync_identity)
    generated_at = _now()
    generation_id = "projgen-candidate-" + d1_sync_digest(
        {
            "sync_identity": frozen_sync_identity,
            "generated_at": generated_at,
        }
    ).removeprefix("sha256:")[:32]
    source_cursor = frozen_sync_identity["source_change_seq"]
    applied_cursor = frozen_sync_identity["applied_change_seq"]
    assert type(source_cursor) is int
    assert type(applied_cursor) is int
    bundle = _render_projection_bundle(
        conn,
        generation_id=generation_id,
        producer_commit_sha=None,
        refresh_status=None,
        source_cursor=source_cursor,
        export_cursor=source_cursor,
        storage_hot_cutoff=None,
        _generated_at=generated_at,
        _seal_and_activate=False,
    )
    final_snapshot = _measure_connection_snapshot(conn)
    if final_snapshot != initial_snapshot:
        raise RuntimeError("Ops Projection source snapshot changed during render")
    rendered_cursors = (
        bundle.envelope.get("source_cursor"),
        bundle.envelope.get("export_cursor"),
        bundle.envelope.get("applied_cursor"),
    )
    if rendered_cursors != (source_cursor, source_cursor, applied_cursor):
        raise RuntimeError("Ops Projection candidate cursor identity changed")
    if bundle.signed_envelope is not None:
        raise RuntimeError("Ops Projection candidate unexpectedly acquired a signer")
    if bundle.activation_included:
        raise RuntimeError("Ops Projection candidate cannot publish or activate")
    envelope = dict(bundle.envelope)
    metadata = dict(bundle.metadata)
    row_counts = dict(bundle.row_counts)
    sync_identity_digest = d1_sync_digest(frozen_sync_identity)
    candidate_document = {
        "schema_version": UNSIGNED_CANDIDATE_SCHEMA,
        "authority_status": "PENDING",
        "sync_identity": frozen_sync_identity,
        "sync_identity_digest": sync_identity_digest,
        "projection": {
            "sql": bundle.sql,
            "generation_id": bundle.generation_id,
            "source_db_digest": bundle.source_db_digest,
            "content_digest": bundle.content_digest,
            "producer_commit_sha": str(envelope["producer_commit_sha"]),
            "contract_digest": str(envelope["contract_digest"]),
            "registry_digest": str(envelope["registry_digest"]),
            "source_cursor": source_cursor,
            "export_cursor": source_cursor,
            "applied_cursor": applied_cursor,
            "metadata": metadata,
            "envelope": envelope,
            "row_counts": row_counts,
            "complete_coverage_segments": bundle.complete_coverage_segments,
            "activation_included": bundle.activation_included,
        },
    }
    return _freeze_unsigned_projection_candidate(
        candidate_document,
        {
            "sync_identity_digest": sync_identity_digest,
            "generation_id": bundle.generation_id,
            "source_db_digest": bundle.source_db_digest,
            "content_digest": bundle.content_digest,
            "producer_commit_sha": str(envelope["producer_commit_sha"]),
            "contract_digest": str(envelope["contract_digest"]),
            "registry_digest": str(envelope["registry_digest"]),
            "source_cursor": source_cursor,
            "export_cursor": source_cursor,
            "applied_cursor": applied_cursor,
        },
    )


def _render_trusted_projection_candidate(
    applied_mirror: Any,
) -> UnsignedOpsProjectionCandidate:
    """Consume one opaque mirror and return an unsigned PENDING candidate."""
    from scripts.sync_d1_to_sqlite import _consume_authenticated_applied_mirror

    return _consume_authenticated_applied_mirror(
        applied_mirror,
        _render_projection_candidate_from_connection,
    )


def _render_trusted_projection_bundle(
    applied_mirror: Any,
    **_kwargs: Any,
) -> ProjectionBundle:
    """Preserve the production publication gate while C4 remains PENDING.

    The publisher still calls this entrypoint.  It deliberately cannot turn an
    unsigned candidate into a publishable bundle or accept a signing service.
    Consuming the positive source capability before failing prevents replay
    through a later, differently configured path.
    """
    from scripts.sync_d1_to_sqlite import _consume_authenticated_applied_mirror

    def pending_authority(
        _conn: sqlite3.Connection,
        _sync_identity: Mapping[str, object],
    ) -> ProjectionBundle:
        raise RuntimeError(
            "Ops Projection signing is PENDING full-source authority integration"
        )

    return _consume_authenticated_applied_mirror(
        applied_mirror,
        pending_authority,
    )


def render_projection_sql(db_path: str | Path, **kwargs: Any) -> str:
    """Compatibility wrapper for callers that only need the SQL document."""
    return render_projection_bundle(db_path, **kwargs).sql


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", required=True, help="validated local control SQLite")
    parser.add_argument("--snapshot-dir", default=None)
    parser.add_argument("--output", default=None)
    parser.add_argument("--storage-hot-cutoff", default=None)
    parser.add_argument("--max-age-seconds", type=int, default=DEFAULT_MAX_AGE_SECONDS)
    args = parser.parse_args(argv)
    bundle = render_projection_bundle(
        args.db,
        snapshot_dir=args.snapshot_dir,
        max_age_seconds=args.max_age_seconds,
        storage_hot_cutoff=args.storage_hot_cutoff,
    )
    if args.output:
        Path(args.output).write_text(bundle.sql, encoding="utf-8")
        print(f"Projection SQL written to {args.output}", file=sys.stderr)
    else:
        sys.stdout.write(bundle.sql)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
