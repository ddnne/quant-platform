# Phase 6.3.2 P — test inventory at `40d1aa90`

**Kind:** read-only inventory. Does **not** delete tests. Does **not** invent
`tests_after`. Does **not** flip GO.  
**SHA counted:** `40d1aa9009ca1e7a6bd9fdc2df4d4da4cf92eab4` (`40d1aa90`)  
`coverage: OTC refresh required set from official index not inventory`  
**Isolation worktree:** `/private/tmp/qp-p632-test-inventory-40d1aa90` on
`docs/p632-test-inventory-40d1aa90` off `origin/grok/phase63-ci-source-closure`.  
**Class SoT:** [`docs/phase63_test_audit.md`](../phase63_test_audit.md) (Lane 17 / 17b).  
Prior collect freezes (cite, do not rewrite): [`P632_test_inventory.md`](P632_test_inventory.md)
(`3ab87d0`, collected **1353**); [`P632_test_inventory_now.md`](P632_test_inventory_now.md)
(`07b4435`, collected **1379**).  
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

| Surface | How counted (this isolation tree at `40d1aa90`) |
|---------|-------------------------------------------------|
| Python collected | `/Users/taku/GitHub/quant-platform/.venv/bin/python -m pytest --collect-only -q tests/` from this worktree. pytest 9.1.1 (`pyproject.toml` `addopts = "-q"`). **PASS**, `1426 tests collected in 0.42s`. |
| `tests/test_*.py` files | `tests/test_*.py` at HEAD (no `__pycache__`) |
| Worker first-party | `platform/workers/**/*.{test.ts,test.mjs}` excluding `node_modules` |
| YAML | `specs/research_logics/**/*.{yaml,yml}` |

Runtime skip/pass was **not** re-run. Collect-only ≠ green pytest.

---

## Counts (actual)

| Metric | Brief §P (`tests_before`) | `07b4435` now-inventory | This SHA (`40d1aa90`) |
|--------|--------------------------:|------------------------:|----------------------:|
| **tests_before (collected)** | ~**1282** | — | — |
| **tests_after (collected)** | *not invented* | *not invented* | *not invented* |
| **collected now (actual)** | — | **1379** | **1426** |
| `tests/test_*.py` files | — | **143** | **146** |
| Worker `*.test.ts` | — | **15** | **16** |
| Worker `*.test.mjs` | — | **4** | **4** |
| Worker first-party test files | — | **19** | **20** |
| `specs/research_logics` YAML | — | **0** | **0** (dir exists; only `README.md`) |

`1426 > 1379 > 1282`. Later landings grew the suite (new modules vs `07b4435`:
`test_collection_coverage_contract.py`, `test_identity_official_clamp.py`,
`test_source_capability.py`, Worker `ingestion-premium/src/identity.test.ts`).
That is **not** a consolidation win and **not** a GO. YAML under
`specs/research_logics` is **0**; compiled catalog identity is not those files.

---

## Remaining mechanism replacements (not closed by this count)

Do **not** delete these surfaces until the replacement owns the invariant.
Do **not** delete them in this lane. Count is not the close.

### 1. Generated IR codec body — **OPEN**

**Replacement asked:** generate Python + TS types/codecs from
`specs/evaluation_ir/schema.json` and delete duplicate hand codec bodies.

**PARTIAL at this SHA (not body-closed):**

- Schema remains codec field SoT (`specs/evaluation_ir/schema.json`).
- Worker `ALLOWED_FIELDS` is emitted from that schema into
  `evaluation_ir_allowed_fields.generated.ts` (`d8821197`). Do not hand-edit.
- Golden is encoder-owned (`emit_evaluation_ir_golden` →
  `specs/evaluation_ir/golden.jsonl`).
- `scripts/verify_ci.sh` invokes Python schema/golden validation, not
  presence-only.

**Still OPEN — generated codec *body*:**

- Python: `packages/product/research/evaluation_ir.py` is still a hand-written
  encode/decode (schema-validating; `job_candidate_grade` is the grade
  predicate).
- Worker: `platform/workers/research-mass-eval/src/evaluation_ir.ts` is still
  a hand-written TS codec body (255 lines). Decode does **not** load a JSON
  Schema engine; unknown keys fail against the generated `ALLOWED_FIELDS` set
  and version must be `evaluation-ir/v1`.
- Dual hand codec bodies remain. Brief asked generated Python+TS types and
  deletion of the duplicate bodies. **Not** done.

Do not delete `tests/test_evaluation_ir.py` or
`research-mass-eval/src/evaluation_ir.test.ts` until a generated codec body
owns unknown-field fail-closed, version const `evaluation-ir/v1`, and re-grade
of smuggled `candidate: true`.

### 2. Catalog compact — optional **HOLD**

Compact `family + template + parameter matrix` is **not** implemented.
`specs/research_catalog/migration.jsonl` is still runtime load SoT. Expanded
compiled n=**2254** is a freeze identity, not a compact-catalog substitute.

This compact is **optional HOLD**. Do not treat it as a required reduction
path for this inventory. Do not report 2254/2092 as a product win. Combo +N
**HOLD**. unique22 leftover occupancy **HOLD**. YAML overlay stays fail-closed
without `QP_ALLOW_YAML_OVERLAY=1`. YAML n=**0**.

Keep compiler-owned emit, digest lock, set-equality, unique22 park legacy.
Do not re-open YAML `+N` or AND-as-product to “compact.”

### 3. `combo_gates.test.ts` — **SoT**

`platform/workers/research-mass-eval/src/combo_gates.test.ts` is SoT for
Worker gate policy (unknown gate fail-closed, cheap_pb vs `pb_rising`,
leftover `pre_mom` occupancy). Source `it(` / `test(` count at this SHA:
**20**. Do **not** delete.

Python must not re-grep Worker bodies for the same policy. Occupancy **HOLD**
remains in `daily_path.ts`. Catalog/Python cheap_pb constants and YAML
leftover-vs-lifted stay; they are not Worker-body greps.

`tests/test_identity_runtime_parity.py` is Invariant (real Py↔TS *execution*
parity), not echo. Do not delete it as a “grep.”

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

- Collect-only **succeeded**. Collected **1426**. Brief `tests_before` ~**1282**.
  Prior now-inventory **1379** at `07b4435`. `tests_after` is **not invented**.
- Collect-only ≠ green pytest. This snapshot does not re-run host PEM isolation
  or a full `tests/` pass. A later `verify_ci` runtime at `f113cc05` (1412
  passed / 4 skipped) is a different SHA and is not this collect.
- Worker **20** is a file count, not `vitest --collect`.
- YAML under `specs/research_logics` is **0**; compiled catalog identity is
  not those files.
- Generated IR **field set** is not a generated **codec body**. Catalog compact
  is optional HOLD, not missing-CLOSE.
- Last-known live facts from prior freezes (not re-fetched this lane):
  22 COMPLETE / 4 PARTIAL, Projection STALE, B0 UNKNOWN, READY null, applied
  cursor null. Cron PASS is not Coverage COMPLETE.

This file is a now-inventory receipt at `40d1aa90`, not a pass.
