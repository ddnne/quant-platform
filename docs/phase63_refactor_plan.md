# Phase 6.3 — refactor plan (authority split, not a rewrite)

**Lane:** refactor PLAN (authority split, not a rewrite)  
**Tip at authoring:** `41003a5`  
**Status at `5c9b962`:** YAML file-count waste **closed** (compiled map is SoT;
`yaml_still_present: false`; tracked files ~631). Combo-gate and PIT-entry
extracts landed. Leftover occupancy **HOLD** in `daily_path.ts`.  
**Later extracts (tip `origin/main`):** `r2_feature_parse`, `r2_feature_normalize`,
`r2_available_at`, `r2_io` get, `r2_feature_mirror`, `coverage_ledger_io`,
`coverage_receipts`, `snapshot_publish_policy`, `snapshot_coverage_proof`,
`snapshot_persist`, `snapshot_read`, `eval_orchestrate`,
`ingestion-premium/collection_receipts.ts` — **DONE** in §7.  
**Live strategy at `cb9916e0`:** §10 — remaining extracts vs HOLD. YAML
file-count waste is closed. Size is not waste. Do not extract leftover
occupancy. Do not add YAML. Do not declare Phase 7 GO.  
**Mass / READY / Phase 7:** unchanged (NO-GO / not declared / OFF)

This is a **refactor plan**, not a rewrite mandate. Later lanes extract
**one authority** from a mixed file. They do **not** invent COMPLETE,
densify, enable Mass/READY/Phase 7, hand-edit generated catalogs, or
fake-split live math because a file is long.

Paired: [`phase63_test_audit.md`](phase63_test_audit.md) (tests: mechanism
over combinatorics). Residual SoT remains
[`phase62_residual_status.md`](phase62_residual_status.md). Layout / import
policy: [`architecture/adr_llm_friendly_refactor.md`](architecture/adr_llm_friendly_refactor.md).
Research recording: [`architecture/adr_research_recording.md`](architecture/adr_research_recording.md).

---

## 1. Decision

Keep **one** of these authorities per module. A file may *import* others;
it must not *own* a second.

| Authority | Owns | Must not own |
|-----------|------|----------------|
| **parsing** | Bytes / YAML / JSONL → typed fields | Canonical keys, gates, writes |
| **normalization** | Canonical dates, keys, row shape, no-invent fills | HTTP, D1/R2 writes, COMPLETE |
| **evidence** | Receipts, digests, coverage proofs, C-checks, raw manifests | Policy that *decides* COMPLETE/READY; HTTP routing |
| **policy** | Gates, occupancy leftover, COMPLETE/READY/Mass fail-closed, inventory grain | Live PnL math; persistence I/O |
| **persistence** | SQLite / D1 / R2 put-get, ledger refresh, snapshot copy | Gate predicates; HTTP path dispatch |
| **orchestration** | Job fan-out, `ingestOne` / `runIngestion`, isolate scheduling | Formula bodies; catalog generation |
| **presentation** | HTTP/MCP JSON, cell packs, reports | Receipt crypto; PIT entry math |

**Live math is not an 8th authority to extract.** It is a keep-together
constraint that **overrides line-count pressure**. Transaction/vol/MTM
formulas stay in one place even at 2k LOC. Splitting a numerator from its
denominator, or a PIT median from the entry that consumes it, is a
rewrite dressed as a refactor.

**Size is not a split key.** `daily_path.ts` is 1677 lines. Combo-gate and
PIT-entry extracts already landed; leftover occupancy **HOLD**s here.
Length is not a reason to extract leftover occupancy.

---

## 2. What is actually large (this tip)

`git ls-files` at `41003a5`: **2873** tracked paths, of which YAML was
**2254** (**78.5%**). At `5c9b962` YAML is gone; tracked files **~631**.
This tip: **653** tracked; YAML **0**; compiled n=**2254**.
Compiler map `specs/research_catalog/` is catalog SoT. Do not add YAML.
Do not hand-edit `catalog_ids.ts`. Unique22 park is leftover occupancy
(`UNIQUE22_PARK_REASONS` / `daily_path.ts`), not YAML.

LOC via `git ls-files … | xargs wc -l` at this tip. Extract statuses
below are already in §7 — this table does **not** schedule new extracts.
Leftover occupancy **HOLD** remains.

| Path | LOC | Split? |
|------|----:|--------|
| `platform/workers/research-mass-eval/src/catalog_ids.ts` | 2327 | **No hand-edit.** GENERATED. Compiler owns emit (**DONE**) |
| `packages/product/research/cost_models.py` | 2210 | **KEEP** live math |
| `platform/workers/research-mass-eval/src/eval.ts` | 1806 | Orchestration vs live math only; `eval_orchestrate.ts` **DONE**; do not family-slice the formulas |
| `platform/workers/research-mass-eval/src/daily_path.ts` | 1677 | Combo-gate + PIT-entry **DONE**. Leftover occupancy **HOLD** here. Do not extract leftover occupancy. Do not unify with `comboEventGateOk` |
| `packages/edge/cf_platform/ingest_premium/coverage.py` | 1624 | KEEP as **evidence** measurement; do not per-check microfiles |
| `platform/workers/ingestion-premium/src/index.ts` | 1350 | Fetch / persist / receipt; `collection_receipts.ts` **DONE** |
| `packages/data_plane/storage/coverage_ledger.py` | 1295 | `coverage_ledger_io` / `coverage_receipts` **DONE**; COMPLETE predicates stay |
| `packages/product/research/options_225_vol_series.py` | 1140 | **KEEP** live math |
| `packages/research_runtime/paper_runtime/snapshot.py` | 958 | Extracts **DONE** (`snapshot_publish_policy.py`, `snapshot_coverage_proof.py`, `snapshot_persist.py`, `snapshot_read.py`) |
| `packages/product/research/unique_logic/constants.py` | 784 | KEEP as **policy**. Park reasons in `UNIQUE22_PARK_REASONS`; leftover occupancy in `daily_path.ts`. Do not explode park lists into YAML clones |
| `packages/product/research/r2_feature_context.py` | 658 | Extracts **DONE** (`r2_feature_parse.py`, `r2_feature_normalize.py`, `r2_available_at.py`, `r2_io` get, `r2_feature_mirror.py`; `build_*_context` orchestration stays) |

`packages/data_plane/data_contracts/coverage.py` is 165 lines and already
**policy** (contract schema). Leave it. Do not merge it into the ledger
or the C-check module.

Already-split siblings — **do not re-merge:** `mdh_collapse.ts`,
`path_broken.ts`, `metrics.ts`, `cost_repo.py`, `cost_defaults.py`,
`eval_loaders*.py`, phase35 coverage matrix split, Worker
`combo_gates.ts` / `combo_gates.test.ts` (combo-gate **policy** extracted),
`event_entry.ts` (PIT **entry** extracted). Leftover occupancy **HOLD**
in `daily_path.ts`. Do not schedule leftover occupancy extract.

---

## 3. `daily_path.ts` — the only size that is mixed authority

