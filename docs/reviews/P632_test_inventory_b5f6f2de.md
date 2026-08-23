# Phase 6.3.2 P — test inventory at `b5f6f2de`

**Kind:** read-only inventory. Does **not** delete tests. Does **not** invent
`tests_after`. Does **not** flip GO.  
**SHA counted:** `b5f6f2ded30a2758533dfd673870c3c58799e173` (`b5f6f2de`)  
`docs: 6.3.2 wave-12 status after commits vs 02fb6cbd`  
**Isolation worktree:** `/Users/taku/tmp/qp-p632-test-inventory-b5f6f2de` on
`docs/p632-test-inventory-b5f6f2de` off `origin/grok/phase63-ci-source-closure`.  
**Class SoT:** [`docs/phase63_test_audit.md`](../phase63_test_audit.md) (Lane 17 / 17b).  
Prior collect freezes (cite, do not rewrite): [`P632_test_inventory.md`](P632_test_inventory.md)
(`3ab87d0`, collected **1353**); [`P632_test_inventory_now.md`](P632_test_inventory_now.md)
(`07b4435`, collected **1379**); [`P632_test_inventory_40d1aa90.md`](P632_test_inventory_40d1aa90.md)
(`40d1aa90`, collected **1426**); [`P632_test_inventory_67fcbd7c.md`](P632_test_inventory_67fcbd7c.md)
(`67fcbd7c`, collected **1448**); [`P632_test_inventory_ed94d504.md`](P632_test_inventory_ed94d504.md)
(`ed94d504`, collected **1470**); [`P632_test_inventory_5103b26b.md`](P632_test_inventory_5103b26b.md)
(`5103b26b`, collected **1496**); [`P632_test_inventory_3b64bdfc.md`](P632_test_inventory_3b64bdfc.md)
(`3b64bdfc`, collected **1503**); [`P632_test_inventory_242c2484.md`](P632_test_inventory_242c2484.md)
(`242c2484`, collected **1506**); [`P632_test_inventory_2b82ec7d.md`](P632_test_inventory_2b82ec7d.md)
(`2b82ec7d`, collected **1509**); [`P632_test_inventory_02fb6cbd.md`](P632_test_inventory_02fb6cbd.md)
(`02fb6cbd`, collected **1505**); [`P632_test_inventory_cf7da56c.md`](P632_test_inventory_cf7da56c.md)
(`cf7da56c`, collected **1504**).  
Mass / READY / Phase 7 Controlled Pilot / reconstitution apply: **unchanged
NO-GO / OFF / false**.

Do **not** treat this count as a win. Do **not** treat a later drop as a win
unless the dropped rows were mechanism-replaced and the never-delete list
still has a remaining owner. Combinatorial paraphrases, integer catalog-size
freezes, and Python restatements of Worker policy already unit-tested are
cost. Count growth is **not** a win.

Brief §P asked `tests_before` ~ **1282** collected. This file re-ran
`pytest --collect-only`. It does **not** invent `tests_after`.

---

## Method

| Surface | How counted (this isolation tree at `b5f6f2de`) |
|---------|-------------------------------------------------|
| Python collected | `/Users/taku/GitHub/quant-platform/.venv/bin/python -m pytest --collect-only -q tests/` from this worktree. Python 3.11.15, pytest 9.1.1 (`pyproject.toml` `addopts = "-q"`). **PASS** (exit 0). Quiet `-q` prints 154 per-file counts summing to **1504**. Confirming with addopts cleared: `1504 tests collected in 4.78s`. `PYTHONPATH` unset. |
| `tests/test_*.py` files | `git ls-files 'tests/test_*.py'` at HEAD (no `__pycache__`) |
| Worker first-party | `git ls-files` `platform/workers/**/*.{test.ts,test.mjs}` excluding `node_modules` |
| YAML | `specs/research_logics/**/*.{yaml,yml}` |

Runtime skip/pass was **not** re-run. Collect-only ≠ green pytest.

---

## Counts (actual)

| Metric | Brief §P (`tests_before`) | `cf7da56c` inventory | This SHA (`b5f6f2de`) |
|--------|--------------------------:|---------------------:|----------------------:|
| **tests_before (collected)** | ~**1282** | — | — |
| **tests_after (collected)** | *not invented* | *not invented* | *not invented* |
| **collected now (actual)** | — | **1504** | **1504** |
| `tests/test_*.py` files | — | **154** | **154** |
| Worker `*.test.ts` | — | **22** | **25** |
| Worker `*.test.mjs` | — | **4** | **4** |
| Worker first-party test files | — | **26** | **29** |
| Worker source `it(` / `test(` | — | **184** | **195** (not vitest collect) |
| `specs/research_logics` YAML | — | **0** | **0** (dir exists; only `README.md`) |

