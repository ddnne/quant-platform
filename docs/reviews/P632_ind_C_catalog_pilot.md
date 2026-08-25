# P632 independent review C — catalog and pilot gates

**Lane:** independent C (isolation worktree `docs/p632-ind-C-catalog-pilot`)  
**Isolation HEAD:** `3ab87d0` (`contracts: nested SourceCapability evidence maps are open`)  
**`origin/main` at this audit:** `b5c326a`  
**Sources:** tree at this HEAD; [`original_plan_gap.md`](original_plan_gap.md); `eval_flags.py`; `catalog_active.py`; `occupancy_guards.py`; `phase7_pilot.py`; `pilot_loop.py`; `reconstitution_evidence.py`; `research_freezes.py`.  
**Code:** none. This file is detect-only.

Mass / READY / Phase 7 Controlled Pilot / reconstitution apply: **NO-GO / OFF / false**.  
Do not invent Coverage COMPLETE, Projection FRESH, B0 PASS, READY, or GO.

Status vocabulary: **OPEN / HOLD / PASS**. P0 = live arming or silent mutation. P1 = residual hole that would regress a stopped gate if exercised.

Live counts at this HEAD (compiled load, yaml n=0):

| Surface | n |
|---------|--:|
| YAML `specs/research_logics/*.yaml` | **0** |
| compiled `migration.jsonl` / freeze `CATALOG_YAML_COUNT_AT_STOP` | **2254** |
| `active_logic_ids()` / `countable_thesis_ids()` / `pilot_candidates()` | **2092** |
| `legacy_logic_ids()` | **162** |
| unique-22 leftover | **22** (17 parked + 5 occupancy-equal lifts) |
| `generation_enabled=True` compiled rows | **0** |

---

## Verdict

| Gate | Status | Live? |
|------|--------|-------|
| YAML re-add | **P1 OPEN** (stop still authorizes yaml n=2254; load overlay replaces compiled). Current yaml n=**0**. | not live |
| AND-enumeration / `+N` growth | **HOLD** (`CATALOG_AND_PLUS_N_STOPPED` / `EVENT_THREE_AND_PLUS_N_STOPPED`) | stopped |
| legacy 2254 in **normal** `pilot_candidates()` | **PASS** for the 162 legacy IDs. **P1 OPEN** inherited: 2092 countable AND rows are still the “active/pilot” universe (factorize not done). | helper not wired to `start()` |
| unique22 silent unpark | **HOLD** (17 parked ∩ active = ∅) | no unpark |
| reconstitution auto-apply | **HOLD** (`RECONSTITUTION_APPLY=False`; both cuts; no member mutation) | no apply |
| Phase 7 `start()` | **HOLD / OFF** | raises |
| Mass flags | **HOLD / NO-GO** | deny-by-default |

**P0 unresolved at this HEAD: 0.**  
Phase 7 Controlled Pilot and Mass Research remain **NO-GO**.

Original 08-22 plan vs AND product: the large invalid deviation is **already corrected for growth**. Treating the frozen 2254/2092 expanded map as the research product would be a **regression**, not a return to the 08-22 combination/funds brief. Cite [`original_plan_gap.md`](original_plan_gap.md) §§3, 6, 7.

---

## Original 08-22 plan vs AND product (cite)

[`original_plan_gap.md`](original_plan_gap.md) register:

| # | Item | Original valid? | Still held? | Direction correction? |
|---|------|-----------------|-------------|------------------------|
| 2 | 08-22 combination/funds from simple gated theses + usable-net metric | Yes | Partial (funds thesis kept; YAML-as-product abandoned) | No further (AND product already cut) |
| 3 | AND-enumeration / YAML product / `+N` without Worker bodies | **Invalid deviation** | Stopped (`CATALOG_AND_PLUS_N_STOPPED`; YAML n=0; compiled n=2254) | **No** — re-opening YAML `+N` or AND-as-product is a regression |
| 6 | Remaining original-plan work | Human reconstitution KEEP 24df | Pending (`RECONSTITUTION_APPLY=False`) | **No** — do not substitute YAML / Mass / Phase 7 |
| 7 | Next phase = Mass / READY / Phase 7 GO | Never the original next step | **NO-GO** | **Forbidden** |

08-22 09:06 product was **simple, sparse gated theses as later combination/funds material**. YAML was declaration (combo gates + Worker body + occupancy-equal), not file-count inventory. 08-22 15:23+ gate permutation / catalog fill (881-class 3-AND, YAML 2254) read that as **combinatorial map fill**. That is the invalid deviation.

Course-correction already in tree (do not undo):

