"""Contract freeze for ExperimentPlan v2 and PlanDependencyClosure v1."""

from __future__ import annotations

from dataclasses import FrozenInstanceError, replace

import features
import pytest
from research.artifacts import (
    EXPERIMENT_PLAN_VERSION,
    EXPERIMENT_PLAN_VERSION_V1,
    ExperimentPlan,
    LegacyExperimentPlanV1,
    load_legacy_experiment_plan,
)
from research.dependency_closure import (
    PLAN_DEPENDENCY_CLOSURE_VERSION,
    PLAN_DEPENDENCY_CLOSURE_VERSION_V2,
    ContractDependency,
    DatasetDependencyScope,
    DatasetReadRequirement,
    PlanDependencyClosure,
    PlanDependencyClosureError,
    build_plan_dependency_closure,
    build_strategy_dependency_closure,
    experiment_plan_digest,
    resolve_strategy_spec,
    verify_plan_dependency_closure,
)
from research.experiment_plans import (
    PILOT_EXPERIMENT_PLAN_IDS,
    load_experiment_plan_closures,
    load_experiment_plan_profiles,
    load_experiment_plans,
)
from research.research_data_profile import (
    PROFILE_VERSION_V2,
    PROFILE_VERSION_V3,
    ResearchDataProfile,
    ResearchDataProfileError,
    profile_from_dependency_closure,
)
from data_contracts.read_scopes import DatasetReadScope, VisibleObservationCount
from execution.controlled_fill_contract import (
    CONTROLLED_FILL_CONTRACT_ID,
    CONTROLLED_FILL_CONTRACT_VERSION,
)
from features.registry import FEATURES_REGISTRY, register
from strategies.spec import (
    FeatureRef,
    StrategySpec,
    TopKRule,
    iter_feature_refs,
    strategy_spec_digest,
)


_EXPECTED_REFS = {
    "exp-mdh-hold10-momentum": [
        {
            "id": "retrospective_split_adjusted_momentum_n",
            "version": "1.0.0",
            "params": {"n": 10},
        }
    ],
    "exp-xs-hold10-mom5": [
        {
            "id": "retrospective_split_adjusted_momentum_n",
            "version": "1.0.0",
            "params": {"n": 5},
        }
    ],
    "exp-event-post-hold5": [
        {"id": "disclosure_flag_fins", "version": "1.0.0", "params": {}}
    ],
    "exp-fund-hold10-value-mom": [
        {
            "id": "retrospective_split_safe_fundamental_value_score",
            "version": "1.0.0",
            "params": {},
        },
        {
            "id": "retrospective_split_adjusted_momentum_n",
            "version": "1.0.0",
            "params": {"n": 10},
        },
    ],
}
_CANONICAL_HISTORICAL_DATASETS = (
    "equities_bars_daily",
    "equities_master",
    "fins_summary",
    "indices_bars_daily_topix",
    "markets_calendar",
)


def _payload() -> dict[str, object]:
    return load_experiment_plans()[0].to_dict()


def test_exact_four_resolve_exact_strategy_and_feature_matrix() -> None:
    plans = load_experiment_plans()
    assert tuple(plan.plan_id for plan in plans) == PILOT_EXPERIMENT_PLAN_IDS
    assert len(set(PILOT_EXPERIMENT_PLAN_IDS)) == 4
    for plan in plans:
        assert plan.version == EXPERIMENT_PLAN_VERSION
        spec = resolve_strategy_spec(
            plan.strategy_spec_id,
            plan.strategy_spec_version,
            plan.strategy_spec_hash,
        )
        assert strategy_spec_digest(spec) == plan.strategy_spec_hash
        assert [ref.to_dict() for ref in plan.feature_refs] == _EXPECTED_REFS[
            plan.plan_id
        ]
        assert [ref.to_dict() for ref in iter_feature_refs(spec)] == _EXPECTED_REFS[
            plan.plan_id
        ]


