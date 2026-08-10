"""Core engine behavior: backtest completion, costs, reproducibility, lookahead.

All tests run offline against a tiny PIT DB seeded by :mod:`_coreseed`. They
verify the Phase 3 handoff's engine-level guarantees:

* a dummy strategy completes a backtest with sensible shape,
* ``next_close`` fills strictly on the next session (no same-bar fill),
* costs move post-cost return but not pre-cost return,
* identical configs reproduce identical results + metadata,
* no future bar is visible at a decision instant (PIT + execution).
"""

from __future__ import annotations

import pytest

import pit
from core import (
    NEXT_CLOSE,
    BacktestResult,
    run_backtest,
    standard_cost,
    stress_cost,
)
from core.execution import close_as_of, open_as_of
from core.strategies.buy_hold import BuyHold
from core.strategy_protocol import BarContext, OrderIntent

from _coreseed import CODES, TRADING_DAYS, close_iso, seed_db

START, END = TRADING_DAYS[0], TRADING_DAYS[-1]


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


class Recorder:
    """Strategy that records each BarContext and optionally echoes intents."""

    strategy_id = "recorder"
    params: dict = {}

    def __init__(self) -> None:
        self.ctxs: list[BarContext] = []

    def on_bar(self, ctx: BarContext) -> list[OrderIntent]:
        self.ctxs.append(ctx)
        return []


# ---------------------------------------------------------------------------
# completion + shape
# ---------------------------------------------------------------------------


def test_buy_hold_completes_backtest_next_close(tmp_path):
    db = seed_db(tmp_path)
    res = run_backtest(
        BuyHold(), START, END, db_path=db, universe=tuple(CODES)
    )
    assert isinstance(res, BacktestResult)
    # One equity-curve point per trading day.
    assert len(res.equity_curve) == len(TRADING_DAYS)
    assert [row["date"] for row in res.equity_curve] == TRADING_DAYS
    # Starts flat at the starting capital.
    assert res.equity_curve[0]["equity"] == pytest.approx(1_000_000.0)
    assert res.equity_curve[0]["positions_value"] == 0.0
    # BuyHold entered once: exactly one fill per code, all from one decision.
    assert len(res.trades) == len(CODES)
    sides = {t["side"] for t in res.trades}
    assert sides == {"buy"}
    # Metrics + metadata present.
    assert "total_return_post_cost" in res.metrics
    assert "max_drawdown" in res.metrics
    md = res.metadata
    assert md["core_engine_version"]
    assert md["pit_api_version"] == pit.PIT_API_VERSION
    assert md["execution_mode"] == "next_close"
    assert md["strategy_id"] == "buy_hold"
    assert md["universe_rule"].startswith("fixed:")


def test_next_close_fills_strictly_next_session(tmp_path):
    """A signal on day D must fill on a strictly later session."""
    db = seed_db(tmp_path)
    res = run_backtest(
        BuyHold(), START, END, db_path=db, universe=tuple(CODES)
    )
    assert res.trades, "expected at least one fill"
    for t in res.trades:
        assert t["fill_date"] > t["decision_date"], t
    # Under next_close the single entry decides on the first day.
    assert {t["decision_date"] for t in res.trades} == {TRADING_DAYS[0]}
    assert {t["fill_date"] for t in res.trades} == {TRADING_DAYS[1]}


# ---------------------------------------------------------------------------
# costs
# ---------------------------------------------------------------------------


def test_costs_change_post_cost_not_pre_cost(tmp_path):
    db = seed_db(tmp_path)
    std = run_backtest(
        BuyHold(), START, END, db_path=db,
        universe=tuple(CODES), cost_model=standard_cost(),
    )
    stress = run_backtest(
        BuyHold(), START, END, db_path=db,
        universe=tuple(CODES), cost_model=stress_cost(multiple=5.0),
    )
    # Stress pays more cost and earns less post-cost return.
    assert stress.metrics["cost_drag"] > std.metrics["cost_drag"]
    assert stress.metrics["total_return_post_cost"] < std.metrics["total_return_post_cost"]
    # Pre-cost is invariant: identical positions, costs only moved cash.
    assert stress.metrics["total_return_pre_cost"] == pytest.approx(
        std.metrics["total_return_pre_cost"]
    )


def test_zero_cost_equals_pre_cost(tmp_path):
    db = seed_db(tmp_path)
    zero = run_backtest(
        BuyHold(), START, END, db_path=db,
        universe=tuple(CODES), cost_model=standard_cost(bps=0.0),
    )
    assert zero.metrics["total_return_pre_cost"] == pytest.approx(
        zero.metrics["total_return_post_cost"]
    )
    assert zero.metrics["cost_drag"] == 0.0


# ---------------------------------------------------------------------------
# reproducibility
# ---------------------------------------------------------------------------


def test_reproducibility_same_config_same_result(tmp_path):
    db = seed_db(tmp_path)
    r1 = run_backtest(BuyHold(), START, END, db_path=db, universe=tuple(CODES))
    r2 = run_backtest(BuyHold(), START, END, db_path=db, universe=tuple(CODES))
    assert r1.metadata == r2.metadata
    assert r1.equity_curve == r2.equity_curve
    assert r1.trades == r2.trades
    assert r1.metrics == r2.metrics
    # Strategy params hash is stable.
    assert r1.metadata["strategy_params_hash"]


