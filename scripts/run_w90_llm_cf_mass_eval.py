#!/usr/bin/env python3
"""W90 / w0816y — strong-model hyp gen + CF multi-logic eval + wide local eval.

Pipeline (no human seeds):
  1. generate_and_evaluate_hypotheses (xAI grok-4.6 preferred)
  2. local wide eval (catalog after_dedup + LLM accepted)
  3. CF multi-logic × multi-period job (research-mass-eval Worker → R2)
  4. write machine-readable packs under --out-dir

Does **not** arm Mass / READY / operational GO / continuous paper / live.
Does **not** retune the three frozen defaults.

Examples
--------
    python scripts/run_w90_llm_cf_mass_eval.py \\
        --out-dir .glm-logs/w0816y_w90_llm_cf/

    python scripts/run_w90_llm_cf_mass_eval.py --synthetic --n-hyps 6
"""

from __future__ import annotations

import argparse
import json
import sys
import time
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


def _dump(path: Path, obj: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(obj, indent=2, default=str) + "\n", encoding="utf-8"
    )


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description="W90: LLM hyp gen + CF mass-eval + wide local eval"
    )
    p.add_argument(
        "--out-dir",
        type=str,
        default=str(ROOT / ".glm-logs" / "w0816y_w90_llm_cf"),
    )
    p.add_argument("--n-hyps", type=int, default=10)
    p.add_argument("--seed", type=int, default=870816)
    p.add_argument(
        "--synthetic",
        action="store_true",
        help="Synthetic bars for local eval (smoke)",
    )
    p.add_argument(
        "--provider",
        type=str,
        default="auto",
        help="auto|xai|openai|anthropic|glm|workers_ai|catalog_seed",
    )
    p.add_argument("--model", type=str, default=None)
    p.add_argument(
        "--skip-llm",
        action="store_true",
        help="Skip LLM gen (catalog wide eval + CF only)",
    )
    p.add_argument(
        "--skip-cf",
        action="store_true",
        help="Skip CF worker invoke",
    )
    p.add_argument(
        "--skip-wide",
        action="store_true",
        help="Skip local wide eval",
    )
    p.add_argument(
        "--max-codes",
        type=int,
        default=20,
    )
    p.add_argument(
        "--max-days",
        type=int,
        default=80,
    )
    p.add_argument(
        "--worker-url",
        type=str,
        default="https://quant-platform-research-mass-eval.taku-haga.workers.dev",
    )
    p.add_argument("--quiet", action="store_true")
    args = p.parse_args(argv)

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    t0 = time.perf_counter()

    def log(msg: str) -> None:
        if not args.quiet:
            print(msg, flush=True)

    from research.mass_strategy_factory import (
        MASS_FACTORY_VERSION,
        MASS_FACTORY_WAVE,
        MASS_RESEARCH,
        CONTINUOUS_PAPER,
        LOGIC_TEMPLATE_IDS,
        LOGIC_TEMPLATES,
        try_cf_minimal_mass_batch,
        llm_logic_entry_status,
        generate_strategy_batch,
        run_batch_eval,
        MassFactoryConfig,
        write_factory_outputs,
    )
    from research.llm_hyp_generator import (
        generate_and_evaluate_hypotheses,
        package_logics_for_cf_eval,
        run_cf_multi_logic_eval_job,
        detect_api_keys,
        LLM_HYP_VERSION,
    )

    log(
        f"[w90] {MASS_FACTORY_WAVE} · factory={MASS_FACTORY_VERSION} · "
        f"llm={LLM_HYP_VERSION} · seed={args.seed}"
    )
    log(
        f"[w90] freezes: mass={MASS_RESEARCH} continuous_paper={CONTINUOUS_PAPER} "
        f"READY=False ops_GO=False frozen_defaults_retuned=False"
    )

    keys = detect_api_keys()
    key_status = {k: bool(v) for k, v in keys.items()}
    log(f"[w90] api_keys_present={key_status}")
    _dump(out_dir / "api_keys_present.json", key_status)

    cf_status = try_cf_minimal_mass_batch()
    llm_status = llm_logic_entry_status()
    _dump(out_dir / "cf_status.json", cf_status)
    _dump(out_dir / "llm_status.json", llm_status)
    log(
        f"[w90] CF status={cf_status.get('status')} "
        f"worker={cf_status.get('worker')}"
    )
    log(
        f"[w90] LLM entry={llm_status.get('status')} "
        f"strong={llm_status.get('strong_model_entry')}"
    )

    # ------------------------------------------------------------------ A. LLM
    llm_pack: dict = {}
    llm_accepted: list = []
    if not args.skip_llm:
        log(f"[w90] A: strong-model hyp gen n={args.n_hyps} provider={args.provider}")
        llm_pack = generate_and_evaluate_hypotheses(
            n=int(args.n_hyps),
            provider=args.provider if args.provider != "auto" else None,
            model=args.model,
            worker_url=args.worker_url,
            evaluate=True,
            synthetic=bool(args.synthetic),
        )
        llm_accepted = list(llm_pack.get("accepted_proposals") or [])
        _dump(out_dir / "llm_hyp_generation.json", llm_pack)
        log(
            f"[w90] A done · model={llm_pack.get('model')} "
            f"provider={llm_pack.get('provider')} "
            f"n_proposed={llm_pack.get('n_proposed')} "
            f"n_accepted={llm_pack.get('n_accepted')} "
            f"n_evaluated={llm_pack.get('n_evaluated')} "
            f"n_survivors={llm_pack.get('n_survivors')}"
        )
        for th in (llm_pack.get("representative_theses") or [])[:6]:
            log(
                f"  · {th.get('logic_id')} [{th.get('family_id')}] "
                f"{(th.get('thesis') or '')[:100]}"
            )
    else:
        log("[w90] A: skipped (--skip-llm)")

    # ------------------------------------------------------------------ C. wide
    wide_pack: dict = {}
    if not args.skip_wide:
        log("[w90] C: wide local eval (catalog after_dedup + LLM accepted)")
        cfg = MassFactoryConfig(
            seed=int(args.seed),
            n=100,
            max_codes=int(args.max_codes),
            max_days_per_period=int(args.max_days),
            use_q4_periods=True,
        )
        gen = generate_strategy_batch(cfg)
        strategies = list(gen.get("strategies_after_dedup") or [])
        seen = {str(s.get("logic_id")) for s in strategies}
        n_llm_merged = 0
        for raw in llm_accepted:
            lid = str(raw.get("logic_id") or "")
            # Prefer unique strategy_id; allow parallel near-similar
            sid = str(raw.get("strategy_id") or "")
            if lid in seen and sid and any(
                str(s.get("strategy_id")) == sid for s in strategies
            ):
                continue
            if lid in seen:
                # keep as parallel under distinct strategy id
                raw = {
                    **dict(raw),
                    "logic_id": lid,
                    "strategy_id": sid
                    or f"llm_{lid}_{n_llm_merged}",
                    "source": raw.get("source") or "llm_merged",
                }
            strategies.append(dict(raw))
            seen.add(str(raw.get("logic_id")))
            n_llm_merged += 1

        gen_for_eval = {
            **gen,
            "strategies_after_dedup": strategies,
            "n_after_dedup": len(strategies),
        }

        def _cb(i: int, n: int, sid: str) -> None:
            if not args.quiet and (i == 1 or i == n or i % 5 == 0):
                print(f"[wide-eval] {i}/{n} {sid}", flush=True)

        batch = run_batch_eval(
            gen_for_eval,
            config=cfg,
            synthetic=bool(args.synthetic),
            progress_cb=_cb,
        )
        wide_pack = {
            "wave": MASS_FACTORY_WAVE,
            "kind": "local_wide_eval",
            "n_strategies": len(strategies),
            "n_catalog_after_dedup": int(gen.get("n_after_dedup") or 0),
            "n_llm_merged": n_llm_merged,
            "n_unique_logic_catalog": int(gen.get("n_unique_logic") or 0),
            "batch_summary": {
                k: batch[k]
                for k in batch
                if k not in {"results", "screens"}
            },
            "screens": batch.get("screens"),
            "ranking": batch.get("ranking"),
            "results_compact": [
                {
                    "strategy_id": r.get("strategy_id"),
                    "logic_id": r.get("logic_id"),
                    "family_id": r.get("family_id"),
                    "survived": (r.get("screen") or {}).get("survived"),
                    "mean_net": r.get("mean_net"),
                    "t_stat": r.get("t_stat"),
                    "sharpe_period": r.get("sharpe_period"),
                    "chosen_sign": r.get("chosen_sign"),
                    "n_periods_ok": r.get("n_periods_ok"),
                    "reject_reasons": (r.get("screen") or {}).get(
                        "reject_reasons"
                    ),
                    "source": r.get("source"),
                }
                for r in (batch.get("results") or [])
            ],
            "mass_research": MASS_RESEARCH,
            "continuous_paper": CONTINUOUS_PAPER,
            "frozen_defaults_retuned": False,
        }
        _dump(out_dir / "wide_eval.json", wide_pack)
        # also standard factory outputs for survivors table
        write_factory_outputs(
            {
                "version": MASS_FACTORY_VERSION,
                "wave": MASS_FACTORY_WAVE,
                "summary": {
                    **(batch if isinstance(batch, dict) else {}),
                    "n_generated": gen.get("n_generated"),
                    "n_unique_logic": gen.get("n_unique_logic"),
                    "n_after_dedup": len(strategies),
                    "n_strategies_evaluated": batch.get(
                        "n_strategies_evaluated"
                    ),
                    "n_survivors": batch.get("n_survivors"),
                    "fail_rate": batch.get("fail_rate"),
                    "wall_time_sec": batch.get("wall_time_sec"),
                    "n_llm_merged": n_llm_merged,
                    "continuous_paper": CONTINUOUS_PAPER,
                    "frozen_defaults_retuned": False,
                    "human_main_candidates_selected": False,
                },
                "generation": {
                    k: gen[k]
                    for k in gen
                    if k
                    not in {
                        "strategies",
                        "strategies_after_dedup",
                        "near_dup_dropped",
                        "gen_rejected",
                        "families_document",
                        "logic_templates_document",
                    }
                },
                "strategies_after_dedup": strategies,
                "batch_ranking": batch.get("ranking"),
                "batch_screens": batch.get("screens"),
                "batch_results": wide_pack["results_compact"],
                "batch": wide_pack["batch_summary"],
            },
            out_dir / "wide_factory",
        )
        sm = wide_pack["batch_summary"]
        log(
            f"[w90] C done · evaluated={sm.get('n_strategies_evaluated')} "
            f"survivors={sm.get('n_survivors')} "
            f"fail_rate={sm.get('fail_rate')} "
            f"wall_s={sm.get('wall_time_sec')} "
            f"llm_merged={n_llm_merged}"
        )
    else:
        log("[w90] C: skipped (--skip-wide)")

    # ------------------------------------------------------------------ B. CF
    cf_pack: dict = {}
    if not args.skip_cf:
        log("[w90] B: CF multi-logic multi-period mass-eval job")
        # Build logics for CF: catalog templates (bar-native + fallback) + LLM
        cf_logics: list[dict] = []
        # Prefer wide-eval results if available (nets_only capable via periods)
        if wide_pack.get("results_compact") and wide_pack.get("screens"):
            # Re-load full period_rows from batch if present via wide_factory
            # Fall back to packaging screens + catalog params
            from research.mass_strategy_factory import evaluate_one_strategy  # noqa: F401

            # Package from wide results_compact + catalog params
            for row in wide_pack.get("results_compact") or []:
                lid = str(row.get("logic_id") or "")
                tpl = LOGIC_TEMPLATES.get(lid)
                cf_logics.append(
                    {
                        "logic_id": lid,
                        "strategy_id": row.get("strategy_id"),
                        "family_id": row.get("family_id")
                        or (tpl.family_id if tpl else "multi_day_hold"),
                        "params": dict(tpl.base_params) if tpl else {},
                        "thesis": (tpl.thesis if tpl else "")[:200],
                        "source": row.get("source") or "wide_eval",
                        "mean_net": row.get("mean_net"),
                        "mean_gross": None,
                        "t_stat": row.get("t_stat"),
                        "sharpe_period": row.get("sharpe_period"),
                        "chosen_sign": row.get("chosen_sign"),
                        "mean_activation": None,
                    }
                )
        else:
            for lid in LOGIC_TEMPLATE_IDS:
                tpl = LOGIC_TEMPLATES[lid]
                cf_logics.append(
                    {
                        "logic_id": lid,
                        "family_id": tpl.family_id,
                        "params": dict(tpl.base_params),
                        "thesis": tpl.thesis,
                        "signal_definition": tpl.signal_definition,
                        "position_rule": tpl.position_rule,
                        "source": "catalog",
                    }
                )
            for raw in llm_accepted:
                cf_logics.append(dict(raw))

        job_id = (
            f"w90-wide-{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}"
        )
        cf_pack = run_cf_multi_logic_eval_job(
            cf_logics,
            job_id=job_id,
            worker_url=args.worker_url,
            seed=int(args.seed),
            mode="synthetic",  # lite multi-period on CF; real bars local
            notes={
                "wave": MASS_FACTORY_WAVE,
                "n_from_wide": len(cf_logics),
                "llm_model": llm_pack.get("model"),
                "note": (
                    "CF lite multi-period synthetic panels for multi-logic "
                    "batch evidence. Local wide eval uses real mirrors."
                ),
            },
        )
        _dump(out_dir / "cf_mass_eval_job.json", cf_pack)
        log(
            f"[w90] B done · job_id={cf_pack.get('job_id')} "
            f"path={cf_pack.get('path_used')} "
            f"status={cf_pack.get('status')} "
            f"n_logics={cf_pack.get('n_logics')} "
            f"n_eval={cf_pack.get('n_logics_evaluated')} "
            f"n_survivors={cf_pack.get('n_survivors')} "
            f"r2={cf_pack.get('r2_prefix')}"
        )
    else:
        log("[w90] B: skipped (--skip-cf)")

    # ------------------------------------------------------------------ summary
    wall = round(time.perf_counter() - t0, 3)
    summary = {
        "wave": MASS_FACTORY_WAVE,
        "factory_version": MASS_FACTORY_VERSION,
        "llm_version": LLM_HYP_VERSION,
        "seed": args.seed,
        "synthetic": bool(args.synthetic),
        "wall_time_sec": wall,
        "llm": {
            "model": llm_pack.get("model"),
            "provider": llm_pack.get("provider"),
            "n_proposed": llm_pack.get("n_proposed"),
            "n_accepted": llm_pack.get("n_accepted"),
            "n_evaluated": llm_pack.get("n_evaluated"),
            "n_survivors": llm_pack.get("n_survivors"),
            "representative_theses": llm_pack.get("representative_theses"),
        },
        "wide_eval": {
            "n_strategies": wide_pack.get("n_strategies"),
            "n_catalog_after_dedup": wide_pack.get("n_catalog_after_dedup"),
            "n_llm_merged": wide_pack.get("n_llm_merged"),
            "n_evaluated": (wide_pack.get("batch_summary") or {}).get(
                "n_strategies_evaluated"
            ),
            "n_survivors": (wide_pack.get("batch_summary") or {}).get(
                "n_survivors"
            ),
            "fail_rate": (wide_pack.get("batch_summary") or {}).get(
                "fail_rate"
            ),
            "wall_time_sec": (wide_pack.get("batch_summary") or {}).get(
                "wall_time_sec"
            ),
            "top_ranking": (wide_pack.get("ranking") or [])[:10],
        },
        "cf_job": {
            "job_id": cf_pack.get("job_id"),
            "path_used": cf_pack.get("path_used"),
            "status": cf_pack.get("status"),
            "n_logics": cf_pack.get("n_logics"),
            "n_periods": cf_pack.get("n_periods"),
            "n_logics_evaluated": cf_pack.get("n_logics_evaluated"),
            "n_survivors": cf_pack.get("n_survivors"),
            "r2_prefix": cf_pack.get("r2_prefix"),
            "r2_paths": cf_pack.get("r2_paths"),
            "worker_url": cf_pack.get("worker_url"),
        },
        "cf_status": {
            "status": cf_status.get("status"),
            "worker": cf_status.get("worker"),
            "endpoint": cf_status.get("endpoint"),
            "r2_prefix": cf_status.get("r2_prefix"),
        },
        "freezes": {
            "mass_research": MASS_RESEARCH,
            "continuous_paper": CONTINUOUS_PAPER,
            "ready_declared": False,
            "operational_go": False,
            "frozen_defaults_retuned": False,
            "human_main_candidates_selected": False,
        },
        "catalog_n_logic_templates": len(LOGIC_TEMPLATE_IDS),
        "out_dir": str(out_dir),
    }
    _dump(out_dir / "w90_summary.json", summary)

    # Markdown table of wide results
    lines = [
        f"# W90 / w0816y run summary",
        "",
        f"- wall_time_sec: **{wall}**",
        f"- model: **{llm_pack.get('model')}** ({llm_pack.get('provider')})",
        f"- n_proposed / accepted / evaluated: "
        f"**{llm_pack.get('n_proposed')}** / "
        f"**{llm_pack.get('n_accepted')}** / "
        f"**{llm_pack.get('n_evaluated')}**",
        f"- wide survivors: "
        f"**{(wide_pack.get('batch_summary') or {}).get('n_survivors')}** "
        f"/ evaluated "
        f"**{(wide_pack.get('batch_summary') or {}).get('n_strategies_evaluated')}**",
        f"- CF job_id: `{cf_pack.get('job_id')}` path=`{cf_pack.get('path_used')}`",
        f"- CF R2: `{cf_pack.get('r2_prefix')}`",
        f"- freezes: Mass={MASS_RESEARCH} continuous_paper={CONTINUOUS_PAPER} "
        f"READY=False ops_GO=False",
        "",
        "## Wide eval results (compact)",
        "",
        "| logic_id | family | survived | mean_net | t_stat | sharpe | sign | n_ok |",
        "|----------|--------|:--------:|---------:|-------:|-------:|:----:|-----:|",
    ]
    def _abs_t(row: dict) -> float:
        t = row.get("t_stat")
        try:
            if isinstance(t, dict):
                t = t.get("t_stat") or t.get("value") or 0
            return abs(float(t or 0))
        except (TypeError, ValueError):
            return 0.0

    def _fmt(v: object) -> str:
        if isinstance(v, float):
            return f"{v:.6g}"
        if isinstance(v, dict):
            return json.dumps(v, default=str)[:40]
        return str(v) if v is not None else ""

    for r in sorted(
        wide_pack.get("results_compact") or [],
        key=_abs_t,
        reverse=True,
    ):
        lines.append(
            f"| {r.get('logic_id')} | {r.get('family_id')} | "
            f"{'yes' if r.get('survived') else 'no'} | "
            f"{_fmt(r.get('mean_net'))} | {_fmt(r.get('t_stat'))} | "
            f"{_fmt(r.get('sharpe_period'))} | {r.get('chosen_sign')} | "
            f"{r.get('n_periods_ok')} |"
        )
    lines.append("")
    (out_dir / "SUMMARY.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    log(f"[w90] done · wall_s={wall} · out_dir={out_dir}")
    log(json.dumps(summary, indent=2, default=str)[:3000])

    # Success criteria: LLM ran or was skipped with reason; CF path is cf_worker
    ok_cf = (
        args.skip_cf
        or str(cf_pack.get("path_used") or "").startswith("cf_worker")
    )
    ok_llm = args.skip_llm or (
        int(llm_pack.get("n_proposed") or 0) >= 1
        and llm_pack.get("model") is not None
    )
    ok_wide = args.skip_wide or int(
        (wide_pack.get("batch_summary") or {}).get("n_strategies_evaluated")
        or 0
    ) >= 5
    return 0 if (ok_cf and ok_llm and ok_wide) else 2


if __name__ == "__main__":
    raise SystemExit(main())
