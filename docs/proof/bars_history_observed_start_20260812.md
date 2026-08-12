# equities_bars_daily history → observed_start < 2024 (2026-08-12)

**Mass / READY / raw無し COMPLETE: NO-GO**  
**Worker pass ≠ Coverage COMPLETE** (no bars COMPLETE seal claimed here)

## Diagnosis (why prior 20-month pass left observed_start=2024-01-04)

| hypothesis | verdict | evidence |
|------------|---------|----------|
| R2-only structured → D1 hot has no history | **TRUE (primary)** | `write_path_config.ts` `isR2Only(equities_bars_daily)`; remote `jquants_records` event window **2026-07-01 → 2026-08-10** only (n≈124k). Local research mirror still shows 2024-01-04 hot residual. |
| coverage only saw hot window (C4 on `jquants_records`) | **TRUE (primary)** | `coverage_ledger._dataset_status` took `observed_*` from C4 `event_time_min/max` only → published **2024-01-04**. |
| worker `rowsInserted=0` pass hides history | **PARTIAL** | Older month-batch passes reported `rowsInserted=0` while raw plane advanced. Week-chunk path for **2008-05+** correctly reports `rowsInserted≈7k–12k` (R2 structured count). **2006–2007** still returns empty API (`rowsInserted=0`, `raw_bytes≈84`) — not entitlement 400; empty `data[]`. |

**Root cause (actionable):** control-plane `dataset_coverage.observed_*` was hot-D1-only while historical SoT is R2 raw + SUCCESS receipts with `raw_row_count>0`.

## Code fix

1. `packages/data_plane/storage/coverage_ledger.py`  
   - `_receipt_observed_window` / `_merge_observed_window`  
   - Union SUCCESS receipts with **`raw_row_count > 0`** into `observed_start` / `observed_end`  
   - Empty SUCCESS shells (`raw_row_count=0`) **do not** extend the window  
2. `scripts/ops_reeval_observed_window.py`  
   - Remote D1 targeted UPDATE from receipt plane (no `coverage_segments` rewrite, no COMPLETE claim)  
3. `packages/data_plane/ops/backfill_planner.py` + `scripts/ops/cf_premium_backfill.py`  
   - `--week-chunks` / `--chunk-days` so today-mode high-volume months subdivide (Worker 1102 avoidance); `segment_id` stays `YYYY-MM`  
4. Test: `tests/test_phase61_coverage_v2.py::test_receipt_observed_window_ignores_empty_success_shells`

## PRE (remote D1 `quant-ingest`)

Captured before reeval / wave2:

| metric | value |
|--------|------:|
| `dataset_coverage.observed_start` | **2024-01-04T15:00:00+09:00** |
| `dataset_coverage.observed_end` | 2026-08-10T15:30:00+09:00 |
| `dataset_coverage.status` | PARTIAL |
| `dataset_coverage.row_count` | 803862 (mirror-published hot residual; not full history) |
| COMPLETE segs (`equities_bars_daily`) | **12** (unchanged; not sealed here) |
| `raw_retention_manifests` total | **1746** (complete 1645) |
| bars raw manifests | **401** (complete 307, sum_rows 9_176_704) |
| SUCCESS receipts `raw_row_count>0` min segment_start | **2008-05-01** (n=138 at PRE snapshot) |

No secrets logged. Dual `cf_premium_backfill` avoided (ps gate).

## Execute waves

### Wave A (in-flight at attach; collected — no dual-start)

```text
.venv/bin/python scripts/ops/cf_premium_backfill.py \
  --datasets equities_bars_daily \
  --from-date 2008-05-01 --to-date 2023-12-31 \
  --execute --week-chunks --chunk-days 7 \
  --max-jobs 40 --workers 2 \
  --plan-out .glm-logs/cf-backfill/aexec_eq_week_plan.json \
  --queue-out .glm-logs/cf-backfill/aexec_eq_week_queue.json \
  --state-out .glm-logs/cf-backfill/aexec_eq_week_state.jsonl
```

| field | value |
|-------|------:|
| pass | **40** |
| fail | **0** |
| rowsInserted sum | **461_365** |
| span | ~2008-05 → 2009-02 week chunks |

### Wave B (this agent; after Wave A exit)

```text
.venv/bin/python scripts/ops/cf_premium_backfill.py \
  --datasets equities_bars_daily \
  --from-date 2006-08-12 --to-date 2008-04-30 \
  --execute --week-chunks --chunk-days 7 \
  --max-jobs 60 --workers 1 \
  --plan-out .glm-logs/cf-backfill/bars_hist_plan.json \
  --queue-out .glm-logs/cf-backfill/bars_hist_queue.json \
  --state-out .glm-logs/cf-backfill/bars_hist_state.jsonl
```

| field | value |
|-------|------:|
| pass | **58** |
| fail | **2** (D1 long-running import: 2007-06-23..29, 2007-08-11..17) |
| rowsInserted sum | **0** (API empty `data[]` for 2006-08..2007-09 week queries) |
| fails retained in | `.glm-logs/cf-backfill/bars_hist_state.jsonl` |

**Smoke (honest):**

- `2007-03-01..07` → pass, `rowsInserted=0`, `rawBytes=84` (empty)
- `2010-06-01..05` → pass, `rowsInserted=9757`, `rawBytes≈6.5MB` (real)

Subscription floor **2006-08-12** still applies (earlier dates → HTTP 400). Empty ≠ COMPLETE.

### Coverage reeval (remote)

```text
.venv/bin/python scripts/ops_reeval_observed_window.py --dataset equities_bars_daily
```

Receipt window used: SUCCESS + `raw_row_count>0` → min **2008-05-01**, max through hot end.

## POST (remote D1)

| metric | PRE | POST | Δ |
|--------|----:|-----:|--:|
| **observed_start** | **2024-01-04** | **2008-05-01** | moved **&lt; 2024-01-01** ✓ |
| observed_end | 2026-08-10T15:30+09 | 2026-08-12 | advanced |
| status | PARTIAL | PARTIAL | (no COMPLETE claim) |
| COMPLETE segs bars | 12 | 12 | 0 (correct) |
| raw_manifests total | 1746 | **1889** | **+143** |
| raw COMPLETE total | 1645 | 1788 | +143 |
| bars raw manifests | 401 | **478** | **+77** |
| bars raw COMPLETE | 307 | 384 | +77 |
| bars sum row_count | 9_176_704 | 9_328_365 | +151_661 |
| nz SUCCESS receipts min | 2008-05-01 | 2008-05-01 | n≈156 |

### Success criteria

1. **remote `observed_start` < 2024-01-01** → **PASS** (`2008-05-01`)  
2. **raw_manifests increase (numeric)** → **PASS** (+143 total, +77 bars)  
3. This proof PRE/POST → **PASS**  
4. git commit + push → (see SHA after push)

### Explicit non-claims

- **No** equities_bars_daily COMPLETE segment inflation  
- **No** Mass / READY  
- Wave B pass≠historical rows for 2006–2007 (empty API); do not treat as history seal  
- `row_count=803862` on coverage remains hot residual, not full R2 history

## Ops note

Future history thickening: prefer `--week-chunks` for bars; after each real-data wave re-run `scripts/ops_reeval_observed_window.py`. To push `observed_start` before 2008-05, need SUCCESS receipts with **`raw_row_count>0`** for earlier months (empty shells ignored by design).
