# Phase 6.3 Lane 17 — test audit

**Tip audited:** `1efb405` (`origin/main`)  
**Worktree:** `p63/lane-17-test-audit`  
**Mass / READY / Phase 7:** unchanged (NO-GO / not declared / OFF). This lane classifies tests; it does not flip GO.  
**HEAD (`origin/main`):** leftover Worker grep drop from `test_unique_logic_event_filters.py` landed in `ed0a2cb`. Live G0 is `tests/README.md` (no `unittest tests.test_smoke`).

Do **not** treat test count as a win. The suite’s job is named invariants (PIT, receipts, false-COMPLETE, immutable READY, Mass fail-closed). Combinatorial paraphrases and YAML-per-file freezes are cost.

## Classes

| Class | Meaning |
|-------|---------|
| **Invariant** | Architectural / policy must-never-break (PIT, `available_at`, receipts, false-COMPLETE, immutable READY, Mass/gateway fail-closed). |
| **Structural enforcement** | AST / import / path / source-scan / file-existence guards. |
| **Representative** | One golden example (or a small set) of a behavior class. |
| **Duplicate combinatorial** | Many similar rows of the *same* invariant; extra paraphrases add no new class. |
| **Freeze file-count** | Pins N files / YAML stems / integer catalog sizes without an extra invariant. |
| **Dual-runtime policy echo** | Python restating Worker policy already unit-tested (or Worker source-grep of a comment). Real Py↔TS *execution* parity is **Invariant**, not echo. |
| **Split-monolith** | Already-split large matrix (keep the split; do not re-merge). |

Primary class per file. Mixed files note the secondary class in **Notes**.

Helpers under `tests/` that pytest does not collect as modules are marked **support**.

---

## Inventory (Lane 17 start, `1efb405`)

| Surface | Count | Bytes |
|---------|------:|------:|
| `tests/` files (no `__pycache__`) | 147 | 1 037 955 |
| `tests/*.py` | 135 | 1 030 653 |
| `tests/test_*.py` | 128 | — |
| Worker first-party `*.test.ts` / `*.test.mjs` | 7 | 29 686 |
| `specs/research_logics/*.yaml` | 2 254 | — |

Worker tests inventoried (no `node_modules`):

- `platform/workers/research-mass-eval/src/{combo_gates,mdh_collapse,path_broken}.test.ts`
- `platform/workers/quant-ops-mcp/test/{auth,mcp,domain-d1,quota}.test.mjs`

No `ingestion-premium` first-party `*.test.ts`. Python↔TS identity for Premium is `tests/test_identity_runtime_parity.py` (executes both runtimes).

---

## Classification table

### `tests/` helpers (not `test_*.py`)

| File | Class | Notes |
|------|-------|-------|
| `tests/conftest.py` | Structural enforcement | Path inserts / shared fixtures. |
| `tests/_coreseed.py` | Split-monolith | COMPLETE-21 seeded builders. |
| `tests/complete21_min_util.py` | Split-monolith | Shared COMPLETE-21 builders. |
| `tests/phase35_matrix_util.py` | Split-monolith | Shared coverage-matrix DB builders. |
| `tests/research_eval_util.py` | Representative | Event-eval fixtures + AST Mass/READY bans. |
| `tests/cf_propose_stub.py` | Representative | Stub propose-thesis payload; never catalog write. |
| `tests/cf_propose_phrase_cases.py` | Duplicate combinatorial | Data only. **This lane** cut occupancy paraphrases 58→9; keep 3 reason classes. |

### `tests/test_*.py`