`1504 = 1504 < 1505 < 1509 > 1506 > 1503 > 1496 > 1470 > 1448 > 1426 > 1379 > 1282`.
Python collected is **unchanged** vs `cf7da56c` (`tests/test_*.py` **154**
unchanged; empty `git diff cf7da56c -- tests/`). Later landings vs `cf7da56c`
added three Worker first-party files (**26 → 29**; `it(` / `test(` **184 → 195**):

- `ingestion-premium/src/write_path_config.test.ts` (4 `it(`; `4f111320`)
- `ingestion-premium/src/rate_limit.test.ts` (4 `it(`; `5b4db591`)
- `ingestion-premium/src/r2_structured_writer.test.ts` (2 `it(`; `0194c64a`)

Sibling landing that did **not** add a Python module:
`cfbaa58e` (`index.test.ts` 11→12 `it(`: unbound `DATA_EXPORT_TOKEN` is 401).
Loose `\bit(` / `\btest(` is **196** because `index.test.ts` also contains
`.test(put.key)`; **195** is the line-start `it(` / `test(` count, comparable
to `cf7da56c` **184**. Worker file-count growth is **not** a win. YAML under
`specs/research_logics` is **0**; compiled catalog identity is not those files.

This commit adds **0** test modules and deletes **0** test modules.

---

## Remaining mechanism replacements (not closed by this count)

Do **not** delete these surfaces until the replacement owns the invariant.
Do **not** delete them in this lane. Count is not the close.

### 1. Leftover `catalog.ts` grep in `test_phase35_premium_set.py` — **CLOSED**

**Replacement asked:** drop Python restatements / Worker-body greps of
policy already unit-tested in the Worker, without deleting real Py↔TS
*execution* parity.

**CLOSED** (`44642dfc`; still closed at this SHA):

- `tests/test_phase35_premium_set.py` (11 collected) no longer greps
  `catalog.ts`. `test_contract_json_matches_premium_core_datasets` is JSON
  contract vs Python `PREMIUM_CORE_DATASETS` set-equality. Keep it.
- Worker `catalog.test.ts` still has 2 `it(`: JSON contract `dataset_id`
  set vs `PREMIUM_CORE_DATASETS` ids (`23a5cbb9`) and dateMode /
  `dayParam` mapping (`2218b861`).

Do not re-add the `catalog.ts` import / `rawContracts.map` /
no-hardcoded-id body greps.
[`docs/phase63_test_audit.md`](../phase63_test_audit.md) classifies
`test_phase35_availability.py` / `test_phase35_premium_set.py` as
Invariant (Python↔Worker contract).

### 2. NK rebuild Python grep in `test_identity_runtime_parity.py` — **CLOSED**

**Replacement asked:** Worker-unit the natural-key v2 rebuild (canonical
fn, atomic swap, post-publish audit) instead of Python source-grep of
`natural_key_migration.ts` / `index.ts`.

**CLOSED** (`8fc9fa30`; still closed at this SHA):

- `platform/workers/ingestion-premium/src/natural_key_migration.test.ts`
  (5 `it(`) remains.
- `tests/test_identity_runtime_parity.py` (2 collected) remains execution
  parity + SQL `0005` defer-without-mutate.

[`docs/phase63_test_audit.md`](../phase63_test_audit.md) classifies
`test_identity_runtime_parity.py` as Invariant. Do not delete the file as
a “grep.” Do not re-add the rebuild source-grep.

### 3. `daily_path` liquidity comment grep — **HOLD**

**Replacement asked:** do not Python-grep `daily_path.ts` comments for
liquidity-bucket policy already live in `cost_models`.

**HOLD at this SHA:**

- `tests/test_cf_cost_verify.py`
  `test_liq_buckets_match_cost_models_sot` still greps
  `research-mass-eval/src/daily_path.ts` for the comment
  `LIQUIDITY_TX_MULT high/mid/low (1.0/1.5/2.5)` plus
  `if (!finite(adv))` / `costAdvIncomplete` / `cost_adv_incomplete`.
- Occupancy leftover in `daily_path.ts` stays **HOLD**. Python must not
  re-grep Worker bodies for leftover `pre_mom` occupancy
  (`combo_gates.test.ts` is SoT). Do not re-add Python greps of
  `daily_path.ts` leftover occupancy.

