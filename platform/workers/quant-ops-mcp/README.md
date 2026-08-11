# Quant Ops Read MCP (remote, GitHub OAuth)

Human-facing Ops MCP for **browser / mobile ChatGPT & Claude**, using the
**same mechanism as `news-mcp`**:

```text
ChatGPT / Claude Connector
        │ OAuth (GitHub login = ALLOWED_LOGIN)
        ▼
workers-oauth-provider  (/authorize /token /register)
        │
        ▼
QuantOpsMcpAgent (/mcp, Durable Object)
        │
        ▼
OPS_DB (quant-ingest D1 projection) — read only
```

No research fact rows, no SQL, no ingestion/admin tools.

## Tools

`ops_status`, `ingestion_last_run`, `dataset_coverage`, `coverage_gaps`,
`coverage_segments`, `backfill_status`, `validation_summary`, `b0_status`,
`latest_ready_snapshot`, `snapshot_quality`, `raw_retention_status`, `sync_status`

## Auth (news-compatible)

- GitHub OAuth via `@cloudflare/workers-oauth-provider`
- Only `ALLOWED_LOGIN` (default `ddnne`) may complete login
- KV binding **must** be named `OAUTH_KV`

### Secrets

```bash
npx wrangler secret put GITHUB_CLIENT_ID
npx wrangler secret put GITHUB_CLIENT_SECRET
# optional: npx wrangler secret put STATE_SECRET
```

### GitHub OAuth App

Create (or reuse) a GitHub OAuth App with callback:

```text
https://quant-platform-ops-read-mcp.taku-haga.workers.dev/callback
```

Homepage can be the Worker origin. Scope used: `read:user`.

If reusing the **news-mcp** OAuth App, add the quant callback URL as an
additional Authorization callback URL (GitHub allows multiple on some plans /
settings; otherwise create a dedicated App).

## Deploy

```bash
cd platform/workers/quant-ops-mcp
npm install
npm test
npx wrangler deploy
```

Apply D1 migrations once (if not already):

```bash
npx wrangler d1 execute quant-ingest --remote \
  --file=migrations/0001_remote_daily_quota.sql
npx wrangler d1 execute quant-ingest --remote \
  --file=migrations/0002_ops_projection.sql
```

## Endpoints

| Path | Auth | Purpose |
|------|------|---------|
| `/mcp` | OAuth Bearer | Streamable HTTP MCP |
| `/sse` | OAuth Bearer | Legacy SSE transport |
| `/authorize`, `/token`, `/register`, `/callback` | OAuth | Authorization server |
| `/healthz` | none | Liveness |
| `/.well-known/oauth-protected-resource` | none | Resource metadata |

Production URL:

```text
https://quant-platform-ops-read-mcp.taku-haga.workers.dev/mcp
```

## Connect from ChatGPT (phone) / Claude

Same as news-mcp:

1. Open Connectors / remote MCP settings
2. Add URL: `https://quant-platform-ops-read-mcp.taku-haga.workers.dev/mcp`
3. Complete **GitHub** login as `ddnne`
4. Call e.g. `ops_status`, `coverage_gaps`

Unauthenticated:

```bash
curl -i https://quant-platform-ops-read-mcp.taku-haga.workers.dev/mcp \
  -H 'content-type: application/json' \
  -H 'accept: application/json, text/event-stream' \
  --data '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"t","version":"0"}}}'
# expect 401 + WWW-Authenticate
```

## Local stdio (dev only)

```bash
.venv/bin/python -m mcp_servers.quant_data \
  --snapshot-dir data/research_snapshots
```

Not for phone/browser.
