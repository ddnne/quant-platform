# Quant Ops Read MCP

Human-facing, GitHub-OAuth-protected operational MCP. The Worker has no
ingestion database binding and no write/admin/research-row tool.

```text
OAuth client
   -> QuantOpsMcpAgent
      -> OPS_PROJECTION_DB (immutable generation read model)
      -> QUOTA_DB          (daily quota + one-shot OAuth state nonce)

quant-ingest -> dedicated Ed25519 publisher -> OPS_PROJECTION_DB
```

`OPS_PROJECTION_DB` and `QUOTA_DB` are physically distinct in production and
staging. `platform/workers/ingestion-premium/migrations/` remains the sole
migration owner for `quant-ingest`.

## Tools

The remote surface contains 17 read tools:

`ops_status`, `source_inventory`, `endpoint_status`, `projection_status`,
`collection_sla_status`, `ingestion_last_run`, `dataset_coverage`,
`coverage_gaps`, `coverage_segments`, `backfill_status`, `validation_summary`,
`b0_status`, `latest_ready_snapshot`, `snapshot_quality`,
`raw_retention_status`, `sync_status`, and `storage_plane_status`.

Every tool reads the pointer-selected sealed generation only. Missing active
rows return `NOT_PROJECTED`; older generations and unsealed content rows are
never fallback data. `storage_plane_status` reads a publisher-materialized JSON
aggregate and does not scan ingestion facts.

The generation is accepted only after three checks: its
`ops-projection-signed-envelope/v1` Ed25519 signature verifies against the
digest-pinned committed `specs/ops_projection/verify_public_keys.json`, the
signed all-table content manifest hashes to the envelope `content_digest`, and
every table required by the selected tool is rehashed from D1. A valid
signature with mutated required content returns
`NOT_PROJECTED`. D1 triggers allow payload writes only while a generation is
`OPEN`; the transition to `SEALED` freezes every payload row before the active
pointer is changed. The committed registry contains public verification
material only. Its current authority state is `PENDING` with zero active keys,
so unsigned or formerly signed generations are not accepted as current.

All 17 tools publish closed `inputSchema` and `outputSchema` objects. The
deterministic SHA-256 over every tool name and both schemas is returned from
`tools/list` as `_meta["quant-platform/tool-schema-digest"]`; a reviewed digest
is frozen in the Worker and in
`specs/ops_projection/mcp_tool_schema_acceptance.json`, so acceptance fails
closed on unreviewed schema drift.

## Migrations

This component README does not authorize remote D1 mutation. `quant-ingest`
migrations are owned by the single JSDA cutover command under the same-D1 CAS
lease; the projection and quota databases remain separate migration targets.
Staging precedes production and the operator records immutable remote evidence.
See
[`docs/operations/current_production_runbook.md`](../../../docs/operations/current_production_runbook.md).

Wrangler resolves the independent source migration directories from each binding:

- `migrations/projection/`
- `migrations/quota/`

When that authority exists, staging must precede production. Back up
`quant-ingest` before the release sequence even though this Worker no longer
owns or writes that database.

## Publish

`ingestion-premium` is the only production publisher. Its scheduled handler
derives bounded metadata from `quant-ingest`, writes a create-only R2 export,
creates an `OPEN` generation in `OPS_PROJECTION_DB`, rehashes every projected
table, transitions it to `SEALED`, and moves the active pointer last. The old
Mac-local publisher is a refusal-only compatibility CLI and cannot mutate D1.

Signing remains operationally closed while the environment-specific registry
has no active key or the Worker signing/SPKI bindings are unprovisioned. Public
consumers use the chained, verify-only registries under
`specs/ops_projection/`; Python and Worker code pin their complete document
identity. Deploy Premium first, wait for a fresh `SEALED` generation, then let
`predeploy_ops_projection_gate.py` authorize the MCP deployment.

## Verify and deploy

```bash
npm ci
npm test
npm run typecheck
npm run types
npx wrangler deploy --dry-run --env=""
npx wrangler deploy --dry-run --env=production
npx wrangler deploy --dry-run --config=wrangler.staging.toml
```

`QuantOpsMcpAgent` remains on the feature-frozen, deprecated `McpAgent`
framework only for legacy session compatibility. `agents` is pinned to exact
version `0.17.4`; the lockfile bytes, resolved package integrity and actual
post-construction workerd prototype inventory are frozen in the active binding
manifest. The framework constructor copies inherited methods onto the product
prototype, so CI compares the complete descriptor chain rather than assuming
that `init` is the only RPC-visible method. Public MCP routing still exposes
only registered MCP methods: inherited `sql`, `agent` and `server` names return
JSON-RPC method-not-found and do not mutate the agent SQLite store.

Exact downloaded Worker-module bytes are the live deployment identity. Static
manifest version/digest fields embedded in that module bind those bytes to the
reviewed RPC and dependency inventory. The npm lockfile is therefore a
source/build input proved transitively through `npm ci`, the runtime bundle and
the exact module bytes; it is not claimed to be independently observable from
Cloudflare's live version API. No live acceptance or deploy is implied by these
source checks. The ordinary authenticated deployment acceptance brackets and
validates the selected live versions of all active Workers, rejecting any
unreviewed Service Binding or Durable Object stub into Quant Ops, and emits
canonical JSON for immutable release-evidence intake. See
[`docs/architecture/adr_quant_ops_mcpagent_migration.md`](../../../docs/architecture/adr_quant_ops_mcpagent_migration.md).

Production MCP URL:

`https://quant-platform-ops-read-mcp.taku-haga.workers.dev/mcp`

The GitHub OAuth callback is the same origin plus `/callback`. Unauthenticated
MCP calls must return `401`; `/health` and `/healthz` are liveness only.
OAuth state is authenticated only with the dedicated `STATE_SECRET` Worker
secret. Each signed state has a closed five-minute `issued_at`/`expires_at`
window and a random nonce recorded in `QUOTA_DB`; callback atomically deletes
that nonce before any GitHub request, so expiry and replay fail closed.
`GITHUB_CLIENT_SECRET` is provider authentication material and is never reused
as the state HMAC key. A missing state secret or nonce store fails before
authorization issuance or callback network I/O.
