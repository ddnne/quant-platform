# Phase 6.3.2 Wave-2 status — after P0 closes (not a GO)

**Isolation worktree:** `docs/p632-wave2-status` (do not push).  
**Does not clobber:** [`P632_brief_leaks.md`](P632_brief_leaks.md) (A–S freeze vs `3ab87d0`).  
**Feature branch:** `grok/phase63-ci-source-closure`  
**This HEAD:** `07b4435` (`07b44355dc745b1a9b7f7c3c4eccbe123e7a171b`) — `docs: merge gate is verify_ci plus authenticated ci-aggregate`.  
**`origin/main`:** `b5c326a` (feature branch is **not** an ancestor of `main`; not merged).  
**Named review SHA in brief:** `b5c326a` — **not** a freeze.  
**Wave-0:** [`P632_wave0_live.md`](P632_wave0_live.md). **Wave-1 A–S register:** [`P632_brief_leaks.md`](P632_brief_leaks.md) vs `3ab87d0`.

Status vocabulary: **OPEN / FIXED / DEFERRED / HOLD / HUMAN / PARTIAL**.  
Do not invent Coverage COMPLETE, Projection FRESH, B0 PASS, READY, Phase 6.3.2 COMPLETE, Phase 6.4 COMPLETE, or Phase 7 GO.

---

## Live MCP (this wave; not last-known docs)

```text
Projection: STALE
B0: UNKNOWN
READY: null
```

No FRESH claim. No B0 PASS. No bound READY generation. Isolation does not refresh the ledger. Last-known-good Coverage **22 COMPLETE / 4 PARTIAL** under STALE `collection-coverage/v2` floors remains the live narrative, **not** a remeasure of the wired V3 planner.

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

Wave-2 P0 **code** closes (core master, `CI_LANE_TOKEN`, `verify_ci` 7 workers, OTC index planner, YAML overlay opt-in) are not a GO. Brief §8 `Pilot_GO` is a conjunction; live legs still fail: Projection **STALE**, B0 **UNKNOWN**, READY **null**, required GitHub `ci-aggregate` **not posted**, independent P0 unresolved ≠ 0.

---

## This session's expected landings (on `07b4435`)

| SHA | Landing | Closes (tree) | Does **not** close |
|-----|---------|---------------|-------------------|
| `aaa830f` | core ResearchDataProfile requires `equities_master` | IND-A-READY-DEPS **code** | live READY **null**; STALE V2 PARTIAL still AND-false |
| `ff053a3` | ci-aggregate receipts require `CI_LANE_TOKEN` | unauthenticated `/v1/receipts` in tree | token **bind** (HUMAN); live check never posted |
| `a30343e` | `verify_ci.sh` includes `ci-aggregate` (7 workers) | P632B-01 script hole (`len(WORKERS)==7`) | merge gate is still live GitHub `ci-aggregate`, not a green `verify_ci` |
| `9a63402` | OTC required days from official index, not calendar | IND-A-JSDA-PHANTOM **planner** | live STALE 8784 inventory; PARSE_ZERO not COMPLETE; missing index → empty UNKNOWN |
| `210deb1` | catalog YAML overlay opt-in fail-closed (`QP_ALLOW_YAML_OVERLAY=1`) | C-YAML load-path replace-compiled | freeze still `n=2254`; opt-in overlay is HOLD identity, not +N |

Adjacent on this branch since the `3ab87d0` A–S freeze (not invented GO): V3 planner for master / AM / earnings (`5796fb0`); OTC contract (`1c92bad`) + 23-col parse (`cc4e340`); projection FRESH requires `refresh_success` (`2f0024d`); parallel SoT master `2008-05-07` (`1cb6d84`); AM/earnings JQ vendor snapshot params (`b214969`); merge-gate docs (`07b4435`).

---

## A–S vs `07b4435` (after wave-2 P0 closes)

