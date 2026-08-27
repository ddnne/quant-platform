# Receipt Evidence Authority activation

This runbook activates the dedicated Receipt Evidence Authority without ever
making its HTTP surface public or exporting private signing material. The
checked-in production and staging configurations are intentionally
`AUTHORITY_MODE = "PENDING"`, omit `ACTIVATED_KEY_ID`, and set both
`workers_dev = false` and `preview_urls = false`.

The implementation commit does not provision Cloudflare resources, install a
secret, run a migration, deploy a Worker, register a key, or make an existing
receipt eligible for `COMPLETE`.

`AUTHORITY_EVIDENCE_BUCKET` is the authority's sole R2 capability. Immutable
raw pages, reconciliation evidence, and the signed product artifact use
disjoint prefixes in that dedicated bucket. Every object is written with an
atomic create-only condition and immediately read back byte-for-byte before
issuance. The Receipt Worker has no binding to shared `quant-structured`, so an
active product-plane Worker cannot replace authority evidence. Account-wide
Cloudflare administration remains the separately declared residual risk.

## Safety boundary

The authority Worker is callable only through its typed Service Binding. Its
`fetch()` handler returns a fixed `404` with `cache-control: no-store` for every
request. Premium likewise has no Receipt HTTP route: the former reconcile,
recover, and public-key-registration paths return `404` even when a valid
`INGESTION_RUN_TOKEN`, body, query, or caller claim is supplied.

The binding manifest separately freezes the reserved `fetch` special and the
ordinary RPC methods for all four named WorkerEntrypoints. The Receipt Durable
Object exposes exactly five RPC methods: public-key registration, governed
issue/recovery, and the two audit-only recovery-canary operations. Key loading,
event transactions, operation lookup and every other internal helper use
JavaScript `#private` methods, not TypeScript-only `private`; workerd rejects the
former helper names before key, Durable Object, D1 or R2 state can change.

`PremiumReceiptOperatorService` is a named, typed Service Binding entrypoint
with no `fetch()` method. Its only PENDING action is the argument-free
`pending_public_key_registration()` proposal. The authority derives and the
Premium entrypoint revalidates the action, environment, complete deployment
source SHA, Worker versions, authority resource digest, key identity, and
`operation_binding_digest`. It cannot return the AES wrapping secret, wrapped
PKCS#8 ciphertext, or an unwrapped private key. A caller principal/Worker is not
yet bound to this entrypoint. The typed Premium surface is therefore only a
source-level partial boundary; it remains operationally unreachable and is not
an implemented operator-to-Premium principal chain.

`RECEIPT_KEY_WRAP_KEY` is a 32-byte, independently generated wrapping key
encoded as exactly 64 lowercase hexadecimal characters. Put
it into each environment with Wrangler's secret input; never place its value in
a command argument, shell history, log, release artifact, D1, Git, or a support
ticket. Production and staging must use different values.

## Preconditions

Before either deployment:

1. Required Cloudflare CI is green for the exact source SHA.
2. The active-binding manifest is clean for base, production, and staging.
3. A D1 backup and checksum evidence exist for the target environment.
4. Canonical ingestion migrations through
   `0019_receipt_authority_recovery_smoke.sql` have been reviewed and applied by
   the single ingestion migration owner.
5. The target D1/R2 bindings, Durable Object migration, and typed acquisition
   and receipt Service Bindings match the reviewed manifest.
6. Queue/DLQ backlog and current ingestion state have been recorded.
7. Production and staging wrapping secrets and Durable Object namespaces are
   treated as distinct authority domains.

The PENDING ceremony is a three-Worker deployment, not an authority-only
upload. `ingestion-secrets` supplies the closed acquisition RPC,
`receipt-evidence-authority` owns reconciliation/signing state, and
`ingestion-premium` is the sole operator-facing caller. All three live versions
must be the same reviewed source SHA at 100% traffic. A local config check or a
Receipt secret-name check alone is not deployment acceptance.

Install the secret interactively, without putting its value on the command
line:

