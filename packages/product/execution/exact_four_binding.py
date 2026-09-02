"""Canonical exact-four plan binding compiled from governed inputs."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from execution.controlled_fill_contract import (
    CONTROLLED_FILL_CONTRACT_DIGEST,
    require_controlled_fill_contract_digest,
    ControlledFillContractError,
)
from execution.exact_four_codec import (
    EXACT_FOUR_BINDING_FORMAT,
    PILOT_EXECUTION_MODE,
    PLAN_EXECUTION_BINDING_FORMAT,
    ExactFourAuthorityContractError,
    _require_date,
    _require_digest,
    _require_text,
    canonical_authority_digest,
)
from research.ready_manifest import load_exact_four_pilot_ready_binding
from research.universe_contract import EXACT_FOUR_UNIVERSE_RULE_DIGEST
from selection.controlled_pilot_policy import (
    CONTROLLED_PILOT_IDENTITY,
    ControlledPilotPolicyError,
    ControlledPilotPolicyPin,
    require_controlled_pilot_identity,
    load_controlled_pilot_policy,
)


@dataclass(frozen=True, slots=True)
class FeatureExecutionPin:
    ordinal: int
    feature_id: str
    feature_version: str
    definition_digest: str
    params_digest: str
    dataset_membership_digest: str

    def __post_init__(self) -> None:
        if type(self.ordinal) is not int or self.ordinal < 0:
            raise ExactFourAuthorityContractError(
                "feature ordinal must be a non-negative integer"
            )
        _require_text(self.feature_id, "feature_id")
        _require_text(self.feature_version, "feature_version")
        _require_digest(self.definition_digest, "definition_digest")
        _require_digest(self.params_digest, "params_digest")
        _require_digest(
            self.dataset_membership_digest, "feature dataset_membership_digest"
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "ordinal": self.ordinal,
            "feature_id": self.feature_id,
            "feature_version": self.feature_version,
            "definition_digest": self.definition_digest,
            "params_digest": self.params_digest,
            "dataset_membership_digest": self.dataset_membership_digest,
        }


@dataclass(frozen=True, slots=True)
class PlanExecutionBinding:
    """Authority-free immutable lineage for one ordered exact-four plan."""

    ordinal: int
    plan_id: str
    plan_digest: str
    dependency_closure_digest: str
    profile_id: str
    profile_version: str
    profile_digest: str
    strategy_spec_id: str
    strategy_spec_version: str
    strategy_spec_hash: str
    feature_pins: tuple[FeatureExecutionPin, ...]
    feature_dependency_set_digest: str
    universe_dependency_set_digest: str
    evaluation_dependency_digest: str
    risk_dependency_digest: str
    cost_dependency_digest: str
    required_dataset_membership_digest: str
    max_gross_weight_ppm: int
    max_paper_runs: int
    risk_execution_limit_digest: str
    period_start: str
    period_end: str
    cost_scenario: str
    fill_contract_digest: str = CONTROLLED_FILL_CONTRACT_DIGEST
    format: str = PLAN_EXECUTION_BINDING_FORMAT

    def __post_init__(self) -> None:
        if type(self.ordinal) is not int or not 1 <= self.ordinal <= 4:
            raise ExactFourAuthorityContractError(
                "plan ordinal must be an integer from one through four"
            )
        if type(self.format) is not str or (
            self.format != PLAN_EXECUTION_BINDING_FORMAT
        ):
            raise ExactFourAuthorityContractError(
                "plan execution binding format is not canonical"
            )
        for name in (
            "plan_id",
            "profile_id",
            "profile_version",
            "strategy_spec_id",
            "strategy_spec_version",
            "period_start",
            "period_end",
            "cost_scenario",
        ):
            _require_text(getattr(self, name), name)
        for name in (
            "plan_digest",
            "dependency_closure_digest",
            "profile_digest",
            "strategy_spec_hash",
            "feature_dependency_set_digest",
            "universe_dependency_set_digest",
            "evaluation_dependency_digest",
            "risk_dependency_digest",
            "cost_dependency_digest",
            "required_dataset_membership_digest",
            "risk_execution_limit_digest",
        ):
            _require_digest(getattr(self, name), name)
        if type(self.max_gross_weight_ppm) is not int or (
            self.max_gross_weight_ppm != 500_000
        ):
            raise ExactFourAuthorityContractError(
                "per-plan max gross weight must remain pinned at 500000 ppm"
            )
        if type(self.max_paper_runs) is not int or self.max_paper_runs != 2:
            raise ExactFourAuthorityContractError(
                "per-plan paper run limit must remain pinned at two"
            )
        expected_limit_digest = canonical_authority_digest(
            {
                "plan_id": self.plan_id,
                "max_gross_weight_ppm": self.max_gross_weight_ppm,
                "max_paper_runs": self.max_paper_runs,
            }
        )
        if self.risk_execution_limit_digest != expected_limit_digest:
            raise ExactFourAuthorityContractError(
                "per-plan risk/execution limit digest mismatch"
            )
        pins = tuple(self.feature_pins)
        if not pins or any(type(pin) is not FeatureExecutionPin for pin in pins):
            raise ExactFourAuthorityContractError(
                "feature_pins must contain exact FeatureExecutionPin values"
            )
        if tuple(pin.ordinal for pin in pins) != tuple(range(len(pins))):
            raise ExactFourAuthorityContractError(
                "feature_pins must preserve canonical ordinal order"
            )
        if canonical_authority_digest([pin.to_dict() for pin in pins]) != (
            self.feature_dependency_set_digest
        ):
            raise ExactFourAuthorityContractError(
                "feature dependency set digest mismatch"
            )
        period_start = _require_date(self.period_start, "period_start")
        period_end = _require_date(self.period_end, "period_end")
        if period_start > period_end:
            raise ExactFourAuthorityContractError("plan period is reversed")
        try:
            require_controlled_fill_contract_digest(self.fill_contract_digest)
        except ControlledFillContractError as exc:
            raise ExactFourAuthorityContractError(str(exc)) from exc
        object.__setattr__(self, "feature_pins", pins)

    def to_canonical_dict(self) -> dict[str, Any]:
        return {
            "format": self.format,
            "ordinal": self.ordinal,
            "plan_id": self.plan_id,
            "plan_digest": self.plan_digest,
            "dependency_closure_digest": self.dependency_closure_digest,
            "profile_id": self.profile_id,
            "profile_version": self.profile_version,
            "profile_digest": self.profile_digest,
            "strategy_spec_id": self.strategy_spec_id,
            "strategy_spec_version": self.strategy_spec_version,
            "strategy_spec_hash": self.strategy_spec_hash,
            "feature_pins": [pin.to_dict() for pin in self.feature_pins],
            "feature_dependency_set_digest": self.feature_dependency_set_digest,
            "universe_dependency_set_digest": self.universe_dependency_set_digest,
            "evaluation_dependency_digest": self.evaluation_dependency_digest,
            "risk_dependency_digest": self.risk_dependency_digest,
            "cost_dependency_digest": self.cost_dependency_digest,
            "required_dataset_membership_digest": (
                self.required_dataset_membership_digest
            ),
            "max_gross_weight_ppm": self.max_gross_weight_ppm,
            "max_paper_runs": self.max_paper_runs,
            "risk_execution_limit_digest": self.risk_execution_limit_digest,
            "period_start": self.period_start,
            "period_end": self.period_end,
            "cost_scenario": self.cost_scenario,
            "fill_contract_digest": self.fill_contract_digest,
        }

    @property
    def binding_digest(self) -> str:
        return canonical_authority_digest(self.to_canonical_dict())

    def to_dict(self) -> dict[str, Any]:
        return {**self.to_canonical_dict(), "binding_digest": self.binding_digest}


@dataclass(frozen=True, slots=True)
class ControlledPilotArtifactCardinality:
    """One batch: 4 Paper, 4 Risk, then one aggregate Selection/Knowledge."""

    batch_authorizations_exactly: int = 1
    paper_results_exactly: int = 4
    risk_results_exactly: int = 4
    aggregate_selection_results_exactly: int = 1
    knowledge_artifacts_exactly: int = 1

    def __post_init__(self) -> None:
        expected = {
            "batch_authorizations_exactly": 1,
            "paper_results_exactly": 4,
            "risk_results_exactly": 4,
            "aggregate_selection_results_exactly": 1,
            "knowledge_artifacts_exactly": 1,
        }
        actual = self.to_dict()
        if (
            any(type(actual[name]) is not int for name in expected)
            or actual != expected
        ):
            raise ExactFourAuthorityContractError(
                "controlled pilot artifact cardinality is not canonical"
            )

    def to_dict(self) -> dict[str, int]:
        return {
            "batch_authorizations_exactly": self.batch_authorizations_exactly,
            "paper_results_exactly": self.paper_results_exactly,
            "risk_results_exactly": self.risk_results_exactly,
            "aggregate_selection_results_exactly": (
                self.aggregate_selection_results_exactly
            ),
            "knowledge_artifacts_exactly": self.knowledge_artifacts_exactly,
        }


def _compiled_plan_bindings() -> tuple[PlanExecutionBinding, ...]:
    binding = load_exact_four_pilot_ready_binding()
    compiled: list[PlanExecutionBinding] = []
    for ordinal, (closure, profile) in enumerate(
        zip(binding.closures, binding.profiles, strict=True), start=1
    ):
        features = tuple(
            FeatureExecutionPin(
                ordinal=feature.ordinal,
                feature_id=feature.feature_id,
                feature_version=feature.feature_version,
                definition_digest=feature.definition_digest,
                params_digest=canonical_authority_digest(dict(feature.params)),
                dataset_membership_digest=canonical_authority_digest(
                    list(feature.dataset_dependencies)
                ),
            )
            for feature in closure.feature_dependencies
        )
        limit_body = {
            "plan_id": closure.plan_id,
            "max_gross_weight_ppm": 500_000,
            "max_paper_runs": 2,
        }
        compiled.append(
            PlanExecutionBinding(
                ordinal=ordinal,
                plan_id=closure.plan_id,
                plan_digest=closure.plan_digest,
                dependency_closure_digest=closure.closure_digest,
                profile_id=profile.profile_id,
                profile_version=profile.profile_version,
                profile_digest=profile.profile_digest,
                strategy_spec_id=closure.strategy_spec_id,
                strategy_spec_version=closure.strategy_spec_version,
                strategy_spec_hash=closure.strategy_spec_hash,
                feature_pins=features,
                feature_dependency_set_digest=canonical_authority_digest(
                    [feature.to_dict() for feature in features]
                ),
                universe_dependency_set_digest=canonical_authority_digest(
                    [item.to_dict() for item in closure.universe_dependencies]
                ),
                evaluation_dependency_digest=(
                    closure.evaluation_dependency.contract_digest
                ),
                risk_dependency_digest=closure.risk_dependency.contract_digest,
                cost_dependency_digest=closure.cost_dependency.contract_digest,
                required_dataset_membership_digest=canonical_authority_digest(
                    list(closure.required_datasets)
                ),
                max_gross_weight_ppm=500_000,
                max_paper_runs=2,
                risk_execution_limit_digest=canonical_authority_digest(limit_body),
                period_start=closure.period_start,
                period_end=closure.period_end,
                cost_scenario=closure.cost_dependency.dependency_id,
                fill_contract_digest=CONTROLLED_FILL_CONTRACT_DIGEST,
            )
        )
    return tuple(compiled)


@dataclass(frozen=True, slots=True)
class ExactFourExecutionBinding:
    """Canonical ordered plan set.  It carries lineage, never authority."""

    plan_bindings: tuple[PlanExecutionBinding, ...]
    policy: ControlledPilotPolicyPin
    artifact_cardinality: ControlledPilotArtifactCardinality
    publication_profile_id: str
    publication_profile_version: str
    plan_set_digest: str
    dependency_closure_set_digest: str
    profile_set_digest: str
    required_dataset_membership_digest: str
    universe_rule_digest: str
    coverage_policy_version: str
    coverage_policy_digest: str
    budget_scope_digest: str
    execution_limit_set_digest: str
    lease_ttl_seconds: int
    fill_contract_digest: str = CONTROLLED_FILL_CONTRACT_DIGEST
    format: str = EXACT_FOUR_BINDING_FORMAT
    execution_mode: str = PILOT_EXECUTION_MODE
    automatic_promotion: bool = False
    mass_research_enabled: bool = False
    live_trading_enabled: bool = False
    identity: str = CONTROLLED_PILOT_IDENTITY

    def __post_init__(self) -> None:
        try:
            require_controlled_pilot_identity(self.identity)
        except ControlledPilotPolicyError as exc:
            raise ExactFourAuthorityContractError(str(exc)) from exc
        if type(self.format) is not str or self.format != EXACT_FOUR_BINDING_FORMAT:
            raise ExactFourAuthorityContractError(
                "exact-four execution binding format is not canonical"
            )
        if type(self.execution_mode) is not str or (
            self.execution_mode != PILOT_EXECUTION_MODE
        ):
            raise ExactFourAuthorityContractError("only paper execution is permitted")
        if (
            type(self.automatic_promotion) is not bool
            or type(self.mass_research_enabled) is not bool
            or type(self.live_trading_enabled) is not bool
            or self.automatic_promotion
            or self.mass_research_enabled
            or self.live_trading_enabled
        ):
            raise ExactFourAuthorityContractError(
                "Mass, live trading, and automatic promotion are disabled"
            )
        if type(self.policy) is not ControlledPilotPolicyPin:
            raise ExactFourAuthorityContractError(
                "exact ControlledPilotPolicyPin is required"
            )
        self.policy.__post_init__()
        if type(self.artifact_cardinality) is not ControlledPilotArtifactCardinality:
            raise ExactFourAuthorityContractError(
                "exact ControlledPilotArtifactCardinality is required"
            )
        self.artifact_cardinality.__post_init__()
        plans = tuple(self.plan_bindings)
        expected = _compiled_plan_bindings()
        if (
            len(plans) != self.policy.plans_exactly
            or any(type(item) is not PlanExecutionBinding for item in plans)
            or tuple(item.ordinal for item in plans) != (1, 2, 3, 4)
            or tuple(item.to_dict() for item in plans)
            != tuple(item.to_dict() for item in expected)
        ):
            raise ExactFourAuthorityContractError(
                "plan bindings are not the canonical ordered exact four"
            )
        for name in (
            "publication_profile_id",
            "publication_profile_version",
            "coverage_policy_version",
        ):
            _require_text(getattr(self, name), name)
        for name in (
            "plan_set_digest",
            "dependency_closure_set_digest",
            "profile_set_digest",
            "required_dataset_membership_digest",
            "universe_rule_digest",
            "coverage_policy_digest",
            "budget_scope_digest",
            "execution_limit_set_digest",
        ):
            _require_digest(getattr(self, name), name)
        source = load_exact_four_pilot_ready_binding()
        if (
            self.publication_profile_id != source.profile_id
            or self.publication_profile_version != source.profile_version
            or self.plan_set_digest != source.plan_set_digest
            or self.dependency_closure_set_digest != source.closure_set_digest
            or self.profile_set_digest != source.profile_digest
            or self.required_dataset_membership_digest
            != canonical_authority_digest(list(source.required_datasets))
            or self.universe_rule_digest != EXACT_FOUR_UNIVERSE_RULE_DIGEST
            or self.coverage_policy_version
            != source.contract_versions["coverage_policy"]
            or self.coverage_policy_digest
            != source.contract_versions["coverage_policy_digest"]
            or self.budget_scope_digest != self.policy.budget_scope_digest
            or self.execution_limit_set_digest
            != canonical_authority_digest(
                [
                    {
                        "ordinal": item.ordinal,
                        "plan_id": item.plan_id,
                        "risk_execution_limit_digest": (
                            item.risk_execution_limit_digest
                        ),
                    }
                    for item in plans
                ]
            )
            or type(self.lease_ttl_seconds) is not int
            or self.lease_ttl_seconds != self.policy.lease_ttl_seconds
        ):
            raise ExactFourAuthorityContractError(
                "exact-four aggregate lineage does not match governed compiler output"
            )
        try:
            require_controlled_fill_contract_digest(self.fill_contract_digest)
        except ControlledFillContractError as exc:
            raise ExactFourAuthorityContractError(str(exc)) from exc
        if any(
            item.fill_contract_digest != self.fill_contract_digest for item in plans
        ):
            raise ExactFourAuthorityContractError(
                "plan fill contracts must match the aggregate fill contract"
            )
        object.__setattr__(self, "plan_bindings", plans)

    def to_canonical_dict(self) -> dict[str, Any]:
        return {
            "format": self.format,
            "identity": self.identity,
            "execution_mode": self.execution_mode,
            "policy": self.policy.to_dict(),
            "artifact_cardinality": self.artifact_cardinality.to_dict(),
            "publication_profile_id": self.publication_profile_id,
            "publication_profile_version": self.publication_profile_version,
            "plan_bindings": [item.to_dict() for item in self.plan_bindings],
            "plan_set_digest": self.plan_set_digest,
            "dependency_closure_set_digest": self.dependency_closure_set_digest,
            "profile_set_digest": self.profile_set_digest,
            "required_dataset_membership_digest": (
                self.required_dataset_membership_digest
            ),
            "universe_rule_digest": self.universe_rule_digest,
            "coverage_policy_version": self.coverage_policy_version,
            "coverage_policy_digest": self.coverage_policy_digest,
            "budget_scope_digest": self.budget_scope_digest,
            "execution_limit_set_digest": self.execution_limit_set_digest,
            "lease_ttl_seconds": self.lease_ttl_seconds,
            "fill_contract_digest": self.fill_contract_digest,
            "automatic_promotion": self.automatic_promotion,
            "mass_research_enabled": self.mass_research_enabled,
            "live_trading_enabled": self.live_trading_enabled,
        }

    @property
    def binding_digest(self) -> str:
        return canonical_authority_digest(self.to_canonical_dict())

    def to_dict(self) -> dict[str, Any]:
        return {**self.to_canonical_dict(), "binding_digest": self.binding_digest}


def load_exact_four_execution_binding() -> ExactFourExecutionBinding:
    source = load_exact_four_pilot_ready_binding()
    policy = load_controlled_pilot_policy()
    plan_bindings = _compiled_plan_bindings()
    return ExactFourExecutionBinding(
        plan_bindings=plan_bindings,
        policy=policy,
        artifact_cardinality=ControlledPilotArtifactCardinality(),
        publication_profile_id=source.profile_id,
        publication_profile_version=source.profile_version,
        plan_set_digest=source.plan_set_digest,
        dependency_closure_set_digest=source.closure_set_digest,
        profile_set_digest=source.profile_digest,
        required_dataset_membership_digest=canonical_authority_digest(
            list(source.required_datasets)
        ),
        universe_rule_digest=EXACT_FOUR_UNIVERSE_RULE_DIGEST,
        coverage_policy_version=source.contract_versions["coverage_policy"],
        coverage_policy_digest=source.contract_versions["coverage_policy_digest"],
        budget_scope_digest=policy.budget_scope_digest,
        execution_limit_set_digest=canonical_authority_digest(
            [
                {
                    "ordinal": item.ordinal,
                    "plan_id": item.plan_id,
                    "risk_execution_limit_digest": item.risk_execution_limit_digest,
                }
                for item in plan_bindings
            ]
        ),
        lease_ttl_seconds=policy.lease_ttl_seconds,
        fill_contract_digest=CONTROLLED_FILL_CONTRACT_DIGEST,
    )


def controlled_pilot_v1_contract() -> dict[str, Any]:
    """Machine-readable closed binding for Worker/Container Controlled Pilot."""

    from data_contracts.coverage import coverage_policy_set_binding
    from execution.controlled_fill_contract import controlled_fill_contract
    from paper_runtime.readiness_attestation import EXACT_FOUR_DATASET_IDS
    from research.experiment_plans import PILOT_EXPERIMENT_PLAN_IDS
    from research.universe_contract import EXACT_FOUR_UNIVERSE_RULE_DIGEST as RULE

    binding = load_exact_four_execution_binding()
    source = load_exact_four_pilot_ready_binding()
    datasets = list(EXACT_FOUR_DATASET_IDS)
    coverage = dict(coverage_policy_set_binding(datasets))
    membership_digest = canonical_authority_digest(sorted(set(datasets)))
    plan_ids = list(PILOT_EXPERIMENT_PLAN_IDS)
    plans = [
        {
            "ordinal": item.ordinal,
            "plan_id": item.plan_id,
            "plan_digest": item.plan_digest,
            "plan_binding_digest": item.binding_digest,
            "strategy_spec_id": item.strategy_spec_id,
            "strategy_spec_version": item.strategy_spec_version,
            "strategy_spec_hash": item.strategy_spec_hash,
            "max_gross_weight_ppm": item.max_gross_weight_ppm,
            "max_paper_runs": item.max_paper_runs,
            "risk_execution_limit_digest": item.risk_execution_limit_digest,
            "period_start": item.period_start,
            "period_end": item.period_end,
            "fill_contract_digest": item.fill_contract_digest,
        }
        for item in binding.plan_bindings
    ]
    if [row["plan_id"] for row in plans] != plan_ids:
        raise ExactFourAuthorityContractError(
            "controlled_pilot_v1 plan order is not the canonical four"
        )
    contract = {
        "format": "controlled-pilot-v1-binding/v1",
        "identity": CONTROLLED_PILOT_IDENTITY,
        "runner_version": "controlled-pilot-container/v1",
        "generation": 1,
        "max_parallel": 2,
        "plan_count": 4,
        "child_count": 10,
        "max_gross_weight_ppm": 500_000,
        "automatic_promotion": False,
        "mass_research_enabled": False,
        "live_trading_enabled": False,
        "plan_ids": plan_ids,
        "plans": plans,
        "fill_contract": controlled_fill_contract(),
        "fill_contract_digest": CONTROLLED_FILL_CONTRACT_DIGEST,
        "dataset_ids": datasets,
        "dataset_membership_digest": membership_digest,
        "profile_id": binding.publication_profile_id,
        "profile_version": binding.publication_profile_version,
        "profile_digest": binding.profile_set_digest,
        "plan_set_digest": binding.plan_set_digest,
        "dependency_closure_digest": binding.dependency_closure_set_digest,
        "universe_rule_digest": RULE,
        "coverage_policy_version": coverage["policy_version"],
        "coverage_policy_digest": coverage["policy_digest"],
        "policy_digest": binding.policy.policy_digest,
        "budget_scope_digest": binding.budget_scope_digest,
        "execution_limit_set_digest": binding.execution_limit_set_digest,
        "lease_ttl_seconds": binding.lease_ttl_seconds,
        "exact_four_binding_digest": binding.binding_digest,
        "required_dataset_membership_digest": (
            binding.required_dataset_membership_digest
        ),
        "source_required_datasets": list(source.required_datasets),
    }
    contract["contract_digest"] = canonical_authority_digest(
        {key: value for key, value in contract.items() if key != "contract_digest"}
    )
    return contract


__all__ = [
    "CONTROLLED_PILOT_IDENTITY",
    "ControlledPilotArtifactCardinality",
    "ExactFourExecutionBinding",
    "FeatureExecutionPin",
    "PlanExecutionBinding",
    "controlled_pilot_v1_contract",
    "load_exact_four_execution_binding",
]
