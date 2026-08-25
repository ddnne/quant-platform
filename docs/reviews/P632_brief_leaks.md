# Phase 6.3.2 brief leak register vs feature branch

**Brief:** Phase 6.3.2 Cloudflare CI & Authority Closure → 6.4 Source Capability / Live Evidence Closure → Phase 7 Controlled Research Pilot.  
**Named review SHA in brief:** `b5c326a7f612563f2da4a84f08063a307ec38e0a` — **not** a freeze (brief forbids pinning it).  
**Wave-0 receipt:** `docs/reviews/P632_wave0_live.md` (`61b773a`) vs that same `origin/main`.  
**This re-diff HEAD:** `3ab87d0` (`contracts: nested SourceCapability evidence maps are open`) on `grok/phase63-ci-source-closure`.  
**`origin/grok/phase63-ci-source-closure` at this audit:** `3ab87d0` (matches this isolation HEAD).  
**`origin/main` at this audit:** `b5c326a` (feature branch is **not** an ancestor of `main`; not merged).  
**PR:** https://github.com/ddnne/quant-platform/pull/1 — `MERGEABLE` / mergeState **`BLOCKED`** (required `ci-aggregate` has not posted).

Status vocabulary: **OPEN / FIXED / DEFERRED / HOLD / HUMAN / PARTIAL**.  
Do not invent Coverage COMPLETE, Projection FRESH, B0 PASS, READY, Phase 6.3.2 COMPLETE, or Phase 7 GO.

Live `quant-mcp` (this audit; not last-known docs):

```text
Projection: STALE
  generated_at: 2026-08-21T12:30:49.152421+00:00
  age_seconds: 177694 (~49.4h)
  active_generation: projgen-ef18b4f86ee946048161d25e2a30a2a8
  refresh_attempt: true
  refresh_success: false
  last_known_good.not_fresh: true

B0: UNKNOWN  (snapshot quality/B0 projection is unavailable)

READY: null  (no published READY generation is bound)

Sync: applied_feed_cursor: null
  latest_change_seq: 2890654
  CURRENT datasets: 0
  typical dataset state: LAGGING_APPLY_UNPINNED
  equities_master: EXPORT_CURRENT_APPLY_UNPINNED (lag 0, pin still null → never CURRENT)

Coverage: 22 COMPLETE / 4 PARTIAL  (policy_version collection-coverage/v2)
Inventory: 26 governed / 5 experimental / 31
Ops last_run: id 14316 PASS (jquants, 2026-08-23T22:15:01+09:00)
Raw: manifests 20447 / complete 18232
AM SLA current_state: PROJECTION_STALE
```

Cron PASS, raw-retention COMPLETE, and row-count growth are **not** Coverage COMPLETE or READY.

---

## Verdict

| Gate | Status |
|------|--------|
| Phase 6.3.2 COMPLETE? | **NOT COMPLETE** |
| Phase 6.4 COMPLETE? | **NOT COMPLETE** |
| Phase 7 Foundation | types exist; `PHASE7=OFF` |
| Phase 7 Controlled Pilot GO? | **NO-GO** |
| Phase 7 Mass Research GO? | **NO-GO** |

Brief §8 `Pilot_GO` is a conjunction. Live legs fail: Projection **STALE**, `refresh_success=false`, B0 **UNKNOWN**, READY **null**, `applied_feed_cursor=null`, required GitHub `ci-aggregate` **not posted** (`check-runs total_count: 0`, commit status `pending` / `total_count: 0`), Coverage still V2 **22 / 4 PARTIAL**, independent P0 unresolved ≠ 0.

Wave-1 landings on this branch (lockfiles, `verify_ci.sh`, V3 **files**, DO budget **code**, R2 409, active/legacy split, IR schema, reconstitution **evidence**) are not a GO.

---

## A–S vs `3ab87d0`

### A. Cloudflare mandatory CI

**status: PARTIAL** (protection + aggregate Worker in repo) / **OPEN** (live check never posted) / **HUMAN** (token + Builds connect)

