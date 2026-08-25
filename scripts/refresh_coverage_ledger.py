#!/usr/bin/env python3
"""Refresh Coverage V2 ledger with receipts and evaluate completeness."""

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

import sqlite3
from urllib.parse import quote

ensure_repo_root()

from ingestion.jsda.official_index import read_local_index_text as _read_index_text
from storage.coverage_ledger import (
    coverage_gaps,
    coverage_summary,
    refresh_coverage_ledger,
)
from data_contracts.coverage import (
    all_coverage_contracts,
)

def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--db",
        required=True,
        help="path to structured SQLite database",
    )
    parser.add_argument(
        "--datasets",
        nargs="*",
        default=None,
        help="specific datasets to refresh (default: all governed)",
    )
    parser.add_argument(
        "--today",
        default=None,
        help="target end date ISO format (default: today)",
    )
    parser.add_argument(
        "--freshness-days",
        type=int,
        default=7,
        help="freshness window in calendar days (default: 7)",
    )
    parser.add_argument(
        "--index-text",
        default=None,
        metavar="PATH",
        help=(
            "local official-archive index HTML. Omitted: index_text is None "
            "so OTC required set is fail-closed empty, not a calendar replay. "
            "Does not fetch live JSDA HTML."
        ),
    )
    parser.add_argument(
        "--summary-only",
        action="store_true",
        help="only print summary without full refresh",
    )
    parser.add_argument(
        "--gaps-only",
        action="store_true",
        help="only print datasets with incomplete coverage",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)

    db_path = Path(args.db).resolve()
    if not db_path.exists():
        print(f"Error: Database not found: {db_path}", file=sys.stderr)
        return 1

    uri = "file:" + quote(str(db_path)) + "?mode=ro"
    try:
        conn = sqlite3.connect(uri, uri=True)
        conn.close()
    except sqlite3.Error as e:
        print(f"Error: Cannot connect to database: {e}", file=sys.stderr)
        return 1

    if args.summary_only:
        summary = coverage_summary(db_path)
        print("Coverage Summary:")
        print(f"  Policy version: {summary['policy_version']}")
        print(f"  Dataset count: {summary['dataset_count']}")
        print(f"  Status counts:")
        for status, count in sorted(summary['status_counts'].items()):
            print(f"    {status}: {count}")
        print(f"  Governed READY: {summary['governed_ready']}")
        return 0

    if args.gaps_only:
        gaps = coverage_gaps(db_path)
        if not gaps:
            print("All governed datasets have COMPLETE coverage.")
            return 0
        print(f"Found {len(gaps)} datasets with incomplete coverage:")
        for gap in gaps:
            print(f"  {gap['dataset']}: {gap['status']}")
            if gap.get('detail_json'):
                import json
                try:
                    detail = json.loads(gap['detail_json'])
                    reason = detail.get('reason', 'unknown')
                    print(f"    Reason: {reason}")
                except:
                    pass
        return 0

    selected = args.datasets
    if selected:
        available = {c.dataset_id for c in all_coverage_contracts()}
        invalid = set(selected) - available
        if invalid:
            print(f"Error: Unknown datasets: {', '.join(sorted(invalid))}", file=sys.stderr)
            print(f"Available datasets: {', '.join(sorted(available))}", file=sys.stderr)
            return 1

    try:
        index_text = _read_index_text(args.index_text)
    except FileNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    try:
        conn = sqlite3.connect("file:" + quote(str(db_path)) + "?mode=rw", uri=True)
        results = refresh_coverage_ledger(
            conn,
            db_path,
            datasets=selected,
            today=args.today,
            freshness_days=args.freshness_days,
            index_text=index_text,
        )
        print(f"Refreshed coverage for {len(results)} datasets:")
        for result in results:
            print(f"  {result['dataset']}: {result['status']}")
            if result['status'] != 'COMPLETE':
                import json
                try:
                    detail = json.loads(result['detail_json'])
                    coverage_v2 = detail.get('coverage_v2', {})
                    status_counts = coverage_v2.get('status_counts', {})
                    if status_counts:
                        print(f"    Segments: {', '.join(f'{s}={c}' for s, c in sorted(status_counts.items()))}")
                except:
                    pass

        conn.close()
        summary = coverage_summary(db_path)
        if summary['governed_ready']:
            print("\nAll governed datasets are COMPLETE and READY for research.")
            return 0
        print("\nSome governed datasets are not COMPLETE. Use --gaps-only for details.")
        return 0

    except sqlite3.Error as e:
        print(f"Database error: {e}", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"Error during refresh: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        return 1

if __name__ == "__main__":
    raise SystemExit(main())
