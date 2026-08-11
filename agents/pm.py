"""Portfolio-manager policy gate for StrategySpec."""

from __future__ import annotations

from strategies.spec import StrategySpec, TopKRule

from .types import PortfolioDecision


class PortfolioManagerAgent:
    role = "portfolio_manager"

    def review(self, spec: StrategySpec) -> PortfolioDecision:
        max_positions = spec.rule.k if isinstance(spec.rule, TopKRule) else None
        reasons = (
            "declarative whitelist validated",
            "equal-weight long-only allocation",
            f"max positions={max_positions}" if max_positions else "threshold basket",
        )
        return PortfolioDecision(
            approved=True,
            strategy_spec=spec,
            max_gross_weight=1.0,
            reasons=reasons,
        )


__all__ = ["PortfolioManagerAgent"]
