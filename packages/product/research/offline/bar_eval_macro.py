"""Offline bar-eval macro family (macro_conditioned, rate_level_xs, rate_curve_xs).

Not CF SoT; no GO.
"""

from __future__ import annotations

from statistics import mean
from typing import Any, Mapping, Sequence

from features.class_signals import (
    CLASS_MACRO_CONDITIONED,
    CLASS_RATE_FACTOR,
    DEFAULT_CURVE_INVERT_THRESHOLD,
    DEFAULT_CURVE_STEEP_THRESHOLD,
    DEFAULT_REPO_HIGH_THRESHOLD,
    DEFAULT_REPO_LOW_THRESHOLD,
    SIGNAL_ID_MACRO_CONDITIONED,
    SIGNAL_ID_RATE_CURVE_XS,
    SIGNAL_ID_RATE_LEVEL_XS,
    amortized_one_way_cost,
    apply_sticky_hold,
    compute_macro_conditioned_signal,
    compute_rate_curve_xs_signal,
    compute_rate_level_xs_signal,
    cross_section_rank_signs,
    multi_day_forward_return,
    occurrence_rate_multiday,
)
from research.cost_models import (
    DEFAULT_ONE_WAY_COST,
    REPO_DATASET_ID,
    lookup_repo_rate,
)
from research.eval_loaders import momentum_series
from research.offline.bar_eval_common import MIN_ACTIVATION_RATE_MULTIDAY, _freeze


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
    """Macro-conditioned momentum on bars + repo (level or change).

    Daily entry; next-session return when active. Full one-way per active day.
    """
    n = int(momentum_n)
    h = int(hold_days)
    signed_returns: list[float] = []
    n_active = 0
    n_regime_gap = 0
    regime_counts: dict[str, int] = {}
    n_code_days = 0
    trading_dates: set[str] = set()

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
            hit = lookup_repo_rate(repo_series, d)
            if hit.get("is_gap"):
                n_regime_gap += 1
                n_code_days += 1
                trading_dates.add(d)
                continue
            rate = hit.get("rate_pct")
            prev_rate = prev_map.get(str(d)[:10])
            if prev_rate is None and repo_dates:
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
            n_code_days += 1
            trading_dates.add(d)
            if val is None or val == 0.0:
                continue
            c0 = closes[i]
            c1 = closes[i + 1]
            if c0 is None or c1 is None or c0 == 0:
                continue
            r1 = (float(c1) / float(c0)) - 1.0
            n_active += 1
            signed_returns.append(float(val) * r1)

    gross = mean(signed_returns) if signed_returns else None
    net = (gross - float(one_way_cost)) if gross is not None else None
    n_trading_days = len(trading_dates)
    occ = occurrence_rate_multiday(
        n_active=n_active,
        n_code_days=n_code_days,
        n_trading_days=n_trading_days,
        n_codes=len(bars_by_code),
        hold_days=1,
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
        "n_regime_gap": n_regime_gap,
        "regime_counts": regime_counts,
        "n_codes": len(bars_by_code),
        "n_code_days": n_code_days,
        "n_trading_days": n_trading_days,
        "occurrence": occ,
        "non_null_rate": (
            float(n_active) / float(n_code_days) if n_code_days else None
        ),
        "repo_dataset": REPO_DATASET_ID,
        **_freeze(),
        "note": (
            f"Macro-conditioned momentum mode={mode} on jsda_tokyo_repo_rates. "
            "Repo gaps → no trade (no invent)."
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
    """Absolute rate-level factor × CS book (risk-on/off), multi-day sticky."""
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
    daily_adj: dict[str, dict[str, float | None]] = {c: {} for c in bars_by_code}
    for d in dates:
        ranks = cross_section_rank_signs(
            by_date[d], long_frac=long_frac, short_frac=short_frac
        )
        hit = lookup_repo_rate(repo_series, d) if repo_series else {"is_gap": True}
        if hit.get("is_gap") or hit.get("rate_pct") is None:
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
            daily_adj.setdefault(code, {})[d] = rec.get("value")

    signed_returns: list[float] = []
    n_active = 0
    n_code_days = 0
    trading_dates: set[str] = set()
    for code, dlist in dates_by_code.items():
        entries = [daily_adj.get(code, {}).get(d) for d in dlist]
        held = apply_sticky_hold(entries, hold_days=h, rebalance_mode="fixed_horizon")
        closes = closes_list[code]
        for i, pos in enumerate(held):
            n_code_days += 1
            trading_dates.add(dlist[i])
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
    n_trading_days = len(trading_dates)
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
        "n_codes": len(bars_by_code),
        "n_code_days": n_code_days,
        "n_trading_days": n_trading_days,
        "occurrence": occ,
        **_freeze(),
        "note": (
            "Absolute rate-level factor × CS risk-on/off book on "
            "jsda_tokyo_repo_rates."
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
    for d in dates:
        ranks = cross_section_rank_signs(
            by_date[d], long_frac=long_frac, short_frac=short_frac
        )
        s_rate = short_by.get(str(d)[:10])
        l_rate = long_by.get(str(d)[:10])
        if s_rate is None or l_rate is None:
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
            daily_adj.setdefault(code, {})[d] = rec.get("value")

    signed_returns: list[float] = []
    n_active = 0
    n_code_days = 0
    trading_dates: set[str] = set()
    for code, dlist in dates_by_code.items():
        entries = [daily_adj.get(code, {}).get(d) for d in dlist]
        held = apply_sticky_hold(entries, hold_days=h, rebalance_mode="fixed_horizon")
        closes = closes_list[code]
        for i, pos in enumerate(held):
            n_code_days += 1
            trading_dates.add(dlist[i])
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
    n_trading_days = len(trading_dates)
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
        "gross_signed_mean_active": gross,
        "net_one_way_mean_active": net,
        "amortized_one_way_cost": am_cost,
        "one_way_cost": float(one_way_cost),
        "n_active_positions": n_active,
        "n_codes": len(bars_by_code),
        "n_code_days": n_code_days,
        "n_trading_days": n_trading_days,
        "occurrence": occ,
        **_freeze(),
        "note": "Repo curve-shape factor (3M−overnight) × CS book.",
    }
