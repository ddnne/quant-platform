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
production --format json` for all six Workers and requires the exact frozen
secret-name set. It reads names and binding kinds only; values are never
requested or printed. Missing authentication, missing names, and unexpected
names all fail closed. Wrangler is `4.125.0`.

## 2. Apply D1 migrations through canonical owners

Do not hand-loop a subset of SQL files. Do not apply Ops projection SQL to
`quant-ingest`. `ingestion-premium` owns `quant-ingest`; `quant-ops-mcp` owns
`quant-ops-projection` and `quant-ops-quota`.

### quant-ingest 0013 quarantine

Do **not** run generic `wrangler d1 migrations apply quant-ingest` while
`0013_restore_specialized_jquants_schema.sql` is pending. Its additive
`IF NOT EXISTS` statements cannot distinguish an absent object from a
same-name malformed object, and a migration-history row does not prove exact
postflight. Migration 0013 stays quarantined until one reviewed authority
orchestrates all of the following against the same authenticated D1 identity:

1. bind `environment`, binding, database name, and database ID to the canonical
   manifest rather than caller input;
2. create and verify a recoverable encrypted backup plus the provider restore
   bookmark before any apply;
3. run exact preflight with no attached/TEMP deputy, accepting only absent or
   exact canonical `sqlite_master`/PRAGMA structure;
4. apply the exact reviewed 0013 checksum after confirmed 0012;
5. run independent exact postflight even when 0013 already has a history row,
   then bind the pre/post schema digests and observed history to immutable
   release evidence.

[`scripts/d1_specialized_schema_validation.py`](../../scripts/d1_specialized_schema_validation.py)
implements only read-only local SQLite validation. It does not authenticate a
live D1, create a backup/bookmark, apply SQL, or mint release evidence. Its
machine-readable result remains `UNVERIFIED` and cannot close A2 or A6. Until
the governed orchestration above exists, stop rather than bypass this hold.

```bash
.venv/bin/python scripts/cloudflare_d1_migration_manifest.py

cd platform/workers/quant-ops-mcp
npx wrangler d1 migrations apply quant-ops-projection --remote --env production
npx wrangler d1 migrations apply quant-ops-quota --remote --env production
cd ../../..
```

JSDA observation identity lives in
`platform/workers/ingestion-premium/migrations/0012_jsda_observation_identity.sql`
and precedes quarantined migration 0013 in the canonical `quant-ingest` chain.

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
