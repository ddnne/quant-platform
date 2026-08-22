"""Flow/fund-family class signals: flow_demand, fundamentals, CS, mf_*.

Not simple daily sign. Mass / READY / GO closed. No S1–S5 un-reject.
"""

from __future__ import annotations

from typing import Any, Mapping

from .class_signals import (
    CANDIDATE_ONLY,
    CLASS_CROSS_SECTION_RELATIVE,
    CLASS_FLOW_DEMAND,
    CLASS_FUNDAMENTALS_PRICE,
    CLASS_MULTI_FACTOR,
    DEFAULT_FLOW_HOLD_DAYS,
    DEFAULT_FUND_HOLD_DAYS,
    DEFAULT_REPO_HIGH_THRESHOLD,
    DEFAULT_REPO_LOW_THRESHOLD,
    FLOW_DEMAND_DATASETS,
    FUNDAMENTAL_RATIO_FEATURE_ID,
    FUNDAMENTALS_PRICE_DATASETS,
    MARGIN_CHANGE_FEATURE_ID,
    MOMENTUM_FEATURE_ID,
    MULTI_FACTOR_DATASETS,
    SHORT_RATIO_FEATURE_ID,
    SIGNAL_ID_CROSS_SECTION,
    SIGNAL_ID_FLOW_DEMAND,
    SIGNAL_ID_FUNDAMENTALS_PRICE,
    SIGNAL_ID_MF_FLOW_PRICE,
    SIGNAL_ID_MF_VALUE_MOM_RATE,
    SIGNAL_STATUS,
    SIGNAL_VERSION,
    TRADING_DAY_FEATURE_ID,
    _freeze_meta,
)
from .class_signals_hold import (
    _as_float_or_none,
    apply_trading_day_filter,
    sign_from_numeric,
)
from .class_signals_macro import repo_regime_from_level


# ---------------------------------------------------------------------------
# optional third: cross_section_relative (rank within day)
# ---------------------------------------------------------------------------


