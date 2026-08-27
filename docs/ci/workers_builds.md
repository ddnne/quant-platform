# Workers Builds Git integration (no GitHub Actions)

**CI/CD lives on Cloudflare, not GitHub Actions.** Do not add `.github/workflows`.
ADR non-goal: “Adding GitHub Actions CI”
([`docs/architecture/adr_llm_friendly_refactor.md`](../architecture/adr_llm_friendly_refactor.md) §3.2).
Architecture: [`docs/architecture.md`](../architecture.md) — CI/CD is Cloudflare.

This document is the operator map for:

1. **Repo-root Workers Build** whose build command is
   [`scripts/workers_builds_verify_ci.sh`](../../scripts/workers_builds_verify_ci.sh),
   which hands authority to [`scripts/verify_ci.sh`](../../scripts/verify_ci.sh).
2. The **native GitHub check run** posted by the Cloudflare Workers & Pages GitHub App (required check).
3. Product-lane Builds (informational only). The dedicated Receipt authority is
   intentionally excluded from those ordinary product lanes and uses its
   reviewed PENDING/ACTIVE two-deployment procedure.

Mass / READY / GO stay unarmed. A green check is not production publication and is
not a research API.

**The native GitHub App check is live and required on `main`.** Its expected
source is pinned to the Cloudflare Workers & Pages GitHub App; a same-named PAT
status cannot satisfy branch protection.

Current live operator state (2026-08-25 JST):

- Cloudflare repository connection:
  `31c86c8c-0883-4b4b-a8ca-dd821817dfab`
  (`github`, account `ddnne`, repository `ddnne/quant-platform`).
- Private CI Worker: `quant-platform-ci-aggregate-staging`; script tag
  `6fb2d1474f884b33aa2be98b6a4bcacf`. The CI deploy command is the no-op
  `true`, so a green check publishes no product Worker.
- Build token UUID: `c43eaa86-018f-47c3-a67d-327f98b424d6`; name:
  `Workers Builds - quant-platform root CI - 2026-08-25`. The secret value was
  neither retrieved nor recorded.
- Non-production trigger: `d9d45236-635c-42cc-a966-6360a6f3c076`; production
  trigger: `53389400-a65c-467f-9634-72861cc3fe68`. Both use repository root
  `/`, build `bash scripts/workers_builds_verify_ci.sh`, deploy `true`, cache
  disabled, and `SKIP_DEPENDENCY_INSTALL=1`.
- Native context: `Workers Builds: quant-platform-ci-aggregate-staging`, GitHub
  App ID `85455`. Build `ce57148b-6c5f-4fc0-9edf-fcf15948011a` passed at commit
  `9b2397f1067781741b0bd8d72b5bc8015a42fec2`; check run `97625670308` concluded
  `success`.

## Authority (required check)

