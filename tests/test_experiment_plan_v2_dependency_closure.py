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
    ContractDependency,
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
from research.research_data_profile import PROFILE_VERSION_V2
from strategies.spec import (
    FeatureRef,
    StrategySpec,
    TopKRule,
    iter_feature_refs,
    strategy_spec_digest,
)


_EXPECTED_REFS = {
    "exp-mdh-hold10-momentum": [
        {"id": "momentum_n", "version": "1.0.0", "params": {"n": 10}}
    ],
    "exp-xs-hold10-mom5": [
        {"id": "momentum_n", "version": "1.0.0", "params": {"n": 5}}
    ],
    "exp-event-post-hold5": [
        {"id": "disclosure_flag_fins", "version": "1.0.0", "params": {}}
    ],
    "exp-fund-hold10-value-mom": [
        {"id": "fundamental_value_score", "version": "1.0.0", "params": {}},
        {"id": "momentum_n", "version": "1.0.0", "params": {"n": 10}},
    ],
}


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
        assert "equities_master" in closure.required_datasets
        assert "markets_calendar" in closure.required_datasets
        assert "equities_bars_daily_am" in closure.required_datasets
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
