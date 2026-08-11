"""Equal-weight strategy selected by the approved one-day return feature."""

from __future__ import annotations

from typing import Any

import core
import features


class Return1dFeatureStrategy:
    """Hold names whose one-session return is above ``threshold``.

    A target is emitted for every current universe member and open position.
    That makes every call a complete rebalance: selected names receive equal
    weight and everything else receives a zero target.
    """

    strategy_id = "return_1d_feature"
    feature_ids = ("return_1d",)

    def __init__(self, db_path: Any, threshold: float = 0.0) -> None:
        self._db_path = db_path
        self.threshold = float(threshold)
        self.params: dict[str, Any] = {"threshold": self.threshold}

    def on_bar(self, ctx: core.BarContext) -> list[core.OrderIntent]:
        selected: set[str] = set()
        for code in sorted(ctx.universe):
            output = features.compute(
                "return_1d",
                as_of=ctx.as_of,
                code=code,
                db_path=self._db_path,
            )
            if output.value is not None and float(output.value) > self.threshold:
                selected.add(code)

        return _complete_equal_weight_targets(ctx, selected)


def _complete_equal_weight_targets(
    ctx: core.BarContext,
    selected: set[str],
) -> list[core.OrderIntent]:
    """Return deterministic targets, including zero targets for exits."""
    all_codes = sorted(set(ctx.universe) | set(ctx.positions))
    weight = 1.0 / len(selected) if selected else 0.0
    return [
        core.OrderIntent(
            code=code,
            target_weight=weight if code in selected else 0.0,
        )
        for code in all_codes
    ]


__all__ = ["Return1dFeatureStrategy"]