def cross_section_rank_signs(
    values_by_code: Mapping[str, float | None],
    *,
    long_frac: float = 0.3,
    short_frac: float = 0.3,
) -> dict[str, float | None]:
    """Rank codes by value; top long_frac → +1, bottom short_frac → −1.

    Remaining middle / missing → 0 or None.
    """
    scored: list[tuple[str, float]] = []
    missing: list[str] = []
    for code, v in values_by_code.items():
        if v is None:
            missing.append(str(code))
            continue
        try:
            scored.append((str(code), float(v)))
        except (TypeError, ValueError):
            missing.append(str(code))
    scored.sort(key=lambda x: (-x[1], x[0]))
    n = len(scored)
    out: dict[str, float | None] = {c: None for c in missing}
    if n == 0:
        return out
    n_long = max(1, int(round(n * float(long_frac)))) if n >= 3 else 1
    n_short = max(1, int(round(n * float(short_frac)))) if n >= 3 else 1
    if n_long + n_short > n:
        n_long = max(1, n // 3)
        n_short = max(1, n // 3)
    for i, (code, _) in enumerate(scored):
        if i < n_long:
            out[code] = 1.0
        elif i >= n - n_short:
            out[code] = -1.0
        else:
            out[code] = 0.0
    return out


def compute_cross_section_signal(
    *,
    momentum_by_code: Mapping[str, float | None],
    is_trading_day: float | None = 1.0,
    long_frac: float = 0.3,
    short_frac: float = 0.3,
    date: str | None = None,
    as_of: str | None = None,
) -> dict[str, Any]:
    """Cross-section relative L-S from same-day momentum ranks (optional third)."""
    filtered_td, filter_meta = apply_trading_day_filter(1.0, is_trading_day)
    if filtered_td is None:
        obs = [
            {
                "signal_id": SIGNAL_ID_CROSS_SECTION,
                "value": None,
                "code": str(c),
                "date": str(date)[:10] if date else None,
                "as_of": as_of,
                "metadata": {"filter": filter_meta},
            }
            for c in momentum_by_code
        ]
        return {
            "signal_id": SIGNAL_ID_CROSS_SECTION,
            "hypothesis_class": CLASS_CROSS_SECTION_RELATIVE,
            "status": SIGNAL_STATUS,
            "observations": obs,
            "filter": filter_meta,
            **_freeze_meta(),
        }

    ranks = cross_section_rank_signs(
        momentum_by_code, long_frac=long_frac, short_frac=short_frac
    )
    obs = []
    for code, val in sorted(ranks.items()):
        obs.append(
            {
                "signal_id": SIGNAL_ID_CROSS_SECTION,
                "version": SIGNAL_VERSION,
                "status": SIGNAL_STATUS,
                "hypothesis_class": CLASS_CROSS_SECTION_RELATIVE,
                "value": val,
                "code": code,
                "date": str(date)[:10] if date else None,
                "as_of": as_of,
                "metadata": {
                    "primary_feature_id": MOMENTUM_FEATURE_ID,
                    "momentum": momentum_by_code.get(code),
                    "long_frac": long_frac,
                    "short_frac": short_frac,
                    "filter": filter_meta,
                    "not_simple_daily_sign": True,
                    **_freeze_meta(),
                },
            }
        )
    return {
        "signal_id": SIGNAL_ID_CROSS_SECTION,
        "version": SIGNAL_VERSION,
        "status": SIGNAL_STATUS,
        "hypothesis_class": CLASS_CROSS_SECTION_RELATIVE,
        "observations": obs,
        "n_codes": len(obs),
        "filter": filter_meta,
        "formula": (
            f"rank(momentum) within day; top {long_frac:.0%} +1 / "
            f"bottom {short_frac:.0%} -1"
        ),
        **_freeze_meta(),
    }

def fundamental_value_score(
    *,
    close: float | None,
    eps: float | None = None,
    bps: float | None = None,
) -> tuple[float | None, dict[str, Any]]:
    """Cheap value score: prefer BPS/price, else EPS/price. None if missing."""
    c = _as_float_or_none(close)
    if c is None or c == 0.0:
        return None, {"reason": "close missing or zero", "close": c}
    b = _as_float_or_none(bps)
    e = _as_float_or_none(eps)
    if b is not None:
        score = b / c
        return score, {"mode": "bps_over_price", "bps": b, "close": c, "score": score}
    if e is not None:
        score = e / c
        return score, {"mode": "eps_over_price", "eps": e, "close": c, "score": score}
    return None, {"reason": "no BPS or EPS", "close": c}


def compute_flow_demand_signal(
    *,
    margin_change: float | None,
    short_ratio_change: float | None = None,
    is_trading_day: float | None = 1.0,
    hold_days: int = DEFAULT_FLOW_HOLD_DAYS,
    require_short_confirm: bool = False,
    short_confirm_mode: str | None = None,
    code: str | None = None,
    date: str | None = None,
    as_of: str | None = None,
    extra_meta: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Multi-day flow/demand from margin interest change (not S4 1d flip).

    Entry = sign(margin_change). Optional short_ratio_change confirmation:

    * ``short_confirm_mode="off"`` (default) — margin only
    * ``"hard"`` / ``require_short_confirm=True`` — same-sign required;
      missing short → no entry
    * ``"soft"`` (W85) — same-sign when short present; margin-only on short
      gap (cheap occurrence improve; no look-ahead)

    Hold via sticky multi-day structure at the eval layer — this returns the
    **entry** sign.
    """
    h = int(hold_days)
    if short_confirm_mode is None:
        mode_s = "hard" if require_short_confirm else "off"
    else:
        mode_s = str(short_confirm_mode).strip().lower()
        if mode_s in {"true", "1", "yes", "on", "require"}:
            mode_s = "hard"
        elif mode_s in {"false", "0", "no", "none"}:
            mode_s = "off"
        elif mode_s not in {"off", "hard", "soft"}:
            raise ValueError(
                f"short_confirm_mode must be off|hard|soft, got "
                f"{short_confirm_mode!r}"
            )
    raw = sign_from_numeric(margin_change)
    filtered, filter_meta = apply_trading_day_filter(raw, is_trading_day)
    short_sign = sign_from_numeric(short_ratio_change)
    confirmed = True
    confirm_meta: dict[str, Any] = {
        "require_short_confirm": mode_s == "hard",
        "short_confirm_mode": mode_s,
        "short_ratio_change": short_ratio_change,
        "short_sign": short_sign,
    }
    value = filtered
    if mode_s == "hard":
        if short_sign is None or filtered is None:
            value = None
            confirmed = False
            confirm_meta["reason"] = "short_or_margin_missing"
        elif short_sign == 0.0 or filtered == 0.0:
            value = 0.0
            confirm_meta["reason"] = "flat_leg"
        elif (short_sign > 0) != (filtered > 0):
            value = None
            confirmed = False
            confirm_meta["reason"] = "short_margin_sign_conflict"
        else:
            confirm_meta["reason"] = "confirmed_same_sign"
    elif mode_s == "soft":
        # Soft (W85 cheap near-miss improve):
        # * same-sign short when available → preferred entry
        # * short gap → margin-only
        # * sign conflict → keep margin entry (confirmation optional, not a hard gate)
        # Distinct from hard confirm (conflict → no entry) and from S4 daily flip.
        if filtered is None:
            value = None
            confirmed = False
            confirm_meta["reason"] = "margin_missing"
        elif short_sign is None:
            value = filtered
            confirmed = True
            confirm_meta["reason"] = "soft_margin_only_short_gap"
        elif short_sign == 0.0 or filtered == 0.0:
            value = 0.0
            confirm_meta["reason"] = "flat_leg"
        elif (short_sign > 0) != (filtered > 0):
            value = filtered
            confirmed = False
            confirm_meta["reason"] = "soft_conflict_keep_margin"
        else:
            confirm_meta["reason"] = "soft_confirmed_same_sign"
    confirm_meta["confirmed"] = confirmed

    meta: dict[str, Any] = {
        "signal_id": SIGNAL_ID_FLOW_DEMAND,
        "signal_version": SIGNAL_VERSION,
        "status": SIGNAL_STATUS,
        "hypothesis_class": CLASS_FLOW_DEMAND,
        "primary_feature_id": MARGIN_CHANGE_FEATURE_ID,
        "short_feature_id": SHORT_RATIO_FEATURE_ID,
        "filter_feature_id": TRADING_DAY_FEATURE_ID,
        "datasets_required": list(FLOW_DEMAND_DATASETS),
        "margin_change": margin_change,
        "hold_days": h,
        "raw_entry_sign": raw,
        "filter": filter_meta,
        "confirm": confirm_meta,
        "formula": (
            f"entry=sign(margin_interest_change); sticky hold={h}d "
            f"(not S4 daily); short_confirm_mode={mode_s}"
        ),
        "not_simple_daily_sign": True,
        "not_s4_rehash": True,
        "note": (
            "Multi-day margin flow demand. Distinct from rejected S4 daily "
            "margin_change_sign. Not READY. Not mass."
        ),
    }
    meta.update(_freeze_meta())
    if code is not None:
        meta["code"] = str(code)
    if date is not None:
        meta["date"] = str(date)[:10]
    if as_of is not None:
        meta["as_of"] = str(as_of)
    if extra_meta:
        meta.update(dict(extra_meta))
    return {
        "signal_id": SIGNAL_ID_FLOW_DEMAND,
        "version": SIGNAL_VERSION,
        "status": SIGNAL_STATUS,
        "hypothesis_class": CLASS_FLOW_DEMAND,
        "value": value,
        "code": str(code) if code is not None else None,
        "date": str(date)[:10] if date is not None else None,
        "as_of": as_of,
        "hold_days": h,
        "metadata": meta,
    }


def compute_fundamentals_price_signal(
    *,
    value_score: float | None,
    momentum: float | None,
    value_benchmark: float | None = None,
    is_trading_day: float | None = 1.0,
    hold_days: int = DEFAULT_FUND_HOLD_DAYS,
    mode: str = "value_momentum_agree",
    code: str | None = None,
    date: str | None = None,
    as_of: str | None = None,
    extra_meta: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Fundamentals × price: value vs benchmark conditioned on momentum.

    Modes
    -----
    value_momentum_agree (default):
        long only when value_score > benchmark AND momentum > 0;
        short only when value_score < benchmark AND momentum < 0;
        else None.
    value_only:
        entry = sign(value_score - benchmark)
    """
    h = int(hold_days)
    m = str(mode or "value_momentum_agree").strip().lower()
    _, filter_meta = apply_trading_day_filter(1.0, is_trading_day)
    if filter_meta.get("passed") is not True:
        value = None
        rule = "non_trading_day"
    elif value_score is None:
        value = None
        rule = "value_score_missing"
    else:
        bench = 0.0 if value_benchmark is None else float(value_benchmark)
        value_sign = sign_from_numeric(float(value_score) - bench)
        mom_sign = sign_from_numeric(momentum)
        if m == "value_only":
            value = value_sign
            rule = "value_only"
        elif m == "value_momentum_agree":
            if value_sign is None or mom_sign is None or value_sign == 0.0:
                value = None if value_sign is None else 0.0
                rule = "flat_or_missing"
            elif mom_sign == 0.0:
                value = None
                rule = "momentum_flat_no_trade"
            elif (value_sign > 0 and mom_sign > 0) or (
                value_sign < 0 and mom_sign < 0
            ):
                value = value_sign
                rule = "value_and_momentum_agree"
            else:
                value = None
                rule = "value_momentum_disagree"
        else:
            raise ValueError(
                f"mode must be value_momentum_agree|value_only, got {mode!r}"
            )

    meta: dict[str, Any] = {
        "signal_id": SIGNAL_ID_FUNDAMENTALS_PRICE,
        "signal_version": SIGNAL_VERSION,
        "status": SIGNAL_STATUS,
        "hypothesis_class": CLASS_FUNDAMENTALS_PRICE,
        "primary_feature_id": FUNDAMENTAL_RATIO_FEATURE_ID,
        "momentum_feature_id": MOMENTUM_FEATURE_ID,
        "filter_feature_id": TRADING_DAY_FEATURE_ID,
        "datasets_required": list(FUNDAMENTALS_PRICE_DATASETS),
        "value_score": value_score,
        "value_benchmark": value_benchmark,
        "momentum": momentum,
        "hold_days": h,
        "mode": m,
        "rule": rule,
        "filter": filter_meta,
        "formula": (
            f"value_score (BPS/P or EPS/P) vs benchmark; mode={m}; "
            f"sticky hold={h}d (PIT fins)"
        ),
        "not_simple_daily_sign": True,
        "note": (
            "Fundamentals vs price with PIT fins_summary. Not READY. Not mass."
        ),
    }
    meta.update(_freeze_meta())
    if code is not None:
        meta["code"] = str(code)
    if date is not None:
        meta["date"] = str(date)[:10]
    if as_of is not None:
        meta["as_of"] = str(as_of)
    if extra_meta:
        meta.update(dict(extra_meta))
    return {
        "signal_id": SIGNAL_ID_FUNDAMENTALS_PRICE,
        "version": SIGNAL_VERSION,
        "status": SIGNAL_STATUS,
        "hypothesis_class": CLASS_FUNDAMENTALS_PRICE,
        "value": value,
        "code": str(code) if code is not None else None,
        "date": str(date)[:10] if date is not None else None,
        "as_of": as_of,
        "hold_days": h,
        "metadata": meta,
    }

# ---------------------------------------------------------------------------
# W89 multi_factor — value×mom×rate · flow×price (thesis-required combinations)
# ---------------------------------------------------------------------------


def compute_mf_value_mom_rate_signal(
    *,
    value_score: float | None,
    momentum: float | None,
    repo_rate: float | None,
    value_benchmark: float | None = None,
    high_threshold: float = DEFAULT_REPO_HIGH_THRESHOLD,
    low_threshold: float = DEFAULT_REPO_LOW_THRESHOLD,
    hold_days: int = DEFAULT_FUND_HOLD_DAYS,
    code: str | None = None,
    date: str | None = None,
    as_of: str | None = None,
    extra_meta: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Three-factor: value × price-mom agree, then funding-level alignment.

    Thesis: cheap winners earn more under easy funding; expensive losers under
    tight funding. Distinct from fund_value_mom_agree (no rate leg).
    """
    h = int(hold_days)
    fund = compute_fundamentals_price_signal(
        value_score=value_score,
        momentum=momentum,
        value_benchmark=value_benchmark,
        hold_days=h,
        mode="value_momentum_agree",
        code=code,
        date=date,
        as_of=as_of,
    )
    base = fund.get("value")
    regime, regime_meta = repo_regime_from_level(
        repo_rate,
        high_threshold=high_threshold,
        low_threshold=low_threshold,
    )
    # Funding alignment: longs only when not high; shorts only when not low
    value: float | None
    rule: str
    if base is None:
        value, rule = None, "base_value_mom_null"
    elif base == 0.0:
        value, rule = 0.0, "base_flat"
    elif regime is None:
        value, rule = None, "rate_regime_missing"
    elif float(base) > 0 and regime in {"low", "mid"}:
        value, rule = float(base), "long_allowed_easy_or_mid_funding"
    elif float(base) < 0 and regime in {"high", "mid"}:
        value, rule = float(base), "short_allowed_tight_or_mid_funding"
    else:
        value, rule = None, "funding_misaligned_no_trade"

    meta: dict[str, Any] = {
        "signal_id": SIGNAL_ID_MF_VALUE_MOM_RATE,
        "signal_version": SIGNAL_VERSION,
        "status": SIGNAL_STATUS,
        "hypothesis_class": CLASS_MULTI_FACTOR,
        "factors": ["value", "momentum", "rate_level"],
        "datasets_required": list(MULTI_FACTOR_DATASETS),
        "base_fund": fund.get("metadata"),
        "repo_rate": repo_rate,
        "regime": regime_meta,
        "rule": rule,
        "hold_days": h,
        "formula": (
            "value_mom_agree AND (long only if rate not high; "
            "short only if rate not low)"
        ),
        "not_simple_daily_sign": True,
        "not_fund_value_mom_agree_only": True,
        "note": (
            "Multi-factor value×mom×rate. Distinct from fund_value_mom_agree. "
            "Not READY. Not mass."
        ),
    }
    meta.update(_freeze_meta())
    if code is not None:
        meta["code"] = str(code)
    if date is not None:
        meta["date"] = str(date)[:10]
    if as_of is not None:
        meta["as_of"] = str(as_of)
    if extra_meta:
        meta.update(dict(extra_meta))
    return {
        "signal_id": SIGNAL_ID_MF_VALUE_MOM_RATE,
        "version": SIGNAL_VERSION,
        "status": SIGNAL_STATUS,
        "candidate_only": CANDIDATE_ONLY,
        "hypothesis_class": CLASS_MULTI_FACTOR,
        "value": value,
        "regime": regime,
        "code": str(code) if code is not None else None,
        "date": str(date)[:10] if date is not None else None,
        "as_of": as_of,
        "metadata": meta,
    }


def compute_mf_flow_price_signal(
    *,
    margin_change: float | None,
    momentum: float | None,
    is_trading_day: float | None = 1.0,
    hold_days: int = DEFAULT_FLOW_HOLD_DAYS,
    code: str | None = None,
    date: str | None = None,
    as_of: str | None = None,
    extra_meta: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Two-factor: margin flow confirmed by price momentum (not short-ratio).

    Thesis: demand pressure earns only when price co-moves (flow×price).
    Distinct from flow_margin_short_hard/soft (short confirm) and
    flow_margin_pressure (flow only).
    """
    h = int(hold_days)
    _, filter_meta = apply_trading_day_filter(1.0, is_trading_day)
    flow_sign = sign_from_numeric(margin_change)
    mom_sign = sign_from_numeric(momentum)
    if filter_meta.get("passed") is not True:
        value, rule = None, "non_trading_day"
    elif flow_sign is None:
        value, rule = None, "margin_change_missing"
    elif mom_sign is None or mom_sign == 0.0:
        value, rule = None, "momentum_flat_or_missing"
    elif flow_sign == 0.0:
        value, rule = 0.0, "flow_flat"
    elif (flow_sign > 0 and mom_sign > 0) or (flow_sign < 0 and mom_sign < 0):
        value, rule = float(flow_sign), "flow_and_price_agree"
    else:
        value, rule = None, "flow_price_disagree"

    meta: dict[str, Any] = {
        "signal_id": SIGNAL_ID_MF_FLOW_PRICE,
        "signal_version": SIGNAL_VERSION,
        "status": SIGNAL_STATUS,
        "hypothesis_class": CLASS_MULTI_FACTOR,
        "factors": ["margin_flow", "price_momentum"],
        "datasets_required": [
            "markets_margin_interest",
            "equities_bars_daily",
            "markets_calendar",
        ],
        "margin_change": margin_change,
        "momentum": momentum,
        "hold_days": h,
        "rule": rule,
        "filter": filter_meta,
        "formula": (
            f"entry only when sign(margin_change)==sign(mom); sticky hold={h}d"
        ),
        "not_simple_daily_sign": True,
        "not_s4_rehash": True,
        "not_short_confirm_variant": True,
        "note": (
            "Multi-factor flow×price confirm. Parallel near-group to "
            "flow_margin_* (keep; do not merge). Not READY. Not mass."
        ),
    }
    meta.update(_freeze_meta())
    if code is not None:
        meta["code"] = str(code)
    if date is not None:
        meta["date"] = str(date)[:10]
    if as_of is not None:
        meta["as_of"] = str(as_of)
    if extra_meta:
        meta.update(dict(extra_meta))
    return {
        "signal_id": SIGNAL_ID_MF_FLOW_PRICE,
        "version": SIGNAL_VERSION,
        "status": SIGNAL_STATUS,
        "candidate_only": CANDIDATE_ONLY,
        "hypothesis_class": CLASS_MULTI_FACTOR,
        "value": value,
        "code": str(code) if code is not None else None,
        "date": str(date)[:10] if date is not None else None,
        "as_of": as_of,
        "metadata": meta,
    }
