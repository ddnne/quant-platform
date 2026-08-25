# Authenticated D1 sync audit

`verify_public_keys.json` is the public-key-only trust root for local mirror
provenance. It is intentionally separate from Receipt, READY, and Ops
Projection signing authorities.

A `COMPLETE` audit is eligible for Ops publication only when the production
sync path has completed this closed sequence:

1. repository-pinned Wrangler 4.125.0 exports the governed production
   `quant-ingest` D1 binding;
2. the artifact is materialized in a private temporary SQLite database;
3. every governed table has exact source/local `table_xinfo`, canonical table
   DDL, index/unique-key, foreign-key, and trigger parity (apart from the
   explicitly local snapshot-invalidation triggers), plus row-count/content
   parity, and the source/applied cursors are equal;
4. a single-use reconciled-export capability is consumed by the dedicated
   host authority, which constructs and signs every envelope claim internally;
   the concrete export type and consume function are bound in a process-private
   closure that ordinary imports and module-attribute replacement cannot
   recreate; no generic mapping signer is exposed; and
5. the SQLite audit row, signature, current local cursor, signed source/local
   schema digests, content digest, and table counts all verify again in one
   publisher-owned read transaction.

Local artifacts, legacy HTTP transport, restricted-table syncs, interrupted
applies, old unsigned audit rows, and caller-written `WRANGLER_REMOTE` fields
remain apply-only and cannot provide a projection cursor. Ops publication
consumes only an authenticated applied-mirror handle, never a generic local
SQLite path or caller-supplied cursors. The private key is loaded only from
`~/.config/quant-platform/d1_sync_signing_key.pem`; it must be an owner-only
regular Ed25519 PEM and must match exactly one active key in this committed
registry. There is no CLI, environment, path, PEM, key-id, or registry
override. Signed issuance time, not mutable audit-row timestamps, selects the
current audit. Current eligibility verifies the newest FULL/chained evidence
with exactly that one active key. Historical rows signed by retired keys remain
auditable and must not block a later active-key current import; revoked keys
are neither current nor historically authoritative. Eligibility expires after
30 minutes, rejects more than 60 seconds of future skew, requires a monotonic
signed cursor/digest history among currently eligible rows, and remote Ops
activation independently refuses a cursor below the already-active projection.