Prior register: [`P632_brief_leaks.md`](P632_brief_leaks.md) vs `3ab87d0`. This table is the wave-2 re-diff, not a rewrite of that file.

### A. Cloudflare mandatory CI

**status: PARTIAL** (protection + Worker + `CI_LANE_TOKEN` in repo) / **OPEN** (live check never posted) / **HUMAN** (`CI_LANE_TOKEN` + `GITHUB_STATUS_TOKEN` bind)

| Sub-item | At `3ab87d0` | After wave-2 |
|----------|--------------|--------------|
| `.github/` workflows | **FIXED** (absent) | **FIXED** — do not add |
| Aggregate Worker | **FIXED** (code; six lane receipts) | **FIXED** (code) + inbound `X-CI-Lane-Token` vs `CI_LANE_TOKEN` (`ff053a3`). Unbound → HTTP **503**. Wrong header → **401**. PR comments still not a substitute. |
| `verify_ci` covers gate Worker | **OPEN** (asserted absent) | **FIXED** (`a30343e`; 7th Worker) |
| Branch protection on `main` | **FIXED** (requires `ci-aggregate`) | **FIXED** (setting). Not a passing receipt. |
| GitHub check-runs / statuses at HEAD | **OPEN** (`total_count: 0`) | **OPEN** — isolation does not post. No `ci-aggregate` success claimed at `07b4435`. |
| Fail/pass merge smoke | **OPEN** | **OPEN** |
| `GITHUB_STATUS_TOKEN` / `CI_LANE_TOKEN` bind | **HUMAN** | **HUMAN** — agent must not mint |
| Workers Builds Git integration | **OPEN** | **OPEN** |
| Explicit promote vs auto-deploy | **HOLD** | **HOLD** |

### B. All six Workers reproducible build

**status: PARTIAL** (lockfiles; `verify_ci` now **seven** Workers) / **OPEN** (clean-checkout proof)

Six product lanes still the receipt batch (`REQUIRED_WORKERS`). Seventh Worker is `ci-aggregate` itself (`verify_ci.sh` `WORKERS` length **7**; tests pin `len(WORKERS) == 7`). `--legacy-peer-deps` remains banned.

Residuals vs brief completion (`npm ci && npm test && typecheck && wrangler types --check && dry-run` from a **clean checkout**): matrix **not** executed at this HEAD in this isolation. Do not invent PASS. `Math.random()` identity/jitter in premium persist remains.

### C. Authoritative CI script

**status: PARTIAL** (`verify_ci.sh` fail-closed, 7 workers, no `VERIFY_*`) / **OPEN** (merge gate is live GitHub context)

- Authoritative: `scripts/verify_ci.sh`. Missing lockfile/dir/script fails. No skip of missing `node_modules`. No `--legacy-peer-deps`. Includes `platform/workers/ci-aggregate`.
- Fast helper remains `scripts/verify_all.sh` (three research workers; optional `VERIFY_*`). Still **not** mandatory CI.
- Residual: does **not** create a fresh venv (requires existing `.venv` 3.11+). Script not proven green at this HEAD. Live merge authority is still “six lane receipts POSTed with `CI_LANE_TOKEN` → GitHub `ci-aggregate`”, not “`verify_ci.sh` exited 0”.

### D. SourceCapabilityContract V3

**status: PARTIAL** (typed loader + **4** dataset files) / **OPEN** (22 governed datasets have no V3 file; nested maps open)

On-disk: `specs/source_capability/{equities_master,equities_earnings_calendar,equities_bars_daily_am,jsda_otc_bond_reference_prices}.json`. Nested evidence maps remain **OPEN** by design (`3ab87d0`). Empty dir is valid; missing dataset rows are not invented.

Planner **does** use V3 when present (`5796fb0` + `9a63402`). That is a wire, not Dataset COMPLETE 23. Live MCP is STALE and still advertises V2 floors.

### E. Equities Master contract

