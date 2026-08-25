# Phase 6.3.2 Wave-4 status — leak register vs `40d1aa90` (not a GO)

**Isolation worktree:** `docs/p632-wave4-status` (do not push).  
**Does not clobber:** [`P632_brief_leaks.md`](P632_brief_leaks.md) (A–S freeze vs `3ab87d0`), [`P632_wave2_status.md`](P632_wave2_status.md) (A–S freeze vs `07b4435`), or [`P632_wave3_status.md`](P632_wave3_status.md) (A–S freeze vs `f224e7e`). Those files stay earlier freezes.  
**Feature branch:** `grok/phase63-ci-source-closure`  
**This HEAD (reviewed):** `40d1aa90` (`40d1aa9009ca1e7a6bd9fdc2df4d4da4cf92eab4`) — `coverage: OTC refresh required set from official index not inventory`.  
**Window:** 20 commits after `f224e7e` (`f224e7e922d93dfdcc14ae86578883cad337ebca`). Count: `git rev-list --count f224e7e..40d1aa90` = **20**.  
**`origin/main`:** `b5c326a` (feature branch is **not** an ancestor of `main`; not merged).  
**Named review SHA in brief:** `b5c326a` — **not** a freeze.  
**PR:** https://github.com/ddnne/quant-platform/pull/1 — `MERGEABLE` / mergeState **`BLOCKED`** (required `ci-aggregate` has not posted). Head OID this turn: `40d1aa90`.

Earlier freezes (cite, do not rewrite):

| Freeze | SHA | File |
|--------|-----|------|
| Wave-0 live remeasure | `61b773a` | [`P632_wave0_live.md`](P632_wave0_live.md) |
| Wave-1 A–S register | `3ab87d0` | [`P632_brief_leaks.md`](P632_brief_leaks.md) |
| Wave-2 after P0 code closes | `07b4435` | [`P632_wave2_status.md`](P632_wave2_status.md) |
| Wave-3 after 30 commits | `f224e7e` | [`P632_wave3_status.md`](P632_wave3_status.md) |
| Wave-4 (this file) | `40d1aa90` | this re-diff |

Status vocabulary: **OPEN / FIXED / DEFERRED / HOLD / HUMAN / PARTIAL**.  
Do not invent Coverage COMPLETE, Projection FRESH, B0 PASS, READY, Phase 6.3.2 COMPLETE, Phase 6.4 COMPLETE, or Phase 7 GO.

---

## Live MCP (this wave; tools available)

quant_mcp tools **worked** this isolation turn. Values below are this-turn reads, not last-known docs. Isolation does not refresh the ledger. No GitHub check-runs MCP existed; live GitHub below is `gh api`, same as wave-3.

```text
Projection: STALE
  generated_at: 2026-08-21T12:30:49.152421+00:00
  age_seconds: 182422 (~50.7h)
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
  equities_master PARTIAL history_target_start 2006-08-13
    backfill 241 / 220 / 21  observed 2008-05-01 → 2026-08-12
  equities_bars_daily_am PARTIAL history_target_start 2024-01-04
    backfill 32 / 1 / 31  observed 2026-08-01 → 2026-08-11
  equities_earnings_calendar PARTIAL history_target_start 2010-01-04
    backfill 200 / 1 / 199  observed 2010-01-04 → 2026-08-14
  jsda_otc_bond_reference_prices PARTIAL history_target_start 2002-08-02
    backfill 8784 / 5886 / 2898  observed 2002-08-06 → 2026-08-20

Inventory: 26 governed / 5 experimental / 31
Ops last_run: id 14317 PASS (jquants, 2026-08-23T23:15:01+09:00)
Raw: manifests 20470 / complete 18255
AM SLA current_state: PROJECTION_STALE (state_reason: ops_projection_stale)
storage_plane_status.p0_claims.mass_research: NO-GO
storage_plane_status.p0_claims.ready: null
```

Live GitHub (this turn; `gh api`, not invented):

