# P0 finish: projection FRESH + breakdown observed_start restore (2026-08-13)

**Mass / READY / raw無し COMPLETE:** NO-GO  
**coverage_segments:** untouched  
**cf_premium execute:** none this pass (receipt evidence already present)

## PRE (remote D1 `quant-ingest`)

| metric | value |
|--------|------:|
| projection | FRESH, `generated_at=2026-08-12T22:54:19Z`, stored age=0 (real age ~hours) |
| active gen | `projgen-a99cecc9832c48a2a2334b07898841c3` |
| COMPLETE segs | **490** |
| raw_retention_manifests | live growing (mid-hole bars under other agent) |
| `markets_breakdown.observed_start` | **`2024-01-01`** (regressed after full publish) |
| breakdown SUCCESS raw>0 | n=**77**, min start **`2015-04-01`**, max end `2026-08-12`, sum_raw=1_149_508 |
| `markets_margin_interest.observed_end` | `2026-08-12` (already current) |
| `equities_bars_daily.observed_start` | **`2008-05-01`** |

## Actions

1. **`ops_reeval_observed_window.py --dataset markets_breakdown`**  
   Receipt union restored `observed_start` without new execute (no double backfill).
2. **`ops_reeval_observed_window.py --dataset markets_margin_interest`**  
   Maintained `observed_end=2026-08-12`; status **PARTIAL** (no COMPLETE).
3. **`ops_reeval_freshness.py`**  
   Targeted FRESH clock reset; COMPLETE segments untouched.

## POST

| metric | PRE | POST |
|--------|----:|-----:|
| breakdown `observed_start` | **2024-01-01** | **`2015-04-01`** |
| breakdown `observed_end` | 2026-08-12 | 2026-08-12 |
| breakdown status | PARTIAL | PARTIAL |
| margin `observed_end` | 2026-08-12 | **2026-08-12** |
| margin status | PARTIAL | PARTIAL |
| projection status / age | FRESH / stale real age | **FRESH / age_seconds=0** |
| projection `generated_at` | 2026-08-12T22:54:19Z | **`2026-08-13T01:01:07.627426+00:00`** |
| projection gen | projgen-a99cecc… | **`projgen-17ba75ec08a640339a7f057b7e36919d`** |
| COMPLETE segs | 490 | **490** (untouched) |
| bars `observed_start` | 2008-05-01 | **2008-05-01** |

## Explicit non-claims

- No Mass / READY / Phase7 ON  
- No dataset COMPLETE claim for breakdown or margin  
- No week execute this pass (receipt plane already held 2015-04+)  
- No secrets logged  
- Worker pass ≠ Coverage COMPLETE
