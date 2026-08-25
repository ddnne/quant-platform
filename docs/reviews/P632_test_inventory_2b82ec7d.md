# Phase 6.3.2 P — test inventory at `2b82ec7d`

**Kind:** read-only inventory. Does **not** delete tests. Does **not** invent
`tests_after`. Does **not** flip GO.  
**SHA counted:** `2b82ec7d26f26464ac5ce8e4f53d5f6a039117a6` (`2b82ec7d`)  
`ops: cf_premium_backfill uses shared official-index HTML reader`  
**Isolation worktree:** `/private/tmp/qp-p632-test-inventory-2b82ec7d` on
`docs/p632-test-inventory-2b82ec7d` off `origin/grok/phase63-ci-source-closure`.  
**Class SoT:** [`docs/phase63_test_audit.md`](../phase63_test_audit.md) (Lane 17 / 17b).  
Prior collect freezes (cite, do not rewrite): [`P632_test_inventory.md`](P632_test_inventory.md)
(`3ab87d0`, collected **1353**); [`P632_test_inventory_now.md`](P632_test_inventory_now.md)
(`07b4435`, collected **1379**); [`P632_test_inventory_40d1aa90.md`](P632_test_inventory_40d1aa90.md)
(`40d1aa90`, collected **1426**); [`P632_test_inventory_67fcbd7c.md`](P632_test_inventory_67fcbd7c.md)
(`67fcbd7c`, collected **1448**); [`P632_test_inventory_ed94d504.md`](P632_test_inventory_ed94d504.md)
(`ed94d504`, collected **1470**); [`P632_test_inventory_5103b26b.md`](P632_test_inventory_5103b26b.md)
(`5103b26b`, collected **1496**); [`P632_test_inventory_3b64bdfc.md`](P632_test_inventory_3b64bdfc.md)
(`3b64bdfc`, collected **1503**); [`P632_test_inventory_242c2484.md`](P632_test_inventory_242c2484.md)
(`242c2484`, collected **1506**).  
Mass / READY / Phase 7 Controlled Pilot / reconstitution apply: **unchanged
NO-GO / OFF / false**.

Do **not** treat this count as a win. Do **not** treat a later drop as a win
unless the dropped rows were mechanism-replaced and the never-delete list
still has a remaining owner. Combinatorial paraphrases, integer catalog-size
freezes, and Python restatements of Worker policy already unit-tested are
cost.

Brief §P asked `tests_before` ~ **1282** collected. This file re-ran
`pytest --collect-only`. It does **not** invent `tests_after`.

---

## Method

| Surface | How counted (this isolation tree at `2b82ec7d`) |
|---------|-------------------------------------------------|
| Python collected | `/Users/taku/GitHub/quant-platform/.venv/bin/python -m pytest --collect-only -q tests/` from this worktree. Python 3.11.15, pytest 9.1.1 (`pyproject.toml` `addopts = "-q"`). **PASS** (exit 0). Quiet `-q` prints 154 per-file counts summing to **1509**. Confirming with addopts cleared: `1509 tests collected in 0.69s`. `PYTHONPATH` unset. |
| `tests/test_*.py` files | `git ls-files 'tests/test_*.py'` at HEAD (no `__pycache__`) |
| Worker first-party | `git ls-files` `platform/workers/**/*.{test.ts,test.mjs}` excluding `node_modules` |
| YAML | `specs/research_logics/**/*.{yaml,yml}` |

Runtime skip/pass was **not** re-run. Collect-only ≠ green pytest.

---

## Counts (actual)

| Metric | Brief §P (`tests_before`) | `242c2484` inventory | This SHA (`2b82ec7d`) |
|--------|--------------------------:|---------------------:|----------------------:|
| **tests_before (collected)** | ~**1282** | — | — |
| **tests_after (collected)** | *not invented* | *not invented* | *not invented* |
| **collected now (actual)** | — | **1506** | **1509** |
| `tests/test_*.py` files | — | **153** | **154** |
| Worker `*.test.ts` | — | **18** | **18** |
| Worker `*.test.mjs` | — | **4** | **4** |
| Worker first-party test files | — | **22** | **22** |
| Worker source `it(` / `test(` | — | **154** | **158** (not vitest collect) |
| `specs/research_logics` YAML | — | **0** | **0** (dir exists; only `README.md`) |

`1509 > 1506 > 1503 > 1496 > 1470 > 1448 > 1426 > 1379 > 1282`. Later
landings grew the suite vs `242c2484` (new `tests/test_cf_premium_backfill_cli.py`
4 collected; `test_jsda_otc_official_domain.py` 17→18;
`test_ingestion_secrets_worker_contract.py` 4→2 after Worker unit replacement
`908e8ef4`; Worker first-party files **22** unchanged; Worker source
`it(` / `test(` **154 → 158**, `ingestion-secrets/src/index.test.ts` 2→6).
That is **not** a consolidation win and **not** a GO. The secrets drop is a
mechanism replacement of a grep; net collected still grew. YAML under
`specs/research_logics` is **0**; compiled catalog identity is not those
files.

This commit adds **0** test modules and deletes **0** test modules.

---

## Remaining mechanism replacements (not closed by this count)

Do **not** delete these surfaces until the replacement owns the invariant.
Do **not** delete them in this lane. Count is not the close.

### 1. Phase 35 availability / identity / catalog Python greps — **OPEN** (siblings have not landed)

**Replacement asked:** drop Python restatements / Worker-body greps of
policy already unit-tested in the Worker, without deleting real Py↔TS
*execution* parity.