def test_closure_is_deterministic_transitive_and_profile_bound() -> None:
    plans = load_experiment_plans()
    closures = load_experiment_plan_closures()
    profiles = load_experiment_plan_profiles()
    assert len(closures) == len(profiles) == 4
    for plan, closure, profile in zip(plans, closures, profiles, strict=True):
        assert closure.version == PLAN_DEPENDENCY_CLOSURE_VERSION
        assert closure.plan_digest == experiment_plan_digest(plan)
        assert closure == build_plan_dependency_closure(plan)
        assert closure.closure_digest.startswith("sha256:")
        assert tuple(sorted(closure.required_datasets)) == closure.required_datasets
        assert closure.required_datasets == _CANONICAL_HISTORICAL_DATASETS
        assert "equities_bars_daily_am" not in closure.required_datasets
        assert "equities_earnings_calendar" not in closure.required_datasets
        derived = {
            dataset
            for dependency in closure.feature_dependencies
            for dataset in dependency.dataset_dependencies
        }
        assert derived.issubset(closure.required_datasets)
        assert profile.profile_version == PROFILE_VERSION_V2
        assert profile.plan_id == plan.plan_id
        assert profile.plan_digest == closure.plan_digest
        assert profile.dependency_closure_digest == closure.closure_digest
        assert profile.required_datasets == closure.required_datasets
        assert closure.period_start == plan.period_start
        assert closure.period_end == plan.period_end
        assert tuple(scope.dataset_id for scope in closure.dataset_scopes) == (
            closure.required_datasets
        )
        assert profile.period_start == closure.period_start
        assert profile.period_end == closure.period_end
        assert profile.required_lookback_trading_days == (
            closure.required_lookback_trading_days
        )
        assert tuple(dict(scope) for scope in profile.dataset_scopes) == tuple(
            scope.to_dict() for scope in closure.dataset_scopes
        )
        assert profile.contract_versions["coverage_policy"] == (
            "collection-coverage/v3"
        )
        assert profile.contract_versions["coverage_policy_digest"].startswith(
            "sha256:"
        )
        assert "collection-coverage/v2" not in profile.contract_versions.values()


def test_feature_lookback_is_machine_readable_and_digest_bound() -> None:
    closures = {
        closure.plan_id: closure for closure in load_experiment_plan_closures()
    }
    momentum = closures["exp-mdh-hold10-momentum"]
    bars_scope = next(
        scope
        for scope in momentum.dataset_scopes
        if scope.dataset_id == "equities_bars_daily"
    )
    assert bars_scope.required_lookback_trading_days == 10
    assert momentum.required_lookback_trading_days == 10
    event = closures["exp-event-post-hold5"]
    assert event.required_lookback_trading_days == 0


def test_generic_compiler_accepts_canonical_strategy_outside_pilot_registry() -> None:
    spec = StrategySpec(
        strategy_id="personal_momentum_top3",
        rule=TopKRule(
            feature=FeatureRef(
                id="momentum_n",
                version="1.0.0",
                params={"n": 20},
            ),
            k=3,
        ),
    )
    with pytest.raises(PlanDependencyClosureError, match="unknown exact"):
        resolve_strategy_spec(spec.strategy_id, spec.version, strategy_spec_digest(spec))

    closure = build_strategy_dependency_closure(
        plan_id="personal-momentum-plan",
        plan_digest="sha256:" + "a" * 64,
        spec=spec,
        universe_dependencies=(
            ContractDependency(
                kind="universe",
                dependency_id="personal-tse-prime",
                version="universe-dependency/v1",
                dataset_dependencies=("equities_master",),
            ),
        ),
        evaluation_dependency=ContractDependency(
            kind="evaluation",
            dependency_id="personal-walk-forward",
            version="evaluation-dependency/v1",
            dataset_dependencies=("equities_bars_daily", "markets_calendar"),
        ),
        risk_dependency=ContractDependency(
            kind="risk",
            dependency_id="personal-risk",
            version="risk-dependency/v1",
            dataset_dependencies=("equities_bars_daily",),
        ),
        cost_dependency=ContractDependency(
            kind="cost",
            dependency_id="personal-cost-10bp",
            version="cost-dependency/v1",
        ),
        research_data_profile_id="personal-research-profile",
        period_start="2020-01-01",
        period_end="2025-12-31",
    )

    assert closure.strategy_spec_id == spec.strategy_id
    assert closure.strategy_spec_hash == strategy_spec_digest(spec)
    assert closure.required_datasets == (
        "equities_bars_daily",
        "equities_master",
        "markets_calendar",
    )
    assert closure.feature_dependencies[0].dataset_dependencies == (
        "equities_bars_daily",
    )
    assert closure.required_lookback_trading_days == 20
    assert next(
        scope
        for scope in closure.dataset_scopes
        if scope.dataset_id == "equities_bars_daily"
    ).required_lookback_trading_days == 20