```sh
cd platform/workers/receipt-evidence-authority
npx wrangler secret put RECEIPT_KEY_WRAP_KEY --config wrangler.staging.toml
npx wrangler secret put RECEIPT_KEY_WRAP_KEY --config wrangler.toml --env production
```

Keep both configurations in `PENDING` and do not add `ACTIVATED_KEY_ID` yet.

Staging additionally needs three independently provisioned, staging-only
credentials before its final source-bound deploy:

```sh
cd platform/workers/ingestion-secrets
npx wrangler secret put JQUANTS_API_KEY --config wrangler.staging.toml
npx wrangler secret put JQUANTS_RPC_CURSOR_HMAC_KEY --config wrangler.staging.toml

cd ../ingestion-premium
npx wrangler secret put INGESTION_RUN_TOKEN --config wrangler.staging.toml
```

The cursor HMAC value must contain at least 32 random bytes and must not match
production. Staging deliberately has no `JQUANTS_PROXY_TOKEN`, so the legacy
HTTP proxy remains unavailable. The Premium token does not authorize any
Receipt operation. The reviewed staging manifest has no Premium workers.dev
hostname, route, custom domain, or operator caller Service Binding.
Registration therefore remains an operational blocker described below.

## Deployment 1: PENDING closure provisioning

This is the only limited exception to the all-P0 activation gate. It may create
and exercise the otherwise unreachable authority resources, but it does not
authorize receipt signing. The acceptance is valid only when all of these
conditions hold:

- `AUTHORITY_MODE=PENDING` and `ACTIVATED_KEY_ID` is absent.
- `workers_dev=false` and `preview_urls=false` remain true.
- Direct HTTP requests cannot reach an operation and always receive the fixed
  `404`.
- `issue_for_segment` and `recover_issue` fail closed before acquisition,
  receipt persistence, or coverage publication.
- The argument-free typed Premium registration capability is the only way to
  trigger key creation and retrieve public registration data; no operator
  caller is deployed yet.
- No collection receipt, coverage state, READY state, or existing signed
  receipt becomes eligible because of this deployment.

Deploy and verify staging first. Deploy production PENDING only after the
staging evidence is reviewed. The exact full Git SHA must appear in both the
version tag/message and the later read-only acceptance result. Run from a clean
checkout of that SHA; do not replace it with a short SHA.

The staging targets, in dependency order, are:

```sh
SOURCE_SHA="<FULL_REVIEWED_GIT_SHA>"

cd platform/workers/ingestion-secrets
npx wrangler deploy --strict --config wrangler.staging.toml \
  --tag "rp-s-a-${SOURCE_SHA}" \
  --message "quant-platform receipt-chain PENDING staging acquisition source ${SOURCE_SHA}"

cd ../receipt-evidence-authority
npx wrangler deploy --strict --config wrangler.staging.toml \
  --tag "rp-s-r-${SOURCE_SHA}" \
  --message "quant-platform receipt-chain PENDING staging authority source ${SOURCE_SHA}"

cd ../ingestion-premium
npx wrangler deploy --strict --config wrangler.staging.toml \
  --tag "rp-s-c-${SOURCE_SHA}" \
  --message "quant-platform receipt-chain PENDING staging caller source ${SOURCE_SHA}"
```

The compact `rp-{environment}-{role}` prefix keeps the tag bounded while the
tag and message both retain all 40 source-SHA characters. Use `p` for the
production environment and each production config/`--env production` only
after staging acceptance.

Immediately after deployment, run the repository acceptance wrapper from
repository root. It first runs frozen CI and the source-only PENDING gate, then
uses `wrangler deployments status`, `wrangler versions view`, and GET-only
Cloudflare API inventory. It brackets the complete three-Worker chain before
and after every source download, rebuilds each Worker from the clean reviewed
Git SHA with a credential-free deterministic `wrangler deploy --dry-run`, and
requires the live downloaded main-module bytes to match the local build
exactly. The SHA must also equal both local and remotely observed official
`origin/main`; version messages and tags are never accepted as source
provenance by themselves.
It also verifies exact Worker/version/100% traffic/bindings/resources plus
workers.dev, previews, routes, custom domains, Cron triggers, Logpush and tail
consumers for all three Workers, and rejects any extra capability surface.
Wrangler returns secret names only; the verifier never reads or emits values.
Authenticated Wrangler downloads and inventories receive only the expected
account ID and API token in a fresh isolated home. They cannot inherit the
operator's Wrangler OAuth session or unrelated ambient secrets.

