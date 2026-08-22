"""Hypothesis-class research signals (W78–W80) — not simple daily sign.

Implements real signal logic for:

* ``multi_day_hold`` — N-day momentum entry with sticky multi-day hold
  (rebalance every ``hold_days``; not 1d flip)
* ``macro_conditioned`` — equity momentum conditioned on Tokyo repo rate
  **level** or **change** from ``jsda_tokyo_repo_rates``
* ``event_post`` — post-disclosure / post-earnings window (not continuous daily)
* ``flow_demand`` — multi-day margin/short flow pressure (not S4 daily rehash)
* ``fundamentals_price`` — PIT fundamentals × price (value / surprise)
* ``cross_section_relative`` — same-day rank L-S (optional; multi-day sticky OK)

Hard constraints
----------------
* Does **not** import ``agents.mass_research`` / mass loop
* Does **not** mint READY / VerifiedResearchReadiness
* Does **not** emit order intents / call paper execution
* Does **not** un-reject S1–S5
* ``simple_daily_sign`` is **not** used
* Mass / READY / operational GO never auto-connect from pass

Status remains ``candidate`` (research). W80 may set ``research_candidate=True``
when production criteria (economic net + occurrence rate + multi-year + risk)
are all met — still not READY / Mass / GO.
"""

from __future__ import annotations

from typing import Any

from features.research_freezes import (
    MASS_RESEARCH,
    ORDER_EXECUTION,
    PHASE7,
    READY_DECLARED,
    S1_S5_UNREJECT,
    SIMPLE_DAILY_SIGN,
)

# ---------------------------------------------------------------------------
# Identity / freeze
# ---------------------------------------------------------------------------

CLASS_SIGNALS_VERSION: str = "class-signals/v10"
CLASS_SIGNALS_WAVE: str = "W95 / w0818e"

SIGNAL_STATUS: str = "candidate"
SIGNAL_VERSION: str = "1.5.0"
CANDIDATE_ONLY: bool = False  # legs may be approved; signal status stays candidate

# ---------------------------------------------------------------------------
# Class ids (align with research.hypothesis_classes)
# ---------------------------------------------------------------------------

CLASS_MULTI_DAY_HOLD: str = "multi_day_hold"
CLASS_MACRO_CONDITIONED: str = "macro_conditioned"
CLASS_CROSS_SECTION_RELATIVE: str = "cross_section_relative"
CLASS_EVENT_POST: str = "event_post"
CLASS_FLOW_DEMAND: str = "flow_demand"
CLASS_FUNDAMENTALS_PRICE: str = "fundamentals_price"
# W89 research families (factory/eval dispatch; not necessarily in registry)
CLASS_RATE_FACTOR: str = "rate_factor"
CLASS_MULTI_FACTOR: str = "multi_factor"
# W91: index-level Nikkei/TOPIX vol regime (not per-name vol gate)
CLASS_INDEX_VOL_REGIME: str = "index_vol_regime"
# W92: Nikkei 225 options BaseVol / ATM IV / spread regime (canonical vol SoT)
CLASS_OPTIONS_VOL_REGIME: str = "options_vol_regime"

