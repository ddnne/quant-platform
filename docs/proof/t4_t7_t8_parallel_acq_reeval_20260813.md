# T4 / T7 / T8 parallel acq + fail-retry + reeval (2026-08-13)

**Mass / READY / Phase7:** **NO-GO / OFF**  
**empty COMPLETE:** none invented  
**Worker pass ≠ Coverage COMPLETE**  
**bars / fins:** left running (not killed); natural exit observed mid-session

## Scope

Parallel **general pool** acquisition (workers 3, `--general-rpm 495`, `--max-jobs 0`) while `equities_bars_daily` + `fins_*` paced runners were live:

| Track | Dataset(s) | plan | wave1 pass/fail | host POST/min |
|-------|------------|-----:|----------------:|--------------:|
| **T4** | `indices_bars_daily_topix` | **192** | **192 / 0** | **142.41** (80s burst) |
| **T7** | `equities_master` | **147** | **118 / 29** | **3.58** |
| **T8** | `markets_short_ratio` + `markets_margin_alert` + `equities_investor_types` | **432** | **407 / 25** | **9.93** |

Queue-close of T7/T8 was also monitor-documented in [`t1_master_misc_close_20260813.md`](t1_master_misc_close_20260813.md) (fail residual **OPEN → G8**). **This proof closes that residual** via retry + receipt-plane reeval.

Prefixes: `t4_topix_*`, `t7_master_*`, `t8_misc_*`, `t478_*`.

---

## PRE (remote D1 `quant-ingest`, before T478 execute)

| metric | value |
|--------|------:|
| `raw_retention_manifests` total | **5265** |
| completeness COMPLETE | **4435** |
| completeness FAILED | **830** |
| sum `row_count` | **41_130_692** |
| sum `raw_bytes` | **23_987_961_111** |

Target dataset raw n / rows (PRE):

| dataset | n | rows |
|---------|--:|-----:|
| `indices_bars_daily_topix` | 614 | 15_498 |
| `equities_master` | 68 | 773_165 |
| `markets_short_ratio` | 66 | 3_094 |
| `markets_margin_alert` | 66 | 21_183 |
| `equities_investor_types` | 53 | 3_314 |

Artifacts: `.glm-logs/cf-backfill/t478_raw_pre.json`, `t478_raw_pre_by_ds.json`

---

## Execute (wave1)

```text
# T4
.venv/bin/python -u scripts/ops/cf_premium_backfill.py \
  --datasets indices_bars_daily_topix \
  --execute --workers 3 --general-rpm 495 --max-jobs 0 \
  --plan-out .glm-logs/cf-backfill/t4_topix_exec_plan.json \
  --queue-out .glm-logs/cf-backfill/t4_topix_exec_queue.json \
  --state-out .glm-logs/cf-backfill/t4_topix_exec_state.jsonl

# T7
.venv/bin/python -u scripts/ops/cf_premium_backfill.py \
  --datasets equities_master \
  --execute --workers 3 --general-rpm 495 --max-jobs 0 \
  --plan-out .glm-logs/cf-backfill/t7_master_exec_plan.json \
  --queue-out .glm-logs/cf-backfill/t7_master_exec_queue.json \
  --state-out .glm-logs/cf-backfill/t7_master_exec_state.jsonl

# T8
.venv/bin/python -u scripts/ops/cf_premium_backfill.py \
  --datasets markets_short_ratio,markets_margin_alert,equities_investor_types \
  --execute --workers 3 --general-rpm 495 --max-jobs 0 \
  --plan-out .glm-logs/cf-backfill/t8_misc_exec_plan.json \
  --queue-out .glm-logs/cf-backfill/t8_misc_exec_queue.json \
  --state-out .glm-logs/cf-backfill/t8_misc_exec_state.jsonl
```

PIDs: topix **87574**, master **87576**, misc **87578**.  
bars PID **79797** / fins **71583** untouched (later natural exit).

### Wave1 worker rowsInserted (from state `detail` JSON)

| track | rowsInserted sum | notes |
|-------|-----------------:|-------|
| T4 topix | **3_833** | all 192 pass |
| T7 master | **36_534** | 118 pass |
| T8 misc | **467_613** | 407 pass |
| **wave1 total** | **508_000** | |

### Wave1 fail taxonomy (54)

| source | 429 | D1 CPU | HTTP 503 | HTTP 0 |
|--------|----:|-------:|---------:|-------:|
| master | 22 | 2 | 5 | 0 |
| misc | 19 | 5 | 0 | 1 |
| **sum** | **41** | **7** | **5** | **1** |

