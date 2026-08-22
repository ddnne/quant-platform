"""Factory batch evaluation (period-net screen; not GO / READY).

Per-strategy eval and auto-screen. Cached panels live in
``research.offline.factory_eval_data``. Generation stays in
``research.offline.factory``. Unique/combo generation_enabled stays False.
"""

from __future__ import annotations

import math
import time
import traceback
from statistics import mean
from typing import Any, Callable, Mapping, Sequence

from features.class_signals import (
    DEFAULT_HOLD_DAYS,
    amortized_one_way_cost,
    apply_sticky_hold,
    multi_day_forward_return,
    sign_from_numeric,
)
from research.freezes import (
    CONTINUOUS_PAPER,
    FROZEN_DEFAULT_PATH,
)
from research.hypothesis_classes import (
    CLASS_CROSS_SECTION_RELATIVE,
    CLASS_EVENT_POST,
    CLASS_FLOW_DEMAND,
    CLASS_FUNDAMENTALS_PRICE,
    CLASS_MACRO_CONDITIONED,
    CLASS_MULTI_DAY_HOLD,
)
from research.offline.factory_templates import (
    FAMILY_INDEX_VOL_REGIME,
    FAMILY_MULTI_FACTOR,
    FAMILY_OPTIONS_VOL_REGIME,
    FAMILY_RATE_FACTOR,
    FAMILY_VOL_RISK_ADJUSTED,
    RESEARCH_UNIQUE_FAMILY_IDS,
)
from research.sign_selection import (
    SIGN_INVERTED,
    SIGN_ORIGINAL,
    choose_sign,
    evaluate_sign_both_sides,
)
from research.stats_metrics import (
    period_stats_report,
    sample_mean,
    t_stat_vs_zero,
)
from research.unique_logic.constants import RESEARCH_UNIQUE_LOGIC_IDS

# Function-default bindings; must match research.offline.factory.
DEFAULT_NEAR_ZERO_ABS: float = 0.0005
DEFAULT_MIN_ACTIVATION: float = 0.01
SCREEN_NEAR_ZERO: str = "near_zero_after_cost"
SCREEN_POST_COST_COLLAPSE: str = "post_cost_collapse"
SCREEN_DATA_MISSING: str = "data_missing"
SCREEN_EVAL_ERROR: str = "eval_error"
SCREEN_NO_PERIODS: str = "no_ok_periods"
SCREEN_LOW_ACTIVATION: str = "low_activation"
SCREEN_BOTH_SIGNS_FAIL: str = "both_signs_near_zero_or_nonpositive"
SCREEN_INFLATED_T_LOW_VARIANCE: str = "inflated_t_low_variance"


