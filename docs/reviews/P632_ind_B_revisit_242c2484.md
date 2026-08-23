# Independent review B revisit — at `242c2484`

**Reviewer:** independent Grok (isolation worktree; not the implementer)  
**Reviewed HEAD:** `242c2484` (`242c2484e9307f9163b13fc603ad90f67c6a0919`)  
**Branch at audit:** `grok/p632-ind-B-revisit-242c2484` (from `grok/phase63-ci-source-closure`)  
**Prior revisits:** `3b64bdfc` ([`P632_ind_B_revisit_3b64bdfc.md`](P632_ind_B_revisit_3b64bdfc.md)); `5103b26b` ([`P632_ind_B_revisit_5103b26b.md`](P632_ind_B_revisit_5103b26b.md)); `ed94d504` ([`P632_ind_B_revisit_ed94d504.md`](P632_ind_B_revisit_ed94d504.md)); `67fcbd7c` ([`P632_ind_B_revisit_67fcbd7c.md`](P632_ind_B_revisit_67fcbd7c.md)); `40d1aa90` ([`P632_ind_B_revisit_40d1aa90.md`](P632_ind_B_revisit_40d1aa90.md)); `f224e7e` ([`P632_ind_B_revisit_f224e7e.md`](P632_ind_B_revisit_f224e7e.md)); `07b4435` ([`P632_ind_B_revisit.md`](P632_ind_B_revisit.md)); freeze `a48c600` ([`P632_ind_B_ci_authority.md`](P632_ind_B_ci_authority.md))  
**origin/main:** `b5c326a7f612563f2da4a84f08063a307ec38e0a` (feature HEAD is **not** an ancestor of `main`; not merged)  
**Scope:** re-measure Independent B — CI skip, `ci-aggregate` live producer, tokens, R2, budget — vs HEAD `242c2484`. Tree-level receipt auth and seven-worker `verify_ci` already landed before `07b4435`. This turn re-diffs those plus P632B-03..07 against `3b64bdfc`. Live GitHub check-runs, `main` protection, and `wrangler deployments list --name quant-platform-ci-aggregate` are this-turn measurements. P632B-01 code-lane delta: Python Evaluation IR codec is generated and frozen in `verify_ci`. P632B-03 remains **HOLD** ([`P632B_03_gateway_token_service_binding_hold.md`](P632B_03_gateway_token_service_binding_hold.md) — HOLD, not closed). P632B-05 leftover remote `default_r2_put(` callers on mass-eval-run / daily-path moved to `put_research_artifact`.

Status vocabulary: **P0 / P1**, **OPEN / FIXED**. Do not invent Projection FRESH, B0 PASS, production READY, Coverage COMPLETE 23, Phase 7 GO, or **CI green**.

This file is **not** a GO. Independent P0 unresolved: **2**. Live producer of required context `ci-aggregate` is **still missing**.

---

## Live MCP (this isolation turn — not invented FRESH)

quant_mcp tools **were available**. Values below are this-turn reads. Projection is **STALE**. Latest READY snapshot is **null**. B0 is **UNKNOWN**. Do not narrate FRESH / READY / B0 PASS.

| Surface | Value |
|---------|--------|
| `ops_status.coverage_status_counts` | **22 COMPLETE · 4 PARTIAL** (ops_current; not a research READY snapshot) |
| `ops_status.last_run` | id 14319, `2026-08-24T01:15:01+09:00`, jquants, pass |
| `projection_status` | **STALE** |
| `active_generation` | `projgen-ef18b4f86ee946048161d25e2a30a2a8` |
| `projection_generated_at` | `2026-08-21T12:30:49.152421+00:00` |
| `projection_source_generation` | `2026-08-21T12:28:33.345482+00:00` |
| `projection_age_seconds` | 186991 (~51.94 h) |
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
| Is `POST /v1/receipts` still unauthenticated **in tree**? | **No.** Unbound `CI_LANE_TOKEN` → HTTP **503**; missing/wrong `X-CI-Lane-Token` → HTTP **401**. Unchanged vs `3b64bdfc`. Empty diff on `platform/workers/ci-aggregate`. |
| Does `verify_ci` include `ci-aggregate` (7 workers)? | **Yes.** `WORKERS` has **7** paths; `tests/test_verify_ci_script.py` pins `len(WORKERS) == 7` and `for name in WORKERS: assert name in src`. Python IR codec freeze is **added**; worker count is unchanged. |
| Are GitHub check-runs still 0 live at `242c2484`? | **Yes.** HEAD `242c2484`, prior `3b64bdfc`, `origin/main` `b5c326a`: `check-runs.total_count = 0`. Commit statuses `total_count = 0` / `state = pending`. PR #1 `statusCheckRollup = []`. Actions workflows **0**. |
| Does live `quant-platform-ci-aggregate` exist? | **No.** `wrangler deployments list --name quant-platform-ci-aggregate` → **10007** on account `11233bca08d134a9b738eaa46b9751d9`. `wrangler versions list` → same 10007. `wrangler secret list` → Worker not found. `*.workers.dev` **1042**. Account script list is **11** names and does **not** include this Worker. `GITHUB_STATUS_TOKEN` / `CI_LANE_TOKEN` therefore remain **unbound in production** (no Worker to hold them). |

