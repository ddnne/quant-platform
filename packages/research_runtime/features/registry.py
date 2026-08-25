"""Feature Registry — versioned metadata for every available feature.

A feature is identified by ``(id, version)`` and carries a ``compute``
callable that takes a :class:`~features.runtime.FeatureContext` and returns a
:class:`~features.types.FeatureOutput`. The registry is the source of truth
for what features exist and what inputs they require.

Built-in features are registered at import time (see :mod:`features.v0`).
Third-party feature packages may call :func:`register` to add their own —
duplicate ``(id, version)`` keys raise ``ValueError``.
"""

from __future__ import annotations

import hashlib
import json
from typing import Iterable

from .types import (
    FeatureDefinition,
    FeatureInput,
    FeatureOutput,
    FeatureVersion,
    IntendedRole,
    FeatureStatus,
)

# Internal module-level registry. Built-in features register here at import.
_FEATURES: dict[tuple[str, str], FeatureDefinition] = {}


class FeatureGovernanceError(PermissionError):
    """A registered feature is not eligible for declarative strategy use."""


def register(feature: FeatureDefinition) -> FeatureDefinition:
    """Add ``feature`` to the registry.

    Raises ``ValueError`` if ``(id, version)`` is already registered — bump
    the version for a new contract.
    """
    key = (feature.id, str(feature.version))
    if key in _FEATURES:
        raise ValueError(
            f"feature already registered: id={feature.id!r} version={feature.version}"
        )
    _FEATURES[key] = feature
    return feature


def feature_definition_digest(feature: FeatureDefinition) -> str:
    """Digest the immutable, JSON-safe portion of a feature definition.

    The callable itself is versioned by ``FeatureVersion`` and remains outside
    this metadata digest.  Dependency closure uses this digest together with an
    exact ``(id, version)`` lookup, so changing declared datasets invalidates a
    previously compiled closure without relying on registry insertion order.
    """
    if not isinstance(feature, FeatureDefinition):
        raise TypeError("FeatureDefinition required")
    payload = {
        "contract": "feature-definition-metadata/v1",
        "id": feature.id,
        "version": str(feature.version),
        "inputs": {
            "required_kwargs": list(feature.inputs.required_kwargs),
            "optional_kwargs": dict(feature.inputs.optional_kwargs),
            "as_of_rule": feature.inputs.as_of_rule,
        },
        "description": feature.description,
        "intended_role": feature.intended_role,
        "dataset_dependencies": list(feature.dataset_dependencies),
        "tags": list(feature.tags),
        "status": feature.status,
        "price_basis": feature.price_basis,
    }
    raw = json.dumps(
        payload,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def get(feature_id: str, version: str | None = None) -> FeatureDefinition:
    """Fetch a feature by id, optionally pinned to a version.

    Without ``version``, returns the **latest** registered version (max by
    semver). Raises ``KeyError`` if no version is registered.
    """
    matches = [
        (v, f) for (fid, v), f in _FEATURES.items() if fid == feature_id
    ]
    if not matches:
        raise KeyError(f"unknown feature id: {feature_id!r}")
    if version is None:
        # Pick the highest semver.
        def _key(item: tuple[str, FeatureDefinition]) -> tuple[int, int, int]:
            parts = item[0].split(".")
            return tuple(int(p) for p in parts[:3])  # type: ignore[return-value]

        v, f = max(matches, key=_key)
        return f
    for v, f in matches:
        if v == version:
            return f
    raise KeyError(
        f"feature {feature_id!r} has no version {version!r}; "
        f"available: {[v for v, _ in matches]}"
    )


def get_for_strategy(
    feature_id: str,
    version: str | None = None,
    *,
    allowed_statuses: tuple[FeatureStatus, ...] = ("approved",),
    allowed_roles: tuple[IntendedRole, ...] = (
        "signal",
        "state",
        "structural",
    ),
) -> FeatureDefinition:
    """Resolve a feature through the fail-closed StrategySpec policy.

    By default only explicitly ``approved`` features intended for strategy
    consumption are returned. A caller must make a visible policy override to
    admit candidate/shadow/retired or utility definitions.
    """
    feature = get(feature_id, version=version)
    if feature.status not in allowed_statuses:
        raise FeatureGovernanceError(
            f"feature {feature.id!r} version {feature.version} has status "
            f"{feature.status!r}; allowed strategy statuses are "
            f"{list(allowed_statuses)!r}"
        )
    if feature.intended_role not in allowed_roles:
        raise FeatureGovernanceError(
            f"feature {feature.id!r} version {feature.version} has intended_role "
            f"{feature.intended_role!r}; allowed strategy roles are "
            f"{list(allowed_roles)!r}"
        )
    return feature


def list_features() -> list[FeatureDefinition]:
    """All registered features, sorted by (id, version)."""
    return sorted(
        _FEATURES.values(),
        key=lambda f: (f.id, str(f.version)),
    )


def ids() -> list[str]:
    """Distinct feature ids (ignoring version)."""
    return sorted({fid for (fid, _) in _FEATURES.keys()})


def clear() -> None:
    """Drop every registration. Test-only."""
    _FEATURES.clear()


# Re-export the public types so callers can do `from features.registry import ...`.
__all__ = [
    "FEATURES_REGISTRY",
    "FeatureDefinition",
    "FeatureInput",
    "FeatureOutput",
    "FeatureVersion",
    "IntendedRole",
    "FeatureStatus",
    "FeatureGovernanceError",
    "feature_definition_digest",
    "register",
    "get",
    "get_for_strategy",
    "list_features",
    "ids",
    "clear",
]


# Sentinel alias for callers who expect a dict-like object.
FEATURES_REGISTRY = _FEATURES
