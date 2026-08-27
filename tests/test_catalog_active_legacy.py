"""The retired catalog is replay-only; exact-four is a separate identity set."""
from __future__ import annotations

import pytest

from research import catalog_active
from research.catalog_active import (
    active_logic_ids,
    catalog_kind,
    legacy_logic_ids,
    pilot_candidates,
)
from research.unique_logic.catalog import compiled_migration_ids
from research.unique_logic.worker_bodies import (
    countable_thesis_ids,
    worker_implemented_logic_ids,
)


def test_entire_compiled_catalog_is_legacy_replay() -> None:
    compiled = compiled_migration_ids()
    assert compiled
    assert active_logic_ids() == frozenset()
    assert countable_thesis_ids() == frozenset()
    assert worker_implemented_logic_ids() == frozenset()
    assert legacy_logic_ids() == compiled
    assert {catalog_kind(logic_id) for logic_id in compiled} == {"legacy"}


def test_exact_four_candidates_are_not_catalog_members() -> None:
    from research.experiment_plans import PILOT_PLAN_COUNT, load_experiment_plans

    compiled = compiled_migration_ids()
    expected = frozenset(plan.strategy_spec_id for plan in load_experiment_plans())
    assert pilot_candidates() == expected
    assert len(expected) == PILOT_PLAN_COUNT == 4
    assert expected.isdisjoint(compiled)


def test_catalog_summary_cannot_be_a_runtime_success_metric() -> None:
    summary = catalog_active.summary()
    assert summary == {
        "n_active": 0,
        "n_legacy": len(compiled_migration_ids()),
        "n_pilot_candidates": 4,
        "n_active_is_not_a_quality_metric": True,
        "go": False,
        "not_a_pass": True,
    }


def test_unknown_catalog_identity_fails_closed() -> None:
    with pytest.raises(KeyError, match="not_a_catalog_logic_id"):
        catalog_kind("not_a_catalog_logic_id")
