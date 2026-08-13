# G4 / T5 fins family — wave1 partial close (no wait for 288) (2026-08-13)

**Mass / READY:** NO-GO  
**empty COMPLETE:** none  
**fins paced runner:** **not killed** — still running at G4 close  
**prefix:** `t5_fins_*` · serial paced · fins pool only (`SLEEP_OK=10`)  
**base tip (pre-doc):** residual SoT prior tip; this commit lands proof + residual partial close

## Goal

Close the **G4 circuit without waiting** for full `288/288` paced months:

1. Snapshot `t5_fins_paced_state.jsonl` pass/fail/n + host jobs/min while job continues.
2. Reeval `fins_summary` (+ touched `fins_details`) via receipt plane.
3. **DEFER** `fins_dividend` / `fins_earnings_date` until their wave months start (or finish).
4. Record PRE/POST `observed_*`, `still_running=yes`.

**Worker pass ≠ Coverage COMPLETE.** No Mass. No empty COMPLETE.

## Wave design (runner)

`.glm-logs/cf-backfill/t5_fins_paced_runner.py` (PID **8449**, started ~2026-08-13T14:05Z local session):

| dataset | range (month chunks) | months |
|---------|----------------------|------:|
| `fins_summary` | 2008-01 → 2013-12 | **72** |
| `fins_details` | 2018-01 → 2023-12 | **72** |
| `fins_dividend` | 2018-01 → 2023-12 | **72** |
| `fins_earnings_date` | 2018-01 → 2023-12 | **72** |
| **wave1 total** | | **288** |

Planner dry-run (full residual, not wave-capped): **860** jobs  
(`.glm-logs/cf-backfill/t5_fins_plan.json` / `t5_fins_queue_dry.json` — summary 219 / details 221 / dividend 222 / earnings_date 198).

## PRE (remote D1, job start — `t5_fins_PRE.json` @ 2026-08-13T14:02:26Z)

| dataset | status | observed_start | observed_end | row_count (hot) | nz SUCCESS receipts |
|---------|--------|----------------|--------------|----------------:|--------------------:|
| `fins_summary` | PARTIAL | **2014-01-01** | 2026-08-12 | 6121 | n=170 window 2014-01-01→2026-08-12 |
| `fins_details` | PARTIAL | **2024-01-01** | 2026-08-12 | 3961 | n=29 window 2026-08-10→2026-08-12 |
| `fins_dividend` | PARTIAL | 2026-05-13 | 2026-08-12 | 1348 | n=41 |
| `fins_earnings_date` | PARTIAL | 2026-05-13 | 2026-08-12 | 764 | n=41 |

## Execute snapshot (G4 close — **partial**, job still running)

Snapshot artifact: `.glm-logs/cf-backfill/t5_fins_G4_snapshot.json`  
State: `.glm-logs/cf-backfill/t5_fins_paced_state.jsonl`  
Log: `.glm-logs/cf-backfill/t5_fins_paced_run.log`

| field | value |
|-------|------:|
| snapshot_at (UTC) | **2026-08-13T15:03:38Z** |
| still_running | **yes** (PID 8449) |
| target n | **288** |
| unique i (final status) | **76** |
| final pass / fail | **76 / 0** |
| attempt rows | **78** (attempt pass 76 / fail 2 — both retried to pass) |
| window | 2026-08-13T14:06:28Z → 2026-08-13T15:03:16Z |
| dur_min | **56.8** |
| host jobs/min (attempts) | **1.373** |
| host jobs/min (unique i) | **1.338** |
| ≈ rpm equivalent | **~1.34–1.37 jobs/min** (serial + `SLEEP_OK=10` + worker wall) |

### By dataset (final status @ snapshot)

| dataset | pass | fail | rowsInserted sum | nz months | wave progress |
|---------|-----:|-----:|-----------------:|----------:|---------------|
| `fins_summary` | **72** | 0 | 120_283 | 66 | **72/72 DONE** (wave range) |
| `fins_details` | **4** | 0 | 4_449 | 4 | **4/72 in progress** |
| `fins_dividend` | 0 | 0 | 0 | 0 | **DEFER** (not started) |
| `fins_earnings_date` | 0 | 0 | 0 | 0 | **DEFER** (not started) |

