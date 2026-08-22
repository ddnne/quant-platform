"""Macro/rate-family class signals: repo regime, macro_conditioned, rate XS.

Not simple daily sign. Mass / READY / GO closed. No S1–S5 un-reject.
"""

from __future__ import annotations

from typing import Any, Mapping

from .class_signals import (
    CANDIDATE_ONLY,
    CLASS_MACRO_CONDITIONED,
    CLASS_RATE_FACTOR,
    DEFAULT_CURVE_INVERT_THRESHOLD,
    DEFAULT_CURVE_STEEP_THRESHOLD,
    DEFAULT_REPO_CHANGE_EPS,
    DEFAULT_REPO_HIGH_THRESHOLD,
    DEFAULT_REPO_LOW_THRESHOLD,
    MACRO_CONDITIONED_DATASETS,
    MOMENTUM_FEATURE_ID,
    RATE_FACTOR_DATASETS,
    REPO_CURVE_FEATURE_ID,
    REPO_CURVE_LONG_TENOR,
    REPO_CURVE_SHORT_TENOR,
    REPO_RATE_FEATURE_ID,
    SIGNAL_ID_MACRO_CONDITIONED,
    SIGNAL_ID_RATE_CURVE_XS,
    SIGNAL_ID_RATE_LEVEL_XS,
    SIGNAL_STATUS,
    SIGNAL_VERSION,
    TRADING_DAY_FEATURE_ID,
    _freeze_meta,
)
from .class_signals_hold import (
    apply_trading_day_filter,
    sign_from_numeric,
)


def repo_regime_from_level(
    repo_rate: float | None,
    *,
    high_threshold: float = DEFAULT_REPO_HIGH_THRESHOLD,
    low_threshold: float = DEFAULT_REPO_LOW_THRESHOLD,
) -> tuple[str | None, dict[str, Any]]:
    """Label rate level regime: high / mid / low (or None if missing)."""
    if repo_rate is None:
        return None, {"reason": "repo_rate missing"}
    try:
        r = float(repo_rate)
    except (TypeError, ValueError):
        return None, {"reason": "repo_rate not numeric", "raw": repo_rate}
    if r >= float(high_threshold):
        label = "high"
    elif r <= float(low_threshold):
        label = "low"
    else:
        label = "mid"
    return label, {
        "repo_rate": r,
        "high_threshold": float(high_threshold),
        "low_threshold": float(low_threshold),
        "regime": label,
    }


def repo_regime_from_change(
    repo_rate: float | None,
    prev_repo_rate: float | None,
    *,
    eps: float = DEFAULT_REPO_CHANGE_EPS,
) -> tuple[str | None, dict[str, Any]]:
    """Label rate change regime: rate_up / rate_down / flat (or None)."""
    if repo_rate is None or prev_repo_rate is None:
        return None, {
            "reason": "repo_rate or prev missing",
            "repo_rate": repo_rate,
            "prev_repo_rate": prev_repo_rate,
        }
    try:
        cur = float(repo_rate)
        prev = float(prev_repo_rate)
    except (TypeError, ValueError):
        return None, {"reason": "repo_rate not numeric"}
    delta = cur - prev
    if delta > float(eps):
        label = "rate_up"
    elif delta < -float(eps):
        label = "rate_down"
    else:
        label = "flat"
    return label, {
        "repo_rate": cur,
        "prev_repo_rate": prev,
        "delta": delta,
        "eps": float(eps),
        "regime": label,
    }


