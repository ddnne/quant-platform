# P0 multi-track throughput — bars / fins / topix chain (2026-08-13)

**Mass / READY / Phase7:** **NO-GO / OFF**  
**empty COMPLETE:** none invented this pass  
**kill running jobs:** none (bars/fins/topix left to finish; dual false-resume noted below)

**Repo tip at task start (pull):** `bde0dd2` (already past `4989d10`)  
**Live tip while writing:** see residual / push SHA after this commit

## Chain monitored (no kill)

| Track | Driver | Window | Result |
|-------|--------|--------|--------|
| `markets_breakdown` solo | `p0_mb_solo` (prior) | 2016-03→2023-12 week-chunks | **409/409 pass**, host **10.97** POST/min |
| `equities_bars_daily` solo | `p0_bars_solo` max-jobs **280** week-chunks | 2008-05-01→2023-12-31 | **280** executed (**264 pass / 16 fail**), host **6.22** POST/min |
| `fins_summary` paced | `p0_fins_paced_runner` | 2016-01→2023-12 months | **max i=96**, pass_n=96 (+retry fails), host **~1.15** POST/min |
| `indices_bars_daily_topix` residual | `p0_topix3` (+ concurrent `t4_topix` from other agent) | hist months | **192/192 pass** (p0_topix3), host **~93.5** POST/min |

Orchestrator log: `ALL_GENERAL_AND_FINS_CHAIN_COMPLETE`  
Poll done: `CHAIN_COMPLETE 2026-08-13T13:43:22Z` (bars 280 py=0, fins i=96 py=0, topix idle)

### Dual-resume note (not killed)

A prior wait shell false-negatived `py_alive` and briefly started:
- bars resume → `p0_bars_solo_state_r2.jsonl` (**3** events only, then stopped)
- second `p0_fins_paced_runner` (shared state jsonl; primary still finished i→96)

**No further resume** after `RESUME.flag`s. Running PIDs were **not** killed (policy).

## Host POST/min (state jsonl → `measure_dispatch_rpm`)

Source rows under `.glm-logs/cf-backfill/` (host `/v1/run` only; Worker page RPM separate ~500/min theoretical).

| State | n_events | requests_per_min | window | first → last (UTC) | 429 |
|-------|---------:|-----------------:|--------|--------------------|----:|
| `p0_mb_solo_state.jsonl` | 409 | **10.97** | 2230.9s | 12:20:35 → 12:57:46 | 0 |
| `p0_bars_solo_state.jsonl` | 280 | **6.22** | 2692.2s | 12:58:06 → 13:42:58 | 0 |
| mb+bars serial combined | 689 | **8.35** | 4943.0s | 12:20:35 → 13:42:58 | 0 |
| `p0_fins_paced_state.jsonl` | 102 | **1.15** | 5256s | 12:14:13 → 13:41:49 | 0 |
| `p0_topix3_state.jsonl` | 192 | **93.48** | 122.6s | 13:33:26 → 13:35:28 | 0 |
| `p0_bars_solo_state_r2.jsonl` (brief dual) | 3 | 7.4 | 16.2s | 13:22:03 → 13:22:19 | 0 |

Mid-run snapshot (~13:24Z, bars still live): bars primary **~8.27** POST/min before tail slowdown/hang on last jobs.

## Remote D1 raw_n / COMPLETE segs

DB: `quant-ingest` (wrangler `--remote`). Column: `raw_retention_manifests.completeness` (not `status`).

| Metric | PRE (~13:23Z this session) | POST (~13:43Z) | Δ |
|--------|---------------------------:|---------------:|--:|
| `raw_retention_manifests` total (`raw_n`) | **5279** | **6118** | **+839** |
| raw COMPLETE | 4449 | 5230 | +781 |
| raw FAILED | 830 | 888 | +58 |
| `coverage_segments` COMPLETE | **503** | **510** | **+7** |
| `coverage_segments` PARTIAL | 12416 | 12413 | −3 |

**COMPLETE +7 honesty:** this session’s chain is **worker pass / raw growth**, not an A3 seal pass. Concurrent agents sealed **EDINET +4** (and related) → live COMPLETE **510** (see `docs/proof/mb_2015dir_reeval_edinet_plus4_20260813.md`). **No empty COMPLETE** minted here.

### raw by focus dataset (POST)

