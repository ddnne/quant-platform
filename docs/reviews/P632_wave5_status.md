# Phase 6.3.2 Wave-5 status — leak register vs `67fcbd7c` (not a GO)

**Isolation worktree:** `/private/tmp/qp-p632-wave5-status` on `grok/p632-wave5-status` (do not push `main`).  
**Does not clobber:** [`P632_brief_leaks.md`](P632_brief_leaks.md) (A–S freeze vs `3ab87d0`), [`P632_wave2_status.md`](P632_wave2_status.md) (A–S freeze vs `07b4435`), [`P632_wave3_status.md`](P632_wave3_status.md) (A–S freeze vs `f224e7e`), or [`P632_wave4_status.md`](P632_wave4_status.md) (A–S freeze vs `40d1aa90`). Those files stay earlier freezes.  
**Feature branch:** `grok/phase63-ci-source-closure`  
**This HEAD (reviewed):** `67fcbd7c` (`67fcbd7cd56847a9fc0fba7bcefbd743b43fc106`) — `docs: independent review C catalog/pilot revisit at 40d1aa90`.  
**Window:** 17 commits after `40d1aa90` (`40d1aa9009ca1e7a6bd9fdc2df4d4da4cf92eab4`). Count: `git rev-list --count 40d1aa90..67fcbd7c` = **17**.  
**`origin/main`:** `b5c326a` (feature branch is **not** an ancestor of `main`; not merged).  
**Named review SHA in brief:** `b5c326a` — **not** a freeze.  
**PR:** https://github.com/ddnne/quant-platform/pull/1 — `MERGEABLE` / mergeState **`BLOCKED`** (required `ci-aggregate` has not posted). Head OID this turn: `67fcbd7c`.

**HUMAN bottleneck:** live `quant-platform-ci-aggregate` Worker **absent** (Wrangler deployments/versions **10007**; secrets “not found”; `workers.dev` `/health` HTTP **404** / error **1042**). Isolation does not deploy it.

Earlier freezes (cite, do not rewrite):

| Freeze | SHA | File |
|--------|-----|------|
| Wave-0 live remeasure | `61b773a` | [`P632_wave0_live.md`](P632_wave0_live.md) |
| Wave-1 A–S register | `3ab87d0` | [`P632_brief_leaks.md`](P632_brief_leaks.md) |
| Wave-2 after P0 code closes | `07b4435` | [`P632_wave2_status.md`](P632_wave2_status.md) |
| Wave-3 after 30 commits | `f224e7e` | [`P632_wave3_status.md`](P632_wave3_status.md) |
| Wave-4 after 20 commits | `40d1aa90` | [`P632_wave4_status.md`](P632_wave4_status.md) |
| Wave-5 (this file) | `67fcbd7c` | this re-diff |

Status vocabulary: **OPEN / FIXED / DEFERRED / HOLD / HUMAN / PARTIAL**.  
Do not invent Coverage COMPLETE, Projection FRESH, B0 PASS, READY, Phase 6.3.2 COMPLETE, Phase 6.4 COMPLETE, or Phase 7 GO.

---

## Live MCP (this wave; tools available)

quant_mcp tools **worked** this isolation turn. Values below are this-turn reads, not last-known docs. Isolation does not refresh the ledger. No GitHub check-runs MCP existed; live GitHub below is `gh api`. Live Cloudflare is Wrangler 4.125.0 (account `11233bca08d134a9b738eaa46b9751d9`, logged in as `taku_haga@icloud.com`).

```text
Projection: STALE
  generated_at: 2026-08-21T12:30:49.152421+00:00
  age_seconds: 183055 (~50.8h)
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
AM SLA current_state: PROJECTION_STALE (state_reason: ops_projection_stale)
storage_plane_status.p0_claims.mass_research: NO-GO
storage_plane_status.p0_claims.ready: null
```

Live GitHub (this turn; `gh api`, not invented):

