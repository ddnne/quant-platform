# G4 / T4 — markets_breakdown residual week-chunks + raw seal close (2026-08-14)

**Mass / READY / Phase7:** still **NO-GO / OFF**  
**empty COMPLETE:** **0** (`receipt_run_id` null/0 = 0)  
**Worker pass ≠ Coverage COMPLETE**  
**prefix:** `w0713_t4_mb_*` · workers **2** · `--general-rpm 495`

## Goal

Close residual `markets_breakdown` history months that were PARTIAL with raw evidence:

1. Residual week-chunk backfill (`cf_premium_backfill`) for densify / 429 retry.
2. R2 week-chunk raw → local raw digest + structured upsert (empty-raw ban).
3. Signed receipts + fail-closed publish (raw-required only).
4. After full publish, re-run `ops_reeval_observed_window --dataset markets_breakdown`.

## PRE (remote D1 `quant-ingest`, session start)

| metric | value |
|--------|------:|
| `markets_breakdown` COMPLETE segs | **32** (`2024-01`…`2026-08`) |
| `markets_breakdown` PARTIAL segs | **132** (`2013-01`…`2023-12`) |
| dataset status | **PARTIAL** |
| `observed_start` / `observed_end` | **`2024-01-01`** / `2026-08-12` (regressed after prior full publish) |
| raw manifests (dataset) | n=**1074** / c=**714** |
| global `raw_retention_manifests` | **7940** |
| global COMPLETE segs | **585** (live tip moved under peer waves during session) |
| SUCCESS nz receipt calendar 2015-03-26…2023-12 | continuous **except** GW2019 hole `2019-04-30`…`2019-05-05` (expected empty) |

## 1) Residual week-chunk backfill

```text
.venv/bin/python -u scripts/ops/cf_premium_backfill.py \
  --datasets markets_breakdown \
  --from-date 2015-03-01 --to-date 2015-12-31 \
  --week-chunks --chunk-days 7 \
  --execute --workers 2 --general-rpm 495 --max-jobs 0 \
  --sleep-on-retry 3 \
  --plan-out  .glm-logs/cf-backfill/w0713_t4_mb_residual_plan.json \
  --queue-out .glm-logs/cf-backfill/w0713_t4_mb_residual_queue.json \
  --state-out .glm-logs/cf-backfill/w0713_t4_mb_residual_state.jsonl
```

| field | value |
|-------|------:|
| plan / executed | **44 / 44** |
| **pass / fail** | **35 / 9** |
| fail taxonomy | all **transient HTTP 429** (shared general pool with peers) |
| host POST/min | **10.11** (window ≈255s) |
| sum `rowsInserted` | **561_352** |
| PID | **87338** (natural exit) |

### 429 retry

| wave | range | workers / rpm | pass / fail | rowsInserted |
|------|-------|---------------|------------:|-------------:|
| retry_a | 2015-03-15…2015-04-25 | 2 / 495 | 1 / 5 | 0 |
| retry_b | 2015-12-13…2015-12-31 | 1 / 200 | 0 / 3 | 0 |
| retry2 | 2015-03-15…2015-04-25 | 1 / 60 | **5 / 1** | **54_475** |
| retry2b | 2015-12-13…2015-12-31 | 1 / 60 | 0 / 3 | 0 |

Residual 429 tails under multi-track contention; prior receipt-plane continuity already covered trading days (only GW2019 empty). **Worker pass ≠ Coverage COMPLETE.**

Artifacts (local): `.glm-logs/cf-backfill/w0713_t4_mb_*`.

## 2) Seal prep — R2 week-chunk → local raw + structured

Driver: `.glm-logs/w0713_t4_mb/seal_from_r2.py`  
(week-window dedupe; prefer single large run ≥50k rows; digest raw ≤20MB for issue_receipts 25MB ban)

| field | value |
|-------|------:|
| floor / ceil | **2015-03** / **2023-12** (2024+ already COMPLETE) |
| candidates with week-raw | **105** months |
| selected this wave | **36** (`2015-04`…`2018-03`) |
| ready (raw+struct) | **36 / 36** |
| skip | `2015-03` thin (`sum_rows` &lt; 20k; source starts ~2015-03-26) |

Example local struct after upsert (natural-key dedupe):

| segment | structured rows (local) |
|---------|------------------------:|
| 2015-04 | **76_303** (21 trading days) |
| 2015-05 | **65_650** |
| 2016-01 | **69_596** |
| 2018-03 | **68_223** |

Digest raw examples under `data/raw/jquants/2026/08/14/markets_breakdown_from=…_from_r2_run*.json` (usable non-empty; empty-raw ban held).

## 3) Signed receipts + publish (raw only)

```text
# bulk issue (stdout buffered; completed with run_ids 900928–900962)
.venv/bin/python -u scripts/issue_receipts_parallel.py \
  --datasets markets_breakdown --struct-hint --limit 40 --workers 6 --order asc

# serial close for residual segment (2015-04 run_id 900963)
.venv/bin/python -u scripts/issue_receipts_parallel.py \
  --datasets markets_breakdown --segment-id 2015-04 --limit 1 --workers 2 --order asc
```

