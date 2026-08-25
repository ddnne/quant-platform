-- Dedicated, read-only-to-MCP Ops Projection schema.
-- The publisher appends a complete immutable generation and flips the singleton
-- pointer last. No table in this database is an ingestion source of truth.

CREATE TABLE IF NOT EXISTS ops_projection_generation (
    generation_id           TEXT PRIMARY KEY,
    status                  TEXT NOT NULL CHECK (status = 'SEALED'),
    source_db_digest        TEXT NOT NULL,
    content_digest          TEXT NOT NULL,
    generated_at            TEXT NOT NULL,
    producer_commit_sha     TEXT NOT NULL,
    contract_digest         TEXT NOT NULL,
    registry_digest         TEXT NOT NULL,
    coverage_policy_version TEXT NOT NULL,
    sealed_at               TEXT NOT NULL,
    signed_envelope_json    TEXT,
    issuer_key_id           TEXT,
    signature               TEXT,
    detail_json             TEXT NOT NULL DEFAULT '{}',
    CHECK (
        (signed_envelope_json IS NULL AND issuer_key_id IS NULL AND signature IS NULL)
        OR
        (signed_envelope_json IS NOT NULL AND issuer_key_id IS NOT NULL AND signature IS NOT NULL)
    )
);

CREATE TABLE IF NOT EXISTS ops_projection_active (
    singleton     INTEGER PRIMARY KEY CHECK (singleton = 1),
    generation_id TEXT NOT NULL,
    activated_at  TEXT NOT NULL,
    FOREIGN KEY (generation_id)
        REFERENCES ops_projection_generation(generation_id)
);

CREATE TABLE IF NOT EXISTS dataset_coverage (
    projection_generation_id         TEXT NOT NULL,
    dataset                         TEXT NOT NULL,
    status                          TEXT NOT NULL CHECK
        (status IN ('COMPLETE', 'PARTIAL', 'STALE', 'UNKNOWN', 'FAILED')),
    policy_version                  TEXT NOT NULL,
    collection_scope                TEXT NOT NULL,
    history_target_start            TEXT NOT NULL,
    history_target_end_rule         TEXT NOT NULL,
    coverage_mode                   TEXT NOT NULL,
    expected_frequency              TEXT NOT NULL,
    universe_rule                   TEXT NOT NULL,
    raw_retention_required          INTEGER NOT NULL,
    structured_reconciliation_required INTEGER NOT NULL,
    governance_tier                 TEXT NOT NULL,
    observed_start                  TEXT,
    observed_end                    TEXT,
    row_count                       INTEGER NOT NULL,
    source_run_id                   INTEGER,
    evaluated_at                    TEXT NOT NULL,
    detail_json                     TEXT NOT NULL,
    PRIMARY KEY (projection_generation_id, dataset)
);

CREATE INDEX IF NOT EXISTS ix_ops_dataset_coverage_status
    ON dataset_coverage
       (projection_generation_id, status, governance_tier, dataset);

CREATE TABLE IF NOT EXISTS coverage_segments (
    projection_generation_id TEXT NOT NULL,
    source          TEXT NOT NULL,
    dataset         TEXT NOT NULL,
    segment_id      TEXT NOT NULL,
    policy_version  TEXT NOT NULL,
    segment_start   TEXT NOT NULL,
    segment_end     TEXT NOT NULL,
    expected_scope  TEXT NOT NULL,
    expected_items  INTEGER,
    status          TEXT NOT NULL,
    receipt_run_id  INTEGER,
    evaluated_at    TEXT NOT NULL,
    detail_json     TEXT NOT NULL,
    PRIMARY KEY (
        projection_generation_id,
        source,
        dataset,
        segment_id,
        policy_version
    )
);

CREATE INDEX IF NOT EXISTS ix_ops_coverage_segments_status
    ON coverage_segments
       (projection_generation_id, dataset, policy_version, status, segment_start);

CREATE TABLE IF NOT EXISTS ops_ready_snapshots (
    projection_generation_id TEXT NOT NULL,
    snapshot_id               TEXT NOT NULL,
    state                     TEXT NOT NULL CHECK (state = 'READY'),
    committed_at              TEXT NOT NULL,
    source_run_id             INTEGER,
    change_seq                INTEGER NOT NULL,
    coverage_policy_version   TEXT NOT NULL,
    quality_policy_version    TEXT NOT NULL,
    coverage_proof_digest     TEXT NOT NULL,
    manifest_json             TEXT NOT NULL,
    PRIMARY KEY (projection_generation_id, snapshot_id)
);

-- A missing READY row is ambiguous.  Every projection generation therefore
-- publishes an explicit READY/NOT_READY state before activation.
CREATE TABLE IF NOT EXISTS ops_ready_state (
    projection_generation_id TEXT PRIMARY KEY,
    status                    TEXT NOT NULL CHECK
        (status IN ('READY', 'NOT_READY')),
    snapshot_id               TEXT,
    reason                    TEXT NOT NULL,
    evaluated_at              TEXT NOT NULL,
    CHECK (
        (status = 'READY' AND snapshot_id IS NOT NULL) OR
        (status = 'NOT_READY' AND snapshot_id IS NULL)
    )
);

CREATE TABLE IF NOT EXISTS ops_snapshot_quality (
    projection_generation_id TEXT NOT NULL,
    snapshot_id    TEXT NOT NULL,
    status         TEXT NOT NULL,
    policy_version TEXT NOT NULL,
    evaluated_at   TEXT NOT NULL,
    summary_json   TEXT NOT NULL,
    PRIMARY KEY (projection_generation_id, snapshot_id)
);

