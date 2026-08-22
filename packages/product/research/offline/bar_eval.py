"""Offline W78–W86 bar-eval surface (not CF SoT; no GO).

``evaluate_*_on_bars`` bodies. Local bar mirrors + SQLite only;
not Mass / READY / Phase7 / operational GO.
"""

from __future__ import annotations

import math
from statistics import mean
from typing import Any, Mapping, Sequence

from features.class_signals import (
    CLASS_EVENT_POST,
    CLASS_FLOW_DEMAND,
    CLASS_FUNDAMENTALS_PRICE,
    CLASS_INDEX_VOL_REGIME,
    CLASS_MACRO_CONDITIONED,
    CLASS_MULTI_DAY_HOLD,
    CLASS_MULTI_FACTOR,
    CLASS_OPTIONS_VOL_REGIME,
    CLASS_RATE_FACTOR,
    DEFAULT_CURVE_INVERT_THRESHOLD,
    DEFAULT_CURVE_STEEP_THRESHOLD,
    DEFAULT_EVENT_POST_HOLD_DAYS,
    DEFAULT_FLOW_HOLD_DAYS,
    DEFAULT_FUND_HOLD_DAYS,
    DEFAULT_FUND_MOMENTUM_N,
    DEFAULT_HOLD_DAYS,
    DEFAULT_MIN_ACTIVATION_RATE_MULTIDAY,
    DEFAULT_MIN_EVENTS_PER_CODE_YEAR,
    DEFAULT_MIN_EVENTS_PER_TRADING_DAY,
    DEFAULT_NKY_VOL_COMPRESS_RATIO,
    DEFAULT_NKY_VOL_EXPAND_RATIO,
    DEFAULT_NKY_VOL_HIGH_THRESHOLD,
    DEFAULT_NKY_VOL_LOW_THRESHOLD,
    DEFAULT_OPT225_VOL_COMPRESS_RATIO,
    DEFAULT_OPT225_VOL_EXPAND_RATIO,
    DEFAULT_OPT225_VOL_HIGH_THRESHOLD,
    DEFAULT_OPT225_VOL_LOW_THRESHOLD,
    DEFAULT_REPO_HIGH_THRESHOLD,
    DEFAULT_REPO_LOW_THRESHOLD,
    DEFAULT_TRADING_DAYS_PER_YEAR,
    EVENT_POST_ENTRY_MODE,
    OPT225_SPREAD_CONVENTION,
    REPO_CURVE_LONG_TENOR,
    REPO_CURVE_SHORT_TENOR,
    SIGNAL_ID_CROSS_SECTION,
    SIGNAL_ID_EVENT_POST,
    SIGNAL_ID_FLOW_DEMAND,
    SIGNAL_ID_FUNDAMENTALS_PRICE,
    SIGNAL_ID_MACRO_CONDITIONED,
    SIGNAL_ID_MF_FLOW_PRICE,
    SIGNAL_ID_MF_VALUE_MOM_RATE,
    SIGNAL_ID_MULTI_DAY_HOLD,
    SIGNAL_ID_NKY_VOL_ABS_LEVEL,
    SIGNAL_ID_NKY_VOL_TERM_LEVELS,
    SIGNAL_ID_NKY_VOL_TERM_RATIO,
    SIGNAL_ID_OPT225_ATM_IV_ABS,
    SIGNAL_ID_OPT225_ATM_IV_TERM_LEVELS,
    SIGNAL_ID_OPT225_ATM_IV_TERM_RATIO,
    SIGNAL_ID_OPT225_BASEVOL_ABS,
    SIGNAL_ID_OPT225_BASEVOL_DELTA_ABS,
    SIGNAL_ID_OPT225_BASEVOL_TERM_LEVELS,
    SIGNAL_ID_OPT225_BASEVOL_TERM_RATIO,
    SIGNAL_ID_OPT225_CM_TERM_ABS,
    SIGNAL_ID_OPT225_SKEW_ABS,
    SIGNAL_ID_OPT225_SPREAD_ABS,
    SIGNAL_ID_OPT225_SPREAD_CHANGE,
    SIGNAL_ID_RATE_CURVE_XS,
    SIGNAL_ID_RATE_LEVEL_XS,
    amortized_one_way_cost,
    apply_sticky_hold,
    compute_event_post_signal,
    compute_flow_demand_signal,
    compute_fundamentals_price_signal,
    compute_macro_conditioned_signal,
    compute_mf_flow_price_signal,
    compute_mf_value_mom_rate_signal,
    compute_nky_vol_abs_level_signal,
    compute_nky_vol_term_levels_signal,
    compute_nky_vol_term_ratio_signal,
    compute_opt225_vol_signal,
    compute_rate_curve_xs_signal,
    compute_rate_level_xs_signal,
    cross_section_rank_signs,
    earnings_surprise_proxy,
    event_post_entry_bar_index,
    fundamental_value_score,
    multi_day_forward_return,
    occurrence_rate_event_post,
    occurrence_rate_multiday,
    sign_from_numeric,
)
from research.cost_models import (
    DEFAULT_ONE_WAY_COST,
    REPO_DATASET_ID,
    lookup_repo_rate,
)
from research.eval_loaders import (
    fins_asof,
    load_fins_latest_asof_map,
    momentum_series,
)
from research.freezes import MASS_RESEARCH, PHASE7, READY_DECLARED
from research.stats_metrics import trade_stats_report

MIN_ACTIVATION_RATE_MULTIDAY: float = DEFAULT_MIN_ACTIVATION_RATE_MULTIDAY
MIN_EVENTS_PER_CODE_YEAR: float = DEFAULT_MIN_EVENTS_PER_CODE_YEAR
MIN_EVENTS_PER_TRADING_DAY: float = DEFAULT_MIN_EVENTS_PER_TRADING_DAY


def _freeze() -> dict[str, Any]:
    return {
        "mass_research": MASS_RESEARCH,
        "phase7": PHASE7,
        "ready_declared": READY_DECLARED,
        "operational_go": False,
        "connected_to_ready": False,
        "connected_to_mass": False,
        "significance_claimed": False,
        "edge_claimed": False,
        "s1_s5_unreject": False,
        "simple_daily_sign": False,
    }


def evaluate_multi_day_hold_on_bars(
    bars_by_code: Mapping[str, Sequence[tuple[str, float]]],
    *,
    hold_days: int = DEFAULT_HOLD_DAYS,
    one_way_cost: float = DEFAULT_ONE_WAY_COST,
    rebalance_mode: str = "fixed_horizon",
) -> dict[str, Any]:
    """Evaluate multi_day_hold signal on an in-memory bars panel.

    Entry = sign(momentum_n) with n=hold_days; sticky hold; gross = mean of
    sign * hold-horizon forward return on rebalance days only.
    Cost net uses amortized one-way over hold_days.
    """
    h = int(hold_days)
    if h < 1:
        raise ValueError(f"hold_days must be >= 1, got {hold_days!r}")
    am_cost = amortized_one_way_cost(one_way_cost, h)

    signed_returns: list[float] = []
    holding_records: list[dict[str, Any]] = []
    n_rebalance = 0
    n_active = 0
    per_code_stats: list[dict[str, Any]] = []

    for code, pairs in sorted(bars_by_code.items()):
        pairs_l = list(pairs)
        if len(pairs_l) < h + 2:
            continue
        moms = momentum_series(pairs_l, n=h)
        entry_signs = [sign_from_numeric(m) for _, m in moms]
        held = apply_sticky_hold(
            entry_signs, hold_days=h, rebalance_mode=rebalance_mode
        )
        closes = [c for _, c in pairs_l]
        dates = [d for d, _ in pairs_l]
        code_signed: list[float] = []
        for i, pos in enumerate(held):
            holding_records.append(
                {
                    "date": dates[i],
                    "code": code,
                    "sign": pos,
                }
            )
            if pos is None or pos == 0.0:
                continue
            # Only score on rebalance boundaries for fixed_horizon.
            if rebalance_mode == "fixed_horizon" and i % h != 0:
                continue
            fwd = multi_day_forward_return(closes, hold_days=h, entry_index=i)
            if fwd is None:
                continue
            n_rebalance += 1
            n_active += 1
            sr = float(pos) * float(fwd)
            signed_returns.append(sr)
            code_signed.append(sr)
        if code_signed:
            per_code_stats.append(
                {
                    "code": code,
                    "n": len(code_signed),
                    "gross_mean": mean(code_signed),
                }
            )

    gross = mean(signed_returns) if signed_returns else None
    net = (gross - am_cost) if gross is not None else None
    # dailyized residual illustration (research only)
    net_daily = (gross - one_way_cost) if gross is not None else None
    trade_stats = trade_stats_report(
        signed_returns,
        hold_days=h,
        one_way_cost=float(one_way_cost),
        amortize_cost=True,
        trading_days_per_year=DEFAULT_TRADING_DAYS_PER_YEAR,
    )

    n_code_days = len(holding_records)
    n_codes = len(bars_by_code)
    all_dates = {r["date"] for r in holding_records}
    n_trading_days = len(all_dates)
    occ = occurrence_rate_multiday(
        n_active=n_active,
        n_code_days=n_code_days,
        n_trading_days=n_trading_days,
        n_codes=n_codes,
        hold_days=h,
        min_activation_rate=MIN_ACTIVATION_RATE_MULTIDAY,
    )

    return {
        "signal_id": SIGNAL_ID_MULTI_DAY_HOLD,
        "hypothesis_class": CLASS_MULTI_DAY_HOLD,
        "hold_days": h,
        "rebalance_mode": rebalance_mode,
        "gross_signed_mean_active": gross,
        "net_one_way_mean_active": net,
        "net_daily_flip_cost_illustration": net_daily,
        "amortized_one_way_cost": am_cost,
        "one_way_cost": float(one_way_cost),
        "n_active_positions": n_active,
        "n_rebalance_events": n_rebalance,
        "n_signed_returns": len(signed_returns),
        "n_codes": n_codes,
        "n_code_days": n_code_days,
        "n_trading_days": n_trading_days,
        "occurrence": occ,
        "trade_stats": trade_stats,
        "per_code_sample": per_code_stats[:10],
        "holding_records": holding_records,
        "non_null": n_active,
        "non_null_rate": (
            float(n_active) / float(n_code_days) if n_code_days else None
        ),
        **_freeze(),
        "note": (
            f"Multi-day hold n={h}: sticky fixed_horizon; "
            "gross = mean(sign * R_hold); net = gross - one_way/hold_days. "
            "Occurrence = activation rate (not count alone). "
            "trade_stats = t/Sharpe/winrate on hold nets. "
            "Not READY / not Mass."
        ),
    }


