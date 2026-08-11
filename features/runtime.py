"""Feature compute runtime — pure, PIT-only, ``as_of``-required.

:func:`compute` is the single entry point. It:

1. Resolves the feature definition from the registry.
2. Validates that ``as_of`` was supplied (hard requirement — no default).
3. Validates required inputs are present.
4. Builds a :class:`FeatureContext` whose PIT getters are scoped to ``as_of``.
5. Calls ``feature.compute(ctx)`` and augments the returned metadata.

The compute function sees only the context; it has no access to ``db_path``,
no connection, no wall-clock time. Facts enter only via the context's
``pit.get_*`` shortcuts, which add ``as_of`` and ``db_path`` automatically.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

import pit
from pit.query import resolve_db_path

from . import registry as _registry
from .types import FeatureDefinition, FeatureOutput

FEATURES_RUNTIME_VERSION = "0.6.0"


class AsOfRequired(ValueError):
    """Raised when a feature compute call omits ``as_of``."""


class MissingInput(KeyError):
    """Raised when a required input is missing on a compute call."""


@dataclass(frozen=True)
class FeatureContext:
    """Read-only PIT-scoped context handed to a feature's ``compute``.

    The ``get_equity_bars_daily`` / ``get_equity_master`` /
    ``get_market_calendar`` shortcuts already inject ``as_of`` and
    ``db_path`` — the feature code simply reads. There is no handle to the
    underlying SQLite DB, no HTTP client, and no wall-clock time.
    """

    as_of: str
    db_path: Any
    inputs: Mapping[str, Any]

    def get_equity_bars_daily(self, **kwargs: Any):
        """PIT daily bars — ``as_of`` and ``db_path`` injected."""
        return pit.get_equity_bars_daily(as_of=self.as_of, db_path=self.db_path, **kwargs)

    def get_equity_master(self, **kwargs: Any):
        """PIT equity master — ``as_of`` and ``db_path`` injected."""
        return pit.get_equity_master(as_of=self.as_of, db_path=self.db_path, **kwargs)

    def get_market_calendar(self, **kwargs: Any):
        """PIT market calendar — ``as_of`` and ``db_path`` injected."""
        return pit.get_market_calendar(as_of=self.as_of, db_path=self.db_path, **kwargs)

    def get_jquants_records(self, dataset: str, **kwargs: Any):
        """PIT generic catalog records — ``as_of`` and ``db_path`` injected."""
        return pit.get_jquants_records(
            dataset=dataset, as_of=self.as_of, db_path=self.db_path, **kwargs
        )


def _require_as_of(as_of: Any) -> str:
    if as_of is None:
        raise AsOfRequired(
            "features.compute requires an explicit `as_of` (PIT hard gate)"
        )
    # Pass through pit's normalizer (raises on invalid input).
    from pit.query import normalize_as_of
    return normalize_as_of(as_of)


def _validate_inputs(feature: FeatureDefinition, inputs: Mapping[str, Any]) -> None:
    missing = [
        k for k in feature.inputs.required_kwargs
        if k not in inputs or inputs[k] is None
    ]
    if missing:
        raise MissingInput(
            f"feature {feature.id!r} missing required inputs: {missing}"
        )


def compute(
    feature,
    *,
    as_of: Any,
    db_path: Any = None,
    **inputs: Any,
) -> FeatureOutput:
    """Compute one feature at ``as_of`` with PIT-scoped reads.

    Parameters
    ----------
    feature : FeatureDefinition | str
        Either a registered :class:`~features.types.FeatureDefinition` or its
        registry id (e.g. ``"return_1d"``). When a str, the latest version is
        used; pin a version by passing the resolved definition.
    as_of : str
        **Required.** PIT decision instant. Anything accepted by
        ``pit.query.normalize_as_of`` (canonical JST ISO).
    db_path : Any, optional
        SQLite DB path (resolved via ``pit.query.resolve_db_path``).
    **inputs :
        Per-feature inputs. Required kwargs are validated against
        ``feature.inputs.required_kwargs``.

    Returns
    -------
    FeatureOutput
        The feature value with provenance metadata: ``feature_id``,
        ``feature_version``, ``as_of``, ``pit_api_version``,
        ``features_runtime_version``, ``rows_seen``, ``db_path``.
    """
    if isinstance(feature, str):
        feature = _registry.get(feature)
    as_of_iso = _require_as_of(as_of)
    _validate_inputs(feature, inputs)

    resolved_db = resolve_db_path(db_path)
    ctx = FeatureContext(as_of=as_of_iso, db_path=resolved_db, inputs=inputs)
    out = feature.compute(ctx)
    if not isinstance(out, FeatureOutput):
        raise TypeError(
            f"feature {feature.id!r} returned {type(out).__name__}; expected FeatureOutput"
        )
    md = dict(out.metadata)
    md.update({
        "feature_id": feature.id,
        "feature_version": str(feature.version),
        "as_of": as_of_iso,
        "pit_api_version": pit.PIT_API_VERSION,
        "features_runtime_version": FEATURES_RUNTIME_VERSION,
        "db_path": str(resolved_db),
    })
    if feature.price_basis is not None:
        md["price_basis"] = feature.price_basis
    return FeatureOutput(value=out.value, metadata=md)


def compute_many(
    feature_ids: list[str],
    *,
    as_of: Any,
    db_path: Any = None,
    **shared_inputs: Any,
) -> dict[str, FeatureOutput]:
    """Compute many features at the same ``as_of`` with shared inputs.

    Each feature still receives only its declared required inputs (extras are
    ignored). Useful for building a feature vector at a decision instant.
    """
    out: dict[str, FeatureOutput] = {}
    for fid in feature_ids:
        feat = _registry.get(fid)
        # Restrict inputs to those the feature declares (required + optional).
        accepted = set(feat.inputs.required_kwargs) | set(feat.inputs.optional_kwargs)
        kwargs = {k: v for k, v in shared_inputs.items() if k in accepted}
        out[fid] = compute(feat, as_of=as_of, db_path=db_path, **kwargs)
    return out
