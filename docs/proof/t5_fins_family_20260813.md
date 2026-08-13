# T5 fins family — FINAL 288 close (2026-08-13 / 2026-08-14 JST)

**Mass / READY / Phase7:** still **NO-GO / OFF**  
**empty COMPLETE:** none  
**runner:** `t5_fins_paced` **DONE** (PID 8449 dead; `t5_wait_complete.flag=DONE`)  
**prefix:** `t5_fins_*` · serial paced · fins pool (`SLEEP_OK=10`)  
**worker pass ≠ Coverage COMPLETE**

## Goal

Close the T5 fins-family paced wave (288 month jobs) end-to-end:

1. Confirm runner drain + summary (`287 pass / 1 fail` month-level, then recover the fail).
2. Reeval `observed_*` for `fins_summary` / `fins_details` / `fins_dividend` / `fins_earnings_date`.
3. Document honest FINAL numbers (no Mass / no empty COMPLETE).
4. Residual SoT: **T5 DONE**.

## Wave design

`.glm-logs/cf-backfill/t5_fins_paced_runner.py` (PID **8449**):

| dataset | range (month chunks) | months |
|---------|----------------------|------:|
| `fins_summary` | 2008-01 → 2013-12 | **72** |
| `fins_details` | 2018-01 → 2023-12 | **72** |
| `fins_dividend` | 2018-01 → 2023-12 | **72** |
| `fins_earnings_date` | 2018-01 → 2023-12 | **72** |
| **wave total** | | **288** |

## PRE (job start — `t5_fins_PRE.json` @ 2026-08-13T14:02:26Z)

| dataset | status | observed_start | observed_end |
|---------|--------|----------------|--------------|
| `fins_summary` | PARTIAL | **2014-01-01** | 2026-08-12 |
| `fins_details` | PARTIAL | **2024-01-01** | 2026-08-12 |
| `fins_dividend` | PARTIAL | 2026-05-13 | 2026-08-12 |
| `fins_earnings_date` | PARTIAL | 2026-05-13 | 2026-08-12 |

## FINAL execute (runner complete)

Artifacts:

- summary: `.glm-logs/cf-backfill/t5_fins_paced_summary.json`
- state: `.glm-logs/cf-backfill/t5_fins_paced_state.jsonl`
- run log: `.glm-logs/cf-backfill/t5_fins_paced_run.log`
- wait flag: `.glm-logs/cf-backfill/t5_wait_complete.flag` = `DONE`
- aggregate: `.glm-logs/cf-backfill/t5_fins_FINAL_aggregate.json`

### Runner summary (month jobs as dispatched)

| field | value |
|-------|------:|
| done | **true** |
| unique months | **288** |
| pass / fail | **287 / 1** |
| host_jobs_per_min | **1.68** |
| elapsed_s | **10270** (~2.85 h) |
| n_429_events | **0** |
| nz_months | **281** |
| sum_rows (runner) | **440366** |
| window | 2026-08-13T14:06:28Z → ~2026-08-13T16:57:40Z |

### By dataset (runner final status)

| dataset | pass | fail | rowsInserted sum | nz months |
|---------|-----:|-----:|-----------------:|----------:|
| `fins_summary` | **72** | 0 | 120_283 | 66 |
| `fins_details` | **71** | **1** | 90_216 | 71 |
| `fins_dividend` | **72** | 0 | 136_447 | 72 |
| `fins_earnings_date` | **72** | 0 | 93_420 | 72 |
| **total** | **287** | **1** | **440_366** | **281** |

Empty shells (`rowsInserted=0`, honest pass) do **not** extend `observed_*` (receipt filter `raw_row_count>0`).  
Early `fins_summary` 2008-01…06 empty → receipt min start **2008-07-01**.

### Fail + recovery (optional retry)

| field | value |
|-------|-------|
| fail month | **`fins_details` 2022-05** (`2022-05-01`…`2022-05-31`) |
| fail cause | HTTP **503** / CF Error **1102** Worker exceeded (attempts 1–3) |
| split retry | half-month: 05-16…31 **pass** (277 rows); 05-01…15 still 503 |
| daily retry | 2022-05-01…15 day/week chunks → **pass** (rowsInserted sum **2607** on daily path) |
| artifact | `.glm-logs/cf-backfill/t5_fins_details_2022-05_{retry,split_retry,daily}.json` |
| post-recovery unique | **288 pass / 0 fail** (see `t5_fins_FINAL_aggregate.json`) |

