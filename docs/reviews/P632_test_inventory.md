# Phase 6.3.2 — test inventory after wave-1

**Kind:** read-only inventory. Does **not** delete tests. Does **not** flip GO.  
**Isolation HEAD:** `3ab87d0ef0f65199d25b9dadccee3b796a384bed` (`docs/p632-test-inventory` off `grok/phase63-ci-source-closure`)  
**Feature tip this counts:** `3ab87d0` `contracts: nested SourceCapability evidence maps are open`  
**Brief review SHA (not a freeze):** `b5c326a` (`origin/main` at Wave 0)  
**Class SoT:** [`docs/phase63_test_audit.md`](../phase63_test_audit.md) (Lane 17 / 17b). Classes reused; new modules classified the same way.  
Mass / READY / Phase 7 Controlled Pilot / reconstitution apply: **unchanged NO-GO / OFF / false**.

Do **not** treat test count as a win. The suite’s job is named invariants (PIT, receipts, false-COMPLETE, immutable READY, Mass fail-closed). Combinatorial paraphrases and integer catalog-size freezes are cost.

---

## Method

| Surface | How counted (this isolation tree) |
|---------|-----------------------------------|
| Python collected | `.venv/bin/python -m pytest tests --collect-only -q` — **PASS**, 0.54s (timeout 120s unused) |
| `tests/test_*.py` files | `tests/test_*.py` at HEAD (no `__pycache__`) |
| Worker first-party | `platform/workers/**/*.{test.ts,test.mjs}` excluding `node_modules` |
| Worker cases | source `it(` / `test(` count (vitest/node:test). Isolation tree has no Worker `node_modules`; not a vitest collect |

Runtime skip/pass is **not** re-run here. Brief’s 4 skip were a live pytest run, not collect-only.

---

## tests_before / tests_after

| Metric | Brief §4 (`b5c326a`) | This HEAD (`3ab87d0`) | Δ |
|--------|---------------------:|----------------------:|--:|
| **tests_before (collected)** | **1282** (1278 pass / 4 skip / 0 fail) | — | — |
| **tests_after (collected)** | — | **1353** | **+71** |
| `tests/` files (no `__pycache__`) | 151 at Lane-17b start `9cbb7fc` | **161** | — |
| `tests/*.py` | 139 / 136 (Lane 17b before/after) | **149** | — |
| `tests/test_*.py` | 128 (Lane 17 start) → 129 (17b after) | **142** | **+13** vs 17b |
| Worker first-party test **files** | 7 (Lane 17) → 13 (17b) | **19** | **+6** vs 17b |
| Worker first-party test **bytes** | 29 686 / 39 522 | **88 563** | — |
| Worker `it()`/`test()` (source) | not in brief | **126** | — |
| `specs/research_logics/*.yaml` | 2 254 at Lane 17 start | **0** (compiled n=**2254**) | — |

Wave-1 **added** modules (SourceCapability v3, tip-only AM/earnings, official master domain, Evaluation IR schema, CI `verify_ci`/`verify_all`, host-PEM isolation, reconstitution evidence, ResearchDataProfile, applied pins, gateway budget DO, six-worker + `ci-aggregate` tests). It did **not** continue Lane 17/17b combinatorial deletion. Count went **up**. That is not a GO and not a consolidation win.

---

## Python collected by class

Primary class per `tests/test_*.py` file, using Lane 17 meanings. Mixed files keep the audit’s primary class (e.g. `test_cf_propose_thesis.py` is Invariant even though its phrase table is combinatorial data).

| Class | Files | Collected |
|-------|------:|----------:|
| **Invariant** | 56 | 501 |
| **Representative** | 58 | 585 |
| **Split-monolith** | 11 | 175 |
| **Structural enforcement** | 10 | 36 |
| **Freeze file-count** | 5 | 29 |
| **Duplicate combinatorial** | 1 | 23 |
| **Dual-runtime policy echo** | 1 | 4 |
| **Total** | **142** | **1353** |

Support (not collected as modules): `conftest.py` Structural; `_coreseed.py` / `complete21_min_util.py` / `phase35_matrix_util.py` Split-monolith; `research_eval_util.py` / `cf_propose_stub.py` Representative; `cf_propose_phrase_cases.py` **Duplicate combinatorial** (data only: **19** rows = 9 occupancy + 9 polarity + 1 sparse; three reason classes).