| File | Class | Notes |
|------|-------|-------|
| `test_agents_pipeline.py` | Representative | Offline paper+risk slice; no DB to roles. |
| `test_agents_roles.py` | Structural enforcement | Role I/O + capability import bans. |
| `test_available_at.py` | Invariant | **Keep.** Conservative placeholder after event. |
| `test_backfill_planner.py` | Representative | Planner jobs; worker summary ≠ pass. |
| `test_baseline_catalog.py` | Invariant | **Keep. Do not delete.** Rejected S1–S5; Mass/READY false. |
| `test_budget_lease.py` | Invariant | Lease authority / concurrent consume. |
| `test_catalog_yaml_parity.py` | Freeze file-count | Identity set `yaml==py==constants` is Invariant. **Follow-up:** `family:` / `theme:` / `go:` raw scans collapsed to **one** YAML pass. cheap_pb Worker body grep moved to `combo_gates.test.ts`. |
| `test_cf_cost_verify.py` | Representative | Missing ADV skip; GO false. |
| `test_cf_daily_path_fanout.py` | Representative | Fan-out ≠ promote; path_broken not COMPLETE. |
| `test_cf_propose_thesis.py` | Invariant | No catalog write, no auto_inject, no GO. Phrase table is Duplicate combinatorial (data). **This lane:** absorbed Worker route scan from husk. |
| `test_class_signals.py` | Representative | Multi-day / event-post PIT; not daily sign. |
| `test_coherence_with_receipts.py` | Invariant | **Keep.** READY coherence fails without receipts. |
| `test_combo_basket_catalog.py` | Representative | Mechanical sleeves; not a pass. |
| `test_complete21_min_compute.py` | Split-monolith | PIT hide future `available_at` + seeded compute. **Keep PIT rows.** |
| `test_complete21_min_features.py` | Split-monolith | Registry / promotion pins. |
| `test_complete21_min_guards.py` | Split-monolith | DEFER fail-closed; COMPLETE-21-only datasets. |
| `test_complete21_min_helpers.py` | Split-monolith | Data-free helpers. |
| `test_complete22_health.py` | Invariant | Floor check; invent COMPLETE 23 fails. |
| `test_core_data_boundary.py` | Structural enforcement | G0: core must not SQLite facts. |
| `test_core_engine.py` | Representative | Engine contract. |
| `test_cost_models_liquidity_linked.py` | Split-monolith | W79 liquidity cost. |
| `test_cost_models_repo_linked.py` | Split-monolith | W78 repo cost. |
| `test_cost_models_short_cost_w85.py` | Split-monolith | W85 short cost. |
| `test_eval_loaders.py` | Representative | No invent / no ffill. |
| `test_eval_registry.py` | Invariant | Recording SoT is R2/D1, not wave markdown. |
| `test_eval_tracks.py` | Representative | ADV-ranked universe; not GO. |
| `test_features_compute.py` | Representative | Feature compute via PIT. |
| `test_features_data_boundary.py` | Structural enforcement | G0. |
| `test_gateway_fail_closed.py` | Invariant | G0 AI gateway. |
| `test_held_book_liquidity.py` | Representative | Held-book ADV. |
| `test_holding_metrics.py` | Representative | Holding metrics + cost default. |
| `test_http_client.py` | Representative | HTTP helper. |
| `test_hypothesis_classes.py` | Invariant | Generation policy; no Mass. |
| `test_idempotency.py` | Invariant | Ingest idempotency. |
| `test_identity_runtime_parity.py` | Invariant | **Not echo:** executes Python and Worker `naturalKey`. Keep. |
| `test_immutable_artifact.py` | Invariant | **Keep.** Content-digest create-if-absent. **Follow-up:** absorbed R2 `default_r2_put` dry-run create-only husk. |
| `test_ingestion_secrets_worker_contract.py` | Dual-runtime policy echo | Static grep of Premium Worker secrets proxy. Keep until replaced by a Worker unit test. |
| `test_issue_receipts_parallel.py` | Invariant | **Keep.** A3 empty-raw ban / receipt issue. |
| `test_jquants_catalog.py` | Representative | Every catalog dataset has `/v2/` route (offline double). |
| `test_jquants_client.py` | Representative | Client paging / errors. |
| `test_jquants_key_migration.py` | Invariant | Natural-key v2. |
| `test_jquants_normalize.py` | Representative | Normalize. |
| `test_jquants_parallel.py` | Representative | Parallel fetch. |
| `test_jquants_pipeline_catalog.py` | Representative | Pipeline catalog + proxy skip. Not a duplicate of `test_jquants_catalog.py` (routing vs persist). |
| `test_jquants_proxy.py` | Representative | Proxy client. |
| `test_jquants_receipt_emit.py` | Invariant | Receipt emit. |
| `test_jsda_corrections.py` | Representative | OTC corrections. |
| `test_jsda_governed.py` | Representative | Governed OTC + PIT provenance. |
| `test_jsda_parse.py` | Representative | Parse. |
| `test_jsda_repo.py` | Representative | Repo CSV. |
| `test_jsda_repo_governed.py` | Representative | Governed repo + receipts. |
| `test_lane_e_ops_auto_projection.py` | Representative husk | **Follow-up:** merged real `--publish-ops` default-OFF into `test_phase35_sync_script.py`; tautology cmd-string tests deleted. |
| `test_mass_research_gate.py` | Invariant | G0 Mass fail-closed; override cannot substitute. |
| `test_mass_strategy_factory.py` | Invariant | Factory freezes; does not clone combo catalog. |
| `test_natural_keys.py` | Invariant | Multi-observation keys. |
| `test_occupancy_audit.py` | Representative | Occupancy maps; not GO. |
| `test_ops_projection_meta.py` | Representative | MISSING / DEGRADED_REFRESH_FAILED. Merge candidate (see below); **not** deleted. |
| `test_ops_projection_publish.py` | Representative | Publish automation. Guard is the sibling G0 file. |
| `test_ops_projection_publish_guard.py` | Invariant | **Keep.** False-COMPLETE / local&lt;remote fail-closed. |
| `test_options_225_vol_series.py` | Representative | Options vol series. |
| `test_paper_boundaries.py` | Structural enforcement | Paper import bans. |
| `test_paper_candidate_adapter.py` | Representative | Unarmed adapter. |
| `test_paper_code_fingerprints.py` | Invariant | Fingerprint stability. |
| `test_paper_execution_service.py` | Representative | Authorized paper service. |
| `test_paper_pipeline.py` | Representative | Phase 5 e2e offline. |
| `test_paper_repo_financing_w86.py` | Representative | Repo financing. |
| `test_paper_snapshot.py` | Invariant | **Keep.** Snapshot / READY publication types. |
| `test_paper_store.py` | Representative | Paper store. |
| `test_parallel_date_jobs.py` | Representative | Date-job fan-out. |
| `test_permanent_defer_history_guard.py` | Invariant | Permanent DEFER must not history-fetch. |
| `test_phase35_availability.py` | Invariant | Python↔`availability.ts` contract. Execution/static parity, keep. |
| `test_phase35_cli_aliases.py` | Representative | CLI aliases. |
| `test_phase35_coverage_cli.py` | Split-monolith | CLI / B0 / validation-log honesty. |
| `test_phase35_coverage_daily.py` | Split-monolith | Daily checks. |
| `test_phase35_coverage_matrix.py` | Split-monolith | **ADR example ~1.2k LOC — already split.** Remaining file is catalog↔doc ID identity + daily tier set. |
| `test_phase35_coverage_weekly.py` | Split-monolith | Weekly checks. |
| `test_phase35_natural_key.py` | Invariant | Contract-selected keys / event-time. |
| `test_phase35_premium_set.py` | Invariant | Premium-core 23 vs `catalog.ts`. |
| `test_phase35_sync_script.py` | Representative | Sync script. |
| `test_phase35_validate.py` | Representative | Validate helpers. |
| `test_phase35_watermarks.py` | Representative | Watermarks. |
| `test_phase4_accept_script.py` | Representative | Accept script. |
| `test_phase4_live_backtest.py` | Representative | Live opt-in; not G0. |
| `test_phase4_live_features.py` | Representative | Live opt-in. |
| `test_phase4_real_db_smoke.py` | Representative | Real-DB smoke opt-in. |
| `test_phase61_coverage_v2.py` | Invariant | **Keep.** Coverage V2 planned segments + receipts; empty ≠ COMPLETE. |
| `test_phase61_ops_projection.py` | Representative | Export SQL JSDA coverage without paths. Overlaps publish; keep (export vs publish). |
| `test_phase61_pit_pagination.py` | Representative | PIT pagination. |
| `test_phase61_read_service.py` | Representative | Read service. |
| `test_phase623_receipt_signature.py` | Invariant | **Keep.** Forgery rejection; staging-only JSDA. |
| `test_phase62_inventory_phase7.py` | Freeze file-count | Pins 31 endpoints / 26 governed. Catalog size is currently an invariant; do not delete without replacing with set-equality vs `data_contracts`. |
| `test_phase6_data_access.py` | Representative | Data-access adapter. |
| `test_phase6_history_sync.py` | Representative | History sync. |
| `test_phase6_snapshot_publication.py` | Invariant | **Keep.** READY snapshot publication fail-closed. |
| `test_phase7_selection.py` | Invariant | Phase 7 foundation fail-closed / budget. |
| `test_pipeline_pit_timestamps.py` | Invariant | **Keep.** Per-job fetch-completion timestamps. |
| `test_pipeline_reports.py` | Representative | Pipeline reports. |
| `test_pit_as_of.py` | Invariant | **Keep.** `as_of` mandatory. |
| `test_pit_coverage.py` | Representative | Happy-path PIT reads per table. |
| `test_pit_lookahead.py` | Invariant | **Keep.** `available_at <= as_of`. |
| `test_pit_revisions_catalog.py` | Invariant | Revisions catalog. |
| `test_plane_import_boundaries.py` | Structural enforcement | G0 plane allow-list. |
| `test_process_isolated_runner.py` | Invariant | Allowlisted binaries; reject shell. |
| `test_r2_feature_context.py` | Representative | R2 feature context. |
| `test_range_batch_scheduler.py` | Representative | Range batch; no token logs. |
| `test_ready_coherence_integration.py` | Invariant | **Keep.** Empty DB / PARTIAL must not publish READY. **This lane:** absorbed `test_ready_policy.py` bundle/policy constructors. |
| `test_receipt_eligibility.py` | Invariant | **Keep.** Only Ed25519-verified receipts COMPLETE. |
| `test_report_raw_throughput.py` | Representative | Throughput script smoke. |
| `test_research_budget_ledger.py` | Invariant | Mass disabled without budget; atomic consume. |
| `test_research_freezes.py` | Invariant | Pins / Mass / READY / GO freeze surface. Secondary Dual-runtime greps **removed this lane** (Worker `combo_gates.test.ts` already owns leftover occupancy). |
| `test_research_robustness_gate.py` | Invariant | Gate pass ≠ READY/Mass. |
| `test_retry_ratelimit.py` | Representative | Deterministic retry. |
| `test_secrets_proxy_pairs.py` | Representative | Pair resolution; several “URL-only is none” rows are mild combinatorics of one invariant. |
| `test_selection_decision.py` | Invariant | Closed schema; reject unknown fields. |
| `test_sign_selection.py` | Representative | Sign flip; document freezes. |
| `test_standard_research_eval.py` | Invariant | Mass/READY closed; period-net stuffed as daily fails. |
| `test_sticky_complete_segment_id_fallback.py` | Invariant | **Keep.** Sticky COMPLETE across segment_end drift. |
| `test_strategies_static_boundaries.py` | Structural enforcement | G0. |
| `test_strategy_spec_schema.py` | Invariant | Closed StrategySpec; no `eval`/`exec`. |
| `test_sync_dataset_coverage_from_segments.py` | Invariant | **Keep.** Empty inventory never COMPLETE; refuse failing checks. |
| `test_timeutil.py` | Representative | JST helpers. |
| `test_tip_auto_path_regression.py` | Structural enforcement | Tip-only forbids history densify/reprobe; AST on issue paths. |
| `test_unique_logic_catalog.py` | Representative | Catalog parse / dispatch / YAML leftover identity. Some integer `n >= 1` pins are mild freeze. |
| `test_unique_logic_event.py` | Representative | Event unique_logic min-impl; PIT median; no ffill. |
| `test_unique_logic_event_filters.py` | Representative | YAML leftover vs lifted is Invariant. **Follow-up:** dropped Worker leftover grep (echo of `combo_gates.test.ts`). |
| `test_wave_script_freeze.py` | Freeze file-count | Empty `ALLOWED_RUN_W` + banned `w0821+` proofs. Structural: residual must stay live flags. Keep (ADR recording). |