| dataset | n manifests | complete_m | failed_m | sum_rows | last_raw_at (+09:00) |
|---------|------------:|-----------:|---------:|---------:|----------------------|
| `equities_bars_daily` | 2000 | 1638 | 362 | 27_323_787 | 2026-08-13T22:32:58 |
| `markets_breakdown` | 1056 | 696 | 360 | 11_753_194 | 2026-08-13T22:33:00 |
| `fins_summary` | 304 | 198 | 106 | 234_420 | 2026-08-13T22:40:56 |
| `indices_bars_daily_topix` | 998 | 997 | 1 | 23_164 | 2026-08-13T22:35:27 |
| `markets_margin_interest` | 76 | 75 | 1 | 144_773 | 2026-08-13T22:15:16 |

## `ops_reeval_observed_window` (POST chain)

No segment rewrite / no COMPLETE claim. SUCCESS receipts with `raw_row_count>0` only.

| dataset | status | observed_start | observed_end | C8 | notes |
|---------|--------|----------------|--------------|----|-------|
| `equities_bars_daily` | **PARTIAL** | **`2008-05-01`** | `2026-08-12` | **pass** lag **1** | held history floor |
| `markets_breakdown` | **PARTIAL** | **`2015-03-26`** | `2026-08-12` | **pass** lag **1** | restored past 2024-01 publish regression |
| `fins_summary` | **PARTIAL** | **`2014-01-01`** | `2026-08-12` | **pass** lag **1** | paced history moved start **2024-01-01 → 2014-01-01** |
| `indices_bars_daily_topix` | **PARTIAL** | **`2008-01-01`** | **`2026-08-13`** | **pass** lag **0** | end advanced to session day |
| `markets_margin_interest` | **PARTIAL** | `2024-01-01` | **`2026-08-13`** | **pass** lag **1** | C8 `source=receipt_observed_end` |

### Margin C8 (detail)

```json
{
  "check_id": "C8",
  "status": "pass",
  "detail": "1 day(s) since latest event_time",
  "metrics": {
    "days_lag": 1,
    "latest_event_time": "2026-08-12",
    "max_days": 7,
    "reference": "2026-08-13",
    "source": "receipt_observed_end"
  }
}
```

Segment COMPLETE counts (POST; **untouched by reeval**):

| dataset | COMPLETE segs | PARTIAL segs |
|---------|--------------:|-------------:|
| bars | 12 | 260 |
| breakdown | 32 | 132 |
| fins_summary | 5 | 219 |
| topix | 32 | 192 |
| margin | 17 | 147 |

## `ops_reeval_freshness`

| Field | POST |
|-------|------|
| status | **FRESH** |
| `generated_at` | **`2026-08-13T13:43:57.356726+00:00`** |
| `age_seconds` | **0** |
| `projection_generation_id` | **`projgen-d511c8243a1944d1a538eed274a25a75`** |
| publisher | `scripts/ops_reeval_freshness.py` |
| COMPLETE segments | **untouched** |

Local mirror: `data/ops/projection_meta.json`.

## last_run (chain)

| Event | UTC |
|-------|-----|
| MB finished | ~2026-08-13T12:57:46Z |
| Bars started | 2026-08-13T12:57:59Z |
| Bars finished executed=280 | 2026-08-13T13:42:58Z |
| Fins last state | 2026-08-13T13:41:49Z (i=96 wave) |
| Topix3 finished | 2026-08-13T13:35:28Z |
| Chain complete marker | **2026-08-13T13:43:22Z** |
| Reeval + freshness | 2026-08-13T13:43:33Z … 13:43:57Z |

## Explicit non-claims

- No Mass / READY / Phase7 ON  
- No fabricated empty COMPLETE segments or dataset COMPLETE  
- Worker **pass ≠** Coverage COMPLETE (bars still **12** COMPLETE months; fins **5**)  
- Host POST/min ≠ upstream JQ page rate  
- Dual-resume was accidental detection bug; not intentional multi-driver policy  
- COMPLETE **510** includes concurrent EDINET seals by other agents

## Commands (replay)

```bash
# host rpm from state (after chain)
.venv/bin/python - <<'PY'
import json
from pathlib import Path
from ops.range_batch_scheduler import measure_dispatch_rpm
rows=[json.loads(l) for l in Path('.glm-logs/cf-backfill/p0_bars_solo_state.jsonl') if l.strip()]
print(measure_dispatch_rpm(rows))
PY

for ds in equities_bars_daily markets_breakdown fins_summary indices_bars_daily_topix markets_margin_interest; do
  .venv/bin/python scripts/ops_reeval_observed_window.py --dataset "$ds" --today 2026-08-13 --freshness-days 7
done
.venv/bin/python scripts/ops_reeval_freshness.py
```