P0 remaining: **yes, 2** (P632B-01 merge-gate producer is still six `npm test` receipts, not `verify_ci`; P632B-02 live producer missing / PAT-mintable `app_id: null` context). **Do not claim CI green.**

---

## Scoreboard vs `3b64bdfc` / `5103b26b` / `ed94d504` / `67fcbd7c` / `40d1aa90` / `f224e7e` / `07b4435` / `a48c600`

| ID | Topic | Sev | At `a48c600` | At `07b4435` | At `f224e7e` | At `40d1aa90` | At `67fcbd7c` | At `ed94d504` | At `5103b26b` | At `3b64bdfc` | At `242c2484` |
|----|-------|-----|--------------|--------------|--------------|---------------|---------------|---------------|---------------|---------------|---------------|
| P632B-01 | `verify_all` skip vs `verify_ci` authority | P0 | OPEN (scripts split FIXED; `ci-aggregate` absent from `verify_ci`; merge gate not `verify_ci`) | OPEN (`ci-aggregate` in `verify_ci` FIXED; GitHub still does not run `verify_ci`) | OPEN (IR jsonschema + `wrangler types --check` in `verify_ci` FIXED; merge gate still six lane receipts) | OPEN (`npm run types -- --check` + ALLOWED_FIELDS freeze in `verify_ci` FIXED; merge gate still six lane receipts) | OPEN (seven-worker `verify_ci` unchanged vs `40d1aa90`; merge gate still six lane receipts) | OPEN (IR encode-keys freeze in `verify_ci` FIXED; merge gate still six lane receipts) | OPEN (IR codec-generated freeze in `verify_ci` FIXED; merge gate still six lane receipts) | OPEN (`verify_ci.sh` empty vs `5103b26b`; test pins now require freeze **calls**; merge gate still six lane receipts) | **OPEN** (Python IR codec generated + `assert_evaluation_ir_codec_py_frozen` in `verify_ci` FIXED; merge gate still six lane receipts) |
| P632B-02 | Branch protection `ci-aggregate` vs actual GitHub checks | P0 | OPEN (unauthenticated POST; Worker 10007; check-runs 0; `app_id: null`) | OPEN (inbound auth FIXED in tree; live Worker / checks / token / app binding still OPEN) | OPEN (same live hole; Worker still 10007; check-runs still 0) | OPEN (same live hole; `wrangler deployments list` still 10007; check-runs still 0) | OPEN (same live hole; `wrangler deployments list` still 10007; check-runs still 0) | OPEN (same live hole; `wrangler deployments list` still 10007; check-runs still 0) | OPEN (same live hole; `wrangler deployments list` still 10007; check-runs still 0; print-only first-deploy helper is not a producer) | OPEN (same live hole; `wrangler deployments list` still **10007**; check-runs still **0**; print-only first-deploy helper is not a producer) | **OPEN** (same live hole; `wrangler deployments list` still **10007**; check-runs still **0**; print-only first-deploy helper is not a producer) |
| P632B-03 | Shared `GATEWAY_TOKEN` / `MASS_EVAL_TOKEN` | P1 | OPEN (header mix-up FIXED) | not re-diffed | OPEN (mass-eval still sends `GATEWAY_TOKEN`) | OPEN (mass-eval still sends `GATEWAY_TOKEN`) | OPEN (empty diff vs `40d1aa90`: mass-eval still sends `GATEWAY_TOKEN`) | OPEN (empty diff vs `67fcbd7c`: mass-eval still sends `GATEWAY_TOKEN`) | OPEN (empty diff vs `ed94d504`: mass-eval still sends `GATEWAY_TOKEN`) | OPEN (empty diff vs `5103b26b`: mass-eval still sends `GATEWAY_TOKEN`) | **OPEN / HOLD** (empty diff vs `3b64bdfc` on `ai_gateway_client.ts`; [`P632B_03_gateway_token_service_binding_hold.md`](P632B_03_gateway_token_service_binding_hold.md) is **HOLD, not closed**) |
| P632B-04 | Edge budget double-spend | P0/P1 | FIXED same-DO occupancy; OPEN P1 residuals | not re-diffed | same | same | same (P0 occupancy still FIXED; P1 residuals still OPEN; `89415105` honesty test only — live DO occupancy unproven) | same (empty production-path diff vs `67fcbd7c`; P1 residuals still OPEN; live DO occupancy unproven) | same (empty production-path diff vs `ed94d504`; P1 residuals still OPEN; live DO occupancy unproven) | same (empty production-path diff vs `5103b26b` on `research-ai-gateway`; P1 residuals still OPEN; live DO occupancy unproven) | **same** (empty production-path diff vs `3b64bdfc` on `research-ai-gateway`; P1 residuals still OPEN; live DO occupancy unproven) |
| P632B-05 | R2 child 409 / Python TOCTOU writer | P0/P1 | FIXED Worker 409; OPEN Python writer | not re-diffed | same | same severity (Worker `onlyIf` FIXED; remote Python put fail-closed without `QP_ALLOW_PYTHON_R2_PUT=1`) | same severity (Worker `onlyIf` still FIXED; `61c14a0d` Worker-client entry fail-closes with no HTTP client and no CLI fallback; callers still `default_r2_put`) | same severity (empty diff vs `67fcbd7c` on Worker `http.ts` and `r2_io.py`) | Worker 409 FIXED; Python default path POST; opt-in `QP_ALLOW_PYTHON_R2_PUT` still TOCTOU (P1 still OPEN; existing `default_r2_put` callers remain) | Worker 409 FIXED; overlay CLI TOCTOU CLOSED in tree; leftover `default_r2_put` callers remain (fail-closed, not racing) | **Worker 409 FIXED; overlay CLI TOCTOU CLOSED; leftover remote `default_r2_put(` on run/daily-path now `put_research_artifact`; remaining `default_r2_put(` is def + dry_run** (P1 residual OPEN; not live R2 proof) |
| P632B-06 | Active / Legacy catalog mix | P1 | FIXED Python partition; OPEN Worker/eval mix | not re-diffed | same | same | same (no `catalog_kind` in mass-eval Worker) | same (empty grep for `catalog_kind` under mass-eval Worker) | same (empty grep for `catalog_kind` under mass-eval Worker) | same (empty grep for `catalog_kind` under mass-eval Worker) | **same** (empty grep for `catalog_kind` under mass-eval Worker) |
| P632B-07 | GitHub Actions presence (must be absent) | P0 if present | FIXED (absent) | FIXED | FIXED | FIXED | FIXED (`git ls-files` has no `.github/`; live Actions workflows **0**) | FIXED (`git ls-files` has no `.github/`; live Actions workflows **0**) | FIXED (`git ls-files` has no `.github/`; live Actions workflows **0**) | FIXED (`git ls-files` has no `.github/`; live Actions workflows **0**) | **FIXED** (`git ls-files` has no `.github/`; live Actions workflows **0**) |

