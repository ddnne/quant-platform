# Authority contracts

This directory freezes the seven signing principals and the cross-process
protocols they are allowed to use. Validate the checked-in contract with:

```sh
uv run --frozen python scripts/authority_principal_manifest.py
```

The manifest is intentionally `PENDING`: it creates no user, key, Worker,
binding, database, bucket, or socket. Its body digest is independently pinned
by the validator, and it binds the canonical digests of all protocol schemas in
this directory.

Each entrypoint has an exact method ACL binding authenticated caller, operation,
purpose, environment, and authentication mechanism. `allowed_callers` is only a
derived inventory; it does not grant every listed caller every listed method.
Parallel lanes may extend `parallel_protocol_schema_digests` only by adding the
reviewed schema path to the validator in the same commit.

`receipt` is the sole Cloudflare-hosted signer. It is a separate
`quant-platform-receipt-evidence-authority` Worker built from the shared
`ingestion-premium` package and uses a SQLite Durable Object plus a
non-extractable WebCrypto key. It owns only the exact quant-ingest, RAW,
STRUCTURED, Durable Object, and outgoing `JQUANTS_ACQUISITION` capabilities.
The caller-side `RECEIPT_EVIDENCE_AUTHORITY` binding is recorded separately as
an inbound relationship. The Worker has no public URL, route, or secret binding,
and public `fetch` is fixed to 404. The other six authorities are separate local
OS services. `trader` is additionally constrained to a WebAuthn platform or
hardware credential with user presence; it may not use a file-backed signer.

The desired `JQUANTS_ACQUISITION` surface is frozen as a closed typed RPC
schema, but the observed `ingestion-secrets` target still uses HTTP plus a
shared header token. The manifest records this as an activation-blocking
`PENDING` dependency; it does not claim the typed RPC exists.

The frozen-mirror v2 protocols bind environment, authenticated caller, exact
method and purpose, request digest, D1 identity, signed audit, immutable mirror
identity, and descriptor identity. A schema-valid handoff is never itself a
verified capability. Runtime inspection and the OS/socket/event-ledger gates
described in the ADR must also succeed; those deployment gates remain pending.

The account-wide scope of Cloudflare Workers Scripts Write remains an explicit
open residual risk. The Worker, Service Binding, Durable Object, and key-custody
split does not make that deployment permission resource-scoped.
