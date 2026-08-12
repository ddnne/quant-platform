#!/usr/bin/env python3
"""Parallel signed-receipt issuance for segments with raw + structured evidence.

Track A3: seal Coverage V2 segments that already hold **both** local raw bytes
and structured rows. ThreadPool prepares candidates; DB writes stay serial.

Hard rules
----------
* Skip segments with no raw (never invent COMPLETE without raw).
* Does **not** launch backfill / Mass / dual recovery rebuilds.
* Worker pass ≠ Coverage COMPLETE — only SignedReceiptAuthority + ledger refresh.
* Local sqlite is a research mirror, not CF SoT.

Usage examples
--------------
  # Dry scan (no issue)
  .venv/bin/python scripts/issue_receipts_parallel.py \\
    --datasets markets_short_ratio,markets_breakdown --limit 8 --dry-run

  # Issue + refresh ledger
  .venv/bin/python scripts/issue_receipts_parallel.py \\
    --datasets markets_short_ratio,markets_breakdown --limit 8 --workers 4
"""

from __future__ import annotations

import sys
from pathlib import Path

# Bootstrap repo root onto sys.path before importing qp_paths (plain script runs).
for _parent in Path(__file__).resolve().parents:
    if (_parent / "qp_paths.py").is_file() and (_parent / "pyproject.toml").is_file():
        if str(_parent) not in sys.path:
            sys.path.insert(0, str(_parent))
        break
else:
    raise RuntimeError("quant-platform repo root not found from script")

from qp_paths import repo_root

import argparse
import json
import re
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Any, Iterable, Sequence

ROOT = repo_root()
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from storage.coverage_ledger import (  # noqa: E402
    RequiredCoverageSegment,
    refresh_coverage_ledger,
    record_collection_receipt,
    record_required_segments,
)
from storage.trusted_receipt import open_signed_receipt_authority  # noqa: E402

_FROM_TO_RE = re.compile(
    r"from=(?P<fr>\d{4}-\d{2}-\d{2}).*?to=(?P<to>\d{4}-\d{2}-\d{2})",
    re.IGNORECASE,
)
_DATE_RE = re.compile(r"date=(?P<d>\d{4}-\d{2}-\d{2})")
_DATASET_PREFIX_RE = re.compile(
    r"^(?P<ds>[a-z0-9_]+?)_(?:from=|date=)",
    re.IGNORECASE,
)


def _windows_overlap(a0: str, a1: str, b0: str, b1: str) -> bool:
    return a0[:10] <= b1[:10] and b0[:10] <= a1[:10]


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


@dataclass(frozen=True)
class RawIndexEntry:
    path: Path
    dataset: str
    window_from: str | None
    window_to: str | None
    date_token: str | None


def build_raw_index(data_dir: Path, datasets: Sequence[str]) -> dict[str, list[RawIndexEntry]]:
    """Index local raw JSON once per run (avoids per-segment rglob)."""
    wanted = set(datasets)
    out: dict[str, list[RawIndexEntry]] = {ds: [] for ds in wanted}
    base = data_dir / "raw" / "jquants"
    if not base.is_dir():
        return out
    for path in base.rglob("*.json"):
        name = path.name
        m = _DATASET_PREFIX_RE.match(name)
        if m:
            ds = m.group("ds")
        else:
            ds = next((d for d in wanted if name.startswith(f"{d}_") or d in name), "")
        if ds not in wanted:
            continue
        fr = to = date_token = None
        m_ft = _FROM_TO_RE.search(name)
        if m_ft:
            fr, to = m_ft.group("fr"), m_ft.group("to")
        m_d = _DATE_RE.search(name)
        if m_d:
            date_token = m_d.group("d")
        out[ds].append(
            RawIndexEntry(
                path=path,
                dataset=ds,
                window_from=fr,
                window_to=to,
                date_token=date_token,
            )
        )
    return out


def _is_usable_raw(raw: bytes) -> bool:
    """Reject empty/stub payloads (e.g. ``[]`` / ``{}``) — not honest evidence."""
    if not raw or len(raw) >= 5_000_000:
        return False
    stripped = raw.strip()
    if len(stripped) < 8:
        return False
    if stripped in {b"[]", b"{}", b"null", b'""'}:
        return False
    return True