CREATE TABLE IF NOT EXISTS ops_b0_status (
    projection_generation_id TEXT NOT NULL,
    singleton       INTEGER NOT NULL CHECK (singleton = 1),
    status          TEXT NOT NULL CHECK (status IN ('PASS', 'FAIL', 'UNKNOWN')),
    policy_version  TEXT NOT NULL,
    evaluated_at    TEXT NOT NULL,
    summary_json    TEXT NOT NULL,
    results_json    TEXT NOT NULL,
    source_build_id TEXT NOT NULL,
    PRIMARY KEY (projection_generation_id, singleton)
);

CREATE TABLE IF NOT EXISTS endpoint_inventory (
    projection_generation_id       TEXT NOT NULL,
    dataset_id                     TEXT NOT NULL,
    display_name                   TEXT NOT NULL,
    source                         TEXT NOT NULL,
    governance_tier                TEXT NOT NULL CHECK
        (governance_tier IN ('governed', 'experimental')),
    inventory_status               TEXT NOT NULL,
    upstream_locator               TEXT,
    collection_window              TEXT,
    expected_frequency             TEXT,
    coverage_segment_granularity   TEXT,
    research_eligible              INTEGER NOT NULL,
    enabled                        INTEGER NOT NULL,
    sla                            TEXT NOT NULL,
    historical_start               TEXT,
    available_at_json              TEXT,
    PRIMARY KEY (projection_generation_id, dataset_id)
);

CREATE INDEX IF NOT EXISTS ix_ops_endpoint_inventory_source
    ON endpoint_inventory
       (projection_generation_id, source, governance_tier, dataset_id);

CREATE TABLE IF NOT EXISTS collection_sla_status (
    projection_generation_id TEXT NOT NULL,
    dataset_id        TEXT NOT NULL,
    expected_after    TEXT,
    usable_by         TEXT,
    freshness_policy  TEXT NOT NULL,
    timezone          TEXT NOT NULL,
    current_state     TEXT NOT NULL,
    state_reason      TEXT,
    state_since       TEXT,
    last_event_date   TEXT,
    last_checked_at   TEXT NOT NULL,
    PRIMARY KEY (projection_generation_id, dataset_id)
);

CREATE TABLE IF NOT EXISTS ops_projection_metadata (
    projection_generation_id TEXT PRIMARY KEY,
    generated_at       TEXT NOT NULL,
    source_generation  TEXT,
    source_cursor       INTEGER,
    export_cursor       INTEGER,
    applied_cursor      INTEGER,
    age_seconds         INTEGER,
    status              TEXT NOT NULL CHECK
        (status IN ('FRESH', 'STALE', 'FAILED', 'UNKNOWN')),
    projection_version  TEXT NOT NULL,
    refresh_attempt_at  TEXT,
    refresh_success_at  TEXT,
    refresh_error       TEXT,
    detail_json         TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS ingestion_run_log (
    projection_generation_id TEXT NOT NULL,
    id       INTEGER NOT NULL,
    ran_at   TEXT NOT NULL,
    source   TEXT NOT NULL,
    runtime  TEXT,
    status   TEXT NOT NULL,
    detail   TEXT,
    PRIMARY KEY (projection_generation_id, id)
);

CREATE TABLE IF NOT EXISTS ingestion_validation (
    projection_generation_id TEXT NOT NULL,
    run_id         INTEGER NOT NULL,
    dataset        TEXT NOT NULL,
    status         TEXT NOT NULL,
    rows_seen      INTEGER,
    rows_inserted  INTEGER,
    rows_revisions INTEGER,
    detail         TEXT,
    PRIMARY KEY (projection_generation_id, run_id, dataset)
);

-- One current authoritative row per source segment. Historical failed attempts
-- are audit evidence upstream, but never remain a current gap after success.
CREATE TABLE IF NOT EXISTS raw_retention_manifests (
    projection_generation_id TEXT NOT NULL,
    source       TEXT NOT NULL,
    dataset      TEXT NOT NULL,
    segment_id   TEXT NOT NULL,
    run_id       INTEGER,
    manifest_key TEXT,
    page_count   INTEGER,
    row_count    INTEGER,
    raw_bytes    INTEGER,
    data_digest  TEXT,
    completeness TEXT,
    created_at   TEXT,
    reason       TEXT,
    PRIMARY KEY (projection_generation_id, source, dataset, segment_id)
);

CREATE TABLE IF NOT EXISTS ingestion_watermarks (
    projection_generation_id TEXT NOT NULL,
    dataset           TEXT NOT NULL,
    last_event_date   TEXT,
    last_ingested_at  TEXT,
    last_export_cursor INTEGER,
    PRIMARY KEY (projection_generation_id, dataset)
);

CREATE TABLE IF NOT EXISTS ops_sync_feed (
    projection_generation_id TEXT NOT NULL,
    feed                     TEXT NOT NULL,
    latest_source_change_seq INTEGER,
    change_log_row_count     INTEGER,
    exported_cursor          INTEGER,
    applied_cursor           INTEGER,
    updated_at               TEXT,
    PRIMARY KEY (projection_generation_id, feed)
);

CREATE TABLE IF NOT EXISTS ops_storage_plane_status (
    projection_generation_id TEXT PRIMARY KEY,
    materialized_at          TEXT NOT NULL,
    payload_json             TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS ops_alerts (
    projection_generation_id TEXT NOT NULL,
    alert_key     TEXT NOT NULL,
    severity      TEXT NOT NULL,
    status        TEXT NOT NULL,
    reason        TEXT NOT NULL,
    observed_at   TEXT NOT NULL,
    detail_json   TEXT NOT NULL DEFAULT '{}',
    PRIMARY KEY (projection_generation_id, alert_key)
);

CREATE INDEX IF NOT EXISTS ix_ops_alerts_status
    ON ops_alerts (projection_generation_id, status, severity, alert_key);
