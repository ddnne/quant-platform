# Wave runners and proof scorecards — deprecated (not deleted)

**Status:** live policy (2026-08-21)  
**ADR:** [`adr_research_recording.md`](./adr_research_recording.md)

Existing `scripts/run_w*.py` and `docs/proof/w08*_wNN_*.md` stay until staged
deletion. **Do not add new ones.** New research goes through
`research.daily_path_eval` / `research.cf_mass_eval_job` /
`research.eval_registry`.

## What is deprecated

| Path | Role now | Replacement |
|------|----------|-------------|
| `scripts/run_w90_*.py` … `run_w98_*.py` | CF mass-eval wrappers | `python -m research.cf_mass_eval_job` |
| `scripts/run_w99_sticky_daily_dd.py` | shim over `daily_path_eval` | `research.daily_path_eval` |
| `scripts/run_w100_*.py` … `run_w107_*.py` | unique_logic + family + deepdive copies | catalog YAML + `evaluate_*` + `daily_path_eval` |
| `docs/proof/w08*_wNN_*.md` scorecards | human restatement of glm-logs | R2 `research/eval/job=` + D1 `research_eval_*` |
| `docs/phase62_residual_status.md` long experiment logs | historical; do not append more | live flags only + registry |

## Staged deletion candidates (do not delete this wave)

Safe to delete **after** importers and tests no longer reference them:

1. Duplicate: `run_w92_options_vol_cf_eval.py` **or** `run_w92_options_vol_cf_mass_eval.py` (keep one).
2. Family wrappers: `run_w105_research_family_register.py`, `run_w106_research_family_append.py`, `run_w107_research_family_append.py` (factory functions already exist).
3. CF wrappers W90–W91 once `cf_mass_eval_job` CLI flags cover job_id/logics/windows.
4. `run_w107_*` after evaluators live in `packages/product/research/unique_logic/`.

Keep until B2 extract finishes:

- `run_w99_sticky_daily_dd.py` (other scripts import it)
- `run_w100_peer_daily_dd.py`, `run_w104_new_hyps_daily_dd.py` (kernel + events)
- `run_w106_new_hyps_daily_dd.py`, `run_w106_funding_surprise_ls.py`

Tests that import `scripts/run_w10x_*` (`tests/test_w104_*.py` … `test_w106_*.py`) must be rewritten or pointed at `unique_logic` before those scripts move.

## Importer snapshot (2026-08-21)

- `mass_strategy_factory._eval_research_unique_on_panel` still imports `run_w104`–`run_w107` (transitional).
- Wave scripts import `run_w99` / `run_w100` as libraries.
- Guard: `tests/test_wave_script_freeze.py` (new files fail; deletions allowed).