def _eval_research_unique_on_panel(
    logic_id: str,
    params: Mapping[str, Any],
    panel: Mapping[str, Any],
    *,
    one_way_cost: float,
) -> dict[str, Any]:
    """Factory dispatch for research-family unique_logic.

    Recognition eval only. Does not mint research_candidate / GO / main.
    Factory synthetic period-net is not a pass. Family append is not promotion.
    """
    from research.unique_logic import all_unique_logic_specs
    from research.unique_logic.dispatch import evaluate_logic_daily_mtm

    spec: dict[str, Any] = {"logic_id": logic_id, "params": dict(params)}
    for cand in all_unique_logic_specs():
        if cand.get("logic_id") == logic_id:
            spec = dict(cand)
            merged = dict(cand.get("params") or {})
            merged.update(dict(params or {}))
            spec["params"] = merged
            break
    bars = panel.get("bars") or {}
    events = panel.get("fins_events") or {}
    repo = panel.get("repo_series") or {}
    curve = panel.get("curve_series") or {}
    overnight = dict(
        (curve or {}).get("short_rates_by_date")
        or (repo or {}).get("rates_by_date")
        or {}
    )
    margin_raw = panel.get("margin") or {}
    margin_by_code: dict[str, dict[str, float]] = {}
    for code, pairs in (margin_raw or {}).items():
        if isinstance(pairs, Mapping):
            margin_by_code[str(code)] = {
                str(k)[:10]: float(v) for k, v in pairs.items() if v is not None
            }
        else:
            margin_by_code[str(code)] = {
                str(d)[:10]: float(v) for d, v in (pairs or []) if v is not None
            }
    p0 = panel.get("period_start")
    p1 = panel.get("period_end")
    topix = dict(panel.get("topix") or panel.get("topix_by_date") or {})
    pack = evaluate_logic_daily_mtm(
        spec,
        bars=bars,
        overnight=overnight,
        curve=curve,
        events=events,
        margin_by_code=margin_by_code,
        topix_by_date=topix,
        one_way_cost=one_way_cost,
        period_start=p0,
        period_end=p1,
    )
    if pack.get("status") == "unknown_logic":
        return {
            "status": "error",
            "skip_reason": f"unregistered_research_unique:{logic_id}",
            "gross_signed_mean_active": None,
            "net_one_way_mean_active": None,
            "research_family_recognition": True,
            "registration_is_not_a_pass": True,
            "promote_as_main": False,
            "go": False,
            "research_candidate": False,
        }

    if pack.get("status") != "ok":
        return {
            "status": "data_missing" if pack.get("daily_path_complete") is False else "error",
            "skip_reason": str(
                pack.get("incomplete_reason") or pack.get("status") or "research_unique_incomplete"
            ),
            "gross_signed_mean_active": None,
            "net_one_way_mean_active": None,
            "research_family_recognition": True,
            "registration_is_not_a_pass": True,
            "promote_as_main": False,
            "go": False,
            "research_candidate": False,
            "n_entered": pack.get("n_entered"),
            "n_events": pack.get("n_events"),
        }

    n_cal = int(pack.get("n_calendar_days") or 0)
    n_act = int(pack.get("n_active_days") or 0)
    h = pack.get("hold_days") or pack.get("post_hold_days") or 5
    return {
        "status": "ok",
        "gross_signed_mean_active": pack.get("mean_gross_daily"),
        "net_one_way_mean_active": pack.get("mean_net_daily"),
        "amortized_one_way_cost": pack.get("amortized_one_way_cost")
        or pack.get("one_way_cost"),
        "n_active_positions": n_act,
        "occurrence": {
            "activation_rate": (float(n_act) / float(n_cal) if n_cal else None),
            "n_active": n_act,
            "n_calendar": n_cal,
            "n_entered": pack.get("n_entered"),
            "n_events": pack.get("n_events"),
            "n_ranked_days": pack.get("n_ranked_days"),
        },
        "signal_id": logic_id,
        "hold_days": int(h) if h is not None else None,
        "research_family_recognition": True,
        "registration_is_not_a_pass": True,
        "research_candidate": False,
        "promote_as_main": False,
        "go": False,
    }


