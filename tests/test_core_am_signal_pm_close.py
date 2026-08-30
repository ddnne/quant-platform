"""AM-signal / PM-close engine semantics for personal retrospective DRAFT."""

from __future__ import annotations

import pytest

from core import (
    PERSONAL_RETROSPECTIVE_ADJUSTED,
    PIT_ADJUSTED,
    RAW,
    UnsupportedPriceBasis,
    run_backtest,
    standard_cost,
)
from core.execution import morning_close_as_of
from core.strategy_protocol import BarContext, OrderIntent
from core.universe import membership_at

from _coreseed import TRADING_DAYS, seed_db

D0, D1, D2, D3 = TRADING_DAYS
CODE = "1332"


def _level(value: float, days=TRADING_DAYS) -> dict[str, dict[str, float]]:
    return {CODE: {day: value for day in days}}


def _seed(
    tmp_path,
    *,
    close=10.0,
    adjc=999.0,
    madjc=100.0,
    aadjc=100.0,
    madjc_by_day=None,
    aadjc_by_day=None,
    adjc_by_day=None,
    close_by_day=None,
):
    days = TRADING_DAYS
    db = seed_db(
        tmp_path,
        codes=[CODE],
        prices={CODE: close_by_day or {day: close for day in days}},
        adjustment_prices={CODE: adjc_by_day or {day: adjc for day in days}},
        morning_adjustment_prices={
            CODE: madjc_by_day or {day: madjc for day in days}
        },
        afternoon_adjustment_prices={
            CODE: aadjc_by_day or {day: aadjc for day in days}
        },
    )
    return db


def _uni(db):
    return membership_at(morning_close_as_of(D0), db_path=db, codes=(CODE,))


def _run(db, strategy, **kwargs):
    return run_backtest(
        strategy,
        D0,
        D3,
        db_path=db,
        universe=_uni(db),
        execution_mode="am_signal_pm_close",
        price_basis=PERSONAL_RETROSPECTIVE_ADJUSTED,
        cost_model=standard_cost(bps=0.0),
        **kwargs,
    )


class Recorder:
    strategy_id = "am_recorder"
    params: dict = {}

    def __init__(self) -> None:
        self.ctxs: list[BarContext] = []

    def on_bar(self, ctx: BarContext) -> list[OrderIntent]:
        self.ctxs.append(ctx)
        return []


class BuyOnce:
    strategy_id = "buy_once"
    params: dict = {}

    def __init__(self, *, day: str = D0, weight: float = 1.0) -> None:
        self.day = day
        self.weight = weight
        self.ctxs: list[BarContext] = []
        self._done = False

    def on_bar(self, ctx: BarContext) -> list[OrderIntent]:
        self.ctxs.append(ctx)
        if self._done or ctx.date != self.day:
            return []
        self._done = True
        return [OrderIntent(code=CODE, target_weight=self.weight)]


def test_am_mode_decision_time_is_1130_and_fill_is_same_date(tmp_path):
    db = _seed(tmp_path)
    rec = Recorder()
    res = _run(db, rec)
    assert rec.ctxs
    for ctx in rec.ctxs:
        assert ctx.as_of == morning_close_as_of(ctx.date)
        assert ctx.as_of.endswith("T11:30:00+09:00")
    res = _run(db, BuyOnce())
    assert res.trades
    for trade in res.trades:
        assert trade["fill_date"] == trade["decision_date"]
        assert trade["decision_date"] == D0
    assert res.metadata["execution_mode"] == "am_signal_pm_close"
    assert "draft_reconstruction_not_11:30_publication" in (
        res.metadata["price_basis_provenance"]["field_time_semantics"]
    )
    assert "may_drift_by_pm_close" in res.metadata["weight_sizing_rule"]


