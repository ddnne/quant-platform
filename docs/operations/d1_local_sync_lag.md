# D1 → local sync lag (visibility)

**Scope:** export cursor + applied change_seq lag only.
Does **not** claim READY, paper-research readiness, or full fact materialization.

## Live measurement (2026-08-12, P1-2 close #2)

| Metric | PRE | POST |
|--------|-----|------|
| origin/main tip (at PRE) | `5c40da5` | *(this commit)* |
| Remote `ingestion_watermarks` n | 23 | 23 |
| Remote null `last_export_cursor` | **0** | **0** |
| Remote `ingestion_change_log` n | 367 | 367 |
| Remote `MAX(change_seq)` | **2859284** | **2859284** |
| Remote `markets_calendar.last_export_cursor` | 2859283 (lag≈1) | 2859283 (lag≈1) |
| Remote `equities_bars_daily.last_export_cursor` | 2859180 (lag≈104) | 2859180 (lag≈104) |
| Remote `indices_bars_daily_topix.last_export_cursor` | 2859284 (lag≈0) | 2859284 (lag≈0) |
| Remote `coverage_segments` n / COMPLETE | 12940 / 401 | 12940 / 401 |
| Remote `collection_receipts` n | 1416 | 1416 |
| Local watermarks null export | **0** | **0** |
| Local `markets_calendar.last_export_cursor` | 2859278 (export_lag=6) | **2859283** (export_lag=**1**) |
| Local `equities_bars_daily.last_export_cursor` | 2859180 (export_lag=104) | 2859180 (export_lag=104; remote tip lag) |
| Local `indices_bars_daily_topix.last_export_cursor` | 2859279 (export_lag=5) | **2859284** (export_lag=**0**) |
| Local `sync_change_state.last_applied_change_seq` | 2859279 | **2859284** |
| Local applied lag (`max_seq - applied`) | **5** | **0** |
| Local `coverage_segments` n / COMPLETE | 12940 / 401 | **12940 / 401** (re-exported) |
| Local `collection_receipts` n | 1630 | **3040** (remote 1416 upserted; local-only rows retained) |

### What was closed (paths)

1. **`ingestion_watermarks` re-export** — D1 → local
   (`markets_calendar` 2859278→2859283, `indices_bars_daily_topix`→2859284).
2. **Incremental change_feed** — applied 2859279→**2859284** (5 non-local
   R2/SCD2 markers skipped; seq advanced; applied_lag **5→0**).
3. **Thin control: `coverage_segments`** — full export 12940 rows registered
   (remote-only column `projection_generation_id` dropped client-side).
4. **Thin control: `collection_receipts`** — full export 1416 rows registered
   into local (local retains extra historical keys → n=3040).

### Script improvements (this close)

- `scripts/sync_d1_to_sqlite.py`: drop remote-only control columns unknown to
  local schema (fixes coverage_segments export after projection metadata
  landed on D1); packages/* path candidates for mid-reorg imports.
- `scripts/report_d1_local_sync_lag.py`: report local control counts
  (`coverage_segments` n/complete, `collection_receipts` n).

### What is *not* claimed

- equities_bars_daily export_lag≈104 is **remote watermark lag** vs tip, not
  a D1→local applied gap (local cursor matches remote cursor).
- `collection_receipts` local n > remote n: no local prune of extra keys.
- No READY / COMPLETE promotion / Mass / sqlite commit snapshot claim.
- applied_lag=0 = tip of **retained** remote change_log window only.

---

## Prior measurement (2026-08-12, first close)

| Metric | PRE | POST |
|--------|-----|------|
| origin/main tip (at PRE) | `bafc5f6` | *(see prior commit)* |
| Remote `ingestion_watermarks` n | 23 | 23 |
| Remote null `last_export_cursor` | **0** | **0** |
| Remote `ingestion_change_log` n | 362 | 362 |
| Remote `MAX(change_seq)` | 2859279 | 2859279 |
| Remote `markets_calendar.last_export_cursor` | 2859278 (lag≈1) | 2859278 (lag≈1) |
| Remote `equities_bars_daily.last_export_cursor` | 2859180 (lag≈99) | 2859180 (lag≈99) |
| Local watermarks null export | **23** | **0** |
| Local `markets_calendar.last_export_cursor` | NULL | **2859278** |
| Local `sync_change_state.last_applied_change_seq` | *(empty)* | **2859279** |
| Local applied lag (`max_seq - applied`) | n/a | **0** |

### What was closed (first path)

1. **Export watermarks D1 → local** via
   `scripts/sync_d1_to_sqlite.py --table ingestion_watermarks`.
2. **Applied change_seq** via
   `scripts/sync_d1_to_sqlite.py --incremental --table jquants_records`
   after skipping non-local markers (`jquants_records_r2`, `equities_master_scd2`).

## Current operation

The preceding measurements are historical, not current operational evidence.
Local HTTP sync is retired; do not repeat the former whole-table counts or
market-history downloads. Use the [current runbook](current_production_runbook.md)
and [cloud storage architecture](../architecture/cf_native_storage_plane.md).
