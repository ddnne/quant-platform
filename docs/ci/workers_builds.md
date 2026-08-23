# Workers Builds Git integration (no GitHub Actions)

**CI/CD lives on Cloudflare, not GitHub Actions.** Do not add `.github/workflows`.
ADR non-goal: “Adding GitHub Actions CI”
([`docs/architecture/adr_llm_friendly_refactor.md`](../architecture/adr_llm_friendly_refactor.md) §3.2).
Architecture: [`docs/architecture.md`](../architecture.md) — CI/CD is Cloudflare.

This document is the operator map for:

1. Per-worker **Workers Builds** Git integration (monorepo).
2. The **ci-aggregate** required GitHub commit status.
3. **Mandatory CI** versus **explicit promote**.

Mass / READY / GO stay unarmed. A green aggregate check is not production
publication and is not a research API.

## What Workers Builds is

[Workers Builds](https://developers.cloudflare.com/workers/ci-cd/builds/) connects
a GitHub repository to a Worker and runs a two-step job on push:

1. **Build command** (optional) — compile / test.
2. **Deploy command** — defaults to `npx wrangler deploy`.

[GitHub integration](https://developers.cloudflare.com/workers/ci-cd/builds/git-integration/github-integration/)
also posts:

- a **pull request comment** with build status and preview URLs
- **check runs** for each connected Worker in a [monorepo](https://developers.cloudflare.com/workers/ci-cd/builds/advanced-setups/#monorepos)

Those GitHub UI signals are **not** the merge gate. A PR comment is
informational. Per-worker check runs can skip when
[build watch paths](https://developers.cloudflare.com/workers/ci-cd/builds/build-watch-paths/)
do not match. Neither is a substitute for the aggregate required status.

## Six lanes (monorepo)

Connect **the same** GitHub repository `ddnne/quant-platform` to each of the
six product Workers. Set **root directory** to that Worker’s tree so Wrangler
`name` matches the dashboard Worker
([name requirement](https://developers.cloudflare.com/workers/ci-cd/builds/troubleshoot/#workers-name-requirement)).

| Worker | Root directory | Wrangler `name` |
|---|---|---|
| ingestion-jsda | `platform/workers/ingestion-jsda` | `quant-platform-ingestion-jsda` |
| ingestion-premium | `platform/workers/ingestion-premium` | `quant-platform-ingestion-premium` |
| ingestion-secrets | `platform/workers/ingestion-secrets` | `quant-platform-ingestion-secrets` |
| quant-ops-mcp | `platform/workers/quant-ops-mcp` | `quant-platform-ops-read-mcp` |
| research-ai-gateway | `platform/workers/research-ai-gateway` | `quant-platform-research-ai-gateway` |
| research-mass-eval | `platform/workers/research-mass-eval` | `quant-platform-research-mass-eval` |

Suggested **build command** (never `npm ci --legacy-peer-deps`):

```bash
npm ci && npm test
```

If a lane has no `test` script yet, the command still has to produce a
`pass`/`fail` receipt; a skipped lane is a missing receipt (fail).

`WORKERS_CI_COMMIT_SHA` is injected by Workers Builds and **must** be the
receipt `sha`. Do not invent a SHA.

## Mandatory CI vs explicit promote

Workers Builds will **upload a version** whenever the deploy command runs.
That is not the same as promoting the Active Deployment.

| Step | Command | When |
|---|---|---|
| Mandatory CI | build command (`npm ci && npm test`) + receipt POST | every push / PR that should merge |
| Version upload (optional, not promote) | `npx wrangler versions upload` | preview / non-production; or production-branch CI that must **not** go live |
| Explicit promote | `npx wrangler deploy` **or** dashboard promote of a specific version | operator, after the aggregate check is green **and** an explicit decision to ship |

**Do not** set the production-branch **deploy command** to `npx wrangler deploy`
for these six Workers. That would auto-promote on green CI.

Use `npx wrangler versions upload` as the production-branch deploy command (and
the non-production command). CI then proves the SHA; an operator promotes
later. Disconnecting Git does not replace this policy — the deploy command is
the switch
([disable automatic deployments](https://developers.cloudflare.com/workers/ci-cd/builds/#disconnecting-builds)).

Local pre-push remains [`scripts/verify_all.sh`](../../scripts/verify_all.sh)
(pytest + catalog freeze + worker `npm test`; no live deploy). That script is
not a GitHub check and does not promote.

## Aggregate required check

Worker: [`platform/workers/ci-aggregate`](../../platform/workers/ci-aggregate/)
(`quant-platform-ci-aggregate`).

**Not a research API.** `wrangler.toml` sets `workers_dev = true` only so lanes
can POST receipts without a custom zone. The `workers.dev` host is not a PIT /
eval / ingest / MCP surface.

### Receipts

Each lane POSTs `{worker, sha, result, command}`. The gate accepts a batch:

```http
POST /v1/receipts
Content-Type: application/json

{
  "receipts": [
    {
      "worker": "ingestion-jsda",
      "sha": "<WORKERS_CI_COMMIT_SHA 40-hex>",
      "result": "pass",
      "command": "npm ci && npm test"
    }
  ]
}
```

`worker` must be one of the six names above. `result` is `pass` or `fail`.
`command` is the lane command that actually ran.

A wrapper at the end of CI (or a seventh Builds job) POSTs the **six**
receipts together. Posting a PR comment, a Cloudflare check-run id, or a
preview URL does **not** count.

### Fail-closed rules

| Condition | Gate | GitHub `ci-aggregate` status |
|---|---|---|
| All six receipts, same HEAD SHA, all `pass` | ok | `success` (token required) |
| Any lane `fail` | not ok (`lane_failed`) | `failure` (never `success`) |
| Receipt SHAs differ | not ok (`sha_mismatch`) | `failure` (never `success`) |
| Missing worker receipt | not ok (`missing_receipt`) | `failure` (never `success`) |
| `GITHUB_STATUS_TOKEN` unbound | HTTP **503** | nothing posted |

The token is a GitHub PAT / fine-grained token with `repo:status` (or
`statuses: write`) on `ddnne/quant-platform`. Set it with
`wrangler secret put GITHUB_STATUS_TOKEN`. Do not put the value in git or
`wrangler.toml`. This Worker does not invent a token.

Status context: `ci-aggregate` (`GITHUB_STATUS_CONTEXT`). Branch protection
on the merge branch must **require** this context. Do not require Cloudflare’s
per-worker check runs as the sole gate, and do not treat the Workers Builds
PR comment as passing CI.

### Example lane receipt POST

After `npm test` in `platform/workers/ingestion-jsda`:

```bash
# result=pass only if npm test exited 0. SHA from Workers Builds, not from a comment.
printf '%s' "$RECEIPT_JSON" | curl -sS -X POST "$CI_AGGREGATE_URL/v1/receipts" \
  -H 'content-type: application/json' \
  --data-binary @-
```

The six-receipt batch is what the Worker evaluates. Incomplete batches fail
on `missing_receipt`.

## What this does not do

- Does not add GitHub Actions workflows.
- Does not run `npm ci --legacy-peer-deps`.
- Does not `wrangler deploy` to production as a side effect of a green check.
- Does not arm Mass / READY / GO.
- Does not read GitHub PR comments, issue comments, or check-run conclusions
  as inputs. Only POSTed receipts plus the bound status token.

## Public surfaces (preview vs production)

Do not publish every Worker on a stable `*.workers.dev` hostname.
Top-level config matches production (same Wrangler `name`; no `-production`
suffix). Production deploys use `--env production` (or `CLOUDFLARE_ENV=production`).
Default `wrangler deploy` without `--env` still targets the top-level Worker;
wrangler 4.x warns to pass `--env=""` or `--env production` when named envs exist.

Preview is **version Preview URLs** (`preview_urls = true`), not a second
product hostname. Those URLs are not a public research API, not public
research execution, and not an ingest API.

| Worker | Wrangler `name` | Preview | Production `workers_dev` | Public surface |
|---|---|---|---|---|
| quant-ops-mcp | `quant-platform-ops-read-mcp` | `workers_dev=true` (OAuth callback host) | `true` | remote public, OAuth required, read-only |
| research-ai-gateway | `quant-platform-research-ai-gateway` | `preview_urls` only | `false` | service binding only; not a public research API |
| research-mass-eval | `quant-platform-research-mass-eval` | `preview_urls` only | `false` | internal/admin; no public research execution |
| ingestion-premium | `quant-platform-ingestion-premium` | `preview_urls` only | `false` | cron/internal |
| ingestion-jsda | `quant-platform-ingestion-jsda` | `preview_urls` only | `false` | cron/internal |
| ingestion-secrets | `quant-platform-ingestion-secrets` | `workers_dev=true` (token-gated proxy host) | `true` | narrow authenticated proxy |

`research-ai-gateway` keeps `[ai]`; `research-mass-eval` keeps service binding
`AI_GATEWAY` and must not bind `env.AI`. wrangler 4.125.0 still dry-runs the
gateway with `workers_dev=false` (no custom route). Ops MCP does not gain
arbitrary SQL, URL fetch, ingest triggers, delete, READY publication, feature
approve, broker/order, shell, or secret-read tools.
