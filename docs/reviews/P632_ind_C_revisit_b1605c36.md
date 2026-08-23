# P632 independent review C revisit — catalog and pilot gates at `b1605c36`

**Lane:** independent C (not the implementer; isolation worktree `grok/p632-ind-C-revisit-b1605c36`; docs only)  
**HEAD:** `b1605c36` (`b1605c36e4a5f2c5048264d71baadea8589c4ed4`) (`docs: P632 verify_ci code-lane result at b5f6f2de`)  
**Prior freeze:** `b5f6f2de` (`b5f6f2ded30a2758533dfd673870c3c58799e173`) — [`P632_ind_C_revisit_b5f6f2de.md`](P632_ind_C_revisit_b5f6f2de.md) (cite, do not rewrite)  
**Earlier freezes:** `cf7da56c` — [`P632_ind_C_revisit_cf7da56c.md`](P632_ind_C_revisit_cf7da56c.md); `02fb6cbd` — [`P632_ind_C_revisit_02fb6cbd.md`](P632_ind_C_revisit_02fb6cbd.md); `2b82ec7d` — [`P632_ind_C_revisit_2b82ec7d.md`](P632_ind_C_revisit_2b82ec7d.md); `242c2484` — [`P632_ind_C_revisit_242c2484.md`](P632_ind_C_revisit_242c2484.md); `0a8ced34` — [`P632_ind_C_revisit_0a8ced34.md`](P632_ind_C_revisit_0a8ced34.md); `5103b26b` — [`P632_ind_C_revisit_5103b26b.md`](P632_ind_C_revisit_5103b26b.md); `ed94d504` — [`P632_ind_C_revisit_ed94d504.md`](P632_ind_C_revisit_ed94d504.md); `67fcbd7c` — [`P632_ind_C_revisit_67fcbd7c.md`](P632_ind_C_revisit_67fcbd7c.md); `40d1aa90` — [`P632_ind_C_revisit_40d1aa90.md`](P632_ind_C_revisit_40d1aa90.md); `f224e7e` — [`P632_ind_C_revisit_f224e7e.md`](P632_ind_C_revisit_f224e7e.md); `07b4435` — [`P632_ind_C_revisit.md`](P632_ind_C_revisit.md); `3ab87d0` — [`P632_ind_C_catalog_pilot.md`](P632_ind_C_catalog_pilot.md)  
**Cite:** [`original_plan_gap.md`](original_plan_gap.md) §§3, 6, 7  
**`origin/main` at this audit:** `b5c326a` (`b5c326a7f612563f2da4a84f08063a307ec38e0a`)  
**Code:** none. This file is detect-only. Does not YAML `+N`. Does not enable factory. Does not unpark unique22. Does not extract leftover occupancy. reconstitution APPLY false.

Mass / READY / Phase 7 Controlled Pilot / reconstitution apply: **NO-GO / OFF / false**.  
Do not invent Coverage COMPLETE, Projection FRESH, B0 PASS, READY, or GO.

Status vocabulary: **OPEN / HOLD / PASS**. P0 = live arming or silent mutation. P1 = residual hole that would regress a stopped gate if exercised.

**Catalog/pilot gates at `b1605c36` are unchanged vs `b5f6f2de`.** Research-catalog identity blobs (eval_flags, overlay load, compiler, freeze n, wrangler Mass/Phase 7, reconstitution apply, Phase 7 `start()`, factory, unique22 park, leftover occupancy Worker policy, `migration.jsonl`) are the same content. The named tree delta `de8f87bf` (`ingest: coverage addon guard ids come from catalog not a second list`) is **C12 ingest-dataset catalog SoT for the addon guard**, not a research-catalog n change. This window is that C12 SoT plus Independent A premium Worker-unit tests plus docs/review pointers; not yaml n, compiled n, overlay, `+N`, apply, unique22 park, leftover occupancy math, Phase 7 `start()`, or Mass flags. Live counts were re-measured at this HEAD, not copied.

Live counts at this HEAD (compiled map on disk, yaml n=0; re-measured):

| Surface | n |
|---------|--:|
| YAML `specs/research_logics/*.yaml` | **0** |
| compiled `migration.jsonl` / freeze `CATALOG_YAML_COUNT_AT_STOP` | **2254** |
| `generation_enabled=True` compiled rows | **0** |
| unique-22 leftover | **22** (17 parked + 5 occupancy-equal lifts) |
| `UNIQUE22_PARK_REASONS` keys | **17** |
| occupancy-equal lifted IDs present in compiled map | **5** |
| `yaml_overlay_allowed()` (`QP_ALLOW_YAML_OVERLAY`) | **False** (env must be exactly `1`; unset here; not in wrangler) |

