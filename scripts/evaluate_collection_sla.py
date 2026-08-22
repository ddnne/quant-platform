#!/usr/bin/env python3
"""Evaluate collection coverage SLA (AVAILABLE / DEGRADED / UNAVAILABLE / UNKNOWN)."""

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

import sqlite3
from typing import Any

ensure_repo_root()

from storage.coverage_ledger import (
    coverage_gaps,
    read_collection_receipts,
    read_coverage_segments,
    read_dataset_coverage,
)
from data_contracts.coverage import (
    all_coverage_contracts,
    COVERAGE_STATUSES,
)

def evaluate_collection_sla(
    db_path: str | Path,
    *,
    dataset: str | None = None,
) -> dict[str, Any]:
    """Evaluate collection coverage SLA for one dataset or all governed datasets."""
    db_path = Path(db_path).resolve()
    if not db_path.exists():
        raise FileNotFoundError(f"Database not found: {db_path}")

    if dataset is None:
        coverage_rows = read_dataset_coverage(db_path)
    else:
        coverage_rows = read_dataset_coverage(db_path, dataset=dataset)

    if not coverage_rows:
        return {
            "sla_state": "UNKNOWN",
            "reason": "No coverage data found",
            "datasets_evaluated": 0,
            "governed_datasets": [],
        }

    governed_contracts = {
        c.dataset_id for c in all_coverage_contracts()
        if c.governance_tier == "governed"
    }

    governed_coverage = [
        row for row in coverage_rows if row["dataset"] in governed_contracts
    ]

    if not governed_coverage:
        return {
            "sla_state": "UNKNOWN",
            "reason": "No governed datasets found in coverage data",
            "datasets_evaluated": len(coverage_rows),
            "governed_datasets": [],
        }

    status_counts: dict[str, int] = {status: 0 for status in COVERAGE_STATUSES}
    for row in governed_coverage:
        status = row["status"]
        if status in status_counts:
            status_counts[status] += 1

    total_governed = len(governed_coverage)
    complete_count = status_counts["COMPLETE"]
    partial_count = status_counts["PARTIAL"]
    failed_count = status_counts["FAILED"]
    stale_count = status_counts["STALE"]
    unknown_count = status_counts["UNKNOWN"]

    if failed_count > 0 or stale_count > 0:
        sla_state = "UNAVAILABLE"
        reason = f"{failed_count} FAILED, {stale_count} STALE datasets"
    elif complete_count == total_governed:
        sla_state = "AVAILABLE"
        reason = f"All {total_governed} governed datasets have COMPLETE coverage"
    elif partial_count > 0:
        sla_state = "DEGRADED"
        reason = f"{complete_count}/{total_governed} COMPLETE, {partial_count} PARTIAL"
    else:
        sla_state = "UNKNOWN"
        reason = "Coverage state cannot be determined"

    gaps = coverage_gaps(db_path)
    governed_gaps = [g for g in gaps if g["dataset"] in governed_contracts]

    return {
        "sla_state": sla_state,
        "reason": reason,
        "datasets_evaluated": total_governed,
        "governed_datasets": [row["dataset"] for row in governed_coverage],
        "status_counts": status_counts,
        "gaps": [
            {
                "dataset": gap["dataset"],
                "status": gap["status"],
                "observed_start": gap.get("observed_start"),
                "observed_end": gap.get("observed_end"),
            }
            for gap in governed_gaps
        ],
    }

