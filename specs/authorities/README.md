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

The `ingestion-secrets` package now contains the closed typed v2
`JQUANTS_ACQUISITION` target alongside its time-bounded legacy HTTP proxy. The
manifest still records an activation-blocking `PENDING` dependency: no live
Receipt caller Service Binding, dedicated cursor-HMAC key, raw persistence and
reconciliation path, or authority activation is provisioned. The target HMAC
authenticates only opaque live continuation state; response headers and metadata
are not standalone receipt proof.

The Python data plane contains a fail-closed candidate receipt-side verifier for
`jquants-acquisition-collection/v2`. It accepts only a runtime-registered live
Service Binding capture, independently rechecks the closed request, exact 37
headers, immutable raw bytes, provider pagination/query transitions, chain and
closed-month Coverage identity, then pins the authority clock only after that
verification completes. Only a subsequently created transaction context may
provide the conservative PIT `available_at`/signed `checked_at`; direct
record-time capture and context-before-capture ordering are rejected. The legacy
`jquants-pagination-evidence/v1` format is audit/recovery-only and cannot mint a
new COMPLETE receipt. Structured rows are committed only after canonical
parse/normalize/natural-key reconciliation; a fresh transaction rereads raw and
structured state before calling the receipt principal. Acquisition expiry and
context freshness are rechecked after that commit, immediately before issuance,
and before local finalization; the returned envelope is public-key verified.

This foundation does not activate D2 or D3. No production live-capture caller,
Receipt Worker/DO, Service Binding, signing key, or authority ledger is
provisioned. A signature can also be truthfully issued after the structured
commit while the later local receipt/final-status transaction fails; the
cross-service append/finalize recovery protocol is still PENDING. Persisted HMAC
headers after a crash remain RAW_ONLY, and master, tip-only, current/partial-month
acquisition plus the 22-dataset reproof remain outside this candidate.

The frozen-mirror v2 protocols bind environment, authenticated caller, exact
method and purpose, request digest, D1 identity, signed audit, immutable mirror
identity, and descriptor identity. A schema-valid handoff is never itself a
verified capability. Runtime inspection and the OS/socket/event-ledger gates
described in the ADR must also succeed; those deployment gates remain pending.

The account-wide scope of Cloudflare Workers Scripts Write remains an explicit
open residual risk. The Worker, Service Binding, Durable Object, and key-custody
split does not make that deployment permission resource-scoped.
