# P632 independent review C revisit — catalog and pilot gates at `0a8ced34`

**Lane:** independent C (not the implementer; isolation worktree `grok/p632-ind-C-revisit-0a8ced34`; docs only)  
**HEAD:** `0a8ced34` (`0a8ced3487b490972ceda054bbf6f2a305dad147`) (`research: mass-eval-run fallback artifacts use Worker put`)  
**Prior freeze:** `5103b26b` (`5103b26bb40b2d73b49d079e03f8cf5b9c2a4c58`) — [`P632_ind_C_revisit_5103b26b.md`](P632_ind_C_revisit_5103b26b.md)  
**Earlier freezes:** `ed94d504` — [`P632_ind_C_revisit_ed94d504.md`](P632_ind_C_revisit_ed94d504.md); `67fcbd7c` — [`P632_ind_C_revisit_67fcbd7c.md`](P632_ind_C_revisit_67fcbd7c.md); `40d1aa90` — [`P632_ind_C_revisit_40d1aa90.md`](P632_ind_C_revisit_40d1aa90.md); `f224e7e` — [`P632_ind_C_revisit_f224e7e.md`](P632_ind_C_revisit_f224e7e.md); `07b4435` — [`P632_ind_C_revisit.md`](P632_ind_C_revisit.md); `3ab87d0` — [`P632_ind_C_catalog_pilot.md`](P632_ind_C_catalog_pilot.md)  
**Cite:** [`original_plan_gap.md`](original_plan_gap.md) §§3, 6, 7  
**`origin/main` at this audit:** `b5c326a` (`b5c326a7f612563f2da4a84f08063a307ec38e0a`)  
**Code:** none. This file is detect-only.

Mass / READY / Phase 7 Controlled Pilot / reconstitution apply: **NO-GO / OFF / false**.  
Do not invent Coverage COMPLETE, Projection FRESH, B0 PASS, READY, or GO.

Status vocabulary: **OPEN / HOLD / PASS**. P0 = live arming or silent mutation. P1 = residual hole that would regress a stopped gate if exercised.

**Catalog/pilot gates at `0a8ced34` are unchanged vs `5103b26b`.** Identity blobs (eval_flags, overlay load, compiler, freeze n, wrangler Mass/Phase 7, reconstitution apply, Phase 7 `start()`, factory) are the same git object. Two adjacent files moved in this window; neither changes yaml n, compiled n, overlay, `+N`, apply, unique22 park set, leftover occupancy math, Phase 7 `start()`, or Mass flags. Live counts were re-measured at this HEAD, not copied.

Live counts at this HEAD (compiled load, yaml n=0; re-measured):

| Surface | n |
|---------|--:|
| YAML `specs/research_logics/*.yaml` | **0** |
| compiled `migration.jsonl` / freeze `CATALOG_YAML_COUNT_AT_STOP` | **2254** |
| `active_logic_ids()` / `countable_thesis_ids()` / `pilot_candidates()` | **2092** |
| `legacy_logic_ids()` | **162** |
| unique-22 leftover | **22** (17 parked + 5 occupancy-equal lifts) |
| unique22 park ∩ active | **∅** |
| `generation_enabled=True` compiled rows | **0** |
| `yaml_overlay_allowed()` (`QP_ALLOW_YAML_OVERLAY`) | **False** |

Manifest digest unchanged: `sha256:6ad5ba57dfa41ed9a97e5895d9238040fbb5539b310a2ea4aa349172b6cb8c69`. `go: false`. `yaml_still_present: false`. Compact `family + template + parameter matrix` still **NOT** done (`migration.jsonl` remains 2254 expanded rows; **HOLD**).

---

## Verdict

HEAD **still matches** the previous PASS/HOLD scoreboard at `5103b26b`. Counts, `+N` stops, reconstitution apply, Phase 7, Mass flags, YAML overlay fail-closed, unique22 park occupancy, and leftover occupancy HOLD are **unchanged**. P0 unresolved for catalog/pilot is **0**. That is **not** Phase 7 GO.

