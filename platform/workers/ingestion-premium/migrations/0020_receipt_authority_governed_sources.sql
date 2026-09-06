-- Forward rebuild of receipt-authority tables for governed jquants|jsda
-- sources and contract-specific segment IDs. Already-applied 0014/0015/0016/0018
-- are left untouched. Every pre-0020 trigger, index, and FK is recreated after
-- the table swap; DROP TABLE would otherwise delete them.

DROP TRIGGER IF EXISTS receipt_authority_rows_insert_collecting;
DROP TRIGGER IF EXISTS receipt_authority_rows_no_update;
DROP TRIGGER IF EXISTS receipt_authority_rows_no_delete;
DROP TRIGGER IF EXISTS receipt_authority_operations_no_delete;
DROP TRIGGER IF EXISTS receipt_authority_operations_identity_immutable;
DROP TRIGGER IF EXISTS receipt_authority_operations_monotonic;
DROP TRIGGER IF EXISTS receipt_authority_receipts_match_operation;
DROP TRIGGER IF EXISTS receipt_authority_receipts_no_update;
DROP TRIGGER IF EXISTS receipt_authority_receipts_no_delete;
DROP TRIGGER IF EXISTS receipt_authority_requests_no_delete;
DROP TRIGGER IF EXISTS receipt_authority_requests_monotonic;
DROP TRIGGER IF EXISTS receipt_authority_raw_identity_immutable;
DROP TRIGGER IF EXISTS receipt_authority_raw_manifest_no_update;
DROP TRIGGER IF EXISTS receipt_authority_raw_manifest_no_delete;
DROP TRIGGER IF EXISTS receipt_authority_run_identity_immutable;
DROP TRIGGER IF EXISTS receipt_authority_run_no_delete;
DROP TRIGGER IF EXISTS receipt_product_materializations_insert_state;
DROP TRIGGER IF EXISTS receipt_product_materializations_no_update;
DROP TRIGGER IF EXISTS receipt_product_materializations_no_delete;

CREATE TABLE receipt_authority_operations_v2 (
    operation_id       TEXT PRIMARY KEY,
    request_digest     TEXT NOT NULL UNIQUE,
    run_id             INTEGER NOT NULL UNIQUE,
    environment        TEXT NOT NULL CHECK (environment IN ('staging','production')),
    source             TEXT NOT NULL CHECK (source IN ('jquants','jsda')),
    contract_id        TEXT NOT NULL,
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
    raw_page_count     INTEGER,
    raw_row_count      INTEGER,
    raw_bytes          INTEGER,
    CHECK (length(contract_id) > 0),
    CHECK (segment_start <= segment_end),
    CHECK (
        (source = 'jquants' AND (
            (length(segment_id) = 7
             AND segment_id GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]')
            OR
            (length(segment_id) = 10
             AND segment_id GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]')
        ))
        OR
        (source = 'jsda' AND
            length(segment_id) BETWEEN 1 AND 200 AND
            segment_id GLOB '[A-Za-z0-9._-]*'
        )
    )
);

INSERT INTO receipt_authority_operations_v2
SELECT operation_id, request_digest, run_id, environment, 'jquants',
       'jquants_premium_core', dataset, segment_id, segment_start, segment_end,
       state, raw_manifest_key, raw_manifest_digest, structured_manifest_key,
       structured_digest, receipt_digest, checked_at, updated_at,
       raw_page_count, raw_row_count, raw_bytes
  FROM receipt_authority_operations;

CREATE TABLE receipt_authority_requests_v2 (
    operation_id  TEXT PRIMARY KEY,
    request_nonce TEXT NOT NULL UNIQUE,
    environment   TEXT NOT NULL CHECK (environment IN ('staging','production')),
    source        TEXT NOT NULL CHECK (source IN ('jquants','jsda')),
    contract_id   TEXT NOT NULL,
    dataset       TEXT NOT NULL,
    segment_id    TEXT NOT NULL,
    state         TEXT NOT NULL CHECK (state IN ('PREPARED','FINALIZED')),
    receipt_digest TEXT,
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL,
    CHECK (length(contract_id) > 0),
    CHECK (request_nonce GLOB '[0-9a-f]*' AND length(request_nonce) = 64),
    CHECK (
        (source = 'jquants' AND (
            (length(segment_id) = 7
             AND segment_id GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]')
            OR
            (length(segment_id) = 10
             AND segment_id GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]')
        ))
        OR
        (source = 'jsda' AND
            length(segment_id) BETWEEN 1 AND 200 AND
            segment_id GLOB '[A-Za-z0-9._-]*'
        )
    ),
    CHECK (
        (state = 'PREPARED' AND receipt_digest IS NULL)
        OR
        (state = 'FINALIZED' AND receipt_digest IS NOT NULL)
    )
);