Deleted this lane (no longer in tree): `test_ready_policy.py` (merged), `test_cf_propose_worker_contract.py` (merged).

### Worker first-party tests

| File | Class | Notes |
|------|-------|-------|
| `platform/workers/research-mass-eval/src/combo_gates.test.ts` | Representative | **SoT for Worker gate policy.** Unknown gate fail-closed, cheap_pb vs pb_rising, leftover `pre_mom` occupancy (source+behavior). Do **not** delete. Calendar `it()`s are one-per-gate representatives, not 2 254-file freeze. |
| `platform/workers/research-mass-eval/src/mdh_collapse.test.ts` | Invariant | Unique MDH fallback is not a candidate path. |
| `platform/workers/research-mass-eval/src/path_broken.test.ts` | Invariant | Generic CS/MDH fallback is path_broken. |
| `platform/workers/quant-ops-mcp/test/auth.test.mjs` | Invariant | OAuth state sign/verify; reject tamper. |
| `platform/workers/quant-ops-mcp/test/mcp.test.mjs` | Invariant | Ops read-only surface. `names.length == 17` is a mild freeze; keep the banned-tool list. |
| `platform/workers/quant-ops-mcp/test/quota.test.mjs` | Invariant | Daily quota fail-closed. |
| `platform/workers/quant-ops-mcp/test/domain-d1.test.mjs` | Representative | D1 domain tools against migrations. |

