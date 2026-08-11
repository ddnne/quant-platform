-- Read-only MCP projection tables. They are populated out-of-band by the
-- production ops projection script; the MCP itself has no projection writes.

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
    raw_retention_required          INTEGER NOT NULL,
    structured_reconciliation_required INTEGER NOT NULL,
    governance_tier                 TEXT NOT NULL,
    observed_start                  TEXT,
    observed_end                    TEXT,
    row_count                       INTEGER NOT NULL,
    source_run_id                   INTEGER,
    evaluated_at                    TEXT NOT NULL,
    detail_json                     TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS ix_ops_dataset_coverage_status
    ON dataset_coverage (status, governance_tier, dataset);

CREATE TABLE IF NOT EXISTS coverage_segments (
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
    PRIMARY KEY (source, dataset, segment_id, policy_version)
);

CREATE INDEX IF NOT EXISTS ix_ops_coverage_segments_status
    ON coverage_segments (dataset, policy_version, status, segment_start, segment_id);

CREATE TABLE IF NOT EXISTS ops_ready_snapshots (
    snapshot_id             TEXT PRIMARY KEY,
    state                   TEXT NOT NULL CHECK (state = 'READY'),
    committed_at            TEXT NOT NULL,
    source_run_id           INTEGER,
    change_seq              INTEGER NOT NULL,
    coverage_policy_version TEXT NOT NULL,
    quality_policy_version  TEXT NOT NULL,
    coverage_proof_digest   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS ops_snapshot_quality (
    snapshot_id    TEXT PRIMARY KEY,
    status         TEXT NOT NULL,
    policy_version TEXT NOT NULL,
    evaluated_at   TEXT NOT NULL,
    summary_json   TEXT NOT NULL,
    FOREIGN KEY (snapshot_id) REFERENCES ops_ready_snapshots(snapshot_id)
);

CREATE TABLE IF NOT EXISTS ops_b0_status (
    singleton       INTEGER PRIMARY KEY CHECK (singleton = 1),
    status          TEXT NOT NULL CHECK (status IN ('PASS', 'FAIL')),
    policy_version  TEXT NOT NULL,
    evaluated_at    TEXT NOT NULL,
    summary_json    TEXT NOT NULL,
    source_build_id TEXT NOT NULL
);
