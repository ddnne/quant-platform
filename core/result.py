"""Backtest result + reproducibility metadata.

A :class:`BacktestResult` always carries enough metadata to reproduce the
run: the engine version, the PIT API version it read through, the period, the
``as_of`` / universe / execution / cost rules, and a deterministic identity of
the strategy (id + params + a short hash). None of this depends on wall-clock
time or randomness, so two runs with identical inputs produce identical
metadata — the basis of the reproducibility test.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class BacktestResult:
    """The outcome of one ``run_backtest`` call.

    Attributes:
        equity_curve: Per-trading-day ``{date, cash, positions_value, equity}``
            (post-cost, marked at each session close).
        trades: Fill log: ``{decision_date, fill_date, code, side, shares,
            price, notional, cost}``.
        metrics: Output of :func:`core.metrics.compute_metrics`.
        metadata: Reproducibility block (see module docstring).
    """

    equity_curve: list[dict[str, Any]] = field(default_factory=list)
    trades: list[dict[str, Any]] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    def total_return_post_cost(self) -> float:
        """Convenience accessor for the headline post-cost total return."""
        return float(self.metrics.get("total_return_post_cost", 0.0))