def test_generic_compiler_resolves_versioned_feature_default_lookback() -> None:
    spec = StrategySpec(
        strategy_id="personal_default_momentum",
        rule=TopKRule(
            feature=FeatureRef(
                id="momentum_n",
                version="1.0.0",
                params={},
            ),
            k=3,
        ),
    )

    def dependency(kind: str) -> ContractDependency:
        return ContractDependency(
            kind=kind,
            dependency_id=f"personal-{kind}",
            version=f"{kind}-dependency/v1",
        )

    closure = build_strategy_dependency_closure(
        plan_id="personal-default-momentum-plan",
        plan_digest="sha256:" + "b" * 64,
        spec=spec,
        universe_dependencies=(dependency("universe"),),
        evaluation_dependency=dependency("evaluation"),
        risk_dependency=dependency("risk"),
        cost_dependency=dependency("cost"),
        research_data_profile_id="personal-research-profile",
        period_start="2020-01-01",
        period_end="2025-12-31",
    )

    assert closure.feature_dependencies[0].params == {}
    assert closure.required_lookback_trading_days == 20
    assert closure.dataset_scopes[0].required_lookback_trading_days == 20


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("period_start", "2024-2-01"),
        ("period_end", "2022-12-31"),
        ("cost_scenario", "unknown"),
        ("evaluation_protocol", "unknown"),
        ("risk_policy", "unknown"),
        ("universe", ["unknown"]),
        ("execution_enabled", True),
    ],
)
def test_v2_strict_scalars_reject(field: str, value: object) -> None:
    payload = _payload()
    payload[field] = value
    with pytest.raises(ValueError):
        ExperimentPlan.from_dict(payload)


@pytest.mark.parametrize("value", [True, 1.5, "1", 0, -1])
def test_budget_is_positive_non_bool_integer(value: object) -> None:
    payload = _payload()
    payload["budget_allocation"] = {"generations": value}
    with pytest.raises(ValueError, match="budget_allocation"):
        ExperimentPlan.from_dict(payload)


def test_feature_refs_must_match_strategy_in_order_and_version() -> None:
    payload = _payload()
    payload["feature_refs"] = [
        {"id": "momentum_n", "version": "1.0.0", "params": {"n": 5}}
    ]
    plan = ExperimentPlan.from_dict(payload)
    with pytest.raises(PlanDependencyClosureError, match="exactly match"):
        build_plan_dependency_closure(plan)

    payload = _payload()
    payload["feature_refs"] = [
        {"id": "momentum_n", "version": "1.0.0", "params": {"n": 10}},
        {"id": "momentum_n", "version": "1.0.0", "params": {"n": 10}},
    ]
    with pytest.raises(ValueError, match="duplicates"):
        ExperimentPlan.from_dict(payload)


def test_strategy_resolution_rejects_unknown_version_or_hash() -> None:
    plan = load_experiment_plans()[0]
    with pytest.raises(PlanDependencyClosureError, match="unknown exact"):
        resolve_strategy_spec(plan.strategy_spec_id, "strategy-spec/v999", plan.strategy_spec_hash)
    with pytest.raises(PlanDependencyClosureError, match="hash mismatch"):
        resolve_strategy_spec(
            plan.strategy_spec_id,
            plan.strategy_spec_version,
            "sha256:" + "0" * 64,
        )


def test_legacy_v1_is_audit_only_and_not_a_v2_plan() -> None:
    payload = _payload()
    payload["version"] = EXPERIMENT_PLAN_VERSION_V1
    with pytest.raises(ValueError, match="audit-only"):
        ExperimentPlan.from_dict(payload)
    legacy = load_legacy_experiment_plan(payload)
    assert isinstance(legacy, LegacyExperimentPlanV1)
    assert legacy.execution_eligible is False
    with pytest.raises(PlanDependencyClosureError, match="v2 required"):
        build_plan_dependency_closure(legacy)  # type: ignore[arg-type]


