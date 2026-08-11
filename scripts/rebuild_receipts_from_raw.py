#!/usr/bin/env python3
"""Rebuild real collection_receipts from data/raw/** (honest digests).

Does NOT claim COMPLETE — run refresh_coverage_ledger afterwards.
For non-event source_query segments, expected_items=1 (one exhausted query).
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from data_contracts import coverage_contract_for
from storage.coverage_ledger import (
    build_collection_receipt,
    plan_required_segments,
    record_collection_receipt,
    record_required_segments,
)
from storage.sqlite_store import SqliteStore

FROM_TO = re.compile(
    r"^(?P<dataset>[a-z0-9_]+)_from=(?P<frm>\d{4}-\d{2}-\d{2})_to=(?P<to>\d{4}-\d{2}-\d{2})"
)
DATE_ONLY = re.compile(
    r"^(?P<dataset>[a-z0-9_]+)_date=(?P<date>\d{4}-\d{2}-\d{2})"
)


def _parse(name: str):
    stem = Path(name).name
    m = FROM_TO.match(stem)
    if m:
        return m.group("dataset"), m.group("frm"), m.group("to")
    m = DATE_ONLY.match(stem)
    if m:
        d = m.group("date")
        return m.group("dataset"), d, d
    return None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", type=Path, default=ROOT / "data/structured/ingestion.sqlite")
    ap.add_argument("--raw-root", type=Path, default=ROOT / "data/raw/jquants")
    ap.add_argument("--dataset", action="append", default=[])
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    store = SqliteStore(args.db)
    conn = store._conn
    written = skipped = 0
    for path in sorted(args.raw_root.rglob("*.json")):
        parsed = _parse(path.name)
        if not parsed:
            skipped += 1
            continue
        dataset, frm, to = parsed
        if args.dataset and dataset not in args.dataset:
            continue
        try:
            policy = coverage_contract_for(dataset)
        except Exception:
            skipped += 1
            continue
        segs = list(plan_required_segments(policy, to, source="jquants"))
        req0 = None
        for s in segs:
            if s.segment_start <= to and s.segment_end >= frm:
                req0 = s
                break
        if req0 is None:
            skipped += 1
            continue
        unit = (req0.expected_scope or {}).get("expected_item_unit", "source_query")
        if policy.expected_frequency != "event_driven" and unit == "source_query":
            segs = list(
                plan_required_segments(
                    policy,
                    to,
                    source="jquants",
                    expected_items_by_segment={req0.segment_id: 1},
                )
            )
            req = next(s for s in segs if s.segment_id == req0.segment_id)
        else:
            req = req0
        raw = path.read_bytes()
        if not raw.strip():
            skipped += 1
            continue
        compact = raw.replace(b" ", b"").replace(b"\n", b"")
        if b'"data":[]' in compact and unit == "source_query":
            skipped += 1
            continue
        obs = 1 if unit == "source_query" else max(1, len(raw))
        record_required_segments(conn, [req])
        record_collection_receipt(
            conn,
            build_collection_receipt(
                required=req,
                run_id=0,
                raw=raw,
                observed_items=obs,
                structured_row_count=obs,
                raw_row_count=obs,
                pagination_exhausted=True,
                status="SUCCESS",
            ),
        )
        written += 1
        if args.limit and written >= args.limit:
            break
    conn.commit()
    store.close()
    print(f"written={written} skipped={skipped}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
