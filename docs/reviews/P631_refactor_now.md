# Phase 6.3.1 — current mixed-authority snapshot (after 6.3 extracts)

**Kind:** current snapshot. Does **not** rewrite
[`phase63_refactor_plan.md`](../phase63_refactor_plan.md) (historical plan at
`41003a5` / `a527a3a`).  
**Tip measured:** `e927b97` (`docs: persist 6.3.1 remaining-audit findings after wave-1 fixes`)  
**Mass / READY / Phase 7:** unchanged (NO-GO / not declared / OFF)  
**Leftover occupancy:** **HOLD** in `daily_path.ts`  
**`RECONSTITUTION_APPLY`:** **False**  
Do not invent COMPLETE. Do not add YAML. Do not hand-edit `catalog_ids.ts`.
Do not rewrite live math. Do not introduce `quant_platform.*` (Batch Z still DEFER).

This snapshot classifies **what is large now** after the 6.3 authority extracts.
Size is not a split key. Live math stays together even at 2k LOC.

Paired: historical plan [`phase63_refactor_plan.md`](../phase63_refactor_plan.md);
tests [`phase63_test_audit.md`](../phase63_test_audit.md);
layout [`architecture/adr_llm_friendly_refactor.md`](../architecture/adr_llm_friendly_refactor.md).
Residual SoT remains [`phase62_residual_status.md`](../phase62_residual_status.md)
(not edited here).

---

## 1. Measure (`git ls-files`)

Exclude `node_modules` and generated `catalog_ids.ts` from the ranking.
`wc -l` on tracked `*.py` / `*.ts` / `*.tsx`.

| Count | Value |
|-------|------:|
| Tracked paths | **658** |
| Catalog YAML (`specs/research_logics/*.yaml`) | **0** |
| Tracked YAML remaining | **1** (`specs/research_themes.yaml` — themes, not catalog logics) |
| py+ts LOC (excl. `node_modules`, `catalog_ids.ts`) | **121128** |
| Generated `catalog_ids.ts` (excluded from rank) | **2327** |

### Top ~25 py/ts (excl. `catalog_ids.ts`)

| LOC | Path | Class now |
|----:|------|-----------|
| 2210 | `packages/product/research/cost_models.py` | **KEEP** live math |
| 1806 | `platform/workers/research-mass-eval/src/eval.ts` | **KEEP** family math (`eval_orchestrate.ts` DONE) |
| 1677 | `platform/workers/research-mass-eval/src/daily_path.ts` | leftover occupancy **HOLD** + live math **KEEP** |
| 1624 | `packages/edge/cf_platform/ingest_premium/coverage.py` | **KEEP** evidence |
| 1350 | `platform/workers/ingestion-premium/src/index.ts` | remaining fetch / upsert / HTTP; receipts DONE |
| 1295 | `packages/data_plane/storage/coverage_ledger.py` | persist extracts DONE; COMPLETE predicates stay |
| 1140 | `packages/product/research/options_225_vol_series.py` | **KEEP** live math |
| 990 | `packages/product/research/offline/multiyear_report.py` | already split from `multiyear.py`; **KEEP** presentation |
| 958 | `packages/research_runtime/paper_runtime/snapshot.py` | remaining façade; publication SQL still mixed |
| 873 | `packages/product/research/offline/factory_eval.py` | already split from `factory.py`; **KEEP** offline eval |
| 841 | `packages/product/research/eval_loaders_sidecars.py` | already split loaders; **KEEP** (do not per-dataset) |
| 811 | `platform/workers/research-ai-gateway/src/schema.ts` | **KEEP** presentation schema |
| 795 | `packages/product/research/stats_metrics.py` | **KEEP** live math |
| 788 | `platform/workers/research-mass-eval/src/combo_gates.ts` | **already extracted** combo-gate policy |
| 786 | `packages/research_runtime/features/minimal_signal.py` | **KEEP** live math |
| 784 | `packages/product/research/unique_logic/constants.py` | **KEEP** policy |
| 782 | `packages/product/research/offline/factory.py` | **KEEP** generation (eval already split) |
| 752 | `tests/test_cf_propose_thesis.py` | **Invariant** (looks large; keep) |
| 744 | `packages/product/research/offline/multiyear.py` | **KEEP** offline stitch (report already split) |
| 742 | `scripts/sync_d1_to_sqlite.py` | script driver; not a mixed-authority split |
| 732 | `packages/product/research/unique_logic/propose_review_tables.py` | **KEEP** policy tables (Worker copy generated) |
| 718 | `packages/product/research/combo_basket_catalog.py` | reconstitution **APPLY false**; not extract |
| 710 | `packages/product/research/cf_propose_thesis.py` | **KEEP** propose (no catalog write / no GO) |
| 706 | `platform/workers/research-mass-eval/src/index.ts` | remaining HTTP + job orchestration |
| 693 | `packages/product/research/occupancy_audit.py` | **KEEP** occupancy evidence (not GO) |