Candidate-grade SoT is `POST /v1/daily-path` (`adr_research_recording.md`).
This file is that path. Three authorities share it today:

| Region (approx) | Authority | Notes |
|-----------------|-----------|-------|
| `surpriseProxy` / `afterClose` / `eventHeld` entry index (`disc_time` hour≥15, `entryIdx`) | **PIT entry** | `CF_EVENT_FIDELITY.intended_lite_entry`. Keep median + after-close + surprise together |
| `if (!comboImpl) { lid === "event_pre_mom_agree_hold" … }` and leftover CS books (`xs_margin_delta_rank`, `xs_low_vol_mom`, `idio_mom_macro_impulse`, lid invert list) | **leftover occupancy** (policy) | Unique-22. Comment: do not drop without occupancy-equal re-eval. Parked leftover stay non-candidate |
| `comboEventGateOk` / `comboCsGateOk` / `comboGatesImplemented` / `clusterWindowSeries` | **combo gates** (policy) | Unknown gate **fail-closed**. Tests already in `combo_gates.test.ts` |
| `equityPathDrawdown` / `heldBookDailyMtm` / `stickyHold` / `csRank` | **live math KEEP** | Occupancy fraction is measured here; leftover *policy* is not |
| `evalLogicDailyPathOnPanel` / `cellsFromPeriodPacks` | **orchestration / presentation** | Façade; may stay as the `daily_path` entry after extracts |

`catalog_ids.ts` header and `scripts/sync_cf_new_thesis_ids.py` already
say: **leftover occupancy stays in `daily_path.ts`.** That remains
**HOLD**. Do not extract leftover occupancy. Do not fold it into combo
gates. Unique22 park is leftover occupancy (`UNIQUE22_PARK_REASONS` /
`daily_path.ts`), not YAML.

### Allowed later extracts (one authority per lane)

1. **Combo gates → `combo_gates.ts`** — **DONE**  
   `comboEventGateOk`, `comboCsGateOk`, gate helpers, unknown-gate
   fail-closed. `combo_gates.test.ts` points at the module. Leftover
   `!comboImpl` lid branches stayed in `daily_path.ts`.

2. **PIT entry → `event_entry.ts` (or equivalent)** — **DONE**  
   Disc-time / surprise / entry bar index / `pitMedian` used for entry.
   Leftover occupancy predicates stayed
   (`event_pre_mom_agree_hold` uses `momentumAt(entryIdx)` on purpose —
   occupancy vs Python unique; combo `pre_mom` is `entryIdx-1`).

3. **Leftover occupancy — HOLD** in `daily_path.ts`  
   Unique-22 lid branches stay here. Do **not** schedule leftover
   occupancy extract. Unifying leftover with `comboEventGateOk` is a
   rewrite (it widens or thins occupancy). Park reasons live in
   `UNIQUE22_PARK_REASONS`; `yaml_still_present: false`.

Do **not** split `heldBookDailyMtm` from `equityPathDrawdown`. Do **not**
slice `gatedCsHeld` by thesis id.

---

## 4. Generated catalog (compiled map is SoT)

**Current (after `5c9b962`):** YAML files **0**; compiled n=**2254**;
`yaml_still_present: false`; digest `sha256:6ad5ba57dfa41…`.
`specs/research_catalog/` is catalog SoT. Do **not** add YAML. Do **not**
re-run digest lock. Do **not** hand-edit `catalog_ids.ts`.

| Artifact | Role now |
|----------|----------|
| `specs/research_logics/*.yaml` | **0 files.** Empty dir. Do not add YAML |
| `research.catalog_compiler` | Closed-DSL rows + `digest` + `semantic_hash`. **SoT**. Emits Worker `catalog_ids.ts` (**DONE**). Does not exec Python, does not add YAML |
| `research.unique_logic.catalog` | Loads YAML if present, else `migration.jsonl` |
| `unique_logic/constants.py` | Policy stays (gates, parks, propose allow-list). Family ID unions come from the compiled catalog (`unique_family_ids_from_yaml` is still the function name; alias `unique_family_ids_from_catalog` exists) |
| `catalog_ids.ts` | **GENERATED.** `catalog_compiler` owns the emit (**DONE**). Do not hand-edit |
| `eval_flags.CATALOG_YAML_COUNT_AT_STOP` (2254) | Freeze identity n: yaml n=0 requires compiled n=2254; digest pin `sha256:6ad5ba57dfa41…` |

### At authoring `41003a5` (historical — not a to-do)

YAML was **2254** files (**78.5%** of tracked). The plan then said:
constrained YAML parse remains until YAML is gone; digest lock is a later
lane; YAML deletion is a later mechanical commit after lock. Those lanes
landed at `5c9b962`. Agents must **not** re-add YAML or re-run digest lock.

| Artifact | Role at `41003a5` | Later (now **DONE**) |
|----------|-------------------|----------------------|
| `specs/research_logics/*.yaml` (2254) | Catalog SoT on disk (**78.5%** of tracked files) | Delete only after digest lock → **DONE** (`5c9b962`; n=0) |
| `research.unique_logic.catalog` | Constrained YAML parse | Parse remains until YAML gone; then load compiler artifact → YAML if present else `migration.jsonl` |
| `unique_logic/constants.py` | Policy; loads family IDs from YAML | Policy stays; ID unions from compiled catalog |
| `catalog_ids.ts` | **GENERATED** by `scripts/sync_cf_new_thesis_ids.py` from Python frozensets | Compiler owns the emit → **DONE** (`catalog_compiler`) |

### Digest lock — **DONE** (do not re-run)

Pin is `sha256:6ad5ba57dfa41…` next to `COMPILER_VERSION`
(`research_catalog_compiler/v1`). Landed steps (not a new lane):

1. `compile_catalog()` digest is the pin (already `sha256:`).
2. Record the pin next to `COMPILER_VERSION`.
3. Tests: compiler `digest` + identity set `logic_id` vs Worker
   `catalog_ids.ts` vs Python constants — **one** pass, not two 2254-file
   regex walks (`test_catalog_yaml_parity.py` freeze; see test audit).
4. Worker load still generated TS. Hand-edits to `catalog_ids.ts` stay
   forbidden.
5. `yaml_still_present` is **false** (`5c9b962`).

### YAML deletion — **DONE** (`5c9b962`; do not re-add YAML)

Mechanical commit, no behavior change: load compiler artifact only.
`yaml_still_present` flipped false in that commit. Do not hand-curate YAML
to keep. Countable theses are `worker_bodies.countable_thesis_ids`
(catalog + Worker body); YAML clones never counted. File-count drop is
not a quality win without the digest pin (already pinned).

---

## 5. Other large files — keep vs extract

### KEEP live math (do not fake-split)

**`cost_models.py` (2210).** Transaction + short-borrow + leverage
financing. `cost_repo.py` / `cost_defaults.py` already hold series I/O
and literals. Remaining body is the live modulation. Liquidity buckets,
repo+spread, date-matched remeasure stay together. Research-only; does
not mint READY / arm Mass.

