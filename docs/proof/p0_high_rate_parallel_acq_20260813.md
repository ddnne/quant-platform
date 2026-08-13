# P0 high-rate parallel acquisition (2026-08-13)

**Mass / READY:** NO-GO  
**COMPLETE fabrications:** none (worker pass ≠ Coverage COMPLETE)  
**Phase7:** OFF  
**base tip PRE:** `4989d10` (already on `origin/main`)

## Scope

Parallel Premium backfill wave (host POST `/v1/run`), general + fins pools, **without** killing live drivers:

| driver | artifact | range / note | result |
|--------|----------|--------------|--------|
| `markets_breakdown` solo | `p0_mb_solo_*` | week-chunks → **409/409 pass** | **DONE** before bars |
| `equities_bars_daily` solo | `p0_bars_solo_*` | 2008-05-01…2023-12-31, week-7d, max-jobs **280**, workers 2, general-rpm 495 | **DONE** executed=280 (pass 264 / fail 16) |
| `fins_summary` paced | `p0_fins_paced_*` | monthly 2016–2023 residual, paced runner | **DONE** 96/96 pass (`"done": true`) |
| `indices_bars_daily_topix` | `p0_topix3_*` (+ peer `t4_topix_exec_*`) | residual history | **DONE** topix3 wave1 **192** pass @ **93.48** rpm; orch residual wave2 **192** pass @ **62.79** rpm (state jsonl n=**384**); peer t4 also 192 pass |

**Bans held:** no Mass; no empty COMPLETE seal; no intentional rate demotion; original bars/fins/chain wait shells not killed.

## PRE baseline (remote D1)

Source: `.glm-logs/cf-backfill/p0_parallel_PRE_20260813T120732Z.json` (`generated_at=2026-08-13T12:07:36Z`)

| metric | PRE |
|--------|-----|
| `raw_retention_manifests` total | **3535** |
| bars `observed_start` / `observed_end` | `2008-05-01` / `2026-08-12` |
| fins `observed_start` / `observed_end` | `2024-01-01` / `2026-08-11` |
| topix `observed_start` / `observed_end` | `2008-01-01` / `2026-08-12` |
| breakdown `observed_start` / `observed_end` | `2024-01-01` / `2026-08-12` |

## Host POST requests/min (state jsonl + run log)

`scripts/report_raw_throughput.py --state-jsonl …` (host dispatch = POST `/v1/run` only; upstream JQ page theory ≈ **500**/min @ 120ms):

| state jsonl | n_events | window_s | **host rpm** | notes |
|-------------|---------:|---------:|-------------:|-------|
| `p0_mb_solo_state.jsonl` | 409 | 2230.9 | **10.97** | all pass |
| `p0_bars_solo_state.jsonl` | 280 | 2692.2 | **6.22** | pass 264 / fail 16; http_429=0 |
| `p0_topix3_state.jsonl` | **384** (2×192) | w1 122.6 / w2 182.5 | **93.48** (w1) / **62.79** (w2) | orch residual re-dispatch after bars; no kill |
| `t4_topix_exec_state.jsonl` (peer) | 192 | 80.5 | **142.41** | concurrent peer agent |
| `p0_fins_paced_state.jsonl` | 102 | 5256 | **1.09–1.16** | runner `host_jobs_per_min=1.09`; report_raw needs `finished_at` (fins uses `ts`) |
| **merged** mb+bars+topix3+fins (early) | 983 / host n=881 | 4943 | **10.68** | first seal snapshot |
| **merged** incl. topix w2 (re-verify) | **1073** | 5224 | **12.31** | `report_raw_throughput --state-jsonl` post orch topix residual |

Run-log `host_dispatch_rpm` (authoritative per driver finish line):

```text
mb:     requests_per_min=10.97  executed=409 pass
bars:   requests_per_min=6.22   executed=280 pass=264 fail=16  http_429=0
topix3: requests_per_min=93.48  executed=192 pass   (wave1)
topix3: requests_per_min=62.79  executed=192 pass   (wave2 / orch residual)
fins:   host_jobs_per_min=1.09  pass=96 fail=0 done=true
```

**Peak host rpm observed this wave:** topix bursts **~63–143** POST/min; sustained multi-driver merge **~11–12**/min; bars solo sustained **~6.2**/min at workers=2 under shared general pool (peer master/misc/mb residual also live).

