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
Candidate pool (code: `CANDIDATE_POLICY`) excludes path_broken / path_collapsed / always_on / always_on_parked / near_empty / near_empty_parked / data_requirement_unmet / near_duplicate / always_on_cs_sticky / worker_isolate_limit / worker_body_missing / unique22_occupancy_mismatch.
Latest empirical jobs (ids only; older ids stay on R2/D1). Two tracks — do not narrate from one print:
- **mid_n_explore** (ADV 80): `eval-cf-dp-basket-alts-20260824ds-mid_n_explore`
- **liq_large** (ADV 100): `eval-cf-dp-basket-alts-20260824ds-liq_large`
Universe `adv_desc_skip_missing_bars_and_fins` (head-N forbidden). Worker `research-mass-eval/v141-24ev-flow50` (`caefdebd-1ad2-4df6-9e5c-1ad6e4a47b4f`). Baskets keep `eval-cf-dp-both-sleeves-20260824df`; alts apply false. Nested detect + reconstitution_options; **apply false** (`RECONSTITUTION_APPLY` false; human pending fund/event_fund; no auto drop_parents/children). Historical sleeves are not `candidate` in basket-trend summary. Cost/risk `eval-usable-cost-risk-20260824ev` not_a_pass. Usable `eval-usable-inventory-20260824ev` n_usable 1880; series `eval-usable-series-20260824ev`; occupancy maps `eval-occupancy-maps-20260824ev`; occupancy audit `eval-occupancy-audit-20260824ev-flow50` flow-thin +50 material thin 0 near_empty 0 (not 3-AND). Thin-series `eval-thin-series-20260824ev` flow filled; vol leftover known-thin; rate is map-count only (not a fill mandate). `CATALOG_AND_PLUS_N_STOPPED`. Drift `eval-occupancy-drift-20260824ev` 0 silent-unpark. unique22 park `eval-unique22-park-20260824ev` 5/17. event 3-AND +N **stopped**. Combo jsonl `eval-combo-jsonl-20260824ev` yaml_remains_sot. Flow 5th stitch blend `eval-flow-5th-blend-20260824ek` thinner; keep current. Reconstitution `eval-reconstitution-plan-20260824ev` apply false. Series-sleeve `eval-series-sleeve-20260824ev`. Propose `eval-cf-propose-20260824ev` llm_failed 0-adopt (not soup). Wave one-call `research.occupancy_audit.run_eval_wave`. Live flags `research.eval_flags`. GO deferred. HOLD: cost_models / options_225 / daily_path leftover / unique22 park YAML / CLI `__main__.py` / `ingestion.jsda.adapters` / `jquants/bulk.py`. Deleted `scripts/parse_jsda_from_r2_mirror.py` · `tests/test_research_offline_bar_eval.py` · `tests/test_http_proxy_verify.py`. `research.cost_defaults` is the shared 10bp literal.