def test_canonical_plan_order_does_not_change_digest_and_tamper_fails() -> None:
    plan = load_experiment_plans()[0]
    reordered = ExperimentPlan.from_dict(dict(reversed(plan.to_dict().items())))
    assert experiment_plan_digest(reordered) == experiment_plan_digest(plan)
    closure = build_plan_dependency_closure(plan)
    tampered = replace(closure, plan_digest="sha256:" + "0" * 64)
    with pytest.raises(PlanDependencyClosureError, match="mismatch"):
        verify_plan_dependency_closure(plan, tampered)


def test_plan_and_dependency_closure_nominal_types_are_final() -> None:
    with pytest.raises(TypeError, match="ExperimentPlan is final"):

        class AlternateExperimentPlan(ExperimentPlan):
            pass

    with pytest.raises(TypeError, match="PlanDependencyClosure is final"):

        class AlternatePlanDependencyClosure(PlanDependencyClosure):
            pass

    canonical = load_experiment_plans()[0]
    feature_refs = list(canonical.feature_refs)
    universe = list(canonical.universe)
    budget = dict(canonical.budget_allocation)
    rebound = replace(
        canonical,
        feature_refs=feature_refs,  # type: ignore[arg-type]
        universe=universe,  # type: ignore[arg-type]
        budget_allocation=budget,
    )
    expected = rebound.to_dict()
    feature_refs.clear()
    universe.clear()
    budget.clear()
    assert rebound.to_dict() == expected


def test_builtin_feature_dataset_dependencies_are_immutable_and_digested() -> None:
    assert all(definition.dataset_dependencies for definition in features.list_features())
    definition = features.get("momentum_n", version="1.0.0")
    assert definition.dataset_dependencies == ("equities_bars_daily",)
    digest = features.feature_definition_digest(definition)
    assert digest.startswith("sha256:") and len(digest) == 71
    with pytest.raises(FrozenInstanceError):
        definition.dataset_dependencies = ("fins_summary",)  # type: ignore[misc]


def test_canonical_four_plan_feature_v1_digests_match_main_baseline() -> None:
    baseline = {
        "retrospective_split_adjusted_momentum_n": (
            "sha256:f53d272fe08fbe589221650c9fe96a787a281c898364657037d21e7ce3433cb9"
        ),
        "disclosure_flag_fins": (
            "sha256:bb72244189e975151c6477e377027ee6b9911f9a9df8685ffd2cd4448987d07e"
        ),
        "retrospective_split_safe_fundamental_value_score": (
            "sha256:1cb7ac7fdd2401a54bd83bd4b2f4a1e6d9e8b3ab8362aa301239a6a7edd953b6"
        ),
    }
    for feature_id, expected in baseline.items():
        definition = features.get(feature_id, version="1.0.0")
        assert definition.read_scopes
        assert features.feature_definition_digest(definition) == expected
        assert features.feature_definition_digest(
            definition, metadata_version="v1"
        ) == expected


_LEGACY_CLOSURE_DIGESTS = {
    "exp-mdh-hold10-momentum": (
        "sha256:1cea3e932f50463aed6bd9f1861a096b5ea2f93f63acb1cde85673f981cd602c"
    ),
    "exp-xs-hold10-mom5": (
        "sha256:dc824de51c0167029db5731825a6d3fd246e11b00b8197b233d22d9a0848e65b"
    ),
    "exp-event-post-hold5": (
        "sha256:b531669b5bbe9ab391368dbc898f0da10509676b44f82874ed6596f466da04ec"
    ),
    "exp-fund-hold10-value-mom": (
        "sha256:7852e3ed9bed5aeb804774e4385ccc6725057714cc6e55f48c7b5b31a859d283"
    ),
}
_LEGACY_PROFILE_DIGESTS = {
    "exp-mdh-hold10-momentum": (
        "sha256:ec1610802c9fd5611f6a3acd16c2681ce8690f0043f6433421f341c11e7c5dc3"
    ),
    "exp-xs-hold10-mom5": (
        "sha256:1deafc7045f01d16cc8deafcce3f2b5cdc4fcd929d1e418cb6ea7b83e10e110c"
    ),
    "exp-event-post-hold5": (
        "sha256:214f18be98ced4f5d1ce809a9482d87460aa9b668a184e6436a8222e1477dab4"
    ),
    "exp-fund-hold10-value-mom": (
        "sha256:baf85355c9fc6875a4d0832bffd97f262bdd4a4eb6723cd50baab53df020f454"
    ),
}


