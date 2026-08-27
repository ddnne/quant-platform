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

from types import SimpleNamespace

import pytest

import pit
from core import (
    NEXT_CLOSE,
    PIT_ADJUSTED,
    RAW,
    BacktestResult,
    UnsupportedPriceBasis,
    run_backtest,
    standard_cost,
    stress_cost,
)
from core.execution import close_as_of, open_as_of
from core.strategies.buy_hold import BuyHold
from core.strategy_protocol import BarContext, OrderIntent
from core.universe import (
    FIXED_UNIVERSE_ENV,
    RawFixedUniverseError,
    load_master,
    membership_at,
)
from storage.sqlite_store import SqliteStore

from _coreseed import CODES, TRADING_DAYS, close_iso, seed_db

START, END = TRADING_DAYS[0], TRADING_DAYS[-1]


def _uni(db, codes=None):
    """PIT-proven membership at the first session close (not a raw code list)."""
    return membership_at(close_as_of(START), db_path=db, codes=codes)


def _write_master_snapshot(db, *, snapshot_date, codes, available_at):
    with SqliteStore(db) as store:
        store.upsert(
            "jquants_listed_info",
            [
                {
                    "source": "jquants",
                    "code": code,
                    "snapshot_date": snapshot_date,
                    "event_time": f"{snapshot_date}T09:00:00+09:00",
                    "available_at": available_at,
                    "ingested_at": available_at,
                    "company_name": f"Co-{code}",
                    "sector_17_code": "1",
                    "market_code": "1",
                }
                for code in codes
            ],
        )


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
        BuyHold(), START, END, db_path=db, universe=_uni(db)
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
    assert md["universe_rule"] == (
        "fixed_allowlist_intersect_pit_equity_master_per_decision_day"
    )
    assert md["fixed_allowlist"] == sorted(CODES)
    assert md["price_basis"] == RAW
    assert md["signal_lookback_days"] == md["lookback_days"]
    assert md["valuation_mark_policy"] == "last_pit_safe_exact_session_bar"


