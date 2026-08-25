# Phase 6.3.2 Wave-8 status — leak register vs current HEAD (not a GO)

**Isolation worktree:** `/private/tmp/qp-p632-wave8-status` on `grok/p632-wave8-status` (do not push `main`).  
**Does not clobber:** [`P632_brief_leaks.md`](P632_brief_leaks.md) (A–S freeze vs `3ab87d0`), [`P632_wave2_status.md`](P632_wave2_status.md) (A–S freeze vs `07b4435`), [`P632_wave3_status.md`](P632_wave3_status.md) (A–S freeze vs `f224e7e`), [`P632_wave4_status.md`](P632_wave4_status.md) (A–S freeze vs `40d1aa90`), [`P632_wave5_status.md`](P632_wave5_status.md) (A–S freeze vs `67fcbd7c`), [`P632_wave6_status.md`](P632_wave6_status.md) (A–S freeze vs `ed94d504`), or [`P632_wave7_status.md`](P632_wave7_status.md) (A–S freeze vs `5103b26b`). Those files stay earlier freezes.  
**Feature branch:** `grok/phase63-ci-source-closure`  
**This HEAD (reviewed):** `3b64bdfc` (`3b64bdfc9a41be76a6e4e881aaea1ff9751443ed`) — `docs: 6.3.2 wave-7 status after 17 commits vs 5103b26b`.  
**Window:** 16 commits after `5103b26b` (`5103b26bb40b2d73b49d079e03f8cf5b9c2a4c58`). Count: `git rev-list --count 5103b26b..3b64bdfc` = **16**.  
**`origin/main`:** `b5c326a` (`b5c326a7f612563f2da4a84f08063a307ec38e0a`) — feature branch is **not** an ancestor of `main`; **not merged**. `main` is an ancestor of this HEAD.  
**Named review SHA in brief:** `b5c326a` — **not** a freeze.  
**PR:** https://github.com/ddnne/quant-platform/pull/1 — `MERGEABLE` / mergeState **`BLOCKED`** (required `ci-aggregate` has not posted). Head OID this turn: `3b64bdfc`.

**HUMAN bottleneck:** live `quant-platform-ci-aggregate` Worker **absent** (Wrangler deployments/versions **10007**; secrets “not found”; `workers.dev` `/health` HTTP **404** / error **1042**). Print-only `scripts/ci_aggregate_first_deploy.sh` does **not** create it. Isolation does not deploy it. **ci-aggregate create remains the bottleneck.**

Earlier freezes (cite, do not rewrite):

| Freeze | SHA | File |
|--------|-----|------|
| Wave-0 live remeasure | `61b773a` | [`P632_wave0_live.md`](P632_wave0_live.md) |
| Wave-1 A–S register | `3ab87d0` | [`P632_brief_leaks.md`](P632_brief_leaks.md) |
| Wave-2 after P0 code closes | `07b4435` | [`P632_wave2_status.md`](P632_wave2_status.md) |
| Wave-3 after 30 commits | `f224e7e` | [`P632_wave3_status.md`](P632_wave3_status.md) |
| Wave-4 after 20 commits | `40d1aa90` | [`P632_wave4_status.md`](P632_wave4_status.md) |
| Wave-5 after 17 commits | `67fcbd7c` | [`P632_wave5_status.md`](P632_wave5_status.md) |
| Wave-6 after 17 commits | `ed94d504` | [`P632_wave6_status.md`](P632_wave6_status.md) |
| Wave-7 after 17 commits | `5103b26b` | [`P632_wave7_status.md`](P632_wave7_status.md) |
| Wave-8 (this file) | `3b64bdfc` | this re-diff |

Status vocabulary: **OPEN / FIXED / PARTIAL / HOLD / HUMAN**.  
Do not invent Coverage COMPLETE, Projection FRESH, B0 PASS, READY, Phase 6.3.2 COMPLETE, Phase 6.4 COMPLETE, or Phase 7 GO.

---

## Live MCP (this wave; tools available)

quant_mcp tools **worked** this isolation turn. Values below are this-turn reads, not last-known docs. Isolation does not refresh the ledger. No GitHub check-runs MCP existed; live GitHub below is `gh api`. Live Cloudflare is Wrangler 4.125.0 (account `11233bca08d134a9b738eaa46b9751d9`, logged in as `taku_haga@icloud.com`).

```text
Projection: STALE
  generated_at: 2026-08-21T12:30:49.152421+00:00
  age_seconds: 185866 (~51.6h)
  active_generation: projgen-ef18b4f86ee946048161d25e2a30a2a8
  projection_source_generation: 2026-08-21T12:28:33.345482+00:00
  refresh_attempt: true
  refresh_success: false
  last_known_good.not_fresh: true

B0: UNKNOWN  (snapshot quality/B0 projection is unavailable)

READY: null  (no published READY generation is bound to this Worker)

Sync: applied_feed_cursor: null
  latest_change_seq: 2890664
  CURRENT datasets: 0
  typical dataset state: LAGGING_APPLY_UNPINNED
  indices_bars_daily_topix: EXPORT_CURRENT_APPLY_UNPINNED (lag 0, pin still null → never CURRENT)

Coverage: 22 COMPLETE / 4 PARTIAL  (policy_version collection-coverage/v2)
  equities_master PARTIAL history_target_start 2006-08-13
    backfill 241 / 220 / 21  observed 2008-05-01 → 2026-08-12
  equities_bars_daily_am PARTIAL history_target_start 2024-01-04
    backfill 32 / 1 / 31  observed 2026-08-01 → 2026-08-11
  equities_earnings_calendar PARTIAL history_target_start 2010-01-04
    backfill 200 / 1 / 199  observed 2010-01-04 → 2026-08-14
  jsda_otc_bond_reference_prices PARTIAL history_target_start 2002-08-02
    backfill 8784 / 5886 / 2898  observed 2002-08-06 → 2026-08-20

Inventory: 26 governed / 5 experimental / 31
Ops last_run: id 14318 PASS (jquants, 2026-08-24T00:15:01+09:00)
Raw: manifests 20493 / complete 18278
  live ops_status.raw_retention still emits complete (no acquired key)
  tree b96d60bd adds acquired + deprecated complete alias; live Worker not that SHA
AM SLA current_state: PROJECTION_STALE (state_reason: ops_projection_stale)
storage_plane_status.p0_claims.mass_research: NO-GO
storage_plane_status.p0_claims.ready: null
```

