# Phase 6.3.2 Wave-10 status — leak register vs current HEAD (not a GO)

**Isolation worktree:** `/Users/taku/tmp/qp-p632-wave10-status` on `grok/p632-wave10-status` (do not push `main`).  
**Does not clobber:** [`P632_brief_leaks.md`](P632_brief_leaks.md) (A–S freeze vs `3ab87d0`), [`P632_wave2_status.md`](P632_wave2_status.md) (A–S freeze vs `07b4435`), [`P632_wave3_status.md`](P632_wave3_status.md) (A–S freeze vs `f224e7e`), [`P632_wave4_status.md`](P632_wave4_status.md) (A–S freeze vs `40d1aa90`), [`P632_wave5_status.md`](P632_wave5_status.md) (A–S freeze vs `67fcbd7c`), [`P632_wave6_status.md`](P632_wave6_status.md) (A–S freeze vs `ed94d504`), [`P632_wave7_status.md`](P632_wave7_status.md) (A–S freeze vs `5103b26b`), [`P632_wave8_status.md`](P632_wave8_status.md) (A–S freeze vs `3b64bdfc`), or [`P632_wave9_status.md`](P632_wave9_status.md) (A–S freeze vs `242c2484`). Those files stay earlier freezes.  
**Feature branch:** `grok/phase63-ci-source-closure`  
**This HEAD (reviewed):** `2b82ec7d` (`2b82ec7d26f26464ac5ce8e4f53d5f6a039117a6`) — `ops: cf_premium_backfill uses shared official-index HTML reader`.  
**Window:** 16 commits after `242c2484` (`242c2484e9307f9163b13fc603ad90f67c6a0919`). Count: `git rev-list --count 242c2484..2b82ec7d` = **16**.  
**`origin/main`:** `b5c326a` (`b5c326a7f612563f2da4a84f08063a307ec38e0a`) — feature branch is **not** an ancestor of `main`; **not merged**. `main` is an ancestor of this HEAD.  
**Named review SHA in brief:** `b5c326a` — **not** a freeze.  
**PR:** https://github.com/ddnne/quant-platform/pull/1 — `MERGEABLE` / mergeState **`BLOCKED`** (required `ci-aggregate` has not posted). Head OID this turn: `2b82ec7d`.

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
| Wave-8 after 16 commits | `3b64bdfc` | [`P632_wave8_status.md`](P632_wave8_status.md) |
| Wave-9 after 18 commits | `242c2484` | [`P632_wave9_status.md`](P632_wave9_status.md) |
| Wave-10 (this file) | `2b82ec7d` | this re-diff |

Status vocabulary: **OPEN / FIXED / PARTIAL / HOLD / HUMAN**.  
Do not invent Coverage COMPLETE, Projection FRESH, B0 PASS, READY, Phase 6.3.2 COMPLETE, Phase 6.4 COMPLETE, or Phase 7 GO.

---

## Live MCP (this wave; tools available)

quant_mcp tools **worked** this isolation turn. Values below are this-turn reads, not last-known docs. Isolation does not refresh the ledger. No GitHub check-runs MCP existed; live GitHub below is `gh api`. Live Cloudflare is Wrangler 4.125.0 (account `11233bca08d134a9b738eaa46b9751d9`, logged in as `taku_haga@icloud.com`).

```text
Projection: STALE
  generated_at: 2026-08-21T12:30:49.152421+00:00
  age_seconds: 187980 (~52.2h)
  active_generation: projgen-ef18b4f86ee946048161d25e2a30a2a8
  projection_source_generation: 2026-08-21T12:28:33.345482+00:00
  refresh_attempt: true
  refresh_success: false
  last_known_good.not_fresh: true

B0: UNKNOWN  (snapshot quality/B0 projection is unavailable)

READY: null  (no published READY generation is bound to this Worker)

Sync: applied_feed_cursor: null
  latest_change_seq: 2890669
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
Ops last_run: id 14319 PASS (jquants, 2026-08-24T01:15:01+09:00)
Raw: manifests 20516 / complete 18301
  live ops_status.raw_retention still emits complete (no acquired key)
  live Worker is not this SHA
AM SLA current_state: PROJECTION_STALE (state_reason: ops_projection_stale)
storage_plane_status.p0_claims.mass_research: NO-GO
storage_plane_status.p0_claims.ready: null
```

Live GitHub (this turn; `gh api` / `gh pr view`, not invented):

```text
commits/2b82ec7d/check-runs  total_count: 0
commits/2b82ec7d/status      state: pending, total_count: 0
PR #1                       mergeable: MERGEABLE
                            mergeStateStatus: BLOCKED
                            statusCheckRollup: []
                            headRefOid: 2b82ec7d26f26464ac5ce8e4f53d5f6a039117a6
                            baseRefOid: b5c326a7f612563f2da4a84f08063a307ec38e0a
Actions workflows           total_count: 0
main protection             required_status_checks.contexts=["ci-aggregate"]
                            app_id: null, strict: true, enforce_admins: true
                            allow_force_pushes: false
origin/main check-runs      total_count: 0
.git/ ls-files .github      0
```

