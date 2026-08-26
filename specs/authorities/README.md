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

The account-wide scope of Cloudflare Workers Scripts Write remains an explicit
open residual risk. The Worker, Service Binding, Durable Object, and key-custody
split does not make that deployment permission resource-scoped.