**Report line of record:** runner **287/1** + recovery → unique months **288** covered.

## FINAL reeval (`ops_reeval_observed_window`)

```bash
for ds in fins_summary fins_details fins_dividend fins_earnings_date; do
  .venv/bin/python scripts/ops_reeval_observed_window.py \
    --dataset "$ds" --today 2026-08-14 --freshness-days 7
done
```

Logs: `.glm-logs/cf-backfill/t5_fins_reeval_{ds}_FINAL.log`  
POST: `.glm-logs/cf-backfill/t5_fins_POST_{ds}_FINAL.json`

### POST observed_* (remote D1)

| dataset | status | PRE observed_start | POST observed_start | observed_end | C8 |
|---------|--------|--------------------|---------------------|--------------|----|
| `fins_summary` | **PARTIAL** | 2014-01-01 | **`2008-07-01`** | **`2026-08-13`** | **pass** lag **1** |
| `fins_details` | **PARTIAL** | 2024-01-01 | **`2018-01-01`** | **`2026-08-13`** | **pass** lag **1** |
| `fins_dividend` | **PARTIAL** | 2026-05-13 | **`2018-01-01`** | **`2026-08-13`** | **pass** lag **1** |
| `fins_earnings_date` | **PARTIAL** | 2026-05-13 | **`2018-01-01`** | **`2026-08-13`** | **pass** lag **1** |

- Coverage **segments not rewritten** by reeval; dataset status remains **PARTIAL**.
- No COMPLETE claim from reeval alone.

## Receipts / COMPLETE (peer T12; this close +0)

Peer wave already sealed usable raw (empty-raw ban):  
[`docs/proof/t12_receipts_wave_20260814.md`](t12_receipts_wave_20260814.md) — **+45** fins seals (`fins_details` +20, `fins_summary` +25) → remote COMPLETE **585**.

This T5 FINAL close dry-scan:

```bash
.venv/bin/python scripts/issue_receipts_parallel.py \
  --datasets fins_summary,fins_details,fins_dividend,fins_earnings_date \
  --struct-hint --limit 12 --workers 4 --dry-run --json-summary
# → ready=0 (no local raw+struct candidates beyond already COMPLETE / no_struct)
```

| item | value |
|------|------:|
| this-close +N COMPLETE | **0** (honest; no invent) |
| remote COMPLETE segs (live) | **585** |
| fins COMPLETE segs | summary **30** / details **23** / dividend **2** / earnings_date **2** |
| remote `raw_retention_manifests` | **7762** |

Further fins month seals remain **DEFER** until local usable raw + structured exist for residual PARTIAL months.

## G4 partial snapshot (historical — superseded by FINAL)

G4 closed without waiting 288: i=**76/288**, still_running=yes, host jobs/min **1.34–1.37**, summary 72/72 + details 4/72.  
Superseded by this FINAL drain. Keep for audit only.

## Forbidden / honesty

- Did **not** claim dataset COMPLETE / Mass / READY / Phase7 ON.
- Did **not** invent empty COMPLETE seals.
- Did **not** issue receipts without raw+structured.
- Worker pass counts ≠ segment COMPLETE.
- Runner natural exit (not killed mid-wave for this close).

## Residual pointers

- Live SoT: [`docs/phase62_residual_status.md`](../phase62_residual_status.md) — **T5 DONE**.
- Peer seals: [`t12_receipts_wave_20260814.md`](t12_receipts_wave_20260814.md).
- Prior fins history: [`fins_summary_history_observed_start_20260813.md`](fins_summary_history_observed_start_20260813.md).

## Report line

```
T5 FINAL: runner 287/1 (fail=fins_details 2022-05 CF1102) + split/daily recover → unique 288
host_jobs_per_min=1.68 elapsed≈10270s 429=0 PID dead flag=DONE
observed: summary 2008-07-01→2026-08-13 C8pass
          details/div/earn 2018-01-01→2026-08-13 C8pass
COMPLETE segs live=585 (T12 +45 peer; this close +0) raw_n=7762
Mass/empty COMPLETE: no  Phase7: OFF
```
