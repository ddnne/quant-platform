# w0713 T5 fins residual months — R2 raw seal + receipts (2026-08-14)

**Mass / READY / Phase7:** still **NO-GO / OFF**  
**empty COMPLETE:** **0** (fins emptyish check; usable non-empty R2 only)  
**prefix:** `w0713_t5_fins_*`  
**path:** residual months **seal raw-only** (R2 mirror → local raw+struct → signed SUCCESS)  
**no** `cf_premium_backfill` / **no** general-pool / fins-pool acq this wave  
**worker pass ≠ Coverage COMPLETE**

## Goal

Continue G5 = T5+T6 fins residual after T5 FINAL + T12 + t5_div_pre:

1. Inventory unsealed months with remote `raw_retention_manifests` COMPLETE + `row_count>0`.
2. Seal residual months (cap **48** = 12×4 datasets) via R2 usable-raw path.
3. Issue signed SUCCESS receipts + publish projection (fail-closed).
4. Reeval `fins_*` observed windows + freshness.
5. Proof + residual SoT + **push**.

## PRE (remote D1 @ wave start)

| item | value |
|------|------:|
| Segment COMPLETE total | **585** (SoT prior) → live probe **585** at inventory |
| `fins_summary` COMPLETE | **30** |
| `fins_details` COMPLETE | **23** |
| `fins_dividend` COMPLETE | **2** |
| `fins_earnings_date` COMPLETE | **2** |
| `raw_retention_manifests` | **8756** (inventory probe) |

## Seal map (selected residual)

| dataset | segments (n=12 each) | first run_ids (ex.) |
|---------|----------------------|---------------------|
| `fins_summary` | **2010-08 … 2011-07** | 6221… |
| `fins_details` | **2019-09 … 2020-08** | 6376… |
| `fins_dividend` | **2018-01 … 2018-12** | 6445… |
| `fins_earnings_date` | **2018-01 … 2018-12** | 6518… |

Artifacts:

- map: `.glm-logs/w0713-t5-fins/w0713_t5_fins_seal_map.json`
- result: `.glm-logs/w0713-t5-fins/seal_result.jsonl`
- run log: `.glm-logs/cf-backfill/w0713_t5_fins_seal_run.log`
- pipeline: `.glm-logs/cf-backfill/w0713_t5_fins_pipeline.log`
- SEAL_DONE: `.glm-logs/w0713-t5-fins/SEAL_DONE`

### Seal execute

| field | value |
|-------|------:|
| selected | **48** |
| ready (post-retry) | **48 / 48** |
| first-pass error | `fins_details/2020-01` database is locked (peer sqlite writers) |
| retry | recovered → ready |
| empty-raw ban | held (`row_count>0` pages only) |

## Receipts (this pipeline issue step)

```text
.venv/bin/python scripts/issue_receipts_parallel.py \
  --datasets fins_summary,fins_details,fins_dividend,fins_earnings_date \
  --struct-hint --limit 60 --workers 6 --order asc --json-summary
```

| field | value |
|-------|------:|
| candidates | **29** |
| ready / issued | **18 / 18** |
| skipped no_raw | **11** (earn 2019-* not in seal map; honest) |
| receipt run_id | **900780 … 900797** |
| local COMPLETE after issue | **720** (all datasets; peer concurrent seals included) |

### Issued segments (**+18** this issue step)

| dataset | segments | n |
|---------|----------|--:|
| `fins_summary` | **2010-08 … 2011-07** | **12** |
| `fins_details` | **2020-01** | **1** |
| `fins_dividend` | **2018-09** | **1** |
| `fins_earnings_date` | **2018-09 … 2018-12** | **4** |

Note: other months in the seal map were already local COMPLETE before this issue step
(concurrent peer seals / prior local ledger). They rode along on the full publish.

## Publish (fail-closed)

```text
.venv/bin/python scripts/publish_ops_projection.py \
  --db data/structured/ingestion.sqlite --refresh-coverage --apply-remote
```

```text
coverage ledger refresh ok
complete_count_guard ok local=742 remote=729 force=False
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

Freshness: `projgen-7630c6668d094d42b0b685575dd1ede4` **FRESH** age=0; `coverage_segments_untouched=1`; Mass **NO-GO**.

## POST (remote D1 live verify)

| item | PRE (wave) | POST | Δ |
|------|----------:|-----:|--:|
| Segment COMPLETE total | **585** | **742** | **+157** (this issue **+18** + concurrent peer seals published) |
| `fins_summary` COMPLETE | **30** | **42** | **+12** |
| `fins_details` COMPLETE | **23** | **35** | **+12** |
| `fins_dividend` COMPLETE | **2** | **14** | **+12** |
| `fins_earnings_date` COMPLETE | **2** | **14** | **+12** |
| `raw_retention_manifests` | **8756** | **9455** | **+699** (peer acq; this wave seal-only) |
| empty COMPLETE (fins) | — | **0** | |

### Remote COMPLETE segment_ids (fins)

- `fins_summary` **42**: `2008-07…2011-07` + tip `2024-01/02`, `2026-06/07/08`
- `fins_details` **35**: `2018-01…2020-08` + tip `2024-01/02`, `2026-08`
- `fins_dividend` **14**: `2018-01…2018-12` + tip `2026-07/08`
- `fins_earnings_date` **14**: `2018-01…2018-12` + tip `2026-07/08`

Datasets remain **PARTIAL** (not dataset-level COMPLETE).

## Forbidden / honesty

- Did **not** launch Mass / READY / Phase7 ON.
- Did **not** invent empty COMPLETE (`{"data":[]}` ban / emptyish **0**).
- Did **not** consume general pool or fins pool for acq this wave (R2 seal only).
- Did **not** double-claim peer-issued months as this-issue +N; issue step **+18** is the audited receipt delta.
- Full publish may include concurrent peer COMPLETE seals (local **742** / remote pre-apply **729**).

## Residual pointers

- Further unsealed fins months remain (summary **2011-08…**, details **2020-09…**, dividend/earn **2019+** history).
- New acq residual months without raw: use **fins pool only** (`--fins-rpm` / `--fins-workers`); do not starve general peers.
- Next wave: continue chronological seal map + issue; keep empty-raw ban.