def evaluate_macro_conditioned_on_bars(
    bars_by_code: Mapping[str, Sequence[tuple[str, float]]],
    repo_series: Mapping[str, Any] | None,
    *,
    momentum_n: int = 5,
    hold_days: int = 5,
    mode: str = "rate_change",
    one_way_cost: float = DEFAULT_ONE_WAY_COST,
    high_threshold: float = DEFAULT_REPO_HIGH_THRESHOLD,
    low_threshold: float = DEFAULT_REPO_LOW_THRESHOLD,
) -> dict[str, Any]:
    """Evaluate macro_conditioned signal using bars + repo rate series.

    Uses daily momentum entry, conditions on repo regime (level or change),
    scores next-session return (T→T+1) when conditioned signal is active.
    Cost: full one-way per active day (conservative; daily condition check).
    """
    n = int(momentum_n)
    h = int(hold_days)
    signed_returns: list[float] = []
    n_active = 0
    n_regime_gap = 0
    n_conditioned_null = 0
    regime_counts: dict[str, int] = {}
    holding_records: list[dict[str, Any]] = []

    # Build prev repo map by sorted dates
    rates_by_date = dict((repo_series or {}).get("rates_by_date") or {})
    repo_dates = sorted(rates_by_date.keys())
    prev_map: dict[str, float | None] = {}
    for i, d in enumerate(repo_dates):
        prev_map[d] = rates_by_date[repo_dates[i - 1]] if i > 0 else None

    for code, pairs in sorted(bars_by_code.items()):
        pairs_l = list(pairs)
        if len(pairs_l) < n + 2:
            continue
        moms = momentum_series(pairs_l, n=n)
        closes = [c for _, c in pairs_l]
        for i, (d, mom) in enumerate(moms):
            if i + 1 >= len(closes):
                break
            # Lookup repo for date; gap → honest null (no invent)
            hit = lookup_repo_rate(repo_series, d)
            if hit.get("is_gap"):
                n_regime_gap += 1
                holding_records.append(
                    {"date": d, "code": code, "sign": None, "regime_gap": True}
                )
                continue
            rate = hit.get("rate_pct")
            # prev: prior calendar repo date or prior bar date lookup
            prev_rate = prev_map.get(str(d)[:10])
            if prev_rate is None and repo_dates:
                # find last repo date < d
                earlier = [x for x in repo_dates if x < str(d)[:10]]
                if earlier:
                    prev_rate = rates_by_date.get(earlier[-1])

            rec = compute_macro_conditioned_signal(
                momentum=mom,
                repo_rate=rate,
                prev_repo_rate=prev_rate,
                is_trading_day=1.0,
                mode=mode,
                high_threshold=high_threshold,
                low_threshold=low_threshold,
                code=code,
                date=d,
            )
            val = rec.get("value")
            regime = rec.get("regime")
            if regime is not None:
                regime_counts[str(regime)] = regime_counts.get(str(regime), 0) + 1
            holding_records.append(
                {
                    "date": d,
                    "code": code,
                    "sign": val,
                    "regime": regime,
                    "repo_rate": rate,
                }
            )
            if val is None or val == 0.0:
                n_conditioned_null += 1
                continue
            # next-day return (conservative daily re-check of regime)
            c0 = closes[i]
            c1 = closes[i + 1]
            if c0 is None or c1 is None or c0 == 0:
                continue
            r1 = (float(c1) / float(c0)) - 1.0
            n_active += 1
            signed_returns.append(float(val) * r1)

    gross = mean(signed_returns) if signed_returns else None
    net = (gross - float(one_way_cost)) if gross is not None else None
    n_code_days = len(holding_records)
    n_trading_days = len({r["date"] for r in holding_records})
    occ = occurrence_rate_multiday(
        n_active=n_active,
        n_code_days=n_code_days,
        n_trading_days=n_trading_days,
        n_codes=len(bars_by_code),
        hold_days=1,  # daily re-check path
        min_activation_rate=MIN_ACTIVATION_RATE_MULTIDAY,
    )

    return {
        "signal_id": SIGNAL_ID_MACRO_CONDITIONED,
        "hypothesis_class": CLASS_MACRO_CONDITIONED,
        "mode": mode,
        "momentum_n": n,
        "hold_days_documented": h,
        "gross_signed_mean_active": gross,
        "net_one_way_mean_active": net,
        "one_way_cost": float(one_way_cost),
        "n_active_positions": n_active,
        "n_signed_returns": len(signed_returns),
        "n_regime_gap": n_regime_gap,
        "n_conditioned_null": n_conditioned_null,
        "regime_counts": regime_counts,
        "n_codes": len(bars_by_code),
        "n_code_days": n_code_days,
        "n_trading_days": n_trading_days,
        "occurrence": occ,
        "holding_records": holding_records,
        "non_null": n_active,
        "non_null_rate": (
            float(n_active) / float(n_code_days) if n_code_days else None
        ),
        "repo_dataset": REPO_DATASET_ID,
        **_freeze(),
        "note": (
            f"Macro-conditioned momentum mode={mode} on jsda_tokyo_repo_rates. "
            "Repo gaps → no trade (no invent). Not READY / not Mass."
        ),
    }


def evaluate_rate_level_xs_on_bars(
    bars_by_code: Mapping[str, Sequence[tuple[str, float]]],
    repo_series: Mapping[str, Any] | None,
    *,
    momentum_n: int = 5,
    hold_days: int = 10,
    long_frac: float = 0.3,
    short_frac: float = 0.3,
    one_way_cost: float = DEFAULT_ONE_WAY_COST,
    high_threshold: float = DEFAULT_REPO_HIGH_THRESHOLD,
    low_threshold: float = DEFAULT_REPO_LOW_THRESHOLD,
) -> dict[str, Any]:
    """Absolute rate-level factor × CS book (risk-on/off), multi-day sticky.

    Distinct from macro_conditioned rate_level (unidirectional mom gate).
    """
    from research.cost_models import lookup_repo_rate

    n = int(momentum_n)
    h = int(hold_days)
    am_cost = amortized_one_way_cost(one_way_cost, h)
    by_date: dict[str, dict[str, float | None]] = {}
    dates_by_code: dict[str, list[str]] = {}
    closes_list: dict[str, list[float]] = {}
    for code, pairs in bars_by_code.items():
        pairs_l = list(pairs)
        moms = momentum_series(pairs_l, n=n)
        for d, m in moms:
            by_date.setdefault(d, {})[code] = m
        dates_by_code[code] = [d for d, _ in pairs_l]
        closes_list[code] = [c for _, c in pairs_l]

    dates = sorted(by_date.keys())
    # Daily CS rank signs, then rate-level risk-adjust
    daily_adj: dict[str, dict[str, float | None]] = {c: {} for c in bars_by_code}
    n_regime_gap = 0
    regime_counts: dict[str, int] = {}
    for d in dates:
        ranks = cross_section_rank_signs(
            by_date[d], long_frac=long_frac, short_frac=short_frac
        )
        hit = lookup_repo_rate(repo_series, d) if repo_series else {"is_gap": True}
        if hit.get("is_gap") or hit.get("rate_pct") is None:
            n_regime_gap += 1
            for code in ranks:
                daily_adj.setdefault(code, {})[d] = None
            continue
        rate = hit.get("rate_pct")
        for code, cs_sign in ranks.items():
            rec = compute_rate_level_xs_signal(
                cs_sign=cs_sign,
                repo_rate=rate,
                high_threshold=high_threshold,
                low_threshold=low_threshold,
                code=code,
                date=d,
            )
            reg = rec.get("regime")
            if reg is not None:
                regime_counts[str(reg)] = regime_counts.get(str(reg), 0) + 1
            daily_adj.setdefault(code, {})[d] = rec.get("value")

    signed_returns: list[float] = []
    n_active = 0
    holding_records: list[dict[str, Any]] = []
    for code, dlist in dates_by_code.items():
        entries = [daily_adj.get(code, {}).get(d) for d in dlist]
        held = apply_sticky_hold(entries, hold_days=h, rebalance_mode="fixed_horizon")
        closes = closes_list[code]
        for i, pos in enumerate(held):
            holding_records.append({"date": dlist[i], "code": code, "sign": pos})
            if pos is None or pos == 0.0:
                continue
            if i % h != 0:
                continue
            fwd = multi_day_forward_return(closes, hold_days=h, entry_index=i)
            if fwd is None:
                continue
            n_active += 1
            signed_returns.append(float(pos) * float(fwd))

    gross = mean(signed_returns) if signed_returns else None
    net = (gross - am_cost) if gross is not None else None
    n_code_days = len(holding_records)
    n_trading_days = len({r["date"] for r in holding_records})
    occ = occurrence_rate_multiday(
        n_active=n_active,
        n_code_days=n_code_days,
        n_trading_days=n_trading_days,
        n_codes=len(bars_by_code),
        hold_days=h,
        min_activation_rate=MIN_ACTIVATION_RATE_MULTIDAY,
    )
    return {
        "signal_id": SIGNAL_ID_RATE_LEVEL_XS,
        "hypothesis_class": CLASS_RATE_FACTOR,
        "mode": "rate_level_xs_risk_adj",
        "momentum_n": n,
        "hold_days": h,
        "gross_signed_mean_active": gross,
        "net_one_way_mean_active": net,
        "amortized_one_way_cost": am_cost,
        "one_way_cost": float(one_way_cost),
        "n_active_positions": n_active,
        "n_signed_returns": len(signed_returns),
        "n_regime_gap": n_regime_gap,
        "regime_counts": regime_counts,
        "n_codes": len(bars_by_code),
        "n_code_days": n_code_days,
        "n_trading_days": n_trading_days,
        "occurrence": occ,
        **_freeze(),
        "note": (
            "Absolute rate-level factor × CS risk-on/off book on "
            "jsda_tokyo_repo_rates. Not macro mom-gate. Not READY / not Mass."
        ),
    }