**status: PARTIAL** (V3 + planner + core profile + parallel SoT in repo) / **OPEN** (live STALE still V2 `2006-08-13`)

Repo: `earliest_official_availability: 2008-05-07`; coverage JSON `history_target_start: 2008-05-07` / `policy_version: collection-coverage/v3`; `canonical_datasets.json` and `EXPECTED_START` aligned (`1cb6d84`). Core profile `required_datasets` includes `equities_master` (`aaa830f`).

Live MCP: last-known **PARTIAL** under STALE V2 `2006-08-13`. Official-domain correction in git ≠ live required-set migration. Do not invent Dataset COMPLETE.

### F. Earnings Calendar contract

**status: PARTIAL** (V3 + tip-snapshot planner) / **OPEN** (live still 200 monthly V2 PARTIAL under STALE)

Planner yields **1** cutoff snapshot, not 200 months. Live gap row is STALE last-known. Do not empty past months into COMPLETE.

### G. AM bars contract

**status: PARTIAL** (V3 + same-day snapshot planner) / **OPEN** (live still monthly V2 PARTIAL; SLA under STALE)

Planner yields **1** cutoff snapshot, not 32 months. AM SLA under Projection **STALE** is not PASS.

### H. JSDA OTC official-index Coverage

**status: PARTIAL** (V3 file + planner uses official index) / **OPEN** (live STALE calendar inventory; PARSE_ZERO not sealed)

`plan_required_segments` for official-archive-index / `jsda_otc` uses `official_index_days` (`9a63402`). Missing `index_text` → **empty** required set (UNKNOWN / fail-closed), **not** an 8784-day calendar walk. Tests pin weekends out of the required set and PARSE_ZERO days **in** it.

Live MCP still last-known Wave-0 **5886 / 8784**. Do not COMPLETE empty non-index days. Do not hide PARSE_ZERO by moving `history_target_start`. 23-col adapter is parse-only — not a 2002-08-02 COMPLETE seal.

### I. ResearchDataProfile / READY

**status: PARTIAL** (v1 predicate + core requires master) / **OPEN** (live READY **null**)

`CORE_REQUIRED_DATASETS` and `specs/research_profiles/core_v1.json` include `equities_master` (`aaa830f`). Tip-only AM / earnings calendar remain excluded. `profile_ready()` still does **not** publish.

Live `latest_ready_snapshot`: **null**. Digest-bound predicate ≠ a bound READY generation. Adding master without a FRESH official-domain ledger keeps READY honest-false against STALE PARTIAL. That is intended; it is not a GO.

Residual (do not re-open READY-DEPS omission): `_complete_under_official` still accepts a bare `"COMPLETE"` **string** with no `official_mode` check (IND-A-FALSE-COMPLETE).

### J. Projection / sync operational closure

**status: OPEN** (live) — code honesty **FIXED** (do not re-open)

| Criterion | Live |
|-----------|------|
| `projection_status` | **STALE** |
| B0 | **UNKNOWN** |
| READY | **null** |

`refresh_success` remains false on the live generation (see [`P632_projection_stale.md`](P632_projection_stale.md)). `applied_feed_cursor` last-known **null** → never CURRENT. `0007_ops_applied_pins` remote apply is **HUMAN**.

### K. Edge Durable Object hard budget

**status: PARTIAL** (DO reserve/reconcile in repo) / **OPEN** (live Edge unproven)

Caps unchanged. String `budget_id` is still not the reserve. Live occupancy / double-spend under production traffic: **not** measured this wave.

### L. Worker public boundary

**status: PARTIAL** (preview vs production split on this branch) / **OPEN** (shared bearer still required on remaining surfaces) / **HOLD** (`workers_dev` kept where documented) / **HUMAN** (secret bind)

