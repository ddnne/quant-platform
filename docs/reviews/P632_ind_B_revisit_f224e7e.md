# Independent review B revisit — at `f224e7e`

**Reviewer:** independent Grok (isolation worktree; not the implementer)  
**Reviewed HEAD:** `f224e7e` (`f224e7e922d93dfdcc14ae86578883cad337ebca`)  
**Branch at audit:** `grok/p632-ind-B-revisit-f224e7e` (from `grok/phase63-ci-source-closure`)  
**Prior revisits:** `07b4435` ([`P632_ind_B_revisit.md`](P632_ind_B_revisit.md)); freeze `a48c600` ([`P632_ind_B_ci_authority.md`](P632_ind_B_ci_authority.md))  
**origin/main:** `b5c326a7f612563f2da4a84f08063a307ec38e0a`  
**Scope:** re-measure Independent B — CI skip, `ci-aggregate`, tokens, R2, budget — vs HEAD `f224e7e`. Tree-level receipt auth and seven-worker `verify_ci` already landed before `07b4435`. This turn re-diffs those plus P632B-03..07.

Status vocabulary: **P0 / P1**, **OPEN / FIXED**. Do not invent Projection FRESH, B0 PASS, production READY, Coverage COMPLETE 23, Phase 7 GO, or **CI green**.

This file is **not** a GO. Independent P0 unresolved: **2**.

---

## Live MCP (this isolation turn — not invented FRESH)

quant_mcp tools **were available**. Values below are this-turn reads. Projection is **STALE**. Latest READY snapshot is **null**. B0 is **UNKNOWN**. Do not narrate FRESH / READY / B0 PASS.

| Surface | Value |
|---------|--------|
| `ops_status.coverage_status_counts` | **22 COMPLETE · 4 PARTIAL** (ops_current; not a research READY snapshot) |
| `ops_status.last_run` | id 14317, `2026-08-23T23:15:01+09:00`, jquants, pass |
| `projection_status` | **STALE** |
| `active_generation` | `projgen-ef18b4f86ee946048161d25e2a30a2a8` |
| `projection_generated_at` | `2026-08-21T12:30:49.152421+00:00` |
| `projection_source_generation` | `2026-08-21T12:28:33.345482+00:00` |
| `projection_age_seconds` | 181053 (~50.3 h) |
| `stages.refresh_success` | **false** |
| `latest_ready_snapshot` | **null** (`reason`: no published READY generation is bound to this Worker) |
| `b0_status` | **UNKNOWN** (`reason`: snapshot quality/B0 projection is unavailable) |
| `storage_plane_status.p0_claims.mass_research` | **NO-GO** |
| `storage_plane_status.p0_claims.ready` | **null** |

`coverage_gaps` still returns **4 PARTIAL** under **`collection-coverage/v2`** floors (STALE projection):

| Dataset | Live `history_target_start` | `evaluated_at` |
|---------|-----------------------------|----------------|
| `equities_master` | **2006-08-13** | 2026-08-18 |
| `equities_bars_daily_am` | **2024-01-04** | 2026-08-14 |
| `equities_earnings_calendar` | **2010-01-04** | 2026-08-14 |
| `jsda_otc_bond_reference_prices` | **2002-08-02** | 2026-08-21 |

Last-known-good narrative remains **22 COMPLETE · 4 PARTIAL**. Mass Autonomous Research remains **NO-GO**. Phase 7 remains **OFF**. This file is not a ledger refresh and is not a GO.

---

## Four questions (this revisit)

