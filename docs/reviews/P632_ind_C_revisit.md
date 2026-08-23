# P632 independent review C revisit — catalog and pilot gates

**Lane:** independent C (not the implementer; isolation worktree; docs only)  
**HEAD:** `07b4435` (`07b44355dc745b1a9b7f7c3c4eccbe123e7a171b`) (`docs: merge gate is verify_ci plus authenticated ci-aggregate`)  
**Prior freeze:** `3ab87d0` — [`P632_ind_C_catalog_pilot.md`](P632_ind_C_catalog_pilot.md)  
**Cite:** [`original_plan_gap.md`](original_plan_gap.md) §§3, 6, 7  
**`origin/main` at this audit:** `b5c326a`  
**Code:** none. This file is detect-only.

Mass / READY / Phase 7 Controlled Pilot / reconstitution apply: **NO-GO / OFF / false**.  
Do not invent Coverage COMPLETE, Projection FRESH, B0 PASS, READY, or GO.

Status vocabulary: **OPEN / HOLD / PASS**. P0 = live arming or silent mutation. P1 = residual hole that would regress a stopped gate if exercised.

Live counts at this HEAD (compiled load, yaml n=0; re-measured, not copied from `3ab87d0`):

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

Manifest digest unchanged: `sha256:6ad5ba57dfa41ed9a97e5895d9238040fbb5539b310a2ea4aa349172b6cb8c69`. `go: false`. `yaml_still_present: false`.

---

## Verdict

HEAD **still matches** the previous PASS/HOLD scoreboard at `3ab87d0` except one gate: YAML **silent** overlay is now **HOLD** (`210deb1`). Counts, +N stops, reconstitution, Phase 7, and Mass flags are unchanged at `07b4435`.

| Gate | At `3ab87d0` | At `07b4435` | Live? |
|------|--------------|--------------|-------|
| YAML silent overlay (load replaces compiled) | **P1 OPEN** | **HOLD** (`QP_ALLOW_YAML_OVERLAY` fail-closed; yaml n=0) | not live |
| YAML freeze identity still accepts n=2254 | part of C-YAML P1 | **P1 OPEN** residual (not silent; needs overlay env=`1`) | not live |
| AND-enumeration / `+N` growth | **HOLD** | **HOLD** (same SHA-class flags; `eval_flags` unmoved) | stopped |
| legacy 162 in **normal** `pilot_candidates()` | **PASS** | **PASS** (same; `pilots == active`; `pilots ∩ legacy = ∅`) | helper not wired to `start()` |
| 2092 AND rows as active/pilot universe | **P1 OPEN** | **P1 OPEN** (`8ba6ca3` labels only; n still 2092) | `start()` OFF |
| unique22 silent unpark | **HOLD** | **HOLD** (17 parked ∩ active = ∅) | no unpark |
| reconstitution auto-apply | **HOLD** | **HOLD** (`RECONSTITUTION_APPLY=False`) | no apply |
| Phase 7 `start()` | **HOLD / OFF** | **HOLD / OFF** | raises |
| Mass flags | **HOLD / NO-GO** | **HOLD / NO-GO** | deny-by-default |

**P0 unresolved at this HEAD: 0.**  
No live arming. No silent catalog mutation. Phase 7 Controlled Pilot and Mass Research remain **NO-GO**.

Do **not** recommend YAML `+N`. Do **not** recommend AND as a product. Do **not** recommend Phase 7 GO.

[`original_plan_gap.md`](original_plan_gap.md) §3: re-opening YAML `+N` or AND-as-product is a **regression**, not a return to the 08-22 combination/funds brief. §6: remaining original-plan work is human reconstitution KEEP 24df. §7: next phase is **not** Mass / READY / Phase 7.

---

## Live MCP (this isolation turn — not invented FRESH)

quant_mcp tools **were available**. Values below are this-turn reads. Projection is **STALE**. Latest READY snapshot is **null**. B0 is **UNKNOWN**. Do not narrate FRESH / READY / B0 PASS.

| Surface | Value |
|---------|--------|
| `ops_status.coverage_status_counts` | **22 COMPLETE · 4 PARTIAL** (ops_current; not a research READY snapshot) |
| `ops_status.last_run` | id 14317, `2026-08-23T23:15:01+09:00`, jquants, pass |
| `projection_status` | **STALE** |
| `active_generation` | `projgen-ef18b4f86ee946048161d25e2a30a2a8` |
| `projection_generated_at` | `2026-08-21T12:30:49.152421+00:00` |
| `projection_source_generation` | `2026-08-21T12:28:33.345482+00:00` |
| `projection_age_seconds` | 180038 (~50.0 h) |
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