Manifest digest unchanged: `sha256:6ad5ba57dfa41ed9a97e5895d9238040fbb5539b310a2ea4aa349172b6cb8c69`. `go: false`. `yaml_still_present: false`. Compact `family + template + parameter matrix` still **NOT** done (`migration.jsonl` remains 2254 expanded rows; **HOLD**).

C12 addon ids (`de8f87bf`): `_ADDON_IDS = frozenset(list_datasets("addon"))` from `ingestion.jquants.catalog` (five addon ids: `equities_bars_minute`, `equities_trades`, `td_list`, `td_files`, `td_bulk`). That is ingest catalog SoT for the C12 guard. It does **not** change research-catalog compiled n=2254.

---

## Verdict

HEAD **still matches** the previous PASS/HOLD scoreboard at `b5f6f2de`. Counts, `+N` stops, reconstitution apply, Phase 7, Mass flags, YAML overlay fail-closed, unique22 park occupancy, leftover occupancy HOLD, and compact-catalog-not-done are **unchanged**. C12 addon-id SoT is **not** a catalog n reopen. P0 unresolved for catalog/pilot is **0**. That is **not** Phase 7 GO.

| Gate | At `b5f6f2de` | At `b1605c36` | Live? |
|------|---------------|---------------|-------|
| YAML silent overlay (load replaces compiled) | **HOLD** (`QP_ALLOW_YAML_OVERLAY` fail-closed; yaml n=0) | **HOLD** (same; overlay env unset) | not live |
| YAML freeze identity still accepts n=2254 | **P1 OPEN** residual (not silent; needs overlay env=`1`) | **P1 OPEN** residual (same) | not live |
| AND-enumeration / `+N` growth | **HOLD** | **HOLD** (`eval_flags` unmoved) | stopped |
| yaml n / compiled n | 0 / 2254 | **0 / 2254** | freeze held |
| reconstitution auto-apply | **HOLD** (`RECONSTITUTION_APPLY=False`) | **HOLD** (`RECONSTITUTION_APPLY=False`) | no apply |
| Phase 7 `start()` | **HOLD / OFF** | **HOLD / OFF** | raises |
| Mass flags | **HOLD / NO-GO** | **HOLD / NO-GO** | deny-by-default |
| YAML overlay `yaml_overlay_allowed()` | **False** | **False** | env unset; not in wrangler |
| unique22 silent unpark | **HOLD** | **HOLD** (17 parked keys unmoved) | no unpark |
| leftover occupancy unify with `comboEventGateOk` | **HOLD** | **HOLD** (`daily_path.ts` leftover comments unmoved) | do not unify |
| compact family+template+parameter matrix | **HOLD** (not done) | **HOLD** (not done) | freeze n=2254 |
| C12 addon ids from catalog | n/a (landed this window) | **PASS** as ingest SoT (`de8f87bf`); **not** a research-catalog n change | C12 guard only |

**P0 unresolved at this HEAD: 0.**  
No live arming. No silent catalog mutation. Phase 7 Controlled Pilot and Mass Research remain **NO-GO**. P0=0 is **not** a Phase 7 GO.

Do **not** recommend YAML `+N`. Do **not** recommend AND as a product. Do **not** recommend Phase 7 GO. Do **not** recommend unique22 unpark. Do **not** recommend unifying leftover occupancy with `comboEventGateOk`. Do **not** treat C12 addon-catalog SoT as compiled n drift.

[`original_plan_gap.md`](original_plan_gap.md) §3: re-opening YAML `+N` or AND-as-product is a **regression**, not a return to the 08-22 combination/funds brief. §6: remaining original-plan work is human reconstitution KEEP 24df. §7: next phase is **not** Mass / READY / Phase 7.

---

## Live MCP (this isolation turn)

quant_mcp servers were listed as connected on the parent session. This independent-C turn did **not** copy MCP numbers from [`P632_ind_C_revisit_b5f6f2de.md`](P632_ind_C_revisit_b5f6f2de.md). Do not invent Projection FRESH, B0 PASS, or READY. Last-known-good narrative in the prior freeze remains **22 COMPLETE · 4 PARTIAL** under STALE V2 floors; this file is not a ledger refresh and is not a catalog GO.

