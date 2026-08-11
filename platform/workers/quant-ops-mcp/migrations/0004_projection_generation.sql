-- Atomic Ops projection generation pointer (Phase 6.2.3 §6).
-- All projection readers must use active generation only.

CREATE TABLE IF NOT EXISTS ops_projection_generation (
    generation_id           TEXT PRIMARY KEY,
    status                  TEXT NOT NULL CHECK
        (status IN ('STAGING', 'ACTIVE', 'RETIRED', 'FAILED')),
    source_db_digest        TEXT,
    generated_at            TEXT NOT NULL,
    producer_commit_sha     TEXT,
    contract_digest         TEXT,
    registry_digest         TEXT,
    coverage_policy_version TEXT,
    activated_at            TEXT,
    detail_json             TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS ops_projection_active (
    singleton       INTEGER PRIMARY KEY CHECK (singleton = 1),
    generation_id   TEXT NOT NULL,
    activated_at    TEXT NOT NULL,
    FOREIGN KEY (generation_id) REFERENCES ops_projection_generation(generation_id)
);

-- Tag rows belonging to a projection generation (nullable for pre-migration rows).
ALTER TABLE dataset_coverage ADD COLUMN projection_generation_id TEXT;
ALTER TABLE coverage_segments ADD COLUMN projection_generation_id TEXT;
ALTER TABLE ops_ready_snapshots ADD COLUMN projection_generation_id TEXT;
ALTER TABLE ops_snapshot_quality ADD COLUMN projection_generation_id TEXT;
ALTER TABLE ops_b0_status ADD COLUMN projection_generation_id TEXT;
ALTER TABLE ops_projection_metadata ADD COLUMN projection_generation_id TEXT;