Also (excluded from rank, still listed):

| LOC | Path | Class |
|----:|------|-------|
| 2327 | `platform/workers/research-mass-eval/src/catalog_ids.ts` | **GENERATED.** Do not hand-edit |
| 165 | `packages/data_plane/data_contracts/coverage.py` | **KEEP** policy (contract grain). Not the C-check module |

`r2_feature_context.py` is **658** after parse / normalize / `available_at` / get / mirror extracts. Remaining `build_*_context` orchestration **KEEP**.

---

## 2. Authority rule (unchanged)

Keep **one** of these authorities per module. A file may *import* others; it
must not *own* a second.

| Authority | Owns | Must not own |
|-----------|------|----------------|
| **parsing** | Bytes / JSONL → typed fields | Canonical keys, gates, writes |
| **normalization** | Canonical dates, keys, row shape, no-invent fills | HTTP, D1/R2 writes, COMPLETE |
| **evidence** | Receipts, digests, coverage proofs, C-checks | Policy that *decides* COMPLETE/READY; HTTP routing |
| **policy** | Gates, leftover occupancy, COMPLETE/READY/Mass fail-closed | Live PnL math; persistence I/O |
| **persistence** | SQLite / D1 / R2 put-get, ledger refresh writes | Gate predicates; HTTP path dispatch |
| **orchestration** | Job fan-out, `ingestOne` / `runIngestion`, isolate scheduling | Formula bodies; catalog generation |
| **presentation** | HTTP/MCP JSON, cell packs, reports | Receipt crypto; PIT entry math |

**Live math is not an 8th authority to extract.** Transaction / vol / MTM
formulas stay in one place even at 2k LOC. Splitting a numerator from its
denominator is a rewrite dressed as a refactor.

---

## 3. Already extracted (6.3 — do not re-merge)

| Sibling | LOC | Authority taken | Left behind |
|---------|----:|-----------------|-------------|
| `combo_gates.ts` (+ `combo_gates.test.ts`) | 788 (+467) | combo-gate **policy** | leftover occupancy in `daily_path.ts` |
| `event_entry.ts` (+ test) | 30 (+26) | PIT **disc-time** (`discTimeKnown` / `afterClose` / `pitEventEntryShift`) | `pitMedian` / unique-22 lid branches stay in `daily_path.ts` |
| `eval_orchestrate.ts` | 235 | period **orchestration** (`evaluateLogicAcrossPeriods`, `rankSurvivors`) | family formulas in `eval.ts` |
| `r2_feature_parse.py` | 101 | **parsing** | `build_*_context` orchestration |
| `r2_feature_normalize.py` | 176 | **normalization** | same |
| `r2_available_at.py` | 113 | `available_at` **policy** (research-only) | same |
| `r2_io.py` | 199 | R2 get **persistence** | same |
| `r2_feature_mirror.py` | 201 | scratch sqlite **persistence** | same |
| `coverage_ledger_io.py` | 199 | record/read **persistence** | COMPLETE predicates in `coverage_ledger.py` |
| `coverage_receipts.py` | 147 | receipt **evidence** builders | eligibility / evaluate stay |
| `snapshot_publish_policy.py` | 190 | READY fail-closed **policy** | façade + remaining SQL |
| `snapshot_coverage_proof.py` | 219 | Coverage V2 **evidence** | façade |
| `snapshot_persist.py` | 40 | file copy / `_atomic_json` **persistence** | BUILDING/SYNCED SQL still in `snapshot.py` |
| `snapshot_read.py` | 104 | list/describe **presentation** | façade |
| `collection_receipts.ts` | 111 | Premium receipt **evidence** | fetch / upsert / HTTP in `index.ts` |
| compiler emit of `catalog_ids.ts` | 2327 | generated **presentation** of policy IDs | **DONE**; do not re-emit / hand-edit |
| digest lock `sha256:6ad5ba57dfa41…` | — | identity pin | **DONE**; do not re-run |
| catalog YAML delete | 0 files | files only | **DONE**; `yaml_still_present: false`; do not re-add |

