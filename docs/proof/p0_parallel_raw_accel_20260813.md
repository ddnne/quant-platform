# P0 parallel raw acceleration (near-ceiling 495 RPM) — 2026-08-13

**Mass / READY / empty-raw COMPLETE:** **NO-GO**  
**Worker pass ≠ Coverage COMPLETE**  
**Rate change base:** `aa43389` (495 RPM host, Worker 120 ms ≈ 500/min)  
**Worker deploy:** `fc5f1492-52f9-4827-bc36-1482b28d782b` (`INGEST_CONCURRENCY=6`)

## Dual-run / collision policy

| rule | result |
|------|--------|
| Same dataset dual `cf_premium_backfill` | **avoided** (general datasets **serialized** solo after multi-general 429 thrash) |
| general × fins parallel | **yes** — fins paced on isolated pool while general ran |
| Multi-general concurrent (bars+MB+topix workers 10/8/6) | **abort** — isolate-local RateLimiter multiplies RPM → mass HTTP 429 |

Lesson: host `--workers` > ~2 concurrent `/v1/run` on separate isolates multiplies upstream budget. Solo general `workers=2` + fins paced held near-ceiling **without** thrash.

## PRE (remote D1 `quant-ingest`)

Artifact: `.glm-logs/cf-backfill/p0_parallel_PRE_20260813T120732Z.json`  
t0 (rate495 solo chain): **2026-08-13T12:13:39Z** / chain end **13:43:09Z** (~1.5 h)

| metric | value |
|--------|------:|
| `raw_retention_manifests` total | **3535** |
| equities_bars_daily raw n / sum_rows | 1404 / 23_380_917 |
| markets_breakdown raw n / sum_rows | 148 / 2_009_038 |
| fins_summary raw n / sum_rows | 197 / 68_288 |
| indices_bars_daily_topix raw n / sum_rows | 420 / 11_662 |
| bars `observed_start` | 2008-05-01 |
| breakdown `observed_start` | 2024-01-01 (regressed on coverage row) |
| fins `observed_start` | 2024-01-01 (regressed) |
| topix `observed_start` | 2008-01-01 |

## Bars 2004–2008-04 smoke → DEFER

Smoke only (direct `/v1/run`, not dual driver):  
`.glm-logs/cf-backfill/p0_bars_smoke_2004_2008_20260813T120801Z.jsonl`

| range | status | rowsInserted | rawBytes | verdict |
|-------|--------|-------------:|---------:|---------|
| 2004-01-05..09 | **fail** | — | — | OOS / subscription |
| 2006-08-13..18 | pass | 0 | 72 | empty `data[]` |
| 2007-06-01..05 | pass | 0 | 60 | empty |
| 2008-04-01..05 | pass | 0 | 60 | empty |
| 2008-05-06..08 | pass | **4988** | ~3.3MB | first nz control |

→ **DEFER** pre-2008-05; do not move `observed_start`.

## Execute results

### 1. `markets_breakdown` week-chunks 2016-03 → 2026-04 (general solo)

```text
--execute --week-chunks --chunk-days 7 --workers 2 --general-rpm 495 --max-jobs 0
```

| field | value |
|-------|------:|
| executed | **409 / 409** |
| pass / fail | **409 / 0** |
| rowsInserted sum (worker detail) | **7_478_872** |
| host_dispatch_rpm | **10.97** req/min (POST `/v1/run`) |
| window | 2231 s |
| http_429 host | **0** |

Upstream pages paced by Worker **120 ms → theoretical 500/min**.

### 2. `equities_bars_daily` mid-hole PARTIAL 2008-05 → 2023-12 (general solo after MB)

```text
--execute --week-chunks --chunk-days 7 --workers 2 --general-rpm 495 --max-jobs 280
```

| field | value |
|-------|------:|
| executed | **280** |
| pass / fail | **264 / 16** |
| rowsInserted sum | **3_081_199** |
| host_dispatch_rpm | **6.22** |
| fail shape | mostly transient 429 exhausted inside worker (12); D1/exception 3; HTTP 0 (1) |

Earlier multi-process wave0 also contributed bars raw (see PRE→POST).

### 3. `indices_bars_daily_topix` residual months

| wave | executed | pass | host_rpm |
|------|---------:|-----:|---------:|
| topix_exec (max 96, pre-rate) | 96 | 96 | 50.03 |
| topix2 (max 96, multi-general) | 96 | 96 | 143.24 |
| topix3 full residual 2008–2023 | **192** | **192** | **93.48** |

### 4. `fins_summary` paced (fins pool, short 429 backoff)

