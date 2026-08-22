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
    CROSS_SECTION_DATASETS,
    DEFAULT_EVENT_POST_HOLD_DAYS,
    DEFAULT_FLOW_HOLD_DAYS,
    DEFAULT_FUND_HOLD_DAYS,
    DEFAULT_HOLD_DAYS,
    DEFAULT_MIN_ABS_T_STAT,
    DEFAULT_MIN_ACTIVATION_RATE_MULTIDAY,
    DEFAULT_MIN_ECONOMIC_NET,
    DEFAULT_MIN_EVENTS_PER_CODE_YEAR,
    DEFAULT_MIN_PERIOD_WIN_RATE,
    DEFAULT_MIN_POSITIVE_PERIODS,
    DEFAULT_MIN_SHARPE_PERIOD,
    DEFAULT_MIN_YEARS_RESEARCH_CANDIDATE,
    DEFAULT_NKY_VOL_COMPRESS_RATIO,
    DEFAULT_NKY_VOL_EXPAND_RATIO,
    DEFAULT_NKY_VOL_HIGH_THRESHOLD,
    DEFAULT_NKY_VOL_LONG_N,
    DEFAULT_NKY_VOL_LOW_THRESHOLD,
    DEFAULT_NKY_VOL_SHORT_N,
    DEFAULT_OPT225_BASEVOL_DELTA_HIGH_THRESHOLD,
    DEFAULT_OPT225_BASEVOL_DELTA_LOW_THRESHOLD,
    DEFAULT_OPT225_CM_TERM_HIGH_THRESHOLD,
    DEFAULT_OPT225_CM_TERM_LOW_THRESHOLD,
    DEFAULT_OPT225_SKEW_HIGH_THRESHOLD,
    DEFAULT_OPT225_SKEW_LOW_THRESHOLD,
    DEFAULT_OPT225_SPREAD_HIGH_THRESHOLD,
    DEFAULT_OPT225_SPREAD_LOW_THRESHOLD,
    DEFAULT_OPT225_VOL_HIGH_THRESHOLD,
    DEFAULT_OPT225_VOL_LOW_THRESHOLD,
    DISCLOSURE_FEATURE_ID,
    EVENT_POST_DATASETS,
    EVENT_POST_ENTRY_MODE,
    FLOW_DEMAND_DATASETS,
    FUNDAMENTAL_RATIO_FEATURE_ID,
    FUNDAMENTALS_PRICE_DATASETS,
    INDEX_VOL_REGIME_DATASETS,
    MACRO_CONDITIONED_DATASETS,
    MARGIN_CHANGE_FEATURE_ID,
    MOMENTUM_FEATURE_ID,
    MULTI_DAY_HOLD_DATASETS,
    MULTI_FACTOR_DATASETS,
    NKY_VOL_ABS_FEATURE_ID,
    NKY_VOL_TERM_LEVELS_FEATURE_ID,
    NKY_VOL_TERM_RATIO_FEATURE_ID,
    OPT225_ATM_IV_FEATURE_ID,
    OPT225_ATM_IV_ROLE,
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
    RATE_FACTOR_DATASETS,
    REPO_CURVE_FEATURE_ID,
    REPO_CURVE_LONG_TENOR,
    REPO_CURVE_SHORT_TENOR,
    REPO_RATE_FEATURE_ID,
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
    SIGNAL_STATUS,
    SIGNAL_VERSION,
    SUPPORTED_HOLD_DAYS,
    TRADING_DAY_FEATURE_ID,
    _freeze_meta,
)


