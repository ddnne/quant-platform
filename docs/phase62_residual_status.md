# Phase 6.2 residual status (honest)

**HEAD**: `9df84a6`  
**Date**: 2026-08-11  
**Track**: GLM-5.2 + orchestrated land

> **Code-complete; live still OPEN.** No `PHASE62_FULL_DONE`. Phase 7 mass research **NO-GO**.

## Code-complete ✅
Inventory 31, ops projection, host cron, receipt emit, rebuild_from_raw, bars date fix,
READY coherence in publish, Phase 7 stubs, offline pytest green.

## Live operational progress

| Item | Status |
|------|--------|
| Coverage COMPLETE (all governed) | **Open** — `markets_calendar` has **11 COMPLETE** months; 213 still PARTIAL (history gap 2008–2016 + remaining months) |
| Production READY ≥1 | **Open** — coherence blocks until all governed COMPLETE |
| Full multi-year JQ/JSDA backfill | **In progress** — calendar 2008–2016 + 2017–2026 jobs running; master/premiums long jobs |
| Cron auto-projection | **Host path ready** (`scripts/cron_publish_ops.sh`); edge not claimed |

## Human-only
- Wall-clock for full premium history
- JSDA site availability
- Live capital / broker

## Notes
- Proxy: `ingestion-secrets` (not premium).
- Non-event COMPLETE needs explicit `expected_items` on receipts (emit sets 1 for source_query).
