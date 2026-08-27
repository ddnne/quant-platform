"""Exactly four typed ExperimentPlans, independent of the replay catalog."""
from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest

from research.artifacts import (
    CORE_RESEARCH_DATA_PROFILE_ID,
    EXPERIMENT_PLAN_VERSION,
    ExperimentPlan,
)
from research.eval_flags import (
    CATALOG_AND_PLUS_N_STOPPED,
    EVENT_THREE_AND_PLUS_N_STOPPED,
    RECONSTITUTION_APPLY,
)
from research.experiment_plans import (
    PILOT_COST_SCENARIO,
    PILOT_EVALUATION_PROTOCOL,
    PILOT_EXECUTION_ENABLED,
    PILOT_EXPERIMENT_PLAN_IDS,
    PILOT_PERIOD_END,
    PILOT_PERIOD_START,
    PILOT_PLAN_COUNT,
    load_experiment_plan_schema,
    load_experiment_plans,
    start,
)
from selection.budget_ledger import MassResearchDisabledError


def test_typed_experiment_plans_are_exactly_four() -> None:
    schema = load_experiment_plan_schema()
    plans = load_experiment_plans()
    assert len(plans) == PILOT_PLAN_COUNT == 4
    assert len(plans) == len(PILOT_EXPERIMENT_PLAN_IDS)
    assert tuple(p.plan_id for p in plans) == PILOT_EXPERIMENT_PLAN_IDS
    assert PILOT_EXECUTION_ENABLED is False
    assert len({plan.strategy_spec_id for plan in plans}) == PILOT_PLAN_COUNT
    for plan in plans:
        payload = plan.to_dict()
        jsonschema.validate(payload, schema)
        assert plan.hypothesis
        assert plan.feature_refs
        assert plan.research_data_profile_id == CORE_RESEARCH_DATA_PROFILE_ID
        assert plan.period_start == PILOT_PERIOD_START
        assert plan.period_end == PILOT_PERIOD_END
        assert plan.cost_scenario == PILOT_COST_SCENARIO
        assert plan.evaluation_protocol == PILOT_EVALUATION_PROTOCOL
        assert not hasattr(plan, "ready_snapshot_id")
        assert "ready_snapshot_id" not in payload
        assert plan.execution_enabled is False
        assert payload["execution_enabled"] is False
        assert plan.version == EXPERIMENT_PLAN_VERSION
        assert payload["research_data_profile_id"] == "core"


def test_experiment_plan_schema_is_closed() -> None:
    schema = load_experiment_plan_schema()
    assert schema["additionalProperties"] is False
    assert schema["properties"]["execution_enabled"]["const"] is False
    assert schema["properties"]["research_data_profile_id"]["const"] == "core"
    plans = load_experiment_plans()
    extra = plans[0].to_dict()
    extra["not_a_field"] = True
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(extra, schema)
    armed = plans[0].to_dict()
    armed["execution_enabled"] = True
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(armed, schema)
    circular = plans[0].to_dict()
    circular["ready_snapshot_id"] = "not-declared"
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(circular, schema)
    with pytest.raises(ValueError, match="unknown field"):
        ExperimentPlan.from_dict(circular)


def test_start_still_raises_mass_research_disabled() -> None:
    from research.pilot_loop import start as pilot_start

    assert PILOT_EXECUTION_ENABLED is False
    with pytest.raises(MassResearchDisabledError, match="capability-off"):
        start()
    with pytest.raises(MassResearchDisabledError, match="capability-off"):
        pilot_start()


def test_pilot_freezes_stay_closed_without_loading_catalog_inventory() -> None:
    assert CATALOG_AND_PLUS_N_STOPPED is True
    assert EVENT_THREE_AND_PLUS_N_STOPPED is True
    assert RECONSTITUTION_APPLY is False
    xs = next(p for p in load_experiment_plans() if p.plan_id == "exp-xs-hold10-mom5")
    assert xs.strategy_spec_id == "cross_section_hold_10"
    assert xs.feature_refs[0].params["n"] == 5
    fund = next(
        p for p in load_experiment_plans() if p.plan_id == "exp-fund-hold10-value-mom"
    )
    assert fund.strategy_spec_id == "fundamentals_hold_10"
    mom = next(r for r in fund.feature_refs if r.id == "momentum_n")
    assert mom.params["n"] == 10


def test_on_disk_plan_files_match_shortlist() -> None:
    from research.experiment_plans import experiment_plans_dir

    directory = experiment_plans_dir()
    names = sorted(p.name for p in directory.glob("*.json"))
    expected = sorted([f"{pid}.json" for pid in PILOT_EXPERIMENT_PLAN_IDS] + ["schema.json"])
    assert names == expected
    schema = load_experiment_plan_schema()
    for plan_id in PILOT_EXPERIMENT_PLAN_IDS:
        raw = json.loads((directory / f"{plan_id}.json").read_text(encoding="utf-8"))
        jsonschema.validate(raw, schema)
        assert raw["execution_enabled"] is False
        assert Path(directory / f"{plan_id}.json").is_file()
