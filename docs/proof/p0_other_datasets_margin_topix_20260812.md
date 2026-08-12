# P0 other datasets: margin + TOPIX (2026-08-12)

**Mass / READY:** NO-GO  
**COMPLETE fabrications:** none  
**premium × bars dual-run:** waited for equities `cf_premium_backfill` to clear before TOPIX (margin is non-bars; short latest-only allowed in parallel)

## Actions

### 1. `markets_margin_interest` — latest week/month execute

| Run | Segment | rowsInserted (worker) | state |
|-----|---------|----------------------|-------|
| latest-only | `2026-08` `2026-08-01`→`2026-08-11` | **4259** | pass |
| month | `2026-07` `2026-07-01`→`2026-07-31` | **21277** | pass |

Artifacts: `.glm-logs/cf-backfill/margin_latest_exec_*`, `margin_jul_exec_*`

Remote evidence after execute:

| Field | PRE | POST |
|-------|-----|------|
| `ingestion_watermarks.last_event_date` | 2026-07-31 | **2026-08-07** |
| `ingestion_watermarks.last_ingested_at` | (prior) | `2026-08-12T23:31:38+09:00` |
| SUCCESS receipts with `raw_row_count>0` max end | ~2026-08-04 | **2026-08-11** (4259 rows) |
| `dataset_coverage.observed_end` | `2025-02-28` | **`2026-08-11`** |
| `dataset_coverage.status` | **STALE** | **PARTIAL** |

#### STALE → PARTIAL (honest, not COMPLETE)

1. Re-eval `observed_*` via `scripts/ops_reeval_observed_window.py --dataset markets_margin_interest`  
   - receipt window nonzero: `2026-05-13` … `2026-08-11` (16 SUCCESS receipts, sum_raw≈85183)  
   - kept `observed_start=2024-01-12` (cold plane); extended `observed_end=2026-08-11`
2. C8 freshness: lag from `2026-08-11` vs evaluation day `2026-08-12` = **1 calendar day ≤ max_days=7** → C8 would pass.
3. Remote UPDATE `status='PARTIAL'` **only where** `status='STALE' AND observed_end >= '2026-08-01'`.  
   - **Did not** set COMPLETE.  
   - Segment inventory unchanged: COMPLETE **14** / PARTIAL **150** (sticky history months).

### 2. `indices_bars_daily_topix` — contract history execute

| Batch | from–to filter | max-jobs | executed | pass | notes |
|-------|----------------|----------|----------|------|-------|
| hist1 | 2008-01-01 → 2023-12-31 | 16 | 16 | 16 | 2008-01..2009-04; Jan–Apr 2008 raw 0; May+ has rows |
| hist2 | same | 24 | 24 | 24 | through 2009-12; ~406 rowsInserted aggregate |
| hist3 | 2010-01-01 → 2015-12-31 | 24 | 24 | 24 | 2010–2011 window first |
| hist4 | 2016-01-01 → 2020-12-31 | 20 | 20 | 20 | 2016-01 → 2017-08; +410 rowsInserted |

All worker states **pass**. 503 retried by driver; no subscription 400 observed in these batches.

Artifacts: `.glm-logs/cf-backfill/topix_hist{,2,3,4}_*`

#### observed_start reeval (receipt plane)

`scripts/ops_reeval_observed_window.py --dataset indices_bars_daily_topix`

| Field | PRE | POST |
|-------|-----|------|
| `observed_start` | `2024-01-04T15:00:00+09:00` | **`2008-01-01`** |
| `observed_end` | `2026-08-10T15:30:00+09:00` | **`2026-08-12`** |
| `status` | PARTIAL | PARTIAL (unchanged) |
| coverage_segments | COMPLETE 32 / PARTIAL 192 | COMPLETE **32** / PARTIAL **124** / UNKNOWN **68** |

Receipt evidence: SUCCESS + `raw_row_count>0` → min `2008-01-01`, max `2026-08-12`, n≈358, sum_raw≈11205.  
`coverage_segments` not rewritten by reeval script. UNKNOWN increase vs prior PARTIAL is residual inventory shape (not promoted to COMPLETE).

D1 `jquants_records` remains **hot-window only** (topix n small); long history lives R2 raw + receipts. Worker pass ≠ Coverage COMPLETE.

## Absolute bans held

- No Mass / READY / B0 claims  
- No fabricated COMPLETE on dataset or segments  
- No token / secret in proof or logs committed  
- premium bars dual-run avoided for TOPIX (equities bars CF cleared first)

## Operator notes

- Residual TOPIX history months still pending (planner still queues PARTIAL/UNKNOWN months beyond executed windows).  
- Margin history 2013–2023 and monthly receipt identity vs weekly CF windows remain open (see prior P1 DEFER proof).  
- Next: more `cf_premium_backfill --datasets indices_bars_daily_topix --max-jobs 12+ --execute` when premium free; margin monthly TRUSTED seal still separate ticket.
