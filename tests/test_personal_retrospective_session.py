"""Personal-retrospective AM/PM session adapter: field-time reconstruction."""

from __future__ import annotations

import json

import pit
import pit.personal_retrospective_session as session_mod
import pytest
from core.execution import close_as_of, morning_close_as_of
from data_contracts.identity import natural_key
from storage.sqlite_store import SqliteStore

from _coreseed import CODES, TRADING_DAYS, seed_db

D0, D1, D2, D3 = TRADING_DAYS
CODE = "1332"


def _level(value: float) -> dict[str, dict[str, float]]:
    return {CODE: {day: value for day in TRADING_DAYS}}


def _am_db(tmp_path, **kwargs):
    defaults = dict(
        codes=[CODE],
        prices=_level(10.0),
        adjustment_prices=_level(999.0),
        morning_adjustment_prices=_level(50.0),
        afternoon_adjustment_prices=_level(80.0),
        morning_adjustment_volumes=_level(1.0),
        afternoon_adjustment_volumes=_level(2.0),
        morning_turnover_values=_level(111.0),
        turnover_values=_level(500.0),
        market_caps=_level(1_000_000.0),
    )
    defaults.update(kwargs)
    return seed_db(tmp_path, **defaults)


def test_am_signal_view_masks_d_and_keeps_prior_full_rows(tmp_path):
    db = _am_db(tmp_path)
    result = pit.get_personal_retrospective_am_signal_equity_bars_daily(
        as_of=morning_close_as_of(D2),
        code=CODE,
        from_event=D0,
        to_event=D2,
        db_path=db,
    )
    dates = [row["date"] for row in result.rows]
    assert dates == [D0, D1, D2]
    prior = result.rows[0]
    assert prior["adjustment_close"] == 999.0
    assert prior["close"] == 10.0
    d_row = result.rows[-1]
    assert d_row["date"] == D2
    assert d_row["adjustment_close"] == 50.0
    assert d_row["adjustment_volume"] == 1.0
    assert "close" not in d_row
    assert "market_cap" not in d_row
    assert "turnover_value" not in d_row
    assert "afternoon_adjustment_close" not in d_row
    assert "raw_payload" not in d_row
    assert result.metadata["as_of"] == morning_close_as_of(D2)
    assert result.metadata["historical_source"] == "equities_bars_daily"
    assert result.metadata["publication_claim"] is False
    assert result.metadata["field_time_reconstruction"] is True


def test_am_signal_latest_n_and_date_bounds_and_ordering(tmp_path):
    by_code = {code: {day: 10.0 for day in TRADING_DAYS} for code in CODES}
    db = seed_db(
        tmp_path,
        codes=list(CODES),
        prices=by_code,
        adjustment_prices={code: {day: 999.0 for day in TRADING_DAYS} for code in CODES},
        morning_adjustment_prices={
            code: {day: 50.0 for day in TRADING_DAYS} for code in CODES
        },
        afternoon_adjustment_prices={
            code: {day: 80.0 for day in TRADING_DAYS} for code in CODES
        },
    )
    latest = pit.get_personal_retrospective_am_signal_equity_bars_daily(
        as_of=morning_close_as_of(D3),
        code=CODE,
        latest_n=2,
        db_path=db,
    )
    assert [row["date"] for row in latest.rows] == [D2, D3]
    assert latest.metadata["latest_n"] == 2

    bounded = pit.get_personal_retrospective_am_signal_equity_bars_daily(
        as_of=morning_close_as_of(D2),
        codes=CODES,
        from_event=D2,
        to_event=D2,
        db_path=db,
    )
    assert [row["date"] for row in bounded.rows] == [D2, D2]
    assert [row["code"] for row in bounded.rows] == sorted(CODES)


def test_am_signal_d_row_does_not_fall_back_to_full_adjc(tmp_path):
    db = _am_db(
        tmp_path,
        morning_adjustment_prices={CODE: {D1: 50.0, D2: 50.0, D3: 50.0}},
        adjustment_prices=_level(999.0),
    )
    result = pit.get_personal_retrospective_am_signal_equity_bars_daily(
        as_of=morning_close_as_of(D0),
        code=CODE,
        db_path=db,
    )
    d_row = result.rows[-1]
    assert d_row["date"] == D0
    assert d_row.get("adjustment_close") is None
    assert "close" not in d_row
    assert "afternoon_adjustment_close" not in d_row
    assert d_row.get("adjustment_close") != 999.0


def test_am_signal_rejects_non_morning_as_of(tmp_path):
    db = _am_db(tmp_path)
    with pytest.raises(ValueError, match="11:30"):
        pit.get_personal_retrospective_am_signal_equity_bars_daily(
            as_of=close_as_of(D0),
            code=CODE,
            db_path=db,
        )


def test_pm_fill_view_returns_only_aadjc(tmp_path):
    db = _am_db(tmp_path)
    result = pit.get_personal_retrospective_pm_fill_equity_bars_daily(
        as_of=close_as_of(D1),
        session_date=D1,
        code=CODE,
        db_path=db,
    )
    assert len(result.rows) == 1
    row = result.rows[0]
    assert row["adjustment_close"] == 80.0
    assert row["afternoon_adjustment_close"] == 80.0
    assert "close" not in row
    assert "morning_adjustment_close" not in row
    assert set(row) <= {
        "source",
        "code",
        "date",
        "adjustment_close",
        "afternoon_adjustment_close",
    }


def test_pm_fill_rejects_as_of_after_official_close(tmp_path):
    db = _am_db(tmp_path)
    with pytest.raises(ValueError, match="official session close"):
        pit.get_personal_retrospective_pm_fill_equity_bars_daily(
            as_of=f"{D1}T17:00:00+09:00",
            session_date=D1,
            code=CODE,
            db_path=db,
        )


