# Phase 6.3.3 stack filemap (`origin/main` … `58133512`)

MAP only. Parent cherry-picks onto stack branches from `origin/main` later.
Source: `git diff --name-only origin/main...58133512e1e896f1e811d1fb597337aa8f53d965`.

| Field | Value |
|-------|--------|
| origin/main | `b5c326a7f612563f2da4a84f08063a307ec38e0a` |
| feature tip | `58133512e1e896f1e811d1fb597337aa8f53d965` |
| commits | 450 |
| files | 421 |
| ADR | [`docs/architecture/adr_phase633_pr_stack.md`](../docs/architecture/adr_phase633_pr_stack.md) |
| PR #1 | https://github.com/ddnne/quant-platform/pull/1 **OPEN** (audit ref; do not close/squash/force-push) |

Each of the 10 product PRs is ≤35 files. Graphite unavailable; plain-git stacked PRs.
`RECONSTITUTION_APPLY` stays False. No Mass/READY/GO/live broker. No YAML `+N`.
No leftover occupancy extract. No GitHub Actions. Never `--legacy-peer-deps`.
Cherry-pick order: **01 → 05 → 04**, then 02, 03, 06–10 as numbered (PR 04 imports 01 and 05).

## Counts

| PR | Theme | n |
|----|-------|--:|
| 01 | contracts / Evaluation IR / source-capability | 19 |
| 02 | receipt authority (Lane B) | 10 |
| 03 | paper execution (Lane C) | 9 |
| 04 | READY manifest/profile (Lane D) — predicate only; READY undeclared | 10 |
| 05 | coverage V3 four datasets (Lane E) | 28 |
| 06 | budget Durable Object (Lane F) | 10 |
| 07 | native CF CI config (Lane G) — HUMAN GitHub App / Workers Build; ci-aggregate is not merge SoT | 19 |
| 08 | public surface wrangler (Lane H) | 35 |
| 09 | data-plane integrity (Lane I) | 35 |
| 10 | agent sandbox + 4 experiment plans (J+K) — factory OFF; RECONSTITUTION_APPLY false | 34 |
| audit-hold-pr1 | docs/reviews audit warehouse — stay on PR #1; do not restack SHA revisits or P632_wave* | 89 |
| later-11 | remaining ingestion-premium fetch/persist/R2/SCD2/export | 19 |
| later-12 | remaining ingestion-premium npm/index/ops/sha256 | 18 |
| later-13 | remaining research-mass-eval HTTP/freeze/parse | 19 |
| later-14 | remaining ingestion-jsda + ingestion-secrets npm/index | 19 |
| later-15 | remaining research-ai-gateway + quant-ops-mcp index/tests | 20 |
| later-16 | remaining Python research I/O, scripts, phase63 docs, pyproject, grok workflow | 28 |
| **sum** | | **421** |

## PR 01 — contracts / Evaluation IR / source-capability

19 files.

```
specs/source_capability/equities_bars_daily_am.json
specs/source_capability/equities_earnings_calendar.json
specs/source_capability/equities_master.json
specs/source_capability/jsda_otc_bond_reference_prices.json
specs/evaluation_ir/schema.json
packages/data_plane/data_contracts/source_capability.py
packages/data_plane/data_contracts/source_capability.schema.json
packages/data_plane/data_contracts/__init__.py
packages/product/research/evaluation_ir.py
packages/product/research/evaluation_ir_codec.generated.py
packages/product/research/evaluation_ir_emit.py
packages/product/research/evaluation_ir_types.generated.py
platform/workers/research-mass-eval/src/evaluation_ir.ts
platform/workers/research-mass-eval/src/evaluation_ir.test.ts
platform/workers/research-mass-eval/src/evaluation_ir_allowed_fields.generated.ts
platform/workers/research-mass-eval/src/evaluation_ir_codec.generated.ts
tests/test_source_capability.py
tests/test_source_capability_contract.py
tests/test_evaluation_ir.py
```

## PR 02 — receipt authority (Lane B)

10 files.

