"""Retired catalog identity registry. Does not delete replay IDs. Not GO.

The product runtime has no active catalog IDs.  Every compiled row is legacy
replay/lineage, while the exact-four Pilot IDs come from ExperimentPlans.
"""
from __future__ import annotations

from functools import lru_cache
from typing import Any, Literal

from research.unique_logic.catalog import compiled_migration_ids

CatalogKind = Literal["active", "legacy"]


@lru_cache(maxsize=1)
def active_logic_ids() -> frozenset[str]:
    """Product-runtime catalog IDs: intentionally empty."""
    return frozenset()


@lru_cache(maxsize=1)
def legacy_logic_ids() -> frozenset[str]:
    """Compiled identity remainder. Replay/lineage only; not a research target."""
    return frozenset(compiled_migration_ids() - active_logic_ids())


def catalog_kind(logic_id: str) -> CatalogKind:
    lid = str(logic_id or "").strip()
    if lid in active_logic_ids():
        return "active"
    if lid in compiled_migration_ids():
        return "legacy"
    raise KeyError(f"unknown catalog logic_id: {lid}")


@lru_cache(maxsize=1)
def pilot_candidates() -> frozenset[str]:
    """Four ExperimentPlan strategy_spec_ids, separate from replay identity.

    Does not alias active_logic_ids(). Those AND rows are inventory, not
    a selection. start() stays off. Not GO.
    """
    from research.experiment_plans import PILOT_PLAN_COUNT, load_experiment_plans

    ids = frozenset(plan.strategy_spec_id for plan in load_experiment_plans())
    if len(ids) != PILOT_PLAN_COUNT:
        return frozenset()
    return ids


def summary() -> dict[str, Any]:
    """Active/pilot inventory. n_active is not a quality metric. Not GO."""
    n_active = len(active_logic_ids())
    return {
        "n_active": n_active,
        "n_legacy": len(legacy_logic_ids()),
        "n_pilot_candidates": len(pilot_candidates()),
        "n_active_is_not_a_quality_metric": True,
        "go": False,
        "not_a_pass": True,
    }