Independent P0 unresolved: **2**. Tree-level holes named at freeze for receipt auth and seventh-worker `verify_ci` stay closed. Overlay CLI put on `default_r2_put` is closed in tree. Python IR codec is present and frozen in local `verify_ci`. The live merge gate still has **no honest producer**. Do not invent Coverage COMPLETE, Projection FRESH, B0 PASS, READY, or CI green.

Window vs `3b64bdfc`: `git rev-list --count 3b64bdfc..242c2484` = **18**. CI-surface deltas that are **not** a P0 close: `c9764ff4` (Python Evaluation IR codec generated from `schema.json`; `verify_ci` presence-checks `evaluation_ir_codec.generated.py` and calls `assert_evaluation_ir_codec_py_frozen()`); `0a8ced34` (`cf_mass_eval_run` fallback artifacts use `put_research_artifact`); `017a43c6` (daily-path `both_track.json` uses `put_research_artifact`); `7221c588` (docs: GATEWAY_TOKEN service-binding residual remains **HOLD**). `platform/workers/ci-aggregate`, `scripts/ci_aggregate_first_deploy.sh`, `platform/workers/research-ai-gateway`, `platform/workers/research-mass-eval/src/ai_gateway_client.ts`, `platform/workers/research-mass-eval/src/http.ts`, and `packages/product/research/r2_io.py` are **empty diffs** against `3b64bdfc`. `scripts/verify_ci.sh` is a **6-line** freeze add, not a merge-gate close. Print-only `scripts/ci_aggregate_first_deploy.sh` is **not** a producer.