def _eval_on_panel(
    family_id: str,
    params: Mapping[str, Any],
    panel: Mapping[str, Any],
    *,
    one_way_cost: float,
    logic_id: str | None = None,
) -> dict[str, Any]:
    """Dispatch pure evaluator for one strategy × one period panel."""
    from research.eval_loaders import momentum_series
    from research.offline.bar_eval import (
        evaluate_cross_section_on_bars,
        evaluate_event_post_on_bars,
        evaluate_flow_demand_on_bars,
        evaluate_fundamentals_price_on_bars,
        evaluate_macro_conditioned_on_bars,
        evaluate_mf_flow_price_on_bars,
        evaluate_mf_value_mom_rate_on_bars,
        evaluate_multi_day_hold_on_bars,
        evaluate_nky_vol_abs_level_on_bars,
        evaluate_nky_vol_term_levels_on_bars,
        evaluate_nky_vol_term_ratio_on_bars,
        evaluate_opt225_vol_on_bars,
        evaluate_rate_curve_xs_on_bars,
        evaluate_rate_level_xs_on_bars,
        evaluate_vol_risk_adjusted_on_bars,
    )

    bars = panel.get("bars") or {}
    if not bars:
        return {
            "status": "data_missing",
            "skip_reason": "empty_or_missing_bars",
            "gross_signed_mean_active": None,
            "net_one_way_mean_active": None,
        }

    fid = str(family_id)
    p = dict(params)
    if fid == CLASS_MULTI_DAY_HOLD:
        polarity = int(p.get("signal_polarity") or 1)
        if polarity >= 0:
            out = evaluate_multi_day_hold_on_bars(
                bars,
                hold_days=int(p.get("hold_days") or DEFAULT_HOLD_DAYS),
                one_way_cost=one_way_cost,
                rebalance_mode=str(p.get("rebalance_mode") or "fixed_horizon"),
            )
        else:
            # Mean-reversion entry: invert momentum sign at signal time
            out = _evaluate_mdh_polarity_on_bars(
                bars,
                hold_days=int(p.get("hold_days") or DEFAULT_HOLD_DAYS),
                one_way_cost=one_way_cost,
                rebalance_mode=str(p.get("rebalance_mode") or "fixed_horizon"),
                polarity=-1,
                momentum_series_fn=momentum_series,
            )
    elif fid == CLASS_CROSS_SECTION_RELATIVE:
        out = evaluate_cross_section_on_bars(
            bars,
            momentum_n=int(p.get("momentum_n") or 5),
            hold_days=int(p.get("hold_days") or 5),
            long_frac=float(p.get("long_frac") or 0.3),
            short_frac=float(p.get("short_frac") or 0.3),
            one_way_cost=one_way_cost,
        )
    elif fid == CLASS_MACRO_CONDITIONED:
        out = evaluate_macro_conditioned_on_bars(
            bars,
            panel.get("repo_series"),
            momentum_n=int(p.get("momentum_n") or 5),
            hold_days=int(p.get("hold_days") or 5),
            mode=str(p.get("mode") or "rate_change"),
            one_way_cost=one_way_cost,
            high_threshold=float(p.get("high_threshold") or 0.05),
            low_threshold=float(p.get("low_threshold") or 0.0),
        )
    elif fid == FAMILY_RATE_FACTOR:
        mode = str(p.get("mode") or "rate_level_xs_risk_adj")
        if mode == "rate_curve_shape_xs":
            out = evaluate_rate_curve_xs_on_bars(
                bars,
                panel.get("curve_series"),
                momentum_n=int(p.get("momentum_n") or 5),
                hold_days=int(p.get("hold_days") or 10),
                long_frac=float(p.get("long_frac") or 0.3),
                short_frac=float(p.get("short_frac") or 0.3),
                one_way_cost=one_way_cost,
                steep_threshold=float(p.get("steep_threshold") or 0.0),
                invert_threshold=float(p.get("invert_threshold") or 0.0),
            )
        else:
            out = evaluate_rate_level_xs_on_bars(
                bars,
                panel.get("repo_series"),
                momentum_n=int(p.get("momentum_n") or 5),
                hold_days=int(p.get("hold_days") or 10),
                long_frac=float(p.get("long_frac") or 0.3),
                short_frac=float(p.get("short_frac") or 0.3),
                one_way_cost=one_way_cost,
                high_threshold=float(p.get("high_threshold") or 0.05),
                low_threshold=float(p.get("low_threshold") or 0.0),
            )
    elif fid == FAMILY_MULTI_FACTOR:
        mode = str(p.get("mode") or "value_mom_rate")
        if mode == "flow_price":
            out = evaluate_mf_flow_price_on_bars(
                bars,
                panel.get("margin") or {},
                hold_days=int(p.get("hold_days") or 10),
                momentum_n=int(p.get("momentum_n") or 10),
                one_way_cost=one_way_cost,
            )
        else:
            out = evaluate_mf_value_mom_rate_on_bars(
                bars,
                panel.get("fins_events") or {},
                panel.get("repo_series"),
                hold_days=int(p.get("hold_days") or 10),
                momentum_n=int(p.get("momentum_n") or 10),
                one_way_cost=one_way_cost,
                high_threshold=float(p.get("high_threshold") or 0.05),
                low_threshold=float(p.get("low_threshold") or 0.0),
            )
    elif fid == CLASS_EVENT_POST:
        out = evaluate_event_post_on_bars(
            bars,
            panel.get("fins_events") or {},
            post_hold_days=int(p.get("post_hold_days") or 5),
            one_way_cost=one_way_cost,
            period_start=panel.get("period_start"),
            period_end=panel.get("period_end"),
            entry_mode=str(p.get("entry_mode") or "same_day_close_if_pre_close"),
        )
    elif fid == CLASS_FUNDAMENTALS_PRICE:
        out = evaluate_fundamentals_price_on_bars(
            bars,
            panel.get("fins_events") or {},
            hold_days=int(p.get("hold_days") or 10),
            momentum_n=int(p.get("momentum_n") or 10),
            one_way_cost=one_way_cost,
            mode=str(p.get("mode") or "value_momentum_agree"),
        )
    elif fid == CLASS_FLOW_DEMAND:
        out = evaluate_flow_demand_on_bars(
            bars,
            panel.get("margin") or {},
            panel.get("short_series"),
            hold_days=int(p.get("hold_days") or 5),
            one_way_cost=one_way_cost,
            require_short_confirm=bool(p.get("require_short_confirm") or False),
            short_confirm_mode=str(p.get("short_confirm_mode") or "off"),
        )
    elif fid == FAMILY_VOL_RISK_ADJUSTED:
        out = evaluate_vol_risk_adjusted_on_bars(
            bars,
            hold_days=int(p.get("hold_days") or 5),
            vol_n=int(p.get("vol_n") or 10),
            vol_threshold=float(p.get("vol_threshold") or 1.0),
            one_way_cost=one_way_cost,
            gate_mode=str(p.get("gate_mode") or "mom_over_vol"),
        )
    elif fid == FAMILY_INDEX_VOL_REGIME:
        mode = str(p.get("mode") or "nky_vol_abs_level")
        nky = panel.get("nky_vol_series")
        common_kw = dict(
            momentum_n=int(p.get("momentum_n") or 5),
            hold_days=int(p.get("hold_days") or 10),
            long_frac=float(p.get("long_frac") or 0.3),
            short_frac=float(p.get("short_frac") or 0.3),
            one_way_cost=one_way_cost,
        )
        if mode == "nky_vol_term_ratio":
            out = evaluate_nky_vol_term_ratio_on_bars(
                bars,
                nky,
                expand_ratio=float(p.get("expand_ratio") or 1.20),
                compress_ratio=float(p.get("compress_ratio") or 0.80),
                **common_kw,
            )
        elif mode == "nky_vol_term_levels":
            out = evaluate_nky_vol_term_levels_on_bars(
                bars,
                nky,
                high_threshold=float(p.get("high_threshold") or 0.20),
                low_threshold=float(p.get("low_threshold") or 0.10),
                **common_kw,
            )
        else:
            out = evaluate_nky_vol_abs_level_on_bars(
                bars,
                nky,
                high_threshold=float(p.get("high_threshold") or 0.20),
                low_threshold=float(p.get("low_threshold") or 0.10),
                **common_kw,
            )
    elif fid == FAMILY_OPTIONS_VOL_REGIME:
        mode = str(p.get("mode") or "opt225_basevol_abs_level")
        sk = str(p.get("series_kind") or "basevol")
        _hi = {
            "basevol": 24.0, "atm_iv": 25.0, "spread": 1.0, "spread_change": 0.5,
            "skew": 3.0, "cm_term": 2.0, "basevol_delta": 1.0,
        }.get(sk, 24.0)
        _lo = {
            "basevol": 12.0, "atm_iv": 12.0, "spread": -0.5, "spread_change": -0.5,
            "skew": 0.5, "cm_term": -1.0, "basevol_delta": -1.0,
        }.get(sk, 12.0)
        out = evaluate_opt225_vol_on_bars(
            bars,
            panel.get("opt225_regime"),
            mode=mode,
            series_kind=sk,
            momentum_n=int(p.get("momentum_n") or 5),
            hold_days=int(p.get("hold_days") or 10),
            long_frac=float(p.get("long_frac") or 0.3),
            short_frac=float(p.get("short_frac") or 0.3),
            one_way_cost=one_way_cost,
            high_threshold=float(
                p["high_threshold"] if p.get("high_threshold") is not None else _hi
            ),
            low_threshold=float(
                p["low_threshold"] if p.get("low_threshold") is not None else _lo
            ),
            expand_ratio=float(p.get("expand_ratio") or 1.20),
            compress_ratio=float(p.get("compress_ratio") or 0.80),
        )
    elif fid in RESEARCH_UNIQUE_FAMILY_IDS or (
        logic_id and str(logic_id) in RESEARCH_UNIQUE_LOGIC_IDS
    ):
        out = _eval_research_unique_on_panel(
            str(logic_id or p.get("mode") or ""),
            p,
            panel,
            one_way_cost=one_way_cost,
        )
        return out
    else:
        return {
            "status": "error",
            "skip_reason": f"unknown_family:{fid}",
            "gross_signed_mean_active": None,
            "net_one_way_mean_active": None,
        }

    return {
        "status": "ok",
        "gross_signed_mean_active": out.get("gross_signed_mean_active"),
        "net_one_way_mean_active": out.get("net_one_way_mean_active"),
        "amortized_one_way_cost": out.get("amortized_one_way_cost")
        or out.get("one_way_cost"),
        "n_active_positions": out.get("n_active_positions"),
        "occurrence": out.get("occurrence"),
        "signal_id": out.get("signal_id"),
        "hold_days": out.get("hold_days") or out.get("hold_days_documented"),
    }