Live Cloudflare producer (this turn; Wrangler 4.125.0, not invented):

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

Cron PASS, raw-retention COMPLETE, and row-count growth are **not** Coverage COMPLETE or READY. Local `verify_ci` at `242c2484` is **not** a posted GitHub context. Print-only first-deploy is **not** a producer. Same generation as wave-9 (`projgen-ef18b4f86ee946048161d25e2a30a2a8`). Age grew 187020 → 187980. Floors and 4-PARTIAL set are unchanged.

---

## Verdict

| Gate | Status |
|------|--------|
| Phase 6.3.2 COMPLETE? | **NOT COMPLETE** |
| Phase 6.4 COMPLETE? | **NOT COMPLETE** |
| Phase 7 Foundation | types exist; `PHASE7=OFF` |
| Phase 7 Controlled Pilot GO? | **NO-GO** |
| Phase 7 Mass Research GO? | **NO-GO** |

Wave-10 **tree** honesty (shared official-index HTML reader, `cf_premium_backfill --index-text`, secrets Worker unit, IR emit extract, IR TypedDict generate) is not a GO. Brief §8 `Pilot_GO` is a conjunction; live legs still fail: Projection **STALE**, `refresh_success=false`, B0 **UNKNOWN**, READY **null**, `applied_feed_cursor=null`, required GitHub `ci-aggregate` **not posted** (`check-runs total_count: 0`), Coverage still V2 **22 / 4 PARTIAL**, independent P0 unresolved ≠ 0 (live merge gate; **ci-aggregate Worker absent**).

**HUMAN bottleneck named:** `quant-platform-ci-aggregate` Worker **absent**. Branch protection requires a context that has no producer on the account. Isolation must not deploy, bind secrets, or PAT-mint `ci-aggregate`. `scripts/ci_aggregate_first_deploy.sh` prints operator commands and refuses `--apply` without `CONFIRM_CI_AGGREGATE_CREATE=1`; even then it is still print-only. **ci-aggregate create remains the bottleneck.**

---

## Named landings this wave (tree, not live GO)

| SHA | Landing | Closes (tree) | Does **not** close |
|-----|---------|---------------|-------------------|
| `2323f6a5` | one official-index local HTML reader for CLIs | `read_local_index_text` lives in `ingestion.jsda.official_index` (89). `issue_*`, sealer, `refresh_coverage_ledger`, `write_collection_receipts` import it. Omitted/blank is fail-closed `None`, not a calendar walk. | Live MCP still V2 STALE **8784 / 5886**. PARSE_ZERO stays empty. Not Dataset COMPLETE. |
| `5a8e78c2` | `cf_premium_backfill` passes `--index-text` into planner | CLI `--index-text PATH` forwards local HTML into `BackfillPlanner.plan(index_text=…)`. Omitted → `index_text=None` (tests pin omit is not V2 required-set). Does not fetch live JSDA HTML. Wave-9 named BackfillPlanner `index_text`; this is the ops driver. | Live ledger still STALE 8784. Dry-run default is not a publish. Not Dataset COMPLETE. |
| `908e8ef4` | secrets proxy boundary is Worker unit not Python grep | `ingestion-secrets/src/index.test.ts` owns request/auth/upstream (`it(` **6**). Python `test_ingestion_secrets_worker_contract.py` is JSON/catalog identity only. | Not a secret bind. `workers_dev=true` on ingestion-secrets stays **HOLD**. Not merge-gate. |
| `54c1f472` | extract Evaluation IR codec emitters from façade | Emit helpers live in `evaluation_ir_emit.py` (823). Façade `evaluation_ir.py` is 646 (schema load, grade wiring, frozen dataclass). Wave-9 named emitters still in the 1224-line façade. | `EvaluationIR` dataclass still hand-written. Worker decode still not a JSON Schema engine. Not merge-gate. |
| `e20be4d9` | emit Evaluation IR python types from schema.json | `evaluation_ir_types.generated.py` (47) is TypedDict SoT (`EvaluationIRPayload` / `EvaluationIREncodeArgs`). `verify_ci` freeze-calls `assert_evaluation_ir_types_py_frozen()`. Wave-9 named TypedDict still hand-written. | TypedDict cannot ban unknown fields; runtime validate remains SoT. `EvaluationIR` dataclass still hand-written. Not merge-gate. |
| `2b82ec7d` | `cf_premium_backfill` uses shared official-index HTML reader | Driver imports `read_local_index_text` from `official_index` (no local duplicate). Same omit/`None` fail-closed. | Live MCP still V2 STALE. Isolation did not execute `--execute`. |

Independent revisits / inventories at `242c2484` (`8c5e626f` A, `2799ba35` B, `e9b32084` C, `71032dc6` wave-9, `09bf316f` P, `915070d8` `verify_ci`, `31e19ca8` original-plan-gap, `de5f4837` residual SoT, `39b97859` §10 remaining mixed, `1b080a47` review index) are freezes / operator notes vs the wave-9 SHA, not live GO. They do **not** yet name shared reader / backfill `--index-text` / secrets Worker unit / IR emit extract / IR TypedDict / backfill shared-reader import. Independent A/B/C freeze SHAs are `242c2484`. Catalog identity is an empty diff `242c2484..2b82ec7d`.

