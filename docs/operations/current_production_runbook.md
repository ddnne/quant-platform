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

- **Cloudflare Access / Zero Trust:** last recorded HOLD is that
  `ingestion-secrets` workers.dev is not Access-protected until Zero Trust is
  initialized; header token remains enabled. Access was **not remeasured** on
  2026-09-10. Do not treat the HOLD as closed, and do not treat it as a fresh
  Access observation.
- **Controlled Pilot:** **NO-GO** until live evidence in
  `docs/phase62_residual_status.md` passes. Green tests do not arm exact-four.
  Runtime still separately enforces signed READY, signed Trader authorization,
  an immutable snapshot, signed projection, and BudgetLedger occupancy.
- **READY publication path:** signing exists at
  `platform/workers/ingestion-premium/src/ready_publication.ts` (source-only
  move from `platform/workers/research-mass-eval`; not rolled out; existing
  Mass staging secret provisioning history is unchanged and actual cutover is
  not done), but there is no cloud candidate-preparation or orchestration
  caller/Service Binding.
  Source includes an undeployed read-only `POST /v1/export/receipt-products`
  descriptor; it does not check profile completeness or physical availability
  and is not READY. Premium Ops metadata still does not bind exact dependency
  scope, raw retention, or validation proofs; those remain a distinct pending
  workflow integration. The Trader production signer is absent. The release
  builder is unconditionally PENDING. Wire the existing trust root; do not add
  another authority. Activating keys alone does not close any of these gaps.
  A metadata-only Ops envelope is not READY.
- **Release evidence:** publication is **PENDING/HOLD**. Normalized caller JSON
  is schema-only and cannot prove any remote response. The dedicated signed
  release-observation authority has zero active keys and is not implemented;
  see `specs/cloudflare/release_observation_authority.json`. A6 remains OPEN.
- **Mass Research:** **NO-GO**. Mass talks to Gateway only through typed
  Service Binding RPC `GatewayService`. `GATEWAY_TOKEN` is HTTP defense in
  depth if a closed route is attached later; it is not a shared Mass
  credential.
- **Mass product-lane deploy trigger:** deployment leg held. Trigger
  `b83cc2ee-8a40-4448-b517-80959796eb3e` had only its deploy command replaced
  via the Cloudflare API; build and test still run. Read-back verified
  `2026-09-09T15:04Z`. Original deploy command:
  `npm run deploy --prefix platform/workers/research-mass-eval`. Temporary
  deploy command:
  `python3 -c "raise SystemExit('DEPLOYMENT HOLD: coordinated staging rollout pending; see current_production_runbook.md')"`.
  Authoritative repo-root CI is unchanged. Restore only after staged then
  production Secrets→Gateway→Mass code rollout is accepted. Smoke must not
  execute market data or Containers. Global live acceptance is the final
  check, not a blocker for prerequisite Worker code rollout. This bounded
  repair does not run D1 migration, JSDA activation, or DLQ mutation.
- **JSDA cutover follow-ups (open):** whole shared-D1 Time Travel restore is
  removed from the operator. A Time Travel bookmark remains recovery-reference
  evidence only; Premium and Receipt writers are not fenced. `--rollback`
  refuses with `FORWARD_REPAIR_REQUIRED` and does not restore D1, resume old
  delivery, or roll a v2-only Worker onto v3 data. Production JSDA no longer
  declares a DLQ consumer; the main Queue still dead-letters onto
  `quant-jsda-ingestion-dlq`. This source change does not close Receipt
  checkpoint/O(N²), scoped READY, or any live rollout. A concrete incident
  needs its own reviewed forward correction from live state.
