-- Coverage V2 keeps the required segment inventory separate from collection
-- receipts. Missing expected segments are therefore visible even when no
-- request (and consequently no receipt) exists for them.

CREATE TABLE IF NOT EXISTS coverage_segments (
    source          TEXT NOT NULL,
    dataset         TEXT NOT NULL,
    segment_id      TEXT NOT NULL,
    policy_version  TEXT NOT NULL,
    segment_start   TEXT NOT NULL,
    segment_end     TEXT NOT NULL,
    expected_scope  TEXT NOT NULL,
    expected_items  INTEGER CHECK
        (expected_items IS NULL OR expected_items >= 0),
    status          TEXT NOT NULL CHECK
        (status IN ('COMPLETE', 'PARTIAL', 'STALE', 'UNKNOWN', 'FAILED')),
    receipt_run_id  INTEGER,
    evaluated_at    TEXT NOT NULL,
    detail_json     TEXT NOT NULL,
    PRIMARY KEY (source, dataset, segment_id, policy_version),
    CHECK (segment_start <= segment_end)
);

CREATE INDEX IF NOT EXISTS ix_coverage_segments_dataset_status
    ON coverage_segments
       (dataset, policy_version, status, segment_start, segment_id);

CREATE TABLE IF NOT EXISTS collection_receipts (
    source               TEXT NOT NULL,
    dataset              TEXT NOT NULL,
    segment_id           TEXT NOT NULL,
    segment_start        TEXT NOT NULL,
    segment_end          TEXT NOT NULL,
    expected_scope       TEXT NOT NULL,
    expected_items       INTEGER CHECK
        (expected_items IS NULL OR expected_items >= 0),
    observed_items       INTEGER NOT NULL CHECK (observed_items >= 0),
    raw_page_count       INTEGER NOT NULL CHECK (raw_page_count >= 0),
    raw_row_count        INTEGER NOT NULL CHECK (raw_row_count >= 0),
    structured_row_count INTEGER NOT NULL CHECK
        (structured_row_count >= 0),
    pagination_exhausted INTEGER NOT NULL CHECK
        (pagination_exhausted IN (0, 1)),
    digests_json         TEXT NOT NULL,
    run_id               INTEGER NOT NULL,
    status               TEXT NOT NULL CHECK (status IN ('SUCCESS', 'FAILED')),
    error                TEXT,
    checked_at           TEXT NOT NULL,
    PRIMARY KEY (source, dataset, segment_id, run_id),
    CHECK (segment_start <= segment_end)
);

CREATE INDEX IF NOT EXISTS ix_collection_receipts_segment_latest
    ON collection_receipts
       (source, dataset, segment_id, segment_start, segment_end,
        checked_at DESC, run_id DESC);
