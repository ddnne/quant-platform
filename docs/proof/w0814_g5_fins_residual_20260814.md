# w0814 G5 fins family residual months — acq + R2 seal (2026-08-14)

**Mass / READY / Phase7:** still **NO-GO / OFF**  
**empty COMPLETE:** **0** (fins emptyish check)  
**prefix:** `w0814_g5_fins_*`  
**path:** residual months **execute** (fins pool only) + **seal raw** (R2 → local raw+struct) + issue + publish + reeval + push  
**fins pool isolation:** serial paced residual runner (general untouched); aborted 4-way parallel attempt after 429 storms

## Goal

Continue G5 fins deepening after w0713_t5_fins residual seal (COMPLETE **42/35/14/14**):

1. Execute residual months on fins pool only (balanced 12×4).
2. Seal residual unsealed months with usable R2 raw (`row_count>0`).
3. Issue signed SUCCESS receipts + publish projection (fail-closed).
4. Reeval `fins_*` observed windows + freshness.
5. Proof + residual SoT + **push**.

## PRE (remote D1 @ wave start)

| item | value |
|------|------:|
| Segment COMPLETE total | **942** |
| `fins_summary` COMPLETE | **42** |
| `fins_details` COMPLETE | **35** |
| `fins_dividend` COMPLETE | **14** |
| `fins_earnings_date` COMPLETE | **14** |
| `raw_retention_manifests` | **9700** |

## Execute residual months (fins pool only)

Serial paced runner (interleaved 4 datasets) — **not** multi-driver fanout:

| field | value |
|-------|------:|
| jobs | **48** (12×4) |
| pass / fail | **48 / 0** |
| n_429_events | **0** |
| nz_months | **48** |
| sum_rows | **73803** |
| host_jobs_per_min | **2.0** |
| elapsed_s | **1437.2** |

Ranges:

| dataset | from | to |
|---------|------|----|
| `fins_summary` | **2011-08-01** | **2012-07-31** |
| `fins_details` | **2020-09-01** | **2021-08-31** |
| `fins_dividend` | **2019-01-01** | **2019-12-31** |
| `fins_earnings_date` | **2019-01-01** | **2019-12-31** |

Artifacts:

- state: `.glm-logs/cf-backfill/w0814_g5_fins_paced_state.jsonl`
- summary: `.glm-logs/cf-backfill/w0814_g5_fins_paced_summary.json`
- run log: `.glm-logs/cf-backfill/w0814_g5_fins_paced_run.log`

**Honesty note:** initial 4 concurrent `cf_premium_backfill.py` drivers (each `--fins-workers 2 --fins-rpm 495`) caused **429** storms; killed immediately; replaced by single serial paced runner. General pool not consumed.

## Seal map (selected residual, usable raw)

| dataset | segments (n=12 each) | note |
|---------|----------------------|------|
| `fins_summary` | **2011-08 … 2012-07** | continues after 2011-07 COMPLETE island |
| `fins_details` | **2020-09 … 2021-08** | continues after 2020-08 |
| `fins_dividend` | **2013-02 … 2014-01** | history near observed_start (nz raw from t5_div_pre) |
| `fins_earnings_date` | **2019-01 … 2019-12** | continues after 2018-12 |

- map: `.glm-logs/w0814-g5-fins/w0814_g5_fins_seal_map.json`
- inventory: unsealed-with-raw summary **150** / details **40** / div **121** / earn **62**

### Seal execute

| field | value |
|-------|------:|
| selected | **48** |
| ready (post-retry) | **48 / 48** |
| first-pass error | `fins_dividend/2013-07` database is locked (peer sqlite writers) |
| retry | recovered → ready |
| empty-raw ban | held (`row_count>0` pages only) |

## Receipts (this pipeline issue step)

```text
.venv/bin/python scripts/issue_receipts_parallel.py \
  --datasets fins_summary,fins_details,fins_dividend,fins_earnings_date \
  --struct-hint --limit 80 --workers 4 --order asc --json-summary
```

