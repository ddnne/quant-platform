"""Minimal COMPLETE-21-only features (W49–W57 / w0815ax_g3).

All features:

* declare required datasets from COMPLETE 21 only;
* call :func:`require_feature_datasets` (permanent DEFER fail-closed) before
  any PIT read.

Promotion:

* W52 / w0815as_g1: ``is_trading_day``, ``volume_change_1d`` → approved
  (version pin ``1.0.0``).
* W53 / w0815at_g1 O2 re-eval: ``topix_relative_1d``, ``disclosure_flag_fins``,
  ``margin_interest_change_1d`` → approved (version pin ``1.0.0``) after
  feature-level CF tip E2E non-null proof.
* W54 / w0815au_g2 selective O2: ``repo_rate_level`` → approved (version pin
  ``1.0.0``) after CF tip E2E non-null on D1 ``jsda_repo_rates`` hot tip.
* W55 / w0815av_g2 selective O2: ``short_ratio_level`` → approved (version pin
  ``1.0.0``) after CF tip E2E non-null with valid S33 ``section`` path.
* W56 / w0815aw_g3 optional O2: ``futures_activity_proxy`` → approved (version
  pin ``1.0.0``) after CF tip E2E non-null on D1
  ``derivatives_bars_daily_futures``.
* W57 / w0815ax_g3 optional O2: ``margin_alert_flag`` → approved (version pin
  ``1.0.0``) after CF tip E2E non-null on D1 ``markets_margin_alert``.
  ``return_1d_c21`` remains candidate (policy twin of v0 ``return_1d``).
  Remaining 1 stays candidate (``return_1d_c21``).
* No READY / Mass / Phase7 claim. ``get_for_strategy`` still admits only
  approved + strategy-facing roles (utility requires explicit role override).

Implemented (W49–W50, 7):

* ``volume_change_1d`` — one-session volume change from equity daily bars.
* ``topix_relative_1d`` — equity 1d return minus TOPIX 1d return.
* ``disclosure_flag_fins`` — binary flag if any ``fins_summary`` row is visible.
* ``fundamental_value_score`` — PIT BPS/P or EPS/P from ``fins_summary`` + close
  (W84 / w0816s; approved for StrategySpec fund value×mom).
* ``margin_interest_change_1d`` — session-over-session margin interest change.
* ``short_ratio_level`` — short-sale ratio level for a sector (S33).
* ``is_trading_day`` — calendar utility: 1.0 if ``date`` is a trading day.
* ``repo_rate_level`` — latest Tokyo repo rate level (JSDA).
* ``repo_rate_change`` — lookback change in Tokyo repo rate (JSDA; W78
  macro_conditioned support; **candidate**).

Implemented (W51 expand, +3):

* ``return_1d_c21`` — complete21-path export of the 1d simple-return formula
  (``require_feature_datasets`` + bars). Does **not** replace approved v0
  ``return_1d``; stays ``candidate`` (W54 T8 policy: no promote).
* ``margin_alert_flag`` — binary flag if any ``markets_margin_alert`` row is
  PIT-visible for ``code``.
* ``futures_activity_proxy`` — sum of latest-session futures volumes from
  ``derivatives_bars_daily_futures`` (optional contract ``code`` filter).

Approved v0 ``return_1d`` remains in ``features.v0`` (DEFER-guarded via
``get_equity_bars_daily``).
"""

from __future__ import annotations

from .complete21_min_compute import (
    _CALENDAR_DATASETS,
    _DISC_DATASETS,
    _FUND_VALUE_DATASETS,
    _FUTURES_DATASETS,
    _MARGIN_ALERT_DATASETS,
    _MARGIN_DATASETS,
    _REPO_DATASETS,
    _RETURN_C21_DATASETS,
    _SHORT_RATIO_DATASETS,
    _TOPIX_REL_DATASETS,
    _VOLUME_DATASETS,
    _disclosure_flag_fins,
    _fundamental_value_score,
    _futures_activity_proxy,
    _is_trading_day,
    _margin_alert_flag,
    _margin_interest_change_1d,
    _repo_rate_change,
    _repo_rate_level,
    _return_1d_c21,
    _short_ratio_level,
    _topix_relative_1d,
    _volume_change_1d,
    disclosure_flag_from_count,
    futures_activity_from_volume_pairs,
    fundamental_value_score_from_parts,
    is_trading_day_from_division,
    margin_alert_flag_from_count,
    margin_interest_change_from_pairs,
    repo_rate_change_from_rows,
    repo_rate_level_from_rows,
    short_ratio_level_from_components,
    simple_return_from_closes,
    topix_relative_from_returns,
    volume_change_from_pairs,
)
from .complete21_min_parsers import (
    _as_float_or_none,
    _latest_fins_eps_bps,
    _latest_short_ratio_row,
    _parse_close_rows,
    _parse_futures_volume_rows,
    _parse_margin_interest_rows,
    _parse_volume_rows,
    _row_payload,
)
from .complete21_min_register import (
    DisclosureFlagFins,
    FundamentalValueScore,
    FuturesActivityProxy,
    IsTradingDay,
    MarginAlertFlag,
    MarginInterestChange1d,
    RepoRateChange,
    RepoRateLevel,
    Return1dC21,
    ShortRatioLevel,
    TopixRelative1d,
    VolumeChange1d,
)


__all__ = [
    "VolumeChange1d",
    "TopixRelative1d",
    "DisclosureFlagFins",
    "MarginInterestChange1d",
    "ShortRatioLevel",
    "IsTradingDay",
    "RepoRateLevel",
    "RepoRateChange",
    "Return1dC21",
    "MarginAlertFlag",
    "FuturesActivityProxy",
    "FundamentalValueScore",
    "volume_change_from_pairs",
    "simple_return_from_closes",
    "topix_relative_from_returns",
    "disclosure_flag_from_count",
    "margin_interest_change_from_pairs",
    "short_ratio_level_from_components",
    "is_trading_day_from_division",
    "repo_rate_level_from_rows",
    "repo_rate_change_from_rows",
    "margin_alert_flag_from_count",
    "futures_activity_from_volume_pairs",
    "fundamental_value_score_from_parts",
]
