-- One immutable AUDIT_ONLY recovery attestation per reviewed Premium staging
-- version. This table never stores a collection Receipt, Coverage assertion,
-- source row, or product data.

CREATE TABLE IF NOT EXISTS receipt_authority_recovery_audit_attestations (
    reservation_id            TEXT PRIMARY KEY,
    source_sha                TEXT NOT NULL,
    caller_worker_version_id  TEXT NOT NULL,
    authority_operation_id    TEXT NOT NULL,
    request_nonce             TEXT NOT NULL,
    state                     TEXT NOT NULL CHECK (state IN ('PREPARED','ATTESTED')),
    signed_attestation_digest TEXT,
    signed_attestation_json   TEXT,
    created_at                TEXT NOT NULL,
    updated_at                TEXT NOT NULL,
    UNIQUE (source_sha, caller_worker_version_id),
    CHECK (reservation_id GLOB 'sha256:*' AND length(reservation_id) = 71),
    CHECK (
        source_sha NOT GLOB '*[^0-9a-f]*' AND length(source_sha) = 40
    ),
    CHECK (
        caller_worker_version_id NOT GLOB '*[^0-9a-f-]*'
        AND length(caller_worker_version_id) = 36
        AND substr(caller_worker_version_id, 9, 1) = '-'
        AND substr(caller_worker_version_id, 14, 1) = '-'
        AND substr(caller_worker_version_id, 15, 1) GLOB '[1-5]'
        AND substr(caller_worker_version_id, 19, 1) = '-'
        AND substr(caller_worker_version_id, 20, 1) GLOB '[89ab]'
        AND substr(caller_worker_version_id, 24, 1) = '-'
    ),
    CHECK (
        authority_operation_id GLOB 'sha256:*'
        AND length(authority_operation_id) = 71
    ),
    CHECK (
        request_nonce NOT GLOB '*[^0-9a-f]*' AND length(request_nonce) = 64
    ),
    CHECK (
        (state = 'PREPARED'
         AND signed_attestation_digest IS NULL
         AND signed_attestation_json IS NULL)
        OR
        (state = 'ATTESTED'
         AND signed_attestation_digest GLOB 'sha256:*'
         AND length(signed_attestation_digest) = 71
         AND json_valid(signed_attestation_json)
         AND json_extract(signed_attestation_json, '$.schema_version') =
             'receipt-audit-recovery-attestation/v1'
         AND json_extract(signed_attestation_json, '$.purpose') =
             'receipt_authority_recovery_canary'
         AND json_extract(signed_attestation_json, '$.eligibility') = 'AUDIT_ONLY'
         AND json_extract(signed_attestation_json, '$.environment') = 'staging'
         AND json_extract(signed_attestation_json, '$.issuer_class') =
             'ReceiptEvidenceAuthorityAuditSigner')
    )
);

CREATE TRIGGER IF NOT EXISTS receipt_authority_recovery_audit_monotonic
BEFORE UPDATE ON receipt_authority_recovery_audit_attestations
WHEN OLD.reservation_id IS NOT NEW.reservation_id
  OR OLD.source_sha IS NOT NEW.source_sha
  OR OLD.caller_worker_version_id IS NOT NEW.caller_worker_version_id
  OR OLD.authority_operation_id IS NOT NEW.authority_operation_id
  OR OLD.request_nonce IS NOT NEW.request_nonce
  OR OLD.created_at IS NOT NEW.created_at
  OR NEW.updated_at < OLD.updated_at
  OR NOT (
      OLD.state = 'PREPARED'
      AND NEW.state = 'ATTESTED'
      AND OLD.signed_attestation_digest IS NULL
      AND OLD.signed_attestation_json IS NULL
      AND NEW.signed_attestation_digest IS NOT NULL
      AND NEW.signed_attestation_json IS NOT NULL
  )
BEGIN
    SELECT RAISE(ABORT, 'receipt recovery audit transition is not monotonic');
END;

CREATE TRIGGER IF NOT EXISTS receipt_authority_recovery_audit_no_delete
BEFORE DELETE ON receipt_authority_recovery_audit_attestations
BEGIN
    SELECT RAISE(ABORT, 'receipt recovery audit evidence is append-only');
END;
