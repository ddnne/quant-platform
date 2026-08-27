# Authenticated D1 sync audit

`verify_public_keys.json` is the public-key-only trust root for local mirror
provenance. It is intentionally separate from Receipt, READY, and Ops
Projection signing authorities.

A future `COMPLETE` audit will be eligible for Ops publication only after a
separately provisioned authority can complete this closed sequence:

1. repository-pinned Wrangler 4.125.0 exports the governed production
   `quant-ingest` D1 binding;
2. the artifact is materialized in a private temporary SQLite database;
3. every governed table has exact source/local `table_xinfo`, canonical table
   DDL, index/unique-key, foreign-key, and trigger parity (apart from the
   explicitly local snapshot-invalidation triggers), plus row-count/content
   parity, and the source/applied cursors are equal;
4. a single-use reconciled-export capability is consumed by a dedicated,
   non-login authority principal, which constructs and signs every envelope
   claim internally; no generic mapping signer is exposed; and
5. the SQLite audit row, signature, current local cursor, signed source/local
   schema digests, content digest, and table counts all verify again in one
   publisher-owned read transaction.

The authority is currently **not provisioned**. The production sync entry
fails before Wrangler acquisition or local database creation, the committed
registry has zero active keys, and sync state therefore remains `UNKNOWN`.
The former same-UID HOME key is revoked; signatures from it are ineligible for
both current and historical trust, including newly minted backdated documents.
No production code loads D1 private material from HOME, environment variables,
caller paths, PEM values, key ids, or registry overrides.

Local artifacts, legacy HTTP transport, restricted-table syncs, interrupted
applies, old unsigned audit rows, and caller-written `WRANGLER_REMOTE` fields
remain apply-only and cannot provide a projection cursor. Ops publication
consumes only an authenticated applied-mirror handle, never a generic local
SQLite path or caller-supplied cursors. Once an external authority and a new
active public key are provisioned, current eligibility will additionally
enforce a 30-minute age limit, at most 60 seconds of future skew, a monotonic
signed cursor/digest history, and the remote Ops activation cursor floor.