**Still OPEN at this SHA:**

- `tests/test_phase35_availability.py` (21 collected) still source-greps
  `ingestion-premium/src/{catalog,availability,identity}.ts`:
  `test_worker_catalog_imports_the_same_contract_document` (JSON import /
  `contractDocument.datasets` / no hardcoded `id: "equities_bars_daily"`)
  and `test_worker_wrappers_delegate_contract_policy_and_identity_constants`
  (`?? "ingest_time_conservative"` / `pickFromContract` / JST clock
  strings `2024-11-05`, `15:30:00`, `15:00:00`, `11:30:00`).
- `tests/test_phase35_premium_set.py` (11 collected)
  `test_typescript_catalog_matches_python` still greps `catalog.ts` for
  the same JSON import / `rawContracts.map` / no hardcoded
  `id: "equities_master"`. JSON contract vs Python `PREMIUM_CORE_DATASETS`
  set-equality is not a Worker-body grep; keep that identity.
- Worker `identity.test.ts` at this SHA is still the one `it(` for
  `crypto.randomUUID` (`newRunId`). It does **not** own JST clocks.
  No `catalog.test.ts` / `availability.test.ts` on
  `origin/grok/phase63-ci-source-closure`.
- Siblings **exist** and have **not** landed on this SHA:
  `test/premium-catalog-identity` (`6954f7e6`) and
  `test/premium-identity-jst-clocks` (`ba933ed2`) are each 1 commit off
  origin; they are **not** this collect. No availability Worker-unit
  commit is on origin. This inventory did not merge them.

`tests/test_identity_runtime_parity.py` is Invariant (real Py↔TS
*execution* parity), not echo. Do not delete it as a “grep.”
[`docs/phase63_test_audit.md`](../phase63_test_audit.md) classifies
`test_phase35_availability.py` / `test_phase35_premium_set.py` as
Invariant (Python↔Worker contract). Keep until the Worker unit tests
own the grepped strings. Catalog/Python cheap_pb constants and YAML
leftover-vs-lifted stay; they are not Worker-body greps. Do not re-add
Python greps of `daily_path.ts` / leftover occupancy.

Secrets Python grep of `ingestion-secrets/src/index.ts` is **not**
remaining here: `908e8ef4` moved request/auth/upstream to
`ingestion-secrets/src/index.test.ts` (6 `it(`). Python file remains
JSON contract identity (2 collected). Do not re-add body greps.

### 2. `verify_ci` not merge-gate — **OPEN**

**Replacement asked:** merge gate is GitHub context `ci-aggregate` after
authenticated receipts **and** `verify_ci`. Do not add
`.github/workflows`.

**Still OPEN at this SHA:**

- `scripts/verify_ci.sh` is mandatory *local* CI (7 workers; no
  `VERIFY_*` skips). That is **not** the merge gate.
- No `.github/workflows` in the tree. Six-lane `npm test` receipts
  alone skip Python/catalog and are **not** `verify_ci`.
- Local `verify_ci` PASS documented at `242c2484`
  ([`P632_verify_ci_242c2484.md`](P632_verify_ci_242c2484.md): **1502
  passed / 4 skipped**) is a different SHA, not this collect, and
  **not** a posted GitHub context. This isolation did **not** re-run
  `scripts/verify_ci.sh`.
- Live producer Worker `quant-platform-ci-aggregate` remains a HUMAN
  first-deploy (print-only helper does not create it). Collect-only
  does not post `ci-aggregate`.

Do not treat this inventory, or a local `verify_ci: ok`, as merge-gate
green.

### 3. Catalog compact — optional **HOLD**

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

### 4. `combo_gates.test.ts` — **SoT** (not a remaining close)

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

- Collect-only **succeeded**. Collected **1509**. Brief `tests_before` ~**1282**.
  Prior inventory **1506** at `242c2484`. `tests_after` is **not invented**.
  The +3 vs `242c2484` (and `tests/test_*.py` **153 → 154**) is not a win.
- Collect-only ≠ green pytest. This snapshot does not re-run host PEM isolation
  or a full `tests/` pass. A later `verify_ci` runtime at `242c2484` is a
  different SHA and is not this collect and is **not** merge-gate.
- Worker **22** is a file count, not `vitest --collect`. Source `it(` / `test(`
  count **158** is also not vitest collect.
- YAML under `specs/research_logics` is **0**; compiled catalog identity is
  not those files.
- Phase 35 availability/identity/catalog Python greps (**OPEN**; siblings
  `6954f7e6` / `ba933ed2` have not landed). `verify_ci` is local authority,
  not merge-gate (**OPEN**). Catalog compact is optional **HOLD**, not
  missing-CLOSE.
- Generated IR TypedDict (`e20be4d9`, `evaluation_ir_types.generated.py`)
  and secrets Worker-unit move (`908e8ef4`) landed after `242c2484`. They
  are not remaining greps at this SHA. TypedDict still cannot ban unknown
  fields; runtime schema remains SoT. Do not delete
  `tests/test_evaluation_ir.py` or
  `research-mass-eval/src/evaluation_ir.test.ts`.
- Last-known live facts from prior freezes (not re-fetched this lane):
  22 COMPLETE / 4 PARTIAL, Projection STALE, B0 UNKNOWN, READY null, applied
  cursor null. Cron PASS is not Coverage COMPLETE.

This file is a now-inventory receipt at `2b82ec7d`, not a pass.
