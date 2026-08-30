"""Engine AM feature contexts use session-masked bars; other PIT stays 11:30."""

from __future__ import annotations

import json

import features
import pit
import pytest
from core import PERSONAL_RETROSPECTIVE_ADJUSTED, run_backtest, standard_cost
from core.execution import morning_close_as_of
from core.strategy_protocol import BarContext, OrderIntent
from core.universe import membership_at
from data_contracts.identity import natural_key
from features.runtime import (
    bind_personal_retrospective_am_session_daily_bars,
    compute_with_engine_daily_bars_capability,
)
from storage.sqlite_store import SqliteStore

from _coreseed import TRADING_DAYS, seed_db

D0, D1, D2, D3 = TRADING_DAYS
CODE = "1332"


def _seed(tmp_path):
    return seed_db(
        tmp_path,
        codes=[CODE],
        prices={CODE: {day: 10.0 for day in TRADING_DAYS}},
        adjustment_prices={CODE: {day: 100.0 for day in TRADING_DAYS}},
        morning_adjustment_prices={
            CODE: {D0: 100.0, D1: 110.0, D2: 110.0, D3: 110.0}
        },
        afternoon_adjustment_prices={CODE: {day: 100.0 for day in TRADING_DAYS}},
    )


def test_ordinary_compute_at_1130_does_not_see_d_full_close(tmp_path):
    db = _seed(tmp_path)
    out = features.compute(
        "retrospective_split_adjusted_momentum_n",
        as_of=morning_close_as_of(D1),
        code=CODE,
        n=1,
        db_path=db,
    )
    # D1 bar publishes at the official close, so ordinary 11:30 PIT cannot see it.
    assert out.value is None
    assert out.metadata.get("last_date") != D1


def test_engine_am_capability_sees_d_morning_adjustment_close(tmp_path):
    db = _seed(tmp_path)
    as_of = morning_close_as_of(D1)
    cap = bind_personal_retrospective_am_session_daily_bars(as_of=as_of, db_path=db)
    out = compute_with_engine_daily_bars_capability(
        "retrospective_split_adjusted_momentum_n",
        as_of=as_of,
        db_path=db,
        daily_bars_capability=cap,
        code=CODE,
        n=1,
    )
    assert out.value == pytest.approx(0.10)
    assert out.metadata["last_date"] == D1
    assert out.metadata["last_adjustment_close"] == 110.0


def test_am_capability_d_row_has_no_full_or_afternoon_fields(tmp_path):
    db = seed_db(
        tmp_path,
        codes=[CODE],
        prices={CODE: {day: 10.0 for day in TRADING_DAYS}},
        adjustment_prices={CODE: {day: 999.0 for day in TRADING_DAYS}},
        morning_adjustment_prices={CODE: {day: 110.0 for day in TRADING_DAYS}},
        afternoon_adjustment_prices={CODE: {day: 180.0 for day in TRADING_DAYS}},
        market_caps={CODE: {day: 1_000_000.0 for day in TRADING_DAYS}},
    )
    seen: dict[str, object] = {}

    def inspect(ctx):
        rows = ctx.get_equity_bars_daily(
            code=CODE, from_event=D1, to_event=D1
        ).rows
        seen["rows"] = rows
        return features.FeatureOutput(value=len(rows))

    definition = features.FeatureDefinition(
        id="am_d_row_mask_fixture",
        version=features.FeatureVersion(1),
        inputs=features.FeatureInput(required_kwargs=("code",)),
        description="inspect AM D row",
        compute=inspect,
        intended_role="utility",
    )
    cap = bind_personal_retrospective_am_session_daily_bars(
        as_of=morning_close_as_of(D1), db_path=db
    )
    compute_with_engine_daily_bars_capability(
        definition,
        as_of=morning_close_as_of(D1),
        db_path=db,
        daily_bars_capability=cap,
        code=CODE,
    )
    assert len(seen["rows"]) == 1
    row = seen["rows"][0]
    assert row["adjustment_close"] == 110.0
    for leaked in (
        "close",
        "market_cap",
        "afternoon_adjustment_close",
        "turnover_value",
        "raw_payload",
    ):
        assert leaked not in row