**`options_225_vol_series.py` (1140).** BaseVol / ATM IV / skew / CM-term
/ ΔBaseVol. Missing days omit (no ffill / no invent). Splitting
`_atm_iv_at_cm` from `build_daily_skew_series` is fake-split.

**`eval.ts` (1806).** Bar-native family evaluators + `barNativeHeldBook` +
`evaluateLogicAcrossPeriods`. Allowed: move **orchestration**
(`evaluateLogicAcrossPeriods`, `rankSurvivors`) and keep family math in
one module. Disallowed: one file per `evalFlowDemand` / `evalFundPrice` /
`evalNkyVolRegime`. MDH collapse already lives in `mdh_collapse.ts`.
Unique event/CS on this period-net path collapse to MDH and must not
enter `n_survivors`.

### Coverage trio (already three authorities — do not collapse)

| Module | Authority | Later split? |
|--------|-----------|--------------|
| `data_contracts/coverage.py` | **policy** (contract fields, event vs calendar grain) | No |
| `storage/coverage_ledger.py` | mixed | **evaluate_segment** + `plan_required_segments` stay **policy** (do not slice COMPLETE predicates). `record_*` / `refresh_*` / `read_*` are **persistence**. `build_collection_receipt` / digest helpers are **evidence** |
| `cf_platform/ingest_premium/coverage.py` | **evidence** (C1–C12 / B0 measurements) | KEEP. `run_coverage` may stay as the orchestrator of checks. Do not make `c1.py`…`c12.py` |

Empty-raw COMPLETE remains banned. Event-zero COMPLETE still requires a
trusted receipt. Calendar-day OTC inventory overhang is a **planner**
issue (`plan_required_segments`), not a floor bump — see
[`phase63_coverage_gap_audit.md`](phase63_coverage_gap_audit.md).

### `paper_runtime/snapshot.py` (958)

| Piece | Authority |
|-------|-----------|
| `_evaluate_publication_gate` / `_transition_policy` | **policy** (READY fail-closed) |
| `_coverage_v2_proof` / `_verify_coverage_v2_manifest` | **evidence** |
| `publish_ready_snapshot` sqlite copy / `_atomic_json` | **persistence** |
| `describe_snapshot` / `list_ready_snapshots` | **presentation** |

Extract along those lines if a lane needs locality. Do not split the
Coverage V2 proof construction to shrink LOC. Production READY stays
NO-GO; this file is the publication *machine*, not a GO switch.

### `r2_feature_context.py` (658)

| Piece | Authority |
|-------|-----------|
| `parse_r2_structured_line` / `_bytes` | **parsing** |
| `normalize_r2_history_row` / tip row mappers | **normalization** |
| `repair_available_at_research` / `available_at_policy_document` | **policy** (research-only; never look-ahead) |
| `default_r2_get_object` / `build_*_context` | **orchestration** |
| `materialize_disposable_sqlite_mirror` | **persistence** (scratch; not experiment SoT) |

Extracts **DONE** (see §7). Remaining `build_*_context` orchestration
stays. Size is not a split key.

### `ingestion-premium/src/index.ts` (1350)

Already extracted: `catalog.ts`, `identity.ts`, `availability.ts`,
rate-limit, SCD2 write, ops archive/prune. The remainder still mixes:

| Piece | Authority |
|-------|-----------|
| `fetchDataset` / `fetchOnePage` / retry | **orchestration** (network; ingestion-only egress) |
| `upsertRecords` / watermarks | **persistence** |
| `writeCollectionReceipt` / `writeRequiredCoverageSegment` / raw digest | **evidence** |
| `export default { fetch, scheduled }` / `handleExport*` | **presentation** |
| `ingestOne` / `runIngestion` | **orchestration** façade |

Natural-key / `available_at` stay in `identity.ts` / `availability.ts`
(**normalization**). Do not move Worker paths (`platform/workers/**`
frozen). No first-party `*.test.ts` here today; Python↔TS identity is
`tests/test_identity_runtime_parity.py` (**Invariant**, not echo).

### `unique_logic/constants.py` (784)

**Policy** (gates, propose allow-list, occupancy parks, candidate exclude
reasons). Park reasons live in `UNIQUE22_PARK_REASONS`; leftover occupancy
stays in `daily_path.ts`. YAML is not SoT. It is not eval scores. Do not
generate per-YAML constant files.
`SPARSE_GATE_COMBOS` / `NEAR_EMPTY_PARK_IDS` stay lists of **reason
classes**, not a 2254-row freeze. Family ID unions come from the compiled
catalog (`unique_family_ids_from_yaml` is still the function name; alias
`unique_family_ids_from_catalog`). That is catalog ownership, not a
constants split.

---

## 6. Tests — mechanism over combinatorics

Cite [`phase63_test_audit.md`](phase63_test_audit.md). That lane
classified the suite; this plan does not re-count tests as a win.

| Rule | Apply when extracting |
|------|----------------------|
| Named invariants stay | PIT, `available_at`, receipts, false-COMPLETE, immutable READY, Mass/gateway fail-closed, `test_baseline_catalog.py` — **never delete** |
| Representative, not paraphrase | One golden per gate *class* (`skip_tuesday`, unknown fail-closed, missing-field fail-closed). Calendar `it()`s in `combo_gates.test.ts` are representatives, not 2254-file freeze |
| No new YAML-per-file tests | Identity set-equality `yaml==py==constants` is Invariant. Two raw walks of 2254 files for `go:` / `family:` / `theme:` are freeze — collapse to **one** pass later; drop only after compiler digest owns those fields |
| Dual-runtime echo | Do not add Python greps of Worker leftover occupancy. `combo_gates.test.ts` is **SoT for Worker gate policy**. Real Py↔TS *execution* parity (`test_identity_runtime_parity.py`) is Invariant |
| Move tests with the extract | `combo_gates.test.ts` already imports from `daily_path.ts`; retarget on extract. Do not duplicate |
| Structural replacement | After digest lock: `n == 2254` → compiler digest + set-equality. Leftover occupancy **HOLD** in `daily_path.ts` (no occupancy-extract fixture lane) |
| Split-monolith already done | COMPLETE-21 / phase35 / cost_models test splits — keep the split; do not re-merge |

Guard pack (every extract commit): Mass fail-closed, gateway fail-closed,
plane import boundaries, publish guard, PIT look-ahead / `as_of`, receipt
eligibility. Full offline G2 at end of each extract lane.

Do **not** add ingestion-premium combinatorics to “cover the split”.
Prefer one Worker unit test per extracted authority (unknown gate
fail-closed, empty-raw receipt ban) over a matrix.

---

## 7. Sequencing

Each row is one revert unit. No mixed “rename + behavior change”.
No Mass/READY/Phase 7 arming.

