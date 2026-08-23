# Phase 6.3.1 review findings

Starting remote HEAD at first wave: `069913c`. Remaining-audit freeze: **`03cd1b1`** (`origin/main`).
Review SHA named in the original brief (`96264f0`) is **not** the freeze.

Per-lane finding files. Status vocabulary: OPEN / FIXED / DEFERRED / HOLD.

Wave-1 implementation P0s (do not re-open): eval_loaders tmp sqlite (`4cc0a47`);
receipt tmp keys (`3e46c97`); `http trust_env=False` (`331f3c4`); npm ci lockfiles
(`992ff41`); JSDA/JQ authority before write (`5f95b8f`); pilot `require_valid` /
no duck bound (`24d7902`); gateway no raw fallback (`ccf486a`); children-then-manifest
(`4d0180f`); catalog `n` compiled (`e8bdf17`); `verify_all.sh` (`e8e65ee`);
IR `golden.jsonl` (`7f2dc12`).

- [`P631_wave1_findings.md`](P631_wave1_findings.md) — implementation-time P0s (fixed)
- [`A01_python_clean_tests.md`](A01_python_clean_tests.md) — remaining at audit freeze: JSDA COMPLETE without injected keys; host PEM isolation
- [`A07_catalog.md`](A07_catalog.md) — remaining at audit freeze: occupancy `yaml_remains_sot`; fabricated `catalog_path`
- [`A10_coverage_gaps.md`](A10_coverage_gaps.md) — 26 governed / 4 PARTIAL; do not invent COMPLETE 23
- [`A11_waste.md`](A11_waste.md) — combo +N HOLD identity; `yaml_remains_sot`; unused `cells_candidate_counts`
- [`A13_docs_claims.md`](A13_docs_claims.md) — COMPLETE-under-STALE; unique22 park YAML wording; AI Gateway deployed ≠ Phase 7
- [`A14_git_ci.md`](A14_git_ci.md) — no GHA by policy; `verify_all.sh` exists; `workers_dev`; check-runs 0
- [`P631_brief_leaks.md`](P631_brief_leaks.md) — 6.3.1 A–X vs tree at `e927b97`; 6.3.1/6.4 NOT COMPLETE; Phase 7 NO-GO
- [`P631_refactor_now.md`](P631_refactor_now.md) — mixed-authority snapshot after 6.3 extracts; leftover occupancy HOLD
- [`D_dead_functions.md`](D_dead_functions.md) — unused-helper deletions vs HOLD false-positives
- [`original_plan_gap.md`](original_plan_gap.md) — 08-20/21 recording reset held; 08-22 funds held; AND-as-product invalid and already stopped
- unique22 park is leftover occupancy (`UNIQUE22_PARK_REASONS` / `daily_path.ts`), not YAML; COMPLETE 22 is last-known STALE projection, not FRESH

## Phase 6.3.2 (feature `grok/phase63-ci-source-closure`)

Historical 6.3.1 files above are not live OPEN/CLOSED for 6.3.2. See:

- [`P632_wave0_live.md`](P632_wave0_live.md) — fetch remeasure
- [`P632_brief_leaks.md`](P632_brief_leaks.md) — A–S vs feature branch
- [`P632_ind_A_pit_complete.md`](P632_ind_A_pit_complete.md) / [`P632_ind_A_revisit.md`](P632_ind_A_revisit.md) / [`P632_ind_B_ci_authority.md`](P632_ind_B_ci_authority.md) / [`P632_ind_C_catalog_pilot.md`](P632_ind_C_catalog_pilot.md)
- [`P632_projection_stale.md`](P632_projection_stale.md) — `refresh_success=false` root cause
- [`P632_test_inventory.md`](P632_test_inventory.md)

Later on this branch (after the A01/A07 freeze): occupancy `yaml_remains_sot` removed; unused `cells_candidate_counts` deleted; compiled `catalog_path` is `migration.jsonl`; JSDA/JQ tests inject tmp Ed25519. Host PEM isolation and fresh-venv pytest remain OPEN.

Phase 7 Controlled Pilot and Mass Research remain **NO-GO** until §19 gates.
Do not invent Coverage COMPLETE, Projection FRESH, B0 PASS, or READY.