---

## Original 08-22 plan vs AND product (cite)

[`original_plan_gap.md`](original_plan_gap.md) register — **unchanged** at this HEAD (banner still names `b5f6f2de`, the prior window’s pointer; this lane does not rewrite it; body freeze remains `e927b97`):

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

## What moved `b5f6f2de` → `b1605c36` (this lane)

`git rev-list --count b5f6f2de..b1605c36` = **16** (GitHub compare `ahead_by: 16`; `origin/grok/phase63-ci-source-closure` = `b1605c36`). Research-catalog identity files for yaml n, compiled n, overlay, `+N`, reconstitution apply, Phase 7 `start()`, unique22 park, leftover occupancy Worker policy, and Mass flags are **unmoved** vs `b5f6f2de`:

`eval_flags.py`, `occupancy_guards.py`, `unique_logic/catalog.py`, `catalog_active.py`, `catalog_compiler.py`, `phase7_pilot.py`, `pilot_loop.py`, `reconstitution_evidence.py`, `reconstitution_pending.py`, `combo_basket_catalog.py`, `eval_tracks.py`, `occupancy_audit.py`, `unique_logic/worker_bodies.py`, `research_freezes.py`, `research_capabilities.py`, `offline/factory.py`, `platform/workers/research-mass-eval/wrangler.toml`, `specs/research_catalog/manifest.json`, `specs/research_catalog/migration.jsonl`, `daily_path.ts`.

No YAML added. No compiled n change. C12 is ingest addon-id SoT, not research-catalog n.

| File | Commit | Effect on this lane |
|------|--------|---------------------|
| `packages/edge/cf_platform/ingest_premium/coverage.py`, `tests/test_phase35_coverage_daily.py` | `de8f87bf` (coverage addon guard ids come from catalog not a second list) | **C12 ingest catalog SoT.** `_ADDON_IDS = frozenset(list_datasets("addon"))`. Not yaml n, compiled n, overlay, `+N`, reconstitution apply, unique22 park, leftover occupancy, Phase 7, or Mass. |
| `platform/workers/ingestion-premium/src/ops_cold_archive.test.ts` | `9956ab51` (premium cold-archive token and args fail-closed Worker unit) | Independent A / ingest tests. Not catalog/pilot n. |
| `platform/workers/ingestion-premium/src/ops_prune_changelog.test.ts` | `9b0582d4` (premium changelog prune unbound token is 401) | Independent A / ingest tests. Not catalog/pilot n. |
| `platform/workers/ingestion-premium/src/ops_parquet_manifest.test.ts` | `359b2566` (premium parquet-manifest unbound token is 401) | Independent A / ingest tests. Not catalog/pilot n. |
| `platform/workers/ingestion-premium/src/ops_artifacts_plan.test.ts` | `329f3959` (premium artifacts-plan token fail-closed Worker unit) | Independent A / ingest tests. Not catalog/pilot n. |
| `platform/workers/ingestion-premium/src/master_scd2/write.test.ts` | `ee167188` (premium master SCD2 write Worker unit with mock R2) | Independent A / ingest tests. Not catalog/pilot n. |

`daily_path.ts` leftover occupancy comments (including “not comboCsGateOk” / “Do not drop without occupancy-equal re-eval”) are **unmoved**. Do not recommend extract-or-unify.

| Commit | Effect on this lane |
|--------|---------------------|
| `ad87f867` `docs: independent review C catalog/pilot revisit at b5f6f2de` | Prior C revisit text. Not a gate change. |
| `1a932405` / `01b5aacc` Independent A–B revisit at `b5f6f2de` | Other lanes. Not catalog/pilot n. |
| `21aafef2` `docs: banner original-plan-gap register still holds at b5f6f2de` | Pointer only. Body freeze remains `e927b97`. Not a gate change. |
| `9254a436` / `90fe27b9` / `20696033` residual SoT banner / §10 remaining mixed / review index names | Pointers only. Not a gate change. |
| `8e363940` / `e1b31a42` / `b1605c36` wave-13 status / test inventory / verify_ci at `b5f6f2de` | Docs. Not yaml n, compiled n, AND stop, reconstitution apply, Phase 7, Mass, overlay, unique22 park, or leftover occupancy. |

---

## P0