Live GitHub (this turn; `gh api`, not invented):

```text
commits/3b64bdfc/check-runs  total_count: 0
commits/3b64bdfc/status      state: pending, total_count: 0
PR #1                       mergeable: MERGEABLE
                            mergeStateStatus: BLOCKED
                            statusCheckRollup: null
                            headRefOid: 3b64bdfc9a41be76a6e4e881aaea1ff9751443ed
Actions workflows           total_count: 0
main protection             required_status_checks.contexts=["ci-aggregate"]
                            app_id: null, strict: true, enforce_admins: true
                            allow_force_pushes: false
origin/main check-runs      total_count: 0
.git/ ls-files .github      0
```

Live Cloudflare producer (this turn; Wrangler, not invented):

```text
wrangler deployments list --name quant-platform-ci-aggregate
  GET /accounts/11233bca…/workers/scripts/quant-platform-ci-aggregate/deployments
  success: false  code: 10007  "This Worker does not exist on your account."

wrangler versions list --name quant-platform-ci-aggregate
  success: false  code: 10007  "This Worker does not exist on your account."

wrangler secret list --name quant-platform-ci-aggregate
  Worker "quant-platform-ci-aggregate" not found.

GET  https://quant-platform-ci-aggregate.taku-haga.workers.dev/health
  HTTP 404  error code: 1042
```

Cron PASS, raw-retention COMPLETE, and row-count growth are **not** Coverage COMPLETE or READY. Local `verify_ci` at `5103b26b` is **not** a posted GitHub context. Print-only first-deploy is **not** a producer.

---

## Verdict

| Gate | Status |
|------|--------|
| Phase 6.3.2 COMPLETE? | **NOT COMPLETE** |
| Phase 6.4 COMPLETE? | **NOT COMPLETE** |
| Phase 7 Foundation | types exist; `PHASE7=OFF` |
| Phase 7 Controlled Pilot GO? | **NO-GO** |
| Phase 7 Mass Research GO? | **NO-GO** |

Wave-8 **tree** honesty (overlay never CLI-put, research job artifacts Worker POST, unbound token **503**, leftover occupancy HOLD pointer, `verify_ci` PASS documented at `5103b26b`, docs freezes) is not a GO. Brief §8 `Pilot_GO` is a conjunction; live legs still fail: Projection **STALE**, `refresh_success=false`, B0 **UNKNOWN**, READY **null**, `applied_feed_cursor=null`, required GitHub `ci-aggregate` **not posted** (`check-runs total_count: 0`), Coverage still V2 **22 / 4 PARTIAL**, independent P0 unresolved ≠ 0 (live merge gate; **ci-aggregate Worker absent**).

**HUMAN bottleneck named:** `quant-platform-ci-aggregate` Worker **absent**. Branch protection requires a context that has no producer on the account. Isolation must not deploy, bind secrets, or PAT-mint `ci-aggregate`. `scripts/ci_aggregate_first_deploy.sh` prints operator commands and refuses `--apply` without `CONFIRM_CI_AGGREGATE_CREATE=1`; even then it is still print-only. **ci-aggregate create remains the bottleneck.**

---

## Named landings this wave (tree, not live GO)

