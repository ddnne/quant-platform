"""Offline multi-year class-hypothesis eval (W78–W83).

Runs class research signals over local bar mirrors + local SQLite
(``jsda_repo_rates``, ``fins_summary``, ``fins_earnings_date``, margin/short),
then feeds cost-aware robustness gate + checklist v2 + economic-net +
**occurrence-rate** + **W81 statistical bar** (t-stat / Sharpe / win-rate)
production candidate bar.

Classes covered
---------------
* multi_day_hold · multi_day_hold_10 · macro_conditioned · cross_section_relative
* cross_section sticky hold=10 (W83 default path when enabled)
* event_post (PIT DiscDate+DiscTime only; no look-ahead revival)
* flow_demand · fundamentals_price

Hard constraints
----------------
* Not simple_daily_sign · no S1–S5 un-reject
* Not READY / Mass / Phase7 / orders
* No invent fill on repo / fins / margin / liquidity gaps
* W81+: ``research_candidate=True`` only when production bar fully met
  including |t| / Sharpe / period win-rate (still never auto-connects
  Mass / READY / operational GO)
* W86+: sign flip both-sides after cost for default/main explore
  (xs hold10 mom5/mom3 · fund hold10); record ``chosen_sign``;
  both near-zero / non-positive → reject or explore demote
* No mean-bp-only promotion
* weak consistent-negative is **not_candidate** (economic net bar)
* noisy low t/Sharpe / unstable yearly signs → demote to discussion_only
* Event sufficiency = occurrence **rate** (not absolute count alone);
  short window with OK rate → extend and re-eval
* event_post entry = W82 PIT first non-look-ahead session close

Runner body lives in ``research.offline.multiyear`` (re-exported here).
"""

from __future__ import annotations

from features.class_signals import (
    DEFAULT_MAX_YEAR_POS_NET_SHARE,
    DEFAULT_MIN_ABS_T_STAT,
    DEFAULT_MIN_ACTIVATION_RATE_MULTIDAY,
    DEFAULT_MIN_ECONOMIC_NET,
    DEFAULT_MIN_EVENTS_PER_CODE_YEAR,
    DEFAULT_MIN_EVENTS_PER_TRADING_DAY,
    DEFAULT_MIN_PERIOD_WIN_RATE,
    DEFAULT_MIN_POSITIVE_PERIODS,
    DEFAULT_MIN_SHARPE_PERIOD,
    DEFAULT_MIN_YEARS_RESEARCH_CANDIDATE,
)
from research.eval_tracks import (
    EVAL_TRACK_LIQ_LARGE,
    EVAL_TRACK_MID_N,
    EVAL_TRACKS,
    eval_track,
    infer_eval_track,
)
from research.eval_universe import (
    DEFAULT_SQLITE,
    EVAL_UNIVERSE_POOL,
    UNIVERSE_SELECT_RULE,
    load_bars_from_sqlite_rich,
    load_fins_events_from_sqlite,
    rank_eval_codes,
    select_eval_universe,
)
from research.eval_loaders import (
    DEFAULT_BARS_FULL_MIRROR_DIR,
    DEFAULT_BARS_MIRROR_DIR,
    bars_rich_to_close_panel,
    build_nky_vol_series,
    build_repo_curve_series,
    collect_liquidity_bar_rows,
    fins_asof,
    fins_summary_ta_eqar_stats,
    load_bars_ndjson,
    load_bars_ndjson_rich,
    load_fins_earnings_date_from_sqlite,
    load_margin_from_sqlite,
    load_margin_ndjson,
    load_nk225f_front_close_series_from_sqlite,
    load_nky_vol_series_from_sqlite,
    load_repo_rows_all_tenors_from_sqlite,
    load_repo_rows_from_sqlite,
    load_short_ratio_series_from_sqlite,
    load_topix_close_series_from_sqlite,
    merge_event_calendars,
    momentum_series,
    repo_history_plane_status,
    resolve_bars_path,
    resolve_margin_path,
)
from research.eval_windows import DEFAULT_PERIODS, DEFAULT_PERIODS_Q4
from research.offline.bar_eval import (
    evaluate_cross_section_on_bars,
    evaluate_event_post_on_bars,
    evaluate_flow_demand_on_bars,
    evaluate_fundamentals_price_on_bars,
    evaluate_macro_conditioned_on_bars,
    evaluate_mf_flow_price_on_bars,
    evaluate_mf_value_mom_rate_on_bars,
    evaluate_multi_day_hold_on_bars,
    evaluate_nky_vol_abs_level_on_bars,
    evaluate_nky_vol_term_levels_on_bars,
    evaluate_nky_vol_term_ratio_on_bars,
    evaluate_opt225_vol_on_bars,
    evaluate_rate_curve_xs_on_bars,
    evaluate_rate_level_xs_on_bars,
)
from research.offline.multiyear import run_class_hyp_multi_year_eval
from research.sign_selection import (
    sign_selection_document,
    sign_selection_from_period_rows,
)

