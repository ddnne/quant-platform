# Wave runners and proof scorecards — deleted / remaining contract proofs

**Status:** live policy (2026-08-21)  
**ADR:** [`adr_research_recording.md`](./adr_research_recording.md)

**Do not add new** `scripts/run_w*.py` or `docs/proof/w08*_wNN_*.md` scorecards.
Evaluators live in `packages/product/research/unique_logic/`.
New research: `research.daily_path_eval` / `research.cf_mass_eval_job` /
`research.eval_registry` and `specs/research_logics/`.

## Deleted run_w (this batch — unique_logic extract)

After moving evaluate functions into `research.unique_logic.w104` …
`w107c` and rewriting tests, **all remaining** `scripts/run_w*.py` had no
packages/tests importers and were deleted:

- `run_w99_sticky_daily_dd.py`
- `run_w100_peer_daily_dd.py`
- `run_w102_dispersion_quality.py`
- `run_w102_event_rate_daily_dd.py`
- `run_w103_dispersion_deepen.py`
- `run_w104_new_hyps_daily_dd.py`
- `run_w105_new_hyps_daily_dd.py`
- `run_w105_research_family_register.py`
- `run_w106_funding_surprise_ls.py`
- `run_w106_new_hyps_daily_dd.py`
- `run_w106_research_family_append.py`
- `run_w107_funding_surprise_adaptive.py`
- `run_w107_new_hyps_daily_dd.py`

Prior importer-zero deletion (2026-08-21 earlier): W90–W98 wrappers plus
`run_w101_*`, `run_w103_repo_*`, `run_w105_funding_surprise_deepdive.py`,
`run_w107_curve_steepen_deepdive.py`, `run_w107_research_family_append.py`.

Replacement: `python -m research.unique_logic` + `research.daily_path_eval`.

## Deleted proof scorecards (this batch)

Unreferenced W91–W107 wave scorecards under `docs/proof/w0818*` / `w0819*` /
`w0820*` (73 files). Scores are R2 + D1.

**Kept** (code/contract citations):

- `w0819b_w99_sticky_daily_dd_20260819.md`
- `w0819c_w100_daily_path_dd_gate_20260819.md`
- older checklist / cost / defer proofs still named from packages

Guard: `tests/test_wave_script_freeze.py` (`ALLOWED_RUN_W` empty).