def condition_signal_on_regime(
    entry_sign: float | None,
    regime: str | None,
    *,
    mode: str = "rate_change",
) -> tuple[float | None, dict[str, Any]]:
    """Apply macro condition to an entry sign (rate_change or rate_level)."""
    m = str(mode or "rate_change").strip().lower()
    if entry_sign is None or regime is None:
        return None, {
            "conditioned": False,
            "reason": "missing entry or regime",
            "mode": m,
            "regime": regime,
            "entry_sign": entry_sign,
        }
    try:
        e = float(entry_sign)
    except (TypeError, ValueError):
        return None, {
            "conditioned": False,
            "reason": "entry not numeric",
            "mode": m,
        }

    if m == "rate_change":
        if regime == "rate_down":
            out = e if e > 0 else (0.0 if e == 0.0 else None)
            rule = "rate_down → long_only"
        elif regime == "rate_up":
            out = e if e < 0 else (0.0 if e == 0.0 else None)
            rule = "rate_up → short_only"
        elif regime == "flat":
            out = None
            rule = "flat → no_trade"
        else:
            out = None
            rule = f"unknown regime {regime!r}"
    elif m == "rate_level":
        if regime == "low":
            out = e if e > 0 else (0.0 if e == 0.0 else None)
            rule = "low_rate → long_only"
        elif regime == "high":
            out = e if e < 0 else (0.0 if e == 0.0 else None)
            rule = "high_rate → short_only"
        elif regime == "mid":
            out = None
            rule = "mid_rate → no_trade"
        else:
            out = None
            rule = f"unknown regime {regime!r}"
    else:
        raise ValueError(f"mode must be rate_change|rate_level, got {mode!r}")

    return out, {
        "conditioned": True,
        "mode": m,
        "regime": regime,
        "entry_sign": e,
        "rule": rule,
        "value": out,
    }


