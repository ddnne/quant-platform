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

Authorization is method-scoped rather than a caller-by-operation Cartesian
product. Each row fixes authenticated caller, target operation, purpose,
environment set, and authentication mechanism. Frozen-mirror requests and
handoffs repeat those values and bind them into canonical request/handoff
digests. Staging and production have different D1 identities.

The closed typed v2 `JQUANTS_ACQUISITION` WorkerEntrypoint target is implemented
and tested in workerd, including a separate-isolate test Service Binding. The
legacy `X-Ingestion-Token` HTTP path remains during migration. Receipt
activation is still blocked: the live caller binding and dedicated HMAC key are
unprovisioned. A receipt-side candidate now verifies runtime-registered live
captures, exact raw and 37-header metadata, target/request/query/chain identity,
raw-derived provider pagination, full closed-month slice order, and canonical
Coverage scope. The verifier pins capture completion from its authority clock;
only a later authority-owned transaction timestamp may become conservative PIT
`available_at`/signed `checked_at`. It then commits reconciled structured rows,
starts a fresh transaction, rereads immutable raw and exact natural keys, and
rechecks both acquisition expiry and context freshness immediately before
issuance and finalization. The returned signed envelope is public-key verified
before local receipt finalization. The legacy v1 pagination evidence is
audit/recovery-only. Target HMAC continuation state is live navigation state;
the response metadata itself is not HMAC-authenticated and is not standalone
COMPLETE evidence.

This is containment, not D2/D3 closure. The production live-capture caller,
Receipt-side create-only raw ledger, Receipt Worker/DO, Ed25519 key and reproof
remain unprovisioned. Structured state must be committed before the external
issuer is called, so a truthful envelope may exist when the later local
receipt/status transaction fails. An authority-owned append/finalize ledger and
recovery protocol are required before activation. Master, tip-only and
current/partial-month acquisition remain explicitly PENDING.

## Enforcement

The schema closes every object. The validator independently pins the manifest
body and protocol-schema digests and rejects principal drift, duplicate
identities/keys/stores/sockets/users, wildcard or broad capabilities,
unauthorized peers, cross-environment resources, cross-signer credential
access, a file-backed Trader key, or missing human presence.

Strict runtime codecs use integer-only canonical JSON: all finite and
non-finite floats, scalar adapters, duplicate keys, and schema coercions are
rejected. Decimal evidence must use a governed scaled integer or an upstream
content digest; authority event payloads are intentionally integer-only.
Inspected request, handoff, event, and WebAuthn candidates carry
module-private nominal provenance backed by a weak registry; raw DTOs and a
copied seal are not positive capabilities. The runtime independently verifies
canonical digests, freshness, the signed D1 audit and governed table identity,
and exactly one read-only SCM_RIGHTS descriptor. A received descriptor is made
non-inheritable immediately, using `MSG_CMSG_CLOEXEC` where available and a
verified `FD_CLOEXEC` fallback; failure closes the descriptor.

Every security-relevant inspector uses the service-owned clock rather than a
caller-supplied timestamp. Authority events require canonical payload and event
digests, a bounded current observation, and an exact sequence/prior digest plus
monotonic prior `observed_at` chain. Historical reconciliation requires a
separate protocol and remains PENDING. WebAuthn requires RP/origin, UP, UV,
expiry, and one-use enforcement; a counting credential cannot roll back to
zero, while counterless mode is valid only when both stored and new counters
are zero. Until the OS peer credential, transactional ledgers, staging signer,
and human-approval services exist, the public activation entrypoints fail with
explicit `PENDING`; shape validation is diagnostic only.

## Residual risk

Cloudflare Workers Scripts Write is account-scoped. Separating the Receipt
Worker, Service Binding, Durable Object, and non-extractable key does not remove
that deployment-level authority. The manifest therefore records this risk as
`OPEN`; it must not be reported as fully isolated until Cloudflare offers or the
deployment process supplies a stronger independently governed boundary.
