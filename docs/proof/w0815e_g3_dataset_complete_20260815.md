# W13-G3 / w0815e_g3 — promote futures + options_225 dataset COMPLETE (2026-08-15)

**Wave:** `w0815e` / **W13-G3**  
**Mass / READY / Phase7:** still **NO-GO / OFF**  
**empty COMPLETE:** **0**  
**empty-raw ban:** held  
**force-apply:** **not** used (fail-closed guard held)  
**peers killed:** **0**  
**prefix:** `w0815e_g3_ds_complete_*`  
**path:** surgical re-aggregate (W10-G12 / W11-G1 / W12-G3) → fail-closed publish → observed-window reeval → freshness → **push**

**Live verified:** 2026-08-15 (JST) / ~2026-08-14T18:31Z UTC  
**Projection:** **FRESH** `projgen-155ea34a533d4d23a162121bf1881aab` (`ops_reeval_freshness`; `coverage_segments_untouched=1`)

## Verdict (one line)

**`derivatives_bars_daily_futures`** and **`derivatives_bars_daily_options_225`** segment planes already **164/164 COMPLETE** (W12-G4 residual seal closed) with C1–C8 **pass** but stale `dataset_coverage` **PARTIAL** (`status_counts` COMPLETE **80** / PARTIAL **84**) → surgical re-aggregate only → both **`dataset_coverage.status=COMPLETE`** (platform Dataset COMPLETE **8 → 10**).  
**`markets_short_ratio`** verified already **COMPLETE** at dataset level (164/164; W12-G3).  
**No invent segs** — global COMPLETE segs held **3308**.

## PRE (remote D1)

| surface | value |
|---------|------:|
| Segment COMPLETE global | **3308** |
| Dataset COMPLETE | **8** |
| empty COMPLETE | **0** |
| `derivatives_bars_daily_futures` segs | **164 / 164 COMPLETE** / PARTIAL **0** |
| `derivatives_bars_daily_futures` `dataset_coverage` | **PARTIAL** (stale `status_counts` COMPLETE **80** / PARTIAL **84**) |
| `derivatives_bars_daily_options_225` segs | **164 / 164 COMPLETE** / PARTIAL **0** |
| `derivatives_bars_daily_options_225` `dataset_coverage` | **PARTIAL** (stale `status_counts` COMPLETE **80** / PARTIAL **84**) |
| `markets_short_ratio` segs | **164 / 164 COMPLETE** |
| `markets_short_ratio` `dataset_coverage` | **COMPLETE** (held; W12-G3) |

C1–C8 on futures + o225 already **pass** (no validation block). Same aggregate-lag class as W10-G12 investor/edinet_major, W11-G1 margin pair, W12-G3 short_ratio.

Segment residual closed earlier by **W12-G4** (`w0815d_g4_fut_o225`): continuous COMPLETE `2013-01…2026-08` (n=**164** each). Aggregate never re-promoted.

Artifacts: `.glm-logs/w0815e_g3_ds_complete/pre/*`, `PRE_sha.txt` (`721c1adc…`)

## Work

### 1. Surgical re-aggregate (G12 / G1 / G3 path)

Local research DB only; **segments untouched**; **no invent segs**:

| dataset | complete==total | failing checks | action |
|---------|----------------:|---------------:|--------|
| `derivatives_bars_daily_futures` | 164==164 | 0 | PARTIAL → **COMPLETE**; `status_counts` `{80,84}` → `{COMPLETE:164}` |
| `derivatives_bars_daily_options_225` | 164==164 | 0 | PARTIAL → **COMPLETE**; `status_counts` `{80,84}` → `{COMPLETE:164}` |
| `markets_short_ratio` | 164==164 | 0 | **verify only** — already COMPLETE |

