"""Feature Registry — PIT-only, versioned, as_of-required feature compute.

The features package computes research features over Japanese-equity facts.
Hard rules (mirrors ``core/``):

* **Facts enter only via PIT.** Feature modules import :mod:`pit` for reads
  and nothing else that touches SQLite/HTTP. ``storage`` / ``sqlite3`` /
  HTTP clients are statically banned (see ``tests/test_features_data_boundary.py``).
* **Every compute call requires ``as_of``.** A feature value at ``as_of`` is
  computable ONLY from facts whose ``available_at <= as_of`` — look-ahead is
  structurally impossible because PIT enforces the gate.
* **Features are pure functions of (registry entry, as_of, inputs, pit reads).**
  No wall-clock time, no randomness; a feature is reproducible.

Quick example::

    from features import compute, registry
    feat = registry.get("return_1d")
    out = compute(feat, as_of="2025-04-03T15:30:00+09:00",
                  code="8697", db_path="data/structured/ingestion.sqlite")
    print(out.value, out.metadata)

See ``docs/features.md`` for the full contract.
"""

from __future__ import annotations

from .registry import (
    FEATURES_REGISTRY,
    FeatureDefinition,
    FeatureInput,
    FeatureOutput,
    FeatureVersion,
    IntendedRole,
    FeatureStatus,
    FeatureGovernanceError,
    feature_definition_digest,
    list_features,
    get,
    get_for_strategy,
    register,
)
from .runtime import compute, compute_many
from .v0 import (
    Return1d,
    MomentumN,
    RetrospectiveSplitAdjustedMomentumN,
    VolatilityN,
)
from .ratio_features import (
    FUNDAMENTAL_RATIO_MODES,
    PRICE_RATIO_MODES,
    PitFundamentalRatio,
    RetrospectivePriceRatio,
)
from .am_session_features import (
    AM_SESSION_FEATURE_IDS,
    AM_SESSION_FUNDAMENTAL_RATIO_ID,
    AM_SESSION_PRICE_RATIO_ID,
    AmSessionFundamentalRatio,
    AmSessionPriceRatio,
)
from .complete21_min import (
    VolumeChange1d,
    TopixRelative1d,
    DisclosureFlagFins,
    MarginInterestChange1d,
    ShortRatioLevel,
    IsTradingDay,
    RepoRateLevel,
    RepoRateChange,
    Return1dC21,
    MarginAlertFlag,
    FuturesActivityProxy,
    FundamentalValueScore,
    RetrospectiveSplitSafeFundamentalValueScore,
)
from .minimal_signal import (
    SIGNAL_ID as MINIMAL_SIGNAL_ID,
    SIGNAL_VERSION as MINIMAL_SIGNAL_VERSION,
    CANDIDATE_ONLY as MINIMAL_SIGNAL_CANDIDATE_ONLY,
    compute_signal_from_feature_observations,
    compute_topix_relative_sign_signal,
    signal_definition as minimal_signal_definition,
)
from .class_signals import (
    SIGNAL_ID_MULTI_DAY_HOLD,
    SIGNAL_ID_MACRO_CONDITIONED,
    SIGNAL_ID_CROSS_SECTION,
    SIGNAL_ID_EVENT_POST,
    SIGNAL_ID_FLOW_DEMAND,
    SIGNAL_ID_FUNDAMENTALS_PRICE,
    class_signal_definitions,
    class_signals_document,
    compute_multi_day_hold_signal,
    compute_macro_conditioned_signal,
    compute_cross_section_signal,
    compute_event_post_signal,
    compute_flow_demand_signal,
    compute_fundamentals_price_signal,
    apply_sticky_hold,
    economic_net_meaningful,
    occurrence_rate_multiday,
    occurrence_rate_event_post,
    multi_year_skew_check,
    production_candidate_bar,
)
from .dataset_guard import (
    COMPLETE_21_DATASETS,
    PermanentDeferHistoryError,
    filter_feature_datasets,
    require_feature_dataset,
    require_feature_datasets,
)

__all__ = [
    # registry
    "FEATURES_REGISTRY",
    "FeatureDefinition",
    "FeatureInput",
    "FeatureOutput",
    "FeatureVersion",
    "IntendedRole",
    "FeatureStatus",
    "FeatureGovernanceError",
    "feature_definition_digest",
    "list_features",
    "get",
    "get_for_strategy",
    "register",
    # runtime
    "compute",
    "compute_many",
    # built-in features (v0)
    "Return1d",
    "MomentumN",
    "RetrospectiveSplitAdjustedMomentumN",
    "VolatilityN",
    "FUNDAMENTAL_RATIO_MODES",
    "PRICE_RATIO_MODES",
    "PitFundamentalRatio",
    "RetrospectivePriceRatio",
    "AM_SESSION_FEATURE_IDS",
    "AM_SESSION_FUNDAMENTAL_RATIO_ID",
    "AM_SESSION_PRICE_RATIO_ID",
    "AmSessionFundamentalRatio",
    "AmSessionPriceRatio",
    # COMPLETE 21 min features (candidate)
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
    "RetrospectiveSplitSafeFundamentalValueScore",
    # minimal signal (W52 candidate-only; no mass / READY / orders)
    "MINIMAL_SIGNAL_ID",
    "MINIMAL_SIGNAL_VERSION",
    "MINIMAL_SIGNAL_CANDIDATE_ONLY",
    "compute_signal_from_feature_observations",
    "compute_topix_relative_sign_signal",
    "minimal_signal_definition",
    # class signals (W78–W81; not simple daily sign; W81 stats bar)
    "SIGNAL_ID_MULTI_DAY_HOLD",
    "SIGNAL_ID_MACRO_CONDITIONED",
    "SIGNAL_ID_CROSS_SECTION",
    "SIGNAL_ID_EVENT_POST",
    "SIGNAL_ID_FLOW_DEMAND",
    "SIGNAL_ID_FUNDAMENTALS_PRICE",
    "class_signal_definitions",
    "class_signals_document",
    "compute_multi_day_hold_signal",
    "compute_macro_conditioned_signal",
    "compute_cross_section_signal",
    "compute_event_post_signal",
    "compute_flow_demand_signal",
    "compute_fundamentals_price_signal",
    "apply_sticky_hold",
    "economic_net_meaningful",
    "occurrence_rate_multiday",
    "occurrence_rate_event_post",
    "multi_year_skew_check",
    "production_candidate_bar",
    # dataset guards
    "COMPLETE_21_DATASETS",
    "PermanentDeferHistoryError",
    "filter_feature_datasets",
    "require_feature_dataset",
    "require_feature_datasets",
    # version
    "__version__",
]

__version__ = "0.8.0"
