"""Controlled Pilot one-loop types stay capability-off."""
from __future__ import annotations

import importlib
import sys
from unittest.mock import patch

import pytest

from selection.budget_ledger import MassResearchDisabledError


def test_importing_module_does_not_construct_scheduler() -> None:
    import research.phase7_pilot as phase7

    calls: list[tuple[tuple[object, ...], dict[str, object]]] = []
    real_init = phase7.MassResearchScheduler.__init__

    def _spy(self: object, *args: object, **kwargs: object) -> None:
        calls.append((args, kwargs))
        real_init(self, *args, **kwargs)

    sys.modules.pop("research.pilot_loop", None)
    with patch.object(phase7.MassResearchScheduler, "__init__", _spy):
        mod = importlib.import_module("research.pilot_loop")
    assert calls == []
    for value in vars(mod).values():
        assert not isinstance(value, phase7.MassResearchScheduler)
    assert mod.start is not None


def test_start_raises() -> None:
    from research.pilot_loop import (
        ControlledPilotLoop,
        ControlledPilotLoopPlan,
        start,
    )

    with pytest.raises(MassResearchDisabledError, match="capability-off"):
        start()
    with pytest.raises(MassResearchDisabledError, match="capability-off"):
        ControlledPilotLoop().start()
    with pytest.raises(MassResearchDisabledError, match="capability-off"):
        ControlledPilotLoopPlan().start()


def test_capabilities_all_false() -> None:
    from research.pilot_loop import EXECUTION_ROUTES, research_capabilities
    from research.research_capabilities import research_capabilities as caps_fn

    caps = research_capabilities()
    assert caps_fn()["go"] is False
    for name in EXECUTION_ROUTES:
        assert caps[name] is False
    assert caps["go"] is False
    assert caps["operator_override"] is False
    assert caps["not_a_pass"] is True


def test_execute_methods_raise_and_generation_count_is_one() -> None:
    from research.pilot_loop import (
        CONTROLLED_PILOT_STAGES,
        ControlledPilotLoopPlan,
        PILOT_LOOP_DEFAULT_GENERATION_COUNT,
    )

    plan = ControlledPilotLoopPlan()
    assert plan.generation_count == PILOT_LOOP_DEFAULT_GENERATION_COUNT == 1
    assert plan.live_orders is False
    assert plan.mass_fan_out is False
    assert plan.paper_mode == "paper"
    assert plan.stages == CONTROLLED_PILOT_STAGES
    assert plan.stages == (
        "ResearchIdea",
        "ResearchMemo",
        "FeatureProposal",
        "StrategySpec",
        "READY",
        "budgeted_paper",
        "independent_risk",
        "SelectionDecision",
        "Knowledge",
    )
    for method_name in (
        "write_research_memo",
        "propose_feature",
        "propose_strategy_specs",
        "pin_ready_snapshot",
        "run_budgeted_paper",
        "independent_risk",
        "select",
        "record_knowledge",
    ):
        with pytest.raises(MassResearchDisabledError, match="capability-off"):
            getattr(plan, method_name)()
    with pytest.raises(MassResearchDisabledError, match="mass fan-out"):
        plan.start_mass_fan_out()
    with pytest.raises(MassResearchDisabledError, match="live orders"):
        plan.place_live_order()


def test_plan_rejects_live_mass_and_extra_generations() -> None:
    from research.pilot_loop import ControlledPilotLoopPlan

    with pytest.raises(MassResearchDisabledError, match="1-cycle"):
        ControlledPilotLoopPlan(generation_count=2)
    with pytest.raises(MassResearchDisabledError, match="live orders"):
        ControlledPilotLoopPlan(live_orders=True)
    with pytest.raises(MassResearchDisabledError, match="mass fan-out"):
        ControlledPilotLoopPlan(mass_fan_out=True)
    with pytest.raises(MassResearchDisabledError, match="paper-only"):
        ControlledPilotLoopPlan(paper_mode="live")


def test_env_flags_cannot_grant_pilot_start(monkeypatch: pytest.MonkeyPatch) -> None:
    from research.pilot_loop import EXECUTION_ROUTES, research_capabilities, start

    monkeypatch.setenv("MASS_RESEARCH", "GO")
    monkeypatch.setenv("PHASE7", "ON")
    monkeypatch.setenv("READY_DECLARED", "true")
    monkeypatch.setenv("OPERATIONAL_GO", "true")
    monkeypatch.setenv("CONTINUOUS_PAPER", "ARMED")
    monkeypatch.setenv("MASS_EVAL_TOKEN", "x")
    caps = research_capabilities()
    for name in EXECUTION_ROUTES:
        assert caps[name] is False
    assert caps["go"] is False
    with pytest.raises(MassResearchDisabledError, match="capability-off"):
        start()
