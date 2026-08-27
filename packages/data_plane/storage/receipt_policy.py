"""Closed source-family and recovery policy shared by receipt consumers."""

from __future__ import annotations

from types import MappingProxyType
from typing import Any, Mapping


_RECEIPT_SOURCE_BY_CANONICAL_SOURCE = MappingProxyType(
    {
        "jquants_premium_core": "jquants",
        "jquants_addon": "jquants",
        "jsda_governed": "jsda",
    }
)
_RECOVERED_RECEIPT_ORIGINS = frozenset(
    {
        "recovered-raw-only",
        "parsed-staging-only",
        "offline-test-fixture",
    }
)


def receipt_source_for_canonical_source(canonical_source: str) -> str:
    """Return the reviewed ingestion-plane identity for a canonical source."""
    if type(canonical_source) is not str or not canonical_source:
        raise ValueError("canonical receipt source must be a non-empty exact string")
    try:
        return _RECEIPT_SOURCE_BY_CANONICAL_SOURCE[canonical_source]
    except KeyError as exc:
        raise ValueError(
            f"unsupported canonical receipt source: {canonical_source}"
        ) from exc


def is_recovered_only_digests(digests: Mapping[str, Any]) -> bool:
    """Identify evidence that must remain ineligible for trusted projection.

    Sentinel fields are exact typed policy inputs.  Malformed values are
    recovery-only rather than exceptions or implicit trusted evidence.
    """
    if not isinstance(digests, Mapping):
        return True
    eligibility = digests.get("eligibility")
    origin = digests.get("origin")
    synthetic = digests.get("synthetic")
    if "eligibility" in digests and (
        type(eligibility) is not str
        or eligibility not in {"TRUSTED_COLLECTION", "RECOVERED_RAW_ONLY"}
    ):
        return True
    if "origin" in digests and type(origin) is not str:
        return True
    if "synthetic" in digests and type(synthetic) is not bool:
        return True
    return (
        eligibility == "RECOVERED_RAW_ONLY"
        or origin in _RECOVERED_RECEIPT_ORIGINS
        or synthetic is True
    )


__all__ = [
    "is_recovered_only_digests",
    "receipt_source_for_canonical_source",
]
