# P0 bars: gap reverify + mid-hole fill (2026-08-13)

**Mass / READY / raw無し COMPLETE:** **NO-GO**  
**Worker pass ≠ Coverage COMPLETE** (COMPLETE segs bars remain **12**)  
**Tip base:** `43dd235`

## Objective

1. Re-verify contract-floor gap **2004-01 → 2008-04** (honest DEFER; no fabricated `observed_start`).
2. Enumerate **2008-05+ mid-holes** from remote receipts / `coverage_segments`.
3. Execute week-chunk backfill for months with non-empty raw (single `cf_premium_backfill`).
4. Reeval `observed_window`, proof, commit+push.

Contract floor (API / plan): **~2006-08-13**. Calendar **2004** is **out of subscription**.

---

## Dual-run gate

| check | result |
|-------|--------|
| Pre-execute | waited until no `cf_premium_backfill.py` (margin jobs finished first) |
| Mid-hole execute | **one** process only (pid 71405) |
| Recent-hole execute | **one** process only (pid 88558, start_new_session) |
| POST | no concurrent `cf_premium_backfill.py` |

---

## PRE (remote D1 `quant-ingest`, session start)

| metric | value |
|--------|------:|
| `dataset_coverage.observed_start` | **2008-05-01** |
| `dataset_coverage.observed_end` | 2026-08-12 |
| `dataset_coverage.status` | PARTIAL |
| `dataset_coverage.row_count` | 803862 (hot residual) |
| bars COMPLETE segs | **12** |
| bars raw manifests | **590** (complete 495, sum_rows **9_453_527**) |
| SUCCESS receipts `raw_row_count>0` | n=**172**, min **2008-05-01**, max 2026-08-12, sum_raw **3_230_720** |
| nz receipt months 2008-05..2026-08 | **42** (continuous 2008-05..2011-04 + sparse later) |

### Receipt mid-holes (PRE)

| band | missing nz SUCCESS months |
|------|---------------------------|
| 2008-05 → 2011-04 | none (already thick) |
| **2011-05 → 2023-12** | **~151 months** (no nz receipts; except 2020-06) |
| 2024-02 → 2026-04 | sparse (several COMPLETE already) |

---

## 1) Gap 2004-01 → 2008-04 — reverify + DEFER

### Smoke (direct `/v1/run`, not dual backfill driver)

| tag | range | http | status | rowsInserted | rawBytes | verdict |
|-----|-------|-----:|--------|-------------:|---------:|---------|
| gap_empty | 2006-08-13 → 2006-08-18 | 200 | pass | **0** | 72 | empty `data[]` |
| gap_empty | 2007-06-01 → 2007-06-05 | 200 | pass | **0** | 60 | empty |
| gap_empty | 2008-04-01 → 2008-04-05 | 200 | pass | **0** | 60 | empty |
| pre_contract | 2004-01-05 → 2004-01-09 | 200 | **fail** | 0 | 0 | entitlement / OOS |
| pre_contract | 2006-08-01 → 2006-08-12 | 200 | **fail** | 0 | 0 | before floor 2006-08-13 |
| control | 2010-06-01 → 2010-06-05 | 200 | pass | 9757 | ~6.5MB | non-empty |

Prior tip proof already dispatched full week-chunks **2006-08-12 → 2008-04-30** (90/90; empty shells). Receipts for 2006-08..2008-04 exist with **n_nz=0**.

### Honest DEFER (do not fabricate observed_start)

| sub-range | reason | action |
|-----------|--------|--------|
| **2004-01 → 2006-08-12** | **Outside contract** (subscription floor ~2006-08-13; API fail) | **DEFER / OOS** — not a fillable history gap |
| **2006-08-13 → 2008-04-30** | API returns **empty `data[]`** for entire band (smoke reverify) | **DEFER** — empty SUCCESS shells only; **must not** move `observed_start` |
| Non-empty history | first nz SUCCESS remains **2008-05-01** | floor holds |

Artifact: `.glm-logs/cf-backfill/bars_p0_smoke_20260813.json`

---

## 2) Mid-hole probes (non-empty raw exists)

| range | rowsInserted | rawBytes | note |
|-------|-------------:|---------:|------|
| 2011-05-09 → 2011-05-13 | 12134 | ~8.1MB | hole band has real data |
| 2015-06-01 → 2015-06-05 | 18765 | ~12.6MB | |
| 2018-03-05 → 2018-03-09 | 19572 | ~13.2MB | |
| 2021-06-01 → 2021-06-04 | 16435 | ~11.0MB | |

→ Eligible for execute fill (unlike 2006–2008 empty).

---

## 3) Execute fills

### A. Mid-history holes `2011-05-01 → 2023-12-31`

```text
.venv/bin/python scripts/ops/cf_premium_backfill.py \
  --datasets equities_bars_daily \
  --from-date 2011-05-01 --to-date 2023-12-31 \
  --execute --week-chunks --chunk-days 7 \
  --max-jobs 0 --workers 2 \
  --plan-out .glm-logs/cf-backfill/bars_midhole_exec_plan.json \
  --queue-out .glm-logs/cf-backfill/bars_midhole_exec_queue.json \
  --state-out .glm-logs/cf-backfill/bars_midhole_exec_state.jsonl
```