[`original_plan_gap.md`](original_plan_gap.md) register — **unchanged** at this HEAD:

| # | Item | Original valid? | Still held? | Direction correction? |
|---|------|-----------------|-------------|------------------------|
| 2 | 08-22 combination/funds from simple gated theses + usable-net metric | Yes | Partial (funds thesis kept; YAML-as-product abandoned) | No further (AND product already cut) |
| 3 | AND-enumeration / YAML product / `+N` without Worker bodies | **Invalid deviation** | Stopped (`CATALOG_AND_PLUS_N_STOPPED`; YAML n=0; compiled n=2254) | **No** — re-opening YAML `+N` or AND-as-product is a regression |
| 6 | Remaining original-plan work | Human reconstitution KEEP 24df | Pending (`RECONSTITUTION_APPLY=False`) | **No** — do not substitute YAML / Mass / Phase 7 |
| 7 | Next phase = Mass / READY / Phase 7 GO | Never the original next step | **NO-GO** | **Forbidden** |

Course-correction already in tree (do not undo):

- `CATALOG_AND_PLUS_N_STOPPED=True` / `EVENT_THREE_AND_PLUS_N_STOPPED=True`
- YAML mechanical delete (`yaml_still_present: false`); overlay now fail-closed without `QP_ALLOW_YAML_OVERLAY=1`
- freeze identity compiled n=2254, digest `sha256:6ad5ba57dfa41ed9a97e5895d9238040fbb5539b310a2ea4aa349172b6cb8c69`
- known-thin unused 2-AND rewrite refused; 3-AND new batch refused
- countable = compiler row + Worker body + occupancy-equal (YAML clone does not count)

Do not: declare Phase 7 GO; recommend YAML `+N`; recommend AND as a product; silent-unpark unique22; flip `RECONSTITUTION_APPLY`; enable factory unique/combo generation.

Do: wait for human `drop_parents` vs `drop_children` on KEEP 24df; keep the freeze; keep scores on R2+D1.

---

## What moved `3ab87d0` → `07b4435`

Catalog/pilot-relevant tree (not the CI/coverage remainder of the branch):

| Commit | Effect on this lane |
|--------|---------------------|
| `210deb1` `research: catalog YAML overlay is opt-in fail-closed` | Silent YAML overlay **HOLD**. `load_catalog_specs` raises `CatalogYamlOverlayError` if any `*.yaml` is present and `QP_ALLOW_YAML_OVERLAY` is not exactly `1`. Compiled map stays load SoT. |
| `8ba6ca3` `research: active catalog count is not a pass` | Labels only. `summary()` now `go=False`, `not_a_pass=True`, `n_active_is_not_a_quality_metric=True`. **n_active still 2092.** Does not factorize. |
| `eval_flags.py` / `occupancy_guards.py` / `phase7_pilot.py` / `pilot_loop.py` / `reconstitution_evidence.py` / `research_freezes.py` | **Unmoved** vs `3ab87d0`. |
| `research-mass-eval/wrangler.toml` | Production env split + `workers_dev=false`. Freeze vars **unchanged**: `MASS_RESEARCH=NO-GO`, `PHASE7=OFF`, `READY_DECLARED=false`. |

---

## P0

None live. Constructed Mass / Pilot paths still require signed `VerifiedResearchReadiness` that production does not mint. Env `MASS_RESEARCH=GO` / `PHASE7=ON` cannot grant (`research_capabilities` `granted = False`; tests `test_env_flags_cannot_grant_pilot_start`, `test_driver_env_flags_cannot_grant`).

`QP_ALLOW_YAML_OVERLAY` is **unset** in tree and wrangler. Overlay env is not an arming switch for Mass / Phase 7.

---

## P1

### C-YAML-SILENT-OVERLAY — HOLD (was OPEN at `3ab87d0`)

