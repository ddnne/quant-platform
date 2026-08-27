-- Bind signed Receipt Evidence Authority output to the actual versioned
-- structured product artifact consumed from the quant-structured plane.

CREATE TABLE IF NOT EXISTS receipt_product_materializations (
    operation_id        TEXT PRIMARY KEY,
    run_id              INTEGER NOT NULL UNIQUE,
    source              TEXT NOT NULL CHECK (source = 'jquants'),
    dataset             TEXT NOT NULL,
    segment_id          TEXT NOT NULL,
    artifact_key        TEXT NOT NULL UNIQUE,
    artifact_digest     TEXT NOT NULL,
    row_count           INTEGER NOT NULL CHECK (row_count > 0),
    byte_count          INTEGER NOT NULL CHECK (byte_count > 0),
    manifest_key        TEXT NOT NULL UNIQUE,
    manifest_digest     TEXT NOT NULL,
    raw_manifest_key    TEXT NOT NULL,
    raw_manifest_digest TEXT NOT NULL,
    raw_page_count      INTEGER NOT NULL CHECK (raw_page_count > 0),
    raw_row_count       INTEGER NOT NULL CHECK (raw_row_count > 0),
    raw_bytes           INTEGER NOT NULL CHECK (raw_bytes > 0),
    committed_at        TEXT NOT NULL,
    FOREIGN KEY (operation_id)
        REFERENCES receipt_authority_operations(operation_id),
    FOREIGN KEY (run_id)
        REFERENCES ingestion_run_log(id)
);

CREATE INDEX IF NOT EXISTS ix_receipt_product_segment
    ON receipt_product_materializations(dataset,segment_id,run_id);

CREATE TRIGGER IF NOT EXISTS receipt_product_materializations_insert_state
BEFORE INSERT ON receipt_product_materializations
WHEN NOT EXISTS (
    SELECT 1 FROM receipt_authority_operations AS operation
     WHERE operation.operation_id = NEW.operation_id
       AND operation.run_id = NEW.run_id
       AND operation.dataset = NEW.dataset
       AND operation.segment_id = NEW.segment_id
       AND operation.state = 'COLLECTING'
)
BEGIN
    SELECT RAISE(ABORT, 'receipt product materialization requires collecting operation');
END;

CREATE TRIGGER IF NOT EXISTS receipt_product_materializations_no_update
BEFORE UPDATE ON receipt_product_materializations
BEGIN
    SELECT RAISE(ABORT, 'receipt product materializations are append-only');
END;

CREATE TRIGGER IF NOT EXISTS receipt_product_materializations_no_delete
BEFORE DELETE ON receipt_product_materializations
BEGIN
    SELECT RAISE(ABORT, 'receipt product materializations are append-only');
END;
