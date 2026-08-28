"""Behavioral invariants for explicit PIT read-connection reuse."""

from __future__ import annotations

import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pit.query as query_module
import pytest
from ingestion.jquants.normalize import normalize_daily_bars
from storage.sqlite_store import SqliteStore

AS_OF = "2025-04-10T15:30:00+09:00"
CODE = "8697"


def _database(tmp_path: Path, name: str, close: float) -> Path:
    path = tmp_path / name
    published = "2025-04-01T15:30:00+09:00"
    row = normalize_daily_bars(
        [
            {
                "Code": CODE,
                "Date": "2025-04-01",
                "Open": close,
                "High": close,
                "Low": close,
                "Close": close,
                "Volume": 1_000,
            }
        ],
        ingested_at=published,
        available_at=published,
    )[0]
    with SqliteStore(path) as store:
        store.upsert("jquants_daily_bars", [row])
    return path


def _read(path: Path) -> list[dict]:
    return query_module.run_query(
        path,
        as_of=AS_OF,
        table="jquants_daily_bars",
        extra_where="code = ?",
        params=[CODE],
        order_by="date",
    )


class _TrackedConnection:
    def __init__(
        self,
        connection: sqlite3.Connection,
        path: Path,
        closed: list[_TrackedConnection],
    ) -> None:
        self.connection = connection
        self.path = path.resolve()
        self.thread_id = threading.get_ident()
        self._closed = closed

    def execute(self, sql, params=()):
        return self.connection.execute(sql, params)

    def rollback(self) -> None:
        self.connection.rollback()

    def close(self) -> None:
        self.connection.close()
        self._closed.append(self)


def _track_connections(monkeypatch: pytest.MonkeyPatch):
    opened: list[_TrackedConnection] = []
    closed: list[_TrackedConnection] = []
    real_connect = query_module.connect_readonly

    def tracked_connect(db_path):
        tracked = _TrackedConnection(real_connect(db_path), Path(db_path), closed)
        opened.append(tracked)
        return tracked

    monkeypatch.setattr(query_module, "connect_readonly", tracked_connect)
    return opened, closed


def test_scope_is_opt_in_nested_safe_readonly_and_result_equivalent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = _database(tmp_path, "paper.sqlite", 101.0)
    expected = _read(path)
    opened, closed = _track_connections(monkeypatch)

    assert _read(path) == expected
    assert _read(path) == expected
    assert len(opened) == len(closed) == 2

    with query_module._readonly_connection_scope(path) as raw_capability:
        assert raw_capability is None
        assert _read(path) == expected
        with query_module._readonly_connection_scope(path.resolve()):
            assert _read(path) == expected
            assert len(opened) == 3
            assert len(closed) == 2
        with pytest.raises(sqlite3.OperationalError, match="readonly"):
            opened[-1].execute("DELETE FROM jquants_daily_bars")

    assert len(opened) == len(closed) == 3
    assert _read(path) == expected
    assert len(opened) == len(closed) == 4


def test_scope_exception_is_not_suppressed_and_always_closes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = _database(tmp_path, "exception.sqlite", 102.0)
    opened, closed = _track_connections(monkeypatch)

    with (
        pytest.raises(RuntimeError, match="paper failed"),
        query_module._readonly_connection_scope(path),
        query_module._readonly_connection_scope(path),
    ):
        assert _read(path)[0]["close"] == 102.0
        raise RuntimeError("paper failed")

    assert len(opened) == len(closed) == 1
    assert _read(path)[0]["close"] == 102.0
    assert len(opened) == len(closed) == 2


def test_scopes_keep_other_databases_independent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first = _database(tmp_path, "first.sqlite", 101.0)
    second = _database(tmp_path, "second.sqlite", 202.0)
    opened, closed = _track_connections(monkeypatch)

    with query_module._readonly_connection_scope(first):
        with query_module._readonly_connection_scope(second):
            assert _read(first)[0]["close"] == 101.0
            assert _read(second)[0]["close"] == 202.0
            assert len(opened) == 2
            assert not closed
        assert [item.path for item in closed] == [second.resolve()]
        assert _read(first)[0]["close"] == 101.0

    assert {item.path for item in opened} == {first.resolve(), second.resolve()}
    assert len(opened) == len(closed) == 2


def test_same_path_scope_is_isolated_per_thread(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = _database(tmp_path, "threads.sqlite", 303.0)
    opened, closed = _track_connections(monkeypatch)

    def read_in_other_thread() -> float:
        with query_module._readonly_connection_scope(path):
            return float(_read(path)[0]["close"])

    with query_module._readonly_connection_scope(path):
        assert _read(path)[0]["close"] == 303.0
        with ThreadPoolExecutor(max_workers=1) as executor:
            assert executor.submit(read_in_other_thread).result() == 303.0
        assert len(opened) == len(closed) + 1 == 2

    assert len(opened) == len(closed) == 2
    assert len({item.thread_id for item in opened}) == 2
