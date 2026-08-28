"""Shared price-basis vocabulary for features and the core engine.

``RAW`` is the vendor's unadjusted session price as it was observed.
``PERSONAL_RETROSPECTIVE_ADJUSTED`` is the vendor's retrospectively
split-adjusted series and is enabled only for local DRAFT research.
``PIT_ADJUSTED`` is reserved
for a series whose corporate-action factors are themselves reconstructed as
of each decision instant.  A vendor adjusted-price column is not, by itself,
evidence that historical values were point-in-time stable.
"""

from __future__ import annotations

from typing import Literal


RAW = "RAW"
PERSONAL_RETROSPECTIVE_ADJUSTED = "PERSONAL_RETROSPECTIVE_ADJUSTED"
PIT_ADJUSTED = "PIT_ADJUSTED"
PriceBasis = Literal[
    "RAW",
    "PERSONAL_RETROSPECTIVE_ADJUSTED",
    "PIT_ADJUSTED",
]


class UnsupportedPriceBasis(ValueError):
    """Raised when a requested basis has no trustworthy runtime implementation."""


def require_supported_price_basis(value: str) -> PriceBasis:
    """Validate and return an enabled price basis.

    ``PIT_ADJUSTED`` is deliberately fail-closed until the ingestion contract
    can prove that adjustment factors and restated history are PIT-versioned.
    """
    normalized = str(value).strip().upper()
    if normalized == RAW:
        return RAW
    if normalized == PERSONAL_RETROSPECTIVE_ADJUSTED:
        return PERSONAL_RETROSPECTIVE_ADJUSTED
    if normalized == PIT_ADJUSTED:
        raise UnsupportedPriceBasis(
            "PIT_ADJUSTED is not enabled: vendor adjusted prices are not "
            "assumed point-in-time safe without versioned adjustment evidence"
        )
    raise UnsupportedPriceBasis(
        f"unknown price basis {value!r}; choose {RAW!r} or "
        f"{PERSONAL_RETROSPECTIVE_ADJUSTED!r} for local DRAFT research "
        f"({PIT_ADJUSTED!r} is reserved but not enabled)"
    )


__all__ = [
    "RAW",
    "PERSONAL_RETROSPECTIVE_ADJUSTED",
    "PIT_ADJUSTED",
    "PriceBasis",
    "UnsupportedPriceBasis",
    "require_supported_price_basis",
]
