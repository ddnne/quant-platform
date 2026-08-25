-- Owned exclusively by quant-platform-ops-read-mcp.
-- Quota state is intentionally isolated from both ingestion and Ops projection.
CREATE TABLE IF NOT EXISTS remote_mcp_daily_quota (
    quota_day   TEXT    NOT NULL,
    subject_id  TEXT    NOT NULL,
    client_id   TEXT    NOT NULL,
    used        INTEGER NOT NULL CHECK (used >= 0 AND used <= limit_value),
    limit_value INTEGER NOT NULL CHECK (limit_value > 0),
    updated_at  TEXT    NOT NULL,
    PRIMARY KEY (quota_day, subject_id, client_id)
);

CREATE INDEX IF NOT EXISTS ix_remote_mcp_quota_updated
    ON remote_mcp_daily_quota (updated_at);
