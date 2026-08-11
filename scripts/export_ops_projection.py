#!/usr/bin/env python3
"""Render a verified local Ops/READY control projection as D1 SQL.

The output is applied out-of-band with ``wrangler d1 execute``. The remote MCP
never receives a projection-write capability.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sqlite3
import sys
from typing import Any, Iterable, Mapping, Sequence
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from paper_runtime import latest_ready_snapshot  # noqa: E402


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
) -> str:
    """Return a complete replaceable projection transaction."""
    path = Path(db_path).resolve()
    conn = sqlite3.connect("file:" + quote(str(path)) + "?mode=ro", uri=True)
    try:
        coverage = _read_rows(conn, "dataset_coverage", DATASET_COVERAGE_COLUMNS)
        segments = _read_rows(conn, "coverage_segments", COVERAGE_SEGMENT_COLUMNS)
        b0_status = _read_latest_b0(conn)
    finally:
        conn.close()

    statements = [
        "BEGIN TRANSACTION;",
        "DELETE FROM dataset_coverage;",
        "DELETE FROM coverage_segments;",
        "DELETE FROM ops_snapshot_quality;",
        "DELETE FROM ops_ready_snapshots;",
        "DELETE FROM ops_b0_status;",
    ]
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
    statements.append("COMMIT;")
    return "\n".join(statements) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", required=True, help="validated local control SQLite")
    parser.add_argument("--snapshot-dir", default=None)
    parser.add_argument("--output", default=None, help="output SQL path (default stdout)")
    args = parser.parse_args(argv)
    rendered = render_projection_sql(args.db, snapshot_dir=args.snapshot_dir)
    if args.output:
        Path(args.output).write_text(rendered, encoding="utf-8")
    else:
        sys.stdout.write(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
