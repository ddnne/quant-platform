# D-dead — unused functions (not modules)

**Lane:** dead-code follow-up (functions, not `docs/phase63_dead_code.md` modules)  
**Mass / READY / Phase 7 / GO:** unchanged.  
**Deleted this lane:** `today_str`, `dump_json`, `load_shard_bars`, `write_manifest_local` (zero importers, zero tests, not CLI / Worker / fail-closed).

AST-walk of `packages/` + `tests/` (+ scripts / Worker string scan). A name is unused only with zero importers, zero tests, not `python -m`, not a Worker mirror, not a public fail-closed gate. Protected KEEP surfaces were not edited.

## False-positives (do not delete)

Naive “def with no `from x import name`” greps miss `mod.fn` after `import mod`, `__getattr__` dispatch, `__all__` public APIs, and JS MCP tool names.

1. `unique_logic.evaluate_*_daily_mtm` — `dispatch.evaluate_logic_daily_mtm` calls `event.fn` / `adaptive.fn`; Worker `daily_path` mirrors. KEEP.
2. `event._ymd` / `_last_print_before` — used as `event._ymd` from filters/CS. KEEP.
3. `jquants.catalog.path_of`, `matrix.list_checks` / `get_check` / `premium_core_datasets` — `catalog.path_of` / `matrix.list_checks`; tests hit them. KEEP.
4. `jquants.bulk` (`bulk_path_for`, `prefers_bulk`) and `jsda.adapters.adapter_for` — HOLD modules (B1-c). KEEP.
5. `inventory.endpoint_status` / `projection_status` — MCP `domain.js` tools. KEEP Worker mirrors.
6. `freezes.freeze_flags` — unused caller, public fail-closed snapshot. KEEP.
7. `eval_registry.d1_upsert_sql` — unwired Python twin of `0006_research_eval_jobs.sql`. KEEP (same class as bulk URL SoT).
8. `normalize_corporate_bond_transactions` — JSDA 社債 mapping, no importer; not a husk. KEEP.
9. `inventory_all_governed_datasets` / `backfill_status_rows` — `__all__` 26-dataset ops API; scripts use a different `backfill_status`. KEEP.
10. `worker_body_missing()` — function unused; flag string is live (`CANDIDATE_POLICY`, `eval_summary`). KEEP gate.
11. `cells_candidate_counts` — another lane deletes it. Not touched.
12. `parse_catalog_yaml` / `combo_row_from_yaml` / `UNIQUE22_PARK_REASONS` / `run_occupancy_track` / `baseline_catalog` / `cost_models` / `options_225` / `paper_runtime.execution` / CLI `__main__` stubs — protected KEEP.

Also kept: `run_class_hyp_multi_year_eval` (documented public entry), `default_na_scenario_bundle`, `shortcut_dataset`, `features.registry.ids`, `compute_*_from_feature_observations` (`__all__` observation-join API, no callers). Zero production **modules** deleted (prior unused-module audit).
