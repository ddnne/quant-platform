"""Core runtime boundary: facts enter via ``pit`` and contexts expose no DB.

The centralized plane dependency test owns the import graph.  These tests
exercise the stronger runtime observations: a real backtest calls the PIT
getters and strategy contexts receive scoped data/capabilities, not storage
handles.
"""

from __future__ import annotations

import pytest

import pit
from core import run_backtest, standard_cost
from core.execution import close_as_of
from core.strategies.buy_hold import BuyHold
from core.universe import membership_at

from _coreseed import CODES, TRADING_DAYS, seed_db

def test_core_reads_facts_through_pit(tmp_path, monkeypatch):
    """A backtest exercises pit.get_market_calendar / get_equity_master / bars."""
    db = seed_db(tmp_path)
    calls: dict[str, int] = {
        "calendar": 0,
        "master": 0,
        "bars": 0,
    }

    real_calendar = pit.get_market_calendar
    real_master = pit.get_equity_master
    real_bars = pit.get_equity_bars_daily

    def spy_calendar(*a, **k):
        calls["calendar"] += 1
        return real_calendar(*a, **k)

    def spy_master(*a, **k):
        calls["master"] += 1
        return real_master(*a, **k)

    def spy_bars(*a, **k):
        calls["bars"] += 1
        return real_bars(*a, **k)

    # core.engine / core.universe look these up on the shared `pit` module at
    # call time, so patching the module attributes is enough.
    monkeypatch.setattr(pit, "get_market_calendar", spy_calendar)
    monkeypatch.setattr(pit, "get_equity_master", spy_master)
    monkeypatch.setattr(pit, "get_equity_bars_daily", spy_bars)

    res = run_backtest(
        BuyHold(),
        TRADING_DAYS[0],
        TRADING_DAYS[-1],
        db_path=db,
        universe=membership_at(close_as_of(TRADING_DAYS[0]), db_path=db, codes=CODES),
        cost_model=standard_cost(),
    )
    assert calls["calendar"] >= 1
    assert calls["master"] >= 1
    assert calls["bars"] >= 1
    # Engine read at least the universe codes' bars.
    assert res.metadata["execution_mode"] == "next_close"


def test_strategy_context_carries_no_db_handle(tmp_path):
    """BarContext exposes data, not a database/PIT handle the strategy could abuse."""
    db = seed_db(tmp_path)
    seen: dict = {}

    class Snoop:
        strategy_id = "snoop"
        params = {}

        def on_bar(self, ctx):
            seen["attrs"] = set(ctx.__dataclass_fields__.keys())
            return []

    run_backtest(
        Snoop(),
        TRADING_DAYS[0],
        TRADING_DAYS[-1],
        db_path=db,
        universe=membership_at(close_as_of(TRADING_DAYS[0]), db_path=db, codes=CODES),
    )
    # No field on the context is a pit/db/sqlite handle.
    assert seen["attrs"] == {
        "as_of", "date", "universe", "positions", "cash", "equity",
        "prices", "bars", "master",
    }
    assert "db_path" not in seen["attrs"]
    assert "conn" not in seen["attrs"]


def test_context_feature_accessor_injects_as_of_and_runtime_db(tmp_path):
    """Strategies name feature inputs, while core owns PIT scope parameters."""
    db = seed_db(tmp_path)
    seen: list[tuple[str, str]] = []

    class FeatureUser:
        strategy_id = "feature_user"
        params = {}

        def on_bar(self, ctx):
            output = ctx.feature("return_1d", code=CODES[0])
            seen.append((output.metadata["as_of"], output.metadata["db_path"]))
            with pytest.raises(TypeError, match="runtime-scoped"):
                ctx.feature("return_1d", code=CODES[0], db_path="other.sqlite")
            with pytest.raises(TypeError, match="runtime-scoped"):
                ctx.compute_feature("return_1d", code=CODES[0], as_of="future")
            return []

    run_backtest(
        FeatureUser(),
        TRADING_DAYS[0],
        TRADING_DAYS[-1],
        db_path=db,
        universe=membership_at(close_as_of(TRADING_DAYS[0]), db_path=db, codes=CODES),
    )

    assert len(seen) == len(TRADING_DAYS)
    assert [as_of for as_of, _ in seen] == [
        f"{day}T15:30:00+09:00" for day in TRADING_DAYS
    ]
    assert {path for _, path in seen} == {str(db.resolve())}
