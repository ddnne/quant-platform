# G2 = T2 + T3: equities_bars_daily + indices_bars_daily_topix residual (2026-08-13)

**Mass / READY / raw無し COMPLETE:** **NO-GO**  
**Worker pass ≠ Coverage COMPLETE**  
**Did not kill live general-495 jobs:** `equities_master` (t7), `short_ratio/margin_alert/investor_types` (t8) — left running until natural exit

## Objective

| track | dataset | observed target | driver |
|-------|---------|-----------------|--------|
| **T2** | `equities_bars_daily` | **2008-05-01 … 2026-08-12** | week-chunks, workers 2, general-rpm 495, max-jobs **120** (one shot) |
| **T3** | `indices_bars_daily_topix` | **2008-01-01 … 2026-08-13** | residual after t4_topix 192, workers 2, general-rpm 495 |

Prefixes: `t2_bars_*`, `t3_topix_*` (separate from completed `p0_bars_solo` / `t4_topix`).

**Forbidden held:** no Mass; no empty COMPLETE; no kill of other jobs; no force COMPLETE of bars pre-2008-05 (empty raw / DEFER).

---

## PRE (remote D1 `quant-ingest`)

| metric | bars | topix |
|--------|-----:|------:|
| `observed_start` | **2008-05-01** | **2008-01-01** |
| `observed_end` | 2026-08-12 | 2026-08-13 |
| `status` | PARTIAL | PARTIAL |
| `row_count` (hot) | 803862 | 635 |
| coverage_segments | COMPLETE **12** / PARTIAL 260 | COMPLETE **32** / UNKNOWN 192 |
| SUCCESS receipts `raw_row_count>0` n | **1301** | **1152** |
| receipt min…max | 2008-05-01 … 2026-08-12 | 2008-01-01 … 2026-08-13 |
| receipt sum_raw | **21_026_871** | **26_997** |

Artifact: `.glm-logs/cf-backfill/t2_t3_PRE.json`

### Dry-run residual (planner, local COMPLETE skip only)

| track | plan_jobs | note |
|-------|----------:|------|
| T2 week-chunks 2008-05-01→2026-08-12 | **905** | COMPLETE segs still only 12 → most months re-queue; max-jobs caps one shot |
| T3 month 2008-01-01→cutoff | **192** | same residual set as t4 (UNKNOWN/PARTIAL history); 2024+ already COMPLETE (32) |

---

## Execute

### T3 `indices_bars_daily_topix` (first — light residual)

```text
.venv/bin/python -u scripts/ops/cf_premium_backfill.py \
  --datasets indices_bars_daily_topix \
  --from-date 2008-01-01 --to-date 2026-08-13 \
  --execute --workers 2 --general-rpm 495 --max-jobs 0 \
  --sleep-on-retry 3.0 \
  --plan-out .glm-logs/cf-backfill/t3_topix_exec_plan.json \
  --queue-out .glm-logs/cf-backfill/t3_topix_exec_queue.json \
  --state-out .glm-logs/cf-backfill/t3_topix_exec_state.jsonl
```

| field | value |
|-------|------:|
| plan / queued / executed | **192 / 192 / 192** |
| pass / fail | **192 / 0** |
| segment range | 2008-01 … 2023-12 |
| host POST rpm | ~45.7 (window ~251s) |
| http_429_count | **0** |
| pid | 6721 |

### T2 `equities_bars_daily` (after T3; concurrent with remaining live general jobs)

```text
.venv/bin/python -u scripts/ops/cf_premium_backfill.py \
  --datasets equities_bars_daily \
  --from-date 2008-05-01 --to-date 2026-08-12 \
  --execute --week-chunks --chunk-days 7 \
  --workers 2 --general-rpm 495 --max-jobs 120 \
  --sleep-on-retry 3.0 \
  --plan-out .glm-logs/cf-backfill/t2_bars_exec_plan.json \
  --queue-out .glm-logs/cf-backfill/t2_bars_exec_queue.json \
  --state-out .glm-logs/cf-backfill/t2_bars_exec_state.jsonl
```

| field | value |
|-------|------:|
| plan_jobs (full residual) | **905** |
| queued / executed (max-jobs) | **120 / 120** |
| pass / fail | **119 / 1** |
| fail | `2009-11` week `2009-11-05`→`2009-11-11` — HTTP **500** (worker_error) |
| rowsInserted sum (worker) | **1_371_723** |
| segment months touched | 2008-05 … 2010-08 (week chunks) |
| host POST rpm | ~6.14 (window ~1163s) |
| http_429_count | **0** |
| pid | 8992 |

