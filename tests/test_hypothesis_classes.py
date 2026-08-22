"""W77 / w0816k — hypothesis class registry + generation policy guards."""

from __future__ import annotations

import pytest

from research.artifacts import ResearchIdea
from research.hypothesis_classes import (
    ALL_CLASS_IDS,
    CLASS_CROSS_SECTION_RELATIVE,
    CLASS_EVENT_POST,
    CLASS_FLOW_DEMAND,
    CLASS_FUNDAMENTALS_PRICE,
    CLASS_MACRO_CONDITIONED,
    CLASS_MULTI_DAY_HOLD,
    CLASS_SIMPLE_DAILY_SIGN,
    DEFAULT_GENERATION_CLASS_IDS,
    HYPOTHESIS_CLASS_REGISTRY,
    REQUIRED_CLASS_FIELDS,
    assert_generation_mix_not_skewed,
    assert_registry_closed_to_ready_mass,
    assert_simple_daily_sign_not_default_enabled,
    build_research_idea_payload,
    default_generation_class_ids,
    get_hypothesis_class,
    hypothesis_class_registry_document,
    is_generation_enabled,
    list_hypothesis_classes,
    select_generation_classes,
    validate_all_classes_have_required_fields,
)

from research.scheduler import (
    ExperimentScheduler,
    select_schedule_hypothesis_classes,
)


EXPECTED_CLASSES = {
    CLASS_MULTI_DAY_HOLD,
    CLASS_EVENT_POST,
    CLASS_CROSS_SECTION_RELATIVE,
    CLASS_MACRO_CONDITIONED,
    CLASS_FUNDAMENTALS_PRICE,
    CLASS_FLOW_DEMAND,
    CLASS_SIMPLE_DAILY_SIGN,
}


def test_registry_contains_required_classes():
    assert set(ALL_CLASS_IDS) == EXPECTED_CLASSES
    assert set(HYPOTHESIS_CLASS_REGISTRY.keys()) == EXPECTED_CLASSES
    assert len(ALL_CLASS_IDS) == 7


def test_required_fields_present_on_every_class():
    validate_all_classes_have_required_fields()
    for cid in ALL_CLASS_IDS:
        spec = get_hypothesis_class(cid)
        d = spec.to_dict()
        for field in REQUIRED_CLASS_FIELDS:
            assert field in d, f"{cid} missing {field}"
        assert d["horizon"]
        assert d["universe"]
        assert d["datasets_required"]
        assert d["feature_kinds"]
        assert d["constraints"]
        assert isinstance(d["generation_enabled_by_default"], bool)
        assert isinstance(d["priority"], int)


def test_simple_daily_sign_not_default_enabled():
    assert_simple_daily_sign_not_default_enabled()
    spec = get_hypothesis_class(CLASS_SIMPLE_DAILY_SIGN)
    assert spec.generation_enabled_by_default is False
    assert spec.opt_in_required is True
    assert CLASS_SIMPLE_DAILY_SIGN not in DEFAULT_GENERATION_CLASS_IDS
    assert CLASS_SIMPLE_DAILY_SIGN not in default_generation_class_ids()
    assert is_generation_enabled(CLASS_SIMPLE_DAILY_SIGN) is False
    # Opt-in path
    assert is_generation_enabled(
        CLASS_SIMPLE_DAILY_SIGN,
        explicit_opt_in=(CLASS_SIMPLE_DAILY_SIGN,),
    ) is True


def test_default_generation_mix_excludes_simple_daily_sign():
    mix = select_generation_classes()
    assert CLASS_SIMPLE_DAILY_SIGN not in mix
    assert len(mix) == 6
    assert set(mix) == set(DEFAULT_GENERATION_CLASS_IDS)
    # Default-enabled classes only
    for cid in mix:
        assert get_hypothesis_class(cid).generation_enabled_by_default is True


def test_simple_daily_sign_lowest_priority():
    specs = list_hypothesis_classes()
    assert specs[-1].class_id == CLASS_SIMPLE_DAILY_SIGN
    assert specs[-1].priority == max(s.priority for s in specs)
    for s in specs[:-1]:
        assert s.priority < specs[-1].priority


def test_generation_mix_skew_and_solo_rejected():
    with pytest.raises(ValueError, match="simple_daily_sign-only"):
        assert_generation_mix_not_skewed([CLASS_SIMPLE_DAILY_SIGN])
    with pytest.raises(ValueError, match="skewed"):
        # 1 of 2 = 50% > 34%
        assert_generation_mix_not_skewed(
            [CLASS_MULTI_DAY_HOLD, CLASS_SIMPLE_DAILY_SIGN]
        )
    # 1 of 3 ≈ 33% allowed under default max share 0.34
    assert_generation_mix_not_skewed(
        [
            CLASS_MULTI_DAY_HOLD,
            CLASS_EVENT_POST,
            CLASS_SIMPLE_DAILY_SIGN,
        ]
    )