Host `/v1/run` envelope `http_429_count`: **0** (429s are Worker→JQ inside summary).

---

## Fail retry (G8 close)

Serial-ish retry of all **54** fail segments (2 workers, multi-attempt on 429/D1):

| field | value |
|-------|------:|
| unique segments | **54** |
| pass after retry | **54** |
| still fail | **0** |
| retry rowsInserted sum | **144_815** |
| state | `.glm-logs/cf-backfill/t478_retry_state.jsonl` |

One segment (`markets_margin_alert/2015-12`) first classified fail by a brittle string check despite worker `status=pass` / `rowsInserted=2449`; reclassified from worker summary (no empty COMPLETE).

**Effective after wave1+retry:** all planned T4/T7/T8 segments **worker-pass** (seal still requires raw+struct+receipt path).

---

## POST raw (remote D1)

| metric | PRE | POST | Δ |
|--------|----:|-----:|--:|
| total manifests | 5265 | **7289** | **+2024** |
| COMPLETE completeness | 4435 | **6400** | **+1965** |
| FAILED completeness | 830 | **889** | **+59** |
| sum rows | 41_130_692 | **61_210_898** | **+20_080_206** |
| sum bytes | 23_987_961_111 | **31_385_538_449** | **+7_397_577_338** |

### Target datasets only (raw n / rows)

| dataset | Δ n | Δ rows |
|---------|----:|-------:|
| `indices_bars_daily_topix` | **+769** | **+15_335** |
| `equities_master` | **+170** | **+14_030_267** |
| `markets_short_ratio` | **+133** | **+91_426** |
| `markets_margin_alert` | **+171** | **+458_568** |
| `equities_investor_types` | **+155** | **+3_095** |
| **target sum** | **+1398** | **+14_598_691** |

Remaining global Δ (~+626 manifests / ~+5.5M rows) attributable to concurrent bars/fins and other peers during the same window.

Artifacts: `.glm-logs/cf-backfill/t478_raw_post.json`, `t478_raw_post_by_ds.json`

---

## Reeval (receipt plane, no segment rewrite / no COMPLETE claim)

```text
for ds in indices_bars_daily_topix equities_master markets_short_ratio \
          markets_margin_alert equities_investor_types; do
  .venv/bin/python scripts/ops_reeval_observed_window.py --dataset $ds --today 2026-08-13
done
.venv/bin/python scripts/ops_reeval_freshness.py
```

| dataset | status | observed_start | observed_end | C8 |
|---------|--------|----------------|--------------|----|
| `indices_bars_daily_topix` | PARTIAL | **2008-01-01** | **2026-08-13** | **pass** lag 0 |
| `equities_master` | PARTIAL | **2006-08-13** | **2026-08-12** | **pass** lag 1 |
| `markets_short_ratio` | PARTIAL | **2013-01-04** | **2026-08-12** | **pass** lag 1 |
| `markets_margin_alert` | PARTIAL | **2013-01-04** | **2026-08-12** | **pass** lag 1 |
| `equities_investor_types` | PARTIAL | **2013-01-04** | **2026-08-12** | **pass** lag 2 |

Notable moves vs residual pre-pass snapshot:

- `markets_short_ratio` observed_start **2024-01-04 → 2013-01-04**; end **2026-08-10 → 2026-08-12**
- `markets_margin_alert` observed_start **2025-03-03 → 2013-01-04**; end **2026-08-07 → 2026-08-12**
- `equities_master` observed_start **2006-08-13** (subscription floor; history thickened)
- `equities_investor_types` observed window filled **2013-01-04 … 2026-08-12**

Projection after freshness: **FRESH** `projgen-6123af6a14464b949b646e7bfdc2817e` (age_seconds=0).  
`coverage_segments` COMPLETE total remote: **531** (not claimed as this pass’s seal; no Mass).

---

## Absolute bans held

- No Mass / READY / B0 / Phase7 ON  
- No fabricated empty COMPLETE  
- No kill of bars/fins or peer drivers  
- No token/secret in proof or committed logs  
- Worker pass ≠ Coverage COMPLETE (explicit)

## Verdict

| Check | Result |
|-------|--------|
| T4 topix 192/192 pass | **PASS** |
| T7+T8 queue close | **PASS** |
| 54 fail retry → 0 residual | **PASS** |
| Target raw n increase | **+1398** manifests |
| observed_* reeval C8 | **all pass** |
| empty COMPLETE | **none** |

**Overall: PASS** (acq + retry + reeval + raw increase evidence).