def test_d_madjc_changes_signal_and_full_close_fields_do_not(tmp_path):
    db_m100 = _seed(tmp_path / "m100", madjc=100.0, aadjc=100.0, adjc=999.0, close=8.0)
    db_m200 = _seed(tmp_path / "m200", madjc=200.0, aadjc=100.0, adjc=999.0, close=8.0)
    db_tempt = _seed(tmp_path / "tempt", madjc=100.0, aadjc=400.0, adjc=50.0, close=1.0)

    a = BuyOnce()
    b = BuyOnce()
    c = BuyOnce()
    res_a = _run(db_m100, a)
    res_b = _run(db_m200, b)
    res_c = _run(db_tempt, c)

    assert a.ctxs[0].prices[CODE] == 100.0
    assert b.ctxs[0].prices[CODE] == 200.0
    assert c.ctxs[0].prices[CODE] == 100.0
    assert res_a.trades[0]["shares"] == pytest.approx(10_000.0)
    assert res_b.trades[0]["shares"] == pytest.approx(5_000.0)
    assert res_c.trades[0]["shares"] == pytest.approx(res_a.trades[0]["shares"])
    d_bar = a.ctxs[0].bars[CODE][-1]
    assert d_bar.date == D0
    assert d_bar.close == 100.0
    assert d_bar.adjustment_close == 100.0


def test_aadjc_mutation_changes_fill_and_pnl_only(tmp_path):
    db_flat = _seed(tmp_path / "flat", madjc=100.0, aadjc=100.0)
    db_up = _seed(tmp_path / "up", madjc=100.0, aadjc=150.0)
    rec_flat = BuyOnce()
    rec_up = BuyOnce()
    flat = _run(db_flat, rec_flat)
    up = _run(db_up, rec_up)

    assert rec_flat.ctxs[0].prices[CODE] == rec_up.ctxs[0].prices[CODE]
    assert flat.trades[0]["shares"] == pytest.approx(up.trades[0]["shares"])
    assert flat.trades[0]["price"] == 100.0
    assert up.trades[0]["price"] == 150.0
    # New position: fill cost is in the D equity point, but no AM-to-PM gain.
    assert up.equity_curve[0]["equity"] == pytest.approx(1_000_000.0)
    assert up.equity_curve[0]["positions_value"] == pytest.approx(1_500_000.0)
    assert up.equity_curve[0]["cash"] == pytest.approx(-500_000.0)


def test_missing_madjc_blocks_that_code_without_adjc_or_prior_fallback(tmp_path):
    other = "8697"
    db = seed_db(
        tmp_path,
        codes=[CODE, other],
        prices={
            CODE: {day: 10.0 for day in TRADING_DAYS},
            other: {day: 10.0 for day in TRADING_DAYS},
        },
        adjustment_prices={
            CODE: {day: 999.0 for day in TRADING_DAYS},
            other: {day: 50.0 for day in TRADING_DAYS},
        },
        morning_adjustment_prices={
            CODE: {D1: 100.0, D2: 100.0, D3: 100.0},
            other: {day: 50.0 for day in TRADING_DAYS},
        },
        afternoon_adjustment_prices={
            CODE: {day: 100.0 for day in TRADING_DAYS},
            other: {day: 50.0 for day in TRADING_DAYS},
        },
    )

    class RecordAndBuy:
        strategy_id = "record_and_buy"
        params: dict = {}

        def __init__(self) -> None:
            self.ctxs: list[BarContext] = []

        def on_bar(self, ctx: BarContext) -> list[OrderIntent]:
            self.ctxs.append(ctx)
            return [
                OrderIntent(code=code, target_weight=0.5)
                for code in ctx.universe
            ]

    rec = RecordAndBuy()
    res = run_backtest(
        rec,
        D0,
        D3,
        db_path=db,
        universe=membership_at(
            morning_close_as_of(D0), db_path=db, codes=(CODE, other)
        ),
        execution_mode="am_signal_pm_close",
        price_basis=PERSONAL_RETROSPECTIVE_ADJUSTED,
        cost_model=standard_cost(bps=0.0),
    )
    day0 = rec.ctxs[0]
    assert day0.prices[CODE] is None
    assert day0.prices[other] == 50.0
    d_bar = day0.bars[CODE][-1]
    assert d_bar.date == D0
    assert d_bar.close is None
    assert d_bar.adjustment_close is None
    day0_trades = [trade for trade in res.trades if trade["fill_date"] == D0]
    assert {trade["code"] for trade in day0_trades} == {other}
    assert all(trade["price"] != 999.0 for trade in res.trades)