Earlier (pre-6.3) siblings — **do not re-merge:** `mdh_collapse.ts`,
`path_broken.ts`, `metrics.ts`, `cost_repo.py`, `cost_defaults.py`,
`eval_loaders.py`, `eval_loaders_bars.py`, Premium `identity.ts` /
`availability.ts` / `catalog.ts` / rate-limit / SCD2 write / ops archive-prune,
`multiyear_report.py`, `factory_eval.py`.

---

## 4. Large files — KEEP vs remaining mix vs HOLD

### KEEP live math (do not fake-split)

**`cost_models.py` (2210).** Transaction + short-borrow + leverage financing.
`cost_repo.py` / `cost_defaults.py` already hold series I/O and literals.
Remaining body is the live modulation. No extract lane.

**`options_225_vol_series.py` (1140).** BaseVol / ATM IV / skew / CM-term /
ΔBaseVol. Missing days omit (no ffill / no invent). Splitting `_atm_iv_at_cm`
from `build_daily_skew_series` is fake-split. No extract lane.

**`eval.ts` (1806).** Bar-native family evaluators + `barNativeHeldBook` +
`evalLogicOnPanel`. Orchestration already in `eval_orchestrate.ts`. Do not
family-slice `evalFlowDemand` / `evalFundPrice` / `evalNkyVolRegime`.

**`stats_metrics.py` (795), `minimal_signal.py` (786),
`unique_logic/event.py`, `unique_logic/cross_section.py`, `core/engine.py`.**
Research math. Not GO.

### `daily_path.ts` (1677) — leftover occupancy HOLD + live math KEEP

Candidate-grade SoT remains `POST /v1/daily-path`. Combo gates and PIT
disc-time already live in siblings. What remains:

| Region | Authority | Now |
|--------|-----------|-----|
| `comboEventGateOk` / `comboCsGateOk` / `comboGatesImplemented` / `clusterWindowSeries` | combo-gate **policy** | **extracted** → `combo_gates.ts` |
| `discTimeKnown` / `afterClose` / `pitEventEntryShift` | PIT **entry** | **extracted** → `event_entry.ts` |
| `if (!comboImpl) { lid === "event_pre_mom_agree_hold" … }` and leftover CS books (`xs_margin_delta_rank`, `xs_low_vol_mom`, `idio_mom_macro_impulse`) | leftover occupancy **policy** | **HOLD** in this file |
| `equityPathDrawdown` / `heldBookDailyMtm` / `stickyHold` / `csRank` / `pitMedian` | **live math KEEP** | occupancy *fraction* is measured here; leftover *policy* is not |
| `evalLogicDailyPathOnPanel` / `cellsFromPeriodPacks` | orchestration / presentation | façade; may stay |

`catalog_ids.ts` header still says leftover occupancy stays in `daily_path.ts`.
Unifying leftover with `comboEventGateOk` is a rewrite (widens or thins
occupancy). Duplicate `surpriseProxy` (daily_path leftover vs combo_gates) is
**not** a cleanup lane.

### KEEP evidence / policy (not mixed enough to split)

**`coverage.py` (edge, 1624).** C1–C12 / B0 measurements. `run_coverage` may
stay as the orchestrator of checks. Do not make `c1.py`…`c12.py`.

**`data_contracts/coverage.py` (165).** Contract fields, event vs calendar
grain. Leave it. Do not merge into the ledger or the C-check module.

**`unique_logic/constants.py` (784).** Gates, parks, propose allow-list.
Family ID unions come from the compiled catalog via
`unique_family_ids_from_yaml` (name kept). Do not explode park lists into
YAML clones.

**`propose_review_tables.py` (732).** Policy tables copied into
`propose_review_tables.ts` by `scripts/sync_cf_new_thesis_ids.py`. Do not
hand-edit the Worker copy.

**`eval_loaders_sidecars.py` (841).** Remaining loaders after
`eval_loaders.py` / `eval_loaders_bars.py`. Splitting by dataset is fake-split.

**`schema.ts` (811).** Strict AI Gateway typed artifacts. Unknown fields
rejected. KEEP.

**`combo_basket_catalog.py` (718).** Mechanical sleeves. Nested parents are
**detected**, not auto-chosen. `RECONSTITUTION_APPLY` is **False**. Human
pending ids stay `HUMAN_RECONSTITUTION_PENDING`. Not an extract lane; not APPLY.

**`r2_feature_context.py` (658).** Remaining `build_*_context` orchestration
after 6.3 extracts. KEEP.

**`occupancy_audit.py` (693).** Occupancy evidence. This tip emits
`yaml_still_present: False` (no `yaml_remains_sot`). Not GO.

### Remaining mixed (next extract candidates)

