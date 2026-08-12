#!/usr/bin/env python3
"""Backfill status report — summarize coverage gaps vs contracts.

This script reports:
- Contract coverage (governed vs experimental)
- Missing historical segments by dataset
- Observed vs expected start/end dates
- Receipt completeness (raw retention, pagination exhaustion)

Usage:
    python scripts/backfill_status_report.py --db data/structured/ingestion.sqlite
    python scripts/backfill_status_report.py --db data/structured/ingestion.sqlite --snapshot-dir data/research_snapshots
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
from dataclasses import asdict
from datetime import date

ROOT = repo_root()
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from data_contracts import (
    all_canonical_datasets,
    all_coverage_contracts,
    governed_datasets,
)
from storage import coverage_gaps, coverage_summary, read_dataset_coverage

def backfill_status(db_path: str | Path) -> dict:
    """Generate comprehensive backfill status vs contracts."""
    try:
        dataset_coverage = read_dataset_coverage(db_path)
    except Exception as exc:
        return {
            "error": f"Cannot read dataset coverage: {exc}",
            "db_path": str(db_path),
        }

    contracts = {c.dataset_id: c for c in all_coverage_contracts()}
    canonical = {c.dataset_id: c for c in all_canonical_datasets()}

    # Build summary by governance tier
    governed_contracts = [c for c in all_coverage_contracts()
                         if c.governance_tier == "governed"]
    experimental_contracts = [c for c in all_coverage_contracts()
                             if c.governance_tier == "experimental"]

    # Analyze gaps
    gaps = coverage_gaps(db_path)

    # Categorize gaps by reason
    missing_data = []
    missing_receipts = []
    stale = []
    failed = []

    for gap in gaps:
        status = gap.get("status", "UNKNOWN")
        if status == "FAILED":
            failed.append(gap)
        elif status == "STALE":
            stale.append(gap)
        elif gap.get("row_count", 0) == 0:
            missing_data.append(gap)
        else:
            missing_receipts.append(gap)

    # Build detailed status per governed dataset
    governed_status = []
    for contract in governed_contracts:
        dataset_id = contract.dataset_id
        coverage_row = next((row for row in dataset_coverage
                            if row["dataset"] == dataset_id), None)

        canonical_info = canonical.get(dataset_id)
        expected_start = canonical_info.historical_start if canonical_info else None

        status_detail = {
            "dataset_id": dataset_id,
            "display_name": canonical_info.display_name if canonical_info else dataset_id,
            "contract_status": coverage_row["status"] if coverage_row else "UNKNOWN",
            "historical_start": expected_start,
            "observed_start": coverage_row.get("observed_start") if coverage_row else None,
            "observed_end": coverage_row.get("observed_end") if coverage_row else None,
            "row_count": coverage_row.get("row_count", 0) if coverage_row else 0,
            "segment_granularity": contract.segment_granularity,
            "coverage_mode": contract.coverage_mode,
        }

        # Add gap analysis
        if coverage_row and coverage_row["status"] != "COMPLETE":
            detail_json = coverage_row.get("detail_json")
            if detail_json:
                try:
                    detail = json.loads(detail_json) if isinstance(detail_json, str) else detail_json
                    status_detail["gap_reason"] = detail.get("reason", "unknown")
                except (json.JSONDecodeError, TypeError):
                    status_detail["gap_reason"] = "parse_error"

        governed_status.append(status_detail)

    # Special handling for AM dataset
    am_status = next((s for s in governed_status if s["dataset_id"] == "equities_bars_daily_am"), None)
    if am_status:
        if am_status["observed_end"] is None and am_status["row_count"] == 0:
            am_status["note"] = "AM dataset null dates are expected before 2024-01-04"
        elif am_status["observed_end"] is None and am_status["row_count"] > 0:
            am_status["note"] = "WARNING: AM data exists but null observed_end may indicate data quality issue"

    return {
        "db_path": str(db_path),
        "summary": coverage_summary(db_path),
        "contracts": {
            "governed_count": len(governed_contracts),
            "experimental_count": len(experimental_contracts),
            "total_contracts": len(all_coverage_contracts()),
        },
        "gaps": {
            "total": len(gaps),
            "missing_data": len(missing_data),
            "missing_receipts": len(missing_receipts),
            "stale": len(stale),
            "failed": len(failed),
        },
        "governed_status": governed_status,
        "am_diagnostic": am_status if am_status else None,
    }

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default="data/structured/ingestion.sqlite",
                       help="Path to SQLite database")
    parser.add_argument("--snapshot-dir", default="data/research_snapshots",
                       help="Path to research snapshots directory")
    parser.add_argument("--json", action="store_true",
                       help="Output JSON (default: pretty JSON)")
    args = parser.parse_args(argv)

    result = backfill_status(args.db)

    if args.json:
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    else:
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))

    # Exit with error if there are critical gaps
    if result.get("gaps", {}).get("failed", 0) > 0:
        return 1
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
