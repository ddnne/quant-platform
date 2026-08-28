"""Behavioral regressions for PIT-owned SQL keyset pagination."""

from __future__ import annotations

from contextlib import nullcontext
from types import SimpleNamespace

import pit.query as pit_query
import pytest
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

    decoded: list[dict] = []
    real_decode = pit_query._decode_row

    def count_decode(row):
        decoded.append(dict(row))
        return real_decode(row)

    monkeypatch.setattr(pit_query, "_decode_row", count_decode)
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
    # The reader materializes exactly one look-ahead row, not all 205 rows.
    assert len(decoded) == 201

    decoded.clear()
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
    # The keyset resumes after row 199 and decodes only the remaining five.
    assert len(decoded) == 5


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
