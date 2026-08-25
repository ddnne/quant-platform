# Independent review B revisit — after receipt auth

**Reviewer:** independent Grok (isolation worktree; not the implementer)  
**Reviewed HEAD:** `07b4435` (`07b44355dc745b1a9b7f7c3c4eccbe123e7a171b`)  
**Branch at audit:** `grok/p632-ind-B-revisit` (from `grok/phase63-ci-source-closure`)  
**Prior freeze:** `a48c600` (`docs/reviews/P632_ind_B_ci_authority.md`)  
**origin/main:** `b5c326a7f612563f2da4a84f08063a307ec38e0a`  
**Scope:** re-diff P632B-01 and P632B-02 after `ff053a3` (`CI_LANE_TOKEN`), `a30343e` (`verify_ci` 7 workers), `07b4435` (verify_ci merge-gate docs). P632B-03..07 not re-audited.

Status vocabulary: **P0 / P1**, **OPEN / FIXED**. Do not invent Projection FRESH, B0 PASS, production READY, Coverage COMPLETE 23, or Phase 7 GO.

---

## Live MCP (this isolation turn — not invented FRESH)

| Surface | Value |
|---------|--------|
| `projection_status` | **STALE** |
| `active_generation` | `projgen-ef18b4f86ee946048161d25e2a30a2a8` |
| `projection_generated_at` | `2026-08-21T12:30:49.152421+00:00` |
| `projection_source_generation` | `2026-08-21T12:28:33.345482+00:00` |
| `projection_age_seconds` | 179551 (~49.9 h) |
| `stages.refresh_success` | **false** |
| `latest_ready_snapshot` | **null** (`reason`: no published READY generation is bound to this Worker) |
| `b0_status` | **UNKNOWN** (`snapshot quality/B0 projection is unavailable`) |

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
| Is `POST /v1/receipts` still unauthenticated? | **No in tree** (`ff053a3`). Unbound `CI_LANE_TOKEN` → HTTP **503**; missing/wrong `X-CI-Lane-Token` → HTTP **401**. **Live: no endpoint** — Worker does not exist (Wrangler **10007**; `*.workers.dev` **1042**). |
| Does `verify_ci` include `ci-aggregate`? | **Yes** (`a30343e`). `WORKERS` has **7** paths; `tests/test_verify_ci_script.py` pins `len(WORKERS) == 7` and the name in the script. The freeze pin `assert "ci-aggregate" not in src` is **gone**. |
| Are GitHub check-runs still 0 live? | **Yes.** HEAD `07b4435`, `origin/main` `b5c326a`, freeze `a48c600`: `check-runs.total_count = 0`. Commit statuses `total_count = 0` / `state = pending`. PR #1 `statusCheckRollup = []`. Actions workflows **0**. |
| `GITHUB_STATUS_TOKEN` still unbound in production? | **Yes.** `quant-platform-ci-aggregate` is not on account `11233bca08d134a9b738eaa46b9751d9` (10007). `wrangler secret list` → Worker not found. A missing Worker cannot hold the secret. Tree still fail-closes on unbound (503, nothing posted). |

P0 remaining: **yes, 2** (P632B-01 merge-gate producer; P632B-02 live producer / PAT-mintable context / unbound production token).

---

## Scoreboard vs `a48c600`

| ID | Topic | Sev | At `a48c600` | At `07b4435` |
|----|-------|-----|--------------|--------------|
| P632B-01 | `verify_all` skip vs `verify_ci` authority | P0 | OPEN (scripts split FIXED; `ci-aggregate` absent from `verify_ci`; merge gate not `verify_ci`) | **OPEN** (`ci-aggregate` in `verify_ci` **FIXED**; GitHub still does not run `verify_ci`) |
| P632B-02 | Branch protection `ci-aggregate` vs actual GitHub checks | P0 | OPEN (unauthenticated POST; Worker 10007; check-runs 0; `app_id: null`) | **OPEN** (inbound auth **FIXED in tree**; live Worker / checks / token / app binding still OPEN) |

Independent P0 unresolved: **2**. Tree-level holes named at freeze are closed; the live merge gate is not. Do not invent Coverage COMPLETE, Projection FRESH, B0 PASS, or READY.

---

## P632B-01 — CI skip / `verify_all` vs `verify_ci`