**research-mass-eval `src/` production files were not edited.** Python tests that only restated Worker policy already in `combo_gates.test.ts` were dropped (see actions).

---

## Consolidate / delete candidates (documented; most not deleted)

Prefer documenting over mass-delete when the extra check might still be the only copy of a field (`family:`, `theme:`, leftover YAML `params.gates`).

| Candidate | Class | Action | Rationale |
|-----------|-------|--------|-----------|
| `cf_propose_phrase_cases.py` occupancy_label_only ×58 | Duplicate combinatorial | **Done this lane:** keep 9 occupancy + all polarity + sparse | Same reason class; paraphrases. Invariant is the reason set, not N titles. |
| `test_catalog_yaml_parity.py` raw regex loop ×2 254 YAML, twice | Freeze file-count | **Follow-up:** one pass | Identity set-equality kept. `family:` / `theme:` / `go:` raw scans now share the first walk. |
| `test_research_freezes.py::test_unique22_leftover_occupancy_not_unified` | Dual-runtime policy echo | **Deleted this lane** | Byte-identical intent to `combo_gates.test.ts` leftover `it()`. |
| `test_research_freezes.py` Worker comment grep for cheap_pb | Dual-runtime policy echo | **Deleted this lane** (Python constants kept) | `combo_gates` tests cheap_pb vs pb_rising; `test_event_cheap_pb_gate_in_combo_and_yaml` greps the gate body. |
| `test_cf_propose_worker_contract.py` | Dual-runtime policy echo | **Merged** into `test_cf_propose_thesis.py` | One-test husk; Python review is stronger. Route/allowlist scan retained. |
| `test_ready_policy.py` | Invariant (thin) | **Merged** into `test_ready_coherence_integration.py` | Bundle pass/fail is weaker than empty-DB READY refuse; keep both assertions, one file. |
| `test_unique_logic_event_filters.py` Worker leftover grep | Dual-runtime policy echo | **Follow-up:** dropped grep, kept YAML leftover-vs-lifted | Worker slice duplicated `combo_gates.test.ts`. Occupancy band asserts untouched. |
| `test_catalog_yaml_parity.py::test_event_cheap_pb_gate_in_combo_and_yaml` Worker body regex | Dual-runtime policy echo | **Follow-up:** dropped Python grep | `combo_gates` cheap_pb `it()` now asserts event path does not read `extras?.cheapPb`. YAML/constants half kept. |
| `test_ops_projection_meta.py` | Representative husk | **Deleted** (dead-code lane) | Assertions live in `test_ops_projection_publish.py`. |
| `test_catalog_family.py` | Representative husk | **Follow-up:** merged | Flow-gate ≠ flow family into `test_catalog_compiler.py`. Dropped `n >= 1` freeze. |
| `test_r2_io_create_only.py` | Representative husk | **Follow-up:** merged | Dry-run create-only into `test_immutable_artifact.py`. |
| `test_lane_e_ops_auto_projection.py` | Representative husk | **Follow-up:** merged | `--publish-ops` default OFF into `test_phase35_sync_script.py`. Deleted tautology husks. |
| `test_secrets_proxy_pairs.py` URL-only ×3 sources | Duplicate combinatorial | Document | Keep env/json/split as three sources (different code paths). |
| `test_phase62_inventory_phase7.py` `len==31` / `26` | Freeze file-count | Document | Replace later with set-equality vs governed JSON; do not drop the names (`td_bulk`, minute bars). |
| `combo_gates.test.ts` calendar `it()`s | Representative | Keep | Distinct gate semantics (Tue vs Wed vs month_start7), not copies of one invariant. |
| `test_jquants_catalog.py` vs `test_jquants_pipeline_catalog.py` | Representative | Keep both | Route coverage vs pipeline persist. |
| COMPLETE-21 / phase35 / cost_models / unique_logic splits | Split-monolith | Keep split | ADR B1-d target (`test_phase35_coverage_matrix.py` was ~1.2k LOC) already landed. |
| PIT / `available_at` / receipts / false-COMPLETE / READY / `test_baseline_catalog.py` | Invariant | **Never delete** | Lane constraint. |

