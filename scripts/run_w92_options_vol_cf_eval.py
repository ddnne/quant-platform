#!/usr/bin/env python3
"""W92 / w0818b — CF wire options_225 BaseVol/ATM/spread panels + real mass-eval.

Canonical Nikkei vol SoT = ``derivatives_bars_daily_options_225`` (COMPLETE).
W91 ``nky_vol_*`` TOPIX/NK225F RV remains proxy/compare only.

Defaults to **real** path (mode=r2_panels), NOT synthetic-as-final.

Does **not** arm Mass / READY / operational GO / continuous paper / live.
Does **not** retune the three frozen default-path representatives.

Examples
--------
    uv run python scripts/run_w92_options_vol_cf_eval.py \\
        --out-dir .glm-logs/w0818b_w92_options_vol/

    uv run python scripts/run_w92_options_vol_cf_eval.py --skip-cf
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

OPT225_LOGIC_IDS: tuple[str, ...] = (
    "opt225_basevol_abs_level",
    "opt225_basevol_term_levels",
    "opt225_basevol_term_ratio",
    "opt225_atm_iv_abs_level",
    "opt225_atm_iv_term_levels",
    "opt225_atm_iv_term_ratio",
    "opt225_iv_base_spread_abs",
    "opt225_iv_base_spread_change",
)


def _dump(path: Path, obj: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(obj, indent=2, default=str) + "\n", encoding="utf-8"
    )


def _compact_row(r: dict) -> dict:
    return {
        "logic_id": r.get("logic_id"),
        "family_id": r.get("family_id"),
        "status": r.get("status"),
        "mean_net": r.get("mean_net"),
        "t_stat": r.get("t_stat"),
        "sharpe_period": r.get("sharpe_period"),
        "chosen_sign": r.get("chosen_sign"),
        "n_periods_ok": r.get("n_periods_ok"),
        "survived": (r.get("screen") or {}).get("survived"),
        "reject_reasons": (r.get("screen") or {}).get("reject_reasons"),
    }


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description="W92: options_225 BaseVol/ATM/spread + real CF mass-eval"
    )
    p.add_argument(
        "--out-dir",
        type=str,
        default=str(ROOT / ".glm-logs" / "w0818b_w92_options_vol"),
    )
    p.add_argument("--seed", type=int, default=870818)
    p.add_argument(
        "--mode",
        type=str,
        default="r2_panels",
        choices=["r2_panels", "d1_bars", "synthetic", "nets_only"],
    )
    p.add_argument("--synthetic", action="store_true")
    p.add_argument("--skip-llm", action="store_true", default=True)
    p.add_argument("--with-llm", action="store_true")
    p.add_argument("--n-hyps", type=int, default=0)
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
        DEFAULT_REAL_MULTIYEAR_PERIODS,
        inventory_complete22,
        run_cf_mass_eval_job,
        try_cf_mass_eval_status,
    )
    from research.options_225_vol_series import (
        OPTIONS_225_VOL_SERIES_VERSION,
        SPREAD_CONVENTION,
        load_opt225_series_cache,
        write_definition_rules,
    )

    mode = "synthetic" if args.synthetic else str(args.mode)
    job_id = f"w92-opt225-{ts}"

    log(
        f"[w92] {MASS_FACTORY_WAVE} · factory={MASS_FACTORY_VERSION} · "
        f"cf={CF_MASS_EVAL_VERSION} · opt_series={OPTIONS_225_VOL_SERIES_VERSION} · "
        f"seed={args.seed} · mode={mode}"
    )
    log(
        f"[w92] freezes: mass={MASS_RESEARCH} continuous_paper={CONTINUOUS_PAPER} "
        f"READY=False ops_GO=False frozen_defaults_retuned=False"
    )
    log(
        "[w92] 3 defaults frozen: "
        + ", ".join(r["representative_id"] for r in FROZEN_DEFAULT_PATH)
    )
    log(
        f"[w92] spread_convention={SPREAD_CONVENTION} · "
        "canonical SoT=derivatives_bars_daily_options_225 · "
        "nky_vol_*=proxy/compare only"
    )

    # Ensure definition rule JSONs exist alongside series cache.
    cache = load_opt225_series_cache(out_dir)
    if cache:
        write_definition_rules(
            out_dir,
            stats={
                "n_base_vol_days": len(cache.get("base_vol_series") or []),
                "n_atm_iv_days": len(cache.get("atm_iv_series") or []),
                "n_spread_days": len(cache.get("spread_series") or []),
                "spread_convention": SPREAD_CONVENTION,
            },
        )
        log(
            f"[w92] series cache: base={len(cache.get('base_vol_series') or [])} "
            f"atm={len(cache.get('atm_iv_series') or [])} "
            f"spread={len(cache.get('spread_series') or [])}"
        )
    else:
        log("[w92] WARN: options_225 series cache missing under out-dir")

    inv = inventory_complete22()
    _dump(out_dir / "complete22_inventory.json", inv)
    complete_ids = set(inv.get("complete_22") or [])
    assert "derivatives_bars_daily_options_225" in complete_ids, (
        "options_225 must be in COMPLETE-22; do not claim missing"
    )
    log(
        f"[w92] COMPLETE22 n={inv.get('dataset_complete_n')} "
        f"defer={inv.get('permanent_defer_n')} "
        f"bars={inv.get('primary_bars_dataset')}"
    )

    cf_status = try_cf_mass_eval_status()
    _dump(out_dir / "cf_status.json", cf_status)
    log(
        f"[w92] CF status={cf_status.get('status')} "
        f"default_mode={cf_status.get('default_mode')}"
    )

    # ------------------------------------------------------------------ wide local
    wide_pack: dict = {}
    if not args.skip_wide:
        log("[w92] B: wide local eval on REAL mirrors (catalog + opt225 + nky proxy)")
        cfg = MassFactoryConfig(
            seed=int(args.seed),
            n=120,
            max_codes=int(args.max_codes),
            max_days_per_period=int(args.max_days),
            use_q4_periods=True,
        )
        gen = generate_strategy_batch(cfg)
        strategies = list(gen.get("strategies_after_dedup") or [])
        seen = {str(s.get("logic_id")) for s in strategies}
        for lid in OPT225_LOGIC_IDS + (
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
                        "source": "w92_force_include",
                    }
                )
                seen.add(lid)

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
        opt_rows = [
            r
            for r in results
            if str(r.get("logic_id") or "").startswith("opt225_")
        ]
        nky_rows = [
            r
            for r in results
            if str(r.get("logic_id") or "").startswith("nky_vol_")
        ]
        basevol_rows = [r for r in opt_rows if "basevol" in str(r.get("logic_id"))]
        atm_rows = [r for r in opt_rows if "atm_iv" in str(r.get("logic_id"))]
        spread_rows = [r for r in opt_rows if "spread" in str(r.get("logic_id"))]
        comparison = {
            "basevol": [_compact_row(r) for r in basevol_rows],
            "atm_iv": [_compact_row(r) for r in atm_rows],
            "spread": [_compact_row(r) for r in spread_rows],
            "nky_proxy_compare": [_compact_row(r) for r in nky_rows],
        }
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
            "n_opt225_logics": len(opt_rows),
            "n_nky_proxy_logics": len(nky_rows),
            "opt225_results": [_compact_row(r) for r in opt_rows],
            "comparison_table": comparison,
            "spread_convention": SPREAD_CONVENTION,
            "ranking_top": (batch.get("ranking") or [])[:25],
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
        _dump(out_dir / "comparison_table.json", comparison)
        log(
            f"[w92] B done · evaluated={wide_pack['n_evaluated']} "
            f"survivors={wide_pack['n_survivors']} "
            f"opt225={wide_pack['n_opt225_logics']} "
            f"path={wide_pack['data_path']}"
        )
        for row in wide_pack["opt225_results"]:
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
            log(f"[w92] write_factory_outputs skip: {exc}")
    else:
        log("[w92] B: wide local skipped")

    # ------------------------------------------------------------------ CF real
    cf_pack: dict = {}
    if not args.skip_cf:
        log(f"[w92] C: CF mass-eval job_id={job_id} mode={mode}")
        logic_ids = list(OPT225_LOGIC_IDS) + [
            "nky_vol_abs_level",
            "nky_vol_term_levels",
            "nky_vol_term_ratio",
            "xs_rank_ls_sticky",
            "mdh_sticky_momentum",
            "vol_risk_adjusted_mom",
        ]
        try:
            cf_pack = run_cf_mass_eval_job(
                job_id=job_id,
                logic_ids=logic_ids,
                periods=list(DEFAULT_REAL_MULTIYEAR_PERIODS),
                mode=mode,
                max_codes=int(args.max_codes),
                max_days=int(args.max_days),
                seed=int(args.seed),
                worker_url=str(args.worker_url),
                deploy_if_needed=not bool(args.skip_deploy),
                dry_run_r2=bool(args.dry_run_r2),
                staging_dir=out_dir / "panels_stage",
            )
        except Exception as exc:
            log(f"[w92] C CF job failed: {exc}")
            cf_pack = {"status": "error", "error": str(exc), "job_id": job_id}
        _dump(out_dir / "cf_mass_eval_job.json", cf_pack)
        # Compact run receipt (W90/W91 shape) for residual proofs.
        wr = cf_pack.get("worker_response") or {}
        _dump(
            out_dir / "cf_job_run.json",
            {
                "status": cf_pack.get("status"),
                "job_id": cf_pack.get("job_id") or job_id,
                "mode": cf_pack.get("mode") or mode,
                "worker_url": cf_pack.get("worker_url"),
                "n_logics": cf_pack.get("n_logics"),
                "n_periods": cf_pack.get("n_periods"),
                "n_eval_ok": cf_pack.get("n_eval_ok") or wr.get("n_eval_ok"),
                "n_eval_fail": wr.get("n_eval_fail"),
                "n_survivors": cf_pack.get("n_survivors"),
                "wall_time_ms": wr.get("wall_time_ms"),
                "wall_time_sec": cf_pack.get("wall_time_sec"),
                "r2_prefix": cf_pack.get("r2_prefix")
                or (cf_pack.get("artifact_paths") or {}).get("prefix"),
                "r2_keys": cf_pack.get("r2_keys") or wr.get("r2_keys"),
                "ranking": wr.get("ranking") or [],
                "opt225_results": [
                    {
                        "logic_id": r.get("logic_id"),
                        "status": r.get("status"),
                        "mean_net": r.get("mean_net"),
                        "t_stat": r.get("t_stat"),
                        "sharpe_period": r.get("sharpe_period"),
                        "chosen_sign": r.get("chosen_sign"),
                        "n_periods_ok": r.get("n_periods_ok"),
                        "signal_ids": sorted(
                            {
                                pr.get("signal_id")
                                for pr in (r.get("period_rows") or [])
                                if pr.get("signal_id")
                            }
                        ),
                    }
                    for r in (wr.get("results") or [])
                    if str(r.get("logic_id") or "").startswith("opt225_")
                ],
                "stage_panels": {
                    "n_ok": (cf_pack.get("stage_panels") or {}).get("n_ok"),
                    "n_periods": (cf_pack.get("stage_panels") or {}).get("n_periods"),
                    "panels_prefix": (cf_pack.get("stage_panels") or {}).get(
                        "panels_prefix"
                    ),
                },
                "deploy": {
                    "status": (cf_pack.get("deploy") or {}).get("status"),
                    "worker_url": (cf_pack.get("deploy") or {}).get("worker_url"),
                },
                "datasets_used": cf_pack.get("datasets_used"),
                "mass_research": "NO-GO",
                "operational_go": False,
                "ready_declared": False,
                "frozen_defaults_retuned": False,
                "wave": "W92 / w0818b",
                "version": cf_pack.get("version"),
            },
        )
        log(
            f"[w92] C done · status={cf_pack.get('status')} "
            f"job_id={cf_pack.get('job_id') or job_id} "
            f"n_survivors={cf_pack.get('n_survivors')} "
            f"mode={cf_pack.get('mode') or mode}"
        )
    else:
        log("[w92] C: CF skipped")

    summary = {
        "wave": MASS_FACTORY_WAVE,
        "cf_wave": CF_MASS_EVAL_WAVE,
        "factory_version": MASS_FACTORY_VERSION,
        "cf_version": CF_MASS_EVAL_VERSION,
        "options_series_version": OPTIONS_225_VOL_SERIES_VERSION,
        "job_id": cf_pack.get("job_id") or job_id,
        "mode": mode,
        "spread_convention": SPREAD_CONVENTION,
        "canonical_dataset": "derivatives_bars_daily_options_225",
        "nky_vol_role": "proxy_compare_only",
        "elapsed_sec": round(time.perf_counter() - t0, 3),
        "wide": {
            "n_evaluated": wide_pack.get("n_evaluated"),
            "n_survivors": wide_pack.get("n_survivors"),
            "n_opt225": wide_pack.get("n_opt225_logics"),
            "data_path": wide_pack.get("data_path"),
        },
        "cf": {
            "status": cf_pack.get("status"),
            "n_survivors": cf_pack.get("n_survivors"),
            "n_logics": cf_pack.get("n_logics"),
            "n_periods": cf_pack.get("n_periods"),
            "r2_prefix": (cf_pack.get("paths") or {}).get("prefix")
            or cf_pack.get("r2_prefix"),
        },
        "freezes": {
            "mass_research": MASS_RESEARCH,
            "continuous_paper": CONTINUOUS_PAPER,
            "ready_declared": False,
            "operational_go": False,
            "phase7": "OFF",
            "frozen_defaults_retuned": False,
        },
        "opt225_logic_ids": list(OPT225_LOGIC_IDS),
        "implementer": "GLM5.3 only. Grok did not implement.",
    }
    _dump(out_dir / "w92_summary.json", summary)
    _dump(
        out_dir / "commit_meta.json",
        {
            "wave": "W92 / w0818b",
            "built_at": datetime.now(timezone.utc).isoformat(),
            "summary": summary,
        },
    )
    log(f"[w92] DONE elapsed={summary['elapsed_sec']}s · job={summary['job_id']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
