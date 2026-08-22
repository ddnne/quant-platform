"""Hold-family class signals: sticky hold, multi_day_hold, trading-day filter.

Not simple daily sign. Mass / READY / GO closed. No S1–S5 un-reject.
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from .class_signals import (
    CANDIDATE_ONLY,
    CLASS_MULTI_DAY_HOLD,
    DEFAULT_HOLD_DAYS,
    MOMENTUM_FEATURE_ID,
    SIGNAL_ID_MULTI_DAY_HOLD,
    SIGNAL_STATUS,
    SIGNAL_VERSION,
    SUPPORTED_HOLD_DAYS,
    TRADING_DAY_FEATURE_ID,
    _freeze_meta,
)


def sign_from_numeric(x: float | None) -> float | None:
    """Map numeric → +1 / 0 / −1, or None if missing."""
    if x is None:
        return None
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    if v > 0:
        return 1.0
    if v < 0:
        return -1.0
    return 0.0


def apply_trading_day_filter(
    signal_value: float | None,
    is_trading_day: float | None,
) -> tuple[float | None, dict[str, Any]]:
    """Null signal on non-trading / missing calendar."""
    if is_trading_day is None:
        return None, {
            "filter": TRADING_DAY_FEATURE_ID,
            "passed": False,
            "reason": "is_trading_day missing",
        }
    try:
        td = float(is_trading_day)
    except (TypeError, ValueError):
        return None, {
            "filter": TRADING_DAY_FEATURE_ID,
            "passed": False,
            "reason": "is_trading_day not numeric",
            "raw": is_trading_day,
        }
    if td != 1.0:
        return None, {
            "filter": TRADING_DAY_FEATURE_ID,
            "passed": False,
            "reason": "non_trading_day",
            "is_trading_day": td,
        }
    return signal_value, {
        "filter": TRADING_DAY_FEATURE_ID,
        "passed": True,
        "is_trading_day": td,
    }


def apply_sticky_hold(
    daily_entry_signs: Sequence[Any],
    *,
    hold_days: int = DEFAULT_HOLD_DAYS,
    rebalance_mode: str = "fixed_horizon",
) -> list[float | None]:
    """Convert daily entry signs into multi-day held positions.

    Parameters
    ----------
    daily_entry_signs:
        Chronological sequence of entry signs (+1/0/−1/None) — typically
        ``sign(momentum_n)`` each day.
    hold_days:
        Hold horizon in sessions (5 / 10 / 20). Must be >= 1.
    rebalance_mode:
        * ``fixed_horizon`` — rebalance every ``hold_days`` sessions only
          (position constant between rebalance days).
        * ``min_hold`` — allow rebalance on sign change only after
          ``hold_days`` sessions held (sticky min-hold).

    Returns
    -------
    list of held position signs (same length). None days stay flat/missing
    until a valid rebalance entry exists.
    """
    h = int(hold_days)
    if h < 1:
        raise ValueError(f"hold_days must be >= 1, got {hold_days!r}")
    mode = str(rebalance_mode or "fixed_horizon").strip().lower()
    if mode not in ("fixed_horizon", "min_hold"):
        raise ValueError(
            f"rebalance_mode must be fixed_horizon|min_hold, got {rebalance_mode!r}"
        )

    n = len(daily_entry_signs)
    out: list[float | None] = [None] * n
    if n == 0:
        return out

    held: float | None = None
    held_for = 0
    days_since_rebalance = 0

    for i, raw in enumerate(daily_entry_signs):
        entry = sign_from_numeric(raw if raw is not None else None)
        # Treat flat 0 as "no entry" for sticky hold (do not force flat mid-hold
        # under fixed_horizon — keep prior held).
        if mode == "fixed_horizon":
            if i == 0 or days_since_rebalance >= h:
                if entry is not None and entry != 0.0:
                    held = entry
                elif entry == 0.0:
                    held = 0.0
                # if entry is None, keep prior held (or None)
                days_since_rebalance = 1
            else:
                days_since_rebalance += 1
            out[i] = held
        else:  # min_hold
            if held is None:
                if entry is not None and entry != 0.0:
                    held = entry
                    held_for = 1
                elif entry == 0.0:
                    held = 0.0
                    held_for = 1
                out[i] = held
                continue
            held_for += 1
            if held_for >= h and entry is not None and entry != held:
                # allow flip / flat after min hold
                held = entry
                held_for = 1
            out[i] = held

    return out


def multi_day_forward_return(
    closes: Sequence[float | None],
    *,
    hold_days: int,
    entry_index: int,
) -> float | None:
    """Close-to-close return from ``entry_index`` over ``hold_days`` sessions.

    ``R = close[t+hold_days] / close[t] - 1`` when both ends present.
    """
    h = int(hold_days)
    if h < 1:
        raise ValueError(f"hold_days must be >= 1, got {hold_days!r}")
    i = int(entry_index)
    j = i + h
    if i < 0 or j >= len(closes):
        return None
    c0 = closes[i]
    c1 = closes[j]
    if c0 is None or c1 is None:
        return None
    try:
        a = float(c0)
        b = float(c1)
    except (TypeError, ValueError):
        return None
    if a == 0.0:
        return None
    return (b / a) - 1.0


def amortized_one_way_cost(
    one_way_cost: float,
    hold_days: int,
) -> float:
    """Research illustration: one-way cost amortized over hold horizon."""
    h = int(hold_days)
    if h < 1:
        raise ValueError(f"hold_days must be >= 1, got {hold_days!r}")
    return float(one_way_cost) / float(h)


def compute_multi_day_hold_signal(
    *,
    momentum: float | None,
    is_trading_day: float | None = 1.0,
    hold_days: int = DEFAULT_HOLD_DAYS,
    momentum_n: int | None = None,
    code: str | None = None,
    date: str | None = None,
    as_of: str | None = None,
    extra_meta: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Single-day entry observation for multi_day_hold (sticky hold is separate)."""
    h = int(hold_days)
    if h not in SUPPORTED_HOLD_DAYS and h < 1:
        raise ValueError(f"hold_days invalid: {hold_days!r}")
    n_mom = int(momentum_n) if momentum_n is not None else h
    raw = sign_from_numeric(momentum)
    filtered, filter_meta = apply_trading_day_filter(raw, is_trading_day)
    meta: dict[str, Any] = {
        "signal_id": SIGNAL_ID_MULTI_DAY_HOLD,
        "signal_version": SIGNAL_VERSION,
        "status": SIGNAL_STATUS,
        "candidate_only": CANDIDATE_ONLY,
        "hypothesis_class": CLASS_MULTI_DAY_HOLD,
        "primary_feature_id": MOMENTUM_FEATURE_ID,
        "filter_feature_id": TRADING_DAY_FEATURE_ID,
        "momentum": momentum,
        "momentum_n": n_mom,
        "hold_days": h,
        "raw_entry_sign": raw,
        "filter": filter_meta,
        "not_simple_daily_sign": True,
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
        "signal_id": SIGNAL_ID_MULTI_DAY_HOLD,
        "version": SIGNAL_VERSION,
        "status": SIGNAL_STATUS,
        "candidate_only": CANDIDATE_ONLY,
        "hypothesis_class": CLASS_MULTI_DAY_HOLD,
        "value": filtered,
        "code": str(code) if code is not None else None,
        "date": str(date)[:10] if date is not None else None,
        "as_of": as_of,
        "hold_days": h,
        "metadata": meta,
    }


def _as_float_or_none(x: Any) -> float | None:
    if x is None or x == "":
        return None
    try:
        return float(x)
    except (TypeError, ValueError):
        return None
