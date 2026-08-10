#!/usr/bin/env python3
"""Phase 3.5 — validation matrix CLI runner.

Runs the catalog checks in ``cf_platform.ingest_premium.matrix`` against a
local PIT SQLite DB and prints the results. Exit 0 if no check failed;
exit 1 if any check failed (``skip`` / ``warn`` are tolerated).

Offline by design — never touches the network or Cloudflare. Pair with
``scripts/sync_d1_to_sqlite.py`` to first build a local mirror of the CF D1
DB, then run this against it.

Examples
--------
  # Daily tier, default:
  python3 scripts/run_phase35_validation.py --db data/structured/ingestion.sqlite

  # Weekly tier (full catalog), machine-readable:
  python3 scripts/run_phase35_validation.py --db ./ingestion.sqlite \\
      --tier weekly --json

  # Supply an X4 sidecar (mapping of dataset -> rows_inserted):
  python3 scripts/run_phase35_validation.py --db ./ingestion.sqlite \\
      --validation-json ./validation_rows.json
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from cf_platform.ingest_premium.coverage import (  # noqa: E402
    has_failures,
    run_coverage,
    summarize,
)


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Phase 3.5 validation matrix runner")
    p.add_argument(
        "--db",
        required=True,
        help="Local PIT SQLite DB path (read-only).",
    )
    p.add_argument(
        "--tier",
        choices=("daily", "weekly"),
        default="daily",
        help="Which execution tier to run (default: daily).",
    )
    p.add_argument(
        "--today",
        default=None,
        help="Reference date for C8 freshness (ISO 8601). "
             "Defaults to latest ingested_at in the DB.",
    )
    p.add_argument(
        "--freshness-days",
        type=int,
        default=None,
        help="Override C8 max freshness window (default: 7 calendar days).",
    )
    p.add_argument(
        "--validation-json",
        default=None,
        help="Path to a JSON sidecar {dataset: rows_inserted} for X4.",
    )
    p.add_argument(
        "--json",
        dest="as_json",
        action="store_true",
        help="Emit JSON instead of human-readable text.",
    )
    p.add_argument(
        "--datasets",
        default=None,
        help="Comma-separated dataset ids to scope (default: Premium core 23).",
    )
    p.add_argument(
        "--workers",
        type=int,
        default=None,
        help="Parallel check-family workers (default: QP_VAL_WORKERS or 4).",
    )
    p.add_argument(
        "--strict-live-gates",
        action="store_true",
        help="Fail if master/bars issuer counts below live order-of-magnitude gates.",
    )
    return p


def _load_validation_sidecar(path: str | None) -> dict[str, int] | None:
    if not path:
        return None
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"validation sidecar not found: {path}")
    with p.open(encoding="utf-8") as fh:
        obj = json.load(fh)
    if not isinstance(obj, dict):
        raise ValueError("validation sidecar must be a JSON object {dataset: int}")
    return {str(k): int(v) for k, v in obj.items()}


def _print_text(results) -> None:
    # Group by check_id then dataset for stable, readable output.
    width_id = max((len(r.check_id) for r in results), default=4)
    width_ds = max((len(r.dataset or "-") for r in results), default=7)
    print(f"{'ID':<{width_id}}  {'dataset':<{width_ds}}  status   detail")
    print("-" * (width_id + width_ds + 30))
    for r in sorted(results, key=lambda x: (x.check_id, x.dataset or "")):
        ds = r.dataset or "-"
        print(f"{r.check_id:<{width_id}}  {ds:<{width_ds}}  {r.status:<7}  {r.detail}")
    counts = summarize(results)
    print("-" * (width_id + width_ds + 30))
    print(f"summary: pass={counts.get('pass', 0)} "
          f"fail={counts.get('fail', 0)} "
          f"skip={counts.get('skip', 0)} "
          f"warn={counts.get('warn', 0)}")


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    sidecar = _load_validation_sidecar(args.validation_json)
    datasets = (
        [s.strip() for s in args.datasets.split(",") if s.strip()]
        if args.datasets else None
    )
    freshness = args.freshness_days if args.freshness_days is not None else None
    results = run_coverage(
        args.db,
        tier=args.tier,
        today=args.today,
        freshness_days=freshness if freshness is not None else 7,
        validation_sidecar=sidecar,
        datasets=datasets,
        workers=args.workers,
        strict_live_gates=args.strict_live_gates,
    )
    if args.as_json:
        # `default=str` keeps any stray non-JSON values from crashing output.
        print(json.dumps(
            [r.as_log_dict() for r in results],
            indent=2, sort_keys=True, default=str,
        ))
    else:
        _print_text(results)
    return 1 if has_failures(results) else 0


if __name__ == "__main__":
    sys.exit(main())