`tests/test_smoke.py` is **absent** (do not recreate). **HEAD:** `tests/README.md` live G0 no longer cites `unittest tests.test_smoke`.

Dirty main (not in `1efb405`) had extra `test_catalog_family.py` / `test_research_capabilities.py` and Worker `capabilities.test.ts` / `candidate.test.ts` / `http.test.ts`. Out of this lane’s tree.

---

## Actions taken this lane

1. **Merged** `test_ready_policy.py` → `test_ready_coherence_integration.py` (stronger READY refuse). Husk deleted.
2. **Merged** `test_cf_propose_worker_contract.py` → `test_cf_propose_thesis.py` (stronger Python review). Husk deleted; Worker route scan kept as one test.
3. **Shrunk** phrase table 68→19 rows (58 occupancy paraphrases → 9 representatives). Structural replacement: `len >= 40` → reason-class set equality.
4. **Deleted** Python Worker-source echo `test_unique22_leftover_occupancy_not_unified` (Worker unit test already owns it).
5. **Trimmed** `test_cheap_pb_event_not_csfundsnaps` to Python constants only.
6. **Did not** add new test modules. **Did not** edit `research-mass-eval` production src. **Did not** flip GO/Mass/READY.

---

## Counts

| Metric | Before | After | Δ |
|--------|-------:|------:|--:|
| `tests/` files | 147 | 145 | −2 |
| `tests/` bytes | 1 037 955 | 1 021 178 | −16 777 |
| `tests/*.py` | 135 | 133 | −2 |
| `tests/test_*.py` | 128 | 126 | −2 |
| Phrase rows | 68 | 19 | −49 |
| Worker first-party test files | 7 | 7 | 0 |