| Order | Lane | Authority moved | Status at `5c9b962` |
|------:|------|-----------------|---------------------|
| 1 | `combo_gates.ts` from `daily_path.ts` | combo-gate **policy** | **DONE** (`combo_gates.ts`; leftover occupancy stayed) |
| 2 | PIT entry module from `daily_path.ts` | PIT **entry** | **DONE** (`event_entry.ts`) |
| 3 | leftover occupancy as **policy** | unique-22 lid branches | **HOLD** in `daily_path.ts` (do not extract; park reasons in `UNIQUE22_PARK_REASONS`, not YAML; do not unify with `comboEventGateOk`) |
| 4 | `r2_feature_context` parse vs normalize vs `available_at` vs persist | parse, normalize, policy, then persist I/O | **DONE** (`r2_feature_parse.py`, `r2_feature_normalize.py`, `r2_available_at.py`, `r2_io` get, `r2_feature_mirror.py`; `build_*_context` orchestration stays) |
| 5 | `coverage_ledger` persist/read vs `evaluate_segment` | persist then evidence | **DONE** (`coverage_ledger_io.py`, `coverage_receipts.py`; COMPLETE predicates stay) |
| 6 | `snapshot.py` publication gate vs artifact write vs proof vs read | policy, evidence, persist, presentation | **DONE** (`snapshot_publish_policy.py`, `snapshot_coverage_proof.py`, `snapshot_persist.py`, `snapshot_read.py`) |
| 7 | Compiler owns `catalog_ids.ts` emit | generated **presentation** of policy IDs | **DONE** |
| 8 | Digest lock (pin `compile_catalog()` digest) | — | **DONE** `sha256:6ad5ba57dfa41…` |
| 9 | Mechanical YAML delete | files only | **DONE** (`yaml_still_present: false`) |
| 10 | ingestion-premium persist vs HTTP vs receipt | receipt **evidence** | **DONE** (`collection_receipts.ts`; fetch/upsert stay in `index.ts`; path frozen) |
| 11 | `eval.ts` period orchestration | orchestration | **DONE** (`eval_orchestrate.ts`; family formulas stayed) |

`coverage.py` C-check *navigation* (comments / table of check ids) is optional and never a prerequisite.
`cost_models.py` and `options_225_vol_series.py` have **no** extract lane.

---

## 8. Hard bans

```text
✗ Rewrite daily_path / eval / cost_models / options_225 formulas
✗ Hand-edit catalog_ids.ts / propose_allowed.ts / propose_review_tables.ts
✗ Unify unique-22 leftover occupancy with comboEventGateOk
✗ Split live math to hit a line budget
✗ Re-add YAML / delete the compiled map / hand-edit `catalog_ids.ts`
✗ Walk 2254 YAML files as a new test, twice
✗ Move platform/workers/** paths or data/**
✗ Claim or enable Mass ON, production READY, Phase 7 GO
✗ Invent COMPLETE (empty-raw, weekend OTC, earnings months, MISDATE master)
✗ Add scripts/run_wNN_*.py or wave proof warehouses
✗ Introduce quant_platform.* imports (Batch Z still DEFER)
```

---

## 9. This lane

**Did:** write this plan.

**Did not:** extract modules, edit `daily_path.ts`, touch
`catalog_ids.ts`, delete YAML, add tests, flip GO flags.

Success for *later* extract lanes: one authority moved, G0 green, occupancy
and COMPLETE predicates unchanged, generated files still generated.

---

## 10. Current remaining extracts vs HOLD (HEAD cb9916e0)

This is the **live** refactor strategy for “the code is full of waste.”
§§1–9 remain the plan at `41003a5` / status at `5c9b962`. Follow this
section now. Size is not a split key. Live math is not waste.

Measured at `b1605c36`: tracked paths **838**; catalog YAML
(`specs/research_logics/*.yaml`) **0**; remaining tracked YAML **1**
(`specs/research_themes.yaml` — themes, not catalog logics); compiled
n=**2254** (`migration.jsonl` 2254 lines);
`yaml_still_present: false`; digest
`sha256:6ad5ba57dfa41ed9a97e5895d9238040fbb5539b310a2ea4aa349172b6cb8c69`.
`specs/research_catalog/` is catalog SoT. `CATALOG_AND_PLUS_N_STOPPED`.
Mass / READY / Phase 7: **NO-GO / not declared / OFF**.
`RECONSTITUTION_APPLY=False`.

LOC via `wc -l` on named files at this HEAD (do not copy stale §2
numbers). `daily_path.ts` is **1682** (was 1677 in §2).
`eval.ts` is **1806**. `eval_orchestrate.ts` is **235**.
`persist_records.ts` is **362**. `ingestion-premium/src/index.ts` is **678**.
`r2_io.py` is **431**. `cost_models.py` is **2210**.
`coverage_ledger.py` is **1454**. `catalog_ids.ts` is **2327** GENERATED.
`coverage.py` is **1627**. `snapshot.py` is **912**.

### 10.1 Waste already closed (do not re-open)

