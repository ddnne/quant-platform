#!/usr/bin/env python3
"""Render a verified local Ops/READY control projection as D1 SQL.

The output is applied out-of-band with ``wrangler d1 execute``. The remote MCP
never receives a projection-write capability.

Phase 6.2 Residual: Added projection metadata with generated_at, source_generation,
age, and status fields to prevent stale data from appearing fresh.
"""

from __future__ import annotations

import sys
from pathlib import Path

_here = Path(__file__).resolve().parent
for _d in (_here, _here.parent):
    if (_d / "_bootstrap.py").is_file():
        if str(_d) not in sys.path:
            sys.path.insert(0, str(_d))
        break
else:
    raise RuntimeError("scripts/_bootstrap.py not found")
from _bootstrap import ensure_repo_root  # noqa: E402

import argparse
import json

import sqlite3
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping, Sequence
from urllib.parse import quote

ROOT = ensure_repo_root()

from paper_runtime import latest_ready_snapshot  # noqa: E402

PROJECTION_VERSION = "ops_projection/v1"
DEFAULT_MAX_AGE_SECONDS = 86400  # 24 hours

def _now() -> str:
    return datetime.now(timezone.utc).isoformat()

def _projection_metadata(
    db_path: str | Path,
    *,
    max_age_seconds: int = DEFAULT_MAX_AGE_SECONDS,
    refresh_status: str | None = None,
    refresh_error: str | None = None,
    last_refresh_attempt_at: str | None = None,
    last_success_at: str | None = None,
    applied_at: str | None = None,
) -> dict[str, Any]:
    """Delegate to shared ops.projection_meta (single status logic)."""
    from ops.projection_meta import build_projection_metadata

    return build_projection_metadata(
        db_path,
        max_age_seconds=max_age_seconds,
        refresh_status=refresh_status,
        refresh_error=refresh_error,
        last_refresh_attempt_at=last_refresh_attempt_at,
        last_success_at=last_success_at,
        applied_at=applied_at,
        publisher="scripts/export_ops_projection.py",
    )

def _source_inventory(
    db_path: str | Path,
) -> list[dict[str, Any]]:
    """Canonical endpoint inventory for Ops projection (all known endpoints)."""
    import json
    from data_contracts.canonical import CANONICAL_REGISTRY_PATH, all_canonical_datasets
    from data_contracts.loader import all_contracts

    path_by_id: dict[str, str] = {}
    for c in all_contracts():
        path = getattr(c, "path", None)
        if path:
            path_by_id[c.dataset_id] = str(path)

    try:
        canonical_json = json.loads(CANONICAL_REGISTRY_PATH.read_text(encoding="utf-8"))
        datasets = {d["dataset_id"]: d for d in canonical_json.get("datasets", [])}
    except Exception:
        datasets = {}

    inventory = []
    for contract in all_canonical_datasets():
        entry = datasets.get(contract.dataset_id, {})
        sla = dict(entry.get("sla") or {})
        # Surface actual upstream locator in sla JSON (no D1 schema change).
        upstream = (
            entry.get("path")
            or entry.get("index_url")
            or entry.get("source_product")
            or path_by_id.get(contract.dataset_id)
        )
        if upstream:
            sla["upstream_locator"] = upstream
        if path_by_id.get(contract.dataset_id):
            sla["jq_path"] = path_by_id[contract.dataset_id]
        inv_status = entry.get("inventory_status")
        if not inv_status:
            inv_status = (
                "GOVERNED" if contract.governance_tier == "governed" else "EXPERIMENTAL"
            )
        inventory.append({
            "dataset_id": contract.dataset_id,
            "display_name": contract.display_name,
            "source": contract.source,
            "governance_tier": contract.governance_tier,
            "inventory_status": inv_status,
            "collection_window": entry.get("collection_window", "full_day"),
            "expected_frequency": contract.expected_frequency,
            "coverage_segment_granularity": contract.coverage_segment_granularity,
            "research_eligible": bool(entry.get("research_eligible", True)),
            "enabled": bool(entry.get("enabled", True)),
            "sla": json.dumps(sla, sort_keys=True, separators=(",", ":")),
            "historical_start": contract.historical_start,
        })
    return inventory

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
    statements = []
    for row in rows:
        values = ",".join(_sql_literal(row.get(column)) for column in columns)
        statements.append(f"INSERT INTO {table} ({names}) VALUES ({values});")
    return statements