| Gate | At `5103b26b` | At `0a8ced34` | Live? |
|------|---------------|---------------|-------|
| YAML silent overlay (load replaces compiled) | **HOLD** (`QP_ALLOW_YAML_OVERLAY` fail-closed; yaml n=0) | **HOLD** (same; overlay env unset) | not live |
| YAML freeze identity still accepts n=2254 | **P1 OPEN** residual (not silent; needs overlay env=`1`) | **P1 OPEN** residual (same) | not live |
| AND-enumeration / `+N` growth | **HOLD** | **HOLD** (`eval_flags` blob unmoved) | stopped |
| yaml n / compiled n | 0 / 2254 | **0 / 2254** | freeze held |
| reconstitution auto-apply | **HOLD** (`RECONSTITUTION_APPLY=False`) | **HOLD** (`RECONSTITUTION_APPLY=False`) | no apply |
| Phase 7 `start()` | **HOLD / OFF** | **HOLD / OFF** | raises |
| Mass flags | **HOLD / NO-GO** | **HOLD / NO-GO** | deny-by-default |
| YAML overlay `yaml_overlay_allowed()` | **False** | **False** | env unset; not in wrangler |
| legacy 162 in **normal** `pilot_candidates()` | **PASS** | **PASS** (`pilots == active`; `pilots ∩ legacy = ∅`) | helper not wired to `start()` |
| 2092 AND rows as active/pilot universe | **P1 OPEN** | **P1 OPEN** (n still 2092) | `start()` OFF |
| unique22 silent unpark | **HOLD** | **HOLD** (17 parked ∩ active = ∅) | no unpark |
| leftover occupancy unify with `comboEventGateOk` | **HOLD** | **HOLD** (`046ae438` pointer only; `daily_path.ts` unmoved) | do not unify |
| compact family+template+parameter matrix | **HOLD** (not done) | **HOLD** (not done) | freeze n=2254 |

**P0 unresolved at this HEAD: 0.**  
No live arming. No silent catalog mutation. Phase 7 Controlled Pilot and Mass Research remain **NO-GO**. P0=0 is **not** a Phase 7 GO.

Do **not** recommend YAML `+N`. Do **not** recommend AND as a product. Do **not** recommend Phase 7 GO. Do **not** recommend unique22 unpark. Do **not** recommend unifying leftover occupancy with `comboEventGateOk`.

[`original_plan_gap.md`](original_plan_gap.md) §3: re-opening YAML `+N` or AND-as-product is a **regression**, not a return to the 08-22 combination/funds brief. §6: remaining original-plan work is human reconstitution KEEP 24df. §7: next phase is **not** Mass / READY / Phase 7.

---

## Live MCP (this isolation turn — not invented FRESH)

quant_mcp tools **were available**. Values below are this-turn reads. Projection is **STALE**. Latest READY snapshot is **null**. B0 is **UNKNOWN**. Do not narrate FRESH / READY / B0 PASS.

| Surface | Value |
|---------|--------|
| `ops_status.coverage_status_counts` | **22 COMPLETE · 4 PARTIAL** (ops_current; not a research READY snapshot) |
| `ops_status.last_run` | id 14318, `2026-08-24T00:15:01+09:00`, jquants, pass |
| `projection_status` | **STALE** |
| `active_generation` | `projgen-ef18b4f86ee946048161d25e2a30a2a8` |
| `projection_generated_at` | `2026-08-21T12:30:49.152421+00:00` |
| `projection_source_generation` | `2026-08-21T12:28:33.345482+00:00` |
| `projection_age_seconds` | 185835 (~51.6 h) |
| `stages.refresh_success` | **false** |
| `latest_ready_snapshot` | **null** (`reason`: no published READY generation is bound to this Worker) |
| `b0_status` | **UNKNOWN** (`reason`: snapshot quality/B0 projection is unavailable) |
| `storage_plane_status.p0_claims.mass_research` | **NO-GO** |
| `storage_plane_status.p0_claims.ready` | **null** |

