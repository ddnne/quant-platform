"""Ordered, idempotent migrations for the local SQLite control plane.

``storage.schema.SCHEMA_SQL`` remains the bootstrap fact-table DDL. Additive
Phase 6+ changes live here so existing local databases upgrade formally.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass


@dataclass(frozen=True)
class Migration:
    version: int
    name: str
    sql: str


@dataclass(frozen=True, slots=True)
class SnapshotInvalidationTrigger:
    table: str
    stem: str
    event: str
    suffix: str

    @property
    def name(self) -> str:
        return f"invalidate_snapshot_{self.stem}_{self.suffix}"

    @property
    def migration_sql(self) -> str:
        return f"""
        CREATE TRIGGER IF NOT EXISTS {self.name}
        AFTER {self.event} ON {self.table} BEGIN
            UPDATE local_snapshot_policy SET snapshot_ready=0,
                active_snapshot_id=NULL,
                last_error='fact mutation invalidated research snapshot'
            WHERE singleton=1;
        END;"""

    @property
    def sqlite_master_sql(self) -> str:
        return (
            f"CREATE TRIGGER {self.name} AFTER {self.event} ON {self.table} "
            "BEGIN UPDATE local_snapshot_policy SET snapshot_ready=0, "
            "active_snapshot_id=NULL, "
            "last_error='fact mutation invalidated research snapshot' "
            "WHERE singleton=1; END"
        )


_PHASE6_FACT_TARGETS: tuple[str | tuple[str, str], ...] = (
    "jquants_listed_info",
    "jquants_daily_bars",
    "jquants_market_calendar",
    "jquants_records",
    "jsda_bond_trades",
    "jsda_repo_rates",
    "jquants_listed_info_revisions",
    "jquants_daily_bars_revisions",
    "jquants_market_calendar_revisions",
    "jquants_records_revisions",
    "jsda_bond_trades_revisions",
    "jsda_repo_rates_revisions",
)
_PHASE61_OTC_TARGETS: tuple[str | tuple[str, str], ...] = (
    ("jsda_otc_bond_reference_prices", "jsda_otc_reference"),
    (
        "jsda_otc_bond_reference_prices_revisions",
        "jsda_otc_reference_revisions",
    ),
)
_PHASE62_CORPORATE_TARGETS: tuple[str | tuple[str, str], ...] = (
    ("jsda_corporate_bond_transactions", "jsda_corporate_transactions"),
    (
        "jsda_corporate_bond_transactions_revisions",
        "jsda_corporate_transactions_revisions",
    ),
)


def _trigger_contracts(
    items: tuple[str | tuple[str, str], ...],
) -> tuple[SnapshotInvalidationTrigger, ...]:
    return tuple(
        SnapshotInvalidationTrigger(
            table=table,
            stem=stem,
            event=event,
            suffix=suffix,
        )
        for item in items
        for table, stem in (
            item if isinstance(item, tuple) else (item, item),
        )
        for event, suffix in (("INSERT", "i"), ("UPDATE", "u"), ("DELETE", "d"))
    )


SNAPSHOT_INVALIDATION_TRIGGERS: tuple[SnapshotInvalidationTrigger, ...] = (
    _trigger_contracts(
        _PHASE6_FACT_TARGETS
        + _PHASE61_OTC_TARGETS
        + _PHASE62_CORPORATE_TARGETS
    )
)


def _invalidate_snapshot_triggers(*items: str | tuple[str, str]) -> str:
    """Fact/revision INSERT/UPDATE/DELETE must drop snapshot_ready."""
    return "".join(_trigger.migration_sql for _trigger in _trigger_contracts(items))


_PHASE6_FACT_TRIGGERS = _invalidate_snapshot_triggers(*_PHASE6_FACT_TARGETS)


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
        """
        + _PHASE6_FACT_TRIGGERS,
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
    Migration(
        5,
        "phase61_collection_coverage_v2",
        """
        CREATE TABLE IF NOT EXISTS coverage_segments (
            source          TEXT NOT NULL,
            dataset         TEXT NOT NULL,
            segment_id      TEXT NOT NULL,
            policy_version  TEXT NOT NULL,
            segment_start   TEXT NOT NULL,
            segment_end     TEXT NOT NULL,
            expected_scope  TEXT NOT NULL,
            expected_items  INTEGER CHECK
                (expected_items IS NULL OR expected_items >= 0),
            status          TEXT NOT NULL CHECK
                (status IN ('COMPLETE', 'PARTIAL', 'STALE', 'UNKNOWN', 'FAILED')),
            receipt_run_id  INTEGER,
            evaluated_at    TEXT NOT NULL,
            detail_json     TEXT NOT NULL,
            PRIMARY KEY (source, dataset, segment_id, policy_version),
            CHECK (segment_start <= segment_end)
        );
        CREATE INDEX IF NOT EXISTS ix_coverage_segments_dataset_status
            ON coverage_segments
               (dataset, policy_version, status, segment_start, segment_id);

        CREATE TABLE IF NOT EXISTS collection_receipts (
            source               TEXT NOT NULL,
            dataset              TEXT NOT NULL,
            segment_id           TEXT NOT NULL,
            segment_start        TEXT NOT NULL,
            segment_end          TEXT NOT NULL,
            expected_scope       TEXT NOT NULL,
            expected_items       INTEGER CHECK
                (expected_items IS NULL OR expected_items >= 0),
            observed_items       INTEGER NOT NULL CHECK (observed_items >= 0),
            raw_page_count       INTEGER NOT NULL CHECK (raw_page_count >= 0),
            raw_row_count        INTEGER NOT NULL CHECK (raw_row_count >= 0),
            structured_row_count INTEGER NOT NULL CHECK
                (structured_row_count >= 0),
            pagination_exhausted INTEGER NOT NULL CHECK
                (pagination_exhausted IN (0, 1)),
            digests_json          TEXT NOT NULL,
            run_id                INTEGER NOT NULL,
            status                TEXT NOT NULL CHECK
                (status IN ('SUCCESS', 'FAILED')),
            error                 TEXT,
            checked_at            TEXT NOT NULL,
            PRIMARY KEY (source, dataset, segment_id, run_id),
            CHECK (segment_start <= segment_end)
        );
        CREATE INDEX IF NOT EXISTS ix_collection_receipts_segment_latest
            ON collection_receipts
               (source, dataset, segment_id, segment_start, segment_end,
                checked_at DESC, run_id DESC);
        """,
    ),
    Migration(
        6,
        "phase61_jsda_otc_bond_reference_archive",
        """
        CREATE TABLE IF NOT EXISTS jsda_otc_bond_reference_prices (
            source                   TEXT NOT NULL,
            publication_label_date   TEXT NOT NULL,
            quote_effective_date     TEXT NOT NULL,
            security_code            TEXT NOT NULL DEFAULT '',
            bond_name                TEXT NOT NULL DEFAULT '',
            quote_effective_time     TEXT NOT NULL,
            event_time               TEXT NOT NULL,
            available_at             TEXT NOT NULL,
            ingested_at              TEXT NOT NULL,
            coupon_rate              REAL,
            maturity_date            TEXT,
            average_price            REAL,
            average_yield            REAL,
            median_price             REAL,
            median_yield             REAL,
            high_price               REAL,
            high_yield               REAL,
            low_price                REAL,
            low_yield                REAL,
            individual_investor_flag TEXT,
            source_row_number        INTEGER,
            source_url               TEXT NOT NULL,
            raw_digest               TEXT NOT NULL,
            segment_id               TEXT NOT NULL,
            source_format            TEXT NOT NULL,
            correction_published_at  TEXT,
            raw_payload              TEXT,
            PRIMARY KEY
                (source, publication_label_date, security_code, bond_name)
        );
        CREATE TABLE IF NOT EXISTS jsda_otc_bond_reference_prices_revisions AS
            SELECT * FROM jsda_otc_bond_reference_prices WHERE 0;
        CREATE UNIQUE INDEX IF NOT EXISTS
            ux_otc_bond_reference_revisions_version
            ON jsda_otc_bond_reference_prices_revisions
               (source, publication_label_date, security_code, bond_name,
                available_at, ingested_at);
        CREATE INDEX IF NOT EXISTS ix_jsda_otc_reference_available_at
            ON jsda_otc_bond_reference_prices
               (quote_effective_date, available_at, security_code);
        """
        + _invalidate_snapshot_triggers(*_PHASE61_OTC_TARGETS),
    ),
    Migration(
        7,
        "phase61_jsda_correction_provenance",
        """
        ALTER TABLE jsda_otc_bond_reference_prices
            ADD COLUMN correction_publication_label TEXT;
        ALTER TABLE jsda_otc_bond_reference_prices
            ADD COLUMN correction_source_url TEXT;
        ALTER TABLE jsda_otc_bond_reference_prices
            ADD COLUMN correction_raw_digest TEXT;
        ALTER TABLE jsda_otc_bond_reference_prices_revisions
            ADD COLUMN correction_publication_label TEXT;
        ALTER TABLE jsda_otc_bond_reference_prices_revisions
            ADD COLUMN correction_source_url TEXT;
        ALTER TABLE jsda_otc_bond_reference_prices_revisions
            ADD COLUMN correction_raw_digest TEXT;
        """,
    ),
    Migration(
        8,
        "phase62_jsda_corporate_bond_transactions",
        """
        CREATE TABLE IF NOT EXISTS jsda_corporate_bond_transactions (
            source                       TEXT NOT NULL,
            publication_label_date       TEXT NOT NULL,
            trade_date                   TEXT NOT NULL,
            security_code                TEXT NOT NULL DEFAULT '',
            source_record_id             TEXT NOT NULL DEFAULT '',
            issuer_name                  TEXT NOT NULL DEFAULT '',
            isin                         TEXT NOT NULL DEFAULT '',
            event_time                   TEXT NOT NULL,
            available_at                 TEXT NOT NULL,
            ingested_at                  TEXT NOT NULL,
            coupon_rate                  REAL,
            maturity_date                TEXT,
            transaction_type             TEXT,
            buyer_counterparty_type      TEXT,
            seller_counterparty_type     TEXT,
            face_value_mil_jpy           REAL,
            trade_amount_mil_jpy         REAL,
            execution_price              REAL,
            execution_yield              REAL,
            source_url                   TEXT NOT NULL,
            raw_digest                   TEXT NOT NULL,
            segment_id                   TEXT NOT NULL,
            source_format                TEXT NOT NULL,
            correction_published_at      TEXT,
            correction_publication_label TEXT,
            correction_source_url        TEXT,
            correction_raw_digest        TEXT,
            raw_payload                  TEXT,
            PRIMARY KEY (source, publication_label_date, trade_date,
                         security_code, source_record_id)
        );
        CREATE TABLE IF NOT EXISTS jsda_corporate_bond_transactions_revisions AS
            SELECT * FROM jsda_corporate_bond_transactions WHERE 0;
        CREATE UNIQUE INDEX IF NOT EXISTS
            ux_corporate_bond_transactions_revisions_version
            ON jsda_corporate_bond_transactions_revisions
               (source, publication_label_date, trade_date, security_code,
                source_record_id, available_at, ingested_at);
        CREATE INDEX IF NOT EXISTS ix_jsda_corporate_transactions_available_at
            ON jsda_corporate_bond_transactions
               (trade_date, available_at, security_code);
        """
        + _invalidate_snapshot_triggers(*_PHASE62_CORPORATE_TARGETS),
    ),
    Migration(
        9,
        "phase632_raw_acquisition_status",
        """
        CREATE TABLE raw_retention_manifests__v9 (
            dataset      TEXT NOT NULL,
            run_id       INTEGER NOT NULL,
            manifest_key TEXT NOT NULL,
            page_count   INTEGER NOT NULL CHECK (page_count >= 0),
            row_count    INTEGER NOT NULL CHECK (row_count >= 0),
            raw_bytes    INTEGER NOT NULL CHECK (raw_bytes >= 0),
            data_digest  TEXT NOT NULL,
            completeness TEXT NOT NULL CHECK
                (completeness IN ('ACQUIRED', 'FAILED', 'COMPLETE')),
            created_at   TEXT NOT NULL,
            PRIMARY KEY (dataset, run_id)
        );
        INSERT INTO raw_retention_manifests__v9
            SELECT dataset, run_id, manifest_key, page_count, row_count,
                   raw_bytes, data_digest, completeness, created_at
            FROM raw_retention_manifests;
        DROP TABLE raw_retention_manifests;
        ALTER TABLE raw_retention_manifests__v9
            RENAME TO raw_retention_manifests;
        CREATE INDEX IF NOT EXISTS ix_raw_retention_run_complete
            ON raw_retention_manifests (run_id, completeness, dataset);
        """,
    ),
    Migration(
        10,
        "phase633_immutable_local_coverage_proofs",
        """
        CREATE TABLE IF NOT EXISTS local_coverage_proofs (
            proof_id                 TEXT PRIMARY KEY CHECK
                (length(proof_id) = 71 AND
                 substr(proof_id, 1, 7) = 'sha256:' AND
                 substr(proof_id, 8) NOT GLOB '*[^0-9a-f]*'),
            format                   TEXT NOT NULL CHECK
                (format = 'local-coverage-proof/v1'),
            required_datasets_json   TEXT NOT NULL,
            coverage_proof_json      TEXT NOT NULL,
            coverage_policy_version  TEXT NOT NULL,
            coverage_policy_digest   TEXT NOT NULL,
            source_generation        INTEGER NOT NULL CHECK
                (source_generation > 0),
            applied_generation       INTEGER NOT NULL CHECK
                (applied_generation > 0),
            persisted_at             TEXT NOT NULL
        );

        CREATE TRIGGER IF NOT EXISTS local_coverage_proofs_no_update
        BEFORE UPDATE ON local_coverage_proofs BEGIN
            SELECT RAISE(ABORT, 'local coverage proofs are immutable');
        END;

        CREATE TRIGGER IF NOT EXISTS local_coverage_proofs_no_delete
        BEFORE DELETE ON local_coverage_proofs BEGIN
            SELECT RAISE(ABORT, 'local coverage proofs are immutable');
        END;
        """,
    ),
    Migration(
        11,
        "phase631_exact_coverage_inventory_proofs",
        """
        CREATE TABLE IF NOT EXISTS local_coverage_proofs_v2 (
            proof_id                 TEXT PRIMARY KEY CHECK
                (length(proof_id) = 71 AND
                 substr(proof_id, 1, 7) = 'sha256:' AND
                 substr(proof_id, 8) NOT GLOB '*[^0-9a-f]*'),
            format                   TEXT NOT NULL CHECK
                (format = 'local-coverage-proof/v2'),
            build_id                 TEXT NOT NULL UNIQUE,
            publication_cutoff       TEXT NOT NULL CHECK
                (length(publication_cutoff) = 10),
            required_datasets_json   TEXT NOT NULL,
            coverage_proof_json      TEXT NOT NULL,
            coverage_policy_version  TEXT NOT NULL,
            coverage_policy_digest   TEXT NOT NULL,
            inventory_set_digest     TEXT NOT NULL,
            source_generation        INTEGER NOT NULL CHECK
                (source_generation > 0),
            applied_generation       INTEGER NOT NULL CHECK
                (applied_generation > 0),
            persisted_at             TEXT NOT NULL
        );

        CREATE TRIGGER IF NOT EXISTS local_coverage_proofs_v2_no_update
        BEFORE UPDATE ON local_coverage_proofs_v2 BEGIN
            SELECT RAISE(ABORT, 'local coverage proofs v2 are immutable');
        END;

        CREATE TRIGGER IF NOT EXISTS local_coverage_proofs_v2_no_delete
        BEFORE DELETE ON local_coverage_proofs_v2 BEGIN
            SELECT RAISE(ABORT, 'local coverage proofs v2 are immutable');
        END;
        """,
    ),
    Migration(
        12,
        "phase631_coverage_complete_transition_tombstones",
        """
        CREATE TABLE IF NOT EXISTS coverage_complete_transition_tombstones (
            transition_id              TEXT PRIMARY KEY CHECK
                (length(transition_id) = 71 AND
                 substr(transition_id, 1, 7) = 'sha256:' AND
                 substr(transition_id, 8) NOT GLOB '*[^0-9a-f]*'),
            format                     TEXT NOT NULL CHECK
                (format = 'coverage-complete-transition/v1'),
            authority_domain           TEXT NOT NULL CHECK
                (authority_domain =
                 'quant-platform/coverage/complete-transition/v1'),
            issuer_key_id              TEXT NOT NULL,
            build_id                   TEXT NOT NULL,
            publication_cutoff         TEXT NOT NULL CHECK
                (length(publication_cutoff) = 10),
            dataset_set_digest         TEXT NOT NULL,
            from_state_digest          TEXT NOT NULL,
            target_state_digest        TEXT NOT NULL,
            coverage_policy_set_digest TEXT NOT NULL,
            inventory_set_digest       TEXT NOT NULL,
            receipt_set_digest         TEXT NOT NULL,
            signed_evidence_json        TEXT NOT NULL,
            consumed_at                TEXT NOT NULL,
            UNIQUE (build_id, dataset_set_digest)
        );

        CREATE TRIGGER IF NOT EXISTS
            coverage_complete_transition_tombstones_no_update
        BEFORE UPDATE ON coverage_complete_transition_tombstones BEGIN
            SELECT RAISE(ABORT, 'coverage transition tombstones are immutable');
        END;

        CREATE TRIGGER IF NOT EXISTS
            coverage_complete_transition_tombstones_no_delete
        BEFORE DELETE ON coverage_complete_transition_tombstones BEGIN
            SELECT RAISE(ABORT, 'coverage transition tombstones are immutable');
        END;
        """,
    ),
    Migration(
        13,
        "phase631_receipt_product_materializations",
        """
        CREATE TABLE IF NOT EXISTS receipt_product_materializations (
            operation_id        TEXT PRIMARY KEY,
            run_id              INTEGER NOT NULL UNIQUE,
            source              TEXT NOT NULL CHECK (source = 'jquants'),
            dataset             TEXT NOT NULL,
            segment_id          TEXT NOT NULL,
            artifact_key        TEXT NOT NULL UNIQUE,
            artifact_digest     TEXT NOT NULL,
            artifact_body       TEXT NOT NULL,
            row_count           INTEGER NOT NULL CHECK (row_count > 0),
            byte_count          INTEGER NOT NULL CHECK (byte_count > 0),
            manifest_key        TEXT NOT NULL UNIQUE,
            manifest_digest     TEXT NOT NULL,
            raw_manifest_key    TEXT NOT NULL,
            raw_manifest_digest TEXT NOT NULL,
            raw_page_count      INTEGER NOT NULL CHECK (raw_page_count > 0),
            raw_row_count       INTEGER NOT NULL CHECK (raw_row_count > 0),
            raw_bytes           INTEGER NOT NULL CHECK (raw_bytes > 0),
            committed_at        TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS ix_receipt_product_segment
            ON receipt_product_materializations(dataset,segment_id,run_id);
        """,
    ),
)


def apply_schema_migrations(conn: sqlite3.Connection) -> None:
    """Apply every unapplied local migration in version order."""
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
