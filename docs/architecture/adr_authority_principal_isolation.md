# ADR: seven-principal signing authority isolation

Status: Accepted contract, operational activation pending.

## Decision

The platform has exactly seven independent signing principals: `receipt`,
`d1_sync`, `ops_projection`, `coverage_transition`, `ready`, `trader`, and
`controlled_execution`. They may share reviewed libraries but may not share a
service identity, private credential, writable event store, or signing
entrypoint.

`receipt` runs as the separate
`quant-platform-receipt-evidence-authority` Cloudflare Worker, built from the
shared `ingestion-premium` package. Its Ed25519 key is a non-extractable
WebCrypto key held by `ReceiptEvidenceAuthority`; its append-only event state is
SQLite Durable Object storage; callers receive only the closed typed Service
Binding capability. The Worker owns the exact quant-ingest, RAW create-only/read,
STRUCTURED create-only/read, Durable Object, and outgoing typed
`JQUANTS_ACQUISITION` capabilities. `RECEIPT_EVIDENCE_AUTHORITY` belongs to the
caller-side inventory, not to the authority's outgoing resource graph. The
Worker has `workers_dev=false`, `preview_urls=false`, no routes, no secret names,
and a fixed 404 public fetch surface.

The remaining six principals run as separate local OS services. Each deployment
has a unique service user, protected key or credential reference, event store,
and Unix socket. `d1_sync` retains the writable mirror descriptor and may hand
only an independently opened read-only descriptor to `ops_projection` or
`coverage_transition`. The common handoff and event schemas are content-bound
by the principal manifest.

`trader` is not a file-key signer. Authorization requires a WebAuthn platform
authenticator or hardware credential and human presence. The other five local
signers use separately protected local keys and service-policy approval.
READY publication is profile/plan/closure-bound, Trader authorization is one
human-present exact-four batch, and controlled execution is one exact-four
one-shot; generic publish, authorize, and execute operations are absent.

All checked-in deployments remain `PENDING_NO_KEY`. Test keys, real OS users,
Cloudflare resources, bindings, migrations, and registry activation are outside
this contract-freeze commit.

## Enforcement

The schema closes every object. The validator independently pins the manifest
body and protocol-schema digests and rejects principal drift, duplicate
identities/keys/stores/sockets/users, wildcard or broad capabilities,
unauthorized peers, cross-environment resources, cross-signer credential
access, a file-backed Trader key, or missing human presence.

## Residual risk

Cloudflare Workers Scripts Write is account-scoped. Separating the Receipt
Worker, Service Binding, Durable Object, and non-extractable key does not remove
that deployment-level authority. The manifest therefore records this risk as
`OPEN`; it must not be reported as fully isolated until Cloudflare offers or the
deployment process supplies a stronger independently governed boundary.