| field | value |
|-------|------:|
| plan / queued / executed | **662 / 662 / 662** |
| pass | **661** |
| fail | **1** → `2013-12-08..14` HTTP 500 |
| rowsInserted sum (worker) | **11_418_621** |
| fail retry | **pass**, rowsInserted **18146** |

### B. Recent PARTIAL holes `2024-04-01 → 2025-12-31`

(COMPLETE months 2024-01..03 / 2025-04 / 2026-01..08 left alone for seal; residual PARTIAL months without nz receipts filled.)

```text
.venv/bin/python scripts/ops/cf_premium_backfill.py \
  --datasets equities_bars_daily \
  --from-date 2024-04-01 --to-date 2025-12-31 \
  --execute --week-chunks --chunk-days 7 \
  --max-jobs 0 --workers 2 \
  --plan-out .glm-logs/cf-backfill/bars_recent_hole2_plan.json \
  --queue-out .glm-logs/cf-backfill/bars_recent_hole2_queue.json \
  --state-out .glm-logs/cf-backfill/bars_recent_hole2_state.jsonl
```

| field | value |
|-------|------:|
| plan / executed | **88 / 88** |
| pass / fail | **88 / 0** |
| rowsInserted sum | **1_807_791** |

---

## 4) Reeval

```text
.venv/bin/python scripts/ops_reeval_observed_window.py --dataset equities_bars_daily
```

| field | PRE | POST |
|-------|-----|------|
| **observed_start** | **2008-05-01** | **2008-05-01** (**unchanged** — no nz raw before May 2008) |
| observed_end | 2026-08-12 | 2026-08-12 |
| status | PARTIAL | PARTIAL |
| evaluated_at | 2026-08-12T15:06:15Z | **2026-08-13T00:56:50Z** |
| COMPLETE segs bars | 12 | **12** (no inflation) |

Receipt window used: SUCCESS + `raw_row_count>0` → min still **2008-05-01**.

---

## POST (remote D1)

| metric | PRE | POST | Δ |
|--------|----:|-----:|--:|
| **observed_start** | 2008-05-01 | **2008-05-01** | 0 |
| nz SUCCESS n | 172 | **953** | **+781** |
| nz SUCCESS sum_raw | 3_230_720 | **17_094_481** | **+13_863_761** |
| bars raw manifests | 590 | **1380** | **+790** |
| bars raw COMPLETE | 495 | **1281** | **+786** |
| bars sum row_count | 9_453_527 | **23_317_288** | **+13_863_761** |
| COMPLETE segs | 12 | 12 | 0 |

### Hole scan POST (nz SUCCESS by month)

| band | holes remaining |
|------|-----------------|
| 2008-05 → 2023-12 | **0** |
| 2024-01 → 2026-07 | 7 months without nz week receipts — all already **coverage_segments COMPLETE** (2024-02/03, 2025-04, 2026-01..04); not open PARTIAL holes |
| 2006-08 → 2008-04 | 21 months empty-only (API empty; DEFER) |

---

## Acceptance

| gate | result |
|------|--------|
| Gap 2004–2008 reverify (empty / OOS honest) | **PASS** (DEFER documented; no fake observed_start) |
| Mid-holes 2011-05→2023-12 filled (non-empty raw) | **PASS** (662 + fail retry) |
| Recent PARTIAL 2024-04→2025-12 filled | **PASS** (88/88) |
| Single `cf_premium_backfill` at a time | **PASS** |
| reeval observed_window | **PASS** |
| observed_start moved into 2006/2007 | **FAIL / impossible** (empty API) — honest |
| No Mass / raw無し COMPLETE | **PASS** |

---

## Explicit non-claims

- **No** `observed_start` advance before **2008-05-01**
- **No** equities_bars_daily COMPLETE inflation (still 12)
- **No** claim that empty worker pass for 2006–2008 == historical bars present
- **2004** history is **out of Premium subscription** for this tenant
- Worker pass ≠ Coverage COMPLETE seal

---

## Residual

| item | note |
|------|------|
| Contract / data floor | API non-empty history from ~**2008-05**; plan text floor **2006-08-13** for entitlement only |
| Empty gap shells 2006-08..2008-04 | kept as SUCCESS raw_row_count=0; reeval ignores them by design |
| COMPLETE months without nz week receipts | 2024-02/03, 2025-04, 2026-01..04 already COMPLETE — optional receipt thickening only |
| `row_count=803862` on coverage | hot D1 residual, not full R2 history |

## Commands (reproducible)

```bash
ps -ax -o pid= -o command= | awk '/cf_premium_backfill\.py/ {print}'

.venv/bin/python scripts/ops/cf_premium_backfill.py \
  --datasets equities_bars_daily \
  --from-date 2011-05-01 --to-date 2023-12-31 \
  --execute --week-chunks --chunk-days 7 \
  --max-jobs 0 --workers 2 \
  --plan-out .glm-logs/cf-backfill/bars_midhole_exec_plan.json \
  --queue-out .glm-logs/cf-backfill/bars_midhole_exec_queue.json \
  --state-out .glm-logs/cf-backfill/bars_midhole_exec_state.jsonl

.venv/bin/python scripts/ops_reeval_observed_window.py --dataset equities_bars_daily
```
