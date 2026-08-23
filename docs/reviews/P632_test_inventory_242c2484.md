# Phase 6.3.2 P — test inventory at `242c2484`

**Kind:** read-only inventory. Does **not** delete tests. Does **not** invent
`tests_after`. Does **not** flip GO.  
**SHA counted:** `242c2484e9307f9163b13fc603ad90f67c6a0919` (`242c2484`)  
`docs: §10 remaining mixed at c9764ff4 after python IR codec`  
**Isolation worktree:** `/private/tmp/qp-p632-test-inventory-242c2484` on
`docs/p632-test-inventory-242c2484` off `origin/grok/phase63-ci-source-closure`.  
**Class SoT:** [`docs/phase63_test_audit.md`](../phase63_test_audit.md) (Lane 17 / 17b).  
Prior collect freezes (cite, do not rewrite): [`P632_test_inventory.md`](P632_test_inventory.md)
(`3ab87d0`, collected **1353**); [`P632_test_inventory_now.md`](P632_test_inventory_now.md)
(`07b4435`, collected **1379**); [`P632_test_inventory_40d1aa90.md`](P632_test_inventory_40d1aa90.md)
(`40d1aa90`, collected **1426**); [`P632_test_inventory_67fcbd7c.md`](P632_test_inventory_67fcbd7c.md)
(`67fcbd7c`, collected **1448**); [`P632_test_inventory_ed94d504.md`](P632_test_inventory_ed94d504.md)
(`ed94d504`, collected **1470**); [`P632_test_inventory_5103b26b.md`](P632_test_inventory_5103b26b.md)
(`5103b26b`, collected **1496**); [`P632_test_inventory_3b64bdfc.md`](P632_test_inventory_3b64bdfc.md)
(`3b64bdfc`, collected **1503**).  
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

| Surface | How counted (this isolation tree at `242c2484`) |
|---------|-------------------------------------------------|
| Python collected | `/Users/taku/GitHub/quant-platform/.venv/bin/python -m pytest --collect-only -q tests/` from this worktree. Python 3.11.15, pytest 9.1.1 (`pyproject.toml` `addopts = "-q"`). **PASS** (exit 0). Quiet `-q` prints 153 per-file counts summing to **1506**. Confirming with addopts cleared: `1506 tests collected in 0.48s`. |
| `tests/test_*.py` files | `git ls-files 'tests/test_*.py'` at HEAD (no `__pycache__`) |
| Worker first-party | `git ls-files` `platform/workers/**/*.{test.ts,test.mjs}` excluding `node_modules` |
| YAML | `specs/research_logics/**/*.{yaml,yml}` |

Runtime skip/pass was **not** re-run. Collect-only ≠ green pytest.

---

## Counts (actual)

| Metric | Brief §P (`tests_before`) | `3b64bdfc` inventory | This SHA (`242c2484`) |
|--------|--------------------------:|---------------------:|----------------------:|
| **tests_before (collected)** | ~**1282** | — | — |
| **tests_after (collected)** | *not invented* | *not invented* | *not invented* |
| **collected now (actual)** | — | **1503** | **1506** |
| `tests/test_*.py` files | — | **153** | **153** |
| Worker `*.test.ts` | — | **16** | **18** |
| Worker `*.test.mjs` | — | **4** | **4** |
| Worker first-party test files | — | **20** | **22** |
| Worker source `it(` / `test(` | — | **146** | **154** (not vitest collect) |
| `specs/research_logics` YAML | — | **0** | **0** (dir exists; only `README.md`) |

`1506 > 1503 > 1496 > 1470 > 1448 > 1426 > 1379 > 1282`. Later landings grew the suite vs
`3b64bdfc` (no new `tests/test_*.py` modules; existing modules grew:
`test_backfill_planner.py` 15→17, `test_immutable_artifact.py` 22→23;
Worker first-party **20 → 22**, new
`ingestion-premium/src/fetch_jq.test.ts` (5 `it(`) and
`retry_jitter.test.ts` (3 `it(`); Worker source `it(` / `test(`
**146 → 154**). That is **not** a consolidation win and **not** a GO.
YAML under `specs/research_logics` is **0**; compiled catalog identity is
not those files.

This commit adds **0** test modules and deletes **0** test modules.

---

## Remaining mechanism replacements (not closed by this count)

Do **not** delete these surfaces until the replacement owns the invariant.
Do **not** delete them in this lane. Count is not the close.

### 1. Generated IR TypedDict — **OPEN** (codec bodies generated)

**Replacement asked:** generate Python + TS types/codecs from
`specs/evaluation_ir/schema.json` and delete duplicate hand codec bodies.

**PARTIAL at this SHA (codec bodies closed; TypedDict not):**

- Schema remains codec field SoT (`specs/evaluation_ir/schema.json`).
- Worker `ALLOWED_FIELDS` is emitted from that schema into
  `evaluation_ir_allowed_fields.generated.ts`. Do not hand-edit.
- Worker encode/decode *body* is emitted from that schema into
  `evaluation_ir_codec.generated.ts` (239 lines; `4661fb14`).
  `evaluation_ir.ts` is a 39-line façade. Do not hand-edit the generated
  file. Decode still does **not** load a JSON Schema engine; unknown keys
  fail against generated `ALLOWED_FIELDS` and version must be
  `evaluation-ir/v1`.