- `CATALOG_AND_PLUS_N_STOPPED=True` / `EVENT_THREE_AND_PLUS_N_STOPPED=True`
- YAML mechanical delete (`yaml_still_present: false`)
- freeze identity compiled n=2254, digest `sha256:6ad5ba57dfa41ed9a97e5895d9238040fbb5539b310a2ea4aa349172b6cb8c69`
- known-thin unused 2-AND rewrite refused; 3-AND new batch refused
- countable = compiler row + Worker body + occupancy-equal (YAML clone does not count)

Do not: declare Phase 7 GO; recommend YAML `+N`; recommend AND as a product; silent-unpark unique22; flip `RECONSTITUTION_APPLY`; enable factory unique/combo generation.

Do: wait for human `drop_parents` vs `drop_children` on KEEP 24df; keep the freeze; keep scores on R2+D1.

---

## P0

None live. Constructed Mass / Pilot paths still require signed `VerifiedResearchReadiness` that production does not mint. Env `MASS_RESEARCH=GO` / `PHASE7=ON` cannot grant (`research_capabilities` `granted = False`; tests `test_env_flags_cannot_grant_pilot_start`, `test_driver_env_flags_cannot_grant`).

---

## P1

### C-YAML-STOP-PERMITS-FULL-READD

- **severity:** P1
- **affected:** `packages/product/research/occupancy_guards.py:76-111`; `packages/product/research/unique_logic/catalog.py:123-135`; `packages/product/research/catalog_compiler.py:328-349`; `packages/product/research/eval_flags.py:7-11`
- **observed fact:** yaml n at this HEAD is **0**. `assert_catalog_and_plus_n_stopped` while stopped: yaml n>0 is **accepted** if n==2254; yaml n==0 requires compiled n==2254. `_load_catalog_specs_cached` **prefers any** `*.yaml` overlay and **returns only those rows**, skipping `load_compiled_specs`. `compile_catalog(persist=True)` compiles from that load path. Tests pin `yaml_still_present is False` / `not any(catalog_dir().glob("*.yaml"))` (`tests/test_catalog_active_legacy.py:58`, `tests/test_unique_logic_catalog.py:178`) but the runtime stop does **not** require yaml n==0.
- **why it matters:** [`original_plan_gap.md`](original_plan_gap.md) §3: “do not re-add YAML.” A full 2254-file restore satisfies the freeze guard and becomes load SoT. A **partial** restore (n≠2254) raises only if the assert is called; load itself does not call it. One stray YAML would replace the compiled 2254 map for any caller of `load_catalog_specs()`.
- **structural fix:** while `CATALOG_AND_PLUS_N_STOPPED`, refuse yaml n>0 (require yaml n==0 and compiled n==freeze). Keep `parse_catalog_yaml` as HOLD identity; do not add YAML.
- **status:** OPEN (not live; yaml n=0)

### C-AND-PRODUCT-STILL-ACTIVE-PILOT

- **severity:** P1 (inherited factorize; not a new +N)
- **affected:** `packages/product/research/catalog_active.py:38-64`; `packages/product/research/phase7_pilot.py:155-167`; `specs/research_catalog/manifest.json`; [`original_plan_gap.md`](original_plan_gap.md) §3; P631 leak **G**
- **observed fact:** v2 split **does** keep the 162 legacy IDs out of `pilot_candidates()` (unique-22 park 17 ⊂ legacy; `pilots == active`; `pilots ∩ legacy = ∅`; `tests/test_catalog_active_legacy.py:74-95`). That leak check **PASS**. The 2254 freeze identity is still almost entirely the **normal** countable set: active/countable/pilot helper = **2092**. `worker_implemented_logic_ids()` = **2254** because `catalog_ids.ts` lists the freeze. `generation_enabled` is False on all compiled rows, so the “no Worker body clone” filter is empty. `MassResearchScheduler.select_pilot_hypotheses` does **not** consult `catalog_kind` / `pilot_candidates`; it accepts any 2–32 distinct strings. `start_mass_catalog_eval` (n default 2000) raises. `pilot_loop.start()` raises capability-off and never constructs the scheduler.
- **why it matters:** 08-22 product is combination/funds from simple theses, not 2092 AND rows as inventory. Factorize-to-templates is **OPEN** (P631 G). Wiring `pilot_candidates()` into a live loop, or treating 2092 as a GO universe, would restore AND-as-product without flipping the +N flags.
- **structural fix:** keep +N stopped. Do not fan out 2092/2254 as Phase 7 candidates. Factorize is a dated brief, not silent unfreeze. If `select_pilot_hypotheses` is ever live, intersect with `pilot_candidates()` and refuse legacy/parked IDs.
- **status:** OPEN (factorize) / HOLD (growth stopped; `start()` OFF)

---

## HOLD confirmations (not P0/P1)

### YAML / AND `+N` growth — stopped

`packages/product/research/eval_flags.py:7-12`:

```text
EVENT_THREE_AND_PLUS_N_STOPPED = True
CATALOG_AND_PLUS_N_STOPPED = True
CATALOG_YAML_COUNT_AT_STOP = 2254
RECONSTITUTION_APPLY = False
```

`assert_new_batch_not_event_three_and` raises on ≥3 gates while stopped. `assert_known_thin_unused_absent` refuses known-thin 2-AND rewrites. Manifest `go: false`, `yaml_still_present: false`. Combo jsonl dump has no `yaml_remains_sot` (do not re-open A07/A11 occupancy leftover; occupancy now emits `yaml_still_present: False`).

No catalog-YAML **write** path found under `packages/product/research/` (`cf_propose_thesis.py:303,392` only stats mtime if a file exists). Factory skips `RESEARCH_UNIQUE_LOGIC_IDS` and unique/combo `generation_enabled` stays False (`offline/factory.py:1-4,543-557`).

### unique22 — no silent unpark

Park set is code, not YAML: `UNIQUE22_PARK_REASONS` (17) == `unique22_occupancy_park()`. Lifted 5 (`afterclose_only_event_hold`, `curve_steep_event_confirm`, `event_funding_easy_short`, `event_funding_stress_skip`, `event_margin_crowding_skip`) have combo-equal `params.gates`. Parked 17 have **empty** gates and are **legacy**, not `pilot_candidates`. Occupancy pack `do_not_silent_unpark: True`. Worker leftover occupancy stays in `daily_path.ts:522-526,916-920` (HOLD policy; do not unify with `comboEventGateOk`). Lift predicate is `spec_gates(catalog_spec(lid))` nonempty (`worker_bodies.py:71-90`) — adding gates to a parked compiled row would unpark; that is occupancy-equal machinery, not a silent unpark at this HEAD. Do not delete leftover occupancy.

### reconstitution — no auto-apply

`RECONSTITUTION_APPLY` is False at eval_flags / combo_basket_catalog / occupancy_audit / reconstitution_pending / reconstitution_evidence (single SoT; `tests/test_eval_tracks.py:131-141`). `reconstitution_options` `apply_reject: False`. Preview and evidence emit **both** `drop_parents_keep_children` and `drop_children_keep_parents`. `recommended_choice` is labeled `recommended_choice_is_not_apply: True` / `do_not_auto_choose: True`. `_economics_clearly_better` can only change the recommendation, not members. `write_reconstitution_evidence_pack` refuses live R2 put (`put_r2 and not dry_run` raises; return `put_r2: False`). `usable_sleeve_coverage` replacement rows `apply: False`. Human pending remains `basket_theme_fund` / `basket_event_fund` on KEEP 24df. Do not restitch 24ek.

### Phase 7 `start()` still OFF

`research.pilot_loop.start` → `ControlledPilotLoopPlan.start` → `_require_execution()` → `MassResearchDisabledError` (“controlled pilot loop remains capability-off”). Import does not construct `MassResearchScheduler`. `generation_count` must be 1; `live_orders` / `mass_fan_out` rejected at plan init. `MassResearchScheduler` is fail-closed at construct (readiness type + `require_valid`, budget, plan snapshot, bound eval service, artifact `create_if_absent`; `operator_override` rejected; n>32 rejected). `start_mass_catalog_eval` always raises. Tests: `tests/test_pilot_loop.py:32-45,115-129`; `tests/test_phase7_pilot_construct.py:208-213`.

Foundation docs stay **OFF**: `docs/architecture/phase7_fail_closed.md`, `docs/operations/phase7_foundation_off.md`. Gateway deployed ≠ Phase 7.

### Mass flags

`packages/research_runtime/features/research_freezes.py:7-38`:

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

`research_capabilities()` always returns `data_ready/generation/mass_screen/promotion/paper_execution = False` and `go: False` (`granted = False` even when env says GO/ON). `start_mass_research` rejects `operator_override` and caller `ready_count` / `go_override`. Drivers refuse without capability (`cf_mass_eval_job`, `cf_daily_path_job`, `cf_propose_thesis`). Compiled catalog `generation_enabled` all False.

---

## What this review does not do

- Does not flip `CATALOG_AND_PLUS_N_STOPPED` / `RECONSTITUTION_APPLY` / `PHASE7`.
- Does not add YAML, unpark unique22, factorize 2254, or enable factory unique/combo generation.
- Does not declare Phase 6.3.1 / 6.4 COMPLETE or Phase 7 GO.
- Does not re-open wave-1 P0s or A07 occupancy `yaml_remains_sot` (FIXED later; occupancy now `yaml_still_present: False`).
- Does not treat HOLD leftover occupancy, factory OFF, or 3 frozen pins as dead code ([`original_plan_gap.md`](original_plan_gap.md) §4).