**severity:** P0  
**affected:** `scripts/verify_ci.sh`; `tests/test_verify_ci_script.py`; `docs/ci/workers_builds.md`; `scripts/README.md`; `tests/README.md`; GitHub required context `ci-aggregate`  
**status:** **OPEN** (seventh Worker in `verify_ci` **FIXED**; merge-gate producer still six `npm test` receipts)

### FIXED (must stay)

`a30343e` added `platform/workers/ci-aggregate` to authoritative CI:

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

`tests/test_verify_ci_script.py` now pins `len(WORKERS) == 7` and `for name in WORKERS: assert name in src`. The freeze assertion that the script must **not** mention `ci-aggregate` is deleted.

Docs match the script:

- `tests/README.md` names `scripts/verify_ci.sh` as mandatory CI; `verify_all.sh` is the helper.
- `scripts/README.md`: “all seven workers including `ci-aggregate`”.
- `docs/ci/workers_builds.md:84-90`: local mandatory CI is `verify_ci.sh`; six-lane `npm test` receipts “skip Python/catalog and are **not** `verify_ci`”. Merge “requires GitHub context `ci-aggregate` after authenticated receipts **and** `verify_ci`”.

The hole the freeze tests **pinned** (`ci-aggregate` not typechecked / dry-run by authoritative CI) is closed in the tree.

### OPEN (still P0)

GitHub `main` protection still requires only context `ci-aggregate`. That context is produced from **six lane receipts** of `npm ci && npm test` (`REQUIRED_WORKERS` in `platform/workers/ci-aggregate/src/index.ts:4-11`; `docs/ci/workers_builds.md:52-56,70,122-127`). It is **not** “`verify_ci.sh` exited 0”.

So the three authorities remain:

| Surface | What it runs | Skip? |
|---------|--------------|-------|
| `verify_all.sh` | pytest + **3** research workers `npm test` | yes (`VERIFY_*`, missing `node_modules`, ingestion + `ci-aggregate` absent) |
| `verify_ci.sh` | pytest + catalog + IR + **7** workers ci/test/typecheck/dry-run | no |
| GitHub required context | six lane **receipts** of `npm ci && npm test` (if anyone POSTs them) | Python, catalog freeze, IR, typecheck, dry-run **not in the batch** |

`07b4435` documents “**and** `verify_ci`”. That is operator prose. Branch protection does not have a `verify_ci` context. PR #1 is `MERGEABLE` / `BLOCKED` because `ci-aggregate` has never posted — not because `verify_ci` ran.

`verify_all.sh` is unchanged as a skippable helper (still three workers). That is acceptable **only** if merge never treats it as CI. A green `verify_all` or a future PAT `ci-aggregate` success is still **not** a `verify_ci` run.

### Why this is still P0

The freeze P0 was merge-gate skip of the Python plane and of the gate Worker. The gate Worker is now in `verify_ci`. The merge gate still skips Python / catalog / IR. Do not treat “`ci-aggregate` is in `verify_ci.sh`” as FIXED for merge authority.

### Structural fix (unchanged intent)

- Make the merge-gate receipt command `scripts/verify_ci.sh` (or an equivalent receipt that cannot be `npm test` on one Worker).
- Keep `ci-aggregate` in `verify_ci` (already done).
- Keep `verify_all.sh` labeled helper-only.

---

## P632B-02 — Branch protection bypass / `ci-aggregate` vs actual GitHub checks

**severity:** P0  
**affected:** GitHub `ddnne/quant-platform` `main` protection; `platform/workers/ci-aggregate/`; live Cloudflare account `11233bca08d134a9b738eaa46b9751d9`  
**status:** **OPEN** (receipt POST auth **FIXED in tree**; live producer still absent)

### FIXED in tree (must stay)

`ff053a3` authenticates `POST /v1/receipts`:

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

SHA-256 compare is timing-safe on digests. Tests pin:

- unbound `CI_LANE_TOKEN` → 503, nothing posted
- wrong `X-CI-Lane-Token` → 401, nothing posted
- unbound `GITHUB_STATUS_TOKEN` still 503 fail-closed
- matching token + six-pass batch posts GitHub `success`
- PR comment body is not a success signal
- GET `/health` stays unauthenticated

`docs/ci/workers_builds.md` documents `X-CI-Lane-Token` / `CI_LANE_TOKEN`. The freeze finding “anyone who can reach the host can submit a six-pass batch” is **false of this tree**. It is still true of a deploy that omitted the secret (503, nothing posted) — fail-closed, not open POST.

