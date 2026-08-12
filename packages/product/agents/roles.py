"""Role names and capability boundaries for the Phase 6 agent team."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class AgentRole(str, Enum):
    MACRO = "macro"
    FUNDAMENTAL = "fundamental"
    QUANT = "quant"
    COMPOSER = "composer"
    STRATEGIST = "strategist"
    PORTFOLIO_MANAGER = "portfolio_manager"
    TRADER = "trader"
    RISK = "risk"


class Capability(str, Enum):
    """Positive capabilities; absence is the authority boundary."""

    STRUCTURED_RESEARCH = "structured_research"
    COMPOSE_MEMOS = "compose_memos"
    PROPOSE_STRATEGY_SPEC = "propose_strategy_spec"
    AUTHORIZE_PAPER = "authorize_paper"
    REQUEST_PAPER_EXECUTION = "request_paper_execution"
    AUDIT_IMMUTABLE_PAPER = "audit_immutable_paper"


@dataclass(frozen=True)
class RoleContract:
    input_type: str
    output_type: str
    capabilities: frozenset[Capability]

    @property
    def may_execute(self) -> bool:
        # No role capability includes engine, shell, HTTP, broker, or storage.
        return False


ROLE_MATRIX: dict[AgentRole, RoleContract] = {
    AgentRole.MACRO: RoleContract("ResearchRequest", "ResearchMemo", frozenset({Capability.STRUCTURED_RESEARCH})),
    AgentRole.FUNDAMENTAL: RoleContract("ResearchRequest", "ResearchMemo", frozenset({Capability.STRUCTURED_RESEARCH})),
    AgentRole.QUANT: RoleContract("ResearchRequest", "ResearchMemo", frozenset({Capability.STRUCTURED_RESEARCH})),
    AgentRole.COMPOSER: RoleContract("tuple[ResearchMemo]", "ComposedMemo", frozenset({Capability.COMPOSE_MEMOS})),
    AgentRole.STRATEGIST: RoleContract("ComposedMemo", "StrategySpec", frozenset({Capability.PROPOSE_STRATEGY_SPEC})),
    AgentRole.PORTFOLIO_MANAGER: RoleContract(
        "StrategySpec", "PortfolioDecision", frozenset({Capability.AUTHORIZE_PAPER})
    ),
    AgentRole.TRADER: RoleContract("PortfolioDecision", "AuthorizedPaperExecutionRequest", frozenset({Capability.REQUEST_PAPER_EXECUTION})),
    AgentRole.RISK: RoleContract("PaperRunResult", "RiskAudit", frozenset({Capability.AUDIT_IMMUTABLE_PAPER})),
}


__all__ = ["AgentRole", "Capability", "ROLE_MATRIX", "RoleContract"]
