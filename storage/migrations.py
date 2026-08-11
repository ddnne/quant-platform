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
    Migration(
        3,
        "phase6_ready_snapshot_and_coverage_ledger",
        """
        ALTER TABLE local_snapshot_policy
            ADD COLUMN publication_state TEXT NOT NULL DEFAULT 'REJECTED'
            CHECK (publication_state IN
                   ('BUILDING', 'SYNCED', 'VALIDATING', 'READY', 'REJECTED'));
        ALTER TABLE local_snapshot_policy ADD COLUMN active_build_id TEXT;
        ALTER TABLE local_snapshot_policy ADD COLUMN active_snapshot_id TEXT;

        CREATE TABLE IF NOT EXISTS dataset_coverage (
            dataset                         TEXT PRIMARY KEY,
            status                          TEXT NOT NULL CHECK
                (status IN ('COMPLETE', 'PARTIAL', 'STALE', 'UNKNOWN', 'FAILED')),
            policy_version                  TEXT NOT NULL,
            collection_scope                TEXT NOT NULL,
            history_target_start            TEXT NOT NULL,
            history_target_end_rule         TEXT NOT NULL,
            coverage_mode                   TEXT NOT NULL,
            expected_frequency              TEXT NOT NULL,
            universe_rule                   TEXT NOT NULL,
            raw_retention_required          INTEGER NOT NULL CHECK
                (raw_retention_required IN (0, 1)),
            structured_reconciliation_required INTEGER NOT NULL CHECK
                (structured_reconciliation_required IN (0, 1)),
            governance_tier                 TEXT NOT NULL CHECK
                (governance_tier IN ('governed', 'experimental')),
            observed_start                  TEXT,
            observed_end                    TEXT,
            row_count                       INTEGER NOT NULL DEFAULT 0,
            source_run_id                   INTEGER,
            evaluated_at                    TEXT NOT NULL,
            detail_json                     TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS ix_dataset_coverage_status
            ON dataset_coverage (status, governance_tier, dataset);

        CREATE TABLE IF NOT EXISTS snapshot_publications (
            build_id                TEXT PRIMARY KEY,
            snapshot_id             TEXT,
            state                   TEXT NOT NULL CHECK
                (state IN ('BUILDING', 'SYNCED', 'VALIDATING', 'READY', 'REJECTED')),
            staging_path            TEXT NOT NULL,
            artifact_path           TEXT,
            manifest_path           TEXT,
            contract_version        TEXT NOT NULL,
            source_run_id           INTEGER,
            change_seq              INTEGER NOT NULL DEFAULT 0,
            coverage_policy_version TEXT NOT NULL,
            quality_policy_version  TEXT NOT NULL,
            created_at              TEXT NOT NULL,
            committed_at            TEXT,
            rejection_reason        TEXT,
            manifest_json           TEXT
        );
        CREATE INDEX IF NOT EXISTS ix_snapshot_publications_ready
            ON snapshot_publications (state, committed_at DESC, snapshot_id);

        CREATE TABLE IF NOT EXISTS snapshot_quality_results (
            build_id       TEXT PRIMARY KEY,
            status         TEXT NOT NULL CHECK (status IN ('PASS', 'FAIL')),
            policy_version TEXT NOT NULL,
            evaluated_at   TEXT NOT NULL,
            summary_json   TEXT NOT NULL,
            results_json   TEXT NOT NULL
        );

        CREATE TRIGGER IF NOT EXISTS invalidate_snapshot_jquants_listed_info_i
        AFTER INSERT ON jquants_listed_info BEGIN
            UPDATE local_snapshot_policy SET snapshot_ready=0,
                active_snapshot_id=NULL,
                last_error='fact mutation invalidated research snapshot'
            WHERE singleton=1;
        END;
        CREATE TRIGGER IF NOT EXISTS invalidate_snapshot_jquants_listed_info_u
        AFTER UPDATE ON jquants_listed_info BEGIN
            UPDATE local_snapshot_policy SET snapshot_ready=0,
                active_snapshot_id=NULL,
                last_error='fact mutation invalidated research snapshot'
            WHERE singleton=1;
        END;
        CREATE TRIGGER IF NOT EXISTS invalidate_snapshot_jquants_listed_info_d
        AFTER DELETE ON jquants_listed_info BEGIN
            UPDATE local_snapshot_policy SET snapshot_ready=0,
                active_snapshot_id=NULL,
                last_error='fact mutation invalidated research snapshot'
            WHERE singleton=1;
        END;

        CREATE TRIGGER IF NOT EXISTS invalidate_snapshot_jquants_daily_bars_i
        AFTER INSERT ON jquants_daily_bars BEGIN
            UPDATE local_snapshot_policy SET snapshot_ready=0,
                active_snapshot_id=NULL,
                last_error='fact mutation invalidated research snapshot'
            WHERE singleton=1;
        END;
        CREATE TRIGGER IF NOT EXISTS invalidate_snapshot_jquants_daily_bars_u
        AFTER UPDATE ON jquants_daily_bars BEGIN
            UPDATE local_snapshot_policy SET snapshot_ready=0,
                active_snapshot_id=NULL,
                last_error='fact mutation invalidated research snapshot'
            WHERE singleton=1;
        END;
        CREATE TRIGGER IF NOT EXISTS invalidate_snapshot_jquants_daily_bars_d
        AFTER DELETE ON jquants_daily_bars BEGIN
            UPDATE local_snapshot_policy SET snapshot_ready=0,
                active_snapshot_id=NULL,
                last_error='fact mutation invalidated research snapshot'
            WHERE singleton=1;
        END;

        CREATE TRIGGER IF NOT EXISTS invalidate_snapshot_jquants_market_calendar_i
        AFTER INSERT ON jquants_market_calendar BEGIN
            UPDATE local_snapshot_policy SET snapshot_ready=0,
                active_snapshot_id=NULL,
                last_error='fact mutation invalidated research snapshot'
            WHERE singleton=1;
        END;
        CREATE TRIGGER IF NOT EXISTS invalidate_snapshot_jquants_market_calendar_u
        AFTER UPDATE ON jquants_market_calendar BEGIN
            UPDATE local_snapshot_policy SET snapshot_ready=0,
                active_snapshot_id=NULL,
                last_error='fact mutation invalidated research snapshot'
            WHERE singleton=1;
        END;
        CREATE TRIGGER IF NOT EXISTS invalidate_snapshot_jquants_market_calendar_d
        AFTER DELETE ON jquants_market_calendar BEGIN
            UPDATE local_snapshot_policy SET snapshot_ready=0,
                active_snapshot_id=NULL,
                last_error='fact mutation invalidated research snapshot'
            WHERE singleton=1;
        END;

        CREATE TRIGGER IF NOT EXISTS invalidate_snapshot_jquants_records_i
        AFTER INSERT ON jquants_records BEGIN
            UPDATE local_snapshot_policy SET snapshot_ready=0,
                active_snapshot_id=NULL,
                last_error='fact mutation invalidated research snapshot'
            WHERE singleton=1;
        END;
        CREATE TRIGGER IF NOT EXISTS invalidate_snapshot_jquants_records_u
        AFTER UPDATE ON jquants_records BEGIN
            UPDATE local_snapshot_policy SET snapshot_ready=0,
                active_snapshot_id=NULL,
                last_error='fact mutation invalidated research snapshot'
            WHERE singleton=1;
        END;
        CREATE TRIGGER IF NOT EXISTS invalidate_snapshot_jquants_records_d
        AFTER DELETE ON jquants_records BEGIN
            UPDATE local_snapshot_policy SET snapshot_ready=0,
                active_snapshot_id=NULL,
                last_error='fact mutation invalidated research snapshot'
            WHERE singleton=1;
        END;

        CREATE TRIGGER IF NOT EXISTS invalidate_snapshot_jsda_bond_trades_i
        AFTER INSERT ON jsda_bond_trades BEGIN
            UPDATE local_snapshot_policy SET snapshot_ready=0,
                active_snapshot_id=NULL,
                last_error='fact mutation invalidated research snapshot'
            WHERE singleton=1;
        END;
        CREATE TRIGGER IF NOT EXISTS invalidate_snapshot_jsda_bond_trades_u
        AFTER UPDATE ON jsda_bond_trades BEGIN
            UPDATE local_snapshot_policy SET snapshot_ready=0,
                active_snapshot_id=NULL,
                last_error='fact mutation invalidated research snapshot'
            WHERE singleton=1;
        END;
        CREATE TRIGGER IF NOT EXISTS invalidate_snapshot_jsda_bond_trades_d
        AFTER DELETE ON jsda_bond_trades BEGIN
            UPDATE local_snapshot_policy SET snapshot_ready=0,
                active_snapshot_id=NULL,
                last_error='fact mutation invalidated research snapshot'
            WHERE singleton=1;
        END;

        CREATE TRIGGER IF NOT EXISTS invalidate_snapshot_jsda_repo_rates_i
        AFTER INSERT ON jsda_repo_rates BEGIN
            UPDATE local_snapshot_policy SET snapshot_ready=0,
                active_snapshot_id=NULL,
                last_error='fact mutation invalidated research snapshot'
            WHERE singleton=1;
        END;
        CREATE TRIGGER IF NOT EXISTS invalidate_snapshot_jsda_repo_rates_u
        AFTER UPDATE ON jsda_repo_rates BEGIN
            UPDATE local_snapshot_policy SET snapshot_ready=0,
                active_snapshot_id=NULL,
                last_error='fact mutation invalidated research snapshot'
            WHERE singleton=1;
        END;
        CREATE TRIGGER IF NOT EXISTS invalidate_snapshot_jsda_repo_rates_d
        AFTER DELETE ON jsda_repo_rates BEGIN
            UPDATE local_snapshot_policy SET snapshot_ready=0,
                active_snapshot_id=NULL,
                last_error='fact mutation invalidated research snapshot'
            WHERE singleton=1;
        END;

        CREATE TRIGGER IF NOT EXISTS invalidate_snapshot_jquants_listed_info_revisions_i
        AFTER INSERT ON jquants_listed_info_revisions BEGIN
            UPDATE local_snapshot_policy SET snapshot_ready=0,
                active_snapshot_id=NULL,
                last_error='fact mutation invalidated research snapshot'
            WHERE singleton=1;
        END;
        CREATE TRIGGER IF NOT EXISTS invalidate_snapshot_jquants_listed_info_revisions_u
        AFTER UPDATE ON jquants_listed_info_revisions BEGIN
            UPDATE local_snapshot_policy SET snapshot_ready=0,
                active_snapshot_id=NULL,
                last_error='fact mutation invalidated research snapshot'
            WHERE singleton=1;
        END;
        CREATE TRIGGER IF NOT EXISTS invalidate_snapshot_jquants_listed_info_revisions_d
        AFTER DELETE ON jquants_listed_info_revisions BEGIN
            UPDATE local_snapshot_policy SET snapshot_ready=0,
                active_snapshot_id=NULL,
                last_error='fact mutation invalidated research snapshot'
            WHERE singleton=1;
        END;

        CREATE TRIGGER IF NOT EXISTS invalidate_snapshot_jquants_daily_bars_revisions_i
        AFTER INSERT ON jquants_daily_bars_revisions BEGIN
            UPDATE local_snapshot_policy SET snapshot_ready=0,
                active_snapshot_id=NULL,
                last_error='fact mutation invalidated research snapshot'
            WHERE singleton=1;
        END;
        CREATE TRIGGER IF NOT EXISTS invalidate_snapshot_jquants_daily_bars_revisions_u
        AFTER UPDATE ON jquants_daily_bars_revisions BEGIN
            UPDATE local_snapshot_policy SET snapshot_ready=0,
                active_snapshot_id=NULL,
                last_error='fact mutation invalidated research snapshot'
            WHERE singleton=1;
        END;
        CREATE TRIGGER IF NOT EXISTS invalidate_snapshot_jquants_daily_bars_revisions_d
        AFTER DELETE ON jquants_daily_bars_revisions BEGIN
            UPDATE local_snapshot_policy SET snapshot_ready=0,
                active_snapshot_id=NULL,
                last_error='fact mutation invalidated research snapshot'
            WHERE singleton=1;
        END;

        CREATE TRIGGER IF NOT EXISTS invalidate_snapshot_jquants_market_calendar_revisions_i
        AFTER INSERT ON jquants_market_calendar_revisions BEGIN
            UPDATE local_snapshot_policy SET snapshot_ready=0,
                active_snapshot_id=NULL,
                last_error='fact mutation invalidated research snapshot'
            WHERE singleton=1;
        END;
        CREATE TRIGGER IF NOT EXISTS invalidate_snapshot_jquants_market_calendar_revisions_u
        AFTER UPDATE ON jquants_market_calendar_revisions BEGIN
            UPDATE local_snapshot_policy SET snapshot_ready=0,
                active_snapshot_id=NULL,
                last_error='fact mutation invalidated research snapshot'
            WHERE singleton=1;
        END;
        CREATE TRIGGER IF NOT EXISTS invalidate_snapshot_jquants_market_calendar_revisions_d
        AFTER DELETE ON jquants_market_calendar_revisions BEGIN
            UPDATE local_snapshot_policy SET snapshot_ready=0,
                active_snapshot_id=NULL,
                last_error='fact mutation invalidated research snapshot'
            WHERE singleton=1;
        END;

        CREATE TRIGGER IF NOT EXISTS invalidate_snapshot_jquants_records_revisions_i
        AFTER INSERT ON jquants_records_revisions BEGIN
            UPDATE local_snapshot_policy SET snapshot_ready=0,
                active_snapshot_id=NULL,
                last_error='fact mutation invalidated research snapshot'
            WHERE singleton=1;
        END;
        CREATE TRIGGER IF NOT EXISTS invalidate_snapshot_jquants_records_revisions_u
        AFTER UPDATE ON jquants_records_revisions BEGIN
            UPDATE local_snapshot_policy SET snapshot_ready=0,
                active_snapshot_id=NULL,
                last_error='fact mutation invalidated research snapshot'
            WHERE singleton=1;
        END;
        CREATE TRIGGER IF NOT EXISTS invalidate_snapshot_jquants_records_revisions_d
        AFTER DELETE ON jquants_records_revisions BEGIN
            UPDATE local_snapshot_policy SET snapshot_ready=0,
                active_snapshot_id=NULL,
                last_error='fact mutation invalidated research snapshot'
            WHERE singleton=1;
        END;

        CREATE TRIGGER IF NOT EXISTS invalidate_snapshot_jsda_bond_trades_revisions_i
        AFTER INSERT ON jsda_bond_trades_revisions BEGIN
            UPDATE local_snapshot_policy SET snapshot_ready=0,
                active_snapshot_id=NULL,
                last_error='fact mutation invalidated research snapshot'
            WHERE singleton=1;
        END;
        CREATE TRIGGER IF NOT EXISTS invalidate_snapshot_jsda_bond_trades_revisions_u
        AFTER UPDATE ON jsda_bond_trades_revisions BEGIN
            UPDATE local_snapshot_policy SET snapshot_ready=0,
                active_snapshot_id=NULL,
                last_error='fact mutation invalidated research snapshot'
            WHERE singleton=1;
        END;
        CREATE TRIGGER IF NOT EXISTS invalidate_snapshot_jsda_bond_trades_revisions_d
        AFTER DELETE ON jsda_bond_trades_revisions BEGIN
            UPDATE local_snapshot_policy SET snapshot_ready=0,
                active_snapshot_id=NULL,
                last_error='fact mutation invalidated research snapshot'
            WHERE singleton=1;
        END;

        CREATE TRIGGER IF NOT EXISTS invalidate_snapshot_jsda_repo_rates_revisions_i
        AFTER INSERT ON jsda_repo_rates_revisions BEGIN
            UPDATE local_snapshot_policy SET snapshot_ready=0,
                active_snapshot_id=NULL,
                last_error='fact mutation invalidated research snapshot'
            WHERE singleton=1;
        END;
        CREATE TRIGGER IF NOT EXISTS invalidate_snapshot_jsda_repo_rates_revisions_u
        AFTER UPDATE ON jsda_repo_rates_revisions BEGIN
            UPDATE local_snapshot_policy SET snapshot_ready=0,
                active_snapshot_id=NULL,
                last_error='fact mutation invalidated research snapshot'
            WHERE singleton=1;
        END;
        CREATE TRIGGER IF NOT EXISTS invalidate_snapshot_jsda_repo_rates_revisions_d
        AFTER DELETE ON jsda_repo_rates_revisions BEGIN
            UPDATE local_snapshot_policy SET snapshot_ready=0,
                active_snapshot_id=NULL,
                last_error='fact mutation invalidated research snapshot'
            WHERE singleton=1;
        END;
        """,
    ),
    Migration(
        4,
        "phase6_raw_retention_attestations",
        """
        CREATE TABLE IF NOT EXISTS raw_retention_manifests (
            dataset      TEXT NOT NULL,
            run_id       INTEGER NOT NULL,
            manifest_key TEXT NOT NULL,
            page_count   INTEGER NOT NULL CHECK (page_count >= 0),
            row_count    INTEGER NOT NULL CHECK (row_count >= 0),
            raw_bytes    INTEGER NOT NULL CHECK (raw_bytes >= 0),
            data_digest  TEXT NOT NULL,
            completeness TEXT NOT NULL CHECK
                (completeness IN ('COMPLETE', 'FAILED')),
            created_at   TEXT NOT NULL,
            PRIMARY KEY (dataset, run_id)
        );
        CREATE INDEX IF NOT EXISTS ix_raw_retention_run_complete
            ON raw_retention_manifests (run_id, completeness, dataset);
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