---

## P632B-01 — CI skip / `verify_all` vs `verify_ci`

**severity:** P0  
**affected:** `scripts/verify_ci.sh`; `scripts/verify_all.sh`; `tests/test_verify_ci_script.py`; `docs/ci/workers_builds.md`; `scripts/README.md`; `tests/README.md`; GitHub required context `ci-aggregate`  
**status:** **OPEN** (seven workers + IR schema + types `--check` honoring `scripts.types` + ALLOWED_FIELDS freeze + encode-keys freeze + TS codec-generated freeze + **Python codec-generated freeze** in `verify_ci` **FIXED**; merge-gate producer still six `npm test` receipts)

### FIXED (must stay)

`scripts/verify_ci.sh` still lists seven Workers (`WORKERS` array empty-diff vs `3b64bdfc`):

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

```186:192:scripts/verify_ci.sh
  if [[ -n "$(npm_script_body "$py" "$dir/package.json" types)" ]]; then
    echo "==> wrangler types --check ($name)"
    # Honor scripts.types flags (include-runtime false). Bare
    # `npx wrangler types --check` regenerates workerd runtime types.
    (cd "$dir" && npm run types -- --check)
```

Delta vs `3b64bdfc` (`c9764ff4`): Python Evaluation IR codec file is **present** and frozen.

- Tracked: `packages/product/research/evaluation_ir_codec.generated.py` (`git ls-files` lists it).
- Header: “Generated by `research.evaluation_ir` from `specs/evaluation_ir/schema.json`. Do not edit by hand.”
- `verify_ci.sh` presence-checks `codec_py` next to golden/schema/TS codec.
- Freeze call: `assert_evaluation_ir_codec_py_frozen()` (`evaluation_ir.py:1050-1063`).
- Tests pin the generated path and the freeze **call** (`tests/test_verify_ci_script.py:62-66,148-155`).

```69:85:scripts/verify_ci.sh
allowed_ts="$ROOT/platform/workers/research-mass-eval/src/evaluation_ir_allowed_fields.generated.ts"
codec_ts="$ROOT/platform/workers/research-mass-eval/src/evaluation_ir_codec.generated.ts"
codec_py="$ROOT/packages/product/research/evaluation_ir_codec.generated.py"
for p in "$golden" "$schema" "$schema_py" "$schema_ts" "$allowed_ts" "$codec_ts" "$codec_py"; do
  if [[ ! -f "$p" ]]; then
    echo "Evaluation IR missing golden/schema: $p" >&2
    exit 1
  fi
done
# ...
"$py" -c 'from research.evaluation_ir import assert_evaluation_ir_allowed_fields_ts_frozen, assert_evaluation_ir_codec_ts_frozen, assert_evaluation_ir_codec_py_frozen, assert_evaluation_ir_encode_keys_match_schema; assert_evaluation_ir_allowed_fields_ts_frozen(); assert_evaluation_ir_codec_ts_frozen(); assert_evaluation_ir_codec_py_frozen(); assert_evaluation_ir_encode_keys_match_schema()'
```

Local CI is stricter. GitHub still does not run `verify_ci`.

`tests/README.md` names `scripts/verify_ci.sh` as mandatory local CI; `verify_all.sh` is the helper. `scripts/README.md` leads with `verify_ci.sh` (seven workers including `ci-aggregate`). `docs/ci/workers_builds.md:96-102` still says six-lane `npm test` receipts “skip Python/catalog and are **not** `verify_ci`”. Merge “requires GitHub context `ci-aggregate` after authenticated receipts **and** `verify_ci`”.

This isolation turn did **not** execute `scripts/verify_ci.sh`. Script/static pins only. [`P632_verify_ci_3b64bdfc.md`](P632_verify_ci_3b64bdfc.md) is a later local PASS at `3b64bdfc`, not a GitHub status and not this SHA.

### OPEN (still P0)

