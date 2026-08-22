"""Minimal COMPLETE-21-only features (W49–W57 / w0815ax_g3).

Dataset tuples are COMPLETE 21 only. Permanent DEFER is fail-closed in
compute. ``return_1d_c21`` stays candidate (twin of v0 ``return_1d``).
No READY / Mass / GO. Catalog registration lives in
``complete21_min_register``.
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
    disclosure_flag_from_count,
    futures_activity_from_volume_pairs,
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
]
