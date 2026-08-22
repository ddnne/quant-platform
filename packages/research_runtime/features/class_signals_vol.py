"""Vol-family class signals: nky realized vol + opt225 compute wrappers.

Not simple daily sign. Mass / READY / GO closed. No S1–S5 un-reject.
"""

from __future__ import annotations

from typing import Any, Mapping

from .class_signals import (
    CANDIDATE_ONLY,
    CLASS_INDEX_VOL_REGIME,
    CLASS_OPTIONS_VOL_REGIME,
    DEFAULT_NKY_VOL_COMPRESS_RATIO,
    DEFAULT_NKY_VOL_EXPAND_RATIO,
    DEFAULT_NKY_VOL_HIGH_THRESHOLD,
    DEFAULT_NKY_VOL_LOW_THRESHOLD,
    DEFAULT_OPT225_BASEVOL_DELTA_HIGH_THRESHOLD,
    DEFAULT_OPT225_BASEVOL_DELTA_LOW_THRESHOLD,
    DEFAULT_OPT225_CM_TERM_HIGH_THRESHOLD,
    DEFAULT_OPT225_CM_TERM_LOW_THRESHOLD,
    DEFAULT_OPT225_SKEW_HIGH_THRESHOLD,
    DEFAULT_OPT225_SKEW_LOW_THRESHOLD,
    DEFAULT_OPT225_SPREAD_HIGH_THRESHOLD,
    DEFAULT_OPT225_SPREAD_LOW_THRESHOLD,
    DEFAULT_OPT225_VOL_COMPRESS_RATIO,
    DEFAULT_OPT225_VOL_EXPAND_RATIO,
    DEFAULT_OPT225_VOL_HIGH_THRESHOLD,
    DEFAULT_OPT225_VOL_LOW_THRESHOLD,
    INDEX_VOL_REGIME_DATASETS,
    MOMENTUM_FEATURE_ID,
    NKY_VOL_ABS_FEATURE_ID,
    NKY_VOL_TERM_LEVELS_FEATURE_ID,
    NKY_VOL_TERM_RATIO_FEATURE_ID,
    OPT225_ATM_IV_FEATURE_ID,
    OPT225_BASEVOL_DELTA_CONVENTION,
    OPT225_BASEVOL_DELTA_FEATURE_ID,
    OPT225_BASEVOL_FEATURE_ID,
    OPT225_CANONICAL_LEVEL,
    OPT225_CM_TERM_CONVENTION,
    OPT225_CM_TERM_FEATURE_ID,
    OPT225_SKEW_CONVENTION,
    OPT225_SKEW_FEATURE_ID,
    OPT225_SPREAD_CONVENTION,
    OPT225_SPREAD_FEATURE_ID,
    OPTIONS_VOL_REGIME_DATASETS,
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
    SIGNAL_STATUS,
    SIGNAL_VERSION,
    _freeze_meta,
)


def nky_vol_regime_from_abs_level(
    vol_level: float | None,
    *,
    high_threshold: float = DEFAULT_NKY_VOL_HIGH_THRESHOLD,
    low_threshold: float = DEFAULT_NKY_VOL_LOW_THRESHOLD,
) -> tuple[str | None, dict[str, Any]]:
    """Label index vol absolute-level regime: high / mid / low."""
    if vol_level is None:
        return None, {"reason": "vol_level missing"}
    try:
        v = float(vol_level)
    except (TypeError, ValueError):
        return None, {"reason": "vol_level not numeric", "raw": vol_level}
    if v != v:  # NaN — signed series (spread / ΔBaseVol / CM-term) may be < 0
        return None, {"reason": "vol_level invalid", "raw": v}
    if v >= float(high_threshold):
        label = "high"
    elif v <= float(low_threshold):
        label = "low"
    else:
        label = "mid"
    return label, {
        "vol_level": v,
        "high_threshold": float(high_threshold),
        "low_threshold": float(low_threshold),
        "regime": label,
    }