This isolation did **not** re-run `scripts/verify_ci.sh` at `2b82ec7d`. The `242c2484` local PASS ([`P632_verify_ci_242c2484.md`](P632_verify_ci_242c2484.md): **1502 passed / 4 skipped**) is the wave-9 reviewed SHA, not this HEAD, and is **not** merge-gate. Prior `3b64bdfc` PASS (**1499 passed / 4 skipped**) is still not this SHA.

---

## The 16 commits after `242c2484`

| SHA | Landing | Lane |
|-----|---------|------|
| `2323f6a5` | one official-index local HTML reader for CLIs | H / Q |
| `5a8e78c2` | `cf_premium_backfill` passes `--index-text` into planner | H / Q |
| `908e8ef4` | secrets proxy boundary is Worker unit not Python grep | L / P |
| `54c1f472` | extract Evaluation IR codec emitters from façade | O / Q |
| `e20be4d9` | emit Evaluation IR python types from schema.json | O / C |
| `8c5e626f` | independent review A revisit at `242c2484` | docs (A freeze) |
| `2799ba35` | independent review B revisit at `242c2484` | docs (B freeze) |
| `e9b32084` | independent review C catalog/pilot revisit at `242c2484` | docs (C freeze) |
| `71032dc6` | wave-9 status after commits vs `3b64bdfc` | docs (wave-9 freeze) |
| `09bf316f` | 6.3.2 P test inventory at `242c2484` | docs (P) |
| `915070d8` | P632 `verify_ci` code-lane result at `242c2484` | docs (C; not merge-gate) |
| `31e19ca8` | banner original-plan-gap register still holds at `242c2484` | docs |
| `de5f4837` | residual SoT banner HEAD `242c2484` vs `origin/main` `b5c326a` | docs |
| `39b97859` | §10 remaining mixed at `242c2484` | docs (Q freeze) |
| `1b080a47` | review index names HEAD `242c2484` vs `origin/main` `b5c326a` | docs |
| `2b82ec7d` | `cf_premium_backfill` uses shared official-index HTML reader | H / Q |

Docs commits in this window (`8c5e626f`, `2799ba35`, `e9b32084`, `71032dc6`, `09bf316f`, `915070d8`, `31e19ca8`, `de5f4837`, `39b97859`, `1b080a47`) are freezes / operator notes, not live GO. Independent A/B/C revisits are authored vs `242c2484` and do **not** yet name shared reader / backfill `--index-text` / secrets Worker unit / IR emit extract / IR TypedDict. `39b97859` remaining-extracts freeze is authored vs `242c2484` (TypedDict “not done” in that freeze); this re-diff is vs `2b82ec7d`.

---

## A–S vs `2b82ec7d` (after the 16)

Prior registers: [`P632_brief_leaks.md`](P632_brief_leaks.md) vs `3ab87d0`; [`P632_wave2_status.md`](P632_wave2_status.md) vs `07b4435`; [`P632_wave3_status.md`](P632_wave3_status.md) vs `f224e7e`; [`P632_wave4_status.md`](P632_wave4_status.md) vs `40d1aa90`; [`P632_wave5_status.md`](P632_wave5_status.md) vs `67fcbd7c`; [`P632_wave6_status.md`](P632_wave6_status.md) vs `ed94d504`; [`P632_wave7_status.md`](P632_wave7_status.md) vs `5103b26b`; [`P632_wave8_status.md`](P632_wave8_status.md) vs `3b64bdfc`; [`P632_wave9_status.md`](P632_wave9_status.md) vs `242c2484`. This table is the wave-10 re-diff, not a rewrite of those files.

### A. Cloudflare mandatory CI

**status: PARTIAL** (protection + Worker **code** + `CI_LANE_TOKEN` + 7-worker `verify_ci` + types flags + IR codec freeze + freeze-**call** pin + python codec freeze + python types freeze + print-only first-deploy helper named in operator map) / **OPEN** (live check never posted; **Worker absent**) / **HUMAN** (`quant-platform-ci-aggregate` first deploy + token bind)

| Sub-item | At `242c2484` (wave-9) | After wave-10 |
|----------|------------------------|---------------|
| `.github/` workflows | **FIXED** (absent) | **FIXED** — `git ls-files .github` empty; Actions `total_count: 0`. Do not add. |
| Aggregate Worker | **FIXED** (code) + helper named. Live Worker **absent**. | **FIXED** (code; empty diff). Live Worker **absent** — deployments **10007**, secrets not found, `/health` **404**. Named **HUMAN** bottleneck. Helper does not wrangler deploy. |
| `verify_ci` covers gate Worker | **FIXED** + python codec freeze. Local PASS documented at `3b64bdfc`, not `242c2484`. | **FIXED** + python types freeze (`e20be4d9` `assert_evaluation_ir_types_py_frozen()`). Local PASS now documented at `242c2484` ([`P632_verify_ci_242c2484.md`](P632_verify_ci_242c2484.md)), not this HEAD, not GitHub. |
| Branch protection on `main` | **FIXED** (requires `ci-aggregate`) | **FIXED** (setting). `app_id: null`. Not a passing receipt. |
| GitHub check-runs / statuses at HEAD | **OPEN** (`242c2484` `total_count: 0`) | **OPEN** — this turn `2b82ec7d` `total_count: 0`; `/status` `pending` / `0`. PR #1 `MERGEABLE` / `BLOCKED`; `statusCheckRollup: []`. |
| Fail/pass merge smoke | **OPEN** | **OPEN** — cannot smoke a producer that does not exist |
| Token bind | **HUMAN** | **HUMAN** — agent must not mint; nothing to bind until Worker exists; helper never puts secret values |
| Workers Builds Git integration | **OPEN** | **OPEN** |
| Explicit promote vs auto-deploy | **HOLD** | **HOLD** |

