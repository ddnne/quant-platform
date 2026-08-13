# G8-final closed circuit — wave2256 final close 2026-08-13

**Mass / READY / Phase7:** **NO-GO / OFF**  
**empty COMPLETE:** none (`receipt_run_id` null/0 = **0**; empty `detail_json` = **0**)  
**kill acq jobs:** **none** — left running: `t5_fins_paced_runner` (pid 8449), `t6_options_near` / `derivatives_bars_daily_options` (pid 19447)

**Session PRE baseline (task brief):** tip `dbb3590` / `4342091`; raw **n=6447** / COMPLETE raw **c=5559**; COMPLETE segs **510**  
**Base tip at G8-final start (local):** `e00b05f` (origin/main already at residual tip-set after G5)

## Scope (final close — no segment rewrite / no COMPLETE claim)

| Step | Tool | Result |
|------|------|--------|
| 1 remote D1 PRE/live | `wrangler d1 execute quant-ingest --remote` | raw + segs + projection |
| 2 observed_* ×5 | `scripts/ops_reeval_observed_window.py` | bars / breakdown / fins / topix / margin — all C8 **pass** |
| 3 freshness | `scripts/ops_reeval_freshness.py` | projection **FRESH** `age_seconds=0` |
| 4 residual | `docs/phase62_residual_status.md` | tip/raw/COMPLETE/C8 live-sync |
| 5 leak check | D1 + `ps` | Mass NO-GO; Phase7 OFF; empty COMPLETE none; acq not killed |

**Forbidden held:** Mass OFF; no empty COMPLETE invented; no kill of peer acq; Phase7 OFF; no A3 seal in this pass.

## Remote D1 raw_n / COMPLETE segs

DB: `quant-ingest` (`platform/workers/ingestion-premium/wrangler.toml`).

```sql
SELECT COUNT(*) n, SUM(CASE WHEN completeness='COMPLETE' THEN 1 ELSE 0 END) c
FROM raw_retention_manifests;

SELECT status, COUNT(*) n FROM coverage_segments GROUP BY status;
```

| Metric | Session PRE (brief) | G8-final POST (~15:03:48Z) | Δ |
|--------|--------------------:|---------------------------:|--:|
| `raw_retention_manifests` total (`raw_n`) | **6447** | **7385** | **+938** |
| raw completeness=COMPLETE | **5559** | **6495** | **+936** |
| `coverage_segments` COMPLETE | **510** | **538** | **+28** (peer seals across session; **not** from this reeval) |
| `coverage_segments` PARTIAL | — | **12386** | — |
| `coverage_segments` UNKNOWN | — | **17** | — |

Mid-pass (pre-reeval ~15:02Z): raw **7383**/6493, COMPLETE segs **538**.  
Raw continues to climb under live fins/options acq — POST is a point-in-time SoT for this proof.

### raw by focus dataset (POST)

| dataset | n manifests | complete_m |
|---------|------------:|-----------:|
| `equities_bars_daily` | 2120 | 1758 |
| `markets_breakdown` | 1066 | 706 |
| `fins_summary` | 379 | 272 |
| `indices_bars_daily_topix` | 1383 | 1382 |
| `markets_margin_interest` | 224 | 223 |

## `ops_reeval_observed_window` (POST)

No segment rewrite / no COMPLETE claim. SUCCESS receipts with `raw_row_count>0` only. `--today 2026-08-13 --freshness-days 7`.

Artifacts: `.glm-logs/cf-backfill/g8_final/reeval_*.log`

