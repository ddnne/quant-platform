#!/usr/bin/env python3
"""W96 / w0818f tracks B+C — new hyps + frozen 3-default quality (no pin retune).

B. New hyps
  * ``research.llm_hyp_generator`` (prefer xAI grok via auth)
  * W95 failure-mode constraints injected (no sign-flip single-regime;
    no soft≡pressure; no low-var t trust; no window-only; no dual options
    level; do not re-polish shape/rate/flow/demoted fund_slow)
  * Always route through ``propose_profit_hypotheses`` + evaluator
    (cost / PIT / low-var gate)

C. Default quality (pins frozen)
  Evaluate exactly:
    1. cross_section_hold_10 (hold=10, mom=5) KEEP
    2. cross_section_hold_10_mom3 (hold=10, mom=3) PROMOTE
    3. fundamentals_hold_10 (hold=10, mom=10, value_momentum_agree) KEEP
  Multi-year windows + cost + PIT + low-var; CF ``r2_panels`` preferred.
  If PROMOTE/KEEP contradicts metrics → **record contradiction, do not
  change pins**.

Freezes held: Mass=NO-GO · READY=false · ops GO=false · continuous paper
UNARMED · 3 defaults not retuned · no GO/live.

Examples
--------
    uv run python scripts/run_w96_hyps_and_defaults.py \\
        --out-dir .glm-logs/w0818f_w96_data_hyps_defaults/

    uv run python scripts/run_w96_hyps_and_defaults.py --skip-cf --skip-local-defaults
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

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
OUT_DEFAULT = ROOT / ".glm-logs" / "w0818f_w96_data_hyps_defaults"
CF_WORKER_URL = (
    "https://quant-platform-research-mass-eval.taku-haga.workers.dev"
)

# Same honest window shards as W93–W95 (contiguous 3y bars mirrors absent).
W96_WINDOWS: tuple[dict[str, Any], ...] = (
    {
        "window_id": "w2017_2019",
        "label": "2017–2019",
        "data_note": "2018 mirror absent; y2017_q4 + y2019_full",
        "shards": (
            {
                "period_id": "y2017_q4",
                "year": 2017,
                "period_start": "2017-09-01",
                "period_end": "2017-12-29",
                "window_kind": "q4",
            },
            {
                "period_id": "y2019_full",
                "year": 2019,
                "period_start": "2019-01-04",
                "period_end": "2019-10-18",
                "window_kind": "full_prefer",
            },
        ),
    },
    {
        "window_id": "w2020_2022",
        "label": "2020–2022",
        "data_note": "2020/2022 mirrors absent; y2021_full only",
        "shards": (
            {
                "period_id": "y2021_full",
                "year": 2021,
                "period_start": "2021-01-04",
                "period_end": "2021-10-15",
                "window_kind": "full_prefer",
            },
        ),
    },
    {
        "window_id": "w2023_2025",
        "label": "2023–2025",
        "data_note": "2024 mirror absent; y2023_full + y2025_q4",
        "shards": (
            {
                "period_id": "y2023_full",
                "year": 2023,
                "period_start": "2023-01-04",
                "period_end": "2023-10-13",
                "window_kind": "full_prefer",
            },
            {
                "period_id": "y2025_q4",
                "year": 2025,
                "period_start": "2025-09-01",
                "period_end": "2025-12-29",
                "window_kind": "q4",
            },
        ),
    },
)

# Explicit pin stances — DO NOT mutate from metrics.
PINNED_STANCES: dict[str, str] = {
    "cross_section_hold_10": "KEEP",
    "cross_section_hold_10_mom3": "PROMOTE",
    "fundamentals_hold_10": "KEEP",
}


def _dump(path: Path, obj: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(obj, indent=2, ensure_ascii=False, default=str) + "\n",
        encoding="utf-8",
    )


def _scalar_f(v: Any) -> float | None:
    if v is None:
        return None
    try:
        fv = float(v)
    except (TypeError, ValueError):
        return None
    return fv if math.isfinite(fv) else None


def _scalar_t(t: Any) -> float | None:
    if t is None:
        return None
    if isinstance(t, Mapping):
        return _scalar_f(t.get("t_stat"))
    return _scalar_f(t)


def _all_shards() -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for w in W96_WINDOWS:
        for s in w["shards"]:
            out.append(dict(s))
    return out


def _frozen_default_extra_logics() -> list[dict[str, Any]]:
    """CF-ready logics with frozen pins (distinct logic_ids for table)."""
    from research.mass_strategy_factory import FROZEN_DEFAULT_PATH, LOGIC_TEMPLATES

    xs = LOGIC_TEMPLATES["xs_rank_ls_sticky"]
    fund = LOGIC_TEMPLATES["fund_value_mom_agree"]
    by_id = {r["representative_id"]: r for r in FROZEN_DEFAULT_PATH}
    out: list[dict[str, Any]] = []

    r = by_id["cross_section_hold_10"]
    out.append(
        {
            "logic_id": "cross_section_hold_10",
            "family_id": "cross_section_relative",
            "params": {
                "hold_days": int(r["hold_days"]),
                "momentum_n": int(r["momentum_n"]),
                "long_frac": float(r["long_frac"]),
                "short_frac": float(r["short_frac"]),
                "book_mode": "balanced_ls",
            },
            "thesis": xs.thesis,
            "signal_definition": xs.signal_definition,
            "position_rule": xs.position_rule,
            "datasets_used": list(xs.datasets_used),
            "representative_id": "cross_section_hold_10",
            "pinned_stance": PINNED_STANCES["cross_section_hold_10"],
            "source": "frozen_default_path",
        }
    )

    r = by_id["cross_section_hold_10_mom3"]
    out.append(
        {
            "logic_id": "cross_section_hold_10_mom3",
            "family_id": "cross_section_relative",
            "params": {
                "hold_days": int(r["hold_days"]),
                "momentum_n": int(r["momentum_n"]),
                "long_frac": float(r["long_frac"]),
                "short_frac": float(r["short_frac"]),
                "book_mode": "balanced_ls",
            },
            "thesis": xs.thesis + " · mom=3 (W85 promote pin; not a retune)",
            "signal_definition": xs.signal_definition,
            "position_rule": xs.position_rule,
            "datasets_used": list(xs.datasets_used),
            "representative_id": "cross_section_hold_10_mom3",
            "pinned_stance": PINNED_STANCES["cross_section_hold_10_mom3"],
            "source": "frozen_default_path",
        }
    )

    r = by_id["fundamentals_hold_10"]
    out.append(
        {
            "logic_id": "fundamentals_hold_10",
            "family_id": "fundamentals_price",
            "params": {
                "hold_days": int(r["hold_days"]),
                "momentum_n": int(r["momentum_n"]),
                "mode": str(r.get("mode") or "value_momentum_agree"),
            },
            "thesis": fund.thesis,
            "signal_definition": fund.signal_definition,
            "position_rule": fund.position_rule,
            "datasets_used": list(fund.datasets_used),
            "representative_id": "fundamentals_hold_10",
            "pinned_stance": PINNED_STANCES["fundamentals_hold_10"],
            "source": "frozen_default_path",
        }
    )
    return out


def _local_default_strategies() -> list[dict[str, Any]]:
    """Local evaluator strategies mapped to catalog executable logic_ids."""
    from research.mass_strategy_factory import FROZEN_DEFAULT_PATH, LOGIC_TEMPLATES

    xs = LOGIC_TEMPLATES["xs_rank_ls_sticky"]
    fund = LOGIC_TEMPLATES["fund_value_mom_agree"]
    by_id = {r["representative_id"]: r for r in FROZEN_DEFAULT_PATH}
    out: list[dict[str, Any]] = []

    r = by_id["cross_section_hold_10"]
    out.append(
        {
            "strategy_id": "msf_w96_default_cross_section_hold_10",
            "logic_id": "xs_rank_ls_sticky",
            "representative_id": "cross_section_hold_10",
            "family_id": xs.family_id,
            "params": {
                "hold_days": int(r["hold_days"]),
                "momentum_n": int(r["momentum_n"]),
                "long_frac": float(r["long_frac"]),
                "short_frac": float(r["short_frac"]),
                "book_mode": "balanced_ls",
            },
            "thesis": xs.thesis,
            "signal_definition": xs.signal_definition,
            "position_rule": xs.position_rule,
            "datasets_used": list(xs.datasets_used),
            "pinned_stance": PINNED_STANCES["cross_section_hold_10"],
            "variant": "frozen_default",
        }
    )
    r = by_id["cross_section_hold_10_mom3"]
    out.append(
        {
            "strategy_id": "msf_w96_default_cross_section_hold_10_mom3",
            "logic_id": "xs_rank_ls_sticky",
            "representative_id": "cross_section_hold_10_mom3",
            "family_id": xs.family_id,
            "params": {
                "hold_days": int(r["hold_days"]),
                "momentum_n": int(r["momentum_n"]),
                "long_frac": float(r["long_frac"]),
                "short_frac": float(r["short_frac"]),
                "book_mode": "balanced_ls",
            },
            "thesis": xs.thesis + " · mom=3 pin",
            "signal_definition": xs.signal_definition,
            "position_rule": xs.position_rule,
            "datasets_used": list(xs.datasets_used),
            "pinned_stance": PINNED_STANCES["cross_section_hold_10_mom3"],
            "variant": "frozen_default",
        }
    )
    r = by_id["fundamentals_hold_10"]
    out.append(
        {
            "strategy_id": "msf_w96_default_fundamentals_hold_10",
            "logic_id": "fund_value_mom_agree",
            "representative_id": "fundamentals_hold_10",
            "family_id": fund.family_id,
            "params": {
                "hold_days": int(r["hold_days"]),
                "momentum_n": int(r["momentum_n"]),
                "mode": str(r.get("mode") or "value_momentum_agree"),
            },
            "thesis": fund.thesis,
            "signal_definition": fund.signal_definition,
            "position_rule": fund.position_rule,
            "datasets_used": list(fund.datasets_used),
            "pinned_stance": PINNED_STANCES["fundamentals_hold_10"],
            "variant": "frozen_default",
        }
    )
    return out


def _reaggregate_window(
    result: Mapping[str, Any],
    *,
    keep_period_ids: set[str],
    near_zero_abs: float,
    min_activation: float,
) -> dict[str, Any]:
    from research.mass_strategy_factory import screen_strategy_result
    from research.sign_selection import (
        SIGN_INVERTED,
        SIGN_ORIGINAL,
        choose_sign,
        evaluate_sign_both_sides,
    )
    from research.stats_metrics import period_stats_report, sample_mean, t_stat_vs_zero

    period_rows = [
        dict(r)
        for r in (result.get("period_rows") or [])
        if str(r.get("period_id") or "") in keep_period_ids
    ]
    ok_rows = [r for r in period_rows if r.get("status") == "ok"]
    grosses = [r.get("gross_signed_mean_active") for r in ok_rows]
    nets = [r.get("net_one_way_mean_active") for r in ok_rows]
    costs = [r.get("amortized_one_way_cost") for r in ok_rows]
    pids = [str(r.get("period_id")) for r in ok_rows]
    hold = None
    for r in ok_rows:
        if r.get("hold_days") is not None:
            hold = int(r["hold_days"])
            break
    act_rates: list[float] = []
    for r in ok_rows:
        ar = r.get("activation_rate")
        if ar is None:
            occ = r.get("occurrence") or {}
            ar = occ.get("activation_rate")
        if ar is not None:
            try:
                act_rates.append(float(ar))
            except (TypeError, ValueError):
                pass
    mean_activation = sample_mean(act_rates)
    both = evaluate_sign_both_sides(
        period_grosses=grosses,
        period_nets=nets,
        amortized_costs=costs if any(c is not None for c in costs) else None,
        period_ids=pids,
        hold_days=hold,
        near_zero_abs=near_zero_abs,
    )
    choice = choose_sign(both, near_zero_abs=near_zero_abs)
    chosen_sign = choice.get("chosen_sign")
    side_key = (
        "original"
        if chosen_sign == SIGN_ORIGINAL
        else ("inverted" if chosen_sign == SIGN_INVERTED else "original")
    )
    side = dict(both.get(side_key) or {})
    side_nets = list(side.get("nets") or side.get("period_nets") or nets)
    stats = period_stats_report(side_nets)
    mean_net = side.get("mean_net")
    if mean_net is None:
        mean_net = sample_mean(nets)
    mean_gross = sample_mean(grosses)
    t_pack = t_stat_vs_zero(side_nets)
    t_stat = t_pack.get("t_stat")
    sharpe = stats.get("sharpe") if isinstance(stats, Mapping) else None
    if t_pack.get("reason") == "low_variance_artifact":
        sharpe = None
        t_stat = None
    pack = {
        "strategy_id": result.get("strategy_id"),
        "logic_id": result.get("logic_id"),
        "representative_id": result.get("representative_id")
        or result.get("logic_id"),
        "family_id": result.get("family_id"),
        "params": result.get("params"),
        "pinned_stance": result.get("pinned_stance"),
        "n_periods_ok": len(ok_rows),
        "n_periods_total": len(period_rows),
        "period_rows": period_rows,
        "mean_gross": mean_gross,
        "mean_net": mean_net,
        "t_stat": t_stat,
        "t_stat_reason": t_pack.get("reason"),
        "raw_t_stat": t_pack.get("raw_t_stat"),
        "low_variance_artifact": t_pack.get("reason") == "low_variance_artifact",
        "sharpe_period": sharpe,
        "mean_activation": mean_activation,
        "sign_selection": {
            "chosen_sign": chosen_sign,
            "decision": choice.get("decision"),
            "reason": choice.get("reason"),
            "verdict": choice.get("verdict"),
        },
        "chosen_sign": chosen_sign,
        "status": "evaluated" if ok_rows else "no_ok_periods",
    }
    scr = screen_strategy_result(
        pack, near_zero_abs=near_zero_abs, min_activation=min_activation
    )
    pack["screen"] = scr
    pack["survived"] = bool(scr.get("survived"))
    pack["reject_reasons"] = list(scr.get("reject_reasons") or [])
    return pack


def _metrics_suggest_stance(row: Mapping[str, Any]) -> str:
    """Heuristic stance suggestion from metrics (does NOT override pins)."""
    survived = bool(row.get("survived"))
    mean_net = _scalar_f(row.get("mean_net"))
    t = _scalar_t(row.get("t_stat") if "t_stat" in row else row.get("t"))
    low_var = bool(row.get("low_variance_artifact"))
    act = _scalar_f(
        row.get("mean_activation") if "mean_activation" in row else row.get("act")
    )
    if low_var:
        return "DEMOTABLE_low_var"
    if not survived:
        return "WEAK_or_FAIL"
    if mean_net is not None and mean_net > 0 and t is not None and abs(t) >= 1.5:
        if act is not None and act >= 0.02:
            return "SUPPORTS_PROMOTE"
        return "SUPPORTS_KEEP"
    if mean_net is not None and mean_net > 0:
        return "SUPPORTS_KEEP"
    return "WEAK_or_FAIL"


def _contradiction(pinned: str, suggested: str) -> str | None:
    if pinned == "PROMOTE" and suggested in {
        "WEAK_or_FAIL",
        "DEMOTABLE_low_var",
    }:
        return (
            f"pinned PROMOTE but metrics suggest {suggested} "
            "(record only; pins held)"
        )
    if pinned == "KEEP" and suggested == "DEMOTABLE_low_var":
        return (
            f"pinned KEEP but metrics suggest {suggested} "
            "(record only; pins held)"
        )
    if pinned == "KEEP" and suggested == "WEAK_or_FAIL":
        return (
            f"pinned KEEP but metrics suggest {suggested} "
            "(record only; pins held)"
        )
    # PROMOTE pin with SUPPORTS_KEEP is mild — note but not hard contradiction
    if pinned == "PROMOTE" and suggested == "SUPPORTS_KEEP":
        return (
            "pinned PROMOTE; metrics only SUPPORTS_KEEP "
            "(mild; pins held)"
        )
    return None


def run_track_b_hyps(
    *,
    out_dir: Path,
    n_hyps: int,
    provider: str,
    model: str | None,
    seed: int,
    synthetic: bool,
    cf_url: str,
    log,
) -> dict[str, Any]:
    from research.llm_hyp_generator import (
        LLM_HYP_VERSION,
        LLM_HYP_WAVE,
        detect_api_keys,
        generate_and_evaluate_hypotheses,
    )
    from research.mass_strategy_factory import (
        CONTINUOUS_PAPER,
        FROZEN_DEFAULT_PATH,
        MASS_RESEARCH,
    )

    keys = detect_api_keys()
    key_presence = {k: bool(v) for k, v in keys.items()}
    _dump(out_dir / "api_keys_present.json", key_presence)
    log(f"[w96/B] api_key_presence={key_presence}")
    log(
        f"[w96/B] generating n={n_hyps} provider={provider} "
        f"wave={LLM_HYP_WAVE} ver={LLM_HYP_VERSION}"
    )

    gen_eval = generate_and_evaluate_hypotheses(
        n=int(n_hyps),
        provider=None if provider == "auto" else provider,
        model=model,
        worker_url=cf_url,
        evaluate=True,
        synthetic=bool(synthetic),
    )

    # Compact generation artifact (no huge eval_results dump twice)
    gen_compact = {
        k: gen_eval[k]
        for k in gen_eval
        if k
        not in {
            "eval_results",
            "eval_screens",
            "proposals_for_eval",
            "accepted_proposals",
            "rejected_proposals",
        }
    }
    _dump(out_dir / "llm_hyp_generation.json", gen_compact)
    _dump(out_dir / "llm_hyp_proposals.json", gen_eval.get("proposals_for_eval") or [])
    _dump(out_dir / "llm_hyp_eval_ranking.json", gen_eval.get("eval_ranking") or [])
    _dump(out_dir / "llm_hyp_eval_screens.json", gen_eval.get("eval_screens") or [])
    _dump(
        out_dir / "llm_hyp_accepted_proposals.json",
        gen_eval.get("accepted_proposals") or [],
    )
    _dump(
        out_dir / "llm_hyp_rejected_proposals.json",
        gen_eval.get("rejected_proposals") or [],
    )

    n_proposed = int(gen_eval.get("n_proposed") or 0)
    n_accepted = int(gen_eval.get("n_accepted") or 0)
    # Generation-time rejects (window tweak / W95 failure-mode)
    n_gen_rejected = n_proposed - n_accepted
    # Evaluator rejects after propose_profit_hypotheses
    n_eval_rejected = len(gen_eval.get("rejected_proposals") or [])
    n_survivors = int(gen_eval.get("n_survivors") or 0)
    theses = list(gen_eval.get("representative_theses") or [])

    summary = {
        "wave": "W96 / w0818f",
        "track": "B_new_hyps",
        "provider": gen_eval.get("provider"),
        "model": gen_eval.get("model"),
        "llm_hyp_version": LLM_HYP_VERSION,
        "n_proposed": n_proposed,
        "n_accepted": n_accepted,
        "n_rejected_generation": n_gen_rejected,
        "n_rejected_evaluator": n_eval_rejected,
        "n_rejected": n_gen_rejected + n_eval_rejected,
        "n_evaluated": gen_eval.get("n_evaluated"),
        "n_survivors": n_survivors,
        "representative_theses": theses,
        "failure_mode_constraints": [
            "no_sign_flip_single_regime_reliance",
            "no_soft_eq_pressure",
            "no_low_var_t_trust",
            "no_window_only",
            "no_dual_options_level",
            "no_repolish_shape_rate_flow_demoted_fund_slow",
        ],
        "routed_through": "propose_profit_hypotheses",
        "gates": ["cost", "PIT", "low_var"],
        "frozen_defaults_retuned": False,
        "frozen_defaults": [r["representative_id"] for r in FROZEN_DEFAULT_PATH],
        "mass_research": MASS_RESEARCH,
        "continuous_paper": CONTINUOUS_PAPER,
        "seed": int(seed),
    }
    _dump(out_dir / "hyp_summary.json", summary)

    log(
        f"[w96/B] n_proposed={n_proposed} n_accepted={n_accepted} "
        f"n_rejected={summary['n_rejected']} "
        f"(gen={n_gen_rejected}+eval={n_eval_rejected}) "
        f"n_survivors={n_survivors} model={gen_eval.get('model')}"
    )
    for th in theses[:8]:
        log(
            f"  · {th.get('logic_id')}: "
            f"{str(th.get('thesis') or '')[:120]}"
        )
    return {"summary": summary, "gen_eval": gen_eval}


def run_track_c_defaults_local(
    *,
    out_dir: Path,
    seed: int,
    max_codes: int,
    max_days: int,
    log,
) -> dict[str, Any]:
    from research.mass_strategy_factory import (
        FROZEN_DEFAULT_PATH,
        MassFactoryConfig,
        evaluate_one_strategy,
        load_batch_data_context,
        screen_strategy_result,
    )

    strategies = _local_default_strategies()
    cfg = MassFactoryConfig(
        seed=int(seed),
        n=len(strategies),
        max_codes=int(max_codes),
        max_days_per_period=int(max_days),
        use_q4_periods=False,
    )
    rows_flat: list[dict[str, Any]] = []
    for w in W96_WINDOWS:
        wid = str(w["window_id"])
        periods = [dict(s) for s in w["shards"]]
        log(f"[w96/C] local defaults {wid} n={len(strategies)}")
        ctx = load_batch_data_context(cfg, periods=periods, synthetic=False)
        for strat in strategies:
            res = evaluate_one_strategy(
                strat,
                ctx,
                near_zero_abs=cfg.near_zero_abs,
                min_activation=cfg.min_activation,
            )
            res["params"] = dict(strat.get("params") or {})
            res["representative_id"] = strat.get("representative_id")
            res["pinned_stance"] = strat.get("pinned_stance")
            res["t_stat"] = _scalar_t(res.get("t_stat"))
            scr = screen_strategy_result(
                res,
                near_zero_abs=cfg.near_zero_abs,
                min_activation=cfg.min_activation,
            )
            res["screen"] = scr
            mean_net = _scalar_f(res.get("mean_net"))
            act = _scalar_f(
                res.get("mean_activation")
                if "mean_activation" in res
                else (res.get("occurrence") or {}).get("activation_rate")
            )
            row = {
                "source": "local",
                "window": wid,
                "representative_id": strat.get("representative_id"),
                "logic_id": strat.get("logic_id"),
                "pinned_stance": strat.get("pinned_stance"),
                "hold_days": (strat.get("params") or {}).get("hold_days"),
                "momentum_n": (strat.get("params") or {}).get("momentum_n"),
                "mode": (strat.get("params") or {}).get("mode"),
                "mean_net": mean_net,
                "t": _scalar_t(res.get("t_stat")),
                "t_stat_reason": res.get("t_stat_reason"),
                "raw_t_stat": res.get("raw_t_stat"),
                "low_variance_artifact": bool(res.get("low_variance_artifact")),
                "act": act,
                "sign": res.get("chosen_sign"),
                "survived": bool(scr.get("survived")),
                "reject_reasons": list(scr.get("reject_reasons") or []),
                "n_periods_ok": res.get("n_periods_ok"),
                "n_periods_total": res.get("n_periods_total"),
            }
            row["metrics_suggest"] = _metrics_suggest_stance(row)
            row["contradiction"] = _contradiction(
                str(row["pinned_stance"]), str(row["metrics_suggest"])
            )
            rows_flat.append(row)

    pack = {
        "wave": "W96 / w0818f",
        "track": "C_default_quality_local",
        "frozen_defaults": [r["representative_id"] for r in FROZEN_DEFAULT_PATH],
        "frozen_defaults_retuned": False,
        "pinned_stances": dict(PINNED_STANCES),
        "rows_flat": rows_flat,
        "n_survivors": sum(1 for r in rows_flat if r.get("survived")),
        "n_contradictions": sum(1 for r in rows_flat if r.get("contradiction")),
    }
    _dump(out_dir / "default_quality_local.json", pack)
    return pack


def run_track_c_defaults_cf(
    *,
    out_dir: Path,
    seed: int,
    max_codes: int,
    max_days: int,
    mode: str,
    worker_url: str,
    skip_deploy: bool,
    log,
) -> dict[str, Any]:
    from research.cf_mass_eval_job import (
        CF_MASS_EVAL_VERSION,
        run_cf_mass_eval_job,
        try_cf_mass_eval_status,
    )
    from research.mass_strategy_factory import FROZEN_DEFAULT_PATH, MassFactoryConfig

    status = try_cf_mass_eval_status()
    _dump(out_dir / "cf_status_defaults.json", status)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    job_id = f"w96-defaults-{ts}"
    extras = _frozen_default_extra_logics()
    shards = _all_shards()
    log(
        f"[w96/C] CF defaults job_id={job_id} mode={mode} "
        f"n_logics={len(extras)} n_shards={len(shards)} "
        f"cf={CF_MASS_EVAL_VERSION}"
    )
    try:
        cf_pack = run_cf_mass_eval_job(
            job_id=job_id,
            logic_ids=[],  # extras only — exact 3 defaults
            extra_logics=extras,
            periods=shards,
            mode=str(mode),
            max_codes=int(max_codes),
            max_days=min(int(max_days), 120),
            seed=int(seed),
            worker_url=str(worker_url),
            deploy_if_needed=not bool(skip_deploy),
            stage_panels=(mode == "r2_panels"),
        )
    except Exception as exc:
        log(f"[w96/C] CF defaults failed: {exc}")
        cf_pack = {
            "status": "error",
            "error": str(exc),
            "job_id": job_id,
            "mode": mode,
        }
    _dump(out_dir / "cf_defaults_job.json", cf_pack)
    wr = cf_pack.get("worker_response") or {}
    if not wr and isinstance(cf_pack.get("results"), list):
        wr = cf_pack
    if wr:
        _dump(out_dir / "cf_defaults_response.json", wr)

    cfg = MassFactoryConfig()
    rows_flat: list[dict[str, Any]] = []
    results_by_lid: dict[str, dict[str, Any]] = {}
    for r in wr.get("results") or []:
        if not isinstance(r, Mapping):
            continue
        lid = str(r.get("logic_id") or "")
        # Attach pin metadata from extras
        for ex in extras:
            if ex["logic_id"] == lid:
                r = {
                    **dict(r),
                    "representative_id": ex.get("representative_id"),
                    "pinned_stance": ex.get("pinned_stance"),
                    "params": r.get("params") or ex.get("params"),
                }
                break
        results_by_lid[lid] = dict(r)

    for w in W96_WINDOWS:
        wid = str(w["window_id"])
        keep = {s["period_id"] for s in w["shards"]}
        for lid, raw in results_by_lid.items():
            pack = _reaggregate_window(
                raw,
                keep_period_ids=keep,
                near_zero_abs=cfg.near_zero_abs,
                min_activation=cfg.min_activation,
            )
            rid = str(
                pack.get("representative_id")
                or raw.get("representative_id")
                or lid
            )
            pinned = str(
                pack.get("pinned_stance")
                or PINNED_STANCES.get(rid)
                or "KEEP"
            )
            params = dict(pack.get("params") or raw.get("params") or {})
            row = {
                "source": "cf_r2_panels" if mode == "r2_panels" else f"cf_{mode}",
                "window": wid,
                "representative_id": rid,
                "logic_id": lid,
                "pinned_stance": pinned,
                "hold_days": params.get("hold_days"),
                "momentum_n": params.get("momentum_n"),
                "mode": params.get("mode"),
                "mean_net": _scalar_f(pack.get("mean_net")),
                "t": _scalar_t(pack.get("t_stat")),
                "t_stat_reason": pack.get("t_stat_reason"),
                "raw_t_stat": pack.get("raw_t_stat"),
                "low_variance_artifact": bool(pack.get("low_variance_artifact")),
                "act": _scalar_f(pack.get("mean_activation")),
                "sign": pack.get("chosen_sign"),
                "survived": bool(pack.get("survived")),
                "reject_reasons": list(pack.get("reject_reasons") or []),
                "n_periods_ok": pack.get("n_periods_ok"),
                "n_periods_total": pack.get("n_periods_total"),
                "job_id": cf_pack.get("job_id") or job_id,
            }
            row["metrics_suggest"] = _metrics_suggest_stance(row)
            row["contradiction"] = _contradiction(
                pinned, str(row["metrics_suggest"])
            )
            rows_flat.append(row)

    pack_out = {
        "wave": "W96 / w0818f",
        "track": "C_default_quality_cf",
        "job_id": cf_pack.get("job_id") or job_id,
        "mode": mode,
        "status": cf_pack.get("status"),
        "frozen_defaults": [r["representative_id"] for r in FROZEN_DEFAULT_PATH],
        "frozen_defaults_retuned": False,
        "pinned_stances": dict(PINNED_STANCES),
        "rows_flat": rows_flat,
        "n_survivors": sum(1 for r in rows_flat if r.get("survived")),
        "n_contradictions": sum(1 for r in rows_flat if r.get("contradiction")),
        "cf_pack_status": cf_pack.get("status"),
    }
    _dump(out_dir / "default_quality_cf.json", pack_out)
    log(
        f"[w96/C] CF done status={cf_pack.get('status')} "
        f"rows={len(rows_flat)} survivors={pack_out['n_survivors']} "
        f"contradictions={pack_out['n_contradictions']}"
    )
    return pack_out


def _aggregate_default_table(
    *,
    local_pack: Mapping[str, Any] | None,
    cf_pack: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Prefer CF r2_panels rows; fall back to local; record contradictions."""
    preferred_rows: list[dict[str, Any]] = []
    source_used = "none"
    cf_status = str(
        (cf_pack or {}).get("status")
        or (cf_pack or {}).get("cf_pack_status")
        or ""
    )
    cf_rows = list((cf_pack or {}).get("rows_flat") or [])
    # Prefer CF r2_panels when we have window rows and not a hard failure.
    if cf_rows and cf_status not in {
        "error",
        "invoke_failed",
        "worker_error",
    }:
        preferred_rows = cf_rows
        source_used = str(
            (preferred_rows[0].get("source") if preferred_rows else None) or "cf"
        )
    if not preferred_rows and local_pack and local_pack.get("rows_flat"):
        preferred_rows = list(local_pack.get("rows_flat") or [])
        source_used = "local"

    # Also keep both for audit
    all_rows = []
    if cf_pack:
        all_rows.extend(list(cf_pack.get("rows_flat") or []))
    if local_pack:
        all_rows.extend(list(local_pack.get("rows_flat") or []))

    # Headline per representative (aggregate across windows of preferred)
    by_rep: dict[str, list[dict[str, Any]]] = {}
    for r in preferred_rows:
        rid = str(r.get("representative_id") or "")
        by_rep.setdefault(rid, []).append(r)

    headline: list[dict[str, Any]] = []
    contradictions: list[dict[str, Any]] = []
    for rid, stance in PINNED_STANCES.items():
        rows = by_rep.get(rid) or []
        n_ok = sum(1 for r in rows if r.get("survived"))
        n_win = len(rows)
        nets = [_scalar_f(r.get("mean_net")) for r in rows]
        nets_f = [x for x in nets if x is not None]
        ts = [_scalar_t(r.get("t")) for r in rows]
        ts_f = [x for x in ts if x is not None]
        low_vars = sum(1 for r in rows if r.get("low_variance_artifact"))
        # Aggregate suggest: worst-case across windows
        suggests = [str(r.get("metrics_suggest") or "") for r in rows]
        if any(s == "DEMOTABLE_low_var" for s in suggests):
            agg_suggest = "DEMOTABLE_low_var"
        elif any(s == "WEAK_or_FAIL" for s in suggests) and n_ok == 0:
            agg_suggest = "WEAK_or_FAIL"
        elif any(s == "SUPPORTS_PROMOTE" for s in suggests):
            agg_suggest = "SUPPORTS_PROMOTE"
        elif any(s == "SUPPORTS_KEEP" for s in suggests) or n_ok > 0:
            agg_suggest = "SUPPORTS_KEEP"
        else:
            agg_suggest = "WEAK_or_FAIL" if rows else "NO_DATA"
        contra = _contradiction(stance, agg_suggest)
        # Per-window contradictions
        win_contras = [
            {
                "window": r.get("window"),
                "contradiction": r.get("contradiction"),
                "metrics_suggest": r.get("metrics_suggest"),
                "survived": r.get("survived"),
                "mean_net": r.get("mean_net"),
                "t": r.get("t"),
            }
            for r in rows
            if r.get("contradiction")
        ]
        if contra or win_contras:
            contradictions.append(
                {
                    "representative_id": rid,
                    "pinned_stance": stance,
                    "metrics_suggest_aggregate": agg_suggest,
                    "aggregate_contradiction": contra,
                    "window_contradictions": win_contras,
                    "pins_changed": False,
                    "note": "contradiction recorded; pins held (no retune)",
                }
            )
        pin_map = {
            "cross_section_hold_10": {"hold_days": 10, "momentum_n": 5},
            "cross_section_hold_10_mom3": {"hold_days": 10, "momentum_n": 3},
            "fundamentals_hold_10": {
                "hold_days": 10,
                "momentum_n": 10,
                "mode": "value_momentum_agree",
            },
        }
        pins = dict(pin_map.get(rid) or {})
        headline.append(
            {
                "representative_id": rid,
                "pinned_stance": stance,
                "pins": pins,
                "source": source_used,
                "n_windows": n_win,
                "n_windows_survived": n_ok,
                "mean_net_avg": (
                    sum(nets_f) / len(nets_f) if nets_f else None
                ),
                "t_avg": (sum(ts_f) / len(ts_f) if ts_f else None),
                "n_low_var_windows": low_vars,
                "metrics_suggest_aggregate": agg_suggest,
                "contradiction": contra,
                "pins_changed": False,
                "per_window": [
                    {
                        "window": r.get("window"),
                        "mean_net": r.get("mean_net"),
                        "t": r.get("t"),
                        "act": r.get("act"),
                        "sign": r.get("sign"),
                        "survived": r.get("survived"),
                        "low_variance_artifact": r.get("low_variance_artifact"),
                        "reject_reasons": r.get("reject_reasons"),
                        "metrics_suggest": r.get("metrics_suggest"),
                        "contradiction": r.get("contradiction"),
                    }
                    for r in rows
                ],
            }
        )

    return {
        "wave": "W96 / w0818f",
        "track": "C_default_quality",
        "preferred_source": source_used,
        "frozen_defaults_retuned": False,
        "pinned_stances": dict(PINNED_STANCES),
        "headline": headline,
        "contradictions": contradictions,
        "n_contradictions": len(contradictions),
        "preferred_rows": preferred_rows,
        "all_rows_audit": all_rows,
        "cf_job_id": (cf_pack or {}).get("job_id"),
        "cf_status": (cf_pack or {}).get("status")
        or (cf_pack or {}).get("cf_pack_status"),
        "local_n_rows": len((local_pack or {}).get("rows_flat") or []),
        "gates": ["cost", "PIT", "low_var", "multi_year_windows"],
        "note": (
            "If PROMOTE/KEEP contradicts metrics, contradiction is recorded; "
            "pins are NOT changed."
        ),
    }