### B. All six Workers reproducible build

**status: PARTIAL** (lockfiles; seven `npm run types -- --check`; retry jitter `crypto.getRandomValues`) / **OPEN** (clean-checkout proof at this HEAD)

Empty diff vs `242c2484` on Worker production sources for lockfiles / jitter / fetch extract. Secrets Worker **unit** tests grew in place (`908e8ef4`; `it(` **6**); that is test-surface honesty, not a clean-checkout matrix.

Local `verify_ci` PASS is now **documented** at `242c2484` ([`P632_verify_ci_242c2484.md`](P632_verify_ci_242c2484.md): 7 workers including `ci-aggregate` 13 tests; **1502 passed / 4 skipped**; `ingestion-secrets` was **2** tests at that SHA). That is a different SHA than this HEAD. Clean-checkout matrix **not** executed at `2b82ec7d` in this isolation.

Do not invent PASS at `2b82ec7d`.

### C. Authoritative CI script

**status: PARTIAL** (`verify_ci.sh` fail-closed, 7 workers, IR schema, generated `ALLOWED_FIELDS`, encode-key lock, generated TS codec freeze, freeze-**call** pin, generated Python codec freeze, generated Python types freeze, types flags, **local PASS at `242c2484`**, print-only first-deploy helper named) / **OPEN** (merge gate is live GitHub context; producer Worker **absent**)

- Authoritative: `scripts/verify_ci.sh`. `WORKERS` still includes `platform/workers/ci-aggregate`. Missing lockfile/dir/script fails. No skip of missing `node_modules`. No `--legacy-peer-deps`.
- Fast helper remains `scripts/verify_all.sh` (three research workers; optional `VERIFY_*`). Still **not** mandatory CI. Do not merge the two (HOLD split).
- `e20be4d9`: `verify_ci.sh` now invokes `assert_evaluation_ir_types_py_frozen()` next to the codec freeze calls. Tests pin the invocation.
- Local PASS at `242c2484`: 1502 passed / 4 skipped; wall 198.19s; `verify_ci: ok`. **Not** merge-gate. **Not** this HEAD. This isolation did not re-run the script after the wave-10 code landings (`2323f6a5`, `5a8e78c2`, `908e8ef4`, `54c1f472`, `e20be4d9`, `2b82ec7d`).
- Print-only operator helper still does **not** create a fresh venv (requires existing `.venv` 3.11+). Live merge authority is still “six lane receipts POSTed with `CI_LANE_TOKEN` → GitHub `ci-aggregate`”, and that POST host **does not exist**.

### D. SourceCapabilityContract V3

**status: PARTIAL** (typed loader + **4** dataset files + SoT clip + missing-file fail-closed + OTC grain token + nested-open pin) / **OPEN** (22 governed datasets have no V3 file; nested maps open)

On-disk: `specs/source_capability/{equities_master,equities_earnings_calendar,equities_bars_daily_am,jsda_otc_bond_reference_prices}.json`. Nested evidence maps remain **OPEN** by design. Missing V3 JSON is `None`, not invented.

Planner **does** clip through SourceCapability SoT. That is a wire, not Dataset COMPLETE 23. Live MCP is STALE and still advertises V2 floors. Empty diff vs wave-9 on the four files.

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

**status: PARTIAL** (V3 file + planner + HTML index SoT + refresh wire + CLI `index_text` + JSON grain + sealer `index_text` + `issue_*` `--index-text` + pipeline held HTML + BackfillPlanner `index_text` + **shared local HTML reader** + **`cf_premium_backfill --index-text`**) / **OPEN** (live STALE calendar inventory; PARSE_ZERO not sealed)

Wave-10 vs wave-9:

- `2323f6a5`: one `read_local_index_text` in `official_index.py` (89). CLIs import it (`issue_*`, sealer, refresh, write receipts). Omitted/blank/`missing_ok` stays fail-closed empty, never a calendar walk.
- `5a8e78c2`: `cf_premium_backfill --index-text PATH` forwards local HTML into `planner.plan(index_text=…)`. Tests pin omit → `None` (not V2 required-set) and supplied path forwarded.
- `2b82ec7d`: the driver uses the shared reader (no local duplicate).

Live MCP still last-known Wave-0 **5886 / 8784** under `history_target_start: 2002-08-02`. Tree refresh ≠ live ledger migration.

- `PARSE_ZERO_SEAL_PROOF` stays empty — `2002-08-02` / `2002-08-05` stay **PARTIAL** without in-repo digest+count.