def test_opt_in_simple_daily_sign_with_multi_class_mix():
    mix = select_generation_classes(
        include_simple_daily_sign=True,
        n=None,
    )
    # full default 6 + simple_daily_sign = 7; share 1/7 ok
    assert CLASS_SIMPLE_DAILY_SIGN in mix
    assert mix[-1] == CLASS_SIMPLE_DAILY_SIGN  # lowest priority last
    assert len([c for c in mix if c != CLASS_SIMPLE_DAILY_SIGN]) >= 2


def test_build_research_idea_payload_aligns_with_research_idea():
    payload = build_research_idea_payload(
        class_id=CLASS_MULTI_DAY_HOLD,
        idea_id="idea-mdh-1",
        hypothesis="multi-day momentum hold over 10d",
        author="human",
    )
    idea = ResearchIdea.from_dict(payload)
    assert idea.idea_id == "idea-mdh-1"
    assert idea.target_horizon == get_hypothesis_class(CLASS_MULTI_DAY_HOLD).horizon
    assert idea.intended_universe == get_hypothesis_class(CLASS_MULTI_DAY_HOLD).universe
    assert idea.candidate_concepts == get_hypothesis_class(CLASS_MULTI_DAY_HOLD).feature_kinds
    assert idea.lineage["hypothesis_class"] == CLASS_MULTI_DAY_HOLD
    assert idea.lineage["datasets_required"]


def test_build_research_idea_rejects_simple_daily_sign_without_opt_in():
    with pytest.raises(ValueError, match="not generation-enabled"):
        build_research_idea_payload(
            class_id=CLASS_SIMPLE_DAILY_SIGN,
            idea_id="idea-sds",
            hypothesis="daily sign",
            author="human",
        )
    payload = build_research_idea_payload(
        class_id=CLASS_SIMPLE_DAILY_SIGN,
        idea_id="idea-sds",
        hypothesis="daily sign opt-in",
        author="human",
        explicit_opt_in=(CLASS_SIMPLE_DAILY_SIGN,),
    )
    idea = ResearchIdea.from_dict(payload)
    assert idea.lineage["hypothesis_class"] == CLASS_SIMPLE_DAILY_SIGN


def test_default_generation_mix_excludes_simple_daily_sign():
    mix = default_generation_class_ids()
    assert CLASS_SIMPLE_DAILY_SIGN not in mix
    assert len(mix) >= 5


def test_scheduler_default_mix_excludes_simple_daily_sign(tmp_path):
    sel = select_schedule_hypothesis_classes()
    assert sel.simple_daily_sign_default_off is True
    assert sel.simple_daily_sign_included is False
    assert CLASS_SIMPLE_DAILY_SIGN not in sel.class_ids

    from selection.budget_ledger import ResearchBudgetCapability
    from selection.screen import ExperimentBudget

    cap = ResearchBudgetCapability(
        "hyp-sched",
        tmp_path / "hyp-sched.sqlite",
        ExperimentBudget(),
    )
    sched = ExperimentScheduler(budget=cap)
    mix = sched.default_hypothesis_class_mix()
    assert CLASS_SIMPLE_DAILY_SIGN not in mix.class_ids
    # Pinning simple_daily_sign without opt-in fails before mass readiness path.
    from research.artifacts import ExperimentPlan
    from selection.budget_ledger import MassResearchDisabledError

    plan = ExperimentPlan.from_dict(
        {
            "plan_id": "p1",
            "idea_id": "i1",
            "strategy_spec_id": "st1",
            "feature_refs": [{"id": "f", "version": "v1"}],
            "ready_snapshot_id": "snap-1",
            "universe": ["1301"],
            "period_start": "2024-01-01",
            "period_end": "2024-12-31",
            "cost_scenario": "default",
            "evaluation_protocol": "signal-default",
            "budget_allocation": {"generations": 1},
        }
    )
    with pytest.raises(MassResearchDisabledError, match="not generation-enabled"):
        sched.schedule(
            plan=plan,
            readiness=None,
            hypothesis_class=CLASS_SIMPLE_DAILY_SIGN,
        )


def test_registry_document_freezes():
    doc = hypothesis_class_registry_document()
    assert doc["version"].startswith("hypothesis-class-registry/")
    assert doc["simple_daily_sign_default_enabled"] is False
    assert doc["mass_research"] == "NO-GO"
    assert doc["phase7"] == "OFF"
    assert doc["ready_declared"] is False
    assert_registry_closed_to_ready_mass(doc)
    assert_registry_closed_to_ready_mass()
