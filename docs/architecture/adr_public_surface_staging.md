# ADR: Public surface and staging topology

| Field | Value |
|-------|--------|
| **Status** | **Accepted** |
| **Date** | 2026-08-24 |
| **Lane** | H — public surface / staging topology |
| **Related** | [`../architecture.md`](../architecture.md) (MCP planes), [`../ci/workers_builds.md`](../ci/workers_builds.md) (operator map), [`llm_nav_map.md`](./llm_nav_map.md) |

**Hard constraints (unchanged):** Mass NO-GO · production READY undeclared · Phase 7 OFF · no production-promote this lane · GATEWAY_TOKEN service-binding remains **HOLD** (do not fake an unspoofable binding) · do not add SQL / R2 browse / ingest trigger / READY publish to Ops MCP · do not treat CF-Worker as auth.

---

## Decision

### 1. Public surface

The **only** public product surface is GitHub OAuth **read-only** Ops MCP
(`quant-platform-ops-read-mcp`). Remote callers get the existing 12 read tools.
Ops MCP must not grow SQL, D1/R2 handles, secret-read, shell, arbitrary URL
fetch, ingest/delete/publish, feature approve, or broker tools.

`workers_dev = true` stays on Ops MCP because the GitHub OAuth App callback is
`OAUTH_AUTHORIZATION_SERVER` (`https://quant-platform-ops-read-mcp.taku-haga.workers.dev`).
Disabling `workers_dev` without a replacement custom route would 404 `/callback`.
That is a documented exception, not a public research API.

### 2. Internal product workers

These workers are **not** public product surfaces. Wrangler 4.125.0 supports
`preview_urls`; they stay off so version preview URLs are not a research or
ingest API.

| Worker | Wrangler `name` | `workers_dev` | `preview_urls` | Surface |
|---|---|---|---|---|
| ingestion-premium | `quant-platform-ingestion-premium` | `false` | `false` | cron / internal |
| ingestion-jsda | `quant-platform-ingestion-jsda` | `false` | `false` | cron / internal |
| research-mass-eval | `quant-platform-research-mass-eval` | `false` | `false` | internal / admin |
| research-ai-gateway | `quant-platform-research-ai-gateway` | `false` | `false` | service binding only |

`research-ai-gateway` still deploys with `workers_dev=false` and no custom route
on wrangler 4.125.0.

### 3. Documented `workers_dev=true` exceptions

| Worker | Why `workers_dev` stays true | Residual |
|---|---|---|
| quant-ops-mcp | GitHub OAuth callback host (above) | keep read-only |
| ingestion-secrets | local runners reach the token-gated host; no custom zone | **HUMAN** Cloudflare Access / mTLS / Tunnel before flipping `workers_dev` off. Closing it now would silently break the secrets proxy. |
| ci-aggregate | receipt POST host without a custom zone | **not** a public research API (no PIT / eval / ingest / MCP). Lane G will abolish this Worker; this lane does **not** delete it. |

Do not treat a `*.workers.dev` hostname as network privacy. Inbound auth is the
fence where a host exists. Do not treat the Worker itself as auth.

### 4. Staging vs production

Staging Workers **must**:

1. Use **different Wrangler `name`s** (suffix `-staging`).
2. Bind **physically separate** D1, R2, KV, and secrets (distinct ids / buckets).
3. Live on a **HUMAN-created** Cloudflare account — not `[env.staging]` in the
   production `wrangler.toml` (that would deploy onto the production account).

This lane does **not** create those Cloudflare resources (**HUMAN**).
`platform/workers/*/wrangler.staging.toml` stubs omit production binding IDs
on purpose. Do not paste production D1 / KV ids or production R2 bucket names
into a staging file.

Secrets-proxy public Access / mTLS / Tunnel credentials are **HUMAN** if needed.

---

## Consequences

- Parse test: `tests/test_wrangler_public_surface.py` (offline `tomllib`).
- Operator map in `docs/ci/workers_builds.md` remains historical for CI
  receipts; this ADR is the public-surface / staging topology SoT.
- No live `wrangler deploy`, no staging account create, no production-promote.

## Residual

| Item | Owner |
|---|---|
| Cloudflare Access / mTLS / Tunnel for ingestion-secrets | **HUMAN** |
| Staging Cloudflare account + Worker names + D1/R2/KV/secrets | **HUMAN** |
| GATEWAY_TOKEN service-binding unspoofable replacement | **HOLD** |
| ci-aggregate abolish | Lane G |