# ---------------------------------------------------------------------------
# Freeze / identity
# ---------------------------------------------------------------------------

CLASS_HYP_EVAL_VERSION: str = "class-hyp-eval/v7"
CLASS_HYP_EVAL_WAVE: str = "W86 / w0816u"
# Economic net bar (research): weak consistent-negative never candidate.
MIN_ECONOMIC_NET: float = DEFAULT_MIN_ECONOMIC_NET
MIN_ACTIVATION_RATE_MULTIDAY: float = DEFAULT_MIN_ACTIVATION_RATE_MULTIDAY
MIN_EVENTS_PER_CODE_YEAR: float = DEFAULT_MIN_EVENTS_PER_CODE_YEAR
MIN_EVENTS_PER_TRADING_DAY: float = DEFAULT_MIN_EVENTS_PER_TRADING_DAY
MIN_YEARS_RESEARCH_CANDIDATE: int = DEFAULT_MIN_YEARS_RESEARCH_CANDIDATE
MAX_YEAR_POS_NET_SHARE: float = DEFAULT_MAX_YEAR_POS_NET_SHARE
# W81 statistical bar floors (period nets).
MIN_ABS_T_STAT: float = DEFAULT_MIN_ABS_T_STAT
MIN_SHARPE_PERIOD: float = DEFAULT_MIN_SHARPE_PERIOD
MIN_PERIOD_WIN_RATE: float = DEFAULT_MIN_PERIOD_WIN_RATE
MIN_POSITIVE_PERIODS: int = DEFAULT_MIN_POSITIVE_PERIODS


__all__ = [
    "CLASS_HYP_EVAL_VERSION",
    "CLASS_HYP_EVAL_WAVE",
    "DEFAULT_BARS_FULL_MIRROR_DIR",
    "DEFAULT_BARS_MIRROR_DIR",
    "EVAL_UNIVERSE_POOL",
    "UNIVERSE_SELECT_RULE",
    "EVAL_TRACKS",
    "EVAL_TRACK_MID_N",
    "EVAL_TRACK_LIQ_LARGE",
    "eval_track",
    "infer_eval_track",
    "rank_eval_codes",
    "select_eval_universe",
    "DEFAULT_PERIODS",
    "DEFAULT_PERIODS_Q4",
    "DEFAULT_SQLITE",
    "MAX_YEAR_POS_NET_SHARE",
    "MIN_ABS_T_STAT",
    "MIN_ACTIVATION_RATE_MULTIDAY",
    "MIN_ECONOMIC_NET",
    "MIN_EVENTS_PER_CODE_YEAR",
    "MIN_EVENTS_PER_TRADING_DAY",
    "MIN_PERIOD_WIN_RATE",
    "MIN_POSITIVE_PERIODS",
    "MIN_SHARPE_PERIOD",
    "MIN_YEARS_RESEARCH_CANDIDATE",
    "bars_rich_to_close_panel",
    "collect_liquidity_bar_rows",
    "fins_summary_ta_eqar_stats",
    "load_bars_from_sqlite_rich",
    "build_nky_vol_series",
    "build_repo_curve_series",
    "evaluate_cross_section_on_bars",
    "evaluate_event_post_on_bars",
    "evaluate_flow_demand_on_bars",
    "evaluate_fundamentals_price_on_bars",
    "evaluate_macro_conditioned_on_bars",
    "evaluate_mf_flow_price_on_bars",
    "evaluate_mf_value_mom_rate_on_bars",
    "evaluate_multi_day_hold_on_bars",
    "evaluate_nky_vol_abs_level_on_bars",
    "evaluate_nky_vol_term_levels_on_bars",
    "evaluate_nky_vol_term_ratio_on_bars",
    "evaluate_opt225_vol_on_bars",
    "evaluate_rate_curve_xs_on_bars",
    "evaluate_rate_level_xs_on_bars",
    "fins_asof",
    "load_bars_ndjson",
    "load_bars_ndjson_rich",
    "load_fins_earnings_date_from_sqlite",
    "load_fins_events_from_sqlite",
    "load_margin_from_sqlite",
    "load_margin_ndjson",
    "load_nk225f_front_close_series_from_sqlite",
    "load_nky_vol_series_from_sqlite",
    "load_repo_rows_all_tenors_from_sqlite",
    "load_repo_rows_from_sqlite",
    "repo_history_plane_status",
    "load_short_ratio_series_from_sqlite",
    "load_topix_close_series_from_sqlite",
    "merge_event_calendars",
    "momentum_series",
    "resolve_bars_path",
    "resolve_margin_path",
    "run_class_hyp_multi_year_eval",
    "sign_selection_document",
    "sign_selection_from_period_rows",
]
