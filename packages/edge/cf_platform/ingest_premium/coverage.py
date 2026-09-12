"""Compatibility re-export of the DataPlane PIT coverage runner."""

from storage.coverage import (
    CheckResult,
    EXPECTED_START,
    has_failures,
    not_implemented_skips,
    persist_report,
    run_coverage,
    summarize,
)

__all__ = [
    "CheckResult",
    "EXPECTED_START",
    "has_failures",
    "not_implemented_skips",
    "persist_report",
    "run_coverage",
    "summarize",
]
