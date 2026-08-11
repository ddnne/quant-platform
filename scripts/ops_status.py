#!/usr/bin/env python3
"""Offline coverage, quality-gate, validation, and READY snapshot status."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from paper_runtime import latest_ready_snapshot  # noqa: E402
from storage import coverage_gaps, coverage_summary  # noqa: E402


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
