-- Verifiable control-plane attestations for full R2 response-page retention.
-- R2 remains the raw source of truth; this bounded table lets snapshot
-- publication and the read-only Data Access MCP verify/trace exact manifests
-- without granting arbitrary R2 listing authority.

CREATE TABLE IF NOT EXISTS raw_retention_manifests (
    dataset      TEXT NOT NULL,
    run_id       INTEGER NOT NULL,
    manifest_key TEXT NOT NULL,
    page_count   INTEGER NOT NULL CHECK (page_count >= 0),
    row_count    INTEGER NOT NULL CHECK (row_count >= 0),
    raw_bytes    INTEGER NOT NULL CHECK (raw_bytes >= 0),
    data_digest  TEXT NOT NULL,
    completeness TEXT NOT NULL CHECK (completeness IN ('COMPLETE', 'FAILED')),
    created_at   TEXT NOT NULL,
    PRIMARY KEY (dataset, run_id)
);

CREATE INDEX IF NOT EXISTS ix_raw_retention_run_complete
    ON raw_retention_manifests (run_id, completeness, dataset);
