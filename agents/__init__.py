"""Deterministic Phase 6 research-role agents and paper orchestrator."""

from .pipeline import AgentPaperPipeline, AgentPipelineResult
from .roles import AgentRole, ROLE_MATRIX, RoleContract
from .types import (
    ComposedMemo,
    FeatureProposal,
    PortfolioDecision,
    ResearchMemo,
    ResearchRequest,
    RiskAudit,
    TradePlan,
)

__all__ = [
    "AgentPaperPipeline",
    "AgentPipelineResult",
    "AgentRole",
    "ComposedMemo",
    "FeatureProposal",
    "PortfolioDecision",
    "ROLE_MATRIX",
    "ResearchMemo",
    "ResearchRequest",
    "RiskAudit",
    "RoleContract",
    "TradePlan",
]
