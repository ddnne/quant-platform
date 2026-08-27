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
- **Staged activation:** the current all-P0 strict gate correctly rejects a
  release, but it also blocks the positive smoke needed to close the same OPEN
  rows. Do not add a general bypass or execute ACTIVE instructions yet. The
  next PR must introduce a narrowly scoped, expiring
  authority/action/environment/SHA/resource-bound staged gate and mark every
  canary output research-ineligible. The all-P0 gate remains mandatory for
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

## 2. Apply D1 migrations through canonical owners

Do not hand-loop a subset of SQL files. Do not apply Ops projection SQL to
`quant-ingest`. `ingestion-premium` owns `quant-ingest`; `quant-ops-mcp` owns
`quant-ops-projection` and `quant-ops-quota`.

### quant-ingest guarded 0011-0018 sequence

Do **not** run generic `wrangler d1 migrations apply quant-ingest` for this
chain. Migration 0012 now copies the populated v2 JSDA graph into a separately
constrained v3 graph, installs v2-to-v3 bridge triggers before copying, and
never drops v2 data. Every statement is resumable, but a migration-history row
alone still does not prove exact schema or data preservation. The canonical
owner is `scripts/apply_ingestion_d1_migrations.py`; it orchestrates all of the
following against the same authenticated D1 identity:

1. bind `environment`, binding, database name, and database ID to the canonical
   manifest rather than caller input;
2. create and verify a recoverable encrypted backup plus the provider restore
   bookmark before any apply;
3. run exact preflight with no attached/TEMP deputy, accepting only absent or
   exact canonical `sqlite_master`/PRAGMA structure;
4. simulate every pending canonical migration on a local copy of the remote
   export, including interruption recovery and v2/v3 preservation;
5. preflight all local paths as resolve-distinct, private, create-only paths,
   publish PREPARED evidence, and occupy the final evidence pathname with a
   durable `REMOTE_APPLY_AUTHORIZED_STATE_UNKNOWN_UNTIL_FINALIZED` reservation;
6. apply the exact manifest chain through the pinned local Wrangler;
7. take a second independent remote export and require exact schema, exact
   migration history, empty FK check, and v2/v3 row preservation;
8. atomically replace only the unchanged reservation with evidence binding the
   bookmark, encrypted backup checksum, pre/post digests, source SHA, manifest,
   database, and environment. If apply or postflight fails, the reservation is
   retained as an auditable remote-state-unknown marker and retry is refused.

[`scripts/d1_specialized_schema_validation.py`](../../scripts/d1_specialized_schema_validation.py)
remains the narrow 0013 semantic contract. The guarded owner additionally uses
[`scripts/d1_ingestion_migration_validation.py`](../../scripts/d1_ingestion_migration_validation.py)
for the complete chain. Both production and staging database name/ID and
migration table come only from the canonical manifest; caller-supplied database
identity is not accepted. Production also cross-binds staging top-level,
preflight, postflight, encrypted-backup database identity, manifest digest, and
backup restore source SHA; a valid old backup cannot be relabelled for a newer
source SHA.

```bash
.venv/bin/python scripts/cloudflare_d1_migration_manifest.py

cd platform/workers/ingestion-premium
npm ci
cd ../../..

# First: distinct staging account/resources and a staging-only backup key.
.venv/bin/python scripts/apply_ingestion_d1_migrations.py \
  --environment staging \
  --backup-target /secure/private/quant-ingest-staging.preapply.sql.enc \
  --backup-key /secure/private/d1_staging_backup_aes256.key \
  --prepare-evidence-target /secure/private/quant-ingest-staging.prepared.json \
  --evidence-target /secure/private/quant-ingest-staging.migration.json

# Review staging postflight, then use the exact same merged source SHA.
.venv/bin/python scripts/apply_ingestion_d1_migrations.py \
  --environment production \
  --backup-target /secure/private/quant-ingest.preapply.sql.enc \
  --backup-key /secure/private/d1_production_backup_aes256.key \
  --prepare-evidence-target /secure/private/quant-ingest.prepared.json \
  --evidence-target /secure/private/quant-ingest.migration.json \
  --staging-evidence /secure/private/quant-ingest-staging.migration.json \
  --staging-backup /secure/private/quant-ingest-staging.preapply.sql.enc \
  --staging-backup-key /secure/private/d1_staging_backup_aes256.key

cd platform/workers/quant-ops-mcp
npx wrangler d1 migrations apply quant-ops-projection --remote --env production
npx wrangler d1 migrations apply quant-ops-quota --remote --env production
cd ../../..
```

JSDA observation identity lives in
`platform/workers/ingestion-premium/migrations/0012_jsda_observation_identity.sql`
and precedes migration 0013 in the canonical `quant-ingest` chain. The Worker
reads/writes v3 after this source revision. Do not roll it back to a v2-only
Worker while retaining post-cutover D1 state. A rollback across this boundary
is coordinated: stop writers, restore the recorded Time Travel bookmark (or
verified encrypted export), then restore the old Worker. A failed unrecorded
prefix should instead be resumed only through the same guarded owner; a
recorded-but-partial or malformed state fails closed and requires review.

Migration success intentionally leaves `jsda_v3_cutover_control.phase` at
`bridge`. The v3 Worker returns/retries `JSDA_V3_CUTOVER_PENDING` and the v2
bridge rejects stale updates that would overwrite newer v3 state. Do not hand
edit the singleton. Activation requires a separate reviewed authority that
proves Cron/producer/consumer disablement, zero in-flight leases, the deployed
v3 source SHA, and an immutable drain-evidence digest before setting
`v3_active`; the database then aborts any late v2 insert/update. That activation
authority is not part of this migration apply command or the production Worker
entrypoint. The production entrypoint uses an explicitly disabled verifier:
even a hand-written, formally valid `v3_active` row reports
`AUTHORITY_DISABLED` and cannot enable product work. A future change must add
and review signed, authority-bound activation verification and wire that
positive capability before product readiness can become true. Source migration
readiness is therefore not a claim that production JSDA is already cut over.

`GET /health` is liveness only and reports `product_ready` plus the observed
cutover phase. It must never be used as the JSDA product smoke. Deployment
acceptance must call `GET /health/ready` and require HTTP 200,
`product_ready:true`, and `cutover:"V3_ACTIVE"` for the deployed version. HTTP
503 with `PENDING` or `AUTHORITY_DISABLED` is the expected fail-closed result
until the separate signed cutover authority exists and completes; it is not a
successful product deployment.

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