| Tests | Count |
|-------|------:|
| **Retained** | All PIT / `available_at` / receipt / false-COMPLETE / immutable READY / `test_baseline_catalog.py` / G0 guards / Worker `combo_gates` |
| **Consolidated** | 2 files merged; phrase table reason-class representatives |
| **Deleted** | 2 husk files; 1 echo test function; 49 occupancy phrase rows |
| **Added** | **0** modules |
| **Structural replacements** | 1 (`len(REVIEW_PHRASE_CASES) >= 40` → reason-class set) |

Affected pytest after edit: `test_cf_propose_thesis.py`, `test_ready_coherence_integration.py`, `test_research_freezes.py`, `test_catalog_yaml_parity.py::test_event_cheap_pb_gate_in_combo_and_yaml` — 26 passed.

Follow-up (fail-closed Gateway): `test_cf_propose_thesis.py` worker contract now asserts **no** `[ai]` / `env.AI.run` on mass-eval, and requires `AI_GATEWAY` service binding. That is a structural replacement, not a new combinatorial test.

---

## Follow-up consolidation (off `9cbb7fc`)

**Tip:** this commit (`p63/lane-17b-test-consol`).  
**Mass / READY / Phase 7:** unchanged. **Added modules: 0.**

Does **not** delete PIT / `available_at` / receipts / false-COMPLETE / READY / fail-closed auth / `job_candidate_grade` / capabilities / `test_baseline_catalog.py` / cost_models liquidity / occupancy band asserts / Worker `combo_gates`.

