"""COMPLETE-21 min FeatureDefinition registration.

Importing this module registers the catalog. Status and version pins are
unchanged. No READY / Mass / GO. Permanent DEFER is enforced in compute.
"""

from __future__ import annotations

from price_basis import RAW

from .complete21_min_compute import (
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
)
from .registry import register
from .types import FeatureDefinition, FeatureInput, FeatureVersion


VolumeChange1d: FeatureDefinition = register(
    FeatureDefinition(
        id="volume_change_1d",
        version=FeatureVersion(1, 0, 0),
        inputs=FeatureInput(
            required_kwargs=("code",),
            as_of_rule="session_close",
        ),
        description=(
            "One-session volume change (COMPLETE 21: equities_bars_daily only). "
            "Returns None when fewer than two volumes are visible at as_of. "
            "Permanent DEFER datasets are rejected before PIT reads."
        ),
        compute=_volume_change_1d,
        tags=("volume", "daily", "complete21"),
        intended_role="signal",
        status="approved",
        price_basis=None,
    )
)


TopixRelative1d: FeatureDefinition = register(
    FeatureDefinition(
        id="topix_relative_1d",
        version=FeatureVersion(1, 0, 0),
        inputs=FeatureInput(
            required_kwargs=("code",),
            as_of_rule="session_close",
        ),
        description=(
            "Equity 1d return minus TOPIX 1d return "
            "(COMPLETE 21: equities_bars_daily + indices_bars_daily_topix). "
            "Permanent DEFER datasets are rejected before PIT reads."
        ),
        compute=_topix_relative_1d,
        tags=("return", "relative", "topix", "complete21"),
        intended_role="signal",
        status="approved",
        price_basis=RAW,
    )
)


DisclosureFlagFins: FeatureDefinition = register(
    FeatureDefinition(
        id="disclosure_flag_fins",
        version=FeatureVersion(1, 0, 0),
        inputs=FeatureInput(
            required_kwargs=("code",),
            as_of_rule="session_close",
        ),
        description=(
            "Binary disclosure flag: 1.0 if any PIT-visible fins_summary row "
            "exists for code at as_of, else 0.0. COMPLETE 21 only "
            "(fins_summary). Permanent DEFER residuals excluded from this feature."
        ),
        compute=_disclosure_flag_fins,
        tags=("disclosure", "fins", "flag", "complete21"),
        intended_role="signal",
        status="approved",
        price_basis=None,
    )
)


MarginInterestChange1d: FeatureDefinition = register(
    FeatureDefinition(
        id="margin_interest_change_1d",
        version=FeatureVersion(1, 0, 0),
        inputs=FeatureInput(
            required_kwargs=("code",),
            as_of_rule="session_close",
        ),
        description=(
            "Session-over-session change in total margin interest "
            "(LongVol + ShrtVol) for code. COMPLETE 21: markets_margin_interest. "
            "Returns None with <2 PIT-visible observations. Permanent DEFER "
            "datasets are rejected before PIT reads."
        ),
        compute=_margin_interest_change_1d,
        tags=("margin", "interest", "complete21"),
        intended_role="signal",
        status="approved",
        price_basis=None,
    )
)


ShortRatioLevel: FeatureDefinition = register(
    FeatureDefinition(
        id="short_ratio_level",
        version=FeatureVersion(1, 0, 0),
        inputs=FeatureInput(
            required_kwargs=("section",),
            as_of_rule="session_close",
        ),
        description=(
            "Latest short-sale ratio level for a TSE 33-sector (S33): "
            "(ShrtWithResVa + ShrtNoResVa) / SellExShortVa. COMPLETE 21: "
            "markets_short_ratio. Permanent DEFER datasets rejected before "
            "PIT reads."
        ),
        compute=_short_ratio_level,
        tags=("short", "ratio", "sector", "complete21"),
        intended_role="signal",
        status="approved",
        price_basis=None,
    )
)


IsTradingDay: FeatureDefinition = register(
    FeatureDefinition(
        id="is_trading_day",
        version=FeatureVersion(1, 0, 0),
        inputs=FeatureInput(
            required_kwargs=(),
            optional_kwargs={"date": None},
            as_of_rule="session_close",
        ),
        description=(
            "Structural/utility flag: 1.0 if markets_calendar marks date as a "
            "trading day (holiday_division=='1'), 0.0 if non-trading, None if "
            "no calendar row is PIT-visible. Default date = as_of calendar day. "
            "COMPLETE 21: markets_calendar. Permanent DEFER rejected."
        ),
        compute=_is_trading_day,
        tags=("calendar", "trading_day", "complete21"),
        intended_role="utility",
        status="approved",
        price_basis=None,
    )
)


