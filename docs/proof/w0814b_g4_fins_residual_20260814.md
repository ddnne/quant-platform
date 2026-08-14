# w0814b G4 fins family residual months — acq + R2 seal (2026-08-14)

**Mass / READY / Phase7:** still **NO-GO / OFF**  
**empty COMPLETE:** **0** (fins emptyish check)  
**prefix:** `w0814b_g4_fins_*`  
**path:** residual months **execute** (fins pool only) + **seal raw** (R2 → local raw+struct) + issue + publish + reeval + push  
**fins pool isolation:** serial paced residual runner (general untouched); multi-driver fanout avoided (G5 429 lesson); envelope ≈ `--fins-workers 2 --fins-rpm 495`

## Goal

Continue fins deepening after w0814_g5_fins residual seal (COMPLETE **54/47/26/26**):

1. Execute residual months on fins pool only (balanced 12×4).
2. Seal residual unsealed months with usable R2 raw (`row_count>0`).
3. Issue signed SUCCESS receipts + publish projection (fail-closed).
4. Reeval `fins_*` observed windows + freshness.
5. Proof + residual SoT + **push**.

## PRE (remote D1 @ wave start)

| item | value |
|------|------:|
| Segment COMPLETE total | **1376** |
| `fins_summary` COMPLETE | **54** |
| `fins_details` COMPLETE | **47** |
| `fins_dividend` COMPLETE | **26** |
| `fins_earnings_date` COMPLETE | **26** |
| `raw_retention_manifests` | **10705** |

## Execute residual months (fins pool only)

Serial paced runner (interleaved 4 datasets) — **not** multi-driver fanout:

| field | value |
|-------|------:|
| jobs | **48** (12×4) |
| pass / fail | **48 / 0** |
| n_429_events | **0** |
| nz_months | **48** |
| sum_rows | **72036** |
| host_jobs_per_min | **1.85** |
| elapsed_s | **1553.7** |

Ranges:

| dataset | from | to |
|---------|------|----|
| `fins_summary` | **2012-08-01** | **2013-07-31** |
| `fins_details` | **2021-09-01** | **2022-08-31** |
| `fins_dividend` | **2014-02-01** | **2015-01-31** |
| `fins_earnings_date` | **2020-01-01** | **2020-12-31** |

Artifacts:

- state: `.glm-logs/cf-backfill/w0814b_g4_fins_paced_state.jsonl`
- summary: `.glm-logs/cf-backfill/w0814b_g4_fins_paced_summary.json`
- run log: `.glm-logs/cf-backfill/w0814b_g4_fins_paced_run.log`

**Honesty note:** serial paced used deliberately (G5 multi-driver 429 storms); equivalent fins pool envelope to `--fins-workers 2 --fins-rpm 495` without concurrent drivers. General pool not consumed. One transient CF1101 on `fins_dividend/2014-05` recovered on retry within job; final **48/0**.

## Seal map (selected residual, usable raw)

| dataset | segments (n=12 each) | note |
|---------|----------------------|------|
| `fins_summary` | **2012-08 … 2013-07** | continues after 2012-07 COMPLETE island |
| `fins_details` | **2021-09 … 2022-08** | continues after 2021-08 |
| `fins_dividend` | **2014-02 … 2015-01** | continues after 2014-01 history island |
| `fins_earnings_date` | **2020-01 … 2020-12** | continues after 2019-12 |

- map: `.glm-logs/w0814b-g4-fins/w0814b_g4_fins_seal_map.json`
- inventory: unsealed-with-raw summary **138** / details **28** / div **109** / earn **50**

### Seal execute

| field | value |
|-------|------:|
| selected | **48** |
| ready (post-retry) | **48 / 48** |
| first-pass error | `fins_summary/2012-10…2013-01` database is locked (peer sqlite writers: g2_mb / g3_idx) |
| retry | recovered → ready **4/4** |
| empty-raw ban | held (`row_count>0` pages only) |

