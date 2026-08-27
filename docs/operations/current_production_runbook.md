# Current production runbook

<!-- CURRENT_PRODUCTION_RUNBOOK -->

This is the **only executable production operations document**. Historical
Phase 6.1 / 6.2 runbooks are non-executable. Live GO flags live in
[`../phase62_residual_status.md`](../phase62_residual_status.md). Review findings
live in [`../phase633_finding_ledger.md`](../phase633_finding_ledger.md).

Do not print secret values. Check presence only.

## Canonical machine-readable authorities

| Authority | Path | Check command |
|-----------|------|----------------|
| D1 migration owners, order, checksums | [`specs/cloudflare/d1_migration_manifest.json`](../../specs/cloudflare/d1_migration_manifest.json) | `.venv/bin/python scripts/cloudflare_d1_migration_manifest.py` |
| Active Worker bindings, toolchain, observability | [`specs/cloudflare/active_worker_bindings.json`](../../specs/cloudflare/active_worker_bindings.json) | `.venv/bin/python scripts/cloudflare_binding_manifest.py` |
| Ops read tool inventory | [`platform/workers/quant-ops-mcp/src/domain.js`](../../platform/workers/quant-ops-mcp/src/domain.js) `OPS_TOOLS` | count `tool("` entries in `OPS_TOOLS` |
| Native CI | [`scripts/verify_ci.sh`](../../scripts/verify_ci.sh) | `scripts/verify_ci.sh` |
| Authenticated production acceptance | [`scripts/verify_cloudflare_deployment_acceptance.sh`](../../scripts/verify_cloudflare_deployment_acceptance.sh) | `scripts/verify_cloudflare_deployment_acceptance.sh` |

`applied_state` in the migration manifest is `UNVERIFIED` on purpose. Record
remote apply results only in immutable release evidence.

## Honest holds

- **Cloudflare Access / Zero Trust:** `ingestion-secrets` workers.dev is not
  Access-protected until a human initializes Zero Trust on the account. Header
  token remains enabled. Do not treat that HOLD as closed.
- **Controlled Pilot:** **NO-GO** until live evidence in
  `docs/phase62_residual_status.md` passes. Green tests do not arm exact-four.
- **Release evidence:** publication is **PENDING/HOLD**. Normalized caller JSON
  is schema-only and cannot prove any remote response. The dedicated signed
  release-observation authority has zero active keys and is not implemented;
  see `specs/cloudflare/release_observation_authority.json`. A6 remains OPEN.
- **Mass Research:** **NO-GO**. Mass talks to Gateway only through typed
  Service Binding RPC `GatewayService`. `GATEWAY_TOKEN` is HTTP defense in
  depth if a closed route is attached later; it is not a shared Mass
  credential.
- **AM history:** do not treat V2 monthly AM completeness as a current target.
  V3 AM is tip-scoped. Residual PARTIAL rows are not permission to mint empty
  COMPLETE receipts.
- **Authority reachability:** the manifest covers one Cloudflare Receipt
  authority and six local OS principals. All six local principals now have
  source-level runner, runtime-config, distinct UID/socket/store/key-backend and
  launchd/bootstrap paths; READY publication is client-only and Trader and
  Controlled are bound to fixed root-owned activation documents. This is not
  operational activation: passive READY preflight is `PENDING/UNKNOWN`, zero
  local principals are provisioned, active keys/credentials remain zero, and
  R5, R10, R11 and A2 remain `OPEN`.
- **Staged activation:** source now includes a narrow Receipt staging ACTIVE
  validator and a Cron-only `AUDIT_ONLY` recovery canary whose operator RPC is
  read-only. The canary has dedicated Durable Object state/events, never calls
  ordinary Receipt issue/recover, and stores only its signed attestation in the
  Premium D1. The validator checks exact source/module/deployment/binding/
  migration/secret names, the pinned one-key registry, the real Ed25519
  signature and the complete initial/first-recovery/replay-confirmation digest
  chain. The first recover call remains unsigned and pending; only a second
  identical recover call appends the authority-owned replay event and signs the
  final attestation. It remains
  research-ineligible and cannot create Coverage or `TRUSTED_COLLECTION`.
  The gate binds an immutable authority-version/caller-version/key/registry
  pair. Every authority deploy, key rotation or registry change therefore
  requires a coordinated Premium redeploy after the authority and a new
  version-scoped D1 audit row. Old rows and attestations are never mutated or
  reused; the gate rejects an old authority attestation and rejects a new one
  until the newer Premium caller version is selected.
  The Receipt Durable Object's exact five-method RPC inventory is frozen in the
  binding manifest; internal key/state/event helpers are JavaScript-private and
  unavailable to workerd RPC. All four named WorkerEntrypoints separately pin
  ordinary RPC methods and the reserved `fetch` special.
  This is still operational HOLD: the operator caller principal, active key,
  migration, deploy and live evidence are absent. Do not add a general bypass
  or execute ACTIVE instructions yet. The all-P0 gate remains mandatory for
  final release, READY eligibility and Controlled Pilot.
