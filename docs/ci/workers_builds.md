# Workers Builds Git integration (no GitHub Actions)

**CI/CD lives on Cloudflare, not GitHub Actions.** Do not add `.github/workflows`.
ADR non-goal: “Adding GitHub Actions CI”
([`docs/architecture/adr_llm_friendly_refactor.md`](../architecture/adr_llm_friendly_refactor.md) §3.2).
Architecture: [`docs/architecture.md`](../architecture.md) — CI/CD is Cloudflare.

This document is the operator map for:

1. **Repo-root Workers Build** whose build command is [`scripts/verify_ci.sh`](../../scripts/verify_ci.sh).
2. The **native GitHub check run** posted by the Cloudflare Workers & Pages GitHub App (required check).
3. Product-lane Builds (informational only).
4. Deprecated **ci-aggregate** receipts (not proof a Cloudflare Build ran).

Mass / READY / GO stay unarmed. A green check is not production publication and is
not a research API.

**The native GitHub App check does not exist live in this commit.** Isolation
does not connect the App, does not change branch protection, and does not
claim CI mandatory complete.

## Authority (required check)

**Merge authority** is the GitHub **check run** that the
[Cloudflare Workers & Pages GitHub App](https://github.com/apps/cloudflare-workers-and-pages)
posts when the **repo-root** Workers Build runs `scripts/verify_ci.sh`.

That check is proof a Cloudflare Build executed the script. Caller-supplied
receipts are not.

| Signal | Role |
|---|---|
| Native GitHub check from the Cloudflare GitHub App (repo-root Build) | **required** merge check, once a HUMAN connects the App and sets branch protection **expected source** to that App |
| Six product-lane Workers Builds / PR comments / per-worker check runs | **informational** |
| `ci-aggregate` Worker + PAT `GITHUB_STATUS_TOKEN` + `CI_LANE_TOKEN` receipts | **deprecated** — not SoT; abolish **after** the native check exists. Do not delete [`platform/workers/ci-aggregate`](../../platform/workers/ci-aggregate/) in this change |

Branch protection must require the native check **from that App** (expected
source / `checks[].app_id` = Cloudflare Workers & Pages). A PAT-posted context
named `ci-aggregate` is not a substitute for a Cloudflare Build.

## Repo-root Build (authoritative)

Connect **one** Workers Build on repository `ddnne/quant-platform`:

| Setting | Value |
|---|---|
| Root directory | repository root (`.`) |
| Build command | `bash scripts/verify_ci.sh` |
| Deploy command | **not** `npx wrangler deploy` of a product Worker. Do not auto-promote. Use a no-op or `npx wrangler versions upload` of a dedicated non-product CI Worker **after** a HUMAN creates it |
| Watch paths | unset (always run `verify_ci.sh`) |

[`scripts/verify_ci.sh`](../../scripts/verify_ci.sh) is fail-closed:

- Bootstraps `.venv` with Python 3.11+ when missing (`python3.11` or `python3` that is 3.11+; never system 3.9). Then `pip install -e ".[dev]"`.
- `pytest tests/`, catalog freeze, Evaluation IR schema/codec.
- All seven workers: `package-lock.json` required, `npm ci`, `npm test`, `npm run typecheck`, `wrangler deploy --dry-run`, types `--check`.
- Missing lockfile or missing `node_modules` (do not skip) is a fail.
- Never `npm ci --legacy-peer-deps`.
- Never live product `wrangler deploy`.
- No `VERIFY_*` skip flags. Do not add `.github/workflows`.

Workers Builds injects `WORKERS_CI_COMMIT_SHA`. Do not invent a SHA.

## HUMAN steps (native check is not live yet)

Isolation does **not** do these. Do not mint `CI_LANE_TOKEN` / `GITHUB_STATUS_TOKEN`.
Do not deploy production.

1. Install and connect the Cloudflare Workers & Pages GitHub App on `ddnne/quant-platform`.
2. Create/connect the repo-root Workers Build with the table above.
3. Set branch protection / ruleset **required status checks** to that native check, with **expected source** = the Cloudflare GitHub App. Do not leave PAT context `ci-aggregate` as the sole required check once the native check exists.
4. Fail/pass smoke: a **fail** SHA must be unmergeable; a **pass** SHA must post the native App check (not a hand-rolled status).

Until those steps land, CI is **not** mandatory-complete.

## Product lanes (informational)

Connect **the same** GitHub repository `ddnne/quant-platform` to each of the
six product Workers if operators want per-Worker preview/history. Set **root
directory** to that Worker’s tree so Wrangler `name` matches the dashboard
Worker
([name requirement](https://developers.cloudflare.com/workers/ci-cd/builds/troubleshoot/#workers-name-requirement)).

These Builds are **informational**. They are not the merge gate. Watch-path
skips do not fail the repo-root `verify_ci.sh` check.

| Worker | Root directory | Wrangler `name` |
|---|---|---|
| ingestion-jsda | `platform/workers/ingestion-jsda` | `quant-platform-ingestion-jsda` |
| ingestion-premium | `platform/workers/ingestion-premium` | `quant-platform-ingestion-premium` |
| ingestion-secrets | `platform/workers/ingestion-secrets` | `quant-platform-ingestion-secrets` |
| quant-ops-mcp | `platform/workers/quant-ops-mcp` | `quant-platform-ops-read-mcp` |
| research-ai-gateway | `platform/workers/research-ai-gateway` | `quant-platform-research-ai-gateway` |
| research-mass-eval | `platform/workers/research-mass-eval` | `quant-platform-research-mass-eval` |

Suggested **build command** on a product lane (never `npm ci --legacy-peer-deps`):

```bash
npm ci && npm test
```

A skipped product lane is not a missing merge receipt. The repo-root Build
already ran every worker through `verify_ci.sh`.

## Mandatory CI vs explicit promote

Workers Builds will **upload a version** whenever the deploy command runs.
That is not the same as promoting the Active Deployment.

| Step | Command | When |
|---|---|---|
| Mandatory CI | repo-root build command `bash scripts/verify_ci.sh` | every push / PR that should merge |
| Version upload (optional, not promote) | `npx wrangler versions upload` | preview / non-production; or production-branch CI that must **not** go live |
| Explicit promote | `npx wrangler deploy` **or** dashboard promote of a specific version | operator, after the native check is green **and** an explicit decision to ship |

**Do not** set any production-branch **deploy command** to `npx wrangler deploy`
for the six product Workers. That would auto-promote on green CI.

Use `npx wrangler versions upload` as the production-branch deploy command (and
the non-production command) on product lanes. Disconnecting Git does not replace
this policy — the deploy command is the switch
([disable automatic deployments](https://developers.cloudflare.com/workers/ci-cd/builds/#disconnecting-builds)).

Local **mandatory** CI is the same script: [`scripts/verify_ci.sh`](../../scripts/verify_ci.sh).
[`scripts/verify_all.sh`](../../scripts/verify_all.sh) is a fast local helper only.
Six-lane `npm test` runs skip Python/catalog and are **not** `verify_ci`.

[Workers Builds](https://developers.cloudflare.com/workers/ci-cd/builds/) Git
integration also posts a **pull request comment** and per-worker **check runs**
in a [monorepo](https://developers.cloudflare.com/workers/ci-cd/builds/advanced-setups/#monorepos).
A PR comment is informational. Per-worker check runs can skip when
[build watch paths](https://developers.cloudflare.com/workers/ci-cd/builds/build-watch-paths/)
do not match. Neither is a substitute for the repo-root native check.

## ci-aggregate (deprecated)

Worker: [`platform/workers/ci-aggregate`](../../platform/workers/ci-aggregate/)
(`quant-platform-ci-aggregate`).

**Deprecated.** `POST /v1/receipts` accepts caller-supplied `{worker, sha, result, command}`.
That is not proof a Cloudflare Build ran `verify_ci.sh`. A client with
`CI_LANE_TOKEN` can post `pass` without Workers Builds.

Keep the Worker **in tree**. `verify_ci.sh` still typechecks it. **Abolish** the
Worker, PAT `GITHUB_STATUS_TOKEN`, and `CI_LANE_TOKEN` **after** the native
GitHub App check exists and is the required check with the expected source set.
Do not delete the Worker in this change. Do not mint those tokens here.

Print-only first-deploy helper (still print-only; not a producer):
[`scripts/ci_aggregate_first_deploy.sh`](../../scripts/ci_aggregate_first_deploy.sh).

**Not a research API.** `wrangler.toml` sets `workers_dev = true` only so a
receipt POST host can exist without a custom zone.

Historical receipt shape (do not treat as merge SoT):

```http
POST /v1/receipts
Content-Type: application/json
X-CI-Lane-Token: <CI_LANE_TOKEN>
```

Unbound or blank `CI_LANE_TOKEN` → HTTP **503**. Wrong header → HTTP **401**.
Do not accept a GitHub PR comment as a success signal.

## What this does not do

- Does not add GitHub Actions workflows.
- Does not run `npm ci --legacy-peer-deps`.
- Does not skip missing `node_modules` or missing lockfiles.
- Does not `wrangler deploy` to production as a side effect of a green check.
- Does not arm Mass / READY / GO.
- Does not claim the Cloudflare native check exists live.
- Does not mint `CI_LANE_TOKEN` / `GITHUB_STATUS_TOKEN`.

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
