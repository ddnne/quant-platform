#!/usr/bin/env python3
"""Run and persist one feature-driven paper backtest (no network/broker)."""

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

from strategies.examples import (  # noqa: E402
    MomentumFeatureStrategy,
    Return1dFeatureStrategy,
)
from strategies.paper import (  # noqa: E402
    JsonPaperStore,
    Lifecycle,
    PaperRunConfig,
    format_paper_report,
    run_paper,
)

def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run one offline Paper research backtest through features + core; "
            "this command never contacts a broker or external API."
        )
    )
    parser.add_argument(
        "--db",
        default="data/structured/ingestion.sqlite",
        help="Local structured PIT database (default: data/structured/ingestion.sqlite).",
    )
    parser.add_argument("--start", required=True, help="First date (YYYY-MM-DD).")
    parser.add_argument("--end", required=True, help="Last date (YYYY-MM-DD).")
    parser.add_argument(
        "--strategy",
        choices=("return-1d", "momentum"),
        default="return-1d",
        help="Bundled feature strategy (default: return-1d).",
    )
    parser.add_argument(
        "--universe",
        required=True,
        help="Comma-separated equity codes; explicit is preferred for reproduction.",
    )
    parser.add_argument(
        "--execution-mode",
        choices=("next_close", "same_day_close"),
        default="next_close",
    )
    parser.add_argument("--cost-bps", type=float, default=5.0)
    parser.add_argument("--starting-capital", type=float, default=1_000_000.0)
    parser.add_argument("--lookback-days", type=int, default=30)
    parser.add_argument(
        "--lifecycle",
        choices=tuple(member.value for member in Lifecycle),
        default=Lifecycle.PAPER.value,
    )
    parser.add_argument("--threshold", type=float, default=0.0)
    parser.add_argument("--momentum-n", type=int, default=20)
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--min-momentum", type=float, default=0.0)
    parser.add_argument(
        "--output-dir",
        default="data/paper",
        help="JSON result root (default: data/paper).",
    )
    parser.add_argument(
        "--no-save", action="store_true", help="Run and report without writing JSON."
    )
    parser.add_argument(
        "--json", action="store_true", help="Print a machine-readable summary."
    )
    return parser

def _codes(value: str) -> tuple[str, ...]:
    codes = tuple(code.strip() for code in value.split(",") if code.strip())
    if not codes:
        raise ValueError("--universe must contain at least one code")
    return codes

def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        universe = _codes(args.universe)
    except ValueError as exc:
        _parser().error(str(exc))

    db_path = Path(args.db)
    if args.strategy == "momentum":
        strategy = MomentumFeatureStrategy(
            n=args.momentum_n,
            top_k=args.top_k,
            min_momentum=args.min_momentum,
        )
    else:
        strategy = Return1dFeatureStrategy(threshold=args.threshold)

    config = PaperRunConfig(
        start=args.start,
        end=args.end,
        db_path=db_path,
        universe=universe,
        execution_mode=args.execution_mode,
        cost_bps=args.cost_bps,
        starting_capital=args.starting_capital,
        lookback_days=args.lookback_days,
        lifecycle=args.lifecycle,
    )
    result = run_paper(strategy, config)
    saved_path = None
    if not args.no_save:
        saved_path = JsonPaperStore(args.output_dir).save(result)

    if args.json:
        summary = {
            "experiment_id": result.experiment_id,
            "run_id": result.run_id,
            "lifecycle": result.lifecycle.value,
            "strategy_id": result.metadata["strategy_id"],
            "metrics": result.metrics,
            "saved_path": str(saved_path) if saved_path is not None else None,
        }
        print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    else:
        print(format_paper_report(result))
        print(f"Saved: {saved_path}" if saved_path is not None else "Saved: no (--no-save)")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
