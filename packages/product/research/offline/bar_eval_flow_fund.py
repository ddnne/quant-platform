"""Offline bar-eval flow/fund family (flow, fundamentals, mf_*, cross_section).

Not CF SoT; no GO.
"""

from __future__ import annotations

from statistics import mean
from typing import Any, Mapping, Sequence

from features.class_signals import (
    CLASS_FLOW_DEMAND,
    CLASS_FUNDAMENTALS_PRICE,
    CLASS_MULTI_FACTOR,
    DEFAULT_FLOW_HOLD_DAYS,
    DEFAULT_FUND_HOLD_DAYS,
    DEFAULT_FUND_MOMENTUM_N,
    DEFAULT_REPO_HIGH_THRESHOLD,
    DEFAULT_REPO_LOW_THRESHOLD,
    SIGNAL_ID_CROSS_SECTION,
    SIGNAL_ID_FLOW_DEMAND,
    SIGNAL_ID_FUNDAMENTALS_PRICE,
    SIGNAL_ID_MF_FLOW_PRICE,
    SIGNAL_ID_MF_VALUE_MOM_RATE,
    amortized_one_way_cost,
    apply_sticky_hold,
    compute_flow_demand_signal,
    compute_fundamentals_price_signal,
    compute_mf_flow_price_signal,
    compute_mf_value_mom_rate_signal,
    cross_section_rank_signs,
    fundamental_value_score,
    multi_day_forward_return,
    occurrence_rate_multiday,
)
from research.cost_models import DEFAULT_ONE_WAY_COST, lookup_repo_rate
from research.eval_loaders import (
    fins_asof,
    load_fins_latest_asof_map,
    momentum_series,
)
from research.offline.bar_eval_common import MIN_ACTIVATION_RATE_MULTIDAY, _freeze


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
    n_code_days = 0
    trading_dates: set[str] = set()
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
            n_code_days += 1
            trading_dates.add(dates[i])
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
        "n_missing_fins_or_rate": n_missing,
        "n_codes": len(bars_by_code),
        "n_code_days": n_code_days,
        "n_trading_days": n_trading_days,
        "occurrence": occ,
        **_freeze(),
        "note": (
            "Multi-factor value×mom×rate. Distinct from fund_value_mom_agree. "
            "PIT fins + date-matched repo."
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
    n_code_days = 0
    trading_dates: set[str] = set()

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
            n_code_days += 1
            trading_dates.add(dates[i])
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
        "n_margin_obs": n_margin_obs,
        "n_codes": len(bars_by_code),
        "n_code_days": n_code_days,
        "n_trading_days": n_trading_days,
        "occurrence": occ,
        **_freeze(),
        "note": (
            "Multi-factor flow×price confirm. Near-group parallel to "
            "flow_margin_hard/soft (do not merge)."
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

    hold_days=1 is daily L-S; hold_days>1 uses sticky fixed_horizon + amortized cost.
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
        "n_codes": n_codes,
        "n_trading_days": n_trading_days,
        "n_code_days": n_code_days,
        "occurrence": occ,
        **_freeze(),
        "note": f"Cross-section rank L-S hold_days={h}.",
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
    """Flow demand: sticky hold of margin-change sign (not daily sign flip).

    ``short_confirm_mode``: off (margin only) / hard (same-sign short required)
    / soft (same-sign when short present; margin-only on short gap).
    """
    h = int(hold_days)
    am_cost = amortized_one_way_cost(one_way_cost, h)
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
    n_code_days = 0
    trading_dates: set[str] = set()

    for code, pairs in sorted(bars_by_code.items()):
        pairs_l = list(pairs)
        if len(pairs_l) < h + 2:
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

        dates = [d for d, _ in pairs_l]
        closes = [c for _, c in pairs_l]
        last_short: float | None = None
        entry_signs: list[float | None] = []
        for d in dates:
            if d in short_chg and short_chg[d] is not None:
                last_short = short_chg[d]
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
                entry_signs.append(None)

        held = apply_sticky_hold(
            entry_signs, hold_days=h, rebalance_mode="min_hold"
        )
        for i, pos in enumerate(held):
            n_code_days += 1
            trading_dates.add(dates[i])
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
    n_trading_days = len(trading_dates)
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
        "n_margin_obs": n_margin_obs,
        "n_codes": n_codes,
        "n_code_days": n_code_days,
        "n_trading_days": n_trading_days,
        "occurrence": occ,
        "n_codes_with_margin": sum(
            1 for c in bars_by_code if len(margin_by_code.get(c) or []) >= 2
        ),
        "non_null": n_active,
        **_freeze(),
        "note": (
            f"Flow demand multi-day hold={h} from margin change "
            f"(short_confirm_mode={mode_s}). Not S4 daily."
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
    """Fundamentals × price: PIT value score × momentum, multi-day hold."""
    h = int(hold_days)
    n = int(momentum_n)
    am_cost = amortized_one_way_cost(one_way_cost, h)
    asof_map = load_fins_latest_asof_map(events_by_code)

    signed_returns: list[float] = []
    n_active = 0
    n_missing_fins = 0
    n_code_days = 0
    trading_dates: set[str] = set()
    value_scores_all: list[float] = []

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
            n_code_days += 1
            trading_dates.add(dates[i])
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
    n_codes = len(bars_by_code)
    occ = occurrence_rate_multiday(
        n_active=n_active,
        n_code_days=n_code_days,
        n_trading_days=n_trading_days,
        n_codes=n_codes,
        hold_days=h,
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
        "n_missing_fins_days": n_missing_fins,
        "n_codes": n_codes,
        "n_code_days": n_code_days,
        "n_trading_days": n_trading_days,
        "occurrence": occ,
        "non_null": n_active,
        **_freeze(),
        "note": f"Fundamentals×price mode={mode} hold={h}d PIT fins.",
    }
