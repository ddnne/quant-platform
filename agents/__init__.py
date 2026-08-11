"""Deterministic Phase 6 research-role agents and paper orchestrator."""

from .pipeline import AgentPaperPipeline, AgentPipelineResult
from .artifacts import ARTIFACT_SCHEMA_VERSION, ArtifactEnvelope
from .roles import AgentRole, Capability, ROLE_MATRIX, RoleContract
from .types import (
    AuthorizedPaperExecutionRequest,
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
    "ARTIFACT_SCHEMA_VERSION",
    "ArtifactEnvelope",
    "AuthorizedPaperExecutionRequest",
    "Capability",
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
