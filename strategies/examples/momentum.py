"""Top-k equal-weight strategy using the approved momentum feature."""

from __future__ import annotations

from typing import Any

import core
import features

from .return_1d import _complete_equal_weight_targets


class MomentumFeatureStrategy:
    """Hold the strongest ``top_k`` names above ``min_momentum``.

    Ties are resolved by code so identical inputs always produce identical
    orders and metadata.
    """

    strategy_id = "momentum_feature"
    feature_ids = ("momentum_n",)

    def __init__(
        self,
        db_path: Any,
        n: int = 20,
        top_k: int = 5,
        min_momentum: float = 0.0,
    ) -> None:
        self._db_path = db_path
        self.n = int(n)
        self.top_k = int(top_k)
        self.min_momentum = float(min_momentum)
        if self.n < 1:
            raise ValueError("n must be >= 1")
        if self.top_k < 1:
            raise ValueError("top_k must be >= 1")
        self.params: dict[str, Any] = {
            "n": self.n,
            "top_k": self.top_k,
            "min_momentum": self.min_momentum,
        }

    def on_bar(self, ctx: core.BarContext) -> list[core.OrderIntent]:
        candidates: list[tuple[str, float]] = []
        for code in sorted(ctx.universe):
            output = features.compute(
                "momentum_n",
                as_of=ctx.as_of,
                code=code,
                n=self.n,
                db_path=self._db_path,
            )
            if output.value is None:
                continue
            value = float(output.value)
            if value >= self.min_momentum:
                candidates.append((code, value))

        ranked = sorted(candidates, key=lambda item: (-item[1], item[0]))
        selected = {code for code, _ in ranked[: self.top_k]}
        return _complete_equal_weight_targets(ctx, selected)


__all__ = ["MomentumFeatureStrategy"]