Largest collected modules (not a delete list): `test_jquants_catalog.py` 34, `test_evaluation_ir.py` 33, `test_phase35_coverage_daily.py` 30, `test_features_compute.py` 28, `test_r2_feature_context.py` 25, `test_complete21_min_compute.py` 24, `test_secrets_proxy_pairs.py` 23, `test_pit_as_of.py` 22.

---

## Remaining combinatorial vs invariant

Lane 17 already merged husks (`test_ready_policy.py`, `test_cf_propose_worker_contract.py`, `test_catalog_family.py`, `test_r2_io_create_only.py`, `test_lane_e_ops_auto_projection.py`, `test_ops_projection_meta.py`) and dropped Worker leftover/cheap_pb Python greps. **Still combinatorial / freeze / echo after wave-1:**

| File | Class | Remaining extra | Keep |
|------|-------|-----------------|------|
| `tests/cf_propose_phrase_cases.py` | Duplicate combinatorial | 9 occupancy paraphrases of one reason class (audit kept 9 after 58→9) | 3 reason classes; polarity/sparse |
| `tests/test_secrets_proxy_pairs.py` (23) | Duplicate combinatorial | URL-only ×3 sources + mix-source paraphrases of one no-Frankenstein rule | env / json / split as **three code paths** |
| `tests/test_phase62_inventory_phase7.py` | Freeze file-count | `len==31` / `26` **and** `source_inventory` repeats the same integers | set-equality vs governed JSON; names `td_bulk`, minute bars |
| `tests/test_catalog_yaml_parity.py` | Freeze file-count | identity walk; integer catalog size is secondary | `yaml==py==constants` set-equality (Invariant) |
| `tests/test_catalog_compiler.py` | Freeze file-count | `n==2254` / yaml-count drift pins overlap identity | compiler-owned emit; no `exec`; flow-gate ≠ flow family |
| `tests/test_catalog_active_legacy.py` | Freeze file-count | `n==2254` again | unique22 park stays legacy (Invariant) |
| `tests/test_wave_script_freeze.py` | Freeze file-count | empty `ALLOWED_RUN_W` | residual live-flags (ADR recording) |
| `tests/test_ingestion_secrets_worker_contract.py` | Dual-runtime policy echo | TS source-grep of import/whitelist strings | JSON contract identity until Worker test asserts the import |
| `quant-ops-mcp/test/mcp.test.mjs` | Invariant (mild freeze) | `names.length == 17` | banned-tool list (`query_dataset`, `sql`, …) |

Wave-1 **Invariant** additions (keep): `test_am_bars_tip_only.py`, `test_earnings_calendar_tip_only.py`, `test_equities_master_official_domain.py`, `test_source_capability_contract.py`, `test_research_data_profile.py`, `test_evaluation_ir.py`, `test_ops_applied_pins.py`, `test_phase7_pilot_construct.py`, `test_pilot_loop.py`, `test_research_capabilities.py`, `test_paper_runtime_execution_not_armed.py`, `test_reconstitution_pending.py`. Structural: `test_receipt_host_pem_isolated.py`, `test_verify_ci_script.py`, `test_verify_all_script.py`. Representative: `test_reconstitution_evidence.py` (apply stays false).

`tests/test_smoke.py` remains **absent**. Live G0 is `tests/README.md`.

---

## Worker first-party (19 files, 126 `it`/`test`)

| File | Class | `it`/`test` |
|------|-------|------------:|
| `research-mass-eval/src/combo_gates.test.ts` | Representative **SoT for Worker gate policy**. Do not delete. | 20 |
| `research-mass-eval/src/http.test.ts` | Representative (presentation) | 16 |
| `research-ai-gateway/src/schema.test.ts` | Invariant (typed decode; no raw fallback) | 14 |
| `quant-ops-mcp/test/domain-d1.test.mjs` | Representative | 12 |
| `research-ai-gateway/src/budget_do.test.ts` | Invariant (hard reserve before provider) | 11 |
| `ci-aggregate/src/index.test.ts` | Invariant (six-lane receipts → required status) | 9 |
| `research-mass-eval/src/evaluation_ir.test.ts` | Invariant (shared golden; candidate from `job_candidate_grade`) | 8 |
| `research-mass-eval/src/capabilities.test.ts` | Invariant deny-by-default | 5 |
| `research-ai-gateway/src/index.test.ts` | Invariant | 4 |
| `research-mass-eval/src/mdh_collapse.test.ts` | Invariant | 4 |
| `research-mass-eval/src/candidate.test.ts` | Invariant | 3 |
| `research-mass-eval/src/event_entry.test.ts` | Invariant | 3 |
| `quant-ops-mcp/test/mcp.test.mjs` | Invariant (read-only surface) | 3 |
| `quant-ops-mcp/test/quota.test.mjs` | Invariant | 3 |
| `ingestion-premium/src/index.test.ts` | Representative (now exists; Lane 17 had none) | 3 |
| `quant-ops-mcp/test/auth.test.mjs` | Invariant | 2 |
| `ingestion-jsda/src/index.test.ts` | Representative | 2 |
| `ingestion-secrets/src/index.test.ts` | Invariant (401 / no secret leak) | 2 |
| `research-mass-eval/src/path_broken.test.ts` | Invariant | 2 |

