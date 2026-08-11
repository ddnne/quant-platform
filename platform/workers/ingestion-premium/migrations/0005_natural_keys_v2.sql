-- Phase 6 hardening -- contract-v2 natural-key rebuild control plane.
--
-- IMPORTANT: natural keys are deliberately *not* rebuilt in SQL.  SQLite's
-- json_object() retains missing fields as JSON null and D1 has no portable
-- SHA-256 SQL function.  An UPDATE based on json_object() therefore disagrees
-- with the canonical Python/Worker rule, which hashes the complete payload
-- whenever any required discriminator is absent.
--
-- The Worker migration in src/natural_key_migration.ts performs the rebuild:
--   legacy rows -> canonical identity function -> staging -> group versions
--   -> atomic live-table replacement -> full post-publish identity audit.
-- Normal ingestion and exports require this row to be READY, so applying this
-- schema migration cannot leave a partially rebuilt dataset in service.

CREATE TABLE IF NOT EXISTS natural_key_migrations (
    migration_id            TEXT PRIMARY KEY,
    state                   TEXT NOT NULL
        CHECK (state IN ('PENDING','BUILDING','VALIDATING','READY','REJECTED')),
    contract_schema_version INTEGER NOT NULL,
    lock_token              TEXT,
    started_at              TEXT,
    completed_at            TEXT,
    rows_primary            INTEGER NOT NULL DEFAULT 0,
    rows_revisions          INTEGER NOT NULL DEFAULT 0,
    rows_changes            INTEGER NOT NULL DEFAULT 0,
    audit_mismatches        INTEGER,
    detail                  TEXT
);

INSERT OR IGNORE INTO natural_key_migrations
    (migration_id, state, contract_schema_version, detail)
VALUES
    ('jquants-premium-natural-keys-v2', 'PENDING', 2,
     'Run the authenticated Worker natural-key rebuild endpoint');

-- Source versions from both the former primary and revision tables.  Staging
-- is outside the read path and can be filled page by page without exposing a
-- half-migrated live table.
CREATE TABLE IF NOT EXISTS jquants_records_nk_v2_versions_stage (
    source               TEXT NOT NULL,
    dataset              TEXT NOT NULL,
    original_natural_key TEXT NOT NULL,
    natural_key          TEXT NOT NULL,
    event_time           TEXT NOT NULL,
    available_at         TEXT NOT NULL,
    ingested_at          TEXT NOT NULL,
    payload              TEXT NOT NULL,
    raw_payload          TEXT,
    origin               TEXT NOT NULL CHECK (origin IN ('primary','revision')),
    origin_rowid         INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS ix_nk_v2_versions_stage_identity
    ON jquants_records_nk_v2_versions_stage
       (source, dataset, natural_key, ingested_at, available_at);

CREATE TABLE IF NOT EXISTS jquants_records_nk_v2_primary_stage (
    source       TEXT NOT NULL,
    dataset      TEXT NOT NULL,
    natural_key  TEXT NOT NULL,
    event_time   TEXT NOT NULL,
    available_at TEXT NOT NULL,
    ingested_at  TEXT NOT NULL,
    payload      TEXT NOT NULL,
    raw_payload  TEXT,
    PRIMARY KEY (source, dataset, natural_key)
);

CREATE TABLE IF NOT EXISTS jquants_records_nk_v2_revisions_stage (
    source       TEXT NOT NULL,
    dataset      TEXT NOT NULL,
    natural_key  TEXT NOT NULL,
    event_time   TEXT NOT NULL,
    available_at TEXT NOT NULL,
    ingested_at  TEXT NOT NULL,
    payload      TEXT NOT NULL,
    raw_payload  TEXT
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_nk_v2_revisions_stage_version
    ON jquants_records_nk_v2_revisions_stage
       (source, dataset, natural_key, available_at, ingested_at, payload);

CREATE TABLE IF NOT EXISTS ingestion_change_log_nk_v2_stage (
    change_seq   INTEGER PRIMARY KEY,
    table_name   TEXT NOT NULL,
    source       TEXT NOT NULL,
    dataset      TEXT NOT NULL,
    natural_key  TEXT NOT NULL,
    event_time   TEXT NOT NULL,
    available_at TEXT NOT NULL,
    ingested_at  TEXT NOT NULL,
    payload      TEXT NOT NULL,
    raw_payload  TEXT,
    changed_at   TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS ix_nk_v2_changes_stage_identity
    ON ingestion_change_log_nk_v2_stage
       (source, dataset, natural_key, change_seq);
