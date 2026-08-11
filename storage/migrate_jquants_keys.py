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

from data_contracts.identity import natural_key
from data_contracts.loader import all_contracts

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
);

CREATE TABLE IF NOT EXISTS jquants_contract_key_migrations (
    migration_id TEXT PRIMARY KEY,
    migrated_at  TEXT NOT NULL,
    rows_rekeyed INTEGER NOT NULL
);
"""

CONTRACT_V2_MIGRATION_ID = "jquants_premium_core:natural_keys:v2"
_PREMIUM_CORE = tuple(contract.dataset_id for contract in all_contracts())
_GENERIC_COLUMNS = (
    "source",
    "dataset",
    "natural_key",
    "event_time",
    "available_at",
    "ingested_at",
    "payload",
    "raw_payload",
)


def ensure_migration_table(conn: sqlite3.Connection) -> None:
    """Create the one-shot migration marker table if absent (idempotent)."""
    conn.executescript(_MIGRATION_TABLE_SQL)
    conn.commit()


def _decoded_payload(row: dict) -> dict | None:
    import json

    for column in ("payload", "raw_payload"):
        value = row.get(column)
        if not isinstance(value, str) or not value:
            continue
        try:
            decoded = json.loads(value)
        except (TypeError, ValueError):
            continue
        if isinstance(decoded, dict):
            return decoded
    return None


def _version_order(row: dict) -> tuple[str, str]:
    return str(row.get("available_at") or ""), str(row.get("ingested_at") or "")


def migrate_contract_keys_v2(conn: sqlite3.Connection, *, now_iso: str) -> int:
    """Re-key Premium-core primary and revision rows from their payloads.

    The migration is one-shot and transactional.  It rebuilds only the 23
    contract-owned datasets, coalesces duplicate primary identities created by
    historical spaced/compact JSON variants, and moves displaced primary rows
    into revision history.  Revision identity includes ``ingested_at`` (F0-F).
    Rows with an unreadable payload retain their legacy key rather than being
    deleted.
    """
    marked = conn.execute(
        "SELECT 1 FROM jquants_contract_key_migrations WHERE migration_id = ?",
        (CONTRACT_V2_MIGRATION_ID,),
    ).fetchone()
    if marked:
        return 0

    placeholders = ",".join("?" for _ in _PREMIUM_CORE)
    primary_rows = [
        dict(zip(("rowid", *_GENERIC_COLUMNS), row))
        for row in conn.execute(
            f"SELECT rowid,{','.join(_GENERIC_COLUMNS)} FROM jquants_records "
            f"WHERE dataset IN ({placeholders})",
            _PREMIUM_CORE,
        )
    ]
    revision_rows = [
        dict(zip(("rowid", *_GENERIC_COLUMNS), row))
        for row in conn.execute(
            f"SELECT rowid,{','.join(_GENERIC_COLUMNS)} FROM jquants_records_revisions "
            f"WHERE dataset IN ({placeholders})",
            _PREMIUM_CORE,
        )
    ]
    rows_rekeyed = 0
    for row in (*primary_rows, *revision_rows):
        payload = _decoded_payload(row)
        if payload is None:
            continue
        updated = natural_key(payload, row["dataset"])
        if updated != row["natural_key"]:
            rows_rekeyed += 1
            row["natural_key"] = updated

    groups: dict[tuple[str, str, str], list[dict]] = {}
    for row in primary_rows:
        key = (row["source"], row["dataset"], row["natural_key"])
        groups.setdefault(key, []).append(row)

    retained_primary: list[dict] = []
    displaced_primary: list[dict] = []
    for rows in groups.values():
        rows.sort(key=_version_order)
        retained_primary.append(rows[-1])
        displaced_primary.extend(rows[:-1])

    conn.execute(
        f"DELETE FROM jquants_records WHERE dataset IN ({placeholders})",
        _PREMIUM_CORE,
    )
    conn.execute(
        f"DELETE FROM jquants_records_revisions WHERE dataset IN ({placeholders})",
        _PREMIUM_CORE,
    )
    column_sql = ",".join(_GENERIC_COLUMNS)
    value_sql = ",".join("?" for _ in _GENERIC_COLUMNS)
    conn.executemany(
        f"INSERT INTO jquants_records ({column_sql}) VALUES ({value_sql})",
        [tuple(row[column] for column in _GENERIC_COLUMNS) for row in retained_primary],
    )
    all_revisions = revision_rows + displaced_primary
    all_revisions.sort(key=_version_order)
    conn.executemany(
        f"INSERT OR IGNORE INTO jquants_records_revisions ({column_sql}) "
        f"VALUES ({value_sql})",
        [tuple(row[column] for column in _GENERIC_COLUMNS) for row in all_revisions],
    )
    conn.execute(
        "INSERT INTO jquants_contract_key_migrations "
        "(migration_id, migrated_at, rows_rekeyed) VALUES (?, ?, ?)",
        (CONTRACT_V2_MIGRATION_ID, now_iso, rows_rekeyed),
    )
    return rows_rekeyed


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
