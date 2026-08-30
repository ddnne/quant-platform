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


def _am_ratio_db(
    tmp_path,
    *,
    madjc=None,
    aadjc=100.0,
    adjc=100.0,
    close=10.0,
    market_caps=None,
    morning_turnover=None,
    turnover=None,
    codes=None,
):
    codes = codes or [CODE]
    days = TRADING_DAYS
    return seed_db(
        tmp_path,
        codes=codes,
        prices={code: {day: close for day in days} for code in codes},
        adjustment_prices={code: {day: adjc for day in days} for code in codes},
        morning_adjustment_prices={
            code: madjc or {D0: 100.0, D1: 110.0, D2: 121.0, D3: 133.1}
            for code in codes
        },
        afternoon_adjustment_prices={
            code: {day: aadjc for day in days} for code in codes
        },
        market_caps=market_caps
        or {code: {D0: 1_000.0, D1: 9_999.0, D2: 9_999.0, D3: 9_999.0} for code in codes},
        morning_turnover_values={
            code: morning_turnover or {day: 10.0 + i for i, day in enumerate(days)}
            for code in codes
        },
        turnover_values={
            code: turnover or {day: 9_000.0 for day in days} for code in codes
        },
        morning_adjustment_volumes={code: {day: 1.0 for day in days} for code in codes},
    )


def _am_compute(db, feature_id, *, as_of=None, **inputs):
    as_of = as_of or morning_close_as_of(D3)
    cap = bind_personal_retrospective_am_session_daily_bars(as_of=as_of, db_path=db)
    return compute_with_engine_daily_bars_capability(
        feature_id,
        as_of=as_of,
        db_path=db,
        daily_bars_capability=cap,
        **inputs,
    )


def test_ordinary_compute_cannot_produce_am_feature_identity(tmp_path):
    db = _am_ratio_db(tmp_path)
    with pytest.raises(ValueError, match="AM session feature"):
        features.compute(
            "am_session_price_ratio",
            as_of=morning_close_as_of(D3),
            db_path=db,
            code=CODE,
            mode="return_ratio",
            short_n=2,
            long_n=3,
        )


def test_am_price_ratio_is_invariant_to_d_full_and_afternoon_mutation(tmp_path):
    def _d_only(*, adjc, aadjc, close):
        return seed_db(
            tmp_path / f"{adjc}-{aadjc}-{close}",
            codes=[CODE],
            prices={
                CODE: {D0: 10.0, D1: 10.0, D2: 10.0, D3: close}
            },
            adjustment_prices={
                CODE: {D0: 100.0, D1: 100.0, D2: 100.0, D3: adjc}
            },
            morning_adjustment_prices={
                CODE: {D0: 100.0, D1: 110.0, D2: 121.0, D3: 133.1}
            },
            afternoon_adjustment_prices={
                CODE: {D0: 100.0, D1: 100.0, D2: 100.0, D3: aadjc}
            },
            market_caps={
                CODE: {D0: 1_000.0, D1: 1_000.0, D2: 1_000.0, D3: aadjc * 10.0}
            },
        )

    db_a = _d_only(adjc=100.0, aadjc=100.0, close=10.0)
    db_b = _d_only(adjc=50.0, aadjc=400.0, close=1.0)
    kwargs = dict(code=CODE, mode="return_ratio", short_n=2, long_n=3)
    out_a = _am_compute(db_a, "am_session_price_ratio", **kwargs)
    out_b = _am_compute(db_b, "am_session_price_ratio", **kwargs)
    assert out_a.value == pytest.approx(out_b.value)
    assert out_a.value == pytest.approx(133.1 / 100.0 - 1.0)
    assert out_a.metadata["last_return_interval"] == "prior PM/full -> D morning"
    assert out_a.metadata["session_view_digest"].startswith("sha256:")
    assert out_a.metadata["information_cutoff"] == "11:30:00+09:00"
    assert out_a.metadata["operational_usable_by"] == "12:30:00+09:00"


def test_am_turnover_uses_mva_on_every_window_row(tmp_path):
    db_a = _am_ratio_db(tmp_path / "a", turnover={day: 1.0 for day in TRADING_DAYS})
    db_b = _am_ratio_db(tmp_path / "b", turnover={day: 9_999.0 for day in TRADING_DAYS})
    kwargs = dict(code=CODE, mode="turnover_ratio", short_n=2, long_n=3)
    out_a = _am_compute(db_a, "am_session_price_ratio", **kwargs)
    out_b = _am_compute(db_b, "am_session_price_ratio", **kwargs)
    assert out_a.value == pytest.approx(out_b.value)
    assert out_a.metadata["turnover_source"] == "MVa_morning_turnover_value"
    assert out_a.metadata["volume_fallback"] is False
    assert out_a.metadata["full_day_va_fallback"] is False


def test_am_size_uses_d1_market_cap_not_current_d(tmp_path):
    db = _am_ratio_db(
        tmp_path,
        market_caps={CODE: {D0: 111.0, D1: 222.0, D2: 333.0, D3: 444.0}},
    )
    out = _am_compute(
        db,
        "am_session_price_ratio",
        as_of=morning_close_as_of(D3),
        code=CODE,
        mode="market_cap",
        short_n=2,
        long_n=3,
    )
    assert out.value == pytest.approx(333.0)
    assert out.metadata["market_cap_lag"] == "D-1"
    assert out.metadata["market_cap_date"] == D2