def test_legacy_four_plan_closure_and_profile_digests_match_main_baseline() -> None:
    plans = load_experiment_plans()
    closures = load_experiment_plan_closures()
    profiles = load_experiment_plan_profiles()
    for plan, closure, profile in zip(plans, closures, profiles, strict=True):
        assert closure.version == PLAN_DEPENDENCY_CLOSURE_VERSION
        assert closure.closure_digest == _LEGACY_CLOSURE_DIGESTS[plan.plan_id]
        assert profile.profile_version == PROFILE_VERSION_V2
        assert profile.profile_digest == _LEGACY_PROFILE_DIGESTS[plan.plan_id]


def test_scope_enabled_named_input_resolution_ignores_unrelated_param() -> None:
    fixture = features.FeatureDefinition(
        id="scoped_count_fixture",
        version=features.FeatureVersion(1, 0, 0),
        inputs=features.FeatureInput(
            required_kwargs=("code",),
            optional_kwargs={"n": 20, "note": 0},
        ),
        description="synthetic count fixture",
        compute=lambda ctx: features.FeatureOutput(value=None),
        intended_role="signal",
        status="approved",
        dataset_dependencies=("equities_bars_daily",),
        read_scopes=(
            DatasetReadScope(
                dataset_id="equities_bars_daily",
                observation_count=VisibleObservationCount.named_integer_input_plus(
                    "n", add=1
                ),
                fields=("adjustment_close", "date"),
            ),
        ),
    )
    FEATURES_REGISTRY.pop((fixture.id, str(fixture.version)), None)
    register(fixture)
    try:
        spec = StrategySpec(
            strategy_id="scoped-count-fixture-spec",
            rule=TopKRule(
                feature=FeatureRef(
                    id=fixture.id,
                    version=str(fixture.version),
                    params={"n": 10, "note": 999},
                ),
                k=3,
            ),
        )
        closure = build_strategy_dependency_closure(
            plan_id="scoped-count-fixture-plan",
            plan_digest="sha256:" + "a" * 64,
            spec=spec,
            universe_dependencies=(
                ContractDependency(
                    kind="universe",
                    dependency_id="personal-tse-prime",
                    version="universe-dependency/v1",
                    dataset_dependencies=("equities_master",),
                ),
            ),
            evaluation_dependency=ContractDependency(
                kind="evaluation",
                dependency_id="personal-walk-forward",
                version="evaluation-dependency/v1",
                dataset_dependencies=("equities_bars_daily", "markets_calendar"),
            ),
            risk_dependency=ContractDependency(
                kind="risk",
                dependency_id="personal-risk",
                version="risk-dependency/v1",
                dataset_dependencies=("equities_bars_daily",),
            ),
            cost_dependency=ContractDependency(
                kind="cost",
                dependency_id="personal-cost-10bp",
                version="cost-dependency/v1",
            ),
            research_data_profile_id="personal-research-profile",
            period_start="2020-01-01",
            period_end="2025-12-31",
            extra_requirements=(),
            closure_version=PLAN_DEPENDENCY_CLOSURE_VERSION_V2,
        )
    finally:
        FEATURES_REGISTRY.pop((fixture.id, str(fixture.version)), None)
    bars = next(
        scope
        for scope in closure.dataset_scopes
        if scope.dataset_id == "equities_bars_daily"
    )
    feature_req = next(
        item for item in bars.requirements if item.consumer_kind == "feature"
    )
    assert feature_req.scope.observation_count is not None
    assert feature_req.scope.observation_count.value == 11
    assert bars.required_lookback_trading_days == 11
    assert closure.required_lookback_trading_days == 11
    plan = load_experiment_plans()[0]
    legacy = build_plan_dependency_closure(plan)
    assert legacy.required_lookback_trading_days == 10
    assert closure.closure_digest != legacy.closure_digest
    xs = next(
        item for item in load_experiment_plans() if item.plan_id == "exp-xs-hold10-mom5"
    )
    xs_scoped = build_plan_dependency_closure(
        xs, closure_version=PLAN_DEPENDENCY_CLOSURE_VERSION_V2
    )
    assert xs_scoped.required_lookback_trading_days == 6
    assert xs_scoped.closure_digest != closure.closure_digest


