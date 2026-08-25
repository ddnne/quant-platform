# Quant Ops Read MCP

Human-facing, GitHub-OAuth-protected operational MCP. The Worker has no
ingestion database binding and no write/admin/research-row tool.

```text
OAuth client
   -> QuantOpsMcpAgent
      -> OPS_PROJECTION_DB (immutable generation read model)
      -> QUOTA_DB          (daily per-subject quota only)

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

The generation is accepted only after its
`ops-projection-signed-envelope/v1` Ed25519 signature verifies against
`OPS_PROJECTION_VERIFY_KEYS_JSON`. The committed empty registry is deliberate:
until a production public key is provisioned, an otherwise active generation
remains `NOT_PROJECTED`.

## Migrations

```bash
cd platform/workers/quant-ops-mcp

npx wrangler d1 migrations apply quant-ops-projection --remote \
  --config=wrangler.toml
npx wrangler d1 migrations apply quant-ops-quota --remote \
  --config=wrangler.toml
```

Wrangler resolves the independent migration directories from each binding:

- `migrations/projection/`
- `migrations/quota/`

Apply staging first with `wrangler.staging.toml`. Back up `quant-ingest` before
the release migration/deploy sequence even though this Worker no longer owns or
writes that database.

## Publish

The publisher appends a complete generation and flips the active pointer last:

```bash
.venv/bin/python scripts/publish_ops_projection.py \
  --db data/structured/ingestion.sqlite \
  --refresh-coverage \
  --source-cursor "$SOURCE_CURSOR" \
  --export-cursor "$EXPORT_CURSOR" \
  --projection-signing-key-id "$OPS_PROJECTION_KEY_ID" \
  --apply-remote
```

The publisher loads only the dedicated private key from
`QUANT_OPS_PROJECTION_SIGNING_KEY_PEM`, an explicit
`--projection-signing-key` path, or
`~/.config/quant-platform/ops_projection_signing_key.pem`. It never falls back
to Receipt or READY keys. Public consumers use
`specs/ops_projection/verify_public_keys.json`; the Worker receives the same
registry as `OPS_PROJECTION_VERIFY_KEYS_JSON`.

No date is assumed for the storage hot window. Supply a reviewed date with
`--storage-hot-cutoff YYYY-MM-DD`, or the aggregate reports that window as
`NOT_PROJECTED`.

## Verify and deploy

```bash
npm install
npm test
npm run typecheck
npm run types
npx wrangler deploy --dry-run --env=""
npx wrangler deploy --dry-run --env=production
npx wrangler deploy --dry-run --config=wrangler.staging.toml
```

Production MCP URL:

`https://quant-platform-ops-read-mcp.taku-haga.workers.dev/mcp`

The GitHub OAuth callback is the same origin plus `/callback`. Unauthenticated
MCP calls must return `401`; `/health` and `/healthz` are liveness only.
