# Track A execute — historical raw inject (POST_AEXEC)

**Date:** 2026-08-12  
**Mode:** `--execute` (live CF premium `/v1/run`)  
**Tip baseline:** `8638936` (Track A dry-run infra) → extended execute + week-chunks land `ddbf1e9`  
**ADR:** [`docs/architecture/adr_historical_raw_acceleration.md`](../architecture/adr_historical_raw_acceleration.md)

## Absolute bans respected

- No Mass ON / READY
- No COMPLETE without raw (no fabricated COMPLETE seals from this Track A path)
- Local sqlite = research mirror only (not CF SoT); **no sqlite DB commit**
- No secrets / tokens in logs or this proof
- Worker `pass` ≠ Coverage COMPLETE (honored throughout)

## PRE (local research mirror)

Captured at execute start (`report_raw_throughput.py --label PRE_AEXEC`):

| Metric | Value |
|--------|------:|
| raw_retention_manifests (local) | **0** (remote SoT not mirrored) |
| complete_segments | **404** (pre-A3 window) |
| complete_datasets | **2** (`markets_calendar`, `jsda_tokyo_repo_rates`) |
| stale_datasets | **1** (`markets_margin_interest`) |
| projection | **FRESH** |

Remote D1 `raw_retention_manifests` PRE (wrangler RO): **1488** (complete_m=1449, failed_m=39).

## Infra notes (equities full-month)

Full calendar-month `equities_bars_daily` POSTs often hit **CF Worker limit → HTTP 503 / 1101/1102** (per-day expansions under month range exceed worker budget under load).  
**Mitigations used:**

1. `--week-chunks` / 7d (landed in `ddbf1e9`)  
2. 5-day sub-range curl loop (this session; same `/v1/run` contract)

Subscription floor: **2006-08-12** — earlier dates → HTTP 400 (recorded, continued).

## Execute results (worker pass ≠ COMPLETE)

### 1) `equities_bars_daily`

| Batch | Range / mode | jobs | pass | fail | Notes |
|-------|--------------|-----:|-----:|-----:|-------|
| month #1 | 2004-01→, month | 36 | **4** | 32 | Fail: subscription pre-2006-08-12 |
| month #2 | 2006-09→, month | 48 | **20** | 28 | Fail: mostly HTTP **503** full-month overload |
| week #1 (`ddbf1e9`) | 2008-05→, 7d chunks | 40 | **40** | 0 | Primary ≥36 line |
| **5d subrange (this session)** | 2008-05→2009-02 | 60 | **57** | 3 | 1×503 + 2×500; continued |
| peer weeks | 2006-08-12→2008-04 | ≥41 | **41+** | 0 | Prior peer history |

**Unique full-month worker pass (planner month chunks):** **20** months `2006-09`…`2008-04`  
**Subrange full months (all 5d windows pass):** `2008-05`, `2008-07`…`2009-01` (**8**); partial: `2008-06`, `2009-02`  
**Calendar-month coverage with successful raw inject ≥ 24:** **YES** (20 month-pass + 8+ subrange-full months; week batch 40 alone ≥ 36 jobs)

Subrange rowsInserted sum (worker): **476258**; rawBytes sum: **~317 MB** (host summary; R2 raw is SoT).

### 2) `indices_bars_daily_topix`

| Batch | max-jobs | pass | fail | Segments |
|-------|--------:|-----:|-----:|----------|
| execute #1 | 12–24 | **24** | 0 | `2008-01`…`2009-12` |
| execute #2 | 24 | **24** | 0 | `2010-01`…`2011-12` |
| **Total unique** | | **48** | **0** | 4 years of months |

Month ranges OK (range-mode, small payload).

### 3) `markets_margin_interest` (latest-only STALE attempt)

```text
segment=2026-08  from=2026-08-01 to=2026-08-11  state=pass
detail rowsInserted=4259
```

- Worker **pass** only — **does not** rewrite STALE → COMPLETE  
- C8 freshness / multi-plane gaps remain (see `p1_markets_margin_interest_stale_defer_20260812.md`)  
- Honest residual: dataset remains **STALE** on local/control mirror until full close

## Remote raw_manifests (CF D1 — true raw evidence plane)