def evaluate_rate_curve_xs_on_bars(
    bars_by_code: Mapping[str, Sequence[tuple[str, float]]],
    curve_series: Mapping[str, Any] | None,
    *,
    momentum_n: int = 5,
    hold_days: int = 10,
    long_frac: float = 0.3,
    short_frac: float = 0.3,
    one_way_cost: float = DEFAULT_ONE_WAY_COST,
    steep_threshold: float = DEFAULT_CURVE_STEEP_THRESHOLD,
    invert_threshold: float = DEFAULT_CURVE_INVERT_THRESHOLD,
) -> dict[str, Any]:
    """Repo curve-shape factor × CS book (steep keep / inverted reverse)."""
    n = int(momentum_n)
    h = int(hold_days)
    am_cost = amortized_one_way_cost(one_way_cost, h)
    short_by = dict((curve_series or {}).get("short_rates_by_date") or {})
    long_by = dict((curve_series or {}).get("long_rates_by_date") or {})

    by_date: dict[str, dict[str, float | None]] = {}
    dates_by_code: dict[str, list[str]] = {}
    closes_list: dict[str, list[float]] = {}
    for code, pairs in bars_by_code.items():
        pairs_l = list(pairs)
        moms = momentum_series(pairs_l, n=n)
        for d, m in moms:
            by_date.setdefault(d, {})[code] = m
        dates_by_code[code] = [d for d, _ in pairs_l]
        closes_list[code] = [c for _, c in pairs_l]

    dates = sorted(by_date.keys())
    daily_adj: dict[str, dict[str, float | None]] = {c: {} for c in bars_by_code}
    n_regime_gap = 0
    regime_counts: dict[str, int] = {}
    for d in dates:
        ranks = cross_section_rank_signs(
            by_date[d], long_frac=long_frac, short_frac=short_frac
        )
        # exact date match; no invent/ffill
        s_rate = short_by.get(str(d)[:10])
        l_rate = long_by.get(str(d)[:10])
        if s_rate is None or l_rate is None:
            n_regime_gap += 1
            for code in ranks:
                daily_adj.setdefault(code, {})[d] = None
            continue
        for code, cs_sign in ranks.items():
            rec = compute_rate_curve_xs_signal(
                cs_sign=cs_sign,
                short_rate=s_rate,
                long_rate=l_rate,
                steep_threshold=steep_threshold,
                invert_threshold=invert_threshold,
                code=code,
                date=d,
            )
            reg = rec.get("regime")
            if reg is not None:
                regime_counts[str(reg)] = regime_counts.get(str(reg), 0) + 1
            daily_adj.setdefault(code, {})[d] = rec.get("value")

    signed_returns: list[float] = []
    n_active = 0
    holding_records: list[dict[str, Any]] = []
    for code, dlist in dates_by_code.items():
        entries = [daily_adj.get(code, {}).get(d) for d in dlist]
        held = apply_sticky_hold(entries, hold_days=h, rebalance_mode="fixed_horizon")
        closes = closes_list[code]
        for i, pos in enumerate(held):
            holding_records.append({"date": dlist[i], "code": code, "sign": pos})
            if pos is None or pos == 0.0:
                continue
            if i % h != 0:
                continue
            fwd = multi_day_forward_return(closes, hold_days=h, entry_index=i)
            if fwd is None:
                continue
            n_active += 1
            signed_returns.append(float(pos) * float(fwd))

    gross = mean(signed_returns) if signed_returns else None
    net = (gross - am_cost) if gross is not None else None
    n_code_days = len(holding_records)
    n_trading_days = len({r["date"] for r in holding_records})
    occ = occurrence_rate_multiday(
        n_active=n_active,
        n_code_days=n_code_days,
        n_trading_days=n_trading_days,
        n_codes=len(bars_by_code),
        hold_days=h,
        min_activation_rate=MIN_ACTIVATION_RATE_MULTIDAY,
    )
    return {
        "signal_id": SIGNAL_ID_RATE_CURVE_XS,
        "hypothesis_class": CLASS_RATE_FACTOR,
        "mode": "rate_curve_shape_xs",
        "momentum_n": n,
        "hold_days": h,
        "curve_short_tenor": (curve_series or {}).get("short_tenor")
        or REPO_CURVE_SHORT_TENOR,
        "curve_long_tenor": (curve_series or {}).get("long_tenor")
        or REPO_CURVE_LONG_TENOR,
        "curve_definition": (curve_series or {}).get("definition"),
        "gross_signed_mean_active": gross,
        "net_one_way_mean_active": net,
        "amortized_one_way_cost": am_cost,
        "one_way_cost": float(one_way_cost),
        "n_active_positions": n_active,
        "n_signed_returns": len(signed_returns),
        "n_regime_gap": n_regime_gap,
        "regime_counts": regime_counts,
        "n_codes": len(bars_by_code),
        "n_code_days": n_code_days,
        "n_trading_days": n_trading_days,
        "occurrence": occ,
        **_freeze(),
        "note": (
            "Repo curve-shape factor (3M−overnight) × CS book. "
            "JSDA tenors only; no invent. Not READY / not Mass."
        ),
    }


def _evaluate_nky_vol_xs_core(
    bars_by_code: Mapping[str, Sequence[tuple[str, float]]],
    nky_vol_series: Mapping[str, Any] | None,
    *,
    mode: str,
    momentum_n: int,
    hold_days: int,
    long_frac: float,
    short_frac: float,
    one_way_cost: float,
    high_threshold: float,
    low_threshold: float,
    expand_ratio: float,
    compress_ratio: float,
) -> dict[str, Any]:
    """Shared CS × index-vol regime evaluator for abs / term_levels / term_ratio."""
    n = int(momentum_n)
    h = int(hold_days)
    am_cost = amortized_one_way_cost(one_way_cost, h)
    m = str(mode or "nky_vol_abs_level")
    short_by = dict((nky_vol_series or {}).get("rv_short_by_date") or {})
    long_by = dict((nky_vol_series or {}).get("rv_long_by_date") or {})
    abs_by = dict(
        (nky_vol_series or {}).get("rv_abs_by_date")
        or (nky_vol_series or {}).get("rv_short_by_date")
        or {}
    )

    by_date: dict[str, dict[str, float | None]] = {}
    dates_by_code: dict[str, list[str]] = {}
    closes_list: dict[str, list[float]] = {}
    for code, pairs in bars_by_code.items():
        pairs_l = list(pairs)
        moms = momentum_series(pairs_l, n=n)
        for d, mom in moms:
            by_date.setdefault(d, {})[code] = mom
        dates_by_code[code] = [d for d, _ in pairs_l]
        closes_list[code] = [c for _, c in pairs_l]

    dates = sorted(by_date.keys())
    daily_adj: dict[str, dict[str, float | None]] = {c: {} for c in bars_by_code}
    n_regime_gap = 0
    regime_counts: dict[str, int] = {}
    for d in dates:
        ranks = cross_section_rank_signs(
            by_date[d], long_frac=long_frac, short_frac=short_frac
        )
        dk = str(d)[:10]
        for code, cs_sign in ranks.items():
            if m == "nky_vol_term_ratio":
                rec = compute_nky_vol_term_ratio_signal(
                    cs_sign=cs_sign,
                    short_vol=short_by.get(dk),
                    long_vol=long_by.get(dk),
                    expand_ratio=expand_ratio,
                    compress_ratio=compress_ratio,
                    code=code,
                    date=d,
                )
            elif m == "nky_vol_term_levels":
                rec = compute_nky_vol_term_levels_signal(
                    cs_sign=cs_sign,
                    short_vol=short_by.get(dk),
                    long_vol=long_by.get(dk),
                    high_threshold=high_threshold,
                    low_threshold=low_threshold,
                    code=code,
                    date=d,
                )
            else:
                rec = compute_nky_vol_abs_level_signal(
                    cs_sign=cs_sign,
                    vol_level=abs_by.get(dk),
                    high_threshold=high_threshold,
                    low_threshold=low_threshold,
                    code=code,
                    date=d,
                )
            if rec.get("regime") is None and rec.get("value") is None:
                n_regime_gap += 1
            reg = rec.get("regime")
            if reg is not None:
                regime_counts[str(reg)] = regime_counts.get(str(reg), 0) + 1
            daily_adj.setdefault(code, {})[d] = rec.get("value")

    signed_returns: list[float] = []
    n_active = 0
    holding_records: list[dict[str, Any]] = []
    for code, dlist in dates_by_code.items():
        entries = [daily_adj.get(code, {}).get(d) for d in dlist]
        held = apply_sticky_hold(entries, hold_days=h, rebalance_mode="fixed_horizon")
        closes = closes_list[code]
        for i, pos in enumerate(held):
            holding_records.append({"date": dlist[i], "code": code, "sign": pos})
            if pos is None or pos == 0.0:
                continue
            if i % h != 0:
                continue
            fwd = multi_day_forward_return(closes, hold_days=h, entry_index=i)
            if fwd is None:
                continue
            n_active += 1
            signed_returns.append(float(pos) * float(fwd))

    gross = mean(signed_returns) if signed_returns else None
    net = (gross - am_cost) if gross is not None else None
    n_code_days = len(holding_records)
    n_trading_days = len({r["date"] for r in holding_records})
    occ = occurrence_rate_multiday(
        n_active=n_active,
        n_code_days=n_code_days,
        n_trading_days=n_trading_days,
        n_codes=len(bars_by_code),
        hold_days=h,
        min_activation_rate=MIN_ACTIVATION_RATE_MULTIDAY,
    )
    sid = {
        "nky_vol_abs_level": SIGNAL_ID_NKY_VOL_ABS_LEVEL,
        "nky_vol_term_levels": SIGNAL_ID_NKY_VOL_TERM_LEVELS,
        "nky_vol_term_ratio": SIGNAL_ID_NKY_VOL_TERM_RATIO,
    }.get(m, SIGNAL_ID_NKY_VOL_ABS_LEVEL)
    return {
        "signal_id": sid,
        "hypothesis_class": CLASS_INDEX_VOL_REGIME,
        "mode": m,
        "momentum_n": n,
        "hold_days": h,
        "vol_source": (nky_vol_series or {}).get("source"),
        "vol_dataset": (nky_vol_series or {}).get("dataset"),
        "short_n": (nky_vol_series or {}).get("short_n"),
        "long_n": (nky_vol_series or {}).get("long_n"),
        "gross_signed_mean_active": gross,
        "net_one_way_mean_active": net,
        "amortized_one_way_cost": am_cost,
        "one_way_cost": float(one_way_cost),
        "n_active_positions": n_active,
        "n_signed_returns": len(signed_returns),
        "n_regime_gap": n_regime_gap,
        "regime_counts": regime_counts,
        "n_codes": len(bars_by_code),
        "n_code_days": n_code_days,
        "n_trading_days": n_trading_days,
        "occurrence": occ,
        **_freeze(),
        "note": (
            f"Index-level Nikkei/TOPIX vol regime mode={m} × CS book. "
            "Not per-name vol_risk_adjusted. Not READY / not Mass."
        ),
    }


