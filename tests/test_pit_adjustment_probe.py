"""Exactness and bounded-materialization contracts for adjusted-close probe."""

from __future__ import annotations

import math
import sqlite3
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import pit
import pit.api as api_module
import pit.query as query_module
import pytest
from core.engine import (
    _required_adjusted_close,
    _validate_prepared_adjustment_window,
)
from ingestion.jquants.normalize import normalize_daily_bars, normalize_generic
from paper_runtime.personal_prepared_frame import _personal_prepared_frame_scope
from storage.sqlite_store import SqliteStore

AS_OF = "2025-06-01T09:00:00+09:00"
CODE = "8697"


def _source_bar(day: str, adjusted: Any = 100.0, *, code: str = CODE) -> dict:
    return {
        "Code": code,
        "Date": day,
        "Open": 100.0,
        "High": 101.0,
        "Low": 99.0,
        "Close": 100.0,
        "Volume": 1_000,
        "AdjustmentClose": adjusted,
    }


def _typed_bar(
    day: str,
    adjusted: Any = 100.0,
    *,
    code: str = CODE,
    available_at: str | None = None,
) -> dict:
    published = available_at or f"{day}T15:30:00+09:00"
    return normalize_daily_bars(
        [_source_bar(day, adjusted, code=code)],
        ingested_at=published,
        available_at=published,
    )[0]


def _first_invalid_from_public(path: Path) -> dict[str, Any] | None:
    rows = pit.get_equity_bars_daily(
        as_of=AS_OF,
        codes=(CODE,),
        from_event="2025-04-01",
        to_event="2025-04-30",
        db_path=path,
    ).rows
    for row in rows:
        value = row.get("adjustment_close")
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            return row
        if not math.isfinite(numeric) or numeric <= 0.0:
            return row
    return None


@pytest.mark.parametrize(
    "stored_value",
    (None, -1.0, "not-a-price", float("inf"), float("-inf"), float("nan")),
    ids=("null", "negative", "text", "positive-inf", "negative-inf", "nan"),
)
def test_probe_returns_exact_first_public_row_for_invalid_typed_values(
    tmp_path: Path,
    stored_value: Any,
) -> None:
    path = tmp_path / "typed-invalid.sqlite"
    with SqliteStore(path) as store:
        store.upsert(
            "jquants_daily_bars",
            [
                _typed_bar("2025-04-01"),
                _typed_bar("2025-04-02"),
                _typed_bar("2025-04-03"),
            ],
        )
    with sqlite3.connect(path) as connection:
        connection.execute(
            "UPDATE jquants_daily_bars SET adjustment_close=? "
            "WHERE code=? AND date=?",
            (stored_value, CODE, "2025-04-02"),
        )

    expected = _first_invalid_from_public(path)
    actual = pit.first_invalid_adjusted_close(
        as_of=AS_OF,
        codes=(CODE,),
        from_event="2025-04-01",
        to_event="2025-04-30",
        db_path=path,
    )
    assert expected is not None
    assert actual == expected


def test_probe_applies_python_float_semantics_to_suspicious_storage(
    tmp_path: Path,
) -> None:
    path = tmp_path / "numeric-blob.sqlite"
    with SqliteStore(path) as store:
        store.upsert(
            "jquants_daily_bars",
            [_typed_bar("2025-04-01"), _typed_bar("2025-04-02")],
        )
    with sqlite3.connect(path) as connection:
        # SQLite's BLOB storage class is a SQL-probe candidate, but float()
        # accepts this exact byte representation. It must not become a false
        # invalid row merely because the optimization saw it.
        connection.execute(
            "UPDATE jquants_daily_bars SET adjustment_close=? "
            "WHERE code=? AND date=?",
            (sqlite3.Binary(b"12.5"), CODE, "2025-04-01"),
        )

    assert _first_invalid_from_public(path) is None
    assert (
        pit.first_invalid_adjusted_close(
            as_of=AS_OF,
            codes=(CODE,),
            from_event="2025-04-01",
            to_event="2025-04-30",
            db_path=path,
        )
        is None
    )


@pytest.mark.parametrize(
    ("original", "amended", "invalid_before", "invalid_after"),
    ((-1.0, 102.0, True, False), (101.0, -2.0, False, True)),
)
def test_probe_preserves_available_revision_selection(
    tmp_path: Path,
    original: float,
    amended: float,
    invalid_before: bool,
    invalid_after: bool,
) -> None:
    path = tmp_path / "typed-revision.sqlite"
    with SqliteStore(path) as store:
        store.upsert(
            "jquants_daily_bars",
            [
                _typed_bar(
                    "2025-04-01",
                    original,
                    available_at="2025-04-02T09:00:00+09:00",
                )
            ],
        )
        store.upsert(
            "jquants_daily_bars",
            [
                _typed_bar(
                    "2025-04-01",
                    amended,
                    available_at="2025-05-01T09:00:00+09:00",
                )
            ],
        )

    before = pit.first_invalid_adjusted_close(
        as_of="2025-04-10T09:00:00+09:00",
        codes=(CODE,),
        db_path=path,
    )
    after = pit.first_invalid_adjusted_close(
        as_of=AS_OF,
        codes=(CODE,),
        db_path=path,
    )
    assert (before is not None) is invalid_before
    assert (after is not None) is invalid_after
    if before is not None:
        assert before == pit.get_equity_bars_daily(
            as_of="2025-04-10T09:00:00+09:00", codes=(CODE,), db_path=path
        ).rows[0]
    if after is not None:
        assert after == pit.get_equity_bars_daily(
            as_of=AS_OF, codes=(CODE,), db_path=path
        ).rows[0]