```text
derivatives_bars_daily_futures: segs={'COMPLETE': 164} total=164 complete=164 old=PARTIAL failing=0 eligible=True
  PROMOTED PARTIAL -> COMPLETE counts {'COMPLETE': 80, 'PARTIAL': 84} -> {'COMPLETE': 164}
derivatives_bars_daily_options_225: segs={'COMPLETE': 164} total=164 complete=164 old=PARTIAL failing=0 eligible=True
  PROMOTED PARTIAL -> COMPLETE counts {'COMPLETE': 80, 'PARTIAL': 84} -> {'COMPLETE': 164}
markets_short_ratio: segs={'COMPLETE': 164} total=164 complete=164 old=COMPLETE failing=0 eligible=True
  VERIFY only status=COMPLETE counts={'COMPLETE': 164}
dataset_coverage counts {'COMPLETE': 10, 'PARTIAL': 16}
all COMPLETE segs 3308
DONE
```

Artifact: `.glm-logs/w0815e_g3_ds_complete/{surgical_reagg.log,reagg_result.json}`

### 2. Publish (fail-closed)

```bash
.venv/bin/python scripts/publish_ops_projection.py \
  --db data/structured/ingestion.sqlite --apply-remote
```

| Step | Guard |
|------|-------|
| apply | `complete_count_guard ok local=3308 remote=3308 force=False` |
| remote | projection applied (13015 queries) |
| `--force-apply-remote` | **not** used |

### 3. Reeval (receipt plane; segments untouched)

```bash
for ds in derivatives_bars_daily_futures derivatives_bars_daily_options_225 markets_short_ratio; do
  .venv/bin/python scripts/ops_reeval_observed_window.py \
    --dataset $ds --today 2026-08-15 --freshness-days 7
done
.venv/bin/python scripts/ops_reeval_freshness.py
```

| dataset | status | observed_start | observed_end | C8 |
|---------|--------|----------------|--------------|----|
| `derivatives_bars_daily_futures` | **COMPLETE** (held) | **`2013-01-04`** | **`2026-08-14`** | **pass** lag **1** ≤7 |
| `derivatives_bars_daily_options_225` | **COMPLETE** (held) | **`2013-01-04`** | **`2026-08-14`** | **pass** lag **1** ≤7 |
| `markets_short_ratio` | **COMPLETE** (held) | **`2013-01-04T00:00:00+09:00`** | **`2026-08-14`** | **pass** lag **1** ≤7 |

### Projection freshness

| Field | POST |
|-------|------|
| status | **FRESH** |
| `active_generation` | **`projgen-155ea34a533d4d23a162121bf1881aab`** |
| publisher | `scripts/ops_reeval_freshness.py` |
| COMPLETE segments | **untouched** by reclock (`coverage_segments_untouched=1`) |
| mass | **NO-GO** |

## POST (remote D1)

| Metric | PRE (this ticket) | POST | Δ |
|--------|------------------:|-----:|--:|
| Dataset COMPLETE | **8** | **10** | **+2** (futures + options_225) |
| Segment COMPLETE global | **3308** | **3308** | **0** (no new segs invented) |
| futures COMPLETE / PARTIAL segs | **164** / **0** | **164** / **0** | held |
| futures `dataset_coverage` | **PARTIAL** | **COMPLETE** | promoted |
| o225 COMPLETE / PARTIAL segs | **164** / **0** | **164** / **0** | held |
| o225 `dataset_coverage` | **PARTIAL** | **COMPLETE** | promoted |
| short_ratio `dataset_coverage` | **COMPLETE** | **COMPLETE** | verified held |
| raw_n | — | **14433** | peer concurrent |
| empty COMPLETE | 0 | **0** | held |

### Dataset COMPLETE = 10 (aligned)

1. `markets_calendar` (224/224)
2. `jsda_tokyo_repo_rates` (1/1)
3. `jsda_corporate_bond_transactions` (12/12)
4. `equities_investor_types` (164/164)
5. `edinet_major_shareholders` (104/104)
6. `markets_margin_alert` (164/164)
7. `markets_margin_interest` (164/164)
8. `markets_short_ratio` (164/164)
9. **`derivatives_bars_daily_futures` (164/164)** — promoted this wave
10. **`derivatives_bars_daily_options_225` (164/164)** — promoted this wave

