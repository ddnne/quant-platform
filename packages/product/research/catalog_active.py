"""Active catalog vs legacy identity registry. Does not delete IDs. Not GO.

Active = countable Worker theses in the compiled map, minus unique-22 park
and generation_enabled-False clones with no Worker body. Legacy is the
compiled remainder (replay/lineage only). Does not add YAML. n_active is
not a quality metric.
"""
from __future__ import annotations

from functools import lru_cache
from typing import Any, Literal

from research.unique_logic.catalog import compiled_migration_ids, load_catalog_specs
from research.unique_logic.worker_bodies import (
    countable_thesis_ids,
    unique22_occupancy_park,
    worker_implemented_logic_ids,
)

CatalogKind = Literal["active", "legacy"]


def _generation_disabled_no_worker_body_ids() -> frozenset[str]:
    """Factory / catalog clones with generation_enabled False and no Worker body."""
    implemented = worker_implemented_logic_ids()
    out: set[str] = set()
    for spec in load_catalog_specs():
        lid = str(spec.get("logic_id") or "").strip()
        if not lid:
            continue
        if bool(spec.get("generation_enabled")):
            continue
        if lid not in implemented:
            out.add(lid)
    return frozenset(out)


@lru_cache(maxsize=1)
def active_logic_ids() -> frozenset[str]:
    """Countable theses ∩ compiled IDs, minus unique-22 park and no-body clones."""
    compiled = compiled_migration_ids()
    countable = countable_thesis_ids()
    parked = unique22_occupancy_park()
    clones = _generation_disabled_no_worker_body_ids()
    return frozenset((countable & compiled) - parked - clones)


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


def pilot_candidates() -> frozenset[str]:
    """Pilot helper returns active only. Legacy IDs stay out.

    n_active is not a quality metric. go=False, not_a_pass=True. AND rows
    remaining classified active/pilot_candidates are inventory, not a pass.
    """
    return active_logic_ids()


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