def test_scope_enabled_financial_master_roundtrip_and_consumer_isolation() -> None:
    plan = next(
        item
        for item in load_experiment_plans()
        if item.plan_id == "exp-fund-hold10-value-mom"
    )
    closure = build_plan_dependency_closure(
        plan, closure_version=PLAN_DEPENDENCY_CLOSURE_VERSION_V2
    )
    profile = profile_from_dependency_closure(closure)
    assert profile.profile_version == PROFILE_VERSION_V3
    reloaded = ResearchDataProfile.from_dict(profile.to_dict())
    assert reloaded.profile_digest == profile.profile_digest
    assert reloaded.dependency_closure_digest == closure.closure_digest
    by_dataset = {scope.dataset_id: scope for scope in closure.dataset_scopes}
    master = by_dataset["equities_master"]
    universe_master = next(
        item for item in master.requirements if item.consumer_kind == "universe"
    )
    assert universe_master.scope.initial_visible_state == (
        "latest_complete_snapshot_plus_updates"
    )
    assert universe_master.scope.fields == (
        "code",
        "market_code",
        "scale_category",
        "snapshot_date",
    )
    fins = by_dataset["fins_summary"]
    feature_fins = [
        item for item in fins.requirements if item.consumer_kind == "feature"
    ]
    universe_fins = [
        item for item in fins.requirements if item.consumer_kind == "universe"
    ]
    assert feature_fins[0].scope.fields == ("payload", "raw_payload")
    assert (
        feature_fins[0].scope.initial_visible_state
        == "latest_qualifying_bps_preferred_else_eps"
    )
    assert universe_fins[0].scope.initial_visible_state == (
        "all_visible_existence_and_count"
    )
    bars = by_dataset["equities_bars_daily"]
    fund_bars = next(
        item
        for item in bars.requirements
        if item.consumer_kind == "feature"
        and item.consumer_id.startswith(
            "retrospective_split_safe_fundamental_value_score@"
        )
    )
    momentum_bars = next(
        item
        for item in bars.requirements
        if item.consumer_kind == "feature"
        and item.consumer_id.startswith("retrospective_split_adjusted_momentum_n@")
    )
    fill_pm = next(
        item for item in bars.requirements if item.consumer_kind == "fill_pm_valuation"
    )
    assert fund_bars.scope.fields == ("adjustment_close", "close", "date")
    assert momentum_bars.scope.fields == ("adjustment_close", "date")
    assert fill_pm.clock == "same_trading_date_pm_close"
    assert fund_bars.clock == "bound_decision_visible_view"
    calendar = by_dataset["markets_calendar"]
    eval_clocks = {
        item.clock
        for item in calendar.requirements
        if item.consumer_kind == "evaluation"
    }
    universe_clocks = {
        item.clock
        for item in calendar.requirements
        if item.consumer_kind == "universe"
    }
    feature_clocks = {
        item.clock
        for item in calendar.requirements
        if item.consumer_kind == "calendar_prerequisite"
    }
    assert eval_clocks == {"period_end_session_close"}
    assert universe_clocks == {"bound_decision_visible_view"}
    assert feature_clocks == {"bound_decision_visible_view"}
    assert not any(
        item.consumer_kind == "evaluation"
        and item.scope.dataset_id == "indices_bars_daily_topix"
        and not item.scope.unconsumed_membership
        for scope in closure.dataset_scopes
        for item in scope.requirements
    )
    payload = profile.to_dict()
    payload["profile_version"] = PROFILE_VERSION_V2
    payload.pop("profile_digest", None)
    with pytest.raises(ResearchDataProfileError, match="not closed"):
        ResearchDataProfile.from_dict(payload)


