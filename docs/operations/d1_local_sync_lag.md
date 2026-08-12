# D1 → local sync lag (visibility)

**Scope:** export cursor + applied change_seq lag only.
Does **not** claim READY, paper-research readiness, or full fact materialization.

## Live measurement (2026-08-12, post-close)

| Metric | PRE | POST |
|--------|-----|------|
| origin/main tip (at PRE) | `bafc5f6` | *(see commit of this doc)* |
| Remote `ingestion_watermarks` n | 23 | 23 |
| Remote null `last_export_cursor` | **0** | **0** |
| Remote `ingestion_change_log` n | 362 | 362 |
| Remote `MAX(change_seq)` | 2859279 | 2859279 |
| Remote `markets_calendar.last_export_cursor` | 2859278 (lag≈1) | 2859278 (lag≈1) |
| Remote `equities_bars_daily.last_export_cursor` | 2859180 (lag≈99) | 2859180 (lag≈99) |
| Local `jquants_market_calendar` rows | 0 | 0 (legacy table unused; remote has no such table) |
| Local `jquants_records` `markets_calendar` rows | 6798 | 6798 |
| Local `markets_calendar` max event_time | 2026-08-11 | 2026-08-11 |
| Local watermarks null export | **23** | **0** |
| Local `markets_calendar.last_export_cursor` | NULL | **2859278** |
| Local `sync_change_state.last_applied_change_seq` | *(empty)* | **2859279** |
| Local applied lag (`max_seq - applied`) | n/a | **0** |
| Local `coverage_segments` COMPLETE | 400 | 400 *(unchanged; not re-evaluated)* |
| Local `dataset_coverage.markets_calendar` | PARTIAL | PARTIAL *(not promoted)* |

### What was closed (one path)

1. **Export watermarks D1 → local** via
   `scripts/sync_d1_to_sqlite.py --table ingestion_watermarks`
   (`markets_calendar` cursor NULL → 2859278).
2. **Applied change_seq** via
   `scripts/sync_d1_to_sqlite.py --incremental --table jquants_records`
   after skipping non-local markers (`jquants_records_r2`, `equities_master_scd2`).
   Applied watermark: 0 → 2859279 (retained change_log window only).

### What is *not* claimed

- `dataset_coverage` / segment COMPLETE was **not** rewritten by this path.
- Full history for `markets_calendar` on remote D1 is thin (n≈42 recent rows);
  bulk structured history may live on R2 (`jquants_records_r2` summary markers).
- Legacy local table `jquants_market_calendar` remains empty; calendar facts live
  in local `jquants_records` (dataset=`markets_calendar`).
- applied_lag=0 means local applied the tip of the **retained** remote change_log,
  not that every historical D1/R2 row is present locally.

## How to re-measure

Remote (from `platform/workers/ingestion-premium`):

```bash
npx wrangler d1 execute quant-ingest --remote --command \
  "SELECT COUNT(*) AS n,
          COUNT(CASE WHEN last_export_cursor IS NULL THEN 1 END) AS null_export
   FROM ingestion_watermarks;"

npx wrangler d1 execute quant-ingest --remote --command \
  "SELECT MAX(change_seq) AS max_seq, COUNT(*) AS n FROM ingestion_change_log;"

npx wrangler d1 execute quant-ingest --remote --command \
  "SELECT dataset, last_export_cursor FROM ingestion_watermarks
   WHERE dataset IN ('markets_calendar','equities_bars_daily')
   ORDER BY dataset;"
```

Local + lag report (read-only):

```bash
python3 scripts/report_d1_local_sync_lag.py \
  --db data/structured/ingestion.sqlite \
  --remote-max-seq 2859279 \
  --remote-change-log-n 362 \
  --focus markets_calendar,equities_bars_daily
```

## Sync command used for the closed path

```bash
export INGESTION_PREMIUM_URL="https://quant-platform-ingestion-premium.<acct>.workers.dev"
export DATA_EXPORT_TOKEN  # from ~/.config/quant-platform/data_export_token — do not commit

# Control-plane watermarks
python3 scripts/sync_d1_to_sqlite.py \
  --db data/structured/ingestion.sqlite \
  --table ingestion_watermarks \
  --url "$INGESTION_PREMIUM_URL" \
  --token "$DATA_EXPORT_TOKEN"

# Applied change_seq (skips R2/SCD2 markers; advances seq)
python3 scripts/sync_d1_to_sqlite.py \
  --db data/structured/ingestion.sqlite \
  --table jquants_records \
  --incremental \
  --url "$INGESTION_PREMIUM_URL" \
  --token "$DATA_EXPORT_TOKEN"
```

Secrets stay in `~/.config/quant-platform/` or env; never in git.
