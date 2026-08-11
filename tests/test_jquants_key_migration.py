"""One-shot migration of legacy collapsed natural keys in ``jquants_records``.

The P1 natural-key fix (commit 13c71e7) widened the key of six multi-observation
datasets so upsert stops collapsing every bar / tick / option contract /
disclosure of a day onto the last row written. Rows a DB collected BEFORE that
fix carry the OLD collapsed key JSON, which the current normalizer no longer
produces — so a post-fix re-fetch would INSERT fresh-key rows alongside the
stale ones instead of matching them, leaving duplicates.

These tests seed a DB with pre-fix-shaped rows (direct INSERT, simulating an
older binary) and assert the store's one-shot ``delete-by-dataset`` migration
clears exactly the affected datasets the first time they are re-written, that
it runs once per (database, dataset), leaves unaffected datasets alone, and
that the delete is atomic with the write (a failed batch rolls it back).
"""

from __future__ import annotations

import json
import sqlite3

import pytest

from ingestion.jquants.normalize import normalize_generic
from storage.migrate_jquants_keys import (
    LEGACY_KEY_DATASETS,
    ensure_migration_table,
    migrate_before_write,
)
from storage.schema import SCHEMA_SQL
from storage.sqlite_store import MissingAvailableAt, SqliteStore

ING = "2025-04-02T09:00:00+09:00"
ET = "2025-04-01T15:00:00+09:00"

# Legacy natural-key JSON shapes the pre-fix normalizer produced. ``json.dumps``
# with ``sort_keys=True`` (what the normalizer emits) inserts a space after each
# ``:`` and ``,`` — these literals mirror that exactly.
LEGACY_MINUTE_KEY = json.dumps({"Code": "8697", "Date": "2025-04-01"}, sort_keys=True)
LEGACY_TD_HASH = json.dumps({"_hash": "deadbeefcafebabe"}, sort_keys=True)
LEGACY_OPTIONS_KEY = json.dumps({"Date": "2025-04-01"}, sort_keys=True)
CANONICAL_DAILY_KEY = json.dumps(
    {"Code": "8697", "Date": "2025-04-01"},
    sort_keys=True,
    separators=(",", ":"),
)


def _seed_legacy(path, rows) -> None:
    """Insert pre-fix ``jquants_records`` rows directly (simulating an old
    binary that wrote collapsed keys). Requires the table to already exist."""
    conn = sqlite3.connect(str(path))
    conn.executemany(
        "INSERT INTO jquants_records "
        "(source, dataset, natural_key, event_time, available_at, "
        "ingested_at, payload, raw_payload) VALUES (?,?,?,?,?,?,?,?)",
        rows,
    )
    conn.commit()
    conn.close()


# --------------------------------------------------------------------------- scenarios


def test_legacy_minute_collapsed_row_deleted_on_new_write(tmp_path):
    """Pre-fix run collapsed every minute of (Code, Date) onto one legacy row;
    post-fix re-fetch must delete it and keep one row per minute."""
    db = tmp_path / "ing.sqlite"
    SqliteStore(db).close()  # create schema + marker table
    _seed_legacy(
        db,
        [("jquants", "equities_bars_minute", LEGACY_MINUTE_KEY, ET, ING, ING, "{}", "{}")],
    )

    rows = [
        {"Code": "8697", "Date": "2025-04-01",
         "DateTime": "2025-04-01T09:00:00+09:00", "C": 100},
        {"Code": "8697", "Date": "2025-04-01",
         "DateTime": "2025-04-01T09:01:00+09:00", "C": 101},
    ]
    norm = normalize_generic(rows, dataset="equities_bars_minute", ingested_at=ING)
    s = SqliteStore(db)
    assert s.upsert("jquants_records", norm) == 2

    stored = s.fetch_all("jquants_records")
    assert len(stored) == 2  # legacy collapsed row gone — no duplicate
    keys = {r["natural_key"] for r in stored}
    assert LEGACY_MINUTE_KEY not in keys
    s.close()