def _read_rows(
    conn: sqlite3.Connection, table: str, columns: Sequence[str]
) -> list[dict[str, Any]]:
    conn.row_factory = sqlite3.Row
    order = "dataset" if table == "dataset_coverage" else "dataset,segment_start,segment_id"
    cursor = conn.execute(
        f"SELECT {','.join(columns)} FROM {table} ORDER BY {order}"
    )
    return [dict(row) for row in cursor.fetchall()]

def _read_latest_b0(conn: sqlite3.Connection) -> dict[str, Any] | None:
    try:
        row = conn.execute(
            "SELECT build_id,status,policy_version,evaluated_at,summary_json "
            "FROM snapshot_quality_results ORDER BY evaluated_at DESC LIMIT 1"
        ).fetchone()
    except sqlite3.OperationalError as exc:
        if "no such table" in str(exc).lower():
            return None
        raise
    if row is None:
        return None
    return {
        "singleton": 1,
        "status": row["status"],
        "policy_version": row["policy_version"],
        "evaluated_at": row["evaluated_at"],
        "summary_json": row["summary_json"],
        "source_build_id": row["build_id"],
    }

def render_projection_sql(
    db_path: str | Path,
    *,
    snapshot_dir: str | Path | None = None,
    max_age_seconds: int = DEFAULT_MAX_AGE_SECONDS,
    use_sql_transaction: bool = True,
    generation_id: str | None = None,
    producer_commit_sha: str | None = None,
) -> str:
    """Return a complete replaceable projection transaction.

    Phase 6.2.3: one generation_id tags every projected row; active pointer
    flips only after the full insert set is present (atomic generation).
    """
    from uuid import uuid4
    import hashlib
    import subprocess

    path = Path(db_path).resolve()
    gen_id = generation_id or ("projgen-" + uuid4().hex)
    commit_sha = producer_commit_sha
    if not commit_sha:
        try:
            commit_sha = subprocess.check_output(
                ["git", "rev-parse", "HEAD"],
                cwd=str(ROOT),
                text=True,
                stderr=subprocess.DEVNULL,
            ).strip()
        except Exception:  # noqa: BLE001
            commit_sha = None

    conn = sqlite3.connect("file:" + quote(str(path)) + "?mode=ro", uri=True)
    try:
        coverage = _read_rows(conn, "dataset_coverage", DATASET_COVERAGE_COLUMNS)
        segments = _read_rows(conn, "coverage_segments", COVERAGE_SEGMENT_COLUMNS)
        b0_status = _read_latest_b0(conn)
        metadata = _projection_metadata(db_path, max_age_seconds=max_age_seconds)
        inventory = _source_inventory(db_path)
    finally:
        conn.close()

    # Tag every row with the generation id for mixed-generation detection.
    for row in coverage:
        row["projection_generation_id"] = gen_id
    for row in segments:
        row["projection_generation_id"] = gen_id
    if b0_status is not None:
        b0_status = dict(b0_status)
        b0_status["projection_generation_id"] = gen_id

    metadata = dict(metadata)
    metadata["projection_generation_id"] = gen_id
    metadata["active_generation"] = gen_id
    metadata["producer_commit_sha"] = commit_sha
    # Digest over row counts for integrity of this generation.
    source_digest = "sha256:" + hashlib.sha256(
        json.dumps(
            {
                "coverage": len(coverage),
                "segments": len(segments),
                "inventory": len(inventory),
                "gen": gen_id,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()
    metadata.setdefault("detail_json", "{}")
    try:
        detail = json.loads(metadata["detail_json"]) if metadata.get("detail_json") else {}
    except json.JSONDecodeError:
        detail = {}
    detail["active_generation"] = gen_id
    detail["source_db_digest"] = source_digest
    metadata["detail_json"] = json.dumps(detail, sort_keys=True, separators=(",", ":"))

    ENDPOINT_INVENTORY_COLUMNS = (
        "dataset_id", "display_name", "source", "governance_tier",
        "inventory_status", "collection_window", "expected_frequency",
        "coverage_segment_granularity", "research_eligible", "enabled",
        "sla", "historical_start",
    )
    PROJECTION_METADATA_COLUMNS = (
        "generated_at", "source_generation", "age_seconds", "status",
        "projection_version", "detail_json", "projection_generation_id",
    )
    COVERAGE_COLS = DATASET_COVERAGE_COLUMNS + ("projection_generation_id",)
    SEGMENT_COLS = COVERAGE_SEGMENT_COLUMNS + ("projection_generation_id",)

    generated_at = metadata.get("generated_at") or _now()
    # Ensure generation tables exist (local test DBs / pre-migration remotes).
    ddl = [
        """CREATE TABLE IF NOT EXISTS ops_projection_generation (
            generation_id TEXT PRIMARY KEY,
            status TEXT NOT NULL,
            source_db_digest TEXT,
            generated_at TEXT NOT NULL,
            producer_commit_sha TEXT,
            contract_digest TEXT,
            registry_digest TEXT,
            coverage_policy_version TEXT,
            activated_at TEXT,
            detail_json TEXT NOT NULL DEFAULT '{}'
        );""",
        """CREATE TABLE IF NOT EXISTS ops_projection_active (
            singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
            generation_id TEXT NOT NULL,
            activated_at TEXT NOT NULL
        );""",
    ]
    # Schema patches live in migrations (0004_projection_generation.sql).
    # Do NOT emit ALTER TABLE ADD COLUMN here: wrangler d1 execute fails the
    # entire import on "duplicate column name" when re-applying a projection.
    statements = (["BEGIN TRANSACTION;"] if use_sql_transaction else []) + ddl + [
        # Stage generation record before bulk replace.
        (
            "INSERT OR REPLACE INTO ops_projection_generation "
            "(generation_id, status, source_db_digest, generated_at, "
            "producer_commit_sha, contract_digest, registry_digest, "
            "coverage_policy_version, activated_at, detail_json) VALUES ("
            f"{_sql_literal(gen_id)}, 'STAGING', {_sql_literal(source_digest)}, "
            f"{_sql_literal(generated_at)}, {_sql_literal(commit_sha)}, NULL, NULL, NULL, "
            "NULL, '{}');"
        ),
        "DELETE FROM dataset_coverage;",
        "DELETE FROM coverage_segments;",
        "DELETE FROM ops_snapshot_quality;",
        "DELETE FROM ops_ready_snapshots;",
        "DELETE FROM ops_b0_status;",
        "DELETE FROM ops_projection_metadata;",
        "DELETE FROM endpoint_inventory;",
    ]
    # Insert projection metadata first
    statements.extend(_insert_sql(
        "ops_projection_metadata", PROJECTION_METADATA_COLUMNS, [metadata]
    ))

    # Insert endpoint inventory
    statements.extend(_insert_sql(
        "endpoint_inventory", ENDPOINT_INVENTORY_COLUMNS, inventory
    ))

    statements.extend(_insert_sql(
        "dataset_coverage", COVERAGE_COLS, coverage
    ))
    statements.extend(_insert_sql(
        "coverage_segments", SEGMENT_COLS, segments
    ))
    if b0_status is not None:
        b0_cols = tuple(b0_status.keys())
        statements.extend(_insert_sql(
            "ops_b0_status", b0_cols, (b0_status,)
        ))

    if snapshot_dir is not None:
        try:
            snapshot = latest_ready_snapshot(snapshot_dir)
        except FileNotFoundError:
            snapshot = None
        if snapshot is not None:
            manifest = snapshot.manifest
            proof = manifest.get("coverage_v2_proof") or {}
            quality = manifest.get("quality") or {}
            source_run = manifest.get("source_run") or {}
            ready_row = {
                "snapshot_id": snapshot.snapshot_id,
                "state": "READY",
                "committed_at": manifest.get("committed_at"),
                "source_run_id": source_run.get("id"),
                "change_seq": int(manifest.get("change_seq", 0)),
                "coverage_policy_version": manifest.get("coverage_policy_version"),
                "quality_policy_version": manifest.get("quality_policy_version"),
                "coverage_proof_digest": proof.get("proof_digest"),
            }
            quality_row = {
                "snapshot_id": snapshot.snapshot_id,
                "status": quality.get("status", "UNKNOWN"),
                "policy_version": manifest.get("quality_policy_version"),
                "evaluated_at": quality.get("evaluated_at") or manifest.get("committed_at"),
                "summary_json": json.dumps(
                    quality.get("summary", {}), sort_keys=True, separators=(",", ":")
                ),
                "projection_generation_id": gen_id,
            }
            ready_row["projection_generation_id"] = gen_id
            statements.extend(_insert_sql(
                "ops_ready_snapshots",
                tuple(ready_row),
                (ready_row,),
            ))
            statements.extend(_insert_sql(
                "ops_snapshot_quality",
                tuple(quality_row),
                (quality_row,),
            ))
    # Atomic activation: only after full bulk insert.
    statements.append(
        "UPDATE ops_projection_generation SET status='ACTIVE', "
        f"activated_at={_sql_literal(generated_at)} "
        f"WHERE generation_id={_sql_literal(gen_id)};"
    )
    statements.append(
        "INSERT OR REPLACE INTO ops_projection_active "
        f"(singleton, generation_id, activated_at) VALUES (1, {_sql_literal(gen_id)}, "
        f"{_sql_literal(generated_at)});"
    )
    if use_sql_transaction:
        statements.append("COMMIT;")
    return "\n".join(statements) + "\n"

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        epilog="Phase 6.2 Residual: Automated projection with metadata freshness tracking."
    )
    parser.add_argument("--db", required=True, help="validated local control SQLite")
    parser.add_argument("--snapshot-dir", default=None, help="READY snapshot directory")
    parser.add_argument("--output", default=None, help="output SQL path (default stdout)")
    parser.add_argument(
        "--max-age-seconds", type=int, default=DEFAULT_MAX_AGE_SECONDS,
        help=f"maximum age for fresh projection (default {DEFAULT_MAX_AGE_SECONDS})"
    )
    parser.add_argument(
        "--auto-deploy", action="store_true",
        help="if wrangler credentials are available, automatically deploy to D1"
    )
    args = parser.parse_args(argv)

    rendered = render_projection_sql(
        args.db,
        snapshot_dir=args.snapshot_dir,
        max_age_seconds=args.max_age_seconds,
    )

    if args.output:
        Path(args.output).write_text(rendered, encoding="utf-8")
        print(f"Projection SQL written to {args.output}", file=sys.stderr)

        # Auto-deploy if requested and wrangler is available
        if args.auto_deploy:
            try:
                import subprocess
                result = subprocess.run(
                    ["wrangler", "d1", "execute", "quant-ops", "--local", "--command", rendered],
                    capture_output=True, text=True, timeout=300,
                )
                if result.returncode == 0:
                    print("Auto-deployed to local D1", file=sys.stderr)
                    return 0
                else:
                    print(f"Auto-deploy failed: {result.stderr}", file=sys.stderr)
                    return 1
            except FileNotFoundError:
                print("wrangler CLI not found, skipping auto-deploy", file=sys.stderr)
                return 0
            except Exception as e:
                print(f"Auto-deploy error: {e}", file=sys.stderr)
                return 1
    else:
        sys.stdout.write(rendered)

    return 0

if __name__ == "__main__":
    raise SystemExit(main())