# Signal ids (stable R2 / catalog keys)
SIGNAL_ID_MULTI_DAY_HOLD: str = "c21_multi_day_momentum_hold"
SIGNAL_ID_MACRO_CONDITIONED: str = "c21_repo_conditioned_momentum"
SIGNAL_ID_CROSS_SECTION: str = "c21_cross_section_momentum_rank"
SIGNAL_ID_EVENT_POST: str = "c21_event_post_disclosure_hold"
SIGNAL_ID_FLOW_DEMAND: str = "c21_margin_flow_multiday"
SIGNAL_ID_FUNDAMENTALS_PRICE: str = "c21_fundamentals_price_value"
SIGNAL_ID_RATE_LEVEL_XS: str = "c21_rate_level_xs_risk_adj"
SIGNAL_ID_RATE_CURVE_XS: str = "c21_rate_curve_shape_xs"
SIGNAL_ID_MF_VALUE_MOM_RATE: str = "c21_mf_value_mom_rate"
SIGNAL_ID_MF_FLOW_PRICE: str = "c21_mf_flow_price_confirm"
SIGNAL_ID_NKY_VOL_ABS_LEVEL: str = "c21_nky_vol_abs_level_xs"
SIGNAL_ID_NKY_VOL_TERM_LEVELS: str = "c21_nky_vol_term_levels_xs"
SIGNAL_ID_NKY_VOL_TERM_RATIO: str = "c21_nky_vol_term_ratio_xs"
SIGNAL_ID_OPT225_BASEVOL_ABS: str = "c21_opt225_basevol_abs_level_xs"
SIGNAL_ID_OPT225_BASEVOL_TERM_LEVELS: str = "c21_opt225_basevol_term_levels_xs"
SIGNAL_ID_OPT225_BASEVOL_TERM_RATIO: str = "c21_opt225_basevol_term_ratio_xs"
SIGNAL_ID_OPT225_ATM_IV_ABS: str = "c21_opt225_atm_iv_abs_level_xs"
SIGNAL_ID_OPT225_ATM_IV_TERM_LEVELS: str = "c21_opt225_atm_iv_term_levels_xs"
SIGNAL_ID_OPT225_ATM_IV_TERM_RATIO: str = "c21_opt225_atm_iv_term_ratio_xs"
SIGNAL_ID_OPT225_SPREAD_ABS: str = "c21_opt225_iv_base_spread_abs_xs"
SIGNAL_ID_OPT225_SPREAD_CHANGE: str = "c21_opt225_iv_base_spread_change_xs"
# W94 skew / CM-term / ΔBaseVol
SIGNAL_ID_OPT225_SKEW_ABS: str = "c21_opt225_skew_abs_level_xs"
SIGNAL_ID_OPT225_CM_TERM_ABS: str = "c21_opt225_cm_term_abs_level_xs"
SIGNAL_ID_OPT225_BASEVOL_DELTA_ABS: str = "c21_opt225_basevol_delta_abs_xs"

# Feature legs (prefer registry-approved)
MOMENTUM_FEATURE_ID: str = "momentum_n"
TRADING_DAY_FEATURE_ID: str = "is_trading_day"
REPO_RATE_FEATURE_ID: str = "repo_rate_level"
REPO_CURVE_FEATURE_ID: str = "repo_curve_spread"
DISCLOSURE_FEATURE_ID: str = "disclosure_flag_fins"
MARGIN_CHANGE_FEATURE_ID: str = "margin_interest_change_1d"
SHORT_RATIO_FEATURE_ID: str = "short_ratio_level"
FUNDAMENTAL_RATIO_FEATURE_ID: str = "fundamental_ratio"
NKY_VOL_ABS_FEATURE_ID: str = "nky_realized_vol_abs"
NKY_VOL_TERM_LEVELS_FEATURE_ID: str = "nky_realized_vol_term_levels"
NKY_VOL_TERM_RATIO_FEATURE_ID: str = "nky_realized_vol_term_ratio"
OPT225_BASEVOL_FEATURE_ID: str = "opt225_basevol_level"
OPT225_ATM_IV_FEATURE_ID: str = "opt225_atm_iv_level"
OPT225_SPREAD_FEATURE_ID: str = "opt225_iv_base_spread"
OPT225_SKEW_FEATURE_ID: str = "opt225_skew_95put"
OPT225_CM_TERM_FEATURE_ID: str = "opt225_cm_term_near_next"
OPT225_BASEVOL_DELTA_FEATURE_ID: str = "opt225_basevol_delta"

# Tokyo repo tenor pins for curve-shape proxy (no invent; only observed tenors).
# Definition: spread = rate(long_tenor) − rate(short_tenor) on same as_of_date.
# Available JSDA tenors include overnight T+0/T+1, 1W–3W, 1M/3M/6M/1Y.
REPO_CURVE_SHORT_TENOR: str = "overnight/翌日物/T+0"
REPO_CURVE_LONG_TENOR: str = "3M/T+1"
DEFAULT_CURVE_STEEP_THRESHOLD: float = 0.0
DEFAULT_CURVE_INVERT_THRESHOLD: float = 0.0

