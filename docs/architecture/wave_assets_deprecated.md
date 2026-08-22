# Wave runners and proof scorecards — deleted

**Status:** live policy (2026-08-21)  
**ADR:** [`adr_research_recording.md`](./adr_research_recording.md)

Existing `docs/proof/` files are **historical evidence**, not live scores and
not operational GO. Query R2 + D1 for eval. Do not add new wave scorecards;
do not treat the warehouse as residual SoT.

**Do not add new** `scripts/run_w*.py` or `docs/proof/w08*_wNN_*.md` scorecards.
Evaluators live in `packages/product/research/unique_logic/` under **functional
names** (not wave numbers). New research: `research.daily_path_eval` /
`research.cf_mass_eval_job` / `research.eval_registry` and
`specs/research_logics/`.

## unique_logic module names

| Old wave file | Functional module |
|---------------|-------------------|
| `w104.py` | `event.py` |
| `w105.py` | `event_filters.py` |
| `w106.py` | `event_sides.py` |
| `w106b.py` | `cross_section.py` |
| `w107b.py` | `cs_overlays.py` |
| `w107c.py` | `adaptive.py` |
| `legacy.py` | **deleted** — factory imports the modules above |

## Deleted run_w

All `scripts/run_w*.py` are gone. Replacement:
`python -m research.unique_logic` + `research.daily_path_eval`.

## Deleted proof scorecards

Unreferenced W91–W107 wave scorecards under `docs/proof/w0818*` / `w0819*` /
`w0820*` (73 files). Scores are R2 + D1.

**Kept** (code/contract citations):

- `w0819b_w99_sticky_daily_dd_20260819.md`
- `w0819c_w100_daily_path_dd_gate_20260819.md`
- older checklist / cost / defer proofs still named from packages

Guard: `tests/test_wave_script_freeze.py` (`ALLOWED_RUN_W` empty).