def _markdown_default_table(table: Mapping[str, Any]) -> str:
    lines = [
        "# W96 / w0818f — frozen 3-default quality",
        "",
        f"**Preferred source:** `{table.get('preferred_source')}`  ",
        f"**CF job:** `{table.get('cf_job_id')}` · status=`{table.get('cf_status')}`  ",
        f"**Pins retuned:** `{table.get('frozen_defaults_retuned')}`  ",
        f"**Contradictions:** {table.get('n_contradictions')}",
        "",
        "## Headline",
        "",
        "| representative_id | pinned | pins | surv_windows | mean_net_avg | t_avg | low_var | metrics_suggest | contradiction |",
        "|---|---|---|---:|---:|---:|---:|---|---|",
    ]
    for h in table.get("headline") or []:
        pins = h.get("pins") or {}
        pin_s = ", ".join(f"{k}={v}" for k, v in pins.items())
        mn = h.get("mean_net_avg")
        t = h.get("t_avg")
        mn_s = f"{mn:.6f}" if isinstance(mn, float) else "—"
        t_s = f"{t:.4f}" if isinstance(t, float) else "—"
        contra = h.get("contradiction") or "—"
        lines.append(
            f"| `{h.get('representative_id')}` | **{h.get('pinned_stance')}** | "
            f"{pin_s} | {h.get('n_windows_survived')}/{h.get('n_windows')} | "
            f"{mn_s} | {t_s} | {h.get('n_low_var_windows')} | "
            f"{h.get('metrics_suggest_aggregate')} | {contra} |"
        )

    lines += ["", "## Per-window (preferred source)", ""]
    lines += [
        "| window | representative_id | pinned | mean_net | t | act | sign | surv | suggest | contradiction |",
        "|---|---|---|---:|---:|---:|---|---|---|---|",
    ]
    for r in table.get("preferred_rows") or []:
        mn, t, act = r.get("mean_net"), r.get("t"), r.get("act")
        mn_s = f"{mn:.6f}" if isinstance(mn, float) else "—"
        t_s = f"{t:.4f}" if isinstance(t, float) else "—"
        act_s = f"{act:.4f}" if isinstance(act, float) else "—"
        sign = r.get("sign")
        sign_s = "—" if sign is None else str(sign)
        contra = r.get("contradiction") or "—"
        lines.append(
            f"| {r.get('window')} | `{r.get('representative_id')}` | "
            f"{r.get('pinned_stance')} | {mn_s} | {t_s} | {act_s} | "
            f"{sign_s} | {r.get('survived')} | {r.get('metrics_suggest')} | "
            f"{contra} |"
        )

    if table.get("contradictions"):
        lines += ["", "## Contradictions (pins held — no retune)", ""]
        for c in table["contradictions"]:
            lines.append(
                f"- **`{c.get('representative_id')}`** pinned "
                f"`{c.get('pinned_stance')}` → metrics "
                f"`{c.get('metrics_suggest_aggregate')}`: "
                f"{c.get('aggregate_contradiction') or '(window-level only)'}"
            )
            for w in c.get("window_contradictions") or []:
                lines.append(
                    f"  - {w.get('window')}: {w.get('contradiction')} "
                    f"(net={w.get('mean_net')}, t={w.get('t')}, "
                    f"surv={w.get('survived')})"
                )

    lines += [
        "",
        "## Freezes held",
        "",
        "- Mass = NO-GO · READY = false · ops GO = false · continuous paper = UNARMED",
        "- 3 default-path pins **not** retuned",
        "- Gates: cost + PIT + low-var + multi-year windows",
        "",
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--out-dir", type=str, default=str(OUT_DEFAULT))
    p.add_argument("--n-hyps", type=int, default=8)
    p.add_argument("--seed", type=int, default=870818)
    p.add_argument(
        "--provider",
        type=str,
        default="auto",
        help="auto|xai|openai|anthropic|glm|workers_ai|catalog",
    )
    p.add_argument("--model", type=str, default=None)
    p.add_argument("--synthetic", action="store_true")
    p.add_argument("--skip-hyps", action="store_true")
    p.add_argument("--skip-cf", action="store_true")
    p.add_argument("--skip-local-defaults", action="store_true")
    p.add_argument("--skip-deploy", action="store_true")
    p.add_argument(
        "--mode",
        type=str,
        default="r2_panels",
        choices=["r2_panels", "synthetic", "nets_only", "d1_bars"],
    )
    p.add_argument("--max-codes", type=int, default=15)
    p.add_argument("--max-days", type=int, default=200)
    p.add_argument("--cf-url", type=str, default=CF_WORKER_URL)
    p.add_argument("--quiet", action="store_true")
    args = p.parse_args(argv)

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    t0 = time.perf_counter()
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    def log(msg: str) -> None:
        if not args.quiet:
            print(msg, flush=True)

    from research.mass_strategy_factory import (
        CONTINUOUS_PAPER,
        FROZEN_DEFAULT_PATH,
        MASS_FACTORY_VERSION,
        MASS_RESEARCH,
        PHASE7,
    )

    log(f"[w96] out={out_dir} ts={ts}")
    log(
        f"[w96] freezes: mass={MASS_RESEARCH} phase7={PHASE7} "
        f"paper={CONTINUOUS_PAPER} READY=False ops_GO=False "
        f"frozen_defaults_retuned=False factory={MASS_FACTORY_VERSION}"
    )
    log(
        "[w96] 3 defaults frozen: "
        + ", ".join(
            f"{r['representative_id']}={r['stance']}" for r in FROZEN_DEFAULT_PATH
        )
    )

    # ------------------------------------------------------------------ B
    hyp_pack: dict[str, Any] = {}
    if not args.skip_hyps:
        hyp_pack = run_track_b_hyps(
            out_dir=out_dir,
            n_hyps=int(args.n_hyps),
            provider=str(args.provider),
            model=args.model,
            seed=int(args.seed),
            synthetic=bool(args.synthetic),
            cf_url=str(args.cf_url),
            log=log,
        )
    else:
        log("[w96/B] skipped")

    # ------------------------------------------------------------------ C local
    local_pack: dict[str, Any] = {}
    if not args.skip_local_defaults:
        local_pack = run_track_c_defaults_local(
            out_dir=out_dir,
            seed=int(args.seed),
            max_codes=int(args.max_codes),
            max_days=int(args.max_days),
            log=log,
        )
        log(
            f"[w96/C] local survivors={local_pack.get('n_survivors')} "
            f"contradictions={local_pack.get('n_contradictions')}"
        )
    else:
        log("[w96/C] local defaults skipped")

    # ------------------------------------------------------------------ C CF
    cf_pack: dict[str, Any] = {}
    if not args.skip_cf:
        cf_pack = run_track_c_defaults_cf(
            out_dir=out_dir,
            seed=int(args.seed),
            max_codes=int(args.max_codes),
            max_days=int(args.max_days),
            mode=str(args.mode),
            worker_url=str(args.cf_url),
            skip_deploy=bool(args.skip_deploy),
            log=log,
        )
    else:
        log("[w96/C] CF defaults skipped")

    # ------------------------------------------------------------------ tables
    table = _aggregate_default_table(local_pack=local_pack, cf_pack=cf_pack)
    _dump(out_dir / "default_quality_table.json", table)
    md = _markdown_default_table(table)
    (out_dir / "default_quality_table.md").write_text(md + "\n", encoding="utf-8")
    log(f"[w96/C] wrote default_quality_table.json/md source={table.get('preferred_source')}")

    hyp_summary = (hyp_pack or {}).get("summary") or {}
    wall = round(time.perf_counter() - t0, 2)
    run_summary = {
        "wave": "W96 / w0818f",
        "tracks": ["B_new_hyps", "C_default_quality"],
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "wall_sec": wall,
        "hyps": {
            "n_proposed": hyp_summary.get("n_proposed"),
            "n_accepted": hyp_summary.get("n_accepted"),
            "n_rejected": hyp_summary.get("n_rejected"),
            "n_survivors": hyp_summary.get("n_survivors"),
            "provider": hyp_summary.get("provider"),
            "model": hyp_summary.get("model"),
            "representative_theses": hyp_summary.get("representative_theses"),
        },
        "defaults": {
            "preferred_source": table.get("preferred_source"),
            "cf_job_id": table.get("cf_job_id"),
            "cf_status": table.get("cf_status"),
            "n_contradictions": table.get("n_contradictions"),
            "headline": table.get("headline"),
            "frozen_defaults_retuned": False,
        },
        "freezes": {
            "mass_research": MASS_RESEARCH,
            "phase7": PHASE7,
            "continuous_paper": CONTINUOUS_PAPER,
            "ready_declared": False,
            "operational_go": False,
            "frozen_defaults_retuned": False,
        },
    }
    _dump(out_dir / "w96_bc_summary.json", run_summary)
    log(f"[w96] done wall_sec={wall}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
