"""Structural regressions for PIT-owned SQL keyset pagination."""

from __future__ import annotations

from contextlib import nullcontext
from types import SimpleNamespace

import pytest

import pit.query as pit_query
from data_access import QuantDataAccess, QuantDataConfig
from pit import get_jquants_records
from storage.sqlite_store import SqliteStore


AS_OF = "2025-01-02T09:00:00+09:00"
EVENT_TIME = "2025-01-01T15:30:00+09:00"
SNAPSHOT_ID = "sha256:" + "a" * 64


def _record(index: int, *, source: str = "jquants") -> dict[str, str]:
    natural_key = f"key-{index:04d}"
    return {
        "source": source,
        "dataset": "equities_bars_daily",
        "natural_key": natural_key,
        "event_time": EVENT_TIME,
        "available_at": "2025-01-01T16:00:00+09:00",
        "ingested_at": "2025-01-01T16:01:00+09:00",
        "payload": f'{{"key":"{natural_key}"}}',
        "raw_payload": f'{{"key":"{natural_key}"}}',
    }


def test_data_access_page_size_200_is_bounded_in_sql(tmp_path, monkeypatch):
    path = tmp_path / "ready.sqlite"
    with SqliteStore(path) as store:
        store.upsert("jquants_records", [_record(index) for index in range(205)])

    statements: list[tuple[str, tuple[object, ...]]] = []
    real_connect = pit_query.connect_readonly

    class RecordingConnection:
        def __init__(self, inner):
            self.inner = inner

        def execute(self, sql, params=()):
            if "SELECT * FROM pit_ranked" in sql:
                statements.append((sql, tuple(params)))
            return self.inner.execute(sql, params)

        def close(self):
            self.inner.close()

    monkeypatch.setattr(
        pit_query,
        "connect_readonly",
        lambda db_path: RecordingConnection(real_connect(db_path)),
    )
    access = QuantDataAccess(
        QuantDataConfig(snapshot_dir=tmp_path, default_page_size=200)
    )
    ready = SimpleNamespace(
        snapshot_id=SNAPSHOT_ID,
        db_path=path,
        manifest={"state": "READY"},
    )
    monkeypatch.setattr(
        access,
        "_pinned_snapshot",
        lambda _snapshot_id=None: nullcontext(ready),
    )

    first = access.query_dataset(
        dataset="equities_bars_daily",
        as_of=AS_OF,
        start="2025-01-01",
        end="2025-01-01",
    )

    assert first["returned"] == 200
    assert first["next_page_token"]
    first_sql, first_params = statements[-1]
    assert "ORDER BY event_time, natural_key, source LIMIT ?" in first_sql
    assert first_params[-1] == 201

    second = access.query_dataset(
        dataset="equities_bars_daily",
        as_of=AS_OF,
        start="2025-01-01",
        end="2025-01-01",
        page_token=first["next_page_token"],
    )

    assert [row["natural_key"] for row in second["rows"]] == [
        f"key-{index:04d}" for index in range(200, 205)
    ]
    assert second["next_page_token"] is None
    second_sql, second_params = statements[-1]
    assert "event_time > ?" in second_sql
    assert "natural_key > ?" in second_sql
    assert "source > ?" in second_sql
    assert second_params[-1] == 201


def test_keyset_cursor_uses_source_tiebreaker_and_binds_snapshot_query(tmp_path):
    path = tmp_path / "pit.sqlite"
    tied = [
        _record(0, source="alpha"),
        _record(0, source="beta"),
        _record(1, source="alpha"),
    ]
    with SqliteStore(path) as store:
        store.upsert("jquants_records", tied)

    common = {
        "as_of": AS_OF,
        "dataset": "equities_bars_daily",
        "db_path": path,
        "page_size": 1,
        "snapshot_id": SNAPSHOT_ID,
    }
    first = get_jquants_records(**common)
    second = get_jquants_records(
        **common, page_token=first.metadata["next_page_token"]
    )
    third = get_jquants_records(
        **common, page_token=second.metadata["next_page_token"]
    )

    assert [
        (result.rows[0]["natural_key"], result.rows[0]["source"])
        for result in (first, second, third)
    ] == [
        ("key-0000", "alpha"),
        ("key-0000", "beta"),
        ("key-0001", "alpha"),
    ]
    assert third.metadata["next_page_token"] is None

    with pytest.raises(ValueError, match="page_token"):
        get_jquants_records(
            **{**common, "snapshot_id": "sha256:" + "b" * 64},
            page_token=first.metadata["next_page_token"],
        )
    with pytest.raises(ValueError, match="page_token"):
        get_jquants_records(
            **{**common, "as_of": "2025-01-03T09:00:00+09:00"},
            page_token=first.metadata["next_page_token"],
        )