- **Equities master:** the closed acquisition route is available only as
  `ACTIVE_RAW_ONLY`; COMPLETE/reproof eligibility remains
  `PENDING_AUTHORITY_ACTIVATION`. The current generated registry expresses
  those two axes by listing `equities_master` as both routed and PENDING. Do not
  interpret route availability as COMPLETE eligibility; the next contract PR
  must split those axes explicitly.

## 1. Preconditions

```bash
test -n "${INGESTION_RUN_TOKEN:-}" && echo INGESTION_RUN_TOKEN=present
test -n "${DATA_EXPORT_TOKEN:-}" && echo DATA_EXPORT_TOKEN=present
test -n "${CLOUDFLARE_API_TOKEN:-}" && echo CLOUDFLARE_API_TOKEN=present
test -n "${CLOUDFLARE_ACCOUNT_ID:-}" && echo CLOUDFLARE_ACCOUNT_ID=present
npx wrangler whoami
scripts/verify_cloudflare_deployment_acceptance.sh
```

Stop if production D1/R2/Queue names or IDs differ from
`specs/cloudflare/active_worker_bindings.json`. Every active environment has
`preview_urls = false`, `observability.enabled = true`,
`head_sampling_rate = 1`, and `[version_metadata] binding = "CF_VERSION_METADATA"`.
The authenticated acceptance gate also runs `wrangler secret list --env
production --format json` for all seven active Workers and requires the exact frozen
secret-name set. It reads names and binding kinds only; values are never
requested or printed. Missing authentication, missing names, and unexpected
names all fail closed. Wrangler is `4.125.0`.

## 2. D1 migration policy: source-only HOLD

Do not hand-loop SQL files or run a remote D1 migration command from this
revision. `ingestion-premium` remains the source owner for `quant-ingest`, and
`quant-ops-mcp` remains the source owner for `quant-ops-projection` and
`quant-ops-quota`, but source ownership is not remote mutation authority. The
frozen manifest deliberately sets the `quant-ingest` owner command to `null`,
remote mutation to `false`, and both staging and production to `HOLD`.

Migration 0012 copies the populated v2 JSDA graph into a separately constrained
v3 graph, installs v2-to-v3 bridge triggers before copying, and never drops v2
data. Every statement is resumable, but neither a migration-history row nor a
local file proves exact remote schema, data preservation, exclusion, or the
source SHA that executed.

[`scripts/d1_ingestion_migration_validation.py`](../../scripts/d1_ingestion_migration_validation.py)
provides exact local preflight/postflight validation. The current
[`scripts/apply_ingestion_d1_migrations.py`](../../scripts/apply_ingestion_d1_migrations.py)
is a fail-closed observation/HOLD and recovery implementation despite its
legacy filename; it publishes no authorized remote apply path. In particular:

1. the canonical reservation identity is exactly environment, canonical D1
   database ID, source SHA, and canonical manifest digest;
2. a local `O_EXCL` reservation is only a crash/audit marker on one host. It is
   not a durable cross-host lock and never authorizes remote mutation;
3. staging remains `HOLD` until a trusted remote lock supplies cross-host
   exclusion and a control-plane attestation binds the executing source SHA;
4. production obtains staging evidence by independently querying and exporting
   the canonical staging D1 binding. It accepts no caller staging JSON, path,
   encrypted backup, or key, and remains `HOLD` even when staging is exact until
   the same trusted control plane attests the staging source SHA;
5. Time Travel bookmarks and verified AES-256-GCM exports are rollback material
   only. A backup, its key, restore result, or digest is never migration or
   staging authority;
6. exact preflight, simulated canonical replay, exact postflight, empty FK
   check, exact history, and v2/v3 preservation remain mandatory after a future
   authority is added. They do not substitute for that authority.

The recovery command classifies a fresh canonical observation with exactly
these semantics:

- `APPLIED` (`RECOVERED_APPLIED_EXACT`): exact canonical postflight and zero
  pending migrations;
- `NOT_APPLIED` (`RECOVERED_NOT_APPLIED`): the live identity, bookmark,
  validation result, and pending inventory exactly match the recorded preflight
  baseline;
- `UNKNOWN`: every unavailable, changed, partial, malformed, or otherwise
  ambiguous state.

Recovery classification does not prove which source SHA performed an earlier
mutation, grant mutation authority, initiate rollback, or authorize a blind
retry. `UNKNOWN` remains `HOLD` for manual investigation. Before publishing any
remote apply procedure, implement and independently review a trusted remote
lock/control-plane service keyed by the canonical reservation identity and
capable of producing a source-SHA attestation.

The source-manifest consistency check does not contact or mutate Cloudflare:

```bash
.venv/bin/python scripts/cloudflare_d1_migration_manifest.py
```

If a prior HOLD observation already created the canonical `UNKNOWN`
reservation for the exact clean source SHA and manifest, the following recovery
command is permitted. It performs read-only live D1 queries/exports and changes
only that canonical local reservation; it accepts no caller path, database,
backup, key, evidence, run ID, or source SHA. It never applies or rolls back a
remote migration:

