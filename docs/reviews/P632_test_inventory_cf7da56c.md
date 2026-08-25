# Phase 6.3.2 P — test inventory at `cf7da56c`

**Kind:** read-only inventory. Does **not** delete tests. Does **not** invent
`tests_after`. Does **not** flip GO.  
**SHA counted:** `cf7da56c17260da2c2693540f28af91c849bd542` (`cf7da56c`)  
`docs: review index names HEAD 02fb6cbd vs origin/main b5c326a`  
**Isolation worktree:** `/private/tmp/qp-p632-test-inventory-cf7da56c` on
`docs/p632-test-inventory-cf7da56c` off `origin/grok/phase63-ci-source-closure`.  
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
(`02fb6cbd`, collected **1505**).  
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

| Surface | How counted (this isolation tree at `cf7da56c`) |
|---------|-------------------------------------------------|
| Python collected | `/Users/taku/GitHub/quant-platform/.venv/bin/python -m pytest --collect-only -q tests/` from this worktree. Python 3.11.15, pytest 9.1.1 (`pyproject.toml` `addopts = "-q"`). **PASS** (exit 0). Quiet `-q` prints 154 per-file counts summing to **1504**. Confirming with addopts cleared: `1504 tests collected in 0.75s`. `PYTHONPATH` unset. |
| `tests/test_*.py` files | `git ls-files 'tests/test_*.py'` at HEAD (no `__pycache__`) |
| Worker first-party | `git ls-files` `platform/workers/**/*.{test.ts,test.mjs}` excluding `node_modules` |
| YAML | `specs/research_logics/**/*.{yaml,yml}` |

Runtime skip/pass was **not** re-run. Collect-only ≠ green pytest.

---

## Counts (actual)

| Metric | Brief §P (`tests_before`) | `02fb6cbd` inventory | This SHA (`cf7da56c`) |
|--------|--------------------------:|---------------------:|----------------------:|
| **tests_before (collected)** | ~**1282** | — | — |
| **tests_after (collected)** | *not invented* | *not invented* | *not invented* |
| **collected now (actual)** | — | **1505** | **1504** |
| `tests/test_*.py` files | — | **154** | **154** |
| Worker `*.test.ts` | — | **21** | **22** |
| Worker `*.test.mjs` | — | **4** | **4** |
| Worker first-party test files | — | **25** | **26** |
| Worker source `it(` / `test(` | — | **177** | **184** (not vitest collect) |
| `specs/research_logics` YAML | — | **0** | **0** (dir exists; only `README.md`) |

`1504 < 1505 < 1509 > 1506 > 1503 > 1496 > 1470 > 1448 > 1426 > 1379 > 1282`. Later
landings vs `02fb6cbd` replaced two Python Worker-body greps (collected
**1505 → 1504**; `tests/test_*.py` **154** unchanged) and added one Worker
first-party file (**25 → 26**; `it(` / `test(` **177 → 184**):
`ingestion-premium/src/natural_key_migration.test.ts` (5 `it(`; `8fc9fa30`).
Sibling landings that did **not** add a Python module: leftover `catalog.ts`
grep dropped in-place (`44642dfc`; `test_phase35_premium_set.py` stayed 11);
dateMode JSON contract Worker unit (`2218b861`; `catalog.test.ts` 1→2);
JSDA fail-closed run-token (`afd94e58`; `ingestion-jsda/src/index.test.ts`
2→4 `it(`). Dropped Python row (not a delete of the never-delete list):
`test_identity_runtime_parity.py` 3→2 lost
`test_worker_rebuild_uses_canonical_fn_atomic_swap_and_post_publish_audit`
(`8fc9fa30`). That drop is **not** a consolidation win and **not** a GO:
remaining greps still have remaining owners (below). Worker file-count
growth is **not** a win. YAML under `specs/research_logics` is **0**;
compiled catalog identity is not those files.

This commit adds **0** test modules and deletes **0** test modules.

---

## Remaining mechanism replacements (not closed by this count)

Do **not** delete these surfaces until the replacement owns the invariant.
Do **not** delete them in this lane. Count is not the close.

### 1. Leftover `catalog.ts` grep in `test_phase35_premium_set.py` — **CLOSED**

**Replacement asked:** drop Python restatements / Worker-body greps of
policy already unit-tested in the Worker, without deleting real Py↔TS
*execution* parity.

**CLOSED at this SHA** (`44642dfc`):

- `tests/test_phase35_premium_set.py` (11 collected) no longer greps
  `catalog.ts`. `test_typescript_catalog_matches_python` was replaced
  in-place by `test_contract_json_matches_premium_core_datasets` (JSON
  contract vs Python `PREMIUM_CORE_DATASETS` set-equality). That identity
  is not a Worker-body grep; keep it.
- Worker `catalog.test.ts` now has 2 `it(`: JSON contract `dataset_id`
  set vs `PREMIUM_CORE_DATASETS` ids (`23a5cbb9`) and dateMode /
  `dayParam` mapping (`2218b861`). Catalog.ts maps
  `contractDocument.datasets` / `rawContracts.map`; no hardcoded
  `id: "equities_master"` list.

Do not re-add the `catalog.ts` import / `rawContracts.map` /
no-hardcoded-id body greps.
[`docs/phase63_test_audit.md`](../phase63_test_audit.md) classifies
`test_phase35_availability.py` / `test_phase35_premium_set.py` as
Invariant (Python↔Worker contract). Python file remains Python policy
execution (11 collected). Catalog/Python cheap_pb constants and YAML
leftover-vs-lifted stay; they are not Worker-body greps.

### 2. NK rebuild Python grep in `test_identity_runtime_parity.py` — **CLOSED**

