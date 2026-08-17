#!/usr/bin/env python3
"""W87 / w0816v — mass strategy factory batch runner.

Generate N>=100 diverse strategy specs across families and batch-evaluate
them (post-cost, both signs, t/Sharpe/activation). Research factory only.

Does **not** arm Mass / READY / operational GO / continuous paper / live.

Examples
--------
    python scripts/run_mass_strategy_batch.py --seed 870816 --n 100 \\
        --out-dir .glm-logs/w0816v_w87_mass/

    python scripts/run_mass_strategy_batch.py --synthetic --n 100 \\
        --out-dir /tmp/msf_syn
"""

from __future__ import annotations

import argparse
import json
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
from _bootstrap import ensure_repo_root

ROOT = ensure_repo_root()


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description="Mass strategy factory: generate + batch-eval (research only)"
    )
    p.add_argument("--seed", type=int, default=870816, help="RNG seed (reproducible IDs)")
    p.add_argument("--n", type=int, default=100, help="Number of strategies to generate")
    p.add_argument(
        "--out-dir",
        type=str,
        default=str(ROOT / ".glm-logs" / "w0816v_w87_mass"),
        help="Output directory for machine-readable results",
    )
    p.add_argument(
        "--synthetic",
        action="store_true",
        help="Use synthetic bars (no local mirrors; for smoke/tests)",
    )
    p.add_argument(
        "--max-codes",
        type=int,
        default=20,
        help="Max equity codes per period (lite eval)",
    )
    p.add_argument(
        "--max-days",
        type=int,
        default=80,
        help="Max trading days per period window",
    )
    p.add_argument(
        "--full-periods",
        action="store_true",
        help="Prefer full-year periods instead of Q4 lite windows",
    )
    p.add_argument(
        "--paper-sample-k",
        type=int,
        default=0,
        help="Record top-k ids for optional short paper (not run; continuous UNARMED)",
    )
    p.add_argument(
        "--one-way-cost",
        type=float,
        default=0.001,
        help="One-way transaction cost",
    )
    p.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress progress lines",
    )
    p.add_argument(
        "--generate-only",
        action="store_true",
        help="Only generate specs (no eval)",
    )
    args = p.parse_args(argv)

    from research.mass_strategy_factory import (
        MASS_FACTORY_VERSION,
        MASS_FACTORY_WAVE,
        MASS_RESEARCH,
        CONTINUOUS_PAPER,
        MassFactoryConfig,
        generate_strategy_batch,
        run_mass_factory,
        write_factory_outputs,
        family_definitions_document,
    )

    cfg = MassFactoryConfig(
        seed=int(args.seed),
        n=int(args.n),
        max_codes=int(args.max_codes),
        max_days_per_period=int(args.max_days),
        use_q4_periods=not bool(args.full_periods),
        paper_sample_k=int(args.paper_sample_k),
        one_way_cost=float(args.one_way_cost),
    )
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    print(
        f"[mass-factory] {MASS_FACTORY_WAVE} · {MASS_FACTORY_VERSION} · "
        f"seed={cfg.seed} n={cfg.n} synthetic={args.synthetic}",
        flush=True,
    )
    print(
        f"[mass-factory] freezes: mass={MASS_RESEARCH} continuous_paper={CONTINUOUS_PAPER} "
        f"READY=False ops_GO=False",
        flush=True,
    )

    if args.generate_only:
        gen = generate_strategy_batch(cfg)
        paths = write_factory_outputs(
            {
                "version": MASS_FACTORY_VERSION,
                "wave": MASS_FACTORY_WAVE,
                "summary": {
                    "n_requested": gen.get("n_requested"),
                    "n_generated_accepted": gen.get("n_generated_accepted"),
                    "n_ge_100": gen.get("n_ge_100"),
                    "n_families_used": gen.get("n_families_used"),
                    "anti_bias_ok": gen.get("anti_bias_ok"),
                    "family_distribution": gen.get("family_distribution"),
                    "n_survivors": None,
                    "fail_rate": None,
                    "wall_time_sec": None,
                    "generate_only": True,
                    "continuous_paper": CONTINUOUS_PAPER,
                    "human_main_candidates_selected": False,
                },
                "generation": {
                    k: gen[k]
                    for k in gen
                    if k not in {"strategies", "gen_rejected", "families_document"}
                },
                "generation_strategies": gen.get("strategies"),
                "generation_rejected": gen.get("gen_rejected"),
                "families": family_definitions_document(),
                "batch_ranking": [],
                "batch_screens": [],
                "batch_results": [],
                "batch": {},
            },
            out_dir,
        )
        print(json.dumps({
            "n_generated_accepted": gen.get("n_generated_accepted"),
            "n_ge_100": gen.get("n_ge_100"),
            "family_distribution": gen.get("family_distribution"),
            "out_dir": str(out_dir),
            "paths": paths,
        }, indent=2))
        return 0 if gen.get("n_ge_100") or gen.get("n_generated_accepted", 0) >= args.n else 1

    pack = run_mass_factory(
        config=cfg,
        synthetic=bool(args.synthetic),
        out_dir=out_dir,
        progress=not args.quiet,
    )
    sm = pack.get("summary") or {}
    print(
        f"[mass-factory] done · accepted={sm.get('n_generated_accepted')} "
        f"N>=100={sm.get('n_ge_100')} survivors={sm.get('n_survivors')} "
        f"fail_rate={sm.get('fail_rate')} wall_s={sm.get('wall_time_sec')}",
        flush=True,
    )
    print(f"[mass-factory] out_dir={out_dir}", flush=True)
    # exit 0 if we achieved N>=100 generated (eval fail-one is soft)
    ok = bool(sm.get("n_ge_100")) or int(sm.get("n_generated_accepted") or 0) >= int(args.n)
    return 0 if ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