## POST remote raw_n (D1 `quant-ingest`)

| metric | PRE | POST first seal | POST re-verify (13:49Z) | Δ vs PRE |
|--------|----:|----------------:|------------------------:|---------:|
| `raw_retention_manifests` total | **3535** | **6213** | **6378** | **+2843** |
| completeness=COMPLETE | — | **5325** | **5490** | — |
| coverage_segments COMPLETE | 501 (prior residual) | **510** | **510** | +9 (peer seals / concurrent A3; **not** invented by this wave) |

> Remote is SoT. Local research-mirror `report_raw_throughput` shows raw_manifests=0 (mirror not raw-synced); do not treat local raw as SoT.

## observed_* reeval (remote; no segment rewrite)

```bash
.venv/bin/python scripts/ops_reeval_observed_window.py --dataset <ds> --today 2026-08-13 --freshness-days 7
```

| dataset | status | observed_start | observed_end | C8 |
|---------|--------|----------------|--------------|----|
| `equities_bars_daily` | **PARTIAL** | **`2008-05-01`** | `2026-08-12` | pass lag 1d |
| `markets_breakdown` | **PARTIAL** | **`2015-03-26`** | `2026-08-12` | pass lag 1d |
| `fins_summary` | **PARTIAL** | **`2014-01-01`** | `2026-08-12` | pass lag 1d |
| `indices_bars_daily_topix` | **PARTIAL** | **`2008-01-01`** | `2026-08-13` | pass lag 0d |
| `markets_margin_interest` | **PARTIAL** | `2024-01-01` | `2026-08-13` | **pass** lag **1d** ≤7 (`source=receipt_observed_end`) |

## Projection freshness

```bash
.venv/bin/python scripts/ops_reeval_freshness.py
```

| field | first seal | re-verify (this pass) |
|-------|------------|------------------------|
| status | **FRESH** | **FRESH** |
| `generated_at` | `2026-08-13T13:45:30.731474+00:00` | **`2026-08-13T13:49:05.920521+00:00`** |
| `age_seconds` | 0 | **0** |
| `projection_generation_id` | `projgen-66763022d5ea4a56b51498874fbd3850` | **`projgen-ef9627ddbb4a4330803bcd2662019d0f`** |
| segments rewritten | none | **none** |

## Margin detail_json C8 (wrangler confirm)

```sql
-- json_extract checks[C8]
status=pass; detail="1 day(s) since latest event_time"; days_lag=1; source=receipt_observed_end
```

**PASS** (not dataset COMPLETE).

## Driver finish evidence

| driver | finish evidence |
|--------|-----------------|
| bars | `p0_bars_solo_run.log`: `finished executed=280 states={'pass': 264, 'fail': 16}` |
| fins | `p0_fins_paced_run.log`: `{"done": true, "pass": 96, "fail": 0, ...}` |
| topix3 | `p0_topix3_run.log`: wave1 `finished executed=192` @ 93.48 rpm; wave2 `finished executed=192` @ 62.79 rpm; state n=384 |
| mb | `p0_mb_solo_run.log` / orch: `finished executed=409 states={'pass': 409}` |
| chain | `p0_chain_orchestrator.log`: `ALL_GENERAL_AND_FINS_CHAIN_COMPLETE` |

## Artifacts

- PRE: `.glm-logs/cf-backfill/p0_parallel_PRE_20260813T120732Z.json`
- POST throughput: `.glm-logs/cf-backfill/p0_parallel_POST_throughput.{json,md}`
- Per-driver rpm JSON: `.glm-logs/cf-backfill/p0_rpm_{bars,topix3,mb,fins}.json`
- Merged state: `.glm-logs/cf-backfill/p0_parallel_wave_merged_state.jsonl`
- State jsonl: `p0_bars_solo_state.jsonl`, `p0_fins_paced_state.jsonl`, `p0_topix3_state.jsonl`, `p0_mb_solo_state.jsonl`

## Absolute bans held

- No Mass / READY / B0  
- No fabricated COMPLETE  
- No intentional low-rate demotion of live bars/fins (general-rpm 495 retained)  
- Did not kill original bars solo / fins paced / chain wait shells  
- Worker pass ≠ Coverage COMPLETE (bars fail 16 left as honest fails; no empty COMPLETE seal)