Live companions **not killed** during T2/T3: t7_master, t8_misc (finished naturally); other agents’ t5_margin_earn / t6_deriv_edinet also concurrent — no SIGTERM from this track.

---

## Reeval

```text
.venv/bin/python scripts/ops_reeval_observed_window.py --dataset equities_bars_daily
.venv/bin/python scripts/ops_reeval_observed_window.py --dataset indices_bars_daily_topix
```

### bars

| field | PRE | POST |
|-------|-----|------|
| **observed_start** | **2008-05-01** | **2008-05-01** (unchanged) |
| observed_end | 2026-08-12 | 2026-08-12 |
| status | PARTIAL | PARTIAL |
| C8 | pass (lag 1d) | **pass** (lag 1d) |
| COMPLETE segs | 12 | **12** (no inflation) |
| receipt n / sum_raw | 1301 / 21_026_871 | **1421** / **22_403_038** |

### topix

| field | PRE | POST |
|-------|-----|------|
| **observed_start** | **2008-01-01** | **2008-01-01** |
| observed_end | 2026-08-13 (coverage) / 2026-08-12 (pre-reeval snap) | **2026-08-13** |
| status | PARTIAL | PARTIAL |
| C8 | pass | **pass** (lag 0d) |
| COMPLETE segs | 32 | **32** (no inflation) |
| receipt n / sum_raw | 1152 / 26_997 | **1341** / **30_833** |

`coverage_segments` not rewritten to COMPLETE by reeval (by design).

---

## POST Δ (receipt plane)

| dataset | Δ n SUCCESS nz | Δ sum_raw | notes |
|---------|---------------:|----------:|-------|
| equities_bars_daily | **+120** | **+1_376_167** | aligns with max-jobs 120 week-chunks (idempotent re-thickening + new weeks) |
| indices_bars_daily_topix | **+189** | **+3_836** | residual re-dispatch after t4; raw already thick |

Hot D1 `row_count` unchanged (R2 cold path for history).

---

## Acceptance

| gate | result |
|------|--------|
| T2 week-chunks one-shot max-jobs 80–150 | **PASS** (120) |
| T3 residual after t4 192 | **PASS** (192/192 pass) |
| reeval bars + topix | **PASS** |
| observed_start bars held at 2008-05-01 | **PASS** (no pre-2008 fabricate) |
| No Mass / empty COMPLETE | **PASS** |
| Did not kill t7/t8 general sharers | **PASS** |
| T2 fail residual | **1** week HTTP 500 — not sealed COMPLETE |

---

## Explicit non-claims

- **No** dataset COMPLETE / Mass / Research READY
- **No** COMPLETE inflation on `coverage_segments` (bars 12, topix 32)
- **No** observed_start move before **2008-05-01** for bars (empty API band 2006-08..2008-04 remains DEFER)
- Worker pass ≠ Coverage COMPLETE seal
- Full T2 planner residual still **905 − 120 = 785** week-jobs if re-run without max-jobs (COMPLETE only 12)

---

## Artifacts

| path | role |
|------|------|
| `.glm-logs/cf-backfill/t2_bars_{plan,queue_dry,exec_*}.{json,jsonl,log}` | T2 plan + execute |
| `.glm-logs/cf-backfill/t3_topix_{plan,queue_dry,exec_*}.{json,jsonl,log}` | T3 plan + execute |
| `.glm-logs/cf-backfill/t2_t3_PRE.json` | PRE snapshot |
| `.glm-logs/cf-backfill/t2_t3_pipeline.log` | wait + reeval transcript |

## Commands (reproducible)

```bash
# dry residual
.venv/bin/python scripts/ops/cf_premium_backfill.py \
  --datasets equities_bars_daily --from-date 2008-05-01 --to-date 2026-08-12 \
  --week-chunks --workers 2 --general-rpm 495 \
  --plan-out .glm-logs/cf-backfill/t2_bars_plan.json \
  --queue-out .glm-logs/cf-backfill/t2_bars_queue_dry.json

.venv/bin/python scripts/ops_reeval_observed_window.py --dataset equities_bars_daily
.venv/bin/python scripts/ops_reeval_observed_window.py --dataset indices_bars_daily_topix
```