Post-Lane-17 tree already absorbed `test_ops_projection_meta.py` (dead-code lane) and added compiler / family / IR / capabilities / R2 create-only / applied-pins / Phase 7 construct tests.

### Inventory (follow-up start, `9cbb7fc`)

| Surface | Count | Bytes |
|---------|------:|------:|
| `tests/` files (no `__pycache__`) | 151 | 1 055 285 |
| `tests/*.py` | 139 | 1 047 983 |
| `tests/test_*.py` | 132 | — |
| Worker first-party `*.test.ts` / `*.test.mjs` | 13 | 39 078 |

### Actions this follow-up

1. **Merged** `test_catalog_family.py` → `test_catalog_compiler.py` (flow-gate ≠ flow family). Dropped `n >= 1` / `>= 0` freeze husk; kept `go is False`.
2. **Merged** `test_r2_io_create_only.py` → `test_immutable_artifact.py` (create-if-absent / dry-run does not need wrangler).
3. **Merged** `test_lane_e_ops_auto_projection.py` → `test_phase35_sync_script.py`. Kept `--publish-ops` default OFF. Deleted tautology husks that asserted argv strings they just built.
4. **Dropped** Worker leftover occupancy grep from `test_unique_logic_event_filters.py`. YAML leftover-vs-lifted `params.gates` kept. `combo_gates.test.ts` remains SoT.
5. **Dropped** Python `cheap_pb` Worker-body regex. **Structural replacement:** existing `combo_gates` cheap_pb `it()` asserts event path uses bars×fins and does not read `extras?.cheapPb`.
6. **Collapsed** catalog YAML `family:` / `theme:` / `go:` raw scans to **one** pass. Identity set-equality `yaml==py==constants` kept.
7. **Did not** add test modules. **Did not** edit `research-mass-eval` production `src/`. **Did not** flip GO/Mass/READY.

### Counts (follow-up)

| Metric | Before (`9cbb7fc`) | After | Δ |
|--------|-------------------:|------:|--:|
| `tests/` files | 151 | 148 | −3 |
| `tests/` bytes | 1 055 285 | 1 049 937 | −5 348 |
| `tests/*.py` | 139 | 136 | −3 |
| `tests/test_*.py` | 132 | 129 | −3 |
| Worker first-party test files | 13 | 13 | 0 |
| Worker test bytes | 39 078 | 39 522 | +444 (cheap_pb event-path assert) |

| Tests | Count |
|-------|------:|
| **Retained** | PIT / receipts / false-COMPLETE / READY / fail-closed auth / `job_candidate_grade` / capabilities / `test_baseline_catalog.py` / cost_models liquidity / occupancy band asserts / Worker `combo_gates` |
| **Consolidated** | 3 files merged; YAML walks → one pass; leftover/cheap_pb Python greps → Worker SoT |
| **Deleted** | 3 husk files; tautology lane-E cmd-string tests; Worker leftover grep body |
| **Added** | **0** modules |
| **Structural replacements** | 1 (`combo_gates` event cheap_pb does not read `extras?.cheapPb`) |
