"""Performance metrics for a finished backtest.

A minimal, unambiguous subset, as required by the Phase 3 handoff:

* total return **pre-cost** and **post-cost**
* maximum drawdown (on the post-cost equity curve)
* trade count and a turnover proxy (sum of one-way traded notional)

Pre-cost vs post-cost: the engine runs a single (post-cost) equity curve —
costs are deducted from cash at fill time. We recover the pre-cost return by
adding the cumulative cost paid back to the terminal equity. This is exact at
the terminal instant and ignores the return the freed cash would have earned
in between; that approximation is documented and fine for a minimal engine.
"""

from __future__ import annotations

from typing import Any


def max_drawdown(equity_series: list[float]) -> float:
    """Peak-to-trough max drawdown as a non-positive fraction.

    Returns ``0.0`` for a flat/empty/non-decreasing curve. Computed on the
    running peak so it is the true max drawdown of the series.
    """
    if not equity_series:
        return 0.0
    peak = equity_series[0]
    mdd = 0.0
    for v in equity_series[1:]:
        if v > peak:
            peak = v
        if peak > 0:
            dd = v / peak - 1.0
            if dd < mdd:
                mdd = dd
    return mdd


def compute_metrics(
    *,
    equity_curve: list[dict[str, Any]],
    trades: list[dict[str, Any]],
) -> dict[str, Any]:
    """Compute the minimal metric subset from an equity curve and trade log.

    ``equity_curve`` items carry ``equity`` (post-cost total equity per day);
    ``trades`` items carry ``notional`` and ``cost``.
    """
    equities = [row["equity"] for row in equity_curve]
    start_equity = equities[0] if equities else 0.0
    end_equity = equities[-1] if equities else 0.0
    total_cost = float(sum(t.get("cost", 0.0) for t in trades))
    turnover = float(sum(abs(t.get("notional", 0.0)) for t in trades))

    post_return = end_equity / start_equity - 1.0 if start_equity else 0.0
    # Counterfactual terminal equity had no costs been deducted from cash.
    pre_end_equity = end_equity + total_cost
    pre_return = pre_end_equity / start_equity - 1.0 if start_equity else 0.0

    return {
        "total_return_pre_cost": pre_return,
        "total_return_post_cost": post_return,
        "cost_drag": total_cost,
        "max_drawdown": max_drawdown(equities),
        "num_trades": len(trades),
        "turnover_notional": turnover,
        "num_trading_days": len(equity_curve),
    }