| metric | PRE | POST |
|--------|----:|-----:|
| Local `markets_breakdown` COMPLETE | **33** (32 tip + peer `2023-12`) | **69** |
| This wave seals | | **+36** (`2015-04`…`2018-03`) |
| Receipt run_ids | | **900928–900963** |
| Reconciliation | | `raw_row_count == structured_row_count` |
| empty COMPLETE | | **0** |

### Publish (fail-closed)

```text
.venv/bin/python -u scripts/publish_ops_projection.py \
  --db data/structured/ingestion.sqlite --refresh-coverage --apply-remote
```

| step | result |
|------|--------|
| first apply | UNIQUE constraint mid-batch (peer concurrent publish race) — **retried** |
| retry apply | **`remote projection applied`** |
| guard | `local COMPLETE ≥ remote` held on successful apply |
| Remote total COMPLETE | **933** |
| Remote `markets_breakdown` COMPLETE | **69** / PARTIAL **95** |

## 4) `ops_reeval_observed_window` (required after full publish)

```text
.venv/bin/python scripts/ops_reeval_observed_window.py \
  --dataset markets_breakdown --today 2026-08-14 --freshness-days 7
```

| field | PRE (post-publish residual) | POST reeval |
|-------|----------------------------:|------------:|
| status | PARTIAL | **PARTIAL** |
| **observed_start** | `2015-04-01` | **`2015-03-26`** |
| **observed_end** | `2026-08-12` | **`2026-08-13`** |
| C8 | pass lag 2 | **pass** lag **1** |
| nz SUCCESS receipts | — | n=**678**, sum_raw=**11_628_344**, window **2015-03-26…2026-08-13** |
| coverage_segments | — | **untouched by reeval** |

Log: `.glm-logs/w0713_t4_mb/reeval.log`.

## POST summary

| metric | PRE (task / session start) | POST |
|--------|---------------------------:|-----:|
| **breakdown COMPLETE segs** | **32** | **69** (**+37** incl. peer `2023-12`; this wave **+36**) |
| breakdown PARTIAL segs | 132 | **95** |
| breakdown `observed_start` | `2024-01-01` (regressed) | **`2015-03-26`** |
| breakdown `observed_end` | `2026-08-12` | **`2026-08-13`** |
| C8 | — | **pass** lag **1** |
| empty COMPLETE | 0 | **0** |
| dataset COMPLETE claim | no | **no** (still PARTIAL) |
| Mass / READY / Phase7 | NO-GO / OFF | **NO-GO / OFF** |

Sealed months this wave: **`2015-04` … `2018-03`** (36 calendar months).  
Remaining PARTIAL: `2013-01`…`2015-03` (empty/pre-source or thin) + `2018-04`…`2023-11` (raw on R2; next seal waves) + honest non-claims.

## Explicit non-claims / bans held

- **No** Mass / READY / Phase7 ON  
- **No** empty-raw COMPLETE (`{"data":[]}` rejected; `receipt_run_id` always set)  
- **No** dataset-level COMPLETE for `markets_breakdown`  
- Worker pass ≠ Coverage COMPLETE  
- No secrets logged  
- Peer acq jobs **not killed**

## Operator repro

```bash
# residual week-chunks
.venv/bin/python -u scripts/ops/cf_premium_backfill.py \
  --datasets markets_breakdown \
  --from-date 2015-03-01 --to-date 2015-12-31 \
  --week-chunks --chunk-days 7 \
  --execute --workers 2 --general-rpm 495 --max-jobs 0 \
  --plan-out  .glm-logs/cf-backfill/w0713_t4_mb_residual_plan.json \
  --queue-out .glm-logs/cf-backfill/w0713_t4_mb_residual_queue.json \
  --state-out .glm-logs/cf-backfill/w0713_t4_mb_residual_state.jsonl

# R2 → local seal prep
T4_MAX_SEAL=36 T4_SINGLE_RUN_MIN_ROWS=50000 \
  .venv/bin/python -u .glm-logs/w0713_t4_mb/seal_from_r2.py

# receipts + publish + reeval
.venv/bin/python -u scripts/issue_receipts_parallel.py \
  --datasets markets_breakdown --struct-hint --limit 40 --workers 6 --order asc
.venv/bin/python -u scripts/publish_ops_projection.py \
  --db data/structured/ingestion.sqlite --refresh-coverage --apply-remote
.venv/bin/python scripts/ops_reeval_observed_window.py \
  --dataset markets_breakdown --today 2026-08-14 --freshness-days 7
```

## Verdict

| Check | Result |
|-------|--------|
| Residual week-chunk execute | **PASS** (44; 35p + retry2 densify; residual 429 under peer load) |
| Seal raw-only 36 months | **PASS** |
| COMPLETE PRE **32** → POST **69** | **PASS** (+36 this wave) |
| empty COMPLETE | **0** |
| reeval observed_* + C8 | **PASS** (`2015-03-26`…`2026-08-13`, lag 1) |
| Mass / Phase7 | **NO-GO / OFF** |

**Overall: PASS** (raw seal close for 2015-04…2018-03; observed window restored after publish).