def _evaluate_mdh_polarity_on_bars(
    bars_by_code: Mapping[str, Sequence[tuple[str, float]]],
    *,
    hold_days: int,
    one_way_cost: float,
    rebalance_mode: str,
    polarity: int,
    momentum_series_fn: Callable[..., Any],
) -> dict[str, Any]:
    """Multi-day hold with explicit entry polarity (reversion when −1)."""
    h = int(hold_days)
    am_cost = amortized_one_way_cost(one_way_cost, h)
    signed_returns: list[float] = []
    n_active = 0
    holding_records: list[dict[str, Any]] = []
    pol = -1.0 if int(polarity) < 0 else 1.0

    for code, pairs in sorted(bars_by_code.items()):
        pairs_l = list(pairs)
        if len(pairs_l) < h + 2:
            continue
        moms = momentum_series_fn(pairs_l, n=h)
        entry_signs = []
        for _, m in moms:
            s = sign_from_numeric(m)
            if s is None:
                entry_signs.append(None)
            else:
                entry_signs.append(float(s) * pol)
        held = apply_sticky_hold(
            entry_signs, hold_days=h, rebalance_mode=rebalance_mode
        )
        closes = [c for _, c in pairs_l]
        dates = [d for d, _ in pairs_l]
        for i, pos in enumerate(held):
            holding_records.append({"date": dates[i], "code": code, "sign": pos})
            if pos is None or pos == 0.0:
                continue
            if rebalance_mode == "fixed_horizon" and i % h != 0:
                continue
            fwd = multi_day_forward_return(closes, hold_days=h, entry_index=i)
            if fwd is None:
                continue
            n_active += 1
            signed_returns.append(float(pos) * float(fwd))

    gross = mean(signed_returns) if signed_returns else None
    net = (gross - am_cost) if gross is not None else None
    n_code_days = len(holding_records)
    return {
        "signal_id": "c21_multi_day_hold_reversion",
        "hypothesis_class": CLASS_MULTI_DAY_HOLD,
        "hold_days": h,
        "signal_polarity": int(polarity),
        "gross_signed_mean_active": gross,
        "net_one_way_mean_active": net,
        "amortized_one_way_cost": am_cost,
        "one_way_cost": float(one_way_cost),
        "n_active_positions": n_active,
        "n_signed_returns": len(signed_returns),
        "occurrence": {
            "activation_rate": (
                float(n_active) / float(n_code_days) if n_code_days else None
            ),
            "n_active": n_active,
        },
        **_freeze(),
        "note": "Mean-reversion entry polarity=-1. Not eval sign flip. Not READY.",
    }