`workers_dev = true` remains so lanes can POST without a custom zone. After a real deploy the host is a public `*.workers.dev` URL; inbound auth is now the fence, not network privacy.

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
GET /repos/ddnne/quant-platform/commits/07b4435…/status     → total_count: 0, state: pending
GET /repos/ddnne/quant-platform/commits/07b4435…/check-runs → total_count: 0
GET /repos/ddnne/quant-platform/commits/a48c600…/status     → total_count: 0
GET /repos/ddnne/quant-platform/commits/a48c600…/check-runs → total_count: 0
GET /repos/ddnne/quant-platform/actions/workflows           → total_count: 0
PR #1  mergeable=MERGEABLE  mergeStateStatus=BLOCKED  statusCheckRollup=[]
```

Wrangler (account `11233bca08d134a9b738eaa46b9751d9`, subdomain `taku-haga`):

```
GET /accounts/…/workers/scripts/quant-platform-ci-aggregate
  success: false  code: 10007  "This Worker does not exist on your account."

wrangler secret list --name quant-platform-ci-aggregate
  Worker "quant-platform-ci-aggregate" not found.

GET https://quant-platform-ci-aggregate.taku-haga.workers.dev/health
GET https://quant-platform-ci-aggregate.taku-haga.workers.dev/v1/receipts  (POST)
  HTTP 404  error code: 1042
```

Account worker list (11 scripts) includes the six product Workers and does **not** include `quant-platform-ci-aggregate`.

`GITHUB_STATUS_TOKEN` is therefore still **unbound in production**: there is no Worker to bind it on. Tree code still refuses to post without it.

### Why it is still P0

Branch protection still requires a context that:

1. has never been posted on `origin/main`, this reviewed SHA, or the prior freeze SHA,
2. is not produced by a deployed Worker,
3. is not an app-bound check-run (`app_id: null`),
4. can still be minted by any `repo:status` PAT **without** lane receipts.

Receipt auth in the tree does **not** close (4). A PAT with `repo:status` can `POST` `state=success` `context=ci-aggregate` for any SHA without talking to this Worker. That is the bypass the required-check configuration actually enforces.

`required_approving_review_count = 0` and `restrictions = null` add no second factor. `enforce_admins = true` only means admins also need that forgeable status. PR #1 stays BLOCKED because the context is missing, not because an honest producer ran.

Cloudflare Workers Builds check-runs remain **0**. Docs still say those are not the merge gate. Live they also do not exist.

### Structural fix (unchanged + tree auth)

- Deploy `quant-platform-ci-aggregate` only with **both** `CI_LANE_TOKEN` and `GITHUB_STATUS_TOKEN` bound (tree now requires both).
- Bind the required check to an **app** (or stop using a raw commit-status context as the sole gate).
- Until a real `success` exists on the SHA, do not merge to `main`. Do not PAT-green the context.
- Require `verify_ci` (P632B-01), not six `npm test` strings.

Do not add `.github/workflows` (P632B-07 remains FIXED-absent; `git ls-files` has no `.github/`; live Actions workflows **0**).

---

## What this review does not claim

- Projection FRESH, B0 PASS, READY, Mass GO, Phase 7 Controlled Pilot ON, Dataset COMPLETE 23.
- `verify_ci.sh` was executed at this HEAD (script/static tests only).
- `quant-platform-ci-aggregate` is live (Wrangler 10007; workers.dev 1042).
- `GITHUB_STATUS_TOKEN` or `CI_LANE_TOKEN` is bound in production (Worker missing).
- Independent P0 count is 0. It is **2** (P632B-01, P632B-02).
- P632B-03..07 were re-diffed (they were not).

---

## Blocked / unverified

- Live MCP remeasure this turn is **STALE** (`refresh_success=false`, READY **null**, B0 **UNKNOWN**). Counts are last-known-good under `projgen-ef18b4f86ee946048161d25e2a30a2a8`, not a new publication.
- Isolation worktree does **not** deploy, bind secrets, PAT-post `ci-aggregate`, or push.
- `wrangler.toml` comments still document only `GITHUB_STATUS_TOKEN`, not `CI_LANE_TOKEN`. Honesty residual, not a live unauthenticated POST.
- Missing-header (empty `X-CI-Lane-Token`) is covered by `authorized()` (`if (!got) return false` → 401 when the secret is bound). Tests pin wrong-token 401 and unbound 503; they do not have a separate no-header case. Not a live P0.