`ddf412e` split: production `workers_dev=false` on research-ai-gateway, research-mass-eval, ingestion-jsda, ingestion-premium. **Kept true:** quant-ops-mcp (OAuth callback), ingestion-secrets (token-gated local), ci-aggregate (receipt POST host). Treat **kept** as **HOLD**. Dual `GATEWAY_TOKEN` / service-binding residual: **OPEN**. Ops MCP must not grow SQL / fetch / ingest / delete / READY publish. Not re-opened.

### M. Immutable artifact authority

**status: PARTIAL** (Worker child digest 409) / **OPEN** (Python CLI still TOCTOU writer)

Unchanged vs `3ab87d0`. Do not treat “TOCTOU recorded” as done.

### N. Active Catalog / Legacy Identity Registry

**status: PARTIAL** (v2 classification + YAML overlay fail-closed) / **OPEN** (compact source; `migration.jsonl` still load SoT)

YAML n at HEAD = **0**. Compiled freeze n = **2254**. Load without `QP_ALLOW_YAML_OVERLAY=1` **raises** if any `*.yaml` is present (`210deb1`). Overlay `=1` still replaces the compiled map (HOLD identity / tests; not a product path). `assert_catalog_and_plus_n_stopped` still accepts yaml n==2254 if files exist — freeze identity, not load SoT.

Do not report 2254/2092 as a product win. Combo +N **HOLD**. unique22 leftover occupancy **HOLD**.

### O. Evaluation IR single generated authority

**status: PARTIAL** (JSON Schema codec SoT; `verify_ci` pins schema.json) / **OPEN** (hand-written dual codecs remain)

Worker `evaluation_ir.ts` is still a hand-written TS codec. Brief asked generated Python+TS types. **Not** done.

### P. Test audit / reduction

**status: OPEN** (inventory not closed) / **PARTIAL** (Lane 17 audit docs exist)

See [`P632_test_inventory.md`](P632_test_inventory.md). Do not invent `tests_after`.

### Q. Whole-repo refactor (authority split)

**status: PARTIAL** / **OPEN** / **HOLD** (named live-math files)

Coverage V2 JSON vs V3 contracts: planner wired for 4 datasets; live MCP still V2 STALE. Python vs TS IR codecs **OPEN**. leftover occupancy / `cost_models.py` / generated `catalog_ids.ts` **HOLD**.

### R. Basket reconstitution evidence

**status: HUMAN** (apply false) / evidence pack **FIXED** (detect-only)

`RECONSTITUTION_APPLY = False`. Agent must not flip apply.

### S. Controlled Pilot

**status: FIXED** (OFF) — GO conditions **OPEN** / unmet

Worker: `MASS_RESEARCH = "NO-GO"`, `PHASE7 = "OFF"`, `READY_DECLARED = "false"`. Python deny-by-default, `go: False`. **Do not** run the one-shot paper loop. Mass remains **NO-GO**.

---

## Independent P0 scoreboard (tree vs live)

| ID | At `3ab87d0` / revisit | After wave-2 landings |
|----|------------------------|------------------------|
| IND-A-DOMAIN | OPEN → FIXED at `5796fb0` (planner) | **FIXED** (planner). Live STALE ≠ COMPLETE 23. |
| IND-A-JSDA-PHANTOM | OPEN | **FIXED** (planner `9a63402`). Live inventory STALE. PARSE_ZERO stays gap. |
| IND-A-PIT-BYPASS | OPEN | **OPEN** |
| IND-A-FORGED-RECEIPT | FIXED | **FIXED** (not reopened) |
| IND-A-FALSE-COMPLETE | OPEN (raw-only ban FIXED) | **OPEN** (event-zero + string COMPLETE) |
| IND-A-READY-DEPS | OPEN | **FIXED** (core includes master). READY still **null**. |
| P632B-01 `verify_all` vs `verify_ci` | OPEN (7th Worker missing) | **PARTIAL** — script covers 7; live merge gate is not `verify_ci` |
| P632B-02 live `ci-aggregate` posted | OPEN | **OPEN** |
| C-YAML load overlay | P1 OPEN | **FIXED** (fail-closed without `QP_ALLOW_YAML_OVERLAY=1`) |

