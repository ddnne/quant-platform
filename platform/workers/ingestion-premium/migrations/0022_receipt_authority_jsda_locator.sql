-- Forward-only: persist the closed JSDA locator on the caller request ledger
-- so PREPARED recovery can reconstruct work_key/raw_object_key/contract digest.
-- 0020 rebuilt receipt_authority_requests without these columns.

ALTER TABLE receipt_authority_requests ADD COLUMN work_key TEXT;
ALTER TABLE receipt_authority_requests ADD COLUMN expected_contract_digest TEXT;
ALTER TABLE receipt_authority_requests ADD COLUMN raw_object_key TEXT;

DROP TRIGGER IF EXISTS receipt_authority_requests_monotonic;

CREATE TRIGGER receipt_authority_requests_monotonic
BEFORE UPDATE ON receipt_authority_requests
WHEN OLD.operation_id IS NOT NEW.operation_id
  OR OLD.request_nonce IS NOT NEW.request_nonce
  OR OLD.environment IS NOT NEW.environment
  OR OLD.source IS NOT NEW.source
  OR OLD.contract_id IS NOT NEW.contract_id
  OR OLD.dataset IS NOT NEW.dataset
  OR OLD.segment_id IS NOT NEW.segment_id
  OR OLD.created_at IS NOT NEW.created_at
  OR OLD.work_key IS NOT NEW.work_key
  OR OLD.expected_contract_digest IS NOT NEW.expected_contract_digest
  OR OLD.raw_object_key IS NOT NEW.raw_object_key
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

CREATE TRIGGER receipt_authority_requests_locator_insert
BEFORE INSERT ON receipt_authority_requests
WHEN NOT (
    (
        NEW.source = 'jquants'
        AND NEW.work_key IS NULL
        AND NEW.expected_contract_digest IS NULL
        AND NEW.raw_object_key IS NULL
    )
    OR (
        NEW.source = 'jsda'
        AND NEW.work_key IS NOT NULL
        AND length(NEW.work_key) BETWEEN 1 AND 400
        AND NEW.expected_contract_digest IS NOT NULL
        AND NEW.expected_contract_digest GLOB 'sha256:[0-9a-f]*'
        AND length(NEW.expected_contract_digest) = 71
        AND NEW.raw_object_key IS NOT NULL
        AND length(NEW.raw_object_key) BETWEEN 1 AND 1024
    )
)
BEGIN
    SELECT RAISE(ABORT, 'receipt authority request locator identity is invalid');
END;

CREATE TRIGGER receipt_authority_requests_locator_update
BEFORE UPDATE ON receipt_authority_requests
WHEN NOT (
    (
        NEW.source = 'jquants'
        AND NEW.work_key IS NULL
        AND NEW.expected_contract_digest IS NULL
        AND NEW.raw_object_key IS NULL
    )
    OR (
        NEW.source = 'jsda'
        AND NEW.work_key IS NOT NULL
        AND length(NEW.work_key) BETWEEN 1 AND 400
        AND NEW.expected_contract_digest IS NOT NULL
        AND NEW.expected_contract_digest GLOB 'sha256:[0-9a-f]*'
        AND length(NEW.expected_contract_digest) = 71
        AND NEW.raw_object_key IS NOT NULL
        AND length(NEW.raw_object_key) BETWEEN 1 AND 1024
    )
)
BEGIN
    SELECT RAISE(ABORT, 'receipt authority request locator identity is invalid');
END;