| SHA | Landing | Closes (tree) | Does **not** close |
|-----|---------|---------------|-------------------|
| `0b81eedb` | remote Python R2 put never CLI-puts even with overlay | `default_r2_put` remote always raises `WORKER_CHILDREN_THEN_MANIFEST_ERROR`. `QP_ALLOW_PYTHON_R2_PUT=1` does **not** grant `wrangler r2 object put`. No `subprocess` in `default_r2_put`. Overlay env is not artifact authority and does not resurrect TOCTOU. `authoritative=True` still refused. dry_run stays local. | Overlay helper `python_r2_put_allowed()` still exists (**HOLD** identity). Live Worker POST unproven. Remaining remote `default_r2_put` callers fail-closed; they are not Worker `onlyIf`. |
| `d6567268` | remote job artifacts use Worker children-then-manifest | `put_research_artifact` POSTs empty children + job object as manifest. `cf_cost_verify`, `cf_mass_eval_job`, `cf_mass_eval_stage`, `cf_propose_thesis`, `occupancy_audit` switched. Overlay does not grant CLI put on this path. Tests stub HTTP. reconstitution evidence stays dry-run-only. | Live mass-eval POST unproven. `cf_daily_path_job` and `cf_mass_eval_run.put_local_fallback_artifacts` still call `default_r2_put`. Not a live R2 create-if-absent proof. |
| `52f3e70e` | children-then-manifest unbound token is 503 | Unbound `MASS_EVAL_TOKEN` fail-closes `POST /v1/children-then-manifest` with **503** and does not put. Missing header stays **401**. Digest mismatch 409 and same-digest replay stay helper-covered. | Live token bind **HUMAN**. Not merge-gate. Not a posted `ci-aggregate`. |
| `046ae438` | leftover occupancy HOLD pointer; do not unify | `unique22_occupancy_park` docstring: park reasons live in `UNIQUE22_PARK_REASONS`; leftover occupancy stays in `daily_path.ts`. Do not extract or unpark. Do not unify with `comboEventGateOk`. | Occupancy extract still **HOLD**. unique22 leftover **22** (17 parked + 5 occupancy-equal lifts). Not a catalog compact. |
| `2e264a08` | pin `verify_ci` Evaluation IR generated TS freeze **calls** | Pins `assert_evaluation_ir_*()` invocations, not just function names. `verify_ci.sh` already `python -c` freeze-checks both generated TS files. | Python encode/decode still hand-written (`evaluation_ir.py` 1076). Not merge-gate. |
| `9c208ec3` | `verify_ci` code-lane PASS documented at `5103b26b` | Local `scripts/verify_ci.sh` exit-0 at `5103b26b`: **1492 passed / 4 skipped**; 7 workers; wall 195.15s. [`P632_verify_ci_5103b26b.md`](P632_verify_ci_5103b26b.md). | **Not** this HEAD. **Not** GitHub `ci-aggregate`. **Not** merge-gate. |
| `a4453658` | name print-only ci-aggregate first-deploy helper | `docs/ci/workers_builds.md` names `scripts/ci_aggregate_first_deploy.sh`. | Does **not** deploy. Worker still **10007**. HUMAN create remains. |
| docs freezes | inventory / remaining-extracts / residual banner / review index / original-plan-gap / independent A–C / wave-7 status | Operator notes vs `5103b26b`. Wave-7 A–S freeze is [`P632_wave7_status.md`](P632_wave7_status.md). | Not live GO. `6447a3fa` remaining-extracts freeze is authored vs `5103b26b` and does **not** yet name overlay-never-CLI-put / research-artifact POST / leftover occupancy pointer / unbound 503. |

This isolation did **not** re-run `scripts/verify_ci.sh` at `3b64bdfc`. The `5103b26b` local PASS ([`P632_verify_ci_5103b26b.md`](P632_verify_ci_5103b26b.md): **1492 passed / 4 skipped**) is the wave-7 freeze SHA, not this HEAD, and is **not** merge-gate.

---

## The 16 commits after `5103b26b`

| SHA | Landing | Lane |
|-----|---------|------|
| `2cb9bd15` | 6.3.2 P test inventory at `5103b26b` | docs (P) |
| `2e264a08` | pin `verify_ci` Evaluation IR generated TS freeze calls | C / O |
| `a4453658` | name print-only ci-aggregate first-deploy helper | docs (A / HUMAN) |
| `52f3e70e` | children-then-manifest unbound token is 503 | M |
| `6447a3fa` | §10.3 mixed authority remaining at `5103b26b` | docs (Q freeze) |
| `11ffe387` | residual SoT banner HEAD `5103b26b` vs `origin/main` `b5c326a` | docs |
| `ed952c44` | review index names HEAD `5103b26b` vs `origin/main` `b5c326a` | docs |
| `4d970200` | banner original-plan-gap register still holds at `5103b26b` | docs |
| `558759e4` | independent review A revisit at `5103b26b` | docs (A freeze) |
| `40d4d9e8` | independent review B revisit at `5103b26b` | docs (B freeze) |
| `71c25a72` | independent review C catalog/pilot revisit at `5103b26b` | docs (C freeze) |
| `046ae438` | leftover occupancy HOLD pointer; do not unify | N / Q HOLD |
| `0b81eedb` | remote python R2 put never CLI-puts even with overlay | M / Q |
| `d6567268` | remote job artifacts use Worker children-then-manifest | M / Q |
| `9c208ec3` | P632 `verify_ci` code-lane PASS at `5103b26b` | docs (C; not merge-gate) |
| `3b64bdfc` | wave-7 status after 17 commits vs `5103b26b` | docs (wave-7 freeze) |

Docs commits in this window (`2cb9bd15`, `a4453658`, `6447a3fa`, `11ffe387`, `ed952c44`, `4d970200`, `558759e4`, `40d4d9e8`, `71c25a72`, `9c208ec3`, `3b64bdfc`) are freezes / operator notes, not live GO. `6447a3fa` remaining-extracts freeze is authored vs `5103b26b` and does **not** yet name the wave-8 code closes.

---

## A–S vs `3b64bdfc` (after the 16)

Prior registers: [`P632_brief_leaks.md`](P632_brief_leaks.md) vs `3ab87d0`; [`P632_wave2_status.md`](P632_wave2_status.md) vs `07b4435`; [`P632_wave3_status.md`](P632_wave3_status.md) vs `f224e7e`; [`P632_wave4_status.md`](P632_wave4_status.md) vs `40d1aa90`; [`P632_wave5_status.md`](P632_wave5_status.md) vs `67fcbd7c`; [`P632_wave6_status.md`](P632_wave6_status.md) vs `ed94d504`; [`P632_wave7_status.md`](P632_wave7_status.md) vs `5103b26b`. This table is the wave-8 re-diff, not a rewrite of those files.

### A. Cloudflare mandatory CI

