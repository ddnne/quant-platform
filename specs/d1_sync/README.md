# Authenticated D1 sync audit

`verify_public_keys.json` is the public-key-only trust root for local mirror
provenance. It is intentionally separate from Receipt, READY, and Ops
Projection signing authorities.

A `COMPLETE` audit is eligible for Ops publication only when the production
sync path has completed this closed sequence:

1. repository-pinned Wrangler 4.125.0 exports the governed production
   `quant-ingest` D1 binding;
2. the artifact is materialized in a private temporary SQLite database;
3. every governed table has exact source/local column order, row count, and
   canonical content parity, and the source/applied cursors are equal;
4. the dedicated host key signs the closed audit envelope; and
5. the SQLite audit row, signature, current local cursor, schema digest,
   content digest, and table counts all verify again in one publisher-owned
   read transaction.

Local artifacts, legacy HTTP transport, restricted-table syncs, interrupted
applies, old unsigned audit rows, and caller-written `WRANGLER_REMOTE` fields
remain apply-only and cannot provide a projection cursor. The private key is
loaded only from `~/.config/quant-platform/d1_sync_signing_key.pem`; it must be
an owner-only regular Ed25519 PEM and must match exactly one active key in this
committed registry. There is no CLI, environment, path, PEM, key-id, or
registry override.