def test_morning_turnover_history_is_consistent_when_requested(tmp_path):
    db = _am_db(tmp_path)
    mixed = pit.get_personal_retrospective_am_signal_equity_bars_daily(
        as_of=morning_close_as_of(D1),
        code=CODE,
        db_path=db,
    )
    assert "turnover_value" not in mixed.rows[-1]
    assert mixed.rows[0]["turnover_value"] == 500.0

    consistent = pit.get_personal_retrospective_am_signal_equity_bars_daily(
        as_of=morning_close_as_of(D1),
        code=CODE,
        include_morning_turnover_history=True,
        db_path=db,
    )
    for row in consistent.rows:
        assert "turnover_value" not in row
    assert consistent.rows[-1]["morning_turnover_value"] == 111.0


def test_adapter_does_not_read_tip_only_am_dataset(tmp_path, monkeypatch):
    db = _am_db(tmp_path)
    payload = {
        "Code": CODE,
        "Date": D1,
        "MAdjC": 1.0,
        "AAdjC": 2.0,
        "AdjC": 3.0,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    store = SqliteStore(db)
    store.upsert(
        "jquants_records",
        [
            {
                "source": "jquants",
                "dataset": "equities_bars_daily_am",
                "natural_key": natural_key(payload, "equities_bars_daily_am"),
                "event_time": f"{D1}T11:30:00+09:00",
                "available_at": f"{D1}T11:30:00+09:00",
                "ingested_at": f"{D1}T11:30:00+09:00",
                "payload": encoded,
                "raw_payload": encoded,
            }
        ],
    )
    store.close()

    real = pit.get_jquants_records

    def guarded(*args, **kwargs):
        if kwargs.get("dataset") == "equities_bars_daily_am":
            raise AssertionError("must not read equities_bars_daily_am")
        return real(*args, **kwargs)

    monkeypatch.setattr(pit, "get_jquants_records", guarded)
    result = pit.get_personal_retrospective_am_signal_equity_bars_daily(
        as_of=morning_close_as_of(D1),
        code=CODE,
        db_path=db,
    )
    assert result.rows[-1]["adjustment_close"] == 50.0


_D_AM_FORBIDDEN_FIELDS = frozenset(
    {
        "event_time",
        "available_at",
        "ingested_at",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "adjustment_open",
        "adjustment_high",
        "adjustment_low",
        "turnover_value",
        "market_cap",
        "afternoon_adjustment_close",
        "afternoon_turnover_value",
        "afternoon_adjustment_volume",
        "morning_adjustment_close",
        "raw_payload",
        "payload",
    }
)
_ROW_TIMESTAMP_FIELDS = ("event_time", "available_at", "ingested_at")


def test_am_d_row_is_allowlisted_and_does_not_leak_later_timestamps(tmp_path):
    db = _am_db(tmp_path)
    as_of = morning_close_as_of(D2)
    result = pit.get_personal_retrospective_am_signal_equity_bars_daily(
        as_of=as_of,
        code=CODE,
        from_event=D0,
        to_event=D2,
        db_path=db,
    )
    assert not isinstance(result, pit.PitResult)
    assert hasattr(result, "rows") and hasattr(result, "metadata")
    d_row = result.rows[-1]
    assert d_row["date"] == D2
    assert set(d_row) <= {
        "source",
        "code",
        "date",
        "adjustment_close",
        "adjustment_volume",
        "morning_turnover_value",
    }
    assert "morning_turnover_value" not in d_row
    for field in _D_AM_FORBIDDEN_FIELDS:
        assert field not in d_row
    for row in result.rows:
        for field in _ROW_TIMESTAMP_FIELDS:
            if field in row:
                assert str(row[field]) <= as_of
    reconstruction = result.metadata["retrospective_reconstruction"]
    assert reconstruction["d_row_source_dataset"] == "equities_bars_daily"
    assert reconstruction["d_row_source_read_as_of"].startswith(D2)
    assert reconstruction["d_row_source_publication_timestamps"]
    source_available = reconstruction["d_row_source_publication_timestamps"][0][
        "source_available_at"
    ]
    assert source_available > as_of
    assert result.metadata["information_cutoff"] == "11:30:00+09:00"
    assert result.metadata["operational_usable_by"] == "12:30:00+09:00"
    assert result.metadata["session_view_digest"].startswith("sha256:")


def test_am_latest_n_bounds_the_prior_query(tmp_path, monkeypatch):
    db = _am_db(tmp_path)
    calls: list[dict] = []
    real = session_mod.get_equity_bars_daily

    def spy(*args, **kwargs):
        calls.append(dict(kwargs))
        return real(*args, **kwargs)

    monkeypatch.setattr(session_mod, "get_equity_bars_daily", spy)
    result = pit.get_personal_retrospective_am_signal_equity_bars_daily(
        as_of=morning_close_as_of(D3),
        code=CODE,
        latest_n=2,
        db_path=db,
    )
    assert [row["date"] for row in result.rows] == [D2, D3]
    prior_calls = [
        call
        for call in calls
        if str(call.get("as_of") or "").endswith("T11:30:00+09:00")
    ]
    d_calls = [
        call
        for call in calls
        if str(call.get("as_of") or "").endswith("T15:30:00+09:00")
    ]
    assert prior_calls
    assert all(call.get("latest_n") == 2 for call in prior_calls)
    assert d_calls
    assert all(call.get("latest_n") is None for call in d_calls)
    assert all(call.get("from_event") == D3 for call in d_calls)
    assert all(call.get("to_event") == D3 for call in d_calls)