def evaluate_nky_vol_abs_level_on_bars(
    bars_by_code: Mapping[str, Sequence[tuple[str, float]]],
    nky_vol_series: Mapping[str, Any] | None,
    *,
    momentum_n: int = 5,
    hold_days: int = 10,
    long_frac: float = 0.3,
    short_frac: float = 0.3,
    one_way_cost: float = DEFAULT_ONE_WAY_COST,
    high_threshold: float = DEFAULT_NKY_VOL_HIGH_THRESHOLD,
    low_threshold: float = DEFAULT_NKY_VOL_LOW_THRESHOLD,
) -> dict[str, Any]:
    """Absolute index RV level × CS risk-on/off book."""
    return _evaluate_nky_vol_xs_core(
        bars_by_code,
        nky_vol_series,
        mode="nky_vol_abs_level",
        momentum_n=momentum_n,
        hold_days=hold_days,
        long_frac=long_frac,
        short_frac=short_frac,
        one_way_cost=one_way_cost,
        high_threshold=high_threshold,
        low_threshold=low_threshold,
        expand_ratio=DEFAULT_NKY_VOL_EXPAND_RATIO,
        compress_ratio=DEFAULT_NKY_VOL_COMPRESS_RATIO,
    )


def evaluate_nky_vol_term_levels_on_bars(
    bars_by_code: Mapping[str, Sequence[tuple[str, float]]],
    nky_vol_series: Mapping[str, Any] | None,
    *,
    momentum_n: int = 5,
    hold_days: int = 10,
    long_frac: float = 0.3,
    short_frac: float = 0.3,
    one_way_cost: float = DEFAULT_ONE_WAY_COST,
    high_threshold: float = DEFAULT_NKY_VOL_HIGH_THRESHOLD,
    low_threshold: float = DEFAULT_NKY_VOL_LOW_THRESHOLD,
) -> dict[str, Any]:
    """Short+long absolute RV levels (agreement) × CS book."""
    return _evaluate_nky_vol_xs_core(
        bars_by_code,
        nky_vol_series,
        mode="nky_vol_term_levels",
        momentum_n=momentum_n,
        hold_days=hold_days,
        long_frac=long_frac,
        short_frac=short_frac,
        one_way_cost=one_way_cost,
        high_threshold=high_threshold,
        low_threshold=low_threshold,
        expand_ratio=DEFAULT_NKY_VOL_EXPAND_RATIO,
        compress_ratio=DEFAULT_NKY_VOL_COMPRESS_RATIO,
    )


def evaluate_nky_vol_term_ratio_on_bars(
    bars_by_code: Mapping[str, Sequence[tuple[str, float]]],
    nky_vol_series: Mapping[str, Any] | None,
    *,
    momentum_n: int = 5,
    hold_days: int = 10,
    long_frac: float = 0.3,
    short_frac: float = 0.3,
    one_way_cost: float = DEFAULT_ONE_WAY_COST,
    expand_ratio: float = DEFAULT_NKY_VOL_EXPAND_RATIO,
    compress_ratio: float = DEFAULT_NKY_VOL_COMPRESS_RATIO,
) -> dict[str, Any]:
    """Short/long RV ratio × CS risk-on/off book."""
    return _evaluate_nky_vol_xs_core(
        bars_by_code,
        nky_vol_series,
        mode="nky_vol_term_ratio",
        momentum_n=momentum_n,
        hold_days=hold_days,
        long_frac=long_frac,
        short_frac=short_frac,
        one_way_cost=one_way_cost,
        high_threshold=DEFAULT_NKY_VOL_HIGH_THRESHOLD,
        low_threshold=DEFAULT_NKY_VOL_LOW_THRESHOLD,
        expand_ratio=expand_ratio,
        compress_ratio=compress_ratio,
    )


_OPT225_SIGNAL_IDS: dict[str, str] = {
    "opt225_basevol_abs_level": SIGNAL_ID_OPT225_BASEVOL_ABS,
    "opt225_basevol_term_levels": SIGNAL_ID_OPT225_BASEVOL_TERM_LEVELS,
    "opt225_basevol_term_ratio": SIGNAL_ID_OPT225_BASEVOL_TERM_RATIO,
    "opt225_atm_iv_abs_level": SIGNAL_ID_OPT225_ATM_IV_ABS,
    "opt225_atm_iv_term_levels": SIGNAL_ID_OPT225_ATM_IV_TERM_LEVELS,
    "opt225_atm_iv_term_ratio": SIGNAL_ID_OPT225_ATM_IV_TERM_RATIO,
    "opt225_iv_base_spread_abs": SIGNAL_ID_OPT225_SPREAD_ABS,
    "opt225_iv_base_spread_change": SIGNAL_ID_OPT225_SPREAD_CHANGE,
    "opt225_skew_abs_level": SIGNAL_ID_OPT225_SKEW_ABS,
    "opt225_cm_term_abs_level": SIGNAL_ID_OPT225_CM_TERM_ABS,
    "opt225_basevol_delta_abs": SIGNAL_ID_OPT225_BASEVOL_DELTA_ABS,
}