def test_missing_aadjc_blocks_fill_without_adjc_fallback(tmp_path):
    aadjc = {D1: 110.0, D2: 110.0, D3: 110.0}
    db = _seed(tmp_path, madjc=100.0, aadjc_by_day=aadjc, adjc=999.0)

    class AlwaysLong:
        strategy_id = "always_long"
        params: dict = {}

        def on_bar(self, ctx: BarContext) -> list[OrderIntent]:
            return [OrderIntent(code=CODE, target_weight=1.0)]

    res = _run(db, AlwaysLong())
    assert res.trades
    assert all(trade["price"] != 999.0 for trade in res.trades)
    assert all(trade["fill_date"] != D0 for trade in res.trades)
    assert res.trades[0]["fill_date"] == D1
    assert res.trades[0]["price"] == 110.0
    assert res.metrics["comparable"] is False
    assert res.metrics["selection_eligible"] is False
    assert D0 in res.metrics["missing_fill_dates"]
    assert D0 in res.metrics["non_comparable_session_dates"]


def test_held_book_decision_equity_uses_d_morning_price(tmp_path):
    db = _seed(
        tmp_path,
        madjc_by_day={D0: 100.0, D1: 120.0, D2: 120.0, D3: 120.0},
        aadjc_by_day={D0: 100.0, D1: 180.0, D2: 180.0, D3: 180.0},
        adjc=999.0,
    )
    rec = BuyOnce(day=D0, weight=1.0)
    res = _run(db, rec)
    day1 = next(ctx for ctx in rec.ctxs if ctx.date == D1)
    # Held overnight: mark at D MAdjC for the decision, not D AAdjC / AdjC.
    assert day1.prices[CODE] == 120.0
    assert day1.equity == pytest.approx(1_200_000.0)
    day1_curve = next(row for row in res.equity_curve if row["date"] == D1)
    assert day1_curve["signal_equity"] == pytest.approx(1_200_000.0)
    assert day1_curve["equity"] == pytest.approx(1_800_000.0)
    d0_curve = next(row for row in res.equity_curve if row["date"] == D0)
    assert d0_curve["signal_equity"] == pytest.approx(1_000_000.0)


def test_new_position_has_no_pre_fill_am_to_pm_return(tmp_path):
    db = _seed(tmp_path, madjc=100.0, aadjc=200.0, adjc=999.0)
    res = _run(db, BuyOnce())
    first = res.equity_curve[0]
    assert first["equity"] == pytest.approx(1_000_000.0)
    assert first["positions_value"] == pytest.approx(2_000_000.0)
    assert first["cash"] == pytest.approx(-1_000_000.0)


def test_am_mode_rejects_non_personal_price_basis(tmp_path):
    db = _seed(tmp_path)
    with pytest.raises(ValueError, match="PERSONAL_RETROSPECTIVE_ADJUSTED"):
        run_backtest(
            BuyOnce(),
            D0,
            D3,
            db_path=db,
            universe=_uni(db),
            execution_mode="am_signal_pm_close",
            price_basis=RAW,
        )
    with pytest.raises(UnsupportedPriceBasis):
        run_backtest(
            BuyOnce(),
            D0,
            D3,
            db_path=db,
            universe=_uni(db),
            execution_mode="am_signal_pm_close",
            price_basis=PIT_ADJUSTED,
        )


