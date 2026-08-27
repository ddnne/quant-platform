-- Signed receipt evidence is append-only after the authority has measured it.
-- These guards also constrain other Workers that retain an account-level
-- binding to the shared ingestion D1 during the operational migration.

CREATE TRIGGER IF NOT EXISTS receipt_authority_rows_insert_collecting
BEFORE INSERT ON receipt_authority_structured_rows
WHEN NOT EXISTS (
    SELECT 1
      FROM receipt_authority_operations AS operation
     WHERE operation.operation_id = NEW.operation_id
       AND operation.state = 'COLLECTING'
       AND operation.dataset = NEW.dataset
)
BEGIN
    SELECT RAISE(ABORT, 'receipt authority rows require collecting operation');
END;

CREATE TRIGGER IF NOT EXISTS receipt_authority_rows_no_update
BEFORE UPDATE ON receipt_authority_structured_rows
BEGIN
    SELECT RAISE(ABORT, 'receipt authority rows are append-only');
END;

CREATE TRIGGER IF NOT EXISTS receipt_authority_rows_no_delete
BEFORE DELETE ON receipt_authority_structured_rows
BEGIN
    SELECT RAISE(ABORT, 'receipt authority rows are append-only');
END;

CREATE TRIGGER IF NOT EXISTS receipt_authority_operations_no_delete
BEFORE DELETE ON receipt_authority_operations
BEGIN
    SELECT RAISE(ABORT, 'receipt authority operations are append-only');
END;

CREATE TRIGGER IF NOT EXISTS receipt_authority_operations_identity_immutable
BEFORE UPDATE ON receipt_authority_operations
WHEN OLD.operation_id IS NOT NEW.operation_id
  OR OLD.request_digest IS NOT NEW.request_digest
  OR OLD.run_id IS NOT NEW.run_id
  OR OLD.environment IS NOT NEW.environment
  OR OLD.dataset IS NOT NEW.dataset
  OR OLD.segment_id IS NOT NEW.segment_id
  OR OLD.segment_start IS NOT NEW.segment_start
  OR OLD.segment_end IS NOT NEW.segment_end
  OR OLD.raw_manifest_key IS NOT NEW.raw_manifest_key
  OR OLD.raw_manifest_digest IS NOT NEW.raw_manifest_digest
  OR OLD.checked_at IS NOT NEW.checked_at
  OR NEW.updated_at < OLD.updated_at
BEGIN
    SELECT RAISE(ABORT, 'receipt authority operation identity is immutable');
END;

CREATE TRIGGER IF NOT EXISTS receipt_authority_operations_monotonic
BEFORE UPDATE ON receipt_authority_operations
WHEN NOT (
    (
        OLD.state = 'COLLECTING'
        AND NEW.state = 'STRUCTURED_COMMITTED'
        AND OLD.structured_manifest_key IS NULL
        AND OLD.structured_digest IS NULL
        AND OLD.receipt_digest IS NULL
        AND NEW.structured_manifest_key IS NOT NULL
        AND NEW.structured_digest IS NOT NULL
        AND NEW.receipt_digest IS NULL
    )
    OR (
        OLD.state = 'STRUCTURED_COMMITTED'
        AND NEW.state = 'STRUCTURED_COMMITTED'
        AND NEW.structured_manifest_key IS OLD.structured_manifest_key
        AND NEW.structured_digest IS OLD.structured_digest
        AND NEW.receipt_digest IS OLD.receipt_digest
    )
    OR (
        OLD.state = 'STRUCTURED_COMMITTED'
        AND NEW.state = 'RECEIPT_COMMITTED'
        AND NEW.structured_manifest_key IS OLD.structured_manifest_key
        AND NEW.structured_digest IS OLD.structured_digest
        AND OLD.receipt_digest IS NULL
        AND NEW.receipt_digest IS NOT NULL
    )
    OR (
        OLD.state = 'RECEIPT_COMMITTED'
        AND NEW.state = 'RECEIPT_COMMITTED'
        AND NEW.structured_manifest_key IS OLD.structured_manifest_key
        AND NEW.structured_digest IS OLD.structured_digest
        AND NEW.receipt_digest IS OLD.receipt_digest
    )
)
BEGIN
    SELECT RAISE(ABORT, 'receipt authority operation transition is not monotonic');
END;

CREATE TRIGGER IF NOT EXISTS receipt_authority_receipts_match_operation
BEFORE INSERT ON collection_receipts
WHEN EXISTS (
    SELECT 1
      FROM receipt_authority_operations AS operation
     WHERE operation.run_id = NEW.run_id
)
AND NOT EXISTS (
    SELECT 1
      FROM receipt_authority_operations AS operation
     WHERE operation.run_id = NEW.run_id
       AND operation.state = 'STRUCTURED_COMMITTED'
       AND operation.dataset = NEW.dataset
       AND operation.segment_id = NEW.segment_id
       AND NEW.source = 'jquants'
       AND NEW.status = 'SUCCESS'
)
BEGIN
    SELECT RAISE(ABORT, 'authority receipt does not match committed operation');
END;

CREATE TRIGGER IF NOT EXISTS receipt_authority_receipts_no_update
BEFORE UPDATE ON collection_receipts
WHEN EXISTS (
    SELECT 1
      FROM receipt_authority_operations AS operation
     WHERE operation.run_id = OLD.run_id
)
BEGIN
    SELECT RAISE(ABORT, 'authority collection receipts are append-only');
END;

CREATE TRIGGER IF NOT EXISTS receipt_authority_receipts_no_delete
BEFORE DELETE ON collection_receipts
WHEN EXISTS (
    SELECT 1
      FROM receipt_authority_operations AS operation
     WHERE operation.run_id = OLD.run_id
)
BEGIN
    SELECT RAISE(ABORT, 'authority collection receipts are append-only');
END;

CREATE TRIGGER IF NOT EXISTS receipt_authority_requests_no_delete
BEFORE DELETE ON receipt_authority_requests
BEGIN
    SELECT RAISE(ABORT, 'receipt authority requests are append-only');
END;

CREATE TRIGGER IF NOT EXISTS receipt_authority_requests_monotonic
BEFORE UPDATE ON receipt_authority_requests
WHEN OLD.operation_id IS NOT NEW.operation_id
  OR OLD.request_nonce IS NOT NEW.request_nonce
  OR OLD.environment IS NOT NEW.environment
  OR OLD.dataset IS NOT NEW.dataset
  OR OLD.segment_id IS NOT NEW.segment_id
  OR OLD.created_at IS NOT NEW.created_at
  OR NEW.updated_at < OLD.updated_at
  OR NOT (
      (
          OLD.state = 'PREPARED'
          AND NEW.state = 'FINALIZED'
          AND OLD.receipt_digest IS NULL
          AND NEW.receipt_digest IS NOT NULL
      )
      OR (
          OLD.state = 'FINALIZED'
          AND NEW.state = 'FINALIZED'
          AND NEW.receipt_digest IS OLD.receipt_digest
      )
  )
BEGIN
    SELECT RAISE(ABORT, 'receipt authority request transition is not monotonic');
END;
