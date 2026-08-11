-- Phase 6.2 Residual: endpoint inventory and SLA status tables

-- Canonical endpoint inventory - single source of truth for all ~31 datasets
CREATE TABLE IF NOT EXISTS endpoint_inventory (
    dataset_id                   TEXT PRIMARY KEY,
    display_name                 TEXT NOT NULL,
    source                       TEXT NOT NULL,
    governance_tier              TEXT NOT NULL CHECK (governance_tier IN ('governed', 'experimental')),
    inventory_status             TEXT NOT NULL CHECK (
        inventory_status IN ('GOVERNED', 'EXPERIMENTAL', 'DISABLED', 'UNAVAILABLE_BY_PLAN', 'UNVERIFIED_ENDPOINT')
    ),
    collection_window            TEXT NOT NULL CHECK (
        collection_window IN ('intraday', 'full_day', 'weekly', 'calendar', 'event', 'lagged', 'archive', 'disclosure_event', 'archive_backfill')
    ),
    expected_frequency           TEXT NOT NULL,
    coverage_segment_granularity TEXT NOT NULL,
    research_eligible            INTEGER NOT NULL,
    enabled                      INTEGER NOT NULL,
    sla                          TEXT NOT NULL,  -- JSON object: {expected_after, usable_by, freshness_policy, timezone}
    historical_start             TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS ix_ops_endpoint_inventory_source_tier
    ON endpoint_inventory (source, governance_tier, inventory_status, dataset_id);

CREATE INDEX IF NOT EXISTS ix_ops_endpoint_inventory_enabled
    ON endpoint_inventory (enabled, research_eligible, dataset_id);

-- Ops projection metadata with freshness tracking
CREATE TABLE IF NOT EXISTS ops_projection_metadata (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    generated_at     TEXT NOT NULL,
    source_generation TEXT,
    age_seconds      INTEGER,
    status           TEXT NOT NULL CHECK (status IN ('FRESH', 'STALE', 'FAILED', 'UNKNOWN')),
    projection_version TEXT NOT NULL,
    detail_json      TEXT
);

CREATE INDEX IF NOT EXISTS ix_ops_projection_metadata_generated_at
    ON ops_projection_metadata (generated_at DESC);

-- Collection SLA/freshness status tracking
CREATE TABLE IF NOT EXISTS collection_sla_status (
    dataset_id        TEXT PRIMARY KEY,
    expected_after    TEXT,
    usable_by         TEXT,
    freshness_policy  TEXT NOT NULL,
    timezone          TEXT DEFAULT 'Asia/Tokyo',
    current_state     TEXT NOT NULL CHECK (
        current_state IN ('AVAILABLE', 'NOT_PUBLISHED', 'HOLIDAY', 'API_ERROR', 'ENTITLEMENT_ERROR', 'STALE', 'UNKNOWN')
    ),
    state_reason      TEXT,
    state_since       TEXT,
    last_event_date   TEXT,
    last_checked_at   TEXT NOT NULL,
    FOREIGN KEY (dataset_id) REFERENCES endpoint_inventory(dataset_id)
);

CREATE INDEX IF NOT EXISTS ix_ops_sla_status_state
    ON collection_sla_status (current_state, state_since, dataset_id);

CREATE INDEX IF NOT EXISTS ix_ops_sla_status_freshness
    ON collection_sla_status (freshness_policy, last_checked_at);
