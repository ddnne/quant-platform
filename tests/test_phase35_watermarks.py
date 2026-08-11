"""Phase 3.5 P0-3 — watermarks + incremental sync scaffolding.

Two layers:

* the D1-side migration ``0002_watermarks.sql`` is exercised against a real
  in-memory SQLite (D1 is SQLite-shaped), so we lock in the table shape, the
  upsert idempotency, and the ``COALESCE`` semantics that protect
  ``last_event_date`` from being overwritten by an empty batch.
* the local sync-side incremental logic is exercised with a stubbed HTTP
  client (no network) to confirm the ``since`` filter is applied after page
  fetch and that a single shared client is reused.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest

_REPO = Path(__file__).resolve().parents[1]
_MIGRATION = (
    _REPO
    / "platform"
    / "workers"
    / "ingestion-premium"
    / "migrations"
    / "0002_watermarks.sql"
)


# ---------------------------------------------------------------------------
# D1-side: 0002_watermarks.sql
# ---------------------------------------------------------------------------


def _apply_migration(conn: sqlite3.Connection) -> None:
    """Run 0002 in isolation — the Worker deploy applies it via wrangler."""
    sql = _MIGRATION.read_text()
    conn.executescript(sql)


def _apply_0001_then_0002(conn: sqlite3.Connection) -> None:
    """Mirror a fresh D1 deploy: 0001 first (creates ingestion_validation
    etc.), then 0002 (adds watermarks)."""
    init = (
        _REPO
        / "platform"
        / "workers"
        / "ingestion-premium"
        / "migrations"
        / "0001_init.sql"
    ).read_text()
    conn.executescript(init)
    conn.executescript(_MIGRATION.read_text())


def test_migration_file_exists():
    assert _MIGRATION.exists(), "0002_watermarks.sql should exist"
    sql = _MIGRATION.read_text()
    # Surface the table + index in the doc / regression.
    assert "CREATE TABLE IF NOT EXISTS ingestion_watermarks" in sql
    assert "CREATE INDEX IF NOT EXISTS ix_watermarks_last_ingested_at" in sql


def test_migration_creates_expected_schema_in_memory():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    _apply_migration(conn)
    cols = {
        r["name"]: r["type"]
        for r in conn.execute("PRAGMA table_info(ingestion_watermarks)")
    }
    assert cols["dataset"] == "TEXT"
    assert cols["last_event_date"] == "TEXT"
    assert cols["last_ingested_at"] == "TEXT"
    assert cols["last_export_cursor"] == "INTEGER"

    pk = conn.execute(
        "SELECT name FROM pragma_table_info('ingestion_watermarks') "
        "WHERE pk > 0 ORDER BY pk"
    ).fetchall()
    assert [row["name"] for row in pk] == ["dataset"]


def test_migration_is_idempotent():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    _apply_migration(conn)
    # Second apply must not raise — every CREATE has IF NOT EXISTS.
    _apply_migration(conn)
    cols = {
        r["name"]
        for r in conn.execute("PRAGMA table_info(ingestion_watermarks)")
    }
    assert {
        "dataset", "last_event_date", "last_ingested_at", "last_export_cursor"
    } <= cols


def test_migration_runs_after_0001_cleanly():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    _apply_0001_then_0002(conn)
    # Both schemas coexist.
    tables = {
        r["name"]
        for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
    }
    assert "ingestion_watermarks" in tables
    assert "jquants_records" in tables
    assert "ingestion_validation" in tables


# The exact UPSERT the Worker issues (mirror of upsertWatermark in index.ts).
_WATERMARK_UPSERT_SQL = (
    "INSERT INTO ingestion_watermarks "
    "  (dataset, last_event_date, last_ingested_at, last_export_cursor) "
    "VALUES (?, ?, ?, NULL) "
    "ON CONFLICT(dataset) DO UPDATE SET "
    "  last_event_date  = COALESCE("
    "      excluded.last_event_date, ingestion_watermarks.last_event_date), "
    "  last_ingested_at = excluded.last_ingested_at"
)


def _upsert_watermark(
    conn: sqlite3.Connection,
    dataset: str,
    last_event_date: str | None,
    last_ingested_at: str,
) -> None:
    conn.execute(
        _WATERMARK_UPSERT_SQL, (dataset, last_event_date, last_ingested_at)
    )
    conn.commit()


def test_watermark_upsert_inserts_then_advances():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    _apply_migration(conn)

    _upsert_watermark(conn, "equities_bars_daily", "2025-04-01", "2025-04-01T10:00:00+09:00")
    row = conn.execute(
        "SELECT * FROM ingestion_watermarks WHERE dataset = ?",
        ("equities_bars_daily",),
    ).fetchone()
    assert row["last_event_date"] == "2025-04-01"
    assert row["last_ingested_at"] == "2025-04-01T10:00:00+09:00"
    assert row["last_export_cursor"] is None

    _upsert_watermark(conn, "equities_bars_daily", "2025-04-02", "2025-04-02T10:00:00+09:00")
    row = conn.execute(
        "SELECT * FROM ingestion_watermarks WHERE dataset = ?",
        ("equities_bars_daily",),
    ).fetchone()
    assert row["last_event_date"] == "2025-04-02"
    assert row["last_ingested_at"] == "2025-04-02T10:00:00+09:00"


def test_watermark_upsert_preserves_event_date_on_empty_batch():
    """An empty batch arrives with last_event_date=NULL. COALESCE must keep
    the previous known value rather than blanking it — exactly the
    non-regression the Worker code calls out."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    _apply_migration(conn)

    _upsert_watermark(conn, "fins_summary", "2025-03-31", "2025-03-31T09:30:00+09:00")
    _upsert_watermark(conn, "fins_summary", None, "2025-04-01T09:30:00+09:00")
    row = conn.execute(
        "SELECT * FROM ingestion_watermarks WHERE dataset = ?",
        ("fins_summary",),
    ).fetchone()
    assert row["last_event_date"] == "2025-03-31"
    assert row["last_ingested_at"] == "2025-04-01T09:30:00+09:00"


