#!/usr/bin/env python3
"""Parallel after-the-fact recovery evidence. Never issues signed COMPLETE.

Optional --index-text PATH is local official-index HTML. Omitted:
index_text is None so OTC required set is fail-closed empty, not
calendar COMPLETE. Does not fetch live JSDA HTML.
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
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Any, Sequence

ROOT = ensure_repo_root()

from ingestion.jsda.official_index import (  # noqa: E402
    read_local_index_text as _read_index_text,
)
from storage.coverage_ledger import (  # noqa: E402
    RequiredCoverageSegment,
    build_collection_receipt,
    refresh_coverage_ledger,
    record_collection_receipt,
    record_required_segments,
    sync_dataset_coverage_from_segments,
)
from storage.sqlite_store import SqliteStore  # noqa: E402
from storage.receipt_crypto import partition_extra_digests  # noqa: E402

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


def _load_structured_records(
    conn: sqlite3.Connection, dataset: str, start: str, end: str
) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT * FROM jquants_records WHERE dataset=? "
        "AND substr(event_time,1,10)>=? AND substr(event_time,1,10)<=? "
        "ORDER BY event_time",
        (dataset, start[:10], end[:10]),
    ).fetchall()
    columns = [str(item[0]) for item in (conn.execute(
        "SELECT name FROM pragma_table_info('jquants_records') ORDER BY cid"
    ).fetchall())]
    return [dict(zip(columns, row, strict=True)) for row in rows]


def _raw_records(raw: bytes) -> list[Any] | None:
    """Return concrete JSON records; opaque/count-only raw is not signable."""
    try:
        payload = json.loads(raw)
    except (json.JSONDecodeError, UnicodeDecodeError, TypeError, ValueError):
        return None
    if isinstance(payload, list):
        return list(payload)
    if isinstance(payload, dict):
        for key in ("data", "rows", "results", "records"):
            value = payload.get(key)
            if isinstance(value, list):
                return list(value)
    return None


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
    """Reject empty/stub payloads (``[]`` / ``{}`` / ``{"data": []}``)."""
    if not raw or len(raw) >= 25_000_000:
        return False
    stripped = raw.strip()
    if len(stripped) < 8:
        return False
    if stripped in {b"[]", b"{}", b"null", b'""', b"''"}:
        return False
    if stripped in {b"[\n]", b"[\r\n]", b"{\n}", b"{\r\n}"}:
        return False
    if stripped in {
        b'{"data":[]}',
        b'{"data": []}',
        b'{"data": [\n]}',
        b'{"data":[]}\n',
        b'{"data": []}\n',
    }:
        return False
    try:
        payload = json.loads(stripped)
    except (json.JSONDecodeError, UnicodeDecodeError, ValueError):
        return True
    if isinstance(payload, list) and len(payload) == 0:
        return False
    if isinstance(payload, dict):
        if not payload:
            return False
        data = payload.get("data")
        if isinstance(data, list) and len(data) == 0:
            return False
        rows = payload.get("rows")
        if isinstance(rows, list) and len(rows) == 0 and "data" not in payload:
            return False
    return True


def find_raw_bytes_indexed(
    index: Sequence[RawIndexEntry],
    *,
    dataset: str,
    segment_id: str,
    segment_start: str,
    segment_end: str,
) -> tuple[Path, bytes] | None:
    """Best non-empty persisted raw artifact for a segment, or None."""
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
        if size < 8:
            continue
        ranked.append((score, size, entry.path))
    ranked.sort(key=lambda item: (item[0], item[1]), reverse=True)
    for _score, _size, path in ranked[:120]:
        try:
            raw = path.read_bytes()
        except OSError:
            continue
        if _is_usable_raw(raw):
            return path, raw
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
    raw_path: Path
    raw: bytes
    raw_records: list[Any]
    structured_records: list[dict[str, Any]]


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
    struct_hint: bool = False,
) -> list[SegmentJob]:
    """Load coverage segments. ``struct_hint`` skips months with zero structured rows."""
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
        if struct_hint:
            q += (
                " AND EXISTS ("
                "  SELECT 1 FROM jquants_records j"
                "  WHERE j.dataset = coverage_segments.dataset"
                "    AND substr(j.event_time, 1, 10)"
                "        >= substr(coverage_segments.segment_start, 1, 10)"
                "    AND substr(j.event_time, 1, 10)"
                "        <= substr(coverage_segments.segment_end, 1, 10)"
                "  LIMIT 1"
                ")"
            )
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
        structured_records = _load_structured_records(
            conn, job.dataset, job.segment_start, job.segment_end
        )
    finally:
        conn.close()
    structured = len(structured_records)

    if structured < min_structured:
        return PrepareResult(job=job, skip_reason=f"no_struct structured={structured}")

    raw_match = find_raw_bytes_indexed(
        raw_index,
        dataset=job.dataset,
        segment_id=job.segment_id,
        segment_start=job.segment_start,
        segment_end=job.segment_end,
    )
    if raw_match is None:
        return PrepareResult(job=job, skip_reason="no_raw")
    raw_path, raw = raw_match
    if raw_path.stat().st_mode & 0o222:
        return PrepareResult(job=job, skip_reason="raw_not_immutable")
    raw_records = _raw_records(raw)
    if raw_records is None or len(raw_records) != structured:
        return PrepareResult(
            job=job,
            skip_reason=(
                "unreconciled concrete raw/structured evidence "
                f"raw={None if raw_records is None else len(raw_records)} "
                f"structured={structured}"
            ),
        )

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
    prepared = PreparedIssue(
        job=job,
        required=required,
        structured=structured,
        raw_path=raw_path,
        raw=raw,
        raw_records=raw_records,
        structured_records=structured_records,
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
    results.sort(
        key=lambda r: (r.job.dataset, r.job.segment_start, r.job.segment_id),
        reverse=True,
    )
    return results


def issue_prepared(
    store: SqliteStore,
    prepared_list: Sequence[PreparedIssue],
    *,
    start_run_id: int,
) -> list[dict[str, Any]]:
    """Record serial RECOVERED_RAW_ONLY observations; never sign."""
    conn = store._conn  # noqa: SLF001 - operator tool shares governed store
    issued_rows: list[dict[str, Any]] = []
    next_run = start_run_id
    for prep in prepared_list:
        record_required_segments(conn, [prep.required])
        receipt = build_collection_receipt(
            required=prep.required,
            run_id=next_run,
            raw=prep.raw,
            observed_items=1 if prep.raw_records else 0,
            raw_row_count=len(prep.raw_records),
            structured_row_count=prep.structured,
            pagination_exhausted=True,
            extra_digests=partition_extra_digests({
                "eligibility": "RECOVERED_RAW_ONLY",
                "origin": "after-the-fact-operator-recovery",
                "raw_path": str(prep.raw_path),
            }),
        )
        record_collection_receipt(conn, receipt)
        next_run += 1
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
    seen: set[str] = set()
    ordered: list[str] = []
    for d in out:
        if d not in seen:
            seen.add(d)
            ordered.append(d)
    return ordered


def _build_parser() -> argparse.ArgumentParser:
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
        help="Max non-COMPLETE segments to scan per dataset.",
    )
    ap.add_argument("--min-structured", type=int, default=1)
    ap.add_argument("--workers", type=int, default=4, help="ThreadPool size.")
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
    ap.add_argument(
        "--struct-hint",
        action="store_true",
        help="Only scan segments that already have in-window structured rows.",
    )
    ap.add_argument(
        "--dry-run",
        action="store_true",
        help="Prepare only; do not sign or refresh.",
    )
    ap.add_argument(
        "--no-refresh",
        action="store_true",
        help="Issue receipts but skip ledger refresh.",
    )
    ap.add_argument(
        "--index-text",
        default=None,
        metavar="PATH",
        help=(
            "local official-archive index HTML. Omitted: index_text is None "
            "so OTC required set is fail-closed empty, not a calendar replay. "
            "Does not fetch live JSDA HTML."
        ),
    )
    ap.add_argument(
        "--json-summary",
        action="store_true",
        help="Print JSON summary on stdout (last line).",
    )
    return ap


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)

    datasets = _parse_datasets(args.datasets, args.dataset)
    if not datasets:
        datasets = ["markets_short_ratio"]

    db = Path(args.db)
    data_dir = Path(args.data_dir)
    if not db.is_file():
        print(f"db missing: {db}", file=sys.stderr)
        return 2

    try:
        index_text = _read_index_text(args.index_text)
    except FileNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    # A dry-run is deliberately read-only: opening ``SqliteStore`` would apply
    # schema migrations and therefore make an operator preview mutate its input.
    # The production path owns the governed store and its migrations.
    store: SqliteStore | None
    if args.dry_run:
        store = None
        conn = sqlite3.connect(db)
        conn.row_factory = sqlite3.Row
    else:
        store = SqliteStore(db)
        conn = store._conn  # noqa: SLF001 - operator tool owns this store
    jobs = load_candidate_segments(
        conn,
        datasets=datasets,
        segment_id=args.segment_id,
        limit_per_dataset=args.limit,
        include_complete=args.include_complete,
        order=args.order,
        struct_hint=bool(args.struct_hint),
    )
    if not jobs:
        print("no segments found", file=sys.stderr)
        if store is not None:
            store.close()
        else:
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
        assert store is not None
        max_run = conn.execute(
            "SELECT COALESCE(MAX(run_id), 900000) FROM collection_receipts"
        ).fetchone()[0]
        start_run = int(max_run) + 1
        issued_rows = issue_prepared(
            store,
            ready,
            start_run_id=start_run,
        )
        conn.commit()
        for row in issued_rows:
            print(
                f"recorded recovery receipt {row['dataset']}/{row['segment_id']} "
                f"structured={row['structured']} run_id={row['run_id']}"
            )
        print(f"summary issued={len(issued_rows)} skipped={skipped}")

        if issued_rows and not args.no_refresh:
            touched = sorted({r["dataset"] for r in issued_rows})
            refresh_coverage_ledger(
                conn, db, datasets=touched, index_text=index_text
            )
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
            reagg = sync_dataset_coverage_from_segments(
                conn,
                datasets=touched,
                wave="issue_receipts_parallel",
            )
            conn.commit()
            for row in reagg:
                print(
                    "dataset_coverage_sync:",
                    {
                        "dataset": row.get("dataset"),
                        "action": row.get("action"),
                        "from": row.get("old_status") or row.get("from"),
                        "to": row.get("to")
                        or row.get("status")
                        or row.get("derived_status"),
                        "status_counts": row.get("status_counts"),
                    },
                )

    complete_after = conn.execute(
        "SELECT COUNT(*) FROM coverage_segments WHERE status='COMPLETE'"
    ).fetchone()[0]
    if store is not None:
        store.close()
    else:
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
            "RECOVERED_RAW_ONLY: a governed ingestion replay must independently "
            "persist, parse, commit, reread, reconcile, and sign before COMPLETE."
        ),
    }
    if args.json_summary:
        print(json.dumps(summary, ensure_ascii=False))

    if args.dry_run:
        return 0 if ready else 1
    return 0 if issued_rows else 1


if __name__ == "__main__":
    raise SystemExit(main())