| Question | Answer |
|----------|--------|
| Is `POST /v1/receipts` still unauthenticated **in tree**? | **No.** Unbound `CI_LANE_TOKEN` → HTTP **503**; missing/wrong `X-CI-Lane-Token` → HTTP **401**. Unchanged vs `07b4435` (`ff053a3`). |
| Does `verify_ci` include `ci-aggregate`? | **Yes.** `WORKERS` has **7** paths; `tests/test_verify_ci_script.py` pins `len(WORKERS) == 7` and the name in the script. |
| Are GitHub check-runs still 0 live at `f224e7e`? | **Yes.** HEAD `f224e7e`, `origin/main` `b5c326a`, prior `07b4435`, freeze `a48c600`: `check-runs.total_count = 0`. Commit statuses `total_count = 0` / `state = pending`. PR #1 `statusCheckRollup = []`. Actions workflows **0**. |
| Does live `quant-platform-ci-aggregate` exist? | **No.** Wrangler **10007** on account `11233bca08d134a9b738eaa46b9751d9`. `wrangler secret list` → Worker not found. `*.workers.dev` **1042**. Account script list is **11** names and does **not** include this Worker. `GITHUB_STATUS_TOKEN` / `CI_LANE_TOKEN` therefore remain **unbound in production** (no Worker to hold them). |

P0 remaining: **yes, 2** (P632B-01 merge-gate producer is still six `npm test` receipts, not `verify_ci`; P632B-02 live producer missing / PAT-mintable `app_id: null` context). **Do not claim CI green.**

---

## Scoreboard vs `07b4435` / `a48c600`

| ID | Topic | Sev | At `a48c600` | At `07b4435` | At `f224e7e` |
|----|-------|-----|--------------|--------------|--------------|
| P632B-01 | `verify_all` skip vs `verify_ci` authority | P0 | OPEN (scripts split FIXED; `ci-aggregate` absent from `verify_ci`; merge gate not `verify_ci`) | OPEN (`ci-aggregate` in `verify_ci` FIXED; GitHub still does not run `verify_ci`) | **OPEN** (IR jsonschema + `wrangler types --check` in `verify_ci` **FIXED**; merge gate still six lane receipts) |
| P632B-02 | Branch protection `ci-aggregate` vs actual GitHub checks | P0 | OPEN (unauthenticated POST; Worker 10007; check-runs 0; `app_id: null`) | OPEN (inbound auth FIXED in tree; live Worker / checks / token / app binding still OPEN) | **OPEN** (same live hole; Worker still 10007; check-runs still 0) |
| P632B-03 | Shared `GATEWAY_TOKEN` / `MASS_EVAL_TOKEN` | P1 | OPEN (header mix-up FIXED) | not re-diffed | **OPEN** (tree unchanged vs `07b4435`: mass-eval still sends `GATEWAY_TOKEN`) |
| P632B-04 | Edge budget double-spend | P0/P1 | FIXED same-DO occupancy; OPEN P1 residuals | not re-diffed | **same** (P0 occupancy still FIXED; P1 residuals still OPEN; no budget-path diff vs `07b4435`) |
| P632B-05 | R2 child 409 / Python TOCTOU writer | P0/P1 | FIXED Worker 409; OPEN Python writer | not re-diffed | **same** (Worker `onlyIf` still FIXED; Python putters still write) |
| P632B-06 | Active / Legacy catalog mix | P1 | FIXED Python partition; OPEN Worker/eval mix | not re-diffed | **same** (no `catalog_kind` in mass-eval Worker) |
| P632B-07 | GitHub Actions presence (must be absent) | P0 if present | FIXED (absent) | FIXED | **FIXED** (`git ls-files` has no `.github/`; live Actions workflows **0**) |

Independent P0 unresolved: **2**. Tree-level holes named at freeze for receipt auth and seventh-worker `verify_ci` stay closed. The live merge gate still has **no honest producer**. Do not invent Coverage COMPLETE, Projection FRESH, B0 PASS, READY, or CI green.

Delta vs `07b4435` that is **not** a P0 close: `9e7d1b6` (`verify_ci` jsonschema-validates Evaluation IR) and `24b81f5` (`wrangler types --check` for all seven workers). Tokens / R2 / budget / catalog / GHA surfaces are **empty diffs** against `07b4435`.

---

## P632B-01 — CI skip / `verify_all` vs `verify_ci`

**severity:** P0  
**affected:** `scripts/verify_ci.sh`; `scripts/verify_all.sh`; `tests/test_verify_ci_script.py`; `docs/ci/workers_builds.md`; `scripts/README.md`; `tests/README.md`; GitHub required context `ci-aggregate`  
**status:** **OPEN** (seven workers + IR schema + types `--check` in `verify_ci` **FIXED**; merge-gate producer still six `npm test` receipts)

