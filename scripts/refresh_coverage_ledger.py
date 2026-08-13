#!/usr/bin/env python3
"""Refresh Coverage V2 ledger with receipts and evaluate completeness.

Phase 6.2 Residual: This script provides the operational path for:
- Refreshing the coverage ledger with fresh coverage V2 evaluation
- Evaluating receipts for completeness
- Updating dataset_coverage and coverage_segments tables

This is the operational path for Coverage V2 receipts processing.
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

import sqlite3
from typing import Any
from urllib.parse import quote

ROOT = ensure_repo_root()

from storage.coverage_ledger import (
    coverage_gaps,
    coverage_summary,
    read_collection_receipts,
    read_coverage_segments,
    read_dataset_coverage,
    refresh_coverage_ledger,
)
from cf_platform.ingest_premium.coverage import run_coverage
from data_contracts.coverage import (
    all_coverage_contracts,
    coverage_contract_for,
)

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        epilog="Phase 6.2 Residual: Coverage V2 operational path with receipts."
    )
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
        "--summary-only",
        action="store_true",
        help="only print summary without full refresh",
    )
    parser.add_argument(
        "--gaps-only",
        action="store_true",
        help="only print datasets with incomplete coverage",
    )
    args = parser.parse_args(argv)

    db_path = Path(args.db).resolve()
    if not db_path.exists():
        print(f"Error: Database not found: {db_path}", file=sys.stderr)
        return 1

    # Validate database connection
    uri = "file:" + quote(str(db_path)) + "?mode=ro"
    try:
        conn = sqlite3.connect(uri, uri=True)
        conn.close()
    except sqlite3.Error as e:
        print(f"Error: Cannot connect to database: {e}", file=sys.stderr)
        return 1

    # Summary-only mode
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

    # Gaps-only mode
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

    # Full refresh mode
    selected = args.datasets
    if selected:
        # Validate dataset names
        available = {c.dataset_id for c in all_coverage_contracts()}
        invalid = set(selected) - available
        if invalid:
            print(f"Error: Unknown datasets: {', '.join(sorted(invalid))}", file=sys.stderr)
            print(f"Available datasets: {', '.join(sorted(available))}", file=sys.stderr)
            return 1

    try:
        # Open write connection
        conn = sqlite3.connect("file:" + quote(str(db_path)) + "?mode=rw", uri=True)

        # Refresh coverage ledger
        results = refresh_coverage_ledger(
            conn,
            db_path,
            datasets=selected,
            today=args.today,
            freshness_days=args.freshness_days,
        )

        # Print results
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

        # Check if all governed datasets are COMPLETE
        summary = coverage_summary(db_path)
        if summary['governed_ready']:
            print("\nAll governed datasets are COMPLETE and READY for research.")
            return 0
        else:
            print("\nSome governed datasets are not COMPLETE. Use --gaps-only for details.")
            return 0  # Still success, just informational

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