class AlwaysLong:
    strategy_id = "always_long"
    params: dict = {}

    def __init__(self) -> None:
        self.ctxs: list[BarContext] = []

    def on_bar(self, ctx: BarContext) -> list[OrderIntent]:
        self.ctxs.append(ctx)
        return [OrderIntent(code=CODE, target_weight=1.0)]


def test_held_missing_madjc_skips_on_bar_and_rebalance(tmp_path):
    db = _seed(
        tmp_path,
        madjc_by_day={D0: 100.0, D2: 120.0, D3: 120.0},
        aadjc_by_day={D0: 100.0, D1: 110.0, D2: 120.0, D3: 120.0},
        adjc=999.0,
    )
    rec = AlwaysLong()
    res = _run(db, rec)
    assert [ctx.date for ctx in rec.ctxs] == [D0, D2, D3]
    assert all(trade["decision_date"] != D1 for trade in res.trades)
    quality = res.metadata["data_quality"]
    assert quality["comparable"] is False
    assert quality["selection_eligible"] is False
    skipped = quality["held_missing_morning_adjustment_close"]
    assert skipped[0]["date"] == D1
    assert skipped[0]["codes"] == [CODE]
    assert skipped[0]["reason"] == "held_missing_morning_adjustment_close"
    assert D1 in res.metrics["skipped_decision_dates"]
    assert res.metrics["comparable"] is False
    assert any(row["date"] == D1 for row in res.equity_curve)
    day1 = next(row for row in res.equity_curve if row["date"] == D1)
    assert day1["signal_equity"] is None
    assert all(row["equity"] != 999.0 * 10_000 for row in res.equity_curve)


def test_held_missing_aadjc_is_incomplete_non_comparable_valuation(tmp_path):
    db = _seed(
        tmp_path,
        madjc=100.0,
        aadjc_by_day={D0: 100.0, D2: 110.0, D3: 110.0},
        adjc=999.0,
    )
    rec = BuyOnce(day=D0, weight=1.0)
    res = _run(db, rec)
    assert rec.ctxs
    assert D1 in {ctx.date for ctx in rec.ctxs}
    assert any(row["date"] == D1 for row in res.equity_curve)
    day1 = next(row for row in res.equity_curve if row["date"] == D1)
    assert CODE in day1["stale_mark_codes"]
    assert day1["signal_equity"] == pytest.approx(1_000_000.0)
    assert res.metrics["comparable"] is False
    assert res.metrics["selection_eligible"] is False
    assert res.metrics["comparison_eligible"] is False
    assert res.metrics["incomplete_valuation"] is True
    assert D1 in res.metrics["incomplete_valuation_dates"]
    assert CODE in res.metrics["incomplete_valuation_codes"]
    assert res.metadata["data_quality"]["comparable"] is False
    assert all(trade["price"] != 999.0 for trade in res.trades)


def test_complete_am_run_is_comparable(tmp_path):
    db = _seed(tmp_path, madjc=100.0, aadjc=100.0)
    res = _run(db, BuyOnce())
    assert res.metrics["comparable"] is True
    assert res.metrics["selection_eligible"] is True
    assert res.metrics["comparison_eligible"] is True
    assert res.metrics["incomplete_valuation"] is False
    assert res.metadata["information_cutoff"] == "11:30:00+09:00"
    assert res.metadata["operational_usable_by"] == "12:30:00+09:00"
    assert res.metadata["session_view_digest"].startswith("sha256:")