None live. Constructed Mass / Pilot paths still require signed `VerifiedResearchReadiness` that production does not mint. Env `MASS_RESEARCH=GO` / `PHASE7=ON` cannot grant (`research_capabilities` `granted = False` even when those env keys are set; remaining deny reason includes `verified_readiness_missing`). Tests still pin `test_env_flags_cannot_grant_pilot_start`, `test_driver_env_flags_cannot_grant`.

`QP_ALLOW_YAML_OVERLAY` is **unset** in this process and is **not** present in wrangler vars (top-level or `[env.production.vars]`). Overlay env is not an arming switch for Mass / Phase 7.

C12 addon SoT does not arm Mass / Phase 7 and does not mutate research-catalog n.

P0=0 on catalog/pilot is **not** Phase 7 GO.

---

## P1 (same as `b5f6f2de`)

### C-YAML-SILENT-OVERLAY — HOLD

- **severity:** was P1 at `3ab87d0`; **status HOLD** at `b5f6f2de` and **HOLD** at `b1605c36`
- **affected:** `packages/product/research/unique_logic/catalog.py:1-26,140-169`; tests `tests/test_unique_logic_catalog.py:195-228`
- **observed fact:** yaml n=**0**. `yaml_overlay_allowed()` is **False** unless `QP_ALLOW_YAML_OVERLAY` is exactly `1`. `_load_catalog_specs_cached` raises `CatalogYamlOverlayError` when yaml paths exist and overlay is not allowed; it does **not** replace the compiled map. Env `"true"` is refused.
- **not a product reopen:** opt-in overlay with env=`1` still **replaces** compiled (test `test_yaml_overlay_opt_in_replaces_compiled`). That is explicit, not silent. Do not set the env. Do not add YAML.

### C-YAML-STOP-PERMITS-FULL-READD — P1 OPEN residual

- **severity:** P1 (not P0: not live, not silent)
- **affected:** `packages/product/research/occupancy_guards.py:76-111`; `packages/product/research/catalog_compiler.py:266-294`; `packages/product/research/eval_flags.py:7-12`
- **observed fact:** `assert_catalog_and_plus_n_stopped` while stopped still **accepts yaml n>0 if n==2254**. yaml n==0 still requires compiled n==2254 (this tree: freeze `CATALOG_YAML_COUNT_AT_STOP=2254`, `yaml_still_present=false`, compiled lines=2254). A full 2254-file restore **plus** `QP_ALLOW_YAML_OVERLAY=1` would satisfy the freeze guard **and** become load SoT.
- **status:** OPEN (not live; yaml n=0; overlay env unset). Same as `b5f6f2de`.

### C-AND-PRODUCT-STILL-ACTIVE-PILOT — P1 OPEN

- **severity:** P1 (inherited factorize; not a new `+N`)
- **affected:** `packages/product/research/catalog_active.py:38-82`; `packages/product/research/phase7_pilot.py:155-167`; `specs/research_catalog/manifest.json`; [`original_plan_gap.md`](original_plan_gap.md) §3
- **observed fact:** `pilot_candidates()` still returns `active_logic_ids()` only. `generation_enabled` is False on all compiled rows (zero `"generation_enabled":true` in `migration.jsonl`). `summary()` still `go=False` / `not_a_pass=True` / `n_active_is_not_a_quality_metric=True`. `MassResearchScheduler.select_pilot_hypotheses` still accepts any 2–32 distinct strings. `MassResearchScheduler.start_mass_catalog_eval` still raises. `pilot_loop.start()` still raises capability-off. Compact family+template+parameter matrix is still **not** done.
- **status:** OPEN (factorize) / HOLD (growth stopped; `start()` OFF; compact matrix not done). Same as `b5f6f2de`. AND-as-product remains **invalid**.

---

## HOLD confirmations (re-measured at `b1605c36`; same as `b5f6f2de`)

### YAML / AND `+N` growth — stopped

`packages/product/research/eval_flags.py:7-12`:

```text
EVENT_THREE_AND_PLUS_N_STOPPED = True
CATALOG_AND_PLUS_N_STOPPED = True
CATALOG_YAML_COUNT_AT_STOP = 2254
RECONSTITUTION_APPLY = False
```

Working tree `specs/research_logics/` has **no** `*.yaml` (README only; directory empty of YAML). `specs/research_catalog/migration.jsonl` has **2254** lines (last `logic_id` `xs_margin_delta_rank`). Manifest: `n=2254`, `yaml_still_present: false`, `go: false`, digest `sha256:6ad5ba57dfa41ed9a97e5895d9238040fbb5539b310a2ea4aa349172b6cb8c69`. Zero compiled rows with `generation_enabled: true`.