def evaluate_one_strategy(
    strategy: Mapping[str, Any],
    ctx: BatchDataContext,
    *,
    near_zero_abs: float = DEFAULT_NEAR_ZERO_ABS,
    min_activation: float = DEFAULT_MIN_ACTIVATION,
) -> dict[str, Any]:
    """Evaluate one strategy across all periods; both signs after cost."""
    sid = str(strategy.get("strategy_id") or "")
    family = str(strategy.get("family_id") or "")
    params = dict(strategy.get("params") or {})
    logic_id = str(strategy.get("logic_id") or "")
    period_rows: list[dict[str, Any]] = []
    errors: list[str] = []

    for panel in ctx.panels:
        pid = str(panel.get("period_id") or "")
        if panel.get("status") not in {"ok", None} and not panel.get("bars"):
            period_rows.append(
                {
                    "period_id": pid,
                    "status": "data_missing",
                    "gross_signed_mean_active": None,
                    "net_one_way_mean_active": None,
                }
            )
            continue
        try:
            ev = _eval_on_panel(
                family,
                params,
                panel,
                one_way_cost=ctx.one_way_cost,
                logic_id=logic_id,
            )
            row = {
                "period_id": pid,
                "year": panel.get("year"),
                **ev,
            }
            period_rows.append(row)
        except Exception as exc:
            errors.append(f"{pid}:{type(exc).__name__}:{exc}")
            period_rows.append(
                {
                    "period_id": pid,
                    "status": "error",
                    "error": f"{type(exc).__name__}: {exc}",
                    "gross_signed_mean_active": None,
                    "net_one_way_mean_active": None,
                }
            )

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
    side_nets = list(side.get("nets") or nets)
    stats = period_stats_report(side_nets)
    mean_net = side.get("mean_net")
    if mean_net is None:
        mean_net = sample_mean(nets)
    mean_gross = sample_mean(grosses)
    t_stat = side.get("t_stat")
    if t_stat is None:
        t_stat = t_stat_vs_zero(side_nets)

    return {
        "strategy_id": sid,
        "logic_id": logic_id,
        "logic_fingerprint": strategy.get("logic_fingerprint"),
        "thesis": strategy.get("thesis"),
        "family_id": family,
        "params": params,
        "n_periods_ok": len(ok_rows),
        "n_periods_total": len(period_rows),
        "period_rows": period_rows,
        "mean_gross": mean_gross,
        "mean_net": mean_net,
        "t_stat": t_stat,
        "sharpe_period": stats.get("sharpe"),
        "win_rate": stats.get("win_rate"),
        "n_positive_periods": stats.get("n_positive"),
        "mean_activation": mean_activation,
        "sign_selection": {
            "chosen_sign": chosen_sign,
            "decision": choice.get("decision"),
            "reason": choice.get("reason"),
            "original_mean_net": (both.get("original") or {}).get("mean_net"),
            "inverted_mean_net": (both.get("inverted") or {}).get("mean_net"),
        },
        "chosen_sign": chosen_sign,
        "period_stats": stats,
        "errors": errors,
        "status": "evaluated",
        **_freeze(),
    }