def test_legacy_tdnet_hash_key_deleted(tmp_path):
    """TDnet ``["Date"]`` matched nothing pre-fix -> rows fell back to a row
    hash; re-fetch under ``DiscDate + DiscNo`` must clear the hash rows."""
    db = tmp_path / "ing.sqlite"
    SqliteStore(db).close()
    _seed_legacy(
        db, [("jquants", "td_list", LEGACY_TD_HASH, ET, ING, ING, "{}", "{}")]
    )

    rows = [
        {"DiscDate": "2025-04-01", "DiscNo": "20250401000001", "Code": "8697"},
        {"DiscDate": "2025-04-01", "DiscNo": "20250401000002", "Code": "8697"},
    ]
    norm = normalize_generic(rows, dataset="td_list", ingested_at=ING)
    s = SqliteStore(db)
    s.upsert("jquants_records", norm)

    keys = {r["natural_key"] for r in s.fetch_all("jquants_records")}
    assert LEGACY_TD_HASH not in keys
    assert s.count("jquants_records") == 2
    s.close()


def test_legacy_options_date_only_key_deleted(tmp_path):
    """The Nikkei-225 option chain collapsed to one legacy row per ``Date``;
    re-fetch under ``Date + Code`` must clear it and keep one row per contract."""
    db = tmp_path / "ing.sqlite"
    SqliteStore(db).close()
    _seed_legacy(
        db,
        [("jquants", "derivatives_bars_daily_options_225",
          LEGACY_OPTIONS_KEY, ET, ING, ING, "{}", "{}")],
    )

    rows = [
        {"Date": "2025-04-01", "Code": "180000018", "C": 50},
        {"Date": "2025-04-01", "Code": "180000026", "C": 51},
    ]
    norm = normalize_generic(
        rows, dataset="derivatives_bars_daily_options_225", ingested_at=ING
    )
    s = SqliteStore(db)
    s.upsert("jquants_records", norm)

    keys = {r["natural_key"] for r in s.fetch_all("jquants_records")}
    assert LEGACY_OPTIONS_KEY not in keys
    assert s.count("jquants_records") == 2
    s.close()


def test_non_legacy_dataset_is_neither_deleted_nor_marked(tmp_path):
    """Datasets whose key did NOT change (e.g. ``equities_bars_daily``) are
    untouched by the migration and never recorded in the marker table."""
    db = tmp_path / "ing.sqlite"
    s = SqliteStore(db)
    rows = [{"Code": "8697", "Date": "2025-04-01", "Close": 100}]
    norm = normalize_generic(rows, dataset="equities_bars_daily", ingested_at=ING)
    assert s.upsert("jquants_records", norm) == 1
    s.upsert("jquants_records", norm)  # idempotent re-upsert
    assert s.count("jquants_records") == 1
    assert s.fetch_all("jquants_key_migrations") == []
    s.close()


def test_migration_runs_once_per_dataset_across_reopen(tmp_path):
    """The marker makes the delete one-shot: a second post-fix run in a fresh
    store must NOT wipe the new-key rows written by the first."""
    db = tmp_path / "ing.sqlite"
    SqliteStore(db).close()
    _seed_legacy(
        db, [("jquants", "equities_bars_minute", LEGACY_MINUTE_KEY, ET, ING, ING, "{}", "{}")]
    )

    norm = normalize_generic(
        [{"Code": "8697", "Date": "2025-04-01",
          "DateTime": "2025-04-01T09:00:00+09:00", "C": 100}],
        dataset="equities_bars_minute", ingested_at=ING,
    )
    s1 = SqliteStore(db)
    s1.upsert("jquants_records", norm)
    assert s1.count("jquants_records") == 1
    s1.close()

    # Fresh store, same DB: marker present -> the new-key row survives.
    s2 = SqliteStore(db)
    s2.upsert("jquants_records", norm)
    assert s2.count("jquants_records") == 1
    marks = {m["dataset"] for m in s2.fetch_all("jquants_key_migrations")}
    assert marks == {"equities_bars_minute"}
    s2.close()


