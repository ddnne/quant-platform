# P0 multi-track wave2 — G8 closed circuit (T13+T14+T15) 2026-08-13

**Mass / READY / Phase7:** **NO-GO / OFF**  
**empty COMPLETE:** none invented  
**kill acq jobs:** none (peer `t7_master` / `t8_misc` / `t5_margin_earn` left running)

**Repo tip at task start:** `4342091` / prior residual tip `dbb3590`  
**Session PRE baseline (~22:58 local / task brief):** raw **n≈6447** / COMPLETE completeness **c≈5559** / COMPLETE segs **510**

## Scope (closed circuit — no segment rewrite)

| Step | Tool | Result |
|------|------|--------|
| T13 observed_* | `scripts/ops_reeval_observed_window.py` ×5 | bars / breakdown / fins / topix / margin — all C8 **pass**; no COMPLETE claim |
| T13 freshness | `scripts/ops_reeval_freshness.py` | projection **FRESH** `age_seconds=0` |
| T14 host rpm | state jsonl + `measure_dispatch_rpm` / `report_raw_throughput --state-jsonl` | samples below |
| T14 remote Δ | wrangler D1 `quant-ingest --remote` | raw PRE→POST + COMPLETE segs Δ |
| T15 residual | `docs/phase62_residual_status.md` | live-sync this pass |

**Forbidden held:** Mass OFF; no empty COMPLETE; no kill of acq jobs; Phase7 OFF.

## Host POST/min (state jsonl sample)

Host = POST `/v1/run` only. Upstream JQ page theory ≈ **500**/min @ Worker 120ms.

| State jsonl | n_events | requests_per_min | window_s | first → last (UTC) | 429 |
|-------------|---------:|-----------------:|---------:|--------------------|----:|
| `p0_mb_solo_state.jsonl` | 409 | **10.97** | 2230.9 | 12:20:35 → 12:57:46 | 0 |
| `p0_bars_solo_state.jsonl` | 280 | **6.22** | 2692.2 | 12:58:06 → 13:42:58 | 0 |
| `p0_fins_paced_state.jsonl` | 102 | **1.15** | 5256 | 12:14:13 → 13:41:49 | 0 |
| `p0_topix3_state.jsonl` w1 (192) | 192 | **93.48** | 122.6 | 13:33:26 → 13:35:28 | 0 |
| `p0_topix3_state.jsonl` w2 (192) | 192 | **62.79** | 182.5 | 13:44:36 → 13:47:39 | 0 |
| `p0_topix3_state.jsonl` full | 384 | 26.94 | 852.9 | 13:33:26 → 13:47:39 | 0 |
| `t4_topix_exec_state.jsonl` (peer) | 192 | **142.41** | 80.5 | 13:24:20 → 13:25:41 | 0 |
| `t7_master_exec_state.jsonl` (live) | ~136 | **3.65** | ~2216 | 13:24:40 → ~14:01 | 0 |
| `t8_misc_exec_state.jsonl` (live) | ~393 | **10.50** | ~2240 | 13:24:21 → ~14:01 | 0 |
| **merged** mb+bars+topix3+fins | **1175** | **12.56** | 5606 | 12:14:13 → 13:47:39 | 0 |
| **merged + peers** t4/t7/t8 | **1896** | **17.63** | 6448 | 12:14:13 → 14:01:40 | 0 |

`report_raw_throughput --state-jsonl p0_bars_solo_state.jsonl` → host_rpm **6.22** (artifact: `.glm-logs/cf-backfill/g8_wave2_throughput_bars.{json,md}`; local mirror raw_n=0 — remote D1 is SoT).

## Remote D1 raw_n / COMPLETE segs

DB: `quant-ingest` (`npx wrangler d1 execute quant-ingest --remote`).

```sql
SELECT COUNT(*) n, SUM(CASE WHEN completeness='COMPLETE' THEN 1 ELSE 0 END) c
FROM raw_retention_manifests;

SELECT status, COUNT(*) n FROM coverage_segments GROUP BY status;
```

| Metric | PRE (task brief ~22:58) | POST (~14:01:48Z) | Δ |
|--------|------------------------:|------------------:|--:|
| `raw_retention_manifests` total (`raw_n`) | **6447** | **6477** | **+30** |
| raw completeness=COMPLETE | **5559** | **5589** | **+30** |
| raw FAILED | — | **888** | — |
| `coverage_segments` COMPLETE | **510** | **510** | **0** |
| `coverage_segments` PARTIAL | — | 12047 | — |
| `coverage_segments` UNKNOWN | — | 384 | — |

Mid-circuit snapshot (~14:00:37Z): raw **6468** / c **5580** (peer t7/t8 still writing).  
**COMPLETE segs Δ=0 honesty:** this circuit is reeval + freshness + throughput measurement only — **no A3 seal**, **no empty COMPLETE**.

### raw by focus dataset (POST)