```
packages/data_plane/ingestion/pipeline_receipts.py
platform/workers/ingestion-premium/src/collection_receipts.ts
platform/workers/ingestion-premium/src/collection_receipts.test.ts
scripts/issue_receipts_parallel.py
scripts/issue_signed_receipts_for_segments.py
scripts/write_collection_receipts.py
tests/test_issue_receipts_parallel_cli.py
tests/test_issue_signed_receipts_for_segments.py
tests/test_write_collection_receipts.py
tests/test_coherence_with_receipts.py
```

## PR 03 — paper execution (Lane C)

9 files.

```
packages/research_runtime/core/engine.py
packages/research_runtime/core/universe.py
tests/test_paper_execution_service.py
tests/test_paper_pipeline.py
tests/test_paper_repo_financing_w86.py
tests/test_paper_store.py
tests/test_core_engine.py
tests/test_phase4_live_backtest.py
tests/test_phase4_real_db_smoke.py
```

## PR 04 — READY manifest/profile (Lane D) — predicate only; READY undeclared

10 files.

```
specs/research_profiles/core_v1.json
packages/product/research/research_data_profile.py
packages/research_runtime/features/dataset_guard.py
packages/research_runtime/features/runtime.py
packages/research_runtime/paper_runtime/snapshot_publish_policy.py
tests/test_research_data_profile.py
tests/test_phase6_snapshot_publication.py
tests/test_ops_coverage_echoes_unpublished_policy.py
tests/test_core_data_boundary.py
tests/test_complete21_min_guards.py
```

## PR 05 — coverage V3 four datasets (Lane E)

28 files.

```
specs/coverage_v3/equities_bars_daily_am_migration.json
specs/coverage_v3/equities_earnings_calendar_migration.json
specs/coverage_v3/equities_master_migration.json
specs/coverage_v3/jsda_otc_official_index_migration.json
packages/data_plane/data_contracts/coverage.py
packages/data_plane/data_contracts/collection_coverage.json
packages/data_plane/data_contracts/canonical_datasets.json
packages/data_plane/data_contracts/jquants_premium_core.json
packages/data_plane/data_contracts/permanent_defer.py
packages/data_plane/storage/coverage_ledger.py
packages/edge/cf_platform/ingest_premium/coverage.py
packages/edge/cf_platform/ingest_premium/matrix.py
packages/edge/cf_platform/ingest_premium/validate.py
packages/data_plane/ops/backfill_planner.py
scripts/refresh_coverage_ledger.py
tests/test_collection_coverage_contract.py
tests/test_phase61_coverage_v2.py
tests/test_phase35_coverage_daily.py
tests/test_phase35_coverage_matrix.py
tests/test_phase35_premium_set.py
tests/test_phase35_availability.py
tests/test_phase35_validate.py
tests/test_am_bars_tip_only.py
tests/test_earnings_calendar_tip_only.py
tests/test_permanent_defer_history_guard.py
tests/test_backfill_planner.py
tests/test_refresh_coverage_ledger_cli.py
tests/test_jquants_catalog.py
```

## PR 06 — budget Durable Object (Lane F)

10 files.

```
platform/workers/research-ai-gateway/src/budget_do.ts
platform/workers/research-ai-gateway/src/budget_do.test.ts
platform/workers/research-ai-gateway/src/budget_http.ts
platform/workers/research-ai-gateway/src/budget_http.test.ts
platform/workers/research-ai-gateway/src/budget_amounts.test.ts
platform/workers/research-ai-gateway/src/budget_http_heartbeat.test.ts
platform/workers/research-ai-gateway/src/budget_http_reconcile.test.ts
platform/workers/research-ai-gateway/src/budget_http_release.test.ts
platform/workers/research-ai-gateway/src/budget_http_reserve_zero.test.ts
platform/workers/research-ai-gateway/src/index_complete_budget.test.ts
```

## PR 07 — native CF CI config (Lane G) — HUMAN GitHub App / Workers Build; ci-aggregate is not merge SoT

19 files.

