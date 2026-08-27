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
dedicated `platform/workers/receipt-evidence-authority` package. Workerd cannot
serialize a `CryptoKey` into Durable Object storage: the runtime acceptance test
observes `DataCloneError: Could not serialize object of type CryptoKey`.
Therefore the Worker generates Ed25519 inside workerd, calls WebCrypto
`wrapKey("pkcs8")` with an AES-256-GCM key supplied only as the
`RECEIPT_KEY_WRAP_KEY` secret, and persists only ciphertext plus a random
96-bit IV. Canonical AAD binds authority, environment, schema, generation,
key id, algorithm, and public key. Every signing use performs authenticated
`unwrapKey(..., extractable=false)`; PKCS#8 bytes are never exposed to
JavaScript. Wrong wrapping key, AAD, ciphertext, or generation fails closed.

Its append-only event state is SQLite Durable Object storage; callers receive
only the closed typed Service Binding capability. The Worker owns the exact
quant-ingest, dedicated authority R2 create-only/readback, Durable Object, and
outgoing typed
`JQUANTS_ACQUISITION` capabilities. `RECEIPT_EVIDENCE_AUTHORITY` belongs to the
caller-side inventory, not to the authority's outgoing resource graph. The
Worker has `workers_dev=false`, `preview_urls=false`, no routes, only the one
wrapping-key secret, and a fixed 404 public fetch surface.

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

All checked-in deployments remain `PENDING_NO_KEY`. The test harness uses only
a conspicuous dummy wrapping value. Real OS users, Cloudflare resources and
secret values, migration application, deployment, and registry activation are
outside this code change; binding and migration declarations are checked in.

Authorization is method-scoped rather than a caller-by-operation Cartesian
product. Each row fixes authenticated caller, target operation, purpose,
environment set, and authentication mechanism. Frozen-mirror requests and
handoffs repeat those values and bind them into canonical request/handoff
digests. Staging and production have different D1 identities.

The closed typed v2 `JQUANTS_ACQUISITION` WorkerEntrypoint target is implemented
and tested in workerd, including a separate-isolate test Service Binding. The
legacy `X-Ingestion-Token` HTTP path remains during migration. Receipt
activation is still blocked: the declared live caller binding and dedicated
HMAC/wrapping keys are unprovisioned. The Receipt Worker verifies governed live
captures, exact raw and 37-header metadata, target/request/query/chain identity,
raw-derived provider pagination, full closed-month slice order, and canonical
Coverage scope. The verifier pins capture completion from its authority clock;
only a later authority-owned transaction timestamp may become conservative PIT
`available_at`/signed `checked_at`. It then commits reconciled structured rows,
starts a fresh transaction, rereads immutable raw and exact natural keys, and
rechecks both acquisition expiry and context freshness immediately before
issuance, after issuance, and at the final local precommit boundary. Authority
time must be nondecreasing across every stage; clock-skew tolerance never permits
a rollback. The returned signed envelope is public-key verified before local
receipt finalization. The legacy v1 pagination evidence is
audit/recovery-only. Target HMAC continuation state is live navigation state;
the response metadata itself is not HMAC-authenticated and is not standalone
COMPLETE evidence.

This is containment, not operational D2/D3 closure. The deployable Worker,
authenticated caller route, typed acquisition/caller bindings, create-only
raw/structured ledger, independently measured pagination transitions, SQLite
authority event ledger, and append/issue/finalize/recover protocol now exist in
code. A crash after signature issue and before receipt finalization recovers the
byte-identical envelope by operation digest. D1 rows, committed receipt
evidence, caller requests, DO operations, key metadata, and event history have
monotonic or append-only triggers.

Cloudflare resources, the wrapping secret, migration application, PENDING
deployment, runtime public-key registration, registry review, exact key-id
activation, and the 22-dataset reproof remain unprovisioned. Master, tip-only,
and current/partial-month acquisition remain explicitly PENDING. The two-deploy
activation procedure is frozen in
`docs/operations/receipt_evidence_authority_activation.md`.

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

The normal ACTIVE deploy gate remains strict. To avoid a circular dependency
where no public key can exist before the first deploy, a narrower
closure-provisioning acceptance permits only the first PENDING deployment. It
requires the frozen binding manifest, applied migrations, wrapping secret,
`AUTHORITY_MODE=PENDING`, no `ACTIVATED_KEY_ID`, public 404, and a demonstrated
signing rejection. It authorizes key generation and public registration only;
it cannot issue a receipt, change Coverage, or satisfy D2/D3. The second ACTIVE
deployment is forbidden until the public registry review and every ordinary P0
activation gate pass.

## Residual risk

Cloudflare Workers Scripts Write is account-scoped. Separating the Receipt
Worker, Service Binding, Durable Object, and non-extractable key does not remove
that deployment-level authority. The manifest therefore records this risk as
`OPEN`; it must not be reported as fully isolated until Cloudflare offers or the
deployment process supplies a stronger independently governed boundary.
