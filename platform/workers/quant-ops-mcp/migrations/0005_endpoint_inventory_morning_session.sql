-- Rebuild endpoint_inventory CHECK to allow collection_window='morning_session'.
-- 0003 was later edited to include morning_session, but CREATE TABLE IF NOT EXISTS
-- never rewrote already-applied remote schemas (constraint still lacks the value).

CREATE TABLE IF NOT EXISTS endpoint_inventory__ms (
    dataset_id                   TEXT PRIMARY KEY,
    display_name                 TEXT NOT NULL,
    source                       TEXT NOT NULL,
    governance_tier              TEXT NOT NULL CHECK (governance_tier IN ('governed', 'experimental')),
    inventory_status             TEXT NOT NULL CHECK (
        inventory_status IN ('GOVERNED', 'EXPERIMENTAL', 'DISABLED', 'UNAVAILABLE_BY_PLAN', 'UNVERIFIED_ENDPOINT')
    ),
    collection_window            TEXT NOT NULL CHECK (
        collection_window IN (
            'intraday', 'full_day', 'weekly', 'calendar', 'event', 'lagged',
            'archive', 'disclosure_event', 'archive_backfill', 'morning_session'
        )
    ),
    expected_frequency           TEXT NOT NULL,
    coverage_segment_granularity TEXT NOT NULL,
    research_eligible            INTEGER NOT NULL,
    enabled                      INTEGER NOT NULL,
    sla                          TEXT NOT NULL,
    historical_start             TEXT NOT NULL,
    projection_generation_id     TEXT
);

-- Copy existing rows when the live table already has projection_generation_id.
INSERT OR IGNORE INTO endpoint_inventory__ms (
    dataset_id, display_name, source, governance_tier, inventory_status,
    collection_window, expected_frequency, coverage_segment_granularity,
    research_eligible, enabled, sla, historical_start, projection_generation_id
)
SELECT
    dataset_id, display_name, source, governance_tier, inventory_status,
    collection_window, expected_frequency, coverage_segment_granularity,
    research_eligible, enabled, sla, historical_start,
    NULL
FROM endpoint_inventory;

DROP TABLE endpoint_inventory;
ALTER TABLE endpoint_inventory__ms RENAME TO endpoint_inventory;

CREATE INDEX IF NOT EXISTS ix_ops_endpoint_inventory_source_tier
    ON endpoint_inventory (source, governance_tier, inventory_status, dataset_id);

CREATE INDEX IF NOT EXISTS ix_ops_endpoint_inventory_enabled
    ON endpoint_inventory (enabled, research_eligible, dataset_id);
