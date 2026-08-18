#!/usr/bin/env python3
"""W93 / w0818c track C — thicken CF r2_panels with COMPLETE-22 sidecars.

Extends W92 options_225 + equities bars staging with denser panels:
  * markets_calendar
  * jsda_tokyo_repo_rates (wired on CF for macro_repo_*)
  * markets_margin_interest / markets_short_ratio (flow sidecar; local_only eval)
  * fins_summary (fund sidecar; local_only eval)
  * indices_bars_daily_topix as TOPIX proxy label

Does **not** arm Mass / READY / operational GO / continuous paper / live.
Does **not** retune the three frozen default-path representatives.

Examples
--------
    uv run python scripts/run_w93_thicken_cf_panels.py \\
        --out-dir .glm-logs/w0818c_w93_opt225_diff/

    uv run python scripts/run_w93_thicken_cf_panels.py --skip-cf
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

THICKEN_LOGIC_IDS: tuple[str, ...] = (
    # keep opt225 + bars natives + newly wired macro repo
    "mdh_sticky_momentum",
    "xs_rank_ls_sticky",
    "opt225_basevol_abs_level",
    "opt225_atm_iv_abs_level",
    "opt225_iv_base_spread_abs",
    "nky_vol_abs_level",
    "macro_repo_rate_change",
    "macro_repo_rate_level",
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
        "signal_id_sample": (
            ((r.get("period_rows") or [{}])[0] or {}).get("signal_id")
            if r.get("period_rows")
            else None
        ),
    }


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description="W93: thicken CF panels (calendar/rate/flow/fund) + opt225"
    )
    p.add_argument(
        "--out-dir",
        type=str,
        default=str(ROOT / ".glm-logs" / "w0818c_w93_opt225_diff"),
    )
    p.add_argument("--seed", type=int, default=870818)
    p.add_argument(
        "--mode",
        type=str,
        default="r2_panels",
        choices=["r2_panels", "d1_bars", "synthetic", "nets_only"],
    )
    p.add_argument("--skip-cf", action="store_true")
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

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    t0 = time.perf_counter()
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    def log(msg: str) -> None:
        if not args.quiet:
            print(msg, flush=True)

    from research.cf_mass_eval_job import (
        CF_MASS_EVAL_VERSION,
        CF_MASS_EVAL_WAVE,
        DEFAULT_REAL_MULTIYEAR_PERIODS,
        build_real_period_panel,
        inventory_cf_panel_wiring,
        inventory_complete22,
        run_cf_mass_eval_job,
        try_cf_mass_eval_status,
    )
    from research.mass_strategy_factory import (
        CONTINUOUS_PAPER,
        FROZEN_DEFAULT_PATH,
        MASS_RESEARCH,
        PHASE7,
    )

    job_id = f"w93-thicken-{ts}"
    mode = str(args.mode)

    log(f"[w93] wave={CF_MASS_EVAL_WAVE} version={CF_MASS_EVAL_VERSION}")
    log(f"[w93] job_id={job_id} mode={mode} out={out_dir}")

    # ------------------------------------------------------------------ A. wiring inventory
    inv22 = inventory_complete22()
    wiring = inventory_cf_panel_wiring()
    _dump(out_dir / "complete22_inventory.json", inv22)
    _dump(out_dir / "cf_wiring_inventory.json", wiring)
    log(
        "[w93] A: wiring inventory "
        f"counts={wiring.get('status_counts')} "
        f"thicken={wiring.get('thicken_panel_datasets')}"
    )

    # ------------------------------------------------------------------ B. sample thickened panel
    sample = build_real_period_panel(
        dict(DEFAULT_REAL_MULTIYEAR_PERIODS[0]),
        max_codes=int(args.max_codes),
        max_days=min(60, int(args.max_days)),
    )
    sample_meta = {
        k: sample.get(k)
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
            "opt225_dataset",
            "opt225_n_base_vol",
            "opt225_n_atm_iv",
            "opt225_n_spread",
            "panel_thicken",
            "thicken_datasets",
            "thicken_counts",
            "thicken_done",
            "thicken_status",
            "index_proxy",
        )
    }
    sample_meta["repo_n_rates"] = (sample.get("repo_rate_regime") or {}).get(
        "n_rates"
    ) or (sample.get("repo_rate_regime") or {}).get("n_obs")
    sample_meta["calendar_n_dates"] = (sample.get("calendar") or {}).get(
        "n_dates"
    )
    sample_meta["flow_n_codes"] = (sample.get("flow_regime") or {}).get(
        "n_codes"
    )
    sample_meta["flow_n_short"] = (sample.get("flow_regime") or {}).get(
        "n_short_obs"
    )
    sample_meta["fund_n_events"] = (sample.get("fund_regime") or {}).get(
        "n_events"
    )
    _dump(out_dir / "sample_thickened_panel_meta.json", sample_meta)
    log(
        f"[w93] B: sample panel {sample_meta.get('period_id')} "
        f"status={sample_meta.get('status')} "
        f"codes={sample_meta.get('n_codes')} "
        f"repo={sample_meta.get('repo_n_rates')} "
        f"cal={sample_meta.get('calendar_n_dates')} "
        f"flow_codes={sample_meta.get('flow_n_codes')} "
        f"fund_events={sample_meta.get('fund_n_events')} "
        f"opt225_bv={sample_meta.get('opt225_n_base_vol')}"
    )

    # ------------------------------------------------------------------ C. CF job (optional)
    cf_pack: dict = {}
    if not args.skip_cf:
        log(f"[w93] C: CF mass-eval mode={mode} job_id={job_id}")
        try:
            cf_pack = run_cf_mass_eval_job(
                job_id=job_id,
                logic_ids=list(THICKEN_LOGIC_IDS),
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
            log(f"[w93] C CF job error: {exc}")
            cf_pack = {
                "status": "error",
                "error": str(exc),
                "job_id": job_id,
                "mode": mode,
            }
        _dump(out_dir / "cf_mass_eval_job.json", cf_pack)
        wr = cf_pack.get("worker_response") or {}
        if not wr and isinstance(cf_pack.get("results"), list):
            wr = cf_pack
        log(
            f"[w93] C done · status={cf_pack.get('status')} "
            f"job_id={cf_pack.get('job_id')} "
            f"n_logics={cf_pack.get('n_logics')} "
            f"n_periods={cf_pack.get('n_periods')} "
            f"n_survivors={cf_pack.get('n_survivors')} "
            f"stage_ok={(cf_pack.get('stage_panels') or {}).get('n_ok')}"
        )
        stage = cf_pack.get("stage_panels") or {}
        _dump(out_dir / "stage_panels.json", stage)
        if wr:
            _dump(out_dir / "cf_mass_eval_response.json", wr)
            results = list(wr.get("results") or cf_pack.get("results") or [])
            opt_rows = [
                r
                for r in results
                if str(r.get("logic_id") or "").startswith("opt225_")
            ]
            rate_rows = [
                r
                for r in results
                if str(r.get("logic_id") or "").startswith("macro_repo_")
            ]
            _dump(
                out_dir / "cf_opt225_rate_results.json",
                {
                    "opt225": [_compact_row(r) for r in opt_rows],
                    "macro_repo": [_compact_row(r) for r in rate_rows],
                    "all": [_compact_row(r) for r in results],
                },
            )
            for r in opt_rows + rate_rows:
                log(
                    f"  · CF {r.get('logic_id')}: net={r.get('mean_net')} "
                    f"t={r.get('t_stat')} "
                    f"survived={(r.get('screen') or {}).get('survived')}"
                )
        try:
            st = try_cf_mass_eval_status(
                str(cf_pack.get("job_id") or job_id),
                worker_url=args.worker_url,
            )
            _dump(out_dir / "cf_status.json", st)
        except Exception as exc:
            _dump(out_dir / "cf_status.json", {"error": str(exc)})
    else:
        log("[w93] C: CF skipped")

    # ------------------------------------------------------------------ summary
    summary = {
        "wave": CF_MASS_EVAL_WAVE,
        "version": CF_MASS_EVAL_VERSION,
        "job_id": cf_pack.get("job_id") or job_id,
        "mode": mode,
        "status": cf_pack.get("status") if cf_pack else "cf_skipped",
        "wiring_counts": wiring.get("status_counts"),
        "sample_panel": sample_meta,
        "stage_ok": (cf_pack.get("stage_panels") or {}).get("n_ok"),
        "n_logics": cf_pack.get("n_logics"),
        "n_periods": cf_pack.get("n_periods"),
        "n_survivors": cf_pack.get("n_survivors"),
        "freezes": {
            "mass_research": MASS_RESEARCH,
            "phase7": PHASE7,
            "ready_declared": False,
            "operational_go": False,
            "continuous_paper": CONTINUOUS_PAPER,
            "frozen_defaults_retuned": False,
            "frozen_default_path": list(FROZEN_DEFAULT_PATH)
            if not isinstance(FROZEN_DEFAULT_PATH, dict)
            else sorted(FROZEN_DEFAULT_PATH.keys()),
        },
        "wall_s": round(time.perf_counter() - t0, 3),
        "ts": ts,
        "note": (
            "Thicker r2_panels: opt225 + calendar + repo rate + flow + fund "
            "sidecars. macro_repo_* wired on CF; flow/fund local_only eval. "
            "TOPIX = proxy label only. COMPLETE never claimed missing."
        ),
    }
    _dump(out_dir / "w93_thicken_summary.json", summary)
    log(f"[w93] done wall_s={summary['wall_s']} job_id={summary['job_id']}")
    return 0 if (args.skip_cf or cf_pack.get("status") in {"ok", "completed", "success"}) else 1


if __name__ == "__main__":
    raise SystemExit(main())
