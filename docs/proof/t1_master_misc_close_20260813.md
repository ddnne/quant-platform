# T1 / G1 — equities_master + misc queue close (2026-08-13)

**Mass / READY / Phase7:** **NO-GO / OFF**  
**empty COMPLETE:** none invented this pass  
**kill running jobs:** **none** (only watched; no SIGTERM/KILL on live drivers)

**Scope:** monitor live `t7_master` + `t8_misc` backfills, resume only if process dies with residual queue, measure host POST/min, write this proof.  
**Residual fail segments:** deferred to G8 (no extra dataset start; no dual-run of same state).

## Live drivers (confirmed, not killed)

| Track | PID (start) | Datasets | workers | general-rpm | max-jobs | state jsonl |
|-------|-------------:|----------|--------:|------------:|---------:|-------------|
| `t7_master` | 87576 | `equities_master` | 3 | 495 | 0 | `.glm-logs/cf-backfill/t7_master_exec_state.jsonl` |
| `t8_misc` | 87578 | `markets_short_ratio`,`markets_margin_alert`,`equities_investor_types` | 3 | 495 | 0 | `.glm-logs/cf-backfill/t8_misc_exec_state.jsonl` |
| `t4_topix` | (prior) | done | — | — | — | n=**192** all pass (out of scope; noted complete) |

Monitor: `.glm-logs/cf-backfill/g1_monitor.sh` @ 60s → `g1_monitor_progress.log` → `BOTH_DONE 2026-08-13T14:08:20Z`.

**Resume events:** **0** (both processes exited with `executed == plan job_count`; no queue residual).

## Final counts (pass / fail / n)

| Job | plan jobs | n (state lines) | pass | fail | pass rate | exit |
|-----|----------:|----------------:|-----:|-----:|----------:|------|
| **t7_master** (`equities_master`) | 147 | **147** | **118** | **29** | 80.3% | clean `finished executed=147` |
| **t8_misc** (3 datasets) | 432 | **432** | **407** | **25** | 94.2% | clean `finished executed=432` |
| **combined** | 579 | **579** | **525** | **54** | 90.7% | both queue-closed |

### misc pass by dataset

| dataset | pass | fail | notes |
|---------|-----:|-----:|-------|
| `equities_investor_types` | **154** | 0 | full plan |
| `markets_short_ratio` | **132** | 0 | full plan |
| `markets_margin_alert` | **121** | **25** | all misc fails |

### fail taxonomy (worker_error)

| Job | HTTP 429 (upstream transient) | D1 CPU limit | HTTP 503 | other |
|-----|------------------------------:|-------------:|---------:|------:|
| master | 22 | 2 | 5 | 0 |
| misc | 19 | 3 | 0 | 3 (D1 long-running import×2, HTTP 0×1) |

Host-side `http_429_count` on `/v1/run` dispatch envelope: **0** for both (429s are Worker→JQ, reported inside worker_error detail).

## Host POST/min (`scripts/report_raw_throughput.py --state-jsonl`)

| State | n_events | **requests_per_min** | window_s | first → last (UTC) | host 429 |
|-------|---------:|---------------------:|---------:|--------------------|---------:|
| `t7_master_exec_state.jsonl` | 147 | **3.58** | 2449.6 | 13:24:40 → 14:05:29 | 0 |
| `t8_misc_exec_state.jsonl` | 432 | **9.93** | 2604.0 | 13:24:21 → 14:07:45 | 0 |

Artifacts: `.glm-logs/cf-backfill/t7_master_throughput.{json,md}`, `t8_misc_throughput.{json,md}`.  
Theoretical upstream page RPM (Worker `RATE_LIMIT_INTERVAL_MS=120`): **500.0** (not host dispatch).

Driver log host_dispatch_rpm matches report:

- master: `requests_per_min=3.58` (`t7_master_exec_run.log`)
- misc: `requests_per_min=9.93` (`t8_misc_exec_run.log`)

## Verdict

| Check | Result |
|-------|--------|
| Both queues fully executed (n == plan) | **PASS** |
| No kill of live jobs | **PASS** |
| No double-start / no other dataset started by G1 | **PASS** |
| Fail-process resume required | **N/A** (clean exit) |
| Segment fail residual (429/D1/503) | **OPEN → G8** (not re-dispatched here) |
| empty COMPLETE invented | **none** |

**Overall G1 close: PASS** (queue close + host rpm measured). Segment-level fail retry is residual, not G1 dual-run.

## Policy notes

- Worker pass ≠ Coverage COMPLETE; seal only with raw+structured (+ receipt path).
- Concurrent other tracks observed while waiting (not owned by G1; not killed): `t5_margin_earn`, `t3_topix`, `t6_deriv_edinet`, `t4b_mb_midhole`.
- This proof only; residual live numbers left for G8.
