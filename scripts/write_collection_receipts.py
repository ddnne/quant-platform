#!/usr/bin/env python3
"""Write real (or hard-gated synthetic) collection receipts. Lane H.

This is the operational receipt-writing path that closes the J-Quants gap:
the J-Quants catalog pipeline persists raw bytes and structured rows but does
not emit ``collection_receipts`` rows, so every J-Quants governed dataset sits
at PARTIAL/UNKNOWN with zero receipts. This script records a REAL receipt whose
``raw`` digest is a SHA-256 over the actual persisted source bytes — so any
COMPLETE verdict is backed by verifiable raw retention.

Two modes:

* **REAL** (default): reads ``--raw-file`` bytes from disk, computes the real
  digest, records one receipt for the chosen planned segment. Run
  ``refresh_coverage_ledger.py`` afterwards to fold the receipt into coverage.
  This never fakes a verdict — :func:`evaluate_segment` decides COMPLETE from
  the policy gates.

* **SYNTHETIC** (``--synthetic``): OFFLINE FIXTURE DATABASES ONLY. Requires the
  explicit ``--allow-fixture-synthetic`` acknowledgement, embeds the
  ``synthetic``/``origin: offline-test-fixture`` sentinel, and is intended for
  generating test fixtures. It must never be run against a production database.

The governed JSDA datasets already have live receipt writers
(``ingestion/jsda/archive.py``, ``repo_archive.py``, ``corrections.py``); this
script is the equivalent path for J-Quants governed datasets and a general
operational tool for any planned segment.

Examples
--------
  # Real receipt for one planned segment (event-driven dataset -> can COMPLETE):
  python3 scripts/write_collection_receipts.py \\
      --db data/structured/ingestion.sqlite --dataset fins_summary \\
      --target-end 2025-03-31 --raw-file data/raw/jquants/2025/03/31/fins_summary.json

  # List planned segment ids when more than one matches:
  python3 scripts/write_collection_receipts.py --db DB --dataset fins_summary --list-segments

  # OTC: local official-index HTML only (never downloaded):
  python3 scripts/write_collection_receipts.py --db DB \\
      --dataset jsda_otc_bond_reference_prices --target-end 2002-08-06 \\
      --index-text tests/fixtures/jsda_otc_official_index_tiny.html --list-segments

  # Synthetic fixture receipt (tests only):
  python3 scripts/write_collection_receipts.py --db fixture.sqlite \\
      --dataset fins_summary --target-end 2025-03-31 \\
      --synthetic --allow-fixture-synthetic
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
import os
import sqlite3

from urllib.parse import quote

ROOT = ensure_repo_root()

from data_contracts import coverage_contract_for  # noqa: E402
from storage.coverage_ledger import (  # noqa: E402
    SYNTHETIC_RECEIPT_MARKER,
    RequiredCoverageSegment,
    build_collection_receipt,
    build_synthetic_complete_receipt,
    plan_required_segments,
    record_collection_receipt,
)

def _coverage_source(dataset: str) -> str:
    return "jsda" if dataset.startswith("jsda_") else "jquants"

def _connect(db_path: Path) -> sqlite3.Connection:
    uri = "file:" + quote(str(db_path)) + "?mode=rw"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    return conn

def _ensure_receipts_table(conn: sqlite3.Connection) -> None:
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='collection_receipts'"
    ).fetchone()
    if row is None:
        raise SystemExit(
            "collection_receipts table is missing — apply the schema first "
            "(e.g. open the database with storage.sqlite_store.SqliteStore and "
            "run platform/workers/ingestion-premium/migrations/"
            "0007_collection_coverage_v2.sql)."
        )

def _read_index_text(path: str | Path | None) -> str | None:
    """Read local official-index HTML. Missing/blank → None (fail-closed).

    Never downloads the index. Never walks a calendar.
    """
    if path is None:
        return None
    raw = str(path).strip()
    if not raw:
        return None
    file_path = Path(raw)
    if not file_path.is_file():
        return None
    text = file_path.read_text(encoding="utf-8")
    if not text.strip():
        return None
    return text

def _index_text_from_cli(cli_path: str | None) -> str | None:
    """Resolve --index-text, else env QP_INDEX_TEXT. Missing/blank is empty."""
    path = cli_path if cli_path is not None else os.environ.get("QP_INDEX_TEXT")
    return _read_index_text(path)

def _plan_segments(
    dataset: str,
    target_end: str,
    source: str,
    index_text: str | None = None,
) -> list[RequiredCoverageSegment]:
    policy = coverage_contract_for(dataset)
    return list(
        plan_required_segments(
            policy, target_end, source=source, index_text=index_text
        )
    )

def _pick_segment(
    segments: list[RequiredCoverageSegment], segment_id: str | None
) -> RequiredCoverageSegment:
    if segment_id is not None:
        for segment in segments:
            if segment.segment_id == segment_id:
                return segment
        available = ", ".join(sorted(s.segment_id for s in segments)) or "(none)"
        raise SystemExit(
            f"no planned segment with segment_id={segment_id!r}; "
            f"available: {available}"
        )
    if len(segments) == 1:
        return segments[0]
    available = ", ".join(sorted(s.segment_id for s in segments))
    raise SystemExit(
        f"{len(segments)} planned segments match — pass --segment-id "
        f"(or --list-segments). Available: {available}"
    )

def _count_observed(raw: bytes) -> int:
    """Best-effort observed-item count from the persisted raw bytes.

    Honest default: the count of records actually present in the raw payload.
    Raises if the bytes are not JSON-parseable in a recognised shape so the
    caller must state the count explicitly rather than guess.
    """
    try:
        decoded = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise SystemExit(
            f"raw file is not UTF-8 JSON ({exc}); pass --observed-items explicitly"
        ) from exc
    try:
        parsed = json.loads(decoded)
    except json.JSONDecodeError as exc:
        raise SystemExit(
            f"raw file is not valid JSON ({exc}); pass --observed-items explicitly"
        ) from exc
    if isinstance(parsed, list):
        return len(parsed)
    if isinstance(parsed, dict):
        for key in ("rows", "data", "results", "records"):
            value = parsed.get(key)
            if isinstance(value, list):
                return len(value)
    # A non-empty object we can't structurally count: treat as one event.
    return 1 if parsed else 0

def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="Lane H: receipt-writing path. REAL receipts only by default.",
    )
    p.add_argument("--db", required=True, help="path to structured SQLite database")
    p.add_argument("--dataset", required=True, help="governed dataset id (e.g. fins_summary)")
    p.add_argument(
        "--target-end", default=None,
        help="plan segments up to this ISO date (default: today UTC)",
    )
    p.add_argument(
        "--index-text",
        default=None,
        help=(
            "local official-index HTML path (env QP_INDEX_TEXT). "
            "Missing path or blank file is fail-closed empty required set. "
            "Never downloaded."
        ),
    )
    p.add_argument(
        "--source", default=None,
        help="receipt source (default: auto from dataset prefix)",
    )
    p.add_argument("--run-id", type=int, default=1, help="run id to stamp on receipts (default 1)")
    p.add_argument(
        "--segment-id", default=None,
        help="target a specific planned segment id (default: the only one, else required)",
    )
    p.add_argument(
        "--list-segments", action="store_true",
        help="print planned segment ids for --dataset/--target-end and exit",
    )
    p.add_argument("--raw-file", default=None, help="path to the verbatim persisted raw bytes (REAL mode)")
    p.add_argument(
        "--observed-items", type=int, default=None,
        help="observed item count (default: parsed from --raw-file JSON)",
    )
    p.add_argument(
        "--structured-rows", type=int, default=None,
        help="structured row count (default: --observed-items)",
    )
    p.add_argument(
        "--raw-rows", type=int, default=None,
        help="raw row count (default: --structured-rows)",
    )
    p.add_argument(
        "--no-pagination-exhausted", dest="pagination_exhausted",
        action="store_false", default=True,
        help="mark pagination as NOT exhausted (segment will not COMPLETE)",
    )
    p.add_argument(
        "--all-segments", action="store_true",
        help="emit a receipt for every planned segment (SYNTHETIC mode only)",
    )
    p.add_argument(
        "--synthetic", action="store_true",
        help="OFFLINE FIXTURE ONLY: emit synthetic COMPLETE receipts",
    )
    p.add_argument(
        "--allow-fixture-synthetic", action="store_true",
        help="required acknowledgement to enable --synthetic (fixture DBs only)",
    )
    return p

def _today_utc() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).date().isoformat()

def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)

    db_path = Path(args.db).resolve()
    if not db_path.exists():
        print(f"Error: Database not found: {db_path}", file=sys.stderr)
        return 1

    target_end = args.target_end or _today_utc()
    source = args.source or _coverage_source(args.dataset)
    index_text = _index_text_from_cli(args.index_text)

    try:
        segments = _plan_segments(
            args.dataset, target_end, source, index_text=index_text
        )
    except KeyError:
        print(f"Error: Unknown dataset: {args.dataset}", file=sys.stderr)
        return 1
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    if args.list_segments:
        print(f"Planned segments for {args.dataset} (source={source}, target_end={target_end}):")
        for segment in segments:
            print(f"  {segment.segment_id}  [{segment.segment_start} .. {segment.segment_end}]")
        return 0

    if not segments:
        print(
            f"No planned segments for {args.dataset} up to {target_end} "
            "(history_target_start may be later).",
            file=sys.stderr,
        )
        return 1

    # SYNTHETIC mode: hard-gated to fixture databases.
    if args.synthetic:
        if not args.allow_fixture_synthetic:
            print(
                "Error: --synthetic writes offline-fixture receipts only and "
                "requires --allow-fixture-synthetic. It must NEVER be used "
                "against a production database.",
                file=sys.stderr,
            )
            return 2
        targets = segments if args.all_segments else [_pick_segment(segments, args.segment_id)]
        conn = _connect(db_path)
        try:
            _ensure_receipts_table(conn)
            for required in targets:
                receipt = build_synthetic_complete_receipt(
                    required=required, run_id=args.run_id
                )
                record_collection_receipt(conn, receipt)
            conn.commit()
        finally:
            conn.close()
        marker = ", ".join(f"{k}={v}" for k, v in SYNTHETIC_RECEIPT_MARKER.items())
        for required in targets:
            print(
                f"SYNTHETIC receipt (FIXTURE ONLY) -> {required.dataset}/"
                f"{required.segment_id} run_id={args.run_id} [{marker}]"
            )
        print(
            "Wrote synthetic fixture receipts. These carry the synthetic "
            "sentinel and must never be used in production.",
            file=sys.stderr,
        )
        return 0

    # REAL mode: digest over actual persisted bytes.
    if args.raw_file is None:
        print(
            "Error: REAL mode requires --raw-file (the verbatim persisted "
            "source bytes for the segment). Use --synthetic --allow-fixture-"
            "synthetic for offline fixture databases.",
            file=sys.stderr,
        )
        return 2
    raw_path = Path(args.raw_file)
    if not raw_path.exists():
        print(f"Error: raw file not found: {raw_path}", file=sys.stderr)
        return 1
    raw = raw_path.read_bytes()

    required = _pick_segment(segments, args.segment_id)
    observed = args.observed_items
    if observed is None:
        observed = _count_observed(raw)
    structured_rows = args.structured_rows if args.structured_rows is not None else observed
    raw_rows = args.raw_rows if args.raw_rows is not None else structured_rows

    from storage.trusted_receipt import open_signed_receipt_authority

    issuer = open_signed_receipt_authority()
    receipt = issuer.issue(
        required=required,
        run_id=args.run_id,
        raw=raw,
        observed_items=observed,
        structured_row_count=structured_rows,
        raw_row_count=raw_rows,
        pagination_exhausted=args.pagination_exhausted,
    )
    conn = _connect(db_path)
    try:
        _ensure_receipts_table(conn)
        record_collection_receipt(conn, receipt)
        conn.commit()
    finally:
        conn.close()

    print(
        f"REAL receipt -> {receipt.dataset}/{receipt.segment_id} "
        f"run_id={receipt.run_id} status={receipt.status} "
        f"observed={receipt.observed_items} raw_digest={receipt.digests['raw']}"
    )
    print(
        "Run scripts/refresh_coverage_ledger.py to fold this receipt into "
        "coverage_segments / dataset_coverage.",
    )
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
