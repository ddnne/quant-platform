# Independent Cloudflare / Security / CI review — `58133512`

**Reviewer:** independent Grok (Cloudflare / Security / CI). Detect-only. Did not fix code.  
**Reviewed SHA:** `58133512e1e896f1e811d1fb597337aa8f53d965` (`docs: review index names HEAD cb9916e0 vs origin/main b5c326a`)  
**Branch for this file:** `grok/p633-review-cf`  
**origin/main:** `b5c326a7f612563f2da4a84f08063a307ec38e0a` (feature HEAD is not an ancestor of `main`; not merged)  
**Account:** Cloudflare `11233bca08d134a9b738eaa46b9751d9` (`Taku_haga@icloud.com's Account`)  
**Repo:** GitHub `ddnne/quant-platform`  
**Mass / READY / Phase 7:** **NO-GO / null / OFF**. This file is not a GO and is not CI green.

Isolation did not `wrangler deploy`, did not `secret put`, did not PAT-mint context `ci-aggregate`, did not push `main`, and did not add `.github/workflows`.

Status: **OPEN / FIXED / HOLD**. P0 = merge-gate or spend/write authority can lie, or a declared-internal Worker is a live public hostname.

---

## Live measurements (this turn)

```
GET /repos/ddnne/quant-platform/branches/main/protection
  required_status_checks.strict = true
  contexts = ["ci-aggregate"]
  checks = [{context: "ci-aggregate", app_id: null}]
  enforce_admins = true
  required_approving_review_count = 0
  restrictions = null
  allow_force_pushes = false

GET /repos/ddnne/quant-platform/commits/58133512…/status     → total_count: 0, state: pending
GET /repos/ddnne/quant-platform/commits/58133512…/check-runs → total_count: 0
GET /repos/ddnne/quant-platform/commits/b5c326a…/status      → total_count: 0, state: pending
GET /repos/ddnne/quant-platform/commits/b5c326a…/check-runs  → total_count: 0
GET /repos/ddnne/quant-platform/actions/workflows            → total_count: 0

npx wrangler deployments list --name quant-platform-ci-aggregate
  GET /accounts/11233bca…/workers/scripts/quant-platform-ci-aggregate/deployments
  → code 10007  This Worker does not exist on your account.
npx wrangler versions list  --name quant-platform-ci-aggregate → 10007
npx wrangler secret list    --name quant-platform-ci-aggregate → Worker not found
GET  https://quant-platform-ci-aggregate.taku-haga.workers.dev/health     HTTP 404 / error 1042
POST https://quant-platform-ci-aggregate.taku-haga.workers.dev/v1/receipts HTTP 404 / error 1042
```

Public `*.workers.dev` (same turn; wrangler 4.125.0):

| Host | Tree `workers_dev` | Live GET `/health` |
|------|--------------------|--------------------|
| `quant-platform-ci-aggregate.taku-haga.workers.dev` | `true` | **1042** (Worker absent) |
| `quant-platform-ops-read-mcp.taku-haga.workers.dev` | `true` (OAuth callback) | **200** `{"ok":true,"service":"quant-ops-read-mcp","auth":"github-oauth"}` |
| `quant-platform-ingestion-secrets.taku-haga.workers.dev` | `true` | **200** `{"ok":true,"has_jquants_key":true}` |
| `quant-platform-research-ai-gateway.taku-haga.workers.dev` | **`false`** | **200** `{"ok":true,"service":"quant-platform-research-ai-gateway"}` |
| `quant-platform-research-mass-eval.taku-haga.workers.dev` | **`false`** | **200** `{"ok":true,"service":"quant-platform-research-mass-eval",…}` |
| `quant-platform-ingestion-premium.taku-haga.workers.dev` | **`false`** | **200** unauthenticated last-run + `has_jquants_key:true` + NK READY |
| `quant-platform-ingestion-jsda.taku-haga.workers.dev` | **`false`** | **200** `{"ok":true,"worker":"ingestion-jsda",…}` |