- Python encode/decode *body* is emitted from that schema into
  `evaluation_ir_codec.generated.py` (184 lines; `c9764ff4`).
  `packages/product/research/evaluation_ir.py` is a 1224-line façade
  (schema load, TS/Python emitters, grade wiring, frozen dataclass
  `EvaluationIR`). Do not hand-edit the generated file.
- Golden is encoder-owned (`emit_evaluation_ir_golden` →
  `specs/evaluation_ir/golden.jsonl`).
- `scripts/verify_ci.sh` invokes Python schema/golden validation and
  `assert_evaluation_ir_codec_py_frozen()`, not presence-only.
- Grade predicate is already shared (`job_candidate_grade` /
  `jobCandidateGrade`).

**Still OPEN — generated TypedDict:**

- No `TypedDict` is emitted from `schema.json`. Python types remain the
  façade dataclass plus `Mapping[str, Any]` in the generated codec.
  [`docs/phase63_refactor_plan.md`](../phase63_refactor_plan.md) §10.3
  row 3: “TypedDict generation not done.” Dual hand codec *bodies* are
  no longer both present. This inventory did not close TypedDict.

Do not delete `tests/test_evaluation_ir.py` or
`research-mass-eval/src/evaluation_ir.test.ts` until generated types
own unknown-field fail-closed, version const `evaluation-ir/v1`, and
re-grade of smuggled `candidate: true`. Keep the Worker tests even
though the TS body is generated. Keep the Python tests even though the
Python body is generated.

### 2. Secrets Python grep — **OPEN** (sibling has not moved it)

**Replacement asked:** drop Python restatements / Worker-body greps of
policy already unit-tested in the Worker, without deleting real Py↔TS
*execution* parity.

**Still OPEN at this SHA:**

- `tests/test_ingestion_secrets_worker_contract.py` (4 collected) still
  source-greps `ingestion-secrets/src/index.ts` for import/whitelist /
  GET-stream / auth-order strings. Keep JSON contract identity
  (`premium` + addon import is the whitelist SoT) until a Worker unit
  test asserts that import. Drop body greps that
  `ingestion-secrets/src/index.test.ts` already covers (401 / no leak)
  only when that Worker test owns them. At this SHA the Worker file is
  still those two `it(` rows; it does **not** own the import/whitelist /
  GET-stream / auth-order strings. No landed sibling commit on
  `origin/grok/phase63-ci-source-closure` moved this grep.
- Catalog/Python cheap_pb constants and YAML leftover-vs-lifted stay;
  they are not Worker-body greps. Do not re-add Python greps of
  `daily_path.ts` / leftover occupancy.

`tests/test_identity_runtime_parity.py` is Invariant (real Py↔TS
*execution* parity), not echo. Do not delete it as a “grep.”

### 3. `verify_ci` not merge-gate — **OPEN**

**Replacement asked:** merge gate is GitHub context `ci-aggregate` after
authenticated receipts **and** `verify_ci`. Do not add
`.github/workflows`.

**Still OPEN at this SHA:**

- `scripts/verify_ci.sh` is mandatory *local* CI (7 workers; no
  `VERIFY_*` skips). That is **not** the merge gate.
- No `.github/workflows` in the tree. Six-lane `npm test` receipts
  alone skip Python/catalog and are **not** `verify_ci`.
- Local `verify_ci` PASS documented at `3b64bdfc`
  ([`P632_verify_ci_3b64bdfc.md`](P632_verify_ci_3b64bdfc.md): **1499
  passed / 4 skipped**) is a different SHA, not this collect, and
  **not** a posted GitHub context. This isolation did **not** re-run
  `scripts/verify_ci.sh`.
- Live producer Worker `quant-platform-ci-aggregate` remains a HUMAN
  first-deploy (print-only helper does not create it). Collect-only
  does not post `ci-aggregate`.

Do not treat this inventory, or a local `verify_ci: ok`, as merge-gate
green.

### 4. Catalog compact — optional **HOLD**

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

### 5. `combo_gates.test.ts` — **SoT** (not a remaining close)

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

- Collect-only **succeeded**. Collected **1506**. Brief `tests_before` ~**1282**.
  Prior inventory **1503** at `3b64bdfc`. `tests_after` is **not invented**.
  The +3 vs `3b64bdfc` (and Worker files **20 → 22**) is not a win.
- Collect-only ≠ green pytest. This snapshot does not re-run host PEM isolation
  or a full `tests/` pass. A later `verify_ci` runtime at `3b64bdfc` is a
  different SHA and is not this collect and is **not** merge-gate.
- Worker **22** is a file count, not `vitest --collect`. Source `it(` / `test(`
  count **154** is also not vitest collect.
- YAML under `specs/research_logics` is **0**; compiled catalog identity is
  not those files.
- Generated IR **Worker + Python codec bodies** are not a generated
  **TypedDict** (**OPEN**). Secrets Python grep of `index.ts` (**OPEN**;
  sibling has not landed a move). `verify_ci` is local authority, not
  merge-gate (**OPEN**). Catalog compact is optional **HOLD**, not
  missing-CLOSE.
- Last-known live facts from prior freezes (not re-fetched this lane):
  22 COMPLETE / 4 PARTIAL, Projection STALE, B0 UNKNOWN, READY null, applied
  cursor null. Cron PASS is not Coverage COMPLETE.

This file is a now-inventory receipt at `242c2484`, not a pass.