def test_scope_enabled_compiler_rejects_unscoped_feature_and_extra_dataset() -> None:
    spec = StrategySpec(
        strategy_id="personal_momentum_top3",
        rule=TopKRule(
            feature=FeatureRef(
                id="momentum_n",
                version="1.0.0",
                params={"n": 20},
            ),
            k=3,
        ),
    )
    kwargs = dict(
        plan_id="personal-momentum-plan",
        plan_digest="sha256:" + "a" * 64,
        spec=spec,
        universe_dependencies=(
            ContractDependency(
                kind="universe",
                dependency_id="personal-tse-prime",
                version="universe-dependency/v1",
                dataset_dependencies=("equities_master",),
            ),
        ),
        evaluation_dependency=ContractDependency(
            kind="evaluation",
            dependency_id="personal-walk-forward",
            version="evaluation-dependency/v1",
            dataset_dependencies=("equities_bars_daily", "markets_calendar"),
        ),
        risk_dependency=ContractDependency(
            kind="risk",
            dependency_id="personal-risk",
            version="risk-dependency/v1",
            dataset_dependencies=("equities_bars_daily",),
        ),
        cost_dependency=ContractDependency(
            kind="cost",
            dependency_id="personal-cost-10bp",
            version="cost-dependency/v1",
        ),
        research_data_profile_id="personal-research-profile",
        period_start="2020-01-01",
        period_end="2025-12-31",
        closure_version=PLAN_DEPENDENCY_CLOSURE_VERSION_V2,
    )
    with pytest.raises(PlanDependencyClosureError, match="declared read scopes"):
        build_strategy_dependency_closure(**kwargs)
    scoped_plan = load_experiment_plans()[0]
    legacy = build_plan_dependency_closure(scoped_plan)
    with pytest.raises(PlanDependencyClosureError, match="explicit requirements"):
        build_strategy_dependency_closure(
            plan_id=scoped_plan.plan_id,
            plan_digest=experiment_plan_digest(scoped_plan),
            spec=resolve_strategy_spec(
                scoped_plan.strategy_spec_id,
                scoped_plan.strategy_spec_version,
                scoped_plan.strategy_spec_hash,
            ),
            universe_dependencies=legacy.universe_dependencies,
            evaluation_dependency=legacy.evaluation_dependency,
            risk_dependency=legacy.risk_dependency,
            cost_dependency=legacy.cost_dependency,
            research_data_profile_id=scoped_plan.research_data_profile_id,
            period_start=scoped_plan.period_start,
            period_end=scoped_plan.period_end,
            extra_datasets=("fins_details",),
            closure_version=PLAN_DEPENDENCY_CLOSURE_VERSION_V2,
        )