```bash
.venv/bin/python scripts/apply_ingestion_d1_migrations.py \
  --environment staging \
  --recover
```

Use `--environment production` only to classify an existing production
reservation. A terminal recovery result remains evidence, not remote mutation
authority. Any error leaves `UNKNOWN` in place and blocks retry/promotion.

JSDA observation identity lives in
`platform/workers/ingestion-premium/migrations/0012_jsda_observation_identity.sql`
and precedes migration 0013 in the canonical `quant-ingest` chain. The Worker
reads/writes v3 after this source revision. Do not roll it back to a v2-only
Worker while retaining post-cutover D1 state. A rollback across this boundary
is coordinated: stop writers, restore the recorded Time Travel bookmark (or
verified encrypted export), then restore the old Worker. AES material supports
that rollback only; it does not authorize it. Any unrecorded prefix,
recorded-but-partial state, or malformed state is `UNKNOWN`, remains `HOLD`, and
requires review rather than automatic resume.

When a future trusted authority applies the migration, it intentionally leaves
`jsda_v3_cutover_control.phase` at `bridge`. The v3 Worker returns/retries
`JSDA_V3_CUTOVER_PENDING` and the v2 bridge rejects stale updates that would
overwrite newer v3 state. Do not hand edit the singleton. Activation requires a
separate reviewed authority that proves Cron/producer/consumer disablement,
zero in-flight leases, the deployed v3 source SHA, and an immutable
drain-evidence digest before setting `v3_active`; the database then aborts any
late v2 insert/update. That activation authority is not implemented by the
HOLD/recovery script or the production Worker entrypoint. The production
entrypoint uses an explicitly disabled verifier: even a hand-written, formally
valid `v3_active` row reports `AUTHORITY_DISABLED` and cannot enable product
work. Source migration readiness is therefore not a claim that production JSDA
is already cut over.

`GET /health` is liveness only and reports `product_ready` plus the observed
cutover phase. It must never be used as the JSDA product smoke. Deployment
acceptance must call `GET /health/ready` and require HTTP 200,
`product_ready:true`, and `cutover:"V3_ACTIVE"` for the deployed source SHA and
version. The canonical release observation must bind its response digest to the
collector provenance digest. A generic `GET /health` `PASS`, a mismatched
digest, or HTTP 503 with `PENDING`/`AUTHORITY_DISABLED` is not a successful
product deployment.

There is currently no reachable collector for that endpoint: JSDA has
`workers_dev=false`, `preview_urls=false`, no route, and no Service Binding
consumer in the frozen binding manifest. Therefore JSDA product smoke and
release publication remain HOLD. Do not substitute caller-supplied HTTP JSON;
a future private Service Binding collector must capture and authority-sign the
exact response bytes for staging and production.

## 3. Publish the signed Ops projection

Projection SQL is applied only to `quant-ops-projection`.

```bash
.venv/bin/python scripts/publish_ops_projection.py \
  --db data/structured/ingestion.sqlite \
  --snapshot-dir data/research_snapshots \
  --apply-remote
```

The publisher refuses a COMPLETE-count regression and requires the dedicated
Ops projection signing key. See
[`projection_publish_guard.md`](projection_publish_guard.md).

## 4. Remote Ops MCP

The repository surface is the frozen `OPS_TOOLS` list in
`platform/workers/quant-ops-mcp/src/domain.js` (**17** tools, including
`storage_plane_status`). Live Cloudflare may lag; do not operate from a 16-tool
memory. Unauthenticated `/mcp` must be `401`.

```bash
curl -i "$QUANT_OPS_MCP_URL/mcp" \
  -H 'content-type: application/json' \
  -H 'accept: application/json, text/event-stream' \
  --data '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"curl-smoke","version":"1"}}}'
```

## 5. JSDA rolling locators

Current-year / current-file JSDA URLs are re-observed per governed run. Dated
archive URLs stay one observation. Each observation gets a D1-owned monotonic
sequence; `current_*` never regresses to an older completion. Artifacts are
content-addressed and may be observed from more than one SourceObject.
Discovery PASS is run-closure, not root-job completion: queued, running, or
transient descendants keep the run nonterminal; a rejected descendant is never
PASS. Cron roots are daily-stable. Queue redelivery of a completed observation
is idempotent, repairs ancestor aggregates, and does not permanently complete a
rolling URL.

```bash
curl -fsS -X POST \
  -H "X-Ingestion-Token: $INGESTION_RUN_TOKEN" \
  "$INGESTION_JSDA_URL/v1/run"
```

## 6. Failure rules

- Persist D1/R2 evidence before Queue ack. Evidence-write failure retries.
- Invalid Queue bodies keep reject/DLQ audit evidence without caller values.
- Controlled Pilot and Mass remain NO-GO until residual live evidence passes.
- Access HOLD remains open until a human initializes Zero Trust.