def test_ordinary_compute_cannot_inject_later_as_of_or_db_scope(tmp_path):
    db = _seed(tmp_path)

    def inspect(ctx):
        with pytest.raises(TypeError, match="runtime-scoped"):
            ctx.get_equity_bars_daily(as_of=f"{D1}T15:30:00+09:00", code=CODE)
        with pytest.raises(TypeError, match="runtime-scoped"):
            ctx.get_equity_bars_daily(db_path="other.sqlite", code=CODE)
        return features.FeatureOutput(value=1.0)

    definition = features.FeatureDefinition(
        id="am_scope_guard_fixture",
        version=features.FeatureVersion(1),
        inputs=features.FeatureInput(required_kwargs=("code",)),
        description="scope guard",
        compute=inspect,
        intended_role="utility",
    )
    features.compute(
        definition,
        as_of=morning_close_as_of(D1),
        code=CODE,
        db_path=db,
    )


def test_bound_capability_rejects_mismatched_as_of(tmp_path):
    db = _seed(tmp_path)
    cap = bind_personal_retrospective_am_session_daily_bars(
        as_of=morning_close_as_of(D1), db_path=db
    )
    with pytest.raises(ValueError, match="as_of"):
        compute_with_engine_daily_bars_capability(
            "retrospective_split_adjusted_momentum_n",
            as_of=morning_close_as_of(D2),
            db_path=db,
            daily_bars_capability=cap,
            code=CODE,
            n=1,
        )


def test_post_1130_non_price_fact_stays_hidden_in_am_engine_context(tmp_path):
    db = _seed(tmp_path)
    payload = {
        "Code": CODE,
        "DiscDate": D1,
        "CurPerEn": D1,
        "BPS": 80.0,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    store = SqliteStore(db)
    store.upsert(
        "jquants_records",
        [
            {
                "source": "jquants",
                "dataset": "fins_summary",
                "natural_key": natural_key(payload, "fins_summary"),
                "event_time": f"{D1}T12:00:00+09:00",
                "available_at": f"{D1}T12:00:00+09:00",
                "ingested_at": f"{D1}T12:00:00+09:00",
                "payload": encoded,
                "raw_payload": encoded,
            }
        ],
    )
    store.close()

    seen: dict[str, float] = {}

    class Probe:
        strategy_id = "am_non_price_probe"
        params: dict = {}

        def on_bar(self, ctx: BarContext) -> list[OrderIntent]:
            if ctx.date == D1:
                out = ctx.feature("disclosure_flag_fins", code=CODE)
                seen["flag"] = float(out.value)
                seen["rows"] = float(out.metadata["rows_seen"])
            return []

    run_backtest(
        Probe(),
        D0,
        D3,
        db_path=db,
        universe=membership_at(
            morning_close_as_of(D0), db_path=db, codes=(CODE,)
        ),
        execution_mode="am_signal_pm_close",
        price_basis=PERSONAL_RETROSPECTIVE_ADJUSTED,
        cost_model=standard_cost(bps=0.0),
    )
    assert seen["flag"] == 0.0
    assert seen["rows"] == 0.0


def test_engine_am_ctx_feature_uses_masked_daily_bars(tmp_path):
    db = _seed(tmp_path)
    seen: dict[str, float] = {}

    class MomentumProbe:
        strategy_id = "am_momentum_probe"
        params: dict = {}

        def on_bar(self, ctx: BarContext) -> list[OrderIntent]:
            if ctx.date == D1:
                out = ctx.feature(
                    "retrospective_split_adjusted_momentum_n",
                    code=CODE,
                    n=1,
                )
                seen["value"] = float(out.value)
                seen["last_close"] = float(out.metadata["last_adjustment_close"])
            return []

    run_backtest(
        MomentumProbe(),
        D0,
        D3,
        db_path=db,
        universe=membership_at(
            morning_close_as_of(D0), db_path=db, codes=(CODE,)
        ),
        execution_mode="am_signal_pm_close",
        price_basis=PERSONAL_RETROSPECTIVE_ADJUSTED,
        cost_model=standard_cost(bps=0.0),
    )
    assert seen["last_close"] == 110.0
    assert seen["value"] == pytest.approx(0.10)
    # Ordinary PIT at the same instant still cannot see D's full close.
    ordinary = pit.get_equity_bars_daily(
        as_of=morning_close_as_of(D1),
        code=CODE,
        from_event=D1,
        to_event=D1,
        db_path=db,
    )
    assert ordinary.rows == []