**status: PARTIAL** (protection + Worker **code** + `CI_LANE_TOKEN` + 7-worker `verify_ci` + types flags + IR codec freeze + freeze-**call** pin + print-only first-deploy helper named in operator map) / **OPEN** (live check never posted; **Worker absent**) / **HUMAN** (`quant-platform-ci-aggregate` first deploy + token bind)

| Sub-item | At `5103b26b` (wave-7) | After wave-8 |
|----------|------------------------|--------------|
| `.github/` workflows | **FIXED** (absent) | **FIXED** — `git ls-files .github` empty; Actions `total_count: 0`. Do not add. |
| Aggregate Worker | **FIXED** (code) + print-only helper. Live Worker **absent**. | **FIXED** (code) + helper named in `docs/ci/workers_builds.md` (`a4453658`). Live Worker **absent** — deployments **10007**, secrets not found, `/health` **404**. Named **HUMAN** bottleneck. Helper does not wrangler deploy. |
| `verify_ci` covers gate Worker | **FIXED** + generated codec freeze. Local PASS documented at `ed94d504`, not `5103b26b`. | **FIXED** + freeze-**call** pin (`2e264a08`). Local PASS now documented at `5103b26b` ([`P632_verify_ci_5103b26b.md`](P632_verify_ci_5103b26b.md)), not this HEAD, not GitHub. |
| Branch protection on `main` | **FIXED** (requires `ci-aggregate`) | **FIXED** (setting). `app_id: null`. Not a passing receipt. |
| GitHub check-runs / statuses at HEAD | **OPEN** (`5103b26b` `total_count: 0`) | **OPEN** — this turn `3b64bdfc` `total_count: 0`; `/status` `pending` / `0`. PR #1 `MERGEABLE` / `BLOCKED`; `statusCheckRollup: null`. |
| Fail/pass merge smoke | **OPEN** | **OPEN** — cannot smoke a producer that does not exist |
| Token bind | **HUMAN** | **HUMAN** — agent must not mint; nothing to bind until Worker exists; helper never puts secret values |
| Workers Builds Git integration | **OPEN** | **OPEN** |
| Explicit promote vs auto-deploy | **HOLD** | **HOLD** |

### B. All six Workers reproducible build

**status: PARTIAL** (lockfiles; seven `npm run types -- --check`) / **OPEN** (clean-checkout proof at this HEAD; retry jitter still `Math.random`)

Unchanged vs wave-7 except: local `verify_ci` PASS is now **documented** at `5103b26b` ([`P632_verify_ci_5103b26b.md`](P632_verify_ci_5103b26b.md): 7 workers including `ci-aggregate` 13 tests; **1492 passed / 4 skipped**). That is a different SHA than this HEAD. Clean-checkout matrix **not** executed at `3b64bdfc` in this isolation. Residual `Math.random()` is retry/jitter only (`ingestion-premium` `index.ts:171,181`, `persist_records.ts:36`) — not identity (`crypto.randomUUID` still FIXED).

Do not invent PASS at `3b64bdfc`.

### C. Authoritative CI script

**status: PARTIAL** (`verify_ci.sh` fail-closed, 7 workers, IR schema, generated `ALLOWED_FIELDS`, encode-key lock, generated codec freeze, freeze-**call** pin, types flags, **local PASS at `5103b26b`**, print-only first-deploy helper named) / **OPEN** (merge gate is live GitHub context; producer Worker **absent**)

- Authoritative: `scripts/verify_ci.sh`. `WORKERS` still includes `platform/workers/ci-aggregate`. Missing lockfile/dir/script fails. No skip of missing `node_modules`. No `--legacy-peer-deps`.
- Fast helper remains `scripts/verify_all.sh` (three research workers; optional `VERIFY_*`). Still **not** mandatory CI. Do not merge the two (HOLD split).
- `2e264a08`: pin actual `assert_evaluation_ir_allowed_fields_ts_frozen()` / `assert_evaluation_ir_codec_ts_frozen()` / `assert_evaluation_ir_encode_keys_match_schema()` invocations in `verify_ci.sh`, not just the function names.
- Local PASS at `5103b26b`: 1492 passed / 4 skipped; wall 195.15s; `verify_ci: ok`. **Not** merge-gate. **Not** this HEAD. This isolation did not re-run the script after the wave-8 code landings (`52f3e70e`, `046ae438`, `0b81eedb`, `d6567268`, `2e264a08`).
- Print-only operator helper still does **not** create a fresh venv (requires existing `.venv` 3.11+). Live merge authority is still “six lane receipts POSTed with `CI_LANE_TOKEN` → GitHub `ci-aggregate`”, and that POST host **does not exist**.

### D. SourceCapabilityContract V3

**status: PARTIAL** (typed loader + **4** dataset files + SoT clip + missing-file fail-closed + OTC grain token + nested-open pin) / **OPEN** (22 governed datasets have no V3 file; nested maps open)

On-disk: `specs/source_capability/{equities_master,equities_earnings_calendar,equities_bars_daily_am,jsda_otc_bond_reference_prices}.json`. Nested evidence maps remain **OPEN** by design. Missing V3 JSON is `None`, not invented.

Planner **does** clip through SourceCapability SoT. That is a wire, not Dataset COMPLETE 23. Live MCP is STALE and still advertises V2 floors. Empty diff vs wave-7 on the four files.

### E. Equities Master contract

**status: PARTIAL** (V3 + planner + core profile + PIT clamp + `jquants_records` island + BackfillPlanner required-segments) / **OPEN** (live STALE still V2 `2006-08-13`)