RepoRateLevel: FeatureDefinition = register(
    FeatureDefinition(
        id="repo_rate_level",
        version=FeatureVersion(1, 0, 0),
        inputs=FeatureInput(
            required_kwargs=(),
            optional_kwargs={"tenor": None, "rate_type": None},
            as_of_rule="session_close",
        ),
        description=(
            "Latest Tokyo repo rate level visible at as_of (JSDA). COMPLETE 21: "
            "jsda_tokyo_repo_rates. Optional tenor / rate_type filters. "
            "Permanent DEFER datasets rejected before PIT reads."
        ),
        compute=_repo_rate_level,
        tags=("repo", "rate", "jsda", "macro", "complete21"),
        intended_role="state",
        status="approved",
        price_basis=None,
    )
)


RepoRateChange: FeatureDefinition = register(
    FeatureDefinition(
        id="repo_rate_change",
        version=FeatureVersion(1, 0, 0),
        inputs=FeatureInput(
            required_kwargs=(),
            optional_kwargs={"lookback": 5, "tenor": None, "rate_type": None},
            as_of_rule="session_close",
        ),
        description=(
            "Change in Tokyo repo rate over lookback distinct as_of_date steps "
            "(JSDA). COMPLETE dataset jsda_tokyo_repo_rates. Candidate until "
            "feature E2E promotion. Permanent DEFER rejected."
        ),
        compute=_repo_rate_change,
        tags=("repo", "rate", "jsda", "macro", "change", "complete21"),
        intended_role="state",
        status="candidate",
        price_basis=None,
    )
)


Return1dC21: FeatureDefinition = register(
    FeatureDefinition(
        id="return_1d_c21",
        version=FeatureVersion(1, 0, 0),
        inputs=FeatureInput(
            required_kwargs=("code",),
            as_of_rule="session_close",
        ),
        description=(
            "COMPLETE-21 path export of one-session simple return "
            "(close-to-close) from equities_bars_daily. Calls "
            "require_feature_datasets before PIT reads. Candidate twin of "
            "approved v0 return_1d — does not replace it; no promotion this wave."
        ),
        compute=_return_1d_c21,
        tags=("return", "daily", "complete21", "export"),
        intended_role="signal",
        status="candidate",
        price_basis=RAW,
    )
)


MarginAlertFlag: FeatureDefinition = register(
    FeatureDefinition(
        id="margin_alert_flag",
        version=FeatureVersion(1, 0, 0),
        inputs=FeatureInput(
            required_kwargs=("code",),
            as_of_rule="session_close",
        ),
        description=(
            "Binary margin-alert flag: 1.0 if any PIT-visible "
            "markets_margin_alert row exists for code at as_of, else 0.0. "
            "COMPLETE 21 only. Permanent DEFER datasets rejected before PIT reads."
        ),
        compute=_margin_alert_flag,
        tags=("margin", "alert", "flag", "complete21"),
        intended_role="signal",
        status="approved",
        price_basis=None,
    )
)


FuturesActivityProxy: FeatureDefinition = register(
    FeatureDefinition(
        id="futures_activity_proxy",
        version=FeatureVersion(1, 0, 0),
        inputs=FeatureInput(
            required_kwargs=(),
            optional_kwargs={"code": None},
            as_of_rule="session_close",
        ),
        description=(
            "Futures activity proxy: sum of Volume on the latest PIT-visible "
            "date from derivatives_bars_daily_futures. Optional contract code "
            "filter. Returns None when no volumes are visible. COMPLETE 21 only. "
            "Permanent DEFER datasets rejected before PIT reads."
        ),
        compute=_futures_activity_proxy,
        tags=("futures", "derivatives", "activity", "complete21"),
        intended_role="state",
        status="approved",
        price_basis=None,
    )
)


FundamentalValueScore: FeatureDefinition = register(
    FeatureDefinition(
        id="fundamental_value_score",
        version=FeatureVersion(1, 0, 0),
        inputs=FeatureInput(
            required_kwargs=("code",),
            as_of_rule="session_close",
        ),
        description=(
            "PIT fundamental value score: BPS/price preferred, else EPS/price, "
            "from fins_summary + equities_bars_daily close at as_of. Not READY."
        ),
        compute=_fundamental_value_score,
        tags=("fundamentals", "value", "fins", "complete21"),
        intended_role="signal",
        status="approved",
        price_basis=RAW,
    )
)