| Sub-item | Status | Evidence |
|----------|--------|----------|
| `.github/` workflows | **FIXED** (absent by policy) | `ls .github` → no such file. ADR non-goal. |
| Aggregate Worker | **FIXED** (code) | `platform/workers/ci-aggregate/` — `REQUIRED_WORKERS` six lanes; context `ci-aggregate` (`src/index.ts:3-18`). `843afdb`. |
| Branch protection on `main` | **FIXED** (setting) | `gh api …/branches/main/protection`: `required_status_checks.contexts=["ci-aggregate"]`, `strict: true`, `enforce_admins.enabled: true`, `allow_force_pushes: false`. Wave-0 recorded protection **OFF**; this audit records **ON**. |
| GitHub check-runs / statuses at HEAD | **OPEN** | `commits/3ab87d0/check-runs` `total_count: 0`. `/status` `state: pending`, `total_count: 0`. PR #1 `statusCheckRollup: []`, mergeState **BLOCKED**. |
| Fail/pass merge smoke | **OPEN** | Not demonstrated. Blocked-because-missing-check is not a passing CI receipt. |
| `GITHUB_STATUS_TOKEN` | **HUMAN** | Unbound → HTTP 503, nothing posted (`docs/ci/workers_builds.md:132`). Agent must not mint. |
| Workers Builds Git integration | **OPEN** | Docs map six roots (`docs/ci/workers_builds.md:36-50`). Zero check-runs ⇒ lanes are not posting receipts for this SHA. |
| Explicit promote vs auto-deploy | **HOLD** (policy in docs) | Mandatory CI ≠ production promote. Not exercised. |

PR comment is not the required check. Empty GHA is still not a missing pipeline to add.

---

### B. All six Workers reproducible build

**status: PARTIAL** (lockfiles / scripts) / **OPEN** (clean-checkout proof; `wrangler types --check` not uniform; `Math.random` identity)

Vs brief §4 snapshot (`ingestion-jsda` lockfile missing, `ingestion-secrets` lockfile missing, premium `npm ci` not clean, workers-types v4):

| Worker | lockfile | workers-types | wrangler | test | typecheck | build (dry-run) |
|--------|----------|---------------|----------|------|-----------|-----------------|
| ingestion-jsda | **FIXED** `24287e7` | `^5.20260820.1` | `^4.120.1` | vitest | tsc | yes |
| ingestion-premium | **FIXED** `6499dcc` | `^5.20260820.1` | `^4.120.1` | vitest | tsc | yes |
| ingestion-secrets | **FIXED** `79adc3a` | `^5.20260820.1` | `^4.120.1` | vitest | tsc | yes |
| quant-ops-mcp | present | `^5.20260820.1` | `^4.120.1` | node:test | tsc | yes |
| research-ai-gateway | present | `^5.20260820.1` | `^4.120.1` | vitest | tsc | yes |
| research-mass-eval | present | `^5.20260820.1` | `^4.120.1` | vitest | tsc | yes |

`--legacy-peer-deps` remains banned (`scripts/verify_ci.sh:3,10,97`).

Remaining vs brief completion (`npm ci && npm test && typecheck && wrangler types --check && dry-run` from a **clean checkout**):

- Only `ingestion-jsda` has a `types` script (`wrangler types --include-runtime false`). `verify_ci.sh:105-111` runs `--check` only when that script exists; others run `npx wrangler types` without `--check`.
- This audit did **not** execute the six-worker clean matrix at `3ab87d0`. Do not invent PASS.
- `Math.random()` still used for identity / jitter: `ingestion-premium/src/master_scd2/write.ts:159`, `index.ts:167,177`, `persist_records.ts:36,180`. Brief wanted `crypto.randomUUID()` or content hash.

---

### C. Authoritative CI script

**status: PARTIAL** (`verify_ci.sh` exists, fail-closed, no `VERIFY_*`) / **OPEN** vs brief matrix

- Authoritative: `scripts/verify_ci.sh` (`164f18a`). Six workers. Missing lockfile/dir/script fails. No skip of missing `node_modules`. No `--legacy-peer-deps`.
- Fast helper remains `scripts/verify_all.sh` — still **three** research workers (`:18-22`); default skips missing `node_modules`; `VERIFY_NPM_*` optional. That is not mandatory CI.
- Residual vs brief §C:
  - Does **not** create a fresh venv. Requires existing `.venv` Python 3.11+ (`verify_ci.sh:41-50`) then `pip install -e ".[dev]"`.
  - Evaluation IR check is **file presence** of `golden.jsonl` / `evaluation_ir.py` / `evaluation_ir.ts` (`:62-75`), not schema/codegen drift.
  - Canonical dataset/inventory drift is not a separate fail.
  - `wrangler types --check` not uniform (item B).
  - Script not proven green at this HEAD.