Factory skips `RESEARCH_UNIQUE_LOGIC_IDS`; unique/combo `generation_enabled` stays False (`offline/factory.py:1-4,543-557`).

### unique22 / leftover occupancy — no silent unpark; do not unify

Park set is code, not YAML. `UNIQUE22_PARK_REASONS` has **17** keys, equal to `unique22_occupancy_park()` identity (`unique_leftover_logic_ids() - unique22_occupancy_equal_lifted()`). Lifted 5 compiled rows with `occupancy_equal_combo_gate` still present: `afterclose_only_event_hold`, `curve_steep_event_confirm`, `event_funding_easy_short`, `event_funding_stress_skip`, `event_margin_crowding_skip`. Leftover unique-22 = **22** (17 parked + 5 occupancy-equal). Do not silently unpark.

`unique22_occupancy_park()` still documents: park reasons live in `UNIQUE22_PARK_REASONS`; leftover occupancy stays in `daily_path.ts`; **do not unify with `comboEventGateOk`**. `daily_path.ts` leftover occupancy Worker policy is **unmoved** (comments at `916-920` still “not comboCsGateOk” / “Do not drop without occupancy-equal re-eval”). Do not delete leftover occupancy. Do not recommend unpark. Do not recommend unify.

### reconstitution — no auto-apply

`RECONSTITUTION_APPLY` is False at eval_flags / combo_basket_catalog / reconstitution_pending / reconstitution_evidence (single SoT). KEEP 24df still needs reconstitution: `basket_theme_fund` and `basket_event_fund` (`HUMAN_RECONSTITUTION_PENDING`). Pending pack still `do_not_auto_choose: True` / `apply` gated on `RECONSTITUTION_APPLY`. Do not restitch 24ek.

### Phase 7 `start()` still OFF

`research.pilot_loop.start` calls `_require_execution()`, which raises `MassResearchDisabledError` (“controlled pilot loop remains capability-off”) because `research_capabilities()` never grants. `MassResearchScheduler.start_mass_catalog_eval` always raises. Foundation docs stay **OFF**. Gateway deployed ≠ Phase 7.

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

`yaml_overlay_allowed()` is **False** unless `QP_ALLOW_YAML_OVERLAY` is exactly `1`. Env unset. No wrangler `QP_ALLOW_YAML_OVERLAY`. Load without env=`1` refuses any `*.yaml` overlay (`CatalogYamlOverlayError`). Current yaml n=0 so compiled `migration.jsonl` is load SoT (2254 rows).

### Compact catalog matrix — still NOT done (HOLD)

Compact `family + template + parameter matrix` is **not** implemented. `specs/research_catalog/migration.jsonl` is still 2254 expanded rows and still load SoT. Freeze n=2254 is **HOLD**. Do not report 2254 as a product win. Do not YAML `+N` as a substitute.

### C12 addon ids from catalog — not a catalog n change

`de8f87bf` replaced a hardcoded five-id frozenset in `coverage.py` with `list_datasets("addon")`. Test `test_C12_guarded_ids_match_catalog_addon_group` freezes the ingest addon group. That is **dataset-catalog SoT for C12**, not `specs/research_catalog/migration.jsonl` n. Do not narrate it as compiled n=2254 drift or as Phase 7 GO.

---

## What this review does not do

- Does not flip `CATALOG_AND_PLUS_N_STOPPED` / `RECONSTITUTION_APPLY` / `PHASE7`.
- Does not add YAML, set `QP_ALLOW_YAML_OVERLAY`, unpark unique22, unify leftover occupancy with `comboEventGateOk`, factorize 2254, or enable factory unique/combo generation.
- Does not declare Phase 6.3.1 / 6.4 COMPLETE or Phase 7 GO.
- Does not recommend YAML `+N`, AND as a product, or Phase 7 GO.
- Does not treat HOLD leftover occupancy, factory OFF, or 3 frozen pins as dead code ([`original_plan_gap.md`](original_plan_gap.md) §4).
- Does not invent Projection FRESH, B0 PASS, or READY.
- Does not treat catalog/pilot P0=0 as Phase 7 GO.
- Does not treat C12 addon-catalog SoT as a research-catalog n change.
- Does not rewrite [`P632_ind_C_revisit_b5f6f2de.md`](P632_ind_C_revisit_b5f6f2de.md) or README.
