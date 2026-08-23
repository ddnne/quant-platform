"""Phase 4 B2 — run_backtest smoke (offline fixtures; live via QP_LIVE=1)."""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from core import close_as_of, run_backtest
from core.costs import standard_cost
from core.strategies.buy_hold import BuyHold
from core.universe import membership_at


def _days(n: int = 40) -> list[str]:
    days: list[str] = []
    for d in range(3, 31):
        if d % 7 in (1, 2):
            continue
        days.append(f"2025-03-{d:02d}")
        if len(days) >= n:
            break
    # add April if needed
    for d in range(1, 30):
        if len(days) >= n:
            break
        if d % 7 in (5, 6):
            continue
        days.append(f"2025-04-{d:02d}")
    return days[:n]


def test_backtest_short_window_offline(tmp_path):
    from tests._coreseed import seed_db

    days = _days(40)
    codes = ["1332", "8697", "7203", "6758", "9984"]
    prices = {c: {d: 100.0 + i + j for j, d in enumerate(days)} for i, c in enumerate(codes)}
    db = seed_db(tmp_path, codes=codes, days=days, prices=prices)
    res = run_backtest(
        BuyHold(),
        days[0],
        days[-1],
        db_path=db,
        universe=membership_at(close_as_of(days[0]), db_path=db, codes=codes),
        cost_model=standard_cost(),
    )
    assert res.metrics is not None
    assert res.metadata.get("strategy_id")
    assert len(res.equity_curve) >= 1
    assert res.metrics.get("num_trading_days", 0) >= 1


@pytest.mark.live
def test_live_backtest_3m():
    if os.environ.get("QP_LIVE") != "1":
        pytest.skip("QP_LIVE!=1")
    db = Path(os.environ.get("QP_DB", "data/structured/ingestion.sqlite"))
    if not db.exists():
        pytest.skip(f"no DB at {db}")
    uni = tuple(
        c.strip()
        for c in os.environ.get("QP_UNIVERSE", "7203,6758,9984").split(",")
        if c.strip()
    )
    start = os.environ.get("QP_BT_START", "2024-01-04")
    end = os.environ.get("QP_BT_END", "2024-03-29")
    res = run_backtest(
        BuyHold(),
        start,
        end,
        db_path=db,
        universe=membership_at(close_as_of(start), db_path=db, codes=uni),
        cost_model=standard_cost(),
    )
    # ~3m calendar window should contain at least 50 trading days for live
    # (configurable for unusual windows). Soft offline fixtures use a much
    # smaller floor — see test_backtest_short_window_offline.
    floor = int(os.environ.get("QP_BT_MIN_DAYS", "50"))
    assert res.metrics["num_trading_days"] >= floor, (
        f"num_trading_days={res.metrics['num_trading_days']} < floor={floor}"
    )
