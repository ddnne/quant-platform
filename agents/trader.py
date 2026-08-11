"""Paper-only trader handoff; no broker or order API exists here."""

from __future__ import annotations

from .types import PortfolioDecision, TradePlan


class TraderAgent:
    role = "trader"

    def prepare(self, decision: PortfolioDecision) -> TradePlan:
        if not decision.approved:
            raise ValueError("trader refuses an unapproved portfolio decision")
        return TradePlan(
            mode="paper",
            strategy_id=decision.strategy_spec.strategy_id,
            instructions=(
                "interpret the reviewed StrategySpec",
                "run through strategies.paper.run_paper",
                "do not contact a broker",
            ),
        )


__all__ = ["TraderAgent"]
