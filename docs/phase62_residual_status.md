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
Candidate pool (code: `CANDIDATE_POLICY`) excludes path_broken / path_collapsed / always_on / near_empty / data_requirement_unmet / near_duplicate / always_on_cs_sticky / worker_isolate_limit / worker_body_missing / unique22_occupancy_mismatch.
Latest empirical jobs (ids only). Two eval tracks — do not narrate from one print:
- **mid_n_explore** (ADV 80): `eval-cf-dp-mid80-20260822a`, `eval-cf-dp-mid80-sleeves-20260822a`, `eval-cf-dp-baskets-mid80-sleeves-20260822a`, `eval-cf-dp-both-sleeves-20260822c-mid_n_explore`, `eval-cf-dp-mid80-plus4-20260822e`, `eval-cf-dp-mid80-plus28-20260822h`, `eval-cf-dp-mid80-adopt3-20260822i`, `eval-cf-dp-mid80-adopt3j-20260822j`, `eval-cf-dp-mid80-plus32-20260822m`, `eval-cf-dp-both-sleeves-20260822m-mid_n_explore`, `eval-cf-dp-mid80-adopt3n-20260822n`, `eval-cf-dp-both-sleeves-20260822p-mid_n_explore`, `eval-cf-dp-mid80-adopt1q-20260822q`, `eval-cf-dp-mid80-adopt1r-20260822r`, `eval-cf-dp-mid80-plus33div-20260823a`, `eval-cf-dp-both-sleeves-20260823a-mid_n_explore`
- **liq_large** (ADV 100): `eval-cf-dp-liq100-20260822b`, `eval-cf-dp-liq100-cross-20260822a`, `eval-cf-dp-liq100-sleeves-20260822a`, `eval-cf-dp-baskets-liq100-sleeves-20260822a`, `eval-cf-dp-both-sleeves-20260822c-liq_large`, `eval-cf-dp-liq100-new22-20260822c`, `eval-cf-dp-liq100-plus4-20260822d`, `eval-cf-dp-liq100-plus28-20260822h`, `eval-cf-dp-liq100-adopt3-20260822i`, `eval-cf-dp-liq100-adopt3j-20260822j`, `eval-cf-dp-liq100-plus32-20260822m`, `eval-cf-dp-both-sleeves-20260822m-liq_large`, `eval-cf-dp-liq100-adopt3n-20260822n`, `eval-cf-dp-both-sleeves-20260822p-liq_large`, `eval-cf-dp-liq100-adopt1q-20260822q`, `eval-cf-dp-liq100-adopt1r-20260822r`, `eval-cf-dp-liq100-plus33div-20260823a`, `eval-cf-dp-both-sleeves-20260823a-liq_large` (head-N contrast `eval-cf-dp-univ100-20260822a` / `eval-cf-dp-baskets100-20260822a`)
Both-track packs include `research/eval/job=eval-cf-dp-both-sleeves-20260823a/both_track.json` (diversity reblend; `n_logic_ok`). Inventory bias `research/eval/job=eval-inventory-bias-20260823a/inventory_bias.json`. Cost ON/OFF `research/eval/job=eval-cf-dp-cost-onoff-20260822c/cost_verify.json`. Cost short/high-turnover `research/eval/job=eval-cf-dp-cost-shortturn-20260822h/cost_verify.json`. Universe rule `adv_desc_skip_missing_bars_and_fins` (head-N forbidden). Worker `research-mass-eval/v30-propose-70b` (`@cf/meta/llama-3.3-70b-instruct-fp8-fast` then 8B CF-internal; LLM failure is `ok:false`/`llm_failed` + `llm_fallback_reason`, not stub `ok:true`). Head-N forbidden. GO deferred. countable requires catalog+Worker body. unique-22: 5 lift / 17 park. `CHEAP_PB_UNIFIED=false`. Latest propose: `eval-cf-propose-llm-20260823a`/`b` `n_adoptable=0` (`llm_failed`, not adopted). plus33 diversity jobs `eval-cf-dp-liq100-plus33div-20260823a` / `eval-cf-dp-mid80-plus33div-20260823a`. Mechanical baskets reblended off cheap_pb/afterclose primaries. unique22 park 17 unchanged. Dead-code this turn: removed Worker `PROPOSE_STUB_TEMPLATES` / `stubProposals` from `propose_thesis.ts` (stub no longer fills `ok:true`). Not deleted: `cost_models.py` / `options_225_vol_series.py` / `daily_path.ts` leftover / factory `generation_enabled=False`. 70B did not yield parseable rows on this account path (fallback 8B `parse_empty`); stay CF-internal.