```text
commits/67fcbd7c/check-runs  total_count: 0
commits/67fcbd7c/status      state: pending, total_count: 0
PR #1                       statusCheckRollup: null, mergeState BLOCKED
                            headRefOid: 67fcbd7cd56847a9fc0fba7bcefbd743b43fc106
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

Cron PASS, raw-retention COMPLETE, and row-count growth are **not** Coverage COMPLETE or READY. Local `verify_ci` at `40d1aa90` is **not** a posted GitHub context.

---

## Verdict

| Gate | Status |
|------|--------|
| Phase 6.3.2 COMPLETE? | **NOT COMPLETE** |
| Phase 6.4 COMPLETE? | **NOT COMPLETE** |
| Phase 7 Foundation | types exist; `PHASE7=OFF` |
| Phase 7 Controlled Pilot GO? | **NO-GO** |
| Phase 7 Mass Research GO? | **NO-GO** |

Wave-5 **tree** honesty (`index_text` CLIs, OTC `official_archive_index_day` grain, Python Worker-client stub, DO `budget_id` pin, documented `verify_ci` PASS at `40d1aa90`) is not a GO. Brief §8 `Pilot_GO` is a conjunction; live legs still fail: Projection **STALE**, `refresh_success=false`, B0 **UNKNOWN**, READY **null**, `applied_feed_cursor=null`, required GitHub `ci-aggregate` **not posted** (`check-runs total_count: 0`), Coverage still V2 **22 / 4 PARTIAL**, independent P0 unresolved ≠ 0 (live merge gate).

**HUMAN bottleneck named:** `quant-platform-ci-aggregate` Worker **absent**. Branch protection requires a context that has no producer on the account. Isolation must not deploy, bind secrets, or PAT-mint `ci-aggregate`.

---

## Named landings this wave (tree, not live GO)

| SHA | Landing | Closes (tree) | Does **not** close |
|-----|---------|---------------|-------------------|
| `34dc85df` | `refresh_coverage_ledger --index-text` forwards local HTML | CLI no longer silently omits `index_text` (missing flag → `None` / empty fail-closed, not 8784) | live ledger still STALE **8784 / 5886**. Does not fetch JSDA HTML. |
| `db569fc7` | `write_collection_receipts --index-text` / `QP_INDEX_TEXT` | `_plan_segments` passes `index_text` into `plan_required_segments`. Blank/missing → empty, not weekends. | never downloads the index; never invents COMPLETE |
| `9524dab7` | `publish_ops_projection --otc-index-html` | `--refresh-coverage` threads `index_text`; omitted/missing file is `None` | does not apply remote or invent FRESH/COMPLETE |
| `ddc40ae9` | ingest reuses fetched JSDA year-index HTML as `index_text` | archive refresh required days stay listed publication days, not empty or weekends | PARSE_ZERO index days stay PARTIAL |
| `26a6ca5e` | OTC JSON grain `official_archive_index_day` | loader + planner treat grain as official_index_days, not calendar. Weekend `2002-08-03` not required. | live MCP still V2 calendar inventory **8784** |
| `61c14a0d` | Python `put_children_then_manifest_via_worker` | Worker-client entry; unbound URL/token fail-closed; no CLI put fallback; no digest forge | **no HTTP client**. Remote always raises until Worker POST is wired. Overlay `QP_ALLOW_PYTHON_R2_PUT=1` still TOCTOU. |
| `89415105` | gateway DO create is not a reserve | in-memory: created ledger occupancy **zero** until `reserve`; string `budget_id` is not authority | live Edge occupancy **unproven** |
| `84d196fb` | `verify_ci` code-lane PASS at `40d1aa90` | local exit-0 documented: **1422 passed / 4 skipped** ([`P632_verify_ci_40d1aa90.md`](P632_verify_ci_40d1aa90.md)) | **not** merge-gate. **not** this SHA. GitHub `ci-aggregate` still 0. |
| `e854ae56` | ci-aggregate operator steps; Worker absent live | docs name first deploy as **HUMAN** create | isolation does not deploy |

This isolation did **not** re-run `scripts/verify_ci.sh` at `67fcbd7c`. The `40d1aa90` local PASS is three commits earlier than this window’s code landings and is **not** merge-gate.

---

## The 17 commits after `40d1aa90`

| SHA | Landing | Lane |
|-----|---------|------|
| `53d811f7` | banner Coverage V2 section as historical Phase 6.1 contract | docs |
| `f2df2962` | banner original-plan-gap register still holds at `40d1aa90` | docs |
| `9524dab7` | thread optional OTC `index_text` into projection coverage refresh | H / J |
| `e854ae56` | ci-aggregate operator steps; Worker absent live | A / HUMAN |
| `1d75bbe7` | independent review A revisit at `40d1aa90` | docs (A freeze) |
| `0d26b817` | independent review B revisit at `40d1aa90` | docs (B freeze) |
| `50193ec3` | wave-4 status after 20 commits vs `40d1aa90` | docs (wave-4 freeze) |
| `c54b9be2` | 6.3.2 P test inventory at `40d1aa90` | docs (P) |
| `84d196fb` | P632 `verify_ci` code-lane PASS at `40d1aa90` | docs (C; not merge-gate) |
| `f8e0f2d5` | §10.3 mixed authority remaining at `40d1aa90` | docs (Q) |
| `34dc85df` | pass local `--index-text` through to coverage ledger refresh | H |
| `61c14a0d` | python children-then-manifest requires Worker, not CLI put | M |
| `db569fc7` | `write_collection_receipts` takes local OTC index HTML | H |
| `89415105` | gateway DO create is not a reserve; live occupancy unproven | K |
| `26a6ca5e` | OTC JSON grain is `official_archive_index_day` | H / D |
| `ddc40ae9` | pass fetched JSDA year-index HTML into coverage refresh | H |
| `67fcbd7c` | independent review C catalog/pilot revisit at `40d1aa90` | docs (C freeze) |

Docs commits in this window (`53d811f7`, `f2df2962`, `e854ae56`, `1d75bbe7`, `0d26b817`, `50193ec3`, `c54b9be2`, `84d196fb`, `f8e0f2d5`, `67fcbd7c`) are freezes / operator notes, not live GO.

---

## A–S vs `67fcbd7c` (after the 17)

Prior registers: [`P632_brief_leaks.md`](P632_brief_leaks.md) vs `3ab87d0`; [`P632_wave2_status.md`](P632_wave2_status.md) vs `07b4435`; [`P632_wave3_status.md`](P632_wave3_status.md) vs `f224e7e`; [`P632_wave4_status.md`](P632_wave4_status.md) vs `40d1aa90`. This table is the wave-5 re-diff, not a rewrite of those files.

### A. Cloudflare mandatory CI

**status: PARTIAL** (protection + Worker **code** + `CI_LANE_TOKEN` + 7-worker `verify_ci` + types flags in repo) / **OPEN** (live check never posted; **Worker absent**) / **HUMAN** (`quant-platform-ci-aggregate` first deploy + token bind)

| Sub-item | At `40d1aa90` | After wave-5 |
|----------|---------------|--------------|
| `.github/` workflows | **FIXED** (absent) | **FIXED** — `git ls-files .github` empty; Actions `total_count: 0`. Do not add. |
| Aggregate Worker | **FIXED** (code). Live bind **HUMAN**. | **FIXED** (code). Live Worker **absent** — deployments **10007**, secrets not found, `/health` **404**. Named **HUMAN** bottleneck (`e854ae56`). |
| `verify_ci` covers gate Worker | **FIXED** (7th Worker + types `--check` + IR schema + `ALLOWED_FIELDS`) | **FIXED** (unchanged script). Local PASS documented at `40d1aa90`, not this SHA, not GitHub. |
| Branch protection on `main` | **FIXED** (requires `ci-aggregate`) | **FIXED** (setting). `app_id: null`. Not a passing receipt. |
| GitHub check-runs / statuses at HEAD | **OPEN** (`40d1aa90` `total_count: 0`) | **OPEN** — this turn `67fcbd7c` `total_count: 0`; `/status` `pending` / `0`. PR #1 `statusCheckRollup: null`, **BLOCKED**. |
| Fail/pass merge smoke | **OPEN** | **OPEN** — cannot smoke a producer that does not exist |
| Token bind | **HUMAN** | **HUMAN** — agent must not mint; nothing to bind until Worker exists |
| Workers Builds Git integration | **OPEN** | **OPEN** |
| Explicit promote vs auto-deploy | **HOLD** | **HOLD** |

### B. All six Workers reproducible build

**status: PARTIAL** (lockfiles; seven `npm run types -- --check`) / **OPEN** (clean-checkout proof at this HEAD; retry jitter still `Math.random`)

Unchanged vs wave-4 except: local `verify_ci` PASS is now **documented** at `40d1aa90` ([`P632_verify_ci_40d1aa90.md`](P632_verify_ci_40d1aa90.md): 7 workers including `ci-aggregate` 13 tests). That is a different SHA. Clean-checkout matrix **not** executed at `67fcbd7c` in this isolation. Residual `Math.random()` is retry/jitter only (`ingestion-premium` `index.ts:171,181`, `persist_records.ts:36`) — not identity (`crypto.randomUUID` still FIXED).

Do not invent PASS at `67fcbd7c`.

### C. Authoritative CI script

**status: PARTIAL** (`verify_ci.sh` fail-closed, 7 workers, IR schema, generated `ALLOWED_FIELDS`, types flags, **local PASS at `40d1aa90`**) / **OPEN** (merge gate is live GitHub context; producer Worker **absent**)

- Authoritative: `scripts/verify_ci.sh`. `WORKERS` still includes `platform/workers/ci-aggregate`. Missing lockfile/dir/script fails. No skip of missing `node_modules`. No `--legacy-peer-deps`.
- Fast helper remains `scripts/verify_all.sh` (three research workers; optional `VERIFY_*`). Still **not** mandatory CI. Do not merge the two (HOLD split).
- Local PASS at `40d1aa90`: 1422 passed / 4 skipped; wall 190.27s; `verify_ci: ok`. **Not** merge-gate. **Not** this HEAD. This isolation did not re-run the script after the 7 code landings.
- Residual: does **not** create a fresh venv (requires existing `.venv` 3.11+). Live merge authority is still “six lane receipts POSTed with `CI_LANE_TOKEN` → GitHub `ci-aggregate`”, and that POST host **does not exist**.

### D. SourceCapabilityContract V3

**status: PARTIAL** (typed loader + **4** dataset files + SoT clip + missing-file fail-closed + OTC grain token) / **OPEN** (22 governed datasets have no V3 file; nested maps open)

On-disk: `specs/source_capability/{equities_master,equities_earnings_calendar,equities_bars_daily_am,jsda_otc_bond_reference_prices}.json`. Loader now accepts `official_archive_index_day` (`coverage.py:37`; `26a6ca5e`). Nested evidence maps remain **OPEN** by design. Empty dir is valid; missing dataset rows load `None` and are **not** COMPLETE.

Planner **does** clip through SourceCapability SoT. That is a wire, not Dataset COMPLETE 23. Live MCP is STALE and still advertises V2 floors.

### E. Equities Master contract

**status: PARTIAL** (V3 + planner + core profile + PIT clamp + `jquants_records` island in repo) / **OPEN** (live STALE still V2 `2006-08-13`)

Unchanged vs wave-4 on the live side. Repo official start `2008-05-07`. Live MCP: last-known **PARTIAL** under STALE V2 `2006-08-13` (`backfill_status` 241 / 220 / 21). Official-domain correction in git ≠ live required-set migration. Do not invent Dataset COMPLETE.

### F. Earnings Calendar contract

**status: PARTIAL** (V3 + tip-snapshot planner + empty receipt PARTIAL + READY fixture honesty) / **OPEN** (live still 200 monthly V2 PARTIAL under STALE)

Unchanged vs wave-4 live: `backfill_status` 200 / 1 / 199. Planner yields **1** cutoff snapshot, not 200 months. Do not empty past months into COMPLETE.

### G. AM bars contract

**status: PARTIAL** (V3 + same-day snapshot planner + empty receipt PARTIAL) / **OPEN** (live still monthly V2 PARTIAL; SLA under STALE)

Planner yields **1** cutoff snapshot, not 32 months. `collection_sla_status(equities_bars_daily_am)` this turn: `current_state: PROJECTION_STALE` / `state_reason: ops_projection_stale`. Live `backfill_status` 32 / 1 / 31. Do not invent AM SLA PASS.

### H. JSDA OTC official-index Coverage

**status: PARTIAL** (V3 file + planner + HTML index SoT + refresh wire + **CLI `index_text`** + **JSON grain**) / **OPEN** (live STALE calendar inventory; PARSE_ZERO not sealed)

Wave-5 tree vs wave-4:

- Grain `collection_coverage.json` `segment_granularity` is now `official_archive_index_day` (`26a6ca5e`). Planner treats that token as `official_index_days`, not calendar (`coverage_ledger.py:288-292,347`).
- CLIs that used to omit `index_text` now take local HTML: `refresh_coverage_ledger --index-text` (`34dc85df`), `write_collection_receipts --index-text` / `QP_INDEX_TEXT` (`db569fc7`), `publish_ops_projection --otc-index-html` (`9524dab7`). Missing/blank → **empty** required set (fail-closed), **not** 8784 weekends.
- Ingest archive refresh reuses already-fetched year-index HTML (`ddc40ae9`) so listed publication days stay required.

Live MCP still last-known Wave-0 **5886 / 8784** under `history_target_start: 2002-08-02`. Tree refresh ≠ live ledger migration. PARSE_ZERO `2002-08-02` / `2002-08-05` stay **PARTIAL**. Do not COMPLETE empty non-index days. Do not hide PARSE_ZERO by moving `history_target_start`.

### I. ResearchDataProfile / READY

**status: PARTIAL** (v1 predicate + core requires master + string COMPLETE rejected + missing V3 false + mixed policy honesty + fixture tip receipts) / **OPEN** (live READY **null**)

Unchanged vs wave-4 live. `latest_ready_snapshot`: **null**. Digest-bound predicate ≠ a bound READY generation. STALE V2 PARTIAL keeps READY honest-false. That is intended; it is not a GO.

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

`--otc-index-html` on `publish_ops_projection` (`9524dab7`) is a tree wire. Isolation did **not** publish. See [`P632_projection_stale.md`](P632_projection_stale.md) and [`P632_projection_refresh_false.md`](P632_projection_refresh_false.md).

### K. Edge Durable Object hard budget

**status: PARTIAL** (DO reserve/reconcile in repo + **create≠reserve pin**) / **OPEN** (live Edge unproven)

`89415105` pins in-memory: created ledger has **zero** occupancy; `budget_id` presence is not a reserve; occupancy moves only on `reserveBudget`. Caps unchanged (`auto_promotion: false`). Live occupancy / double-spend under production traffic: **not** measured this wave. String `budget_id` is still not the reserve.

### L. Worker public boundary

**status: PARTIAL** (preview vs production split) / **OPEN** (shared bearer still required on remaining surfaces) / **HOLD** (`workers_dev` kept where documented) / **HUMAN** (secret bind)

Unchanged vs wave-4: production `workers_dev=false` on research-ai-gateway, research-mass-eval, ingestion-jsda, ingestion-premium. **Kept true:** quant-ops-mcp (OAuth callback), ingestion-secrets (token-gated local), ci-aggregate (receipt POST host). Treat **kept** as **HOLD**. Dual `GATEWAY_TOKEN` / service-binding residual: **OPEN** (mass-eval `ai_gateway_client.ts` still sends `GATEWAY_TOKEN` as `X-Gateway-Token`). Ops MCP must not grow SQL / fetch / ingest / delete / READY publish. Not re-opened.

`ci-aggregate` `workers_dev=true` is moot until the Worker exists.

### M. Immutable artifact authority

**status: PARTIAL** (Worker child digest 409 + Python overlay fail-closed + **Worker-client stub**) / **OPEN** (no HTTP client; TOCTOU remains if overlay `=1`) / **HOLD** (overlay identity)

Worker children-then-manifest `onlyIf` remains immutable authority. `put_children_then_manifest_via_worker` (`61c14a0d`) is the Worker-client entry: unbound `MASS_EVAL_WORKER_URL` / `MASS_EVAL_TOKEN` fail-closed; dry_run local-only; **no CLI put fallback**; **no digest forge**. This commit **does not ship an HTTP client** — remote always raises `python must use Worker children-then-manifest; CLI put is not authority`. `QP_ALLOW_PYTHON_R2_PUT=1` does not grant CLI put on that path.

`default_r2_put` overlay `=1` is still head-then-put TOCTOU. `authoritative=True` still refused. Do not treat “stub exists” as Worker-equivalent create-if-absent.

### N. Active Catalog / Legacy Identity Registry

**status: PARTIAL** (v2 classification + YAML overlay fail-closed + digest identity + `yaml_*` aliases) / **OPEN** (compact source; `migration.jsonl` still load SoT) / **HOLD** (+N / unique22 / freeze n)

Unchanged vs wave-4 / Independent C at `40d1aa90` ([`P632_ind_C_revisit_40d1aa90.md`](P632_ind_C_revisit_40d1aa90.md)): YAML n = **0**; compiled freeze n = **2254**; `yaml_overlay_allowed()` **False**; `go: false`. Compact `family + template + parameter matrix` **not** implemented.

Do not report 2254/2092 as a product win. Combo +N **HOLD**. unique22 leftover occupancy **HOLD**.

### O. Evaluation IR single generated authority

**status: PARTIAL** (JSON Schema codec SoT; `verify_ci` validates golden + generated `ALLOWED_FIELDS`) / **OPEN** (hand-written TS codec remains)

Unchanged vs wave-4. `ALLOWED_FIELDS` generated (`d8821197`). Worker `evaluation_ir.ts` is still a hand-written TS codec. Brief asked generated Python+TS types. **Not** done.

### P. Test audit / reduction

**status: OPEN** (inventory not closed) / **PARTIAL** (Lane 17 audit + collect freezes + digest identity + READY fixture honesty)

See [`P632_test_inventory.md`](P632_test_inventory.md) (`3ab87d0`, collected **1353**), [`P632_test_inventory_now.md`](P632_test_inventory_now.md) (`07b4435`, **1379**), [`P632_test_inventory_40d1aa90.md`](P632_test_inventory_40d1aa90.md) (**1426** collected; `tests/test_*.py` **146**; Worker first-party **20**; YAML **0**). Local `verify_ci` at `40d1aa90` reported **1422 passed, 4 skipped**.

This HEAD `git ls-files tests/test_*.py` = **148** (two files landed in this window). Worker first-party test files still **20** (`budget_do.test.ts` grew in place). This wave did **not** re-run `pytest --collect-only`. Do not invent `tests_after`. Count growth is not a consolidation win.

### Q. Whole-repo refactor (authority split)

**status: PARTIAL** / **OPEN** / **HOLD** (named live-math files)

§10 remaining-extracts freeze is still authored vs `40d1aa90` ([`docs/phase63_refactor_plan.md`](../phase63_refactor_plan.md)). Wave-5 landings vs that freeze:

| §10.3 later | At `40d1aa90` | After wave-5 |
|-------------|---------------|--------------|
| 1 BackfillPlanner vs `plan_required_segments` | PARTIAL (tip snapshots + OTC refresh wired) | **PARTIAL** — CLI/`archive.py` now pass `index_text`; non-tip still month-chunks |
| 2 Python `r2_io.py` TOCTOU | PARTIAL (overlay fail-closed; TOCTOU if `=1`) | **PARTIAL** — Worker-client stub (`61c14a0d`); no HTTP client; overlay TOCTOU if `=1` remains |
| 3 hand-written `evaluation_ir.ts` | PARTIAL (`ALLOWED_FIELDS` generated; codec hand-written) | **PARTIAL** — unchanged |
| 4 MCP frozen “Coverage V2” strings | FIXED (Worker + Python echo stored `policy_version`) | **FIXED** (not reopened) |
| 5 `verify_all` vs `verify_ci` | HOLD (keep both) | **HOLD** (local PASS at `40d1aa90` is not merge-gate) |

leftover occupancy / `cost_models.py` / generated `catalog_ids.ts` **HOLD**. Coverage V2 JSON vs V3 contracts: planner + OTC grain + `index_text` CLIs wired for 4 datasets; live MCP still V2 STALE.

### R. Basket reconstitution evidence

**status: HUMAN** (apply false) / evidence pack **FIXED** (detect-only)

`RECONSTITUTION_APPLY = False`. Agent must not flip apply.

### S. Controlled Pilot

**status: FIXED** (OFF) — GO conditions **OPEN** / unmet

Worker: `MASS_RESEARCH = "NO-GO"`, `PHASE7 = "OFF"`, `READY_DECLARED = "false"` (`research-mass-eval/wrangler.toml`). Python deny-by-default, `go: False`. **Do not** run the one-shot paper loop. Mass remains **NO-GO**. Auto promotion **OFF**. Live broker **OFF**. Independent C at `40d1aa90`: catalog/pilot P0 unresolved **0** (no live arming); that is not Phase 7 GO.

---

## Independent P0 scoreboard (tree vs live)

| ID | At `40d1aa90` (wave-4) | After wave-5 (`67fcbd7c`) |
|----|------------------------|---------------------------|
| IND-A-DOMAIN | **FIXED**. Live STALE still V2 `2006-08-13`. | **FIXED** (not reopened). Live still STALE. |
| IND-A-JSDA-PHANTOM | **FIXED** (tree: refresh wire). Live inventory STALE **8784 / 5886**. | **FIXED** (tree) + CLI/`archive.py` `index_text` + grain token. Live still **8784 / 5886**. PARSE_ZERO stays gap. |
| IND-A-PIT-BYPASS | **FIXED** | **FIXED** (not reopened) |
| IND-A-FORGED-RECEIPT | **FIXED** | **FIXED** (not reopened) |
| IND-A-FALSE-COMPLETE | **PARTIAL** — READY fixture tip receipts FIXED; genuine `event_driven` event-zero COMPLETE remains | **PARTIAL** — same residual (`test_event_zero_successful_exhausted_raw_receipt_is_complete`) |
| IND-A-READY-DEPS | **FIXED**. Live READY **null**. | **FIXED**. Live **null**. |
| P632B-01 `verify_all` vs `verify_ci` | **PARTIAL** — types flags + generated `ALLOWED_FIELDS`; live merge gate is GitHub `ci-aggregate` never posted | **PARTIAL** — local PASS at `40d1aa90` documented; live merge gate still not `verify_ci`; producer Worker **absent** |
| P632B-02 live `ci-aggregate` posted | **OPEN** (`check-runs 0`, `app_id: null`) | **OPEN** — Worker **absent** (10007). **HUMAN** create. Check-runs still **0**. |
| P632B-03 `GATEWAY_TOKEN` / `MASS_EVAL_TOKEN` | **OPEN** (mass-eval still sends `GATEWAY_TOKEN`) | **OPEN** (empty diff on that path) |
| P632B-05 Python R2 TOCTOU | **PARTIAL** — overlay fail-closed; **OPEN** if `=1` | **PARTIAL** — Worker stub fail-closed without HTTP; overlay `=1` still TOCTOU |
| C-YAML load overlay | **FIXED**. +N **HOLD**. | **FIXED**. +N **HOLD**. Independent C P0 unresolved **0** (no live arming). |

Independent P0 unresolved ≠ 0 (live CI never posted; **ci-aggregate Worker absent**; event-zero residual). `Pilot_GO.IndependentReview_P0_Zero` stays **OPEN**. Tree JSDA CLI/grain close is not a live Coverage COMPLETE.

---

## Brief §8 `Pilot_GO` (current tree + live MCP)

| Criterion | Status |
|-----------|--------|
| Mandatory_CF_CI | **OPEN** — Worker **absent** (10007); live check-runs **0**. HUMAN deploy. |
| Main_Protected | **FIXED** (setting requires `ci-aggregate`) |
| Six_Workers_Clean | lockfiles **FIXED**; `verify_ci` 7 workers **FIXED** (script); local PASS at `40d1aa90` **FIXED** (docs); clean-checkout matrix at this HEAD **OPEN** |
| SourceCapabilityContract_V3 | **PARTIAL** — 4/26 files; nested maps OPEN; missing file fail-closed; OTC grain token **FIXED** |
| RequiredDomain_Subset_OfficialDomain | **PARTIAL** — planner + OTC refresh + `index_text` CLIs + grain; live MCP still V2 STALE |
| ResearchDataProfile_Complete | **PARTIAL** — core includes master; string COMPLETE rejected; fixture tip receipts; READY **null** |
| Projection_FRESH | **NO** — **STALE** |
| Refresh_SUCCESS | **NO** — `false` |
| B0_PASS | **NO** — **UNKNOWN** |
| READY_Profile_Exists | **NO** — **null** |
| AppliedCursor_Pinned | **NO** — **null** |
| EdgeBudget_Hard | **PARTIAL** (code + create≠reserve pin) / live **OPEN** |
| Artifact_Coherent | Worker digest 409 **FIXED**; Python overlay fail-closed **PARTIAL**; Worker stub **PARTIAL** (no HTTP); TOCTOU if overlay **OPEN** |
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

1. **Bottleneck:** create `quant-platform-ci-aggregate` on account `11233bca08d134a9b738eaa46b9751d9`. Bind `CI_LANE_TOKEN` and `GITHUB_STATUS_TOKEN`. Connect Workers Builds for six lanes. Prove a **failing** SHA is unmergeable and a **passing** six-receipt SHA posts `ci-aggregate` success. Isolation worktree does **not** do that. Do not PAT-mint the required context.
2. Bind `GATEWAY_TOKEN` / `MASS_EVAL_TOKEN` / `QUANT_READINESS_HMAC_SECRET` on the intended env. Do not commit values.
3. Apply `0007_ops_applied_pins` to remote D1 only when the operator is ready to pin. Until then CURRENT stays impossible.
4. Refresh the ops projection so MCP is FRESH with `refresh_success=true`, passing official-index HTML (`--otc-index-html` / `--index-text`). Tree honesty is not a publish. Live still **8784 / 5886**.
5. Dated reconstitution brief for `basket_theme_fund` / `basket_event_fund` only. Do not flip `RECONSTITUTION_APPLY`.
6. Isolation worktree does **not** push `main`. PR #1 stays **BLOCKED** until `ci-aggregate` actually posts from a **deployed** Worker.

---

## What this file is not

- A rewrite of [`P632_brief_leaks.md`](P632_brief_leaks.md), [`P632_wave2_status.md`](P632_wave2_status.md), [`P632_wave3_status.md`](P632_wave3_status.md), or [`P632_wave4_status.md`](P632_wave4_status.md).
- A live Coverage remeasure. Planner, grain, and `index_text` CLIs are git; MCP is **STALE**.
- Dataset COMPLETE 23, OTC COMPLETE, B0 PASS, READY, Phase 6.3.2 COMPLETE, Phase 6.4 COMPLETE, or Phase 7 GO.
- Proof that `verify_ci.sh` is green at `67fcbd7c`. Local PASS at `40d1aa90` is not this SHA and is not merge-gate.
- A deploy of `quant-platform-ci-aggregate`. The Worker is **absent**. That is the HUMAN bottleneck.

Wave-5 **tree** honesty landed. Phase 6.3.2 remains **NOT COMPLETE**. Phase 6.4 remains **NOT COMPLETE**. Controlled Pilot remains **NO-GO**.