@pytest.mark.parametrize(
    ("typed_value", "catalog_value", "expect_invalid"),
    ((-1.0, 103.0, False), (101.0, -3.0, True)),
)
def test_probe_preserves_typed_catalog_latest_visible_merge(
    tmp_path: Path,
    typed_value: float,
    catalog_value: float,
    expect_invalid: bool,
) -> None:
    path = tmp_path / "dual-store.sqlite"
    with SqliteStore(path) as store:
        store.upsert(
            "jquants_daily_bars",
            [
                _typed_bar(
                    "2025-04-01",
                    typed_value,
                    available_at="2025-04-02T09:00:00+09:00",
                )
            ],
        )
        store.upsert(
            "jquants_records",
            normalize_generic(
                [_source_bar("2025-04-01", catalog_value)],
                dataset="equities_bars_daily",
                ingested_at="2025-04-03T09:00:00+09:00",
                available_at="2025-04-03T09:00:00+09:00",
            ),
        )

    public_rows = pit.get_equity_bars_daily(
        as_of=AS_OF, codes=(CODE,), db_path=path
    ).rows
    assert len(public_rows) == 1
    actual = pit.first_invalid_adjusted_close(
        as_of=AS_OF, codes=(CODE,), db_path=path
    )
    assert (actual is not None) is expect_invalid
    if actual is not None:
        assert actual == public_rows[0]


def test_typed_fast_path_materializes_only_candidates_and_checks_shape_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "bounded-probe.sqlite"
    start = date(2024, 1, 1)
    rows = [
        _typed_bar((start + timedelta(days=offset)).isoformat())
        for offset in range(300)
    ]
    rows[-1]["adjustment_close"] = -1.0
    with SqliteStore(path) as store:
        store.upsert("jquants_daily_bars", rows)

    statements: list[str] = []
    decoded = 0
    real_connect = query_module.connect_readonly
    real_decode = query_module._decode_row

    def traced_connect(db_path):
        connection = real_connect(db_path)
        connection.set_trace_callback(statements.append)
        return connection

    def tracked_decode(row):
        nonlocal decoded
        decoded += 1
        return real_decode(row)

    def forbidden_full_read(*_args, **_kwargs):
        raise AssertionError("standalone typed fast path used the full PIT read")

    monkeypatch.setattr(query_module, "connect_readonly", traced_connect)
    monkeypatch.setattr(query_module, "_decode_row", tracked_decode)
    monkeypatch.setattr(api_module, "get_equity_bars_daily", forbidden_full_read)

    with query_module._readonly_connection_scope(path):
        for _ in range(2):
            invalid = pit.first_invalid_adjusted_close(
                as_of=AS_OF,
                codes=(CODE,),
                from_event="2024-01-01",
                to_event="2025-01-31",
                db_path=path,
            )
            assert invalid is not None
            assert invalid["date"] == rows[-1]["date"]

    # One offending row per call leaves SQLite; the other 299 rows are never
    # decoded/materialized. DB-shape authority is established once per scoped
    # immutable connection, not once per decision day.
    assert decoded == 2
    assert sum(
        "FROM jquants_daily_bars_revisions LIMIT 1" in sql
        for sql in statements
    ) == 1
    assert sum(
        "SELECT source FROM jquants_daily_bars" in sql for sql in statements
    ) == 2


@pytest.mark.parametrize(
    ("value", "message"),
    (
        (None, "requires adjustment_close"),
        ("bad", "non-numeric adjustment_close"),
        (-1.0, "requires a positive adjustment_close"),
        (float("inf"), "requires a positive adjustment_close"),
        (float("nan"), "requires a positive adjustment_close"),
    ),
)
def test_required_adjusted_close_rejects_invalid_domain_with_stable_messages(
    value: Any,
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        _required_adjusted_close(
            {"code": CODE, "date": "2025-04-01", "adjustment_close": value}
        )


def test_validation_marker_is_written_only_after_probe_success(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "marker.sqlite"
    SqliteStore(path).close()
    calls = 0

    def probe(**_kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            return {
                "code": CODE,
                "date": "2025-04-01",
                "adjustment_close": None,
            }
        return None

    monkeypatch.setattr(pit, "first_invalid_adjusted_close", probe)
    kwargs = {
        "as_of": AS_OF,
        "codes": {CODE},
        "from_event": "2025-04-01",
        "to_event": "2025-04-30",
        "db_path": path,
    }
    with _personal_prepared_frame_scope(
        db_path=path,
        snapshot_id="sha256:" + "0" * 64,
    ) as frame:
        with pytest.raises(ValueError, match="requires adjustment_close"):
            _validate_prepared_adjustment_window(**kwargs)
        assert frame.stats()["price_window_writes"] == 0

        _validate_prepared_adjustment_window(**kwargs)
        assert frame.stats()["price_window_writes"] == 1
        _validate_prepared_adjustment_window(**kwargs)

    assert calls == 2
