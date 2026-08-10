"""Core backtest engine — a trusted black box over the PIT Data API.

The engine simulates a strategy on Japanese-equity daily bars. It is a
**black box**: agents and research code call :func:`run_backtest` and consume
the :class:`BacktestResult`; they do not reach inside. Every fact the engine
and the strategy can see enters through :mod:`pit` (``pit.get_*`` with a
required ``as_of``), never via direct SQLite — look-ahead is prevented
structurally, twice (PIT's ``available_at <= as_of`` gate + execution timing).

Quick example::

    from core import run_backtest, standard_cost
    from core.strategies.buy_hold import BuyHold

    result = run_backtest(
        BuyHold(),
        "2025-04-01", "2025-05-31",
        db_path="data/structured/ingestion.sqlite",
        execution_mode="next_close",
        cost_model=standard_cost(),
    )
    print(result.metrics)
    print(result.metadata)

See :mod:`core.engine` for the loop and guarantees, and ``docs/core_engine.md``
for the full contract.
"""

from __future__ import annotations

from .costs import CostModel, standard_cost, stress_cost
from .engine import CORE_ENGINE_VERSION, describe_strategy, run_backtest
from .execution import (
    MODES,
    NEXT_CLOSE,
    SAME_DAY_CLOSE,
    ExecutionMode,
    close_as_of,
    get_mode,
)
from .metrics import compute_metrics, max_drawdown
from .result import BacktestResult
from .strategy_protocol import (
    Bar,
    BarContext,
    EquityMaster,
    OrderIntent,
    Position,
    Strategy,
)
from .universe import build_universe, load_master

__all__ = [
    # entry point + version
    "run_backtest",
    "CORE_ENGINE_VERSION",
    "describe_strategy",
    # result / metrics
    "BacktestResult",
    "compute_metrics",
    "max_drawdown",
    # strategy interface (narrow)
    "Strategy",
    "BarContext",
    "OrderIntent",
    "Bar",
    "Position",
    "EquityMaster",
    # execution
    "ExecutionMode",
    "NEXT_CLOSE",
    "SAME_DAY_CLOSE",
    "MODES",
    "get_mode",
    "close_as_of",
    # costs
    "CostModel",
    "standard_cost",
    "stress_cost",
    # universe
    "build_universe",
    "load_master",
]

__version__ = CORE_ENGINE_VERSION
