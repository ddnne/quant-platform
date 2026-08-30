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

The interactive product surface is GitHub OAuth **read-only** Ops MCP
(`quant-platform-ops-read-mcp`). Remote callers get the existing 17 read tools.
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
| research-ai-gateway | `quant-platform-research-ai-gateway` | `false` | `false` | service binding only |

`research-ai-gateway` still deploys with `workers_dev=false` and no custom route
on wrangler 4.125.0.

### 3. Documented `workers_dev=true` exceptions

| Worker | Why `workers_dev` stays true | Residual |
|---|---|---|
| quant-ops-mcp | GitHub OAuth callback host (above) | keep read-only |
| ingestion-secrets | local runners reach the token-gated host; no custom zone | **HUMAN** Cloudflare Access / mTLS / Tunnel before flipping `workers_dev` off. Closing it now would silently break the secrets proxy. |
| research-mass-eval | one-person, token-gated personal DRAFT Container; no custom zone | exact-four only; at most two instances during runner rollover; one job per named Container; Mass/READY/GO remain closed |

Do not treat a `*.workers.dev` hostname as network privacy. Inbound auth is the
fence where a host exists. Do not treat the Worker itself as auth.

### 4. Staging vs production

Staging Workers **must**:

1. Use **different Wrangler `name`s** (suffix `-staging`).
2. Bind **physically separate** D1, R2, KV, Queue, and secrets (distinct ids /
   buckets), even when they live in the same Cloudflare account.
3. Use standalone `wrangler.staging.toml`, not `[env.staging]` in production
   configuration, so a production deploy cannot select staging accidentally.

The operational-closure lane created empty, staging-only resources on
2026-08-24: D1 `quant-ingest-staging`, R2 `quant-raw-staging` and
`quant-structured-staging`, KV `quant-ops-mcp-oauth-staging`, and JSDA work/DLQ
Queues. `platform/workers/*/wrangler.staging.toml` binds only those resources.
No production secret was copied. The staging secrets proxy is private
(`workers_dev=false`, `preview_urls=false`) until a service-binding consumer is
available. `research-mass-eval` staging is the token-gated personal DRAFT
exception: `workers_dev=true`, `preview_urls=false`, `MASS_EVAL_TOKEN`
required, no custom domain. Do not treat that hostname as network privacy.

---

## Consequences

- Parse test: `tests/test_wrangler_public_surface.py` (offline `tomllib`).
- Operator map in `docs/ci/workers_builds.md` remains historical for CI
  receipts; this ADR is the public-surface / staging topology SoT.
- Staging resource creation and version upload do not promote production.

## Residual

| Item | Owner |
|---|---|
| Cloudflare Access / mTLS / Tunnel for ingestion-secrets | **HUMAN** |
| Separate staging OAuth application and staging-only secrets | **HUMAN** |
| GATEWAY_TOKEN service-binding unspoofable replacement | **HOLD** |
| caller-supplied CI receipt aggregator | **retired**; native Cloudflare GitHub App check is the only merge authority |
