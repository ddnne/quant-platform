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
| OTC COMPLETE | **5886** |
| OTC PARTIAL | **2898** |
| required | 8784 |
| span | **2002-08-06…2026-08-20** |
| remaining official 2003 | **0** |
| remaining official 2002 | **2** PARSE_ZERO (`2002-08-02`, `2002-08-05`; not invented COMPLETE) |
| remaining official 2004 | **0** |
| projection | **FRESH** (`projgen-ef18b4f86ee946048161d25e2a30a2a8`) |
| COMPLETE datasets | **22** held |
| DEFER | **4** |
| PARTIAL (4, not invented COMPLETE) | `equities_earnings_calendar` · `equities_bars_daily_am` (tip-wait) · `equities_master` · OTC |
| `jsda_tokyo_repo_rates` | **COMPLETE** (1/1 · 2012-10-29…2026-08-14 · research eval uses local sqlite history; D1 is hot tip only) |

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
| **candidate SoT** | `POST /v1/daily-path` (`daily_path_mtm_after_cost/v1`) → R2 `research/eval/job={id}/` |
| CF period-net | bar-native **auxiliary** only; unique event/CS → `path_collapsed`; `n_survivors` is **not** a pass |
| index | `research.eval_registry` → R2 + D1 |
| catalog | `specs/research_logics/` |

Completion of a research turn requires an R2 **daily_path** job, not local JSON.
Do not paste cell scores into this file. Latest recorded job id belongs in D1.
Candidate pool (code: `CANDIDATE_POLICY`) excludes path_broken / path_collapsed / always_on / near_empty / data_requirement_unmet / near_duplicate / always_on_cs_sticky / worker_isolate_limit / worker_body_missing.
Latest empirical jobs (ids only). Two eval tracks — do not narrate from one print:
- **mid_n_explore** (ADV 80): `eval-cf-dp-mid80-20260822a`, `eval-cf-dp-mid80-sleeves-20260822a`, `eval-cf-dp-baskets-mid80-sleeves-20260822a`, `eval-cf-dp-both-sleeves-20260822c-mid_n_explore`
- **liq_large** (ADV 100): `eval-cf-dp-liq100-20260822b`, `eval-cf-dp-liq100-cross-20260822a`, `eval-cf-dp-liq100-sleeves-20260822a`, `eval-cf-dp-baskets-liq100-sleeves-20260822a`, `eval-cf-dp-both-sleeves-20260822c-liq_large`, `eval-cf-dp-liq100-new22-20260822c` (head-N contrast `eval-cf-dp-univ100-20260822a` / `eval-cf-dp-baskets100-20260822a`)
Both-track pack `research/eval/job=eval-cf-dp-both-sleeves-20260822c/both_track.json`. Cost ON/OFF `research/eval/job=eval-cf-dp-cost-onoff-20260822c/cost_verify.json`. Composition compare `research/eval/sleeve_stability/headn100_vs_liq100b.json`. Triad `research/eval/sleeve_stability/univ50_vs_univ80_vs_univ100.json`. Universe rule `adv_desc_skip_missing_bars_and_fins` (head-N forbidden on both tracks). Isolate park set is empty after `csFundSnaps` hoist + `eval-cf-dp-cs-hoist-20260822a` (N=100 complete). Linearized: cluster three + those three CS. Worker `research-mass-eval/v22-thesis-gates`. Head-N list slice forbidden on both tracks. GO deferred. Thesis count requires catalog + Worker body (`countable_thesis_ids`). CF propose is `POST /v1/propose-thesis` (stub, no auto-inject).