Cost-model split files (live math, not husks) stay on the never-delete
list. This HOLD is not a missing-CLOSE for this inventory.

### 4. `write_path_config` second 23-id list — **CLOSED**

**Replacement asked:** do not keep a second hardcoded Premium-core 23-id
list beside the JSON contract that `catalog.ts` already maps.

**CLOSED at this SHA** (`4f111320`):

- `platform/workers/ingestion-premium/src/write_path_config.ts` now
  exports `PREMIUM_CORE_DATASET_IDS = PREMIUM_CORE_DATASETS.map(spec =>
  spec.id)` (catalog JSON map, not a handwritten 23-string array).
  `HIGH_VOLUME_DATASETS` is a `Set` of that same mapped array.
- `write_path_config.test.ts` landed (4 `it(`): JSON contract
  `dataset_id` set vs mapped ids vs `PREMIUM_CORE_DATASETS`; `isR2Only`
  default / allowlist / unknown `jsda_` dataset.

Do not re-add a handwritten 23-id copy. JSON contract remains catalog
identity SoT. Do not treat the matching 23-id identity as Dataset
COMPLETE 23.

### 5. `persist_records` / `master_scd2` / `ops_*` — **OPEN** (still untested)

**Replacement asked:** Worker-unit persist / SCD2 / ops surfaces instead
of leaving production modules without first-party tests.

**Still untested at this SHA** (`origin/grok/phase63-ci-source-closure`):

| Module | Exports (untested here) | First-party `*.test.ts` |
|--------|-------------------------|-------------------------|
| `ingestion-premium/src/persist_records.ts` | `upsertWatermark`, `upsertRecords` | **none** (`retry_jitter.test.ts` only greps the file for no `Math.random`) |
| `ingestion-premium/src/master_scd2/write.ts` | `payloadToMasterRecord`, `writeMasterScd2` | **none** |
| `ingestion-premium/src/ops_artifacts_plan.ts` | `handleArtifactsJoinPlan` | **none** |
| `ingestion-premium/src/ops_cold_archive.ts` | `handleArchiveCold` | **none** |
| `ingestion-premium/src/ops_parquet_manifest.ts` | `handleParquetManifest` | **none** |
| `ingestion-premium/src/ops_prune_changelog.ts` | `handlePruneChangelog` | **none** |

Python `tests/test_ops_applied_pins.py` / `test_ops_projection_publish.py`
/ `test_ops_projection_publish_guard.py` / `test_phase61_ops_projection.py`
are ops *projection* / pins, not these Worker modules. They are not a
substitute.

Sibling commits / worktrees for `master_scd2` write unit and `ops_*`
token fail-closed have **not** landed on
`origin/grok/phase63-ci-source-closure`. This inventory did not merge
them. `persist_records.ts` still has no `*.test.ts` on this SHA. Do not
invent those tests as present.

This OPEN is not a missing-CLOSE for this inventory. Count growth of
Worker units that *did* land (`write_path_config` / `rate_limit` /
`r2_structured_writer`) is **not** a win and does not close persist /
SCD2 / ops.

### 6. `verify_ci` not merge-gate — **OPEN**

**Replacement asked:** merge gate is GitHub context `ci-aggregate` after
authenticated receipts **and** `verify_ci`. Do not add
`.github/workflows`.

**Still OPEN at this SHA:**

- `scripts/verify_ci.sh` is mandatory *local* CI (7 workers; no
  `VERIFY_*` skips). That is **not** the merge gate.
- No `.github/workflows` in the tree. Six-lane `npm test` receipts
  alone skip Python/catalog and are **not** `verify_ci`.
- Local `verify_ci` PASS documented at `cf7da56c`
  ([`P632_verify_ci_cf7da56c.md`](P632_verify_ci_cf7da56c.md): **1500
  passed / 4 skipped**) is a different SHA, not this collect, and
  **not** a posted GitHub context. This isolation did **not** re-run
  `scripts/verify_ci.sh`.
- Live producer Worker `quant-platform-ci-aggregate` remains a HUMAN
  first-deploy (print-only helper does not create it). Collect-only
  does not post `ci-aggregate`.

Do not treat this inventory, or a local `verify_ci: ok`, as merge-gate
green.

### 7. Catalog compact — optional **HOLD**