Independent P0 unresolved ≠ 0 (PIT bypass, false-COMPLETE, live CI never posted). `Pilot_GO.IndependentReview_P0_Zero` stays **OPEN**.

---

## Brief §8 `Pilot_GO` (current tree + live MCP)

| Criterion | Status |
|-----------|--------|
| Mandatory_CF_CI | **OPEN** — Worker+token+protection PARTIAL; live check-runs **not posted** |
| Main_Protected | **FIXED** (setting requires `ci-aggregate`) |
| Six_Workers_Clean | lockfiles **FIXED**; `verify_ci` 7 workers **FIXED** (script); clean-checkout matrix **OPEN** |
| SourceCapabilityContract_V3 | **PARTIAL** — 4/26 files; nested maps OPEN |
| RequiredDomain_Subset_OfficialDomain | **PARTIAL** — planner wired (master / AM / earnings / OTC); live MCP still V2 STALE |
| ResearchDataProfile_Complete | **PARTIAL** — core includes master; READY **null** |
| Projection_FRESH | **NO** — **STALE** |
| Refresh_SUCCESS | **NO** |
| B0_PASS | **NO** — **UNKNOWN** |
| READY_Profile_Exists | **NO** — **null** |
| AppliedCursor_Pinned | **NO** (last-known unpinned) |
| EdgeBudget_Hard | **PARTIAL** (code) / live **OPEN** |
| Artifact_Coherent | Worker digest 409 **FIXED**; Python TOCTOU **OPEN** |
| AI_Gateway_Typed | **FIXED** (6.3.1; still true) |
| PaperExecution_Authoritative | not re-opened; Mass/paper still unarmed |
| IndependentReview_P0_Zero | **OPEN** |

## 6.4 live (not invented)

| Criterion | Live |
|-----------|------|
| governed Coverage COMPLETE (official mode) | **NO** — 22 held / **4 PARTIAL** last-known under STALE |
| projection FRESH | **STALE** |
| B0 PASS | **UNKNOWN** |
| applied sync generation pinned/current | **unpinned** (last-known) |
| immutable READY ≥ 1 | **null** |
| AM SLA live evidence | under **STALE** — not PASS |

---

## Human actions (not agent)

1. Bind `CI_LANE_TOKEN` and `GITHUB_STATUS_TOKEN` on `quant-platform-ci-aggregate`. Connect Workers Builds for six lanes. Prove a **failing** SHA is unmergeable and a **passing** six-receipt SHA posts `ci-aggregate` success. Isolation worktree does **not** do that.
2. Bind `GATEWAY_TOKEN` / `MASS_EVAL_TOKEN` / `QUANT_READINESS_HMAC_SECRET` on the intended env. Do not commit values.
3. Apply `0007_ops_applied_pins` to remote D1 only when the operator is ready to pin. Until then CURRENT stays impossible.
4. Refresh the ops projection so MCP is FRESH with `refresh_success=true`. Tree honesty (`2f0024d`) is not a publish.
5. Dated reconstitution brief for `basket_theme_fund` / `basket_event_fund` only. Do not flip `RECONSTITUTION_APPLY`.
6. Isolation worktree does **not** push. PR #1 stays **BLOCKED** until `ci-aggregate` actually posts.

---

## What this file is not

- A rewrite of [`P632_brief_leaks.md`](P632_brief_leaks.md).
- A live Coverage remeasure. Planner wires are git; MCP is **STALE**.
- Dataset COMPLETE 23, OTC COMPLETE, B0 PASS, READY, or Phase 7 GO.
- Proof that `verify_ci.sh` is green at `07b4435`.

Wave-2 P0 **code** closed. Phase 6.3.2 remains **NOT COMPLETE**. Phase 6.4 remains **NOT COMPLETE**. Controlled Pilot remains **NO-GO**.
