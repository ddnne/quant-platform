# Phase 6.3.2 P — test inventory now (`07b4435`)

**Kind:** read-only inventory. Does **not** delete tests. Does **not** invent
`tests_after`. Does **not** flip GO.  
**SHA:** `07b44355dc745b1a9b7f7c3c4eccbe123e7a171b` (`07b4435`)  
`docs: merge gate is verify_ci plus authenticated ci-aggregate`  
**Branch base:** `origin/grok/phase63-ci-source-closure` at that SHA.  
**Class SoT:** [`docs/phase63_test_audit.md`](../phase63_test_audit.md) (Lane 17 / 17b).  
Mass / READY / Phase 7 Controlled Pilot / reconstitution apply: **unchanged
NO-GO / OFF / false**.

Brief §P asked `tests_before` ~ **1282** collected. This file re-ran
`pytest --collect-only`. It does **not** invent `tests_after`.

---

## Classification reminder

Do **not** treat a count drop as a win. Do **not** treat a count rise as a
closure. The suite’s job is named invariants (PIT, `available_at`, receipts,
false-COMPLETE, immutable READY, Mass/gateway fail-closed,
`test_baseline_catalog.py`). Combinatorial paraphrases, integer catalog-size
freezes, and Python restatements of Worker policy already unit-tested are
cost. Mechanism replacements (compiler digest, Worker `combo_gates` tests,
generated IR codec) are the allowed reduction path. Deleting the only copy of
an invariant is not.

---

## Method

| Surface | How counted (this isolation tree at `07b4435`) |
|---------|-----------------------------------------------|
| Python collected | `/Users/taku/GitHub/quant-platform/.venv/bin/python -m pytest --collect-only -q tests/` from this worktree. pytest 9.1.1. **PASS**, `1379 tests collected in 0.48s`. |
| `tests/test_*.py` files | `tests/test_*.py` at HEAD (no `__pycache__`) |
| Worker first-party | `platform/workers/**/*.{test.ts,test.mjs}` excluding `node_modules` |
| YAML | `specs/research_logics/**/*.{yaml,yml}` |

Runtime skip/pass was **not** re-run. Collect-only ≠ green pytest.

---

## Counts (actual)

| Metric | Brief §P (`tests_before`) | This SHA (`07b4435`) |
|--------|--------------------------:|---------------------:|
| **tests_before (collected)** | ~**1282** | — |
| **tests_after (collected)** | *not invented* | *not invented* |
| **collected now (actual)** | — | **1379** |
| `tests/test_*.py` files | — | **143** |
| Worker `*.test.ts` | — | **15** |
| Worker `*.test.mjs` | — | **4** |
| Worker first-party test files | — | **19** |
| `specs/research_logics` YAML | — | **0** (dir exists; only `README.md`) |

`1379 > 1282`. Wave-1 and later landings grew the suite. That is **not** a
consolidation win and **not** a GO. A later drop is also **not** a win unless
the dropped rows were mechanism-replaced and the never-delete list below still
has a remaining owner.

---

## Remaining reduction candidates (mechanism replacements only)

Do **not** delete these surfaces until the replacement owns the invariant.
Do **not** delete them in this lane.

### 1. Compiler digest vs freeze walks

**Replacement:** `compile_catalog()` digest + set-equality (`logic_id` set vs
compiled map / constants). Integer `n==2254` is not an extra invariant once
digest lock + set-equality exist.

**Still freeze walks / integer pins at this SHA:**

- `tests/test_catalog_compiler.py` — `pack["n"] == CATALOG_YAML_COUNT_AT_STOP`;
  freeze dict `n_digest == freeze == n_logic_ids == 2254`; yaml-count drift
  pins while stopped.
- `tests/test_catalog_active_legacy.py` — `pack["n"] == n == 2254` and
  `len(compiled_migration_ids()) == 2254` again.
- `tests/test_catalog_yaml_parity.py` — identity walk of
  `specs/research_logics/*.yaml` (glob is empty; YAML count is 0). Set-equality
  `yaml==py==constants` is the Invariant half; keep **one** identity check.
- `tests/test_eval_tracks.py` — `CATALOG_YAML_COUNT_AT_STOP == 2254`.

Keep compiler-owned emit, no `exec`, flow-gate ≠ flow family, unique22 park
legacy. Dedup the integer `n` pins **after** digest + set-equality is the
single remaining identity owner.

### 2. `combo_gates.test.ts` vs Python greps

**Replacement:** `platform/workers/research-mass-eval/src/combo_gates.test.ts`
is SoT for Worker gate policy (unknown gate fail-closed, cheap_pb vs
`pb_rising`, leftover `pre_mom` occupancy). Python must not re-grep Worker
bodies for the same policy.

**Still dual-runtime echo / grep candidates at this SHA:**

- `tests/test_ingestion_secrets_worker_contract.py` — `index.ts` source-grep of
  import/whitelist strings. Keep JSON contract identity (`premium` + addon
  import) until the Worker test asserts that import. Drop body greps that
  `ingestion-secrets/src/index.test.ts` already covers (401 / no leak).
- Catalog/Python cheap_pb **constants and YAML leftover-vs-lifted** stay; they
  are not Worker-body greps. Do not re-add Python greps of `daily_path.ts` /
  leftover occupancy. Occupancy **HOLD** remains in `daily_path.ts`.

`tests/test_identity_runtime_parity.py` is Invariant (real Py↔TS *execution*
parity), not echo. Do not delete it as a “grep.”

### 3. Generated IR codec vs dual hand codecs

**Replacement:** generate Python + TS types from
`specs/evaluation_ir/schema.json` and delete duplicate hand codecs.

**Still dual hand codecs at this SHA:**

- Python: `packages/product/research/evaluation_ir.py` (encode/decode validates
  schema; `job_candidate_grade` is the grade predicate).
- Worker: `platform/workers/research-mass-eval/src/evaluation_ir.ts`
  (hand-written TS codec; `jobCandidateGrade` shared).
- Golden is encoder-owned (`emit_evaluation_ir_golden` →
  `specs/evaluation_ir/golden.jsonl`).
- `scripts/verify_ci.sh` checks **file presence** of golden / schema / both
  codec files, not schema/codegen drift.

Do not delete `tests/test_evaluation_ir.py` or
`research-mass-eval/src/evaluation_ir.test.ts` until a generated codec owns
unknown-field fail-closed, version const `evaluation-ir/v1`, and re-grade of
smuggled `candidate: true`.

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

No modules deleted this lane. **Added modules: 0.**

---

## Honesty

- Collect-only **succeeded**. Collected **1379**. Brief `tests_before` ~**1282**.
  `tests_after` is **not invented**.
- Collect-only ≠ green pytest. This snapshot does not re-run host PEM isolation
  or a full `tests/` pass.
- Worker **19** is a file count, not `vitest --collect`.
- YAML under `specs/research_logics` is **0**; compiled catalog identity is
  not those files.
- 22 COMPLETE / 4 PARTIAL, Projection STALE, B0 UNKNOWN, READY null, applied
  cursor null — **unchanged live facts**. Cron PASS is not Coverage COMPLETE.

This file is a now-inventory receipt at `07b4435`, not a pass.