Mutating probes (no header): gateway `/v1/complete`, mass-eval `/v1/mass-eval`, secrets `/v1/proxy/jquants` → HTTP **401**. Same 401 with only `CF-Worker: research-mass-eval` or only `?token=`. That does **not** make the host private.

---

## Scoreboard

| ID | Topic | Sev | Status |
|----|-------|-----|--------|
| Issue 1 | `ci-aggregate` is caller-supplied receipts, not native CF Build | P0 | **OPEN** |
| Issue 2 | check-runs **0**; Worker **10007** absent; `app_id: null` | P0 | **OPEN** |
| Issue 3 | GitHub Actions must stay absent | P0 if present | **FIXED** (absent; do not add) |
| Issue 4 | `workers_dev` / preview as public surface | P0 | **OPEN** |
| Issue 5 | `GATEWAY_TOKEN` vs service binding; `CF-Worker` is not auth | P1 | **HOLD** |
| Issue 6 | Caller-supplied `budget_id` as occupancy | P0 | **OPEN** |
| Issue 7 | Query `token` as auth | P1 | **FIXED** in tree and live |
| Issue 8 | Secrets proxy public host + unauthenticated key-presence | P1 | **OPEN** |
| Issue 9 | `--legacy-peer-deps` / skip `node_modules` | P1 | **OPEN** (`verify_all` skip); `verify_ci` bans both |

**Unresolved P0 count: 4** (Issues 1, 2, 4, 6). Issue 3 is FIXED and must stay that way.

---

## Issue 1 P0 — `ci-aggregate` is caller-supplied receipts, not native Cloudflare Build

**File:** `platform/workers/ci-aggregate/src/receipts_gate.ts:4-11,99-116,118-173`  
**File:** `platform/workers/ci-aggregate/src/index.ts:120-180,201-208`  
**File:** `docs/ci/workers_builds.md:64-139,96-102`

**Status:** OPEN

`REQUIRED_WORKERS` is a six-name string list. `collectReceipts` accepts a JSON array, `{receipts:[…]}`, or a single object with `worker` / `sha` / `result` / `command`. `evaluateReceipts` checks name set, uniqueness, same 40-hex SHA, and `result === "pass"`. It never:

- calls the Workers Builds API,
- reads a Cloudflare check-run id,
- verifies `WORKERS_CI_COMMIT_SHA` against a live Build,
- executes `npm test`,
- or runs `scripts/verify_ci.sh`.

Success then `POST`s GitHub commit status context `ci-aggregate` (`index.ts:61-99,162-180`). Inbound gate is only `X-CI-Lane-Token` vs `CI_LANE_TOKEN` (`index.ts:202-207`). Docs tell operators to wrap `npm ci && npm test` and POST the six receipts (`workers_builds.md:64-68,137-139`). That wrapper is **caller-supplied attestation**.

`workers_builds.md:96-102` itself says six-lane `npm test` receipts skip Python/catalog and are **not** `verify_ci`, then still names GitHub context `ci-aggregate` as the merge requirement. Local `verify_ci.sh` covering seven workers (`scripts/verify_ci.sh:13-21`) is not what GitHub requires.

A green `ci-aggregate` status (if anyone ever posts one) is not native CF Build and is not `verify_ci`. Do not claim CI green.

---

## Issue 2 P0 — check-runs 0; Worker 10007 absent; PAT-mintable required context

**File:** `platform/workers/ci-aggregate/wrangler.toml:10-17`  
**File:** `docs/ci/workers_builds.md:19-27,104-170`  
**File:** `scripts/ci_aggregate_first_deploy.sh:1-53`

**Status:** OPEN

Live:

- `quant-platform-ci-aggregate` **does not exist** (deployments **10007**, versions **10007**, `secret list` Worker not found).
- `*.workers.dev` **1042**. `CI_LANE_TOKEN` / `GITHUB_STATUS_TOKEN` are unbound in production because there is no Worker to hold them.
- GitHub check-runs on this SHA and on `origin/main` `b5c326a`: **`total_count: 0`**.
- Commit statuses: **`total_count: 0` / `state: pending`**.
- `main` protection requires context `ci-aggregate` with **`app_id: null`**.

`app_id: null` means GitHub does not bind the required context to this Worker (or any App). A PAT with `repo:status` can `POST` `state=success` `context=ci-aggregate` for any SHA without receipts and without Cloudflare. `required_approving_review_count = 0` and `restrictions = null` add no second factor.

`scripts/ci_aggregate_first_deploy.sh` is print-only (`--apply` still prints; never `wrangler deploy`). It is not a producer.

Workers Builds, if connected, would post **check-runs** (watch-path skippable). Those are not the required context (`workers_builds.md:43-46`). Live they are also **0**, so native CF Build is not the merge gate either.

Human bottleneck: create the Worker with both secrets bound, bind the required check to an app, prove a failing SHA is unmergeable. Isolation must not do that. Do not PAT-mint `ci-aggregate`.

---

## Issue 3 P0 — GitHub Actions must stay absent

**File:** `docs/ci/workers_builds.md:1-5,190`  
**File:** `docs/architecture/adr_llm_friendly_refactor.md:107`  
**File:** `docs/architecture.md:28`

**Status:** FIXED (absent)

`git ls-tree -r --name-only 58133512` has **no** `.github/` paths. Live `GET /repos/ddnne/quant-platform/actions/workflows` → **`total_count: 0`**. ADR non-goal is “Adding GitHub Actions CI”.

`.grok/workflows/*.rhai` is not GitHub Actions. Empty GHA is **not** a missing pipeline. **Do not add** `.github/workflows` to “fix” Issues 1–2. If GHA appears, this becomes an unresolved P0.

---

## Issue 4 P0 — `workers_dev` / preview as public surface

**File:** `platform/workers/research-ai-gateway/wrangler.toml:3-16,32-35`  
**File:** `platform/workers/research-mass-eval/wrangler.toml:23-31,64-67`  
**File:** `platform/workers/ingestion-premium/wrangler.toml:24-31,67-70`  
**File:** `platform/workers/ingestion-jsda/wrangler.toml:5-11,38-41`  
**File:** `docs/ci/workers_builds.md:198-217`

**Status:** OPEN

Tree claims production has **no** `workers.dev` hostname for gateway, mass-eval, premium, and JSDA (`workers_dev = false`; `preview_urls = true` “version-only”). Docs table (`workers_builds.md:213-217`) says gateway is “service binding only; not a public research API” and premium/JSDA are “cron/internal”.

Live this turn, all four `*.workers.dev` hosts return **HTTP 200** on unauthenticated `/health`. Gateway wrangler comment at `wrangler.toml:4` already admits “wrangler 4.125.0 still deploys with `workers_dev=false` (no route required).” With no custom zone, the reachable hostname is `workers.dev`. `preview_urls = true` adds additional public version URLs.

Premium `/health` (`ingestion-premium/src/index.ts:572-590,632-634`) is unauthenticated and live-leaked `has_jquants_key: true`, natural-key migration **READY** (`rowsPrimary: 1047`, `auditMismatches: 0`, `detail` with **438212** rows), and `last_run` (cron, `2026-08-24T20:15:01+09:00`, 23/23 pass, `rowsInserted: 4459`). That is operational SoT on a host the tree calls internal.

Mutating routes 401 without tokens (see Issue 7). That is not a private API. A declared-internal AI gateway and ingest Worker on a stable public hostname is a public surface. Do not treat `workers_dev = false` in git as proof the hostname is gone.

Kept-true hosts (not this P0, see Issue 8 / Ops MCP OAuth): `quant-ops-mcp` and `ingestion-secrets` `workers_dev = true` by design. `ci-aggregate` `workers_dev = true` is moot until Issue 2 is closed; once deployed it becomes another public receipt POST host.