Exact module equality is a mandatory acceptance condition. The Cloudflare
script `etag` is retained as an observed identifier but is not treated as a
local bundle hash. If dashboard download shape changes or the live module
digest/size differs from the reviewed dry-run output, the result is `HOLD`;
do not infer source provenance from the message, tag, or `etag`.

```sh
scripts/verify_cloudflare_deployment_acceptance.sh \
  --pending-receipt-authority staging \
  --expected-source-sha "${SOURCE_SHA}"
```

Preserve its one-line JSON as immutable non-secret evidence. A PASS is only
`PENDING_LIVE_ACCEPTANCE_ONLY`: active key count remains zero, positive Receipt
operations remain forbidden, and the result is explicitly research-ineligible.

**STOP / HOLD after staging PENDING acceptance.** There is no `PREMIUM_ORIGIN`:
Premium has `workers_dev=false`, no route and no custom domain. Adding any of
those public surfaces to make an old `curl` example work is prohibited. The
typed Premium capability and exact named-handler acceptance are now checked in,
but no operator principal/Worker owns a Service Binding to it. Until that
separately reviewed, no-public-surface caller is configured and accepted, do
not generate a key or claim that registration is executable.

Preserve the non-secret response, source/deployment SHA, environment, Worker
version, Durable Object generation, and response digest as immutable release
evidence. Confirm independently that:

- `algorithm` is exactly `Ed25519`;
- `authority_status` is exactly `PENDING`;
- `environment` matches the target environment;
- `authority_instance_digest` matches the reviewed canonical D1, dedicated R2,
  Durable Object, and acquisition Service Binding instance for that environment;
- `key_id`, `public_key_base64`, and `registration_digest` match the canonical
  registration encoding;
- a repeat call returns the same generation, key ID, public key, and digest.

The first registration call generates the key inside the Durable Object. Its
PKCS#8 form is wrapped with AES-256-GCM using a fresh 96-bit IV and
environment/authority/schema/generation-bound AAD. Subsequent operational use
unwraps it as `extractable:false`. Cloudflare workerd cannot serialize a
`CryptoKey` directly into Durable Object storage; wrapped ciphertext is the
durable representation.

## Registry review

Prepare a normal reviewed change to
`packages/data_plane/data_contracts/receipt_verify_public_keys.<environment>.json`
using the captured public registration only. The unscoped v1/v2 registry is
historical audit evidence and cannot activate v3 COMPLETE eligibility:

1. Add exactly one `pending` Ed25519 key for the target authority.
2. Advance the registry generation and prior-registry digest chain.
3. Recompute and validate the canonical registry digest.
4. Confirm no other key became active and no revoked key was revived.
5. Confirm `environment` and `authority_instance_digest` exactly match
   `receipt_authority_instances.json`; never copy a staging key/receipt into the
   production registry.
6. Merge the registry change through the required Cloudflare check.

No operator may infer or manually choose the activated key ID. It must equal
the exact `key_id` returned by the PENDING authority and merged into the
reviewed public-key registry.

## Deployment 2: ACTIVE

