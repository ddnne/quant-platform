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

from typing import Iterable

from .types import FeatureDefinition, FeatureInput, FeatureOutput, FeatureVersion

# Internal module-level registry. Built-in features register here at import.
_FEATURES: dict[tuple[str, str], FeatureDefinition] = {}


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
    "register",
    "get",
    "list_features",
    "ids",
    "clear",
]


# Sentinel alias for callers who expect a dict-like object.
FEATURES_REGISTRY = _FEATURES
