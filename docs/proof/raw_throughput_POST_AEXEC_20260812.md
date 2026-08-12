# Track A execute — historical raw inject (POST_AEXEC)

**Date:** 2026-08-12  
**Mode:** `--execute` (live CF premium `/v1/run`)  
**Tip baseline:** `8638936` (Track A dry-run infra)  
**ADR:** [`docs/architecture/adr_historical_raw_acceleration.md`](../architecture/adr_historical_raw_acceleration.md)

## Absolute bans respected

- No Mass ON / READY
- No COMPLETE without raw (no fabricated COMPLETE seals)
- Local sqlite = research mirror only (not CF SoT); **no sqlite DB commit**
- No secrets / tokens in logs or this proof
- Worker `pass` ≠ Coverage COMPLETE

## PRE (local research mirror)

Captured at execute start (`report_raw_throughput.py --label PRE_AEXEC`):

| Metric | Value |
|--------|------:|
| raw_retention_manifests (local) | **0** (remote SoT not mirrored) |
| complete_segments | **404** |
| complete_datasets | **2** (`markets_calendar`, `jsda_tokyo_repo_rates`) |
| stale_datasets | **1** (`markets_margin_interest`) |
| projection | **FRESH** |

Remote D1 `raw_retention_manifests` baseline (dry-run proof / snippet): **~1488**.

## Infra fix required for equities full-month dispatch

Full calendar-month `equities_bars_daily` POSTs hit **CF Worker resource limit 1102 → HTTP 503** (month of per-day expansions exceeds worker budget). Week ranges succeed.

### Code change (this commit)

- `BackfillPlanner(prefer_month_chunks_for_today=False)` → `_week_chunks` for today-mode
- CLI: `scripts/ops/cf_premium_backfill.py --week-chunks --chunk-days 7`
- Coverage `segment_id` remains **YYYY-MM** (identity unchanged)

## Execute results (queue SoT; worker pass ≠ COMPLETE)

### 1) `equities_bars_daily` (2004–2023 focus)

| Batch | Range / mode | max-jobs | pass | fail | Notes |
|-------|--------------|--------:|-----:|-----:|-------|
| month #1 | 2004-01→ earliest pending, month chunks | 36 | **4** | 32 | Fail: J-Quants plan starts **2006-08-12** (HTTP 400 subscription) |
| month #2 | 2006-09→, month chunks | 48 | **20** | 28 | Fail: mostly HTTP **503 / 1102** full-month overload |
| **week #1** | 2008-05→, `--week-chunks 7d` | **40** | **40** | 0 | **Target line met** (36+ bars jobs) |
| peer week hist | 2006-08-12→2008-04, week | ≥41 | **41+** | 0 | Additional history (same infra) |

**Bars jobs success (this session, queue-backed):**  
- Month pass: **24** unique months (2006-09…2008-04)  
- Week pass: **40** (primary 36+ line)  
- **Total worker-pass jobs ≥ 64** (4+20+40); week batch alone = **40 ≥ 36**

Subscription floor: **2006-08-12** — jobs before that date are expected fail (recorded, continued).

### 2) `indices_bars_daily_topix`

| Batch | max-jobs | pass | fail |
|-------|--------:|-----:|-----:|
| execute | **12** | **12** | 0 |

Month ranges OK (range-mode, small payload). State file may show extra peer smoke lines; **queue SoT = 12/12 pass**.

### 3) `markets_margin_interest` (latest-only STALE attempt)

```text
segment=2026-08  from=2026-08-01 to=2026-08-11  state=pass
detail rowsInserted=4259
```

- Worker **pass** only — **does not** rewrite STALE → COMPLETE  
- C8 freshness / monthly receipt identity gaps remain (see `p1_markets_margin_interest_stale_defer_20260812.md`)  
- Honest residual: dataset remains **STALE** on local mirror until full multi-plane close

## Remote raw_manifests (CF D1 export — true raw evidence plane)

