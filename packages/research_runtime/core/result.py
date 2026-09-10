"""Backtest result + reproducibility metadata.

A :class:`BacktestResult` always carries enough metadata to reproduce the
run: the engine version, the PIT API version it read through, the period, the
``as_of`` / universe / execution / cost rules, and a deterministic identity of
the strategy (id + params + a short hash). None of this depends on wall-clock
time or randomness, so two runs with identical inputs produce identical
metadata — the basis of the reproducibility test.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class GrossLimitObservation:
    """PM-marked gross versus an AM-frozen limit. Never a quantity rewrite."""

    date: str
    decision_timestamp: str
    limit: float
    observed_gross_weight: float | None
    observed_equity: float | None
    observed_gross_notional: float | None
    status: str
    resized: bool = False
    undefined_ratio_reason: str | None = None
    partial_marked_equity: float | None = None
    partial_marked_gross_notional: float | None = None
    unpriced_held_codes: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        weight = self.observed_gross_weight
        if weight is not None and not (
            isinstance(weight, float) and math.isfinite(weight)
        ):
            weight = None
        payload = {
            "date": self.date,
            "decision_timestamp": self.decision_timestamp,
            "limit": self.limit,
            "observed_gross_weight": weight,
            "observed_equity": self.observed_equity,
            "observed_gross_notional": self.observed_gross_notional,
            "status": self.status,
            "resized": self.resized,
            "undefined_ratio_reason": self.undefined_ratio_reason,
            "filled_quantities_changed": False,
            "correction_timing": "next_observable_am_decision",
        }
        if self.status == "INCOMPLETE":
            payload["partial_marked_equity"] = self.partial_marked_equity
            payload["partial_marked_gross_notional"] = self.partial_marked_gross_notional
            payload["unpriced_held_codes"] = list(self.unpriced_held_codes)
        return payload


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