Do not COMPLETE empty non-index days. Do not hide PARSE_ZERO by moving `history_target_start`.

### I. ResearchDataProfile / READY

**status: PARTIAL** (v1 predicate + core requires master + string COMPLETE rejected + missing V3 false + mixed policy honesty + fixture tip receipts + tip/index event-zero PARTIAL) / **OPEN** (live READY **null**)

Unchanged vs wave-9 live. `latest_ready_snapshot`: **null**. Digest-bound predicate ≠ a bound READY generation. STALE V2 PARTIAL keeps READY honest-false. That is intended; it is not a GO.

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

Live MCP this turn still returns only `complete: 18301` on `ops_status.raw_retention` — the deployed ops-mcp Worker is **not** this SHA. Tree honesty is not a publish. See [`P632_projection_stale.md`](P632_projection_stale.md) and [`P632_projection_refresh_false.md`](P632_projection_refresh_false.md).

### K. Edge Durable Object hard budget

**status: PARTIAL** (DO reserve/reconcile in repo + create≠reserve pin) / **OPEN** (live Edge unproven)

Unchanged vs wave-9. Caps unchanged (`auto_promotion: false`). Live occupancy / double-spend under production traffic: **not** measured this wave. String `budget_id` is still not the reserve. Empty diff vs `242c2484` on `research-ai-gateway`.

### L. Worker public boundary

**status: PARTIAL** (preview vs production split; secrets proxy **Worker unit**) / **OPEN** (shared bearer still required on remaining surfaces) / **HOLD** (`workers_dev` kept where documented; GATEWAY service-binding residual) / **HUMAN** (secret bind)

Unchanged vs wave-9 production `workers_dev=false` on research-ai-gateway, research-mass-eval, ingestion-jsda, ingestion-premium. **Kept true:** quant-ops-mcp (OAuth callback), ingestion-secrets (token-gated local), ci-aggregate (receipt POST host). Treat **kept** as **HOLD**. Dual `GATEWAY_TOKEN` / service-binding residual: **OPEN** / **HOLD** (`7221c588`; mass-eval `ai_gateway_client.ts` still sends `GATEWAY_TOKEN` as `X-Gateway-Token`; empty diff vs `242c2484`). Ops MCP must not grow SQL / fetch / ingest / delete / READY publish. Not re-opened.

`908e8ef4`: secrets proxy request/auth/upstream is Worker unit (`index.test.ts` `it(` **6**); Python tests no longer grep Worker source. That is contract-vs-unit split, **not** a secret bind.

`ci-aggregate` `workers_dev=true` is moot until the Worker exists. Unbound mass-eval token on children-then-manifest stays **503**; that is fail-closed, not a secret bind.

### M. Immutable artifact authority

**status: PARTIAL** (Worker child digest 409 + overlay never CLI-put + Worker POST client + research-artifact POST + unbound token 503 + daily-path Worker put + mass-eval-run Worker put) / **OPEN** (live POST unproven) / **HOLD** (overlay identity helper still exists; reconstitution dry-run still `default_r2_put`)

Empty diff vs `242c2484` on `r2_io.py` (431) and `reconstitution_evidence.py`. Remaining `default_r2_put` production caller: `reconstitution_evidence` dry-run-only (`default_r2_put(..., dry_run=True)`). `put_research_artifact` still stages locally via `default_r2_put` when `dry_run=True`. Overlay identity **HOLD**.

Do not treat “HTTP client exists” or “CLI put deleted” as live Worker-equivalent create-if-absent.

### N. Active Catalog / Legacy Identity Registry

**status: PARTIAL** (v2 classification + YAML overlay fail-closed + digest identity + `yaml_*` aliases + leftover occupancy HOLD **pointer**) / **OPEN** (compact source; `migration.jsonl` still load SoT) / **HOLD** (+N / unique22 / freeze n / leftover occupancy)

Independent C at `242c2484` ([`P632_ind_C_revisit_242c2484.md`](P632_ind_C_revisit_242c2484.md)): YAML n = **0**; compiled freeze n = **2254**; `yaml_overlay_allowed()` **False**; `go: false`. Compact `family + template + parameter matrix` **not** implemented. Catalog identity is an empty diff `242c2484..2b82ec7d` (`specs/research_catalog/`, `catalog_ids.ts`, `daily_path.ts`).

unique22 leftover still **22** (17 parked + 5 occupancy-equal lifts). Leftover occupancy HOLD pointer unchanged. Do not unify with `comboEventGateOk`. Do not extract.

Do not report 2254/2092 as a product win. Combo +N **HOLD**. unique22 leftover occupancy **HOLD**.

### O. Evaluation IR single generated authority

**status: PARTIAL** (JSON Schema codec SoT; `verify_ci` validates golden + generated `ALLOWED_FIELDS` + encode-key lock + generated TS codec body + freeze-**call** pin + generated Python codec body + **emit extract** + **generated Python TypedDict**) / **OPEN** (`EvaluationIR` dataclass still hand-written; TS decode does not load a JSON Schema engine)

Wave-10 vs wave-9:

- `54c1f472`: codec emitters live in `evaluation_ir_emit.py` (823). Façade `evaluation_ir.py` is 646 (schema load, grade wiring, frozen dataclass). Wave-9 façade was 1224 with emitters in-file.
- `e20be4d9`: emits `evaluation_ir_types.generated.py` (47) from `schema.json`. TypedDict cannot ban unknown fields; runtime `validate_evaluation_ir_schema` remains SoT. `verify_ci` freeze-checks the generated types body.

Codec bodies unchanged: generated Python codec (184); generated TS codec (239); Worker façade `evaluation_ir.ts` (39). Encode object keys remain schema properties; grade remains `jobCandidateGrade` / `job_candidate_grade`. Unknown fields still fail; version stays `evaluation-ir/v1`.

Wave-9 named TypedDict/`EvaluationIR` dataclass still hand-written. TypedDict is now generated. **`@dataclass(frozen=True) class EvaluationIR` is still hand-written** in the façade. Decode on the Worker still uses generated `ALLOWED_FIELDS`, not a JSON Schema engine.

### P. Test audit / reduction

**status: OPEN** (inventory not closed) / **PARTIAL** (Lane 17 audit + collect freezes + digest identity + READY fixture honesty + event-zero tip/index pins + secrets Worker unit)

See [`P632_test_inventory.md`](P632_test_inventory.md) (`3ab87d0`, collected **1353**), [`P632_test_inventory_now.md`](P632_test_inventory_now.md) (`07b4435`, **1379**), [`P632_test_inventory_40d1aa90.md`](P632_test_inventory_40d1aa90.md) (**1426**), [`P632_test_inventory_67fcbd7c.md`](P632_test_inventory_67fcbd7c.md) (**1448**), [`P632_test_inventory_ed94d504.md`](P632_test_inventory_ed94d504.md) (**1470**), [`P632_test_inventory_5103b26b.md`](P632_test_inventory_5103b26b.md) (**1496**), [`P632_test_inventory_3b64bdfc.md`](P632_test_inventory_3b64bdfc.md) (**1503**), [`P632_test_inventory_242c2484.md`](P632_test_inventory_242c2484.md) (**1506** collected; `tests/test_*.py` **153**; Worker first-party **22**; YAML **0**). Local `verify_ci` at `242c2484` reported **1502 passed, 4 skipped**.

This HEAD `git ls-files tests/test_*.py` = **154** (`test_cf_premium_backfill_cli.py` added). Worker first-party test **files** still **22** (18 `*.test.ts` + 4 `*.test.mjs`). Secrets `index.test.ts` grew `it(` **2 → 6** in place. Wave-10 grew existing Python modules (`test_evaluation_ir.py`, `test_jsda_otc_official_domain.py`, `test_verify_ci_script.py`) and shrank Python secrets greps. This wave did **not** re-run `pytest --collect-only`. Do not invent `tests_after`. Count growth is not a consolidation win.

### Q. Whole-repo refactor (authority split)

**status: PARTIAL** / **OPEN** / **HOLD** (named live-math files)

§10 remaining-extracts freeze is authored vs `242c2484` ([`docs/phase63_refactor_plan.md`](../phase63_refactor_plan.md); `39b97859`). That freeze still says TypedDict generation not done. Wave-10 landings vs that freeze:

| §10.3 later | At `242c2484` (wave-9) | After wave-10 |
|-------------|------------------------|---------------|
| 1 BackfillPlanner vs `plan_required_segments` | **DONE** (JQ jobs from required segments; pipeline held OTC HTML; `issue_*` `--index-text`; BackfillPlanner `index_text`). | **DONE** — shared local HTML reader (`2323f6a5`); `cf_premium_backfill --index-text` (`5a8e78c2`); driver uses shared reader (`2b82ec7d`). Live MCP still V2 STALE. |
| 2 Python `r2_io.py` TOCTOU | **PARTIAL** — overlay never CLI-put; research artifacts POST; unbound token 503; daily-path + mass-eval-run Worker put. Remaining `default_r2_put` caller: reconstitution dry_run only. Overlay helper **HOLD**. `r2_io.py` **431**. | **PARTIAL** — empty diff. Remaining `default_r2_put` caller: reconstitution dry_run only. Overlay helper still exists (**HOLD**). `r2_io.py` still **431**. Live POST unproven. |
| 3 hand-written `evaluation_ir.ts` | **PARTIAL** — Python codec body generated (`c9764ff4`, 184). Façade `evaluation_ir.py` 1224. TypedDict/`EvaluationIR` dataclass still hand-written. TS decode still not a JSON Schema engine. | **PARTIAL** — emit extract (`54c1f472`; `evaluation_ir_emit.py` 823; façade 646). Python TypedDict generated (`e20be4d9`, 47). `EvaluationIR` dataclass still hand-written. TS decode still not a JSON Schema engine. |
| 4 MCP frozen “Coverage V2” strings | **FIXED** (not reopened). Live MCP still emits `complete` only. | **FIXED** (not reopened). Live MCP still emits `complete` only. |
| 5 `verify_all` vs `verify_ci` | **HOLD** (local PASS at `3b64bdfc` is not merge-gate; python codec freeze; print-only first-deploy still does not create the producer) | **HOLD** (local PASS at `242c2484` is not merge-gate; python types freeze added; print-only first-deploy still does not create the producer) |