---

## Issue 5 P1 — `GATEWAY_TOKEN` vs service binding; `CF-Worker` is not auth

**File:** `platform/workers/research-mass-eval/src/ai_gateway_client.ts:23-58`  
**File:** `platform/workers/research-ai-gateway/src/authorized.ts:21-29`  
**File:** `platform/workers/research-ai-gateway/src/index.ts:131-133`  
**File:** `platform/workers/research-ai-gateway/src/index_cf_worker.test.ts:27-46`  
**File:** `platform/workers/research-mass-eval/wrangler.toml:44-47,78-80`

**Status:** HOLD (not CLOSED)

Mass-eval has a service binding `AI_GATEWAY` → `quant-platform-research-ai-gateway` but still requires a **second copy** of `GATEWAY_TOKEN` and sends it as `X-Gateway-Token` on `env.AI_GATEWAY.fetch`. Gateway `authorized()` compares only that header to `env.GATEWAY_TOKEN`. Unbound token denies. `MASS_EVAL_TOKEN` is a different secret.

Live POST `/v1/complete` with only `CF-Worker: research-mass-eval` and no `X-Gateway-Token` → **401** (matches `index_cf_worker.test.ts`). Cloudflare documents `CF-Worker` as **not** authorization; inbound callers can supply it before the edge sets it. Service-binding HTTP `fetch` does not attach an unspoofable caller identity.

Until there is a **documented** binding-only RPC / caller identity, public/preview `fetch` must stay token-gated **and** the internal path keeps a shared bearer. Dual secret copies remain. Do not invent a `CF-Worker` allowlist as a close.

---

## Issue 6 P0 — Caller-supplied `budget_id` as occupancy

**File:** `platform/workers/research-ai-gateway/src/index.ts:65-75,157-166,196-219`  
**File:** `platform/workers/research-ai-gateway/src/schema.ts:146-150,185-193`  
**File:** `platform/workers/research-ai-gateway/src/budget_do.ts:1,150-152,284-369`  
**File:** `platform/workers/research-ai-gateway/src/budget_http.ts:1`

**Status:** OPEN

`POST /v1/complete` takes `budget_id` from the JSON body (`schema.ts:185-193`) and passes it to `budgetRpc` → `BUDGET_LEDGER.idFromName(budgetId)` (`index.ts:74,157`). Occupancy algebra in `budget_do.ts` is real **per Durable Object instance** (`PILOT_BUDGET_CAPS`, reserve/reconcile/lease). Caps do not apply across names.

Any caller who can pass `authorized()` (shared `GATEWAY_TOKEN`, Issue 5) can mint a fresh ledger by sending a new `budget_id` string. That instance starts at zero occupancy (`budget_do.test.ts:53-64` pins created ledger has zero occupancy). Presence of the string is treated as the occupancy key.

`schema.ts:146-150` still says “A persistent Durable Object ledger is not in this commit” and “Presence of `budget_id` is not a transactional reserve.” That comment is stale versus `index.ts` which **does** `/reserve` then `/reconcile` on that caller-chosen name. Tests that assert “`budget_id` is not occupancy” document the hole; they do not close it.

Combined with Issue 4 (public gateway hostname) this is spend-authority bypass of the pilot cap, not a missing field. Live Edge occupancy across a single operator ledger is **unproven**.

---

## Issue 7 P1 — Query `token` as auth

**File:** `platform/workers/research-ai-gateway/src/authorized.ts:21-29`  
**File:** `platform/workers/ci-aggregate/src/authorized.ts:1-3,30-39`  
**File:** `platform/workers/ingestion-secrets/src/authorized.ts:1-22`  
**File:** `platform/workers/research-mass-eval/src/authorized.ts:1-35`  
**File:** `packages/data_plane/ingestion/common/http.py:251-256`