def test_watermark_upsert_is_idempotent_for_same_dataset():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    _apply_migration(conn)
    _upsert_watermark(conn, "markets_calendar", "2025-04-01", "2025-04-01T09:00:00+09:00")
    _upsert_watermark(conn, "markets_calendar", "2025-04-01", "2025-04-01T09:00:00+09:00")
    n = conn.execute(
        "SELECT COUNT(*) AS c FROM ingestion_watermarks WHERE dataset = ?",
        ("markets_calendar",),
    ).fetchone()["c"]
    assert n == 1


# ---------------------------------------------------------------------------
# Local sync-side: incremental filtering + client reuse
# ---------------------------------------------------------------------------


@pytest.fixture
def sync_module():
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "sync_d1_to_sqlite",
        _REPO / "scripts" / "sync_d1_to_sqlite.py",
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _rows(ingested_at: str, n: int = 3, *, date: str = "2025-04-01") -> list[dict]:
    return [
        {
            "source": "jquants",
            "dataset": "equities_bars_daily",
            "natural_key": f'{{"Code":"100{i}","Date":"{date}"}}',
            "event_time": f"{date}T09:00:00+09:00",
            "available_at": ingested_at,
            "ingested_at": ingested_at,
            "payload": "{}",
            "raw_payload": "{}",
        }
        for i in range(n)
    ]


def test_filter_since_drops_rows_at_or_before_watermark(sync_module):
    rows = _rows("2025-04-01T10:00:00+09:00") + _rows("2025-04-02T10:00:00+09:00")
    kept, skipped = sync_module._filter_since(rows, "2025-04-01T10:00:00+09:00")
    assert skipped == 3
    assert len(kept) == 3
    assert all(r["ingested_at"] > "2025-04-01T10:00:00+09:00" for r in kept)


def test_filter_since_is_noop_when_since_empty(sync_module):
    rows = _rows("2025-04-01T10:00:00+09:00")
    kept, skipped = sync_module._filter_since(rows, "")
    assert skipped == 0
    assert kept == rows


def test_derive_since_reads_local_max(tmp_path, sync_module):
    from storage.sqlite_store import SqliteStore

    store = SqliteStore(tmp_path / "t.sqlite")
    store.upsert(
        "jquants_records",
        _rows("2025-04-01T10:00:00+09:00", 1),
    )
    store.upsert(
        "jquants_records",
        _rows("2025-04-02T10:00:00+09:00", 1),
    )
    assert (
        sync_module._derive_since(store, "jquants_records")
        == "2025-04-02T10:00:00+09:00"
    )
    store.close()


def test_derive_since_returns_none_for_empty_table(tmp_path, sync_module):
    from storage.sqlite_store import SqliteStore

    store = SqliteStore(tmp_path / "t.sqlite")
    assert sync_module._derive_since(store, "jquants_records") is None
    store.close()