- **Quant Ops legacy agent:** `QuantOpsMcpAgent` remains on deprecated,
  feature-frozen `McpAgent` for un-inventoried legacy `/sse` compatibility.
  Source CI pins `agents` and the lock bytes and measures the complete
  post-construction workerd prototype. Exact module-byte acceptance is the live
  identity and transitively binds the embedded binding-manifest digest. It also
  brackets all active production Worker versions and rejects any live binding,
  handler, migration or runtime drift, including external Quant Ops Service
  Bindings and Durable Object stubs. The lockfile itself is not claimed as a
  live API observation. No deploy or legacy client drain has occurred. Follow
  [`../architecture/adr_quant_ops_mcpagent_migration.md`](../architecture/adr_quant_ops_mcpagent_migration.md): migrate `/mcp` to `createMcpHandler`, then drain
  `/sse` only after a real client inventory.
- **AM history:** do not treat V2 monthly AM completeness as a current target.
  V3 AM is tip-scoped. Residual PARTIAL rows are not permission to mint empty
  COMPLETE receipts.
- **Authority reachability:** Paper-only trust is the existing Cloudflare
  Receipt evidence authority, READY publisher, environment-scoped public-key
  registries, typed Service Bindings, content-addressed R2 snapshot, and
  BudgetLedger occupancy. Local six-principal OS users, root installers,
  WebAuthn, and external-anchor ceremonies are not production tasks on this
  path. Operational activation remains open: Receipt is PENDING-only, READY
  and trader registries have active keys=0, no accepted READY sidecar exists,
  no signed FRESH projection has been produced, Coverage V3 cloud transition
  is unaccepted, and A2, D2, D3, R5, R10, R11, C4 and C10 remain `OPEN`.
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
  or execute ACTIVE instructions yet. The all-P0 gate remains the final
  release checklist. Runtime Worker paths separately enforce keys, READY,
  Trader authorization, and BudgetLedger occupancy; those checks are not the
  all-P0 gate.
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

## 2. D1 migration policy: single Cloudflare operator

Do not hand-loop SQL files or invoke `wrangler d1 migrations apply` directly.
`ingestion-premium` owns the `quant-ingest` chain; the only staging/production
mutation entry is:

```bash
.venv/bin/python scripts/activate_jsda_v3_cutover.py --environment staging --activate --yes
# After staging is ACTIVATED at the same reviewed source SHA:
.venv/bin/python scripts/activate_jsda_v3_cutover.py --environment production --activate --yes
```

Use `scripts/apply_ingestion_d1_migrations.py --environment ENV --check` for a
read-only observation. The canonical chain currently ends at
`0023_mutation_lease`; never apply only a prefix.

Migration 0012 copies the populated v2 JSDA graph into a separately constrained
v3 graph, installs v1/v2 retire triggers, and never drops v1/v2 data. Every
statement is resumable, but neither a migration-history row nor a local file
proves exact remote schema, data preservation, exclusion, or the source SHA
that executed.

[`scripts/d1_ingestion_migration_validation.py`](../../scripts/d1_ingestion_migration_validation.py)
provides exact ephemeral schema/history validation. The operator then:

1. records a small create-only control intent before changing JSDA Cron;
2. stops JSDA Cron, observes two stable drains, pauses the JSDA main Queue, and
   verifies the drain again so a post-pause enqueue cannot race the bookmark.
   This does not stop Premium or Receipt writers on the shared D1;
3. records a Time Travel bookmark as recovery-reference evidence before applying
   any migration. The bookmark is not restore authority;
4. acquires the same-D1 CAS lease, crosses the `remote_spawned` fence, applies
   the canonical chain with a bounded Wrangler subprocess, and verifies exact
   schema/history;
5. activates the new source SHA and restores the exact prior JSDA Queue/Cron
   state.

The local control intent is a few-kilobyte crash-recovery cache, not authority.
Remote D1 plus live Cloudflare version/config/Queue/Cron observations are the
source of truth. Whole-file local D1 exports are not part of cutover. The
operator does not restore `quant-ingest` / `quant-ingest-staging` via Time
Travel. `--rollback` fails closed with `FORWARD_REPAIR_REQUIRED`. Use `--check`
for read-only diagnosis. Any concrete incident requires an independently
reviewed forward corrective migration or compatible Worker release.