GitHub `main` protection still requires only context `ci-aggregate`. That context is produced from **six lane receipts** of `npm ci && npm test` (`REQUIRED_WORKERS` in `platform/workers/ci-aggregate/src/index.ts:4-11`; `docs/ci/workers_builds.md:52-56,122-127`). It is **not** “`verify_ci.sh` exited 0”.

The three authorities remain:

| Surface | What it runs | Skip? |
|---------|--------------|-------|
| `verify_all.sh` | pytest + **3** research workers `npm test` | yes (`VERIFY_*`, missing `node_modules`, ingestion + `ci-aggregate` absent) |
| `verify_ci.sh` | pytest + catalog + IR jsonschema + ALLOWED_FIELDS freeze + encode-keys freeze + TS codec freeze + **Python codec freeze** + **7** workers ci/test/typecheck/dry-run/types `--check` | no |
| GitHub required context | six lane **receipts** of `npm ci && npm test` (if anyone POSTs them) | Python, catalog freeze, IR, typecheck, dry-run **not in the batch** |

`scripts/verify_all.sh` is unchanged as a skippable helper (`WORKERS` is still the three research workers). That is acceptable **only** if merge never treats it as CI.

`scripts/README.md:17` still says Evaluation IR golden/schema **presence** in the mandatory-CI sentence; `verify_ci.sh` jsonschema-validates and now freezes encode keys plus generated TS codec plus generated Python codec. Honesty residual, not a merge-gate close.

PR #1 is `MERGEABLE` / `BLOCKED` because `ci-aggregate` has never posted — not because `verify_ci` ran. Head SHA this turn is `242c2484`. A green `verify_all` or a future PAT `ci-aggregate` success is still **not** a `verify_ci` run. **Do not claim CI green.**

### Why this is still P0

The freeze P0 was merge-gate skip of the Python plane and of the gate Worker. The gate Worker is in `verify_ci`. The merge gate still skips Python / catalog / IR. Do not treat “`ci-aggregate` is in `verify_ci.sh`” or “Python codec freeze calls are pinned” as FIXED for merge authority.

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

`POST /v1/receipts` still authenticates. Empty diff vs `3b64bdfc` on `platform/workers/ci-aggregate`:

```235:244:platform/workers/ci-aggregate/src/index.ts
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

`docs/ci/workers_builds.md:19` still says: “live: Worker absent from account as of Independent B f224e7e/40d1aa90 — HUMAN create.” This turn re-measures: still absent. Line 21 still names the print-only helper.

`scripts/ci_aggregate_first_deploy.sh` is an **empty diff** vs `3b64bdfc`. Default is dry-run / print-only. `--apply` without `CONFIRM_CI_AGGREGATE_CREATE=1` fails closed. With the confirm env, the script **still prints** `npx wrangler deploy` as a comment and does **not** exec it. Tests pin no live secret values. That helper is operator text, not a producer. This isolation turn did **not** run `--apply` and did **not** deploy.

### Live GitHub / Cloudflare (this isolation turn)

Fetched 2026-08-23T16:28Z via `gh api` and Wrangler 4.125.0 (account `11233bca08d134a9b738eaa46b9751d9`, logged in as `taku_haga@icloud.com`, subdomain `taku-haga`):

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
GET /repos/ddnne/quant-platform/commits/3b64bdfc…/status    → total_count: 0, state: pending
GET /repos/ddnne/quant-platform/commits/3b64bdfc…/check-runs → total_count: 0
GET /repos/ddnne/quant-platform/commits/242c2484…/status    → total_count: 0, state: pending
GET /repos/ddnne/quant-platform/commits/242c2484…/check-runs → total_count: 0
GET /repos/ddnne/quant-platform/actions/workflows           → total_count: 0
PR #1  head=242c2484  mergeable=MERGEABLE  mergeStateStatus=BLOCKED  statusCheckRollup=[]
```

Wrangler deployments / versions / secrets for the named producer:

```
wrangler deployments list --name quant-platform-ci-aggregate
  GET /accounts/…/workers/scripts/quant-platform-ci-aggregate/deployments
  success: false  code: 10007  "This Worker does not exist on your account."

wrangler versions list --name quant-platform-ci-aggregate
  GET /accounts/…/workers/scripts/quant-platform-ci-aggregate/versions?deployable=true
  success: false  code: 10007  "This Worker does not exist on your account."

wrangler secret list --name quant-platform-ci-aggregate
  Worker "quant-platform-ci-aggregate" not found.

GET  https://quant-platform-ci-aggregate.taku-haga.workers.dev/health
POST https://quant-platform-ci-aggregate.taku-haga.workers.dev/v1/receipts
  HTTP 404  error code: 1042
```

