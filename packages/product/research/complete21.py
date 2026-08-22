"""COMPLETE 21 dataset allowlist. Do not invent Dataset COMPLETE 22."""

from __future__ import annotations

from typing import Sequence

from data_contracts.permanent_defer import (
    PERMANENT_DEFER_DATASETS,
    reject_permanent_defer_for_history,
)
from features.minimal_signal import DEFAULT_SIGNAL_DATASETS

# COMPLETE 21 dataset ids (residual SoT; do not invent 22).

COMPLETE_21_DATASETS: tuple[str, ...] = (
    "derivatives_bars_daily_futures",
    "derivatives_bars_daily_options",
    "derivatives_bars_daily_options_225",
    "edinet_cross_shareholdings",
    "edinet_large_volume_shareholders",
    "edinet_major_shareholders",
    "equities_bars_daily",
    "equities_investor_types",
    "fins_details",
    "fins_dividend",
    "fins_summary",
    "indices_bars_daily",
    "indices_bars_daily_topix",
    "jsda_corporate_bond_transactions",
    "jsda_tokyo_repo_rates",
    "markets_breakdown",
    "markets_calendar",
    "markets_margin_alert",
    "markets_margin_interest",
    "markets_short_ratio",
    "markets_short_sale_report",
)

COMPLETE_21_DATASET_SET: frozenset[str] = frozenset(COMPLETE_21_DATASETS)
DEFAULT_FEATURE_DATASETS: tuple[str, ...] = DEFAULT_SIGNAL_DATASETS

if len(COMPLETE_21_DATASETS) != 21:
    raise RuntimeError(
        f"COMPLETE_21_DATASETS must have exactly 21 ids, got {len(COMPLETE_21_DATASETS)}"
    )
if COMPLETE_21_DATASET_SET & PERMANENT_DEFER_DATASETS:
    raise RuntimeError(
        "COMPLETE_21_DATASETS must not intersect permanent DEFER: "
        f"{sorted(COMPLETE_21_DATASET_SET & PERMANENT_DEFER_DATASETS)}"
    )


class Complete21Error(ValueError):
    """Dataset is not in COMPLETE 21 or empty after filter."""


def require_complete_21_only(
    datasets: Sequence[str] | str,
    *,
    context: str = "COMPLETE 21 datasets",
) -> tuple[str, ...]:
    """Return ordered unique COMPLETE-21 ids. Fail-closed on DEFER / unknown / empty."""
    if isinstance(datasets, str):
        requested = (datasets,)
    else:
        requested = tuple(datasets)

    reject_permanent_defer_for_history(requested, context=context)

    out: list[str] = []
    seen: set[str] = set()
    unknown: list[str] = []
    for item in requested:
        value = str(item).strip()
        if not value or value in seen:
            continue
        if value not in COMPLETE_21_DATASET_SET:
            unknown.append(value)
            continue
        seen.add(value)
        out.append(value)

    if unknown:
        raise Complete21Error(
            f"{context}: dataset(s) not in COMPLETE 21 allowlist: "
            f"{sorted(set(unknown))}. Prefer residual COMPLETE 21; "
            "do not invent Dataset COMPLETE 22."
        )
    if not out:
        raise Complete21Error(
            f"{context}: at least one COMPLETE 21 dataset id is required"
        )
    return tuple(out)


__all__ = [
    "COMPLETE_21_DATASETS",
    "COMPLETE_21_DATASET_SET",
    "Complete21Error",
    "DEFAULT_FEATURE_DATASETS",
    "require_complete_21_only",
]
