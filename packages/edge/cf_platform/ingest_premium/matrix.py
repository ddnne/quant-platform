"""Compatibility re-export of the DataPlane validation-matrix catalog."""

from storage.matrix import (
    CHECKS,
    CheckDef,
    DAILY_IDS,
    WEEKLY_IDS,
    get_check,
    list_checks,
    premium_core_datasets,
)

__all__ = [
    "CHECKS",
    "CheckDef",
    "DAILY_IDS",
    "WEEKLY_IDS",
    "get_check",
    "list_checks",
    "premium_core_datasets",
]