def evaluate_opt225_vol_on_bars(
    bars_by_code: Mapping[str, Sequence[tuple[str, float]]],
    opt225_series: Mapping[str, Any] | None,
    *,
    mode: str = "opt225_basevol_abs_level",
    series_kind: str = "basevol",
    momentum_n: int = 5,
    hold_days: int = 10,
    long_frac: float = 0.3,
    short_frac: float = 0.3,
    one_way_cost: float = DEFAULT_ONE_WAY_COST,
    high_threshold: float = DEFAULT_OPT225_VOL_HIGH_THRESHOLD,
    low_threshold: float = DEFAULT_OPT225_VOL_LOW_THRESHOLD,
    expand_ratio: float = DEFAULT_OPT225_VOL_EXPAND_RATIO,
    compress_ratio: float = DEFAULT_OPT225_VOL_COMPRESS_RATIO,
) -> dict[str, Any]:
    """options_225 BaseVol / ATM IV / spread regime × CS book."""
    n = int(momentum_n)
    h = int(hold_days)
    am_cost = amortized_one_way_cost(one_way_cost, h)
    m = str(mode or "opt225_basevol_abs_level")
    sk = str(series_kind or "basevol")
    series = opt225_series or {}
    # Accept either a single regime map or a bundle keyed by series_kind.
    if "rv_abs_by_date" not in series and sk in series:
        series = dict(series.get(sk) or {})
    short_by = dict(series.get("rv_short_by_date") or {})
    long_by = dict(series.get("rv_long_by_date") or {})
    abs_by = dict(
        series.get("rv_abs_by_date")
        or series.get("level_by_date")
        or series.get("rv_short_by_date")
        or {}
    )
    transform = "abs_level"
    if "term_ratio" in m:
        transform = "term_ratio"
    elif "term_levels" in m:
        transform = "term_levels"

    sid = _OPT225_SIGNAL_IDS.get(m, SIGNAL_ID_OPT225_BASEVOL_ABS)
    feature_id = {
        "basevol": "opt225_basevol_level",
        "atm_iv": "opt225_atm_iv_level",
        "spread": "opt225_iv_base_spread",
        "spread_change": "opt225_iv_base_spread",
        "skew": "opt225_skew_95put",
        "cm_term": "opt225_cm_term_near_next",
        "basevol_delta": "opt225_basevol_delta",
    }.get(sk, "opt225_basevol_level")

    by_date: dict[str, dict[str, float | None]] = {}
    dates_by_code: dict[str, list[str]] = {}
    closes_list: dict[str, list[float]] = {}
    for code, pairs in bars_by_code.items():
        if str(code).startswith("__"):
            continue
        pairs_l = list(pairs)
        moms = momentum_series(pairs_l, n=n)
        for d, mom in moms:
            by_date.setdefault(d, {})[code] = mom
        dates_by_code[code] = [d for d, _ in pairs_l]
        closes_list[code] = [c for _, c in pairs_l]

    dates = sorted(by_date.keys())
    daily_adj: dict[str, dict[str, float | None]] = {c: {} for c in dates_by_code}
    n_regime_gap = 0
    regime_counts: dict[str, int] = {}
    for d in dates:
        ranks = cross_section_rank_signs(
            by_date[d], long_frac=long_frac, short_frac=short_frac
        )
        dk = str(d)[:10]
        for code, cs_sign in ranks.items():
            rec = compute_opt225_vol_signal(
                mode=transform,
                cs_sign=cs_sign,
                vol_level=abs_by.get(dk),
                short_vol=short_by.get(dk),
                long_vol=long_by.get(dk),
                high_threshold=high_threshold,
                low_threshold=low_threshold,
                expand_ratio=expand_ratio,
                compress_ratio=compress_ratio,
                signal_id=sid,
                feature_id=feature_id,
                series_kind=sk,
                code=code,
                date=d,
            )
            if rec.get("regime") is None and rec.get("value") is None:
                n_regime_gap += 1
            reg = rec.get("regime")
            if reg is not None:
                regime_counts[str(reg)] = regime_counts.get(str(reg), 0) + 1
            daily_adj.setdefault(code, {})[d] = rec.get("value")

    signed_returns: list[float] = []
    n_active = 0
    holding_records: list[dict[str, Any]] = []
    for code, dlist in dates_by_code.items():
        entries = [daily_adj.get(code, {}).get(d) for d in dlist]
        held = apply_sticky_hold(entries, hold_days=h, rebalance_mode="fixed_horizon")
        closes = closes_list[code]
        for i, pos in enumerate(held):
            holding_records.append({"date": dlist[i], "code": code, "sign": pos})
            if pos is None or pos == 0.0:
                continue
            if i % h != 0:
                continue
            fwd = multi_day_forward_return(closes, hold_days=h, entry_index=i)
            if fwd is None:
                continue
            n_active += 1
            signed_returns.append(float(pos) * float(fwd))

    gross = mean(signed_returns) if signed_returns else None
    net = (gross - am_cost) if gross is not None else None
    n_code_days = len(holding_records)
    n_trading_days = len({r["date"] for r in holding_records})
    occ = occurrence_rate_multiday(
        n_active=n_active,
        n_code_days=n_code_days,
        n_trading_days=n_trading_days,
        n_codes=len(dates_by_code),
        hold_days=h,
        min_activation_rate=MIN_ACTIVATION_RATE_MULTIDAY,
    )
    return {
        "signal_id": sid,
        "hypothesis_class": CLASS_OPTIONS_VOL_REGIME,
        "mode": m,
        "series_kind": sk,
        "transform": transform,
        "momentum_n": n,
        "hold_days": h,
        "vol_source": series.get("source"),
        "vol_dataset": series.get("dataset") or "derivatives_bars_daily_options_225",
        "units": series.get("units") or "percent_vol_points",
        "spread_convention": OPT225_SPREAD_CONVENTION,
        "short_n": series.get("short_n"),
        "long_n": series.get("long_n"),
        "gross_signed_mean_active": gross,
        "net_one_way_mean_active": net,
        "amortized_one_way_cost": am_cost,
        "one_way_cost": float(one_way_cost),
        "n_active_positions": n_active,
        "n_signed_returns": len(signed_returns),
        "n_regime_gap": n_regime_gap,
        "regime_counts": regime_counts,
        "n_codes": len(dates_by_code),
        "n_code_days": n_code_days,
        "n_trading_days": n_trading_days,
        "occurrence": occ,
        **_freeze(),
        "note": (
            f"options_225 {sk} regime mode={m} × CS book. Canonical Nikkei vol SoT. "
            "nky_vol_* remains proxy/compare only. Not READY / not Mass."
        ),
    }


