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
    list_features,
    get,
    get_for_strategy,
    register,
)
from .runtime import compute, compute_many
from .v0 import (
    Return1d,
    MomentumN,
    VolatilityN,
)
from .complete21_min import (
    VolumeChange1d,
    TopixRelative1d,
    DisclosureFlagFins,
    MarginInterestChange1d,
    ShortRatioLevel,
    IsTradingDay,
    RepoRateLevel,
    Return1dC21,
    MarginAlertFlag,
    FuturesActivityProxy,
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
    "VolatilityN",
    # COMPLETE 21 min features (candidate)
    "VolumeChange1d",
    "TopixRelative1d",
    "DisclosureFlagFins",
    "MarginInterestChange1d",
    "ShortRatioLevel",
    "IsTradingDay",
    "RepoRateLevel",
    "Return1dC21",
    "MarginAlertFlag",
    "FuturesActivityProxy",
    # dataset guards
    "COMPLETE_21_DATASETS",
    "PermanentDeferHistoryError",
    "filter_feature_datasets",
    "require_feature_dataset",
    "require_feature_datasets",
    # version
    "__version__",
]

__version__ = "0.6.0"