def test_next_close_fills_strictly_next_session(tmp_path):
    """A signal on day D must fill on a strictly later session."""
    db = seed_db(tmp_path)
    res = run_backtest(
        BuyHold(), START, END, db_path=db, universe=_uni(db)
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
        universe=_uni(db), cost_model=standard_cost(),
    )
    stress = run_backtest(
        BuyHold(), START, END, db_path=db,
        universe=_uni(db), cost_model=stress_cost(multiple=5.0),
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
        universe=_uni(db), cost_model=standard_cost(bps=0.0),
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
    r1 = run_backtest(BuyHold(), START, END, db_path=db, universe=_uni(db))
    r2 = run_backtest(BuyHold(), START, END, db_path=db, universe=_uni(db))
    assert r1.metadata == r2.metadata
    assert r1.equity_curve == r2.equity_curve
    assert r1.trades == r2.trades
    assert r1.metrics == r2.metrics
    # Strategy params hash is stable.
    assert r1.metadata["strategy_params_hash"]


def test_metadata_reflects_different_inputs(tmp_path):
    db = seed_db(tmp_path)
    a = run_backtest(BuyHold(), START, END, db_path=db, universe=_uni(db))
    b = run_backtest(
        BuyHold(), START, END, db_path=db,
        universe=_uni(db), cost_model=stress_cost(),
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
    seen: list[tuple[str, str, str, tuple[str, ...]]] = []

    def wrapped(
        as_of=None, code=None, from_event=None, to_event=None, *, codes=None,
        db_path=None,
    ):
        seen.append((as_of, from_event, to_event, tuple(codes or ())))
        return real_bars(
            as_of=as_of, code=code, from_event=from_event,
            to_event=to_event, codes=codes, db_path=db_path,
        )

    monkeypatch.setattr(pit, "get_equity_bars_daily", wrapped)

    run_backtest(BuyHold(), START, END, db_path=db, universe=_uni(db))
    assert seen, "engine should read bars through pit"
    end_close = close_as_of(END)
    for as_of, _from, to_event, codes in seen:
        # as_of never beyond the period's last close ...
        assert as_of <= end_close, (as_of, end_close)
        # ... and for a bars read with to_event=D the as_of is D's close (<= D).
        if to_event is not None:
            assert as_of <= close_as_of(to_event), (as_of, to_event)
        # The engine pushes its requested universe into the PIT query instead
        # of scanning every market bar and filtering only in Python.
        assert set(codes) == set(CODES)


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
        rec, START, _DAYS[-2], db_path=db, universe=_uni(db, codes=("1332",)),
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
        BuyHold(), START, END, db_path=db, universe=_uni(db),
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


def test_same_day_close_debits_cash_and_marks_after_fill(tmp_path):
    """A same-day buy updates cash and that session's close equity point."""
    db = seed_db(tmp_path, codes=["1332"])
    res = run_backtest(
        BuyHold(), START, END, db_path=db, universe=_uni(db, codes=("1332",)),
        execution_mode="same_day_close",
    )
    assert len(res.trades) == 1
    trade = res.trades[0]
    fill_row = next(
        row for row in res.equity_curve if row["date"] == trade["fill_date"]
    )
    expected_cash = 1_000_000.0 - trade["notional"] - trade["cost"]
    assert fill_row["cash"] == pytest.approx(expected_cash)
    assert fill_row["cash"] < 1_000_000.0
    assert fill_row["positions_value"] == pytest.approx(
        trade["shares"] * trade["price"]
    )


def test_same_day_decision_equity_uses_prior_close(tmp_path):
    """A held position's current-day close cannot leak through ctx.equity."""
    prices = {
        "1332": {
            TRADING_DAYS[0]: 100.0,
            TRADING_DAYS[1]: 100.0,
            TRADING_DAYS[2]: 1_000.0,
            TRADING_DAYS[3]: 1_000.0,
        }
    }
    db = seed_db(tmp_path, codes=["1332"], prices=prices)

    class EnterThenRecord(Recorder):
        def on_bar(self, ctx: BarContext) -> list[OrderIntent]:
            self.ctxs.append(ctx)
            if ctx.date == TRADING_DAYS[1]:
                return [OrderIntent(code="1332", target_weight=0.5)]
            return []

    strategy = EnterThenRecord()
    res = run_backtest(
        strategy, START, END, db_path=db, universe=_uni(db, codes=("1332",)),
        execution_mode="same_day_close", cost_model=standard_cost(bps=0.0),
    )
    day3_ctx = next(ctx for ctx in strategy.ctxs if ctx.date == TRADING_DAYS[2])
    assert day3_ctx.prices["1332"] == 100.0
    assert day3_ctx.equity == pytest.approx(1_000_000.0)
    # Close-time reporting still includes day 3's price move.
    day3_curve = next(row for row in res.equity_curve if row["date"] == TRADING_DAYS[2])
    assert day3_curve["equity"] == pytest.approx(5_500_000.0)


def test_next_close_missing_fill_bar_carries_order(tmp_path):
    """A stale prior close must not be relabeled as a missing session's fill."""
    prices = {
        "1332": {
            TRADING_DAYS[0]: 100.0,
            # No bar on the first intended fill session.
            TRADING_DAYS[2]: 103.0,
            TRADING_DAYS[3]: 104.0,
        }
    }
    db = seed_db(tmp_path, codes=["1332"], prices=prices)
    res = run_backtest(
        BuyHold(), START, END, db_path=db, universe=_uni(db, codes=("1332",)),
        cost_model=standard_cost(bps=0.0),
    )
    assert len(res.trades) == 1
    assert res.trades[0]["decision_date"] == TRADING_DAYS[0]
    assert res.trades[0]["fill_date"] == TRADING_DAYS[2]
    assert res.trades[0]["price"] == 103.0


def test_stale_mark_survives_beyond_signal_lookback(tmp_path):
    """A suspension carries valuation without inventing a fill or a zero mark."""
    prices = {
        "1332": {
            TRADING_DAYS[0]: 100.0,
            TRADING_DAYS[1]: 100.0,
            # Position is held but no bars exist on day 2 or day 3.
        }
    }
    db = seed_db(tmp_path, codes=["1332"], prices=prices)
    res = run_backtest(
        BuyHold(), START, END, db_path=db, universe=_uni(db, codes=("1332",)),
        lookback_days=1, cost_model=standard_cost(bps=0.0),
    )
    assert len(res.trades) == 1
    assert [row["equity"] for row in res.equity_curve] == pytest.approx(
        [1_000_000.0] * len(TRADING_DAYS)
    )
    for row in res.equity_curve[2:]:
        assert row["mark_dates"] == {"1332": TRADING_DAYS[1]}
        assert row["stale_mark_codes"] == ["1332"]
        assert row["unpriced_codes"] == []


def test_raw_basis_ignores_unproven_vendor_adjusted_history(tmp_path):
    """Adjusted vendor columns are not silently treated as PIT-safe."""
    raw = {
        "1332": {
            TRADING_DAYS[0]: 100.0,
            TRADING_DAYS[1]: 100.0,
            TRADING_DAYS[2]: 50.0,
            TRADING_DAYS[3]: 50.0,
        }
    }
    adjusted = {"1332": {d: 50.0 for d in TRADING_DAYS}}
    db = seed_db(
        tmp_path, codes=["1332"], prices=raw, adjustment_prices=adjusted
    )
    res = run_backtest(
        BuyHold(), START, END, db_path=db, universe=_uni(db, codes=("1332",)),
        cost_model=standard_cost(bps=0.0),
    )
    assert res.metadata["price_basis"] == RAW
    assert res.trades[0]["price"] == 100.0
    assert [row["equity"] for row in res.equity_curve] == pytest.approx(
        [1_000_000.0, 1_000_000.0, 500_000.0, 500_000.0]
    )


def test_pit_adjusted_basis_fails_closed_without_evidence(tmp_path):
    db = seed_db(tmp_path, codes=["1332"])
    with pytest.raises(UnsupportedPriceBasis, match="not enabled"):
        run_backtest(
            BuyHold(), START, END, db_path=db, universe=_uni(db, codes=("1332",)),
            price_basis=PIT_ADJUSTED,
        )


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
    master = load_master(close_as_of(START), db_path=db)
    assert master.pit_as_of == close_as_of(START)
    assert master.membership_proof == f"pit_equity_master:{close_as_of(START)}"


def test_raw_code_list_without_as_of_is_rejected(tmp_path):
    db = seed_db(tmp_path)
    with pytest.raises(RawFixedUniverseError, match="pit_as_of"):
        run_backtest(BuyHold(), START, END, db_path=db, universe=tuple(CODES))
    with pytest.raises(RawFixedUniverseError, match=FIXED_UNIVERSE_ENV):
        run_backtest(BuyHold(), START, END, db_path=db, universe=list(CODES))


def test_raw_code_list_requires_research_env(tmp_path, monkeypatch):
    db = seed_db(tmp_path)
    monkeypatch.delenv(FIXED_UNIVERSE_ENV, raising=False)
    with pytest.raises(RawFixedUniverseError):
        run_backtest(BuyHold(), START, END, db_path=db, universe=tuple(CODES))
    monkeypatch.setenv(FIXED_UNIVERSE_ENV, "true")
    with pytest.raises(RawFixedUniverseError, match=FIXED_UNIVERSE_ENV):
        run_backtest(BuyHold(), START, END, db_path=db, universe=tuple(CODES))
    monkeypatch.setenv(FIXED_UNIVERSE_ENV, "1")
    res = run_backtest(BuyHold(), START, END, db_path=db, universe=tuple(CODES))
    assert res.metadata["universe_rule"] == (
        "fixed_allowlist_intersect_pit_equity_master_per_decision_day"
    )


def test_load_master_mapping_injects_fixed_universe(tmp_path):
    db = seed_db(tmp_path, codes=["1332", "8697", "7203"])
    rec = Recorder()
    master = load_master(close_as_of(START), db_path=db)
    run_backtest(rec, START, END, db_path=db, universe=master)
    assert rec.ctxs[0].universe == ("1332", "7203", "8697")
    subset = membership_at(close_as_of(START), db_path=db, codes=("1332",))
    rec2 = Recorder()
    run_backtest(rec2, START, END, db_path=db, universe=subset)
    assert rec2.ctxs[0].universe == ("1332",)
    with pytest.raises(ValueError, match="not in PIT equity master"):
        membership_at(close_as_of(START), db_path=db, codes=("9999",))
    rec3 = Recorder()
    run_backtest(
        rec3,
        START,
        END,
        db_path=db,
        universe={"codes": ("1332",), "pit_as_of": close_as_of(START)},
    )
    assert rec3.ctxs[0].universe == ("1332",)


def test_universe_uses_latest_complete_master_snapshot(tmp_path):
    """A code omitted from the latest visible snapshot leaves the universe."""
    db = seed_db(tmp_path, codes=["1332", "8697"])
    with SqliteStore(db) as store:
        store.upsert(
            "jquants_listed_info",
            [
                {
                    "source": "jquants",
                    "code": "1332",
                    "snapshot_date": "2025-04-02",
                    "event_time": "2025-04-02T09:00:00+09:00",
                    "available_at": "2025-04-02T09:00:00+09:00",
                    "ingested_at": "2025-04-02T09:00:00+09:00",
                    "company_name": "Co-1332",
                }
            ],
        )
    rec = Recorder()
    run_backtest(rec, START, END, db_path=db)
    assert rec.ctxs[0].universe == ("1332", "8697")
    assert rec.ctxs[1].universe == ("1332",)


def test_fixed_allowlist_is_intersected_with_daily_pit_membership(
    tmp_path, monkeypatch
):
    """A candidate allowlist follows listing and delisting snapshots daily."""
    db = seed_db(tmp_path, codes=["1332", "7203"])
    _write_master_snapshot(
        db,
        snapshot_date="2025-04-01",
        codes=["1332"],
        available_at="2025-04-01T08:00:00+09:00",
    )
    _write_master_snapshot(
        db,
        snapshot_date="2025-04-02",
        codes=["1332", "7203"],
        available_at="2025-04-02T08:00:00+09:00",
    )
    _write_master_snapshot(
        db,
        snapshot_date="2025-04-03",
        codes=["7203"],
        available_at="2025-04-03T08:00:00+09:00",
    )
    monkeypatch.setenv(FIXED_UNIVERSE_ENV, "1")
    rec = Recorder()
    result = run_backtest(
        rec,
        START,
        END,
        db_path=db,
        universe=("1332", "7203", "9999"),
    )
    assert [ctx.universe for ctx in rec.ctxs] == [
        ("1332",),
        ("1332", "7203"),
        ("7203",),
        ("7203",),
    ]
    assert all(set(ctx.master) == set(ctx.universe) for ctx in rec.ctxs)
    assert result.metadata["fixed_allowlist"] == ["1332", "7203", "9999"]


def test_resolved_daily_universe_recomputes_membership_digest(tmp_path):
    from research.universe_contract import ResolvedUniverseMembership

    db = seed_db(tmp_path, codes=["1332", "7203"])
    resolved = ResolvedUniverseMembership(
        period_start=START,
        period_end=END,
        decision_memberships=tuple(
            (decision_date, ("1332",)) for decision_date in TRADING_DAYS
        ),
    )
    recorder = Recorder()
    result = run_backtest(
        recorder,
        START,
        END,
        db_path=db,
        universe=resolved,
    )
    assert [context.universe for context in recorder.ctxs] == [
        ("1332",),
    ] * len(TRADING_DAYS)
    assert (
        result.metadata["resolved_universe_digest"]
        == resolved.resolved_membership_digest
    )


def test_resolved_daily_universe_rejects_self_reported_digest(tmp_path):
    from research.universe_contract import ResolvedUniverseMembership

    db = seed_db(tmp_path, codes=["1332", "7203"])
    resolved = ResolvedUniverseMembership(
        period_start=START,
        period_end=END,
        decision_memberships=tuple(
            (decision_date, ("1332",)) for decision_date in TRADING_DAYS
        ),
    )
    substituted_membership = dict(resolved.membership_by_date)
    substituted_membership[TRADING_DAYS[-1]] = ("7203",)
    forged = SimpleNamespace(
        membership_by_date=substituted_membership,
        resolved_membership_digest=resolved.resolved_membership_digest,
        membership_proof=resolved.membership_proof,
        rule_id=resolved.rule_id,
        rule_version=resolved.rule_version,
        rule_digest=resolved.rule_digest,
        period_start=resolved.period_start,
        period_end=resolved.period_end,
    )
    with pytest.raises(
        RawFixedUniverseError,
        match="membership digest does not match its map",
    ):
        run_backtest(
            Recorder(),
            START,
            END,
            db_path=db,
            universe=forged,
        )


def test_next_close_pending_order_is_cancelled_after_membership_exit(
    tmp_path, monkeypatch
):
    db = seed_db(tmp_path, codes=["1332", "7203"])
    _write_master_snapshot(
        db,
        snapshot_date="2025-04-01",
        codes=["1332"],
        available_at="2025-04-01T08:00:00+09:00",
    )
    _write_master_snapshot(
        db,
        snapshot_date="2025-04-02",
        codes=["7203"],
        available_at="2025-04-02T08:00:00+09:00",
    )

    class BuyFirstVisible:
        strategy_id = "buy_first_visible"
        params = {}

        def __init__(self):
            self.sent = False

        def on_bar(self, ctx):
            if self.sent:
                return []
            self.sent = True
            return [OrderIntent(code=ctx.universe[0], target_weight=1.0)]

    monkeypatch.setenv(FIXED_UNIVERSE_ENV, "1")
    result = run_backtest(
        BuyFirstVisible(),
        START,
        END,
        db_path=db,
        universe=("1332", "7203"),
    )
    assert result.trades == []


def test_same_day_membership_uses_open_decision_instant(tmp_path, monkeypatch):
    db = seed_db(tmp_path, codes=["1332", "7203"])
    _write_master_snapshot(
        db,
        snapshot_date="2025-04-01",
        codes=["1332"],
        available_at="2025-04-01T08:00:00+09:00",
    )
    _write_master_snapshot(
        db,
        snapshot_date="2025-04-02",
        codes=["1332", "7203"],
        available_at="2025-04-02T09:30:00+09:00",
    )
    monkeypatch.setenv(FIXED_UNIVERSE_ENV, "1")
    rec = Recorder()
    run_backtest(
        rec,
        START,
        END,
        db_path=db,
        execution_mode="same_day_close",
        universe=("1332", "7203"),
    )
    assert rec.ctxs[0].universe == ("1332",)
    assert rec.ctxs[1].universe == ("1332",)
    assert rec.ctxs[2].universe == ("1332", "7203")


def test_open_and_close_as_of_helpers():
    assert close_as_of("2025-04-01") == "2025-04-01T15:30:00+09:00"
    assert close_as_of("2024-10-31") == "2024-10-31T15:00:00+09:00"
    assert open_as_of("2025-04-01") == "2025-04-01T09:00:00+09:00"


if __name__ == "__main__":
    pytest.main([__file__, "-q"])