def test_mixed_batch_migrates_only_legacy_datasets(tmp_path):
    """A batch touching a legacy-changed dataset and an unchanged one migrates
    only the former; the latter relies on normal upsert conflict resolution."""
    db = tmp_path / "ing.sqlite"
    SqliteStore(db).close()
    _seed_legacy(
        db,
        [
            # minute: legacy collapsed key -> will be deleted (key changed).
            ("jquants", "equities_bars_minute", LEGACY_MINUTE_KEY, ET, ING, ING, "{}", "{}"),
            # Daily is outside the P1 delete set and already carries the F0
            # canonical serialization, so ordinary conflict handling applies.
            ("jquants", "equities_bars_daily", CANONICAL_DAILY_KEY, ET, ING, ING, "{}", "{}"),
        ],
    )

    minute = normalize_generic(
        [{"Code": "8697", "Date": "2025-04-01",
          "DateTime": "2025-04-01T09:00:00+09:00", "C": 1}],
        dataset="equities_bars_minute", ingested_at=ING,
    )
    daily = normalize_generic(
        [{"Code": "8697", "Date": "2025-04-01", "Close": 2}],
        dataset="equities_bars_daily", ingested_at=ING,
    )
    s = SqliteStore(db)
    s.upsert("jquants_records", minute + daily)

    # 1 minute (legacy collapsed row deleted) + 1 daily (overwritten in place).
    by_ds: dict[str, list[dict]] = {}
    for r in s.fetch_all("jquants_records"):
        by_ds.setdefault(r["dataset"], []).append(r)
    assert len(by_ds["equities_bars_minute"]) == 1
    # the surviving minute row is the new-key one — it carries the canonical
    # ``Time`` = HH:MM discriminator that makes minute bars unique (the legacy
    # row collapsed every minute of (Code, Date) onto a Date-only key).
    nk = by_ds["equities_bars_minute"][0]["natural_key"]
    assert json.loads(nk)["Time"] == "09:00"  # canonicalized from ``DateTime``
    assert len(by_ds["equities_bars_daily"]) == 1
    # only the key-changed dataset was marked for migration
    marks = {m["dataset"] for m in s.fetch_all("jquants_key_migrations")}
    assert marks == {"equities_bars_minute"}  # daily never marked
    s.close()


def test_migration_rolls_back_with_write_on_failed_batch(tmp_path):
    """The delete runs in the upsert transaction: a row that fails AFTER the
    delete (NOT NULL violation) rolls both the delete and the marker back."""
    db = tmp_path / "ing.sqlite"
    SqliteStore(db).close()
    _seed_legacy(
        db, [("jquants", "equities_bars_minute", LEGACY_MINUTE_KEY, ET, ING, ING, "{}", "{}")]
    )

    good = normalize_generic(
        [{"Code": "8697", "Date": "2025-04-01",
          "DateTime": "2025-04-01T09:00:00+09:00", "C": 1}],
        dataset="equities_bars_minute", ingested_at=ING,
    )[0]
    bad = dict(good)
    bad["natural_key"] = None  # NOT NULL violation, raised after the delete

    s = SqliteStore(db)
    with pytest.raises(sqlite3.IntegrityError):
        s.upsert("jquants_records", [good, bad])

    # Rolled back: legacy row survives and the dataset is NOT marked, so the
    # next (successful) write will migrate it cleanly.
    assert s.count("jquants_records") == 1
    assert {r["natural_key"] for r in s.fetch_all("jquants_records")} == {LEGACY_MINUTE_KEY}
    assert s.fetch_all("jquants_key_migrations") == []
    s.close()


# --------------------------------------------------------------- module unit guards


def test_legacy_dataset_registry_is_the_p1_fix_set():
    """Pin the exact set of datasets whose key schema changed in commit 13c71e7
    so an accidental catalog edit does not silently shrink the migration."""
    assert LEGACY_KEY_DATASETS == frozenset(
        {
            "equities_bars_minute",
            "equities_trades",
            "derivatives_bars_daily_options_225",
            "td_list",
            "td_files",
            "td_bulk",
        }
    )


def test_migrate_before_write_is_noop_for_unaffected_dataset():
    """Datasets outside the legacy set are skipped entirely (no delete, no mark)."""
    conn = sqlite3.connect(":memory:")
    conn.executescript(SCHEMA_SQL)
    ensure_migration_table(conn)
    assert migrate_before_write(conn, ["equities_bars_daily"], now_iso=ING) == 0
    assert conn.execute("SELECT COUNT(*) FROM jquants_key_migrations").fetchone()[0] == 0
    conn.close()


def test_migrate_before_write_is_idempotent():
    """A second call for an already-migrated dataset deletes nothing."""
    conn = sqlite3.connect(":memory:")
    conn.executescript(SCHEMA_SQL)
    ensure_migration_table(conn)
    # first call: nothing to delete but the dataset gets marked
    assert migrate_before_write(conn, ["td_list"], now_iso=ING) == 0
    assert migrate_before_write(conn, ["td_list"], now_iso=ING) == 0  # already marked
    assert conn.execute("SELECT COUNT(*) FROM jquants_key_migrations").fetchone()[0] == 1
    conn.close()
