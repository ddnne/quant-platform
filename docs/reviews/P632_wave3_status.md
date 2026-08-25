# Phase 6.3.2 Wave-3 status — leak register vs `f224e7e` (not a GO)

**Isolation worktree:** `docs/p632-wave3-status` (do not push).  
**Does not clobber:** [`P632_brief_leaks.md`](P632_brief_leaks.md) (A–S freeze vs `3ab87d0`) or [`P632_wave2_status.md`](P632_wave2_status.md) (A–S freeze vs `07b4435`). Those files stay earlier freezes.  
**Feature branch:** `grok/phase63-ci-source-closure`  
**This HEAD (reviewed):** `f224e7e` (`f224e7e922d93dfdcc14ae86578883cad337ebca`) — `contracts: missing SourceCapability V3 is fail-closed not COMPLETE`.  
**Window:** 30 commits after `07b4435` (`07b44355dc745b1a9b7f7c3c4eccbe123e7a171b`). Count: `git rev-list --count 07b4435..f224e7e` = **30**.  
**`origin/main`:** `b5c326a` (feature branch is **not** an ancestor of `main`; not merged).  
**Named review SHA in brief:** `b5c326a` — **not** a freeze.  
**PR:** https://github.com/ddnne/quant-platform/pull/1 — `MERGEABLE` / mergeState **`BLOCKED`** (required `ci-aggregate` has not posted).

Earlier freezes (cite, do not rewrite):

| Freeze | SHA | File |
|--------|-----|------|
| Wave-0 live remeasure | `61b773a` | [`P632_wave0_live.md`](P632_wave0_live.md) |
| Wave-1 A–S register | `3ab87d0` | [`P632_brief_leaks.md`](P632_brief_leaks.md) |
| Wave-2 after P0 code closes | `07b4435` | [`P632_wave2_status.md`](P632_wave2_status.md) |
| Wave-3 (this file) | `f224e7e` | this re-diff |

Status vocabulary: **OPEN / FIXED / DEFERRED / HOLD / HUMAN / PARTIAL**.  
Do not invent Coverage COMPLETE, Projection FRESH, B0 PASS, READY, Phase 6.3.2 COMPLETE, Phase 6.4 COMPLETE, or Phase 7 GO.

---

## Live MCP (this wave; tools available)

quant_mcp tools **worked** this isolation turn. Values below are this-turn reads, not last-known docs. Isolation does not refresh the ledger.

```text
Projection: STALE
  generated_at: 2026-08-21T12:30:49.152421+00:00
  age_seconds: 181074 (~50.3h)
  active_generation: projgen-ef18b4f86ee946048161d25e2a30a2a8
  projection_source_generation: 2026-08-21T12:28:33.345482+00:00
  refresh_attempt: true
  refresh_success: false
  last_known_good.not_fresh: true

B0: UNKNOWN  (snapshot quality/B0 projection is unavailable)

READY: null  (no published READY generation is bound to this Worker)

Sync: applied_feed_cursor: null
  latest_change_seq: 2890659
  CURRENT datasets: 0
  typical dataset state: LAGGING_APPLY_UNPINNED
  indices_bars_daily_topix: EXPORT_CURRENT_APPLY_UNPINNED (lag 0, pin still null → never CURRENT)

Coverage: 22 COMPLETE / 4 PARTIAL  (policy_version collection-coverage/v2)
  equities_master PARTIAL history_target_start 2006-08-13 (observed 2008-05-01 → 2026-08-12)
  equities_bars_daily_am PARTIAL history_target_start 2024-01-04
  equities_earnings_calendar PARTIAL history_target_start 2010-01-04
  jsda_otc_bond_reference_prices PARTIAL history_target_start 2002-08-02

Inventory: 26 governed (coverage_gaps INCOMPLETE)
Ops last_run: id 14317 PASS (jquants, 2026-08-23T23:15:01+09:00)
Raw: manifests 20470 / complete 18255
AM SLA current_state: PROJECTION_STALE (state_reason: ops_projection_stale)
storage_plane_status.p0_claims.mass_research: NO-GO
storage_plane_status.p0_claims.ready: null
```