```
docs/ci/workers_builds.md
scripts/ci_aggregate_first_deploy.sh
scripts/verify_ci.sh
scripts/verify_all.sh
tests/test_ci_aggregate_first_deploy_script.py
tests/test_verify_ci_script.py
platform/workers/ci-aggregate/package-lock.json
platform/workers/ci-aggregate/package.json
platform/workers/ci-aggregate/src/authorized.test.ts
platform/workers/ci-aggregate/src/authorized.ts
platform/workers/ci-aggregate/src/http_json.test.ts
platform/workers/ci-aggregate/src/http_json.ts
platform/workers/ci-aggregate/src/index.test.ts
platform/workers/ci-aggregate/src/index.ts
platform/workers/ci-aggregate/src/receipts_gate.ts
platform/workers/ci-aggregate/tsconfig.json
platform/workers/ci-aggregate/vitest.config.ts
platform/workers/ci-aggregate/worker-configuration.d.ts
platform/workers/ci-aggregate/wrangler.toml
```

## PR 08 — public surface wrangler (Lane H)

35 files.

```
platform/workers/ingestion-jsda/wrangler.toml
platform/workers/ingestion-jsda/worker-configuration.d.ts
platform/workers/ingestion-jsda/src/authorized.ts
platform/workers/ingestion-jsda/src/authorized.test.ts
platform/workers/ingestion-jsda/src/http_json.ts
platform/workers/ingestion-jsda/src/http_json.test.ts
platform/workers/ingestion-premium/wrangler.toml
platform/workers/ingestion-premium/worker-configuration.d.ts
platform/workers/ingestion-premium/src/http_json.ts
platform/workers/ingestion-premium/src/http_json.test.ts
platform/workers/ingestion-premium/src/ingestion_token.ts
platform/workers/ingestion-premium/src/ingestion_token.test.ts
platform/workers/ingestion-secrets/wrangler.toml
platform/workers/ingestion-secrets/worker-configuration.d.ts
platform/workers/ingestion-secrets/src/authorized.ts
platform/workers/ingestion-secrets/src/authorized.test.ts
platform/workers/ingestion-secrets/src/http_json.ts
platform/workers/ingestion-secrets/src/http_json.test.ts
platform/workers/research-ai-gateway/wrangler.toml
platform/workers/research-ai-gateway/worker-configuration.d.ts
platform/workers/research-ai-gateway/src/authorized.ts
platform/workers/research-ai-gateway/src/authorized.test.ts
platform/workers/research-ai-gateway/src/http_json.ts
platform/workers/research-mass-eval/wrangler.toml
platform/workers/research-mass-eval/worker-configuration.d.ts
platform/workers/research-mass-eval/src/authorized.ts
platform/workers/research-mass-eval/src/authorized.test.ts
platform/workers/research-mass-eval/src/http_json.ts
platform/workers/research-mass-eval/src/http_json.test.ts
platform/workers/quant-ops-mcp/wrangler.toml
platform/workers/quant-ops-mcp/worker-configuration.d.ts
platform/workers/quant-ops-mcp/src/index.js
platform/workers/quant-ops-mcp/src/health.js
packages/edge/mcp_servers/quant_data/server.py
tests/test_phase61_read_service.py
```

## PR 09 — data-plane integrity (Lane I)

35 files.

```
packages/data_plane/ingestion/jsda/archive.py
packages/data_plane/ingestion/jsda/official_index.py
packages/data_plane/ingestion/jsda/parse.py
packages/data_plane/ingestion/jsda/repo_archive.py
packages/data_plane/ingestion/pipeline.py
packages/data_plane/data_contracts/identity.py
packages/data_plane/data_access/service.py
packages/data_plane/pit/api.py
packages/data_plane/storage/migrations.py
packages/data_plane/ops/projection_meta.py
packages/data_plane/ops/range_batch_scheduler.py
packages/data_plane/README.md
packages/data_plane/data_contracts/README.md
scripts/jsda_otc_seal_official.py
scripts/export_ops_projection.py
scripts/publish_ops_projection.py
tests/test_jsda_governed.py
tests/test_jsda_otc_official_domain.py
tests/test_jsda_otc_seal_official.py
tests/test_jsda_parse.py
tests/test_jsda_repo_governed.py
tests/test_equities_master_official_domain.py
tests/test_identity_official_clamp.py
tests/test_identity_runtime_parity.py
tests/test_pipeline_otc_index_text.py
tests/fixtures/jsda_otc_official_index_tiny.html
tests/fixtures/jsda_otc_reference_headerless_23col.csv
tests/test_ops_projection_publish.py
tests/test_phase6_data_access.py
tests/test_phase6_history_sync.py
tests/test_range_batch_scheduler.py
tests/test_complete22_health.py
platform/workers/ingestion-premium/src/identity.ts
platform/workers/ingestion-premium/src/identity.test.ts
platform/workers/ingestion-premium/migrations/0010_raw_acquisition_status.sql
```

