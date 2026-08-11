# Quant Ops Read MCP (remote)

This Cloudflare Worker is the human-facing MCP endpoint for browser and mobile
clients. It exposes current operational status over MCP Streamable HTTP at
`/mcp`. The Python stdio server remains an offline development adapter.

The remote server is deliberately Ops-only. It does not return research fact
rows and has no SQL, D1/R2 handle, secret, shell, arbitrary URL fetch,
ingestion trigger, deletion, publication, feature approval, or broker tool.
`latest_ready_snapshot` and `snapshot_quality` return bounded publication
metadata only; a Research Read MCP must not be enabled until Cloudflare can pin
and verify a published immutable READY generation.

## Tools

- `ops_status`, `ingestion_last_run`
- `dataset_coverage`, `coverage_gaps`, `coverage_segments`
- `backfill_status`, `validation_summary`, `b0_status`
- `latest_ready_snapshot`, `snapshot_quality`
- `raw_retention_status`, `sync_status`

Every result says whether it came from mutable `ops_current` state or immutable
`research_ready` publication metadata.

## Authentication and authorization

Put the Worker behind a Cloudflare Access application and configure Cloudflare
Managed OAuth (or an equivalent OAuth authorization server) for the MCP
client-facing flow. The Worker publishes OAuth protected-resource metadata at
`/.well-known/oauth-protected-resource` and still validates the Access JWT
signature, issuer, audience, and expiry itself.

Required OAuth resource scope: `quant.read.ops`. Cloudflare Managed OAuth
forwards a normal Access assertion to the origin; that assertion does not
contain the OAuth scope or client ID. Therefore the dedicated Access
application/AUD is itself the server-side `quant.read.ops` authorization
boundary. Do not share this Access application with research or write APIs.
Human quota keys use Access `sub` plus the authenticated `identity_nonce`
(managed-OAuth grant/session); service-token keys use `common_name`, the
Access service client ID.

Reserve `quant.read.research` for a separately deployed Research Read server.
Write scopes belong to separate services and must never be granted to this
Worker. Human identity tokens and automation service tokens are kept as
different principal kinds. Automation should use an Access service token and
its own OAuth client identity; it must not reuse a person's browser token.

Cloudflare setup references:

- [Remote MCP server and OAuth](https://developers.cloudflare.com/agents/model-context-protocol/guides/remote-mcp-server/)
- [Validate Access JWTs in a Worker](https://developers.cloudflare.com/cloudflare-one/access-controls/applications/http-apps/authorization-cookie/validating-json/)
- [MCP Streamable HTTP transport](https://modelcontextprotocol.io/specification/2025-06-18/basic/transports)

Configure these public Wrangler variables before deploy:

- `ACCESS_TEAM_DOMAIN`: `<team>.cloudflareaccess.com`
- `ACCESS_AUD`: Access application audience tag
- `OAUTH_AUTHORIZATION_SERVER`: Managed OAuth issuer advertised to clients
- `ALLOWED_ORIGINS`: exact comma-separated browser origins
- `DAILY_ROW_QUOTA`: positive per-principal/client/UTC-day limit

The checked-in placeholders fail closed. Do not store a JWT, service-token
secret, or OAuth client secret in `wrangler.toml`.

## D1 and deployment

`OPS_DB` points at the existing `quant-ingest` D1 control database. Apply the
ingestion Coverage V2 migration first, then this Worker's durable-quota
migration:

```bash
npx wrangler d1 execute quant-ingest --remote \
  --file=../ingestion-premium/migrations/0007_collection_coverage_v2.sql

npx wrangler d1 execute quant-ingest --remote \
  --file=migrations/0001_remote_daily_quota.sql

npx wrangler d1 execute quant-ingest --remote \
  --file=migrations/0002_ops_projection.sql
```

After local Coverage V2 evaluation and READY verification, refresh the bounded
read projection out-of-band (this is not an MCP tool):

```bash
.venv/bin/python scripts/export_ops_projection.py \
  --db data/structured/ingestion.sqlite \
  --snapshot-dir data/research_snapshots \
  --output /tmp/quant-ops-projection.sql

npx wrangler d1 execute quant-ingest --remote \
  --file=/tmp/quant-ops-projection.sql
```

If the projection is absent, coverage tools return `UNKNOWN` plus every
governed JQ/JSDA dataset as a gap; they never turn a missing table into an
empty-success result.

Install, verify, and deploy from this directory:

```bash
npm install
npm test
npm run typecheck
npx wrangler deploy
```

Production endpoint:

```text
https://quant-platform-ops-read-mcp.<account-subdomain>.workers.dev/mcp
```

An unauthenticated MCP request must return `401`:

```bash
curl -i https://quant-platform-ops-read-mcp.<account-subdomain>.workers.dev/mcp \
  -H 'content-type: application/json' \
  -H 'accept: application/json, text/event-stream' \
  --data '{"jsonrpc":"2.0","id":1,"method":"initialize"}'
```

For authenticated smoke, obtain a token through the configured OAuth/Access
flow (MCP Inspector is convenient) and call `initialize`, `tools/list`, then
`ops_status`. Never paste or commit the token. The repository tests exercise
the same unauthorized and authenticated paths with ephemeral keys.

## ChatGPT connection

In ChatGPT's remote MCP/connectors settings, add the production `/mcp` URL.
The client reads protected-resource metadata, opens the configured OAuth flow,
and requests `quant.read.ops`. Availability of custom remote MCP connections
depends on the user's ChatGPT workspace/plan; server-side acceptance can still
be completed with MCP Inspector and the automated tests here.

The local command below is for offline development only and is not the browser
or mobile connection path:

```bash
.venv/bin/python -m mcp_servers.quant_data \
  --snapshot-dir data/research_snapshots \
  --ops-db data/structured/ingestion.sqlite
```