`coverage_gaps` still returns **4 PARTIAL** under **`collection-coverage/v2`** floors (STALE projection, not a catalog GO):

| Dataset | Live `history_target_start` | `evaluated_at` |
|---------|-----------------------------|----------------|
| `equities_master` | **2006-08-13** | 2026-08-18 |
| `equities_bars_daily_am` | **2024-01-04** | 2026-08-14 |
| `equities_earnings_calendar` | **2010-01-04** | 2026-08-14 |
| `jsda_otc_bond_reference_prices` | **2002-08-02** | 2026-08-21 |

Last-known-good narrative remains **22 COMPLETE · 4 PARTIAL**. This file is not a ledger refresh.

---

## Original 08-22 plan vs AND product (cite)

[`original_plan_gap.md`](original_plan_gap.md) register — **unchanged** at this HEAD (banner still names `5103b26b`, prior-window pointer only; this lane does not rewrite it; body freeze remains `e927b97`):

| # | Item | Original valid? | Still held? | Direction correction? |
|---|------|-----------------|-------------|------------------------|
| 2 | 08-22 combination/funds from simple gated theses + usable-net metric | Yes | Partial (funds thesis kept; YAML-as-product abandoned) | No further (AND product already cut) |
| 3 | AND-enumeration / YAML product / `+N` without Worker bodies | **Invalid deviation** | Stopped (`CATALOG_AND_PLUS_N_STOPPED`; YAML n=0; compiled n=2254) | **No** — re-opening YAML `+N` or AND-as-product is a regression |
| 6 | Remaining original-plan work | Human reconstitution KEEP 24df | Pending (`RECONSTITUTION_APPLY=False`) | **No** — do not substitute YAML / Mass / Phase 7 |
| 7 | Next phase = Mass / READY / Phase 7 GO | Never the original next step | **NO-GO** | **Forbidden** |

Course-correction already in tree (do not undo):

- `CATALOG_AND_PLUS_N_STOPPED=True` / `EVENT_THREE_AND_PLUS_N_STOPPED=True`
- YAML mechanical delete (`yaml_still_present: false`); overlay fail-closed without `QP_ALLOW_YAML_OVERLAY=1`
- freeze identity compiled n=2254, digest `sha256:6ad5ba57dfa41ed9a97e5895d9238040fbb5539b310a2ea4aa349172b6cb8c69`
- known-thin unused 2-AND rewrite refused; 3-AND new batch refused
- countable = compiler row + Worker body + occupancy-equal (YAML clone does not count)
- compact `family + template + parameter matrix` **not** implemented; freeze n=2254 is **HOLD**, not a product win

Do not: declare Phase 7 GO; recommend YAML `+N`; recommend AND as a product; silent-unpark unique22; unify leftover occupancy with `comboEventGateOk`; flip `RECONSTITUTION_APPLY`; enable factory unique/combo generation.

Do: wait for human `drop_parents` vs `drop_children` on KEEP 24df; keep the freeze; keep scores on R2+D1.

---

## What moved `5103b26b` → `0a8ced34` (this lane)

`git rev-list --count 5103b26b..0a8ced34` = **18**. Identity blobs for yaml n, compiled n, overlay, `+N`, reconstitution apply, Phase 7 `start()`, and Mass flags are **identical** (same git object):

`eval_flags.py`, `occupancy_guards.py`, `unique_logic/catalog.py`, `catalog_active.py`, `catalog_compiler.py`, `phase7_pilot.py`, `pilot_loop.py`, `reconstitution_evidence.py`, `reconstitution_pending.py`, `combo_basket_catalog.py`, `eval_tracks.py`, `research_freezes.py`, `research_capabilities.py`, `offline/factory.py`, `platform/workers/research-mass-eval/wrangler.toml`, `specs/research_catalog/manifest.json`, `specs/research_catalog/migration.jsonl`, `daily_path.ts`, `combo_gates.ts`, `catalog_ids.ts`.