def screen_strategy_result(
    result: Mapping[str, Any],
    *,
    near_zero_abs: float = DEFAULT_NEAR_ZERO_ABS,
    min_activation: float = DEFAULT_MIN_ACTIVATION,
) -> dict[str, Any]:
    """Auto-reject near-zero / data missing / post-cost collapse / both-sign fail."""
    reasons: list[str] = []
    n_ok = int(result.get("n_periods_ok") or 0)
    if n_ok <= 0:
        reasons.append(SCREEN_NO_PERIODS)
    period_rows = list(result.get("period_rows") or [])
    if any(r.get("status") == "data_missing" for r in period_rows) and n_ok == 0:
        reasons.append(SCREEN_DATA_MISSING)
    if result.get("errors"):
        if n_ok == 0:
            reasons.append(SCREEN_EVAL_ERROR)

    mean_gross = result.get("mean_gross")
    mean_net = result.get("mean_net")
    if mean_gross is not None and mean_net is not None:
        try:
            g, n = float(mean_gross), float(mean_net)
            if abs(g) >= near_zero_abs and abs(n) < near_zero_abs:
                reasons.append(SCREEN_POST_COST_COLLAPSE)
            if g > near_zero_abs and n < -near_zero_abs and (g - n) > abs(g):
                if SCREEN_POST_COST_COLLAPSE not in reasons:
                    reasons.append(SCREEN_POST_COST_COLLAPSE)
        except (TypeError, ValueError):
            pass

    if mean_net is not None:
        try:
            if abs(float(mean_net)) < near_zero_abs:
                reasons.append(SCREEN_NEAR_ZERO)
        except (TypeError, ValueError):
            pass
    else:
        if n_ok > 0:
            reasons.append(SCREEN_NEAR_ZERO)

    ss = dict(result.get("sign_selection") or {})
    if ss.get("decision") in {"reject", "explore_demote"} or ss.get("chosen_sign") is None:
        if n_ok > 0:
            reasons.append(SCREEN_BOTH_SIGNS_FAIL)

    act = result.get("mean_activation")
    if act is not None:
        try:
            if float(act) < float(min_activation) and n_ok > 0:
                reasons.append(SCREEN_LOW_ACTIVATION)
        except (TypeError, ValueError):
            pass

    # W95 low-variance / inflated-t demotion (window or pairwise subset).
    t_reason = str(result.get("t_stat_reason") or "")
    if t_reason == "low_variance_artifact" or result.get("low_variance_artifact"):
        reasons.append(SCREEN_INFLATED_T_LOW_VARIANCE)
    elif n_ok >= 2:
        try:
            from research.stats_metrics import (
                LOW_VARIANCE_REASON,
                has_pairwise_low_variance_artifact,
                t_stat_vs_zero,
            )

            nets = [
                r.get("net_one_way_mean_active")
                for r in period_rows
                if r.get("status") == "ok"
            ]
            full = t_stat_vs_zero(nets)
            if full.get("reason") == LOW_VARIANCE_REASON or has_pairwise_low_variance_artifact(
                nets
            ):
                reasons.append(SCREEN_INFLATED_T_LOW_VARIANCE)
        except Exception:
            pass

    seen: set[str] = set()
    uniq: list[str] = []
    for r in reasons:
        if r not in seen:
            seen.add(r)
            uniq.append(r)

    survived = len(uniq) == 0 and n_ok > 0
    return {
        "strategy_id": result.get("strategy_id"),
        "logic_id": result.get("logic_id"),
        "family_id": result.get("family_id"),
        "survived": survived,
        "reject_reasons": uniq,
        "mean_net": mean_net,
        "mean_gross": mean_gross,
        "t_stat": result.get("t_stat"),
        "sharpe_period": result.get("sharpe_period"),
        "chosen_sign": result.get("chosen_sign"),
        "mean_activation": act,
        "n_periods_ok": n_ok,
    }