---

### D. SourceCapabilityContract V3

**status: PARTIAL** (typed loader + 3 dataset files) / **OPEN** (23 governed datasets have no V3 file; planner still V2; nested maps open)

- Loader: `packages/data_plane/data_contracts/source_capability.py` (`46e57fe`). Schema: `source_capability.schema.json`.
- On-disk contracts (only): `specs/source_capability/{equities_master,equities_earnings_calendar,equities_bars_daily_am}.json`.
- Coverage / backfill / MCP **do not** derive required starts from V3. `source_capability.py:11-12`: “This module does not rewrite `plan_required_segments`.” Live SoT remains `collection_coverage.json` `schema_version: 2` / `policy_version: collection-coverage/v2` (`collection_coverage.json:1-2`).
- Nested evidence maps **OPEN** by design at this HEAD (`source_capability.py:92-94`; commit `3ab87d0`). Dataset-level keys closed; nested objects are not.
- Empty dir is valid; missing dataset rows are not invented. That is honest — it is also **not** “every dataset has a V3 contract.”

---

### E. Equities Master contract

**status: PARTIAL** (V3 + migration artifact) / **OPEN** (live V2 required start still `2006-08-13`)

Repo (not live COMPLETE):

- Contract: `earliest_official_availability: 2008-05-07`; `not_historical_required_start: 2006-08-13`; clamp-to-official (`specs/source_capability/equities_master.json`; `d5163e4`).
- Migration: `specs/coverage_v3/equities_master_migration.json` — 21 V2 PARTIAL months `2006-08..2008-04` mapped `excluded_official_unavailable`. `invent_complete: false`.

Live MCP `coverage_gaps`:

- `equities_master` **PARTIAL**, `policy_version: collection-coverage/v2`, `history_target_start: 2006-08-13`, observed `2008-05-01` → `2026-08-12`, `row_count: 8072621`.
- Runtime coverage JSON still `history_target_start: 2006-08-13` (`collection_coverage.json:13-14`).

Official-domain correction in git ≠ live required-set migration. Do not invent Dataset COMPLETE.

---

### F. Earnings Calendar contract

**status: PARTIAL** (V3 + migration) / **OPEN** (live still 200 monthly V2 PARTIAL)

- Contract: `history_mode: next_business_day_snapshot`, `historical_research_eligible: false`, `tip_only_operational: true` (`specs/source_capability/equities_earnings_calendar.json`; `4069b34`).
- Migration: `specs/coverage_v3/equities_earnings_calendar_migration.json`.
- Live MCP: **PARTIAL**, `history_target_start: 2010-01-04`, `coverage_mode: event_reconciled`, Wave-0 `1/200` unchanged as a live number in this fetch (gap row still present). Runtime JSON still `2010-01-04` (`collection_coverage.json:59-60`).
- Past months were not emptied into COMPLETE. Good. 200 monthly required segments are **not** abolished in the live planner.

---

### G. AM bars contract

**status: PARTIAL** (V3 + migration) / **OPEN** (live still monthly V2 PARTIAL; SLA under STALE)

- Contract: `history_mode: recent_snapshot`, `tip_only_operational: true`, SLA `expected_after 11:30` / `usable_by 12:30` JST (`specs/source_capability/equities_bars_daily_am.json`; `ea12767`).
- Migration: `specs/coverage_v3/equities_bars_daily_am_migration.json`.
- Live MCP gap: **PARTIAL**, `history_target_start: 2024-01-04`, observed `2026-08-01` → `2026-08-11`. Runtime JSON still that start (`collection_coverage.json:27-28`). 32 monthly historical required **not** removed from V2 planner.
- `collection_sla_status(equities_bars_daily_am)`: `current_state: PROJECTION_STALE` / `state_reason: ops_projection_stale`. Do not invent AM SLA PASS.

