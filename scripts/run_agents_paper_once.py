#!/usr/bin/env python3
"""Run the complete offline Phase 6 role-agent paper pipeline once."""

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
import os

_REPO_ROOT = str(repo_root())
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from agents import AgentPaperPipeline  # noqa: E402
from agents.strategist import StrategistAgent  # noqa: E402
from risk import JsonRiskStore  # noqa: E402
from strategies.paper import JsonPaperStore, PaperRunConfig  # noqa: E402

def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run deterministic research roles, a declarative StrategySpec, "
            "the PIT paper engine, and an independent risk audit. No network "
            "or broker is used."
        )
    )
    parser.add_argument("--db", default="data/structured/ingestion.sqlite")
    parser.add_argument("--start", required=True, help="First date (YYYY-MM-DD).")
    parser.add_argument("--end", required=True, help="Last date (YYYY-MM-DD).")
    parser.add_argument("--universe", required=True, help="Comma-separated codes.")
    parser.add_argument("--momentum-n", type=int, default=5)
    parser.add_argument("--top-k", type=int, default=1)
    parser.add_argument("--cost-bps", type=float, default=5.0)
    parser.add_argument("--starting-capital", type=float, default=1_000_000.0)
    parser.add_argument("--lookback-days", type=int, default=45)
    parser.add_argument("--paper-output", default="data/paper")
    parser.add_argument("--risk-output", default="data/risk/audits")
    return parser

def _codes(value: str) -> tuple[str, ...]:
    codes = tuple(code.strip() for code in value.split(",") if code.strip())
    if not codes:
        raise ValueError("--universe must contain at least one code")
    return codes

def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    try:
        universe = _codes(args.universe)
    except ValueError as exc:
        parser.error(str(exc))
    pipeline = AgentPaperPipeline(
        paper_store=JsonPaperStore(args.paper_output),
        risk_store=JsonRiskStore(args.risk_output),
        strategist=StrategistAgent(momentum_n=args.momentum_n, top_k=args.top_k),
    )
    result = pipeline.run(
        PaperRunConfig(
            start=args.start,
            end=args.end,
            db_path=Path(args.db),
            universe=universe,
            cost_bps=args.cost_bps,
            starting_capital=args.starting_capital,
            lookback_days=args.lookback_days,
        )
    )
    print(
        json.dumps(
            {
                "strategy_id": result.strategy_spec.strategy_id,
                "experiment_id": result.paper_result.experiment_id,
                "paper_result": str(result.paper_result_path),
                "risk_audit_id": result.risk_audit.audit_id,
                "risk_status": result.risk_audit.status,
                "risk_audit": str(result.risk_audit_path),
            },
            sort_keys=True,
        )
    )
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
