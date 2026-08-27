"""Versioned research lineage types (Phase 7). Mass stays closed until READY."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from types import MappingProxyType
from typing import Any, Mapping, Sequence

from strategies.spec import FeatureRef, StrategySpecError


def _text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a non-empty string")
    return value.strip()


@dataclass(frozen=True)
class ResearchIdea:
    idea_id: str
    hypothesis: str
    target_horizon: str
    intended_universe: tuple[str, ...]
    candidate_concepts: tuple[str, ...]
    constraints: tuple[str, ...]
    author: str
    lineage: Mapping[str, Any] = field(default_factory=dict)
    version: str = "research-idea/v1"

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "ResearchIdea":
        if not isinstance(payload, Mapping):
            raise ValueError("ResearchIdea must be an object")
        allowed = {
            "idea_id",
            "hypothesis",
            "target_horizon",
            "intended_universe",
            "candidate_concepts",
            "constraints",
            "author",
            "lineage",
            "version",
        }
        unknown = sorted(set(payload) - allowed)
        if unknown:
            raise ValueError(f"ResearchIdea unknown field(s): {unknown}")
        for req in (
            "idea_id",
            "hypothesis",
            "target_horizon",
            "intended_universe",
            "author",
        ):
            if req not in payload:
                raise ValueError(f"ResearchIdea missing {req}")
        uni = payload["intended_universe"]
        if not isinstance(uni, (list, tuple)):
            raise ValueError("intended_universe must be a list")
        concepts = payload.get("candidate_concepts", ())
        if not isinstance(concepts, (list, tuple)):
            raise ValueError("candidate_concepts must be a list")
        constraints = payload.get("constraints", ())
        if not isinstance(constraints, (list, tuple)):
            raise ValueError("constraints must be a list")
        lineage = payload.get("lineage") or {}
        if not isinstance(lineage, Mapping):
            raise ValueError("lineage must be an object")
        return cls(
            idea_id=_text(payload["idea_id"], "idea_id"),
            hypothesis=_text(payload["hypothesis"], "hypothesis"),
            target_horizon=_text(payload["target_horizon"], "target_horizon"),
            intended_universe=tuple(str(x) for x in uni),
            candidate_concepts=tuple(str(x) for x in concepts),
            constraints=tuple(str(x) for x in constraints),
            author=_text(payload["author"], "author"),
            lineage=dict(lineage),
            version=str(payload.get("version", "research-idea/v1")),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "idea_id": self.idea_id,
            "hypothesis": self.hypothesis,
            "target_horizon": self.target_horizon,
            "intended_universe": list(self.intended_universe),
            "candidate_concepts": list(self.candidate_concepts),
            "constraints": list(self.constraints),
            "author": self.author,
            "lineage": dict(self.lineage),
            "version": self.version,
        }


EXPERIMENT_PLAN_VERSION_V1: str = "experiment-plan/v1"
EXPERIMENT_PLAN_VERSION: str = "experiment-plan/v2"
CORE_RESEARCH_DATA_PROFILE_ID: str = "core"
PLAN_UNIVERSE_IDS: frozenset[str] = frozenset({"tse_prime_with_fins"})
PLAN_COST_SCENARIOS: frozenset[str] = frozenset({"default_one_way_10bp"})
PLAN_EVALUATION_PROTOCOLS: frozenset[str] = frozenset(
    {"standard_research_eval"}
)
PLAN_RISK_POLICIES: frozenset[str] = frozenset({"core_crash_high_vol"})
PLAN_BUDGET_COUNTERS: frozenset[str] = frozenset(
    {
        "generations",
        "model_calls",
        "input_tokens",
        "output_tokens",
        "cached_tokens",
        "paper_runs",
        "compute_time_ms",
        "estimated_cost_micros",
    }
)
_SHA256_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_PLAN_FIELDS = {
    "plan_id",
    "idea_id",
    "hypothesis",
    "strategy_spec_id",
    "strategy_spec_version",
    "strategy_spec_hash",
    "feature_refs",
    "research_data_profile_id",
    "universe",
    "period_start",
    "period_end",
    "cost_scenario",
    "evaluation_protocol",
    "risk_policy",
    "budget_allocation",
    "execution_enabled",
    "version",
}
_PLAN_REQUIRED = {
    "version",
    "plan_id",
    "idea_id",
    "hypothesis",
    "strategy_spec_id",
    "strategy_spec_version",
    "strategy_spec_hash",
    "feature_refs",
    "research_data_profile_id",
    "universe",
    "period_start",
    "period_end",
    "cost_scenario",
    "evaluation_protocol",
    "risk_policy",
    "budget_allocation",
    "execution_enabled",
}


def _iso_date(value: Any, label: str) -> str:
    text = _text(value, label)
    try:
        parsed = date.fromisoformat(text)
    except ValueError as exc:
        raise ValueError(f"{label} must be an ISO date (YYYY-MM-DD)") from exc
    if parsed.isoformat() != text:
        raise ValueError(f"{label} must be an ISO date (YYYY-MM-DD)")
    return text


def _enum(value: Any, label: str, allowed: frozenset[str]) -> str:
    text = _text(value, label)
    if text not in allowed:
        raise ValueError(f"{label} must be one of {sorted(allowed)}")
    return text


def _sha256(value: Any, label: str) -> str:
    text = _text(value, label)
    if _SHA256_RE.fullmatch(text) is None:
        raise ValueError(f"{label} must be a canonical sha256 digest")
    return text


@dataclass(frozen=True, slots=True)
class LegacyExperimentPlanV1:
    """Audit-only view of a v1 declaration; never execution eligible."""

    payload: Mapping[str, Any]
    version: str = EXPERIMENT_PLAN_VERSION_V1
    execution_eligible: bool = False

    def to_dict(self) -> dict[str, Any]:
        return _thaw_json(self.payload)


def _freeze_json(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType(
            {str(key): _freeze_json(item) for key, item in value.items()}
        )
    if isinstance(value, (list, tuple)):
        return tuple(_freeze_json(item) for item in value)
    return value


def _thaw_json(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _thaw_json(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw_json(item) for item in value]
    return value


def load_legacy_experiment_plan(payload: Mapping[str, Any]) -> LegacyExperimentPlanV1:
    if not isinstance(payload, Mapping):
        raise ValueError("legacy ExperimentPlan must be an object")
    if payload.get("version") != EXPERIMENT_PLAN_VERSION_V1:
        raise ValueError(
            f"legacy ExperimentPlan version must be {EXPERIMENT_PLAN_VERSION_V1}"
        )
    if payload.get("execution_enabled", False) is not False:
        raise ValueError("legacy ExperimentPlan execution_enabled must be false")
    return LegacyExperimentPlanV1(payload=_freeze_json(payload))


@dataclass(frozen=True, slots=True)
class ExperimentPlan:
    """One versioned experiment declaration (not a runnable mass job)."""

    def __init_subclass__(cls, **kwargs: Any) -> None:
        raise TypeError("ExperimentPlan is final")

    def __post_init__(self) -> None:
        object.__setattr__(self, "feature_refs", tuple(self.feature_refs))
        object.__setattr__(self, "universe", tuple(self.universe))
        object.__setattr__(
            self,
            "budget_allocation",
            MappingProxyType(dict(sorted(self.budget_allocation.items()))),
        )

    plan_id: str
    idea_id: str
    strategy_spec_id: str
    strategy_spec_version: str
    strategy_spec_hash: str
    feature_refs: tuple[FeatureRef, ...]
    universe: tuple[str, ...]
    period_start: str
    period_end: str
    cost_scenario: str
    evaluation_protocol: str
    risk_policy: str
    budget_allocation: Mapping[str, int]
    hypothesis: str = ""
    research_data_profile_id: str = CORE_RESEARCH_DATA_PROFILE_ID
    execution_enabled: bool = False
    version: str = EXPERIMENT_PLAN_VERSION

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "ExperimentPlan":
        if not isinstance(payload, Mapping):
            raise ValueError("ExperimentPlan must be an object")
        unknown = sorted(set(payload) - _PLAN_FIELDS)
        if unknown:
            raise ValueError(f"ExperimentPlan unknown field(s): {unknown}")
        missing = _PLAN_REQUIRED - set(payload)
        if missing:
            raise ValueError(f"ExperimentPlan missing {sorted(missing)}")
        version = payload.get("version")
        if version == EXPERIMENT_PLAN_VERSION_V1:
            raise ValueError(
                "experiment-plan/v1 is audit-only; use load_legacy_experiment_plan"
            )
        if version != EXPERIMENT_PLAN_VERSION:
            raise ValueError(
                f"unsupported ExperimentPlan version {version!r}; "
                f"expected {EXPERIMENT_PLAN_VERSION!r}"
            )
        refs = payload["feature_refs"]
        if not isinstance(refs, (list, tuple)) or not refs:
            raise ValueError("feature_refs must be a non-empty list")
        try:
            feature_refs = tuple(FeatureRef.from_dict(raw) for raw in refs)
        except StrategySpecError as exc:
            raise ValueError(f"invalid feature_refs: {exc}") from exc
        canonical_refs = tuple(
            (ref.id, ref.version, tuple(sorted(ref.params.items())))
            for ref in feature_refs
        )
        if len(canonical_refs) != len(set(canonical_refs)):
            raise ValueError("feature_refs cannot contain duplicates")
        uni = payload["universe"]
        if not isinstance(uni, (list, tuple)) or not uni:
            raise ValueError("universe must be a non-empty list")
        universe = tuple(_enum(item, "universe[]", PLAN_UNIVERSE_IDS) for item in uni)
        if len(universe) != len(set(universe)):
            raise ValueError("universe cannot contain duplicates")
        alloc = payload["budget_allocation"]
        if not isinstance(alloc, Mapping) or not alloc:
            raise ValueError("budget_allocation must be a non-empty object")
        budget: dict[str, int] = {}
        for raw_key, raw_value in alloc.items():
            key = _text(raw_key, "budget_allocation key")
            if key not in PLAN_BUDGET_COUNTERS:
                raise ValueError(f"unknown budget_allocation counter {key!r}")
            if isinstance(raw_value, bool) or not isinstance(raw_value, int):
                raise ValueError(f"budget_allocation.{key} must be an integer")
            if raw_value <= 0:
                raise ValueError(f"budget_allocation.{key} must be positive")
            budget[key] = raw_value
        if payload.get("execution_enabled") is not False:
            raise ValueError("ExperimentPlan execution_enabled must be false")
        profile_raw = payload.get("research_data_profile_id")
        profile_id = (
            CORE_RESEARCH_DATA_PROFILE_ID
            if profile_raw is None
            else _text(profile_raw, "research_data_profile_id")
        )
        hypothesis = payload.get("hypothesis", "")
        if hypothesis is None:
            hypothesis = ""
        if not isinstance(hypothesis, str):
            raise ValueError("hypothesis must be a string")
        period_start = _iso_date(payload["period_start"], "period_start")
        period_end = _iso_date(payload["period_end"], "period_end")
        if period_start > period_end:
            raise ValueError("period_start must be on or before period_end")
        return cls(
            plan_id=_text(payload["plan_id"], "plan_id"),
            idea_id=_text(payload["idea_id"], "idea_id"),
            strategy_spec_id=_text(payload["strategy_spec_id"], "strategy_spec_id"),
            strategy_spec_version=_text(
                payload["strategy_spec_version"], "strategy_spec_version"
            ),
            strategy_spec_hash=_sha256(
                payload["strategy_spec_hash"], "strategy_spec_hash"
            ),
            feature_refs=feature_refs,
            universe=universe,
            period_start=period_start,
            period_end=period_end,
            cost_scenario=_enum(
                payload["cost_scenario"], "cost_scenario", PLAN_COST_SCENARIOS
            ),
            evaluation_protocol=_enum(
                payload["evaluation_protocol"],
                "evaluation_protocol",
                PLAN_EVALUATION_PROTOCOLS,
            ),
            risk_policy=_enum(
                payload["risk_policy"], "risk_policy", PLAN_RISK_POLICIES
            ),
            budget_allocation=MappingProxyType(dict(sorted(budget.items()))),
            hypothesis=hypothesis.strip(),
            research_data_profile_id=profile_id,
            execution_enabled=False,
            version=version,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "plan_id": self.plan_id,
            "idea_id": self.idea_id,
            "hypothesis": self.hypothesis,
            "strategy_spec_id": self.strategy_spec_id,
            "strategy_spec_version": self.strategy_spec_version,
            "strategy_spec_hash": self.strategy_spec_hash,
            "feature_refs": [ref.to_dict() for ref in self.feature_refs],
            "research_data_profile_id": self.research_data_profile_id,
            "universe": list(self.universe),
            "period_start": self.period_start,
            "period_end": self.period_end,
            "cost_scenario": self.cost_scenario,
            "evaluation_protocol": self.evaluation_protocol,
            "risk_policy": self.risk_policy,
            "budget_allocation": dict(self.budget_allocation),
            "execution_enabled": False,
            "version": self.version,
        }


__all__ = [
    "CORE_RESEARCH_DATA_PROFILE_ID",
    "EXPERIMENT_PLAN_VERSION",
    "EXPERIMENT_PLAN_VERSION_V1",
    "ExperimentPlan",
    "LegacyExperimentPlanV1",
    "PLAN_BUDGET_COUNTERS",
    "PLAN_COST_SCENARIOS",
    "PLAN_EVALUATION_PROTOCOLS",
    "PLAN_RISK_POLICIES",
    "PLAN_UNIVERSE_IDS",
    "ResearchIdea",
    "load_legacy_experiment_plan",
]