def evaluate_mf_value_mom_rate_on_bars(
    bars_by_code: Mapping[str, Sequence[tuple[str, float]]],
    events_by_code: Mapping[str, Sequence[Mapping[str, Any]]],
    repo_series: Mapping[str, Any] | None,
    *,
    hold_days: int = DEFAULT_FUND_HOLD_DAYS,
    momentum_n: int = DEFAULT_FUND_MOMENTUM_N,
    one_way_cost: float = DEFAULT_ONE_WAY_COST,
    high_threshold: float = DEFAULT_REPO_HIGH_THRESHOLD,
    low_threshold: float = DEFAULT_REPO_LOW_THRESHOLD,
) -> dict[str, Any]:
    """Multi-factor value × mom × rate-level (PIT + cost)."""
    from research.cost_models import lookup_repo_rate

    h = int(hold_days)
    n = int(momentum_n)
    am_cost = amortized_one_way_cost(one_way_cost, h)
    asof_map = load_fins_latest_asof_map(events_by_code)

    value_by_code_date: dict[str, dict[str, float | None]] = {}
    value_scores_all: list[float] = []
    for code, pairs in bars_by_code.items():
        series = asof_map.get(code) or []
        value_by_code_date[code] = {}
        for d, close in pairs:
            fin = fins_asof(series, d)
            if fin is None:
                value_by_code_date[code][d] = None
                continue
            score, _ = fundamental_value_score(
                close=close, eps=fin.get("eps"), bps=fin.get("bps")
            )
            value_by_code_date[code][d] = score
            if score is not None:
                value_scores_all.append(score)
    global_median = None
    if value_scores_all:
        ss = sorted(value_scores_all)
        global_median = ss[len(ss) // 2]

    signed_returns: list[float] = []
    n_active = 0
    n_missing = 0
    holding_records: list[dict[str, Any]] = []
    for code, pairs in sorted(bars_by_code.items()):
        pairs_l = list(pairs)
        if len(pairs_l) < max(h, n) + 2:
            continue
        moms = momentum_series(pairs_l, n=n)
        mom_by_date = {d: m for d, m in moms}
        closes = [c for _, c in pairs_l]
        dates = [d for d, _ in pairs_l]
        entries: list[float | None] = []
        for d, _close in pairs_l:
            vscore = value_by_code_date.get(code, {}).get(d)
            hit = (
                lookup_repo_rate(repo_series, d)
                if repo_series
                else {"is_gap": True}
            )
            rate = None if hit.get("is_gap") else hit.get("rate_pct")
            if vscore is None:
                n_missing += 1
                entries.append(None)
                continue
            rec = compute_mf_value_mom_rate_signal(
                value_score=vscore,
                momentum=mom_by_date.get(d),
                repo_rate=rate,
                value_benchmark=global_median,
                high_threshold=high_threshold,
                low_threshold=low_threshold,
                hold_days=h,
                code=code,
                date=d,
            )
            entries.append(rec.get("value"))
        held = apply_sticky_hold(entries, hold_days=h, rebalance_mode="fixed_horizon")
        for i, pos in enumerate(held):
            holding_records.append({"date": dates[i], "code": code, "sign": pos})
            if pos is None or pos == 0.0:
                continue
            if i % h != 0:
                continue
            fwd = multi_day_forward_return(closes, hold_days=h, entry_index=i)
            if fwd is None:
                continue
            n_active += 1
            signed_returns.append(float(pos) * float(fwd))

    gross = mean(signed_returns) if signed_returns else None
    net = (gross - am_cost) if gross is not None else None
    n_code_days = len(holding_records)
    n_trading_days = len({r["date"] for r in holding_records})
    occ = occurrence_rate_multiday(
        n_active=n_active,
        n_code_days=n_code_days,
        n_trading_days=n_trading_days,
        n_codes=len(bars_by_code),
        hold_days=h,
        min_activation_rate=MIN_ACTIVATION_RATE_MULTIDAY,
    )
    return {
        "signal_id": SIGNAL_ID_MF_VALUE_MOM_RATE,
        "hypothesis_class": CLASS_MULTI_FACTOR,
        "mode": "value_mom_rate",
        "hold_days": h,
        "momentum_n": n,
        "gross_signed_mean_active": gross,
        "net_one_way_mean_active": net,
        "amortized_one_way_cost": am_cost,
        "one_way_cost": float(one_way_cost),
        "n_active_positions": n_active,
        "n_signed_returns": len(signed_returns),
        "n_missing_fins_or_rate": n_missing,
        "n_codes": len(bars_by_code),
        "n_code_days": n_code_days,
        "n_trading_days": n_trading_days,
        "occurrence": occ,
        **_freeze(),
        "note": (
            "Multi-factor value×mom×rate. Distinct from fund_value_mom_agree. "
            "PIT fins + date-matched repo. Not READY / not Mass."
        ),
    }


def evaluate_mf_flow_price_on_bars(
    bars_by_code: Mapping[str, Sequence[tuple[str, float]]],
    margin_by_code: Mapping[str, Sequence[tuple[str, float]]],
    *,
    hold_days: int = DEFAULT_FLOW_HOLD_DAYS,
    momentum_n: int = 10,
    one_way_cost: float = DEFAULT_ONE_WAY_COST,
) -> dict[str, Any]:
    """Multi-factor flow × price-mom confirm (parallel to flow hard/soft)."""
    h = int(hold_days)
    n = int(momentum_n)
    am_cost = amortized_one_way_cost(one_way_cost, h)
    signed_returns: list[float] = []
    n_active = 0
    n_margin_obs = 0
    holding_records: list[dict[str, Any]] = []

    for code, pairs in sorted(bars_by_code.items()):
        pairs_l = list(pairs)
        if len(pairs_l) < max(h, n) + 2:
            continue
        margin_pairs = list(margin_by_code.get(code) or [])
        if len(margin_pairs) < 2:
            continue
        margin_chg_by_date: dict[str, float | None] = {}
        for i, (d, m) in enumerate(margin_pairs):
            if i == 0:
                margin_chg_by_date[d] = None
                continue
            prev = margin_pairs[i - 1][1]
            if prev == 0:
                margin_chg_by_date[d] = None
            else:
                margin_chg_by_date[d] = (float(m) - float(prev)) / float(prev)
            n_margin_obs += 1

        moms = momentum_series(pairs_l, n=n)
        mom_by_date = {d: m for d, m in moms}
        dates = [d for d, _ in pairs_l]
        closes = [c for _, c in pairs_l]
        entry_signs: list[float | None] = []
        for d in dates:
            if d in margin_chg_by_date and margin_chg_by_date[d] is not None:
                rec = compute_mf_flow_price_signal(
                    margin_change=margin_chg_by_date[d],
                    momentum=mom_by_date.get(d),
                    is_trading_day=1.0,
                    hold_days=h,
                    code=code,
                    date=d,
                )
                entry_signs.append(rec.get("value"))
            else:
                entry_signs.append(None)

        held = apply_sticky_hold(
            entry_signs, hold_days=h, rebalance_mode="min_hold"
        )
        for i, pos in enumerate(held):
            holding_records.append({"date": dates[i], "code": code, "sign": pos})
            if pos is None or pos == 0.0:
                continue
            if entry_signs[i] is None or entry_signs[i] == 0.0:
                continue
            fwd = multi_day_forward_return(closes, hold_days=h, entry_index=i)
            if fwd is None:
                continue
            n_active += 1
            signed_returns.append(float(pos) * float(fwd))

    gross = mean(signed_returns) if signed_returns else None
    net = (gross - am_cost) if gross is not None else None
    n_code_days = len(holding_records)
    n_trading_days = len({r["date"] for r in holding_records})
    occ = occurrence_rate_multiday(
        n_active=n_active,
        n_code_days=n_code_days,
        n_trading_days=n_trading_days,
        n_codes=len(bars_by_code),
        hold_days=h,
        min_activation_rate=MIN_ACTIVATION_RATE_MULTIDAY,
    )
    return {
        "signal_id": SIGNAL_ID_MF_FLOW_PRICE,
        "hypothesis_class": CLASS_MULTI_FACTOR,
        "mode": "flow_price",
        "hold_days": h,
        "momentum_n": n,
        "gross_signed_mean_active": gross,
        "net_one_way_mean_active": net,
        "amortized_one_way_cost": am_cost,
        "one_way_cost": float(one_way_cost),
        "n_active_positions": n_active,
        "n_signed_returns": len(signed_returns),
        "n_margin_obs": n_margin_obs,
        "n_codes": len(bars_by_code),
        "n_code_days": n_code_days,
        "n_trading_days": n_trading_days,
        "occurrence": occ,
        **_freeze(),
        "note": (
            "Multi-factor flow×price confirm. Near-group parallel to "
            "flow_margin_hard/soft (do not merge). Not READY / not Mass."
        ),
    }


def evaluate_cross_section_on_bars(
    bars_by_code: Mapping[str, Sequence[tuple[str, float]]],
    *,
    momentum_n: int = 5,
    one_way_cost: float = DEFAULT_ONE_WAY_COST,
    long_frac: float = 0.3,
    short_frac: float = 0.3,
    hold_days: int = 1,
) -> dict[str, Any]:
    """Cross-section relative rank L-S on momentum.

    W79 improve: when ``hold_days`` > 1, apply sticky fixed_horizon hold per
    code and score multi-day forward returns on rebalance boundaries
    (amortized cost). hold_days=1 keeps prior daily L-S path.
    """
    n = int(momentum_n)
    h = int(hold_days)
    by_date: dict[str, dict[str, float | None]] = {}
    close_by: dict[str, dict[str, float]] = {}
    dates_by_code: dict[str, list[str]] = {}
    closes_list: dict[str, list[float]] = {}
    for code, pairs in bars_by_code.items():
        pairs_l = list(pairs)
        moms = momentum_series(pairs_l, n=n)
        for d, m in moms:
            by_date.setdefault(d, {})[code] = m
        dates_by_code[code] = [d for d, _ in pairs_l]
        closes_list[code] = [c for _, c in pairs_l]
        for d, c in pairs_l:
            close_by.setdefault(code, {})[d] = c

    dates = sorted(by_date.keys())
    signed_returns: list[float] = []
    n_active = 0

    if h <= 1:
        for i, d in enumerate(dates[:-1]):
            nxt = dates[i + 1]
            ranks = cross_section_rank_signs(
                by_date[d], long_frac=long_frac, short_frac=short_frac
            )
            for code, sign in ranks.items():
                if sign is None or sign == 0.0:
                    continue
                c0 = close_by.get(code, {}).get(d)
                c1 = close_by.get(code, {}).get(nxt)
                if c0 is None or c1 is None or c0 == 0:
                    continue
                r1 = (float(c1) / float(c0)) - 1.0
                n_active += 1
                signed_returns.append(float(sign) * r1)
        am_cost = float(one_way_cost)
    else:
        # Per-code sticky hold of daily rank signs
        daily_rank: dict[str, dict[str, float | None]] = {
            c: {} for c in bars_by_code
        }
        for d in dates:
            ranks = cross_section_rank_signs(
                by_date[d], long_frac=long_frac, short_frac=short_frac
            )
            for code, sign in ranks.items():
                daily_rank.setdefault(code, {})[d] = sign
        am_cost = amortized_one_way_cost(one_way_cost, h)
        for code, dlist in dates_by_code.items():
            entries = [daily_rank.get(code, {}).get(d) for d in dlist]
            held = apply_sticky_hold(entries, hold_days=h, rebalance_mode="fixed_horizon")
            closes = closes_list[code]
            for i, pos in enumerate(held):
                if pos is None or pos == 0.0:
                    continue
                if i % h != 0:
                    continue
                fwd = multi_day_forward_return(closes, hold_days=h, entry_index=i)
                if fwd is None:
                    continue
                n_active += 1
                signed_returns.append(float(pos) * float(fwd))

    gross = mean(signed_returns) if signed_returns else None
    net = (gross - float(am_cost)) if gross is not None else None
    n_codes = len(bars_by_code)
    n_trading_days = len(dates)
    n_code_days = n_trading_days * n_codes if n_trading_days and n_codes else 0
    occ = occurrence_rate_multiday(
        n_active=n_active,
        n_code_days=n_code_days,
        n_trading_days=n_trading_days,
        n_codes=n_codes,
        hold_days=h if h > 1 else 1,
        min_activation_rate=MIN_ACTIVATION_RATE_MULTIDAY,
    )
    return {
        "signal_id": SIGNAL_ID_CROSS_SECTION,
        "hypothesis_class": "cross_section_relative",
        "momentum_n": n,
        "hold_days": h,
        "gross_signed_mean_active": gross,
        "net_one_way_mean_active": net,
        "one_way_cost": float(one_way_cost),
        "amortized_one_way_cost": float(am_cost),
        "n_active_positions": n_active,
        "n_signed_returns": len(signed_returns),
        "n_codes": n_codes,
        "n_trading_days": n_trading_days,
        "n_code_days": n_code_days,
        "occurrence": occ,
        **_freeze(),
        "note": (
            f"Cross-section rank L-S hold_days={h}. Not READY / not Mass."
        ),
    }


def evaluate_event_post_on_bars(
    bars_by_code: Mapping[str, Sequence[tuple[str, float]]],
    events_by_code: Mapping[str, Sequence[Mapping[str, Any]]],
    *,
    post_hold_days: int = DEFAULT_EVENT_POST_HOLD_DAYS,
    one_way_cost: float = DEFAULT_ONE_WAY_COST,
    period_start: str | None = None,
    period_end: str | None = None,
    entry_mode: str = EVENT_POST_ENTRY_MODE,
) -> dict[str, Any]:
    """Evaluate event_post: post-disclosure multi-day hold on surprise sign.

    Scores only on disclosure events within period. Entry is **PIT-safe**:
    DiscDate+DiscTime SoT → first session close that does not look ahead
    (after-close / missing DiscTime → next trading bar). Hold is close-to-close
    over ``post_hold_days`` sessions from that entry.
    """
    h = int(post_hold_days)
    am_cost = amortized_one_way_cost(one_way_cost, h)
    signed_returns: list[float] = []
    n_events = 0
    n_scored = 0
    n_no_surprise = 0
    n_no_bar_match = 0
    n_same_day_entry = 0
    n_next_session_entry = 0
    holding_records: list[dict[str, Any]] = []

    for code, pairs in sorted(bars_by_code.items()):
        pairs_l = list(pairs)
        if len(pairs_l) < h + 1:
            continue
        date_to_idx = {str(d)[:10]: i for i, (d, _) in enumerate(pairs_l)}
        closes = [c for _, c in pairs_l]
        events = list(events_by_code.get(code) or [])
        for ev in events:
            disc = str(ev.get("disc_date") or "")[:10]
            if not disc:
                continue
            if period_start and disc < str(period_start)[:10]:
                continue
            if period_end and disc > str(period_end)[:10]:
                continue
            n_events += 1
            surprise, s_meta = earnings_surprise_proxy(
                eps=ev.get("eps"),
                feps=ev.get("feps"),
                prior_eps=ev.get("prior_eps"),
            )
            # Prefer envelope available_at / event_time when present (dataset SoT)
            disc_time = ev.get("disc_time")
            event_time = ev.get("event_time") or ev.get("available_at")
            idx, entry_date, entry_meta = event_post_entry_bar_index(
                date_to_idx,
                disc_date=disc,
                disc_time=disc_time,
                event_time=str(event_time) if event_time else None,
                entry_mode=entry_mode,
            )
            if idx is None or entry_date is None:
                n_no_bar_match += 1
                holding_records.append(
                    {
                        "date": None,
                        "code": code,
                        "sign": None,
                        "disc_date": disc,
                        "disc_time": disc_time,
                        "surprise": surprise,
                        "entry_meta": entry_meta,
                        "skip": "no_eligible_entry_bar",
                    }
                )
                continue
            if entry_date == disc:
                n_same_day_entry += 1
            else:
                n_next_session_entry += 1
            rec = compute_event_post_signal(
                surprise=surprise,
                is_event_day=True,
                is_trading_day=1.0,
                post_hold_days=h,
                code=code,
                date=entry_date,
                disc_date=disc,
                as_of=entry_meta.get("available_at"),
                extra_meta={
                    "surprise_meta": s_meta,
                    "entry_meta": entry_meta,
                },
            )
            val = rec.get("value")
            holding_records.append(
                {
                    "date": entry_date,
                    "code": code,
                    "sign": val,
                    "disc_date": disc,
                    "disc_time": disc_time,
                    "surprise": surprise,
                    "entry_meta": entry_meta,
                    "available_at": entry_meta.get("available_at"),
                }
            )
            if val is None or val == 0.0:
                n_no_surprise += 1
                continue
            fwd = multi_day_forward_return(closes, hold_days=h, entry_index=idx)
            if fwd is None:
                continue
            n_scored += 1
            signed_returns.append(float(val) * float(fwd))

    gross = mean(signed_returns) if signed_returns else None
    net = (gross - am_cost) if gross is not None else None
    trade_stats = trade_stats_report(
        signed_returns,
        hold_days=h,
        one_way_cost=float(one_way_cost),
        amortize_cost=True,
        trading_days_per_year=DEFAULT_TRADING_DAYS_PER_YEAR,
    )
    n_codes = len(bars_by_code)
    all_bar_dates: set[str] = set()
    for pairs in bars_by_code.values():
        for d, _ in pairs:
            all_bar_dates.add(str(d)[:10])
    if period_start:
        all_bar_dates = {d for d in all_bar_dates if d >= str(period_start)[:10]}
    if period_end:
        all_bar_dates = {d for d in all_bar_dates if d <= str(period_end)[:10]}
    n_trading_days = len(all_bar_dates)
    n_code_days = n_trading_days * n_codes if n_trading_days and n_codes else 0
    occ = occurrence_rate_event_post(
        n_events=n_events,
        n_scored=n_scored,
        n_trading_days=n_trading_days,
        n_codes=n_codes,
        n_code_days=n_code_days,
        trading_days_per_year=DEFAULT_TRADING_DAYS_PER_YEAR,
        min_events_per_code_year=MIN_EVENTS_PER_CODE_YEAR,
        min_events_per_trading_day=MIN_EVENTS_PER_TRADING_DAY,
    )
    return {
        "signal_id": SIGNAL_ID_EVENT_POST,
        "hypothesis_class": CLASS_EVENT_POST,
        "post_hold_days": h,
        "entry_mode": str(entry_mode),
        "gross_signed_mean_active": gross,
        "net_one_way_mean_active": net,
        "amortized_one_way_cost": am_cost,
        "one_way_cost": float(one_way_cost),
        "n_active_positions": n_scored,
        "n_signed_returns": len(signed_returns),
        "n_events": n_events,
        "n_no_surprise": n_no_surprise,
        "n_no_bar_match": n_no_bar_match,
        "n_same_day_entry": n_same_day_entry,
        "n_next_session_entry": n_next_session_entry,
        "n_codes": n_codes,
        "n_trading_days": n_trading_days,
        "n_code_days": n_code_days,
        "occurrence": occ,
        "trade_stats": trade_stats,
        "holding_records": holding_records,
        "non_null": n_scored,
        "non_null_rate": (
            float(n_scored) / float(n_events) if n_events else None
        ),
        **_freeze(),
        "note": (
            f"Event-post hold={h}d PIT entry (mode={entry_mode}) on fins "
            "DiscDate+DiscTime surprise proxy (+ fins_earnings_date thicken "
            "when merged; no invent surprise). Entry = first session close "
            "not looking ahead of availability. Occurrence = rate not count. "
            "trade_stats = t/Sharpe/winrate on hold nets. Gaps → skip. "
            "Not READY / not Mass."
        ),
    }


def evaluate_flow_demand_on_bars(
    bars_by_code: Mapping[str, Sequence[tuple[str, float]]],
    margin_by_code: Mapping[str, Sequence[tuple[str, float]]],
    short_series: Sequence[tuple[str, float]] | None = None,
    *,
    hold_days: int = DEFAULT_FLOW_HOLD_DAYS,
    one_way_cost: float = DEFAULT_ONE_WAY_COST,
    require_short_confirm: bool = False,
    short_confirm_mode: str | None = None,
) -> dict[str, Any]:
    """Evaluate flow_demand: multi-day sticky hold of margin change sign.

    Distinct from rejected S4 (daily sign flip). Rebalance on margin
    observation updates; hold sticky for ``hold_days`` sessions.

    ``short_confirm_mode`` (W85):
    * ``off`` — margin only (default when require_short_confirm=False)
    * ``hard`` — same-sign short required; missing short → no entry
    * ``soft`` — same-sign when short present; margin-only on short gap
      (cheap near-miss improve for occurrence without look-ahead)
    """
    h = int(hold_days)
    am_cost = amortized_one_way_cost(one_way_cost, h)
    # Resolve confirm mode (backward-compat with require_short_confirm bool).
    mode_raw = short_confirm_mode
    if mode_raw is None:
        mode_s = "hard" if require_short_confirm else "off"
    else:
        mode_s = str(mode_raw).strip().lower()
        if mode_s in {"true", "1", "yes", "on", "require"}:
            mode_s = "hard"
        elif mode_s in {"false", "0", "no", "none", "off"}:
            mode_s = "off"
        elif mode_s not in {"off", "hard", "soft"}:
            raise ValueError(
                f"short_confirm_mode must be off|hard|soft, got {mode_raw!r}"
            )
    require_hard = mode_s == "hard"
    # short ratio change map by date
    short_chg: dict[str, float | None] = {}
    if short_series:
        s_pairs = list(short_series)
        for i, (d, r) in enumerate(s_pairs):
            if i == 0:
                short_chg[d] = None
            else:
                prev = s_pairs[i - 1][1]
                if prev == 0:
                    short_chg[d] = None
                else:
                    short_chg[d] = (float(r) - float(prev)) / float(prev)

    signed_returns: list[float] = []
    n_active = 0
    n_margin_obs = 0
    holding_records: list[dict[str, Any]] = []

    for code, pairs in sorted(bars_by_code.items()):
        pairs_l = list(pairs)
        if len(pairs_l) < h + 2:
            continue
        margin_pairs = list(margin_by_code.get(code) or [])
        if len(margin_pairs) < 2:
            continue
        # Build daily entry signs: only non-null on margin update days
        margin_chg_by_date: dict[str, float | None] = {}
        for i, (d, m) in enumerate(margin_pairs):
            if i == 0:
                margin_chg_by_date[d] = None
                continue
            prev = margin_pairs[i - 1][1]
            if prev == 0:
                margin_chg_by_date[d] = None
            else:
                margin_chg_by_date[d] = (float(m) - float(prev)) / float(prev)
            n_margin_obs += 1

        dates = [d for d, _ in pairs_l]
        closes = [c for _, c in pairs_l]
        # Forward-fill last margin change onto bar calendar for entry series
        last_chg: float | None = None
        last_short: float | None = None
        entry_signs: list[float | None] = []
        for d in dates:
            if d in margin_chg_by_date and margin_chg_by_date[d] is not None:
                last_chg = margin_chg_by_date[d]
            if d in short_chg and short_chg[d] is not None:
                last_short = short_chg[d]
            # Only allow rebalance entry on margin observation days
            if d in margin_chg_by_date and margin_chg_by_date[d] is not None:
                rec = compute_flow_demand_signal(
                    margin_change=margin_chg_by_date[d],
                    short_ratio_change=last_short,
                    is_trading_day=1.0,
                    hold_days=h,
                    require_short_confirm=require_hard,
                    short_confirm_mode=mode_s,
                    code=code,
                    date=d,
                )
                entry_signs.append(rec.get("value"))
            else:
                # between margin prints: no new entry (sticky hold handles)
                entry_signs.append(None)

        held = apply_sticky_hold(
            entry_signs, hold_days=h, rebalance_mode="min_hold"
        )
        for i, pos in enumerate(held):
            holding_records.append(
                {"date": dates[i], "code": code, "sign": pos}
            )
            if pos is None or pos == 0.0:
                continue
            # Score on days where we have a fresh margin entry (rebalance)
            if entry_signs[i] is None or entry_signs[i] == 0.0:
                continue
            fwd = multi_day_forward_return(closes, hold_days=h, entry_index=i)
            if fwd is None:
                continue
            n_active += 1
            signed_returns.append(float(pos) * float(fwd))

    gross = mean(signed_returns) if signed_returns else None
    net = (gross - am_cost) if gross is not None else None
    n_code_days = len(holding_records)
    n_trading_days = len({r["date"] for r in holding_records})
    n_codes = len(bars_by_code)
    occ = occurrence_rate_multiday(
        n_active=n_active,
        n_code_days=n_code_days,
        n_trading_days=n_trading_days,
        n_codes=n_codes,
        hold_days=h,
        min_activation_rate=MIN_ACTIVATION_RATE_MULTIDAY,
    )
    return {
        "signal_id": SIGNAL_ID_FLOW_DEMAND,
        "hypothesis_class": CLASS_FLOW_DEMAND,
        "hold_days": h,
        "require_short_confirm": bool(require_hard),
        "short_confirm_mode": mode_s,
        "gross_signed_mean_active": gross,
        "net_one_way_mean_active": net,
        "amortized_one_way_cost": am_cost,
        "one_way_cost": float(one_way_cost),
        "n_active_positions": n_active,
        "n_signed_returns": len(signed_returns),
        "n_margin_obs": n_margin_obs,
        "n_codes": n_codes,
        "n_code_days": n_code_days,
        "n_trading_days": n_trading_days,
        "occurrence": occ,
        "n_codes_with_margin": sum(
            1 for c in bars_by_code if len(margin_by_code.get(c) or []) >= 2
        ),
        "holding_records": holding_records,
        "non_null": n_active,
        **_freeze(),
        "note": (
            f"Flow demand multi-day hold={h} from margin change "
            f"(short_confirm_mode={mode_s}). Not S4 daily. "
            "Not READY / not Mass."
        ),
    }


def evaluate_fundamentals_price_on_bars(
    bars_by_code: Mapping[str, Sequence[tuple[str, float]]],
    events_by_code: Mapping[str, Sequence[Mapping[str, Any]]],
    *,
    hold_days: int = DEFAULT_FUND_HOLD_DAYS,
    momentum_n: int = DEFAULT_FUND_MOMENTUM_N,
    one_way_cost: float = DEFAULT_ONE_WAY_COST,
    mode: str = "value_momentum_agree",
) -> dict[str, Any]:
    """Evaluate fundamentals_price: PIT value score × momentum, multi-day hold."""
    h = int(hold_days)
    n = int(momentum_n)
    am_cost = amortized_one_way_cost(one_way_cost, h)
    asof_map = load_fins_latest_asof_map(events_by_code)

    signed_returns: list[float] = []
    n_active = 0
    n_missing_fins = 0
    holding_records: list[dict[str, Any]] = []
    value_scores_all: list[float] = []

    # Cross-sectional benchmark: median value score per date when possible
    # First pass: collect value scores
    value_by_code_date: dict[str, dict[str, float | None]] = {}
    for code, pairs in bars_by_code.items():
        series = asof_map.get(code) or []
        value_by_code_date[code] = {}
        for d, close in pairs:
            fin = fins_asof(series, d)
            if fin is None:
                value_by_code_date[code][d] = None
                continue
            score, _ = fundamental_value_score(
                close=close, eps=fin.get("eps"), bps=fin.get("bps")
            )
            value_by_code_date[code][d] = score
            if score is not None:
                value_scores_all.append(score)

    global_median = None
    if value_scores_all:
        ss = sorted(value_scores_all)
        global_median = ss[len(ss) // 2]

    for code, pairs in sorted(bars_by_code.items()):
        pairs_l = list(pairs)
        if len(pairs_l) < max(h, n) + 2:
            continue
        moms = momentum_series(pairs_l, n=n)
        mom_by_date = {d: m for d, m in moms}
        closes = [c for _, c in pairs_l]
        dates = [d for d, _ in pairs_l]
        entries: list[float | None] = []
        for d, _close in pairs_l:
            vscore = value_by_code_date.get(code, {}).get(d)
            if vscore is None:
                n_missing_fins += 1
                entries.append(None)
                continue
            rec = compute_fundamentals_price_signal(
                value_score=vscore,
                momentum=mom_by_date.get(d),
                value_benchmark=global_median,
                is_trading_day=1.0,
                hold_days=h,
                mode=mode,
                code=code,
                date=d,
            )
            entries.append(rec.get("value"))
        held = apply_sticky_hold(entries, hold_days=h, rebalance_mode="fixed_horizon")
        for i, pos in enumerate(held):
            holding_records.append(
                {"date": dates[i], "code": code, "sign": pos}
            )
            if pos is None or pos == 0.0:
                continue
            if i % h != 0:
                continue
            fwd = multi_day_forward_return(closes, hold_days=h, entry_index=i)
            if fwd is None:
                continue
            n_active += 1
            signed_returns.append(float(pos) * float(fwd))

    gross = mean(signed_returns) if signed_returns else None
    net = (gross - am_cost) if gross is not None else None
    n_code_days = len(holding_records)
    n_trading_days = len({r["date"] for r in holding_records})
    n_codes = len(bars_by_code)
    occ = occurrence_rate_multiday(
        n_active=n_active,
        n_code_days=n_code_days,
        n_trading_days=n_trading_days,
        n_codes=n_codes,
        hold_days=h,
        # value×momentum agree is sparse by design; floor lower than sticky mom
        min_activation_rate=min(MIN_ACTIVATION_RATE_MULTIDAY, 0.01),
    )
    return {
        "signal_id": SIGNAL_ID_FUNDAMENTALS_PRICE,
        "hypothesis_class": CLASS_FUNDAMENTALS_PRICE,
        "hold_days": h,
        "momentum_n": n,
        "mode": mode,
        "value_benchmark_median": global_median,
        "gross_signed_mean_active": gross,
        "net_one_way_mean_active": net,
        "amortized_one_way_cost": am_cost,
        "one_way_cost": float(one_way_cost),
        "n_active_positions": n_active,
        "n_signed_returns": len(signed_returns),
        "n_missing_fins_days": n_missing_fins,
        "n_codes": n_codes,
        "n_code_days": n_code_days,
        "n_trading_days": n_trading_days,
        "occurrence": occ,
        "holding_records": holding_records,
        "non_null": n_active,
        **_freeze(),
        "note": (
            f"Fundamentals×price mode={mode} hold={h}d PIT fins. "
            "Not READY / not Mass."
        ),
    }


def _realized_vol(closes: Sequence[float], end_i: int, vol_n: int) -> float | None:
    if end_i < vol_n or vol_n < 2:
        return None
    rets: list[float] = []
    for j in range(end_i - vol_n + 1, end_i + 1):
        if j < 1:
            return None
        c0, c1 = closes[j - 1], closes[j]
        if c0 is None or c1 is None or c0 == 0:
            return None
        rets.append((float(c1) / float(c0)) - 1.0)
    if len(rets) < 2:
        return None
    m = mean(rets)
    var = sum((r - m) ** 2 for r in rets) / (len(rets) - 1)
    return math.sqrt(var) if var >= 0 else None


def evaluate_vol_risk_adjusted_on_bars(
    bars_by_code: Mapping[str, Sequence[tuple[str, float]]],
    *,
    hold_days: int = 5,
    vol_n: int = 10,
    vol_threshold: float = 1.0,
    one_way_cost: float = DEFAULT_ONE_WAY_COST,
    gate_mode: str = "mom_over_vol",
) -> dict[str, Any]:
    """Vol-gated multi-day mom (mom_over_vol or vol_expand)."""
    h = int(hold_days)
    vn = int(vol_n)
    thr = float(vol_threshold)
    mode = str(gate_mode or "mom_over_vol")
    am_cost = amortized_one_way_cost(one_way_cost, h)
    signed_returns: list[float] = []
    n_active = 0
    n_filtered = 0
    holding_records: list[dict[str, Any]] = []

    for code, pairs in sorted(bars_by_code.items()):
        pairs_l = list(pairs)
        if len(pairs_l) < max(h, vn) + 2:
            continue
        moms = momentum_series(pairs_l, n=h)
        closes = [c for _, c in pairs_l]
        dates = [d for d, _ in pairs_l]
        entry_signs: list[float | None] = []
        for i, (_d, mom) in enumerate(moms):
            if mom is None:
                entry_signs.append(None)
                continue
            vol = _realized_vol(closes, i, vn)
            if vol is None or vol <= 1e-12:
                entry_signs.append(None)
                n_filtered += 1
                continue
            if mode == "vol_expand":
                prior = _realized_vol(closes, i - vn, vn) if i >= 2 * vn else None
                if prior is None or prior <= 1e-12:
                    entry_signs.append(None)
                    n_filtered += 1
                    continue
                expand = vol / prior
                if expand < thr:
                    entry_signs.append(0.0)
                    n_filtered += 1
                    continue
                entry_signs.append(sign_from_numeric(mom))
            else:
                score = abs(float(mom)) / vol
                if score < thr:
                    entry_signs.append(0.0)
                    n_filtered += 1
                    continue
                entry_signs.append(sign_from_numeric(mom))
        held = apply_sticky_hold(
            entry_signs, hold_days=h, rebalance_mode="fixed_horizon"
        )
        for i, pos in enumerate(held):
            holding_records.append(
                {"date": dates[i], "code": code, "sign": pos}
            )
            if pos is None or pos == 0.0:
                continue
            if i % h != 0:
                continue
            fwd = multi_day_forward_return(closes, hold_days=h, entry_index=i)
            if fwd is None:
                continue
            n_active += 1
            signed_returns.append(float(pos) * float(fwd))

    gross = mean(signed_returns) if signed_returns else None
    net = (gross - am_cost) if gross is not None else None
    n_code_days = len(holding_records)
    n_trading_days = len({r["date"] for r in holding_records})
    return {
        "signal_id": f"c21_vol_risk_{mode}",
        "hypothesis_class": "vol_risk_adjusted",
        "hold_days": h,
        "vol_n": vn,
        "vol_threshold": thr,
        "gate_mode": mode,
        "gross_signed_mean_active": gross,
        "net_one_way_mean_active": net,
        "amortized_one_way_cost": am_cost,
        "one_way_cost": float(one_way_cost),
        "n_active_positions": n_active,
        "n_filtered": n_filtered,
        "n_signed_returns": len(signed_returns),
        "n_codes": len(bars_by_code),
        "n_code_days": n_code_days,
        "n_trading_days": n_trading_days,
        "occurrence": {
            "activation_rate": (
                float(n_active) / float(n_code_days) if n_code_days else None
            ),
            "n_active": n_active,
        },
        **_freeze(),
        "note": (
            f"Vol gate mode={mode} thr={thr} hold={h} vol_n={vn}. "
            "Not READY / not Mass."
        ),
    }


__all__ = [
    "evaluate_cross_section_on_bars",
    "evaluate_event_post_on_bars",
    "evaluate_flow_demand_on_bars",
    "evaluate_fundamentals_price_on_bars",
    "evaluate_macro_conditioned_on_bars",
    "evaluate_mf_flow_price_on_bars",
    "evaluate_mf_value_mom_rate_on_bars",
    "evaluate_multi_day_hold_on_bars",
    "evaluate_nky_vol_abs_level_on_bars",
    "evaluate_nky_vol_term_levels_on_bars",
    "evaluate_nky_vol_term_ratio_on_bars",
    "evaluate_opt225_vol_on_bars",
    "evaluate_rate_curve_xs_on_bars",
    "evaluate_rate_level_xs_on_bars",
    "evaluate_vol_risk_adjusted_on_bars",
]