### FIXED (must stay)

`scripts/verify_ci.sh` still lists seven Workers:

```13:21:scripts/verify_ci.sh
WORKERS=(
  platform/workers/ingestion-jsda
  platform/workers/ingestion-premium
  platform/workers/ingestion-secrets
  platform/workers/quant-ops-mcp
  platform/workers/research-ai-gateway
  platform/workers/research-mass-eval
  platform/workers/ci-aggregate
)
```

`tests/test_verify_ci_script.py` pins `len(WORKERS) == 7` and `for name in WORKERS: assert name in src`. The freeze pin `assert "ci-aggregate" not in src` remains gone.

Since `07b4435`, authoritative CI got **stricter** (still not the merge gate):

- `9e7d1b6`: Evaluation IR is `jsonschema.validate` + Python encode/decode, not a presence check.
- `24b81f5`: if `package.json` has `scripts.types`, `verify_ci` runs `npx wrangler types --check` (tests pin that all seven workers define it).

`tests/README.md` names `scripts/verify_ci.sh` as mandatory CI; `verify_all.sh` is the helper. `docs/ci/workers_builds.md:84-90` still says six-lane `npm test` receipts “skip Python/catalog and are **not** `verify_ci`”. Merge “requires GitHub context `ci-aggregate` after authenticated receipts **and** `verify_ci`”.

### OPEN (still P0)

GitHub `main` protection still requires only context `ci-aggregate`. That context is produced from **six lane receipts** of `npm ci && npm test` (`REQUIRED_WORKERS` in `platform/workers/ci-aggregate/src/index.ts:4-11`; `docs/ci/workers_builds.md:52-56,122-127`). It is **not** “`verify_ci.sh` exited 0”.

The three authorities remain:

| Surface | What it runs | Skip? |
|---------|--------------|-------|
| `verify_all.sh` | pytest + **3** research workers `npm test` | yes (`VERIFY_*`, missing `node_modules`, ingestion + `ci-aggregate` absent) |
| `verify_ci.sh` | pytest + catalog + IR jsonschema + **7** workers ci/test/typecheck/dry-run/types `--check` | no |
| GitHub required context | six lane **receipts** of `npm ci && npm test` (if anyone POSTs them) | Python, catalog freeze, IR, typecheck, dry-run **not in the batch** |

`scripts/verify_all.sh` is unchanged as a skippable helper (`WORKERS` is still the three research workers). That is acceptable **only** if merge never treats it as CI.

`scripts/README.md:19` still says “Evaluation IR golden/schema **presence**”. The script now validates. Honesty residual, not a merge-gate close.

PR #1 is `MERGEABLE` / `BLOCKED` because `ci-aggregate` has never posted — not because `verify_ci` ran. A green `verify_all` or a future PAT `ci-aggregate` success is still **not** a `verify_ci` run. **Do not claim CI green.**

### Why this is still P0

The freeze P0 was merge-gate skip of the Python plane and of the gate Worker. The gate Worker is in `verify_ci`. The merge gate still skips Python / catalog / IR. Do not treat “`ci-aggregate` is in `verify_ci.sh`” or “IR is jsonschema-checked locally” as FIXED for merge authority.

### Structural fix (unchanged intent)

- Make the merge-gate receipt command `scripts/verify_ci.sh` (or an equivalent receipt that cannot be `npm test` on one Worker).
- Keep `ci-aggregate` in `verify_ci` (already done).
- Keep `verify_all.sh` labeled helper-only.

---

## P632B-02 — Branch protection bypass / `ci-aggregate` vs actual GitHub checks

**severity:** P0  
**affected:** GitHub `ddnne/quant-platform` `main` protection; `platform/workers/ci-aggregate/`; live Cloudflare account `11233bca08d134a9b738eaa46b9751d9`  
**status:** **OPEN** (receipt POST auth **FIXED in tree**; **live producer still missing**)

### FIXED in tree (must stay)

`POST /v1/receipts` still authenticates:

