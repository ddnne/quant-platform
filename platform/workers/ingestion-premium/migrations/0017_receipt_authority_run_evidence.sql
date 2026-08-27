-- Allocate Receipt Evidence Authority work from the ordinary monotonic
-- ingestion_run_log identity and make its final raw evidence append-only.
-- ingestion-premium remains the sole migration owner for quant-ingest.

ALTER TABLE ingestion_run_log
    ADD COLUMN authority_operation_id TEXT;

CREATE UNIQUE INDEX IF NOT EXISTS ux_ingestion_run_authority_operation
    ON ingestion_run_log(authority_operation_id)
    WHERE authority_operation_id IS NOT NULL;

ALTER TABLE receipt_authority_operations
    ADD COLUMN raw_page_count INTEGER;
ALTER TABLE receipt_authority_operations
    ADD COLUMN raw_row_count INTEGER;
ALTER TABLE receipt_authority_operations
    ADD COLUMN raw_bytes INTEGER;

CREATE TRIGGER IF NOT EXISTS receipt_authority_raw_identity_immutable
BEFORE UPDATE ON receipt_authority_operations
WHEN OLD.raw_manifest_key IS NOT NEW.raw_manifest_key
  OR OLD.raw_manifest_digest IS NOT NEW.raw_manifest_digest
  OR OLD.raw_page_count IS NOT NEW.raw_page_count
  OR OLD.raw_row_count IS NOT NEW.raw_row_count
  OR OLD.raw_bytes IS NOT NEW.raw_bytes
BEGIN
    SELECT RAISE(ABORT, 'receipt authority raw identity is immutable');
END;

CREATE TRIGGER IF NOT EXISTS receipt_authority_run_identity_immutable
BEFORE UPDATE ON ingestion_run_log
WHEN OLD.authority_operation_id IS NOT NULL
 AND (
      NEW.id IS NOT OLD.id
      OR NEW.ran_at IS NOT OLD.ran_at
      OR NEW.source IS NOT OLD.source
      OR NEW.runtime IS NOT OLD.runtime
      OR NEW.authority_operation_id IS NOT OLD.authority_operation_id
      OR NOT (
          (OLD.status = 'RUNNING' AND NEW.status = 'SUCCESS')
          OR (OLD.status = 'SUCCESS' AND NEW.status = 'SUCCESS'
              AND NEW.detail IS OLD.detail)
      )
 )
BEGIN
    SELECT RAISE(ABORT, 'receipt authority ingestion run is immutable');
END;

CREATE TRIGGER IF NOT EXISTS receipt_authority_run_no_delete
BEFORE DELETE ON ingestion_run_log
WHEN OLD.authority_operation_id IS NOT NULL
BEGIN
    SELECT RAISE(ABORT, 'receipt authority ingestion run is append-only');
END;

CREATE TRIGGER IF NOT EXISTS receipt_authority_raw_manifest_no_update
BEFORE UPDATE ON raw_retention_manifests
WHEN EXISTS (
    SELECT 1 FROM receipt_authority_operations AS operation
     WHERE operation.run_id = OLD.run_id
)
BEGIN
    SELECT RAISE(ABORT, 'receipt authority raw manifest is append-only');
END;

CREATE TRIGGER IF NOT EXISTS receipt_authority_raw_manifest_no_delete
BEFORE DELETE ON raw_retention_manifests
WHEN EXISTS (
    SELECT 1 FROM receipt_authority_operations AS operation
     WHERE operation.run_id = OLD.run_id
)
BEGIN
    SELECT RAISE(ABORT, 'receipt authority raw manifest is append-only');
END;
