-- OAuth authorization state is a short-lived, one-shot capability.
-- D1 DELETE-with-predicate consumption gives stronger replay protection than
-- eventually consistent KV get/delete operations.
CREATE TABLE IF NOT EXISTS oauth_state_nonce (
    nonce_digest TEXT PRIMARY KEY
        CHECK (length(nonce_digest) = 43),
    issued_at    INTEGER NOT NULL,
    expires_at   INTEGER NOT NULL
        CHECK (expires_at > issued_at)
);

CREATE INDEX IF NOT EXISTS ix_oauth_state_nonce_expiry
    ON oauth_state_nonce (expires_at);