Compact `family + template + parameter matrix` is **not** implemented.
`specs/research_catalog/migration.jsonl` is still runtime load SoT (2254
expanded rows). Expanded compiled n=**2254** is a freeze identity, not a
compact-catalog substitute. Manifest digest
`sha256:6ad5ba57dfa41ed9a97e5895d9238040fbb5539b310a2ea4aa349172b6cb8c69`;
`go: false`; `yaml_still_present: false`. `yaml_overlay_allowed()` is
**False** unless `QP_ALLOW_YAML_OVERLAY=1`.

This compact is **optional HOLD**. Do not treat it as a required reduction
path for this inventory. Do not report 2254/2092 as a product win. Combo +N
**HOLD**. unique22 leftover occupancy **HOLD**. YAML overlay stays fail-closed
without `QP_ALLOW_YAML_OVERLAY=1`. YAML n=**0**.

Keep compiler-owned emit, digest lock, set-equality, unique22 park legacy.
Do not re-open YAML `+N` or AND-as-product to “compact.”

### 8. `combo_gates.test.ts` — **SoT** (not a remaining close)

`platform/workers/research-mass-eval/src/combo_gates.test.ts` is SoT for
Worker gate policy (unknown gate fail-closed, cheap_pb vs `pb_rising`,
leftover `pre_mom` occupancy). Source `it(` / `test(` count at this SHA:
**20**. Do **not** delete.

Python must not re-grep Worker bodies for the same policy. Occupancy **HOLD**
remains in `daily_path.ts`. Catalog/Python cheap_pb constants and YAML
leftover-vs-lifted stay; they are not Worker-body greps.

---

## Invariants that must NEVER be deleted

These stay even if collected count is the metric someone wants to move:

- PIT / `as_of` / `available_at <= as_of` / pipeline fetch-completion timestamps
- Receipts: Ed25519 eligibility, issue/empty-raw ban, signature forgery, host
  PEM isolation
- False-COMPLETE / empty inventory / PARTIAL must not publish READY / sticky
  COMPLETE
- Immutable READY snapshot publication; coherence without receipts
- Mass fail-closed; gateway fail-closed
- `tests/test_baseline_catalog.py` (rejected S1–S5; Mass/READY false)
- Worker `combo_gates.test.ts` leftover occupancy / cheap_pb SoT (replace
  Python greps; do not delete the Worker tests)
- Occupancy band asserts; unique22 park not silently unparked
- `RECONSTITUTION_APPLY` stays false
- Cost-model split files (live math, not husks)

No modules deleted this lane. **Added modules: 0** (this commit is docs only).

---

## Honesty

- Collect-only **succeeded**. Collected **1504**. Brief `tests_before` ~**1282**.
  Prior inventory **1504** at `cf7da56c`. `tests_after` is **not invented**.
  Python count is unchanged. That is **not** a win: `daily_path` liquidity
  comment grep remains **HOLD**; `persist_records` / `master_scd2` / `ops_*`
  remain untested on origin; `verify_ci` is not merge-gate. Worker
  first-party **26 → 29** is count growth, also not a win.
- Collect-only ≠ green pytest. This snapshot does not re-run host PEM isolation
  or a full `tests/` pass. A later `verify_ci` runtime at `cf7da56c` is a
  different SHA and is not this collect and is **not** merge-gate.
- Worker **29** is a file count, not `vitest --collect`. Source `it(` / `test(`
  count **195** is also not vitest collect.
- YAML under `specs/research_logics` is **0**; compiled catalog identity is
  not those files.
- Leftover `catalog.ts` grep (**CLOSED** `44642dfc`). NK rebuild Python grep
  (**CLOSED** `8fc9fa30`). `write_path_config` second 23-id list (**CLOSED**
  `4f111320`). `daily_path` liquidity comment grep **HOLD**.
  `persist_records` / `master_scd2` / `ops_*` still untested on this SHA
  (**OPEN**). `verify_ci` is local authority, not merge-gate (**OPEN**).
  Catalog compact is optional **HOLD**, not missing-CLOSE.
- Availability/identity wrapper greps, coverage-segment / raw-page
  retain greps, leftover `catalog.ts` greps, NK rebuild greps, and the
  write-path 23-id copy landed as Worker units after `02fb6cbd`. They are
  not remaining greps at this SHA. Do not re-add them. Do not delete
  `tests/test_identity_runtime_parity.py` execution parity.
- Last-known live facts from prior freezes (not re-fetched this lane):
  22 COMPLETE / 4 PARTIAL, Projection STALE, B0 UNKNOWN, READY null, applied
  cursor null. Cron PASS is not Coverage COMPLETE.

This file is a now-inventory receipt at `b5f6f2de`, not a pass.