| Closed | Fact at `07b4435` |
|--------|-------------------|
| Catalog YAML 2254 files | Deleted (`5c9b962`). yaml n=0. Compiled n=**2254** is SoT. `yaml_still_present: false`. Do not add YAML. |
| combo-gate policy | **DONE** `combo_gates.ts` (788) |
| PIT entry | **DONE** `event_entry.ts` (30) |
| r2 parse / normalize / `available_at` / io get / mirror | **DONE** `r2_feature_parse.py` (101), `r2_feature_normalize.py` (176), `r2_available_at.py` (113), `r2_io` get, `r2_feature_mirror.py` (201). `build_*_context` stays. |
| coverage ledger persist / receipts | **DONE** `coverage_ledger_io.py` (295), `coverage_receipts.py` (147). COMPLETE predicates stay in `coverage_ledger.py`. |
| snapshot publication split | **DONE** `snapshot_publish_policy.py` (190), `snapshot_coverage_proof.py` (219), `snapshot_persist.py` (124), `snapshot_read.py` (104) |
| eval period orchestration | **DONE** `eval_orchestrate.ts` (235). Family formulas stay in `eval.ts`. |
| ingestion collection receipts | **DONE** `collection_receipts.ts` (111). Fetch/upsert stay in `index.ts`. |
| `catalog_ids.ts` emit | **DONE** compiler owns emit. **2327** GENERATED. Do not hand-edit. Digest lock **DONE**. |
| index_text CLIs / OTC grain | **DONE** at `67fcbd7c`: `refresh_coverage_ledger --index-text` (`34dc85df`); `write_collection_receipts --index-text` (`db569fc7`); ops projection `--otc-index-html` (`9524dab7`); ingest passes fetched year-index HTML (`ddc40ae9`). JSON grain `official_archive_index_day` (`26a6ca5e`). Missing `index_text` stays fail-closed empty, not calendar inventory. |
| Worker R2 stub | **DONE** (`61c14a0d`): `put_children_then_manifest_via_worker` requires Worker URL+token; no CLI put fallback. Remote CLI put later fenced (`0b81eedb`). |
| Worker children-then-manifest POST | **DONE** (`5103b26b`): `put_children_then_manifest_via_worker` POSTs `/v1/children-then-manifest` with `X-Mass-Eval-Token`. No CLI put fallback. Unbound URL/token fail closed. |
| Remote Python CLI-put fence | **DONE** (`0b81eedb`): remote `default_r2_put` never CLI-puts; `QP_ALLOW_PYTHON_R2_PUT=1` does not resurrect TOCTOU. dry_run stays local. |
| Python job-artifact Worker put | **DONE** after `3b64bdfc`: `put_research_artifact` (`d6567268`); `cf_daily_path_job` (`017a43c6`); `cf_mass_eval_run` (`0a8ced34`). Named remaining callers after wave-7 are gone. `reconstitution_evidence` dry-run uses `put_research_artifact` (`cb613667`). Direct `default_r2_put(` callers outside `r2_io.py` are gone (glob pin `8299ad84`). |
| Evaluation IR encode/decode | **DONE** (`4661fb14`): `evaluation_ir_codec.generated.ts` emitted from `schema.json`. `evaluation_ir.ts` is façade. `ALLOWED_FIELDS` generated (`d882119`). Python codec body generated **DONE** (`c9764ff4`; `evaluation_ir_codec.generated.py`). Python TypedDicts generated **DONE** (`e20be4d9`; `evaluation_ir_types.generated.py`). Codec emitters extract **DONE** (`54c1f472`; `evaluation_ir_emit.py`). |
| DO `budget_id` pin | **DONE** (`89415105`): create is not a reserve; string `budget_id` is not occupancy authority. In-memory algebra; live Edge occupancy unproven. |
| BackfillPlanner JQ required segments | **DONE** (`bcd52f47`): all JQ jobs come from `plan_required_segments`. Bars/fins stay calendar_month jobs. Missing V3 does not invent official domain or COMPLETE. |
| Shared official-index local HTML reader | **DONE** (`2323f6a5`): `ingestion.jsda.official_index.read_local_index_text`. CLIs use it. `cf_premium_backfill` uses it (`2b82ec7d`). Missing/blank stays fail-closed empty, not calendar inventory. |
| Premium Worker units vs Python greps | **DONE**: catalog identity (`23a5cbb9`; `catalog.test.ts`); availability policy (`8fc13e24`; `availability.test.ts`); identity JST clocks (`5ac9cce1`; `identity.test.ts`); raw-page retain (`0383311f`; `index.test.ts`); coverage-segment plan (`0fee1b1e`; `index.test.ts` / `collection_receipts.test.ts`); NK rebuild (`8fc9fa30`; `natural_key_migration.test.ts`). Replaced Python greps. |
| Premium write-path ids from catalog | **DONE** (`4f111320`): `PREMIUM_CORE_DATASET_IDS` from catalog JSON (`write_path_config.ts` / `write_path_config.test.ts`), not a second hardcoded list. |
| Premium RateLimiter / R2 writer / export unbound tests | **DONE**: RateLimiter acquire and 429 cooldown (`5b4db591`; `rate_limit.test.ts`); R2 structured writer mock bucket (`0194c64a`; `r2_structured_writer.test.ts`); export unbound `DATA_EXPORT_TOKEN` 401 (`cfbaa58e`; `index.test.ts`). |
| C12 addon guard ids from catalog | **DONE** (`de8f87bf`): `_ADDON_IDS = frozenset(list_datasets("addon"))`. Second id list closed. C12 still fails on addon leak; addons stay out of `PREMIUM_CORE_DATASETS`. Do not re-add a handwritten addon list. |
| Premium ops fail-closed Worker units | **DONE**: cold-archive token/args (`9956ab51`; `ops_cold_archive.test.ts`); changelog prune unbound token 401 (`9b0582d4`; `ops_prune_changelog.test.ts`); parquet-manifest unbound token 401 (`359b2566`; `ops_parquet_manifest.test.ts`); artifacts-plan token fail-closed (`329f3959`; `ops_artifacts_plan.test.ts`). |
| Premium master SCD2 write mock R2 unit | **DONE** (`ee167188`; `master_scd2/write.test.ts`): `payloadToMasterRecord` / `writeMasterScd2` against in-memory mock bucket. |

File-count drop after YAML deletion is not a quality win without the
digest pin (already pinned). Do not re-run digest lock.

### 10.2 Not waste (HOLD — do not delete/unify to “clean”)

These look large or leftover. They are **policy / live math / freeze**.
Deleting or unifying them to shrink the tree is a rewrite.

| HOLD | Why it stays |
|------|----------------|
| Leftover occupancy in `daily_path.ts` (1682) | Unique-22 lid branches + leftover CS books. Do not drop without occupancy-equal re-eval. Unifying with `comboEventGateOk` **rewrites occupancy**. **Do not schedule leftover occupancy extract.** |
| `UNIQUE22_PARK_REASONS` (17 parked) | Park is code in `unique_logic/worker_bodies.py`, not YAML. Occupancy-equal lifts already exist. Do not silent-unpark. |
| `cost_models.py` (2210) / `options_225_vol_series.py` (1140) | **KEEP** live math. Size is not a split key. Fake-split numerator from denominator is a rewrite. **No extract lane.** |
| Factory `generation_enabled=False` | Unique/combo stay ungenerated (`factory.py`, `factory_templates.py`). Intentional. Do not enable. |
| 3 pins frozen | `FROZEN_PIN_SNAPSHOT`: `cross_section_hold_10` mom=5 **KEEP** · `cross_section_hold_10_mom3` mom=3 **PROMOTE** · `fundamentals_hold_10` **KEEP**. Not retuned. |
| PARSE_ZERO 2 genuine gaps | OTC `2002-08-02`, `2002-08-05` (23-col vs 29-col parser) stay **PARTIAL**. Do not invent COMPLETE. 2898 PARTIAL ≠ 2 PARSE_ZERO. |
| cheap_pb event vs CS non-unify | `CHEAP_PB_EVENT_VS_CS = event_bars_x_fins_not_csfundsnaps`. Event cheap_pb is bars×fins; CS uses `csFundSnaps`. `combo_gates.ts`: do not unify. Cap `CHEAP_PB_PRIMARY_GATE_CAP`. |
| `test_baseline_catalog.py` rejected S1–S5 | W65 rejected catalog. Mass/READY stay false. **Never delete** (named invariant). |
| Combo AND +N freeze n=2254 | `CATALOG_AND_PLUS_N_STOPPED`. Expanding n is not a product. Compact family+template+parameter matrix is **optional** and **not done**; freeze n=2254 is **HOLD**. |
| `eval.ts` family math (1806) | Orchestration already extracted. Do not family-slice formulas. |
| `ingest_premium/coverage.py` C-checks (1627) | KEEP as evidence measurement. Do not per-check microfiles. |
| `persist_records.ts` live upsert (362) | KEEP fetch/upsert together. Do not fake-split live upsert. Empty-row unit is agent-capable, not HOLD, and is **untested** at this SHA. |

### 10.3 Real remaining mixed authority (one authority per later commit)