```text
month loop sleep_ok=6s sleep_429=18s max_retry=4  (2016-01 → 2023-12, 96 months)
```

| field | value |
|-------|------:|
| unique months | **96** |
| final pass / fail | **95 / 1** |
| rowsInserted sum (unique pass) | **151_811** |
| host jobs/min | **~1.2** (serial paced; fins budget isolated) |

## Measured RPM (proof)

| layer | measured | note |
|-------|----------|------|
| Worker floor | **120 ms** | deploy `INGEST_CONCURRENCY=6` → **≈500 upstream req/min** theoretical |
| Host general RPM cap | **495** | driver default post-`aa43389` |
| MB solo host POST rpm | **10.97** | jobs long; pagination dominates |
| Bars solo host POST rpm | **6.22** | heavy week chunks |
| Topix3 host POST rpm | **93.48** | light months |
| Fins paced host jobs/min | **~1.2** | intentional; short 429 backoff only |
| Multi-general anti-pattern | host ~150 job/min with **mass 429** | **rejected** |

**raw_n growth rate:** PRE 3535 → POST **6118** (**+2583** in ~1.49 h) ≈ **1732 raw manifests / hour**.

## POST (remote D1)

Artifact: `.glm-logs/cf-backfill/p0_parallel_POST_20260813T134329Z.json`

### raw_retention_manifests

| dataset | PRE n | POST n | Δ n | PRE sum_rows | POST sum_rows |
|---------|------:|-------:|----:|-------------:|--------------:|
| **total** | **3535** | **6118** | **+2583** | — | — |
| equities_bars_daily | 1404 | 2000 | +596 | 23_380_917 | 27_323_787 |
| markets_breakdown | 148 | 1056 | +908 | 2_009_038 | 11_753_194 |
| fins_summary | 197 | 304 | +107 | 68_288 | 234_420 |
| indices_bars_daily_topix | 420 | 998 | +578 | 11_662 | 23_164 |

### SUCCESS receipts `raw_row_count>0`

| dataset | PRE n_nz | POST n_nz | PRE sum_raw | POST sum_raw | min_nz | max_nz |
|---------|---------:|----------:|------------:|-------------:|--------|--------|
| equities_bars_daily | 966 | 1301 | 17_158_110 | 21_026_871 | **2008-05-01** | 2026-08-12 |
| markets_breakdown | 88 | 623 | 1_195_763 | 10_816_994 | **2015-03-26** | 2026-08-12 |
| fins_summary | 68 | 170 | 53_502 | 216_430 | **2014-01-01** | 2026-08-12 |
| indices_bars_daily_topix | 399 | 964 | 11_662 | 23_164 | **2008-01-01** | 2026-08-13 |

### `dataset_coverage` after `ops_reeval_observed_window.py`

| dataset | status | observed_start | observed_end |
|---------|--------|----------------|--------------|
| equities_bars_daily | PARTIAL | **2008-05-01** (unchanged) | 2026-08-12 |
| markets_breakdown | PARTIAL | **2015-03-26** | 2026-08-12 |
| fins_summary | PARTIAL | **2014-01-01** | 2026-08-12 |
| indices_bars_daily_topix | PARTIAL | **2008-01-01** | **2026-08-13** |

### coverage_segments (no empty-raw COMPLETE claimed by this pass)

| dataset | COMPLETE | PARTIAL |
|---------|---------:|--------:|
| equities_bars_daily | 12 | 260 |
| markets_breakdown | 32 | 132 |
| fins_summary | 5 | 219 |
| indices_bars_daily_topix | 32 | 192 |

Worker pass ≠ seal. No Mass / READY.

## Explicit non-claims

- No equities_bars_daily `observed_start` < 2008-05-01  
- No COMPLETE fabrication / empty-raw COMPLETE  
- No Mass / READY / Phase7 ON  
- Host job rpm ≠ upstream JQ rpm (worker 120 ms is the ~500/min proof surface)  
- Residual: bars 16 fail weeks retryable; fins 1 month residual; planner still queues PARTIAL history beyond this wave

## Acceptance

| gate | result |
|------|--------|
| Pull rate change then execute | **PASS** (`aa43389` + worker deploy) |
| Parallel general/fins pools without same-dataset dual | **PASS** (after 429 thrash fix) |
| Near-ceiling pacing (not low-rate park) | **PASS** (495 / 120 ms; short 429 backoff) |
| raw_n PRE→POST growth proof | **PASS** (+2583) |
| bars 2004–2008-04 DEFER | **PASS** |
| No empty-raw COMPLETE | **PASS** |
