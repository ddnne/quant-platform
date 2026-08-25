# Phase 6.3.2 P — test inventory at `5103b26b`

**Kind:** read-only inventory. Does **not** delete tests. Does **not** invent
`tests_after`. Does **not** flip GO.  
**SHA counted:** `5103b26bb40b2d73b49d079e03f8cf5b9c2a4c58` (`5103b26b`)  
`research: POST Worker children-then-manifest instead of raising`  
**Isolation worktree:** `/private/tmp/qp-p632-test-inventory-5103b26b` on
`docs/p632-test-inventory-5103b26b` off `origin/grok/phase63-ci-source-closure`.  
**Class SoT:** [`docs/phase63_test_audit.md`](../phase63_test_audit.md) (Lane 17 / 17b).  
Prior collect freezes (cite, do not rewrite): [`P632_test_inventory.md`](P632_test_inventory.md)
(`3ab87d0`, collected **1353**); [`P632_test_inventory_now.md`](P632_test_inventory_now.md)
(`07b4435`, collected **1379**); [`P632_test_inventory_40d1aa90.md`](P632_test_inventory_40d1aa90.md)
(`40d1aa90`, collected **1426**); [`P632_test_inventory_67fcbd7c.md`](P632_test_inventory_67fcbd7c.md)
(`67fcbd7c`, collected **1448**); [`P632_test_inventory_ed94d504.md`](P632_test_inventory_ed94d504.md)
(`ed94d504`, collected **1470**).  
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

| Surface | How counted (this isolation tree at `5103b26b`) |
|---------|-------------------------------------------------|
| Python collected | `/Users/taku/GitHub/quant-platform/.venv/bin/python -m pytest --collect-only -q tests/` from this worktree. Python 3.11.15, pytest 9.1.1 (`pyproject.toml` `addopts = "-q"`). **PASS** (exit 0). Quiet `-q` prints 153 per-file counts summing to **1496**. Confirming with addopts cleared: `1496 tests collected in 0.96s`. |
| `tests/test_*.py` files | `git ls-files 'tests/test_*.py'` at HEAD (no `__pycache__`) |
| Worker first-party | `git ls-files` `platform/workers/**/*.{test.ts,test.mjs}` excluding `node_modules` |
| YAML | `specs/research_logics/**/*.{yaml,yml}` |

Runtime skip/pass was **not** re-run. Collect-only ≠ green pytest.

---

## Counts (actual)

| Metric | Brief §P (`tests_before`) | `ed94d504` inventory | This SHA (`5103b26b`) |
|--------|--------------------------:|---------------------:|----------------------:|
| **tests_before (collected)** | ~**1282** | — | — |
| **tests_after (collected)** | *not invented* | *not invented* | *not invented* |
| **collected now (actual)** | — | **1470** | **1496** |
| `tests/test_*.py` files | — | **149** | **153** |
| Worker `*.test.ts` | — | **16** | **16** |
| Worker `*.test.mjs` | — | **4** | **4** |
| Worker first-party test files | — | **20** | **20** |
| Worker source `it(` / `test(` | — | **141** | **145** (not vitest collect) |
| `specs/research_logics` YAML | — | **0** | **0** (dir exists; only `README.md`) |

`1496 > 1470 > 1448 > 1426 > 1379 > 1282`. Later landings grew the suite vs
`ed94d504` (new modules: `test_ci_aggregate_first_deploy_script.py` 6,
`test_issue_receipts_parallel_cli.py` 5,
`test_issue_signed_receipts_for_segments.py` 8,
`test_pipeline_otc_index_text.py` 3; existing modules also grew; Worker
source `it(` / `test(` **141 → 145**). That is **not** a consolidation win
and **not** a GO. YAML under `specs/research_logics` is **0**; compiled
catalog identity is not those files.

This commit adds **0** test modules and deletes **0** test modules.

---

## Remaining mechanism replacements (not closed by this count)

Do **not** delete these surfaces until the replacement owns the invariant.
Do **not** delete them in this lane. Count is not the close.

### 1. Generated IR codec body — **OPEN** (Python body)

**Replacement asked:** generate Python + TS types/codecs from
`specs/evaluation_ir/schema.json` and delete duplicate hand codec bodies.

**PARTIAL at this SHA (not body-closed):**

- Schema remains codec field SoT (`specs/evaluation_ir/schema.json`).
- Worker `ALLOWED_FIELDS` is emitted from that schema into
  `evaluation_ir_allowed_fields.generated.ts`. Do not hand-edit.
- Worker encode/decode *body* is emitted from that schema into
  `evaluation_ir_codec.generated.ts` (239 lines; `4661fb14`).
  `evaluation_ir.ts` is a 39-line façade. Do not hand-edit the generated
  file. Decode still does **not** load a JSON Schema engine; unknown keys
  fail against generated `ALLOWED_FIELDS` and version must be
  `evaluation-ir/v1`.
- Golden is encoder-owned (`emit_evaluation_ir_golden` →
  `specs/evaluation_ir/golden.jsonl`).
- `scripts/verify_ci.sh` invokes Python schema/golden validation, not
  presence-only.

**Still OPEN — generated Python codec *body*:**

- Python: `packages/product/research/evaluation_ir.py` is still a
  hand-written encode/decode (1076 lines; schema-validating;
  `job_candidate_grade` is the grade predicate).
- Dual hand codec bodies are no longer both present on the Worker side.
  Brief asked generated Python+TS types and deletion of the duplicate
  bodies. Python body **not** done. This inventory did not close that.

Do not delete `tests/test_evaluation_ir.py` or
`research-mass-eval/src/evaluation_ir.test.ts` until a generated Python
codec body owns unknown-field fail-closed, version const
`evaluation-ir/v1`, and re-grade of smuggled `candidate: true`. Keep the
Worker tests even though the TS body is generated.

### 2. Catalog compact — optional **HOLD**

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

### 3. `combo_gates.test.ts` — **SoT** (not a remaining close)

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

- Collect-only **succeeded**. Collected **1496**. Brief `tests_before` ~**1282**.
  Prior inventory **1470** at `ed94d504`. `tests_after` is **not invented**.
  The +26 vs `ed94d504` is not a win.
- Collect-only ≠ green pytest. This snapshot does not re-run host PEM isolation
  or a full `tests/` pass. A later `verify_ci` runtime at `ed94d504` is a
  different SHA and is not this collect.
- Worker **20** is a file count, not `vitest --collect`. Source `it(` / `test(`
  count **145** is also not vitest collect.
- YAML under `specs/research_logics` is **0**; compiled catalog identity is
  not those files.
- Generated IR **Worker codec body** is not a generated **Python codec body**
  (**OPEN**). Catalog compact is optional **HOLD**, not missing-CLOSE.
- Last-known live facts from prior freezes (not re-fetched this lane):
  22 COMPLETE / 4 PARTIAL, Projection STALE, B0 UNKNOWN, READY null, applied
  cursor null. Cron PASS is not Coverage COMPLETE.

This file is a now-inventory receipt at `5103b26b`, not a pass.
