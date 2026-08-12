# markets_breakdown history → observed_start < 2024 (2026-08-12)

**Mass / READY / raw無し COMPLETE: NO-GO**  
**Worker pass ≠ Coverage COMPLETE** (no markets_breakdown COMPLETE seal claimed)

## Contract / planner notes

| item | value |
|------|------:|
| Coverage Contract `history_target_start` | **2013-01-04** |
| CLI `--from-date` (requested) | 2006-08-12 (clipped by planner to contract start) |
| Date mode | `today` (month default; week-chunks for real-data months) |
| Track A focus range | 2013-01-04 → 2099-12-31 |

Empty API shells for **2013-01 → 2015-03** (month jobs pass, `rowsInserted=0`) do **not** extend `observed_*` (receipt filter `raw_row_count > 0`).

## PRE (remote D1 `quant-ingest`)

| metric | value |
|--------|------:|
| `dataset_coverage.observed_start` | **2024-01-04T00:00:00+09:00** |
| `dataset_coverage.observed_end` | 2026-08-10T00:00:00+09:00 |
| `dataset_coverage.status` | PARTIAL |
| `dataset_coverage.row_count` | 2669153 (hot residual; not full R2 history) |
| SUCCESS receipts `raw_row_count>0` | n=**19**, window **2026-05-13 → 2026-08-10**, sum_raw≈290593 |
| `raw_retention_manifests` (dataset) | **43** |

No secrets logged. Dual `cf_premium_backfill` gate: waited / single markets_breakdown driver only.

## Execute waves

### Wave 1 — month chunks (diagnostic; 503 on real-data months)

```text
.venv/bin/python scripts/ops/cf_premium_backfill.py \
  --datasets markets_breakdown \
  --from-date 2006-08-12 --to-date 2023-12-31 \
  --execute --max-jobs 48 --workers 1 \
  --plan-out .glm-logs/cf-backfill/mb_hist_plan.json \
  --queue-out .glm-logs/cf-backfill/mb_hist_queue.json \
  --state-out .glm-logs/cf-backfill/mb_hist_state.jsonl
```

| field | value |
|-------|------:|
| executed (stopped mid-queue) | **36** |
| pass | **25** (2013-01 → 2015-03 empty shells, `rowsInserted=0`) |
| fail | **11** (2015-04 → 2016-02 **HTTP 503** full-month overload) |
| rowsInserted sum | **0** |

Month-range jobs blow up once source data is dense → stop + switch to week chunks (503 retry path).

### Wave 2 — week chunks (SUCCESS + raw)

```text
.venv/bin/python scripts/ops/cf_premium_backfill.py \
  --datasets markets_breakdown \
  --from-date 2015-04-01 --to-date 2023-12-31 \
  --week-chunks --chunk-days 7 \
  --execute --max-jobs 48 --workers 1 \
  --plan-out .glm-logs/cf-backfill/mb_week_plan.json \
  --queue-out .glm-logs/cf-backfill/mb_week_queue.json \
  --state-out .glm-logs/cf-backfill/mb_week_state.jsonl
```

| field | value |
|-------|------:|
| pass | **48** |
| fail | **0** |
| rowsInserted sum | **816_865** |
| span | **2015-04-01 → 2016-03-01** week windows |
| plan residual | 457 week jobs total for 2015-04..2023-12 (409 still pending) |

Artifacts: `.glm-logs/cf-backfill/mb_week_*` (local; not committed).

## Coverage reeval (remote receipt union)

```text
.venv/bin/python scripts/ops_reeval_observed_window.py --dataset markets_breakdown
```

Receipt window used: SUCCESS + `raw_row_count>0` → min **2015-04-01**, max **2026-08-10**, n=**67**, sum_raw=**1_107_458**.

`coverage_segments` **not** rewritten. No COMPLETE / Mass / READY claim.

## POST (remote D1)

| metric | PRE | POST | Δ |
|--------|----:|-----:|--:|
| **observed_start** | **2024-01-04** | **2015-04-01** | moved **&lt; 2024-01-01** ✓ |
| observed_end | 2026-08-10 | 2026-08-10 | (unchanged) |
| status | PARTIAL | PARTIAL | (no COMPLETE claim) |
| nz SUCCESS receipts | 19 (hot only) | **67** | **+48** |
| nz receipt min start | 2026-05-13 | **2015-04-01** | history |
| raw_manifests (dataset) | 43 | **127** | **+84** |
| raw COMPLETE (dataset) | — | **127** | all complete |
| raw sum row_count | — | 1_920_733 | — |

### Success criteria

1. **remote `observed_start` < 2024-01-01** → **PASS** (`2015-04-01`)
2. **SUCCESS + raw receipts** (no raw無し COMPLETE) → **PASS**
3. **503 path**: month fails retried via `--week-chunks` → **PASS** (48/48)
4. docs/proof + git commit push → (see SHA after push)

### Explicit non-claims

- **No** markets_breakdown dataset COMPLETE
- **No** Mass / READY
- **No** seal of 2013-01..2015-03 empty shells as history
- Residual week jobs for **2016-03 → 2023-12** still pending (`plan_jobs=457`, this wave `max-jobs=48`)
- D1 `jquants_records` remains hot-window; long history is R2 raw + receipts
- Worker pass ≠ Coverage COMPLETE

## Ops note

Prefer `--week-chunks --chunk-days 7` for `markets_breakdown` once source data exists (~2015-04+). Full-month ranges → HTTP 503. After each real-data wave re-run `scripts/ops_reeval_observed_window.py --dataset markets_breakdown`. Empty SUCCESS (`raw_row_count=0`) never moves `observed_start`.