The source-manifest consistency check does not contact or mutate Cloudflare:

```bash
.venv/bin/python scripts/cloudflare_d1_migration_manifest.py
```

If the process exits after it has created a run, resume only that run ID:

```bash
.venv/bin/python scripts/activate_jsda_v3_cutover.py \
  --environment staging --resume --run-id RUN_ID --yes
```

`--rollback --yes` is a policy refusal, not a restore. It does not mutate Cron,
Queue, D1, Worker versions, leases, or local evidence.

JSDA observation identity lives in
`platform/workers/ingestion-premium/migrations/0012_jsda_observation_identity.sql`
and precedes migration 0013 in the canonical `quant-ingest` chain. The Worker
reads/writes v3 after this source revision. Do not deploy a v2-only Worker
against post-cutover D1 state. Reverse Worker rollback after a shared-D1
restore is removed from this operator.

When 0012 is applied it leaves `jsda_v3_cutover_control.phase` at `bridge`.
Safe JSDA writer sequence is: stop old v1/v2 Cron and the JSDA main consumer,
drain leases/jobs/main queue to zero, persist the bookmark as evidence, migrate,
deploy and activate v3. Product Cron/Queue stay fail-closed until
`v3_active`. Activation is one-way; D1 forbids reverse transition, INSERT
OR REPLACE, and late v1 `jsda_acquisition_jobs` writes.

[`scripts/activate_jsda_v3_cutover.py`](../../scripts/activate_jsda_v3_cutover.py)
directly observes Cloudflare state. `--check` never mutates. `--activate`
requires double-observed zero JSDA jobs/leases/backlog, stopped JSDA Cron and
main Queue delivery, the production main dead-letter route without a production
DLQ consumer, canonical bindings, and a pre-migration Time Travel bookmark used
only as recovery-reference evidence.
Production additionally requires a remote staging `ACTIVATED` run for the same
source SHA plus matching live Worker/config/Queue/Cron observations. Caller
JSON or a local admission file is not authority. Cloud Ops Projection
publication is the ingestion-premium scheduled publisher, not Mac-local SQLite.

`GET /health` is liveness only. Deployment acceptance must call
`GET /health/ready` and require HTTP 200, `product_ready:true`,
`cutover:"V3_ACTIVE"`, `activated_source_sha` equal to the Cloudflare build
commit SHA, plus distinct `cutover_config_digest` and
`drain_evidence_digest`. A generic `GET /health` `PASS` is not product
deployment.

The JSDA Worker has no public route. Cutover acceptance therefore uses the
remote D1 activation record and authenticated Cloudflare control-plane
observations; `/health/ready` remains an internal product-readiness response,
not migration authority.

## 3. Publish the signed Ops projection (HOLD)

Do not publish from Mac-local `data/structured/ingestion.sqlite` or
`data/research_snapshots`. Persistent data is R2 authority plus D1 metadata;
Container SQLite is ephemeral only.

Safe cloud-only order, still HOLD:

1. Apply projection/quota migrations `0001`/`0002` to **staging** dedicated D1
   (`quant-ops-projection-staging`, `quant-ops-quota-staging`).
2. Publish one SEALED generation from the ingestion-premium scheduled
   publisher into the dedicated staging projection D1. Mac-local
   `publish_ops_projection.py --apply-remote` is disabled. Do not switch MCP
   traffic onto an empty dedicated D1. `npm run deploy` in quant-ops-mcp
   fails closed unless a signed SEALED active generation is present.
3. Deploy staging MCP bound to the dedicated staging projection/quota D1.
4. 17-tool / schema / generation smoke against staging.
5. Repeat migrate/publish for production dedicated D1.
6. Switch production MCP bindings only after a SEALED generation exists.
7. Production 17-tool smoke.

Until the cloud-side publisher exists, keep live MCP on its current binding
and leave dedicated projection/quota DBs unpublished. See
[`projection_publish_guard.md`](projection_publish_guard.md) for the
COMPLETE-count guard once a publisher exists.

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