def class_signal_definitions(
    *,
    hold_days: int = DEFAULT_HOLD_DAYS,
    macro_mode: str = "rate_change",
    event_hold_days: int = DEFAULT_EVENT_POST_HOLD_DAYS,
    flow_hold_days: int = DEFAULT_FLOW_HOLD_DAYS,
    fund_hold_days: int = DEFAULT_FUND_HOLD_DAYS,
) -> list[dict[str, Any]]:
    """Declarative catalog for W79 class-based research signals."""
    return [
        {
            "signal_id": SIGNAL_ID_MULTI_DAY_HOLD,
            "version": SIGNAL_VERSION,
            "status": SIGNAL_STATUS,
            "candidate_only": CANDIDATE_ONLY,
            "hypothesis_class": CLASS_MULTI_DAY_HOLD,
            "horizon": f"{int(hold_days)}d_hold",
            "primary_feature_id": MOMENTUM_FEATURE_ID,
            "filter_feature_id": TRADING_DAY_FEATURE_ID,
            "feature_kinds": [
                "multi_day_return",
                "momentum_n",
                "hold_period_score",
                "turnover_aware_signal",
            ],
            "datasets_required": list(MULTI_DAY_HOLD_DATASETS),
            "hold_days": int(hold_days),
            "formula": (
                f"entry=sign(momentum_n n={int(hold_days)}); "
                f"sticky fixed_horizon hold={int(hold_days)}d; "
                "forward return over hold (not 1d nextday primary)"
            ),
            "not_simple_daily_sign": True,
            "role": "multi_day_hold",
        },
        {
            "signal_id": SIGNAL_ID_EVENT_POST,
            "version": SIGNAL_VERSION,
            "status": SIGNAL_STATUS,
            "candidate_only": CANDIDATE_ONLY,
            "hypothesis_class": CLASS_EVENT_POST,
            "horizon": f"1d_to_{int(event_hold_days)}d_post_event",
            "primary_feature_id": DISCLOSURE_FEATURE_ID,
            "filter_feature_id": TRADING_DAY_FEATURE_ID,
            "feature_kinds": [
                "disclosure_flag",
                "event_window",
                "post_event_drift",
                "earnings_surprise_proxy",
            ],
            "datasets_required": list(EVENT_POST_DATASETS),
            "post_hold_days": int(event_hold_days),
            "formula": (
                f"on fins DiscDate+DiscTime (SoT): PIT entry at first session "
                f"close not looking ahead; sign(surprise_proxy); "
                f"hold={int(event_hold_days)}d close-to-close; non-event no trade"
            ),
            "entry_mode": EVENT_POST_ENTRY_MODE,
            "not_simple_daily_sign": True,
            "role": "event_post",
        },
        {
            "signal_id": SIGNAL_ID_MACRO_CONDITIONED,
            "version": SIGNAL_VERSION,
            "status": SIGNAL_STATUS,
            "candidate_only": CANDIDATE_ONLY,
            "hypothesis_class": CLASS_MACRO_CONDITIONED,
            "horizon": "20d_to_60d_regime_conditioned",
            "primary_feature_id": MOMENTUM_FEATURE_ID,
            "macro_feature_id": REPO_RATE_FEATURE_ID,
            "filter_feature_id": TRADING_DAY_FEATURE_ID,
            "feature_kinds": [
                "regime_label",
                "macro_state",
                "conditioned_signal",
                "rate_environment",
            ],
            "datasets_required": list(MACRO_CONDITIONED_DATASETS),
            "macro_mode": str(macro_mode),
            "formula": (
                f"entry=sign(momentum); regime from repo_rate_{macro_mode}; "
                "long_only on rate_down/low; short_only on rate_up/high"
            ),
            "not_simple_daily_sign": True,
            "role": "macro_conditioned",
        },
        {
            "signal_id": SIGNAL_ID_CROSS_SECTION,
            "version": SIGNAL_VERSION,
            "status": SIGNAL_STATUS,
            "candidate_only": CANDIDATE_ONLY,
            "hypothesis_class": CLASS_CROSS_SECTION_RELATIVE,
            "horizon": "5d_to_20d_cross_section",
            "primary_feature_id": MOMENTUM_FEATURE_ID,
            "feature_kinds": [
                "cross_section_rank",
                "relative_value",
                "dispersion_signal",
            ],
            "datasets_required": list(CROSS_SECTION_DATASETS),
            "formula": (
                "rank(momentum) L-S within day; optional sticky multi-day hold"
            ),
            "not_simple_daily_sign": True,
            "role": "cross_section_relative",
            "optional": True,
        },
        {
            "signal_id": SIGNAL_ID_FLOW_DEMAND,
            "version": SIGNAL_VERSION,
            "status": SIGNAL_STATUS,
            "candidate_only": CANDIDATE_ONLY,
            "hypothesis_class": CLASS_FLOW_DEMAND,
            "horizon": f"{int(flow_hold_days)}d_to_20d_flow",
            "primary_feature_id": MARGIN_CHANGE_FEATURE_ID,
            "feature_kinds": [
                "flow_delta",
                "demand_pressure",
                "positioning_level",
            ],
            "datasets_required": list(FLOW_DEMAND_DATASETS),
            "hold_days": int(flow_hold_days),
            "formula": (
                f"entry=sign(margin_change); sticky hold={int(flow_hold_days)}d; "
                "not S4 daily rehash; optional short_ratio confirm"
            ),
            "not_simple_daily_sign": True,
            "not_s4_rehash": True,
            "role": "flow_demand",
        },
        {
            "signal_id": SIGNAL_ID_FUNDAMENTALS_PRICE,
            "version": SIGNAL_VERSION,
            "status": SIGNAL_STATUS,
            "candidate_only": CANDIDATE_ONLY,
            "hypothesis_class": CLASS_FUNDAMENTALS_PRICE,
            "horizon": f"{int(fund_hold_days)}d_to_60d_fundamental",
            "primary_feature_id": FUNDAMENTAL_RATIO_FEATURE_ID,
            "feature_kinds": [
                "fundamental_ratio",
                "earnings_surprise_proxy",
                "value_score",
            ],
            "datasets_required": list(FUNDAMENTALS_PRICE_DATASETS),
            "hold_days": int(fund_hold_days),
            "formula": (
                f"value_score=BPS/P|EPS/P (PIT); agree with momentum; "
                f"hold={int(fund_hold_days)}d"
            ),
            "not_simple_daily_sign": True,
            "role": "fundamentals_price",
        },
        {
            "signal_id": SIGNAL_ID_RATE_LEVEL_XS,
            "version": SIGNAL_VERSION,
            "status": SIGNAL_STATUS,
            "candidate_only": CANDIDATE_ONLY,
            "hypothesis_class": CLASS_RATE_FACTOR,
            "horizon": "multi_day_cs_rate_level",
            "primary_feature_id": REPO_RATE_FEATURE_ID,
            "feature_kinds": [
                "repo_rate_level",
                "cross_section_rank",
                "risk_on_off_book",
            ],
            "datasets_required": list(RATE_FACTOR_DATASETS),
            "formula": (
                "CS mom L-S risk-adjusted by absolute Tokyo repo level "
                "(low keep / high reverse / mid flat)"
            ),
            "not_simple_daily_sign": True,
            "not_macro_mom_gate_only": True,
            "role": "rate_factor_abs_level",
        },
        {
            "signal_id": SIGNAL_ID_RATE_CURVE_XS,
            "version": SIGNAL_VERSION,
            "status": SIGNAL_STATUS,
            "candidate_only": CANDIDATE_ONLY,
            "hypothesis_class": CLASS_RATE_FACTOR,
            "horizon": "multi_day_cs_rate_curve",
            "primary_feature_id": REPO_CURVE_FEATURE_ID,
            "feature_kinds": [
                "repo_curve_spread",
                "cross_section_rank",
                "term_structure_proxy",
            ],
            "datasets_required": list(RATE_FACTOR_DATASETS),
            "formula": (
                f"spread={REPO_CURVE_LONG_TENOR}-"
                f"{REPO_CURVE_SHORT_TENOR}; steep keep CS / inverted reverse"
            ),
            "not_simple_daily_sign": True,
            "role": "rate_factor_curve_shape",
            "curve_definition": {
                "short_tenor": REPO_CURVE_SHORT_TENOR,
                "long_tenor": REPO_CURVE_LONG_TENOR,
                "note": "JSDA repo tenors only (no JGB/OIS invent)",
            },
        },
        {
            "signal_id": SIGNAL_ID_MF_VALUE_MOM_RATE,
            "version": SIGNAL_VERSION,
            "status": SIGNAL_STATUS,
            "candidate_only": CANDIDATE_ONLY,
            "hypothesis_class": CLASS_MULTI_FACTOR,
            "horizon": f"{int(fund_hold_days)}d_multi_factor",
            "primary_feature_id": FUNDAMENTAL_RATIO_FEATURE_ID,
            "feature_kinds": ["value", "momentum", "rate_level"],
            "datasets_required": list(MULTI_FACTOR_DATASETS),
            "formula": "value×mom agree AND funding-level alignment",
            "not_simple_daily_sign": True,
            "not_fund_value_mom_agree_only": True,
            "role": "multi_factor_value_mom_rate",
        },
        {
            "signal_id": SIGNAL_ID_MF_FLOW_PRICE,
            "version": SIGNAL_VERSION,
            "status": SIGNAL_STATUS,
            "candidate_only": CANDIDATE_ONLY,
            "hypothesis_class": CLASS_MULTI_FACTOR,
            "horizon": f"{int(flow_hold_days)}d_multi_factor",
            "primary_feature_id": MARGIN_CHANGE_FEATURE_ID,
            "feature_kinds": ["margin_flow", "price_momentum"],
            "datasets_required": [
                "markets_margin_interest",
                "equities_bars_daily",
                "markets_calendar",
            ],
            "formula": "sign(margin_change)==sign(mom); sticky multi-day hold",
            "not_simple_daily_sign": True,
            "not_short_confirm_variant": True,
            "role": "multi_factor_flow_price",
        },
        {
            "signal_id": SIGNAL_ID_NKY_VOL_ABS_LEVEL,
            "version": SIGNAL_VERSION,
            "status": SIGNAL_STATUS,
            "candidate_only": CANDIDATE_ONLY,
            "hypothesis_class": CLASS_INDEX_VOL_REGIME,
            "horizon": "multi_day_cs_index_vol_abs",
            "primary_feature_id": NKY_VOL_ABS_FEATURE_ID,
            "feature_kinds": [
                "index_realized_vol",
                "cross_section_rank",
                "risk_on_off_book",
            ],
            "datasets_required": list(INDEX_VOL_REGIME_DATASETS),
            "formula": (
                "CS mom L-S risk-adjusted by absolute Nikkei/TOPIX realized vol "
                f"(high≥{DEFAULT_NKY_VOL_HIGH_THRESHOLD} reverse / "
                f"low≤{DEFAULT_NKY_VOL_LOW_THRESHOLD} keep / mid flat)"
            ),
            "not_simple_daily_sign": True,
            "not_per_name_vol_gate": True,
            "role": "index_vol_abs_level",
            "proxy_note": (
                "No cash Nikkei code in indices_bars_daily; prefer NK225F front "
                "realized vol, TOPIX fallback; NKVIF optional abs-level overlay."
            ),
        },
        {
            "signal_id": SIGNAL_ID_NKY_VOL_TERM_LEVELS,
            "version": SIGNAL_VERSION,
            "status": SIGNAL_STATUS,
            "candidate_only": CANDIDATE_ONLY,
            "hypothesis_class": CLASS_INDEX_VOL_REGIME,
            "horizon": "multi_day_cs_index_vol_term_levels",
            "primary_feature_id": NKY_VOL_TERM_LEVELS_FEATURE_ID,
            "feature_kinds": [
                "index_realized_vol_short",
                "index_realized_vol_long",
                "cross_section_rank",
                "risk_on_off_book",
            ],
            "datasets_required": list(INDEX_VOL_REGIME_DATASETS),
            "formula": (
                f"short RV n={DEFAULT_NKY_VOL_SHORT_N} + long RV n="
                f"{DEFAULT_NKY_VOL_LONG_N}; both high reverse / both low keep"
            ),
            "not_simple_daily_sign": True,
            "not_per_name_vol_gate": True,
            "not_ratio_only": True,
            "role": "index_vol_term_levels",
        },
        {
            "signal_id": SIGNAL_ID_NKY_VOL_TERM_RATIO,
            "version": SIGNAL_VERSION,
            "status": SIGNAL_STATUS,
            "candidate_only": CANDIDATE_ONLY,
            "hypothesis_class": CLASS_INDEX_VOL_REGIME,
            "horizon": "multi_day_cs_index_vol_term_ratio",
            "primary_feature_id": NKY_VOL_TERM_RATIO_FEATURE_ID,
            "feature_kinds": [
                "index_realized_vol_term_ratio",
                "cross_section_rank",
                "vol_term_structure",
            ],
            "datasets_required": list(INDEX_VOL_REGIME_DATASETS),
            "formula": (
                f"ratio=RV({DEFAULT_NKY_VOL_SHORT_N})/RV({DEFAULT_NKY_VOL_LONG_N}); "
                f"≥{DEFAULT_NKY_VOL_EXPAND_RATIO} expand reverse / "
                f"≤{DEFAULT_NKY_VOL_COMPRESS_RATIO} compress keep"
            ),
            "not_simple_daily_sign": True,
            "not_per_name_vol_gate": True,
            "not_name_level_vol_expand": True,
            "role": "index_vol_term_ratio",
            "proxy_compare_only": True,
        },
        {
            "signal_id": SIGNAL_ID_OPT225_BASEVOL_ABS,
            "version": SIGNAL_VERSION,
            "status": SIGNAL_STATUS,
            "candidate_only": CANDIDATE_ONLY,
            "hypothesis_class": CLASS_OPTIONS_VOL_REGIME,
            "horizon": "multi_day_cs_opt225_basevol_abs",
            "primary_feature_id": OPT225_BASEVOL_FEATURE_ID,
            "feature_kinds": [
                "options_basevol",
                "cross_section_rank",
                "risk_on_off_book",
            ],
            "datasets_required": list(OPTIONS_VOL_REGIME_DATASETS),
            "formula": (
                "CS mom L-S × abs options_225 BaseVol "
                f"(high≥{DEFAULT_OPT225_VOL_HIGH_THRESHOLD} reverse / "
                f"low≤{DEFAULT_OPT225_VOL_LOW_THRESHOLD} keep / mid flat); "
                "units=percent_vol_points"
            ),
            "not_simple_daily_sign": True,
            "canonical_nky_vol": True,
            "role": "opt225_basevol_abs_level",
        },
        {
            "signal_id": SIGNAL_ID_OPT225_BASEVOL_TERM_LEVELS,
            "version": SIGNAL_VERSION,
            "status": SIGNAL_STATUS,
            "candidate_only": CANDIDATE_ONLY,
            "hypothesis_class": CLASS_OPTIONS_VOL_REGIME,
            "horizon": "multi_day_cs_opt225_basevol_term_levels",
            "primary_feature_id": OPT225_BASEVOL_FEATURE_ID,
            "datasets_required": list(OPTIONS_VOL_REGIME_DATASETS),
            "not_simple_daily_sign": True,
            "role": "opt225_basevol_term_levels",
            "canonical_nky_vol": True,
        },
        {
            "signal_id": SIGNAL_ID_OPT225_BASEVOL_TERM_RATIO,
            "version": SIGNAL_VERSION,
            "status": SIGNAL_STATUS,
            "candidate_only": CANDIDATE_ONLY,
            "hypothesis_class": CLASS_OPTIONS_VOL_REGIME,
            "horizon": "multi_day_cs_opt225_basevol_term_ratio",
            "primary_feature_id": OPT225_BASEVOL_FEATURE_ID,
            "datasets_required": list(OPTIONS_VOL_REGIME_DATASETS),
            "not_simple_daily_sign": True,
            "role": "opt225_basevol_term_ratio",
            "canonical_nky_vol": True,
        },
        {
            "signal_id": SIGNAL_ID_OPT225_ATM_IV_ABS,
            "version": SIGNAL_VERSION,
            "status": SIGNAL_STATUS,
            "candidate_only": CANDIDATE_ONLY,
            "hypothesis_class": CLASS_OPTIONS_VOL_REGIME,
            "horizon": "multi_day_cs_opt225_atm_iv_abs",
            "primary_feature_id": OPT225_ATM_IV_FEATURE_ID,
            "datasets_required": list(OPTIONS_VOL_REGIME_DATASETS),
            "not_simple_daily_sign": True,
            "role": "opt225_atm_iv_abs_level",
            "compare_only": True,
            "atm_iv_role": OPT225_ATM_IV_ROLE,
            "canonical_level": OPT225_CANONICAL_LEVEL,
            "note": "W94: ATM reconstructed compare-only; BaseVol is canonical level.",
        },
        {
            "signal_id": SIGNAL_ID_OPT225_ATM_IV_TERM_LEVELS,
            "version": SIGNAL_VERSION,
            "status": SIGNAL_STATUS,
            "candidate_only": CANDIDATE_ONLY,
            "hypothesis_class": CLASS_OPTIONS_VOL_REGIME,
            "primary_feature_id": OPT225_ATM_IV_FEATURE_ID,
            "datasets_required": list(OPTIONS_VOL_REGIME_DATASETS),
            "not_simple_daily_sign": True,
            "role": "opt225_atm_iv_term_levels",
            "compare_only": True,
            "atm_iv_role": OPT225_ATM_IV_ROLE,
        },
        {
            "signal_id": SIGNAL_ID_OPT225_ATM_IV_TERM_RATIO,
            "version": SIGNAL_VERSION,
            "status": SIGNAL_STATUS,
            "candidate_only": CANDIDATE_ONLY,
            "hypothesis_class": CLASS_OPTIONS_VOL_REGIME,
            "primary_feature_id": OPT225_ATM_IV_FEATURE_ID,
            "datasets_required": list(OPTIONS_VOL_REGIME_DATASETS),
            "not_simple_daily_sign": True,
            "role": "opt225_atm_iv_term_ratio",
            "compare_only": True,
            "atm_iv_role": OPT225_ATM_IV_ROLE,
        },
        {
            "signal_id": SIGNAL_ID_OPT225_SPREAD_ABS,
            "version": SIGNAL_VERSION,
            "status": SIGNAL_STATUS,
            "candidate_only": CANDIDATE_ONLY,
            "hypothesis_class": CLASS_OPTIONS_VOL_REGIME,
            "primary_feature_id": OPT225_SPREAD_FEATURE_ID,
            "datasets_required": list(OPTIONS_VOL_REGIME_DATASETS),
            "formula": (
                f"spread={OPT225_SPREAD_CONVENTION}; "
                f"high≥{DEFAULT_OPT225_SPREAD_HIGH_THRESHOLD} reverse / "
                f"low≤{DEFAULT_OPT225_SPREAD_LOW_THRESHOLD} keep"
            ),
            "not_simple_daily_sign": True,
            "role": "opt225_iv_base_spread_abs",
            "compare_only": True,
            "note": "W93/W94: non-informative at frozen thresholds post min_dte=6.",
        },
        {
            "signal_id": SIGNAL_ID_OPT225_SPREAD_CHANGE,
            "version": SIGNAL_VERSION,
            "status": SIGNAL_STATUS,
            "candidate_only": CANDIDATE_ONLY,
            "hypothesis_class": CLASS_OPTIONS_VOL_REGIME,
            "primary_feature_id": OPT225_SPREAD_FEATURE_ID,
            "datasets_required": list(OPTIONS_VOL_REGIME_DATASETS),
            "not_simple_daily_sign": True,
            "role": "opt225_iv_base_spread_change",
            "compare_only": True,
        },
        {
            "signal_id": SIGNAL_ID_OPT225_SKEW_ABS,
            "version": SIGNAL_VERSION,
            "status": SIGNAL_STATUS,
            "candidate_only": CANDIDATE_ONLY,
            "hypothesis_class": CLASS_OPTIONS_VOL_REGIME,
            "horizon": "multi_day_cs_opt225_skew_abs",
            "primary_feature_id": OPT225_SKEW_FEATURE_ID,
            "datasets_required": list(OPTIONS_VOL_REGIME_DATASETS),
            "formula": (
                f"skew={OPT225_SKEW_CONVENTION}; listed put only (no invent); "
                f"high≥{DEFAULT_OPT225_SKEW_HIGH_THRESHOLD} reverse / "
                f"low≤{DEFAULT_OPT225_SKEW_LOW_THRESHOLD} keep"
            ),
            "not_simple_daily_sign": True,
            "role": "opt225_skew_abs_level",
            "invent_strike": False,
            "canonical_nky_vol": True,
        },
        {
            "signal_id": SIGNAL_ID_OPT225_CM_TERM_ABS,
            "version": SIGNAL_VERSION,
            "status": SIGNAL_STATUS,
            "candidate_only": CANDIDATE_ONLY,
            "hypothesis_class": CLASS_OPTIONS_VOL_REGIME,
            "horizon": "multi_day_cs_opt225_cm_term_abs",
            "primary_feature_id": OPT225_CM_TERM_FEATURE_ID,
            "datasets_required": list(OPTIONS_VOL_REGIME_DATASETS),
            "formula": (
                f"cm_term={OPT225_CM_TERM_CONVENTION}; min_dte>=6; "
                f"high≥{DEFAULT_OPT225_CM_TERM_HIGH_THRESHOLD} reverse / "
                f"low≤{DEFAULT_OPT225_CM_TERM_LOW_THRESHOLD} keep"
            ),
            "not_simple_daily_sign": True,
            "role": "opt225_cm_term_abs_level",
            "invent_strike": False,
            "canonical_nky_vol": True,
        },
        {
            "signal_id": SIGNAL_ID_OPT225_BASEVOL_DELTA_ABS,
            "version": SIGNAL_VERSION,
            "status": SIGNAL_STATUS,
            "candidate_only": CANDIDATE_ONLY,
            "hypothesis_class": CLASS_OPTIONS_VOL_REGIME,
            "horizon": "multi_day_cs_opt225_basevol_delta_abs",
            "primary_feature_id": OPT225_BASEVOL_DELTA_FEATURE_ID,
            "datasets_required": list(OPTIONS_VOL_REGIME_DATASETS),
            "formula": (
                f"delta={OPT225_BASEVOL_DELTA_CONVENTION}; first day omitted; "
                f"high≥{DEFAULT_OPT225_BASEVOL_DELTA_HIGH_THRESHOLD} reverse / "
                f"low≤{DEFAULT_OPT225_BASEVOL_DELTA_LOW_THRESHOLD} keep"
            ),
            "not_simple_daily_sign": True,
            "role": "opt225_basevol_delta_abs",
            "canonical_level": OPT225_CANONICAL_LEVEL,
            "canonical_nky_vol": True,
        },
    ]