def run_batch_eval(
    generation: Mapping[str, Any],
    *,
    config: MassFactoryConfig | None = None,
    ctx: BatchDataContext | None = None,
    synthetic: bool = False,
    progress_cb: Callable[[int, int, str], None] | None = None,
) -> dict[str, Any]:
    """Batch-evaluate distinct logics (after dedup); fail-one-continue.

    Does **not** pick human main candidates. continuous paper UNARMED.
    Does **not** retune frozen default-path representatives.
    """
    t0 = time.perf_counter()
    cfg = config or MassFactoryConfig(
        seed=int((generation.get("config") or {}).get("seed") or DEFAULT_SEED),
        n=int(generation.get("n_requested") or DEFAULT_N),
    )
    if ctx is None:
        ctx = load_batch_data_context(cfg, synthetic=synthetic)

    # Prefer after-dedup strategies (distinct logics)
    if cfg.eval_after_dedup and generation.get("strategies_after_dedup"):
        strategies = list(generation.get("strategies_after_dedup") or [])
        eval_set = "after_dedup"
    else:
        strategies = list(generation.get("strategies") or [])
        eval_set = "generated_all"

    results: list[dict[str, Any]] = []
    screens: list[dict[str, Any]] = []
    n_fail = 0
    n_ok_eval = 0

    for i, strat in enumerate(strategies):
        sid = str(strat.get("strategy_id") or f"idx{i}")
        if progress_cb is not None:
            progress_cb(i + 1, len(strategies), sid)
        try:
            res = evaluate_one_strategy(
                strat,
                ctx,
                near_zero_abs=cfg.near_zero_abs,
                min_activation=cfg.min_activation,
            )
            n_ok_eval += 1
        except Exception as exc:
            n_fail += 1
            if not cfg.fail_one_continue:
                raise
            res = {
                "strategy_id": sid,
                "logic_id": strat.get("logic_id"),
                "family_id": strat.get("family_id"),
                "params": strat.get("params"),
                "status": "eval_error",
                "errors": [f"{type(exc).__name__}: {exc}"],
                "error_traceback": traceback.format_exc(limit=5),
                "n_periods_ok": 0,
                "n_periods_total": 0,
                "period_rows": [],
                "mean_gross": None,
                "mean_net": None,
                "t_stat": None,
                "sharpe_period": None,
                "chosen_sign": None,
                "sign_selection": {"decision": "reject", "reason": "eval_error"},
                **_freeze(),
            }
        scr = screen_strategy_result(
            res,
            near_zero_abs=cfg.near_zero_abs,
            min_activation=cfg.min_activation,
        )
        res["screen"] = scr
        results.append(res)
        screens.append(scr)

    survivors = [s for s in screens if s.get("survived")]
    rejected = [s for s in screens if not s.get("survived")]

    def _rank_key(s: Mapping[str, Any]) -> tuple[float, float]:
        t = s.get("t_stat")
        m = s.get("mean_net")
        tv = abs(float(t)) if t is not None and math.isfinite(float(t)) else -1.0
        mv = float(m) if m is not None and math.isfinite(float(m)) else -1e9
        return (tv, mv)

    survivors_ranked = sorted(survivors, key=_rank_key, reverse=True)

    by_family: dict[str, list[dict[str, Any]]] = {}
    by_logic: dict[str, list[dict[str, Any]]] = {}
    for s in survivors_ranked:
        by_family.setdefault(str(s.get("family_id")), []).append(dict(s))
        by_logic.setdefault(str(s.get("logic_id") or ""), []).append(dict(s))
    family_top: dict[str, list[dict[str, Any]]] = {
        f: rows[:3] for f, rows in sorted(by_family.items())
    }
    survivor_family_dist = {f: len(v) for f, v in by_family.items()}
    survivor_logic_dist = {k: len(v) for k, v in by_logic.items() if k}

    reason_hist: dict[str, int] = {}
    for s in rejected:
        for r in s.get("reject_reasons") or ["unspecified"]:
            reason_hist[str(r)] = reason_hist.get(str(r), 0) + 1

    wall = time.perf_counter() - t0
    ranking = [
        {
            "rank": i + 1,
            "strategy_id": s.get("strategy_id"),
            "logic_id": s.get("logic_id"),
            "family_id": s.get("family_id"),
            "mean_net": s.get("mean_net"),
            "t_stat": s.get("t_stat"),
            "sharpe_period": s.get("sharpe_period"),
            "chosen_sign": s.get("chosen_sign"),
            "mean_activation": s.get("mean_activation"),
        }
        for i, s in enumerate(survivors_ranked)
    ]

    paper_note = {
        "continuous_paper": CONTINUOUS_PAPER,
        "paper_sample_k": int(cfg.paper_sample_k),
        "paper_ran": False,
        "note": (
            "Optional short paper only for sample subset (top-k); "
            "not full papers. continuous paper UNARMED this wave."
        ),
    }
    if cfg.paper_sample_k > 0 and survivors_ranked:
        paper_note["sample_ids"] = [
            s.get("strategy_id") for s in survivors_ranked[: cfg.paper_sample_k]
        ]
        paper_note["note"] += " Sample ids recorded only; paper runner not armed."

    return {
        "version": MASS_FACTORY_VERSION,
        "wave": MASS_FACTORY_WAVE,
        "config": cfg.to_dict(),
        "data_load_notes": ctx.load_notes,
        "eval_set": eval_set,
        "n_strategies_evaluated": len(strategies),
        "n_eval_ok": n_ok_eval,
        "n_eval_fail": n_fail,
        "fail_rate": (n_fail / len(strategies)) if strategies else 0.0,
        "n_survivors": len(survivors),
        "n_screen_rejected": len(rejected),
        "wall_time_sec": round(wall, 3),
        "n_generated": generation.get("n_generated")
        or generation.get("n_generated_accepted"),
        "n_unique_logic": generation.get("n_unique_logic"),
        "n_after_dedup": generation.get("n_after_dedup"),
        "n_numeric_variant": generation.get("n_numeric_variant"),
        "n_ge_100_generated": bool(generation.get("n_ge_100")),
        "n_generated_accepted": generation.get("n_generated_accepted"),
        "generation_family_distribution": generation.get("family_distribution"),
        "generation_logic_distribution": generation.get("logic_distribution"),
        "survivor_family_distribution": survivor_family_dist,
        "survivor_logic_distribution": survivor_logic_dist,
        "family_top_survivors": family_top,
        "ranking": ranking,
        "reject_reason_histogram": reason_hist,
        "screens": screens,
        "results": results,
        "paper": paper_note,
        "human_main_candidates_selected": False,
        "frozen_default_path": list(FROZEN_DEFAULT_PATH),
        "frozen_defaults_retuned": False,
        "note": (
            "Auto screen on distinct logics only (after near-dup). "
            "Do NOT treat survivors as human main candidates or "
            "research_candidate production defaults. "
            "3 frozen defaults untouched. Mass/READY/ops GO remain closed."
        ),
        **_freeze(),
    }


from research.offline.factory_eval_data import (  # noqa: E402
    BatchDataContext,
    load_batch_data_context,
)
from research.offline.factory import (  # noqa: E402
    DEFAULT_N,
    DEFAULT_SEED,
    MASS_FACTORY_VERSION,
    MASS_FACTORY_WAVE,
    MassFactoryConfig,
    _freeze,
)

__all__ = [
    "BatchDataContext",
    "evaluate_one_strategy",
    "load_batch_data_context",
    "run_batch_eval",
    "screen_strategy_result",
]