**Operationally blocked.** The source tree now contains the narrow
`receipt_authority_staging_active_gate.py` validator and an ACTIVE-staging Cron
audit canary. The canary uses domain-separated `AUDIT_ONLY` begin/recover RPCs,
dedicated Durable Object tables and an append-only three-event chain:
`INITIAL_COMMITTED`, `RECOVERY_COMPLETED`, then `REPLAY_CONFIRMED`. The first
recover call persists `RECOVERED_PENDING_REPLAY` without any signed
attestation. Only the second identical recover call appends the authority-owned
replay event, transitions to `AUDIT_FINALIZED`, and signs. It never
calls ordinary `issue_for_segment`/`recover_issue`, never writes
`collection_receipts`, Coverage, product raw/structured state or authority R2,
and cannot produce `TRUSTED_COLLECTION`. Premium D1 stores only the canonical
signed audit attestation and its separately named whole-envelope digest. The
ACTIVE audit method can only read that attestation; the only other exact RPC is
the argument-free PENDING registration proposal. Neither operator method can
initiate a positive Receipt operation.

The public gate owns one fixed gitignored ops attestation path and the pinned
staging registry path; only its private test core accepts mappings or alternate
paths. It collects the live documents itself with GET-only Cloudflare calls and
isolated Wrangler homes, reads the attestation once as canonical JSON, and
remeasures the exact three-Worker deployment bracket, module bytes, bindings,
Durable Object
migration tag, secret-name and public surfaces, and verifies the complete
initial/first-recovery/replay-confirmation operation chain with the real
Ed25519 key from the pinned staging registry. Its public API accepts neither
live evidence mappings, paths, a registry/verifier override, nor an in-memory
attestation/Receipt. The signed-claims digest and whole signed-
attestation digest are distinct. It accepts no count, product digest or GO
override and marks output `AUDIT_ONLY` and research-ineligible.

This is only a source-level partial safety boundary, not permission to activate.
The active registry,
ACTIVE vars, migration, deployment, closed operator caller, and live recovery
evidence do not exist. The ordinary all-P0 gate still rejects release. A generic
`ignore P0` switch is not an acceptable substitute, and this runbook does not
authorize ACTIVE deployment under the current gate.

The staging gate treats the authority deployment version, Premium caller
deployment version, active key ID, and exact registry digest as one immutable
activation pair. Any authority deploy, authority version replacement, key
rotation, or registry change requires a coordinated Premium redeploy *after*
the authority deploy. That redeploy must create a new Cloudflare caller version
and a new version-scoped Premium D1 audit row. Never update or reuse an older
row or attestation. The gate rejects the old signed attestation after the
authority side changes and continues to reject a newly signed authority
attestation until the newer caller version is selected and bound to the same
key/registry surface.

Activation is a separate reviewed change. Set:

```toml
AUTHORITY_MODE = "ACTIVE"
ACTIVATED_KEY_ID = "<exact reviewed registration key_id>"
AUTHORITY_REGISTRY_DIGEST = "<exact reviewed scoped registry digest>"
RECEIPT_AUTHORITY_OPERATION_MODE = "ACTIVE" # Premium staging only
RECEIPT_AUTHORITY_ACTIVE_KEY_ID = "<same exact key_id>" # Premium staging only
RECEIPT_AUTHORITY_REGISTRY_DIGEST = "<same exact registry digest>" # Premium staging only
```

The ordinary strict activation gate applies to this deployment; the PENDING
exception no longer applies. At minimum, require:

1. The active public-key registry containing the exact key ID is merged and
   deployed to every verifier.
2. The D1 backup, canonical migrations, Service Bindings, R2, and Durable
   Object state all match the reviewed environment manifest.
3. The current source SHA passes typecheck, workerd runtime tests, and
   base/production/staging dry-runs.
4. No unresolved receipt-authority P0 remains.
5. Staging audit activation, dedicated-state recovery/replay, signature
   verification, and no-product-write smoke tests pass. This audit canary is not
   exact-segment reconciliation and cannot satisfy D2 reproof.
6. Rollback ownership and monitoring are live.
7. The selected Premium caller version was deployed after the selected
   authority version; the signed attestation names both exact versions and the
   registry-derived key. An older pair or mutable row is not accepted.

Both checked-in scoped registries remain `PENDING` with no active key. This
runbook does not authorize changing either registry or Worker to `ACTIVE` while
any receipt-authority P0 remains unresolved.