INSERT INTO receipt_authority_requests_v2
SELECT operation_id, request_nonce, environment, 'jquants',
       'jquants_premium_core', dataset, segment_id, state, receipt_digest,
       created_at, updated_at
  FROM receipt_authority_requests;

CREATE TABLE receipt_authority_structured_rows_v2 (
    operation_id TEXT NOT NULL,
    natural_key  TEXT NOT NULL,
    source       TEXT NOT NULL CHECK (source IN ('jquants','jsda')),
    dataset      TEXT NOT NULL,
    event_time   TEXT NOT NULL,
    available_at TEXT NOT NULL,
    ingested_at  TEXT NOT NULL,
    payload      TEXT NOT NULL,
    raw_payload  TEXT NOT NULL,
    row_digest   TEXT NOT NULL,
    PRIMARY KEY (operation_id, natural_key),
    FOREIGN KEY (operation_id)
        REFERENCES receipt_authority_operations_v2(operation_id)
);

INSERT INTO receipt_authority_structured_rows_v2
SELECT * FROM receipt_authority_structured_rows;

CREATE TABLE receipt_product_materializations_v2 (
    operation_id        TEXT PRIMARY KEY,
    run_id              INTEGER NOT NULL UNIQUE,
    source              TEXT NOT NULL CHECK (source IN ('jquants','jsda')),
    dataset             TEXT NOT NULL,
    segment_id          TEXT NOT NULL,
    artifact_key        TEXT NOT NULL UNIQUE,
    artifact_digest     TEXT NOT NULL,
    artifact_body       TEXT NOT NULL,
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
        REFERENCES receipt_authority_operations_v2(operation_id),
    FOREIGN KEY (run_id)
        REFERENCES ingestion_run_log(id)
);

INSERT INTO receipt_product_materializations_v2
SELECT * FROM receipt_product_materializations;

DROP TABLE receipt_product_materializations;
DROP TABLE receipt_authority_structured_rows;
DROP TABLE receipt_authority_requests;
DROP TABLE receipt_authority_operations;

ALTER TABLE receipt_authority_operations_v2 RENAME TO receipt_authority_operations;
ALTER TABLE receipt_authority_requests_v2 RENAME TO receipt_authority_requests;
ALTER TABLE receipt_authority_structured_rows_v2 RENAME TO receipt_authority_structured_rows;
ALTER TABLE receipt_product_materializations_v2 RENAME TO receipt_product_materializations;

CREATE INDEX IF NOT EXISTS ix_receipt_authority_segment
    ON receipt_authority_operations
       (environment,source,dataset,segment_id,state,checked_at);
CREATE INDEX IF NOT EXISTS ix_receipt_authority_rows_dataset
    ON receipt_authority_structured_rows
       (operation_id,dataset,natural_key);
CREATE INDEX IF NOT EXISTS ix_receipt_authority_requests_pending
    ON receipt_authority_requests(state,environment,source,dataset,segment_id,created_at);
CREATE INDEX IF NOT EXISTS ix_receipt_product_segment
    ON receipt_product_materializations(source,dataset,segment_id,run_id);

-- Mutation-lease authority is owned by 0023 (idempotent bootstrap + journal).

CREATE TRIGGER receipt_authority_rows_insert_collecting
BEFORE INSERT ON receipt_authority_structured_rows
WHEN NOT EXISTS (
    SELECT 1
      FROM receipt_authority_operations AS operation
     WHERE operation.operation_id = NEW.operation_id
       AND operation.state = 'COLLECTING'
       AND operation.dataset = NEW.dataset
       AND operation.source = NEW.source
)
BEGIN
    SELECT RAISE(ABORT, 'receipt authority rows require collecting operation');
END;

CREATE TRIGGER receipt_authority_rows_no_update
BEFORE UPDATE ON receipt_authority_structured_rows
BEGIN
    SELECT RAISE(ABORT, 'receipt authority rows are append-only');
END;

CREATE TRIGGER receipt_authority_rows_no_delete
BEFORE DELETE ON receipt_authority_structured_rows
BEGIN
    SELECT RAISE(ABORT, 'receipt authority rows are append-only');
END;

CREATE TRIGGER receipt_authority_operations_no_delete
BEFORE DELETE ON receipt_authority_operations
BEGIN
    SELECT RAISE(ABORT, 'receipt authority operations are append-only');
