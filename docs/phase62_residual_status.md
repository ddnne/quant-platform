# Phase 6.2 / 6.3 residual status

**Live residual SoT** (agents: prefer this file over any `phase62*_status` / final_report).  
**Live verified:** 2026-08-12 (A3 COMPLETE +71 → segment COMPLETE **479**; Track B residual live-sync)  
**Proof:** `docs/proof/complete_plus23_parallel_receipts_20260812.md`, `docs/proof/complete_plus3_otc_20260812.md`, `docs/proof/raw_throughput_POST_AEXEC_20260812T141214Z.md`, `docs/proof/track_a_dryrun_20260812.md`, `docs/proof/data_quality_scan_20260812.md`  
**Repo tip:** `7a5a74b` — Track B residual live-sync + docs SoT (COMPLETE 479 / raw 1696 / Phase7 OFF)

## Live snapshot

| Item | Value |
|------|--------|
| Dataset COMPLETE | **2** — `markets_calendar` (224/224 segs), `jsda_tokyo_repo_rates` (1/1) |
| Segment COMPLETE total | **479** (local == remote; A3 +71 seal from local 408 → 479; see plus23 proof) |
| calendar segments | **224 COMPLETE / 0 PARTIAL** |
| JSDA OTC COMPLETE segs | **5** — `2026-08-06`, `2026-08-07`, `2026-08-10`, `2026-08-12`, `2026-08-13` (dataset still PARTIAL) |
| JSDA corporate COMPLETE segs | **1** — year `2026` (dataset still PARTIAL) |
| A3 sealed (partial datasets) | `markets_short_ratio` 32, `markets_breakdown` 32, `markets_margin_alert` 18, `equities_investor_types` 7 (all still dataset PARTIAL) |
| Remote `raw_retention_manifests` | **1696** (D1 `quant-ingest` RO count 2026-08-12; POST_AEXEC was 1593; local research mirror still **0**) |
| `equities_bars_daily` | dataset **PARTIAL**; COMPLETE segs **12**; `observed_start` **`2024-01-04T15:00:00+09:00`** → `observed_end` `2026-08-10T15:30:00+09:00`; row_count **803862** (local==remote coverage) |
| `markets_margin_interest` | **STALE** (C8); sticky COMPLETE segs **14**; observed `2024-01-12`→`2025-02-28` — DEFER (see p1 margin proof) |
| master | `scd2_event_sourcing` / D1 hot |
| projection | **FRESH** — `projgen-0ca2910127a84d0fa3b7b8d770736da9` (fail-closed full publish after A3) |
| sticky COMPLETE | **fixed inventory status load** + demotion guard in `storage/coverage_ledger.py` |
| Full publish guard | `scripts/publish_ops_projection.py` fail-closed |
| Targeted freshness | `scripts/ops_reeval_freshness.py` (no segment rewrite) |
| Layout migration | **DONE** — libraries under `packages/{edge,data_plane,research_runtime,product}`; import leaf names unchanged |
| Track A (historical raw accel) | **infra + execute + A3 seal** — planner `8638936`; POST_AEXEC raw delta proof; A3 parallel receipts → COMPLETE **479**; subscription floor **`2006-08-12`**; no dual backfill start |
| Track B1 (LLM-friendly) | **landed** `7b09e1b` + residual/docs SoT pass (this commit); Batch Z still **DEFER** |
| Mass / READY / B0 | **NO-GO** |
| Phase 7 | **OFF / foundation only** — **must remain OFF**; no mass arming, no production READY, no Phase7 switch ON |

## DONE vs DEFER

| Area | Status |
|------|--------|
| Sticky COMPLETE + inventory status fix | **DONE** |
| Publish fail-closed guard | **DONE** |
| Honest segment COMPLETE path (raw + signed SUCCESS) | **DONE** (OTC 5 segs; A3 +71; total COMPLETE **479**) |
| JSDA min COMPLETE (otc/corp/tokyo) | **DONE** (otc 5; corp/tokyo ≥1 each) |
| Physical layout → `packages/*` planes | **DONE** (Batches 0–E; import names leaf top-level) |
| Track A planner / throughput / A3 seal | **DONE** (infra + execute proof + parallel receipts; further raw months separate) |
| Track B1 docs hub + plane import guards | **DONE** (`7b09e1b`) |
| Track B residual live-sync + docs SoT banners | **DONE** (this commit) |
| Extra COMPLETE without raw | **DEFER** / **Forbidden** |
| OTC full archive COMPLETE | **DEFER** (thousands of trading days remain) |
| `markets_margin_interest` STALE repair | **DEFER** (P1-1 proof) |
| JSDA corporate years 2015–2025 | **DEFER** |
| Mass / READY / Phase7 switch ON | **NO-GO** (Phase7 **OFF** maintained) |
| applied_cursor materialization | **DEFER** |
| Batch Z (`quant_platform.*` imports) | **DEFER** (ADR Accepted; out of B1) |
| B1-c full dead-code purge | **partial** — inventory only this pass (see llm_nav §11); no unsafe deletes |
| B1-d / B1-e | **pending** |

## Note on COMPLETE counts
- **Dataset-level COMPLETE = 2** means only two datasets have *all* required segments COMPLETE.
- **Segment COMPLETE = 479** counts every COMPLETE segment across datasets (calendar 224 + master/topix/markets/JSDA/A3 seals, etc.).
- Next honest +1 requires additional **real raw** (R2 or official fetch) + structured + signed SUCCESS; do not invent.
- **Do not** start `cf_premium_backfill` / Mass / READY from residual prose alone.

## Phase 7 OFF (explicit)
Phase 7 remains **foundation-only / OFF**. Stubs under `knowledge/`, `selection/`, `gateway/`, `research/` are scaffolding.  
Fail-closed surface: `agents/mass_research.py`, `research/readiness.py`, `selection/budget_ledger.py`.  
Ops note: [`docs/operations/phase7_foundation_off.md`](operations/phase7_foundation_off.md).  
Architecture: [`docs/architecture/phase7_fail_closed.md`](architecture/phase7_fail_closed.md).

## Agent pointers
- LLM nav map: [`docs/architecture/llm_nav_map.md`](architecture/llm_nav_map.md)
- Layout SoT: [`docs/architecture/repo_layout_migration.md`](architecture/repo_layout_migration.md)
- LLM-friendly refactor ADR: [`docs/architecture/adr_llm_friendly_refactor.md`](architecture/adr_llm_friendly_refactor.md) (**Accepted**)