Transient attempt fails (retried OK):  
- `fins_summary` 2009-04 attempt1 fail → attempt2 pass  
- `fins_details` 2018-03 attempt1 fail → attempt2 pass  

Empty shells (`rowsInserted=0`, honest pass) do **not** extend `observed_*` (receipt filter `raw_row_count>0`).  
Early `fins_summary` 2008-01…06 are empty → receipt min start **2008-07-01**, not 2008-01-01.

## Reeval (G4)

```bash
.venv/bin/python scripts/ops_reeval_observed_window.py \
  --dataset fins_summary --today 2026-08-13 --freshness-days 7
.venv/bin/python scripts/ops_reeval_observed_window.py \
  --dataset fins_details --today 2026-08-13 --freshness-days 7
# dividend / earnings_date: dry-run only — DEFER apply until T5 wave reaches them
```

Logs:  
`.glm-logs/cf-backfill/t5_fins_reeval_summary_G4.log`  
`.glm-logs/cf-backfill/t5_fins_reeval_details_G4.log`  
POST JSON: `.glm-logs/cf-backfill/t5_fins_POST_fins_summary.json`  
`.glm-logs/cf-backfill/t5_fins_POST_fins_details.json`

### POST observed_* (remote D1 after reeval)

| dataset | status | PRE observed_start | POST observed_start | observed_end | C8 | receipt n / sum_raw |
|---------|--------|--------------------|---------------------|--------------|----|---------------------|
| `fins_summary` | **PARTIAL** | 2014-01-01 (job PRE) | **`2008-07-01`** | **2026-08-12** | **pass** lag **1** | n=**238** / sum_raw 337_293 |
| `fins_details` | **PARTIAL** | 2024-01-01 | **`2018-01-01`** | **2026-08-12** | **pass** lag **1** | n=**35** / sum_raw 11_588 |
| `fins_dividend` | PARTIAL | 2026-05-13 | **DEFER** (no G4 apply) | 2026-08-12 | — | dry-run would show receipt min **2022-06-01** (peer raw; not T5 wave) |
| `fins_earnings_date` | PARTIAL | 2026-05-13 | **DEFER** (no G4 apply) | 2026-08-12 | — | dry-run would show receipt min **2022-06-01** (peer raw; not T5 wave) |

Notes:

- Mid-job reeval had already advanced `fins_summary` toward 2008-07; G4 reeval **confirmed** POST and rewrote detail_json C8.
- `fins_details` **moved** 2024-01-01 → **2018-01-01** from early wave months already landed.
- Coverage segments **untouched**; status remains **PARTIAL** (not COMPLETE).
- Dividend / earnings_date: **DEFER** — T5 runner has not entered those ranges; dry-run only, no remote UPDATE in G4.

## still_running

| field | value |
|-------|-------|
| still_running | **yes** |
| PID | **8449** |
| i/n @ G4 snapshot | **76/288** |
| expected remaining | details residual + full dividend + earnings_date months (~212+) |
| action | **leave running** — natural exit; do not kill |

## Forbidden / honesty

- Did **not** kill `t5_fins_paced_runner`.
- Did **not** claim dataset COMPLETE / Mass / READY.
- Did **not** invent empty COMPLETE seals.
- Worker pass counts ≠ segment COMPLETE.

## Residual pointers

- Live SoT: [`docs/phase62_residual_status.md`](../phase62_residual_status.md) — T5 wave1 **partial** + job still running.
- Prior fins history: [`fins_summary_history_observed_start_20260813.md`](fins_summary_history_observed_start_20260813.md) (start was 2014-01-01; this pass deepens to **2008-07-01**).

## Report line

```
G4 T5 fins family partial: i=76/288 pass=76 fail=0 (final) attempts=78
host_jobs/min≈1.34–1.37 still_running=yes PID=8449
fins_summary observed_start PRE 2014-01-01 → POST 2008-07-01 C8 pass lag1 n_receipts=238
fins_details observed_start PRE 2024-01-01 → POST 2018-01-01 C8 pass lag1 n_receipts=35
fins_dividend / fins_earnings_date DEFER (wave not started)
Mass/empty COMPLETE: no
```