Repo official start `2008-05-07`. Live MCP: last-known **PARTIAL** under STALE V2 `2006-08-13` (`backfill_status` 241 / 220 / 21). Official-domain correction in git ≠ live required-set migration. Do not invent Dataset COMPLETE.

### F. Earnings Calendar contract

**status: PARTIAL** (V3 + tip-snapshot planner + empty receipt PARTIAL + READY fixture honesty + event-zero tip PARTIAL) / **OPEN** (live still 200 monthly V2 PARTIAL under STALE)

Planner yields **1** cutoff snapshot, not 200 months. Do not empty past months into COMPLETE. Live `backfill_status` 200 / 1 / 199.

### G. AM bars contract

**status: PARTIAL** (V3 + same-day snapshot planner + empty receipt PARTIAL + event-zero tip PARTIAL) / **OPEN** (live still monthly V2 PARTIAL; SLA under STALE)

Planner yields **1** cutoff snapshot, not 32 months. `collection_sla_status(equities_bars_daily_am)` this turn: `current_state: PROJECTION_STALE` / `state_reason: ops_projection_stale`. Live `backfill_status` 32 / 1 / 31. Do not invent AM SLA PASS.

### H. JSDA OTC official-index Coverage

**status: PARTIAL** (V3 file + planner + HTML index SoT + refresh wire + CLI `index_text` + JSON grain + sealer `index_text` + `issue_*` `--index-text` + pipeline held HTML) / **OPEN** (live STALE calendar inventory; PARSE_ZERO not sealed; BackfillPlanner still has no `index_text`)

Empty production-path diff vs wave-7 on JSDA. Live MCP still last-known Wave-0 **5886 / 8784** under `history_target_start: 2002-08-02`. Tree refresh ≠ live ledger migration.

- `PARSE_ZERO_SEAL_PROOF` stays empty — `2002-08-02` / `2002-08-05` stay **PARTIAL** without in-repo digest+count.
- BackfillPlanner still has **no** `index_text` argument (`packages/data_plane/ops/backfill_planner.py`). JQ jobs do not need it; an OTC job through that planner would fail-closed empty.

Do not COMPLETE empty non-index days. Do not hide PARSE_ZERO by moving `history_target_start`.

### I. ResearchDataProfile / READY

**status: PARTIAL** (v1 predicate + core requires master + string COMPLETE rejected + missing V3 false + mixed policy honesty + fixture tip receipts + tip/index event-zero PARTIAL) / **OPEN** (live READY **null**)

Unchanged vs wave-7 live. `latest_ready_snapshot`: **null**. Digest-bound predicate ≠ a bound READY generation. STALE V2 PARTIAL keeps READY honest-false. That is intended; it is not a GO.

### J. Projection / sync operational closure

**status: OPEN** (live) — presentation honesty **FIXED** (do not re-open)

| Criterion | Live (this turn) |
|-----------|------------------|
| `projection_status` | **STALE** |
| `refresh_success` | **false** |
| `applied_feed_cursor` | **null** |
| CURRENT datasets | **0** |
| B0 | **UNKNOWN** |
| READY | **null** |

`applied == null` still never CURRENT. Last-known-good is **not** FRESH (`last_known_good.not_fresh: true`). `0007_ops_applied_pins` remote apply is **HUMAN**.

Live MCP this turn still returns only `complete: 18278` — the deployed ops-mcp Worker is **not** this SHA. Tree honesty is not a publish. See [`P632_projection_stale.md`](P632_projection_stale.md) and [`P632_projection_refresh_false.md`](P632_projection_refresh_false.md).

### K. Edge Durable Object hard budget

**status: PARTIAL** (DO reserve/reconcile in repo + create≠reserve pin) / **OPEN** (live Edge unproven)

Unchanged vs wave-7. Caps unchanged (`auto_promotion: false`). Live occupancy / double-spend under production traffic: **not** measured this wave. String `budget_id` is still not the reserve.

### L. Worker public boundary

**status: PARTIAL** (preview vs production split) / **OPEN** (shared bearer still required on remaining surfaces) / **HOLD** (`workers_dev` kept where documented) / **HUMAN** (secret bind)

Unchanged vs wave-7: production `workers_dev=false` on research-ai-gateway, research-mass-eval, ingestion-jsda, ingestion-premium. **Kept true:** quant-ops-mcp (OAuth callback), ingestion-secrets (token-gated local), ci-aggregate (receipt POST host). Treat **kept** as **HOLD**. Dual `GATEWAY_TOKEN` / service-binding residual: **OPEN** (mass-eval `ai_gateway_client.ts` still sends `GATEWAY_TOKEN` as `X-Gateway-Token`). Ops MCP must not grow SQL / fetch / ingest / delete / READY publish. Not re-opened.

`ci-aggregate` `workers_dev=true` is moot until the Worker exists. Unbound mass-eval token on children-then-manifest is now **503** (`52f3e70e`); that is fail-closed, not a secret bind.

### M. Immutable artifact authority

**status: PARTIAL** (Worker child digest 409 + overlay never CLI-put + Worker POST client + research-artifact POST + unbound token 503) / **OPEN** (live POST unproven; remaining remote `default_r2_put` callers fail-closed, not Worker `onlyIf`) / **HOLD** (overlay identity helper still exists)

Wave-8 vs wave-7:

