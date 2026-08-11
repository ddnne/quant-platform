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


@dataclass(frozen=True)
class RoleContract:
    input_type: str
    output_type: str
    may_execute: bool = False
    forbidden: tuple[str, ...] = (
        "secrets",
        "raw J-Quants",
        "SQLite handles",
        "HTTP clients",
        "arbitrary Python",
    )


ROLE_MATRIX: dict[AgentRole, RoleContract] = {
    AgentRole.MACRO: RoleContract("ResearchRequest", "ResearchMemo"),
    AgentRole.FUNDAMENTAL: RoleContract("ResearchRequest", "ResearchMemo"),
    AgentRole.QUANT: RoleContract("ResearchRequest", "ResearchMemo"),
    AgentRole.COMPOSER: RoleContract("tuple[ResearchMemo]", "ComposedMemo"),
    AgentRole.STRATEGIST: RoleContract("ComposedMemo", "StrategySpec"),
    AgentRole.PORTFOLIO_MANAGER: RoleContract(
        "StrategySpec", "PortfolioDecision"
    ),
    AgentRole.TRADER: RoleContract("PortfolioDecision", "TradePlan"),
    AgentRole.RISK: RoleContract("PaperRunResult", "RiskAudit"),
}


__all__ = ["AgentRole", "ROLE_MATRIX", "RoleContract"]