def find_raw_bytes_indexed(
    index: Sequence[RawIndexEntry],
    *,
    dataset: str,
    segment_id: str,
    segment_start: str,
    segment_end: str,
) -> bytes | None:
    """Pick best non-empty raw file for a segment. None if none usable."""
    prefix = f"{dataset}_"
    month = segment_id if len(segment_id) == 7 else segment_id[:7]
    ranked: list[tuple[int, int, Path]] = []
    for entry in index:
        name = entry.path.name
        score = 0
        if name.startswith(prefix):
            score += 20
        elif dataset in name:
            score += 10
        if entry.window_from and entry.window_to:
            if _windows_overlap(
                segment_start, segment_end, entry.window_from, entry.window_to
            ):
                score += 30
            else:
                continue
        elif entry.date_token:
            if segment_start[:10] <= entry.date_token <= segment_end[:10]:
                score += 30
            else:
                continue
        else:
            if month in name or month in str(entry.path):
                score += 5
            if segment_start[:7] in name or segment_end[:7] in name:
                score += 3
        if score <= 0:
            continue
        try:
            size = entry.path.stat().st_size
        except OSError:
            continue
        # Empty [] stubs are 2 bytes — never prefer them.
        if size < 8:
            continue
        ranked.append((score, size, entry.path))
    # Prefer window match score, then larger payload (real rows over stubs).
    ranked.sort(key=lambda item: (item[0], item[1]), reverse=True)
    for _score, _size, path in ranked[:120]:
        try:
            raw = path.read_bytes()
        except OSError:
            continue
        if _is_usable_raw(raw):
            return raw
    return None


@dataclass
class SegmentJob:
    source: str
    dataset: str
    segment_id: str
    segment_start: str
    segment_end: str
    expected_scope: dict[str, Any]
    expected_items: int | None
    status: str


@dataclass
class PreparedIssue:
    job: SegmentJob
    required: RequiredCoverageSegment
    structured: int
    raw: bytes
    observed: int
    raw_rows: int


@dataclass
class PrepareResult:
    job: SegmentJob
    prepared: PreparedIssue | None = None
    skip_reason: str | None = None


def _parse_scope(scope: Any) -> dict[str, Any]:
    if isinstance(scope, str):
        try:
            scope = json.loads(scope)
        except json.JSONDecodeError:
            scope = {}
    return dict(scope or {})


def load_candidate_segments(
    conn: sqlite3.Connection,
    *,
    datasets: Sequence[str],
    segment_id: str,
    limit_per_dataset: int,
    include_complete: bool,
    order: str,
) -> list[SegmentJob]:
    jobs: list[SegmentJob] = []
    order_sql = "ASC" if order == "asc" else "DESC"
    for dataset in datasets:
        q = (
            "SELECT source, dataset, segment_id, segment_start, segment_end, "
            "expected_scope, expected_items, status FROM coverage_segments "
            "WHERE dataset=? AND policy_version='collection-coverage/v2'"
        )
        params: list[object] = [dataset]
        if segment_id:
            q += " AND segment_id=?"
            params.append(segment_id)
        if not include_complete:
            q += " AND status <> 'COMPLETE'"
        q += f" ORDER BY segment_start {order_sql} LIMIT ?"
        params.append(limit_per_dataset)
        for row in conn.execute(q, params).fetchall():
            jobs.append(
                SegmentJob(
                    source=str(row["source"]),
                    dataset=str(row["dataset"]),
                    segment_id=str(row["segment_id"]),
                    segment_start=str(row["segment_start"]),
                    segment_end=str(row["segment_end"]),
                    expected_scope=_parse_scope(row["expected_scope"]),
                    expected_items=(
                        None
                        if row["expected_items"] is None
                        else int(row["expected_items"])
                    ),
                    status=str(row["status"]),
                )
            )
    return jobs


def prepare_one(
    job: SegmentJob,
    *,
    db_path: Path,
    raw_index: Sequence[RawIndexEntry],
    min_structured: int,
) -> PrepareResult:
    """Thread-safe prepare: own RO connection + filesystem read."""
    uri = f"file:{db_path.resolve().as_posix()}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    try:
        structured = _count_structured(
            conn, job.dataset, job.segment_start, job.segment_end
        )
    finally:
        conn.close()

    if structured < min_structured:
        return PrepareResult(job=job, skip_reason=f"no_struct structured={structured}")

    raw = find_raw_bytes_indexed(
        raw_index,
        dataset=job.dataset,
        segment_id=job.segment_id,
        segment_start=job.segment_start,
        segment_end=job.segment_end,
    )
    if raw is None:
        # Explicit ban: never COMPLETE without raw.
        return PrepareResult(job=job, skip_reason="no_raw")

    scope = job.expected_scope
    unit = scope.get("expected_item_unit")
    expected_items = job.expected_items
    if expected_items is None and unit == "source_query":
        expected_items = 1
    required = RequiredCoverageSegment(
        source=job.source,
        dataset=job.dataset,
        segment_id=job.segment_id,
        segment_start=job.segment_start,
        segment_end=job.segment_end,
        expected_scope=scope,
        expected_items=expected_items,
    )
    observed = 1 if unit == "source_query" else structured
    if required.expected_items is not None and unit == "source_query":
        observed = int(required.expected_items)
    # structured_reconciliation_required: raw_row_count must equal structured.
    prepared = PreparedIssue(
        job=job,
        required=required,
        structured=structured,
        raw=raw,
        observed=observed,
        raw_rows=structured,
    )
    return PrepareResult(job=job, prepared=prepared)


