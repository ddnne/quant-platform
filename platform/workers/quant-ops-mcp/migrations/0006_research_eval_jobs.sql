-- Research eval job index. Small rows only — no bars, no daily path arrays.
-- Populated out-of-band (same pattern as ops projection). MCP is read-only.
-- Artifact blobs live in R2 quant-structured under research/eval/job={id}/.

CREATE TABLE IF NOT EXISTS research_eval_jobs (
    job_id              TEXT PRIMARY KEY,
    created_at          TEXT NOT NULL,
    protocol            TEXT NOT NULL,
    git_sha             TEXT,
    factory_version     TEXT,
    n_logics            INTEGER NOT NULL,
    n_windows           INTEGER NOT NULL,
    n_cells             INTEGER NOT NULL,
    one_way_cost        REAL,
    r2_prefix           TEXT NOT NULL,
    status              TEXT NOT NULL DEFAULT 'recorded'
        CHECK (status IN ('recorded', 'failed', 'superseded')),
    promote_as_main     INTEGER NOT NULL DEFAULT 0,
    go_flag             INTEGER NOT NULL DEFAULT 0,
    mass                TEXT NOT NULL DEFAULT 'NO-GO',
    research_candidate  INTEGER NOT NULL DEFAULT 0,
    notes               TEXT NOT NULL DEFAULT ''
);

CREATE INDEX IF NOT EXISTS ix_research_eval_jobs_created
    ON research_eval_jobs (created_at, protocol);

CREATE TABLE IF NOT EXISTS research_eval_cells (
    job_id              TEXT NOT NULL,
    logic_id            TEXT NOT NULL,
    window_id           TEXT NOT NULL,
    daily_path_DD       REAL,
    total_ret_net       REAL,
    occupancy           REAL,
    dd_duration         INTEGER,
    recovered           INTEGER,
    n_days              INTEGER,
    survived            INTEGER NOT NULL DEFAULT 0,
    daily_path_complete INTEGER NOT NULL DEFAULT 0,
    params_hash         TEXT,
    PRIMARY KEY (job_id, logic_id, window_id),
    FOREIGN KEY (job_id) REFERENCES research_eval_jobs (job_id)
);

CREATE INDEX IF NOT EXISTS ix_research_eval_cells_logic_window
    ON research_eval_cells (logic_id, window_id);