---

### H. JSDA OTC official-index Coverage

**status: OPEN**

- No `specs/source_capability/jsda_otc_bond_reference_prices.json`. No `specs/coverage_v3/` JSDA migration.
- Runtime: `history_target_start: 2002-08-02`, `coverage_mode: official_archive_index_reconciled` (`collection_coverage.json:157-164`).
- Live MCP: **PARTIAL**, same start, observed `2002-08-06` → `2026-08-20`, `row_count: 47814126`. Wave-0 **5886 / 8784** not re-derived here; weekend/holiday still in the V2 required calendar-day set until official-index required-set generation lands.
- 2002-08-02 / 05 adapter COMPLETE (23-column, nz parse, digest, trusted receipt) **not** closed on this branch.
- PARSE_ZERO / empty-row COMPLETE remains forbidden. Do not invent COMPLETE 23.

---

### I. ResearchDataProfile / READY

**status: PARTIAL** (v1 predicate in repo) / **OPEN** (live READY **null**)

- `packages/product/research/research_data_profile.py` (`0cce277`). `PROFILE_VERSION = research-data-profile/v1`. `profile_ready()` does **not** publish (`:155-176`).
- Core profile: `specs/research_profiles/core_v1.json` — required daily bars + fins_* + `markets_calendar`; excludes AM + earnings calendar with reasons. FeatureRef/StrategySpec datasets cannot be omitted.
- Live `latest_ready_snapshot`: `snapshot: null`, `reason: no published READY generation is bound to this Worker`.
- No existing-READY schema migration on Cloudflare. Digest-bound predicate ≠ a bound READY generation.

---

### J. Projection / sync operational closure

**status: OPEN** (live) — code honesty **FIXED** (do not re-open)

Live (this fetch):

| Criterion | Live |
|-----------|------|
| `projection_status` | **STALE** |
| `refresh_success` | **false** |
| `applied_feed_cursor` | **null** |
| CURRENT datasets | **0** |
| B0 | **UNKNOWN** |
| READY | **null** |

`applied == null` still never CURRENT (`LAGGING_APPLY_UNPINNED` / `EXPORT_CURRENT_APPLY_UNPINNED`). Last-known-good projection is **not** FRESH (`last_known_good.not_fresh: true`).

`0007_ops_applied_pins.sql:1-5` — schema only; “Do not apply this migration remotely from this change set.” Remote apply is **HUMAN** (item remains OPEN until pin ≠ null).

Coverage refresh root cause is **not** closed: `refresh_attempt true` / `refresh_success false` still the live pair.

---

### K. Edge Durable Object hard budget

**status: PARTIAL** (DO reserve/reconcile in repo) / **OPEN** (live Edge unproven; string `budget_id` still also required)

- `platform/workers/research-ai-gateway/src/budget_do.ts` (`8afe0a2`). Caps match brief (`PILOT_BUDGET_CAPS`: plans 4 / parallel 2 / generations 1 / model_calls 16 / tokens 400k/80k / paper 8 / $20 / TTL 1800 / `auto_promotion: false`).
- Binding: `wrangler.toml:16-21` `BUDGET_LEDGER` / `BudgetLedger` sqlite migration tag `v1`.
- `index.ts` reserves **before** provider call; exhaustion fails closed.
- Presence of `budget_id` remains a schema requirement (`schema.test.ts`) — that is **not** the reserve. Brief forbids counting the string check as hard budget done; the DO is the new authority **in this tree**, not proven on the deployed gateway.
- Live Cloudflare DO occupancy / double-spend under production traffic: **not** measured this audit.

---

### L. Worker public boundary

**status: PARTIAL** (service binding present) / **OPEN** (shared `GATEWAY_TOKEN` still required) / **HOLD** (`workers_dev=true`) / **HUMAN** (secret bind)

Intended:

| Worker | Brief | Tree |
|--------|-------|------|
| quant-ops-mcp | remote public, OAuth, read-only | still `workers_dev = true` (`wrangler.toml:7`) |
| research-ai-gateway | service binding only, no external public | `workers_dev = true`; still `GATEWAY_TOKEN` fail-closed (`wrangler.toml:4-11`) |
| research-mass-eval | internal/admin | `workers_dev = true`; `AI_GATEWAY` service binding (`wrangler.toml:40-42`) **and** `GATEWAY_TOKEN` header (`ai_gateway_client.ts:23-51`) |
| ingestion-* | cron/internal / narrow proxy | all `workers_dev = true` |

