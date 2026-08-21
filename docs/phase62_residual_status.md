# Phase 6.2 / 6.3 residual status

**Live residual SoT** (agents: prefer this file over any `phase62*_status` / final_report).

This file holds **live flags only**. Experiment scores and wave essays are
**not** stored here and are **not** restated in another Git markdown file.
Query Cloudflare: R2 `quant-structured/research/eval/job={id}/` and D1
`research_eval_jobs` / `research_eval_cells`. Candidate-grade eval is
`research.daily_path_eval`. See
[`architecture/adr_research_recording.md`](architecture/adr_research_recording.md).

Do **not** add `scripts/run_wNN_*.py` or `docs/proof/w08*_wNN_*.md` scorecards.

## Live coverage (remote SoT / quant-mcp)

| Flag | Value |
|------|-------|
| OTC dataset | `jsda_otc_bond_reference_prices` **PARTIAL** |
| OTC COMPLETE | **5852** |
| OTC PARTIAL | **2932** |
| required | 8784 |
| span | **2002-09-25…2026-08-20** |
| remaining official 2003 | **0** |
| remaining official 2002 | **36** |
| remaining official 2004 | **0** |
| projection | **FRESH** (`projgen-96b8bd434c4c4b21a2f8fad79bc182f7`) |
| COMPLETE datasets | **22** held |
| DEFER | **4** |

Coverage SoT is quant-mcp (`dataset_coverage` / `backfill_status`), not this
prose. Update the table after a published projection.

## Live gates (fail-closed)

| Flag | Value |
|------|-------|
| Mass | **NO-GO** |
| production READY | **未宣言** |
| Phase 7 | **OFF** |
| operational GO | **未宣言** |
| GO judgment | **deferred** |
| continuous paper | **UNARMED** |
| promote_as_main | **false** |
| human main | **not selected** |
| 3 default pins | **frozen** (not retuned) |
| `cross_section_hold_10` | hold=10 mom=5 **KEEP** |
| `cross_section_hold_10_mom3` | hold=10 mom=3 **PROMOTE** |
| `fundamentals_hold_10` | hold=10 mom=10 **KEEP** |
| invent COMPLETE / empty COMPLETE / fake densify | **forbidden** |
| period_net_DD-only pass | **forbidden** (`daily_path_DD` required) |

## Eval recording

| Plane | Path |
|-------|------|
| candidate-grade | `research.daily_path_eval` (`daily_path_mtm_after_cost/v1`) |
| CF screen | `research.cf_mass_eval_job` (period-net; incomplete vs checklist) |
| index | `research.eval_registry` → R2 + D1 |
| catalog | `specs/research_logics/` |

Do not paste cell scores into this file. Latest recorded job id belongs in D1.
