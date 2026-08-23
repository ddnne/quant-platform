"""Active catalog vs legacy identity registry. Does not delete IDs. Not GO."""
from __future__ import annotations

from research import catalog_active
from research.catalog_active import (
    active_logic_ids,
    catalog_kind,
    legacy_logic_ids,
    pilot_candidates,
)
from research.catalog_compiler import (
    COMPILER_VERSION,
    SPLIT_VERSION,
    assert_catalog_ids_emit_frozen,
)
from research.catalog_compiler import (
    active_logic_ids as compiler_active_logic_ids,
)
from research.catalog_compiler import (
    catalog_kind as compiler_catalog_kind,
)
from research.catalog_compiler import (
    legacy_logic_ids as compiler_legacy_logic_ids,
)
from research.catalog_compiler import (
    pilot_candidates as compiler_pilot_candidates,
)
from research.unique_logic.catalog import compiled_migration_ids, load_catalog_specs
from research.unique_logic.worker_bodies import (
    UNIQUE22_PARK_REASONS,
    unique22_occupancy_equal_lifted,
    unique22_occupancy_park,
    worker_implemented_logic_ids,
)


def test_freeze_n_compiled_still_2254() -> None:
    # Freeze n=2254 and digest pin live in test_catalog_compiler (compiler emit).
    freeze = assert_catalog_ids_emit_frozen()
    assert freeze["ok"] is True
    assert freeze["go"] is False
    assert freeze["n_yaml"] == 0
    assert COMPILER_VERSION == "research_catalog_compiler/v1"
    assert SPLIT_VERSION == "research_catalog_compiler/v2"


def test_active_legacy_partition_compiled() -> None:
    compiled = compiled_migration_ids()
    active = active_logic_ids()
    legacy = legacy_logic_ids()
    assert active < compiled
    assert active | legacy == compiled
    assert active.isdisjoint(legacy)
    assert len(active) + len(legacy) == len(compiled)
    assert compiler_active_logic_ids() == active
    assert compiler_legacy_logic_ids() == legacy


def test_pilot_candidates_are_active_only() -> None:
    active = active_logic_ids()
    legacy = legacy_logic_ids()
    pilots = pilot_candidates()
    assert pilots <= active
    assert pilots == active
    assert pilots.isdisjoint(legacy)
    assert compiler_pilot_candidates() == pilots
    assert not any(catalog_kind(lid) == "legacy" for lid in pilots)


def test_active_catalog_count_is_not_a_pass() -> None:
    pack = catalog_active.summary()
    assert catalog_active.summary()["go"] is False
    assert catalog_active.summary()["not_a_pass"] is True
    assert pack["n_active_is_not_a_quality_metric"] is True
    assert pack["n_active"] == len(pilot_candidates()) == len(active_logic_ids())
    assert pack["n_pilot_candidates"] == pack["n_active"]
    assert pack["go"] is False
    assert pack["not_a_pass"] is True


def test_unique22_park_is_legacy_not_unparked() -> None:
    parked = unique22_occupancy_park()
    active = active_logic_ids()
    compiled = compiled_migration_ids()
    assert parked
    assert parked <= compiled
    assert parked.isdisjoint(active)
    assert set(UNIQUE22_PARK_REASONS) == set(parked)
    for lid in parked:
        assert catalog_kind(lid) == "legacy"
        assert compiler_catalog_kind(lid) == "legacy"
    lifted = unique22_occupancy_equal_lifted() & active
    for lid in lifted:
        assert catalog_kind(lid) == "active"


def test_generation_disabled_no_worker_body_is_legacy() -> None:
    implemented = worker_implemented_logic_ids()
    active = active_logic_ids()
    for spec in load_catalog_specs():
        lid = str(spec.get("logic_id") or "")
        if not lid:
            continue
        if bool(spec.get("generation_enabled")):
            continue
        if lid not in implemented:
            assert lid not in active
            assert catalog_kind(lid) == "legacy"


def test_catalog_kind_covers_compiled() -> None:
    compiled = compiled_migration_ids()
    kinds = {catalog_kind(lid) for lid in compiled}
    assert kinds == {"active", "legacy"}
    sample_active = next(iter(active_logic_ids()))
    sample_legacy = next(iter(legacy_logic_ids()))
    assert catalog_kind(sample_active) == "active"
    assert catalog_kind(sample_legacy) == "legacy"
    try:
        catalog_kind("not_a_catalog_logic_id")
        raise AssertionError("unknown logic_id must fail closed")
    except KeyError as exc:
        assert "not_a_catalog_logic_id" in str(exc)
