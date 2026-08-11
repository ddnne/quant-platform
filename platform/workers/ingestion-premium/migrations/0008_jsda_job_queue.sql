-- JSDA durable acquisition jobs (Phase 6.2.3 §13).
-- Cron enqueues discovery/file jobs; worker drains a bounded batch.

CREATE TABLE IF NOT EXISTS jsda_acquisition_jobs (
    job_id          TEXT PRIMARY KEY,
    dataset         TEXT NOT NULL,
    job_type        TEXT NOT NULL CHECK (job_type IN ('discover_root', 'discover_year', 'fetch_file')),
    target_url      TEXT NOT NULL,
    segment_id      TEXT,
    state           TEXT NOT NULL CHECK
        (state IN ('pending', 'running', 'pass', 'partial', 'fail', 'retry')),
    attempt         INTEGER NOT NULL DEFAULT 0,
    priority        INTEGER NOT NULL DEFAULT 100,
    reason_code     TEXT,
    detail          TEXT,
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL,
    lease_until     TEXT
);

CREATE INDEX IF NOT EXISTS ix_jsda_jobs_state_priority
    ON jsda_acquisition_jobs (state, priority, created_at);
