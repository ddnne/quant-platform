#!/usr/bin/env python3
"""W91 / w0818a — real COMPLETE-backed CF mass-eval + Nikkei vol logics + wide eval.

Defaults to **real** path (mode=r2_panels), NOT synthetic-as-final.

Pipeline
--------
1. Inventory COMPLETE-22 + permanent DEFER residual
2. Optional small strong-model hyp batch (quality, not mass)
3. Wide local eval on real mirrors (catalog after_dedup + nky vol + optional LLM)
4. Stage real multi-year panels → R2 → deploy Worker → CF mass-eval job
5. Write machine-readable packs under --out-dir

Does **not** arm Mass / READY / operational GO / continuous paper / live.
Does **not** retune the three frozen defaults.

Examples
--------
    uv run python scripts/run_w91_real_cf_mass_eval.py \\
        --out-dir .glm-logs/w0818a_w91_real_vol/

    uv run python scripts/run_w91_real_cf_mass_eval.py --skip-llm --skip-cf
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
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
        description="W91: real CF mass-eval + Nikkei vol + wide local eval"
    )
    p.add_argument(
        "--out-dir",
        type=str,
        default=str(ROOT / ".glm-logs" / "w0818a_w91_real_vol"),
    )
    p.add_argument("--seed", type=int, default=870816)
    p.add_argument(
        "--mode",
        type=str,
        default="r2_panels",
        choices=["r2_panels", "d1_bars", "synthetic", "nets_only"],
        help="CF panel mode (default r2_panels = real COMPLETE-backed)",
    )
    p.add_argument(
        "--synthetic",
        action="store_true",
        help="Force synthetic for local wide eval AND CF (smoke only; not final)",
    )
    p.add_argument("--skip-llm", action="store_true", default=True)
    p.add_argument(
        "--with-llm",
        action="store_true",
        help="Run optional small strong-model hyp batch (quality, not mass)",
    )
    p.add_argument("--n-hyps", type=int, default=4)
    p.add_argument("--skip-cf", action="store_true")
    p.add_argument("--skip-wide", action="store_true")
    p.add_argument("--skip-deploy", action="store_true")
    p.add_argument("--max-codes", type=int, default=15)
    p.add_argument("--max-days", type=int, default=120)
    p.add_argument(
        "--worker-url",
        type=str,
        default="https://quant-platform-research-mass-eval.taku-haga.workers.dev",
    )
    p.add_argument("--dry-run-r2", action="store_true")
    p.add_argument("--quiet", action="store_true")
    args = p.parse_args(argv)

    if args.with_llm:
        args.skip_llm = False

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    t0 = time.perf_counter()
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

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
        FROZEN_DEFAULT_PATH,
        generate_strategy_batch,
        run_batch_eval,
        MassFactoryConfig,
        write_factory_outputs,
    )
    from research.cf_mass_eval_job import (
        CF_MASS_EVAL_VERSION,
        CF_MASS_EVAL_WAVE,
        DEFAULT_W91_MODE,
        DEFAULT_REAL_MULTIYEAR_PERIODS,
        inventory_complete22,
        run_cf_mass_eval_job,
        try_cf_mass_eval_status,
        stage_real_panels_to_r2,
        build_real_period_panel,
    )

    mode = "synthetic" if args.synthetic else str(args.mode)
    job_id = f"w91-real-{ts}"

    log(
        f"[w91] {MASS_FACTORY_WAVE} · factory={MASS_FACTORY_VERSION} · "
        f"cf={CF_MASS_EVAL_VERSION} · seed={args.seed} · mode={mode}"
    )
    log(
        f"[w91] freezes: mass={MASS_RESEARCH} continuous_paper={CONTINUOUS_PAPER} "
        f"READY=False ops_GO=False frozen_defaults_retuned=False"
    )
    log(
        f"[w91] 3 defaults frozen: "
        + ", ".join(r["representative_id"] for r in FROZEN_DEFAULT_PATH)
    )

    inv = inventory_complete22()
    _dump(out_dir / "complete22_inventory.json", inv)
    log(
        f"[w91] COMPLETE22 n={inv.get('dataset_complete_n')} "
        f"defer={inv.get('permanent_defer_n')} "
        f"bars={inv.get('primary_bars_dataset')}"
    )

    cf_status = try_cf_mass_eval_status()
    _dump(out_dir / "cf_status.json", cf_status)
    log(f"[w91] CF status={cf_status.get('status')} default_mode={cf_status.get('default_mode')}")

    # ------------------------------------------------------------------ A. optional LLM (quality, not mass)
    llm_pack: dict = {}
    llm_accepted: list = []
    if not args.skip_llm:
        log(f"[w91] A: strong-model hyp gen n={args.n_hyps} (quality batch)")
        try:
            from research.llm_hyp_generator import (
                generate_and_evaluate_hypotheses,
                detect_api_keys,
            )

            keys = detect_api_keys()
            _dump(
                out_dir / "api_keys_present.json",
                {k: bool(v) for k, v in keys.items()},
            )
            llm_pack = generate_and_evaluate_hypotheses(
                n=int(args.n_hyps),
                evaluate=True,
                synthetic=bool(args.synthetic),
            )
            llm_accepted = list(llm_pack.get("accepted_proposals") or [])
            _dump(out_dir / "llm_hyp_generation.json", llm_pack)
            log(
                f"[w91] A done · model={llm_pack.get('model')} "
                f"n_proposed={llm_pack.get('n_proposed')} "
                f"n_accepted={llm_pack.get('n_accepted')} "
                f"n_evaluated={llm_pack.get('n_evaluated')}"
            )
        except Exception as exc:
            log(f"[w91] A failed (non-fatal): {exc}")
            _dump(out_dir / "llm_hyp_error.json", {"error": str(exc)})
    else:
        log("[w91] A: LLM skipped (default; pass --with-llm for small quality batch)")

    # ------------------------------------------------------------------ B. local wide real eval
    wide_pack: dict = {}
    if not args.skip_wide:
        log("[w91] B: wide local eval on REAL mirrors (catalog + nky vol)")
        cfg = MassFactoryConfig(
            seed=int(args.seed),
            n=100,
            max_codes=int(args.max_codes),
            max_days_per_period=int(args.max_days),
            use_q4_periods=True,
        )
        gen = generate_strategy_batch(cfg)
        strategies = list(gen.get("strategies_after_dedup") or [])
        # ensure nky templates present
        seen = {str(s.get("logic_id")) for s in strategies}
        for lid in (
            "nky_vol_abs_level",
            "nky_vol_term_levels",
            "nky_vol_term_ratio",
        ):
            if lid not in seen and lid in LOGIC_TEMPLATES:
                tpl = LOGIC_TEMPLATES[lid]
                strategies.append(
                    {
                        "strategy_id": f"msf_force_{lid}",
                        "logic_id": lid,
                        "family_id": tpl.family_id,
                        "params": dict(tpl.base_params),
                        "thesis": tpl.thesis,
                        "signal_definition": tpl.signal_definition,
                        "position_rule": tpl.position_rule,
                        "datasets_used": list(tpl.datasets_used),
                        "source": "w91_force_include",
                    }
                )
                seen.add(lid)
        # merge LLM accepted
        extra = 0
        for raw in llm_accepted:
            lid = str(raw.get("logic_id") or "")
            if not lid:
                continue
            if lid in seen:
                lid = f"{lid}__llm_{extra}"
                raw = {**dict(raw), "logic_id": lid}
            strategies.append(dict(raw))
            seen.add(lid)
            extra += 1

        gen_for_eval = {
            **gen,
            "strategies_after_dedup": strategies,
            "n_after_dedup": len(strategies),
        }
        batch = run_batch_eval(
            gen_for_eval,
            config=cfg,
            synthetic=bool(args.synthetic),
        )
        results = list(batch.get("results") or [])
        screens = list(batch.get("screens") or [])
        survivors = [s for s in screens if s.get("survived")]
        nky_rows = [
            r
            for r in results
            if str(r.get("logic_id") or "").startswith("nky_vol_")
        ]
        wide_pack = {
            "version": MASS_FACTORY_VERSION,
            "wave": MASS_FACTORY_WAVE,
            "kind": "local_wide_eval",
            "synthetic": bool(args.synthetic),
            "data_path": "synthetic" if args.synthetic else "real_mirrors",
            "n_catalog_after_dedup": int(gen.get("n_after_dedup") or 0),
            "n_evaluated": len(results),
            "n_survivors": len(survivors),
            "fail_rate": (
                1.0 - (len(survivors) / len(results)) if results else None
            ),
            "n_nky_logics": len(nky_rows),
            "nky_results": [
                {
                    "logic_id": r.get("logic_id"),
                    "status": r.get("status"),
                    "mean_net": r.get("mean_net"),
                    "t_stat": r.get("t_stat"),
                    "sharpe_period": r.get("sharpe_period"),
                    "chosen_sign": r.get("chosen_sign"),
                    "n_periods_ok": r.get("n_periods_ok"),
                    "survived": (r.get("screen") or {}).get("survived"),
                    "reject_reasons": (r.get("screen") or {}).get(
                        "reject_reasons"
                    ),
                }
                for r in nky_rows
            ],
            "ranking_top": (batch.get("ranking") or [])[:20],
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
                }
                for r in results
            ],
            "load_notes": (batch.get("load_notes") or {}),
            "frozen_defaults_retuned": False,
            "mass_research": MASS_RESEARCH,
            "continuous_paper": CONTINUOUS_PAPER,
        }
        _dump(out_dir / "wide_eval.json", wide_pack)
        log(
            f"[w91] B done · evaluated={wide_pack['n_evaluated']} "
            f"survivors={wide_pack['n_survivors']} "
            f"nky={wide_pack['n_nky_logics']} "
            f"path={wide_pack['data_path']}"
        )
        for row in wide_pack["nky_results"]:
            log(
                f"  · {row['logic_id']}: net={row['mean_net']} "
                f"t={row['t_stat']} survived={row['survived']} "
                f"reasons={row['reject_reasons']}"
            )
        try:
            write_factory_outputs(
                {
                    "summary": {
                        "n_after_dedup": len(strategies),
                        "n_unique_logic": gen.get("n_unique_logic"),
                        "wave": MASS_FACTORY_WAVE,
                    },
                    "generation": gen_for_eval,
                    "generation_strategies": gen.get("strategies") or [],
                    "strategies_after_dedup": strategies,
                    "batch_ranking": batch.get("ranking"),
                    "screens": batch.get("screens"),
                    "results_compact": wide_pack["results_compact"],
                },
                out_dir / "factory_wide",
            )
        except Exception as exc:
            log(f"[w91] write_factory_outputs skip: {exc}")
    else:
        log("[w91] B: wide local skipped")

    # ------------------------------------------------------------------ C. CF real mass-eval
    cf_pack: dict = {}
    if not args.skip_cf:
        log(f"[w91] C: CF mass-eval mode={mode} job_id={job_id}")
        # smoke one panel build for evidence
        sample_panel = build_real_period_panel(
            dict(DEFAULT_REAL_MULTIYEAR_PERIODS[0]),
            max_codes=int(args.max_codes),
            max_days=min(60, int(args.max_days)),
        )
        _dump(
            out_dir / "sample_real_panel_meta.json",
            {
                k: sample_panel.get(k)
                for k in (
                    "period_id",
                    "status",
                    "n_codes",
                    "n_days",
                    "source",
                    "dataset",
                    "bars_path",
                    "nky_proxy",
                    "nky_dataset",
                    "nky_n_closes",
                )
            },
        )
        log(
            f"[w91] sample panel {sample_panel.get('period_id')} "
            f"status={sample_panel.get('status')} "
            f"codes={sample_panel.get('n_codes')} "
            f"days={sample_panel.get('n_days')} "
            f"nky={sample_panel.get('nky_proxy')}"
        )

        # full catalog + nky for CF
        logic_ids = list(LOGIC_TEMPLATE_IDS)
        try:
            cf_pack = run_cf_mass_eval_job(
                job_id=job_id,
                logic_ids=logic_ids,
                periods=list(DEFAULT_REAL_MULTIYEAR_PERIODS),
                max_codes=int(args.max_codes),
                max_days=int(args.max_days),
                seed=int(args.seed),
                mode=mode,
                stage_panels=(mode == "r2_panels"),
                worker_url=args.worker_url,
                deploy_if_needed=not args.skip_deploy,
                dry_run_r2=bool(args.dry_run_r2),
                staging_dir=out_dir / "r2_stage" if args.dry_run_r2 else None,
            )
        except Exception as exc:
            log(f"[w91] C CF job error: {exc}")
            cf_pack = {
                "status": "error",
                "error": str(exc),
                "job_id": job_id,
                "mode": mode,
            }
        _dump(out_dir / "cf_mass_eval_job.json", cf_pack)
        wr = cf_pack.get("worker_response") or {}
        log(
            f"[w91] C done · status={cf_pack.get('status')} "
            f"job_id={cf_pack.get('job_id')} mode={cf_pack.get('mode') or mode} "
            f"n_logics={cf_pack.get('n_logics')} n_periods={cf_pack.get('n_periods')} "
            f"n_survivors={cf_pack.get('n_survivors')} "
            f"stage_ok={(cf_pack.get('stage_panels') or {}).get('n_ok')}"
        )
        if wr:
            _dump(out_dir / "cf_mass_eval_response.json", wr)
            # nky subset from CF results
            nky_cf = [
                r
                for r in (wr.get("results") or [])
                if str(r.get("logic_id") or "").startswith("nky_vol_")
            ]
            _dump(out_dir / "cf_nky_results.json", nky_cf)
            for r in nky_cf:
                log(
                    f"  · CF {r.get('logic_id')}: net={r.get('mean_net')} "
                    f"t={r.get('t_stat')} survived={(r.get('screen') or {}).get('survived')}"
                )
    else:
        log("[w91] C: CF skipped")

    # ------------------------------------------------------------------ summary
    remaining = {
        "synthetic_as_final": mode == "synthetic",
        "cf_mode": mode,
        "d1_bars_multi_year": False,
        "d1_note": "D1 is tip-only (~hot months); multi-year uses r2_panels staging",
        "nky_proxy": (wide_pack.get("load_notes") or {}).get("nky_vol_source")
        or (
            ((cf_pack.get("stage_panels") or {}).get("panels") or [{}])[0].get(
                "nky_proxy"
            )
        )
        or "topix_realized (ndjson) preferred; cash Nikkei not in indices_bars_daily",
        "nkvif_implied_not_wired": True,
        "rate_mf_full_factor_legs_on_cf_pure_ts": "fallback_mdh_or_local",
        "complete22_held": inv.get("dataset_complete_n") == 22,
        "permanent_defer": inv.get("permanent_defer"),
    }
    summary = {
        "wave": "W91 / w0818a",
        "job_id": cf_pack.get("job_id") or job_id,
        "mode": mode,
        "factory_version": MASS_FACTORY_VERSION,
        "cf_version": CF_MASS_EVAL_VERSION,
        "n_logic_templates": len(LOGIC_TEMPLATE_IDS),
        "nky_logic_ids": [
            "nky_vol_abs_level",
            "nky_vol_term_levels",
            "nky_vol_term_ratio",
        ],
        "wide": {
            "n_evaluated": wide_pack.get("n_evaluated"),
            "n_survivors": wide_pack.get("n_survivors"),
            "data_path": wide_pack.get("data_path"),
            "nky_results": wide_pack.get("nky_results"),
        },
        "cf": {
            "status": cf_pack.get("status"),
            "job_id": cf_pack.get("job_id"),
            "mode": cf_pack.get("mode") or mode,
            "n_logics": cf_pack.get("n_logics"),
            "n_periods": cf_pack.get("n_periods"),
            "n_survivors": cf_pack.get("n_survivors"),
            "period_ids": cf_pack.get("period_ids"),
            "r2_prefix": (cf_pack.get("artifact_paths") or {}).get("prefix"),
            "stage": cf_pack.get("stage_panels"),
            "datasets_used": [
                "equities_bars_daily",
                "indices_bars_daily_topix",
                "markets_calendar",
            ],
        },
        "complete22": inv,
        "freezes": {
            "mass_research": MASS_RESEARCH,
            "ready_declared": False,
            "operational_go": False,
            "continuous_paper": CONTINUOUS_PAPER,
            "phase7": "OFF",
            "frozen_defaults_retuned": False,
            "frozen_defaults": [
                r["representative_id"] for r in FROZEN_DEFAULT_PATH
            ],
        },
        "remaining_synthetic_unconnected": remaining,
        "wall_time_sec": round(time.perf_counter() - t0, 3),
    }
    _dump(out_dir / "w91_summary.json", summary)

    status_md = out_dir / "SUMMARY.md"
    status_md.write_text(
        "\n".join(
            [
                f"# W91 / w0818a run summary",
                "",
                f"- job_id: `{summary['job_id']}`",
                f"- mode: **{mode}** (default real r2_panels)",
                f"- wide evaluated: {summary['wide'].get('n_evaluated')} · "
                f"survivors: {summary['wide'].get('n_survivors')} · "
                f"path: {summary['wide'].get('data_path')}",
                f"- CF status: {summary['cf'].get('status')} · "
                f"n_logics={summary['cf'].get('n_logics')} · "
                f"n_periods={summary['cf'].get('n_periods')} · "
                f"survivors={summary['cf'].get('n_survivors')}",
                f"- R2 prefix: `{summary['cf'].get('r2_prefix')}`",
                f"- freezes: Mass={MASS_RESEARCH} READY=false ops_GO=false "
                f"continuous_paper={CONTINUOUS_PAPER} defaults frozen",
                f"- wall_s: {summary['wall_time_sec']}",
                "",
            ]
        ),
        encoding="utf-8",
    )
    log(f"[w91] wrote {out_dir / 'w91_summary.json'} wall={summary['wall_time_sec']}s")
    if mode == "synthetic":
        log("[w91] WARNING: synthetic mode — not final success path")
        return 2
    if not args.skip_cf and cf_pack.get("status") not in {
        "ok",
        "completed",
        "success",
    }:
        log(f"[w91] CF status not ok: {cf_pack.get('status')}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
