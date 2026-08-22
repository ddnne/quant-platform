"""Offline bar-eval vol family (nky_vol_*, opt225_vol, vol_risk_adjusted).

Not CF SoT; no GO.
"""

from __future__ import annotations

import math
from statistics import mean
from typing import Any, Mapping, Sequence

from features.class_signals import (
    CLASS_INDEX_VOL_REGIME,
    CLASS_OPTIONS_VOL_REGIME,
    DEFAULT_NKY_VOL_COMPRESS_RATIO,
    DEFAULT_NKY_VOL_EXPAND_RATIO,
    DEFAULT_NKY_VOL_HIGH_THRESHOLD,
    DEFAULT_NKY_VOL_LOW_THRESHOLD,
    DEFAULT_OPT225_VOL_COMPRESS_RATIO,
    DEFAULT_OPT225_VOL_EXPAND_RATIO,
    DEFAULT_OPT225_VOL_HIGH_THRESHOLD,
    DEFAULT_OPT225_VOL_LOW_THRESHOLD,
    OPT225_SPREAD_CONVENTION,
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
    amortized_one_way_cost,
    apply_sticky_hold,
    compute_nky_vol_abs_level_signal,
    compute_nky_vol_term_levels_signal,
    compute_nky_vol_term_ratio_signal,
    compute_opt225_vol_signal,
    cross_section_rank_signs,
    multi_day_forward_return,
    occurrence_rate_multiday,
    sign_from_numeric,
)
from research.cost_models import DEFAULT_ONE_WAY_COST
from research.eval_loaders import momentum_series
from research.offline.bar_eval_common import MIN_ACTIVATION_RATE_MULTIDAY, _freeze


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
        "n_regime_gap": n_regime_gap,
        "regime_counts": regime_counts,
        "n_codes": len(bars_by_code),
        "n_code_days": n_code_days,
        "n_trading_days": n_trading_days,
        "occurrence": occ,
        **_freeze(),
        "note": (
            f"Index-level Nikkei/TOPIX vol regime mode={m} × CS book. "
            "Not per-name vol_risk_adjusted."
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
        "n_regime_gap": n_regime_gap,
        "regime_counts": regime_counts,
        "n_codes": len(dates_by_code),
        "n_code_days": n_code_days,
        "n_trading_days": n_trading_days,
        "occurrence": occ,
        **_freeze(),
        "note": (
            f"options_225 {sk} regime mode={m} × CS book. Canonical Nikkei vol SoT. "
            "nky_vol_* remains proxy/compare only."
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
    n_code_days = 0
    trading_dates: set[str] = set()

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
                continue
            if mode == "vol_expand":
                prior = _realized_vol(closes, i - vn, vn) if i >= 2 * vn else None
                if prior is None or prior <= 1e-12:
                    entry_signs.append(None)
                    continue
                expand = vol / prior
                if expand < thr:
                    entry_signs.append(0.0)
                    continue
                entry_signs.append(sign_from_numeric(mom))
            else:
                score = abs(float(mom)) / vol
                if score < thr:
                    entry_signs.append(0.0)
                    continue
                entry_signs.append(sign_from_numeric(mom))
        held = apply_sticky_hold(
            entry_signs, hold_days=h, rebalance_mode="fixed_horizon"
        )
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
        "note": f"Vol gate mode={mode} thr={thr} hold={h} vol_n={vn}.",
    }