Account script list (`wrangler deployments list --name` probes) is **11** names and does **not** include `quant-platform-ci-aggregate`:

```
news-collect, news-ingest, news-mcp,
quant-platform-ingestion-jsda, quant-platform-ingestion-premium,
quant-platform-ingestion-secrets, quant-platform-jsda-otc-probe-w80,
quant-platform-ops-read-mcp, quant-platform-research-ai-gateway,
quant-platform-research-mass-eval, tmp-exp-eval
```

`wrangler deployments list` therefore does **not** include `quant-platform-ci-aggregate`. The deployments endpoint 10007 is the existence proof, not an empty-but-present Worker.

### Why it is still P0

Branch protection still requires a context that:

1. has never been posted on `origin/main`, this reviewed SHA `242c2484`, prior revisit `3b64bdfc`, or earlier Independent B SHAs,
2. is not produced by a deployed Worker (`deployments list` 10007),
3. is not an app-bound check-run (`app_id: null`),
4. can still be minted by any `repo:status` PAT **without** lane receipts.

Receipt auth in the tree does **not** close (4). A PAT with `repo:status` can `POST` `state=success` `context=ci-aggregate` for any SHA without talking to this Worker. That is the bypass the required-check configuration actually enforces.

`required_approving_review_count = 0` and `restrictions = null` add no second factor. `enforce_admins = true` only means admins also need that forgeable status. PR #1 stays BLOCKED because the context is **missing**, not because an honest producer ran. Missing is not green.

Cloudflare Workers Builds check-runs remain **0**. Docs still say those are not the merge gate. Live they also do not exist.

A print-only first-deploy helper does not create the Worker. Do not treat `7dbcd9ea` / `a4453658` as P632B-02 FIXED. This isolation turn did **not** deploy `ci-aggregate` and did **not** PAT-mint the context.

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
**status:** **OPEN / HOLD** (cross-header substitute **FIXED**; shared secret on the caller **OPEN**). Empty diff vs `3b64bdfc` on `ai_gateway_client.ts`. [`P632B_03_gateway_token_service_binding_hold.md`](P632B_03_gateway_token_service_binding_hold.md) is **HOLD, not closed**.

### FIXED (must stay)

Gateway `authorized()` compares **only** `X-Gateway-Token` to `env.GATEWAY_TOKEN`. Tests still pin:

- `X-Mass-Eval-Token` is not accepted as the gateway header.
- `MASS_EVAL_TOKEN` value in `X-Gateway-Token` is not accepted.
- Unbound `GATEWAY_TOKEN` denies even if `MASS_EVAL_TOKEN` is set.

Mass-eval HTTP routes authorize with `env.MASS_EVAL_TOKEN` / `X-Mass-Eval-Token` only. Unbound `MASS_EVAL_TOKEN` on `POST /v1/children-then-manifest` is **503** (`52f3e70e`) — that is inbound mass-eval auth, not a gateway-token split.

### OPEN — HOLD (not closed)

Mass-eval still **sends** `GATEWAY_TOKEN` over the `AI_GATEWAY` service binding. Live grep this turn on `platform/workers/research-mass-eval/src/ai_gateway_client.ts`:

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

`7221c588` added [`P632B_03_gateway_token_service_binding_hold.md`](P632B_03_gateway_token_service_binding_hold.md). That document is an isolation HOLD: no documented unspoofable service-binding caller identity (`CF-Worker` is not authorization; service-binding HTTP `fetch` does not attach one). It does **not** close P632B-03. This Independent B revisit treats that HOLD as still in force. Do not mark P632B-03 FIXED.

---

## P632B-04 — Edge budget double-spend

**severity:** P0 (same-DO occupancy) **FIXED**; P1 residuals **OPEN**  
**affected:** `platform/workers/research-ai-gateway/src/budget_do.ts`; `src/index.ts`; `src/schema.ts`  
**status:** mixed. Production budget path empty vs `3b64bdfc`.

### FIXED (P0 occupancy)

`/v1/complete` still reserves before `env.AI.run`. Unbound `BUDGET_LEDGER` → 503. Occupancy = `used + reserved`. Same idempotency key does not double-increment. Exhausted reserve does not mutate counters.