def nky_vol_regime_from_term_levels(
    short_vol: float | None,
    long_vol: float | None,
    *,
    high_threshold: float = DEFAULT_NKY_VOL_HIGH_THRESHOLD,
    low_threshold: float = DEFAULT_NKY_VOL_LOW_THRESHOLD,
) -> tuple[str | None, dict[str, Any]]:
    """Dual short/long absolute levels: agree high/low → regime; else mid/flat."""
    if short_vol is None or long_vol is None:
        return None, {
            "reason": "missing short or long vol",
            "short_vol": short_vol,
            "long_vol": long_vol,
        }
    s_lab, s_meta = nky_vol_regime_from_abs_level(
        short_vol, high_threshold=high_threshold, low_threshold=low_threshold
    )
    l_lab, l_meta = nky_vol_regime_from_abs_level(
        long_vol, high_threshold=high_threshold, low_threshold=low_threshold
    )
    if s_lab is None or l_lab is None:
        return None, {
            "reason": "leg regime missing",
            "short": s_meta,
            "long": l_meta,
        }
    if s_lab == "high" and l_lab == "high":
        label = "high"
    elif s_lab == "low" and l_lab == "low":
        label = "low"
    else:
        label = "mid"
    return label, {
        "short_vol": float(short_vol),
        "long_vol": float(long_vol),
        "short_regime": s_lab,
        "long_regime": l_lab,
        "high_threshold": float(high_threshold),
        "low_threshold": float(low_threshold),
        "regime": label,
        "agreement": s_lab == l_lab and s_lab in {"high", "low"},
    }


def nky_vol_regime_from_term_ratio(
    short_vol: float | None,
    long_vol: float | None,
    *,
    expand_ratio: float = DEFAULT_NKY_VOL_EXPAND_RATIO,
    compress_ratio: float = DEFAULT_NKY_VOL_COMPRESS_RATIO,
) -> tuple[str | None, dict[str, Any]]:
    """Term-structure of realized vol: short/long ratio → expand / compress / mid."""
    if short_vol is None or long_vol is None:
        return None, {
            "reason": "missing short or long vol",
            "short_vol": short_vol,
            "long_vol": long_vol,
        }
    try:
        s = float(short_vol)
        lo = float(long_vol)
    except (TypeError, ValueError):
        return None, {"reason": "non_numeric_vol"}
    if lo <= 1e-12 or s < 0:
        return None, {"reason": "invalid_vol_for_ratio", "short": s, "long": lo}
    ratio = s / lo
    if ratio >= float(expand_ratio):
        label = "expanding"
    elif ratio <= float(compress_ratio):
        label = "compressing"
    else:
        label = "mid"
    return label, {
        "short_vol": s,
        "long_vol": lo,
        "ratio": ratio,
        "expand_ratio": float(expand_ratio),
        "compress_ratio": float(compress_ratio),
        "regime": label,
    }


def nky_vol_risk_adjust_sign(
    cs_sign: float | None,
    regime: str | None,
    *,
    mode: str = "vol_risk_on_off",
) -> tuple[float | None, dict[str, Any]]:
    """Transform CS sign by index-vol regime (keep / reverse / flat)."""
    m = str(mode or "vol_risk_on_off").strip().lower()
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
    reg = str(regime).strip().lower()
    if m == "vol_term_ratio":
        if reg == "compressing":
            out, rule = e, "vol compressing → risk_on keep CS"
        elif reg == "expanding":
            out, rule = -e, "vol expanding → risk_off reverse CS"
        elif reg == "mid":
            out, rule = None, "vol ratio mid → no_trade"
        else:
            out, rule = None, f"unknown vol-ratio regime {reg!r}"
    else:
        # vol_risk_on_off for abs level + term levels agreement
        if reg == "low":
            out, rule = e, "low index vol → risk_on keep CS"
        elif reg == "high":
            out, rule = -e, "high index vol → risk_off reverse CS"
        elif reg == "mid":
            out, rule = None, "mid index vol → no_trade"
        else:
            out, rule = None, f"unknown vol-level regime {reg!r}"
    return out, {
        "adjusted": True,
        "mode": m,
        "regime": reg,
        "cs_sign": e,
        "rule": rule,
        "value": out,
    }


