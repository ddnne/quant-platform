# Phase 6.2 / 6.3 residual status

**Live residual SoT** (agents: prefer this file over any `phase62*_status` / final_report).  
**Live verified:** 2026-08-12 (OTC COMPLETE +3 publish → segment COMPLETE **404**)  
**Proof:** `docs/proof/complete_plus3_otc_20260812.md`, `docs/proof/track_a_dryrun_20260812.md`  
**Repo tip (Track A infra):** `8638936` — historical raw acceleration planner + throughput report

## Live snapshot

| Item | Value |
|------|--------|
| Dataset COMPLETE | **2** — `markets_calendar` (224/224 segs), `jsda_tokyo_repo_rates` (1/1) |
| Segment COMPLETE total | **404** (+3 OTC on 2026-08-12; see plus3 proof) |
| calendar segments | **224 COMPLETE / 0 PARTIAL** |
| JSDA OTC COMPLETE segs | **5** — `2026-08-06`, `2026-08-07`, `2026-08-10`, `2026-08-12`, `2026-08-13` (dataset still PARTIAL) |
| JSDA corporate COMPLETE segs | **1** — year `2026` (dataset still PARTIAL) |
| master | `scd2_event_sourcing` / D1 hot |
| projection | FRESH (fail-closed full publish after +3) |
| sticky COMPLETE | **fixed inventory status load** + demotion guard in `storage/coverage_ledger.py` |
| Full publish guard | `scripts/publish_ops_projection.py` fail-closed |
| Targeted freshness | `scripts/ops_reeval_freshness.py` (no segment rewrite) |
| Layout migration | **DONE** — libraries under `packages/{edge,data_plane,research_runtime,product}`; import leaf names unchanged |
| Track A (historical raw accel) | **infra landed** on tip `8638936` (dry-run proof only; no COMPLETE claim from Track A) |
| Mass / READY / B0 | **NO-GO** |
| Phase 7 | **OFF / foundation only** |

## DONE vs DEFER

| Area | Status |
|------|--------|
| Sticky COMPLETE + inventory status fix | **DONE** |
| Publish fail-closed guard | **DONE** |
| Honest segment COMPLETE path (raw + signed SUCCESS) | **DONE** (OTC now 5 segs; total COMPLETE 404) |
| JSDA min COMPLETE (otc/corp/tokyo) | **DONE** (otc 5; corp/tokyo ≥1 each) |
| Physical layout → `packages/*` planes | **DONE** (Batches 0–E; import names leaf top-level) |
| Track A planner / throughput report | **DONE** (infra + dry-run proof; execute/COMPLETE separate) |
| Extra COMPLETE without raw | **DEFER** |
| OTC full archive COMPLETE | **DEFER** (thousands of trading days remain) |
| Mass / READY / Phase7 switch ON | **NO-GO** |
| applied_cursor materialization | **DEFER** |
| Batch Z (`quant_platform.*` imports) | **DEFER** (ADR Accepted; out of B1) |

## Note on COMPLETE counts
- **Dataset-level COMPLETE = 2** means only two datasets have *all* required segments COMPLETE.
- **Segment COMPLETE = 404** counts every COMPLETE segment across datasets (calendar 224, master, JSDA progress, etc.).
- Next honest +1 requires additional **real raw** (R2 or official fetch); do not invent.

## Agent pointers
- LLM nav map: [`docs/architecture/llm_nav_map.md`](architecture/llm_nav_map.md)
- Layout SoT: [`docs/architecture/repo_layout_migration.md`](architecture/repo_layout_migration.md)
- LLM-friendly refactor ADR: [`docs/architecture/adr_llm_friendly_refactor.md`](architecture/adr_llm_friendly_refactor.md) (**Accepted**)
