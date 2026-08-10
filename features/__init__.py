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
    list_features,
    get,
    register,
)
from .runtime import compute, compute_many
from .v0 import (
    Return1d,
    MomentumN,
    VolatilityN,
)

__all__ = [
    # registry
    "FEATURES_REGISTRY",
    "FeatureDefinition",
    "FeatureInput",
    "FeatureOutput",
    "FeatureVersion",
    "list_features",
    "get",
    "register",
    # runtime
    "compute",
    "compute_many",
    # built-in features
    "Return1d",
    "MomentumN",
    "VolatilityN",
    # version
    "__version__",
    "LIVE_GATES",
    "measure_b0",
    "b0_pass",
]

__version__ = "0.4.0"

from .live_gates import LIVE_GATES, measure_b0, b0_pass  # noqa: E402
