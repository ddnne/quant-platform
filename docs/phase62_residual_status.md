# Phase 6.2 / 6.3 residual status (2026-08-12 live resync)

| Area | Status | Notes |
|------|--------|-------|
| Segment COMPLETE | **400** | calendar 224, master 94 COMPLETE segs, JSDA min 3, etc. |
| Dataset-level COMPLETE | **2** | markets_calendar + jsda_tokyo_repo_rates (all required segs COMPLETE) |
| Aggregate/detail desync | **FIXED** | dataset_coverage recomputed from coverage_segments |
| Sticky COMPLETE on re-eval | **CODE** | demotion blocked when SUCCESS receipt still eligible |
| master SCD2 | **DONE** | scd2_event_sourcing / D1 hot 128811 |
| Full publish guard | **DONE** | fe6aafc |
| Local COMPLETE heal | **DONE** | local 400 = remote 400 |
| Mass / READY / B0 | **NO-GO** | |

## origin/main lag
Local branch ahead of origin with guard + ops tooling + docs. Push when authorized.
