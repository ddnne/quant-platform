# Phase 6.3.1 review findings

> **Live vs freeze.** Feature HEAD `8299ad84` vs `origin/main` `b5c326a`. PR #1 is **BLOCKED** until `ci-aggregate` posts. Live MCP: Projection **STALE**, READY **null**. Historical A01 / A07 / A11 files are remaining-audit **freezes** at `03cd1b1`, not live SoT. `f224e7e` / `40d1aa90` / `67fcbd7c` / `ed94d504` / `5103b26b` / wave-7 (`3b64bdfc`) / wave-8 / `0a8ced34` / `242c2484` / wave-9 / `2b82ec7d` / wave-10 / `02fb6cbd` / wave-11 / `cf7da56c` / wave-12 / `b5f6f2de` / wave-13 review files stay earlier freezes, not live HEAD.

Starting remote HEAD at first wave: `069913c`. Remaining-audit freeze: **`03cd1b1`**. Current `origin/main` is **`b5c326a`**.
Review SHA named in the original brief (`96264f0`) is **not** the freeze.

Per-lane finding files. Status vocabulary: OPEN / FIXED / DEFERRED / HOLD.

Wave-1 implementation P0s (do not re-open): eval_loaders tmp sqlite (`4cc0a47`);
receipt tmp keys (`3e46c97`); `http trust_env=False` (`331f3c4`); npm ci lockfiles
(`992ff41`); JSDA/JQ authority before write (`5f95b8f`); pilot `require_valid` /
no duck bound (`24d7902`); gateway no raw fallback (`ccf486a`); children-then-manifest
(`4d0180f`); catalog `n` compiled (`e8bdf17`); `verify_all.sh` (`e8e65ee`);
IR `golden.jsonl` (`7f2dc12`).

- [`P631_wave1_findings.md`](P631_wave1_findings.md) — implementation-time P0s (fixed)
- [`A01_python_clean_tests.md`](A01_python_clean_tests.md) — freeze, not live SoT: JSDA COMPLETE without injected keys; host PEM isolation
- [`A07_catalog.md`](A07_catalog.md) — freeze, not live SoT: occupancy `yaml_remains_sot`; fabricated `catalog_path`
- [`A10_coverage_gaps.md`](A10_coverage_gaps.md) — 26 governed / 4 PARTIAL; do not invent COMPLETE 23
- [`A11_waste.md`](A11_waste.md) — freeze, not live SoT: combo +N HOLD identity; `yaml_remains_sot`; unused `cells_candidate_counts`
- [`A13_docs_claims.md`](A13_docs_claims.md) — COMPLETE-under-STALE; unique22 park YAML wording; AI Gateway deployed ≠ Phase 7
- [`A14_git_ci.md`](A14_git_ci.md) — no GHA by policy; `verify_all.sh` exists; `workers_dev`; check-runs 0
- [`P631_brief_leaks.md`](P631_brief_leaks.md) — 6.3.1 A–X vs tree at `e927b97`; 6.3.1/6.4 NOT COMPLETE; Phase 7 NO-GO
- [`P631_refactor_now.md`](P631_refactor_now.md) — mixed-authority snapshot after 6.3 extracts; leftover occupancy HOLD
- [`D_dead_functions.md`](D_dead_functions.md) — unused-helper deletions vs HOLD false-positives
- [`original_plan_gap.md`](original_plan_gap.md) — 08-20/21 recording reset held; 08-22 funds held; AND-as-product invalid and already stopped
- unique22 park is leftover occupancy (`UNIQUE22_PARK_REASONS` / `daily_path.ts`), not YAML; COMPLETE 22 is last-known STALE projection, not FRESH

## Phase 6.3.2 (feature `grok/phase63-ci-source-closure`)