```text
commits/40d1aa90/check-runs  total_count: 0
commits/40d1aa90/status      state: pending, total_count: 0
PR #1                       statusCheckRollup: null, mergeState BLOCKED
                            headRefOid: 40d1aa9009ca1e7a6bd9fdc2df4d4da4cf92eab4
Actions workflows           total_count: 0
main protection             required_status_checks.contexts=["ci-aggregate"]
                            app_id: null, strict: true, enforce_admins: true
                            allow_force_pushes: false
origin/main check-runs      total_count: 0
.git/ ls-files .github      0
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

Wave-4 **tree** honesty (JSDA refresh from official index, Python R2 overlay fail-closed, IR `ALLOWED_FIELDS` generated, `verify_ci` types flags, READY fixture tip receipts) is not a GO. Brief §8 `Pilot_GO` is a conjunction; live legs still fail: Projection **STALE**, `refresh_success=false`, B0 **UNKNOWN**, READY **null**, `applied_feed_cursor=null`, required GitHub `ci-aggregate` **not posted** (`check-runs total_count: 0`), Coverage still V2 **22 / 4 PARTIAL**, independent P0 unresolved ≠ 0 (live merge gate).

---

## Named landings this wave (tree, not live GO)

| SHA | Landing | Closes (tree) | Does **not** close |
|-----|---------|---------------|-------------------|
| `40d1aa90` | OTC `refresh_coverage_ledger` required set from official index, not calendar inventory | IND-A-JSDA-PHANTOM **refresh wire**. Missing `index_text` → empty fail-closed, not 8784 weekends. PARSE_ZERO days stay PARTIAL. | live MCP still **8784 / 5886** under STALE V2. No invented COMPLETE. |
| `b65fa1d6` | remote Python R2 put fail-closed unless `QP_ALLOW_PYTHON_R2_PUT=1` | Python CLI overlay **default off**. `authoritative=True` still refused. dry_run staging stays allowed. | overlay `=1` is still head-then-put **TOCTOU**. Worker `onlyIf` remains immutable authority. |
| `d8821197` | Worker `ALLOWED_FIELDS` emitted from `schema.json` | generated `evaluation_ir_allowed_fields.generated.ts`; `verify_ci` freeze-checks it | hand-written `evaluation_ir.ts` codec **OPEN**. Not generated Python+TS types. |
| `cb14d67b` | `verify_ci` types `--check` honors `scripts.types` (`npm run types -- --check`) | bare `npx wrangler types --check` no longer regenerates workerd runtime types | merge gate is still live GitHub `ci-aggregate`, not a green `verify_ci` |
| `8d92e053` | regenerate ingestion-jsda wrangler types (`--include-runtime false`) | committed Env-only `d.ts` matches wrangler 4.125.0 | not a merge-gate receipt |
| `28160c3f` | READY fixture collects tip-snapshot receipts, not empty COMPLETE | publication helper no longer plants event-zero COMPLETE on earnings calendar | live READY **null**. Genuine `event_driven` event-zero COMPLETE residual remains. |

Local code-lane PASS at `f113cc05` ([`P632_verify_ci_f224e7e.md`](P632_verify_ci_f224e7e.md): 1412 passed / 4 skipped) is the same three commits (`28160c3f` / `8d92e053` / `cb14d67b`) now on this branch. This isolation did **not** re-run `verify_ci.sh` at `40d1aa90`. That local exit-0 is **not** merge-gate.

---

## The 20 commits after `f224e7e`

| SHA | Landing | Lane |
|-----|---------|------|
| `0cc17bb3` | scripts README names `verify_ci` as mandatory local CI | docs (C) |
| `519edb89` | `yaml_*` helper names are aliases; compiled catalog is SoT | N |
| `49a2f299` | BackfillPlanner tip-snapshot wire is DONE at `f224e7e` | docs (Q / F / G) |
| `7aa9ed12` | review index names HEAD `f224e7e` vs `origin/main` `b5c326a` | docs |
| `f2816dc9` | leftover occupancy echo greps stay dropped; `combo_gates` is SoT | N / P |
| `e73c933d` | independent review B revisit at `f224e7e` | docs (B freeze) |
| `da400b8f` | wave-3 status after 30 commits vs `f224e7e` | docs (wave-3 freeze) |
| `49b802f9` | independent review C catalog/pilot revisit at `f224e7e` | docs (C freeze) |
| `b65fa1d6` | remote python R2 put fail-closed without `QP_ALLOW_PYTHON_R2_PUT` | M |
| `d65236d4` | `jquants_records` master uses official `2008-05-07` island | E / A-PIT |
| `e7e297da` | ops-mcp treats raw ACQUIRED as captured, not Coverage COMPLETE | J / FALSE-COMPLETE |
| `d8821197` | emit Evaluation IR `ALLOWED_FIELDS` from `schema.json` | O / C |
| `3d3e68ab` | data_access reports stored `policy_version` not frozen V2 | J / Q |
| `0e4157e8` | independent review A revisit at `f224e7e` | docs (A freeze) |
| `552dfbc2` | pin live projection `refresh_success=false` write path | docs (J) |
| `28160c3f` | READY fixture collects tip-snapshot receipts, not empty COMPLETE | I / F / FALSE-COMPLETE |
| `8d92e053` | regenerate ingestion-jsda wrangler types | B / C |
| `cb14d67b` | `verify_ci` types `--check` honors `scripts.types` flags | B / C |
| `75ebf99f` | P632 `verify_ci` code-lane PASS at `f113cc05` vs `f224e7e` | docs (C; not merge-gate) |
| `40d1aa90` | OTC refresh required set from official index not inventory | H / IND-A-JSDA-PHANTOM |

Docs commits in this window (`0cc17bb3`, `49a2f299`, `7aa9ed12`, `e73c933d`, `da400b8f`, `49b802f9`, `0e4157e8`, `552dfbc2`, `75ebf99f`) are freezes, not live GO.

---

## A–S vs `40d1aa90` (after the 20)

Prior registers: [`P632_brief_leaks.md`](P632_brief_leaks.md) vs `3ab87d0`; [`P632_wave2_status.md`](P632_wave2_status.md) vs `07b4435`; [`P632_wave3_status.md`](P632_wave3_status.md) vs `f224e7e`. This table is the wave-4 re-diff, not a rewrite of those files.

### A. Cloudflare mandatory CI

**status: PARTIAL** (protection + Worker + `CI_LANE_TOKEN` + 7-worker `verify_ci` + types flags in repo) / **OPEN** (live check never posted) / **HUMAN** (`CI_LANE_TOKEN` + `GITHUB_STATUS_TOKEN` bind)

| Sub-item | At `f224e7e` | After wave-4 |
|----------|--------------|--------------|
| `.github/` workflows | **FIXED** (absent) | **FIXED** — `git ls-files .github` empty; Actions `total_count: 0`. Do not add. |
| Aggregate Worker | **FIXED** (code + inbound token) | **FIXED** (code). Live Worker bind still **HUMAN**. |
| `verify_ci` covers gate Worker | **FIXED** (7th Worker + types `--check` + IR schema) | **FIXED** + types honors `scripts.types` (`cb14d67b`) + generated `ALLOWED_FIELDS` freeze (`d8821197`) |
| Branch protection on `main` | **FIXED** (requires `ci-aggregate`) | **FIXED** (setting). `app_id: null`. Not a passing receipt. |
| GitHub check-runs / statuses at HEAD | **OPEN** (`total_count: 0`) | **OPEN** — this turn `40d1aa90` `total_count: 0`; `/status` `pending` / `0`. PR #1 `statusCheckRollup: null`, **BLOCKED**. |
| Fail/pass merge smoke | **OPEN** | **OPEN** |
| Token bind | **HUMAN** | **HUMAN** — agent must not mint |
| Workers Builds Git integration | **OPEN** | **OPEN** |
| Explicit promote vs auto-deploy | **HOLD** | **HOLD** |

### B. All six Workers reproducible build

**status: PARTIAL** (lockfiles; seven `npm run types -- --check`) / **OPEN** (clean-checkout proof at this HEAD; retry jitter still `Math.random`)

Seven first-party Workers each have `package-lock.json` and `scripts.types` with `wrangler types --include-runtime false`. `verify_ci.sh` runs `npm run types -- --check` so those flags are honored (`cb14d67b`). `--legacy-peer-deps` remains banned.

Identity run ids: **FIXED** `crypto.randomUUID` (unchanged). Residual `Math.random()` is retry/jitter only (`ingestion-premium` `index.ts:171,181`, `persist_records.ts:36`) — not identity.

Clean-checkout matrix **not** executed at `40d1aa90` in this isolation. Local PASS at `f113cc05` is documented, not this SHA. Do not invent PASS at `40d1aa90`.

### C. Authoritative CI script

**status: PARTIAL** (`verify_ci.sh` fail-closed, 7 workers, IR schema, generated `ALLOWED_FIELDS`, types flags) / **OPEN** (merge gate is live GitHub context)

- Authoritative: `scripts/verify_ci.sh`. Missing lockfile/dir/script fails. No skip of missing `node_modules`. No `--legacy-peer-deps`. Includes `platform/workers/ci-aggregate`. Golden + schema + generated `evaluation_ir_allowed_fields.generated.ts` freeze-checked (`d8821197`). Hand-written `evaluation_ir.ts` stays a **presence** check in that gate.
- Fast helper remains `scripts/verify_all.sh` (three research workers; optional `VERIFY_*`). Still **not** mandatory CI. Do not merge the two (HOLD split).
- Residual: does **not** create a fresh venv (requires existing `.venv` 3.11+). Script not proven green at this HEAD in this isolation. Live merge authority is still “six lane receipts POSTed with `CI_LANE_TOKEN` → GitHub `ci-aggregate`”, not “`verify_ci.sh` exited 0”.

### D. SourceCapabilityContract V3

**status: PARTIAL** (typed loader + **4** dataset files + SoT clip + missing-file fail-closed) / **OPEN** (22 governed datasets have no V3 file; nested maps open)

On-disk: `specs/source_capability/{equities_master,equities_earnings_calendar,equities_bars_daily_am,jsda_otc_bond_reference_prices}.json`. Nested evidence maps remain **OPEN** by design (`source_capability.py:16`). Empty dir is valid; missing dataset rows load `None` and are **not** COMPLETE.

Planner **does** clip through SourceCapability SoT. That is a wire, not Dataset COMPLETE 23. Live MCP is STALE and still advertises V2 floors.

### E. Equities Master contract

**status: PARTIAL** (V3 + planner + core profile + PIT clamp + `jquants_records` island in repo) / **OPEN** (live STALE still V2 `2006-08-13`)

Repo: official start `2008-05-07`. `FeatureContext.get_jquants_records(dataset="equities_master")` shares the official-island path (`d65236d4`): `as_of` before that start is empty; on/after is PIT. Remaining PARTIAL stays PD-D2-MASTER — not Dataset COMPLETE.

Live MCP: last-known **PARTIAL** under STALE V2 `2006-08-13` (`backfill_status` 241 / 220 / 21). Official-domain correction in git ≠ live required-set migration. Do not invent Dataset COMPLETE.

### F. Earnings Calendar contract

**status: PARTIAL** (V3 + tip-snapshot planner + empty receipt PARTIAL + READY fixture honesty) / **OPEN** (live still 200 monthly V2 PARTIAL under STALE)

Planner yields **1** cutoff snapshot, not 200 months. Empty trusted SUCCESS receipt is **PARTIAL**. READY publication helper now plants tip-snapshot receipts, not event-zero COMPLETE (`28160c3f`). Live gap row is STALE last-known (`backfill_status` 200 / 1 / 199). Do not empty past months into COMPLETE.

### G. AM bars contract

**status: PARTIAL** (V3 + same-day snapshot planner + empty receipt PARTIAL) / **OPEN** (live still monthly V2 PARTIAL; SLA under STALE)

Planner yields **1** cutoff snapshot, not 32 months. Same empty-receipt and tip path as F. `collection_sla_status(equities_bars_daily_am)` this turn: `current_state: PROJECTION_STALE` / `state_reason: ops_projection_stale`. Live `backfill_status` 32 / 1 / 31. Do not invent AM SLA PASS.

### H. JSDA OTC official-index Coverage

**status: PARTIAL** (V3 file + planner + HTML index SoT + **refresh wire**) / **OPEN** (live STALE calendar inventory; PARSE_ZERO not sealed)

`refresh_coverage_ledger` for official-archive-index uses `plan_required_segments` / `index_text` (`40d1aa90`). Calendar inventory is **not** replayed. Tests pin: weekend COMPLETE rows drop out of the required set; missing/blank `index_text` → **empty** required set (fail-closed, `required_segments == 0`), **not** 8784; PARSE_ZERO index days stay **PARTIAL**.

Live MCP still last-known Wave-0 **5886 / 8784** under `history_target_start: 2002-08-02`. Tree refresh ≠ live ledger migration. Do not COMPLETE empty non-index days. Do not hide PARSE_ZERO by moving `history_target_start`.

### I. ResearchDataProfile / READY

**status: PARTIAL** (v1 predicate + core requires master + string COMPLETE rejected + missing V3 false + mixed policy honesty + fixture tip receipts) / **OPEN** (live READY **null**)

`CORE_REQUIRED_DATASETS` includes `equities_master`. `profile_ready()` still does **not** publish. READY fixture no longer treats tip-snapshot earnings as event-zero COMPLETE (`28160c3f`) — test honesty, not a bound generation.

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

Python data_access / MCP now echo stored `dataset_coverage.policy_version` rather than frozen “Coverage V2” words (`3d3e68ab`; Worker path already `27ff7e6`). Ops-mcp maps raw `ACQUIRED` to captured, not dataset Coverage COMPLETE (`e7e297da`). Tree honesty is not a publish. See [`P632_projection_stale.md`](P632_projection_stale.md) and [`P632_projection_refresh_false.md`](P632_projection_refresh_false.md).

### K. Edge Durable Object hard budget

**status: PARTIAL** (DO reserve/reconcile in repo) / **OPEN** (live Edge unproven)

Unchanged vs `f224e7e`. Caps unchanged. String `budget_id` is still not the reserve. Live occupancy / double-spend under production traffic: **not** measured this wave.

### L. Worker public boundary

**status: PARTIAL** (preview vs production split) / **OPEN** (shared bearer still required on remaining surfaces) / **HOLD** (`workers_dev` kept where documented) / **HUMAN** (secret bind)

Unchanged vs wave-3: production `workers_dev=false` on research-ai-gateway, research-mass-eval, ingestion-jsda, ingestion-premium. **Kept true:** quant-ops-mcp (OAuth callback), ingestion-secrets (token-gated local), ci-aggregate (receipt POST host). Treat **kept** as **HOLD**. Dual `GATEWAY_TOKEN` / service-binding residual: **OPEN**. Ops MCP must not grow SQL / fetch / ingest / delete / READY publish. Not re-opened.

### M. Immutable artifact authority

**status: PARTIAL** (Worker child digest 409 + Python overlay fail-closed) / **OPEN** (TOCTOU remains if overlay `=1`) / **HOLD** (overlay identity)

Worker children-then-manifest `onlyIf` remains immutable authority. Python `default_r2_put` is not artifact authority; `authoritative=True` refused. Remote (non `dry_run`) put now fail-closes unless `QP_ALLOW_PYTHON_R2_PUT=1` (`b65fa1d6`; same overlay shape as YAML). Overlay `=1` is still head-then-put TOCTOU. Do not treat “TOCTOU recorded” or “overlay off” as Worker-equivalent create-if-absent.

### N. Active Catalog / Legacy Identity Registry

**status: PARTIAL** (v2 classification + YAML overlay fail-closed + digest identity + `yaml_*` aliases) / **OPEN** (compact source; `migration.jsonl` still load SoT) / **HOLD** (+N / unique22 / freeze n)

YAML n at HEAD = **0**. Compiled freeze n = **2254**. `yaml_*` helper names are aliases; compiled catalog is SoT (`519edb89`). Leftover occupancy echo greps stay dropped; `combo_gates.ts` remains Worker gate SoT (`f2816dc9`). Overlay without `QP_ALLOW_YAML_OVERLAY=1` still fail-closes. Compact `family + template + parameter matrix` **not** implemented.

Do not report 2254/2092 as a product win. Combo +N **HOLD**. unique22 leftover occupancy **HOLD**.

### O. Evaluation IR single generated authority

**status: PARTIAL** (JSON Schema codec SoT; `verify_ci` validates golden + generated `ALLOWED_FIELDS`) / **OPEN** (hand-written TS codec remains)

`ALLOWED_FIELDS` is generated from `schema.json` properties into `evaluation_ir_allowed_fields.generated.ts` (`d8821197`). `verify_ci.sh` freeze-checks that file. Worker `evaluation_ir.ts` is still a hand-written TS codec (decode uses the generated set; does not load a JSON Schema engine). Brief asked generated Python+TS types. **Not** done.

### P. Test audit / reduction

**status: OPEN** (inventory not closed) / **PARTIAL** (Lane 17 audit + `07b4435` collect freeze + digest identity + READY fixture honesty)

See [`P632_test_inventory.md`](P632_test_inventory.md) and [`P632_test_inventory_now.md`](P632_test_inventory_now.md) (collected **1379** at `07b4435`; that file does not invent `tests_after`). Local `verify_ci` at `f113cc05` reported **1412 passed, 4 skipped** — a different SHA, not this isolation, not `tests_after`. This wave did **not** re-run `pytest --collect-only`. Do not invent `tests_after`.

### Q. Whole-repo refactor (authority split)

**status: PARTIAL** / **OPEN** / **HOLD** (named live-math files)

§10 remaining-extracts freeze is still authored vs `07b4435` / `f224e7e` ([`docs/phase63_refactor_plan.md`](../phase63_refactor_plan.md)). Wave-4 landings vs that freeze:

| §10.3 later | At `f224e7e` | After wave-4 |
|-------------|--------------|--------------|
| 1 BackfillPlanner vs `plan_required_segments` | PARTIAL (tip snapshots wired) | **PARTIAL** — unchanged; non-tip still month-chunks |
| 2 Python `r2_io.py` TOCTOU | OPEN | **PARTIAL** — overlay fail-closed (`b65fa1d6`); TOCTOU remains if `QP_ALLOW_PYTHON_R2_PUT=1` |
| 3 hand-written `evaluation_ir.ts` | OPEN (schema lock / verify_ci PARTIAL) | **PARTIAL** — `ALLOWED_FIELDS` generated; codec still hand-written |
| 4 MCP frozen “Coverage V2” strings | FIXED (Worker echo stored `policy_version`) | **FIXED** + Python data_access echo (`3d3e68ab`) |
| 5 `verify_all` vs `verify_ci` | HOLD (keep both) | **HOLD** (`verify_ci` grew types flags + generated fields freeze) |

leftover occupancy / `cost_models.py` / generated `catalog_ids.ts` **HOLD**. Coverage V2 JSON vs V3 contracts: planner + OTC refresh wired for 4 datasets; live MCP still V2 STALE.

### R. Basket reconstitution evidence

**status: HUMAN** (apply false) / evidence pack **FIXED** (detect-only)

`RECONSTITUTION_APPLY = False`. Agent must not flip apply.

### S. Controlled Pilot

**status: FIXED** (OFF) — GO conditions **OPEN** / unmet

Worker: `MASS_RESEARCH = "NO-GO"`, `PHASE7 = "OFF"`, `READY_DECLARED = "false"` (`research-mass-eval/wrangler.toml`). Python deny-by-default, `go: False`. **Do not** run the one-shot paper loop. Mass remains **NO-GO**. Auto promotion **OFF**. Live broker **OFF**.

---

## Independent P0 scoreboard (tree vs live)

| ID | At `f224e7e` (wave-3) | After wave-4 (`40d1aa90`) |
|----|------------------------|---------------------------|
| IND-A-DOMAIN | **FIXED** (planner). Live STALE ≠ COMPLETE 23. | **FIXED**. `jquants_records` master island (`d65236d4`). Live STALE still V2 `2006-08-13`. |
| IND-A-JSDA-PHANTOM | **FIXED** (planner) / Independent A named refresh inventory replay **OPEN** | **FIXED** (tree: refresh wire `40d1aa90`). Live inventory STALE **8784 / 5886**. PARSE_ZERO stays gap. |
| IND-A-PIT-BYPASS | **FIXED** (tree) | **FIXED** (not reopened). `jquants_records` island shares the same PIT path. |
| IND-A-FORGED-RECEIPT | **FIXED** | **FIXED** (not reopened) |
| IND-A-FALSE-COMPLETE | **PARTIAL** — string COMPLETE / tip empty / raw / missing V3 **FIXED**; event-zero COMPLETE remains | **PARTIAL** — READY fixture tip receipts **FIXED** (`28160c3f`); ops-mcp ACQUIRED ≠ Coverage COMPLETE (`e7e297da`). Genuine `event_driven` event-zero COMPLETE **remains** (`test_event_zero_successful_exhausted_raw_receipt_is_complete`). |
| IND-A-READY-DEPS | **FIXED**. READY still **null**. | **FIXED**. Fixture honesty is not a bound READY. Live **null**. |
| P632B-01 `verify_all` vs `verify_ci` | **PARTIAL** (script 7 + types `--check` + IR schema; live gate not `verify_ci`) | **PARTIAL** — types flags + generated `ALLOWED_FIELDS`; live merge gate is still GitHub `ci-aggregate` never posted |
| P632B-02 live `ci-aggregate` posted | **OPEN** | **OPEN** (`check-runs total_count: 0`, `app_id: null`) |
| P632B-05 Python R2 TOCTOU | **OPEN** (Python writer) | **PARTIAL** — overlay fail-closed; **OPEN** if `QP_ALLOW_PYTHON_R2_PUT=1` |
| C-YAML load overlay | **FIXED**. +N **HOLD**. | **FIXED**. `yaml_*` aliases (`519edb89`). +N **HOLD**. |

Independent P0 unresolved ≠ 0 (live CI never posted; event-zero residual). `Pilot_GO.IndependentReview_P0_Zero` stays **OPEN**. Tree JSDA refresh close is not a live Coverage COMPLETE.

---

## Brief §8 `Pilot_GO` (current tree + live MCP)

| Criterion | Status |
|-----------|--------|
| Mandatory_CF_CI | **OPEN** — Worker+token+protection PARTIAL; live check-runs **0** |
| Main_Protected | **FIXED** (setting requires `ci-aggregate`) |
| Six_Workers_Clean | lockfiles **FIXED**; `verify_ci` 7 workers + types flags **FIXED** (script); clean-checkout matrix at this HEAD **OPEN** |
| SourceCapabilityContract_V3 | **PARTIAL** — 4/26 files; nested maps OPEN; missing file fail-closed |
| RequiredDomain_Subset_OfficialDomain | **PARTIAL** — planner + OTC refresh wired (master / AM / earnings / OTC); live MCP still V2 STALE |
| ResearchDataProfile_Complete | **PARTIAL** — core includes master; string COMPLETE rejected; fixture tip receipts; READY **null** |
| Projection_FRESH | **NO** — **STALE** |
| Refresh_SUCCESS | **NO** — `false` |
| B0_PASS | **NO** — **UNKNOWN** |
| READY_Profile_Exists | **NO** — **null** |
| AppliedCursor_Pinned | **NO** — **null** |
| EdgeBudget_Hard | **PARTIAL** (code) / live **OPEN** |
| Artifact_Coherent | Worker digest 409 **FIXED**; Python overlay fail-closed **PARTIAL**; TOCTOU if overlay **OPEN** |
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
4. Refresh the ops projection so MCP is FRESH with `refresh_success=true`. Tree honesty (including JSDA index refresh) is not a publish. Live still **8784 / 5886**.
5. Dated reconstitution brief for `basket_theme_fund` / `basket_event_fund` only. Do not flip `RECONSTITUTION_APPLY`.
6. Isolation worktree does **not** push. Do **not** push `main`. PR #1 stays **BLOCKED** until `ci-aggregate` actually posts.

---

## What this file is not

- A rewrite of [`P632_brief_leaks.md`](P632_brief_leaks.md), [`P632_wave2_status.md`](P632_wave2_status.md), or [`P632_wave3_status.md`](P632_wave3_status.md).
- A live Coverage remeasure. Planner and refresh wires are git; MCP is **STALE**.
- Dataset COMPLETE 23, OTC COMPLETE, B0 PASS, READY, Phase 6.3.2 COMPLETE, Phase 6.4 COMPLETE, or Phase 7 GO.
- Proof that `verify_ci.sh` is green at `40d1aa90`. Local PASS at `f113cc05` is not this SHA and is not merge-gate.

Wave-4 **tree** honesty landed. Phase 6.3.2 remains **NOT COMPLETE**. Phase 6.4 remains **NOT COMPLETE**. Controlled Pilot remains **NO-GO**.
