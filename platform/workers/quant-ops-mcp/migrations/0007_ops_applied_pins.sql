-- Local research apply pin, projected out-of-band into Ops D1.
-- MCP reads this; it does not write it. Do not apply this migration remotely
-- from this change set — schema only.
--
-- last_applied_change_seq NULL = unpinned. CURRENT requires a non-null pin.
-- Never coerce a missing pin to 0 (Number(null)===Number(0) would be CURRENT).

CREATE TABLE IF NOT EXISTS ops_applied_pins (
    feed                     TEXT PRIMARY KEY,
    last_applied_change_seq  INTEGER,
    updated_at               TEXT,
    projected_at             TEXT NOT NULL,
    projection_generation_id TEXT
);

CREATE INDEX IF NOT EXISTS ix_ops_applied_pins_seq
    ON ops_applied_pins (last_applied_change_seq, feed);
