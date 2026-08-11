"""Versioned research foundation artifacts (Phase 7).

Mass autonomous research remains disabled until VerifiedResearchReadiness exists
in production; these types only declare experiment lineage.
"""

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


@dataclass(frozen=True)
class ExperimentPlan:
    """One versioned experiment declaration (not a runnable mass job)."""

    plan_id: str
    idea_id: str
    strategy_spec_id: str
    feature_refs: tuple[Mapping[str, str], ...]
    ready_snapshot_id: str
    universe: tuple[str, ...]
    period_start: str
    period_end: str
    cost_scenario: str
    evaluation_protocol: str
    budget_allocation: Mapping[str, int]
    version: str = "experiment-plan/v1"

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "ExperimentPlan":
        if not isinstance(payload, Mapping):
            raise ValueError("ExperimentPlan must be an object")
        required = {
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
        missing = required - set(payload)
        if missing:
            raise ValueError(f"ExperimentPlan missing {sorted(missing)}")
        refs = payload["feature_refs"]
        if not isinstance(refs, (list, tuple)):
            raise ValueError("feature_refs must be a list")
        uni = payload["universe"]
        if not isinstance(uni, (list, tuple)):
            raise ValueError("universe must be a list")
        alloc = payload["budget_allocation"]
        if not isinstance(alloc, Mapping):
            raise ValueError("budget_allocation must be an object")
        return cls(
            plan_id=_text(payload["plan_id"], "plan_id"),
            idea_id=_text(payload["idea_id"], "idea_id"),
            strategy_spec_id=_text(payload["strategy_spec_id"], "strategy_spec_id"),
            feature_refs=tuple(dict(r) for r in refs),
            ready_snapshot_id=_text(payload["ready_snapshot_id"], "ready_snapshot_id"),
            universe=tuple(str(x) for x in uni),
            period_start=_text(payload["period_start"], "period_start"),
            period_end=_text(payload["period_end"], "period_end"),
            cost_scenario=_text(payload["cost_scenario"], "cost_scenario"),
            evaluation_protocol=_text(
                payload["evaluation_protocol"], "evaluation_protocol"
            ),
            budget_allocation={str(k): int(v) for k, v in alloc.items()},
            version=str(payload.get("version", "experiment-plan/v1")),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "plan_id": self.plan_id,
            "idea_id": self.idea_id,
            "strategy_spec_id": self.strategy_spec_id,
            "feature_refs": [dict(r) for r in self.feature_refs],
            "ready_snapshot_id": self.ready_snapshot_id,
            "universe": list(self.universe),
            "period_start": self.period_start,
            "period_end": self.period_end,
            "cost_scenario": self.cost_scenario,
            "evaluation_protocol": self.evaluation_protocol,
            "budget_allocation": dict(self.budget_allocation),
            "version": self.version,
        }


@dataclass(frozen=True)
class ExperimentInsight:
    insight_id: str
    plan_id: str
    summary: str
    outcome: str
    evidence: Mapping[str, Any] = field(default_factory=dict)
    version: str = "experiment-insight/v1"

    def to_dict(self) -> dict[str, Any]:
        return {
            "insight_id": self.insight_id,
            "plan_id": self.plan_id,
            "summary": self.summary,
            "outcome": self.outcome,
            "evidence": dict(self.evidence),
            "version": self.version,
        }


@dataclass(frozen=True)
class FeatureEvidence:
    feature_id: str
    feature_version: str
    role: str
    findings: tuple[str, ...]
    version: str = "feature-evidence/v1"

    def to_dict(self) -> dict[str, Any]:
        return {
            "feature_id": self.feature_id,
            "feature_version": self.feature_version,
            "role": self.role,
            "findings": list(self.findings),
            "version": self.version,
        }


@dataclass(frozen=True)
class RejectionReason:
    subject_id: str
    reason_codes: tuple[str, ...]
    detail: str
    version: str = "rejection-reason/v1"

    def to_dict(self) -> dict[str, Any]:
        return {
            "subject_id": self.subject_id,
            "reason_codes": list(self.reason_codes),
            "detail": self.detail,
            "version": self.version,
        }


__all__ = [
    "ExperimentInsight",
    "ExperimentPlan",
    "FeatureEvidence",
    "RejectionReason",
    "ResearchIdea",
]
