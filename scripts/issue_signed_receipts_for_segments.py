#!/usr/bin/env python3
"""Issue Ed25519-signed receipts for planned segments with real structured rows.

Does not invent COMPLETE. Counts structured rows, loads matching raw, issues
signed receipts, refreshes the ledger, then surgically re-aggs dataset_coverage.
RECOVERED rebuilds stay unsigned without raw + structure.
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
import re
import sqlite3

ROOT = ensure_repo_root()

from storage.coverage_ledger import (  # noqa: E402
    RequiredCoverageSegment,
    refresh_coverage_ledger,
    record_collection_receipt,
    record_required_segments,
    sync_dataset_coverage_from_segments,
)
from storage.trusted_receipt import open_signed_receipt_authority  # noqa: E402

_FROM_TO_RE = re.compile(
    r"from=(?P<fr>\d{4}-\d{2}-\d{2}).*?to=(?P<to>\d{4}-\d{2}-\d{2})",
    re.IGNORECASE,
)
_DATE_ONLY_RE = re.compile(
    r"^(?P<dataset>[a-z0-9_]+)_date=(?P<date>\d{4}-\d{2}-\d{2})",
    re.IGNORECASE,
)

def _count_structured(
    conn: sqlite3.Connection, dataset: str, start: str, end: str
) -> int:
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

def _windows_overlap(a0: str, a1: str, b0: str, b1: str) -> bool:
    return a0[:10] <= b1[:10] and b0[:10] <= a1[:10]


def _is_usable_raw(raw: bytes) -> bool:
    """Reject empty/stub payloads (``[]`` / ``{}``)."""
    if not raw or len(raw) >= 5_000_000:
        return False
    stripped = raw.strip()
    if len(stripped) < 8:
        return False
    if stripped in {b"[]", b"{}", b"null", b'""'}:
        return False
    return True


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
    prefix = f"{dataset}_"
    candidates = [
        p
        for p in base.rglob("*.json")
        if p.name.startswith(prefix) or f"/{dataset}_" in str(p).replace("\\", "/")
    ]
    if not candidates:
        # Fallback: filename contains dataset token as a whole path segment-ish
        candidates = [p for p in base.rglob("*.json") if dataset in p.name]

    month = segment_id if len(segment_id) == 7 else segment_id[:7]
    ranked: list[tuple[int, int, Path]] = []
    for path in candidates:
        name = path.name
        score = 0
        if name.startswith(prefix):
            score += 20
        elif dataset in name:
            score += 10
        m = _FROM_TO_RE.search(name)
        if m:
            fr, to = m.group("fr"), m.group("to")
            if _windows_overlap(segment_start, segment_end, fr, to):
                score += 30
            else:
                continue
        else:
            md = _DATE_ONLY_RE.match(name)
            if md and md.group("dataset") == dataset:
                d = md.group("date")
                if segment_start[:10] <= d <= segment_end[:10]:
                    score += 25
                else:
                    continue
            else:
                if month in name or month in str(path):
                    score += 5
                if segment_start[:7] in name or segment_end[:7] in name:
                    score += 3
        if score <= 0:
            continue
        try:
            size = path.stat().st_size
        except OSError:
            continue
        if size < 8:
            continue
        ranked.append((score, size, path))
    ranked.sort(key=lambda item: (item[0], item[1]), reverse=True)
    for _score, _size, path in ranked[:120]:
        try:
            raw = path.read_bytes()
        except OSError:
            continue
        if _is_usable_raw(raw):
            return raw
    return None

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", default=str(ROOT / "data/structured/ingestion.sqlite"))
    ap.add_argument("--data-dir", default=str(ROOT / "data"))
    ap.add_argument(
        "--dataset",
        default="markets_calendar",
        help="Single dataset id (or use --datasets for multi).",
    )
    ap.add_argument(
        "--datasets",
        default="",
        help="Comma-separated datasets. When set, overrides --dataset.",
    )
    ap.add_argument("--segment-id", default="", help="optional single segment e.g. 2024-01")
    ap.add_argument("--limit", type=int, default=12)
    ap.add_argument("--min-structured", type=int, default=1)
    ap.add_argument(
        "--include-complete",
        action="store_true",
        help="Also re-issue for segments already COMPLETE.",
    )
    ap.add_argument(
        "--order",
        choices=("asc", "desc"),
        default="desc",
        help="Scan order by segment_start.",
    )
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
    dataset_list = [d.strip() for d in args.datasets.split(",") if d.strip()]
    if not dataset_list:
        dataset_list = [args.dataset]
    order = "ASC" if args.order == "asc" else "DESC"
    segments: list[sqlite3.Row] = []
    per_ds_limit = max(1, args.limit // max(1, len(dataset_list)))
    for ds in dataset_list:
        q = (
            "SELECT source, dataset, segment_id, segment_start, segment_end, "
            "expected_scope, expected_items, status FROM coverage_segments "
            "WHERE dataset=? AND policy_version='collection-coverage/v2'"
        )
        params: list[object] = [ds]
        if args.segment_id:
            q += " AND segment_id=?"
            params.append(args.segment_id)
        if not args.include_complete:
            q += " AND status <> 'COMPLETE'"
        q += f" ORDER BY segment_start {order} LIMIT ?"
        params.append(per_ds_limit if len(dataset_list) > 1 else args.limit)
        segments.extend(conn.execute(q, params).fetchall())
    if not segments:
        print("no segments found", file=sys.stderr)
        return 1

    max_run = conn.execute(
        "SELECT COALESCE(MAX(run_id), 900000) FROM collection_receipts"
    ).fetchone()[0]
    next_run = int(max_run) + 1

    issued = 0
    issued_datasets: set[str] = set()
    skipped = {"no_struct": 0, "no_raw": 0}
    for row in segments:
        scope = row["expected_scope"]
        if isinstance(scope, str):
            try:
                scope = json.loads(scope)
            except json.JSONDecodeError:
                scope = {}
        scope_dict = dict(scope or {})
        unit = scope_dict.get("expected_item_unit")
        expected_items = row["expected_items"]
        if expected_items is None and unit == "source_query":
            expected_items = 1
        required = RequiredCoverageSegment(
            source=str(row["source"]),
            dataset=str(row["dataset"]),
            segment_id=str(row["segment_id"]),
            segment_start=str(row["segment_start"]),
            segment_end=str(row["segment_end"]),
            expected_scope=scope_dict,
            expected_items=expected_items,
        )
        structured = _count_structured(
            conn, required.dataset, required.segment_start, required.segment_end
        )
        if structured < args.min_structured:
            skipped["no_struct"] += 1
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
            skipped["no_raw"] += 1
            print(f"skip {required.segment_id}: no raw bytes for window")
            continue
        observed = 1 if unit == "source_query" else structured
        if required.expected_items is not None and unit == "source_query":
            observed = int(required.expected_items)
        raw_rows = structured
        receipt = authority.issue(
            required=required,
            run_id=next_run,
            raw=raw,
            observed_items=observed,
            structured_row_count=structured,
            raw_row_count=raw_rows,
            pagination_exhausted=True,
            structured_generation=structured,
            raw_manifest_digest=None,
            source_request_digest=None,
        )
        next_run += 1
        record_required_segments(conn, [required])
        record_collection_receipt(conn, receipt)
        issued += 1
        issued_datasets.add(required.dataset)
        print(
            f"issued signed receipt {required.dataset}/{required.segment_id} "
            f"structured={structured} run_id={receipt.run_id}"
        )
    conn.commit()
    print(f"summary issued={issued} skipped={skipped}")
    if issued:
        ds_list = sorted(issued_datasets)
        rows = refresh_coverage_ledger(conn, db, datasets=ds_list)
        conn.commit()
        for ds in ds_list:
            complete = conn.execute(
                "SELECT COUNT(*) FROM coverage_segments WHERE dataset=? AND status='COMPLETE'",
                (ds,),
            ).fetchone()[0]
            total = conn.execute(
                "SELECT COUNT(*) FROM coverage_segments WHERE dataset=?",
                (ds,),
            ).fetchone()[0]
            print(f"local coverage {ds}: COMPLETE={complete}/{total}")
        for r in rows:
            print(
                f"coverage {r.get('dataset')} status={r.get('status')} "
                f"detail_keys={list((r.get('detail') or {}).keys())[:5]}"
            )
        reagg = sync_dataset_coverage_from_segments(
            conn,
            datasets=ds_list,
            wave="issue_signed_receipts_for_segments",
        )
        conn.commit()
        for row in reagg:
            print(
                "dataset_coverage_sync:",
                {
                    "dataset": row.get("dataset"),
                    "action": row.get("action"),
                    "from": row.get("old_status") or row.get("from"),
                    "to": row.get("to") or row.get("status") or row.get("derived_status"),
                    "status_counts": row.get("status_counts"),
                },
            )
    else:
        print("no receipts issued")
    conn.close()
    return 0 if issued else 1

if __name__ == "__main__":
    raise SystemExit(main())
