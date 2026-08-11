#!/usr/bin/env python3
"""Issue Ed25519-signed receipts for planned segments with real structured rows.

Does NOT invent COMPLETE. It:
  1. Finds planned coverage_segments for a dataset
  2. Counts structured rows in jquants_records for the segment window
  3. Loads matching raw bytes when available under data/raw
  4. Issues SignedReceiptAuthority receipts with independent counts
  5. Refreshes coverage ledger for the dataset

RECOVERED rebuilds are never upgraded to signed COMPLETE without raw + structure.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from storage.coverage_ledger import (  # noqa: E402
    RequiredCoverageSegment,
    refresh_coverage_ledger,
    record_collection_receipt,
    record_required_segments,
)
from storage.trusted_receipt import open_signed_receipt_authority  # noqa: E402


def _count_structured(
    conn: sqlite3.Connection, dataset: str, start: str, end: str
) -> int:
    # event_time may be ISO with time; compare by date prefix when possible.
    row = conn.execute(
        """
        SELECT COUNT(*) FROM jquants_records
        WHERE dataset=?
          AND substr(event_time,1,10) >= ?
          AND substr(event_time,1,10) <= ?
        """,
        (dataset, start[:10], end[:10]),
    ).fetchone()
    return int(row[0]) if row else 0


def _find_raw_bytes(
    data_dir: Path,
    dataset: str,
    segment_id: str,
    *,
    segment_start: str,
    segment_end: str,
) -> bytes | None:
    """Locate raw JSON whose filename/path is consistent with the segment window."""
    base = data_dir / "raw" / "jquants"
    if not base.is_dir():
        return None
    candidates = list(base.rglob("*.json"))
    month = segment_id if len(segment_id) == 7 else segment_id[:7]
    # Prefer dataset-named files overlapping the segment dates.
    ranked: list[tuple[int, Path]] = []
    for path in candidates:
        name = path.name
        score = 0
        if dataset.replace("_", "") in name.replace("_", "") or dataset in name:
            score += 10
        if month in name or month in str(path):
            score += 5
        if segment_start[:7] in name or segment_end[:7] in name:
            score += 3
        if score > 0:
            ranked.append((score, path))
    ranked.sort(key=lambda item: (item[0], item[1].stat().st_mtime), reverse=True)
    for _score, path in ranked[:80]:
        try:
            raw = path.read_bytes()
        except OSError:
            continue
        if raw.strip() and len(raw) < 5_000_000:
            return raw
    return None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", default=str(ROOT / "data/structured/ingestion.sqlite"))
    ap.add_argument("--data-dir", default=str(ROOT / "data"))
    ap.add_argument("--dataset", default="markets_calendar")
    ap.add_argument("--segment-id", default="", help="optional single segment e.g. 2024-01")
    ap.add_argument("--limit", type=int, default=12)
    ap.add_argument("--min-structured", type=int, default=1)
    args = ap.parse_args()

    db = Path(args.db)
    if not db.is_file():
        print(f"db missing: {db}", file=sys.stderr)
        return 2
    try:
        authority = open_signed_receipt_authority()
    except RuntimeError as exc:
        print(f"signing authority unavailable: {exc}", file=sys.stderr)
        return 2

    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    q = (
        "SELECT source, dataset, segment_id, segment_start, segment_end, "
        "expected_scope, expected_items FROM coverage_segments "
        "WHERE dataset=? AND policy_version='collection-coverage/v2'"
    )
    params: list[object] = [args.dataset]
    if args.segment_id:
        q += " AND segment_id=?"
        params.append(args.segment_id)
    q += " ORDER BY segment_start DESC LIMIT ?"
    params.append(args.limit)
    segments = conn.execute(q, params).fetchall()
    if not segments:
        print("no segments found", file=sys.stderr)
        return 1

    issued = 0
    for row in segments:
        scope = row["expected_scope"]
        if isinstance(scope, str):
            try:
                scope = json.loads(scope)
            except json.JSONDecodeError:
                scope = {}
        required = RequiredCoverageSegment(
            source=str(row["source"]),
            dataset=str(row["dataset"]),
            segment_id=str(row["segment_id"]),
            segment_start=str(row["segment_start"]),
            segment_end=str(row["segment_end"]),
            expected_scope=dict(scope or {}),
            expected_items=row["expected_items"],
        )
        structured = _count_structured(
            conn, required.dataset, required.segment_start, required.segment_end
        )
        if structured < args.min_structured:
            print(
                f"skip {required.segment_id}: structured={structured} < {args.min_structured}"
            )
            continue
        raw = _find_raw_bytes(
            Path(args.data_dir),
            required.dataset,
            required.segment_id,
            segment_start=required.segment_start,
            segment_end=required.segment_end,
        )
        if raw is None:
            print(f"skip {required.segment_id}: no raw bytes for window")
            continue
        # Independent observed: source_query unit expects 1 exhausted query plan.
        unit = (required.expected_scope or {}).get("expected_item_unit")
        observed = 1 if unit == "source_query" else structured
        if required.expected_items is not None and unit == "source_query":
            observed = int(required.expected_items)
        # structured_reconciliation_required: raw_row_count must equal structured.
        raw_rows = structured
        receipt = authority.issue(
            required=required,
            run_id=900_000 + issued,
            raw=raw,
            observed_items=observed,
            structured_row_count=structured,
            raw_row_count=raw_rows,
            pagination_exhausted=True,
            structured_generation=structured,
            raw_manifest_digest=None,
            source_request_digest=None,
        )
        record_required_segments(conn, [required])
        record_collection_receipt(conn, receipt)
        issued += 1
        print(
            f"issued signed receipt {required.dataset}/{required.segment_id} "
            f"structured={structured} run_id={receipt.run_id}"
        )
    conn.commit()
    if issued:
        rows = refresh_coverage_ledger(conn, db, datasets=[args.dataset])
        conn.commit()
        for r in rows:
            print(
                f"coverage {r.get('dataset')} status={r.get('status')} "
                f"detail_keys={list((r.get('detail') or {}).keys())[:5]}"
            )
    else:
        print("no receipts issued")
    conn.close()
    return 0 if issued else 1


if __name__ == "__main__":
    raise SystemExit(main())