`89415105` still pins: created ledger has **zero** occupancy; `budget_id` presence is not a reserve. Comment: “Live Cloudflare Durable Object occupancy is unproven.” That is honesty, not a live occupancy proof and not a P1 close. Empty production-path diff vs `3b64bdfc`.

### OPEN (P1)

1. **`schema.ts` still advertises the stub** (lines 147–151, error at 186): “A persistent Durable Object ledger is not in this commit” / “Edge ledger is not yet transactional.” Codec comment contradicts `index.ts` + `budget_do.ts`.
2. **Caller-chosen `budget_id` = new DO = new cap.** `idFromName(budgetId)` (`index.ts:112`). Each distinct id gets `PILOT_BUDGET_CAPS` again.
3. **Default idempotency is `crypto.randomUUID()`** (`index.ts:194`). Mass-eval `completeViaGateway` still does **not** send `Idempotency-Key` (grep over that Worker is empty this turn).
4. **Reconcile failure after a successful `AI.run` is ignored.** Handler still returns `ok: true` without checking reconcile `.ok`.

Not a live spend this turn (Mass NO-GO). Residual is still the same hole if the gateway is exercised.

---

## P632B-05 — R2 child conflict / Python TOCTOU writer as authority

**severity:** P0 Worker overwrite **FIXED**; overlay CLI TOCTOU **FIXED in tree**; P1 leftover callers **OPEN** (narrowed vs `3b64bdfc`)  
**affected:** `platform/workers/research-mass-eval/src/http.ts`; `src/http_routes.ts`; `packages/product/research/r2_io.py`; `cf_mass_eval_run.py`; `cf_mass_eval_stage.py`; `cf_mass_eval_job.py`; `cf_daily_path_job.py`; `reconstitution_evidence.py`  
**status:** mixed. Worker `onlyIf` empty vs `3b64bdfc`. `r2_io.py` empty vs `3b64bdfc`. Overlay CLI put remains closed. Two leftover **remote** `default_r2_put(` callers named at `3b64bdfc` now `put_research_artifact`. Live R2 POST unproven.

### FIXED (Worker 409)

`putJsonCreateOnly` (`http.ts:113-138`): `onlyIf: { etagDoesNotMatch: "*" }`; existing key with a different digest → 409. Child conflict still does not mint a manifest. Empty diff vs `3b64bdfc` on `http.ts`.

`putChildrenThenManifest` still writes children first, then the job manifest; any child `conflict` returns 409 without putting the manifest (`http.ts:207-230`).

Unbound `MASS_EVAL_TOKEN` on `POST /v1/children-then-manifest` is **503** (`52f3e70e`; tests pin empty put order). Missing/wrong token remains 401.

### FIXED (Python default path POST — tree only; overlay CLI TOCTOU closed)

`default_r2_put` remote path **always** raises `WORKER_CHILDREN_THEN_MANIFEST_ERROR` (`r2_io.py:361`). Overlay `QP_ALLOW_PYTHON_R2_PUT=1` does **not** resurrect `wrangler r2 object put`. Empty diff vs `3b64bdfc` on `r2_io.py`.

`put_research_artifact` dry_run stages locally via `default_r2_put`; remote POSTs Worker children-then-manifest with empty children and the object as the manifest (`r2_io.py:278-310`). Unbound URL/token fail closed. Overlay does not grant CLI put.

Delta vs `3b64bdfc`:

- `0a8ced34`: `cf_mass_eval_run.put_local_fallback_artifacts` default `put_fn` is `put_research_artifact`.
- `017a43c6`: `cf_daily_path_job` remote `both_track.json` calls `put_research_artifact`.

Job-artifact callers this HEAD that use `put_research_artifact`: `cf_mass_eval_job`, `cf_mass_eval_stage`, `cf_mass_eval_run`, `cf_daily_path_job`, `cf_cost_verify`, `cf_propose_thesis`, `occupancy_audit`.

That is Worker `onlyIf` on the default Worker-client path and no remaining CLI overlay writer. It is **not** a live R2 proof (Mass NO-GO; this isolation turn did not POST a live mass-eval host).

### OPEN (leftover `default_r2_put(` under `packages/product/research/*.py`)

Live grep this turn — remaining files that still **call** `default_r2_put(`:

| File | Role this HEAD |
|------|----------------|
| `r2_io.py` | definition (`:313`); dry_run staging inside `put_research_artifact` (`:297`) |
| `reconstitution_evidence.py` | `dry_run=True` only (`:377`) |

Gone vs `3b64bdfc` as **callers**: `cf_mass_eval_run.py`, `cf_daily_path_job.py`. Mentions of the name in `r2_io.py` comments / `__all__` remain.

Those leftover calls are dry_run / definition. They are **not** the overlay TOCTOU writer named at `5103b26b`. They are also **not** Worker `onlyIf`. Vestigial `python_r2_put_allowed()` still parses `QP_ALLOW_PYTHON_R2_PUT`; `default_r2_put` ignores it.

Do not treat P632B-05 as fully FIXED. Worker 409 stays FIXED. Overlay CLI TOCTOU is closed in tree. Remote job-artifact default path is Worker POST. Leftover dry_run callers + live POST remain residuals.

---

## P632B-06 — Active / Legacy catalog mix (spot-check)

**severity:** P1  
**status:** **FIXED** (Python partition); **OPEN** (Worker / eval still mixed). Empty grep for `catalog_kind` under `platform/workers/research-mass-eval`. `catalog_ids.ts` header still locks n=2254. `cf_mass_eval_job.default_logic_specs` still does `py_by_id or yaml_by_id` over `load_catalog_specs()` (`cf_mass_eval_job.py:159-165`). Not GO. Independent C owns the catalog scoreboard; this line is occupancy, not a new P0.

---

## P632B-07 — GitHub Actions presence (must be absent)

**severity:** P0 if present  
**status:** **FIXED** (absent)

- `git ls-files .github` is empty. No workflow YAML under `.github/`.
- `GET /repos/ddnne/quant-platform/actions/workflows` → **0**.

`.grok/workflows/*.rhai` is not GitHub Actions. Empty GHA is **not** a missing pipeline. Do **not** add `.github/workflows` to “fix” P632B-01/02.

---

## What this review does not claim

- Projection FRESH, B0 PASS, READY, Mass GO, Phase 7 Controlled Pilot ON, Dataset COMPLETE 23.
- **CI green.** Check-runs are 0. Statuses are pending/empty. The required context has never been posted. `wrangler deployments list` does not include `quant-platform-ci-aggregate`.
- `verify_ci.sh` was executed at this HEAD (script/static tests only).
- `quant-platform-ci-aggregate` is live (Wrangler deployments **10007**; versions **10007**; workers.dev **1042**).
- `GITHUB_STATUS_TOKEN` or `CI_LANE_TOKEN` is bound in production (Worker missing).
- Live children-then-manifest POST against a production mass-eval host (tree + HTTP stub only).
- Independent P0 count is 0. It is **2** (P632B-01, P632B-02).
- P632B-03 CLOSED. It is **HOLD** ([`P632B_03_gateway_token_service_binding_hold.md`](P632B_03_gateway_token_service_binding_hold.md)).
- P632B-05 fully FIXED. Worker 409 is FIXED; overlay CLI TOCTOU is closed in tree; leftover remote run/daily-path callers now Worker POST; leftover `default_r2_put(` is definition + dry_run; live R2 unproven.

---

## Blocked / unverified

- Live MCP remeasure this turn is **STALE** (`refresh_success=false`, READY **null**, B0 **UNKNOWN**). Counts are last-known-good under `projgen-ef18b4f86ee946048161d25e2a30a2a8`, not a new publication.
- Isolation worktree does **not** deploy, bind secrets, PAT-post `ci-aggregate`, push `main`, or invent GO.
- `wrangler.toml` comments still document only `GITHUB_STATUS_TOKEN`, not `CI_LANE_TOKEN`.
- Missing-header (empty `X-CI-Lane-Token`) is covered by `authorized()` (`if (!got) return false` → 401 when the secret is bound). Tests pin wrong-token 401 and unbound 503; they do not have a separate no-header case. Not a live P0.
- `scripts/README.md:17` still says Evaluation IR golden/schema **presence**; `verify_ci.sh` jsonschema-validates and freezes generated ALLOWED_FIELDS plus encode keys plus generated TS codec plus generated Python codec. Honesty residual. Merge gate is still not `verify_ci`.
- Print-only first-deploy helper was not executed with `--apply`. Default path prints dry-run commands only. It is not a producer.

Keep GitHub Actions absent (P632B-07). Do not merge `main` on a PAT `ci-aggregate` success.
