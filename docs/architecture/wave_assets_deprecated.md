# Wave runners and proof scorecards — deprecated (staged deletion)

**Status:** live policy (2026-08-21)  
**ADR:** [`adr_research_recording.md`](./adr_research_recording.md)

**Do not add new** `scripts/run_w*.py` or `docs/proof/w08*_wNN_*.md` scorecards.
New research goes through `research.daily_path_eval` /
`research.cf_mass_eval_job` / `research.eval_registry` and
`specs/research_logics/`.

Existing `docs/proof/w08*_wNN_*.md` stay until a later pass (no bulk delete
this batch). Residual history was **deleted**, not archived to Git markdown.

## Deleted this batch (importer-zero)

W90–W98 CF wrappers and unused deep-dives / family CLI with no packages or
test importers:

- `run_w90_llm_cf_mass_eval.py`
- `run_w90_llm_hyp_cf_eval.py`
- `run_w91_real_cf_mass_eval.py`
- `run_w92_options_vol_cf_eval.py`
- `run_w92_options_vol_cf_mass_eval.py`
- `run_w93_opt225_diff_windows.py`
- `run_w93_thicken_cf_panels.py`
- `run_w94_opt_skew_windows.py`
- `run_w94_thick_factor_windows.py`
- `run_w95_factor_failure_decomp.py`
- `run_w95_promising_reeval.py`
- `run_w95_shape_deepdive.py`
- `run_w95_shape_factor_decomp.py`
- `run_w96_hyps_and_defaults.py`
- `run_w97_survivor_deep_eval.py`
- `run_w98_xs_rank_ls_sticky_deep.py`
- `run_w98_xs_sticky_deepdive.py`
- `run_w101_hyps_dd_close.py`
- `run_w103_repo_gate_deepen.py`
- `run_w103_repo_short_cost.py`
- `run_w105_funding_surprise_deepdive.py`
- `run_w107_curve_steepen_deepdive.py`
- `run_w107_research_family_append.py`

Replacement: `python -m research.cf_mass_eval_job` (screen) and
`python -m research.unique_logic` / `research.daily_path_eval` (candidate-grade).

## Still referenced (kept)

| Path | Why kept |
|------|----------|
| `run_w99_sticky_daily_dd.py` | other remaining scripts import helpers |
| `run_w100_peer_daily_dd.py` | kernel + tests/scripts |
| `run_w102_event_rate_daily_dd.py` | unique_logic overnight/events |
| `run_w102_dispersion_quality.py` | family wrappers |
| `run_w103_dispersion_deepen.py` | family wrappers |
| `run_w104_new_hyps_daily_dd.py` | `unique_logic.legacy` + tests |
| `run_w105_new_hyps_daily_dd.py` | `unique_logic.legacy` + tests |
| `run_w105_research_family_register.py` | tests |
| `run_w106_funding_surprise_ls.py` | `unique_logic.legacy` + tests |
| `run_w106_new_hyps_daily_dd.py` | `unique_logic.legacy` + tests |
| `run_w106_research_family_append.py` | tests |
| `run_w107_new_hyps_daily_dd.py` | `unique_logic.legacy` |
| `run_w107_funding_surprise_adaptive.py` | `unique_logic.legacy` |

Factory dispatch uses `research.unique_logic.legacy` (not a direct
`scripts.run_w*` import in `mass_strategy_factory`).

## Next deletion candidates

Rewrite tests that import family wrappers / `run_w104`–`run_w107`, then extract
evaluators into `packages/product/research/unique_logic/` and delete the rest.

Guard: `tests/test_wave_script_freeze.py` (new files fail; deletions allowed;
residual must stay live flags only).
