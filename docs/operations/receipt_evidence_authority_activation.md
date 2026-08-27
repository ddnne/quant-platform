# Receipt Evidence Authority activation

This runbook activates the dedicated Receipt Evidence Authority without ever
making its HTTP surface public or exporting private signing material. The
checked-in production and staging configurations are intentionally
`AUTHORITY_MODE = "PENDING"`, omit `ACTIVATED_KEY_ID`, and set both
`workers_dev = false` and `preview_urls = false`.

The implementation commit does not provision Cloudflare resources, install a
secret, run a migration, deploy a Worker, register a key, or make an existing
receipt eligible for `COMPLETE`.

## Safety boundary

The authority Worker is callable only through its typed Service Binding. Its
`fetch()` handler returns a fixed `404` with `cache-control: no-store` for every
request. The only operator-facing registration path is the authenticated
Premium operation:

```text
POST /v1/admin/receipt-evidence/public-key-registration
```

That operation accepts no body and no query parameters, requires the existing
Premium `INGESTION_RUN_TOKEN`, and returns only the Ed25519 public-key
registration proposal. It cannot return the AES wrapping secret, wrapped
PKCS#8 ciphertext, or an unwrapped private key.

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
   `0016_receipt_authority_immutability.sql` have been reviewed and applied by
   the single ingestion migration owner.
5. The target D1/R2 bindings, Durable Object migration, and typed acquisition
   and receipt Service Bindings match the reviewed manifest.
6. Queue/DLQ backlog and current ingestion state have been recorded.
7. Production and staging wrapping secrets and Durable Object namespaces are
   treated as distinct authority domains.

Install the secret interactively, without putting its value on the command
line:

```sh
cd platform/workers/receipt-evidence-authority
npx wrangler secret put RECEIPT_KEY_WRAP_KEY --config wrangler.staging.toml
npx wrangler secret put RECEIPT_KEY_WRAP_KEY --config wrangler.toml --env production
```

Keep both configurations in `PENDING` and do not add `ACTIVATED_KEY_ID` yet.

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
- The authenticated Premium registration operation is the only way to trigger
  key creation and retrieve public registration data.
- No collection receipt, coverage state, READY state, or existing signed
  receipt becomes eligible because of this deployment.

Deploy and verify staging first. Deploy production PENDING only after the
staging evidence is reviewed. Use the repository's reviewed release workflow;
the illustrative Wrangler targets are:

```sh
cd platform/workers/receipt-evidence-authority
npx wrangler deploy --config wrangler.staging.toml
npx wrangler deploy --config wrangler.toml --env production
```

From an approved operator environment, call the Premium registration endpoint
with the token supplied through a protected environment variable or secret
manager. Do not enable shell tracing and do not print the token:

```sh
curl --fail-with-body --silent --show-error \
  --request POST \
  --header "X-Ingestion-Token: ${INGESTION_RUN_TOKEN}" \
  "${PREMIUM_ORIGIN}/v1/admin/receipt-evidence/public-key-registration"
```

Preserve the non-secret response, source/deployment SHA, environment, Worker
version, Durable Object generation, and response digest as immutable release
evidence. Confirm independently that:

- `algorithm` is exactly `Ed25519`;
- `authority_status` is exactly `PENDING`;
- `environment` matches the target environment;
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
`packages/data_plane/data_contracts/receipt_verify_public_keys.json` using the
captured public registration only:

1. Add exactly one `pending` Ed25519 key for the target authority.
2. Advance the registry generation and prior-registry digest chain.
3. Recompute and validate the canonical registry digest.
4. Confirm no other key became active and no revoked key was revived.
5. Merge the registry change through the required Cloudflare check.

No operator may infer or manually choose the activated key ID. It must equal
the exact `key_id` returned by the PENDING authority and merged into the
reviewed public-key registry.

## Deployment 2: ACTIVE

Activation is a separate reviewed change. Set:

```toml
AUTHORITY_MODE = "ACTIVE"
ACTIVATED_KEY_ID = "<exact reviewed registration key_id>"
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
5. Staging activation, exact-segment reconciliation, recovery, signature
   verification, and post-sign immutability smoke tests pass.
6. Rollback ownership and monitoring are live.

Deploy ACTIVE to staging first, retain its immutable evidence, then repeat the
review for production. A smoke reconciliation may pass only `dataset` and
`segment`; callers cannot supply counts, digests, pagination state, natural
keys, raw keys, or signatures. Verify the public key ID and signature against
the deployed registry, the operation event chain, the immutable raw and
structured objects, exact D1 natural-key readback, and terminal pagination
proof.

After production activation, re-prove the intended dataset segments through
this governed path. The previously reported 22 `COMPLETE` datasets do not
inherit eligibility from older or unsigned receipts. Do not publish profile
READY or run the controlled pilot until all independent READY gates pass.

## Recovery and rollback

The Premium request ledger persists `PREPARED` before RPC and scheduled
recovery resubmits only the opaque operation ID. Issuance, finalization, and
recovery are idempotent. A crash after signature issuance but before caller
finalization must recover the same receipt rather than mint a second one.

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
Staging and production remain PENDING and unprovisioned. The first deployment,
secret installation, public registration capture, registry review, ACTIVE
deployment, segment re-proof, and final operational sign-off remain explicit
human/account-authorized actions.
