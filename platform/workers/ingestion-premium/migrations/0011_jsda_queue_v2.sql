-- Convergent JSDA acquisition graph.
-- v1 is retained as audit history; the Worker uses only these v2 tables.

CREATE TABLE IF NOT EXISTS jsda_acquisition_jobs_v2 (
    work_key               TEXT PRIMARY KEY,
    run_key                TEXT NOT NULL,
    dataset                TEXT NOT NULL,
    job_type               TEXT NOT NULL CHECK
        (job_type IN ('discover_root', 'discover_year', 'fetch_file')),
    target_url             TEXT NOT NULL,
    segment_id             TEXT NOT NULL,
    parent_work_key        TEXT,
    contract_digest        TEXT NOT NULL,
    state                  TEXT NOT NULL CHECK
        (state IN ('pending', 'queued', 'running', 'completed',
                   'failed_transient', 'rejected')),
    attempt                INTEGER NOT NULL DEFAULT 0 CHECK (attempt >= 0),
    cursor                 INTEGER NOT NULL DEFAULT 0 CHECK (cursor >= 0),
    frontier_json          TEXT,
    last_error             TEXT,
    content_digest         TEXT,
    raw_key                TEXT,
    audit_receipt_key      TEXT,
    audit_receipt_digest   TEXT,
    requested_by           TEXT NOT NULL CHECK (requested_by IN ('cron', 'manual')),
    requested_at           TEXT NOT NULL,
    first_seen_at          TEXT NOT NULL,
    enqueued_at            TEXT,
    started_at             TEXT,
    completed_at           TEXT,
    updated_at             TEXT NOT NULL,
    lease_until            TEXT,
    CHECK ((state NOT IN ('completed', 'rejected')) OR
           (audit_receipt_key IS NOT NULL AND audit_receipt_digest IS NOT NULL)),
    CHECK ((job_type = 'discover_root' AND parent_work_key IS NULL) OR
           (job_type != 'discover_root' AND parent_work_key IS NOT NULL))
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_jsda_jobs_v2_child_url
    ON jsda_acquisition_jobs_v2 (dataset, job_type, target_url)
    WHERE job_type != 'discover_root';

CREATE INDEX IF NOT EXISTS ix_jsda_jobs_v2_state_updated
    ON jsda_acquisition_jobs_v2 (state, updated_at, work_key);

CREATE INDEX IF NOT EXISTS ix_jsda_jobs_v2_run_parent
    ON jsda_acquisition_jobs_v2 (run_key, parent_work_key, job_type, state);

CREATE TABLE IF NOT EXISTS jsda_acquisition_events_v2 (
    event_id               INTEGER PRIMARY KEY AUTOINCREMENT,
    work_key               TEXT NOT NULL,
    run_key                TEXT NOT NULL,
    dataset                TEXT NOT NULL,
    job_type               TEXT NOT NULL,
    segment_id             TEXT NOT NULL,
    attempt                INTEGER NOT NULL,
    cursor                 INTEGER NOT NULL,
    result                 TEXT NOT NULL CHECK
        (result IN ('continued', 'completed', 'failed_transient', 'rejected')),
    reason_code            TEXT,
    detail                 TEXT,
    content_digest         TEXT,
    raw_key                TEXT,
    audit_receipt_key      TEXT NOT NULL,
    audit_receipt_digest   TEXT NOT NULL,
    occurred_at            TEXT NOT NULL,
    FOREIGN KEY (work_key) REFERENCES jsda_acquisition_jobs_v2(work_key)
);

CREATE INDEX IF NOT EXISTS ix_jsda_events_v2_run_time
    ON jsda_acquisition_events_v2 (run_key, occurred_at, event_id);

CREATE TABLE IF NOT EXISTS jsda_queue_rejects_v2 (
    message_id             TEXT PRIMARY KEY,
    attempt                INTEGER NOT NULL,
    reason_code            TEXT NOT NULL,
    body_json              TEXT NOT NULL,
    body_digest            TEXT NOT NULL,
    audit_receipt_key      TEXT NOT NULL,
    audit_receipt_digest   TEXT NOT NULL,
    rejected_at            TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS ix_jsda_queue_rejects_v2_time
    ON jsda_queue_rejects_v2 (rejected_at, reason_code);
