"""Buy & hold dummy strategy (test-only).

Equal-weight buy & hold: on the first decision bar, go long every universe
code at equal weight (``1 / N``); thereafter return ``[]`` (no rebalancing).
Because the engine only trades the delta versus the current position, the
strategy incurs cost only on its single entry — a clean, minimal way to prove
the engine fills once and then holds.
"""

from __future__ import annotations

from typing import Any

from ..strategy_protocol import BarContext, OrderIntent


class BuyHold:
    """Equal-weight buy & hold across the as-of universe.

    ``strategy_id`` and ``params`` make the strategy reproducibly identifiable
    in :class:`~core.result.BacktestResult` metadata.
    """

    strategy_id = "buy_hold"

    def __init__(self) -> None:
        # params intentionally captures only configuration, not runtime state.
        self.params: dict[str, Any] = {"rebalance": False}
        self._entered = False

    def on_bar(self, ctx: BarContext) -> list[OrderIntent]:
        if self._entered:
            return []
        # Only enter on names with a visible price; under same_day_close the
        # decision is at the session open, so today's close is not yet visible
        # and we wait a session rather than entering blind.
        tradeable = [c for c in ctx.universe if ctx.prices.get(c) is not None]
        if not tradeable:
            return []
        self._entered = True
        weight = 1.0 / len(tradeable)
        return [OrderIntent(code=code, target_weight=weight) for code in tradeable]
