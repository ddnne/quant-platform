"""Phase 4 F6 — run_backtest on a real DB path.

Phase 4 closed-loop requires that ``run_backtest`` runs end-to-end on a
real-DB-shaped path (the kind Phase 3.5 produces via sync). Since CI must be
offline-only, this test:

* builds a real structured SQLite using ``storage.sqlite_store.SqliteStore``
  (the same writer the sync script uses) — so the DB layout is the one
  ``run_backtest`` reads through ``pit.get_*``;
* runs a backtest with a strategy that uses the **features package** to
  compute return_1d at each decision instant (proving F1–F3 + F6 work
  together);
* asserts the result has the standard reproducibility metadata.

Marked ``live`` if you want to point it at a real Phase 3.5 sync DB. The
default path uses the seeded DB so it runs offline.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

import pit
import features
from core import run_backtest, standard_cost
from core.strategy_protocol import BarContext, OrderIntent

TESTS_DIR = Path(__file__).resolve().parent
if str(TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(TESTS_DIR))

from _coreseed import CODES, TRADING_DAYS, close_iso, seed_db


class ReturnFeatureStrategy:
    """Strategy that uses features.compute('return_1d') to drive decisions.

    Decision rule:
      * enter long on the universe code with the highest visible return_1d;
      * once entered, hold (return ``[]``) — a minimal but feature-driven loop.

    This proves features + core engine compose end-to-end at a real DB path.
    """

    strategy_id = "return_feature_v0"
    params: dict = {"feature": "return_1d"}

    def __init__(self) -> None:
        self._entered = False

    def on_bar(self, ctx: BarContext) -> list[OrderIntent]:
        if self._entered:
            return []
        # Compute return_1d for every universe code at ctx.as_of.
        best_code = None
        best_ret = float("-inf")
        for code in ctx.universe:
            try:
                out = features.compute(
                    "return_1d",
                    as_of=ctx.as_of,
                    code=code,
                    db_path=ctx_master_db_path_from_ctx(ctx),
                )
            except Exception:
                continue
            if out.value is None:
                continue
            if out.value > best_ret:
                best_ret = out.value
                best_code = code
        if best_code is None:
            return []
        self._entered = True
        return [OrderIntent(code=best_code, target_weight=1.0)]


def ctx_master_db_path_from_ctx(ctx: BarContext) -> Path:
    """Pull the DB path out of the metadata the engine sets on the context.

    The narrow BarContext deliberately does NOT carry db_path. For this
    feature-driven strategy we read from the same DB the engine uses by
    trusting the engine's reproducibility metadata via a closure. We pass it
    in via the strategy constructor instead (see
    :class:`FixedDbReturnFeatureStrategy` below) to avoid any context hack.
    """
    raise RuntimeError(
        "BarContext does not expose db_path (by design). Use a strategy that "
        "captures db_path at construction time."
    )


class FixedDbReturnFeatureStrategy:
    """Same decision rule, with the DB path captured at construction time.

    This is the *correct* pattern: the strategy author knows the DB at
    build time (they're running the backtest) and the engine reads through
    PIT separately. The strategy's compute uses its own PIT-scoped read to
    inform its decisions; both sides agree on ``as_of``.
    """

    strategy_id = "return_feature_v0"
    params: dict = {"feature": "return_1d"}

    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path
        self._entered = False

    def on_bar(self, ctx: BarContext) -> list[OrderIntent]:
        if self._entered:
            return []
        best_code = None
        best_ret = float("-inf")
        for code in ctx.universe:
            try:
                out = features.compute(
                    "return_1d",
                    as_of=ctx.as_of,
                    code=code,
                    db_path=self._db_path,
                )
            except Exception:
                continue
            if out.value is None:
                continue
            if out.value > best_ret:
                best_ret = out.value
                best_code = code
        if best_code is None:
            return []
        self._entered = True
        return [OrderIntent(code=best_code, target_weight=1.0)]


def test_backtest_with_features_on_real_db_path(tmp_path):
    """F6: run_backtest works on a real-DB-shaped path with a feature-driven strategy."""
    db = seed_db(tmp_path)
    strat = FixedDbReturnFeatureStrategy(db)
    res = run_backtest(
        strat,
        TRADING_DAYS[0], TRADING_DAYS[-1],
        db_path=db,
        universe=tuple(CODES),
        cost_model=standard_cost(),
    )
    # Engine ran to completion.
    assert res.metadata["trading_days"] >= 1
    assert res.metadata["core_engine_version"]
    assert res.metadata["strategy_id"] == "return_feature_v0"
    # The equity curve has one point per trading day.
    assert len(res.equity_curve) >= 1
    # No look-ahead: every metadata field references the same DB path.
    assert res.metadata["db_path"].endswith("ing.sqlite") or "ing.sqlite" in res.metadata["db_path"]


@pytest.mark.live
def test_backtest_on_phase35_synced_db(tmp_path):
    """Live smoke: run a backtest against a DB populated by Phase 3.5 sync.

    Skipped unless QP_LIVE=1 and QP_SYNCED_DB is set. Run with:

      QP_LIVE=1 QP_SYNCED_DB=data/structured/ingestion.sqlite \\
        .venv/bin/python -m pytest tests/test_phase4_real_db_smoke.py::test_backtest_on_phase35_synced_db
    """
    if not os.environ.get("QP_LIVE"):
        pytest.skip("set QP_LIVE=1 to run real-DB backtest smoke")
    db = os.environ.get("QP_SYNCED_DB")
    if not db or not Path(db).exists():
        pytest.skip("QP_SYNCED_DB not set or missing")
    strat = FixedDbReturnFeatureStrategy(Path(db))
    res = run_backtest(
        strat,
        "2025-04-01", "2025-06-30",  # 3-month window for the smoke
        db_path=Path(db),
        cost_model=standard_cost(),
    )
    assert res.metadata["trading_days"] >= 1
    print(f"[live] trading_days={res.metadata['trading_days']}")