## PR 10 — agent sandbox + 4 experiment plans (J+K) — factory OFF; RECONSTITUTION_APPLY false

34 files.

```
packages/product/research/catalog_active.py
packages/product/research/catalog_compiler.py
packages/product/research/cf_propose_policy.py
packages/product/research/cf_propose_thesis.py
packages/product/research/cf_daily_path_job.py
packages/product/research/offline/factory_eval.py
packages/product/research/offline/factory_eval_data.py
packages/product/research/offline/factory_eval_screen.py
packages/product/research/offline/multiyear.py
packages/product/research/unique_logic/catalog.py
packages/product/research/unique_logic/catalog_yaml_parse.py
packages/product/research/unique_logic/worker_bodies.py
packages/product/research/occupancy_audit.py
packages/product/research/occupancy_audit_run.py
packages/product/research/reconstitution_evidence.py
packages/product/research/combo_basket_catalog.py
packages/product/research/cf_mass_eval_job.py
packages/product/research/cf_mass_eval_run.py
packages/product/research/cf_mass_eval_stage.py
packages/product/research/cf_mass_eval_thicken.py
docs/phase63_reconstitution_pending.md
tests/test_agents_pipeline.py
tests/test_cf_propose_thesis.py
tests/test_catalog_compiler.py
tests/test_catalog_active_legacy.py
tests/test_catalog_yaml_parity.py
tests/test_occupancy_audit.py
tests/test_reconstitution_evidence.py
tests/test_unique_logic_catalog.py
tests/test_unique_logic_event_filters.py
tests/test_cf_mass_eval_deploy_opt_in.py
platform/workers/research-mass-eval/src/propose_thesis.test.ts
platform/workers/research-mass-eval/src/candidate.test.ts
tests/test_phase62_inventory_phase7.py
```

## Leftover (not in the 10 PRs)

Cap 35/group. `docs/reviews/**` stay on PR #1 as audit. later-11…16 are after the product stack.

## audit-hold-pr1 — docs/reviews audit warehouse — stay on PR #1; do not restack SHA revisits or P632_wave*

89 files.