Two catalog-adjacent files **did** move. Neither is a catalog/pilot gate change:

| File | Commit | Effect on this lane |
|------|--------|---------------------|
| `unique_logic/worker_bodies.py` | `046ae438` `research: leftover occupancy HOLD pointer; do not unify` | Docstring only on `unique22_occupancy_park()`: park reasons stay in `UNIQUE22_PARK_REASONS`; leftover occupancy stays in `daily_path.ts`; **do not unify with `comboEventGateOk`**. Park set still 17. Not unpark. |
| `occupancy_audit.py` | `d6567268` `research: remote job artifacts use Worker children-then-manifest` | `_put_eval_bytes` now calls `put_research_artifact` instead of `default_r2_put`. Independent B / artifact POST. Not yaml n, compiled n, overlay, `+N`, reconstitution apply, Phase 7, or Mass. Reconstitution evidence still dry-run-only. |

`daily_path.ts` leftover occupancy comments (including “not comboCsGateOk” / “Do not drop without occupancy-equal re-eval”) are **unmoved**. Do not recommend extract-or-unify.

| Commit | Effect on this lane |
|--------|---------------------|
| `71c25a72` `docs: independent review C catalog/pilot revisit at 5103b26b` | Prior C revisit text. Not a gate change. |
| `4d970200` `docs: banner original-plan-gap register still holds at 5103b26b` | Pointer only. Body freeze remains `e927b97`. Not a gate change. |
| `046ae438` leftover occupancy HOLD pointer | HOLD confirmation. Not unpark. Not unify. |
| `0b81eedb` / `d6567268` / `52f3e70e` (Python R2 overlay fail-closed / Worker POST artifacts / unbound token 503) | Independent B / artifact authority. Not catalog/pilot n. |
| `017a43c6` `research: daily-path both-track artifact uses Worker put` | `cf_daily_path_job.py` Worker put. Not catalog n, overlay, `+N`, apply, Phase 7, or Mass. |
| `0a8ced34` `research: mass-eval-run fallback artifacts use Worker put` | `cf_mass_eval_run.py` Worker put. Not catalog n, overlay, `+N`, apply, Phase 7, or Mass. |
| `2e264a08` / `9c208ec3` (`verify_ci` Evaluation IR freeze pin / code-lane PASS) | Independent B / CI. Not catalog/pilot. |
| remaining docs / review-index / Independent A–B revisit / wave-7 status / test inventory | Not yaml n, compiled n, AND stop, reconstitution apply, Phase 7, Mass, or overlay. |

---

## P0

None live. Constructed Mass / Pilot paths still require signed `VerifiedResearchReadiness` that production does not mint. Env `MASS_RESEARCH=GO` / `PHASE7=ON` cannot grant (`research_capabilities` `granted = False` even when those env keys are set; remaining deny reason `verified_readiness_missing`). Tests still pin `test_env_flags_cannot_grant_pilot_start`, `test_driver_env_flags_cannot_grant`.

`QP_ALLOW_YAML_OVERLAY` is **unset** in this process and is **not** present in wrangler vars (top-level or `[env.production.vars]`). Overlay env is not an arming switch for Mass / Phase 7.

P0=0 on catalog/pilot is **not** Phase 7 GO.

---

## P1 (same as `5103b26b`)

### C-YAML-SILENT-OVERLAY — HOLD

- **severity:** was P1 at `3ab87d0`; **status HOLD** at `5103b26b` and **HOLD** at `0a8ced34`
- **affected:** `packages/product/research/unique_logic/catalog.py:1-26,140-169`; tests `tests/test_unique_logic_catalog.py:195-228`
- **observed fact:** yaml n=**0**. `yaml_overlay_allowed()` is **False**. `_load_catalog_specs_cached` raises `CatalogYamlOverlayError` when yaml paths exist and overlay is not allowed; it does **not** replace the compiled map. Env must be exactly `1` (`"true"` is refused).
- **not a product reopen:** opt-in overlay with env=`1` still **replaces** compiled (test `test_yaml_overlay_opt_in_replaces_compiled`). That is explicit, not silent. Do not set the env. Do not add YAML.