| Snapshot | total | complete_m | failed_m | equities_bars_daily n | indices_topix n | margin n |
|----------|------:|-----------:|---------:|----------------------:|----------------:|---------:|
| PRE (AEXEC start) | **1488** | 1449 | 39 | 270 | 253 | 42 |
| Mid (parallel AEXEC) | ~1757–1839 | — | — | — | — | — |
| **POST (this write)** | **1889** | **1788** | **101** | **478** | **355** | **47** |

| Delta PRE→POST | Δ total | Δ equities n | Δ indices n | Δ margin n |
|----------------|--------:|-------------:|------------:|-----------:|
| raw_retention_manifests | **+401** | **+208** | **+102** | **+5** |

Local `report_raw_throughput` still shows `raw_manifests=0` — **expected** (local not D1-synced; mirror only).

## POST local throughput report

Artifacts:

- `docs/proof/raw_throughput_POST_AEXEC_20260812T143225Z.json` / `.md` (this session)
- `docs/proof/raw_throughput_POST_AEXEC_20260812T142910Z.json` / `.md` (peer)
- `docs/proof/remote_raw_POST_AEXEC_snippet.txt` (wrangler RO export)

| Metric (local mirror) | PRE_AEXEC | POST_AEXEC |
|-----------------------|----------:|-----------:|
| raw_retention_manifests | 0 | 0 |
| complete_segments | 404 | **482** (A3 parallel seals — **not** Track A forge; see A3 proofs) |
| complete_datasets | 2 | 2 |
| stale | margin STALE | margin still **STALE** |
| projection | FRESH | FRESH |

Track A focus datasets remain PARTIAL/STALE on structured coverage plane. Raw landed on **R2 + D1 raw_retention_manifests**.

## Failure log (continued without abort)

| Class | Count (approx) | Handling |
|-------|---------------:|----------|
| Subscription pre-2006-08-12 (HTTP 400) | 32 | Recorded; shift from_date ≥ 2006-09 |
| CF 503 / 1101/1102 full month | 27+ | Week / 5d chunks |
| Subrange 503/500 | 3 | Recorded; continue |
| D1 long-running import | 1 | Recorded |

## Commands (token never logged)

```bash
# PRE
python scripts/report_raw_throughput.py --label PRE_AEXEC --format both --out-dir docs/proof

# equities (week chunks preferred under CF limits)
python scripts/ops/cf_premium_backfill.py \
  --track-a --datasets equities_bars_daily \
  --from-date 2006-09-01 --to-date 2023-12-31 \
  --execute --week-chunks --chunk-days 7 --max-jobs 40 --workers 2

# indices
python scripts/ops/cf_premium_backfill.py \
  --track-a --datasets indices_bars_daily_topix \
  --from-date 2008-01-01 --to-date 2011-12-31 \
  --execute --max-jobs 48 --workers 2

# margin latest-only (STALE attempt; no COMPLETE forge)
python scripts/ops/cf_premium_backfill.py \
  --datasets markets_margin_interest --latest-only --max-jobs 1 --execute

# POST
python scripts/report_raw_throughput.py --label POST_AEXEC --format both --out-dir docs/proof
```

Auth: `~/.config/quant-platform/ingestion_run_token` + premium worker URL (default in driver). Never print tokens.

## Artifacts (local logs — not committed)

- `.glm-logs/cf-backfill/aexec_equities*_*.jsonl`
- `.glm-logs/cf-backfill/aexec_equities_subrange.jsonl`
- `.glm-logs/cf-backfill/aexec_indices*_*.jsonl`
- `.glm-logs/cf-backfill/aexec_margin_*`

## Bottom line

| Goal | Result |
|------|--------|
| equities ≥ 24 calendar-month jobs success | **YES** — 20 full-month pass + 8 subrange-full months + 40 week jobs |
| indices 数本〜十数本+ | **YES — 48/48 month pass** |
| margin latest-only execute | **YES — pass** (still STALE; no COMPLETE forge) |
| raw_manifests increase (remote) | **YES — 1488 → 1889 (Δ +401)** |
| worker pass ≠ COMPLETE | Honored throughout |
| COMPLETE dataset count change | **No** (still 2); segment COMPLETE 404→482 is **A3 receipt seals**, not Track A auto-COMPLETE |
