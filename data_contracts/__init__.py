"""Canonical external-dataset contracts and identity normalization."""

from .loader import (
    AVAILABLE_AT_POLICIES,
    DatasetContract,
    all_contracts,
    contract_for,
)

__all__ = [
    "AVAILABLE_AT_POLICIES",
    "DatasetContract",
    "all_contracts",
    "contract_for",
]