def test_scope_enabled_profile_rejects_inconsistent_feature_requirements() -> None:
    plan = load_experiment_plans()[0]
    closure = build_plan_dependency_closure(
        plan, closure_version=PLAN_DEPENDENCY_CLOSURE_VERSION_V2
    )
    profile = profile_from_dependency_closure(closure)

    stripped = profile.to_dict()
    stripped.pop("profile_digest", None)
    stripped["feature_dependencies"][0]["metadata_version"] = (
        "feature-definition-metadata/v1"
    )
    stripped["feature_dependencies"][0].pop("resolved_read_scopes", None)
    with pytest.raises(ResearchDataProfileError):
        ResearchDataProfile.from_dict(stripped)

    widened = profile.to_dict()
    widened.pop("profile_digest", None)
    bars = next(
        item
        for item in widened["dataset_scopes"]
        if item["dataset_id"] == "equities_bars_daily"
    )
    feature_req = next(
        item for item in bars["requirements"] if item["consumer_kind"] == "feature"
    )
    feature_req["scope"]["fields"] = ["adjustment_close", "close", "date"]
    with pytest.raises(ResearchDataProfileError):
        ResearchDataProfile.from_dict(widened)

    unbound = profile.to_dict()
    unbound.pop("profile_digest", None)
    bars = next(
        item
        for item in unbound["dataset_scopes"]
        if item["dataset_id"] == "equities_bars_daily"
    )
    feature_req = next(
        item for item in bars["requirements"] if item["consumer_kind"] == "feature"
    )
    feature_req["consumer_id"] = "unregistered-feature@1.0.0#0"
    with pytest.raises(ResearchDataProfileError):
        ResearchDataProfile.from_dict(unbound)

    widened_scope = replace(
        closure.feature_dependencies[0].resolved_read_scopes[0],
        fields=("adjustment_close", "close", "date"),
    )
    widened_dep = replace(
        closure.feature_dependencies[0],
        resolved_read_scopes=(widened_scope,),
    )
    with pytest.raises(PlanDependencyClosureError):
        replace(
            closure,
            feature_dependencies=(widened_dep, *closure.feature_dependencies[1:]),
        )

    control = ResearchDataProfile.from_dict(profile.to_dict())
    assert control.profile_digest == profile.profile_digest

    calendar = next(
        item
        for item in profile.to_dict()["dataset_scopes"]
        if item["dataset_id"] == "markets_calendar"
    )
    universe_req = next(
        item for item in calendar["requirements"] if item["consumer_kind"] == "universe"
    )
    with pytest.raises(PlanDependencyClosureError, match="duplicate"):
        DatasetDependencyScope(
            dataset_id="markets_calendar",
            period_start=plan.period_start,
            period_end=plan.period_end,
            required_lookback_trading_days=0,
            requirements=(
                DatasetReadRequirement.from_mapping(universe_req),
                DatasetReadRequirement.from_mapping(universe_req),
            ),
        )
    duplicated = profile.to_dict()
    duplicated.pop("profile_digest", None)
    cal = next(
        item
        for item in duplicated["dataset_scopes"]
        if item["dataset_id"] == "markets_calendar"
    )
    cal["requirements"] = list(cal["requirements"]) + [dict(universe_req)]
    with pytest.raises(ResearchDataProfileError):
        ResearchDataProfile.from_dict(duplicated)

    with pytest.raises(PlanDependencyClosureError, match="unresolved observation count"):
        DatasetReadRequirement(
            consumer_kind="fill_am_mark",
            consumer_id=(
                f"{CONTROLLED_FILL_CONTRACT_ID}@{CONTROLLED_FILL_CONTRACT_VERSION}"
            ),
            clock="bound_decision_visible_view",
            scope=DatasetReadScope(
                dataset_id="equities_bars_daily",
                observation_count=VisibleObservationCount.named_integer_input_plus(
                    "n", add=1
                ),
                fields=("adjustment_close", "date"),
            ),
        )
    named_fill = profile.to_dict()
    named_fill.pop("profile_digest", None)
    bars = next(
        item
        for item in named_fill["dataset_scopes"]
        if item["dataset_id"] == "equities_bars_daily"
    )
    am_req = next(
        item for item in bars["requirements"] if item["consumer_kind"] == "fill_am_mark"
    )
    am_req["scope"]["observation_count"] = {
        "kind": "named_integer_input_plus",
        "input_name": "n",
        "add": 1,
    }
    with pytest.raises(ResearchDataProfileError):
        ResearchDataProfile.from_dict(named_fill)

    with pytest.raises(PlanDependencyClosureError, match="bound decision-visible view"):
        DatasetReadRequirement.from_mapping(
            {**universe_req, "clock": "same_trading_date_pm_close"}
        )
    switched = profile.to_dict()
    switched.pop("profile_digest", None)
    cal = next(
        item
        for item in switched["dataset_scopes"]
        if item["dataset_id"] == "markets_calendar"
    )
    cal_universe = next(
        item for item in cal["requirements"] if item["consumer_kind"] == "universe"
    )
    cal_universe["clock"] = "same_trading_date_pm_close"
    with pytest.raises(ResearchDataProfileError):
        ResearchDataProfile.from_dict(switched)

    original_bars = next(
        item
        for item in profile.to_dict()["dataset_scopes"]
        if item["dataset_id"] == "equities_bars_daily"
    )
    original_am = next(
        item
        for item in original_bars["requirements"]
        if item["consumer_kind"] == "fill_am_mark"
    )
    with pytest.raises(PlanDependencyClosureError, match="extra_requirements"):
        build_strategy_dependency_closure(
            plan_id=plan.plan_id,
            plan_digest=experiment_plan_digest(plan),
            spec=resolve_strategy_spec(
                plan.strategy_spec_id,
                plan.strategy_spec_version,
                plan.strategy_spec_hash,
            ),
            universe_dependencies=closure.universe_dependencies,
            evaluation_dependency=closure.evaluation_dependency,
            risk_dependency=closure.risk_dependency,
            cost_dependency=closure.cost_dependency,
            research_data_profile_id=plan.research_data_profile_id,
            period_start=plan.period_start,
            period_end=plan.period_end,
            extra_requirements=(DatasetReadRequirement.from_mapping(original_am),),
        )