def test_am_per_share_uses_strictly_prior_raw_close(tmp_path):
    db = _am_ratio_db(tmp_path, close=10.0, madjc={day: 50.0 for day in TRADING_DAYS})
    payload = {
        "Code": CODE,
        "DiscDate": D1,
        "CurPerEn": D0,
        "BPS": 80.0,
        "EPS": 5.0,
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
                "event_time": f"{D0}T16:00:00+09:00",
                "available_at": f"{D0}T16:00:00+09:00",
                "ingested_at": f"{D0}T16:00:00+09:00",
                "payload": encoded,
                "raw_payload": encoded,
            }
        ],
    )
    store.close()
    out = _am_compute(
        db,
        "am_session_fundamental_ratio",
        as_of=morning_close_as_of(D3),
        code=CODE,
        mode="book_to_price",
    )
    assert out.value == pytest.approx(80.0 / 10.0)
    assert out.metadata["price_lag"] == "strictly_prior_session"
    assert out.metadata["raw_close_date"] == D2
    assert out.metadata["raw_close"] == 10.0


def test_am_feature_hides_post_1130_disclosure(tmp_path):
    db = _am_ratio_db(tmp_path, close=10.0)
    early = {
        "Code": CODE,
        "DiscDate": D0,
        "CurPerEn": D0,
        "BPS": 40.0,
    }
    late = {
        "Code": CODE,
        "DiscDate": D3,
        "CurPerEn": D3,
        "BPS": 999.0,
    }
    store = SqliteStore(db)
    store.upsert(
        "jquants_records",
        [
            {
                "source": "jquants",
                "dataset": "fins_summary",
                "natural_key": natural_key(early, "fins_summary"),
                "event_time": f"{D0}T16:00:00+09:00",
                "available_at": f"{D0}T16:00:00+09:00",
                "ingested_at": f"{D0}T16:00:00+09:00",
                "payload": json.dumps(early, sort_keys=True, separators=(",", ":")),
                "raw_payload": json.dumps(early, sort_keys=True, separators=(",", ":")),
            },
            {
                "source": "jquants",
                "dataset": "fins_summary",
                "natural_key": natural_key(late, "fins_summary"),
                "event_time": f"{D3}T12:00:00+09:00",
                "available_at": f"{D3}T12:00:00+09:00",
                "ingested_at": f"{D3}T12:00:00+09:00",
                "payload": json.dumps(late, sort_keys=True, separators=(",", ":")),
                "raw_payload": json.dumps(late, sort_keys=True, separators=(",", ":")),
            },
        ],
    )
    store.close()
    out = _am_compute(
        db,
        "am_session_fundamental_ratio",
        as_of=morning_close_as_of(D3),
        code=CODE,
        mode="book_to_price",
    )
    assert out.value == pytest.approx(40.0 / 10.0)
    assert out.metadata["numerator"] == 40.0


def test_am_missing_one_code_returns_none_without_abort(tmp_path):
    other = "8697"
    db = seed_db(
        tmp_path,
        codes=[CODE, other],
        prices={
            CODE: {day: 10.0 for day in TRADING_DAYS},
            other: {day: 10.0 for day in TRADING_DAYS},
        },
        adjustment_prices={
            CODE: {day: 100.0 for day in TRADING_DAYS},
            other: {day: 100.0 for day in TRADING_DAYS},
        },
        morning_adjustment_prices={
            CODE: {D0: 100.0, D1: 110.0, D2: 121.0},
            other: {D0: 100.0, D1: 110.0, D2: 121.0, D3: 133.1},
        },
        afternoon_adjustment_prices={
            CODE: {day: 100.0 for day in TRADING_DAYS},
            other: {day: 100.0 for day in TRADING_DAYS},
        },
    )
    missing = _am_compute(
        db,
        "am_session_price_ratio",
        code=CODE,
        mode="return_ratio",
        short_n=2,
        long_n=3,
    )
    present = _am_compute(
        db,
        "am_session_price_ratio",
        code=other,
        mode="return_ratio",
        short_n=2,
        long_n=3,
    )
    assert missing.value is None
    assert "missing D morning" in missing.metadata["reason"]
    assert present.value == pytest.approx(133.1 / 100.0 - 1.0)


def test_am_cache_identity_is_isolated_from_ordinary_close(tmp_path):
    from paper_runtime.personal_prepared_frame import _feature_cache_key_document

    ordinary = _feature_cache_key_document(
        snapshot_id="sha256:" + "1" * 64,
        as_of=morning_close_as_of(D3),
        code=CODE,
        feature_id="retrospective_price_ratio",
        feature_version="1.0.0",
        definition_digest="sha256:" + "2" * 64,
        params={"mode": "return_ratio", "short_n": 2, "long_n": 3},
    )
    am_same_legacy_id = _feature_cache_key_document(
        snapshot_id="sha256:" + "1" * 64,
        as_of=morning_close_as_of(D3),
        code=CODE,
        feature_id="retrospective_price_ratio",
        feature_version="1.0.0",
        definition_digest="sha256:" + "2" * 64,
        params={"mode": "return_ratio", "short_n": 2, "long_n": 3},
        session_view_digest="sha256:" + "3" * 64,
    )
    am_new_id = _feature_cache_key_document(
        snapshot_id="sha256:" + "1" * 64,
        as_of=morning_close_as_of(D3),
        code=CODE,
        feature_id="am_session_price_ratio",
        feature_version="1.0.0",
        definition_digest="sha256:" + "2" * 64,
        params={"mode": "return_ratio", "short_n": 2, "long_n": 3},
        session_view_digest="sha256:" + "3" * 64,
    )
    assert ordinary != am_same_legacy_id
    assert ordinary != am_new_id
    assert am_same_legacy_id != am_new_id
    assert "session_view_digest" not in ordinary
    assert am_new_id["session_view_digest"].startswith("sha256:")
