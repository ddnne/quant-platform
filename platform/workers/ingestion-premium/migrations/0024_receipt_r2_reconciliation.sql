-- One immutable measurement per operation, not one row per market record.
-- Published only after canonical normalization and full R2 byte readback.
ALTER TABLE receipt_authority_operations ADD COLUMN structured_storage TEXT NOT NULL
    DEFAULT 'legacy_d1' CHECK (structured_storage IN ('legacy_d1','r2_scratch_v1'));

CREATE TRIGGER IF NOT EXISTS receipt_storage_mode_immutable
BEFORE UPDATE OF structured_storage ON receipt_authority_operations
WHEN OLD.structured_storage IS NOT NEW.structured_storage
BEGIN SELECT RAISE(ABORT, 'receipt storage mode is immutable'); END;

CREATE TABLE IF NOT EXISTS receipt_r2_reconciliations (
    operation_id TEXT PRIMARY KEY REFERENCES receipt_product_materializations(operation_id),
    artifact_digest TEXT NOT NULL,
    row_count INTEGER NOT NULL CHECK (row_count > 0),
    natural_key_digest TEXT NOT NULL,
    last_event_time TEXT NOT NULL,
    measured_at TEXT NOT NULL
);

CREATE TRIGGER IF NOT EXISTS receipt_r2_reconciliation_matches_product
BEFORE INSERT ON receipt_r2_reconciliations
WHEN NOT EXISTS (
    SELECT 1 FROM receipt_product_materializations p
    JOIN receipt_authority_operations o ON o.operation_id=p.operation_id
    WHERE p.operation_id=NEW.operation_id
      AND p.artifact_digest=NEW.artifact_digest AND p.row_count=NEW.row_count
      AND p.committed_at=NEW.measured_at
      AND o.state IN ('COLLECTING','STRUCTURED_COMMITTED')
)
BEGIN
    SELECT RAISE(ABORT, 'R2 reconciliation must match measured product');
END;

CREATE TRIGGER IF NOT EXISTS receipt_r2_reconciliation_no_update
BEFORE UPDATE ON receipt_r2_reconciliations
BEGIN SELECT RAISE(ABORT, 'R2 reconciliation is immutable'); END;

CREATE TRIGGER IF NOT EXISTS receipt_r2_reconciliation_no_delete
BEFORE DELETE ON receipt_r2_reconciliations
BEGIN SELECT RAISE(ABORT, 'R2 reconciliation is immutable'); END;
