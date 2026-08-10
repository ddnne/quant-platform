"""One-shot migration of legacy collapsed natural keys in ``jquants_records``.

Background
----------
The P1 natural-key fix (commit 13c71e7, branch ``phase1/fix-p1-keys``) added
per-observation discriminators to six multi-observation datasets so the generic
upsert stops collapsing every bar / tick / option contract / disclosure of a
day onto the last row written:

    dataset                                legacy key        new key
    ------------------------------------   ---------------   -----------------------------------
    equities_bars_minute                   [Code, Date]      [Code, Date, DateTime, Time]
    equities_trades                        [Code, Date]      [Code, Date, DateTime]
    derivatives_bars_daily_options_225     [Date]            [Date, Code]
    td_list                                [Date] -> hash    [DiscDate, DiscNo]
    td_files                               [Date] -> hash    [DiscDate, DiscNo]
    td_bulk                                [Date] -> hash    [DiscDate, DiscNo]

Rows written BEFORE that fix are stale:

* minute / trade rows collapsed every observation sharing a ``(Code, Date)``
  onto the last one written;
* the Nikkei-225 option chain collapsed to a single row per ``Date``;
* the TDnet datasets' ``["Date"]`` key matched nothing in the payload (which
  exposes ``DiscDate``), so they silently fell back to a per-row SHA-1 hash.

The collapsed observations cannot be reconstructed from what survived, so the
only correct fix is to drop the affected rows and let the next fetch
re-populate them under the new key. Re-fetching under the NEW key would
otherwise INSERT fresh rows alongside the stale legacy ones — the
``natural_key`` JSON differs, so it never conflicts — leaving duplicates.

Strategy (Phase-1 local SQLite)
-------------------------------
A one-shot, idempotent **delete-by-dataset** the first time each affected
dataset is (re)written after the fix, tracked in a small marker table
(:func:`ensure_migration_table`) so it runs exactly once per (database,
dataset). A cheap, lossy re-fetch of one dataset beats a fragile per-row
re-key that still cannot recover the observations the legacy key collapsed
away. Hooked from :meth:`storage.sqlite_store.SqliteStore.upsert`, in the
caller's transaction, so a failed batch rolls the deletion back too.

The marker table is created here (not in :mod:`storage.schema`) on purpose:
it is migration bookkeeping, not part of the core data model, and this module
is the single owner of the legacy-key migration.
"""

from __future__ import annotations

import sqlite3
from typing import Iterable

# Datasets whose natural-key schema changed in the P1 fix (commit 13c71e7).
# A legacy row for any of these carries a ``natural_key`` JSON that the current
# normalizer no longer produces, so a re-fetch would duplicate it. A frozenset
# for O(1) membership checks during upsert.
LEGACY_KEY_DATASETS: frozenset[str] = frozenset(
    {
        "equities_bars_minute",
        "equities_trades",
        "derivatives_bars_daily_options_225",
        "td_list",
        "td_files",
        "td_bulk",
    }
)

# Marker table recording which datasets have already been migrated in this DB.
# ``dataset`` is the ``jquants_records.dataset`` value; ``migrated_at`` is an
# ISO timestamp for auditability. Idempotent DDL, so creating it on every store
# open is free after the first time.
_MIGRATION_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS jquants_key_migrations (
    dataset      TEXT PRIMARY KEY,
    migrated_at  TEXT NOT NULL
)
"""


def ensure_migration_table(conn: sqlite3.Connection) -> None:
    """Create the one-shot migration marker table if absent (idempotent)."""
    conn.executescript(_MIGRATION_TABLE_SQL)
    conn.commit()


def _migrated_datasets(conn: sqlite3.Connection) -> set[str]:
    cur = conn.execute("SELECT dataset FROM jquants_key_migrations")
    return {r[0] for r in cur.fetchall()}


def migrate_before_write(
    conn: sqlite3.Connection,
    datasets: Iterable[str],
    *,
    now_iso: str,
) -> int:
    """One-shot delete-by-dataset for legacy-key datasets about to be (re)written.

    For each ``dataset`` in ``datasets`` whose key schema changed in the P1 fix
    and that has not already been migrated in this DB, delete every existing
    ``jquants_records`` row for that dataset and record the migration. Already-
    migrated or unaffected datasets are skipped, so this is safe to call on
    every upsert and is a no-op once a dataset has been migrated.

    Runs in the caller's transaction (no commit) so a failed batch rolls the
    deletion back too. Returns the number of stale legacy rows deleted (0 when
    there was nothing to migrate).
    """
    # de-dup while preserving order; keep only datasets whose key changed.
    pending = [
        d for d in dict.fromkeys(datasets) if d in LEGACY_KEY_DATASETS
    ]
    if not pending:
        return 0
    todo = [d for d in pending if d not in _migrated_datasets(conn)]
    if not todo:
        return 0
    deleted = 0
    for d in todo:
        cur = conn.execute(
            "DELETE FROM jquants_records WHERE dataset = ?", (d,)
        )
        # DELETE rowcount is -1 on some drivers when unavailable; guard it.
        if cur.rowcount and cur.rowcount > 0:
            deleted += cur.rowcount
        conn.execute(
            "INSERT OR REPLACE INTO jquants_key_migrations "
            "(dataset, migrated_at) VALUES (?, ?)",
            (d, now_iso),
        )
    return deleted
