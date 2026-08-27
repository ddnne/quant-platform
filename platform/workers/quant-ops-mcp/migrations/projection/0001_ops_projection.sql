-- Dedicated, read-only-to-MCP Ops Projection schema.
-- The publisher appends a complete immutable generation and flips the singleton
-- pointer last. No table in this database is an ingestion source of truth.

CREATE TABLE IF NOT EXISTS ops_projection_generation (
    generation_id           TEXT PRIMARY KEY,
    status                  TEXT NOT NULL CHECK (status IN ('OPEN', 'SEALED')),
    source_db_digest        TEXT NOT NULL,
    content_digest          TEXT NOT NULL,
    generated_at            TEXT NOT NULL,
    producer_commit_sha     TEXT NOT NULL,
    contract_digest         TEXT NOT NULL,
    registry_digest         TEXT NOT NULL,
    coverage_policy_version TEXT NOT NULL,
    sealed_at               TEXT,
    signed_envelope_json    TEXT,
    issuer_key_id           TEXT,
    signature               TEXT,
    detail_json             TEXT NOT NULL DEFAULT '{}',
    CHECK (
        (signed_envelope_json IS NULL AND issuer_key_id IS NULL AND signature IS NULL)
        OR
        (signed_envelope_json IS NOT NULL AND issuer_key_id IS NOT NULL AND signature IS NOT NULL)
    ),
    CHECK (
        (status = 'OPEN' AND sealed_at IS NULL)
        OR (status = 'SEALED' AND sealed_at IS NOT NULL)
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


-- Publication is a capability transition. Content may be assembled only while
-- its generation is OPEN. The signed metadata transition to SEALED freezes the
-- generation before the singleton pointer can expose it.
CREATE TRIGGER IF NOT EXISTS ops_projection_generation_insert_open
BEFORE INSERT ON ops_projection_generation
WHEN NEW.status <> 'OPEN'
BEGIN
    SELECT RAISE(ABORT, 'Ops Projection generations must be created OPEN');
END;

CREATE TRIGGER IF NOT EXISTS ops_projection_generation_sealed_immutable
BEFORE UPDATE ON ops_projection_generation
WHEN OLD.status = 'SEALED'
  OR EXISTS (
      SELECT 1 FROM ops_projection_active
       WHERE generation_id = OLD.generation_id
  )
  OR NEW.generation_id IS NOT OLD.generation_id
  OR (
      NEW.status = 'SEALED'
      AND (
          NEW.source_db_digest IS NOT OLD.source_db_digest
          OR NEW.content_digest IS NOT OLD.content_digest
          OR NEW.generated_at IS NOT OLD.generated_at
          OR NEW.producer_commit_sha IS NOT OLD.producer_commit_sha
          OR NEW.contract_digest IS NOT OLD.contract_digest
          OR NEW.registry_digest IS NOT OLD.registry_digest
          OR NEW.coverage_policy_version IS NOT OLD.coverage_policy_version
          OR NEW.signed_envelope_json IS NOT OLD.signed_envelope_json
          OR NEW.issuer_key_id IS NOT OLD.issuer_key_id
          OR NEW.signature IS NOT OLD.signature
          OR NEW.detail_json IS NOT OLD.detail_json
          OR NEW.sealed_at IS NULL
      )
  )
BEGIN
    SELECT RAISE(ABORT, 'sealed Ops Projection generation is immutable');
END;

CREATE TRIGGER IF NOT EXISTS ops_projection_generation_delete_guard
BEFORE DELETE ON ops_projection_generation
WHEN OLD.status = 'SEALED'
  OR EXISTS (
      SELECT 1 FROM ops_projection_active
       WHERE generation_id = OLD.generation_id
  )
BEGIN
    SELECT RAISE(ABORT, 'sealed Ops Projection generation is immutable');
END;

CREATE TRIGGER IF NOT EXISTS ops_projection_active_insert_sealed
BEFORE INSERT ON ops_projection_active
WHEN NOT EXISTS (
    SELECT 1 FROM ops_projection_generation
     WHERE generation_id = NEW.generation_id AND status = 'SEALED'
)
BEGIN
    SELECT RAISE(ABORT, 'active Ops Projection generation must be SEALED');
END;

CREATE TRIGGER IF NOT EXISTS ops_projection_active_update_sealed
BEFORE UPDATE ON ops_projection_active
WHEN NEW.singleton <> 1
  OR NOT EXISTS (
      SELECT 1 FROM ops_projection_generation
       WHERE generation_id = NEW.generation_id AND status = 'SEALED'
  )
BEGIN
    SELECT RAISE(ABORT, 'active Ops Projection generation must be SEALED');
END;

CREATE TRIGGER IF NOT EXISTS ops_projection_active_delete_guard
BEFORE DELETE ON ops_projection_active
BEGIN
    SELECT RAISE(ABORT, 'active Ops Projection pointer is immutable except pointer-last rotation');
END;


CREATE TRIGGER IF NOT EXISTS dataset_coverage_open_insert
BEFORE INSERT ON dataset_coverage
WHEN NOT EXISTS (
    SELECT 1 FROM ops_projection_generation
     WHERE generation_id = NEW.projection_generation_id AND status = 'OPEN'
)
BEGIN
    SELECT RAISE(ABORT, 'dataset_coverage rows require an OPEN projection generation');
END;

CREATE TRIGGER IF NOT EXISTS dataset_coverage_open_update
BEFORE UPDATE ON dataset_coverage
WHEN NOT EXISTS (
    SELECT 1 FROM ops_projection_generation
     WHERE generation_id = OLD.projection_generation_id AND status = 'OPEN'
)
  OR NOT EXISTS (
    SELECT 1 FROM ops_projection_generation
     WHERE generation_id = NEW.projection_generation_id AND status = 'OPEN'
)
BEGIN
    SELECT RAISE(ABORT, 'dataset_coverage rows are immutable after projection seal');
END;

CREATE TRIGGER IF NOT EXISTS dataset_coverage_open_delete
BEFORE DELETE ON dataset_coverage
WHEN NOT EXISTS (
    SELECT 1 FROM ops_projection_generation
     WHERE generation_id = OLD.projection_generation_id AND status = 'OPEN'
)
BEGIN
    SELECT RAISE(ABORT, 'dataset_coverage rows are immutable after projection seal');
END;


CREATE TRIGGER IF NOT EXISTS coverage_segments_open_insert
BEFORE INSERT ON coverage_segments
WHEN NOT EXISTS (
    SELECT 1 FROM ops_projection_generation
     WHERE generation_id = NEW.projection_generation_id AND status = 'OPEN'
)
BEGIN
    SELECT RAISE(ABORT, 'coverage_segments rows require an OPEN projection generation');
END;

CREATE TRIGGER IF NOT EXISTS coverage_segments_open_update
BEFORE UPDATE ON coverage_segments
WHEN NOT EXISTS (
    SELECT 1 FROM ops_projection_generation
     WHERE generation_id = OLD.projection_generation_id AND status = 'OPEN'
)
  OR NOT EXISTS (
    SELECT 1 FROM ops_projection_generation
     WHERE generation_id = NEW.projection_generation_id AND status = 'OPEN'
)
BEGIN
    SELECT RAISE(ABORT, 'coverage_segments rows are immutable after projection seal');
END;

CREATE TRIGGER IF NOT EXISTS coverage_segments_open_delete
BEFORE DELETE ON coverage_segments
WHEN NOT EXISTS (
    SELECT 1 FROM ops_projection_generation
     WHERE generation_id = OLD.projection_generation_id AND status = 'OPEN'
)
BEGIN
    SELECT RAISE(ABORT, 'coverage_segments rows are immutable after projection seal');
END;


CREATE TRIGGER IF NOT EXISTS ops_ready_snapshots_open_insert
BEFORE INSERT ON ops_ready_snapshots
WHEN NOT EXISTS (
    SELECT 1 FROM ops_projection_generation
     WHERE generation_id = NEW.projection_generation_id AND status = 'OPEN'
)
BEGIN
    SELECT RAISE(ABORT, 'ops_ready_snapshots rows require an OPEN projection generation');
END;

CREATE TRIGGER IF NOT EXISTS ops_ready_snapshots_open_update
BEFORE UPDATE ON ops_ready_snapshots
WHEN NOT EXISTS (
    SELECT 1 FROM ops_projection_generation
     WHERE generation_id = OLD.projection_generation_id AND status = 'OPEN'
)
  OR NOT EXISTS (
    SELECT 1 FROM ops_projection_generation
     WHERE generation_id = NEW.projection_generation_id AND status = 'OPEN'
)
BEGIN
    SELECT RAISE(ABORT, 'ops_ready_snapshots rows are immutable after projection seal');
END;

CREATE TRIGGER IF NOT EXISTS ops_ready_snapshots_open_delete
BEFORE DELETE ON ops_ready_snapshots
WHEN NOT EXISTS (
    SELECT 1 FROM ops_projection_generation
     WHERE generation_id = OLD.projection_generation_id AND status = 'OPEN'
)
BEGIN
    SELECT RAISE(ABORT, 'ops_ready_snapshots rows are immutable after projection seal');
END;


CREATE TRIGGER IF NOT EXISTS ops_ready_state_open_insert
BEFORE INSERT ON ops_ready_state
WHEN NOT EXISTS (
    SELECT 1 FROM ops_projection_generation
     WHERE generation_id = NEW.projection_generation_id AND status = 'OPEN'
)
BEGIN
    SELECT RAISE(ABORT, 'ops_ready_state rows require an OPEN projection generation');
END;

CREATE TRIGGER IF NOT EXISTS ops_ready_state_open_update
BEFORE UPDATE ON ops_ready_state
WHEN NOT EXISTS (
    SELECT 1 FROM ops_projection_generation
     WHERE generation_id = OLD.projection_generation_id AND status = 'OPEN'
)
  OR NOT EXISTS (
    SELECT 1 FROM ops_projection_generation
     WHERE generation_id = NEW.projection_generation_id AND status = 'OPEN'
)
BEGIN
    SELECT RAISE(ABORT, 'ops_ready_state rows are immutable after projection seal');
END;

CREATE TRIGGER IF NOT EXISTS ops_ready_state_open_delete
BEFORE DELETE ON ops_ready_state
WHEN NOT EXISTS (
    SELECT 1 FROM ops_projection_generation
     WHERE generation_id = OLD.projection_generation_id AND status = 'OPEN'
)
BEGIN
    SELECT RAISE(ABORT, 'ops_ready_state rows are immutable after projection seal');
END;


CREATE TRIGGER IF NOT EXISTS ops_snapshot_quality_open_insert
BEFORE INSERT ON ops_snapshot_quality
WHEN NOT EXISTS (
    SELECT 1 FROM ops_projection_generation
     WHERE generation_id = NEW.projection_generation_id AND status = 'OPEN'
)
BEGIN
    SELECT RAISE(ABORT, 'ops_snapshot_quality rows require an OPEN projection generation');
END;

CREATE TRIGGER IF NOT EXISTS ops_snapshot_quality_open_update
BEFORE UPDATE ON ops_snapshot_quality
WHEN NOT EXISTS (
    SELECT 1 FROM ops_projection_generation
     WHERE generation_id = OLD.projection_generation_id AND status = 'OPEN'
)
  OR NOT EXISTS (
    SELECT 1 FROM ops_projection_generation
     WHERE generation_id = NEW.projection_generation_id AND status = 'OPEN'
)
BEGIN
    SELECT RAISE(ABORT, 'ops_snapshot_quality rows are immutable after projection seal');
END;

CREATE TRIGGER IF NOT EXISTS ops_snapshot_quality_open_delete
BEFORE DELETE ON ops_snapshot_quality
WHEN NOT EXISTS (
    SELECT 1 FROM ops_projection_generation
     WHERE generation_id = OLD.projection_generation_id AND status = 'OPEN'
)
BEGIN
    SELECT RAISE(ABORT, 'ops_snapshot_quality rows are immutable after projection seal');
END;


CREATE TRIGGER IF NOT EXISTS ops_b0_status_open_insert
BEFORE INSERT ON ops_b0_status
WHEN NOT EXISTS (
    SELECT 1 FROM ops_projection_generation
     WHERE generation_id = NEW.projection_generation_id AND status = 'OPEN'
)
BEGIN
    SELECT RAISE(ABORT, 'ops_b0_status rows require an OPEN projection generation');
END;

CREATE TRIGGER IF NOT EXISTS ops_b0_status_open_update
BEFORE UPDATE ON ops_b0_status
WHEN NOT EXISTS (
    SELECT 1 FROM ops_projection_generation
     WHERE generation_id = OLD.projection_generation_id AND status = 'OPEN'
)
  OR NOT EXISTS (
    SELECT 1 FROM ops_projection_generation
     WHERE generation_id = NEW.projection_generation_id AND status = 'OPEN'
)
BEGIN
    SELECT RAISE(ABORT, 'ops_b0_status rows are immutable after projection seal');
END;

CREATE TRIGGER IF NOT EXISTS ops_b0_status_open_delete
BEFORE DELETE ON ops_b0_status
WHEN NOT EXISTS (
    SELECT 1 FROM ops_projection_generation
     WHERE generation_id = OLD.projection_generation_id AND status = 'OPEN'
)
BEGIN
    SELECT RAISE(ABORT, 'ops_b0_status rows are immutable after projection seal');
END;


CREATE TRIGGER IF NOT EXISTS endpoint_inventory_open_insert
BEFORE INSERT ON endpoint_inventory
WHEN NOT EXISTS (
    SELECT 1 FROM ops_projection_generation
     WHERE generation_id = NEW.projection_generation_id AND status = 'OPEN'
)
BEGIN
    SELECT RAISE(ABORT, 'endpoint_inventory rows require an OPEN projection generation');
END;

CREATE TRIGGER IF NOT EXISTS endpoint_inventory_open_update
BEFORE UPDATE ON endpoint_inventory
WHEN NOT EXISTS (
    SELECT 1 FROM ops_projection_generation
     WHERE generation_id = OLD.projection_generation_id AND status = 'OPEN'
)
  OR NOT EXISTS (
    SELECT 1 FROM ops_projection_generation
     WHERE generation_id = NEW.projection_generation_id AND status = 'OPEN'
)
BEGIN
    SELECT RAISE(ABORT, 'endpoint_inventory rows are immutable after projection seal');
END;

CREATE TRIGGER IF NOT EXISTS endpoint_inventory_open_delete
BEFORE DELETE ON endpoint_inventory
WHEN NOT EXISTS (
    SELECT 1 FROM ops_projection_generation
     WHERE generation_id = OLD.projection_generation_id AND status = 'OPEN'
)
BEGIN
    SELECT RAISE(ABORT, 'endpoint_inventory rows are immutable after projection seal');
END;


CREATE TRIGGER IF NOT EXISTS collection_sla_status_open_insert
BEFORE INSERT ON collection_sla_status
WHEN NOT EXISTS (
    SELECT 1 FROM ops_projection_generation
     WHERE generation_id = NEW.projection_generation_id AND status = 'OPEN'
)
BEGIN
    SELECT RAISE(ABORT, 'collection_sla_status rows require an OPEN projection generation');
END;

CREATE TRIGGER IF NOT EXISTS collection_sla_status_open_update
BEFORE UPDATE ON collection_sla_status
WHEN NOT EXISTS (
    SELECT 1 FROM ops_projection_generation
     WHERE generation_id = OLD.projection_generation_id AND status = 'OPEN'
)
  OR NOT EXISTS (
    SELECT 1 FROM ops_projection_generation
     WHERE generation_id = NEW.projection_generation_id AND status = 'OPEN'
)
BEGIN
    SELECT RAISE(ABORT, 'collection_sla_status rows are immutable after projection seal');
END;

CREATE TRIGGER IF NOT EXISTS collection_sla_status_open_delete
BEFORE DELETE ON collection_sla_status
WHEN NOT EXISTS (
    SELECT 1 FROM ops_projection_generation
     WHERE generation_id = OLD.projection_generation_id AND status = 'OPEN'
)
BEGIN
    SELECT RAISE(ABORT, 'collection_sla_status rows are immutable after projection seal');
END;


CREATE TRIGGER IF NOT EXISTS ops_projection_metadata_open_insert
BEFORE INSERT ON ops_projection_metadata
WHEN NOT EXISTS (
    SELECT 1 FROM ops_projection_generation
     WHERE generation_id = NEW.projection_generation_id AND status = 'OPEN'
)
BEGIN
    SELECT RAISE(ABORT, 'ops_projection_metadata rows require an OPEN projection generation');
END;

CREATE TRIGGER IF NOT EXISTS ops_projection_metadata_open_update
BEFORE UPDATE ON ops_projection_metadata
WHEN NOT EXISTS (
    SELECT 1 FROM ops_projection_generation
     WHERE generation_id = OLD.projection_generation_id AND status = 'OPEN'
)
  OR NOT EXISTS (
    SELECT 1 FROM ops_projection_generation
     WHERE generation_id = NEW.projection_generation_id AND status = 'OPEN'
)
BEGIN
    SELECT RAISE(ABORT, 'ops_projection_metadata rows are immutable after projection seal');
END;

CREATE TRIGGER IF NOT EXISTS ops_projection_metadata_open_delete
BEFORE DELETE ON ops_projection_metadata
WHEN NOT EXISTS (
    SELECT 1 FROM ops_projection_generation
     WHERE generation_id = OLD.projection_generation_id AND status = 'OPEN'
)
BEGIN
    SELECT RAISE(ABORT, 'ops_projection_metadata rows are immutable after projection seal');
END;


CREATE TRIGGER IF NOT EXISTS ingestion_run_log_open_insert
BEFORE INSERT ON ingestion_run_log
WHEN NOT EXISTS (
    SELECT 1 FROM ops_projection_generation
     WHERE generation_id = NEW.projection_generation_id AND status = 'OPEN'
)
BEGIN
    SELECT RAISE(ABORT, 'ingestion_run_log rows require an OPEN projection generation');
END;

CREATE TRIGGER IF NOT EXISTS ingestion_run_log_open_update
BEFORE UPDATE ON ingestion_run_log
WHEN NOT EXISTS (
    SELECT 1 FROM ops_projection_generation
     WHERE generation_id = OLD.projection_generation_id AND status = 'OPEN'
)
  OR NOT EXISTS (
    SELECT 1 FROM ops_projection_generation
     WHERE generation_id = NEW.projection_generation_id AND status = 'OPEN'
)
BEGIN
    SELECT RAISE(ABORT, 'ingestion_run_log rows are immutable after projection seal');
END;

CREATE TRIGGER IF NOT EXISTS ingestion_run_log_open_delete
BEFORE DELETE ON ingestion_run_log
WHEN NOT EXISTS (
    SELECT 1 FROM ops_projection_generation
     WHERE generation_id = OLD.projection_generation_id AND status = 'OPEN'
)
BEGIN
    SELECT RAISE(ABORT, 'ingestion_run_log rows are immutable after projection seal');
END;


CREATE TRIGGER IF NOT EXISTS ingestion_validation_open_insert
BEFORE INSERT ON ingestion_validation
WHEN NOT EXISTS (
    SELECT 1 FROM ops_projection_generation
     WHERE generation_id = NEW.projection_generation_id AND status = 'OPEN'
)
BEGIN
    SELECT RAISE(ABORT, 'ingestion_validation rows require an OPEN projection generation');
END;

CREATE TRIGGER IF NOT EXISTS ingestion_validation_open_update
BEFORE UPDATE ON ingestion_validation
WHEN NOT EXISTS (
    SELECT 1 FROM ops_projection_generation
     WHERE generation_id = OLD.projection_generation_id AND status = 'OPEN'
)
  OR NOT EXISTS (
    SELECT 1 FROM ops_projection_generation
     WHERE generation_id = NEW.projection_generation_id AND status = 'OPEN'
)
BEGIN
    SELECT RAISE(ABORT, 'ingestion_validation rows are immutable after projection seal');
END;

CREATE TRIGGER IF NOT EXISTS ingestion_validation_open_delete
BEFORE DELETE ON ingestion_validation
WHEN NOT EXISTS (
    SELECT 1 FROM ops_projection_generation
     WHERE generation_id = OLD.projection_generation_id AND status = 'OPEN'
)
BEGIN
    SELECT RAISE(ABORT, 'ingestion_validation rows are immutable after projection seal');
END;


CREATE TRIGGER IF NOT EXISTS raw_retention_manifests_open_insert
BEFORE INSERT ON raw_retention_manifests
WHEN NOT EXISTS (
    SELECT 1 FROM ops_projection_generation
     WHERE generation_id = NEW.projection_generation_id AND status = 'OPEN'
)
BEGIN
    SELECT RAISE(ABORT, 'raw_retention_manifests rows require an OPEN projection generation');
END;

CREATE TRIGGER IF NOT EXISTS raw_retention_manifests_open_update
BEFORE UPDATE ON raw_retention_manifests
WHEN NOT EXISTS (
    SELECT 1 FROM ops_projection_generation
     WHERE generation_id = OLD.projection_generation_id AND status = 'OPEN'
)
  OR NOT EXISTS (
    SELECT 1 FROM ops_projection_generation
     WHERE generation_id = NEW.projection_generation_id AND status = 'OPEN'
)
BEGIN
    SELECT RAISE(ABORT, 'raw_retention_manifests rows are immutable after projection seal');
END;

CREATE TRIGGER IF NOT EXISTS raw_retention_manifests_open_delete
BEFORE DELETE ON raw_retention_manifests
WHEN NOT EXISTS (
    SELECT 1 FROM ops_projection_generation
     WHERE generation_id = OLD.projection_generation_id AND status = 'OPEN'
)
BEGIN
    SELECT RAISE(ABORT, 'raw_retention_manifests rows are immutable after projection seal');
END;


CREATE TRIGGER IF NOT EXISTS ingestion_watermarks_open_insert
BEFORE INSERT ON ingestion_watermarks
WHEN NOT EXISTS (
    SELECT 1 FROM ops_projection_generation
     WHERE generation_id = NEW.projection_generation_id AND status = 'OPEN'
)
BEGIN
    SELECT RAISE(ABORT, 'ingestion_watermarks rows require an OPEN projection generation');
END;

CREATE TRIGGER IF NOT EXISTS ingestion_watermarks_open_update
BEFORE UPDATE ON ingestion_watermarks
WHEN NOT EXISTS (
    SELECT 1 FROM ops_projection_generation
     WHERE generation_id = OLD.projection_generation_id AND status = 'OPEN'
)
  OR NOT EXISTS (
    SELECT 1 FROM ops_projection_generation
     WHERE generation_id = NEW.projection_generation_id AND status = 'OPEN'
)
BEGIN
    SELECT RAISE(ABORT, 'ingestion_watermarks rows are immutable after projection seal');
END;

CREATE TRIGGER IF NOT EXISTS ingestion_watermarks_open_delete
BEFORE DELETE ON ingestion_watermarks
WHEN NOT EXISTS (
    SELECT 1 FROM ops_projection_generation
     WHERE generation_id = OLD.projection_generation_id AND status = 'OPEN'
)
BEGIN
    SELECT RAISE(ABORT, 'ingestion_watermarks rows are immutable after projection seal');
END;


CREATE TRIGGER IF NOT EXISTS ops_sync_feed_open_insert
BEFORE INSERT ON ops_sync_feed
WHEN NOT EXISTS (
    SELECT 1 FROM ops_projection_generation
     WHERE generation_id = NEW.projection_generation_id AND status = 'OPEN'
)
BEGIN
    SELECT RAISE(ABORT, 'ops_sync_feed rows require an OPEN projection generation');
END;

CREATE TRIGGER IF NOT EXISTS ops_sync_feed_open_update
BEFORE UPDATE ON ops_sync_feed
WHEN NOT EXISTS (
    SELECT 1 FROM ops_projection_generation
     WHERE generation_id = OLD.projection_generation_id AND status = 'OPEN'
)
  OR NOT EXISTS (
    SELECT 1 FROM ops_projection_generation
     WHERE generation_id = NEW.projection_generation_id AND status = 'OPEN'
)
BEGIN
    SELECT RAISE(ABORT, 'ops_sync_feed rows are immutable after projection seal');
END;

CREATE TRIGGER IF NOT EXISTS ops_sync_feed_open_delete
BEFORE DELETE ON ops_sync_feed
WHEN NOT EXISTS (
    SELECT 1 FROM ops_projection_generation
     WHERE generation_id = OLD.projection_generation_id AND status = 'OPEN'
)
BEGIN
    SELECT RAISE(ABORT, 'ops_sync_feed rows are immutable after projection seal');
END;


CREATE TRIGGER IF NOT EXISTS ops_storage_plane_status_open_insert
BEFORE INSERT ON ops_storage_plane_status
WHEN NOT EXISTS (
    SELECT 1 FROM ops_projection_generation
     WHERE generation_id = NEW.projection_generation_id AND status = 'OPEN'
)
BEGIN
    SELECT RAISE(ABORT, 'ops_storage_plane_status rows require an OPEN projection generation');
END;

CREATE TRIGGER IF NOT EXISTS ops_storage_plane_status_open_update
BEFORE UPDATE ON ops_storage_plane_status
WHEN NOT EXISTS (
    SELECT 1 FROM ops_projection_generation
     WHERE generation_id = OLD.projection_generation_id AND status = 'OPEN'
)
  OR NOT EXISTS (
    SELECT 1 FROM ops_projection_generation
     WHERE generation_id = NEW.projection_generation_id AND status = 'OPEN'
)
BEGIN
    SELECT RAISE(ABORT, 'ops_storage_plane_status rows are immutable after projection seal');
END;

CREATE TRIGGER IF NOT EXISTS ops_storage_plane_status_open_delete
BEFORE DELETE ON ops_storage_plane_status
WHEN NOT EXISTS (
    SELECT 1 FROM ops_projection_generation
     WHERE generation_id = OLD.projection_generation_id AND status = 'OPEN'
)
BEGIN
    SELECT RAISE(ABORT, 'ops_storage_plane_status rows are immutable after projection seal');
END;


CREATE TRIGGER IF NOT EXISTS ops_alerts_open_insert
BEFORE INSERT ON ops_alerts
WHEN NOT EXISTS (
    SELECT 1 FROM ops_projection_generation
     WHERE generation_id = NEW.projection_generation_id AND status = 'OPEN'
)
BEGIN
    SELECT RAISE(ABORT, 'ops_alerts rows require an OPEN projection generation');
END;

CREATE TRIGGER IF NOT EXISTS ops_alerts_open_update
BEFORE UPDATE ON ops_alerts
WHEN NOT EXISTS (
    SELECT 1 FROM ops_projection_generation
     WHERE generation_id = OLD.projection_generation_id AND status = 'OPEN'
)
  OR NOT EXISTS (
    SELECT 1 FROM ops_projection_generation
     WHERE generation_id = NEW.projection_generation_id AND status = 'OPEN'
)
BEGIN
    SELECT RAISE(ABORT, 'ops_alerts rows are immutable after projection seal');
END;

CREATE TRIGGER IF NOT EXISTS ops_alerts_open_delete
BEFORE DELETE ON ops_alerts
WHEN NOT EXISTS (
    SELECT 1 FROM ops_projection_generation
     WHERE generation_id = OLD.projection_generation_id AND status = 'OPEN'
)
BEGIN
    SELECT RAISE(ABORT, 'ops_alerts rows are immutable after projection seal');
END;
