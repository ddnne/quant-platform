"""Feature-pipeline guards: permanent DEFER datasets cannot feed history loads.

COMPLETE 21 usage readiness (W49): research features must not treat permanent
DEFER residuals as full-history inputs. W68: permanent DEFER n=4
(PD-MX-EARN-TIP / fins_earnings_date tip4 superseded by live seal). This module
re-exports the data-contracts helpers and adds a small COMPLETE-21 allowlist
for catalog / feature declarations.

Ops / tip / SCD2 CURRENT paths are out of scope — only feature history loads.
"""

from __future__ import annotations

from typing import Iterable, Sequence

from data_contracts.permanent_defer import (
    PERMANENT_DEFER_DATASETS,
    PERMANENT_DEFER_IDS,
    PermanentDeferHistoryError,
    filter_permanent_defer,
    is_permanent_defer,
    reject_permanent_defer_for_history,
    require_history_eligible,
)
from data_contracts.source_capability import source_capability_contract_for

# Dataset COMPLETE 21 (held). Must stay aligned with residual SoT /
# docs/proof/coverage_baseline_21_usage_notes_20260815.md.
COMPLETE_21_DATASETS: frozenset[str] = frozenset(
    {
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
    }
)

# Curated PIT shortcuts that map to a single dataset id.
_SHORTCUT_DATASET: dict[str, str] = {
    "equity_bars_daily": "equities_bars_daily",
    # PD-D2-MASTER residual (PARTIAL after official start). FeatureContext
    # get_equity_master uses PIT from 2008-05-07; generic history still DEFERs.
    "equity_master": "equities_master",
    "market_calendar": "markets_calendar",
    "jsda_repo_rates": "jsda_tokyo_repo_rates",
}


def master_pit_history_start() -> str:
    """Official listed-info start for PIT master reads. Not Dataset COMPLETE."""
    return source_capability_contract_for(
        "equities_master"
    ).earliest_official_availability


def require_feature_dataset(
    dataset: str,
    *,
    context: str = "feature history load",
) -> str:
    """Return ``dataset`` if eligible for feature history; raise if DEFER."""
    return require_history_eligible(dataset, context=context)


def require_feature_datasets(
    datasets: Sequence[str] | str,
    *,
    context: str = "feature history load",
) -> list[str]:
    """Fail-closed: every requested dataset must be history-eligible (not DEFER).

    Returns the normalized list (order preserved, blanks dropped) after the
    reject check so callers can stash provenance.
    """
    if isinstance(datasets, str):
        requested = [datasets]
    else:
        requested = list(datasets)
    cleaned = [str(item).strip() for item in requested if str(item).strip()]
    reject_permanent_defer_for_history(cleaned, context=context)
    return cleaned


def filter_feature_datasets(datasets: Iterable[str]) -> list[str]:
    """Drop permanent DEFER ids from a feature input dataset list."""
    return filter_permanent_defer(datasets)


def shortcut_dataset(resource: str) -> str | None:
    """Map a FeatureContext resource name to its underlying dataset id, if any."""
    return _SHORTCUT_DATASET.get(resource)


__all__ = [
    "COMPLETE_21_DATASETS",
    "PERMANENT_DEFER_DATASETS",
    "PERMANENT_DEFER_IDS",
    "PermanentDeferHistoryError",
    "filter_feature_datasets",
    "filter_permanent_defer",
    "is_permanent_defer",
    "master_pit_history_start",
    "reject_permanent_defer_for_history",
    "require_feature_dataset",
    "require_feature_datasets",
    "require_history_eligible",
    "shortcut_dataset",
]