**Merge authority** is the GitHub **check run** that the
[Cloudflare Workers & Pages GitHub App](https://github.com/apps/cloudflare-workers-and-pages)
posts when the **repo-root** Workers Build runs `scripts/verify_ci.sh`.

That check is proof a Cloudflare Build executed the script. Caller-supplied
receipts are not.

| Signal | Role |
|---|---|
| Native GitHub check from the Cloudflare GitHub App (repo-root Build) | **required** merge check; `main` pins context `Workers Builds: quant-platform-ci-aggregate-staging` to App ID `85455` |
| Six ordinary product-lane Workers Builds / PR comments / per-worker check runs | **informational**; the dedicated Receipt authority is not a product lane |

Branch protection requires the exact native context above with expected source
`checks[].app_id = 85455`. A PAT-posted context named `ci-aggregate` is not a
substitute for a Cloudflare Build.

## Repo-root Build (authoritative)

Connect **one** Workers Build on repository `ddnne/quant-platform`:

| Setting | Value |
|---|---|
| Root directory | repository root (`.`) |
| Build command | `bash scripts/workers_builds_verify_ci.sh` |
| Deploy command | `true` (no-op; never product publication or auto-promotion) |
| Watch paths | unset (always run `verify_ci.sh`) |

Set build variable `SKIP_DEPENDENCY_INSTALL=1`. The repository wrapper probes
the documented Ubuntu 24.04 image's `/usr/bin/python3` for Python 3.11+ and an
actual in-memory SQLite query, creates `.venv` with Cloudflare's preinstalled
`pipx` and pinned `virtualenv`, then `exec`s the authoritative
[`scripts/verify_ci.sh`](../../scripts/verify_ci.sh). It fails closed on image,
interpreter, SQLite, or bootstrap drift; it does not require root, apt, or an
asdf rebuild.

[`scripts/verify_ci.sh`](../../scripts/verify_ci.sh) is fail-closed:

- Validates the pinned finding ledger and reports OPEN operational P0 rows.
  This merge check is not the production finding-ledger release gate.
- Uses pinned `uv 0.11.26` and `uv sync --frozen --extra dev` with the tracked lockfile.
- `pytest tests/`, catalog freeze, Evaluation IR schema/codec.
- Seven active workers run in parallel: `package-lock.json` required, `npm ci`, `npm test`, `npm run typecheck`, generated types `--check`, and Wrangler dry-runs for base, production, and isolated staging.
- [`active_worker_bindings.json`](../../specs/cloudflare/active_worker_bindings.json) freezes D1, R2, Queue/DLQ, Durable Object, Service Binding, Cron, vars, and secret names. Values of secrets are never read or stored.
- Wrangler `[secrets].required` declarations are part of generated Env exactness for base and production. Staging declares no production secrets.
- Wrangler, TypeScript, and Cloudflare Worker types are exact-version policy across all active workers.
- Missing lockfile or missing `node_modules` (do not skip) is a fail.
- Never `npm ci --legacy-peer-deps`.
- Never live product `wrangler deploy`.
- No `VERIFY_*` skip flags. Do not add `.github/workflows`.

The merge check is deliberately non-deploying and does not receive production
secret-management authority. Before a production migration or deploy, run the
authenticated read-only
[`scripts/verify_cloudflare_deployment_acceptance.sh`](../../scripts/verify_cloudflare_deployment_acceptance.sh).
It first runs the strict [`finding_ledger_gate.py`](../../scripts/finding_ledger_gate.py),
then reruns `verify_ci.sh` and compares each live production `wrangler secret
list --format json` name set to the frozen manifest. It never requests or emits
secret values and fails closed on an OPEN P0, authentication, or inventory
drift.

Workers Builds injects `WORKERS_CI_COMMIT_SHA`. Do not invent a SHA.

## Required-check activation and smoke evidence

- `main` branch protection remains strict and now requires only the exact native
  context with expected source App ID `85455`. Admin enforcement and the other
  protection fields were preserved.
- Failure smoke PR #34: native check `FAILURE`; GitHub reported
  `mergeStateStatus=BLOCKED`. The disposable branch was then deleted.
- Success smoke PR #33, temporarily evaluated against `main` at
  `9b2397f1067781741b0bd8d72b5bc8015a42fec2`: native check `SUCCESS`; GitHub
  reported `mergeStateStatus=CLEAN`. The PR was restored to its original stacked
  base and Draft state after the observation.
- No `CI_LANE_TOKEN` or `GITHUB_STATUS_TOKEN` was minted. No smoke operation
  deployed production.

## Product lanes (informational)

Connect **the same** GitHub repository `ddnne/quant-platform` to each of the
six ordinary product Workers if operators want per-Worker preview/history. Set **root
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

The authoritative repo-root lane uses deploy command `true` and uploads no
version. A product lane configured with `npx wrangler versions upload` stores a
version when that deploy command runs; that is not the same as promoting the
Active Deployment.

| Step | Command | When |
|---|---|---|
| Mandatory CI | repo-root build command `bash scripts/workers_builds_verify_ci.sh` | every push / PR that should merge |
| Version upload (optional, not promote) | `npx wrangler versions upload` | preview / non-production; or production-branch CI that must **not** go live |
| Explicit promote | `npx wrangler deploy` **or** dashboard promote of a specific version | operator, after the native check is green **and** an explicit decision to ship |

**Do not** set any production-branch **deploy command** to `npx wrangler deploy`
for the six ordinary product Workers. That would auto-promote on green CI. The
seventh active Worker, `receipt-evidence-authority`, is deployed only through
its reviewed PENDING/ACTIVE activation procedure and is not an automatic lane.

Use `npx wrangler versions upload` as the production-branch deploy command (and
the non-production command) on product lanes. Disconnecting Git does not replace
this policy — the deploy command is the switch
([disable automatic deployments](https://developers.cloudflare.com/workers/ci-cd/builds/#disconnecting-builds)).

Local **mandatory** CI is the same script: [`scripts/verify_ci.sh`](../../scripts/verify_ci.sh).
[`scripts/verify_all.sh`](../../scripts/verify_all.sh) is a fast local helper only.
Six ordinary product-lane `npm test` runs skip Python/catalog and are **not**
`verify_ci`; authoritative `verify_ci` covers all seven active Workers.

[Workers Builds](https://developers.cloudflare.com/workers/ci-cd/builds/) Git
integration also posts a **pull request comment** and per-worker **check runs**
in a [monorepo](https://developers.cloudflare.com/workers/ci-cd/builds/advanced-setups/#monorepos).
A PR comment is informational. Per-worker check runs can skip when
[build watch paths](https://developers.cloudflare.com/workers/ci-cd/builds/build-watch-paths/)
do not match. Neither is a substitute for the repo-root native check.

## Retired receipt aggregator

The caller-supplied receipt Worker and its first-deploy helper were removed.
No `CI_LANE_TOKEN` or `GITHUB_STATUS_TOKEN` path remains in the active CI
implementation. The similarly named private
`quant-platform-ci-aggregate-staging` service is only the no-op Cloudflare
Workers Builds anchor that runs the repository-root command; it is not the
retired receipt API and exposes no product route.

## What this does not do

- Does not add GitHub Actions workflows.
- Does not run `npm ci --legacy-peer-deps`.
- Does not skip missing `node_modules` or missing lockfiles.
- Does not `wrangler deploy` to production as a side effect of a green check.
- Does not arm Mass / READY / GO.
- Does not treat a green native check as product publication or READY / GO.
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