| dataset | n manifests | complete_m | failed_m |
|---------|------------:|-----------:|---------:|
| `equities_bars_daily` | 2000 | 1638 | 362 |
| `markets_breakdown` | 1056 | 696 | 360 |
| `fins_summary` | 304 | 198 | 106 |
| `indices_bars_daily_topix` | 1190 | 1189 | 1 |
| `markets_margin_interest` | 76 | 75 | 1 |
| `equities_master` (peer t7) | 198 | 175 | 23 |

## `ops_reeval_observed_window` (POST)

No segment rewrite / no COMPLETE claim. SUCCESS receipts with `raw_row_count>0` only. `--today 2026-08-13 --freshness-days 7`.

| dataset | status | observed_start | observed_end | C8 |
|---------|--------|----------------|--------------|----|
| `equities_bars_daily` | **PARTIAL** | **`2008-05-01`** | `2026-08-12` | **pass** lag **1** |
| `markets_breakdown` | **PARTIAL** | **`2015-03-26`** | `2026-08-12` | **pass** lag **1** |
| `fins_summary` | **PARTIAL** | **`2014-01-01`** | `2026-08-12` | **pass** lag **1** |
| `indices_bars_daily_topix` | **PARTIAL** | **`2008-01-01`** | **`2026-08-13`** | **pass** lag **0** |
| `markets_margin_interest` | **PARTIAL** | `2024-01-01` | **`2026-08-13`** | **pass** lag **1** (`source=receipt_observed_end`) |

Segment COMPLETE counts (POST; **untouched by reeval**):

| dataset | COMPLETE segs | PARTIAL segs |
|---------|--------------:|-------------:|
| bars | 12 | 260 |
| breakdown | 32 | 132 |
| fins_summary | 5 | 219 |
| topix | 32 | 0 |
| margin | 17 | 147 |

## `ops_reeval_freshness` → FRESH age=0

| Field | POST |
|-------|------|
| status | **FRESH** |
| `generated_at` | **`2026-08-13T14:01:21.532627+00:00`** |
| `age_seconds` | **0** |
| `projection_generation_id` | **`projgen-8927d3b38aae41c18dc740df9a7ed6ad`** |
| publisher | `scripts/ops_reeval_freshness.py` |
| COMPLETE segments | **untouched** |

Local mirror: `data/ops/projection_meta.json`.

## last_run (this closed circuit)

| Event | UTC |
|-------|-----|
| Task start tip | `4342091` (residual tip `dbb3590`) |
| Live D1 PRE-ish measure | 2026-08-13T14:00:37Z (raw 6468/5580, COMPLETE 510) |
| reeval bars | 2026-08-13T14:00:57Z |
| reeval breakdown | 2026-08-13T14:01:03Z |
| reeval fins | 2026-08-13T14:01:08Z |
| reeval topix | 2026-08-13T14:01:13Z |
| reeval margin | 2026-08-13T14:01:18Z |
| freshness FRESH age=0 | **2026-08-13T14:01:21Z** gen=`projgen-8927d3b38aae41c18dc740df9a7ed6ad` |
| POST D1 + rpm seal | 2026-08-13T14:01:48Z (raw **6477** / c **5589** / COMPLETE **510**) |
| Peer acq still live | t7_master, t8_misc, t5_margin_earn (**not killed**) |

## Explicit non-claims

- No Mass / READY / Phase7 ON  
- No fabricated empty COMPLETE segments or dataset COMPLETE  
- Worker **pass ≠** Coverage COMPLETE (bars still **12** COMPLETE months; fins **5**)  
- Host POST/min ≠ upstream JQ page rate  
- COMPLETE **510** unchanged this circuit (peer seals earlier; this pass measurement-only)  
- raw Δ **+30** is concurrent peer write (t7/t8/t5), not invented seals

## Commands (replay)

```bash
# observed windows (no segment rewrite)
for ds in equities_bars_daily markets_breakdown fins_summary \
          indices_bars_daily_topix markets_margin_interest; do
  .venv/bin/python scripts/ops_reeval_observed_window.py \
    --dataset "$ds" --today 2026-08-13 --freshness-days 7
done

# projection FRESH age=0
.venv/bin/python scripts/ops_reeval_freshness.py

# remote SoT
npx wrangler d1 execute quant-ingest --remote \
  --config=platform/workers/ingestion-premium/wrangler.toml --json \
  --command "SELECT COUNT(*) n, SUM(CASE WHEN completeness='COMPLETE' THEN 1 ELSE 0 END) c FROM raw_retention_manifests"
npx wrangler d1 execute quant-ingest --remote \
  --config=platform/workers/ingestion-premium/wrangler.toml --json \
  --command "SELECT status, COUNT(*) n FROM coverage_segments GROUP BY status"

# host rpm sample
.venv/bin/python scripts/report_raw_throughput.py \
  --state-jsonl .glm-logs/cf-backfill/p0_bars_solo_state.jsonl \
  --format both --out-dir .glm-logs/cf-backfill
```
