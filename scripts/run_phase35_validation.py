#!/usr/bin/env python3
"""Phase 3.5 — validation matrix CLI runner.

Runs the catalog checks in ``cf_platform.ingest_premium.matrix`` against a
local PIT SQLite DB and prints the results. Exit 0 if no check failed;
exit 1 if any check failed (``skip`` / ``warn`` are tolerated).

Offline by design — never touches the network or Cloudflare. Pair with
``scripts/sync_d1_to_sqlite.py`` to first build a local mirror of the CF D1
DB, then run this against it.

P0-2 honesty add-ons:

* The CLI always persists the full result set under
  ``data/reports/validation_YYYYMMDD_HHMMSS.json`` so an operator can audit
  what the runner saw even after the DB is re-synced.
* ``--require-implemented`` (default **True** for ``--tier weekly``,
  default **False** for ``--tier daily``) treats a ``skip`` with
  ``reason_code == "not_implemented"`` as a failure. The weekly tier
  therefore fails until every weekly check has a real implementation; the
  daily tier tolerates stubs. ``reason_code == "needs_r2"`` is exempt.

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

ROOT = ensure_repo_root()

from cf_platform.ingest_premium.coverage import (  # noqa: E402
    has_failures,
    not_implemented_skips,
    persist_report,
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
        "--reports-dir",
        default=str(ROOT / "data" / "reports"),
        help="Directory for persisted JSON reports (default: data/reports).",
    )
    p.add_argument(
        "--no-persist-report",
        action="store_true",
        help="Skip writing the JSON report under data/reports/.",
    )
    # ``--require-implemented`` defaults to True for the weekly tier and
    # False for the daily tier; the tri-state below captures "user did not
    # pass either flag" (None) so main() can apply the per-tier default.
    req_group = p.add_mutually_exclusive_group()
    req_group.add_argument(
        "--require-implemented",
        action="store_const",
        const=True,
        default=None,
        dest="require_implemented",
        help="Treat skip+not_implemented as failure (weekly default).",
    )
    req_group.add_argument(
        "--allow-not-implemented",
        action="store_const",
        const=False,
        default=None,
        dest="require_implemented",
        help="Tolerate skip+not_implemented (daily default).",
    )
    # ``--strict-live-gates`` defaults to True when QP_LIVE=1 (production
    # runs must enforce LIVE_GATES). The explicit ``--no-strict-live-gates``
    # flag overrides that for one-shot diagnostic runs.
    strict_group = p.add_mutually_exclusive_group()
    strict_group.add_argument(
        "--strict-live-gates",
        action="store_const",
        const=True,
        default=None,
        dest="strict_live_gates",
        help="Fail if master/bars issuer counts below live order-of-magnitude gates.",
    )
    strict_group.add_argument(
        "--no-strict-live-gates",
        action="store_const",
        const=False,
        default=None,
        dest="strict_live_gates",
        help="Disable strict live gates (overrides the QP_LIVE=1 default).",
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

def _print_text(results, *, require_implemented: bool) -> None:
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
    ni = not_implemented_skips(results)
    if ni:
        note = (
            "FAIL (require-implemented)" if require_implemented else "tolerated"
        )
        print(
            f"not_implemented skips: {len(ni)} "
            f"({'; '.join(sorted({r.check_id for r in ni}))}) — {note}"
        )

def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    # Resolve the tri-state --strict-live-gates. Explicit flag wins; else
    # default to True when QP_LIVE=1 so live runs enforce LIVE_GATES.
    if args.strict_live_gates is None:
        args.strict_live_gates = os.environ.get("QP_LIVE", "") == "1"
    # Resolve the tri-state --require-implemented. Explicit flag wins; else
    # default to True for the weekly tier (completion mode) and False for
    # the daily tier (nightly soft path).
    if args.require_implemented is None:
        args.require_implemented = args.tier == "weekly"

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
        _print_text(results, require_implemented=args.require_implemented)

    # Persist the JSON report unless explicitly disabled. The reports dir
    # is gitignored (data/reports/* but keep .gitkeep).
    report_path: Path | None = None
    if not args.no_persist_report:
        try:
            report_path = persist_report(
                results,
                tier=args.tier,
                db_path=args.db,
                reports_dir=args.reports_dir,
            )
        except OSError as exc:
            # Don't let a non-writable reports dir mask the actual result.
            print(f"[warn] could not persist validation report: {exc}",
                  file=sys.stderr)
    if report_path is not None:
        print(f"[ok] validation report: {report_path}")

    return 1 if has_failures(results,
                             require_implemented=args.require_implemented) else 0

if __name__ == "__main__":
    sys.exit(main())