# W91 Nikkei / index realized-vol regime defaults (annualized sample stdev).
# No cash Nikkei code in indices_bars_daily; proxy = NK225F front (prefer) or TOPIX.
DEFAULT_NKY_VOL_SHORT_N: int = 10
DEFAULT_NKY_VOL_LONG_N: int = 60
DEFAULT_NKY_VOL_HIGH_THRESHOLD: float = 0.20  # 20% ann. RV → high
DEFAULT_NKY_VOL_LOW_THRESHOLD: float = 0.10  # 10% ann. RV → low
DEFAULT_NKY_VOL_EXPAND_RATIO: float = 1.20  # short/long ≥ → expanding
DEFAULT_NKY_VOL_COMPRESS_RATIO: float = 0.80  # short/long ≤ → compressing
NKY_VOL_PROXY_NK225F: str = "nk225f_front_realized"
NKY_VOL_PROXY_TOPIX: str = "topix_realized"
TRADING_DAYS_ANN: int = 252

DEFAULT_HOLD_DAYS: int = 5
SUPPORTED_HOLD_DAYS: tuple[int, ...] = (5, 10, 20)
DEFAULT_EVENT_POST_HOLD_DAYS: int = 5
DEFAULT_FLOW_HOLD_DAYS: int = 5
DEFAULT_FUND_HOLD_DAYS: int = 20
DEFAULT_FUND_MOMENTUM_N: int = 20
# PIT event_post entry: first session close that is knowable after disclosure.
# "same_day_close_if_pre_close" = trade event-day close only when DiscTime is
# present and strictly before that day's session close; otherwise next bar.
# Never invent DiscTime; missing time → next trading session (conservative).
EVENT_POST_ENTRY_MODE: str = "same_day_close_if_pre_close"
# TSE cash close moved 15:00 → 15:30 JST on 2024-11-05 (dataset / exchange SoT).
SESSION_CLOSE_CHANGE_DATE: str = "2024-11-05"
# Candidate bar helper: residual after costs must clear this for "economic"
# meaningfulness discussion (research only).
DEFAULT_MIN_ECONOMIC_NET: float = 0.002  # 20bp per scored hold

# ---------------------------------------------------------------------------
# W80 occurrence-rate / production-candidate bar (rate-based, not count alone)
# ---------------------------------------------------------------------------
# multi_day_hold: scored rebalances / code-days. fixed_horizon expect ~1/hold.
# Floor at half expected for hold=10 → 0.05; use 0.04 research buffer.
DEFAULT_MIN_ACTIVATION_RATE_MULTIDAY: float = 0.04
# event_post: annualized scored events per code (earnings ~4/yr typical).
# 0.5 = at least half an event / code / year average across multi-year.
DEFAULT_MIN_EVENTS_PER_CODE_YEAR: float = 0.5
# event_post panel intensity: scored events / trading days (not code-days).
DEFAULT_MIN_EVENTS_PER_TRADING_DAY: float = 0.05
# multi-year: single-year share of sum(max(net,0)) must stay below this.
DEFAULT_MAX_YEAR_POS_NET_SHARE: float = 0.75
# research_candidate requires enough independent years (not count of events).
DEFAULT_MIN_YEARS_RESEARCH_CANDIDATE: int = 4
DEFAULT_TRADING_DAYS_PER_YEAR: int = 245

# ---------------------------------------------------------------------------
# W81 statistical bar (raise beyond mean bp) — period-net metrics
# ---------------------------------------------------------------------------
# |t| of period mean nets vs 0 (sample std). Below ~1.0 is noise with n≈6.
DEFAULT_MIN_ABS_T_STAT: float = 1.5
# Period Sharpe = mean/std of period nets (periods_per_year=1).
DEFAULT_MIN_SHARPE_PERIOD: float = 0.50
# Share of periods with net > 0 (yearly sign stability).
DEFAULT_MIN_PERIOD_WIN_RATE: float = 0.60
# Absolute positive-net year count.
DEFAULT_MIN_POSITIVE_PERIODS: int = 4