| Snapshot | total | equities_bars_daily | indices_bars_daily_topix | markets_margin_interest |
|----------|------:|--------------------:|-------------------------:|------------------------:|
| PRE (dry-run era) | ~1488 | — | — | — |
| Mid-execute (~23:12 JST) | 1595 | 311 | 253 | 42 |
| POST (end of AEXEC window) | **1757** | **411** | **291** | **46** |

| Delta (mid→POST) | Δ total | Δ equities | Δ indices | Δ margin |
|------------------|--------:|-----------:|----------:|---------:|
| raw_retention_manifests | **+162** | **+100** | **+38** | **+4** |

Approx PRE(~1488)→POST(1757): **~+269** remote manifests.

Equities nonzero raw in AEXEC window: **100+** COMPLETE manifests with multi‑MB `raw_bytes` (example ~30MB / ~45k rows per week).  
Local `report_raw_throughput` still shows `raw_manifests=0` — **expected** (local not D1-synced).

## POST local throughput report

Artifacts:

- `docs/proof/raw_throughput_POST_AEXEC_20260812T142910Z.json`
- `docs/proof/raw_throughput_POST_AEXEC_20260812T142910Z.md`

| Metric (local mirror) | POST |
|-----------------------|-----:|
| raw_retention_manifests | 0 |
| complete_segments | 480 (mirror drift; **not** claimed as AEXEC COMPLETE seal) |
| complete_datasets | 2 |
| stale | `markets_margin_interest` still **STALE** |
| projection | FRESH |

Track A focus remains PARTIAL/STALE on local structured plane — raw landed on **R2 + D1 manifests**, not full local COMPLETE closure.

## Failure log (continued without abort)

| Class | Count (approx) | Handling |
|-------|---------------:|----------|
| Subscription pre-2006-08-12 (HTTP 400) | 32+ | Recorded; shift from_date to plan start |
| CF 1102 / HTTP 503 full month | 27+ | Mitigated via `--week-chunks` |
| D1 long-running import | 1 | Recorded; retry later |

## Commands (token never logged)

```bash
# PRE
python scripts/report_raw_throughput.py --label PRE_AEXEC --format both --out-dir docs/proof

# equities (week chunks — required under CF limits)
python scripts/ops/cf_premium_backfill.py \
  --datasets equities_bars_daily \
  --from-date 2008-05-01 --to-date 2023-12-31 \
  --execute --week-chunks --chunk-days 7 --max-jobs 40 --workers 2

# indices
python scripts/ops/cf_premium_backfill.py \
  --datasets indices_bars_daily_topix \
  --from-date 2008-01-01 --to-date 2023-12-31 \
  --execute --max-jobs 12 --workers 2

# margin latest-only (STALE attempt)
python scripts/ops/cf_premium_backfill.py \
  --datasets markets_margin_interest --latest-only --max-jobs 1 --execute

# POST
python scripts/report_raw_throughput.py --label POST_AEXEC --format both --out-dir docs/proof
```

Auth: `~/.config/quant-platform/ingestion_run_token` + premium worker URL (default in driver).  
Export metrics used `data_export_token` via `/v1/export/d1` (not printed).

## Artifacts (local logs — not committed)

- `.glm-logs/cf-backfill/aexec_equities*_*.jsonl`
- `.glm-logs/cf-backfill/aexec_eq_week_*`
- `.glm-logs/cf-backfill/aexec_indices_*`
- `.glm-logs/cf-backfill/aexec_margin_*`
- `.glm-logs/cf-backfill/aexec_remote_manifests_POST.json`

## Bottom line

| Goal | Result |
|------|--------|
| equities bars jobs success ≥ 36 | **YES — 40/40 week batch** (+ prior month passes) |
| indices ≥ 12 | **YES — 12/12** |
| margin latest-only execute | **YES — pass** (still STALE; no COMPLETE forge) |
| raw_manifests increase (remote) | **YES — +162 mid→POST; ~+269 vs dry-run PRE** |
| worker pass ≠ COMPLETE | Honored throughout |