- `0b81eedb`: remote `default_r2_put` **never** CLI-puts, even with `QP_ALLOW_PYTHON_R2_PUT=1`. No `subprocess` in that function. Overlay does not resurrect TOCTOU. Wave-7 named overlay `=1` as remaining TOCTOU; that CLI path is now **FIXED** (tree fail-closed).
- `d6567268`: `put_research_artifact` POSTs Worker children-then-manifest (empty children; object is the manifest). Callers switched: `cf_cost_verify`, `cf_mass_eval_job`, `cf_mass_eval_stage`, `cf_propose_thesis`, `occupancy_audit`. Tests stub HTTP. This isolation did not hit a live mass-eval Worker.
- `52f3e70e`: unbound `MASS_EVAL_TOKEN` on `POST /v1/children-then-manifest` is **503** and does not put. Missing header stays **401**.

Remaining remote `default_r2_put` callers: `cf_daily_path_job` (non-`dry_run` still calls it — now raises), `cf_mass_eval_run.put_local_fallback_artifacts`. `reconstitution_evidence` stays dry-run-only (`default_r2_put(..., dry_run=True)`). `python_r2_put_allowed()` still exists and is still `=1`-only; it is **not** consulted by `default_r2_put`. Overlay identity **HOLD**.

Do not treat “HTTP client exists” or “CLI put deleted” as live Worker-equivalent create-if-absent.

### N. Active Catalog / Legacy Identity Registry

**status: PARTIAL** (v2 classification + YAML overlay fail-closed + digest identity + `yaml_*` aliases + leftover occupancy HOLD **pointer**) / **OPEN** (compact source; `migration.jsonl` still load SoT) / **HOLD** (+N / unique22 / freeze n / leftover occupancy)

Independent C at `5103b26b` ([`P632_ind_C_revisit_5103b26b.md`](P632_ind_C_revisit_5103b26b.md)): YAML n = **0**; compiled freeze n = **2254**; `yaml_overlay_allowed()` **False**; `go: false`. Compact `family + template + parameter matrix` **not** implemented.

`046ae438`: leftover occupancy HOLD pointer in `unique22_occupancy_park` — park reasons live in `UNIQUE22_PARK_REASONS`; leftover occupancy stays in `daily_path.ts` (1682). Do not unify with `comboEventGateOk`. Do not extract. unique22 leftover still **22** (17 parked + 5 occupancy-equal lifts).

Do not report 2254/2092 as a product win. Combo +N **HOLD**. unique22 leftover occupancy **HOLD**.

### O. Evaluation IR single generated authority

**status: PARTIAL** (JSON Schema codec SoT; `verify_ci` validates golden + generated `ALLOWED_FIELDS` + encode-key lock + generated TS codec body + freeze-**call** pin) / **OPEN** (Python encode/decode still hand-written; TS decode does not load a JSON Schema engine)

`2e264a08` pins the freeze **invocations**. Encode object keys remain schema properties; grade remains `jobCandidateGrade`. Unknown fields still fail; version stays `evaluation-ir/v1`.

Python `evaluation_ir.py` (1076) still owns hand-written encode/decode **and** the TS emitter. Brief asked generated Python+TS types. Python types are **not** generated. Decode on the Worker still uses generated `ALLOWED_FIELDS`, not a JSON Schema engine. Façade `evaluation_ir.ts` (39); generated codec (239).

### P. Test audit / reduction

**status: OPEN** (inventory not closed) / **PARTIAL** (Lane 17 audit + collect freezes + digest identity + READY fixture honesty + event-zero tip/index pins)

See [`P632_test_inventory.md`](P632_test_inventory.md) (`3ab87d0`, collected **1353**), [`P632_test_inventory_now.md`](P632_test_inventory_now.md) (`07b4435`, **1379**), [`P632_test_inventory_40d1aa90.md`](P632_test_inventory_40d1aa90.md) (**1426**), [`P632_test_inventory_67fcbd7c.md`](P632_test_inventory_67fcbd7c.md) (**1448**), [`P632_test_inventory_ed94d504.md`](P632_test_inventory_ed94d504.md) (**1470**), [`P632_test_inventory_5103b26b.md`](P632_test_inventory_5103b26b.md) (**1496** collected; `tests/test_*.py` **153**; Worker first-party **20**; YAML **0**). Local `verify_ci` at `5103b26b` reported **1492 passed, 4 skipped**.

This HEAD `git ls-files tests/test_*.py` = **153** (unchanged file count vs `5103b26b`). Worker first-party test files still **20**. Wave-8 grew existing modules (`test_immutable_artifact.py`, `test_cf_cost_verify.py`, `test_cf_propose_thesis.py`, `test_occupancy_audit.py`, `test_verify_ci_script.py`, mass-eval `http.test.ts`). This wave did **not** re-run `pytest --collect-only`. Do not invent `tests_after`. Count growth is not a consolidation win.

### Q. Whole-repo refactor (authority split)

**status: PARTIAL** / **OPEN** / **HOLD** (named live-math files)

§10 remaining-extracts freeze is authored vs `5103b26b` ([`docs/phase63_refactor_plan.md`](../phase63_refactor_plan.md); `6447a3fa`). That freeze still lists `r2_io.py` (454) and remaining mixed “opt-in Python TOCTOU (`QP_ALLOW_PYTHON_R2_PUT=1`)”. Wave-8 landings vs that freeze:

