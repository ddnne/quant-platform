-- Caller-owned idempotency/recovery ledger for the Receipt Service Binding.
-- The random nonce is persisted before the RPC starts, so a lost response can
-- be recovered without caller reconstruction or caller-supplied evidence.

CREATE TABLE IF NOT EXISTS receipt_authority_requests (
    operation_id  TEXT PRIMARY KEY,
    request_nonce TEXT NOT NULL UNIQUE,
    environment   TEXT NOT NULL CHECK (environment IN ('staging','production')),
    dataset       TEXT NOT NULL,
    segment_id    TEXT NOT NULL,
    state         TEXT NOT NULL CHECK (state IN ('PREPARED','FINALIZED')),
    receipt_digest TEXT,
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL,
    CHECK (request_nonce GLOB '[0-9a-f]*' AND length(request_nonce) = 64),
    CHECK (segment_id GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]'),
    CHECK (
        (state = 'PREPARED' AND receipt_digest IS NULL)
        OR
        (state = 'FINALIZED' AND receipt_digest IS NOT NULL)
    )
);

CREATE INDEX IF NOT EXISTS ix_receipt_authority_requests_pending
    ON receipt_authority_requests(state,environment,dataset,segment_id,created_at);
