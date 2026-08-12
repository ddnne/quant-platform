# Raw throughput report (POST_AEXEC)

- generated_at: `2026-08-12T14:11:34.150927+00:00`
- label: **POST_AEXEC**
- db: `/Users/taku/GitHub/quant-platform/data/structured/ingestion.sqlite`
- note: Local/research mirror metrics. Not CF control-plane SoT unless this file was synced from D1. Do not treat as sole evidence of COMPLETE.
- companion JSON: `docs/proof/raw_throughput_POST_AEXEC_20260812T141214Z.json`
- remote D1 snippet: `docs/proof/remote_raw_POST_AEXEC_snippet.txt`

## Absolute bans respected

- No Mass ON / READY
- **No COMPLETE claimed for fail jobs**
- Worker `pass` ≠ Coverage `COMPLETE` (seal only with raw+structured + receipt)
- Local sqlite = research mirror, not sole SoT
- No secrets / tokens in this proof
- No second parallel `cf_premium_backfill` process started by this Track A execute agent (reused in-flight run)

## Subscription constraint (J-Quants Premium)

Worker/API returns **HTTP 400** for dates before:

> **2006-08-12 ~** (open-ended upper bound)

Therefore historical execute **must** use `--from-date 2006-08-12` (or later).  
Partial month **2006-08** still fails when the planner emits `2006-08-01..2006-08-31` (start before floor). First clean full months: **2006-09+**.

## Execute waves collected (no double-start)

### Wave 0 (prior, context) — subscription misses

- cmd: `equities_bars_daily` from early history (`2004-…`) `--max-jobs 36` (and retries → state n=66)
- **pass=4 / fail=62**
- pass segments: `2006-09`, `2006-10`, `2006-11`, `2006-12`
- fail reason: almost all `HTTP 400` subscription floor

### Wave 1 (in-flight at agent start; collected only) — subscription-safe

Already running when Track A execute agent attached (`pgrep` hit). **Did not launch a second process.**

```text
.venv/bin/python scripts/ops/cf_premium_backfill.py \
  --track-a \
  --datasets equities_bars_daily \
  --from-date 2006-09-01 \
  --to-date 2023-12-31 \
  --execute \
  --max-jobs 48 \
  --plan-out .glm-logs/cf-backfill/aexec_equities2_plan.json \
  --queue-out .glm-logs/cf-backfill/aexec_equities2_queue.json \
  --state-out .glm-logs/cf-backfill/aexec_equities2_state.jsonl
```

| field | value |
|-------|------:|
| mode | execute |
| queued / executed | 48 / 48 |
| **pass** | **20** |
| **fail** | **28** |

**Pass segments (value; only these count as successful jobs):**

`2006-09` … `2008-04` (20 months continuous)

Worker summary on pass: `{"failed":0,"passed":1,"rowsInserted":0}`  
→ host driver pass; structured D1 insert count 0 (raw plane still advanced — see remote raw).

**Fail segments (NOT COMPLETE):**

`2008-05` … `2010-08` (28 months)

| fail class | n | notes |
|------------|--:|-------|
| HTTP 503 | 27 | worker/edge overload under parallel ingest |
| D1 long-running import | 1 | `Currently processing a long-running import.` (`2010-08`) |

### topix / margin latest

**Not executed** in this window: after wave-1 503 + D1 import pressure there was no safe capacity; dual-start ban also forbids a parallel second driver.

## Remote raw delta (CF D1 SoT for manifests)

| metric | PRE (AEXEC baseline) | POST | Δ |
|--------|---------------------:|-----:|--:|
| raw_retention_manifests total | **1488** | **1593** | **+105** |
| completeness=COMPLETE | 1449 | 1492 | +43 |
| completeness=FAILED | 39 | 101 | +62 |

### equities_bars_daily (remote)

| metric | value |
|--------|------:|
| manifests n | 309 |
| complete_n | 215 |
| sum row_count | 8101966 |

### AEXEC-window manifests (`created_at >= 2026-08-12T22:55+09:00`, equities_bars_daily)

