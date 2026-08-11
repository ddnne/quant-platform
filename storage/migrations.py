"""Ordered, idempotent migrations for the local SQLite control plane.

``storage.schema.SCHEMA_SQL`` remains the bootstrap definition for the fact
tables.  Additive Phase 6 changes are recorded here so an existing local
database can be upgraded formally instead of relying on scattered
``CREATE TABLE IF NOT EXISTS`` calls.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass


@dataclass(frozen=True)
class Migration:
    version: int
    name: str
    sql: str


MIGRATIONS: tuple[Migration, ...] = (
    Migration(
        1,
        "phase6_sync_and_snapshot_control",
        """
        CREATE TABLE IF NOT EXISTS sync_change_state (
            feed                    TEXT PRIMARY KEY,
            last_applied_change_seq INTEGER NOT NULL DEFAULT 0,
            updated_at              TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS local_snapshot_policy (
            singleton       INTEGER PRIMARY KEY CHECK (singleton = 1),
            require_manifest INTEGER NOT NULL DEFAULT 0,
            snapshot_ready   INTEGER NOT NULL DEFAULT 0,
            sync_started_at  TEXT,
            last_error       TEXT
        );

        CREATE TABLE IF NOT EXISTS local_snapshot_manifests (
            snapshot_id      TEXT PRIMARY KEY,
            format           TEXT NOT NULL,
            committed_at     TEXT NOT NULL,
            source_run_id    INTEGER NOT NULL,
            change_seq       INTEGER NOT NULL,
            manifest_json    TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS ix_local_snapshots_committed
            ON local_snapshot_manifests (committed_at DESC, snapshot_id);
        """,
    ),
    Migration(
        2,
        "revision_identity_includes_ingestion_time",
        """
        DROP INDEX IF EXISTS ux_listed_info_revisions_version;
        CREATE UNIQUE INDEX ux_listed_info_revisions_version
            ON jquants_listed_info_revisions
               (source, code, snapshot_date, available_at, ingested_at);
        DROP INDEX IF EXISTS ux_daily_bars_revisions_version;
        CREATE UNIQUE INDEX ux_daily_bars_revisions_version
            ON jquants_daily_bars_revisions
               (source, code, date, available_at, ingested_at);
        DROP INDEX IF EXISTS ux_market_calendar_revisions_version;
        CREATE UNIQUE INDEX ux_market_calendar_revisions_version
            ON jquants_market_calendar_revisions
               (source, date, available_at, ingested_at);
        DROP INDEX IF EXISTS ux_records_revisions_version;
        CREATE UNIQUE INDEX ux_records_revisions_version
            ON jquants_records_revisions
               (source, dataset, natural_key, available_at, ingested_at);
        DROP INDEX IF EXISTS ux_bond_trades_revisions_version;
        CREATE UNIQUE INDEX ux_bond_trades_revisions_version
            ON jsda_bond_trades_revisions
               (source, trade_date, isin, issuer_name, available_at,
                ingested_at);
        DROP INDEX IF EXISTS ux_repo_rates_revisions_version;
        CREATE UNIQUE INDEX ux_repo_rates_revisions_version
            ON jsda_repo_rates_revisions
               (source, as_of_date, tenor, rate_type, available_at,
                ingested_at);
        """,
    ),
)


def apply_schema_migrations(conn: sqlite3.Connection) -> None:
    """Apply every unapplied local migration in version order.

    Each migration and its ledger insert share one transaction.  Reopening a
    database is therefore cheap and a failed migration is never marked done.
    """
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version    INTEGER PRIMARY KEY,
            name       TEXT NOT NULL UNIQUE,
            applied_at TEXT NOT NULL
                DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
        )
        """
    )
    applied = {
        int(row[0])
        for row in conn.execute("SELECT version FROM schema_migrations")
    }
    for migration in MIGRATIONS:
        if migration.version in applied:
            continue
        quoted_name = "'" + migration.name.replace("'", "''") + "'"
        try:
            conn.executescript(
                "BEGIN IMMEDIATE;\n"
                + migration.sql
                + "\nINSERT INTO schema_migrations (version, name) VALUES ("
                + str(migration.version)
                + ", "
                + quoted_name
                + ");\nCOMMIT;"
            )
        except Exception:
            conn.rollback()
            raise


__all__ = ["MIGRATIONS", "Migration", "apply_schema_migrations"]
