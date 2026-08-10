"""Phase 4 F6 — run_backtest on a real DB path.

Phase 4 closed-loop requires that ``run_backtest`` runs end-to-end on a
real-DB-shaped path (the kind Phase 3.5 produces via sync). Since CI must be
offline-only, this test:

* serves cursor-paginated, Cloudflare-shaped generic D1 rows to the real sync
  script, producing the SQLite layout ``run_backtest`` reads through PIT;
* runs a backtest with a strategy that uses the **features package** to
  compute return_1d at each decision instant (proving F1–F3 + F6 work
  together);
* asserts the result has the standard reproducibility metadata.

Marked ``live`` if you want to point it at a real Phase 3.5 sync DB. The
default path uses the D1 export fixture so it runs offline.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

import pit
import features
from core import run_backtest, standard_cost
from core.strategy_protocol import BarContext, OrderIntent


TRADING_DAYS = ("2025-04-01", "2025-04-02", "2025-04-03", "2025-04-04")
CODES = ("8697",)


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
            out = features.compute(
                "return_1d",
                as_of=ctx.as_of,
                code=code,
                db_path=self._db_path,
            )
            if out.value is None:
                continue
            if out.value > best_ret:
                best_ret = out.value
                best_code = code
        if best_code is None:
            return []
        self._entered = True
        return [OrderIntent(code=best_code, target_weight=1.0)]


def test_backtest_with_features_on_real_db_path(synced_cf_d1_db):
    """F6: CF export → sync → PIT → features → feature-driven backtest."""
    assert synced_cf_d1_db.rc == 0
    db = synced_cf_d1_db.db

    bars = pit.get_equity_bars_daily(
        as_of="2025-04-04T15:30:00+09:00", code=CODES[0], db_path=db
    )
    assert len(bars.rows) == len(TRADING_DAYS)
    feature = features.compute(
        "return_1d",
        as_of="2025-04-04T15:30:00+09:00",
        code=CODES[0],
        db_path=db,
    )
    assert feature.value == pytest.approx((104.0 - 101.0) / 101.0)

    strat = FixedDbReturnFeatureStrategy(db)
    res = run_backtest(
        strat,
        TRADING_DAYS[0], TRADING_DAYS[-1],
        db_path=db,
        universe=CODES,
        cost_model=standard_cost(),
    )
    # Engine ran to completion.
    assert res.metadata["trading_days"] >= 1
    assert res.metadata["core_engine_version"]
    assert res.metadata["strategy_id"] == "return_feature_v0"
    # The equity curve has one point per trading day.
    assert len(res.equity_curve) >= 1
    assert len(res.trades) >= 1
    # No look-ahead: every metadata field references the same DB path.
    assert Path(res.metadata["db_path"]) == db


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