**This HEAD:** `8299ad84` (later than wave-13 / `b1605c36`). **`origin/main`:** `b5c326a` (not merged). PR #1 **BLOCKED** until `ci-aggregate` posts. Live MCP: Projection **STALE**, READY **null**. Historical 6.3.1 files above (A01 / A07 / A11 included) are not live OPEN/CLOSED or live SoT for 6.3.2. `f224e7e` / `40d1aa90` / `67fcbd7c` / `ed94d504` / `5103b26b` / wave-7 (`3b64bdfc`) / wave-8 / `242c2484` / wave-9 / `2b82ec7d` / wave-10 / `02fb6cbd` / wave-11 / `cf7da56c` / wave-12 / `b5f6f2de` review files stay earlier freezes, not live HEAD. See:

- [`P632_wave0_live.md`](P632_wave0_live.md) — fetch remeasure
- [`P632_brief_leaks.md`](P632_brief_leaks.md) — A–S vs feature branch
- [`P632_ind_A_pit_complete.md`](P632_ind_A_pit_complete.md) / [`P632_ind_A_revisit.md`](P632_ind_A_revisit.md) / [`P632_ind_A_revisit_f224e7e.md`](P632_ind_A_revisit_f224e7e.md) / [`P632_ind_A_revisit_40d1aa90.md`](P632_ind_A_revisit_40d1aa90.md) / [`P632_ind_A_revisit_67fcbd7c.md`](P632_ind_A_revisit_67fcbd7c.md) / [`P632_ind_B_ci_authority.md`](P632_ind_B_ci_authority.md) / [`P632_ind_C_catalog_pilot.md`](P632_ind_C_catalog_pilot.md)
- [`P632_projection_stale.md`](P632_projection_stale.md) — `refresh_success=false` root cause
- [`P632_projection_refresh_false.md`](P632_projection_refresh_false.md) — live write of `refresh_success=false` (`refresh_attempt=true`, `not_fresh=true`)
- [`P632_test_inventory.md`](P632_test_inventory.md)
- [`P632_wave7_status.md`](P632_wave7_status.md) — A–S freeze vs `5103b26b`
- [`P632_wave8_status.md`](P632_wave8_status.md) — A–S freeze vs `3b64bdfc`
- [`P632_wave9_status.md`](P632_wave9_status.md) — A–S freeze vs `242c2484`
- [`P632_wave10_status.md`](P632_wave10_status.md) — A–S freeze vs `2b82ec7d`
- [`P632_wave11_status.md`](P632_wave11_status.md) — A–S freeze vs `02fb6cbd`
- [`P632_wave12_status.md`](P632_wave12_status.md) — A–S freeze vs `cf7da56c`
- [`P632_wave13_status.md`](P632_wave13_status.md) — A–S freeze vs `b5f6f2de`
- [`P632_ind_A_revisit_b1605c36.md`](P632_ind_A_revisit_b1605c36.md) / [`P632_verify_ci_b1605c36.md`](P632_verify_ci_b1605c36.md) — Independent A and `verify_ci` at `b1605c36` (later code HEAD `8299ad84`)
- [`P632_ind_A_revisit_b5f6f2de.md`](P632_ind_A_revisit_b5f6f2de.md) / [`P632_ind_B_revisit_b5f6f2de.md`](P632_ind_B_revisit_b5f6f2de.md) / [`P632_ind_C_revisit_b5f6f2de.md`](P632_ind_C_revisit_b5f6f2de.md) / [`P632_test_inventory_b5f6f2de.md`](P632_test_inventory_b5f6f2de.md) / [`P632_verify_ci_b5f6f2de.md`](P632_verify_ci_b5f6f2de.md) — prior Independent A/B/C / inventory / `verify_ci` freezes

Later on this branch (after the A01/A07 freeze): occupancy `yaml_remains_sot` removed; unused `cells_candidate_counts` deleted; compiled `catalog_path` is `migration.jsonl`; JSDA/JQ tests inject tmp Ed25519. Host PEM isolation and fresh-venv pytest remain OPEN.

Phase 7 Controlled Pilot and Mass Research remain **NO-GO** until §19 gates.
Do not invent Coverage COMPLETE, Projection FRESH, B0 PASS, or READY.
