#!/usr/bin/env python3
"""Historical backfill driver with resume + honest logging.

Does NOT claim Coverage COMPLETE. Writes logs under .glm-logs/backfill/.
Fixes common footguns:
  - datasets that need ``date`` (not only from/to) get per-day expansion via
    the existing catalog expand_jobs path inside run_ingestion_once.
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
import subprocess
from datetime import date, datetime

ROOT = repo_root()
LOG_ROOT = ROOT / ".glm-logs" / "backfill"

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", type=Path, default=ROOT / "data/structured/ingestion.sqlite")
    ap.add_argument("--dataset", action="append", default=[], help="dataset id (repeatable)")
    ap.add_argument("--from-date", required=True)
    ap.add_argument("--to-date", required=True)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--chunk-days", type=int, default=30)
    ap.add_argument("--source", choices=["jquants", "jsda", "all"], default="jquants")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    LOG_ROOT.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%dT%H%M%S")
    ds = args.dataset or ["markets_calendar"]
    log = LOG_ROOT / f"hist_{stamp}_{'_'.join(ds)[:60]}.log"
    cmd = [
        str(ROOT / ".venv" / "bin" / "python"),
        "-u",
        str(ROOT / "scripts" / "run_ingestion_once.py"),
        "--source",
        args.source,
        "--runtime",
        "local",
        "--mode",
        "backfill",
        "--from-date",
        args.from_date,
        "--to-date",
        args.to_date,
        "--workers",
        str(args.workers),
        "--chunk-days",
        str(args.chunk_days),
        "--db",
        str(args.db),
    ]
    for d in ds:
        cmd.extend(["--dataset", d])

    meta = {
        "cmd": cmd,
        "started": stamp,
        "note": "Does not claim COMPLETE; run refresh_coverage_ledger after.",
    }
    (LOG_ROOT / f"hist_{stamp}_meta.json").write_text(json.dumps(meta, indent=2))
    print(json.dumps(meta, indent=2))
    if args.dry_run:
        return 0
    with log.open("w") as fh:
        fh.write(f"# {' '.join(cmd)}\n")
        fh.flush()
        proc = subprocess.run(cmd, stdout=fh, stderr=subprocess.STDOUT)
    print(f"log={log} exit={proc.returncode}")
    print("Next: python scripts/refresh_coverage_ledger.py && python scripts/backfill_status_report.py")
    return int(proc.returncode)

if __name__ == "__main__":
    raise SystemExit(main())