Live GitHub (this turn; `gh api`, not invented):

```text
commits/f224e7e/check-runs  total_count: 0
commits/f224e7e/status      state: pending, total_count: 0
PR #1                       statusCheckRollup: [], mergeState BLOCKED
Actions workflows           total_count: 0
main protection             required_status_checks.contexts=["ci-aggregate"]
                            app_id: null, strict: true, enforce_admins: true
                            allow_force_pushes: false
origin/main check-runs      total_count: 0
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

Wave-3 **tree** honesty (missing V3 fail-closed, mixed coverage_policy, IR schema gate, PIT clamp, tip-snapshot empty PARTIAL, catalog digest identity) is not a GO. Brief §8 `Pilot_GO` is a conjunction; live legs still fail: Projection **STALE**, `refresh_success=false`, B0 **UNKNOWN**, READY **null**, `applied_feed_cursor=null`, required GitHub `ci-aggregate` **not posted** (`check-runs total_count: 0`), Coverage still V2 **22 / 4 PARTIAL**, independent P0 unresolved ≠ 0 (live merge gate).

---

## The 30 commits after `07b4435`

| SHA | Landing | Lane |
|-----|---------|------|
| `a9ad3c3` | independent review B revisit after receipt auth | docs (B freeze) |
| `f89930d` | wave-2 status after P0 closes | docs (wave-2 freeze) |
| `6bee72a` | repo sqlite loader is PIT-gated on `as_of` | A-PIT / I |
| `64e1300` | evaluation-ir decode rejects unknown fields via schema lock | O |
| `e22b33f` | equity master PIT clamps to official `2008-05-07` | E / A-PIT |
| `8ae9363` | `fixed_universe` injection cannot skip PIT `as_of` | A-PIT |
| `b23820e` | `profile_ready` rejects string COMPLETE labels | I / FALSE-COMPLETE |
| `207d6c5` | 23-col OTC parse is not Coverage COMPLETE | H |
| `5c9c93a` | tip-snapshot empty receipt is PARTIAL not COMPLETE | F / G / FALSE-COMPLETE |
| `ab1da71` | JSDA official index HTML parser is one SoT | H |
| `05773dd` | AM and earnings fetch params match vendor snapshot contract | F / G |
| `42b0e37` | raw acquisition status is not Coverage COMPLETE | J / FALSE-COMPLETE |
| `27ff7e6` | ops-mcp reports stored `policy_version` not frozen V2 | J / Q |
| `0ca9de2` | premium persist run ids use `crypto.randomUUID` | B |
| `624160e` | 6.3.2 P test inventory at `07b4435` | P (docs freeze) |
| `50c2281` | banner remaining-audit freeze vs HEAD `07b4435` | Q (docs) |
| `49991c0` | retain vendor coverage annotations without rewriting history start | D |
| `025395f` | SourceCapability SoT clips `plan_required_segments` | D |
| `697fb1a` | raw retention completeness allows ACQUIRED | J |
| `7ea2ac7` | add `p632-remaining-close` dense workflow | chore |
| `154472f` | equity master PIT path from official `2008-05-07` | E / A-PIT |
| `792ae2b` | BackfillPlanner does not month-chunk tip snapshots | Q / F / G |
| `44c7279` | catalog freeze is compiler digest plus one identity | N / P |
| `24b81f5` | `wrangler types --check` for all seven workers | B / C |
| `5af28dc` | independent review C catalog/pilot revisit at `07b4435` | docs (C freeze) |
| `8775426` | remaining extracts vs HOLD at `07b4435` | Q (docs freeze) |
| `d6f7868` | `available_at_for` consults official start; ingest-time stays fail-safe | D / E / A-PIT |
| `9e7d1b6` | `verify_ci` validates Evaluation IR against `schema.json` | C / O |
| `04af1ed` | core `coverage_policy` is mixed v2/v3, not live-ready | I |
| `f224e7e` | missing SourceCapability V3 is fail-closed not COMPLETE | D / I |

Docs commits in this window (`a9ad3c3`, `f89930d`, `624160e`, `50c2281`, `5af28dc`, `8775426`) are freezes, not live GO. `7ea2ac7` is a workflow pack, not a gate close.

---

## A–S vs `f224e7e` (after the 30)

Prior registers: [`P632_brief_leaks.md`](P632_brief_leaks.md) vs `3ab87d0`; [`P632_wave2_status.md`](P632_wave2_status.md) vs `07b4435`. This table is the wave-3 re-diff, not a rewrite of those files.

### A. Cloudflare mandatory CI

**status: PARTIAL** (protection + Worker + `CI_LANE_TOKEN` + 7-worker `verify_ci` in repo) / **OPEN** (live check never posted) / **HUMAN** (`CI_LANE_TOKEN` + `GITHUB_STATUS_TOKEN` bind)

| Sub-item | At `07b4435` | After wave-3 |
|----------|--------------|--------------|
| `.github/` workflows | **FIXED** (absent) | **FIXED** — `ls .github` none; Actions `total_count: 0`. Do not add. |
| Aggregate Worker | **FIXED** (code + inbound token) | **FIXED** (code). Live Worker bind still **HUMAN**. |
| `verify_ci` covers gate Worker | **FIXED** (7th Worker) | **FIXED** + `wrangler types --check` on all seven (`24b81f5`) + IR schema validate (`9e7d1b6`) |
| Branch protection on `main` | **FIXED** (requires `ci-aggregate`) | **FIXED** (setting). `app_id: null`. Not a passing receipt. |
| GitHub check-runs / statuses at HEAD | **OPEN** (`total_count: 0`) | **OPEN** — this turn `f224e7e` `total_count: 0`; `/status` `pending` / `0`. PR #1 `statusCheckRollup: []`, **BLOCKED**. |
| Fail/pass merge smoke | **OPEN** | **OPEN** |
| Token bind | **HUMAN** | **HUMAN** — agent must not mint |
| Workers Builds Git integration | **OPEN** | **OPEN** |
| Explicit promote vs auto-deploy | **HOLD** | **HOLD** |

### B. All six Workers reproducible build

**status: PARTIAL** (lockfiles; seven `types --check` scripts) / **OPEN** (clean-checkout proof; retry jitter still `Math.random`)

Seven first-party Workers each have `package-lock.json` and `scripts.types = wrangler types --include-runtime false`. `verify_ci.sh` runs `npx wrangler types --check` for every lane (`24b81f5`). `--legacy-peer-deps` remains banned.

Identity run ids: **FIXED** `crypto.randomUUID` (`0ca9de2`; `ingestion-premium/src/identity.ts`). Residual `Math.random()` is retry/jitter only (`index.ts:171,181`, `persist_records.ts:36`) — not identity.

Clean-checkout `npm ci && npm test && typecheck && wrangler types --check && dry-run` **not** executed at this HEAD in this isolation. Do not invent PASS.

### C. Authoritative CI script

**status: PARTIAL** (`verify_ci.sh` fail-closed, 7 workers, IR schema, types `--check`) / **OPEN** (merge gate is live GitHub context)

- Authoritative: `scripts/verify_ci.sh`. Missing lockfile/dir/script fails. No skip of missing `node_modules`. No `--legacy-peer-deps`. Includes `platform/workers/ci-aggregate`. Golden lines validated against `specs/evaluation_ir/schema.json` (`9e7d1b6`). Hand-written `evaluation_ir.ts` stays a **presence** check in that gate.
- Fast helper remains `scripts/verify_all.sh` (three research workers; optional `VERIFY_*`). Still **not** mandatory CI. Do not merge the two (HOLD split).
- Residual: does **not** create a fresh venv (requires existing `.venv` 3.11+). Script not proven green at this HEAD. Live merge authority is still “six lane receipts POSTed with `CI_LANE_TOKEN` → GitHub `ci-aggregate`”, not “`verify_ci.sh` exited 0”.

### D. SourceCapabilityContract V3

**status: PARTIAL** (typed loader + **4** dataset files + SoT clip + missing-file fail-closed) / **OPEN** (22 governed datasets have no V3 file; nested maps open)

On-disk: `specs/source_capability/{equities_master,equities_earnings_calendar,equities_bars_daily_am,jsda_otc_bond_reference_prices}.json`. Nested evidence maps remain **OPEN** by design (`source_capability.py:16`). Empty dir is valid; missing dataset rows load `None` and are **not** COMPLETE (`f224e7e`).

Planner **does** clip through SourceCapability SoT (`025395f` + prior `5796fb0` / `9a63402`). Vendor annotations may be retained without rewriting `history_target_start` (`49991c0`). That is a wire, not Dataset COMPLETE 23. Live MCP is STALE and still advertises V2 floors.

### E. Equities Master contract

**status: PARTIAL** (V3 + planner + core profile + PIT clamp + feature path in repo) / **OPEN** (live STALE still V2 `2006-08-13`)

Repo: official start `2008-05-07`. PIT query clamps (`e22b33f`). `FeatureContext.get_equity_master` reads the official island through PIT; `as_of` before that start is empty / fail-closed (`154472f`). `available_at_for` consults official start and keeps ingest-time fail-safe (`d6f7868`) — not a Date-derived eligibility mint.

Live MCP: last-known **PARTIAL** under STALE V2 `2006-08-13`. Official-domain correction in git ≠ live required-set migration. Do not invent Dataset COMPLETE.

### F. Earnings Calendar contract

**status: PARTIAL** (V3 + tip-snapshot planner + vendor fetch params + empty receipt PARTIAL) / **OPEN** (live still 200 monthly V2 PARTIAL under STALE)

Planner yields **1** cutoff snapshot, not 200 months. Empty trusted SUCCESS receipt is **PARTIAL** (`5c9c93a`). Worker fetch params match vendor snapshot contract (`05773dd`). BackfillPlanner uses `plan_required_segments` for tip snapshots and does **not** month-chunk them (`792ae2b`). Live gap row is STALE last-known. Do not empty past months into COMPLETE.

### G. AM bars contract

**status: PARTIAL** (V3 + same-day snapshot planner + vendor fetch params + empty receipt PARTIAL) / **OPEN** (live still monthly V2 PARTIAL; SLA under STALE)

Planner yields **1** cutoff snapshot, not 32 months. Same empty-receipt and BackfillPlanner tip path as F. `collection_sla_status(equities_bars_daily_am)` this turn: `current_state: PROJECTION_STALE` / `state_reason: ops_projection_stale`. Do not invent AM SLA PASS.

### H. JSDA OTC official-index Coverage

**status: PARTIAL** (V3 file + planner uses official index + one HTML parser SoT) / **OPEN** (live STALE calendar inventory; PARSE_ZERO not sealed)

Official index HTML parser is one SoT (`ab1da71`). Missing `index_text` → **empty** required set (UNKNOWN / fail-closed), **not** an 8784-day calendar walk. 23-col parse is **not** Coverage COMPLETE (`207d6c5`).

Live MCP still last-known Wave-0 **5886 / 8784** under `history_target_start: 2002-08-02`. Do not COMPLETE empty non-index days. Do not hide PARSE_ZERO by moving `history_target_start`.

### I. ResearchDataProfile / READY

**status: PARTIAL** (v1 predicate + core requires master + string COMPLETE rejected + missing V3 false + mixed policy honesty) / **OPEN** (live READY **null**)

`CORE_REQUIRED_DATASETS` includes `equities_master`. `profile_ready()` still does **not** publish. A string COMPLETE label is not official-mode proof (`b23820e`). Missing SourceCapability V3 is not official-complete (`f224e7e`). Core `coverage_policy` stays document-root `collection-coverage/v2` while master/AM/earnings rows may be v3 (`04af1ed`) — mixed, **not live-ready**.

Live `latest_ready_snapshot`: **null**. Digest-bound predicate ≠ a bound READY generation. STALE V2 PARTIAL keeps READY honest-false. That is intended; it is not a GO.

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

MCP now echoes stored `dataset_coverage.policy_version` rather than frozen “Coverage V2” words (`27ff7e6`). Raw acquisition completeness is not Coverage COMPLETE (`42b0e37`); retention enum may be ACQUIRED (`697fb1a`). Tree honesty is not a publish. See [`P632_projection_stale.md`](P632_projection_stale.md).

### K. Edge Durable Object hard budget

**status: PARTIAL** (DO reserve/reconcile in repo) / **OPEN** (live Edge unproven)

Unchanged vs `07b4435`. Caps unchanged. String `budget_id` is still not the reserve. Live occupancy / double-spend under production traffic: **not** measured this wave.

### L. Worker public boundary

**status: PARTIAL** (preview vs production split) / **OPEN** (shared bearer still required on remaining surfaces) / **HOLD** (`workers_dev` kept where documented) / **HUMAN** (secret bind)

Unchanged vs wave-2: production `workers_dev=false` on research-ai-gateway, research-mass-eval, ingestion-jsda, ingestion-premium. **Kept true:** quant-ops-mcp (OAuth callback), ingestion-secrets (token-gated local), ci-aggregate (receipt POST host). Treat **kept** as **HOLD**. Dual `GATEWAY_TOKEN` / service-binding residual: **OPEN**. Ops MCP must not grow SQL / fetch / ingest / delete / READY publish. Not re-opened.

### M. Immutable artifact authority

**status: PARTIAL** (Worker child digest 409) / **OPEN** (Python CLI still TOCTOU writer)

Unchanged vs `3ab87d0` / `07b4435`. `r2_io.py` still `python_cli_put_is_not_immutable_authority`; `authoritative=True` refused. Do not treat “TOCTOU recorded” as done.

### N. Active Catalog / Legacy Identity Registry

**status: PARTIAL** (v2 classification + YAML overlay fail-closed + digest identity) / **OPEN** (compact source; `migration.jsonl` still load SoT) / **HOLD** (+N / unique22 / freeze n)

YAML n at HEAD = **0**. Compiled freeze n = **2254**. Freeze walks collapsed to compiler digest plus one identity (`44c7279`). Overlay without `QP_ALLOW_YAML_OVERLAY=1` still fail-closes. Compact `family + template + parameter matrix` **not** implemented.

Do not report 2254/2092 as a product win. Combo +N **HOLD**. unique22 leftover occupancy **HOLD**.

### O. Evaluation IR single generated authority

**status: PARTIAL** (JSON Schema codec SoT; `verify_ci` validates golden; Worker decode schema-locks unknown fields) / **OPEN** (hand-written dual codecs remain)

Worker `evaluation_ir.ts` is still a hand-written TS codec (`64e1300` pins `ALLOWED_FIELDS` / unknown-key reject; does not load a JSON Schema engine). Brief asked generated Python+TS types. **Not** done. `verify_ci.sh` now fails Python schema/golden drift (`9e7d1b6`); TS stays presence-only in that gate.

### P. Test audit / reduction

**status: OPEN** (inventory not closed) / **PARTIAL** (Lane 17 audit + `07b4435` collect freeze + digest identity)

See [`P632_test_inventory.md`](P632_test_inventory.md) and [`P632_test_inventory_now.md`](P632_test_inventory_now.md) (collected **1379** at `07b4435`; that file does not invent `tests_after`). `44c7279` reduced integer freeze walks to digest + one identity. This wave did **not** re-run `pytest --collect-only`. Do not invent `tests_after`.

### Q. Whole-repo refactor (authority split)

**status: PARTIAL** / **OPEN** / **HOLD** (named live-math files)

§10 remaining-extracts freeze is still authored vs `07b4435` ([`docs/phase63_refactor_plan.md`](../phase63_refactor_plan.md)). Wave-3 landings vs that freeze:

| §10.3 later | At `07b4435` | After wave-3 |
|-------------|--------------|--------------|
| 1 BackfillPlanner vs `plan_required_segments` | OPEN (month-chunk tip) | **PARTIAL** — tip snapshots call `plan_required_segments` (`792ae2b`); non-tip still month-chunks |
| 2 Python `r2_io.py` TOCTOU | OPEN | **OPEN** |
| 3 hand-written `evaluation_ir.ts` | OPEN | **OPEN** (schema lock / verify_ci PARTIAL) |
| 4 MCP frozen “Coverage V2” strings | OPEN | **FIXED** (echo stored `policy_version`) |
| 5 `verify_all` vs `verify_ci` | KEEP both | **HOLD** (keep both; `verify_ci` grew IR schema) |

leftover occupancy / `cost_models.py` / generated `catalog_ids.ts` **HOLD**. Coverage V2 JSON vs V3 contracts: planner wired for 4 datasets; live MCP still V2 STALE.

### R. Basket reconstitution evidence

**status: HUMAN** (apply false) / evidence pack **FIXED** (detect-only)

`RECONSTITUTION_APPLY = False`. Agent must not flip apply.

### S. Controlled Pilot

**status: FIXED** (OFF) — GO conditions **OPEN** / unmet

Worker: `MASS_RESEARCH = "NO-GO"`, `PHASE7 = "OFF"`, `READY_DECLARED = "false"` (`research-mass-eval/wrangler.toml`). Python deny-by-default, `go: False`. **Do not** run the one-shot paper loop. Mass remains **NO-GO**. Auto promotion **OFF**. Live broker **OFF**.

---

## Independent P0 scoreboard (tree vs live)

| ID | At `07b4435` (wave-2) | After wave-3 (`f224e7e`) |
|----|------------------------|--------------------------|
| IND-A-DOMAIN | **FIXED** (planner) | **FIXED** (planner). Live STALE ≠ COMPLETE 23. |
| IND-A-JSDA-PHANTOM | **FIXED** (planner) | **FIXED** (planner) + HTML index SoT (`ab1da71`). Live inventory STALE. PARSE_ZERO stays gap. |
| IND-A-PIT-BYPASS | **OPEN** | **FIXED** (tree: PIT clamp `e22b33f`, sqlite `as_of` `6bee72a`, `fixed_universe` `8ae9363`, feature path `154472f`, official consult `d6f7868`). Ingest-time fail-safe is honesty, not a bypass. Live MCP is not a PIT remeasure. |
| IND-A-FORGED-RECEIPT | **FIXED** | **FIXED** (not reopened) |
| IND-A-FALSE-COMPLETE | **OPEN** (event-zero + string COMPLETE) | **PARTIAL** — string COMPLETE **FIXED** (`b23820e`); tip-snapshot empty **FIXED** PARTIAL (`5c9c93a`); raw acquisition ≠ Coverage COMPLETE (`42b0e37`); missing V3 not COMPLETE (`f224e7e`). Genuine `event_driven` event-zero COMPLETE **remains** (`test_event_zero_successful_exhausted_raw_receipt_is_complete`). |
| IND-A-READY-DEPS | **FIXED** (core includes master) | **FIXED**. READY still **null**. Mixed v2/v3 policy is honesty (`04af1ed`). |
| P632B-01 `verify_all` vs `verify_ci` | **PARTIAL** (script 7; live gate not `verify_ci`) | **PARTIAL** — script 7 + types `--check` + IR schema; live merge gate is still GitHub `ci-aggregate` never posted |
| P632B-02 live `ci-aggregate` posted | **OPEN** | **OPEN** (`check-runs total_count: 0`, `app_id: null`) |
| C-YAML load overlay | **FIXED** | **FIXED**. Digest identity tightened (`44c7279`). +N **HOLD**. |

Independent P0 unresolved ≠ 0 (live CI never posted; event-zero residual). `Pilot_GO.IndependentReview_P0_Zero` stays **OPEN**.

---

## Brief §8 `Pilot_GO` (current tree + live MCP)

| Criterion | Status |
|-----------|--------|
| Mandatory_CF_CI | **OPEN** — Worker+token+protection PARTIAL; live check-runs **0** |
| Main_Protected | **FIXED** (setting requires `ci-aggregate`) |
| Six_Workers_Clean | lockfiles **FIXED**; `verify_ci` 7 workers + types `--check` **FIXED** (script); clean-checkout matrix **OPEN** |
| SourceCapabilityContract_V3 | **PARTIAL** — 4/26 files; nested maps OPEN; missing file fail-closed |
| RequiredDomain_Subset_OfficialDomain | **PARTIAL** — planner wired (master / AM / earnings / OTC); live MCP still V2 STALE |
| ResearchDataProfile_Complete | **PARTIAL** — core includes master; string COMPLETE rejected; READY **null** |
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
| governed Coverage COMPLETE (official mode) | **NO** — 22 held / **4 PARTIAL** last-known under STALE V2 |
| projection FRESH | **STALE** |
| B0 PASS | **UNKNOWN** |
| applied sync generation pinned/current | **unpinned** (`applied_feed_cursor=null`) |
| immutable READY ≥ 1 | **null** |
| AM SLA live evidence | **PROJECTION_STALE** — not PASS |

---

## Human actions (not agent)

1. Bind `CI_LANE_TOKEN` and `GITHUB_STATUS_TOKEN` on `quant-platform-ci-aggregate`. Connect Workers Builds for six lanes. Prove a **failing** SHA is unmergeable and a **passing** six-receipt SHA posts `ci-aggregate` success. Isolation worktree does **not** do that.
2. Bind `GATEWAY_TOKEN` / `MASS_EVAL_TOKEN` / `QUANT_READINESS_HMAC_SECRET` on the intended env. Do not commit values.
3. Apply `0007_ops_applied_pins` to remote D1 only when the operator is ready to pin. Until then CURRENT stays impossible.
4. Refresh the ops projection so MCP is FRESH with `refresh_success=true`. Tree honesty is not a publish.
5. Dated reconstitution brief for `basket_theme_fund` / `basket_event_fund` only. Do not flip `RECONSTITUTION_APPLY`.
6. Isolation worktree does **not** push. Do **not** push `main`. PR #1 stays **BLOCKED** until `ci-aggregate` actually posts.

---

## What this file is not

- A rewrite of [`P632_brief_leaks.md`](P632_brief_leaks.md) or [`P632_wave2_status.md`](P632_wave2_status.md).
- A live Coverage remeasure. Planner wires are git; MCP is **STALE**.
- Dataset COMPLETE 23, OTC COMPLETE, B0 PASS, READY, Phase 6.3.2 COMPLETE, Phase 6.4 COMPLETE, or Phase 7 GO.
- Proof that `verify_ci.sh` is green at `f224e7e`.

Wave-3 **tree** honesty landed. Phase 6.3.2 remains **NOT COMPLETE**. Phase 6.4 remains **NOT COMPLETE**. Controlled Pilot remains **NO-GO**.