def class_signals_document() -> dict[str, Any]:
    """Public document for class signal surface."""
    return {
        "version": CLASS_SIGNALS_VERSION,
        "wave": CLASS_SIGNALS_WAVE,
        "signals": class_signal_definitions(),
        "supported_hold_days": list(SUPPORTED_HOLD_DAYS),
        "min_economic_net": DEFAULT_MIN_ECONOMIC_NET,
        "min_activation_rate_multiday": DEFAULT_MIN_ACTIVATION_RATE_MULTIDAY,
        "min_events_per_code_year": DEFAULT_MIN_EVENTS_PER_CODE_YEAR,
        "min_years_research_candidate": DEFAULT_MIN_YEARS_RESEARCH_CANDIDATE,
        "min_abs_t_stat": DEFAULT_MIN_ABS_T_STAT,
        "min_sharpe_period": DEFAULT_MIN_SHARPE_PERIOD,
        "min_period_win_rate": DEFAULT_MIN_PERIOD_WIN_RATE,
        "min_positive_periods": DEFAULT_MIN_POSITIVE_PERIODS,
        "not_simple_daily_sign": True,
        "s1_s5_unreject": S1_S5_UNREJECT,
        **_freeze_meta(),
        "note": (
            "W94 class-based research signals. multi_day_hold + event_post + "
            "macro_conditioned + flow_demand + fundamentals_price "
            "(+ optional cross_section) + rate_factor (abs level / curve) + "
            "multi_factor (value×mom×rate / flow×price) + index_vol_regime "
            "(nky abs / term levels / term ratio; TOPIX/NK225F proxy/compare) + "
            "options_vol_regime (canonical options_225 BaseVol level + W94 "
            "skew / CM-term / ΔBaseVol; ATM IV compare-only; spread compare). "
            "Production research_candidate only if economic net + "
            "occurrence rate + multi-year no extreme skew + risk OK + "
            "statistical bar. READY/Mass never auto-connect. No S1–S5 un-reject."
        ),
    }
