# Phase 6.2 / 6.3 residual status

**Live residual SoT** (agents: prefer this file over any `phase62*_status` / final_report).  
**Live verified:** 2026-08-12 (A3 COMPLETE **482**; Track A execute raw **1488→1889** Δ+401; bars `observed_start` **2008-05-01**; Phase7 OFF)  
**Proof:** `docs/proof/raw_throughput_POST_AEXEC_20260812.md`, `docs/proof/raw_throughput_POST_AEXEC_20260812T143446Z.md`, `docs/proof/bars_history_observed_start_20260812.md`, `docs/proof/complete_plus23_parallel_receipts_20260812.md`, `docs/proof/complete_plus1_bars_202608_20260812.md`, `docs/proof/track_a_dryrun_20260812.md`  
**Repo tip:** `69a0bd2` — COMPLETE **482** / raw **1889** / bars observed **2008-05-01** / Phase7 **OFF**

## Live snapshot

| Item | Value |
|------|--------|
| Dataset COMPLETE | **2** — `markets_calendar` (224/224 segs), `jsda_tokyo_repo_rates` (1/1) |
| Segment COMPLETE total | **482** (local == remote; A3 window 408→479→481→**482**; see plus23 / plus3-struct-hint / plus1-bars proofs) |
| calendar segments | **224 COMPLETE / 0 PARTIAL** |
| JSDA OTC COMPLETE segs | **5** — `2026-08-06`, `2026-08-07`, `2026-08-10`, `2026-08-12`, `2026-08-13` (dataset still PARTIAL) |
| JSDA corporate COMPLETE segs | **1** — year `2026` (dataset still PARTIAL) |
| A3 sealed (partial datasets) | `markets_short_ratio` 32, `markets_breakdown` 32, `markets_margin_alert` 18, `equities_investor_types` 7, `equities_earnings_calendar` 1, `fins_details` 2, `equities_bars_daily` 12 (all still dataset PARTIAL except calendar/tokyo) |
| Remote `raw_retention_manifests` | **1889** (D1 RO POST_AEXEC final; PRE_AEXEC **1488** → Δ **+401**; local research mirror still **0**) |
| Track A execute jobs | equities: month pass **20** + week **40** + 5d subrange **57/60**; indices month pass **48/48**; margin latest **pass** (`2026-08`, rowsInserted 4259). Failures recorded (sub pre-2006-08-12 / CF 503) and continued. **Worker pass ≠ COMPLETE** |
| `equities_bars_daily` | dataset **PARTIAL**; COMPLETE segs **12**; `observed_start` **`2008-05-01`** → `observed_end` `2026-08-12`; remote raw manifests **478** (Δ +208 vs PRE); local row_count **803862** |
| `indices_bars_daily_topix` | dataset **PARTIAL**; remote raw manifests **355** (Δ +102); AEXEC month jobs **48 pass** (2008-01…2011-12) |
| `markets_margin_interest` | **STALE** (C8) still; sticky COMPLETE segs **14**; latest-only worker **pass** (not a COMPLETE seal); observed local `2024-01-12`→`2025-02-28` — DEFER (see p1 margin proof) |
| master | `scd2_event_sourcing` / D1 hot |
| projection | **FRESH** — `projgen-eb0412ea86f34c6ab51b5f312d3ebcbc` (fail-closed full publish after bars 2026-08 +1) |
| sticky COMPLETE | **fixed inventory status load** + demotion guard in `storage/coverage_ledger.py` |
| Full publish guard | `scripts/publish_ops_projection.py` fail-closed |
| Targeted freshness | `scripts/ops_reeval_freshness.py` (no segment rewrite) |
| Observed window re-eval | `scripts/ops_reeval_observed_window.py` (SUCCESS receipts raw_row_count>0; no segment rewrite / no COMPLETE claim) |
| Layout migration | **DONE** — libraries under `packages/{edge,data_plane,research_runtime,product}`; import leaf names unchanged |
| Track A (historical raw accel) | **EXECUTE DONE (this window)** — PRE raw **1488** → POST **1889** (Δ+401); equities ≥24 mo coverage + week/5d chunks; indices **48** mo pass; margin latest pass but still STALE; subscription floor **`2006-08-12`**; week-chunks CLI in `ddbf1e9` |
| Track B1 (LLM-friendly) | **landed** `7b09e1b` + residual/docs SoT passes; Batch Z still **DEFER** |
| Mass / READY / B0 | **NO-GO** |
| Phase 7 | **OFF / foundation only** — **must remain OFF**; no mass arming, no production READY, no Phase7 switch ON |

## DONE vs DEFER

| Area | Status |
|------|--------|
| Sticky COMPLETE + inventory status fix | **DONE** |
| Publish fail-closed guard | **DONE** |
| Honest segment COMPLETE path (raw + signed SUCCESS) | **DONE** (OTC 5; A3 +71/+3/+1; total COMPLETE **482**) |
| JSDA min COMPLETE (otc/corp/tokyo) | **DONE** (otc 5; corp/tokyo ≥1 each) |
| Physical layout → `packages/*` planes | **DONE** (Batches 0–E; import names leaf top-level) |
| Track A planner / throughput / execute | **DONE** (infra + live execute proof; raw Δ+401; further months still open) |
| Track B1 docs hub + plane import guards | **DONE** (`7b09e1b`; plane import tests green) |
| Track B residual live-sync + docs SoT banners | **DONE** (this pass; historical banners present) |
| bars `observed_start` receipt-plane union | **DONE** (code `22a9d56` + remote `2008-05-01`; proof `bars_observed_start_move_*`) |
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
- **Segment COMPLETE = 482** counts every COMPLETE segment across datasets (calendar 224 + master/topix/markets/JSDA/A3 seals, etc.).
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