```
docs/reviews/A07_catalog.md
docs/reviews/A11_waste.md
docs/reviews/P632B_03_gateway_token_service_binding_hold.md
docs/reviews/P632_brief_leaks.md
docs/reviews/P632_ind_A_pit_complete.md
docs/reviews/P632_ind_A_revisit.md
docs/reviews/P632_ind_A_revisit_02fb6cbd.md
docs/reviews/P632_ind_A_revisit_242c2484.md
docs/reviews/P632_ind_A_revisit_2b82ec7d.md
docs/reviews/P632_ind_A_revisit_3b64bdfc.md
docs/reviews/P632_ind_A_revisit_40d1aa90.md
docs/reviews/P632_ind_A_revisit_5103b26b.md
docs/reviews/P632_ind_A_revisit_67fcbd7c.md
docs/reviews/P632_ind_A_revisit_b1605c36.md
docs/reviews/P632_ind_A_revisit_b5f6f2de.md
docs/reviews/P632_ind_A_revisit_cf7da56c.md
docs/reviews/P632_ind_A_revisit_ed94d504.md
docs/reviews/P632_ind_A_revisit_f224e7e.md
docs/reviews/P632_ind_B_ci_authority.md
docs/reviews/P632_ind_B_revisit.md
docs/reviews/P632_ind_B_revisit_02fb6cbd.md
docs/reviews/P632_ind_B_revisit_242c2484.md
docs/reviews/P632_ind_B_revisit_2b82ec7d.md
docs/reviews/P632_ind_B_revisit_3b64bdfc.md
docs/reviews/P632_ind_B_revisit_40d1aa90.md
docs/reviews/P632_ind_B_revisit_5103b26b.md
docs/reviews/P632_ind_B_revisit_67fcbd7c.md
docs/reviews/P632_ind_B_revisit_b1605c36.md
docs/reviews/P632_ind_B_revisit_b5f6f2de.md
docs/reviews/P632_ind_B_revisit_cf7da56c.md
docs/reviews/P632_ind_B_revisit_ed94d504.md
docs/reviews/P632_ind_B_revisit_f224e7e.md
docs/reviews/P632_ind_C_catalog_pilot.md
docs/reviews/P632_ind_C_revisit.md
docs/reviews/P632_ind_C_revisit_02fb6cbd.md
docs/reviews/P632_ind_C_revisit_0a8ced34.md
docs/reviews/P632_ind_C_revisit_242c2484.md
docs/reviews/P632_ind_C_revisit_2b82ec7d.md
docs/reviews/P632_ind_C_revisit_40d1aa90.md
docs/reviews/P632_ind_C_revisit_5103b26b.md
docs/reviews/P632_ind_C_revisit_67fcbd7c.md
docs/reviews/P632_ind_C_revisit_b1605c36.md
docs/reviews/P632_ind_C_revisit_b5f6f2de.md
docs/reviews/P632_ind_C_revisit_cf7da56c.md
docs/reviews/P632_ind_C_revisit_ed94d504.md
docs/reviews/P632_ind_C_revisit_f224e7e.md
docs/reviews/P632_projection_refresh_false.md
docs/reviews/P632_projection_stale.md
docs/reviews/P632_test_inventory.md
docs/reviews/P632_test_inventory_02fb6cbd.md
docs/reviews/P632_test_inventory_242c2484.md
docs/reviews/P632_test_inventory_2b82ec7d.md
docs/reviews/P632_test_inventory_3b64bdfc.md
docs/reviews/P632_test_inventory_40d1aa90.md
docs/reviews/P632_test_inventory_5103b26b.md
docs/reviews/P632_test_inventory_67fcbd7c.md
docs/reviews/P632_test_inventory_b1605c36.md
docs/reviews/P632_test_inventory_b5f6f2de.md
docs/reviews/P632_test_inventory_cf7da56c.md
docs/reviews/P632_test_inventory_ed94d504.md
docs/reviews/P632_test_inventory_now.md
docs/reviews/P632_verify_ci_02fb6cbd.md
docs/reviews/P632_verify_ci_242c2484.md
docs/reviews/P632_verify_ci_2b82ec7d.md
docs/reviews/P632_verify_ci_3b64bdfc.md
docs/reviews/P632_verify_ci_40d1aa90.md
docs/reviews/P632_verify_ci_5103b26b.md
docs/reviews/P632_verify_ci_67fcbd7c.md
docs/reviews/P632_verify_ci_b1605c36.md
docs/reviews/P632_verify_ci_b5f6f2de.md
docs/reviews/P632_verify_ci_cf7da56c.md
docs/reviews/P632_verify_ci_ed94d504.md
docs/reviews/P632_verify_ci_f224e7e.md
docs/reviews/P632_wave0_live.md
docs/reviews/P632_wave10_status.md
docs/reviews/P632_wave11_status.md
docs/reviews/P632_wave12_status.md
docs/reviews/P632_wave13_status.md
docs/reviews/P632_wave14_status.md
docs/reviews/P632_wave2_status.md
docs/reviews/P632_wave3_status.md
docs/reviews/P632_wave4_status.md
docs/reviews/P632_wave5_status.md
docs/reviews/P632_wave6_status.md
docs/reviews/P632_wave7_status.md
docs/reviews/P632_wave8_status.md
docs/reviews/P632_wave9_status.md
docs/reviews/README.md
docs/reviews/original_plan_gap.md
```

## later-11 — remaining ingestion-premium fetch/persist/R2/SCD2/export

19 files.