### C-YAML-STOP-PERMITS-FULL-READD — P1 OPEN residual

- **severity:** P1 (not P0: not live, not silent)
- **affected:** `packages/product/research/occupancy_guards.py:76-111`; `packages/product/research/catalog_compiler.py:266-294`; `packages/product/research/eval_flags.py:7-12`
- **observed fact:** `assert_catalog_and_plus_n_stopped` while stopped still **accepts yaml n>0 if n==2254**. yaml n==0 still requires compiled n==2254 (this tree: stop pack `n=0`, `n_compiled=2254`, `yaml_still_present=False`). A full 2254-file restore **plus** `QP_ALLOW_YAML_OVERLAY=1` would satisfy the freeze guard **and** become load SoT.
- **status:** OPEN (not live; yaml n=0; overlay env unset). Same as `5103b26b`.

### C-AND-PRODUCT-STILL-ACTIVE-PILOT — P1 OPEN

- **severity:** P1 (inherited factorize; not a new `+N`)
- **affected:** `packages/product/research/catalog_active.py:38-82`; `packages/product/research/phase7_pilot.py:155-167`; `specs/research_catalog/manifest.json`; [`original_plan_gap.md`](original_plan_gap.md) §3
- **observed fact:** 162 legacy IDs stay out of `pilot_candidates()` (`pilots == active`; `pilots ∩ legacy = ∅`). Active/countable/pilot helper = **2092**. `worker_implemented_logic_ids()` = **2254**. `generation_enabled` is False on all compiled rows. `summary()` still `go=False` / `not_a_pass=True` / `n_active_is_not_a_quality_metric=True`. `MassResearchScheduler.select_pilot_hypotheses` still accepts any 2–32 distinct strings. `MassResearchScheduler.start_mass_catalog_eval` still raises. `pilot_loop.start()` still raises capability-off. Scheduler construct still raises (`ResearchBudgetCapability required`). Compact family+template+parameter matrix is still **not** done.
- **status:** OPEN (factorize) / HOLD (growth stopped; `start()` OFF; compact matrix not done). Same as `5103b26b`.

---

## HOLD confirmations (re-measured at `0a8ced34`; same as `5103b26b`)

### YAML / AND `+N` growth — stopped

`packages/product/research/eval_flags.py:7-12` (blob unmoved vs `5103b26b`):

```text
EVENT_THREE_AND_PLUS_N_STOPPED = True
CATALOG_AND_PLUS_N_STOPPED = True
CATALOG_YAML_COUNT_AT_STOP = 2254
RECONSTITUTION_APPLY = False
```

Live `assert_catalog_and_plus_n_stopped()`: `stopped=True`, `n=0`, `n_compiled=2254`, `yaml_still_present=False`, `freeze=2254`, `ok=True`, `go=False`. `assert_catalog_ids_emit_frozen()`: `n_yaml=0`, `n_digest=2254`, `n_logic_ids=2254`. `compile_catalog()` digest matches the freeze.

Factory skips `RESEARCH_UNIQUE_LOGIC_IDS`; unique/combo `generation_enabled` stays False (`offline/factory.py:1-4,543-557`).

### unique22 / leftover occupancy — no silent unpark; do not unify

Park set is code, not YAML. `UNIQUE22_PARK_REASONS` (17) == `unique22_occupancy_park()`. Parked 17 are all **legacy**. Lifted 5: `afterclose_only_event_hold`, `curve_steep_event_confirm`, `event_funding_easy_short`, `event_funding_stress_skip`, `event_margin_crowding_skip`. One lifted ID (`event_funding_stress_skip`) is **legacy**, not unparked.