| dataset | status | observed_start | observed_end | C8 |
|---------|--------|----------------|--------------|----|
| `equities_bars_daily` | **PARTIAL** | **`2008-05-01`** | `2026-08-12` | **pass** lag **1** |
| `markets_breakdown` | **PARTIAL** | **`2015-03-26`** | `2026-08-12` | **pass** lag **1** (restored after full-publish reset to 2024-01-01) |
| `fins_summary` | **PARTIAL** | **`2008-07-01`** | `2026-08-12` | **pass** lag **1** (receipt deepen vs prior residual 2014-01-01) |
| `indices_bars_daily_topix` | **PARTIAL** | **`2008-01-01`** | **`2026-08-13`** | **pass** lag **0** |
| `markets_margin_interest` | **PARTIAL** | **`2013-01-04`** | **`2026-08-13`** | **pass** lag **1** (restored after full-publish reset to 2024-01-01) |

Segment COMPLETE counts (POST; **untouched by reeval**):

| dataset | COMPLETE segs | PARTIAL segs |
|---------|--------------:|-------------:|
| bars | 12 | 260 |
| breakdown | 32 | 132 |
| fins_summary | 5 | 207 (+12 UNKNOWN) |
| topix | 32 | 192 |
| margin | 17 | 147 |

## `ops_reeval_freshness` → FRESH age=0

| Field | POST |
|-------|------|
| status | **FRESH** |
| `generated_at` | **`2026-08-13T15:02:49.905484+00:00`** |
| `age_seconds` | **0** |
| `projection_generation_id` | **`projgen-a0595ef1b56a4abe8d94473555ddf22d`** |
| publisher | `scripts/ops_reeval_freshness.py` |
| COMPLETE segments | **untouched** |

Local mirror: `data/ops/projection_meta.json` (gitignored).

## empty COMPLETE / Mass / Phase7 / acq

| Check | Result |
|-------|--------|
| COMPLETE ∧ (`receipt_run_id` IS NULL OR =0) | **0** |
| COMPLETE ∧ empty `detail_json` | **0** |
| Mass / READY / B0 | **NO-GO** (residual + `ops_status` no READY snapshot) |
| Phase 7 | **OFF** (residual explicit; foundation only) |
| Live acq killed? | **no** — fins paced + options near still `ps` alive |

## last_run jobs (remote `ingestion_run_log`, sample)

Peer acq still active around close (JST = UTC+9):

| id | ran_at (JST) | status | note |
|----|--------------|--------|------|
| 6352 | 2026-08-14T00:03:26 | running | `fins_details` 2018-05 |
| 6351 | 2026-08-14T00:02:57 | pass | rowsInserted 840 |
| 6350 | 2026-08-14T00:02:27 | pass | rowsInserted 244 |
| 6349 | 2026-08-14T00:01:37 | fail | `fins_details` transient HTTP 429 |
| 6345 | 2026-08-13T23:59:41 | running | `derivatives_bars_daily_options` 2026-07-27…31 |

Host processes not killed: `t5_fins_paced_runner.py`, `cf_premium_backfill.py … derivatives_bars_daily_options`.

## last_run (this closed circuit)

| Event | UTC |
|-------|-----|
| Task PRE tip / baseline | tip `dbb3590`/`4342091`; raw 6447/5559; COMPLETE segs 510 |
| G8-final start tip | `e00b05f` |
| D1 live pre-reeval | ~2026-08-13T15:02:09Z raw 7383/6493 COMPLETE segs 538 |
| reeval bars | 2026-08-13T15:02:27Z |
| reeval breakdown | 2026-08-13T15:02:31Z |
| reeval fins | 2026-08-13T15:02:36Z |
| reeval topix | 2026-08-13T15:02:41Z |
| reeval margin | 2026-08-13T15:02:46Z |
| freshness FRESH | 2026-08-13T15:02:49Z `projgen-a0595ef1b56a4abe8d94473555ddf22d` |
| D1 POST snapshot | 2026-08-13T15:03:48Z raw **7385**/6495 COMPLETE segs **538** |

## Residual sync

`docs/phase62_residual_status.md` updated to COMPLETE **538** / raw_n **7385** / observed_* + C8 above / projection FRESH / Phase7 OFF / G8-final proof index.