leftover occupancy / `cost_models.py` / generated `catalog_ids.ts` **HOLD**. Coverage V2 JSON vs V3 contracts: planner + OTC grain + `index_text` CLIs + sealer + pipeline held HTML + `issue_*` + BackfillPlanner `index_text` + shared reader + backfill `--index-text` wired for 4 datasets; live MCP still V2 STALE.

Premium fetch/retry extract still **DONE** (`a20d14d4`; `fetch_jq.ts` 297; `index.ts` façade 678). Retry jitter extract still **DONE** (`82ef0f7b`; `retry_jitter.ts`). GATEWAY residual stays **HOLD** (`7221c588`; empty diff on `ai_gateway_client.ts`).

### R. Basket reconstitution evidence

**status: HUMAN** (apply false) / evidence pack **FIXED** (detect-only)

`RECONSTITUTION_APPLY = False`. Agent must not flip apply. Reconstitution evidence stays dry-run-only (`default_r2_put` local stage). Empty diff vs `242c2484` on `reconstitution_evidence.py`.

### S. Controlled Pilot

**status: FIXED** (OFF) — GO conditions **OPEN** / unmet

Worker: `MASS_RESEARCH = "NO-GO"`, `PHASE7 = "OFF"`, `READY_DECLARED = "false"` (`research-mass-eval/wrangler.toml`). Python deny-by-default, `go: False`. **Do not** run the one-shot paper loop. Mass remains **NO-GO**. Auto promotion **OFF**. Live broker **OFF**. Independent C at `242c2484`: catalog/pilot P0 unresolved **0** (no live arming); that is not Phase 7 GO. Catalog identity empty vs this HEAD.

---

## Independent P0 scoreboard (tree vs live)

| ID | At `242c2484` (wave-9) | After wave-10 (`2b82ec7d`) |
|----|------------------------|----------------------------|
| IND-A-DOMAIN | **FIXED**. Live STALE still V2 `2006-08-13`. | **FIXED** (not reopened). Live still STALE. Independent A freeze now at `242c2484`. |
| IND-A-JSDA-PHANTOM | **FIXED** (tree) + BackfillPlanner `index_text`. Live still **8784 / 5886**. PARSE_ZERO stays gap. | **FIXED** (tree) + shared local HTML reader + `cf_premium_backfill --index-text`. Live still **8784 / 5886**. PARSE_ZERO stays gap. Independent A freeze file is still vs `242c2484`. |
| IND-A-PIT-BYPASS | **FIXED** | **FIXED** (not reopened) |
| IND-A-FORGED-RECEIPT | **FIXED** | **FIXED** (not reopened) |
| IND-A-FALSE-COMPLETE | **PARTIAL** (planner forwards `index_text`; omit still not weekend COMPLETE). Live MCP still `complete`. Independent A tree P0 = 0. | **PARTIAL** (shared reader / backfill omit still `None`, not weekend COMPLETE). Live MCP still `complete`. Independent A freeze at `242c2484` still tree P0 = 0. |
| IND-A-READY-DEPS | **FIXED**. Live READY **null**. | **FIXED**. Live **null**. |
| P632B-01 `verify_all` vs `verify_ci` | **PARTIAL** — local PASS at `3b64bdfc`; python codec freeze; live merge gate still not `verify_ci`; producer Worker **absent** | **PARTIAL** — local PASS at `242c2484` documented; python types freeze; live merge gate still not `verify_ci`; producer Worker **absent** |
| P632B-02 live `ci-aggregate` posted | **OPEN** — Worker **absent** (10007). Print-only helper is not a create. **HUMAN** create. Check-runs **0**. | **OPEN** — Worker **absent** (10007). Helper still print-only. **HUMAN** create. Check-runs still **0**. |
| P632B-03 `GATEWAY_TOKEN` / `MASS_EVAL_TOKEN` | **OPEN** / **HOLD** (`7221c588` pointer; empty diff on `ai_gateway_client.ts`). Unbound mass-eval token on children-then-manifest stays **503**. | **OPEN** / **HOLD** (empty diff vs `242c2484` on `ai_gateway_client.ts`). Unbound mass-eval token stays **503**. |
| P632B-05 Python R2 TOCTOU | **PARTIAL** — daily-path + mass-eval-run Worker put. Remaining `default_r2_put` caller: reconstitution dry_run only. Live POST unproven. Overlay helper **HOLD**. | **PARTIAL** — empty diff vs `242c2484`. Remaining `default_r2_put` caller: reconstitution dry_run only. Live POST unproven. Overlay helper **HOLD**. |
| C-YAML load overlay | **FIXED**. +N **HOLD**. Independent C freeze at `0a8ced34` (P0 unresolved **0**; not Phase 7 GO). Catalog identity empty vs `242c2484`. | **FIXED**. +N **HOLD**. Independent C freeze now at `242c2484` (P0 unresolved **0**; not Phase 7 GO). Catalog identity empty vs this HEAD. |