Schedule remaining mixed rows. Do **not** bundle. Each later commit
moves **one** authority. Python R2 writer stays **non-authority**.
index_text CLIs, OTC grain, Worker R2 stub, Worker POST
`/v1/children-then-manifest`, IR encode/decode generated TS, DO
`budget_id` pin, BackfillPlanner JQ required segments, remote Python
CLI-put fence (`0b81eedb`), and job-artifact Worker put (`d6567268`;
`017a43c6` `cf_daily_path_job`; `0a8ced34` `cf_mass_eval_run`) are
**DONE**. MCP presentation echo and JSDA refresh inventory replay stay
**DONE**. Remaining mixed: leftover occupancy **HOLD** — do not schedule leftover
occupancy extract. `UNIQUE22_PARK_REASONS`, `cost_models.py` live math,
and factory `generation_enabled=False` stay **HOLD**. `persist_records.ts`
live upsert is **HOLD** (do not fake-split). Compact catalog is optional
HOLD, not a required extract. `verify_all` vs `verify_ci` stay **HOLD**
split. `GATEWAY_TOKEN` service-binding residual stays **HOLD** (P632B-03).
Do not YAML +N. Do not declare Phase 7 GO. Python Evaluation IR codec emit **DONE**
(`c9764ff4`; `evaluation_ir_codec.generated.py`). Python TypedDict
generation **DONE** (`e20be4d9`; `evaluation_ir_types.generated.py`).
Codec emitters extract **DONE** (`54c1f472`; `evaluation_ir_emit.py`). Premium
fetch/retry extract **DONE** (`a20d14d4`; `fetch_jq.ts`). BackfillPlanner
`index_text` **DONE** (`2cbd894d`). Shared official-index reader **DONE**
(`2323f6a5`; `cf_premium_backfill` uses it at `2b82ec7d`). Premium Worker
units replaced catalog/availability/identity/raw-page/coverage-segment/NK
Python greps **DONE** (`23a5cbb9`; `8fc13e24`; `5ac9cce1`; `0383311f`;
`0fee1b1e`; `8fc9fa30`). Premium write-path ids from catalog **DONE**
(`4f111320`). RateLimiter / R2 writer / export unbound Worker tests
**DONE** (`5b4db591`; `0194c64a`; `cfbaa58e`). C12 addon guard ids from
catalog **DONE** (`de8f87bf`). Premium ops cold-archive / prune_changelog /
parquet_manifest / artifacts_plan fail-closed Worker units **DONE**
(`9956ab51`; `9b0582d4`; `359b2566`; `329f3959`). Master SCD2 write mock
R2 unit **DONE** (`ee167188`). After `63afd000`: persist empty-row,
metrics, eval_orchestrate, panels defaultPeriods + missing R2/D1,
propose-thesis HTTP 403 + window_tweak, ai_gateway unbound, parseRequest
export, GET 405 / freezePayload /health / nets_only HTTP, json no-store,
export D1/changes arg 400s, projection shared OTC reader, snapshot
`index_text=None` — **LANDED**. After `ad49ed96`: JSDA/premium `/v1/run`
POST-only (`121c4557`; `41878b82`); JSDA/premium `/health` GET-only
(`8e8b8c56`; `81fecac8`); `index_text=None` explicit on pipeline /
range_batch / tokyo-repo (`556cbecc`; `c95cec45`; `3a567e8e`);
collection receipt SUCCESS is not Coverage COMPLETE (`0e67f719`);
write-path r2 segments (`0f00ea16`); ci-aggregate health 405/404
(`3500c1cc`); `jobCandidateGrade` true is not Mass GO (`7335c184`) —
**LANDED**. After `81fecac8`: premium archive-cold / prune-changelog /
parquet-manifest POST-only GET 405 (`e1d71a18`; `bff7e2e1`;
`bb9e0c91`); artifacts-plan GET no mutate (`7d5dafd8`); ai-gateway
fetch 404/405 (`1b20fe1f`); complete unbound 503 (`a4aaa9db`) —
**LANDED**. After `1b20fe1f`: premium archive-cold / prune-changelog /
parquet-manifest / artifacts-plan header-only tokens (`af85daf3`;
`17025eb7`; `4c732e8b`; `2a98ef12`); budget HTTP dispatcher
(`72c30726`); ops-mcp GET `/mcp` 405 (`83941c19`) —
**LANDED**. After `03409ccd`: premium D1 export GET-only POST 405
(`db217acf`); mass-eval wrangler deploy opt-in fail-closed
(`d93ee610`); r2 get non-authority pins (`9e265280`; `3c212f7d`;
`8a61a03d`; `e0a6fa44`; `06f5c640`); budget HTTP missing-field
units (`539f95f4`; `7f4c0a6a`; `24f0e8d2`; `395e4676`;
`e4517282`); query-token header-only (already before); ci-aggregate
GET receipts (`bf0c0953`); JSDA/secrets/ops-mcp remaining HTTP
(`4f9a7db4`; `94765c86`; `a5dd3765`); ops-mcp health extract
(`d1028961`) — **LANDED**. After `d1028961`: budget POST `/reserve`
without amounts zero occupancy (`248ba80d`); ai-gateway complete
invalid JSON / unknown field / missing `budget_id` / CF-Worker 401
(`2bd8a91c`; `d7462d4f`; `39b140a2`; `ff3e5601`); GET/POST health
liveness not Coverage COMPLETE (`ae9be278`; `208bfedb`; `28c91d69`);
retry backoff delay helpers live in `retry_jitter` (`ec960406`) —
**LANDED**. After `ec960406`: premium retry sleep helper lives in
`retry_jitter` (`d3bfb5e8`); canonical registry pins JSON id sets not
magic 31/26 (`035e9306`); premium SHA-256 hex helper is one module
(`98545741`) — **LANDED**. After `98545741`: premium JST now-clock helpers
live in identity (`ca00ff6d`); premium ops token compare is timing-safe
header-only (`67436ab7`); ai-gateway json response helper is one module
(`7a0801a6`) — **LANDED**. After `7a0801a6`: premium ingest run token
compare is timing-safe header-only (`b51c8812`); premium ingest run
ignores query token (`a2e70c9f`) — **LANDED**. After `a2e70c9f`: premium
json response helper is one module (`a1428a21`; `http_json.ts` is
`Response.json` only, no Cache-Control; not gateway charset+no-store);
premium export / JSDA / secrets / mass-eval / ai-gateway query-token
pins (`809e45af`; `6be287db`; `7f97497d`; `6138b6ae`; `a7d1e93d`) —
**LANDED**. After `a7d1e93d`: reconstitution evidence dry-run uses
`put_research_artifact` (`cb613667`; last production `default_r2_put(`
caller outside `r2_io.py` closed; still never live-puts); premium
export success uses json helper (`c0b07935`); R2 writer digest pin
uses sha256 helper (`accbb9d9`); ops unpublished policy_version echo
pin (`159d8975`); ops-mcp OAuth bearer header-only (`f34b9dcc`) —
**LANDED**. After `f34b9dcc`: ci-aggregate json helper is one module
(`7dfed713`; charset + no-store, not premium); premium ops JSON
responses use json helper (`77505a8f`); research `default_r2_put(`
callers glob stays in `r2_io.py` (`8299ad84`) — **LANDED**. After
`8299ad84`: JSDA json helper (`adddbb87`); secrets json helper
(`61a55e96`; proxy stream stays no-store); mass-eval json helper
(`8a0475f7`; http.ts re-exports); ci-aggregate token compare
(`e91d5f41`); ai-gateway token compare (`88564075`; GATEWAY_TOKEN
service-binding HOLD unchanged) — **LANDED**. After `88564075`: JSDA
token compare (`9befdbc4`); secrets token compare (`7fb8e188`; WebCrypto
timingSafeEqual); mass-eval SHA-256 hex (`c126261f`); ai-gateway SHA-256
hex (`b8696205`) — **LANDED**. After `b8696205`: JSDA SHA-256 hex
(`9136dc53`); mass-eval token compare (`70d7c8bd`) — **LANDED**. After
`70d7c8bd`: mass-eval freezePayload (`7fa38828`); extracted json/token/sha256
glob (`31f9a99b`) — **LANDED**. After `31f9a99b`: freezePayload glob
(`cafc3fc0`); secrets proxy invalid JSON fail-closed (`bad3ab77`); residual
last_run 14324 (`7fb6924b`) — **LANDED**. After `7fb6924b`: validate addon
default from catalog (`94dac1fa`); matrix premium-core ids from catalog
(`773bab04`); propose review policy (`810d23e9`; `cf_propose_policy.py`);
occupancy-track run (`08b121b0`; `occupancy_audit_run.py`); pipeline receipt
evidence (`830a215b`; `pipeline_receipts.py`); catalog YAML overlay parse
(`f0e3c570`; `catalog_yaml_parse.py`); factory eval screen (`ae06f9fa`;
`factory_eval_screen.py`); daily-path DD gate (`5e6d36a7`;
`stats_metrics_gates.py`); ops-mcp 415/406/protocol/callback pins
(`3c73ca74`; `800ced41`; `a8daa996`; `3eb7bf04`); children[] required
(`3712b8c7`); secrets-proxy / jquants-catalog / budget-amount paraphrase
shrinks (`fb6bb56a`; `d348c93f`; `f008a4f3`); mass-eval parseRequest
(`70bfbefe`; `parse_request.ts`); ci-aggregate receipts gate (`aa503996`;
`receipts_gate.ts`); ops-mcp domain policy (`2cde56ac`; `domain_policy.js`);
budget HTTP dispatcher (`cb9916e0`; `budget_http.ts`) — **LANDED**. Remaining
mixed HOLD: leftover occupancy, unique22, GATEWAY_TOKEN P632B-03, persist
live upsert, compact catalog, `verify_all` vs `verify_ci`. putJson persist
stays in http.ts (do not fake-split). Do not schedule leftover occupancy.
Do not YAML +N. Do not declare Phase 7 GO. Do not claim ci-aggregate
Worker exists live. Do not treat CF-Worker as auth.