| completeness | n | sum row_count |
|--------------|--:|--------------:|
| COMPLETE | 45 | 1_046_715 |
| FAILED | 62 | 0 |

Honest note: window COMPLETE count (45) > driver pass (20) because prior wave-0 + partial re-ingest / empty COMPLETE shells (row_count=0) also land in the same wall-clock window. **Value for this agent = wave-1 pass=20 only.**

## Coverage COMPLETE (do not over-claim)

| plane | equities_bars_daily COMPLETE segs | note |
|-------|----------------------------------:|------|
| remote D1 | **12** | **unchanged** by this execute |
| local research mirror Track A focus | **12/272** | still PARTIAL |

Local overall `complete_segments` 404→431 (+27) is **not** attributed to Track A execute (parallel receipt/seal work elsewhere; see other proof commits). **Track A does not report those as A-value.**

## Local research-mirror report (auto)

### raw_retention_manifests (local)

| metric | value |
|--------|------:|
| total | 0 |
| COMPLETE | 0 |
| FAILED | 0 |
| sum_row_count | 0 |
| sum_raw_bytes | 0 |

Local mirror still **not** synced for raw manifests — remote is authoritative for raw_n.

### coverage (local)

| metric | value |
|--------|------:|
| complete_segments | 431 |
| partial_segments | 12466 |
| complete_datasets | 2 |
| stale_datasets | 1 |
| complete_dataset_ids | jsda_tokyo_repo_rates, markets_calendar |
| stale_dataset_ids | markets_margin_interest |

### projection

- status: **FRESH**
- generation: `projgen-767c79b919b74c3085e01c255eade424`

### Track A focus (local)

| dataset | status | complete/total segs | records | event_time span |
|---------|--------|--------------------:|--------:|-----------------|
| equities_bars_daily | PARTIAL | 12/272 | 803862 | 2024-01-04T15:00:00+09:00 → 2026-08-10T15:30:00+09:00 |
| indices_bars_daily_topix | PARTIAL | 32/224 | 635 | 2024-01-04T15:00:00+09:00 → 2026-08-10T15:30:00+09:00 |
| markets_breakdown | PARTIAL | 15/164 | 2669153 | 2024-01-04T00:00:00+09:00 → 2026-08-10T00:00:00+09:00 |
| fins_summary | PARTIAL | 5/224 | 6121 | 2024-01-04T09:00:00+09:00 → 2026-08-10T09:00:00+09:00 |
| equities_master | PARTIAL | 94/314 | 7679458 | 2015-01-05T00:00:00+09:00 → 2026-08-12T00:00:00+09:00 |
| markets_margin_interest | STALE | 14/164 | 251470 | 2024-01-12T00:00:00+09:00 → 2025-02-28T00:00:00+09:00 |

## PRE→POST delta (local mirror only)

```json
{
  "raw_manifests_total": 0,
  "raw_manifests_complete": 0,
  "jquants_records_total": 0,
  "complete_segments": 27,
  "complete_datasets": 0,
  "stale_datasets": 0,
  "note": "Positive delta = growth. COMPLETE never auto-claimed by this report. +27 complete_segments is parallel non-A work; not Track A seal."
}
```

## Value summary (Track A execute)

| item | result |
|------|--------|
| Successful jobs (wave-1) | **pass=20** (`equities_bars_daily` 2006-09→2008-04) |
| Failed jobs (wave-1) | **fail=28** (503 / D1 import) — **not COMPLETE** |
| Prior context wave | pass=4 / fail=62 (subscription) |
| remote raw_n | **1488 → 1593** (+105) |
| Coverage COMPLETE (equities_bars_daily) | **no change** (still 12) |
| topix / margin | not run (capacity) |

### Residual for next wave

1. Retry fail band `2008-05`→… with lower `--max-jobs` / cooldown after D1 import settles  
2. Continue `2006-09+` history toward FRESH window with subscription floor enforced  
3. Optional: topix + margin `--latest-only` when worker 503 rate is healthy  
4. Do **not** seal COMPLETE until raw+structured+receipt for each segment

---
Evidence closure: COMPLETE only with raw+structured. This report never forges COMPLETE/READY/Mass.