| §10.3 later | At `5103b26b` | After wave-8 |
|-------------|---------------|--------------|
| 1 BackfillPlanner vs `plan_required_segments` | **DONE** (JQ jobs from required segments; pipeline held OTC HTML; `issue_*` `--index-text`) | **DONE** (not reopened). BackfillPlanner still has no `index_text`. Live MCP still V2 STALE. |
| 2 Python `r2_io.py` TOCTOU | PARTIAL (Worker POST wired; overlay `=1` still TOCTOU; `default_r2_put` callers remain) | **PARTIAL** — overlay never CLI-put (`0b81eedb`); research artifacts POST (`d6567268`); unbound token 503 (`52f3e70e`). Live POST unproven. Remaining remote `default_r2_put` callers fail-closed (`cf_daily_path_job`, `cf_mass_eval_run`). Overlay helper still exists (**HOLD**). `r2_io.py` is now **431**. |
| 3 hand-written `evaluation_ir.ts` | PARTIAL (TS codec body generated; Python encode/decode hand-written) | **PARTIAL** — freeze-**call** pin (`2e264a08`); Python encode/decode still hand-written (1076) |
| 4 MCP frozen “Coverage V2” strings | FIXED + tool-description pin | **FIXED** (not reopened). Live MCP still emits `complete` only. |
| 5 `verify_all` vs `verify_ci` | HOLD (local PASS at `ed94d504` is not merge-gate) | **HOLD** (local PASS at `5103b26b` is not merge-gate; freeze-call pin added; print-only first-deploy still does not create the producer) |

leftover occupancy / `cost_models.py` / generated `catalog_ids.ts` **HOLD**. `046ae438` makes the leftover occupancy HOLD **pointer** explicit; it is not an extract. Coverage V2 JSON vs V3 contracts: planner + OTC grain + `index_text` CLIs + sealer + pipeline held HTML + `issue_*` wired for 4 datasets; live MCP still V2 STALE.

### R. Basket reconstitution evidence

**status: HUMAN** (apply false) / evidence pack **FIXED** (detect-only)

`RECONSTITUTION_APPLY = False`. Agent must not flip apply. `d6567268`: reconstitution evidence stays dry-run-only (`default_r2_put` local stage).

### S. Controlled Pilot

**status: FIXED** (OFF) — GO conditions **OPEN** / unmet

Worker: `MASS_RESEARCH = "NO-GO"`, `PHASE7 = "OFF"`, `READY_DECLARED = "false"` (`research-mass-eval/wrangler.toml`). Python deny-by-default, `go: False`. **Do not** run the one-shot paper loop. Mass remains **NO-GO**. Auto promotion **OFF**. Live broker **OFF**. Independent C at `5103b26b`: catalog/pilot P0 unresolved **0** (no live arming); that is not Phase 7 GO.

---

## Independent P0 scoreboard (tree vs live)

| ID | At `5103b26b` (wave-7) | After wave-8 (`3b64bdfc`) |
|----|------------------------|---------------------------|
| IND-A-DOMAIN | **FIXED**. Live STALE still V2 `2006-08-13`. | **FIXED** (not reopened). Live still STALE. |
| IND-A-JSDA-PHANTOM | **FIXED** (tree) + `issue_*` `--index-text` + pipeline held HTML. Live still **8784 / 5886**. PARSE_ZERO stays gap. | **FIXED** (tree; empty JSDA diff). Live still **8784 / 5886**. PARSE_ZERO stays gap. |
| IND-A-PIT-BYPASS | **FIXED** | **FIXED** (not reopened) |
| IND-A-FORGED-RECEIPT | **FIXED** | **FIXED** (not reopened) |
| IND-A-FALSE-COMPLETE | **PARTIAL** — JQ-without-`index_text` is not OTC weekend COMPLETE. Genuine `fins_*` event-zero COMPLETE **remains intended**. Live MCP still `complete`. | **PARTIAL** (not reopened). Live MCP still `complete`. |
| IND-A-READY-DEPS | **FIXED**. Live READY **null**. | **FIXED**. Live **null**. |
| P632B-01 `verify_all` vs `verify_ci` | **PARTIAL** — local PASS at `ed94d504`; generated codec freeze; print-only first-deploy; live merge gate still not `verify_ci`; producer Worker **absent** | **PARTIAL** — local PASS at `5103b26b` documented; freeze-**call** pin; live merge gate still not `verify_ci`; producer Worker **absent** |
| P632B-02 live `ci-aggregate` posted | **OPEN** — Worker **absent** (10007). Print-only helper is not a create. **HUMAN** create. Check-runs **0**. | **OPEN** — Worker **absent** (10007). Helper named in operator map; still print-only. **HUMAN** create. Check-runs still **0**. |
| P632B-03 `GATEWAY_TOKEN` / `MASS_EVAL_TOKEN` | **OPEN** (mass-eval still sends `GATEWAY_TOKEN`) | **OPEN** (empty diff on that path). Unbound mass-eval token on children-then-manifest is now **503** (not a GATEWAY mix-up close). |
| P632B-05 Python R2 TOCTOU | **PARTIAL** — Worker POST wired; live POST unproven; overlay `=1` and `default_r2_put` callers still TOCTOU | **PARTIAL** — overlay never CLI-put (**FIXED** tree); research artifacts POST; unbound 503. Live POST unproven. Remaining remote `default_r2_put` callers fail-closed, not Worker `onlyIf`. Overlay helper **HOLD**. |
| C-YAML load overlay | **FIXED**. +N **HOLD**. Independent C P0 unresolved **0** (no live arming). | **FIXED**. +N **HOLD**. Leftover occupancy HOLD pointer (`046ae438`). Independent C P0 unresolved **0** (no live arming). |

Independent P0 unresolved ≠ 0 (live CI never posted; **ci-aggregate Worker absent**). `Pilot_GO.IndependentReview_P0_Zero` stays **OPEN**. Tree overlay-never-CLI-put / research-artifact POST / unbound 503 / leftover occupancy pointer is not a live Coverage COMPLETE.

