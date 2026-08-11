"""Convert a composed memo into a closed StrategySpec."""

from __future__ import annotations

from strategies.spec import StrategySpec, TopKRule

from .types import ComposedMemo


class StrategistAgent:
    role = "strategist"

    def __init__(self, *, momentum_n: int = 5, top_k: int = 1) -> None:
        if momentum_n < 1 or top_k < 1:
            raise ValueError("momentum_n and top_k must be >= 1")
        self.momentum_n = int(momentum_n)
        self.top_k = int(top_k)

    def propose(self, memo: ComposedMemo) -> StrategySpec:
        return StrategySpec(
            strategy_id="agent_momentum_top_k",
            rule=TopKRule(
                feature_id="momentum_n",
                k=self.top_k,
                min_score=0.0,
                feature_params={"n": self.momentum_n},
            ),
            rationale=memo.thesis,
        )


__all__ = ["StrategistAgent"]
