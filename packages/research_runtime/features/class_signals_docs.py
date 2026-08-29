"""Class-signal catalog dumps (definitions + public document).

Not simple daily sign. Mass / READY / GO closed. No S1–S5 un-reject.
"""

from __future__ import annotations

from typing import Any

from .research_freezes import S1_S5_UNREJECT
from .class_signals import (
    CANDIDATE_ONLY,
    CLASS_CROSS_SECTION_RELATIVE,
    CLASS_EVENT_POST,
    CLASS_FLOW_DEMAND,
    CLASS_FUNDAMENTALS_PRICE,
    CLASS_INDEX_VOL_REGIME,
    CLASS_MACRO_CONDITIONED,
    CLASS_MULTI_DAY_HOLD,
    CLASS_MULTI_FACTOR,
    CLASS_OPTIONS_VOL_REGIME,
    CLASS_RATE_FACTOR,
    CLASS_SIGNALS_VERSION,
    CLASS_SIGNALS_WAVE,
    DEFAULT_EVENT_POST_HOLD_DAYS,
    DEFAULT_FLOW_HOLD_DAYS,
    DEFAULT_FUND_HOLD_DAYS,
    DEFAULT_HOLD_DAYS,
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
    SIGNAL_ID_OPT225_CM_TERM_RATIO,
    SIGNAL_ID_OPT225_SKEW_ABS,
    SIGNAL_ID_OPT225_SPREAD_ABS,
    SIGNAL_ID_OPT225_SPREAD_CHANGE,
    SIGNAL_ID_RATE_CURVE_XS,
    SIGNAL_ID_RATE_LEVEL_XS,
    SIGNAL_STATUS,
    SIGNAL_VERSION,
    _freeze_meta,
)


def _entry(signal_id: str, hypothesis_class: str, **extra: Any) -> dict[str, Any]:
    return {
        "signal_id": signal_id,
        "version": SIGNAL_VERSION,
        "status": SIGNAL_STATUS,
        "candidate_only": CANDIDATE_ONLY,
        "hypothesis_class": hypothesis_class,
        "not_simple_daily_sign": True,
        **extra,
    }