def compute_macro_conditioned_signal(
    *,
    momentum: float | None,
    repo_rate: float | None,
    prev_repo_rate: float | None = None,
    is_trading_day: float | None = 1.0,
    mode: str = "rate_change",
    high_threshold: float = DEFAULT_REPO_HIGH_THRESHOLD,
    low_threshold: float = DEFAULT_REPO_LOW_THRESHOLD,
    code: str | None = None,
    date: str | None = None,
    as_of: str | None = None,
    extra_meta: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Macro-conditioned research signal (repo rate level or change)."""
    m = str(mode or "rate_change").strip().lower()
    raw = sign_from_numeric(momentum)
    filtered, filter_meta = apply_trading_day_filter(raw, is_trading_day)

    if m == "rate_change":
        regime, regime_meta = repo_regime_from_change(
            repo_rate, prev_repo_rate
        )
    else:
        regime, regime_meta = repo_regime_from_level(
            repo_rate,
            high_threshold=high_threshold,
            low_threshold=low_threshold,
        )

    conditioned, cond_meta = condition_signal_on_regime(
        filtered, regime, mode=m
    )

    meta: dict[str, Any] = {
        "signal_id": SIGNAL_ID_MACRO_CONDITIONED,
        "signal_version": SIGNAL_VERSION,
        "status": SIGNAL_STATUS,
        "candidate_only": CANDIDATE_ONLY,
        "hypothesis_class": CLASS_MACRO_CONDITIONED,
        "primary_feature_id": MOMENTUM_FEATURE_ID,
        "macro_feature_id": REPO_RATE_FEATURE_ID,
        "filter_feature_id": TRADING_DAY_FEATURE_ID,
        "datasets_required": list(MACRO_CONDITIONED_DATASETS),
        "momentum": momentum,
        "repo_rate": repo_rate,
        "prev_repo_rate": prev_repo_rate,
        "mode": m,
        "raw_entry_sign": raw,
        "filter": filter_meta,
        "regime": regime_meta,
        "condition": cond_meta,
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
        "signal_id": SIGNAL_ID_MACRO_CONDITIONED,
        "version": SIGNAL_VERSION,
        "status": SIGNAL_STATUS,
        "candidate_only": CANDIDATE_ONLY,
        "hypothesis_class": CLASS_MACRO_CONDITIONED,
        "value": conditioned,
        "code": str(code) if code is not None else None,
        "date": str(date)[:10] if date is not None else None,
        "as_of": as_of,
        "regime": regime,
        "metadata": meta,
    }

def repo_curve_spread(
    short_rate: float | None,
    long_rate: float | None,
) -> tuple[float | None, dict[str, Any]]:
    """Term-structure proxy: long_rate − short_rate (no invent on missing leg)."""
    if short_rate is None or long_rate is None:
        return None, {
            "reason": "missing_leg",
            "short_rate": short_rate,
            "long_rate": long_rate,
        }
    try:
        s = float(short_rate)
        lo = float(long_rate)
    except (TypeError, ValueError):
        return None, {"reason": "non_numeric_leg"}
    spread = lo - s
    return spread, {
        "short_rate": s,
        "long_rate": lo,
        "spread": spread,
        "definition": "long_tenor_rate - short_tenor_rate",
    }


def repo_regime_from_curve(
    spread: float | None,
    *,
    steep_threshold: float = DEFAULT_CURVE_STEEP_THRESHOLD,
    invert_threshold: float = DEFAULT_CURVE_INVERT_THRESHOLD,
) -> tuple[str | None, dict[str, Any]]:
    """Label curve regime: steep / inverted / flat (or None if missing)."""
    if spread is None:
        return None, {"reason": "curve_spread missing"}
    try:
        sp = float(spread)
    except (TypeError, ValueError):
        return None, {"reason": "curve_spread not numeric", "raw": spread}
    if sp > float(steep_threshold):
        label = "steep"
    elif sp < float(invert_threshold):
        label = "inverted"
    else:
        label = "flat"
    return label, {
        "spread": sp,
        "steep_threshold": float(steep_threshold),
        "invert_threshold": float(invert_threshold),
        "regime": label,
    }


def rate_level_risk_adjust_sign(
    cs_sign: float | None,
    regime: str | None,
    *,
    mode: str = "risk_on_off_book",
) -> tuple[float | None, dict[str, Any]]:
    """Transform a cross-section sign by absolute rate-level regime."""
    m = str(mode or "risk_on_off_book").strip().lower()
    if cs_sign is None or regime is None:
        return None, {
            "adjusted": False,
            "reason": "missing cs_sign or regime",
            "mode": m,
            "regime": regime,
            "cs_sign": cs_sign,
        }
    try:
        e = float(cs_sign)
    except (TypeError, ValueError):
        return None, {"adjusted": False, "reason": "cs_sign not numeric", "mode": m}
    if e == 0.0:
        return 0.0, {
            "adjusted": True,
            "mode": m,
            "regime": regime,
            "rule": "cs_flat",
            "value": 0.0,
        }
    if m != "risk_on_off_book":
        raise ValueError(f"mode must be risk_on_off_book, got {mode!r}")
    if regime == "low":
        out, rule = e, "low_rate → risk_on keep CS"
    elif regime == "high":
        out, rule = -e, "high_rate → risk_off reverse CS"
    elif regime == "mid":
        out, rule = None, "mid_rate → no_trade"
    else:
        out, rule = None, f"unknown regime {regime!r}"
    return out, {
        "adjusted": True,
        "mode": m,
        "regime": regime,
        "cs_sign": e,
        "rule": rule,
        "value": out,
    }


def rate_curve_risk_adjust_sign(
    cs_sign: float | None,
    regime: str | None,
    *,
    mode: str = "steep_risk_on",
) -> tuple[float | None, dict[str, Any]]:
    """Transform CS sign by repo curve-shape regime."""
    m = str(mode or "steep_risk_on").strip().lower()
    if cs_sign is None or regime is None:
        return None, {
            "adjusted": False,
            "reason": "missing cs_sign or curve regime",
            "mode": m,
            "regime": regime,
            "cs_sign": cs_sign,
        }
    try:
        e = float(cs_sign)
    except (TypeError, ValueError):
        return None, {"adjusted": False, "reason": "cs_sign not numeric", "mode": m}
    if e == 0.0:
        return 0.0, {
            "adjusted": True,
            "mode": m,
            "regime": regime,
            "rule": "cs_flat",
            "value": 0.0,
        }
    if m != "steep_risk_on":
        raise ValueError(f"mode must be steep_risk_on, got {mode!r}")
    if regime == "steep":
        out, rule = e, "steep_curve → risk_on keep CS"
    elif regime == "inverted":
        out, rule = -e, "inverted_curve → risk_off reverse CS"
    elif regime == "flat":
        out, rule = None, "flat_curve → no_trade"
    else:
        out, rule = None, f"unknown regime {regime!r}"
    return out, {
        "adjusted": True,
        "mode": m,
        "regime": regime,
        "cs_sign": e,
        "rule": rule,
        "value": out,
    }


def compute_rate_level_xs_signal(
    *,
    cs_sign: float | None,
    repo_rate: float | None,
    high_threshold: float = DEFAULT_REPO_HIGH_THRESHOLD,
    low_threshold: float = DEFAULT_REPO_LOW_THRESHOLD,
    code: str | None = None,
    date: str | None = None,
    as_of: str | None = None,
    extra_meta: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Absolute rate-level factor × cross-section book (risk-on/off)."""
    regime, regime_meta = repo_regime_from_level(
        repo_rate,
        high_threshold=high_threshold,
        low_threshold=low_threshold,
    )
    adjusted, adj_meta = rate_level_risk_adjust_sign(cs_sign, regime)
    meta: dict[str, Any] = {
        "signal_id": SIGNAL_ID_RATE_LEVEL_XS,
        "signal_version": SIGNAL_VERSION,
        "status": SIGNAL_STATUS,
        "hypothesis_class": CLASS_RATE_FACTOR,
        "primary_feature_id": REPO_RATE_FEATURE_ID,
        "secondary_feature_id": MOMENTUM_FEATURE_ID,
        "datasets_required": list(RATE_FACTOR_DATASETS),
        "cs_sign": cs_sign,
        "repo_rate": repo_rate,
        "regime": regime_meta,
        "adjust": adj_meta,
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
        "signal_id": SIGNAL_ID_RATE_LEVEL_XS,
        "version": SIGNAL_VERSION,
        "status": SIGNAL_STATUS,
        "candidate_only": CANDIDATE_ONLY,
        "hypothesis_class": CLASS_RATE_FACTOR,
        "value": adjusted,
        "regime": regime,
        "code": str(code) if code is not None else None,
        "date": str(date)[:10] if date is not None else None,
        "as_of": as_of,
        "metadata": meta,
    }


def compute_rate_curve_xs_signal(
    *,
    cs_sign: float | None,
    short_rate: float | None,
    long_rate: float | None,
    steep_threshold: float = DEFAULT_CURVE_STEEP_THRESHOLD,
    invert_threshold: float = DEFAULT_CURVE_INVERT_THRESHOLD,
    code: str | None = None,
    date: str | None = None,
    as_of: str | None = None,
    extra_meta: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Repo curve-shape factor × cross-section book."""
    spread, spread_meta = repo_curve_spread(short_rate, long_rate)
    regime, regime_meta = repo_regime_from_curve(
        spread,
        steep_threshold=steep_threshold,
        invert_threshold=invert_threshold,
    )
    adjusted, adj_meta = rate_curve_risk_adjust_sign(cs_sign, regime)
    meta: dict[str, Any] = {
        "signal_id": SIGNAL_ID_RATE_CURVE_XS,
        "signal_version": SIGNAL_VERSION,
        "status": SIGNAL_STATUS,
        "hypothesis_class": CLASS_RATE_FACTOR,
        "primary_feature_id": REPO_CURVE_FEATURE_ID,
        "secondary_feature_id": MOMENTUM_FEATURE_ID,
        "datasets_required": list(RATE_FACTOR_DATASETS),
        "curve_definition": {
            "short_tenor": REPO_CURVE_SHORT_TENOR,
            "long_tenor": REPO_CURVE_LONG_TENOR,
            "spread": "long - short",
        },
        "cs_sign": cs_sign,
        "spread": spread_meta,
        "regime": regime_meta,
        "adjust": adj_meta,
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
        "signal_id": SIGNAL_ID_RATE_CURVE_XS,
        "version": SIGNAL_VERSION,
        "status": SIGNAL_STATUS,
        "candidate_only": CANDIDATE_ONLY,
        "hypothesis_class": CLASS_RATE_FACTOR,
        "value": adjusted,
        "regime": regime,
        "spread": spread,
        "code": str(code) if code is not None else None,
        "date": str(date)[:10] if date is not None else None,
        "as_of": as_of,
        "metadata": meta,
    }