- **severity:** was P1; **status HOLD** at `07b4435`
- **affected:** `packages/product/research/unique_logic/catalog.py:1-23,137-167`; tests `tests/test_unique_logic_catalog.py:195-228`
- **observed fact:** yaml n=**0**. `yaml_overlay_allowed()` is **False**. `_load_catalog_specs_cached` raises `CatalogYamlOverlayError` when yaml paths exist and overlay is not allowed; it does **not** replace the compiled map. Env must be exactly `1` (`"true"` is refused). `QP_ALLOW_YAML_OVERLAY` is not present in wrangler vars or other config files searched this turn.
- **why it matters:** [`original_plan_gap.md`](original_plan_gap.md) §3: “do not re-add YAML.” At `3ab87d0` one stray YAML replaced the compiled 2254 map for any `load_catalog_specs()` caller. That silent mutation path is **closed**.
- **not a product reopen:** opt-in overlay with env=`1` still **replaces** compiled (test `test_yaml_overlay_opt_in_replaces_compiled`). That is explicit, not silent. Do not set the env. Do not add YAML.

### C-YAML-STOP-PERMITS-FULL-READD — P1 OPEN residual

- **severity:** P1 (not P0: not live, not silent)
- **affected:** `packages/product/research/occupancy_guards.py:76-111`; `packages/product/research/catalog_compiler.py:266-294`; `packages/product/research/eval_flags.py:7-12`
- **observed fact:** `assert_catalog_and_plus_n_stopped` while stopped still **accepts yaml n>0 if n==2254**. yaml n==0 still requires compiled n==2254 (current tree). `compile_catalog(persist=True)` still compiles from `load_catalog_specs()`. A full 2254-file restore **plus** `QP_ALLOW_YAML_OVERLAY=1` would satisfy the freeze guard **and** become load SoT. A partial restore without overlay env **raises** at load (fail-closed). A partial restore with overlay env replaces compiled with n≠2254 unless the freeze assert is called.
- **why it matters:** freeze identity name is historical (`CATALOG_YAML_COUNT_AT_STOP`). [`original_plan_gap.md`](original_plan_gap.md) §3 still says do not re-add YAML. The `3ab87d0` structural ask (refuse yaml n>0 while stopped) is **not** implemented. Overlay fail-closed removed the silent path; it did not make yaml n>0 illegal.
- **structural fix (still):** while `CATALOG_AND_PLUS_N_STOPPED`, refuse yaml n>0 (require yaml n==0 and compiled n==freeze). Keep `parse_catalog_yaml` as HOLD identity. Do not add YAML. Do not set `QP_ALLOW_YAML_OVERLAY`.
- **status:** OPEN (not live; yaml n=0; overlay env unset)

### C-AND-PRODUCT-STILL-ACTIVE-PILOT — P1 OPEN (same as `3ab87d0`)

- **severity:** P1 (inherited factorize; not a new +N)
- **affected:** `packages/product/research/catalog_active.py:38-82`; `packages/product/research/phase7_pilot.py:155-167`; `specs/research_catalog/manifest.json`; [`original_plan_gap.md`](original_plan_gap.md) §3; P631 leak **G**
- **observed fact:** v2 split **still** keeps the 162 legacy IDs out of `pilot_candidates()` (unique-22 park 17 ⊂ legacy; `pilots == active`; `pilots ∩ legacy = ∅`; `tests/test_catalog_active_legacy.py:75-110`). That leak check **PASS** (same as `3ab87d0`). Active/countable/pilot helper = **2092**. `worker_implemented_logic_ids()` = **2254**. `generation_enabled` is False on all compiled rows. `8ba6ca3` added `go=False` / `not_a_pass=True` / `n_active_is_not_a_quality_metric=True` — it did **not** shrink the universe. `MassResearchScheduler.select_pilot_hypotheses` still accepts any 2–32 distinct strings (does not consult `catalog_kind` / `pilot_candidates`). `start_mass_catalog_eval` (n default 2000) still raises. `pilot_loop.start()` still raises capability-off.
- **why it matters:** 08-22 product is combination/funds from simple theses, not 2092 AND rows as inventory. Wiring `pilot_candidates()` into a live loop, or treating 2092 as a GO universe, would restore AND-as-product without flipping the +N flags.
- **structural fix:** keep +N stopped. Do not fan out 2092/2254 as Phase 7 candidates. Factorize is a dated brief, not silent unfreeze. If `select_pilot_hypotheses` is ever live, intersect with `pilot_candidates()` and refuse legacy/parked IDs.
- **status:** OPEN (factorize) / HOLD (growth stopped; `start()` OFF)

---

## HOLD confirmations (not P0; same as `3ab87d0` at SHA `07b4435`)

### YAML / AND `+N` growth — stopped

`packages/product/research/eval_flags.py:7-12` (unmoved vs `3ab87d0`):

