-- Project the exact receipt -> run -> raw -> research-product digest chain.
-- This remains an immutable read model; the MCP Worker receives no ingestion
-- source binding and can write rows only while a generation is OPEN.

ALTER TABLE ingestion_run_log
    ADD COLUMN authority_operation_id TEXT;

CREATE TABLE IF NOT EXISTS receipt_product_materializations (
    projection_generation_id TEXT NOT NULL,
    operation_id        TEXT NOT NULL,
    run_id              INTEGER NOT NULL,
    source              TEXT NOT NULL CHECK (source = 'jquants'),
    dataset             TEXT NOT NULL,
    segment_id          TEXT NOT NULL,
    artifact_key        TEXT NOT NULL,
    artifact_digest     TEXT NOT NULL,
    artifact_body       TEXT NOT NULL,
    row_count           INTEGER NOT NULL CHECK (row_count > 0),
    byte_count          INTEGER NOT NULL CHECK (byte_count > 0),
    manifest_key        TEXT NOT NULL,
    manifest_digest     TEXT NOT NULL,
    raw_manifest_key    TEXT NOT NULL,
    raw_manifest_digest TEXT NOT NULL,
    raw_page_count      INTEGER NOT NULL CHECK (raw_page_count > 0),
    raw_row_count       INTEGER NOT NULL CHECK (raw_row_count > 0),
    raw_bytes           INTEGER NOT NULL CHECK (raw_bytes > 0),
    committed_at        TEXT NOT NULL,
    PRIMARY KEY (projection_generation_id, operation_id),
    UNIQUE (projection_generation_id, run_id)
);

CREATE INDEX IF NOT EXISTS ix_ops_receipt_product_segment
    ON receipt_product_materializations
       (projection_generation_id,dataset,segment_id,run_id);

CREATE TRIGGER IF NOT EXISTS receipt_product_materializations_open_insert
BEFORE INSERT ON receipt_product_materializations
WHEN NOT EXISTS (
    SELECT 1 FROM ops_projection_generation
     WHERE generation_id = NEW.projection_generation_id AND status = 'OPEN'
)
BEGIN
    SELECT RAISE(ABORT, 'receipt product rows require an OPEN projection generation');
END;

CREATE TRIGGER IF NOT EXISTS receipt_product_materializations_open_update
BEFORE UPDATE ON receipt_product_materializations
WHEN NOT EXISTS (
    SELECT 1 FROM ops_projection_generation
     WHERE generation_id = OLD.projection_generation_id AND status = 'OPEN'
)
  OR NOT EXISTS (
    SELECT 1 FROM ops_projection_generation
     WHERE generation_id = NEW.projection_generation_id AND status = 'OPEN'
)
BEGIN
    SELECT RAISE(ABORT, 'receipt product rows are immutable after projection seal');
END;

CREATE TRIGGER IF NOT EXISTS receipt_product_materializations_open_delete
BEFORE DELETE ON receipt_product_materializations
WHEN NOT EXISTS (
    SELECT 1 FROM ops_projection_generation
     WHERE generation_id = OLD.projection_generation_id AND status = 'OPEN'
)
BEGIN
    SELECT RAISE(ABORT, 'receipt product rows are immutable after projection seal');
END;