def test_new_target_missing_aadjc_is_explicit_non_comparable_unfilled_order(tmp_path):
    db = _seed(
        tmp_path,
        madjc=100.0,
        aadjc_by_day={D1: 110.0, D2: 110.0, D3: 110.0},
        adjc=999.0,
    )
    rec = AlwaysLong()
    res = _run(db, rec)
    assert rec.ctxs[0].date == D0
    assert rec.ctxs[0].prices[CODE] == 100.0
    assert all(trade["fill_date"] != D0 for trade in res.trades)
    assert all(trade["price"] != 999.0 for trade in res.trades)
    d0_curve = next(row for row in res.equity_curve if row["date"] == D0)
    assert d0_curve["positions_value"] == pytest.approx(0.0)
    assert d0_curve["cash"] == pytest.approx(1_000_000.0)
    quality = res.metadata["data_quality"]
    unfilled = quality["missing_afternoon_adjustment_close_unfilled"]
    assert unfilled
    assert unfilled[0]["date"] == D0
    assert unfilled[0]["reason"] == "missing_afternoon_adjustment_close"
    assert unfilled[0]["codes"] == [CODE]
    assert unfilled[0]["new_target_codes"] == [CODE]
    assert unfilled[0]["held_codes"] == []
    assert unfilled[0]["fallback"] is False
    assert unfilled[0]["fill_substituted"] is False
    assert CODE in unfilled[0]["unfilled_target_shares"]
    assert quality["comparable"] is False
    assert quality["selection_eligible"] is False
    assert D0 in quality["missing_fill_dates"]
    assert D0 in quality["non_comparable_session_dates"]
    assert res.metrics["comparable"] is False
    assert res.metrics["selection_eligible"] is False
    assert D0 in res.metrics["non_comparable_session_dates"]


def test_held_target_missing_same_day_aadjc_keeps_prior_units_and_is_non_comparable(
    tmp_path,
):
    db = _seed(
        tmp_path,
        madjc=100.0,
        aadjc_by_day={D0: 100.0, D2: 110.0, D3: 110.0},
        adjc=999.0,
    )
    rec = AlwaysLong()
    res = _run(db, rec)
    d0_trades = [trade for trade in res.trades if trade["fill_date"] == D0]
    assert len(d0_trades) == 1
    assert d0_trades[0]["price"] == 100.0
    assert all(trade["fill_date"] != D1 for trade in res.trades)
    assert all(trade["price"] != 999.0 for trade in res.trades)
    day1 = next(row for row in res.equity_curve if row["date"] == D1)
    assert CODE in day1["stale_mark_codes"]
    assert day1["positions_value"] == pytest.approx(1_000_000.0)
    quality = res.metadata["data_quality"]
    unfilled = [
        event
        for event in quality["missing_afternoon_adjustment_close_unfilled"]
        if event["date"] == D1
    ]
    assert unfilled
    assert unfilled[0]["reason"] == "missing_afternoon_adjustment_close"
    assert unfilled[0]["codes"] == [CODE]
    assert unfilled[0]["held_codes"] == [CODE]
    assert unfilled[0]["new_target_codes"] == []
    assert unfilled[0]["fallback"] is False
    assert D1 in quality["incomplete_valuation_dates"]
    assert D1 in quality["missing_fill_dates"]
    assert D1 in quality["non_comparable_session_dates"]
    assert quality["comparable"] is False
    assert quality["selection_eligible"] is False
    assert res.metrics["comparable"] is False
    assert res.metrics["selection_eligible"] is False


def test_unheld_missing_m_and_a_stay_no_fill_without_adjc(tmp_path):
    db = _seed(
        tmp_path,
        madjc_by_day={D1: 100.0, D2: 100.0, D3: 100.0},
        aadjc_by_day={D1: 110.0, D2: 110.0, D3: 110.0},
        adjc=999.0,
    )
    rec = AlwaysLong()
    res = _run(db, rec)
    assert rec.ctxs[0].date == D0
    assert rec.ctxs[0].prices[CODE] is None
    assert all(trade["fill_date"] != D0 for trade in res.trades)
    assert all(trade["price"] != 999.0 for trade in res.trades)
    assert res.trades[0]["fill_date"] == D1
    assert res.trades[0]["price"] == 110.0
