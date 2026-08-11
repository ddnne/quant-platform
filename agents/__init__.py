"""Deterministic Phase 6 research-role agents and paper orchestrator."""

from .pipeline import AgentPaperPipeline, AgentPipelineResult
from .artifacts import ARTIFACT_SCHEMA_VERSION, ArtifactEnvelope
from .roles import AgentRole, Capability, ROLE_MATRIX, RoleContract
from .runtime import (
    NEGATIVE_BOUNDARIES,
    AgentRuntimePolicy,
    DomainTool,
    SandboxedAgentRunner,
    all_runtime_policies,
    assert_no_capability_leak,
    positive_tools_for_role,
    runtime_policy_for_role,
)
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
    "AgentRuntimePolicy",
    "ARTIFACT_SCHEMA_VERSION",
    "ArtifactEnvelope",
    "AuthorizedPaperExecutionRequest",
    "Capability",
    "ComposedMemo",
    "DomainTool",
    "FeatureProposal",
    "NEGATIVE_BOUNDARIES",
    "PortfolioDecision",
    "ROLE_MATRIX",
    "ResearchMemo",
    "ResearchRequest",
    "RiskAudit",
    "RoleContract",
    "SandboxedAgentRunner",
    "TradePlan",
    "all_runtime_policies",
    "assert_no_capability_leak",
    "positive_tools_for_role",
    "runtime_policy_for_role",
]