**Replacement asked:** Worker-unit the natural-key v2 rebuild (canonical
fn, atomic swap, post-publish audit) instead of Python source-grep of
`natural_key_migration.ts` / `index.ts`.

**CLOSED at this SHA** (`8fc9fa30`):

- `platform/workers/ingestion-premium/src/natural_key_migration.test.ts`
  landed (5 `it(`): 0005 control-row identity; incomplete short-ratio
  hash; fail-closed PENDING / rejected live audit; rebuild via canonical
  `naturalKey` + one-batch swap + READY publish; ingest gate on READY
  and no payload `available_at`.
- `tests/test_identity_runtime_parity.py` (2 collected) dropped
  `test_worker_rebuild_uses_canonical_fn_atomic_swap_and_post_publish_audit`.
  Remaining rows are execution parity and SQL `0005` defer-without-mutate.

`test_python_and_worker_share_canonical_identity_and_availability_semantics`
is Invariant (real Py↔TS *execution* parity), not echo. Do not delete
the file as a “grep.”
[`docs/phase63_test_audit.md`](../phase63_test_audit.md) classifies
`test_identity_runtime_parity.py` as Invariant. Keep the execution
parity and the SQL `0005` defer-without-mutate row. Do not re-add the
rebuild source-grep.

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

### 4. `write_path_config` second 23-id list — **OPEN** (still present)

**Replacement asked:** do not keep a second hardcoded Premium-core 23-id
list beside the JSON contract that `catalog.ts` already maps.

**Still present at this SHA:**

- `platform/workers/ingestion-premium/src/write_path_config.ts`
  exports `PREMIUM_CORE_DATASET_IDS` as a 23-string array (same order
  as `packages/data_plane/data_contracts/jquants_premium_core.json`
  `dataset_id`s). `HIGH_VOLUME_DATASETS` is a spread of that same array,
  not a third handwritten list.
- No `write_path_config.test.ts` on
  `origin/grok/phase63-ci-source-closure`. Worker `catalog.test.ts`
  owns JSON↔`PREMIUM_CORE_DATASETS` identity; it does **not** own the
  write-path copy.
- Sibling `test/premium-r2-structured-writer-worker-unit` (`8c0b01c9`)
  adds `r2_structured_writer.test.ts` and has **not** landed on this
  SHA. It does **not** touch `write_path_config.ts`. This inventory
  did not merge it.

Do not treat the matching 23-id copy as Dataset COMPLETE 23. JSON
contract remains catalog identity SoT. This OPEN is not a missing-CLOSE
for this inventory.

### 5. `verify_ci` not merge-gate — **OPEN**

**Replacement asked:** merge gate is GitHub context `ci-aggregate` after
authenticated receipts **and** `verify_ci`. Do not add
`.github/workflows`.

**Still OPEN at this SHA:**

- `scripts/verify_ci.sh` is mandatory *local* CI (7 workers; no
  `VERIFY_*` skips). That is **not** the merge gate.
- No `.github/workflows` in the tree. Six-lane `npm test` receipts
  alone skip Python/catalog and are **not** `verify_ci`.
- Local `verify_ci` PASS documented at `02fb6cbd`
  ([`P632_verify_ci_02fb6cbd.md`](P632_verify_ci_02fb6cbd.md): **1501
  passed / 4 skipped**) is a different SHA, not this collect, and
  **not** a posted GitHub context. This isolation did **not** re-run
  `scripts/verify_ci.sh`.
- Live producer Worker `quant-platform-ci-aggregate` remains a HUMAN
  first-deploy (print-only helper does not create it). Collect-only
  does not post `ci-aggregate`.

Do not treat this inventory, or a local `verify_ci: ok`, as merge-gate
green.

### 6. Catalog compact — optional **HOLD**

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

### 7. `combo_gates.test.ts` — **SoT** (not a remaining close)

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
  Prior inventory **1505** at `02fb6cbd`. `tests_after` is **not invented**.
  The −1 vs `02fb6cbd` is one mechanism-replaced Python grep (NK rebuild),
  not a win: `daily_path` liquidity comment grep remains **HOLD**;
  `write_path_config` second 23-id list remains **OPEN**; `verify_ci` is
  not merge-gate. Worker first-party **25 → 26** is count growth, also
  not a win.
- Collect-only ≠ green pytest. This snapshot does not re-run host PEM isolation
  or a full `tests/` pass. A later `verify_ci` runtime at `02fb6cbd` is a
  different SHA and is not this collect and is **not** merge-gate.
- Worker **26** is a file count, not `vitest --collect`. Source `it(` / `test(`
  count **184** is also not vitest collect.
- YAML under `specs/research_logics` is **0**; compiled catalog identity is
  not those files.
- Leftover `catalog.ts` grep in `test_phase35_premium_set.py` (**CLOSED**
  `44642dfc`). NK rebuild Python grep (**CLOSED** `8fc9fa30`).
  `daily_path` liquidity comment grep **HOLD**. `write_path_config`
  second 23-id list still present (**OPEN**; sibling `8c0b01c9` has not
  landed and does not own it). `verify_ci` is local authority, not
  merge-gate (**OPEN**). Catalog compact is optional **HOLD**, not
  missing-CLOSE.
- Availability/identity wrapper greps, coverage-segment / raw-page
  retain greps, leftover `catalog.ts` greps, and NK rebuild greps landed
  as Worker units after `2b82ec7d`. They are not remaining greps at this
  SHA. Do not re-add them. Do not delete
  `tests/test_identity_runtime_parity.py` execution parity.
- Last-known live facts from prior freezes (not re-fetched this lane):
  22 COMPLETE / 4 PARTIAL, Projection STALE, B0 UNKNOWN, READY null, applied
  cursor null. Cron PASS is not Coverage COMPLETE.

This file is a now-inventory receipt at `cf7da56c`, not a pass.
