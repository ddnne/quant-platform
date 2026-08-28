"""COMPLETE-21 min FeatureDefinition registration.

Importing this module registers the catalog. Status and version pins are
unchanged. No READY / Mass / GO. Permanent DEFER is enforced in compute.
"""

from __future__ import annotations

from price_basis import PERSONAL_RETROSPECTIVE_ADJUSTED, RAW

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
    _retrospective_split_safe_fundamental_value_score,
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
            "One-session volume change from equities_bars_daily. "
            "None with fewer than two PIT-visible volumes. Permanent DEFER rejected."
        ),
        compute=_volume_change_1d,
        dataset_dependencies=_VOLUME_DATASETS,
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
            "(equities_bars_daily + indices_bars_daily_topix). Permanent DEFER rejected."
        ),
        compute=_topix_relative_1d,
        dataset_dependencies=_TOPIX_REL_DATASETS,
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
            "exists for code at as_of, else 0.0. Permanent DEFER rejected."
        ),
        compute=_disclosure_flag_fins,
        dataset_dependencies=_DISC_DATASETS,
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
            "(LongVol + ShrtVol). None with <2 PIT-visible observations. "
            "Permanent DEFER rejected."
        ),
        compute=_margin_interest_change_1d,
        dataset_dependencies=_MARGIN_DATASETS,
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
            "Latest TSE 33-sector short-sale ratio: "
            "(ShrtWithResVa + ShrtNoResVa) / SellExShortVa. Permanent DEFER rejected."
        ),
        compute=_short_ratio_level,
        dataset_dependencies=_SHORT_RATIO_DATASETS,
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
            "1.0 if markets_calendar holiday_division=='1', 0.0 if non-trading, "
            "None if no PIT-visible row. Default date = as_of calendar day. "
            "Permanent DEFER rejected."
        ),
        compute=_is_trading_day,
        dataset_dependencies=_CALENDAR_DATASETS,
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
            "Latest Tokyo repo rate level at as_of (JSDA). Optional tenor / "
            "rate_type filters. Permanent DEFER rejected."
        ),
        compute=_repo_rate_level,
        dataset_dependencies=_REPO_DATASETS,
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
            "(JSDA). Candidate until feature E2E promotion. Permanent DEFER rejected."
        ),
        compute=_repo_rate_change,
        dataset_dependencies=_REPO_DATASETS,
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
            "COMPLETE-21 close-to-close simple return from equities_bars_daily. "
            "Candidate twin of approved v0 return_1d; does not replace it."
        ),
        compute=_return_1d_c21,
        dataset_dependencies=_RETURN_C21_DATASETS,
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
            "Permanent DEFER rejected."
        ),
        compute=_margin_alert_flag,
        dataset_dependencies=_MARGIN_ALERT_DATASETS,
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
            "Sum of Volume on the latest PIT-visible date from "
            "derivatives_bars_daily_futures. Optional contract code filter. "
            "None when no volumes are visible. Permanent DEFER rejected."
        ),
        compute=_futures_activity_proxy,
        dataset_dependencies=_FUTURES_DATASETS,
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
        dataset_dependencies=_FUND_VALUE_DATASETS,
        tags=("fundamentals", "value", "fins", "complete21"),
        intended_role="signal",
        status="approved",
        price_basis=RAW,
    )
)


RetrospectiveSplitSafeFundamentalValueScore: FeatureDefinition = register(
    FeatureDefinition(
        id="retrospective_split_safe_fundamental_value_score",
        version=FeatureVersion(1, 0, 0),
        inputs=FeatureInput(
            required_kwargs=("code",),
            as_of_rule="session_close",
        ),
        description=(
            "Raw BPS/price (or EPS/price) with a retrospective vendor split "
            "factor and adjusted-price continuity blackout from the selected "
            "statement anchor. Local DRAFT only; not PIT or live eligible."
        ),
        compute=_retrospective_split_safe_fundamental_value_score,
        dataset_dependencies=_FUND_VALUE_DATASETS,
        tags=("fundamentals", "value", "split-safe", "retrospective", "personal"),
        intended_role="signal",
        status="approved",
        price_basis=PERSONAL_RETROSPECTIVE_ADJUSTED,
    )
)