```234:244:platform/workers/ci-aggregate/src/index.ts
export async function authorized(
  request: Request,
  env: AggregateEnv,
): Promise<boolean> {
  const expected = secretBound(env.CI_LANE_TOKEN);
  if (!expected) return false;
  const got = request.headers.get("X-CI-Lane-Token") || "";
  if (!got) return false;
  return tokenMatches(got, expected);
}
```

```391:396:platform/workers/ci-aggregate/src/index.ts
  if (!secretBound(env.CI_LANE_TOKEN)) {
    return json({ ok: false, reason: "unbound_ci_lane_token" }, 503);
  }
  if (!(await authorized(request, env))) {
    return json({ ok: false, reason: "unauthorized" }, 401);
  }
```

Tests still pin unbound `CI_LANE_TOKEN` → 503; wrong `X-CI-Lane-Token` → 401; unbound `GITHUB_STATUS_TOKEN` → 503; matching token + six-pass batch posts GitHub `success`; PR comment is not a success signal; GET `/health` stays unauthenticated.

`workers_dev = true` remains. After a real deploy the host is a public `*.workers.dev` URL; inbound auth is the fence. There is **no** live host this turn.

`wrangler.toml` comments still document only `GITHUB_STATUS_TOKEN`, not `CI_LANE_TOKEN`. Honesty residual, not a live unauthenticated POST (the Worker does not exist).

### Live GitHub / Cloudflare (this isolation turn)

```
GET /repos/ddnne/quant-platform/branches/main/protection
  required_status_checks.strict = true
  contexts = ["ci-aggregate"]
  checks = [{context: "ci-aggregate", app_id: null}]
  enforce_admins = true
  allow_force_pushes = false
  required_approving_review_count = 0
  restrictions = null

GET /repos/ddnne/quant-platform/commits/b5c326a…/status     → total_count: 0, state: pending
GET /repos/ddnne/quant-platform/commits/b5c326a…/check-runs → total_count: 0
GET /repos/ddnne/quant-platform/commits/f224e7e…/status     → total_count: 0, state: pending
GET /repos/ddnne/quant-platform/commits/f224e7e…/check-runs → total_count: 0
GET /repos/ddnne/quant-platform/commits/07b4435…/status     → total_count: 0, state: pending
GET /repos/ddnne/quant-platform/commits/07b4435…/check-runs → total_count: 0
GET /repos/ddnne/quant-platform/commits/a48c600…/status     → total_count: 0, state: pending
GET /repos/ddnne/quant-platform/commits/a48c600…/check-runs → total_count: 0
GET /repos/ddnne/quant-platform/actions/workflows           → total_count: 0
PR #1  head=f224e7e  mergeable=MERGEABLE  mergeStateStatus=BLOCKED  statusCheckRollup=[]
```

Wrangler (account `11233bca08d134a9b738eaa46b9751d9`, subdomain `taku-haga`):

```
GET /accounts/…/workers/scripts  → 11 scripts, ci-aggregate absent
  news-collect, news-ingest, news-mcp,
  quant-platform-ingestion-jsda, quant-platform-ingestion-premium,
  quant-platform-ingestion-secrets, quant-platform-jsda-otc-probe-w80,
  quant-platform-ops-read-mcp, quant-platform-research-ai-gateway,
  quant-platform-research-mass-eval, tmp-exp-eval

GET /accounts/…/workers/scripts/quant-platform-ci-aggregate/deployments
  success: false  code: 10007  "This Worker does not exist on your account."

wrangler secret list --name quant-platform-ci-aggregate
  Worker "quant-platform-ci-aggregate" not found.

GET  https://quant-platform-ci-aggregate.taku-haga.workers.dev/health
POST https://quant-platform-ci-aggregate.taku-haga.workers.dev/v1/receipts
  HTTP 404  error code: 1042
```

### Why it is still P0

Branch protection still requires a context that:

1. has never been posted on `origin/main`, this reviewed SHA `f224e7e`, prior revisit `07b4435`, or freeze `a48c600`,
2. is not produced by a deployed Worker,
3. is not an app-bound check-run (`app_id: null`),
4. can still be minted by any `repo:status` PAT **without** lane receipts.