```text
EVENT_THREE_AND_PLUS_N_STOPPED = True
CATALOG_AND_PLUS_N_STOPPED = True
CATALOG_YAML_COUNT_AT_STOP = 2254
RECONSTITUTION_APPLY = False
```

`assert_new_batch_not_event_three_and` raises on ≥3 gates while stopped. `assert_known_thin_unused_absent` refuses known-thin 2-AND rewrites. Manifest `go: false`, `yaml_still_present: false`. Combo jsonl dump has no `yaml_remains_sot`. Occupancy pack still emits `yaml_still_present: False`.

No catalog-YAML **write** path found under `packages/product/research/` this turn. Factory skips `RESEARCH_UNIQUE_LOGIC_IDS` and unique/combo `generation_enabled` stays False (`offline/factory.py:1-4,543-557`).

### unique22 — no silent unpark

Park set is code, not YAML: `UNIQUE22_PARK_REASONS` (17) == `unique22_occupancy_park()`. Lifted 5 (`afterclose_only_event_hold`, `curve_steep_event_confirm`, `event_funding_easy_short`, `event_funding_stress_skip`, `event_margin_crowding_skip`) have combo-equal `params.gates`. Parked 17 have empty gates and are **legacy**, not `pilot_candidates`. Occupancy pack `do_not_silent_unpark: True`. Worker leftover occupancy stays in `daily_path.ts:522-526,916-920` (HOLD policy; do not unify with `comboEventGateOk`). Lift predicate is `spec_gates(catalog_spec(lid))` nonempty (`worker_bodies.py:71-90`). One lifted ID (`event_funding_stress_skip`) is **legacy** via `is_near_duplicate`, not unparked. Do not delete leftover occupancy.

### reconstitution — no auto-apply

`RECONSTITUTION_APPLY` is False at eval_flags / combo_basket_catalog / occupancy_audit / reconstitution_pending / reconstitution_evidence (single SoT; `tests/test_eval_tracks.py:131-141`). `reconstitution_options` `apply_reject: False`. Preview and evidence emit **both** `drop_parents_keep_children` and `drop_children_keep_parents`. `recommended_choice` is labeled `recommended_choice_is_not_apply: True` / `do_not_auto_choose: True`. `_economics_clearly_better` can only change the recommendation, not members. `write_reconstitution_evidence_pack` refuses live R2 put (`put_r2 and not dry_run` raises; return `put_r2: False`). Human pending remains `basket_theme_fund` / `basket_event_fund` on KEEP 24df. Do not restitch 24ek.

### Phase 7 `start()` still OFF

`research.pilot_loop.start` → `ControlledPilotLoopPlan.start` → `_require_execution()` → `MassResearchDisabledError` (“controlled pilot loop remains capability-off”). Import does not construct `MassResearchScheduler`. `generation_count` must be 1; `live_orders` / `mass_fan_out` rejected at plan init. `MassResearchScheduler` is fail-closed at construct. `start_mass_catalog_eval` always raises. Tests: `tests/test_pilot_loop.py:32-45,115-129`; `tests/test_phase7_pilot_construct.py:208-213`.

Foundation docs stay **OFF**: `docs/architecture/phase7_fail_closed.md`, `docs/operations/phase7_foundation_off.md`. Gateway deployed ≠ Phase 7.

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

`research_capabilities()` always returns `data_ready/generation/mass_screen/promotion/paper_execution = False` and `go: False` (`granted = False` even when env says GO/ON). `start_mass_research` rejects `operator_override` and caller `ready_count` / `go_override`. Drivers refuse without capability. Compiled catalog `generation_enabled` all False.

---

## What this review does not do

- Does not flip `CATALOG_AND_PLUS_N_STOPPED` / `RECONSTITUTION_APPLY` / `PHASE7`.
- Does not add YAML, set `QP_ALLOW_YAML_OVERLAY`, unpark unique22, factorize 2254, or enable factory unique/combo generation.
- Does not declare Phase 6.3.1 / 6.4 COMPLETE or Phase 7 GO.
- Does not recommend YAML `+N`, AND as a product, or Phase 7 GO.
- Does not treat HOLD leftover occupancy, factory OFF, or 3 frozen pins as dead code ([`original_plan_gap.md`](original_plan_gap.md) §4).
- Does not invent Projection FRESH, B0 PASS, or READY from live MCP STALE / null / UNKNOWN.