`046ae438` added a HOLD pointer on `unique22_occupancy_park()`: park reasons live in `UNIQUE22_PARK_REASONS`; leftover occupancy stays in `daily_path.ts`; **do not unify with `comboEventGateOk`**. `daily_path.ts` leftover occupancy Worker policy is **unmoved**. Do not delete leftover occupancy. Do not recommend unpark. Do not recommend unify.

### reconstitution — no auto-apply

`RECONSTITUTION_APPLY` is False at eval_flags / combo_basket_catalog / reconstitution_pending / reconstitution_evidence (single SoT; occupancy_audit imports the same flag from `combo_basket_catalog`; `tests/test_eval_tracks.py:131-141`). `reconstitution_options` `apply_reject: False`. KEEP 24df still needs reconstitution: `basket_theme_fund` (nested 1) and `basket_event_fund` (nested 3). Evidence pack labels `recommended_choice_is_not_apply: True` / `do_not_auto_choose: True`. `write_reconstitution_evidence_pack(put_r2=True, dry_run=False)` raises; return `put_r2: False`. Do not restitch 24ek.

### Phase 7 `start()` still OFF

`research.pilot_loop.start` raises `MassResearchDisabledError` (“controlled pilot loop remains capability-off”). `MassResearchScheduler()` raises at construct (`ResearchBudgetCapability required`). `start_mass_catalog_eval` always raises. Foundation docs stay **OFF**. Gateway deployed ≠ Phase 7.

### Mass flags

`packages/research_runtime/features/research_freezes.py:7-38` (unmoved):

| Flag | Value |
|------|-------|
| `MASS_RESEARCH` | `NO-GO` |
| `PHASE7` | `OFF` |
| `READY_DECLARED` | False |
| `OPERATIONAL_GO` | False |
| `GO` | False |
| `MASS_GENERATE_SIGNALS` | False |
| `CONNECTED_TO_MASS` | False |
| `CONTINUOUS_PAPER` | `UNARMED` |
| `LIVE_ORDERS` | False |
| `PHASE7_ENV_ARMING_SWITCHES` | empty |
| `MASS_RESEARCH_ENV_ARMING_SWITCHES` | empty |

`platform/workers/research-mass-eval/wrangler.toml` `[vars]` and `[env.production.vars]`: `MASS_RESEARCH = "NO-GO"`, `PHASE7 = "OFF"`, `READY_DECLARED = "false"`.

`research_capabilities()` always returns `data_ready/generation/mass_screen/promotion/paper_execution = False` and `go: False`.

### YAML overlay — fail-closed

`yaml_overlay_allowed()` is **False**. `QP_ALLOW_YAML_OVERLAY` is unset. No wrangler `QP_ALLOW_YAML_OVERLAY`. Load without env=`1` refuses any `*.yaml` overlay (`CatalogYamlOverlayError`). Current yaml n=0 so compiled `migration.jsonl` is load SoT (2254 rows).

### Compact catalog matrix — still NOT done (HOLD)

Compact `family + template + parameter matrix` is **not** implemented. `specs/research_catalog/migration.jsonl` is still 2254 expanded rows and still load SoT. Freeze n=2254 is **HOLD**. Do not report 2254/2092 as a product win. Do not YAML `+N` as a substitute.

---

## What this review does not do

- Does not flip `CATALOG_AND_PLUS_N_STOPPED` / `RECONSTITUTION_APPLY` / `PHASE7`.
- Does not add YAML, set `QP_ALLOW_YAML_OVERLAY`, unpark unique22, unify leftover occupancy with `comboEventGateOk`, factorize 2254, or enable factory unique/combo generation.
- Does not declare Phase 6.3.1 / 6.4 COMPLETE or Phase 7 GO.
- Does not recommend YAML `+N`, AND as a product, or Phase 7 GO.
- Does not treat HOLD leftover occupancy, factory OFF, or 3 frozen pins as dead code ([`original_plan_gap.md`](original_plan_gap.md) §4).
- Does not invent Projection FRESH, B0 PASS, or READY from live MCP STALE / null / UNKNOWN.
- Does not treat catalog/pilot P0=0 as Phase 7 GO.
