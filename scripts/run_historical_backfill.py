#!/usr/bin/env python3
"""Historical backfill driver with resume + honest logging.

Default is **dry-run** (print planned command / CF queue). Pass ``--execute``
to run. Does NOT claim Coverage COMPLETE. Writes logs under .glm-logs/backfill/.

Two runtimes:
  * ``local`` — subprocess to ``run_ingestion_once.py`` (J-Quants via local/proxy)
  * ``cf``    — contract planner + range batch scheduler → CF premium ``/v1/run``

Fixes common footguns:
  - datasets that need ``date`` (not only from/to) get per-day expansion via
    the existing catalog expand_jobs path inside run_ingestion_once.
  - CF path uses date-range batch as standard (month segments).
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

_here = Path(__file__).resolve().parent
for _d in (_here, _here.parent):
    if (_d / "_bootstrap.py").is_file():
        if str(_d) not in sys.path:
            sys.path.insert(0, str(_d))
        break
from _bootstrap import ensure_repo_root

ROOT = ensure_repo_root()
LOG_ROOT = ROOT / ".glm-logs" / "backfill"


def _run_cf(args: argparse.Namespace) -> int:
    """Delegate to CF premium range-batch driver (same dry-run / --execute)."""
    cmd = [
        sys.executable,
        "-u",
        str(ROOT / "scripts" / "ops" / "cf_premium_backfill.py"),
        "--db",
        str(args.db),
        "--from-date",
        args.from_date,
        "--to-date",
        args.to_date,
        "--max-jobs",
        str(args.max_jobs),
        "--general-rpm",
        str(args.general_rpm),
        "--fins-rpm",
        str(args.fins_rpm),
    ]
    if args.execute and not args.dry_run:
        cmd.append("--execute")
    else:
        cmd.append("--dry-run")
    if args.track_a:
        cmd.append("--track-a")
    if args.latest_only:
        cmd.append("--latest-only")
    for d in args.dataset:
        # cf driver takes comma list once
        pass
    if args.dataset:
        cmd.extend(["--datasets", ",".join(args.dataset)])
    if args.workers:
        cmd.extend(["--workers", str(args.workers)])
    print(json.dumps({"runtime": "cf", "cmd": cmd}, indent=2))
    if args.dry_run and not args.execute:
        # Still invoke CF driver in dry-run so plan/queue artifacts are written.
        pass
    proc = subprocess.run(cmd)
    return int(proc.returncode)


def _run_local(args: argparse.Namespace) -> int:
    LOG_ROOT.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%dT%H%M%S")
    ds = args.dataset or ["markets_calendar"]
    log = LOG_ROOT / f"hist_{stamp}_{'_'.join(ds)[:60]}.log"
    py = ROOT / ".venv" / "bin" / "python"
    if not py.is_file():
        py = Path(sys.executable)
    cmd = [
        str(py),
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
    if args.personal_draft:
        cmd.append("--personal-draft")

    meta = {
        "cmd": cmd,
        "started": stamp,
        "runtime": "local",
        "mode": "execute" if (args.execute and not args.dry_run) else "dry-run",
        "note": (
            (
                "Personal DRAFT only; never issue or refresh governed "
                "Coverage/READY. "
                if args.personal_draft
                else "Does not claim COMPLETE; run refresh_coverage_ledger after. "
            )
            + "Default is dry-run; pass --execute to run ingestion."
        ),
    }
    (LOG_ROOT / f"hist_{stamp}_meta.json").write_text(
        json.dumps(meta, indent=2), encoding="utf-8"
    )
    print(json.dumps(meta, indent=2))
    if not args.execute or args.dry_run:
        print("dry-run complete (local). Re-run with --execute to ingest.")
        return 0
    with log.open("w", encoding="utf-8") as fh:
        fh.write(f"# {' '.join(cmd)}\n")
        fh.flush()
        proc = subprocess.run(cmd, stdout=fh, stderr=subprocess.STDOUT)
    print(f"log={log} exit={proc.returncode}")
    if args.personal_draft:
        print(
            "Personal DRAFT complete: no Coverage COMPLETE, receipt, or READY "
            "was issued. Validate observed rows before research."
        )
    else:
        print(
            "Next: python scripts/refresh_coverage_ledger.py && "
            "python scripts/backfill_status_report.py && "
            "python scripts/report_raw_throughput.py"
        )
    return int(proc.returncode)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", type=Path, default=None)
    ap.add_argument("--dataset", action="append", default=[], help="dataset id (repeatable)")
    ap.add_argument("--from-date", required=True)
    ap.add_argument("--to-date", required=True)
    ap.add_argument(
        "--workers",
        type=int,
        default=12,
        help="General pool workers for CF runtime (default 12)",
    )
    ap.add_argument("--chunk-days", type=int, default=30)
    ap.add_argument("--source", choices=["jquants", "jsda", "all"], default="jquants")
    ap.add_argument(
        "--runtime",
        choices=["local", "cf"],
        default="local",
        help="local=run_ingestion_once; cf=premium /v1/run via range batch scheduler",
    )
    ap.add_argument(
        "--execute",
        action="store_true",
        help="Actually run ingestion / CF posts (default: dry-run)",
    )
    ap.add_argument(
        "--personal-draft",
        action="store_true",
        help=(
            "local-only unsigned personal history; defaults to the dedicated "
            "personal-ingestion.sqlite database"
        ),
    )
    ap.add_argument(
        "--dry-run",
        action="store_true",
        help="Force dry-run (default when --execute omitted; wins over --execute)",
    )
    ap.add_argument("--track-a", action="store_true", help="CF: Track A dataset filter")
    ap.add_argument(
        "--latest-only",
        action="store_true",
        help="CF: one latest segment per dataset (e.g. margin interest refresh)",
    )
    ap.add_argument("--max-jobs", type=int, default=0, help="CF: cap queued jobs")
    ap.add_argument(
        "--general-rpm",
        type=float,
        default=495.0,
        help="General pool RPM near Premium ~500/min (default 495)",
    )
    ap.add_argument(
        "--fins-rpm",
        type=float,
        default=495.0,
        help="Fins separate rate pool (do not share with general; default 495)",
    )
    args = ap.parse_args(argv)

    if args.personal_draft:
        if args.runtime != "local":
            ap.error("--personal-draft requires --runtime local")
        if args.source != "jquants":
            ap.error("--personal-draft requires --source jquants")
        if not args.dataset:
            ap.error("--personal-draft requires at least one --dataset")
    if args.db is None:
        filename = (
            "personal-ingestion.sqlite"
            if args.personal_draft
            else "ingestion.sqlite"
        )
        args.db = ROOT / "data" / "structured" / filename

    # Default dry-run: --execute required for side effects.
    if not args.execute:
        args.dry_run = True

    if args.runtime == "cf":
        return _run_cf(args)
    return _run_local(args)


if __name__ == "__main__":
    raise SystemExit(main())