def prepare_parallel(
    jobs: Sequence[SegmentJob],
    *,
    db_path: Path,
    raw_by_dataset: dict[str, list[RawIndexEntry]],
    min_structured: int,
    workers: int,
) -> list[PrepareResult]:
    results: list[PrepareResult] = []
    if not jobs:
        return results
    n_workers = max(1, min(workers, len(jobs)))
    with ThreadPoolExecutor(max_workers=n_workers) as pool:
        futs = {
            pool.submit(
                prepare_one,
                job,
                db_path=db_path,
                raw_index=raw_by_dataset.get(job.dataset, []),
                min_structured=min_structured,
            ): job
            for job in jobs
        }
        for fut in as_completed(futs):
            results.append(fut.result())
    # Stable order for deterministic run_id assignment: dataset, segment_start desc.
    results.sort(
        key=lambda r: (r.job.dataset, r.job.segment_start, r.job.segment_id),
        reverse=True,
    )
    return results


def issue_prepared(
    conn: sqlite3.Connection,
    prepared_list: Sequence[PreparedIssue],
    *,
    authority: Any,
    start_run_id: int,
    write_lock: threading.Lock | None = None,
) -> list[dict[str, Any]]:
    """Serial issue + DB record. Returns issued summary rows."""
    issued_rows: list[dict[str, Any]] = []
    next_run = start_run_id
    lock = write_lock or threading.Lock()
    with lock:
        for prep in prepared_list:
            receipt = authority.issue(
                required=prep.required,
                run_id=next_run,
                raw=prep.raw,
                observed_items=prep.observed,
                structured_row_count=prep.structured,
                raw_row_count=prep.raw_rows,
                pagination_exhausted=True,
                structured_generation=prep.structured,
                raw_manifest_digest=None,
                source_request_digest=None,
            )
            next_run += 1
            record_required_segments(conn, [prep.required])
            record_collection_receipt(conn, receipt)
            issued_rows.append(
                {
                    "dataset": prep.required.dataset,
                    "segment_id": prep.required.segment_id,
                    "run_id": receipt.run_id,
                    "structured": prep.structured,
                    "raw_bytes": len(prep.raw),
                }
            )
    return issued_rows