**`ingestion-premium/src/index.ts` (1350).** Receipts already in
`collection_receipts.ts`. Worker **package path frozen** (siblings in the
same worker are allowed; do not move `platform/workers/**`). Remainder still
mixes:

| Piece | Authority |
|-------|-----------|
| `fetchDataset` / `fetchOnePage` / retry | **orchestration** (network) |
| `upsertRecords` / `upsertWatermark` / `writeValidation` | **persistence** |
| `handleHealth` / `handleRun` / `handleExport*` / `export default` | **presentation** |
| `ingestOne` / `runIngestion` | **orchestration** façade |

Natural-key / `available_at` stay in `identity.ts` / `availability.ts`.

**`coverage_ledger.py` (1295).** `record_*` / `read_*` already in
`coverage_ledger_io.py`; receipt builders in `coverage_receipts.py`.
`evaluate_segment` / `plan_required_segments` / `is_complete_eligible_receipt`
stay **policy**. Remainder still mixes persist writes into refresh:

- `refresh_coverage_ledger` `BEGIN IMMEDIATE` + `executemany` DELETE/INSERT
- `sync_dataset_coverage_from_segments` inventory writes

**`snapshot.py` (958).** Policy / proof / file-copy / read already extracted.
`publish_ready_snapshot` is the façade, but it still owns publication SQL
(`INSERT` BUILDING/SYNCED, `begin_snapshot_sync` / `fail_snapshot_sync` /
`commit_snapshot_manifest`) plus sqlite state builders
(`_schema_state` / `_watermark_state` / `_validation_state` /
`_fact_table_state`). READY fail-closed stays in `snapshot_publish_policy.py`.

**`research-mass-eval/src/index.ts` (706).** `http.ts` already has
`authorized` / `json` / children-then-manifest. Remainder mixes route
`fetch` (**presentation**) with `runMassEval` / `runDailyPath`
(**orchestration**). Same worker path frozen.

---

## 5. YAML-named aliases that are implementation names, not waste

Compiled map is catalog SoT (`specs/research_catalog/`; yaml n=0). Function
**names** still say yaml. That is identity, not leftover files. Do **not**
rename-chase. Do **not** edit `unique_logic/catalog.py` in this snapshot.

| Name | Alias / role |
|------|----------------|
| `unique_family_ids_from_yaml` | `unique_family_ids_from_catalog` — family ID unions from compiled catalog |
| `yaml_combo_rows` | `combo_rows_from_catalog` |
| `combo_row_from_yaml` | `combo_row_from_spec` |
| `unique_row_from_yaml` / `yaml_unique_rows` | unique-row load from compiled specs |
| `yaml_still_present` / `yaml_files_present` | status flag (false today) |
| `assert_yaml_matches_specs` | identity self-check (compiled vs constants) |
| `test_catalog_yaml_parity.py` | identity set-equality filename; freeze n=2254 |
| `CATALOG_YAML_COUNT_AT_STOP` (2254) | freeze identity n; yaml n=0 requires compiled n=2254 |

Combo AND +N expansion stays **HOLD** (`CATALOG_AND_PLUS_N_STOPPED`). Runtime
names `yaml_combo_rows` / `combo_row_from_yaml` after YAML deletion are not
D-dead.

---

## 6. Tests that look excessive but are invariants

Do not treat test count as a win. Do not delete these because they look
combinatorial. Cite [`phase63_test_audit.md`](../phase63_test_audit.md).

| Surface | Why it stays |
|---------|----------------|
| PIT / `available_at` / as_of | `test_available_at.py`, `test_pit_as_of.py`, `test_pit_lookahead.py`, `test_pit_coverage.py`, `test_pipeline_pit_timestamps.py`, `test_phase61_pit_pagination.py`, COMPLETE-21 PIT rows in `test_complete21_min_compute.py` |
| Receipts | `test_coherence_with_receipts.py`, `test_issue_receipts_parallel.py`, `test_jquants_receipt_emit.py`, `test_phase623_receipt_signature.py`, `test_receipt_eligibility.py` |
| false-COMPLETE | `test_complete22_health.py` (invent COMPLETE 23 fails), `test_sticky_complete_segment_id_fallback.py`, empty-raw ban inside receipt issue |
| `test_baseline_catalog.py` | Rejected S1–S5; Mass/READY false. **Do not delete.** |
| Mass / gateway fail-closed | `test_mass_research_gate.py`, `test_gateway_fail_closed.py`, `test_mass_strategy_factory.py` |
| Py↔TS execution parity | `test_identity_runtime_parity.py` (**Invariant**, not echo) |
| Immutable READY / create-only | `test_immutable_artifact.py` |
| Catalog identity | `test_catalog_yaml_parity.py` set-equality + digest; not a second 2254-file walk |
| Propose | `test_cf_propose_thesis.py` (752) — no catalog write, no auto_inject, no GO. Phrase table is data, not a second policy |