def evaluate_receipt_sla(
    db_path: str | Path,
    *,
    dataset: str | None = None,
) -> dict[str, Any]:
    """Evaluate receipt compliance for SLA monitoring."""
    db_path = Path(db_path).resolve()
    if not db_path.exists():
        raise FileNotFoundError(f"Database not found: {db_path}")

    complete_segments = read_coverage_segments(db_path, dataset=dataset, status="COMPLETE")

    if not complete_segments:
        return {
            "receipt_sla_state": "UNKNOWN",
            "reason": "No COMPLETE segments found",
            "complete_segments_checked": 0,
            "receipt_compliance": {},
        }

    issues = []
    compliant_count = 0

    for segment in complete_segments:
        receipts = read_collection_receipts(
            db_path, dataset=segment["dataset"], segment_id=segment["segment_id"]
        )

        if not receipts:
            issues.append({
                "dataset": segment["dataset"],
                "segment_id": segment["segment_id"],
                "issue": "no_receipt_found"
            })
            continue

        latest_receipt = max(receipts, key=lambda r: (r["checked_at"], r["run_id"]))

        segment_issues = []
        if latest_receipt["status"] != "SUCCESS":
            segment_issues.append(f"receipt_status_{latest_receipt['status']}")
        if latest_receipt["raw_page_count"] < 1:
            segment_issues.append("no_raw_pages")
        if not latest_receipt["pagination_exhausted"]:
            segment_issues.append("pagination_not_exhausted")
        if latest_receipt["raw_row_count"] != latest_receipt["structured_row_count"]:
            segment_issues.append("raw_structured_mismatch")

        if segment_issues:
            issues.append({
                "dataset": segment["dataset"],
                "segment_id": segment["segment_id"],
                "issues": segment_issues,
                "receipt_status": latest_receipt["status"],
            })
        else:
            compliant_count += 1

    receipt_sla_state = "COMPLIANT" if not issues else "NON_COMPLIANT"

    return {
        "receipt_sla_state": receipt_sla_state,
        "reason": f"{compliant_count}/{len(complete_segments)} segments have compliant receipts",
        "complete_segments_checked": len(complete_segments),
        "compliant_segments": compliant_count,
        "non_compliant_segments": len(issues),
        "issues": issues,
    }

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--db",
        required=True,
        help="path to structured SQLite database",
    )
    parser.add_argument(
        "--dataset",
        default=None,
        help="specific dataset to evaluate (default: all governed)",
    )
    parser.add_argument(
        "--check-receipts",
        action="store_true",
        help="also evaluate receipt SLA compliance",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="output results as JSON",
    )
    args = parser.parse_args(argv)

    db_path = Path(args.db).resolve()
    if not db_path.exists():
        print(f"Error: Database not found: {db_path}", file=sys.stderr)
        return 1

    try:
        collection_result = evaluate_collection_sla(db_path, dataset=args.dataset)

        result = {
            "collection_sla": collection_result,
        }

        if args.check_receipts:
            receipt_result = evaluate_receipt_sla(db_path, dataset=args.dataset)
            result["receipt_sla"] = receipt_result

        if args.json:
            print(json.dumps(result, indent=2))
        else:
            print("Collection Coverage SLA Evaluation")
            print("=" * 50)
            print(f"SLA State: {collection_result['sla_state']}")
            print(f"Reason: {collection_result['reason']}")
            print(f"Datasets Evaluated: {collection_result['datasets_evaluated']}")
            print(f"\nStatus Counts:")
            for status, count in sorted(collection_result['status_counts'].items()):
                if count > 0:
                    print(f"  {status}: {count}")

            if collection_result.get('gaps'):
                print(f"\nGaps ({len(collection_result['gaps'])}):")
                for gap in collection_result['gaps']:
                    print(f"  {gap['dataset']}: {gap['status']}")

            if "receipt_sla" in result:
                receipt_result = result["receipt_sla"]
                print(f"\nReceipt SLA State: {receipt_result['receipt_sla_state']}")
                print(f"Reason: {receipt_result['reason']}")
                print(f"Segments Checked: {receipt_result['complete_segments_checked']}")
                print(f"Compliant: {receipt_result['compliant_segments']}")
                print(f"Non-Compliant: {receipt_result['non_compliant_segments']}")

                if receipt_result.get('issues'):
                    print(f"\nReceipt Issues:")
                    for issue in receipt_result['issues']:
                        print(f"  {issue['dataset']}/{issue['segment_id']}: {', '.join(issue.get('issues', ['unknown']))}")

        if collection_result['sla_state'] == "AVAILABLE":
            if "receipt_sla" in result and result["receipt_sla"]["receipt_sla_state"] != "COMPLIANT":
                return 1
            return 0
        if collection_result['sla_state'] == "DEGRADED":
            return 1
        return 2

    except sqlite3.Error as e:
        print(f"Database error: {e}", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"Error during evaluation: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        return 1

if __name__ == "__main__":
    raise SystemExit(main())