Dual authority is **not** resolved: service binding exists; shared bearer still required (`gateway_token_unbound` if missing). Bind is **HUMAN**.

Ops MCP must not grow SQL / fetch / ingest / delete / READY publish / approve / broker / shell / secret-read. Not re-opened.

`workers_dev=true` kept on all product wranglers plus `ci-aggregate` (receipt POST host). Treat **kept** as **HOLD**, not a silent disable.

---

### M. Immutable artifact authority

**status: PARTIAL** (Worker child digest 409) / **OPEN** (Python CLI still TOCTOU writer)

- Worker: existing child digest mismatch → 409, no manifest (`research-mass-eval/src/http.ts:85-137`, `putChildrenThenManifest`; `eef69ef`). Replay same digest is idempotent (tests in `http.test.ts`).
- Python: `packages/product/research/r2_io.py:1-4,50-69` — head-then-put **TOCTOU**; `authoritative=True` refused; CLI put is still the put path. Tests pin the TOCTOU comment (`tests/test_immutable_artifact.py`). Brief: do **not** treat “TOCTOU recorded” as done. Publication is **not** delegated to Worker conditional-put.

---

### N. Active Catalog / Legacy Identity Registry

**status: PARTIAL** (v2 classification) / **OPEN** (compact source; `migration.jsonl` still load SoT)

Measured at `3ab87d0`:

```text
compiled n = 2254  (freeze CATALOG_YAML_COUNT_AT_STOP)
active     = 2092
legacy     = 162
pilot_candidates() == active  (legacy disjoint)
yaml_still_present = false
```

- `packages/product/research/catalog_active.py` (`f9fb9a1`). Compiler split version `research_catalog_compiler/v2` over v1 digest lock (`catalog_compiler.py:26-27`). Unique22 park stays **legacy**, not unparked (`tests/test_catalog_active_legacy.py:85-90`).
- Load SoT is still `specs/research_catalog/migration.jsonl` (`unique_logic/catalog.py:180-208`). Not demoted to generated-only. Compact `family + template + parameter matrix` **not** implemented.
- `catalog_ids.ts` not hand-edited this audit. YAML not re-added. AND/+N remain stopped (`eval_flags.py:7-11`). Do not report 2254 as a product win; do not report 2092 as expansion.

Combo +N **HOLD** (identity freeze). unique22 leftover occupancy **HOLD** (`daily_path.ts:522-525`).

---

### O. Evaluation IR single generated authority

**status: PARTIAL** (JSON Schema codec SoT) / **OPEN** (hand-written dual codecs remain)

- Schema: `specs/evaluation_ir/schema.json` (`548d269`). Python encode/decode validates; unknown fields fail; version const `evaluation-ir/v1` (`evaluation_ir.py:1-17`).
- Golden still encoder-owned (`emit_evaluation_ir_golden` → `specs/evaluation_ir/golden.jsonl`).
- Worker `evaluation_ir.ts` is still a **hand-written** TS codec. Grade predicate shared (`job_candidate_grade` / `jobCandidateGrade`). Brief asked generated Python+TS types and deletion of duplicate codecs. **Not** done.
- `verify_ci.sh` does not fail schema/codegen drift (item C).

---

### P. Test audit / reduction

**status: OPEN** (inventory not closed on this branch) / **PARTIAL** (Lane 17 audit docs exist)

- Brief `tests_before` ~ **1282** collected. This register did **not** re-run `pytest --collect-only`. Do not invent `tests_after`.
- Historical audit: `docs/phase63_test_audit.md` (tip `1efb405`). Combinatorial / dual-runtime echoes / freeze-n tests remain the reduction target.
- Mechanism replacements (route registry, generated schema, compiler set-equality) are incomplete (see C, N, O).
- Sibling inventory (if any) is not this file.

---

### Q. Whole-repo refactor (authority split)