### POST target detail

| dataset | COMPLETE/total | dataset_coverage | status_counts | observed_start | observed_end |
|---------|---------------:|------------------|---------------|----------------|--------------|
| `derivatives_bars_daily_futures` | **164/164** | **COMPLETE** | `{"COMPLETE":164}` | 2013-01-04 | 2026-08-14 |
| `derivatives_bars_daily_options_225` | **164/164** | **COMPLETE** | `{"COMPLETE":164}` | 2013-01-04 | 2026-08-14 |
| `markets_short_ratio` | **164/164** | **COMPLETE** | `{"COMPLETE":164}` | 2013-01-04T00:00:00+09:00 | 2026-08-14 |

## Absolute bans held

- No Mass / READY / B0 / Phase7 ON  
- No empty COMPLETE invented  
- No invent segs for futures/o225 (already 164/164)  
- Worker pass ≠ Coverage COMPLETE  
- No tokens/secrets in proof  
- Peers **not** killed  
- `--force-apply-remote` **not** used  
- No densify / issue / restore this wave (aggregate-only)

## Explicit non-claims

- `derivatives_bars_daily_options` (near-month full) **not** claimed COMPLETE (segment residual remains).  
- Other 16 governed datasets remain **PARTIAL**.  
- Mass / READY / Phase7 **not** armed.  
- No claim that segment inventory grew this wave (Δ segs **0**).

## Operator repro

```bash
npx wrangler d1 execute quant-ingest --remote --command \
  "SELECT dataset,
     SUM(CASE WHEN status='COMPLETE' THEN 1 ELSE 0 END) AS complete,
     COUNT(*) AS total
   FROM coverage_segments
   WHERE dataset IN (
     'derivatives_bars_daily_futures',
     'derivatives_bars_daily_options_225',
     'markets_short_ratio'
   )
   GROUP BY dataset;"

npx wrangler d1 execute quant-ingest --remote --command \
  "SELECT dataset, status,
          json_extract(detail_json,'\$.coverage_v2.status_counts') AS status_counts
   FROM dataset_coverage
   WHERE dataset IN (
     'derivatives_bars_daily_futures',
     'derivatives_bars_daily_options_225',
     'markets_short_ratio'
   );"
```

## Artifacts

| Path | Role |
|------|------|
| `docs/proof/w0815e_g3_dataset_complete_20260815.md` | this proof |
| `.glm-logs/w0815e_g3_ds_complete/pre/*` | PRE D1 dumps |
| `.glm-logs/w0815e_g3_ds_complete/surgical_reagg.log` | futures + o225 promote |
| `.glm-logs/w0815e_g3_ds_complete/reagg_result.json` | promote result |
| `.glm-logs/w0815e_g3_ds_complete/publish.log` | fail-closed publish |
| `.glm-logs/w0815e_g3_ds_complete/reeval_observed_post_publish.log` | observed_* + C8 |
| `.glm-logs/w0815e_g3_ds_complete/reeval_freshness.log` | FRESH reclock |
| `.glm-logs/w0815e_g3_ds_complete/post/*` | POST verify |
| `docs/phase62_residual_status.md` | live residual SoT sync |

## Result

| Item | Status |
|------|--------|
| futures segs | **164/164 COMPLETE** (held; no invent) |
| futures `dataset_coverage` | **PARTIAL → COMPLETE** |
| o225 segs | **164/164 COMPLETE** (held; no invent) |
| o225 `dataset_coverage` | **PARTIAL → COMPLETE** |
| short_ratio `dataset_coverage` | **COMPLETE** (verified held) |
| Dataset COMPLETE | **8 → 10** |
| Segment COMPLETE global | **3308** (Δ **0**) |
| empty COMPLETE | **0** |
| Mass / READY / Phase7 | **NO-GO / OFF** |
| FRESH | `projgen-155ea34a533d4d23a162121bf1881aab` |