def compute_nky_vol_abs_level_signal(
    *,
    cs_sign: float | None,
    vol_level: float | None,
    high_threshold: float = DEFAULT_NKY_VOL_HIGH_THRESHOLD,
    low_threshold: float = DEFAULT_NKY_VOL_LOW_THRESHOLD,
    code: str | None = None,
    date: str | None = None,
    as_of: str | None = None,
    extra_meta: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Absolute Nikkei/index realized-vol level × CS risk-on/off book."""
    regime, regime_meta = nky_vol_regime_from_abs_level(
        vol_level,
        high_threshold=high_threshold,
        low_threshold=low_threshold,
    )
    adjusted, adj_meta = nky_vol_risk_adjust_sign(
        cs_sign, regime, mode="vol_risk_on_off"
    )
    meta: dict[str, Any] = {
        "signal_id": SIGNAL_ID_NKY_VOL_ABS_LEVEL,
        "signal_version": SIGNAL_VERSION,
        "status": SIGNAL_STATUS,
        "hypothesis_class": CLASS_INDEX_VOL_REGIME,
        "primary_feature_id": NKY_VOL_ABS_FEATURE_ID,
        "secondary_feature_id": MOMENTUM_FEATURE_ID,
        "datasets_required": list(INDEX_VOL_REGIME_DATASETS),
        "cs_sign": cs_sign,
        "vol_level": vol_level,
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
        "signal_id": SIGNAL_ID_NKY_VOL_ABS_LEVEL,
        "version": SIGNAL_VERSION,
        "status": SIGNAL_STATUS,
        "candidate_only": CANDIDATE_ONLY,
        "hypothesis_class": CLASS_INDEX_VOL_REGIME,
        "value": adjusted,
        "regime": regime,
        "code": str(code) if code is not None else None,
        "date": str(date)[:10] if date is not None else None,
        "as_of": as_of,
        "metadata": meta,
    }


def compute_nky_vol_term_levels_signal(
    *,
    cs_sign: float | None,
    short_vol: float | None,
    long_vol: float | None,
    high_threshold: float = DEFAULT_NKY_VOL_HIGH_THRESHOLD,
    low_threshold: float = DEFAULT_NKY_VOL_LOW_THRESHOLD,
    code: str | None = None,
    date: str | None = None,
    as_of: str | None = None,
    extra_meta: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Short+long absolute RV levels (agreement) × CS risk-on/off book."""
    regime, regime_meta = nky_vol_regime_from_term_levels(
        short_vol,
        long_vol,
        high_threshold=high_threshold,
        low_threshold=low_threshold,
    )
    adjusted, adj_meta = nky_vol_risk_adjust_sign(
        cs_sign, regime, mode="vol_risk_on_off"
    )
    meta: dict[str, Any] = {
        "signal_id": SIGNAL_ID_NKY_VOL_TERM_LEVELS,
        "signal_version": SIGNAL_VERSION,
        "status": SIGNAL_STATUS,
        "hypothesis_class": CLASS_INDEX_VOL_REGIME,
        "primary_feature_id": NKY_VOL_TERM_LEVELS_FEATURE_ID,
        "secondary_feature_id": MOMENTUM_FEATURE_ID,
        "datasets_required": list(INDEX_VOL_REGIME_DATASETS),
        "cs_sign": cs_sign,
        "short_vol": short_vol,
        "long_vol": long_vol,
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
        "signal_id": SIGNAL_ID_NKY_VOL_TERM_LEVELS,
        "version": SIGNAL_VERSION,
        "status": SIGNAL_STATUS,
        "candidate_only": CANDIDATE_ONLY,
        "hypothesis_class": CLASS_INDEX_VOL_REGIME,
        "value": adjusted,
        "regime": regime,
        "code": str(code) if code is not None else None,
        "date": str(date)[:10] if date is not None else None,
        "as_of": as_of,
        "metadata": meta,
    }


def compute_nky_vol_term_ratio_signal(
    *,
    cs_sign: float | None,
    short_vol: float | None,
    long_vol: float | None,
    expand_ratio: float = DEFAULT_NKY_VOL_EXPAND_RATIO,
    compress_ratio: float = DEFAULT_NKY_VOL_COMPRESS_RATIO,
    code: str | None = None,
    date: str | None = None,
    as_of: str | None = None,
    extra_meta: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Short/long realized-vol ratio × CS risk-on/off book."""
    regime, regime_meta = nky_vol_regime_from_term_ratio(
        short_vol,
        long_vol,
        expand_ratio=expand_ratio,
        compress_ratio=compress_ratio,
    )
    adjusted, adj_meta = nky_vol_risk_adjust_sign(
        cs_sign, regime, mode="vol_term_ratio"
    )
    meta: dict[str, Any] = {
        "signal_id": SIGNAL_ID_NKY_VOL_TERM_RATIO,
        "signal_version": SIGNAL_VERSION,
        "status": SIGNAL_STATUS,
        "hypothesis_class": CLASS_INDEX_VOL_REGIME,
        "primary_feature_id": NKY_VOL_TERM_RATIO_FEATURE_ID,
        "secondary_feature_id": MOMENTUM_FEATURE_ID,
        "datasets_required": list(INDEX_VOL_REGIME_DATASETS),
        "cs_sign": cs_sign,
        "short_vol": short_vol,
        "long_vol": long_vol,
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
        "signal_id": SIGNAL_ID_NKY_VOL_TERM_RATIO,
        "version": SIGNAL_VERSION,
        "status": SIGNAL_STATUS,
        "candidate_only": CANDIDATE_ONLY,
        "hypothesis_class": CLASS_INDEX_VOL_REGIME,
        "value": adjusted,
        "regime": regime,
        "code": str(code) if code is not None else None,
        "date": str(date)[:10] if date is not None else None,
        "as_of": as_of,
        "metadata": meta,
    }


def compute_opt225_vol_signal(
    *,
    mode: str,
    cs_sign: float | None,
    vol_level: float | None = None,
    short_vol: float | None = None,
    long_vol: float | None = None,
    high_threshold: float = DEFAULT_OPT225_VOL_HIGH_THRESHOLD,
    low_threshold: float = DEFAULT_OPT225_VOL_LOW_THRESHOLD,
    expand_ratio: float = DEFAULT_OPT225_VOL_EXPAND_RATIO,
    compress_ratio: float = DEFAULT_OPT225_VOL_COMPRESS_RATIO,
    signal_id: str = SIGNAL_ID_OPT225_BASEVOL_ABS,
    feature_id: str = OPT225_BASEVOL_FEATURE_ID,
    series_kind: str = "basevol",
    code: str | None = None,
    date: str | None = None,
    as_of: str | None = None,
    extra_meta: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Generic options_225 vol-regime × CS risk-on/off signal."""
    m = str(mode or "abs_level").strip().lower()
    if m in {"term_ratio", "opt225_term_ratio"}:
        regime, regime_meta = nky_vol_regime_from_term_ratio(
            short_vol,
            long_vol,
            expand_ratio=expand_ratio,
            compress_ratio=compress_ratio,
        )
        adjusted, adj_meta = nky_vol_risk_adjust_sign(
            cs_sign, regime, mode="vol_term_ratio"
        )
    elif m in {"term_levels", "opt225_term_levels"}:
        regime, regime_meta = nky_vol_regime_from_term_levels(
            short_vol,
            long_vol,
            high_threshold=high_threshold,
            low_threshold=low_threshold,
        )
        adjusted, adj_meta = nky_vol_risk_adjust_sign(
            cs_sign, regime, mode="vol_risk_on_off"
        )
    else:
        regime, regime_meta = nky_vol_regime_from_abs_level(
            vol_level,
            high_threshold=high_threshold,
            low_threshold=low_threshold,
        )
        adjusted, adj_meta = nky_vol_risk_adjust_sign(
            cs_sign, regime, mode="vol_risk_on_off"
        )
    meta: dict[str, Any] = {
        "signal_id": signal_id,
        "signal_version": SIGNAL_VERSION,
        "status": SIGNAL_STATUS,
        "hypothesis_class": CLASS_OPTIONS_VOL_REGIME,
        "primary_feature_id": feature_id,
        "secondary_feature_id": MOMENTUM_FEATURE_ID,
        "datasets_required": list(OPTIONS_VOL_REGIME_DATASETS),
        "series_kind": series_kind,
        "mode": m,
        "units": "percent_vol_points",
        "spread_convention": OPT225_SPREAD_CONVENTION,
        "cs_sign": cs_sign,
        "vol_level": vol_level,
        "short_vol": short_vol,
        "long_vol": long_vol,
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
        "signal_id": signal_id,
        "version": SIGNAL_VERSION,
        "status": SIGNAL_STATUS,
        "candidate_only": CANDIDATE_ONLY,
        "hypothesis_class": CLASS_OPTIONS_VOL_REGIME,
        "value": adjusted,
        "regime": regime,
        "code": str(code) if code is not None else None,
        "date": str(date)[:10] if date is not None else None,
        "as_of": as_of,
        "metadata": meta,
    }


def compute_opt225_basevol_abs_level_signal(**kwargs: Any) -> dict[str, Any]:
    return compute_opt225_vol_signal(
        mode="abs_level",
        signal_id=SIGNAL_ID_OPT225_BASEVOL_ABS,
        feature_id=OPT225_BASEVOL_FEATURE_ID,
        series_kind="basevol",
        **kwargs,
    )


def compute_opt225_basevol_term_levels_signal(**kwargs: Any) -> dict[str, Any]:
    return compute_opt225_vol_signal(
        mode="term_levels",
        signal_id=SIGNAL_ID_OPT225_BASEVOL_TERM_LEVELS,
        feature_id=OPT225_BASEVOL_FEATURE_ID,
        series_kind="basevol",
        **kwargs,
    )


def compute_opt225_basevol_term_ratio_signal(**kwargs: Any) -> dict[str, Any]:
    return compute_opt225_vol_signal(
        mode="term_ratio",
        signal_id=SIGNAL_ID_OPT225_BASEVOL_TERM_RATIO,
        feature_id=OPT225_BASEVOL_FEATURE_ID,
        series_kind="basevol",
        **kwargs,
    )


def compute_opt225_atm_iv_abs_level_signal(**kwargs: Any) -> dict[str, Any]:
    return compute_opt225_vol_signal(
        mode="abs_level",
        signal_id=SIGNAL_ID_OPT225_ATM_IV_ABS,
        feature_id=OPT225_ATM_IV_FEATURE_ID,
        series_kind="atm_iv",
        high_threshold=kwargs.pop("high_threshold", 25.0),
        low_threshold=kwargs.pop("low_threshold", 12.0),
        **kwargs,
    )


def compute_opt225_atm_iv_term_levels_signal(**kwargs: Any) -> dict[str, Any]:
    return compute_opt225_vol_signal(
        mode="term_levels",
        signal_id=SIGNAL_ID_OPT225_ATM_IV_TERM_LEVELS,
        feature_id=OPT225_ATM_IV_FEATURE_ID,
        series_kind="atm_iv",
        high_threshold=kwargs.pop("high_threshold", 25.0),
        low_threshold=kwargs.pop("low_threshold", 12.0),
        **kwargs,
    )


def compute_opt225_atm_iv_term_ratio_signal(**kwargs: Any) -> dict[str, Any]:
    return compute_opt225_vol_signal(
        mode="term_ratio",
        signal_id=SIGNAL_ID_OPT225_ATM_IV_TERM_RATIO,
        feature_id=OPT225_ATM_IV_FEATURE_ID,
        series_kind="atm_iv",
        **kwargs,
    )


def compute_opt225_iv_base_spread_abs_signal(**kwargs: Any) -> dict[str, Any]:
    return compute_opt225_vol_signal(
        mode="abs_level",
        signal_id=SIGNAL_ID_OPT225_SPREAD_ABS,
        feature_id=OPT225_SPREAD_FEATURE_ID,
        series_kind="spread",
        high_threshold=kwargs.pop(
            "high_threshold", DEFAULT_OPT225_SPREAD_HIGH_THRESHOLD
        ),
        low_threshold=kwargs.pop(
            "low_threshold", DEFAULT_OPT225_SPREAD_LOW_THRESHOLD
        ),
        **kwargs,
    )


def compute_opt225_iv_base_spread_change_signal(**kwargs: Any) -> dict[str, Any]:
    return compute_opt225_vol_signal(
        mode="abs_level",
        signal_id=SIGNAL_ID_OPT225_SPREAD_CHANGE,
        feature_id=OPT225_SPREAD_FEATURE_ID,
        series_kind="spread_change",
        high_threshold=kwargs.pop("high_threshold", 0.5),
        low_threshold=kwargs.pop("low_threshold", -0.5),
        **kwargs,
    )


def compute_opt225_skew_abs_level_signal(**kwargs: Any) -> dict[str, Any]:
    """95% put skew abs × CS (no invent)."""
    return compute_opt225_vol_signal(
        mode="abs_level",
        signal_id=SIGNAL_ID_OPT225_SKEW_ABS,
        feature_id=OPT225_SKEW_FEATURE_ID,
        series_kind="skew",
        high_threshold=kwargs.pop(
            "high_threshold", DEFAULT_OPT225_SKEW_HIGH_THRESHOLD
        ),
        low_threshold=kwargs.pop(
            "low_threshold", DEFAULT_OPT225_SKEW_LOW_THRESHOLD
        ),
        extra_meta={
            "skew_convention": OPT225_SKEW_CONVENTION,
            "invent_strike": False,
            **dict(kwargs.pop("extra_meta", None) or {}),
        },
        **kwargs,
    )


def compute_opt225_cm_term_abs_level_signal(**kwargs: Any) -> dict[str, Any]:
    """Near−next CM ATM-ish term abs × CS."""
    return compute_opt225_vol_signal(
        mode="abs_level",
        signal_id=SIGNAL_ID_OPT225_CM_TERM_ABS,
        feature_id=OPT225_CM_TERM_FEATURE_ID,
        series_kind="cm_term",
        high_threshold=kwargs.pop(
            "high_threshold", DEFAULT_OPT225_CM_TERM_HIGH_THRESHOLD
        ),
        low_threshold=kwargs.pop(
            "low_threshold", DEFAULT_OPT225_CM_TERM_LOW_THRESHOLD
        ),
        extra_meta={
            "cm_term_convention": OPT225_CM_TERM_CONVENTION,
            "invent_strike": False,
            **dict(kwargs.pop("extra_meta", None) or {}),
        },
        **kwargs,
    )


def compute_opt225_basevol_delta_abs_signal(**kwargs: Any) -> dict[str, Any]:
    """BaseVol[t]−BaseVol[t-1] abs × CS."""
    return compute_opt225_vol_signal(
        mode="abs_level",
        signal_id=SIGNAL_ID_OPT225_BASEVOL_DELTA_ABS,
        feature_id=OPT225_BASEVOL_DELTA_FEATURE_ID,
        series_kind="basevol_delta",
        high_threshold=kwargs.pop(
            "high_threshold", DEFAULT_OPT225_BASEVOL_DELTA_HIGH_THRESHOLD
        ),
        low_threshold=kwargs.pop(
            "low_threshold", DEFAULT_OPT225_BASEVOL_DELTA_LOW_THRESHOLD
        ),
        extra_meta={
            "basevol_delta_convention": OPT225_BASEVOL_DELTA_CONVENTION,
            "canonical_level": OPT225_CANONICAL_LEVEL,
            **dict(kwargs.pop("extra_meta", None) or {}),
        },
        **kwargs,
    )