def class_signal_definitions(
    *,
    hold_days: int = DEFAULT_HOLD_DAYS,
    macro_mode: str = "rate_change",
    event_hold_days: int = DEFAULT_EVENT_POST_HOLD_DAYS,
    flow_hold_days: int = DEFAULT_FLOW_HOLD_DAYS,
    fund_hold_days: int = DEFAULT_FUND_HOLD_DAYS,
) -> list[dict[str, Any]]:
    """Declarative catalog for class-based research signals."""
    h = int(hold_days)
    eh = int(event_hold_days)
    fh = int(flow_hold_days)
    uh = int(fund_hold_days)
    return [
        _entry(
            SIGNAL_ID_MULTI_DAY_HOLD,
            CLASS_MULTI_DAY_HOLD,
            hold_days=h,
            role="multi_day_hold",
        ),
        _entry(
            SIGNAL_ID_EVENT_POST,
            CLASS_EVENT_POST,
            post_hold_days=eh,
            role="event_post",
        ),
        _entry(
            SIGNAL_ID_MACRO_CONDITIONED,
            CLASS_MACRO_CONDITIONED,
            macro_mode=str(macro_mode),
            role="macro_conditioned",
        ),
        _entry(
            SIGNAL_ID_CROSS_SECTION,
            CLASS_CROSS_SECTION_RELATIVE,
            role="cross_section_relative",
        ),
        _entry(
            SIGNAL_ID_FLOW_DEMAND,
            CLASS_FLOW_DEMAND,
            hold_days=fh,
            role="flow_demand",
        ),
        _entry(
            SIGNAL_ID_FUNDAMENTALS_PRICE,
            CLASS_FUNDAMENTALS_PRICE,
            hold_days=uh,
            role="fundamentals_price",
        ),
        _entry(
            SIGNAL_ID_RATE_LEVEL_XS,
            CLASS_RATE_FACTOR,
            role="rate_factor_abs_level",
        ),
        _entry(
            SIGNAL_ID_RATE_CURVE_XS,
            CLASS_RATE_FACTOR,
            role="rate_factor_curve_shape",
        ),
        _entry(
            SIGNAL_ID_MF_VALUE_MOM_RATE,
            CLASS_MULTI_FACTOR,
            role="multi_factor_value_mom_rate",
        ),
        _entry(
            SIGNAL_ID_MF_FLOW_PRICE,
            CLASS_MULTI_FACTOR,
            role="multi_factor_flow_price",
        ),
        _entry(
            SIGNAL_ID_NKY_VOL_ABS_LEVEL,
            CLASS_INDEX_VOL_REGIME,
            role="index_vol_abs_level",
        ),
        _entry(
            SIGNAL_ID_NKY_VOL_TERM_LEVELS,
            CLASS_INDEX_VOL_REGIME,
            role="index_vol_term_levels",
        ),
        _entry(
            SIGNAL_ID_NKY_VOL_TERM_RATIO,
            CLASS_INDEX_VOL_REGIME,
            role="index_vol_term_ratio",
        ),
        _entry(
            SIGNAL_ID_OPT225_BASEVOL_ABS,
            CLASS_OPTIONS_VOL_REGIME,
            role="opt225_basevol_abs_level",
        ),
        _entry(
            SIGNAL_ID_OPT225_BASEVOL_TERM_LEVELS,
            CLASS_OPTIONS_VOL_REGIME,
            role="opt225_basevol_term_levels",
        ),
        _entry(
            SIGNAL_ID_OPT225_BASEVOL_TERM_RATIO,
            CLASS_OPTIONS_VOL_REGIME,
            role="opt225_basevol_term_ratio",
        ),
        _entry(
            SIGNAL_ID_OPT225_ATM_IV_ABS,
            CLASS_OPTIONS_VOL_REGIME,
            role="opt225_atm_iv_abs_level",
        ),
        _entry(
            SIGNAL_ID_OPT225_ATM_IV_TERM_LEVELS,
            CLASS_OPTIONS_VOL_REGIME,
            role="opt225_atm_iv_term_levels",
        ),
        _entry(
            SIGNAL_ID_OPT225_ATM_IV_TERM_RATIO,
            CLASS_OPTIONS_VOL_REGIME,
            role="opt225_atm_iv_term_ratio",
        ),
        _entry(
            SIGNAL_ID_OPT225_SPREAD_ABS,
            CLASS_OPTIONS_VOL_REGIME,
            role="opt225_iv_base_spread_abs",
        ),
        _entry(
            SIGNAL_ID_OPT225_SPREAD_CHANGE,
            CLASS_OPTIONS_VOL_REGIME,
            role="opt225_iv_base_spread_change",
        ),
        _entry(
            SIGNAL_ID_OPT225_SKEW_ABS,
            CLASS_OPTIONS_VOL_REGIME,
            role="opt225_skew_abs_level",
        ),
        _entry(
            SIGNAL_ID_OPT225_CM_TERM_ABS,
            CLASS_OPTIONS_VOL_REGIME,
            role="opt225_cm_term_abs_level",
        ),
        _entry(
            SIGNAL_ID_OPT225_CM_TERM_RATIO,
            CLASS_OPTIONS_VOL_REGIME,
            role="opt225_cm_term_ratio",
        ),
        _entry(
            SIGNAL_ID_OPT225_BASEVOL_DELTA_ABS,
            CLASS_OPTIONS_VOL_REGIME,
            role="opt225_basevol_delta_abs",
        ),
    ]


def class_signals_document() -> dict[str, Any]:
    """Public document for class signal surface."""
    return {
        "version": CLASS_SIGNALS_VERSION,
        "wave": CLASS_SIGNALS_WAVE,
        "signals": class_signal_definitions(),
        "not_simple_daily_sign": True,
        "s1_s5_unreject": S1_S5_UNREJECT,
        **_freeze_meta(),
    }
