# Phase 6.2 / 6.3 residual status

> **Live residual SoT.** Feature HEAD `cf7da56c` vs `origin/main` `b5c326a`. Live MCP: Projection **STALE**, READY **null**, B0 **UNKNOWN**, `applied_cursor` **null**. Mass **NO-GO**. Phase 7 **OFF**. Do not treat 22 COMPLETE as live V3.

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
| projection | **STALE** (`projgen-ef18b4f86ee946048161d25e2a30a2a8`; last generated 2026-08-21) |
| COMPLETE datasets | **22** held (last-known projected ledger under STALE projection, not a current FRESH seal) |
| DEFER | **4** |
| PARTIAL (4, not invented COMPLETE) | `equities_earnings_calendar` · `equities_bars_daily_am` (tip-wait) · `equities_master` · OTC |
| `jsda_tokyo_repo_rates` | **COMPLETE** (1/1 · 2012-10-29…2026-08-14 · research eval uses local sqlite history; D1 is hot tip only) |

Coverage SoT is quant-mcp (`dataset_coverage` / `backfill_status`), not this
prose. Update the table after a published projection.

## Live gates (fail-closed)

| Flag | Value |
|------|-------|
| Mass | **NO-GO** (Worker `/v1/mass-eval` `/v1/daily-path` `/v1/propose-thesis` 403 `capability_missing` until verified readiness) |
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
| catalog | `specs/research_catalog/` (compiled, n=2254, `yaml_still_present: false`); `specs/research_logics/` YAML removed at `5c9b962` |

Completion of a research turn requires an R2 **daily_path** job, not local JSON.
Do not paste cell scores into this file. Latest recorded job id belongs in D1.
Candidate pool (code: `CANDIDATE_POLICY`) excludes path_broken / path_collapsed / always_on / always_on_parked / near_empty / near_empty_parked / data_requirement_unmet / near_duplicate / always_on_cs_sticky / worker_isolate_limit / worker_body_missing / unique22_occupancy_mismatch.
Latest empirical jobs (ids only; older ids stay on R2/D1). Two tracks — do not narrate from one print:
- **mid_n_explore** (ADV 80): `eval-cf-dp-basket-alts-20260824ds-mid_n_explore`
- **liq_large** (ADV 100): `eval-cf-dp-basket-alts-20260824ds-liq_large`
Universe `adv_desc_skip_missing_bars_and_fins` (head-N forbidden). Worker `research-mass-eval/v142-63-failclosed` deployed (`fb45befa-13b7-440e-a51b-fe9828f27036` wrangler current this turn; DiscTime `00:00:00` is not a known clock; daily-path writes `evaluation-ir/v1`; period-net orchestration in `eval_orchestrate.ts`). Live: `/health` `{ok,service,version}` only; `/v1/daily-path` and `/v1/mass-eval` **401** without token. Auth fail-closed if `MASS_EVAL_TOKEN` unbound; eval/propose 403 without verified readiness; no direct `env.AI`; R2 create-if-absent. AI Gateway deployed (`a3d26b40-7a78-46df-bb76-7d6381267887` wrangler current this turn). Ops MCP deployed (`cfcddfc1-a5bb-4d83-a8f3-9871c121f080` wrangler current this turn). Candidate grade false unless expected cells all complete (`research.candidate_policy`); daily-path job artifacts carry `evaluation-ir/v1` (encode calls that grade). MCP `sync_status` applies feed pin to `applied_cursor` (null pin still never CURRENT). Coverage without an active projection generation is UNKNOWN (last-known-good is not current COMPLETE). Baskets keep `eval-cf-dp-both-sleeves-20260824df`; reconstitution **apply false** (human pending: `basket_theme_fund`, `basket_event_fund`; do not auto-choose drop_parents vs drop_children). Usable `eval-usable-inventory-20260824ev` n_usable 1880. `CATALOG_AND_PLUS_N_STOPPED`. unique22 park 5/17 leftover occupancy (not YAML). Propose 0-adopt. B0 **UNKNOWN**. READY **null**. Projection **STALE** (`refresh_success=false`; last-known-good is not FRESH). Sync `applied_cursor=null` → `EXPORT_CURRENT_APPLY_UNPINNED` / `LAGGING_APPLY_UNPINNED`, never CURRENT. Ops projector can emit `ops_applied_pins` from local `sync_change_state`; CURRENT stays impossible while the pin is NULL (0007 schema, not applied remote). AM SLA `PROJECTION_STALE`. Raw AM 0-row COMPLETE = `EXPECTED_EMPTY_WITH_EVIDENCE` (not Coverage COMPLETE). JSDA inventory locators live. Family reclass (`research.catalog_family`, n=2254): event 1350 · surprise_xs 891 · other 12 · CS 1. **flow_family true = 0**; flow **gate** but not flow family = **848**. Gate ≠ family. HOLD: cost_models / options_225 / daily_path leftover occupancy / unique22 park leftover occupancy (`UNIQUE22_PARK_REASONS` / `daily_path.ts`; YAML gone, `yaml_still_present: false`). `research.eval_flags` / `occupancy_guards` / `research_capabilities` / `catalog_compiler`.