Worker `combo_gates.test.ts` is SoT for Worker gate policy. Dual-runtime
**echo** (Python greps of Worker leftover occupancy) stays dropped
(`ed0a2cb`). Do not add it back.

Guard pack on every later extract: Mass fail-closed, gateway fail-closed,
plane import boundaries, publish guard, PIT look-ahead / `as_of`, receipt
eligibility. No ingestion-premium combinatorics to “cover the split”.

---

## 7. Next extract lanes (sequenced, one authority each)

Each row is one revert unit. No mixed “rename + behavior change”.
No Mass / READY / Phase 7 arming. Leftover occupancy is **not** in this
queue.

| Order | Lane | Authority moved | Must not move |
|------:|------|-----------------|---------------|
| 1 | Premium HTTP handlers from `ingestion-premium/src/index.ts` (sibling in **same** worker) | **presentation** (`handleHealth` / `handleRun` / `handleExport*` / `export default` dispatch) | `fetchDataset` / `upsertRecords`; Worker package path |
| 2 | Premium D1 upsert / watermark / validation writes from the same `index.ts` | **persistence** | `ingestOne` / `runIngestion` / `fetchDataset` façade; `identity.ts` / `availability.ts` |
| 3 | Snapshot publication SQL into `snapshot_persist.py` (or persist sibling) | **persistence** (`begin_snapshot_sync` / `fail_snapshot_sync` / `commit_snapshot_manifest` / BUILDING–SYNCED rows) | READY gate (`snapshot_publish_policy.py`); `publish_ready_snapshot` façade |
| 4 | Coverage ledger refresh/sync **writes** into `coverage_ledger_io.py` | **persistence** (`refresh_coverage_ledger` executemany; `sync_dataset_coverage_from_segments` writes) | `evaluate_segment` / `plan_required_segments` / `is_complete_eligible_receipt` |
| 5 | mass-eval Worker HTTP `fetch` routes from `index.ts` (sibling in **same** worker) | **presentation** | `runMassEval` / `runDailyPath`; `http.ts` R2 put already extracted |
| 6 | Snapshot sqlite state builders (`_schema_state` / `_watermark_state` / `_validation_state` / `_fact_table_state`) | **evidence** (after lane 3) | `data_snapshot_id` façade export may stay; READY policy stays |

**HOLD (not a lane):** leftover occupancy in `daily_path.ts` (unique-22 lid
branches + leftover CS books). Occupancy-equal re-eval required before any
move. Do not unify with `comboEventGateOk`.

**No lane:** `cost_models.py`, `options_225_vol_series.py`, `eval.ts` family
math, `coverage.py` C-checks, `constants.py`, `combo_basket_catalog.py`
reconstitution, `catalog_ids.ts`, `unique_logic/catalog.py`.

Do **not** recommend a rewrite. Do **not** recommend Batch Z
`quant_platform.*` imports.

---

## 8. Hard bans (current)

```text
✗ Rewrite daily_path / eval / cost_models / options_225 formulas
✗ Extract leftover occupancy from daily_path.ts
✗ Unify unique-22 leftover occupancy with comboEventGateOk
✗ Fake-split cost_models / options_225 / eval family math to hit a line budget
✗ Hand-edit catalog_ids.ts / propose_allowed.ts / propose_review_tables.ts
✗ Re-add YAML / delete the compiled map / re-run digest lock
✗ Edit unique_logic/catalog.py
✗ Edit daily_path.ts / eval.ts formulas / phase62_residual_status.md
✗ Move platform/workers/** package paths or data/**
✗ Claim or enable Mass ON, production READY, Phase 7 GO
✗ Invent COMPLETE (empty-raw, weekend OTC, earnings months, MISDATE master)
✗ Flip RECONSTITUTION_APPLY
✗ Introduce quant_platform.* imports (Batch Z still DEFER)
```

---

## 9. This snapshot

**Did:** measure `git ls-files` LOC at `e927b97`; classify KEEP vs already
extracted vs remaining mix vs HOLD; write this current snapshot.

**Did not:** rewrite [`phase63_refactor_plan.md`](../phase63_refactor_plan.md);
extract modules; edit `daily_path.ts` / `eval.ts` / `cost_models.py` /
`options_225_vol_series.py` / `unique_logic/catalog.py` / `catalog_ids.ts`;
add YAML; flip GO flags.