# Macro regime defaults (research placeholders; disclose when overridden)
# Repo rates in local JSDA are percent-like (e.g. 0.1 = 0.1%).
DEFAULT_REPO_HIGH_THRESHOLD: float = 0.05  # level above → high
DEFAULT_REPO_LOW_THRESHOLD: float = 0.0  # level below → low
DEFAULT_REPO_CHANGE_EPS: float = 1e-6

MACRO_CONDITIONED_DATASETS: tuple[str, ...] = (
    "equities_bars_daily",
    "markets_calendar",
    "indices_bars_daily_topix",
    "jsda_tokyo_repo_rates",
)
RATE_FACTOR_DATASETS: tuple[str, ...] = (
    "equities_bars_daily",
    "markets_calendar",
    "indices_bars_daily_topix",
    "jsda_tokyo_repo_rates",
)
MULTI_FACTOR_DATASETS: tuple[str, ...] = (
    "equities_bars_daily",
    "markets_calendar",
    "fins_summary",
    "jsda_tokyo_repo_rates",
    "markets_margin_interest",
)
EVENT_POST_DATASETS: tuple[str, ...] = (
    "fins_summary",
    "fins_earnings_date",  # W80 thicken event calendar when available
    "equities_bars_daily",
    "markets_calendar",
)
FLOW_DEMAND_DATASETS: tuple[str, ...] = (
    "markets_margin_interest",
    "markets_short_ratio",
    "equities_bars_daily",
    "markets_calendar",
)
FUNDAMENTALS_PRICE_DATASETS: tuple[str, ...] = (
    "fins_summary",
    "equities_bars_daily",
    "markets_calendar",
)
# W91 index-vol regime: equity CS book + index/futures vol proxy.
# Prefer NK225F continuous front realized vol; TOPIX fallback.
INDEX_VOL_REGIME_DATASETS: tuple[str, ...] = (
    "equities_bars_daily",
    "markets_calendar",
    "indices_bars_daily_topix",
    "indices_bars_daily",
    "derivatives_bars_daily_futures",
)

# W92 options vol regime: equity CS book + Nikkei 225 options SoT (COMPLETE).
# Canonical Nikkei vol = derivatives_bars_daily_options_225 (not TOPIX RV proxy).
OPTIONS_VOL_REGIME_DATASETS: tuple[str, ...] = (
    "equities_bars_daily",
    "markets_calendar",
    "derivatives_bars_daily_options_225",
)

# Default thresholds in percent vol points (J-Quants BaseVol / IV units).
DEFAULT_OPT225_VOL_HIGH_THRESHOLD: float = 24.0
DEFAULT_OPT225_VOL_LOW_THRESHOLD: float = 12.0
DEFAULT_OPT225_SPREAD_HIGH_THRESHOLD: float = 1.0
DEFAULT_OPT225_SPREAD_LOW_THRESHOLD: float = -0.5
DEFAULT_OPT225_SKEW_HIGH_THRESHOLD: float = 3.0
DEFAULT_OPT225_SKEW_LOW_THRESHOLD: float = 0.5
DEFAULT_OPT225_CM_TERM_HIGH_THRESHOLD: float = 2.0
DEFAULT_OPT225_CM_TERM_LOW_THRESHOLD: float = -1.0
DEFAULT_OPT225_BASEVOL_DELTA_HIGH_THRESHOLD: float = 1.0
DEFAULT_OPT225_BASEVOL_DELTA_LOW_THRESHOLD: float = -1.0
DEFAULT_OPT225_VOL_EXPAND_RATIO: float = 1.20
DEFAULT_OPT225_VOL_COMPRESS_RATIO: float = 0.80
OPT225_SPREAD_CONVENTION: str = "atm_iv - base_vol"