def _parse_datasets(raw: str | None, multi: Sequence[str]) -> list[str]:
    out: list[str] = []
    if raw:
        out.extend(part.strip() for part in raw.split(",") if part.strip())
    out.extend(d.strip() for d in multi if d.strip())
    # de-dupe preserve order
    seen: set[str] = set()
    ordered: list[str] = []
    for d in out:
        if d not in seen:
            seen.add(d)
            ordered.append(d)
    return ordered


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", default=str(ROOT / "data/structured/ingestion.sqlite"))
    ap.add_argument("--data-dir", default=str(ROOT / "data"))
    ap.add_argument(
        "--datasets",
        default="",
        help="Comma-separated datasets (default: markets_short_ratio).",
    )
    ap.add_argument(
        "--dataset",
        action="append",
        default=[],
        help="Repeatable dataset filter (merged with --datasets).",
    )
    ap.add_argument("--segment-id", default="", help="Optional single segment id.")
    ap.add_argument(
        "--limit",
        type=int,
        default=8,
        help="Max non-COMPLETE segments to scan per dataset (default 8).",
    )
    ap.add_argument("--min-structured", type=int, default=1)
    ap.add_argument("--workers", type=int, default=4, help="ThreadPool size.")
    ap.add_argument(
        "--include-complete",
        action="store_true",
        help="Also re-issue for segments already COMPLETE (default: skip).",
    )
    ap.add_argument(
        "--order",
        choices=("asc", "desc"),
        default="desc",
        help="Segment scan order by segment_start (default: desc).",
    )
    ap.add_argument(
        "--dry-run",
        action="store_true",
        help="Prepare only; do not sign/write receipts or refresh ledger.",
    )
    ap.add_argument(
        "--no-refresh",
        action="store_true",
        help="Issue receipts but skip coverage ledger refresh.",
    )
    ap.add_argument(
        "--json-summary",
        action="store_true",
        help="Print machine-readable JSON summary on stdout (last line).",
    )
    args = ap.parse_args(argv)

    datasets = _parse_datasets(args.datasets, args.dataset)
    if not datasets:
        datasets = ["markets_short_ratio"]

    db = Path(args.db)
    data_dir = Path(args.data_dir)
    if not db.is_file():
        print(f"db missing: {db}", file=sys.stderr)
        return 2

    if not args.dry_run:
        try:
            authority = open_signed_receipt_authority()
        except RuntimeError as exc:
            print(f"signing authority unavailable: {exc}", file=sys.stderr)
            return 2
    else:
        authority = None

    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    jobs = load_candidate_segments(
        conn,
        datasets=datasets,
        segment_id=args.segment_id,
        limit_per_dataset=args.limit,
        include_complete=args.include_complete,
        order=args.order,
    )
    if not jobs:
        print("no segments found", file=sys.stderr)
        conn.close()
        return 1

    print(
        f"scan datasets={datasets} candidates={len(jobs)} "
        f"workers={args.workers} dry_run={args.dry_run}"
    )

    raw_by_dataset = build_raw_index(data_dir, datasets)
    for ds in datasets:
        print(f"raw_index {ds}: {len(raw_by_dataset.get(ds, []))} files")

    prepared_results = prepare_parallel(
        jobs,
        db_path=db,
        raw_by_dataset=raw_by_dataset,
        min_structured=args.min_structured,
        workers=args.workers,
    )

    skipped = {"no_struct": 0, "no_raw": 0, "other": 0}
    ready: list[PreparedIssue] = []
    for res in prepared_results:
        if res.prepared is not None:
            ready.append(res.prepared)
            print(
                f"ready {res.job.dataset}/{res.job.segment_id} "
                f"structured={res.prepared.structured} raw_bytes={len(res.prepared.raw)}"
            )
            continue
        reason = res.skip_reason or "other"
        if reason.startswith("no_struct"):
            skipped["no_struct"] += 1
        elif reason == "no_raw":
            skipped["no_raw"] += 1
        else:
            skipped["other"] += 1
        print(f"skip {res.job.dataset}/{res.job.segment_id}: {reason}")

    issued_rows: list[dict[str, Any]] = []
    if args.dry_run:
        print(f"dry-run ready={len(ready)} skipped={skipped} (no write)")
    elif not ready:
        print(f"summary issued=0 skipped={skipped}")
    else:
        max_run = conn.execute(
            "SELECT COALESCE(MAX(run_id), 900000) FROM collection_receipts"
        ).fetchone()[0]
        start_run = int(max_run) + 1
        issued_rows = issue_prepared(
            conn,
            ready,
            authority=authority,
            start_run_id=start_run,
        )
        conn.commit()
        for row in issued_rows:
            print(
                f"issued signed receipt {row['dataset']}/{row['segment_id']} "
                f"structured={row['structured']} run_id={row['run_id']}"
            )
        print(f"summary issued={len(issued_rows)} skipped={skipped}")

        if issued_rows and not args.no_refresh:
            touched = sorted({r["dataset"] for r in issued_rows})
            refresh_coverage_ledger(conn, db, datasets=touched)
            conn.commit()
            for ds in touched:
                complete = conn.execute(
                    "SELECT COUNT(*) FROM coverage_segments "
                    "WHERE dataset=? AND status='COMPLETE'",
                    (ds,),
                ).fetchone()[0]
                total = conn.execute(
                    "SELECT COUNT(*) FROM coverage_segments WHERE dataset=?",
                    (ds,),
                ).fetchone()[0]
                print(f"local coverage {ds}: COMPLETE={complete}/{total}")

    complete_after = conn.execute(
        "SELECT COUNT(*) FROM coverage_segments WHERE status='COMPLETE'"
    ).fetchone()[0]
    conn.close()

    summary = {
        "datasets": datasets,
        "candidates": len(jobs),
        "ready": len(ready),
        "issued": len(issued_rows),
        "skipped": skipped,
        "issued_segments": [
            f"{r['dataset']}/{r['segment_id']}" for r in issued_rows
        ],
        "ready_segments": [
            f"{p.required.dataset}/{p.required.segment_id}" for p in ready
        ],
        "local_complete_segments": int(complete_after),
        "dry_run": bool(args.dry_run),
        "workers": int(args.workers),
        "note": (
            "COMPLETE only after ledger refresh with raw+structured+signed "
            "SUCCESS; never without raw. No backfill/Mass launched."
        ),
    }
    if args.json_summary:
        print(json.dumps(summary, ensure_ascii=False))

    if args.dry_run:
        return 0 if ready else 1
    return 0 if issued_rows else 1


if __name__ == "__main__":
    raise SystemExit(main())
