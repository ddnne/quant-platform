"""Exact, immutable dependency closure for ExperimentPlan v2.

Compilation is deliberately resolver-owned: plan strings never select a
"latest" StrategySpec or FeatureDefinition, and dataset dependencies come
from governed definitions rather than from the plan payload.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from functools import lru_cache
from types import MappingProxyType
from typing import Any, Mapping, Sequence

import features
from strategies.spec import (
    FeatureRef,
    StrategySpec,
    iter_feature_refs,
    resolve_feature_ref,
    strategy_spec_digest,
)

from research.artifacts import EXPERIMENT_PLAN_VERSION, ExperimentPlan
from research.paper_candidate_specs import (
    build_cross_section_hold_strategy_spec,
    build_event_post_strategy_spec,
    build_fundamentals_hold_strategy_spec,
    build_multi_day_hold_strategy_spec,
)


PLAN_DEPENDENCY_CLOSURE_VERSION = "plan-dependency-closure/v1"
_SHA256_PREFIX = "sha256:"


class PlanDependencyClosureError(ValueError):
    """Raised when an exact plan dependency cannot be resolved or verified."""


def _canonical_digest(payload: Mapping[str, Any]) -> str:
    raw = json.dumps(
        payload,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return _SHA256_PREFIX + hashlib.sha256(raw).hexdigest()


def experiment_plan_digest(plan: ExperimentPlan) -> str:
    if not isinstance(plan, ExperimentPlan) or plan.version != EXPERIMENT_PLAN_VERSION:
        raise PlanDependencyClosureError("ExperimentPlan v2 required")
    return _canonical_digest(plan.to_dict())


def _dataset_ids(values: Sequence[str], label: str) -> tuple[str, ...]:
    if isinstance(values, (str, bytes)):
        raise PlanDependencyClosureError(f"{label} must be an array")
    normalized = tuple(sorted(str(value).strip() for value in values))
    if any(not value for value in normalized):
        raise PlanDependencyClosureError(f"{label} cannot contain blanks")
    if len(normalized) != len(set(normalized)):
        raise PlanDependencyClosureError(f"{label} cannot contain duplicates")
    return normalized


@dataclass(frozen=True, slots=True)
class ResolvedFeatureDependency:
    ordinal: int
    feature_id: str
    feature_version: str
    params: Mapping[str, Any]
    definition_digest: str
    dataset_dependencies: tuple[str, ...]

    def __post_init__(self) -> None:
        if isinstance(self.ordinal, bool) or self.ordinal < 0:
            raise PlanDependencyClosureError("feature ordinal must be non-negative")
        object.__setattr__(self, "params", MappingProxyType(dict(self.params)))
        object.__setattr__(
            self,
            "dataset_dependencies",
            _dataset_ids(self.dataset_dependencies, "feature dataset_dependencies"),
        )
        if not self.dataset_dependencies:
            raise PlanDependencyClosureError(
                f"feature {self.feature_id!r} has no immutable dataset_dependencies"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "ordinal": self.ordinal,
            "feature_id": self.feature_id,
            "feature_version": self.feature_version,
            "params": dict(self.params),
            "definition_digest": self.definition_digest,
            "dataset_dependencies": list(self.dataset_dependencies),
        }


@dataclass(frozen=True, slots=True)
class ContractDependency:
    kind: str
    dependency_id: str
    version: str
    dataset_dependencies: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.kind not in {"universe", "evaluation", "risk", "cost"}:
            raise PlanDependencyClosureError(f"unsupported dependency kind {self.kind!r}")
        object.__setattr__(
            self,
            "dataset_dependencies",
            _dataset_ids(self.dataset_dependencies, f"{self.kind} dataset_dependencies"),
        )

    def to_canonical_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "id": self.dependency_id,
            "version": self.version,
            "dataset_dependencies": list(self.dataset_dependencies),
        }

    @property
    def contract_digest(self) -> str:
        return _canonical_digest(self.to_canonical_dict())

    def to_dict(self) -> dict[str, Any]:
        body = self.to_canonical_dict()
        body["contract_digest"] = self.contract_digest
        return body


_UNIVERSE_DEPENDENCIES: Mapping[str, ContractDependency] = MappingProxyType(
    {
        "tse_prime_with_fins": ContractDependency(
            kind="universe",
            dependency_id="tse_prime_with_fins",
            version="universe-dependency/v1",
            dataset_dependencies=("equities_master", "fins_summary"),
        )
    }
)
_EVALUATION_DEPENDENCIES: Mapping[str, ContractDependency] = MappingProxyType(
    {
        "standard_research_eval": ContractDependency(
            kind="evaluation",
            dependency_id="standard_research_eval",
            version="evaluation-dependency/v1",
            dataset_dependencies=(
                "equities_bars_daily",
                "indices_bars_daily_topix",
                "markets_calendar",
            ),
        )
    }
)
_RISK_DEPENDENCIES: Mapping[str, ContractDependency] = MappingProxyType(
    {
        "core_crash_high_vol": ContractDependency(
            kind="risk",
            dependency_id="core_crash_high_vol",
            version="risk-dependency/v1",
            dataset_dependencies=(
                "equities_bars_daily",
                "indices_bars_daily_topix",
                "markets_calendar",
            ),
        )
    }
)
_COST_DEPENDENCIES: Mapping[str, ContractDependency] = MappingProxyType(
    {
        "default_one_way_10bp": ContractDependency(
            kind="cost",
            dependency_id="default_one_way_10bp",
            version="cost-dependency/v1",
        )
    }
)


@lru_cache(maxsize=1)
def pilot_strategy_specs() -> Mapping[tuple[str, str], StrategySpec]:
    """Return the closed, exact StrategySpec registry for the four-plan pilot."""
    specs = (
        build_multi_day_hold_strategy_spec(
            strategy_id="paper_mdh_hold10_momentum_topk"
        ),
        build_cross_section_hold_strategy_spec(strategy_id="cross_section_hold_10"),
        build_event_post_strategy_spec(
            strategy_id="paper_event_post_hold5_disclosure_proxy"
        ),
        build_fundamentals_hold_strategy_spec(strategy_id="fundamentals_hold_10"),
    )
    registry = {(spec.strategy_id, spec.version): spec for spec in specs}
    if len(registry) != len(specs):
        raise PlanDependencyClosureError("duplicate pilot StrategySpec identity")
    return MappingProxyType(registry)


def resolve_strategy_spec(
    strategy_id: str,
    strategy_version: str,
    expected_hash: str,
) -> StrategySpec:
    """Resolve an exact id/version/hash triple; never select latest."""
    key = (strategy_id, strategy_version)
    try:
        spec = pilot_strategy_specs()[key]
    except KeyError as exc:
        raise PlanDependencyClosureError(
            f"unknown exact StrategySpec {strategy_id!r}@{strategy_version!r}"
        ) from exc
    actual_hash = strategy_spec_digest(spec)
    if actual_hash != expected_hash:
        raise PlanDependencyClosureError(
            f"StrategySpec hash mismatch for {strategy_id!r}@{strategy_version!r}"
        )
    return spec


def _contract(
    registry: Mapping[str, ContractDependency], dependency_id: str, label: str
) -> ContractDependency:
    try:
        return registry[dependency_id]
    except KeyError as exc:
        raise PlanDependencyClosureError(
            f"unknown {label} dependency {dependency_id!r}"
        ) from exc


@dataclass(frozen=True, slots=True)
class PlanDependencyClosure:
    plan_id: str
    plan_digest: str
    strategy_spec_id: str
    strategy_spec_version: str
    strategy_spec_hash: str
    feature_dependencies: tuple[ResolvedFeatureDependency, ...]
    universe_dependencies: tuple[ContractDependency, ...]
    evaluation_dependency: ContractDependency
    risk_dependency: ContractDependency
    cost_dependency: ContractDependency
    research_data_profile_id: str
    required_datasets: tuple[str, ...]
    version: str = PLAN_DEPENDENCY_CLOSURE_VERSION

    def __post_init__(self) -> None:
        if self.version != PLAN_DEPENDENCY_CLOSURE_VERSION:
            raise PlanDependencyClosureError(
                f"unsupported closure version {self.version!r}"
            )
        object.__setattr__(
            self,
            "required_datasets",
            _dataset_ids(self.required_datasets, "required_datasets"),
        )
        if not self.feature_dependencies or not self.universe_dependencies:
            raise PlanDependencyClosureError(
                "feature and universe dependencies must be non-empty"
            )

    def to_canonical_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "plan_id": self.plan_id,
            "plan_digest": self.plan_digest,
            "strategy_spec_id": self.strategy_spec_id,
            "strategy_spec_version": self.strategy_spec_version,
            "strategy_spec_hash": self.strategy_spec_hash,
            "feature_dependencies": [
                dependency.to_dict() for dependency in self.feature_dependencies
            ],
            "universe_dependencies": [
                dependency.to_dict() for dependency in self.universe_dependencies
            ],
            "evaluation_dependency": self.evaluation_dependency.to_dict(),
            "risk_dependency": self.risk_dependency.to_dict(),
            "cost_dependency": self.cost_dependency.to_dict(),
            "research_data_profile_id": self.research_data_profile_id,
            "required_datasets": list(self.required_datasets),
        }

    @property
    def closure_digest(self) -> str:
        return _canonical_digest(self.to_canonical_dict())

    def to_dict(self) -> dict[str, Any]:
        body = self.to_canonical_dict()
        body["closure_digest"] = self.closure_digest
        return body


def build_plan_dependency_closure(plan: ExperimentPlan) -> PlanDependencyClosure:
    """Compile and bind all transitive dependencies for one v2 plan."""
    if not isinstance(plan, ExperimentPlan) or plan.version != EXPERIMENT_PLAN_VERSION:
        raise PlanDependencyClosureError("ExperimentPlan v2 required")
    spec = resolve_strategy_spec(
        plan.strategy_spec_id,
        plan.strategy_spec_version,
        plan.strategy_spec_hash,
    )
    expected_refs = tuple(ref.to_dict() for ref in iter_feature_refs(spec))
    declared_refs = tuple(ref.to_dict() for ref in plan.feature_refs)
    if declared_refs != expected_refs:
        raise PlanDependencyClosureError(
            "ExperimentPlan feature_refs must exactly match StrategySpec rule order"
        )

    feature_dependencies: list[ResolvedFeatureDependency] = []
    for ordinal, ref in enumerate(plan.feature_refs):
        try:
            definition = resolve_feature_ref(ref)
        except Exception as exc:
            raise PlanDependencyClosureError(
                f"cannot resolve feature {ref.id!r}@{ref.version!r}: {exc}"
            ) from exc
        feature_dependencies.append(
            ResolvedFeatureDependency(
                ordinal=ordinal,
                feature_id=ref.id,
                feature_version=ref.version,
                params=ref.params,
                definition_digest=features.feature_definition_digest(definition),
                dataset_dependencies=definition.dataset_dependencies,
            )
        )

    universe_dependencies = tuple(
        _contract(_UNIVERSE_DEPENDENCIES, item, "universe")
        for item in plan.universe
    )
    evaluation = _contract(
        _EVALUATION_DEPENDENCIES, plan.evaluation_protocol, "evaluation"
    )
    risk = _contract(_RISK_DEPENDENCIES, plan.risk_policy, "risk")
    cost = _contract(_COST_DEPENDENCIES, plan.cost_scenario, "cost")

    required_datasets: set[str] = set()
    for dependency in feature_dependencies:
        required_datasets.update(dependency.dataset_dependencies)
    for dependency in (*universe_dependencies, evaluation, risk, cost):
        required_datasets.update(dependency.dataset_dependencies)

    return PlanDependencyClosure(
        plan_id=plan.plan_id,
        plan_digest=experiment_plan_digest(plan),
        strategy_spec_id=spec.strategy_id,
        strategy_spec_version=spec.version,
        strategy_spec_hash=strategy_spec_digest(spec),
        feature_dependencies=tuple(feature_dependencies),
        universe_dependencies=universe_dependencies,
        evaluation_dependency=evaluation,
        risk_dependency=risk,
        cost_dependency=cost,
        research_data_profile_id=plan.research_data_profile_id,
        required_datasets=tuple(sorted(required_datasets)),
    )


def verify_plan_dependency_closure(
    plan: ExperimentPlan, closure: PlanDependencyClosure
) -> None:
    if not isinstance(closure, PlanDependencyClosure):
        raise PlanDependencyClosureError("PlanDependencyClosure v1 required")
    rebuilt = build_plan_dependency_closure(plan)
    if closure.to_dict() != rebuilt.to_dict():
        raise PlanDependencyClosureError("PlanDependencyClosure mismatch")


__all__ = [
    "ContractDependency",
    "PLAN_DEPENDENCY_CLOSURE_VERSION",
    "PlanDependencyClosure",
    "PlanDependencyClosureError",
    "ResolvedFeatureDependency",
    "build_plan_dependency_closure",
    "experiment_plan_digest",
    "pilot_strategy_specs",
    "resolve_strategy_spec",
    "verify_plan_dependency_closure",
]
