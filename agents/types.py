"""Narrow, immutable messages exchanged by Phase 6 role agents."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from strategies.spec import StrategySpec


@dataclass(frozen=True)
class ResearchRequest:
    """Public research scope; deliberately contains no data or secret handle."""

    as_of: str
    universe: tuple[str, ...]
    objective: str = "produce one PIT-safe paper strategy"


@dataclass(frozen=True)
class FeatureProposal:
    """Governance proposal only; it does not register or approve a feature."""

    feature_id: str
    intended_role: str
    rationale: str
    status: str = "candidate"

    def __post_init__(self) -> None:
        if self.intended_role not in {"signal", "state", "structural", "utility"}:
            raise ValueError(f"unknown feature intended_role: {self.intended_role!r}")
        if self.status != "candidate":
            raise ValueError("agent feature proposals must begin as candidate")


@dataclass(frozen=True)
class ResearchMemo:
    role: str
    as_of: str
    thesis: str
    evidence: tuple[str, ...] = ()
    feature_proposals: tuple[FeatureProposal, ...] = ()


@dataclass(frozen=True)
class ComposedMemo:
    as_of: str
    thesis: str
    source_roles: tuple[str, ...]
    constraints: tuple[str, ...] = (
        "PIT reads only",
        "approved features only",
        "paper execution only",
    )


@dataclass(frozen=True)
class PortfolioDecision:
    approved: bool
    strategy_spec: StrategySpec
    max_gross_weight: float
    reasons: tuple[str, ...] = ()


@dataclass(frozen=True)
class TradePlan:
    mode: str
    strategy_id: str
    instructions: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.mode != "paper":
            raise ValueError("Phase 6 trader supports paper mode only")


@dataclass(frozen=True)
class RiskAudit:
    audit_id: str
    experiment_id: str
    run_id: str
    status: str
    checks: Mapping[str, bool]
    findings: tuple[str, ...] = ()
    metrics: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "audit_id": self.audit_id,
            "experiment_id": self.experiment_id,
            "run_id": self.run_id,
            "status": self.status,
            "checks": dict(self.checks),
            "findings": list(self.findings),
            "metrics": dict(self.metrics),
        }