```
platform/workers/ingestion-premium/src/availability.test.ts
platform/workers/ingestion-premium/src/catalog.test.ts
platform/workers/ingestion-premium/src/fetch_jq.test.ts
platform/workers/ingestion-premium/src/fetch_jq.ts
platform/workers/ingestion-premium/src/http_export.test.ts
platform/workers/ingestion-premium/src/http_export.ts
platform/workers/ingestion-premium/src/http_export_query_token.test.ts
platform/workers/ingestion-premium/src/master_scd2/write.test.ts
platform/workers/ingestion-premium/src/master_scd2/write.ts
platform/workers/ingestion-premium/src/natural_key_migration.test.ts
platform/workers/ingestion-premium/src/persist_records.test.ts
platform/workers/ingestion-premium/src/persist_records.ts
platform/workers/ingestion-premium/src/r2_structured_writer.test.ts
platform/workers/ingestion-premium/src/r2_structured_writer.ts
platform/workers/ingestion-premium/src/rate_limit.test.ts
platform/workers/ingestion-premium/src/retry_jitter.test.ts
platform/workers/ingestion-premium/src/retry_jitter.ts
platform/workers/ingestion-premium/src/write_path_config.test.ts
platform/workers/ingestion-premium/src/write_path_config.ts
```

## later-12 — remaining ingestion-premium npm/index/ops/sha256

18 files.

```
platform/workers/ingestion-premium/.gitignore
platform/workers/ingestion-premium/package-lock.json
platform/workers/ingestion-premium/package.json
platform/workers/ingestion-premium/src/index.test.ts
platform/workers/ingestion-premium/src/index.ts
platform/workers/ingestion-premium/src/index_run_query_token.test.ts
platform/workers/ingestion-premium/src/ops_artifacts_plan.test.ts
platform/workers/ingestion-premium/src/ops_artifacts_plan.ts
platform/workers/ingestion-premium/src/ops_cold_archive.test.ts
platform/workers/ingestion-premium/src/ops_cold_archive.ts
platform/workers/ingestion-premium/src/ops_parquet_manifest.test.ts
platform/workers/ingestion-premium/src/ops_parquet_manifest.ts
platform/workers/ingestion-premium/src/ops_prune_changelog.test.ts
platform/workers/ingestion-premium/src/ops_prune_changelog.ts
platform/workers/ingestion-premium/src/sha256.test.ts
platform/workers/ingestion-premium/src/sha256.ts
platform/workers/ingestion-premium/tsconfig.json
platform/workers/ingestion-premium/vitest.config.ts
```

## later-13 — remaining research-mass-eval HTTP/freeze/parse

19 files.

```
platform/workers/research-mass-eval/package.json
platform/workers/research-mass-eval/src/ai_gateway_client.test.ts
platform/workers/research-mass-eval/src/eval_orchestrate.test.ts
platform/workers/research-mass-eval/src/freeze.test.ts
platform/workers/research-mass-eval/src/freeze.ts
platform/workers/research-mass-eval/src/http.test.ts
platform/workers/research-mass-eval/src/http.ts
platform/workers/research-mass-eval/src/http_children_required.test.ts
platform/workers/research-mass-eval/src/http_health.test.ts
platform/workers/research-mass-eval/src/http_nets_only.test.ts
platform/workers/research-mass-eval/src/http_query_token.test.ts
platform/workers/research-mass-eval/src/http_remaining.test.ts
platform/workers/research-mass-eval/src/http_routes.ts
platform/workers/research-mass-eval/src/http_routes_parse.test.ts
platform/workers/research-mass-eval/src/metrics.test.ts
platform/workers/research-mass-eval/src/panels.test.ts
platform/workers/research-mass-eval/src/parse_request.ts
platform/workers/research-mass-eval/src/sha256.test.ts
platform/workers/research-mass-eval/src/sha256.ts
```

## later-14 — remaining ingestion-jsda + ingestion-secrets npm/index

19 files.

