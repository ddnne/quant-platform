# Phase 6.3 — refactor plan (authority split, not a rewrite)

**Lane:** refactor PLAN (authority split, not a rewrite)  
**Tip at authoring:** `41003a5`  
**Status at `5c9b962`:** YAML file-count waste **closed** (compiled map is SoT;
`yaml_still_present: false`; tracked files ~631). Combo-gate and PIT-entry
extracts landed. Leftover occupancy **HOLD** in `daily_path.ts`.  
**Later extracts (tip `origin/main`):** `r2_feature_parse`, `r2_feature_normalize`,
`r2_available_at`, `coverage_ledger_io`, `coverage_receipts`, `snapshot_publish_policy`,
`snapshot_coverage_proof`, `snapshot_persist`, `eval_orchestrate` — **DONE** in §7.  
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

**Size is not a split key.** `daily_path.ts` is 2411 lines because it
mixes three authorities (PIT entry, leftover occupancy, combo gates), not
because 800-line files are virtuous.

---

## 2. What is actually large (this tip)

`git ls-files` at `41003a5`: **2873** tracked paths, of which YAML was
**2254** (**78.5%**). At `5c9b962` YAML is gone; tracked files **~631**.
Compiler map `specs/research_catalog/` is catalog SoT. Do not add YAML.
Do not hand-edit `catalog_ids.ts`.

| Path | LOC | Split? |
|------|----:|--------|
| `platform/workers/research-mass-eval/src/daily_path.ts` | 2411 | **Yes — by authority** (PIT entry / leftover occupancy / combo gates) |
| `platform/workers/research-mass-eval/src/catalog_ids.ts` | 2326 | **No hand-edit.** GENERATED. Compiler owns it later |
| `packages/product/research/cost_models.py` | 2210 | **KEEP** live math |
| `platform/workers/research-mass-eval/src/eval.ts` | 2030 | Orchestration vs live math only; do not family-slice the formulas |
| `packages/edge/cf_platform/ingest_premium/coverage.py` | 1624 | KEEP as **evidence** measurement; do not per-check microfiles |
| `packages/data_plane/storage/coverage_ledger.py` | 1564 | Policy evaluate vs persistence I/O vs evidence builders |
| `platform/workers/ingestion-premium/src/index.ts` | 1439 | Fetch / persist / receipt evidence / HTTP presentation |
| `packages/research_runtime/paper_runtime/snapshot.py` | 1407 | Publication policy vs proof evidence vs artifact persist |
| `packages/product/research/r2_feature_context.py` | 1160 | Parse vs normalize vs `available_at` policy vs orchestrate |
| `packages/product/research/options_225_vol_series.py` | 1140 | **KEEP** live math |
| `packages/product/research/unique_logic/constants.py` | 778 | KEEP as **policy**. Do not explode park lists into YAML clones |

`packages/data_plane/data_contracts/coverage.py` is 165 lines and already
**policy** (contract schema). Leave it. Do not merge it into the ledger
or the C-check module.

Already-split siblings — **do not re-merge:** `mdh_collapse.ts`,
`path_broken.ts`, `metrics.ts`, `cost_repo.py`, `cost_defaults.py`,
`eval_loaders*.py`, phase35 coverage matrix split, Worker
`combo_gates.test.ts` (tests already extracted; production gates still
live in `daily_path.ts`). At this tip there is **no** `event_entry.ts`.

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
say: **leftover occupancy stays in `daily_path.ts`.** That remains true
until a dedicated occupancy module is extracted *as leftover policy*,
not folded into combo gates.

### Allowed later extracts (one authority per lane)

1. **Combo gates → `combo_gates.ts`**  
   Move `comboEventGateOk`, `comboCsGateOk`, gate helpers, unknown-gate
   fail-closed. Point `combo_gates.test.ts` at the new module. Do **not**
   move leftover `!comboImpl` lid branches in the same commit.

2. **PIT entry → `event_entry.ts` (or equivalent)**  
   Disc-time / surprise / entry bar index / `pitMedian` used for entry.
   Do **not** relocate leftover occupancy predicates
   (`event_pre_mom_agree_hold` uses `momentumAt(entryIdx)` on purpose —
   occupancy vs Python unique; combo `pre_mom` is `entryIdx-1`).

3. **Leftover occupancy stays until (1)+(2) exist**  
   Then a third lane may move unique-22 lid branches + leftover CS books
   as **policy**, with occupancy-equal re-eval. Unifying leftover with
   `comboEventGateOk` is a rewrite (it widens or thins occupancy).

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

**`eval.ts` (2030).** Bar-native family evaluators + `barNativeHeldBook` +
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

### `paper_runtime/snapshot.py` (1407)

| Piece | Authority |
|-------|-----------|
| `_evaluate_publication_gate` / `_transition_policy` | **policy** (READY fail-closed) |
| `_coverage_v2_proof` / `_verify_coverage_v2_manifest` | **evidence** |
| `publish_ready_snapshot` sqlite copy / `_atomic_json` | **persistence** |
| `describe_snapshot` / `list_ready_snapshots` | **presentation** |

Extract along those lines if a lane needs locality. Do not split the
Coverage V2 proof construction to shrink LOC. Production READY stays
NO-GO; this file is the publication *machine*, not a GO switch.

### `r2_feature_context.py` (1160)

| Piece | Authority |
|-------|-----------|
| `parse_r2_structured_line` / `_bytes` | **parsing** |
| `normalize_r2_history_row` / tip row mappers | **normalization** |
| `repair_available_at_research` / `available_at_policy_document` | **policy** (research-only; never look-ahead) |
| `default_r2_get_object` / `build_*_context` | **orchestration** |
| `materialize_disposable_sqlite_mirror` | **persistence** (scratch; not experiment SoT) |

Four authorities in one file is the problem, not 1160 lines.

### `ingestion-premium/src/index.ts` (1439)

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

### `unique_logic/constants.py` (778)

**Policy** (gates, propose allow-list, occupancy parks, candidate exclude
reasons). It is not eval scores. Do not generate per-YAML constant files.
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
| Structural replacement | After digest lock: `n == 2254` → compiler digest + set-equality. After occupancy extract: occupancy-equal fixture, not N paraphrases |
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
| 3 | leftover occupancy as **policy** | unique-22 lid branches | **HOLD** in `daily_path.ts` (occupancy-equal re-eval required; do not unify with `comboEventGateOk`) |
| 4 | `r2_feature_context` parse vs normalize vs `available_at` policy | parse, normalize, then policy | **DONE** (`r2_feature_parse.py`, `r2_feature_normalize.py`, `r2_available_at.py`; orchestration stays) |
| 5 | `coverage_ledger` persist/read vs `evaluate_segment` | persist then evidence | **DONE** (`coverage_ledger_io.py`, `coverage_receipts.py`; COMPLETE predicates stay) |
| 6 | `snapshot.py` publication gate vs artifact write vs proof | policy, evidence, persist | **DONE** (`snapshot_publish_policy.py`, `snapshot_coverage_proof.py`, `snapshot_persist.py`) |
| 7 | Compiler owns `catalog_ids.ts` emit | generated **presentation** of policy IDs | **DONE** |
| 8 | Digest lock (pin `compile_catalog()` digest) | — | **DONE** `sha256:6ad5ba57dfa41…` |
| 9 | Mechanical YAML delete | files only | **DONE** (`yaml_still_present: false`) |
| 10 | ingestion-premium persist vs HTTP vs receipt | one of persist / presentation / evidence | **optional**; worker path frozen — in-place only |
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