## Receipts (this pipeline issue step)

```text
.venv/bin/python scripts/issue_receipts_parallel.py \
  --datasets fins_summary,fins_details,fins_dividend,fins_earnings_date \
  --struct-hint --limit 80 --workers 4 --order asc --json-summary
```

| field | value |
|-------|------:|
| candidates | **60** |
| ready / issued | **48 / 48** |
| skipped no_raw | **12** (honest) |
| receipt run_id | **901987 … 902034** |
| local COMPLETE after issue (fins) | summary **66** / details **59** / div **38** / earn **38** |

### Issued segments (**+48** this issue step)

| dataset | segments | n |
|---------|----------|--:|
| `fins_summary` | **2012-08 … 2013-07** | **12** |
| `fins_details` | **2021-09 … 2022-08** | **12** |
| `fins_dividend` | **2014-02 … 2015-01** | **12** |
| `fins_earnings_date` | **2020-01 … 2020-12** | **12** |

## Publish (fail-closed)

```text
.venv/bin/python scripts/publish_ops_projection.py \
  --db data/structured/ingestion.sqlite --refresh-coverage --apply-remote
```

```text
coverage ledger refresh ok
complete_count_guard ok local=1727 remote=1727 force=False
remote projection applied
```

Note: automated pipeline publish was SIGTERM'd by peer contention; **manual resume** of the same fail-closed command succeeded (same args).

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

Freshness: `projgen-5fe71c606e82456896a57c258fa52d3b` **FRESH**; `coverage_segments_untouched=1`; Mass **NO-GO**.

## POST (remote D1 live verify)

| item | PRE (wave) | POST | Δ |
|------|----------:|-----:|--:|
| Segment COMPLETE total | **1376** | **1727** | **+351** (this issue **+48** + concurrent peer seals published) |
| `fins_summary` COMPLETE | **54** | **66** | **+12** |
| `fins_details` COMPLETE | **47** | **59** | **+12** |
| `fins_dividend` COMPLETE | **26** | **38** | **+12** |
| `fins_earnings_date` COMPLETE | **26** | **38** | **+12** |
| `raw_retention_manifests` | **10705** | **11280** | **+575** (this acq + peers) |
| empty COMPLETE (fins) | — | **0** | |

### Remote COMPLETE segment_ids (fins, islands)

- `fins_summary` **66**: `2008-07…2013-07` + tip `2024-01/02`, `2026-06/07/08`
- `fins_details` **59**: `2018-01…2022-08` + tip `2024-01/02`, `2026-08`
- `fins_dividend` **38**: `2013-02…2015-01` + `2018-01…12` + tip `2026-07/08`
- `fins_earnings_date` **38**: `2018-01…12` + `2019-01…12` + `2020-01…12` + tip `2026-07/08`

Datasets remain **PARTIAL** (not dataset-level COMPLETE).

## Forbidden / honesty

- Did **not** launch Mass / READY / Phase7 ON.
- Did **not** invent empty COMPLETE (`{"data":[]}` ban / emptyish **0**).
- Did **not** consume general pool for acq (fins-only serial paced).
- Did **not** fan-out multi-driver fins at 495 each (G5 429 lesson).
- Full publish may include concurrent peer COMPLETE seals (local/remote **1727**).
- Worker pass ≠ Coverage COMPLETE (acq then seal+receipt path).
- Pipeline publish SIGTERM recovered via same fail-closed command (manual resume).

## Residual pointers

- Further unsealed fins months remain (summary **2013-08…**, details **2022-09…**, dividend mid-hole **2015-02…2017-12**, earn **2021+**).
- New acq residual months: use **fins pool only** (serial or single-driver `--fins-rpm` / `--fins-workers`); do not fan-out multiple drivers at 495 each.
- Next wave: continue chronological seal map + issue; keep empty-raw ban.
