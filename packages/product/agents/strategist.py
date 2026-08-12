"""Convert a composed memo into a closed StrategySpec."""

from __future__ import annotations

from strategies.spec import FeatureRef, StrategySpec, TopKRule

from .types import ComposedMemo
from .roles import AgentRole, ROLE_MATRIX


class StrategistAgent:
    role = "strategist"
    capabilities = ROLE_MATRIX[AgentRole.STRATEGIST].capabilities

    def __init__(
        self,
        *,
        momentum_n: int = 5,
        top_k: int = 1,
        momentum_version: str = "1.0.0",
    ) -> None:
        if momentum_n < 1 or top_k < 1:
            raise ValueError("momentum_n and top_k must be >= 1")
        self.momentum_n = int(momentum_n)
        self.top_k = int(top_k)
        self.momentum_version = str(momentum_version)

    def propose(self, memo: ComposedMemo) -> StrategySpec:
        return StrategySpec(
            strategy_id="agent_momentum_top_k",
            rule=TopKRule(
                feature=FeatureRef(
                    id="momentum_n",
                    version=self.momentum_version,
                    params={"n": self.momentum_n},
                ),
                k=self.top_k,
                min_score=0.0,
            ),
            rationale=memo.thesis,
        )


__all__ = ["StrategistAgent"]