def test_metadata_reflects_different_inputs(tmp_path):
    db = seed_db(tmp_path)
    a = run_backtest(BuyHold(), START, END, db_path=db, universe=tuple(CODES))
    b = run_backtest(
        BuyHold(), START, END, db_path=db,
        universe=tuple(CODES), cost_model=stress_cost(),
    )
    assert a.metadata["execution_mode"] == b.metadata["execution_mode"]
    assert a.metadata["cost_model"] != b.metadata["cost_model"]


# ---------------------------------------------------------------------------
# lookahead: PIT as_of + execution definition
# ---------------------------------------------------------------------------


def test_engine_never_uses_future_as_of_for_bars(tmp_path, monkeypatch):
    """Every bars read uses an as_of <= the day being decided (no future)."""
    db = seed_db(tmp_path)
    real_bars = pit.get_equity_bars_daily
    seen: list[tuple[str, str, str]] = []  # (as_of, from_event, to_event)

    def wrapped(as_of=None, code=None, from_event=None, to_event=None, *, db_path=None):
        seen.append((as_of, from_event, to_event))
        return real_bars(
            as_of=as_of, code=code, from_event=from_event,
            to_event=to_event, db_path=db_path,
        )

    monkeypatch.setattr(pit, "get_equity_bars_daily", wrapped)

    run_backtest(BuyHold(), START, END, db_path=db, universe=tuple(CODES))
    assert seen, "engine should read bars through pit"
    end_close = close_as_of(END)
    for as_of, _from, to_event in seen:
        # as_of never beyond the period's last close ...
        assert as_of <= end_close, (as_of, end_close)
        # ... and for a bars read with to_event=D the as_of is D's close (<= D).
        if to_event is not None:
            assert as_of <= close_as_of(to_event), (as_of, to_event)


def test_no_future_bar_visible_at_decision(tmp_path):
    """A bar published far in the future is invisible at an earlier decision."""
    # Seed bars where 1332's 04-04 close is only "published" 2025-12-31.
    from _coreseed import CODES as _CODES, TRADING_DAYS as _DAYS, rising_prices

    prices = rising_prices(_CODES, _DAYS)
    db = seed_db(
        tmp_path,
        bar_available_at_for={_DAYS[-1]: "2025-12-31T00:00:00+09:00"},
        prices=prices,
    )

    rec = Recorder()
    # Only look at code 1332 on the second-to-last day's decision.
    run_backtest(
        rec, START, _DAYS[-2], db_path=db, universe=("1332",),
        calendar_as_of=close_iso(END),
    )
    # On 04-03's decision (as_of 04-03 15:30), the 04-04 bar (avail 12-31) is
    # look-ahead and must be hidden: the latest visible bar is 04-03.
    last_ctx = rec.ctxs[-1]
    bars_1332 = last_ctx.bars["1332"]
    assert bars_1332, "should have at least one visible bar"
    assert max(b.date for b in bars_1332) == _DAYS[-2]


# ---------------------------------------------------------------------------
# same_day_close mode
# ---------------------------------------------------------------------------


def test_same_day_close_fills_same_session_and_excludes_same_day_close(tmp_path):
    """same_day_close decides at the open and fills at that session's close."""
    db = seed_db(tmp_path)
    res = run_backtest(
        BuyHold(), START, END, db_path=db, universe=tuple(CODES),
        execution_mode="same_day_close",
    )
    assert res.metadata["execution_mode"] == "same_day_close"
    assert res.trades, "expected entry fills"
    for t in res.trades:
        # Same-session fill by definition.
        assert t["fill_date"] == t["decision_date"], t
    # Entry could NOT happen on day 0: at 04-01 09:00 no bar is visible yet
    # (bars publish at the 15:30 close), so the strategy waited until 04-02.
    assert {t["decision_date"] for t in res.trades} == {TRADING_DAYS[1]}


# ---------------------------------------------------------------------------
# universe from PIT master (anti-survivorship first step)
# ---------------------------------------------------------------------------


def test_universe_built_from_pit_master_when_not_fixed(tmp_path):
    db = seed_db(tmp_path, codes=["1332", "8697", "7203"])
    rec = Recorder()
    run_backtest(rec, START, END, db_path=db)  # no universe= -> from PIT master
    first = rec.ctxs[0]
    assert first.universe == ("1332", "7203", "8697")
    assert set(first.master.keys()) == {"1332", "7203", "8697"}
    assert first.master["7203"].company_name == "Co-7203"


def test_open_and_close_as_of_helpers():
    assert close_as_of("2025-04-01") == "2025-04-01T15:30:00+09:00"
    assert close_as_of("2024-10-31") == "2024-10-31T15:00:00+09:00"
    assert open_as_of("2025-04-01") == "2025-04-01T09:00:00+09:00"


if __name__ == "__main__":
    pytest.main([__file__, "-q"])