END;

CREATE TRIGGER receipt_authority_operations_identity_immutable
BEFORE UPDATE ON receipt_authority_operations
WHEN OLD.operation_id IS NOT NEW.operation_id
  OR OLD.request_digest IS NOT NEW.request_digest
  OR OLD.run_id IS NOT NEW.run_id
  OR OLD.environment IS NOT NEW.environment
  OR OLD.source IS NOT NEW.source
  OR OLD.contract_id IS NOT NEW.contract_id
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

CREATE TRIGGER receipt_authority_operations_monotonic
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

CREATE TRIGGER receipt_authority_receipts_match_operation
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
       AND operation.source = NEW.source
       AND NEW.source IN ('jquants','jsda')
       AND NEW.status = 'SUCCESS'
)
BEGIN
    SELECT RAISE(ABORT, 'authority receipt does not match committed operation');
END;

CREATE TRIGGER receipt_authority_receipts_no_update
BEFORE UPDATE ON collection_receipts
WHEN EXISTS (
    SELECT 1
      FROM receipt_authority_operations AS operation
     WHERE operation.run_id = OLD.run_id
)
BEGIN
    SELECT RAISE(ABORT, 'authority collection receipts are append-only');
END;

CREATE TRIGGER receipt_authority_receipts_no_delete
BEFORE DELETE ON collection_receipts
WHEN EXISTS (
    SELECT 1
      FROM receipt_authority_operations AS operation
     WHERE operation.run_id = OLD.run_id
)
BEGIN
    SELECT RAISE(ABORT, 'authority collection receipts are append-only');
END;

CREATE TRIGGER receipt_authority_requests_no_delete
BEFORE DELETE ON receipt_authority_requests
BEGIN
    SELECT RAISE(ABORT, 'receipt authority requests are append-only');
END;

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

CREATE TRIGGER receipt_authority_raw_identity_immutable
BEFORE UPDATE ON receipt_authority_operations
WHEN OLD.raw_manifest_key IS NOT NEW.raw_manifest_key
  OR OLD.raw_manifest_digest IS NOT NEW.raw_manifest_digest
  OR OLD.raw_page_count IS NOT NEW.raw_page_count
  OR OLD.raw_row_count IS NOT NEW.raw_row_count
  OR OLD.raw_bytes IS NOT NEW.raw_bytes
BEGIN
    SELECT RAISE(ABORT, 'receipt authority raw identity is immutable');
END;

CREATE TRIGGER receipt_authority_raw_manifest_no_update
BEFORE UPDATE ON raw_retention_manifests
WHEN EXISTS (
    SELECT 1 FROM receipt_authority_operations AS operation
     WHERE operation.run_id = OLD.run_id
)
BEGIN
    SELECT RAISE(ABORT, 'receipt authority raw manifest is append-only');
END;

CREATE TRIGGER receipt_authority_raw_manifest_no_delete
BEFORE DELETE ON raw_retention_manifests
WHEN EXISTS (
    SELECT 1 FROM receipt_authority_operations AS operation
     WHERE operation.run_id = OLD.run_id
)
BEGIN
    SELECT RAISE(ABORT, 'receipt authority raw manifest is append-only');
END;

CREATE TRIGGER receipt_authority_run_identity_immutable
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

CREATE TRIGGER receipt_authority_run_no_delete
BEFORE DELETE ON ingestion_run_log
WHEN OLD.authority_operation_id IS NOT NULL
BEGIN
    SELECT RAISE(ABORT, 'receipt authority ingestion run is append-only');
END;

CREATE TRIGGER receipt_product_materializations_insert_state
BEFORE INSERT ON receipt_product_materializations
WHEN NOT EXISTS (
    SELECT 1 FROM receipt_authority_operations AS operation
     WHERE operation.operation_id = NEW.operation_id
       AND operation.run_id = NEW.run_id
       AND operation.dataset = NEW.dataset
       AND operation.segment_id = NEW.segment_id
       AND operation.source = NEW.source
       AND operation.state = 'COLLECTING'
)
BEGIN
    SELECT RAISE(ABORT, 'receipt product materialization requires collecting operation');
END;

CREATE TRIGGER receipt_product_materializations_no_update
BEFORE UPDATE ON receipt_product_materializations
BEGIN
    SELECT RAISE(ABORT, 'receipt product materializations are append-only');
END;

CREATE TRIGGER receipt_product_materializations_no_delete
BEFORE DELETE ON receipt_product_materializations
BEGIN
    SELECT RAISE(ABORT, 'receipt product materializations are append-only');
END;