| Later | Mixed surface | Authority to pick | Must not |
|------:|---------------|-------------------|----------|
| 1 | `BackfillPlanner` (`ops/backfill_planner.py`, 666) vs `plan_required_segments` (`coverage_ledger.py`) | **ops product** inventory planner. Tip-snapshot wire **DONE** (`792ae2b`): AM bars / earnings calendar call `plan_required_segments` (no month-chunk). JSDA refresh inventory replay **DONE** (`40d1aa90`). OTC JSON grain **DONE** (`26a6ca5e`): `segment_granularity=official_archive_index_day`. index_text CLIs **DONE**: `refresh_coverage_ledger --index-text` (`34dc85df`); `write_collection_receipts --index-text` (`db569fc7`); ops projection `--otc-index-html` (`9524dab7`); ingest passes fetched year-index HTML (`ddc40ae9`). Bounded-history JQ month chunks **DONE** (`bcd52f47`): all JQ jobs come from `plan_required_segments` (bars/fins stay calendar_month jobs; missing V3 does not invent official domain or COMPLETE). BackfillPlanner `index_text` **DONE** (`2cbd894d`). Shared official-index local HTML reader **DONE** (`2323f6a5`; `cf_premium_backfill` uses it at `2b82ec7d`). | Invent COMPLETE; calendar-walk OTC; delete one planner without a dated ops brief |
| 2 | Python `r2_io.py` (431) vs Worker children-then-manifest (`http.ts` `putChildrenThenManifest`; digest mismatch **409**) | Worker is immutable authority. Python stays **non-authority** (`python_cli_put_is_not_immutable_authority`; `authoritative=True` refused). Remote `default_r2_put` never CLI-puts (`0b81eedb`; `QP_ALLOW_PYTHON_R2_PUT=1` does not resurrect TOCTOU). Worker POST **DONE** (`5103b26b`). `put_research_artifact` **DONE** (`d6567268`). After `3b64bdfc`: `cf_daily_path_job` **DONE** (`017a43c6`); `cf_mass_eval_run` **DONE** (`0a8ced34`). Remaining `default_r2_put` caller reconstitution_evidence dry_run **DONE** via `put_research_artifact` dry_run (`cb613667`). Still never live-put. Python still non-authority. | Treat “TOCTOU recorded in tests” as done; make Python CLI the SoT |
| 3 | `evaluation_ir.ts` (39) façade vs generated `evaluation_ir_codec.generated.ts` (239) vs `evaluation_ir_codec.generated.py` vs `specs/evaluation_ir/schema.json` (67) | Schema is codec SoT. `ALLOWED_FIELDS` generated **DONE** (`d882119`). Encode/decode TS body generated **DONE** (`4661fb14`). Python codec body generated **DONE** (`c9764ff4`). TypedDict generation **DONE** (`e20be4d9`; `evaluation_ir_types.generated.py`). Emit extract **DONE** (`54c1f472`; `evaluation_ir_emit.py`). Façades remain. Grade predicate is already shared (`job_candidate_grade` / `jobCandidateGrade`). | Second grade policy; delete schema; dual-edit field lists forever |
| 4 | MCP `OPS_TOOLS` strings vs stored `policy_version` (`dataset_coverage.policy_version`; live `collection-coverage/v2`) | Presentation echo **DONE** (Worker `27ff7e62`, Python `3d3e68ab`): both echo stored `policy_version`, not frozen “Coverage V2”. Remaining mixed: live projection is still `collection-coverage/v2` STALE — not unpublished V3 completeness. Do not schedule a second string rewrite. | Unify strings to mint FRESH / COMPLETE 23 |
| 5 | `scripts/verify_all.sh` skippable helper vs `scripts/verify_ci.sh` authority | **Keep both. Do not merge.** Helper: 3 research workers, `VERIFY_*` skips. Authority: pytest + catalog freeze + IR schema + 7 workers (`ci-aggregate` included), no skips. Merge gate is `verify_ci` plus authenticated `ci-aggregate`. | Fold `verify_ci` into `verify_all`; add GitHub Actions |