**status: PARTIAL** (some extracts already on `main` / this branch) / **OPEN** / **HOLD** (named live-math files)

Split when mixed authority, not by line count. Still mixed or explicitly held:

| Surface | Status |
|---------|--------|
| leftover occupancy `daily_path.ts` / `UNIQUE22_PARK_REASONS` | **HOLD** |
| `cost_models.py` / `options_225_vol_series.py` | **HOLD** (do not split for line count) |
| generated `catalog_ids.ts` | **HOLD** (compiler emit; do not hand-edit) |
| Python vs TS IR codecs | **OPEN** (O) |
| Coverage V2 JSON vs V3 contracts | **OPEN** (D–H) |
| historical review docs as live SoT | freeze files stay historical; this file is the re-diff |
| dead helpers | prior `D_dead_functions.md`; not re-opened |

Live status must come from CI receipt / MCP projection. This register uses live MCP + tree SHA, not freeze-doc numbers.

---

### R. Basket reconstitution evidence

**status: HUMAN** (apply false) / evidence pack **FIXED** (detect-only)

- `RECONSTITUTION_APPLY: bool = False` (`eval_flags.py:12`).
- Pack: `packages/product/research/reconstitution_evidence.py` (`1569dbb`). `recommended_choice = drop_children_keep_parents` unless economics clearly better (default path: not clearly better). `apply` stays false. Live R2 put refused (`write_reconstitution_evidence_pack` `put_r2` + not `dry_run` raises).
- Tests: `tests/test_reconstitution_evidence.py:42-56` — `apply is False`, `recommended_choice_is_not_apply`, `evidence_status == local_schema_only`.
- Pending ids remain `basket_theme_fund` / `basket_event_fund`. Agent must not flip apply. Does **not** block CI/profile **code**; **does** remain a human gate. No remote R2 evidence_key published this audit.

---

### S. Controlled Pilot

**status: FIXED** (OFF) — GO conditions **OPEN** / unmet

- Worker: `MASS_RESEARCH = "NO-GO"`, `PHASE7 = "OFF"`, `READY_DECLARED = "false"` (`research-mass-eval/wrangler.toml:48-50`).
- Python: `research_capabilities.py:13-51` deny-by-default, `go: False`. `pilot_loop.py` execution routes raise `MassResearchDisabledError`. Construct still `require_valid` (6.3.1 D; do not re-open).
- Brief: start() stays OFF until `Pilot_GO`. `Pilot_GO` fails (see Verdict). **Do not** run the one-shot paper loop.
- Mass remains **NO-GO**. Auto promotion **OFF**. Live broker **OFF**. Reconstitution pending baskets not auto-changed.

---

## Mechanism vs thesis

None of the remaining leaks is a new thesis YAML. Do not add YAML. `CATALOG_AND_PLUS_N_STOPPED` holds n=2254.

| Concern | Mechanism | Not a thesis |
|---------|-----------|--------------|
| Merge gate | Cloudflare `ci-aggregate` status + branch protection | not a workflow YAML in `.github` |
| Worker build | lockfile + `verify_ci.sh` six-lane npm ci | not `--legacy-peer-deps` |
| Official domain | SourceCapability V3 → Coverage V3 migration | not a floor bump on V2 JSON |
| READY | `ResearchDataProfile` digest ∧ COMPLETE(Deps(P)) | not 26 historical COMPLETE |
| Sync CURRENT | non-null applied pin | not coverage COMPLETE |
| LLM spend | DO reserve/reconcile before provider | not `budget_id` string |
| Artifact | Worker children-then-manifest + digest 409 | not Python CLI put |
| Catalog | active 2092 / legacy 162 over freeze 2254 | not +N / not YAML |
| IR | schema.json SoT | not a second grade policy |
| Pilot | capabilities deny + PHASE7=OFF | not GO |
| Reconstitution | evidence pack, apply false | not auto-choose |

---

## Brief §8 `Pilot_GO` (current tree + live MCP)

