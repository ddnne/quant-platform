"""Exact, immutable dependency closure for ExperimentPlan v2.

Compilation is deliberately resolver-owned: plan strings never select a
"latest" StrategySpec or FeatureDefinition, and dataset dependencies come
from governed definitions rather than from the plan payload.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import date
from functools import lru_cache
from types import MappingProxyType
from typing import Any, Mapping, Sequence

import features
from data_contracts.read_scopes import (
    DatasetDependencyScope,
    DatasetReadRequirement,
    DatasetReadScope,
    DatasetRequirementError,
    _derived_observation_lookback,
    require_complete_feature_read_scopes,
    resolve_dataset_read_scopes,
)
from features.registry import (
    FEATURE_DEFINITION_METADATA_V1,
    FEATURE_DEFINITION_METADATA_V2,
)
from strategies.spec import (
    FeatureRef,
    StrategySpec,
    iter_feature_refs,
    resolve_feature_ref,
    strategy_spec_digest,
)

from execution.controlled_fill_contract import (
    CONTROLLED_FILL_CONTRACT_ID,
    CONTROLLED_FILL_CONTRACT_VERSION,
    CONTROLLED_FILL_SIGNAL_PRICE_DATASET,
)
from research.artifacts import EXPERIMENT_PLAN_VERSION, ExperimentPlan
from research.paper_candidate_specs import (
    build_cross_section_hold_strategy_spec,
    build_event_post_strategy_spec,
    build_fundamentals_hold_strategy_spec,
    build_multi_day_hold_strategy_spec,
)


PLAN_DEPENDENCY_CLOSURE_VERSION_V1 = "plan-dependency-closure/v1"
PLAN_DEPENDENCY_CLOSURE_VERSION_V2 = "plan-dependency-closure/v2"
PLAN_DEPENDENCY_CLOSURE_VERSION = PLAN_DEPENDENCY_CLOSURE_VERSION_V1
SUPPORTED_CLOSURE_VERSIONS = frozenset(
    {PLAN_DEPENDENCY_CLOSURE_VERSION_V1, PLAN_DEPENDENCY_CLOSURE_VERSION_V2}
)
_SHA256_PREFIX = "sha256:"
PlanDependencyClosureError = DatasetRequirementError


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


def _iso_date(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise PlanDependencyClosureError(f"{label} must be an ISO date")
    text = value.strip()
    try:
        parsed = date.fromisoformat(text)
    except ValueError as exc:
        raise PlanDependencyClosureError(f"{label} must be an ISO date") from exc
    if parsed.isoformat() != text:
        raise PlanDependencyClosureError(f"{label} must be an ISO date")
    return text


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
    metadata_version: str = FEATURE_DEFINITION_METADATA_V1
    resolved_read_scopes: tuple[DatasetReadScope, ...] = ()

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
        object.__setattr__(self, "resolved_read_scopes", tuple(self.resolved_read_scopes))
        if self.metadata_version not in {
            FEATURE_DEFINITION_METADATA_V1,
            FEATURE_DEFINITION_METADATA_V2,
        }:
            raise PlanDependencyClosureError(
                f"unsupported feature metadata version {self.metadata_version!r}"
            )
        if self.metadata_version == FEATURE_DEFINITION_METADATA_V2:
            try:
                require_complete_feature_read_scopes(
                    self.dataset_dependencies, self.resolved_read_scopes
                )
            except ValueError as exc:
                raise PlanDependencyClosureError(str(exc)) from exc
            _require_literal_observation_counts(
                self.resolved_read_scopes,
                f"feature {self.feature_id!r} resolved read scopes",
            )

    def to_dict(self, *, scoped: bool = False) -> dict[str, Any]:
        body = {
            "ordinal": self.ordinal,
            "feature_id": self.feature_id,
            "feature_version": self.feature_version,
            "params": dict(self.params),
            "definition_digest": self.definition_digest,
            "dataset_dependencies": list(self.dataset_dependencies),
        }
        if scoped:
            body["metadata_version"] = self.metadata_version
            body["resolved_read_scopes"] = [
                scope.canonical_mapping() for scope in self.resolved_read_scopes
            ]
        return body


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
            strategy_id="paper_mdh_hold10_momentum_topk",
            momentum_feature_id="retrospective_split_adjusted_momentum_n",
        ),
        build_cross_section_hold_strategy_spec(
            strategy_id="cross_section_hold_10",
            momentum_feature_id="retrospective_split_adjusted_momentum_n",
        ),
        build_event_post_strategy_spec(
            strategy_id="paper_event_post_hold5_disclosure_proxy"
        ),
        build_fundamentals_hold_strategy_spec(
            strategy_id="fundamentals_hold_10",
            momentum_feature_id="retrospective_split_adjusted_momentum_n",
            value_feature_id="retrospective_split_safe_fundamental_value_score",
        ),
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


def _require_contract_kind(
    dependency: ContractDependency,
    expected_kind: str,
) -> ContractDependency:
    if not isinstance(dependency, ContractDependency):
        raise PlanDependencyClosureError(
            f"{expected_kind} dependency must be a ContractDependency"
        )
    if dependency.kind != expected_kind:
        raise PlanDependencyClosureError(
            f"expected {expected_kind} dependency, got {dependency.kind!r}"
        )
    return dependency


@dataclass(frozen=True, slots=True)
class PlanDependencyClosure:
    def __init_subclass__(cls, **kwargs: Any) -> None:
        raise TypeError("PlanDependencyClosure is final")

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
    period_start: str
    period_end: str
    required_lookback_trading_days: int
    dataset_scopes: tuple[DatasetDependencyScope, ...]
    version: str = PLAN_DEPENDENCY_CLOSURE_VERSION

    def __post_init__(self) -> None:
        if self.version not in SUPPORTED_CLOSURE_VERSIONS:
            raise PlanDependencyClosureError(
                f"unsupported closure version {self.version!r}"
            )
        object.__setattr__(
            self, "feature_dependencies", tuple(self.feature_dependencies)
        )
        object.__setattr__(
            self, "universe_dependencies", tuple(self.universe_dependencies)
        )
        object.__setattr__(self, "dataset_scopes", tuple(self.dataset_scopes))
        object.__setattr__(
            self,
            "required_datasets",
            _dataset_ids(self.required_datasets, "required_datasets"),
        )
        object.__setattr__(self, "period_start", _iso_date(self.period_start, "period_start"))
        object.__setattr__(self, "period_end", _iso_date(self.period_end, "period_end"))
        if not self.feature_dependencies or not self.universe_dependencies:
            raise PlanDependencyClosureError(
                "feature and universe dependencies must be non-empty"
            )
        if self.period_start > self.period_end:
            raise PlanDependencyClosureError("closure period is reversed")
        if (
            isinstance(self.required_lookback_trading_days, bool)
            or self.required_lookback_trading_days < 0
        ):
            raise PlanDependencyClosureError(
                "closure lookback must be a non-negative integer"
            )
        if tuple(scope.dataset_id for scope in self.dataset_scopes) != self.required_datasets:
            raise PlanDependencyClosureError(
                "dataset scopes must exactly match required_datasets"
            )
        if any(
            scope.period_start != self.period_start
            or scope.period_end != self.period_end
            for scope in self.dataset_scopes
        ):
            raise PlanDependencyClosureError(
                "dataset scopes must match the plan evaluation period"
            )
        if max(
            (scope.required_lookback_trading_days for scope in self.dataset_scopes),
            default=0,
        ) != self.required_lookback_trading_days:
            raise PlanDependencyClosureError("closure lookback summary mismatch")
        scoped = self.version == PLAN_DEPENDENCY_CLOSURE_VERSION_V2
        if scoped:
            if any(not scope.requirements for scope in self.dataset_scopes):
                raise PlanDependencyClosureError(
                    "scope-enabled dataset scopes require per-consumer requirements"
                )
            for scope in self.dataset_scopes:
                derived = _derived_observation_lookback(scope.requirements)
                if derived != scope.required_lookback_trading_days:
                    raise PlanDependencyClosureError(
                        "scope-enabled lookback must be derived from declared "
                        f"trading observations for {scope.dataset_id!r}"
                    )
            validate_scoped_feature_binding(
                self.feature_dependencies, self.dataset_scopes
            )
        elif any(scope.requirements for scope in self.dataset_scopes):
            raise PlanDependencyClosureError(
                "plan-dependency-closure/v1 cannot carry scoped requirements"
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
                dependency.to_dict(scoped=self.version == PLAN_DEPENDENCY_CLOSURE_VERSION_V2)
                for dependency in self.feature_dependencies
            ],
            "universe_dependencies": [
                dependency.to_dict() for dependency in self.universe_dependencies
            ],
            "evaluation_dependency": self.evaluation_dependency.to_dict(),
            "risk_dependency": self.risk_dependency.to_dict(),
            "cost_dependency": self.cost_dependency.to_dict(),
            "research_data_profile_id": self.research_data_profile_id,
            "required_datasets": list(self.required_datasets),
            "period_start": self.period_start,
            "period_end": self.period_end,
            "required_lookback_trading_days": self.required_lookback_trading_days,
            "dataset_scopes": [scope.to_dict() for scope in self.dataset_scopes],
        }

    @property
    def closure_digest(self) -> str:
        return _canonical_digest(self.to_canonical_dict())

    def to_dict(self) -> dict[str, Any]:
        body = self.to_canonical_dict()
        body["closure_digest"] = self.closure_digest
        return body


def _require_literal_observation_counts(
    scopes: Sequence[DatasetReadScope],
    where: str,
) -> None:
    for scope in scopes:
        count = scope.observation_count
        if count is not None and count.kind != "literal":
            raise PlanDependencyClosureError(
                f"{where} has unresolved observation count for {scope.dataset_id!r}"
            )


def _effective_feature_params(definition: Any, ref: FeatureRef) -> dict[str, Any]:
    effective = dict(definition.inputs.optional_kwargs)
    effective.update(dict(ref.params))
    return effective


def _feature_consumer_id(dependency: ResolvedFeatureDependency) -> str:
    return (
        f"{dependency.feature_id}@{dependency.feature_version}#{dependency.ordinal}"
    )


def _bind_resolved_feature(dependency: ResolvedFeatureDependency) -> None:
    try:
        ref = FeatureRef(
            id=dependency.feature_id,
            version=dependency.feature_version,
            params=dict(dependency.params),
        )
        definition = resolve_feature_ref(ref)
        require_complete_feature_read_scopes(
            definition.dataset_dependencies, definition.read_scopes
        )
        resolved = resolve_dataset_read_scopes(
            definition.read_scopes, _effective_feature_params(definition, ref)
        )
        digest = features.feature_definition_digest(definition, metadata_version="v2")
    except Exception as exc:
        raise PlanDependencyClosureError(
            f"cannot bind scoped feature {dependency.feature_id!r}@"
            f"{dependency.feature_version!r}: {exc}"
        ) from exc
    if dependency.definition_digest != digest:
        raise PlanDependencyClosureError(
            f"feature {dependency.feature_id!r} definition digest mismatch"
        )
    if tuple(scope.canonical_mapping() for scope in dependency.resolved_read_scopes) != (
        tuple(scope.canonical_mapping() for scope in resolved)
    ):
        raise PlanDependencyClosureError(
            f"feature {dependency.feature_id!r} resolved read scopes mismatch"
        )
    if dependency.dataset_dependencies != definition.dataset_dependencies:
        raise PlanDependencyClosureError(
            f"feature {dependency.feature_id!r} dataset_dependencies mismatch"
        )


def validate_scoped_feature_binding(
    feature_dependencies: Sequence[ResolvedFeatureDependency],
    dataset_scopes: Sequence[DatasetDependencyScope],
) -> None:
    """Exact feature identity and per-consumer requirements for closure v2 / profile v3."""
    expected: list[tuple[str, str, str]] = []
    seen_consumers: set[str] = set()
    for dependency in feature_dependencies:
        if dependency.metadata_version != FEATURE_DEFINITION_METADATA_V2:
            raise PlanDependencyClosureError(
                "scope-enabled features require feature-definition-metadata/v2"
            )
        consumer_id = _feature_consumer_id(dependency)
        if consumer_id in seen_consumers:
            raise PlanDependencyClosureError(
                f"duplicate scoped feature consumer {consumer_id!r}"
            )
        seen_consumers.add(consumer_id)
        _bind_resolved_feature(dependency)
        _require_literal_observation_counts(
            dependency.resolved_read_scopes,
            f"feature {dependency.feature_id!r} resolved read scopes",
        )
        for scope in dependency.resolved_read_scopes:
            expected.append(
                (consumer_id, scope.dataset_id, json.dumps(scope.canonical_mapping(), sort_keys=True))
            )
    actual: list[tuple[str, str, str]] = []
    for dataset_scope in dataset_scopes:
        consumers_on_dataset: set[str] = set()
        for requirement in dataset_scope.requirements:
            if requirement.consumer_kind != "feature":
                continue
            if requirement.consumer_id in consumers_on_dataset:
                raise PlanDependencyClosureError(
                    f"duplicate feature requirement {requirement.consumer_id!r} "
                    f"on {dataset_scope.dataset_id!r}"
                )
            consumers_on_dataset.add(requirement.consumer_id)
            actual.append(
                (
                    requirement.consumer_id,
                    requirement.scope.dataset_id,
                    json.dumps(requirement.scope.canonical_mapping(), sort_keys=True),
                )
            )
    if sorted(actual) != sorted(expected):
        raise PlanDependencyClosureError(
            "feature requirements must match each feature consumer exactly"
        )


def _universe_requirements(
    universe: Sequence[ContractDependency],
) -> tuple[DatasetReadRequirement, ...]:
    requirements: list[DatasetReadRequirement] = []
    for dependency in universe:
        consumer_id = f"{dependency.dependency_id}@{dependency.version}"
        if "equities_master" in dependency.dataset_dependencies:
            requirements.append(
                DatasetReadRequirement(
                    consumer_kind="universe",
                    consumer_id=consumer_id,
                    clock="bound_decision_visible_view",
                    scope=DatasetReadScope(
                        dataset_id="equities_master",
                        initial_visible_state="latest_complete_snapshot_plus_updates",
                        fields=("code", "market_code", "scale_category", "snapshot_date"),
                    ),
                )
            )
        if "fins_summary" in dependency.dataset_dependencies:
            requirements.append(
                DatasetReadRequirement(
                    consumer_kind="universe",
                    consumer_id=consumer_id,
                    clock="bound_decision_visible_view",
                    scope=DatasetReadScope(
                        dataset_id="fins_summary",
                        initial_visible_state="all_visible_existence_and_count",
                    ),
                )
            )
        leftover = set(dependency.dataset_dependencies) - {
            "equities_master",
            "fins_summary",
        }
        if leftover:
            raise PlanDependencyClosureError(
                f"universe {dependency.dependency_id!r} has undeclared datasets: "
                f"{sorted(leftover)}"
            )
        requirements.append(
            DatasetReadRequirement(
                consumer_kind="universe",
                consumer_id=consumer_id,
                clock="bound_decision_visible_view",
                scope=DatasetReadScope(
                    dataset_id="markets_calendar",
                    fields=("date", "holiday_division"),
                ),
            )
        )
    return tuple(requirements)


def _unconsumed_membership_requirements(
    *,
    consumer_kind: str,
    consumer_id: str,
    dataset_ids: Sequence[str],
) -> tuple[DatasetReadRequirement, ...]:
    return tuple(
        DatasetReadRequirement(
            consumer_kind=consumer_kind,
            consumer_id=consumer_id,
            clock="unconsumed_policy_membership",
            scope=DatasetReadScope(
                dataset_id=dataset_id,
                unconsumed_membership=True,
            ),
        )
        for dataset_id in dataset_ids
    )


def _evaluation_requirements(
    evaluation: ContractDependency,
) -> tuple[DatasetReadRequirement, ...]:
    consumer_id = f"{evaluation.dependency_id}@{evaluation.version}"
    requirements: list[DatasetReadRequirement] = []
    unused: list[str] = []
    for dataset_id in evaluation.dataset_dependencies:
        if dataset_id == "markets_calendar":
            requirements.append(
                DatasetReadRequirement(
                    consumer_kind="evaluation",
                    consumer_id=consumer_id,
                    clock="period_end_session_close",
                    scope=DatasetReadScope(
                        dataset_id="markets_calendar",
                        fields=("date", "holiday_division"),
                    ),
                )
            )
            continue
        if dataset_id in {"equities_bars_daily", "indices_bars_daily_topix"}:
            unused.append(dataset_id)
            continue
        raise PlanDependencyClosureError(
            f"evaluation {evaluation.dependency_id!r} has undeclared dataset "
            f"{dataset_id!r}"
        )
    requirements.extend(
        _unconsumed_membership_requirements(
            consumer_kind="evaluation",
            consumer_id=consumer_id,
            dataset_ids=unused,
        )
    )
    return tuple(requirements)


def _controlled_fill_requirements() -> tuple[DatasetReadRequirement, ...]:
    consumer_id = (
        f"{CONTROLLED_FILL_CONTRACT_ID}@{CONTROLLED_FILL_CONTRACT_VERSION}"
    )
    dataset_id = CONTROLLED_FILL_SIGNAL_PRICE_DATASET
    return (
        DatasetReadRequirement(
            consumer_kind="fill_am_mark",
            consumer_id=consumer_id,
            clock="bound_decision_visible_view",
            scope=DatasetReadScope(
                dataset_id=dataset_id,
                fields=("adjustment_close", "date"),
            ),
        ),
        DatasetReadRequirement(
            consumer_kind="fill_pm_valuation",
            consumer_id=consumer_id,
            clock="same_trading_date_pm_close",
            scope=DatasetReadScope(
                dataset_id=dataset_id,
                fields=("adjustment_close", "date"),
            ),
        ),
    )


def _calendar_prerequisites(
    feature_dependencies: Sequence[ResolvedFeatureDependency],
) -> tuple[DatasetReadRequirement, ...]:
    requirements: list[DatasetReadRequirement] = []
    for dependency in feature_dependencies:
        if any(
            scope.observation_count is not None
            for scope in dependency.resolved_read_scopes
        ):
            requirements.append(
                DatasetReadRequirement(
                    consumer_kind="calendar_prerequisite",
                    consumer_id=_feature_consumer_id(dependency),
                    clock="bound_decision_visible_view",
                    scope=DatasetReadScope(
                        dataset_id="markets_calendar",
                        fields=("date", "holiday_division"),
                    ),
                )
            )
    return tuple(requirements)


def _feature_requirements(
    feature_dependencies: Sequence[ResolvedFeatureDependency],
) -> tuple[DatasetReadRequirement, ...]:
    requirements: list[DatasetReadRequirement] = []
    for dependency in feature_dependencies:
        consumer_id = _feature_consumer_id(dependency)
        for scope in dependency.resolved_read_scopes:
            requirements.append(
                DatasetReadRequirement(
                    consumer_kind="feature",
                    consumer_id=consumer_id,
                    clock="bound_decision_visible_view",
                    scope=scope,
                )
            )
    return tuple(requirements)


def _assemble_dataset_scopes(
    *,
    required_datasets: Sequence[str],
    period_start: str,
    period_end: str,
    requirements: Sequence[DatasetReadRequirement],
) -> tuple[DatasetDependencyScope, ...]:
    by_dataset: dict[str, list[DatasetReadRequirement]] = {
        dataset_id: [] for dataset_id in required_datasets
    }
    for requirement in requirements:
        dataset_id = requirement.scope.dataset_id
        if dataset_id not in by_dataset:
            raise PlanDependencyClosureError(
                f"requirement dataset {dataset_id!r} is not in required_datasets"
            )
        by_dataset[dataset_id].append(requirement)
    missing = [
        dataset_id
        for dataset_id, items in by_dataset.items()
        if not items
    ]
    if missing:
        raise PlanDependencyClosureError(
            f"missing per-dataset scope declarations for {missing}"
        )
    return tuple(
        DatasetDependencyScope(
            dataset_id=dataset_id,
            period_start=period_start,
            period_end=period_end,
            required_lookback_trading_days=_derived_observation_lookback(
                by_dataset[dataset_id]
            ),
            requirements=tuple(by_dataset[dataset_id]),
        )
        for dataset_id in sorted(required_datasets)
    )


def build_strategy_dependency_closure(
    plan_id: str,
    plan_digest: str,
    spec: StrategySpec,
    universe_dependencies: Sequence[ContractDependency],
    evaluation_dependency: ContractDependency,
    risk_dependency: ContractDependency,
    cost_dependency: ContractDependency,
    research_data_profile_id: str,
    period_start: str,
    period_end: str,
    extra_datasets: Sequence[str] = (),
    extra_requirements: Sequence[DatasetReadRequirement] = (),
    closure_version: str = PLAN_DEPENDENCY_CLOSURE_VERSION,
) -> PlanDependencyClosure:
    """Compile a dependency closure for any canonical ``StrategySpec``.

    Strategy selection is intentionally outside this compiler.  The caller
    supplies the exact spec and governed non-feature contracts; this function
    resolves every exact ``FeatureRef`` from the spec and derives the complete
    dataset and lookback scope. Default ``closure_version`` remains v1.
    """
    if not isinstance(spec, StrategySpec):
        raise PlanDependencyClosureError("canonical StrategySpec required")
    if isinstance(universe_dependencies, (str, bytes)):
        raise PlanDependencyClosureError(
            "universe dependencies must be ContractDependency values"
        )
    universe = tuple(
        _require_contract_kind(dependency, "universe")
        for dependency in universe_dependencies
    )
    evaluation = _require_contract_kind(evaluation_dependency, "evaluation")
    risk = _require_contract_kind(risk_dependency, "risk")
    cost = _require_contract_kind(cost_dependency, "cost")

    if closure_version not in SUPPORTED_CLOSURE_VERSIONS:
        raise PlanDependencyClosureError(
            f"unsupported closure version {closure_version!r}"
        )
    scoped = closure_version == PLAN_DEPENDENCY_CLOSURE_VERSION_V2
    if not scoped and extra_requirements:
        raise PlanDependencyClosureError(
            "plan-dependency-closure/v1 cannot carry extra_requirements"
        )

    feature_dependencies: list[ResolvedFeatureDependency] = []
    feature_lookbacks: list[int] = []
    for ordinal, ref in enumerate(iter_feature_refs(spec)):
        try:
            definition = resolve_feature_ref(ref)
        except Exception as exc:
            raise PlanDependencyClosureError(
                f"cannot resolve feature {ref.id!r}@{ref.version!r}: {exc}"
            ) from exc
        # FeatureRef omits optional values that intentionally use the exact
        # versioned FeatureDefinition defaults.  Scope calculation must use
        # those effective parameters without rewriting the caller's canonical
        # FeatureRef (and therefore without changing explicit-plan digests).
        effective_params = _effective_feature_params(definition, ref)
        resolved_scopes: tuple[DatasetReadScope, ...] = ()
        metadata_version = FEATURE_DEFINITION_METADATA_V1
        definition_digest = features.feature_definition_digest(definition)
        if scoped:
            try:
                require_complete_feature_read_scopes(
                    definition.dataset_dependencies, definition.read_scopes
                )
                resolved_scopes = resolve_dataset_read_scopes(
                    definition.read_scopes, effective_params
                )
                _require_literal_observation_counts(
                    resolved_scopes,
                    f"feature {ref.id!r}@{ref.version!r}",
                )
            except ValueError as exc:
                raise PlanDependencyClosureError(
                    f"cannot compile scoped feature {ref.id!r}@{ref.version!r}: {exc}"
                ) from exc
            metadata_version = FEATURE_DEFINITION_METADATA_V2
            definition_digest = features.feature_definition_digest(
                definition, metadata_version="v2"
            )
        feature_dependencies.append(
            ResolvedFeatureDependency(
                ordinal=ordinal,
                feature_id=ref.id,
                feature_version=ref.version,
                params=ref.params,
                definition_digest=definition_digest,
                dataset_dependencies=definition.dataset_dependencies,
                metadata_version=metadata_version,
                resolved_read_scopes=resolved_scopes,
            )
        )
        if not scoped:
            feature_lookbacks.append(
                max(
                    (
                        int(value)
                        for key, value in effective_params.items()
                        if key
                        in {
                            "n",
                            "short_n",
                            "long_n",
                            "lookback",
                            "lookback_days",
                            "window",
                            "window_days",
                        }
                        and isinstance(value, int)
                        and not isinstance(value, bool)
                        and value > 0
                    ),
                    default=0,
                )
            )

    required_datasets: set[str] = set()
    for dependency in feature_dependencies:
        required_datasets.update(dependency.dataset_dependencies)
    for dependency in (*universe, evaluation, risk, cost):
        required_datasets.update(dependency.dataset_dependencies)
    extra_ids = (
        set(_dataset_ids(tuple(extra_datasets), "fill contract datasets"))
        if extra_datasets
        else set()
    )
    if extra_requirements and any(
        not isinstance(item, DatasetReadRequirement) for item in extra_requirements
    ):
        raise PlanDependencyClosureError(
            "extra_requirements must be DatasetReadRequirement values"
        )
    extra_requirement_ids = {
        requirement.scope.dataset_id for requirement in extra_requirements
    }
    if scoped:
        uncovered_extra = extra_ids - extra_requirement_ids
        if uncovered_extra:
            raise PlanDependencyClosureError(
                "scope-enabled extra datasets require explicit requirements: "
                f"{sorted(uncovered_extra)}"
            )
        required_datasets.update(extra_ids)
        required_datasets.update(extra_requirement_ids)
        required_datasets.add("markets_calendar")
    elif extra_datasets:
        required_datasets.update(extra_ids)

    if scoped:
        try:
            requirements = (
                *_feature_requirements(feature_dependencies),
                *_universe_requirements(universe),
                *_evaluation_requirements(evaluation),
                *tuple(extra_requirements),
                *_unconsumed_membership_requirements(
                    consumer_kind="risk",
                    consumer_id=f"{risk.dependency_id}@{risk.version}",
                    dataset_ids=risk.dataset_dependencies,
                ),
                *_calendar_prerequisites(feature_dependencies),
            )
            _require_literal_observation_counts(
                tuple(item.scope for item in requirements),
                "scope-enabled requirements",
            )
            dataset_scopes = _assemble_dataset_scopes(
                required_datasets=tuple(sorted(required_datasets)),
                period_start=period_start,
                period_end=period_end,
                requirements=requirements,
            )
        except ValueError as exc:
            raise PlanDependencyClosureError(str(exc)) from exc
        lookback_by_dataset = {
            scope.dataset_id: scope.required_lookback_trading_days
            for scope in dataset_scopes
        }
    else:
        lookback_by_dataset = {dataset_id: 0 for dataset_id in required_datasets}
        for dependency, lookback in zip(
            feature_dependencies, feature_lookbacks, strict=True
        ):
            for dataset_id in dependency.dataset_dependencies:
                lookback_by_dataset[dataset_id] = max(
                    lookback_by_dataset.get(dataset_id, 0), lookback
                )
        dataset_scopes = tuple(
            DatasetDependencyScope(
                dataset_id=dataset_id,
                period_start=period_start,
                period_end=period_end,
                required_lookback_trading_days=lookback_by_dataset[dataset_id],
            )
            for dataset_id in sorted(required_datasets)
        )

    return PlanDependencyClosure(
        plan_id=plan_id,
        plan_digest=plan_digest,
        strategy_spec_id=spec.strategy_id,
        strategy_spec_version=spec.version,
        strategy_spec_hash=strategy_spec_digest(spec),
        feature_dependencies=tuple(feature_dependencies),
        universe_dependencies=universe,
        evaluation_dependency=evaluation,
        risk_dependency=risk,
        cost_dependency=cost,
        research_data_profile_id=research_data_profile_id,
        required_datasets=tuple(sorted(required_datasets)),
        period_start=period_start,
        period_end=period_end,
        required_lookback_trading_days=max(lookback_by_dataset.values(), default=0),
        dataset_scopes=dataset_scopes,
        version=closure_version,
    )


def build_plan_dependency_closure(
    plan: ExperimentPlan,
    *,
    closure_version: str = PLAN_DEPENDENCY_CLOSURE_VERSION,
) -> PlanDependencyClosure:
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
    universe_dependencies = tuple(
        _contract(_UNIVERSE_DEPENDENCIES, item, "universe")
        for item in plan.universe
    )
    evaluation = _contract(
        _EVALUATION_DEPENDENCIES, plan.evaluation_protocol, "evaluation"
    )
    risk = _contract(_RISK_DEPENDENCIES, plan.risk_policy, "risk")
    cost = _contract(_COST_DEPENDENCIES, plan.cost_scenario, "cost")
    fill_datasets: tuple[str, ...] = ()
    extra_requirements: tuple[DatasetReadRequirement, ...] = ()
    fill = dict(plan.fill_contract)
    signal_dataset = fill.get("signal_price_dataset")
    if type(signal_dataset) is str and signal_dataset.strip():
        fill_datasets = (signal_dataset.strip(),)
    if closure_version == PLAN_DEPENDENCY_CLOSURE_VERSION_V2:
        extra_requirements = _controlled_fill_requirements()
        fill_ids = {item.scope.dataset_id for item in extra_requirements}
        if fill_datasets and set(fill_datasets) - fill_ids:
            raise PlanDependencyClosureError(
                "scope-enabled fill datasets require explicit requirements: "
                f"{sorted(set(fill_datasets) - fill_ids)}"
            )
        fill_datasets = ()
    return build_strategy_dependency_closure(
        plan_id=plan.plan_id,
        plan_digest=experiment_plan_digest(plan),
        spec=spec,
        universe_dependencies=universe_dependencies,
        evaluation_dependency=evaluation,
        risk_dependency=risk,
        cost_dependency=cost,
        research_data_profile_id=plan.research_data_profile_id,
        period_start=plan.period_start,
        period_end=plan.period_end,
        extra_datasets=fill_datasets,
        extra_requirements=extra_requirements,
        closure_version=closure_version,
    )


def verify_plan_dependency_closure(
    plan: ExperimentPlan, closure: PlanDependencyClosure
) -> None:
    if not isinstance(closure, PlanDependencyClosure):
        raise PlanDependencyClosureError("PlanDependencyClosure required")
    rebuilt = build_plan_dependency_closure(plan, closure_version=closure.version)
    if closure.to_dict() != rebuilt.to_dict():
        raise PlanDependencyClosureError("PlanDependencyClosure mismatch")


__all__ = [
    "ContractDependency",
    "DatasetDependencyScope",
    "DatasetReadRequirement",
    "PLAN_DEPENDENCY_CLOSURE_VERSION",
    "PLAN_DEPENDENCY_CLOSURE_VERSION_V1",
    "PLAN_DEPENDENCY_CLOSURE_VERSION_V2",
    "PlanDependencyClosure",
    "PlanDependencyClosureError",
    "ResolvedFeatureDependency",
    "validate_scoped_feature_binding",
    "build_plan_dependency_closure",
    "build_strategy_dependency_closure",
    "experiment_plan_digest",
    "pilot_strategy_specs",
    "resolve_strategy_spec",
    "verify_plan_dependency_closure",
]