| field | value |
|-------|------:|
| candidates | **59** |
| ready / issued | **48 / 48** |
| skipped no_raw | **11** (honest) |
| receipt run_id | **901652 … 901699** |
| local COMPLETE after issue (fins) | summary **54** / details **47** / div **26** / earn **26** |

### Issued segments (**+48** this issue step)

| dataset | segments | n |
|---------|----------|--:|
| `fins_summary` | **2011-08 … 2012-07** | **12** |
| `fins_details` | **2020-09 … 2021-08** | **12** |
| `fins_dividend` | **2013-02 … 2014-01** | **12** |
| `fins_earnings_date` | **2019-01 … 2019-12** | **12** |

## Publish (fail-closed)

```text
.venv/bin/python scripts/publish_ops_projection.py \
  --db data/structured/ingestion.sqlite --refresh-coverage --apply-remote
```

```text
coverage ledger refresh ok
complete_count_guard ok local=1339 remote=1291 force=False
remote projection applied
```

## FINAL reeval (`ops_reeval_observed_window`)

```bash
for ds in fins_summary fins_details fins_dividend fins_earnings_date; do
  .venv/bin/python scripts/ops_reeval_observed_window.py \
    --dataset "$ds" --today 2026-08-14 --freshness-days 7
done
```

| dataset | status | observed_start | observed_end | C8 |
|---------|--------|----------------|--------------|----|
| `fins_summary` | **PARTIAL** | **`2008-07-01`** | **`2026-08-13`** | **pass** lag **1** |
| `fins_details` | **PARTIAL** | **`2018-01-01`** | **`2026-08-13`** | **pass** lag **1** |
| `fins_dividend` | **PARTIAL** | **`2013-02-01`** | **`2026-08-13`** | **pass** lag **1** |
| `fins_earnings_date` | **PARTIAL** | **`2018-01-01`** | **`2026-08-13`** | **pass** lag **1** |

Freshness: `projgen-1b55c469719d4e1493e9b7d0a8d515bd` **FRESH**; `coverage_segments_untouched=1`; Mass **NO-GO**.

## POST (remote D1 live verify)

| item | PRE (wave) | POST | Δ |
|------|----------:|-----:|--:|
| Segment COMPLETE total | **942** | **1339** | **+397** (this issue **+48** + concurrent peer seals published) |
| `fins_summary` COMPLETE | **42** | **54** | **+12** |
| `fins_details` COMPLETE | **35** | **47** | **+12** |
| `fins_dividend` COMPLETE | **14** | **26** | **+12** |
| `fins_earnings_date` COMPLETE | **14** | **26** | **+12** |
| `raw_retention_manifests` | **9700** | **10672** | **+972** (this acq + peers) |
| empty COMPLETE (fins) | — | **0** | |

### Remote COMPLETE segment_ids (fins, islands)

- `fins_summary` **54**: `2008-07…2012-07` + tip `2024-01/02`, `2026-06/07/08`
- `fins_details` **47**: `2018-01…2021-08` + tip `2024-01/02`, `2026-08`
- `fins_dividend` **26**: `2013-02…2014-01` + `2018-01…12` + tip `2026-07/08`
- `fins_earnings_date` **26**: `2018-01…12` + `2019-01…12` + tip `2026-07/08`

Datasets remain **PARTIAL** (not dataset-level COMPLETE).

## Forbidden / honesty

- Did **not** launch Mass / READY / Phase7 ON.
- Did **not** invent empty COMPLETE (`{"data":[]}` ban / emptyish **0**).
- Did **not** consume general pool for acq (fins-only serial paced).
- Did **not** leave multi-driver 429 storm running (killed; single paced replacement).
- Full publish may include concurrent peer COMPLETE seals (local **1339** / remote pre-apply **1291**).
- Worker pass ≠ Coverage COMPLETE (acq then seal+receipt path).

## Residual pointers

- Further unsealed fins months remain (summary **2012-08…**, details **2021-09…**, dividend mid-holes / post-2014 history, earn **2020+**).
- New acq residual months: use **fins pool only** (serial or single-driver `--fins-rpm` / `--fins-workers`); do not fan-out multiple drivers at 495 each.
- Next wave: continue chronological seal map + issue; keep empty-raw ban.
