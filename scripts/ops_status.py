#!/usr/bin/env python3
"""Offline coverage, quality-gate, validation, and READY snapshot status."""

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

ROOT = repo_root()
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from paper_runtime import latest_ready_snapshot  # noqa: E402
from storage import coverage_gaps, coverage_summary  # noqa: E402

def _am_diagnostic(db_path: str | Path) -> dict:
    """Add diagnostic for equities_bars_daily_am null last_event_date.

    This detects when AM dataset has null observed_end but may have data,
    which indicates a data quality issue. Null dates before 2024-01-04 are
    expected — not an error. Null dates after that with row_count > 0 are
    suspicious and should be flagged.

    Returns a diagnostic dict that is honest about the AM state without
    claiming PASS when there's a potential problem.
    """
    from storage import read_dataset_coverage

    try:
        coverage = read_dataset_coverage(db_path, dataset="equities_bars_daily_am")
    except Exception:
        return {"error": "Cannot read AM dataset coverage"}

    if not coverage:
        return {"note": "AM dataset not found in coverage ledger"}

    am_row = coverage[0]
    observed_start = am_row.get("observed_start")
    observed_end = am_row.get("observed_end")
    row_count = am_row.get("row_count", 0)
    status = am_row.get("status", "UNKNOWN")

    diagnostic = {
        "dataset": "equities_bars_daily_am",
        "status": status,
        "row_count": row_count,
        "observed_start": observed_start,
        "observed_end": observed_end,
    }

    # AM dataset historical start per canonical contract
    am_expected_start = "2024-01-04"

    # Case 1: No data at all - expected before AM era
    if row_count == 0 and observed_end is None:
        diagnostic["diagnostic"] = "NO_DATA"
        diagnostic["note"] = f"AM data not yet ingested; expected from {am_expected_start}"
        return diagnostic

    # Case 2: Data exists but null observed_end - suspicious!
    if row_count > 0 and observed_end is None:
        diagnostic["diagnostic"] = "SUSPICIOUS"
        diagnostic["warning"] = f"AM has {row_count} rows but null observed_end"
        diagnostic["recommendation"] = "Check data quality and event_time values"
        return diagnostic

    # Case 3: Normal state - data with proper dates
    if row_count > 0 and observed_end is not None:
        diagnostic["diagnostic"] = "HEALTHY"
        return diagnostic

    # Case 4: Edge case - null dates but somehow no rows
    diagnostic["diagnostic"] = "UNKNOWN"
    diagnostic["note"] = "AM dataset in unexpected state"
    return diagnostic

def status(snapshot_dir: str | Path) -> dict:
    try:
        snapshot = latest_ready_snapshot(snapshot_dir)
    except FileNotFoundError:
        return {
            "snapshot": {"state": "NONE", "snapshot_id": None},
            "coverage": {"status": "UNKNOWN", "reason": "no READY snapshot"},
            "b0": {"status": "UNKNOWN", "reason": "no READY snapshot"},
            "validation": {"status": "UNKNOWN", "reason": "no READY snapshot"},
            "coverage_gaps": [],
            "am_diagnostic": {"error": "no READY snapshot"},
        }
    manifest = snapshot.manifest
    quality = manifest.get("quality", {})
    validations = list(manifest.get("validations", []))
    validation_failed = [row for row in validations if row.get("status") != "pass"]

    return {
        "snapshot": {
            "state": manifest.get("state"),
            "snapshot_id": snapshot.snapshot_id,
            "committed_at": manifest.get("committed_at"),
            "source_run": manifest.get("source_run"),
            "change_seq": manifest.get("change_seq"),
        },
        "coverage": coverage_summary(snapshot.db_path),
        "b0": {
            "status": quality.get("status", "UNKNOWN"),
            "policy_version": manifest.get("quality_policy_version"),
            "summary": quality.get("summary", {}),
        },
        "validation": {
            "status": "PASS" if validations and not validation_failed else "FAIL",
            "dataset_count": len(validations),
            "failures": validation_failed,
        },
        "coverage_gaps": coverage_gaps(snapshot.db_path),
        "am_diagnostic": _am_diagnostic(snapshot.db_path),
    }

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot-dir", default="data/research_snapshots")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    result = status(args.snapshot_dir)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    else:
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