Deploy ACTIVE to staging first, retain its immutable evidence, then repeat the
review for production. A smoke reconciliation may pass only `dataset` and
`segment`; callers cannot supply counts, digests, pagination state, natural
keys, raw keys, or signatures. Verify the public key ID and signature against
the deployed registry, the operation event chain, the immutable raw and signed
product objects in `quant-receipt-evidence`, exact D1 natural-key readback, and
terminal pagination proof.

After production activation, re-prove the intended dataset segments through
this governed path. The previously reported 22 `COMPLETE` datasets do not
inherit eligibility from older or unsigned receipts. Do not publish profile
READY or run the controlled pilot until all independent READY gates pass.

## Recovery and rollback

The Premium request ledger persists `PREPARED` before RPC and scheduled
recovery resubmits only the opaque operation ID. Issuance, finalization, and
recovery are idempotent. Each acquisition attempt has an authority-owned ID,
nonce, and start time. A completed capture is stored as canonical bytes in the
dedicated evidence bucket and its exact digest/key are committed in Durable
Object SQLite before D1 reconciliation. `recover_issue` reloads those anchored
bytes. If acquisition stopped with only partial raw pages, recovery marks that
attempt `ABANDONED` and uses a new attempt identity and distinct create-only R2
prefix; it never overwrites the partial evidence. Existing D1 operation,
shadow rows, governed product row, change-log row, and materialization index
must also reconcile before signing. A crash after signature issuance but
before caller finalization must recover the same receipt rather than mint a
second one.

Every Durable Object state transition and its audit event or paired events are
committed in one synchronous SQLite transaction. Event-append failure rolls
back the state mutation. Begin/recovery replay, signing, and finalization all
recompute the complete chained event history and reject a missing, partial, or
corrupt required event.

The acquisition context still expires fail-closed. Recovery does not overwrite
old raw bytes, accept changed upstream bytes, extend an expired acquisition, or
mint a replacement operation under the old request nonce. If a `COLLECTING`
operation cannot reproduce its immutable capture within the governed context,
an operator must retain that failed operation as evidence and start a new
request with a fresh nonce; the old caller-ledger row is not silently promoted
to `FINALIZED`.

For an authority or verifier incident:

1. Change the affected environment back to `AUTHORITY_MODE=PENDING` through an
   emergency reviewed deployment.
2. Do not delete the Durable Object, key metadata, wrapped key, operation rows,
   event chain, structured evidence, or caller request ledger.
3. Invalidate dependent READY evidence and stop new controlled execution.
4. Record the last valid operation/event hashes and deployment versions.
5. Rotate by incrementing `RECEIPT_KEY_GENERATION`; repeat the two-deployment
   process and registry review. Never reuse a wrapping secret across
   environments.

Wrong wrapping keys, wrong AAD, ciphertext tampering, undeclared authority
modes (including `ACTIVE_TEST`), an absent/mismatched `ACTIVATED_KEY_ID`, replay
with a changed request, and post-sign structured-row mutation all fail closed.

## Current status

The repository contains the inactive implementation and test evidence only.
Staging and production remain PENDING and unprovisioned. The checked-in
deployment contract now includes the minimum staging acquisition/caller secret
names and a fail-closed live three-Worker acceptance verifier. It does not
install their values, deploy, migrate, generate a key, or call registration.
Staging registration remains HOLD because the typed Premium entrypoint has no
bound operator caller principal/Worker. The source-only ACTIVE validator and
Cron recovery canary are present, but have not been migrated, deployed, or
measured. Production acceptance additionally remains C7 HOLD because
the acquisition Worker's workers.dev hostname is enabled and no Cloudflare
Access application/policy is provisioned or verified; the live collector
intentionally refuses to report a production PASS in that state.
The first deployment, secret installation, public registration capture,
registry review, ACTIVE deployment, segment re-proof, and final operational
sign-off remain account-authorized actions. The source Worker has only the
dedicated authority bucket and no shared `quant-structured` binding. D2/D3
remain operationally open until the exact live chain and environment/resource-
bound registry are activated with fresh keys and eligible segments are
re-proved through the deployed authority path.