def _freeze_meta() -> dict[str, Any]:
    return {
        "mass_research": MASS_RESEARCH,
        "phase7": PHASE7,
        "ready_declared": READY_DECLARED,
        "order_execution": ORDER_EXECUTION,
        "s1_s5_unreject": S1_S5_UNREJECT,
        "simple_daily_sign": SIMPLE_DAILY_SIGN,
        "class_signals_version": CLASS_SIGNALS_VERSION,
        "wave": CLASS_SIGNALS_WAVE,
    }


from .class_signals_hold import (
    amortized_one_way_cost,
    apply_sticky_hold,
    compute_multi_day_hold_signal,
    multi_day_forward_return,
    sign_from_numeric,
)
from .class_signals_event_index import (
    compute_event_post_signal,
    earnings_surprise_proxy,
    event_post_available_at_from_fields,
    event_post_entry_bar_index,
    parse_disc_time_hhmmss,
    session_close_hhmmss,
)
from .class_signals_metrics import (
    economic_net_meaningful,
    multi_year_skew_check,
    occurrence_rate_event_post,
    occurrence_rate_multiday,
    production_candidate_bar,
)
from .class_signals_macro import (
    compute_macro_conditioned_signal,
    compute_rate_curve_xs_signal,
    compute_rate_level_xs_signal,
    condition_signal_on_regime,
    repo_regime_from_change,
    repo_regime_from_level,
)
from .class_signals_vol import (
    compute_nky_vol_abs_level_signal,
    compute_nky_vol_term_levels_signal,
    compute_nky_vol_term_ratio_signal,
    compute_opt225_atm_iv_abs_level_signal,
    compute_opt225_atm_iv_term_levels_signal,
    compute_opt225_atm_iv_term_ratio_signal,
    compute_opt225_basevol_abs_level_signal,
    compute_opt225_basevol_delta_abs_signal,
    compute_opt225_basevol_term_levels_signal,
    compute_opt225_basevol_term_ratio_signal,
    compute_opt225_cm_term_abs_level_signal,
    compute_opt225_iv_base_spread_abs_signal,
    compute_opt225_iv_base_spread_change_signal,
    compute_opt225_skew_abs_level_signal,
    compute_opt225_vol_signal,
    nky_vol_regime_from_abs_level,
    nky_vol_regime_from_term_levels,
    nky_vol_regime_from_term_ratio,
)
from .class_signals_flow_fund import (
    compute_cross_section_signal,
    compute_flow_demand_signal,
    compute_fundamentals_price_signal,
    compute_mf_flow_price_signal,
    compute_mf_value_mom_rate_signal,
    cross_section_rank_signs,
    fundamental_value_score,
)
from .class_signals_docs import (
    class_signal_definitions,
    class_signals_document,
)


