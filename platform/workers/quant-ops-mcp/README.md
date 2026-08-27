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

This component README does not authorize remote D1 mutation. The canonical
manifest currently has no owner command for either target; staging and
production application needs a reviewed authority path and immutable remote
evidence. See
[`docs/operations/current_production_runbook.md`](../../../docs/operations/current_production_runbook.md).

Wrangler resolves the independent source migration directories from each binding:

- `migrations/projection/`
- `migrations/quota/`

When that authority exists, staging must precede production. Back up
`quant-ingest` before the release sequence even though this Worker no longer
owns or writes that database.

## Publish

The publisher creates an `OPEN` generation, inserts and verifies every expected
row count, seals it, and flips the active pointer last:

```bash
.venv/bin/python scripts/publish_ops_projection.py \
  --db data/structured/ingestion.sqlite \
  --refresh-coverage \
  --apply-remote
```

The publisher derives source/export cursors from the latest COMPLETE,
content-addressed authenticated D1 sync audit and requires exact equality with
the local applied cursor. Remote publication accepts only the governed local
mirror path. Production signing is disabled until a dedicated full-source
authority owns derivation and signing; HOME paths and environment private keys
are not signing inputs. Public consumers use the chained, verify-only registry
in `specs/ops_projection/verify_public_keys.json`. Python and Worker code pin
its complete document digest, body digest, generation, and prior audit pointer;
runtime vars cannot replace that root. Generation 1 is an audit-only revocation
record and is structurally unusable as a verifier registry.

No date is assumed for the storage hot window. A diagnostic render may supply a
reviewed `--storage-hot-cutoff YYYY-MM-DD`; remote publication rejects this
caller-selected policy until it is backed by a governed configuration.

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
source checks. See
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