| Criterion | Status |
|-----------|--------|
| Mandatory_CF_CI | **OPEN** — Worker+protection PARTIAL; live check-runs **0** |
| Main_Protected | **FIXED** (setting requires `ci-aggregate`) |
| Six_Workers_Clean | lockfiles **FIXED**; clean-checkout matrix **OPEN** |
| SourceCapabilityContract_V3 | **PARTIAL** — 3/26 files; nested maps OPEN |
| RequiredDomain_Subset_OfficialDomain | **OPEN** — live planner still V2 |
| ResearchDataProfile_Complete | **PARTIAL** — predicate only; READY **null** |
| Projection_FRESH | **NO** — **STALE** |
| Refresh_SUCCESS | **NO** — `false` |
| B0_PASS | **NO** — **UNKNOWN** |
| READY_Profile_Exists | **NO** — **null** |
| AppliedCursor_Pinned | **NO** — **null** |
| EdgeBudget_Hard | **PARTIAL** (code) / live **OPEN** |
| Artifact_Coherent | Worker digest 409 **FIXED**; Python TOCTOU **OPEN** |
| AI_Gateway_Typed | **FIXED** (6.3.1; still true) |
| PaperExecution_Authoritative | not re-opened; Mass/paper still unarmed |
| IndependentReview_P0_Zero | **OPEN** |

## 6.4 live (not invented)

| Criterion | Live |
|-----------|------|
| governed Coverage COMPLETE (official mode) | **NO** — 22 held / **4 PARTIAL** under V2 |
| projection FRESH | **STALE** |
| B0 PASS | **UNKNOWN** |
| applied sync generation pinned/current | **unpinned** (`applied_cursor=null`) |
| immutable READY ≥ 1 | **null** |
| AM SLA live evidence | **PROJECTION_STALE** |
| Remote MCP vs docs | last-known under STALE; no active gen ⇒ B0 UNKNOWN |

---

## Human actions (not agent)

1. Bind `GITHUB_STATUS_TOKEN` on `quant-platform-ci-aggregate`. Connect Workers Builds for six lanes. Prove a **failing** SHA is unmergeable and a **passing** six-receipt SHA posts `ci-aggregate` success. Isolation worktree does **not** do that.
2. Bind `GATEWAY_TOKEN` / `MASS_EVAL_TOKEN` / `QUANT_READINESS_HMAC_SECRET` on the intended env. Do not commit values.
3. Apply `0007_ops_applied_pins` to remote D1 only when the operator is ready to pin. Until then CURRENT stays impossible.
4. Dated reconstitution brief for `basket_theme_fund` / `basket_event_fund` only. Do not flip `RECONSTITUTION_APPLY`.
5. Isolation worktree does **not** push. This register is vs `3ab87d0` on `grok/phase63-ci-source-closure`. PR #1 stays **BLOCKED** until `ci-aggregate` actually posts.

---

## Commits this re-diff accounts for

`origin/main..3ab87d0` (not a GO claim):

| SHA | Purpose | Lane |
|-----|---------|------|
| `61b773a` | Wave-0 live remeasure | (receipt) |
| `24287e7` | ingestion-jsda lockfile / npm ci / typecheck / dry-run | B |
| `79adc3a` | ingestion-secrets lockfile / npm ci / typecheck / dry-run | B |
| `f9fb9a1` | active catalog vs legacy identity | N |
| `6499dcc` | ingestion-premium npm ci without legacy-peer-deps | B |
| `164f18a` | `verify_ci.sh` six workers | C |
| `46e57fe` | SourceCapabilityContract v3 typed loader | D |
| `d5163e4` | equities_master official domain 2008-05-07 | E |
| `0cce277` | ResearchDataProfile v1 digest-bound READY predicate | I |
| `548d269` | evaluation-ir JSON Schema codec SoT | O |
| `eef69ef` | R2 existing child digest mismatch 409 | M |
| `843afdb` | ci-aggregate required status from six lane receipts | A |
| `1569dbb` | reconstitution evidence pack; apply false | R |
| `4069b34` | earnings calendar tip snapshot | F |
| `ea12767` | AM bars same-day snapshot | G |
| `8afe0a2` | Durable Object hard budget reserve | K |
| `3ab87d0` | nested SourceCapability evidence maps are open | D |

Do not re-litigate 6.3.1 freeze docs (`03cd1b1` / `P631_brief_leaks.md`) as live SoT. This file is the 6.3.2 A–S re-diff vs `3ab87d0`.
