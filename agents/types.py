"""Narrow, immutable messages exchanged by Phase 6 role agents."""

from __future__ import annotations

import hashlib
import json
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
class AuthorizedPaperExecutionRequest:
    """Capability-free authorization for the trusted Paper runtime.

    This is data, not an executable order: it contains no broker, callable,
    credential, database path, or transport handle.
    """

    mode: str
    authorization_id: str
    strategy_id: str
    strategy_spec_hash: str
    max_gross_weight: float
    instructions: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.mode != "paper":
            raise ValueError("Phase 6 trader supports paper mode only")
        if not self.authorization_id or not self.strategy_spec_hash:
            raise ValueError("paper execution authorization requires immutable ids")
        if not 0.0 < float(self.max_gross_weight) <= 1.0:
            raise ValueError("max_gross_weight must be in (0, 1]")


# Compatibility name for callers that only inspect the structured paper plan.
TradePlan = AuthorizedPaperExecutionRequest


@dataclass(frozen=True)
class RiskAudit:
    audit_id: str
    experiment_id: str
    run_id: str
    status: str
    checks: Mapping[str, bool]
    findings: tuple[str, ...] = ()
    metrics: Mapping[str, Any] = field(default_factory=dict)

    def content_payload(self) -> dict[str, Any]:
        """Return the immutable content covered by ``audit_id``."""
        return {
            "experiment_id": self.experiment_id,
            "run_id": self.run_id,
            "status": self.status,
            "checks": dict(self.checks),
            "findings": list(self.findings),
            "metrics": dict(self.metrics),
        }

    def expected_audit_id(self) -> str:
        canonical = json.dumps(
            self.content_payload(),
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def verify_content_hash(self) -> None:
        expected = self.expected_audit_id()
        if self.audit_id != expected:
            raise ValueError(
                "risk audit_id does not match the canonical audit content"
            )

    def to_dict(self) -> dict[str, Any]:
        return {"audit_id": self.audit_id, **self.content_payload()}
