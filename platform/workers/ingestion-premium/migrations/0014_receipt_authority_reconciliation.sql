-- Dedicated Receipt Evidence Authority staging area.
--
-- Rows are append-only per operation and are not a mutable product read path.
-- A receipt can be issued only after the authority rereads this exact natural-
-- key set and proves it equals the canonical parser/normalizer output.  The
-- existing collection_receipts table remains the consumer-facing mirror.

CREATE TABLE IF NOT EXISTS receipt_authority_operations (
    operation_id       TEXT PRIMARY KEY,
    request_digest     TEXT NOT NULL UNIQUE,
    run_id             INTEGER NOT NULL UNIQUE,
    environment        TEXT NOT NULL CHECK (environment IN ('staging','production')),
    dataset            TEXT NOT NULL,
    segment_id         TEXT NOT NULL,
    segment_start      TEXT NOT NULL,
    segment_end        TEXT NOT NULL,
    state              TEXT NOT NULL CHECK (
        state IN ('COLLECTING','STRUCTURED_COMMITTED','RECEIPT_COMMITTED')
    ),
    raw_manifest_key   TEXT,
    raw_manifest_digest TEXT,
    structured_manifest_key TEXT,
    structured_digest TEXT,
    receipt_digest     TEXT,
    checked_at         TEXT NOT NULL,
    updated_at         TEXT NOT NULL,
    CHECK (segment_start <= segment_end)
);

CREATE TABLE IF NOT EXISTS receipt_authority_structured_rows (
    operation_id TEXT NOT NULL,
    natural_key  TEXT NOT NULL,
    source       TEXT NOT NULL CHECK (source = 'jquants'),
    dataset      TEXT NOT NULL,
    event_time   TEXT NOT NULL,
    available_at TEXT NOT NULL,
    ingested_at  TEXT NOT NULL,
    payload      TEXT NOT NULL,
    raw_payload  TEXT NOT NULL,
    row_digest   TEXT NOT NULL,
    PRIMARY KEY (operation_id, natural_key),
    FOREIGN KEY (operation_id)
        REFERENCES receipt_authority_operations(operation_id)
);

CREATE INDEX IF NOT EXISTS ix_receipt_authority_segment
    ON receipt_authority_operations
       (environment,dataset,segment_id,state,checked_at);

CREATE INDEX IF NOT EXISTS ix_receipt_authority_rows_dataset
    ON receipt_authority_structured_rows
       (operation_id,dataset,natural_key);
