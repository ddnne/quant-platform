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
    PlanDependencyClosureError,
    build_plan_dependency_closure,
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
from strategies.spec import iter_feature_refs, strategy_spec_digest


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


def test_builtin_feature_dataset_dependencies_are_immutable_and_digested() -> None:
    assert all(definition.dataset_dependencies for definition in features.list_features())
    definition = features.get("momentum_n", version="1.0.0")
    assert definition.dataset_dependencies == ("equities_bars_daily",)
    digest = features.feature_definition_digest(definition)
    assert digest.startswith("sha256:") and len(digest) == 71
    with pytest.raises(FrozenInstanceError):
        definition.dataset_dependencies = ("fins_summary",)  # type: ignore[misc]