```
platform/workers/ingestion-jsda/.gitignore
platform/workers/ingestion-jsda/package-lock.json
platform/workers/ingestion-jsda/package.json
platform/workers/ingestion-jsda/src/index.test.ts
platform/workers/ingestion-jsda/src/index.ts
platform/workers/ingestion-jsda/src/index_run_query_token.test.ts
platform/workers/ingestion-jsda/src/sha256.test.ts
platform/workers/ingestion-jsda/src/sha256.ts
platform/workers/ingestion-jsda/tsconfig.json
platform/workers/ingestion-jsda/vitest.config.ts
platform/workers/ingestion-secrets/.gitignore
platform/workers/ingestion-secrets/package-lock.json
platform/workers/ingestion-secrets/package.json
platform/workers/ingestion-secrets/src/index.test.ts
platform/workers/ingestion-secrets/src/index.ts
platform/workers/ingestion-secrets/src/index_proxy_query_token.test.ts
platform/workers/ingestion-secrets/src/test-setup.ts
platform/workers/ingestion-secrets/tsconfig.json
platform/workers/ingestion-secrets/vitest.config.ts
```

## later-15 — remaining research-ai-gateway + quant-ops-mcp index/tests

20 files.

```
platform/workers/research-ai-gateway/package.json
platform/workers/research-ai-gateway/src/index.test.ts
platform/workers/research-ai-gateway/src/index.ts
platform/workers/research-ai-gateway/src/index_cf_worker.test.ts
platform/workers/research-ai-gateway/src/index_complete.test.ts
platform/workers/research-ai-gateway/src/index_complete_json.test.ts
platform/workers/research-ai-gateway/src/index_complete_unknown.test.ts
platform/workers/research-ai-gateway/src/index_query_token.test.ts
platform/workers/research-ai-gateway/src/sha256.test.ts
platform/workers/research-ai-gateway/src/sha256.ts
platform/workers/quant-ops-mcp/package.json
platform/workers/quant-ops-mcp/src/domain.js
platform/workers/quant-ops-mcp/src/domain_policy.js
platform/workers/quant-ops-mcp/test/domain-d1.test.mjs
platform/workers/quant-ops-mcp/test/mcp.test.mjs
platform/workers/quant-ops-mcp/test/mcp_http_accept.test.mjs
platform/workers/quant-ops-mcp/test/mcp_http_content_type.test.mjs
platform/workers/quant-ops-mcp/test/mcp_http_protocol_version.test.mjs
platform/workers/quant-ops-mcp/test/oauth_callback_missing.test.mjs
platform/workers/quant-ops-mcp/test/well_known.test.mjs
```

## later-16 — remaining Python research I/O, scripts, phase63 docs, pyproject, grok workflow

28 files.

```
.grok/workflows/p632-remaining-close.rhai
docs/architecture.md
docs/phase62_residual_status.md
docs/phase63_dead_code.md
docs/phase63_refactor_plan.md
docs/phase63_test_audit.md
packages/product/research/cf_cost_verify.py
packages/product/research/eval_loaders_sidecars.py
packages/product/research/r2_feature_context.py
packages/product/research/r2_io.py
packages/product/research/stats_metrics.py
packages/product/research/stats_metrics_gates.py
pyproject.toml
scripts/README.md
scripts/ops/cf_premium_backfill.py
scripts/ops_reeval_freshness.py
scripts/run_phase4_accept.py
tests/README.md
tests/test_cf_cost_verify.py
tests/test_cf_premium_backfill_cli.py
tests/test_eval_loaders.py
tests/test_immutable_artifact.py
tests/test_ingestion_secrets_worker_contract.py
tests/test_r2_get_object_non_authority.py
tests/test_research_default_r2_put_callers.py
tests/test_secrets_proxy_pairs.py
tests/test_try_r2_get_json.py
tests/test_worker_extracted_helpers.py
```

## Constraints for parent cherry-picks

- Do not force-push `main` or PR #1. Do not close PR #1.
- Do not add `docs/reviews/P632_wave*` files.
- Do not extract leftover occupancy from `daily_path.ts` (not in this delta).
- Lane G: `ci-aggregate` Worker is **not** the final merge SoT. HUMAN GitHub App / Workers Build project.
- PR 10 experiment plans are declarations (`experiment-plan/v1`), not Mass start.
- `scripts/ops/cf_premium_backfill.py` is leftover (later-16); do not launch from residual prose.
