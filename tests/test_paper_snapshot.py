"""Focused tests for the lightweight paper data snapshot identifier."""

from __future__ import annotations

import os
import re
import sqlite3

import pytest

from paper_runtime import data_snapshot_id
from paper_runtime.snapshot import _immutable_data_snapshot_id


def _create_fallback_db(path) -> None:
    with sqlite3.connect(path) as conn:
        conn.executescript(
            """
            PRAGMA user_version = 5;
            CREATE TABLE facts (
                id INTEGER PRIMARY KEY,
                ingested_at TEXT NOT NULL,
                value REAL
            );
            INSERT INTO facts (id, ingested_at, value)
            VALUES (1, '2025-04-01T15:30:00+09:00', 100.0);
            """
        )


def _create_control_plane_db(path) -> None:
    with sqlite3.connect(path) as conn:
        conn.executescript(
            """
            PRAGMA user_version = 5;
            CREATE TABLE ingestion_watermarks (
                dataset TEXT PRIMARY KEY,
                last_event_date TEXT,
                last_ingested_at TEXT NOT NULL,
                last_export_cursor INTEGER
            );
            CREATE TABLE ingestion_validation (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id INTEGER,
                dataset TEXT NOT NULL,
                started_at TEXT NOT NULL,
                finished_at TEXT NOT NULL,
                status TEXT NOT NULL,
                rows_seen INTEGER NOT NULL DEFAULT 0,
                rows_inserted INTEGER NOT NULL DEFAULT 0,
                rows_revisions INTEGER NOT NULL DEFAULT 0,
                available_at_min TEXT,
                available_at_max TEXT,
                detail TEXT
            );
            CREATE TABLE facts (
                id INTEGER PRIMARY KEY,
                ingested_at TEXT NOT NULL,
                value REAL
            );
            INSERT INTO ingestion_watermarks
                (dataset, last_event_date, last_ingested_at)
            VALUES
                ('equities_bars_daily', '2025-04-01',
                 '2025-04-01T15:30:00+09:00');
            INSERT INTO ingestion_validation
                (run_id, dataset, started_at, finished_at, status,
                 rows_seen, rows_inserted, rows_revisions)
            VALUES
                (1, 'equities_bars_daily',
                 '2025-04-01T15:29:00+09:00',
                 '2025-04-01T15:30:00+09:00', 'pass', 10, 10, 0);
            INSERT INTO facts (id, ingested_at, value)
            VALUES (1, '2025-04-01T15:30:00+09:00', 100.0);
            """
        )


def test_snapshot_is_stable_for_unchanged_fixture_without_control_tables(tmp_path):
    db = tmp_path / "fixture.sqlite"
    _create_fallback_db(db)

    first = data_snapshot_id(db)
    second = data_snapshot_id(db)

    assert first == second
    assert re.fullmatch(r"sha256:[0-9a-f]{64}", first)


def test_snapshot_read_does_not_create_wal_or_shared_memory_sidecars(tmp_path):
    db = tmp_path / "wal-fixture.sqlite"
    with sqlite3.connect(db) as conn:
        assert conn.execute("PRAGMA journal_mode=WAL").fetchone()[0] == "wal"
        conn.execute(
            "CREATE TABLE facts (id INTEGER PRIMARY KEY, ingested_at TEXT)"
        )
        conn.execute(
            "INSERT INTO facts VALUES (1, '2025-04-01T15:30:00+09:00')"
        )
        conn.commit()
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")

    (tmp_path / "wal-fixture.sqlite-wal").unlink(missing_ok=True)
    (tmp_path / "wal-fixture.sqlite-shm").unlink(missing_ok=True)
    _immutable_data_snapshot_id(db)

    assert not (tmp_path / "wal-fixture.sqlite-wal").exists()
    assert not (tmp_path / "wal-fixture.sqlite-shm").exists()


def test_current_snapshot_reads_committed_uncheckpointed_wal(tmp_path):
    db = tmp_path / "mutable-wal.sqlite"
    writer = sqlite3.connect(db)
    try:
        assert writer.execute("PRAGMA journal_mode=WAL").fetchone()[0] == "wal"
        writer.execute("PRAGMA wal_autocheckpoint=0")
        writer.execute(
            "CREATE TABLE facts (id INTEGER PRIMARY KEY, ingested_at TEXT)"
        )
        writer.execute(
            "INSERT INTO facts VALUES (1, '2025-04-01T15:30:00+09:00')"
        )
        writer.commit()
        first = data_snapshot_id(db)

        writer.execute(
            "INSERT INTO facts VALUES (2, '2025-04-02T15:30:00+09:00')"
        )
        writer.commit()

        assert data_snapshot_id(db) != first
    finally:
        writer.close()


def test_fallback_snapshot_changes_when_fact_state_changes(tmp_path):
    db = tmp_path / "fixture.sqlite"
    _create_fallback_db(db)
    before = data_snapshot_id(db)

    with sqlite3.connect(db) as conn:
        conn.execute(
            "INSERT INTO facts (id, ingested_at, value) VALUES (?, ?, ?)",
            (2, "2025-04-02T15:30:00+09:00", 101.0),
        )

    assert data_snapshot_id(db) != before


def test_control_plane_changes_snapshot_but_file_touch_does_not(tmp_path):
    db = tmp_path / "controlled.sqlite"
    _create_control_plane_db(db)
    original = data_snapshot_id(db)

    stat = db.stat()
    os.utime(db, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000))
    assert data_snapshot_id(db) == original

    with sqlite3.connect(db) as conn:
        conn.execute(
            "UPDATE ingestion_watermarks SET "
            "last_event_date = ?, last_ingested_at = ? WHERE dataset = ?",
            (
                "2025-04-02",
                "2025-04-02T15:30:00+09:00",
                "equities_bars_daily",
            ),
        )
    advanced = data_snapshot_id(db)
    assert advanced != original

    with sqlite3.connect(db) as conn:
        conn.execute(
            "INSERT INTO ingestion_validation "
            "(run_id, dataset, started_at, finished_at, status, rows_seen, "
            " rows_inserted, rows_revisions) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                2,
                "equities_bars_daily",
                "2025-04-02T15:29:00+09:00",
                "2025-04-02T15:30:00+09:00",
                "pass",
                11,
                1,
                0,
            ),
        )
    assert data_snapshot_id(db) != advanced


def test_snapshot_rejects_missing_database(tmp_path):
    with pytest.raises(FileNotFoundError, match="paper database does not exist"):
        data_snapshot_id(tmp_path / "missing.sqlite")