Receipt auth in the tree does **not** close (4). A PAT with `repo:status` can `POST` `state=success` `context=ci-aggregate` for any SHA without talking to this Worker. That is the bypass the required-check configuration actually enforces.

`required_approving_review_count = 0` and `restrictions = null` add no second factor. `enforce_admins = true` only means admins also need that forgeable status. PR #1 stays BLOCKED because the context is **missing**, not because an honest producer ran. Missing is not green.

Cloudflare Workers Builds check-runs remain **0**. Docs still say those are not the merge gate. Live they also do not exist.

### Structural fix (unchanged + tree auth)

- Deploy `quant-platform-ci-aggregate` only with **both** `CI_LANE_TOKEN` and `GITHUB_STATUS_TOKEN` bound (tree now requires both).
- Bind the required check to an **app** (or stop using a raw commit-status context as the sole gate).
- Until a real `success` exists on the SHA, do not merge to `main`. Do not PAT-green the context.
- Require `verify_ci` (P632B-01), not six `npm test` strings.

Do not add `.github/workflows` (P632B-07 remains FIXED-absent).

---

## P632B-03 — Shared token authority (`GATEWAY_TOKEN` vs `MASS_EVAL_TOKEN`)

**severity:** P1  
**affected:** `platform/workers/research-ai-gateway/src/index.ts`; `platform/workers/research-mass-eval/src/ai_gateway_client.ts`  
**status:** **OPEN** (cross-header substitute **FIXED**; shared secret on the caller **OPEN**). Empty diff vs `07b4435`.

### FIXED (must stay)

Gateway `authorized()` compares **only** `X-Gateway-Token` to `env.GATEWAY_TOKEN` (`index.ts:40-47`). Tests still pin:

- `X-Mass-Eval-Token` is not accepted as the gateway header.
- `MASS_EVAL_TOKEN` value in `X-Gateway-Token` is not accepted.
- Unbound `GATEWAY_TOKEN` denies even if `MASS_EVAL_TOKEN` is set.

Mass-eval HTTP routes authorize with `env.MASS_EVAL_TOKEN` / `X-Mass-Eval-Token` only.

### OPEN

Mass-eval still **sends** `GATEWAY_TOKEN` over the `AI_GATEWAY` service binding:

```23:52:platform/workers/research-mass-eval/src/ai_gateway_client.ts
function gatewayToken(env: Env): string | undefined {
  const rec = env as Env & { GATEWAY_TOKEN?: string };
  return rec.GATEWAY_TOKEN;
}
// ...
    "X-Gateway-Token": token,
```

`Env` in `types.ts` does not declare `GATEWAY_TOKEN`. The client casts the extra secret in. Binding identity is still not the auth.

If operators bind the **same** string to both secrets, the test-pinned header separation is cosmetic. If they do not bind `GATEWAY_TOKEN` on mass-eval, propose/gateway calls fail closed (`gateway_token_unbound`) — Mass remains NO-GO either way.

---

## P632B-04 — Edge budget double-spend

**severity:** P0 (same-DO occupancy) **FIXED**; P1 residuals **OPEN**  
**affected:** `platform/workers/research-ai-gateway/src/budget_do.ts`; `src/index.ts`; `src/schema.ts`  
**status:** mixed. Empty diff vs `07b4435` on these files.

### FIXED (P0 occupancy)

`/v1/complete` still reserves before `env.AI.run`. Unbound `BUDGET_LEDGER` → 503. Occupancy = `used + reserved`. Same idempotency key does not double-increment. Exhausted reserve does not mutate counters.

### OPEN (P1)

1. **`schema.ts` still advertises the stub** (lines 147–151, error at 186): “A persistent Durable Object ledger is not in this commit” / “Edge ledger is not yet transactional.” Codec comment contradicts `index.ts` + `budget_do.ts`.
2. **Caller-chosen `budget_id` = new DO = new cap.** `idFromName(budgetId)` (`index.ts:112`). Each distinct id gets `PILOT_BUDGET_CAPS` again.
3. **Default idempotency is `crypto.randomUUID()`** (`index.ts:193-194`). Mass-eval `completeViaGateway` still does **not** send `Idempotency-Key` (grep over that Worker is empty).
4. **Reconcile failure after a successful `AI.run` is ignored.** `index.ts:234-259` does not check `.ok`; the handler still returns `ok: true`.