**Status:** FIXED (tree + live). Keep tests.

Production `authorized()` helpers hash-compare **headers only** (`X-Gateway-Token`, `X-CI-Lane-Token`, `X-Ingestion-Token`, `X-Mass-Eval-Token`). They do not read `searchParams`. Python proxy client sends `X-Ingestion-Token` and does not put the token on the URL.

Live this turn: gateway `/v1/complete?token=test`, secrets `/v1/proxy/jquants?token=test` → **401**, no upstream. Worker tests pin the same.

Not an unresolved P0. Do not re-introduce query-token auth on public `workers.dev` / preview URLs.

---

## Issue 8 P1 — Secrets proxy exposure

**File:** `platform/workers/ingestion-secrets/wrangler.toml:4-10,19-21`  
**File:** `platform/workers/ingestion-secrets/src/index.ts:53-60,63-109`  
**File:** `packages/data_plane/ingestion/common/secrets.py:1-25`

**Status:** OPEN (documented public host; unauthenticated key-presence)

`workers_dev = true` so local runners can reach a token-gated proxy. That is a **stable public hostname**. `/v1/proxy/jquants` is header-gated (Issue 7 FIXED) and path-allowlisted; live POST without header → **401**. Python never holds `JQUANTS_API_KEY`; the Worker injects `x-api-key` upstream (`index.ts:96-99`).

Residual: `GET /health` is unauthenticated and live-returns `{"ok":true,"has_jquants_key":true}` (`index.ts:57-60`). Combined with Issue 4, premium health also advertises the key boolean plus last-run. Token theft on this host is a live J-Quants proxy. Do not widen methods/paths. Do not treat workers.dev as a non-public surface.

---

## Issue 9 P1 — `--legacy-peer-deps` / skip `node_modules`

**File:** `scripts/verify_ci.sh:3-11,166-183`  
**File:** `scripts/verify_all.sh:10-12,18-22,80-91`  
**File:** `tests/test_verify_ci_script.py:109-120`  
**File:** `docs/ci/workers_builds.md:64-68,96-102`

**Status:** OPEN for merge-gate skip; `verify_ci` itself bans both

`verify_ci.sh` always `npm ci` from `package-lock.json` (no `--legacy-peer-deps`), never skips missing `node_modules`, no `VERIFY_*` flags, seven workers including `ci-aggregate`. Tests pin that.

`verify_all.sh` still skips a worker when `node_modules` is missing unless `VERIFY_NPM_CI=1` (`verify_all.sh:80-91`), covers only three research workers, and is the skippable helper.

The GitHub merge gate is Issue 1’s six `npm ci && npm test` receipts, not `verify_ci`. Suggested Workers Builds command (`workers_builds.md:64-68`) is that same `npm ci && npm test` — it does not run pytest, catalog freeze, IR, typecheck, or dry-run. A lane that resolved the graph with `--legacy-peer-deps` locally could still POST `result=pass`. Tree `verify_ci` hygiene does not bind the live gate.

Do not add `--legacy-peer-deps` to `verify_ci` or to Builds commands. Do not treat a green `verify_all` as mandatory CI.

---

## Unresolved P0 count

**4**

| ID | One line |
|----|----------|
| Issue 1 | Merge context is caller JSON receipts, not native CF Build / not `verify_ci` |
| Issue 2 | Producer Worker **10007** absent; check-runs **0**; `app_id: null` PAT-mintable |
| Issue 4 | Tree `workers_dev=false` Workers are live public `*.workers.dev` (incl. gateway + premium health) |
| Issue 6 | Occupancy keyed by caller `budget_id` → `idFromName` mint |

Issue 3 (GHA absent) is FIXED and must remain absent. Issue 5 HOLD. Issue 7 FIXED. Issues 8–9 P1 OPEN.

Do not invent Projection FRESH, B0 PASS, production READY, Coverage COMPLETE, Phase 7 GO, or **CI green**.
