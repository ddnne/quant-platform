#!/usr/bin/env python3
"""Render a verified local Ops/READY control projection as D1 SQL.

The output is applied out-of-band with ``wrangler d1 execute``. The remote MCP
never receives a projection-write capability.

Phase 6.2 Residual: Added projection metadata with generated_at, source_generation,
age, and status fields to prevent stale data from appearing fresh.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sqlite3
import sys
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping, Sequence
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from paper_runtime import latest_ready_snapshot  # noqa: E402


PROJECTION_VERSION = "ops_projection/v1"
DEFAULT_MAX_AGE_SECONDS = 86400  # 24 hours


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _projection_metadata(
    db_path: str | Path,
    *,
    max_age_seconds: int = DEFAULT_MAX_AGE_SECONDS,
) -> dict[str, Any]:
    """Generate projection metadata with generated_at, source_generation, age, status."""
    path = Path(db_path).resolve()
    conn = sqlite3.connect("file:" + quote(str(path)) + "?mode=ro", uri=True)
    try:
        # Get latest source generation from change log or coverage evaluation
        try:
            row = conn.execute(
                "SELECT MAX(evaluated_at) AS latest_evaluated FROM dataset_coverage"
            ).fetchone()
            source_generation = row[0] if row and row[0] else None
        except sqlite3.OperationalError:
            source_generation = None

        # Calculate age
        generated_at = _now()
        age_seconds = None
        status = "UNKNOWN"

        if source_generation:
            try:
                source_dt = datetime.fromisoformat(source_generation)
                generated_dt = datetime.fromisoformat(generated_at)
                age_seconds = int((generated_dt - source_dt).total_seconds())

                if age_seconds <= max_age_seconds:
                    status = "FRESH"
                else:
                    status = "STALE"
            except (ValueError, TypeError):
                status = "FAILED"
        else:
            status = "FAILED"

        return {
            "generated_at": generated_at,
            "source_generation": source_generation,
            "age_seconds": age_seconds,
            "status": status,
            "projection_version": PROJECTION_VERSION,
            "detail_json": json.dumps({
                "max_age_seconds": max_age_seconds,
                "calculation": "age = generated_at - MAX(dataset_coverage.evaluated_at)",
            }, sort_keys=True, separators=(",", ":")),
        }
    finally:
        conn.close()


def _source_inventory(
    db_path: str | Path,
) -> list[dict[str, Any]]:
    """Read canonical endpoint inventory from local DB."""
    from data_contracts.canonical import all_canonical_datasets  # noqa: E402
    from data_contracts.loader import all_contracts  # noqa: E402

    # Map canonical contracts to inventory format
    inventory = []
    for contract in all_canonical_datasets():
        # Get inventory status from canonical_datasets.json if available
        try:
            import json
            from data_contracts.canonical import CANONICAL_REGISTRY_PATH
            canonical_json = json.loads(CANONICAL_REGISTRY_PATH.read_text(encoding="utf-8"))
            datasets = canonical_json.get("datasets", [])
            dataset_entry = next(
                (d for d in datasets if d["dataset_id"] == contract.dataset_id),
                None
            )
            if dataset_entry:
                sla = dataset_entry.get("sla", {})
                inventory_entry = {
                    "dataset_id": contract.dataset_id,
                    "display_name": contract.display_name,
                    "source": contract.source,
                    "governance_tier": contract.governance_tier,
                    "inventory_status": dataset_entry.get("inventory_status", (
                        "GOVERNED" if contract.governance_tier == "governed" else "EXPERIMENTAL"
                    )),
                    "collection_window": dataset_entry.get("collection_window", "full_day"),
                    "expected_frequency": contract.expected_frequency,
                    "coverage_segment_granularity": contract.coverage_segment_granularity,
                    "research_eligible": dataset_entry.get("research_eligible", True),
                    "enabled": dataset_entry.get("enabled", True),
                    "sla": json.dumps(sla, sort_keys=True, separators=(",", ":")),
                    "historical_start": contract.historical_start,
                }
                inventory.append(inventory_entry)
        except Exception:
            # Fallback to basic contract info
            inventory.append({
                "dataset_id": contract.dataset_id,
                "display_name": contract.display_name,
                "source": contract.source,
                "governance_tier": contract.governance_tier,
                "inventory_status": "GOVERNED" if contract.governance_tier == "governed" else "EXPERIMENTAL",
                "collection_window": "full_day",
                "expected_frequency": contract.expected_frequency,
                "coverage_segment_granularity": contract.coverage_segment_granularity,
                "research_eligible": True,
                "enabled": True,
                "sla": "{}",
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
) -> str:
    """Return a complete replaceable projection transaction."""
    path = Path(db_path).resolve()
    conn = sqlite3.connect("file:" + quote(str(path)) + "?mode=ro", uri=True)
    try:
        coverage = _read_rows(conn, "dataset_coverage", DATASET_COVERAGE_COLUMNS)
        segments = _read_rows(conn, "coverage_segments", COVERAGE_SEGMENT_COLUMNS)
        b0_status = _read_latest_b0(conn)
        metadata = _projection_metadata(db_path, max_age_seconds=max_age_seconds)
        inventory = _source_inventory(db_path)
    finally:
        conn.close()

    ENDPOINT_INVENTORY_COLUMNS = (
        "dataset_id", "display_name", "source", "governance_tier",
        "inventory_status", "collection_window", "expected_frequency",
        "coverage_segment_granularity", "research_eligible", "enabled",
        "sla", "historical_start",
    )
    PROJECTION_METADATA_COLUMNS = (
        "generated_at", "source_generation", "age_seconds", "status",
        "projection_version", "detail_json",
    )

    statements = (["BEGIN TRANSACTION;"] if use_sql_transaction else []) + [
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
        "dataset_coverage", DATASET_COVERAGE_COLUMNS, coverage
    ))
    statements.extend(_insert_sql(
        "coverage_segments", COVERAGE_SEGMENT_COLUMNS, segments
    ))
    if b0_status is not None:
        statements.extend(_insert_sql(
            "ops_b0_status", tuple(b0_status), (b0_status,)
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
            }
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