Not code extracts (environment / docs / optional freeze):

| Surface | Status | Action |
|---------|--------|--------|
| leftover git worktrees | **Environment waste, not code waste.** Measured **25** `git worktree list` rows at this write (this isolation included); `/private/tmp/qp-*` dirs were **101**. | Prune the environment. Not a module extract. |
| Historical `docs/reviews/*.md` as live SoT | Freeze files stay historical (`HEAD at remaining-audit: 03cd1b1`; P632 re-diffs at named SHAs). | **Banners, not deletion.** Live flags: `phase62_residual_status.md` + MCP projection + this §10. |
| Compact catalog family+template+parameter matrix | **NOT done.** `migration.jsonl` is still 2254 expanded rows. | Optional. Freeze n=2254 **HOLD**. Do not report 2254 as a product win. Do not YAML +N. |
| GATEWAY_TOKEN service-binding residual | **HOLD** (P632B-03). Mass-eval still needs a second `GATEWAY_TOKEN` copy on the `AI_GATEWAY` service-binding path. Public/preview `fetch` stays token-gated. | Do not close without a documented unspoofable binding signal. Do not treat `CF-Worker` as auth. See [`reviews/P632B_03_gateway_token_service_binding_hold.md`](reviews/P632B_03_gateway_token_service_binding_hold.md). |

`ingestion-premium/src/index.ts` (~678 after `a20d14d4`) is the ingest
façade. Fetch/retry lives in `fetch_jq.ts`; persist in `persist_records.ts`;
export HTTP in `http_export.ts`; receipts in `collection_receipts.ts`.
Retry jitter is `retry_jitter.ts` (`crypto.getRandomValues`). Backoff
delay helpers live there (`ec960406`). Sleep helper lives there
(`d3bfb5e8`). SHA-256 hex is `sha256.ts` (`98545741`). JST now-clock
helpers live in `identity.ts` (`ca00ff6d`). Premium json helper lives in
`http_json.ts` (`a1428a21`). Premium ops also import `http_json.ts`
(`77505a8f`). ci-aggregate json lives in its own `http_json.ts`
(`7dfed713`). JSDA/secrets json live in their `http_json.ts`.
mass-eval json lives in `http_json.ts` re-exported from `http.ts`.
ci-aggregate token compare lives in `authorized.ts`. gateway token
compare lives in `authorized.ts`. JSDA/secrets token compare live in
their `authorized.ts`. JSDA/mass-eval/gateway SHA-256 hex live in their
`sha256.ts`. mass-eval authorized lives in `authorized.ts` re-exported
from `http.ts`. mass-eval `freeze.ts` re-exported from `http.ts`.
Do not family-slice remaining façade handlers.

### 10.4 Do not

```text
✗ Schedule leftover occupancy extract from daily_path.ts
✗ Unify unique-22 leftover occupancy with comboEventGateOk
✗ Recommend YAML +N / re-add specs/research_logics/*.yaml
✗ Recommend Phase 7 GO / Mass ON / production READY
✗ Fake-split cost_models / options_225 / eval family math for LOC
✗ Hand-edit catalog_ids.ts / unpark UNIQUE22 without occupancy-equal re-eval
✗ Invent PARSE_ZERO COMPLETE / retune 3 pins / enable factory generation
✗ Merge verify_all.sh into verify_ci.sh (or the reverse)
✗ Treat git worktrees or historical review docs as code waste
✗ Treat compiled n=2254 expanded rows as a compact-catalog substitute
✗ Fake-split persist_records live upsert
✗ Claim mass-eval eval_orchestrate/metrics/ai_gateway_client/panels/propose-thesis HTTP tests or persist_records empty-row unit landed at b1605c36
✗ Claim mutating premium ops archive-cold / prune-changelog / parquet-manifest are POST-only at 81fecac8
✗ Claim query-string token on premium ops is closed / header-only token is operator contract at 1b20fe1f
✗ Claim premium export POST does not dump D1 / deploy_cf_mass_eval_worker has opt-in env at 03409ccd
✗ Claim leftover occupancy / unique22 / GATEWAY_TOKEN P632B-03 / persist live upsert / compact catalog / verify_all vs verify_ci closed at d1028961
✗ Claim leftover occupancy / unique22 / GATEWAY_TOKEN P632B-03 / persist live upsert / compact catalog / verify_all vs verify_ci closed at ec960406
✗ Claim leftover occupancy / unique22 / GATEWAY_TOKEN P632B-03 / persist live upsert / compact catalog / verify_all vs verify_ci closed at 98545741
✗ Claim leftover occupancy / unique22 / GATEWAY_TOKEN P632B-03 / persist live upsert / compact catalog / verify_all vs verify_ci closed at 7a0801a6
✗ Claim leftover occupancy / unique22 / GATEWAY_TOKEN P632B-03 / persist live upsert / compact catalog / verify_all vs verify_ci closed at a7d1e93d
✗ Claim ingest authorized still plaintext === / premium json() still two copies at a7d1e93d
✗ Claim leftover occupancy / unique22 / GATEWAY_TOKEN P632B-03 / persist live upsert / compact catalog / verify_all vs verify_ci closed at f34b9dcc
✗ Claim reconstitution_evidence still calls default_r2_put at f34b9dcc
✗ Claim leftover occupancy / unique22 / GATEWAY_TOKEN P632B-03 / persist live upsert / compact catalog / verify_all vs verify_ci closed at 8299ad84
✗ Claim ci-aggregate Worker exists live at 8299ad84
✗ Claim leftover occupancy / unique22 / GATEWAY_TOKEN P632B-03 / persist live upsert / compact catalog / verify_all vs verify_ci closed at 88564075
✗ Claim ci-aggregate Worker exists live / CF-Worker is auth at 88564075
✗ Claim leftover occupancy / unique22 / GATEWAY_TOKEN P632B-03 / persist live upsert / compact catalog / verify_all vs verify_ci closed at b8696205
✗ Claim ci-aggregate Worker exists live / CF-Worker is auth at b8696205
✗ Claim leftover occupancy / unique22 / GATEWAY_TOKEN P632B-03 / persist live upsert / compact catalog / verify_all vs verify_ci closed at 70d7c8bd
✗ Claim ci-aggregate Worker exists live / CF-Worker is auth at 70d7c8bd
✗ Claim leftover occupancy / unique22 / GATEWAY_TOKEN P632B-03 / persist live upsert / compact catalog / verify_all vs verify_ci closed at 31f9a99b
✗ Claim ci-aggregate Worker exists live / CF-Worker is auth at 31f9a99b
✗ Claim leftover occupancy / unique22 / GATEWAY_TOKEN P632B-03 / persist live upsert / compact catalog / verify_all vs verify_ci closed at 7fb6924b
✗ Claim ci-aggregate Worker exists live / CF-Worker is auth at 7fb6924b
✗ Claim ci-aggregate Worker exists live
```

Success for a later extract commit: one authority moved, G0 green,
occupancy and COMPLETE predicates unchanged, generated files still
generated, Python R2 still non-authority.
