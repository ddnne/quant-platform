"""Versioned research lineage types (Phase 7). Mass stays closed until READY."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence


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


EXPERIMENT_PLAN_VERSION: str = "experiment-plan/v1"
CORE_RESEARCH_DATA_PROFILE_ID: str = "core"
_PLAN_FIELDS = {
    "plan_id",
    "idea_id",
    "hypothesis",
    "strategy_spec_id",
    "feature_refs",
    "research_data_profile_id",
    "ready_snapshot_id",
    "universe",
    "period_start",
    "period_end",
    "cost_scenario",
    "evaluation_protocol",
    "budget_allocation",
    "execution_enabled",
    "version",
}
_PLAN_REQUIRED = {
    "plan_id",
    "idea_id",
    "strategy_spec_id",
    "feature_refs",
    "ready_snapshot_id",
    "universe",
    "period_start",
    "period_end",
    "cost_scenario",
    "evaluation_protocol",
    "budget_allocation",
}
_FEATURE_REF_FIELDS = {"id", "version", "params"}


def _feature_ref(raw: Any, *, index: int) -> dict[str, Any]:
    if not isinstance(raw, Mapping):
        raise ValueError(f"feature_refs[{index}] must be an object")
    unknown = sorted(set(raw) - _FEATURE_REF_FIELDS)
    if unknown:
        raise ValueError(
            f"feature_refs[{index}] unknown field(s): {unknown}"
        )
    feature_id = _text(raw.get("id"), f"feature_refs[{index}].id")
    version = _text(raw.get("version"), f"feature_refs[{index}].version")
    out: dict[str, Any] = {"id": feature_id, "version": version}
    if "params" in raw:
        params = raw["params"]
        if not isinstance(params, Mapping):
            raise ValueError(f"feature_refs[{index}].params must be an object")
        out["params"] = dict(params)
    return out


@dataclass(frozen=True)
class ExperimentPlan:
    """One versioned experiment declaration (not a runnable mass job)."""

    plan_id: str
    idea_id: str
    strategy_spec_id: str
    feature_refs: tuple[Mapping[str, Any], ...]
    ready_snapshot_id: str
    universe: tuple[str, ...]
    period_start: str
    period_end: str
    cost_scenario: str
    evaluation_protocol: str
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
        refs = payload["feature_refs"]
        if not isinstance(refs, (list, tuple)) or not refs:
            raise ValueError("feature_refs must be a non-empty list")
        feature_refs = tuple(
            _feature_ref(raw, index=i) for i, raw in enumerate(refs)
        )
        uni = payload["universe"]
        if not isinstance(uni, (list, tuple)) or not uni:
            raise ValueError("universe must be a non-empty list")
        alloc = payload["budget_allocation"]
        if not isinstance(alloc, Mapping) or not alloc:
            raise ValueError("budget_allocation must be a non-empty object")
        version = str(payload.get("version", EXPERIMENT_PLAN_VERSION)).strip()
        if version != EXPERIMENT_PLAN_VERSION:
            raise ValueError(
                f"unsupported ExperimentPlan version {version!r}; "
                f"expected {EXPERIMENT_PLAN_VERSION!r}"
            )
        if "execution_enabled" in payload and payload["execution_enabled"] is not False:
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
        return cls(
            plan_id=_text(payload["plan_id"], "plan_id"),
            idea_id=_text(payload["idea_id"], "idea_id"),
            strategy_spec_id=_text(payload["strategy_spec_id"], "strategy_spec_id"),
            feature_refs=feature_refs,
            ready_snapshot_id=_text(payload["ready_snapshot_id"], "ready_snapshot_id"),
            universe=tuple(str(x) for x in uni),
            period_start=_text(payload["period_start"], "period_start"),
            period_end=_text(payload["period_end"], "period_end"),
            cost_scenario=_text(payload["cost_scenario"], "cost_scenario"),
            evaluation_protocol=_text(
                payload["evaluation_protocol"], "evaluation_protocol"
            ),
            budget_allocation={str(k): int(v) for k, v in alloc.items()},
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
            "feature_refs": [dict(r) for r in self.feature_refs],
            "research_data_profile_id": self.research_data_profile_id,
            "ready_snapshot_id": self.ready_snapshot_id,
            "universe": list(self.universe),
            "period_start": self.period_start,
            "period_end": self.period_end,
            "cost_scenario": self.cost_scenario,
            "evaluation_protocol": self.evaluation_protocol,
            "budget_allocation": dict(self.budget_allocation),
            "execution_enabled": False,
            "version": self.version,
        }


__all__ = [
    "CORE_RESEARCH_DATA_PROFILE_ID",
    "EXPERIMENT_PLAN_VERSION",
    "ExperimentPlan",
    "ResearchIdea",
]