Independent P0 unresolved ≠ 0 (live CI never posted; **ci-aggregate Worker absent**). Independent A tree P0 = 0. Independent B live P0 = **2**. Independent C catalog/pilot P0 = 0. `Pilot_GO.IndependentReview_P0_Zero` stays **OPEN**. Tree shared reader / backfill `--index-text` / secrets Worker unit / IR emit extract / IR TypedDict is not a live Coverage COMPLETE.

---

## Brief §8 `Pilot_GO` (current tree + live MCP)

| Criterion | Status |
|-----------|--------|
| Mandatory_CF_CI | **OPEN** — Worker **absent** (10007); live check-runs **0**. Print-only helper. HUMAN deploy. Conjunction **fails**. |
| Main_Protected | **FIXED** (setting requires `ci-aggregate`) |
| Six_Workers_Clean | lockfiles **FIXED**; `verify_ci` 7 workers **FIXED** (script); retry jitter `getRandomValues` **FIXED** (tree); local PASS at `242c2484` **FIXED** (docs); python types freeze **FIXED** (tree); clean-checkout matrix at this HEAD **OPEN** |
| SourceCapabilityContract_V3 | **PARTIAL** — 4/26 files; nested maps OPEN; missing file fail-closed; OTC grain token **FIXED** |
| RequiredDomain_Subset_OfficialDomain | **PARTIAL** — planner + OTC refresh + `index_text` CLIs + grain + sealer + pipeline held HTML + `issue_*` + BackfillPlanner `index_text` + shared reader + `cf_premium_backfill --index-text`; live MCP still V2 STALE |
| ResearchDataProfile_Complete | **PARTIAL** — core includes master; string COMPLETE rejected; fixture tip receipts; tip/index event-zero PARTIAL; READY **null** |
| Projection_FRESH | **NO** — **STALE** |
| Refresh_SUCCESS | **NO** — `false` |
| B0_PASS | **NO** — **UNKNOWN** |
| READY_Profile_Exists | **NO** — **null** |
| AppliedCursor_Pinned | **NO** — **null** |
| EdgeBudget_Hard | **PARTIAL** (code + create≠reserve pin) / live **OPEN** |
| Artifact_Coherent | Worker digest 409 **FIXED**; overlay never CLI-put **FIXED** (tree); Worker POST client **PARTIAL** (live unproven); daily-path + mass-eval-run Worker put **FIXED** (tree); reconstitution dry_run `default_r2_put` **HOLD** |
| AI_Gateway_Typed | **FIXED** (6.3.1; still true). Dual `GATEWAY_TOKEN` on service-binding **HOLD** (`7221c588`) |
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
2. Bind `GATEWAY_TOKEN` / `MASS_EVAL_TOKEN` / `QUANT_READINESS_HMAC_SECRET` on the intended env. Do not commit values. Unbound mass-eval token stays **503** on children-then-manifest; that is fail-closed, not a bind. P632B-03 service-binding residual stays HOLD until a documented unspoofable caller identity exists.
3. Apply `0007_ops_applied_pins` to remote D1 only when the operator is ready to pin. Until then CURRENT stays impossible.
4. Refresh the ops projection so MCP is FRESH with `refresh_success=true`, passing official-index HTML (`--otc-index-html` / `--index-text`). Tree honesty is not a publish. Live still **8784 / 5886**. Redeploy ops-mcp if `raw_retention.acquired` should be live.
5. Dated reconstitution brief for `basket_theme_fund` / `basket_event_fund` only. Do not flip `RECONSTITUTION_APPLY`.
6. Isolation worktree does **not** push `main`. PR #1 stays **BLOCKED** until `ci-aggregate` actually posts from a **deployed** Worker.

---

## What this file is not

- A rewrite of [`P632_brief_leaks.md`](P632_brief_leaks.md), [`P632_wave2_status.md`](P632_wave2_status.md), [`P632_wave3_status.md`](P632_wave3_status.md), [`P632_wave4_status.md`](P632_wave4_status.md), [`P632_wave5_status.md`](P632_wave5_status.md), [`P632_wave6_status.md`](P632_wave6_status.md), [`P632_wave7_status.md`](P632_wave7_status.md), [`P632_wave8_status.md`](P632_wave8_status.md), or [`P632_wave9_status.md`](P632_wave9_status.md).
- A live Coverage remeasure. Shared reader, backfill `--index-text`, secrets Worker unit, IR emit extract, and IR TypedDict are git; MCP is **STALE**.
- Dataset COMPLETE 23, OTC COMPLETE, B0 PASS, READY, Phase 6.3.2 COMPLETE, Phase 6.4 COMPLETE, or Phase 7 GO.
- Proof that `verify_ci.sh` is green at `2b82ec7d`. Local PASS at `242c2484` is not this SHA and is not merge-gate.
- A deploy of `quant-platform-ci-aggregate`. The print-only helper does not create the Worker. The Worker is **absent**. That is the HUMAN bottleneck.

Wave-10 **tree** honesty landed. Phase 6.3.2 remains **NOT COMPLETE**. Phase 6.4 remains **NOT COMPLETE**. Controlled Pilot remains **NO-GO**.