Not a live spend this turn (Mass NO-GO). Residual is still the same hole if the gateway is exercised.

---

## P632B-05 — R2 child conflict / Python TOCTOU writer as authority

**severity:** P0 Worker overwrite **FIXED**; P1 Python writer **OPEN**  
**affected:** `platform/workers/research-mass-eval/src/http.ts`; `packages/product/research/r2_io.py`; `cf_mass_eval_run.py`; `cf_mass_eval_stage.py`; `cf_mass_eval_job.py`  
**status:** mixed. Empty diff vs `07b4435` on these files.

### FIXED (Worker)

`putJsonCreateOnly` (`http.ts:113-138`): `onlyIf: { etagDoesNotMatch: "*" }`; existing key with a different digest → 409. Child conflict still does not mint a manifest.

### OPEN (Python CLI still writes)

`r2_io.py` still documents head-then-put **TOCTOU** and refuses `authoritative=True` (`python_cli_put_is_not_immutable_authority = True`). Callers still put Worker job keys: `cf_mass_eval_run.put_local_fallback_artifacts`, `cf_mass_eval_stage`, `cf_mass_eval_job`. `wrangler r2 object put` has no `onlyIf`. A flag is not a fence.

---

## P632B-06 — Active / Legacy catalog mix (spot-check)

**severity:** P1  
**status:** **FIXED** (Python partition); **OPEN** (Worker / eval still mixed). Empty grep for `catalog_kind` under `platform/workers/research-mass-eval`. `catalog_ids.ts` header still locks n=2254. `cf_mass_eval_job.default_logic_specs` still does `py_by_id or yaml_by_id` over `load_catalog_specs()` (`cf_mass_eval_job.py:159-165`). Not GO. Independent C owns the catalog scoreboard; this line is occupancy, not a new P0.

---

## P632B-07 — GitHub Actions presence (must be absent)

**severity:** P0 if present  
**status:** **FIXED** (absent)

- `git ls-files` has no `.github/` and no workflow YAML.
- `GET /repos/ddnne/quant-platform/actions/workflows` → **0**.

Empty GHA is **not** a missing pipeline. Do **not** add `.github/workflows` to “fix” P632B-01/02.

---

## What this review does not claim

- Projection FRESH, B0 PASS, READY, Mass GO, Phase 7 Controlled Pilot ON, Dataset COMPLETE 23.
- **CI green.** Check-runs are 0. Statuses are pending/empty. The required context has never been posted.
- `verify_ci.sh` was executed at this HEAD (script/static tests only).
- `quant-platform-ci-aggregate` is live (Wrangler 10007; workers.dev 1042).
- `GITHUB_STATUS_TOKEN` or `CI_LANE_TOKEN` is bound in production (Worker missing).
- Independent P0 count is 0. It is **2** (P632B-01, P632B-02).

---

## Blocked / unverified

- Live MCP remeasure this turn is **STALE** (`refresh_success=false`, READY **null**, B0 **UNKNOWN**). Counts are last-known-good under `projgen-ef18b4f86ee946048161d25e2a30a2a8`, not a new publication.
- Isolation worktree does **not** deploy, bind secrets, PAT-post `ci-aggregate`, push `main`, or invent GO.
- `wrangler.toml` comments still document only `GITHUB_STATUS_TOKEN`, not `CI_LANE_TOKEN`.
- Missing-header (empty `X-CI-Lane-Token`) is covered by `authorized()` (`if (!got) return false` → 401 when the secret is bound). Tests pin wrong-token 401 and unbound 503; they do not have a separate no-header case. Not a live P0.
- `scripts/README.md` still says Evaluation IR is a presence check; `verify_ci.sh` now jsonschema-validates. Honesty residual.

Keep GitHub Actions absent (P632B-07). Do not merge `main` on a PAT `ci-aggregate` success.