def test_incremental_skips_already_mirrored_rows(tmp_path, monkeypatch, sync_module):
    """End-to-end: first pull populates the local DB; second pull with
    ``--incremental`` fetches the same pages but registers nothing new."""
    # Fresh local DB seeded with one batch at t0 (codes 1000/1001/1002).
    first_rows = _rows("2025-04-01T10:00:00+09:00", 3, date="2025-04-01")
    # The remote advances: the same 3 old rows + 2 new rows on a different
    # date so they get distinct natural keys and land as new primary rows.
    remote_rows = first_rows + _rows("2025-04-02T10:00:00+09:00", 2, date="2025-04-02")

    calls: list[str] = []
    client_sentinel = object()

    def fake_http_get_json(client, url: str, token: str) -> dict:
        # The same client object must be reused on every call — this proves
        # the single-shared-client refactor and the network mock at once.
        assert client is client_sentinel
        calls.append(url)
        q = parse_qs(urlparse(url).query)
        cursor = int(q.get("cursor", ["0"])[0])
        limit = int(q["limit"][0])
        page = remote_rows[cursor : cursor + limit]
        nxt = cursor + len(page)
        return {
            "table": q["table"][0],
            "rows": page,
            "cursor": cursor,
            "next_cursor": nxt if nxt < len(remote_rows) else None,
            "has_more": nxt < len(remote_rows),
            "limit": limit,
        }

    monkeypatch.setattr(sync_module, "_new_http_client", lambda: client_sentinel)
    monkeypatch.setattr(sync_module, "_http_get_json", fake_http_get_json)

    from storage.sqlite_store import SqliteStore

    db = tmp_path / "incremental.sqlite"
    # Seed: pre-load the old batch so MAX(ingested_at) is t0.
    seed_store = SqliteStore(db)
    seed_store.upsert("jquants_records", first_rows)
    seed_store.close()

    rc = sync_module.main(
        [
            "--db",
            str(db),
            "--url",
            "https://fixture.invalid",
            "--token",
            "fixture-token",
            "--table",
            "jquants_records",
            "--page-limit",
            "10",  # one page covers everything
            "--incremental",
        ]
    )
    assert rc == 0

    # Walked exactly one page (limit > row count) and registered only the 2
    # new rows; the 3 already-mirrored rows were filtered client-side.
    assert len(calls) == 1
    post = SqliteStore(db)
    n_total = post.count("jquants_records")
    # Seed had 3, sync added 2.
    assert n_total == 5
    post.close()


def test_incremental_with_explicit_since_overrides_local_max(
    tmp_path, monkeypatch, sync_module
):
    """--since bypasses _derive_since entirely."""
    rows = _rows("2025-04-01T10:00:00+09:00") + _rows("2025-04-03T10:00:00+09:00")

    def fake_http_get_json(client, url: str, token: str) -> dict:
        q = parse_qs(urlparse(url).query)
        return {
            "table": q["table"][0],
            "rows": rows,
            "cursor": 0,
            "next_cursor": None,
            "has_more": False,
            "limit": int(q["limit"][0]),
        }

    captured_since: list[str | None] = []

    # Wrap the real _filter_since to capture the watermark it received. We
    # do not change behaviour, only assert the override propagated.
    real_filter = sync_module._filter_since

    def wrapped(rows_in, since):
        captured_since.append(since)
        return real_filter(rows_in, since)

    monkeypatch.setattr(sync_module, "_new_http_client", lambda: object())
    monkeypatch.setattr(sync_module, "_http_get_json", fake_http_get_json)
    monkeypatch.setattr(sync_module, "_filter_since", wrapped)

    db = tmp_path / "since.sqlite"
    rc = sync_module.main(
        [
            "--db",
            str(db),
            "--url",
            "https://fixture.invalid",
            "--token",
            "x",
            "--table",
            "jquants_records",
            "--page-limit",
            "5",
            "--incremental",
            "--since",
            "2025-04-02T00:00:00+09:00",
        ]
    )
    assert rc == 0
    assert captured_since == ["2025-04-02T00:00:00+09:00"]


def test_since_requires_incremental(tmp_path, monkeypatch, sync_module):
    """--since without --incremental is rejected before any network call."""
    touched = {"http": False}

    def fake_http_get_json(client, url, token):
        touched["http"] = True
        return {}

    monkeypatch.setattr(sync_module, "_new_http_client", lambda: object())
    monkeypatch.setattr(sync_module, "_http_get_json", fake_http_get_json)

    rc = sync_module.main(
        [
            "--db",
            str(tmp_path / "x.sqlite"),
            "--url",
            "https://fixture.invalid",
            "--token",
            "x",
            "--table",
            "jquants_records",
            "--since",
            "2025-04-01T00:00:00+09:00",
        ]
    )
    assert rc == 2
    assert touched["http"] is False
