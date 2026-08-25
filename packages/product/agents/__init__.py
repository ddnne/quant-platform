"""Deterministic Phase 6 research-role agents and paper orchestrator."""

from .artifacts import ARTIFACT_SCHEMA_VERSION, ArtifactEnvelope
from .roles import AgentRole, Capability, ROLE_MATRIX, RoleContract
from .runtime import (
    NEGATIVE_BOUNDARIES,
    AgentCapabilityRouter,
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


def __getattr__(name: str):
    """Load the orchestrator lazily across the execution-authority boundary."""
    if name in {"AgentPaperPipeline", "AgentPipelineResult"}:
        from .pipeline import AgentPaperPipeline, AgentPipelineResult

        globals().update(
            {
                "AgentPaperPipeline": AgentPaperPipeline,
                "AgentPipelineResult": AgentPipelineResult,
            }
        )
        return globals()[name]
    raise AttributeError(name)


__all__ = [
    "AgentPaperPipeline",
    "AgentPipelineResult",
    "AgentRole",
    "AgentCapabilityRouter",
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
