# Phase 6.2 residual status (honest)

**HEAD**: `9c9c58d`  
**Date**: 2026-08-11  
**Track**: GLM-5.2 + orchestrated land

> **Not fully done.** Code-complete; live partial. No `PHASE62_FULL_DONE`.  
> Phase 7 mass research **NO-GO** until all governed COMPLETE + READY ≥1.

## Live milestone ✅

| Dataset | Status | Evidence |
|---------|--------|----------|
| **markets_calendar** | **COMPLETE** | 224/224 segments COMPLETE with real receipts |

## Code-complete ✅
Inventory, projection, host cron, JQ receipt emit, rebuild_from_raw, bars `date=` fix,
READY coherence wire, Phase 7 stubs, pytest green.

## Still OPEN 🚫

| Item | Status |
|------|--------|
| All 26 governed Coverage COMPLETE | **Open** — only markets_calendar COMPLETE so far |
| Production READY ≥1 | **Open** — needs full governed COMPLETE |
| Full multi-year JQ/JSDA backfill | **In progress** (background jobs) |
| JSDA COMPLETE | **Open** (site/timeout risk) |
| CF edge auto-projection | Host path only |

## Human-only
- Wall-clock for remaining 25 governed datasets history
- JSDA availability
- Live capital/broker (OOS)