---

## Brief §8 `Pilot_GO` (current tree + live MCP)

| Criterion | Status |
|-----------|--------|
| Mandatory_CF_CI | **OPEN** — Worker **absent** (10007); live check-runs **0**. Print-only helper. HUMAN deploy. Conjunction **fails**. |
| Main_Protected | **FIXED** (setting requires `ci-aggregate`) |
| Six_Workers_Clean | lockfiles **FIXED**; `verify_ci` 7 workers **FIXED** (script); local PASS at `5103b26b` **FIXED** (docs); clean-checkout matrix at this HEAD **OPEN** |
| SourceCapabilityContract_V3 | **PARTIAL** — 4/26 files; nested maps OPEN; missing file fail-closed; OTC grain token **FIXED** |
| RequiredDomain_Subset_OfficialDomain | **PARTIAL** — planner + OTC refresh + `index_text` CLIs + grain + sealer + pipeline held HTML + `issue_*`; live MCP still V2 STALE |
| ResearchDataProfile_Complete | **PARTIAL** — core includes master; string COMPLETE rejected; fixture tip receipts; tip/index event-zero PARTIAL; READY **null** |
| Projection_FRESH | **NO** — **STALE** |
| Refresh_SUCCESS | **NO** — `false` |
| B0_PASS | **NO** — **UNKNOWN** |
| READY_Profile_Exists | **NO** — **null** |
| AppliedCursor_Pinned | **NO** — **null** |
| EdgeBudget_Hard | **PARTIAL** (code + create≠reserve pin) / live **OPEN** |
| Artifact_Coherent | Worker digest 409 **FIXED**; overlay never CLI-put **FIXED** (tree); Worker POST client **PARTIAL** (live unproven); remaining `default_r2_put` remote callers fail-closed **PARTIAL** |
| AI_Gateway_Typed | **FIXED** (6.3.1; still true) |
| PaperExecution_Authoritative | not re-opened; Mass/paper still unarmed |
| IndependentReview_P0_Zero | **OPEN** |

Brief §8 `Pilot_GO` is a conjunction. Live legs still fail. Do not invent GO.

## 6.4 live (not invented)

| Criterion | Live |
|-----------|------|
| governed Coverage COMPLETE (official mode) | **NO** — 22 held / **4 PARTIAL** last-known under STALE V2 |
| projection FRESH | **STALE** |
| B0 PASS | **UNKNOWN** |
| applied sync generation pinned/current | **unpinned** (`applied_feed_cursor=null`) |
| immutable READY ≥ 1 | **null** |
| AM SLA live evidence | **PROJECTION_STALE** — not PASS |

---

## Human actions (not agent)

1. **Bottleneck:** create `quant-platform-ci-aggregate` on account `11233bca08d134a9b738eaa46b9751d9`. Bind `CI_LANE_TOKEN` and `GITHUB_STATUS_TOKEN`. Connect Workers Builds for six lanes. Prove a **failing** SHA is unmergeable and a **passing** six-receipt SHA posts `ci-aggregate` success. `scripts/ci_aggregate_first_deploy.sh` is print-only; Isolation worktree does **not** do that. Do not PAT-mint the required context. **ci-aggregate create remains the bottleneck.**
2. Bind `GATEWAY_TOKEN` / `MASS_EVAL_TOKEN` / `QUANT_READINESS_HMAC_SECRET` on the intended env. Do not commit values. Unbound mass-eval token is now **503** on children-then-manifest; that is fail-closed, not a bind.
3. Apply `0007_ops_applied_pins` to remote D1 only when the operator is ready to pin. Until then CURRENT stays impossible.
4. Refresh the ops projection so MCP is FRESH with `refresh_success=true`, passing official-index HTML (`--otc-index-html` / `--index-text`). Tree honesty is not a publish. Live still **8784 / 5886**. Redeploy ops-mcp if `raw_retention.acquired` should be live.
5. Dated reconstitution brief for `basket_theme_fund` / `basket_event_fund` only. Do not flip `RECONSTITUTION_APPLY`.
6. Isolation worktree does **not** push `main`. PR #1 stays **BLOCKED** until `ci-aggregate` actually posts from a **deployed** Worker.

---

## What this file is not

- A rewrite of [`P632_brief_leaks.md`](P632_brief_leaks.md), [`P632_wave2_status.md`](P632_wave2_status.md), [`P632_wave3_status.md`](P632_wave3_status.md), [`P632_wave4_status.md`](P632_wave4_status.md), [`P632_wave5_status.md`](P632_wave5_status.md), [`P632_wave6_status.md`](P632_wave6_status.md), or [`P632_wave7_status.md`](P632_wave7_status.md).
- A live Coverage remeasure. Overlay never CLI-put, research-artifact POST, unbound 503, and leftover occupancy HOLD pointer are git; MCP is **STALE**.
- Dataset COMPLETE 23, OTC COMPLETE, B0 PASS, READY, Phase 6.3.2 COMPLETE, Phase 6.4 COMPLETE, or Phase 7 GO.
- Proof that `verify_ci.sh` is green at `3b64bdfc`. Local PASS at `5103b26b` is not this SHA and is not merge-gate.
- A deploy of `quant-platform-ci-aggregate`. The print-only helper does not create the Worker. The Worker is **absent**. That is the HUMAN bottleneck.

Wave-8 **tree** honesty landed. Phase 6.3.2 remains **NOT COMPLETE**. Phase 6.4 remains **NOT COMPLETE**. Controlled Pilot remains **NO-GO**.