Python↔TS **execution** parity remains `tests/test_identity_runtime_parity.py` (Invariant, not echo).

---

## Retained core (never delete here)

From Lane 17 constraint + G0 pack in `tests/README.md` + wave-1 fail-closed landings:

- PIT / `as_of` / `available_at <= as_of` / pipeline fetch-completion timestamps
- Receipts: Ed25519 eligibility, issue/empty-raw ban, signature forgery, host PEM isolation
- False-COMPLETE / empty inventory / PARTIAL must not publish READY / sticky COMPLETE
- Immutable READY snapshot publication; coherence without receipts
- Mass fail-closed; gateway fail-closed; Phase 7 construct / pilot loop capability-off
- `test_baseline_catalog.py` (rejected S1–S5; Mass/READY false)
- `job_candidate_grade` / research capabilities deny-by-default
- Applied pin: null cursor never CURRENT
- Official-domain / tip-only: AM not 32 months COMPLETE; earnings calendar not 200 months COMPLETE; master required start 2008-05-07; remaining genuine gaps stay PARTIAL
- Worker `combo_gates.test.ts` leftover occupancy / cheap_pb SoT
- Cost-model split files (live math, not husks)
- Occupancy band asserts; unique22 park not silently unparked
- `RECONSTITUTION_APPLY` stays false

---

## Suggested next deletions (do **not** delete in this commit)

Prefer documenting over mass-delete when the extra check might be the only copy of a field.

1. **Collapse occupancy phrase paraphrases 9→3** in `cf_propose_phrase_cases.py` (one row per occupancy reason class). Keep polarity + sparse.
2. **Replace `len==31`/`26` with set-equality** in `test_phase62_inventory_phase7.py`; drop the duplicate integer asserts in `test_source_inventory_metadata_only_counts`. Keep `td_bulk` / minute-bar **names**.
3. **Trim `test_secrets_proxy_pairs.py` mix-source paraphrases** to one representative per unordered pair of sources. Keep the three completeness paths (env / json / split).
4. **Drop Python Worker-body greps** in `test_ingestion_secrets_worker_contract.py` that `ingestion-secrets/src/index.test.ts` now covers (401 / no leak). Keep JSON contract identity (`premium` + addon import is the whitelist SoT) until the Worker test asserts that import.
5. **Dedup integer `n==2254` pins** across `test_catalog_compiler.py` / `test_catalog_active_legacy.py` / `test_catalog_yaml_parity.py`. Keep **one** identity set-equality. Do not drop without a remaining set check vs compiled map.
6. **Do not** merge COMPLETE-21 / phase35 / cost_models splits. **Do not** delete G0 / PIT / receipt / READY / Mass / `baseline_catalog` / `combo_gates`.

No modules deleted this lane. **Added modules: 0.**

---

## Honesty

- Collected **1353** > brief **1282**. Wave-1 grew the suite. Consolidation leftover is still the freeze/echo rows above.
- Collect-only ≠ green pytest. Host PEM isolation and fresh-venv pytest were OPEN at 6.3.1 remaining-audit; this snapshot does not re-run them.
- Worker **126** is a source `it`/`test` count, not `vitest --collect`.
- 22 COMPLETE / 4 PARTIAL, Projection STALE, B0 UNKNOWN, READY null, applied cursor null — **unchanged live facts**. Cron PASS is not Coverage COMPLETE.

This file is a Wave-1 inventory receipt, not a pass.