__all__ = [
    "CANDIDATE_ONLY",
    "CLASS_CROSS_SECTION_RELATIVE",
    "CLASS_EVENT_POST",
    "CLASS_FLOW_DEMAND",
    "CLASS_FUNDAMENTALS_PRICE",
    "CLASS_MACRO_CONDITIONED",
    "CLASS_MULTI_DAY_HOLD",
    "CLASS_INDEX_VOL_REGIME",
    "CLASS_OPTIONS_VOL_REGIME",
    "CLASS_MULTI_FACTOR",
    "CLASS_RATE_FACTOR",
    "CLASS_SIGNALS_VERSION",
    "CLASS_SIGNALS_WAVE",
    "DEFAULT_EVENT_POST_HOLD_DAYS",
    "DEFAULT_FLOW_HOLD_DAYS",
    "EVENT_POST_ENTRY_MODE",
    "SESSION_CLOSE_CHANGE_DATE",
    "DEFAULT_FUND_HOLD_DAYS",
    "DEFAULT_FUND_MOMENTUM_N",
    "DEFAULT_HOLD_DAYS",
    "DEFAULT_MAX_YEAR_POS_NET_SHARE",
    "DEFAULT_MIN_ACTIVATION_RATE_MULTIDAY",
    "DEFAULT_MIN_ECONOMIC_NET",
    "DEFAULT_MIN_ABS_T_STAT",
    "DEFAULT_MIN_EVENTS_PER_CODE_YEAR",
    "DEFAULT_MIN_EVENTS_PER_TRADING_DAY",
    "DEFAULT_MIN_PERIOD_WIN_RATE",
    "DEFAULT_MIN_POSITIVE_PERIODS",
    "DEFAULT_MIN_SHARPE_PERIOD",
    "DEFAULT_MIN_YEARS_RESEARCH_CANDIDATE",
    "DEFAULT_CURVE_INVERT_THRESHOLD",
    "DEFAULT_CURVE_STEEP_THRESHOLD",
    "DEFAULT_NKY_VOL_COMPRESS_RATIO",
    "DEFAULT_NKY_VOL_EXPAND_RATIO",
    "DEFAULT_NKY_VOL_HIGH_THRESHOLD",
    "DEFAULT_NKY_VOL_LONG_N",
    "DEFAULT_NKY_VOL_LOW_THRESHOLD",
    "DEFAULT_NKY_VOL_SHORT_N",
    "DEFAULT_REPO_CHANGE_EPS",
    "DEFAULT_REPO_HIGH_THRESHOLD",
    "DEFAULT_REPO_LOW_THRESHOLD",
    "DEFAULT_TRADING_DAYS_PER_YEAR",
    "DISCLOSURE_FEATURE_ID",
    "EVENT_POST_DATASETS",
    "FLOW_DEMAND_DATASETS",
    "FUNDAMENTALS_PRICE_DATASETS",
    "FUNDAMENTAL_RATIO_FEATURE_ID",
    "INDEX_VOL_REGIME_DATASETS",
    "OPTIONS_VOL_REGIME_DATASETS",
    "MACRO_CONDITIONED_DATASETS",
    "MARGIN_CHANGE_FEATURE_ID",
    "MOMENTUM_FEATURE_ID",
    "MULTI_FACTOR_DATASETS",
    "NKY_VOL_ABS_FEATURE_ID",
    "NKY_VOL_PROXY_NK225F",
    "NKY_VOL_PROXY_TOPIX",
    "NKY_VOL_TERM_LEVELS_FEATURE_ID",
    "NKY_VOL_TERM_RATIO_FEATURE_ID",
    "OPT225_BASEVOL_FEATURE_ID",
    "OPT225_ATM_IV_FEATURE_ID",
    "OPT225_SPREAD_FEATURE_ID",
    "OPT225_SKEW_FEATURE_ID",
    "OPT225_CM_TERM_FEATURE_ID",
    "OPT225_BASEVOL_DELTA_FEATURE_ID",
    "OPT225_SPREAD_CONVENTION",
    "DEFAULT_OPT225_VOL_HIGH_THRESHOLD",
    "DEFAULT_OPT225_VOL_LOW_THRESHOLD",
    "DEFAULT_OPT225_SPREAD_HIGH_THRESHOLD",
    "DEFAULT_OPT225_SPREAD_LOW_THRESHOLD",
    "DEFAULT_OPT225_SKEW_HIGH_THRESHOLD",
    "DEFAULT_OPT225_SKEW_LOW_THRESHOLD",
    "DEFAULT_OPT225_CM_TERM_HIGH_THRESHOLD",
    "DEFAULT_OPT225_CM_TERM_LOW_THRESHOLD",
    "DEFAULT_OPT225_BASEVOL_DELTA_HIGH_THRESHOLD",
    "DEFAULT_OPT225_BASEVOL_DELTA_LOW_THRESHOLD",
    "DEFAULT_OPT225_VOL_EXPAND_RATIO",
    "DEFAULT_OPT225_VOL_COMPRESS_RATIO",
    "RATE_FACTOR_DATASETS",
    "REPO_CURVE_FEATURE_ID",
    "REPO_CURVE_LONG_TENOR",
    "REPO_CURVE_SHORT_TENOR",
    "REPO_RATE_FEATURE_ID",
    "SHORT_RATIO_FEATURE_ID",
    "SIGNAL_ID_CROSS_SECTION",
    "SIGNAL_ID_EVENT_POST",
    "SIGNAL_ID_FLOW_DEMAND",
    "SIGNAL_ID_FUNDAMENTALS_PRICE",
    "SIGNAL_ID_MACRO_CONDITIONED",
    "SIGNAL_ID_MF_FLOW_PRICE",
    "SIGNAL_ID_MF_VALUE_MOM_RATE",
    "SIGNAL_ID_MULTI_DAY_HOLD",
    "SIGNAL_ID_NKY_VOL_ABS_LEVEL",
    "SIGNAL_ID_NKY_VOL_TERM_LEVELS",
    "SIGNAL_ID_NKY_VOL_TERM_RATIO",
    "SIGNAL_ID_OPT225_BASEVOL_ABS",
    "SIGNAL_ID_OPT225_BASEVOL_TERM_LEVELS",
    "SIGNAL_ID_OPT225_BASEVOL_TERM_RATIO",
    "SIGNAL_ID_OPT225_ATM_IV_ABS",
    "SIGNAL_ID_OPT225_ATM_IV_TERM_LEVELS",
    "SIGNAL_ID_OPT225_ATM_IV_TERM_RATIO",
    "SIGNAL_ID_OPT225_SPREAD_ABS",
    "SIGNAL_ID_OPT225_SPREAD_CHANGE",
    "SIGNAL_ID_OPT225_SKEW_ABS",
    "SIGNAL_ID_OPT225_CM_TERM_ABS",
    "SIGNAL_ID_OPT225_BASEVOL_DELTA_ABS",
    "SIGNAL_ID_RATE_CURVE_XS",
    "SIGNAL_ID_RATE_LEVEL_XS",
    "SIGNAL_STATUS",
    "SIGNAL_VERSION",
    "SUPPORTED_HOLD_DAYS",
    "TRADING_DAY_FEATURE_ID",
    "TRADING_DAYS_ANN",
    "amortized_one_way_cost",
    "apply_sticky_hold",
    "class_signal_definitions",
    "class_signals_document",
    "compute_cross_section_signal",
    "compute_event_post_signal",
    "compute_flow_demand_signal",
    "compute_fundamentals_price_signal",
    "compute_macro_conditioned_signal",
    "compute_mf_flow_price_signal",
    "compute_mf_value_mom_rate_signal",
    "compute_multi_day_hold_signal",
    "compute_nky_vol_abs_level_signal",
    "compute_nky_vol_term_levels_signal",
    "compute_nky_vol_term_ratio_signal",
    "compute_opt225_vol_signal",
    "compute_opt225_basevol_abs_level_signal",
    "compute_opt225_basevol_term_levels_signal",
    "compute_opt225_basevol_term_ratio_signal",
    "compute_opt225_atm_iv_abs_level_signal",
    "compute_opt225_atm_iv_term_levels_signal",
    "compute_opt225_atm_iv_term_ratio_signal",
    "compute_opt225_iv_base_spread_abs_signal",
    "compute_opt225_iv_base_spread_change_signal",
    "compute_opt225_skew_abs_level_signal",
    "compute_opt225_cm_term_abs_level_signal",
    "compute_opt225_basevol_delta_abs_signal",
    "compute_rate_curve_xs_signal",
    "compute_rate_level_xs_signal",
    "condition_signal_on_regime",
    "cross_section_rank_signs",
    "earnings_surprise_proxy",
    "economic_net_meaningful",
    "event_post_available_at_from_fields",
    "nky_vol_regime_from_abs_level",
    "nky_vol_regime_from_term_levels",
    "nky_vol_regime_from_term_ratio",
    "event_post_entry_bar_index",
    "fundamental_value_score",
    "multi_day_forward_return",
    "multi_year_skew_check",
    "occurrence_rate_event_post",
    "occurrence_rate_multiday",
    "parse_disc_time_hhmmss",
    "production_candidate_bar",
    "repo_regime_from_change",
    "repo_regime_from_level",
    "session_close_hhmmss",
    "sign_from_numeric",
]
