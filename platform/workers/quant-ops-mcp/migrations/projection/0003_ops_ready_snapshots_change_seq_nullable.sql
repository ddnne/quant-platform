-- Native READY has no D1 change_seq. Rebuild only that column as nullable.
-- Preserve existing rows and OPEN-generation immutability triggers.

DROP TRIGGER IF EXISTS ops_ready_snapshots_open_insert;
DROP TRIGGER IF EXISTS ops_ready_snapshots_open_update;
DROP TRIGGER IF EXISTS ops_ready_snapshots_open_delete;

CREATE TABLE ops_ready_snapshots__v3 (
    projection_generation_id TEXT NOT NULL,
    snapshot_id               TEXT NOT NULL,
    state                     TEXT NOT NULL CHECK (state = 'READY'),
    committed_at              TEXT NOT NULL,
    source_run_id             INTEGER,
    change_seq                INTEGER,
    coverage_policy_version   TEXT NOT NULL,
    quality_policy_version    TEXT NOT NULL,
    coverage_proof_digest     TEXT NOT NULL,
    manifest_json             TEXT NOT NULL,
    PRIMARY KEY (projection_generation_id, snapshot_id)
);

INSERT INTO ops_ready_snapshots__v3 (
    projection_generation_id, snapshot_id, state, committed_at,
    source_run_id, change_seq, coverage_policy_version,
    quality_policy_version, coverage_proof_digest, manifest_json
)
SELECT
    projection_generation_id, snapshot_id, state, committed_at,
    source_run_id, change_seq, coverage_policy_version,
    quality_policy_version, coverage_proof_digest, manifest_json
FROM ops_ready_snapshots;

DROP TABLE ops_ready_snapshots;
ALTER TABLE ops_ready_snapshots__v3 RENAME TO ops_ready_snapshots;

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
