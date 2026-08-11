# Phase 3.5 P0-3 — Storage scale path (R2 bulk timeseries + D1 control plane)

The Phase 3.5 closed loop currently writes **every** Premium core row into D1
(`jquants_records` + `*_revisions`). That is fine for the 23 core datasets at
hourly cadence — low millions of rows per year — but it is **not** the right
home for high-volume paths: minute bars, full TDnet, ad-hoc backfill windows,
or downstream feature dumps. This doc defines the *minimal viable* split that
unblocks incremental sync today and leaves a clean runway to parquet later.

## TL;DR

| Tier | Store | Shape | Examples |
|------|-------|-------|----------|
| **R2** | `quant-raw`, `quant-structured` | Bulk timeseries partitions: `raw/{dataset}/{yyyy}/{mm}/{dd}/{stamp}.json` (already live) and, for future use, `structured/{dataset}/{yyyy}/{mm}/{dd}/part-*.parquet` under `quant-structured` | Verbatim source JSON, future parquet dumps |
| **D1** | `quant-ingest` | Control plane — runs, validation results, **watermarks**, manifests, the *current* structured row per natural key | `jquants_records`, `ingestion_run_log`, `ingestion_validation`, `ingestion_watermarks` |

D1 remains the **operational source of truth** for "what is the latest value
of row X". R2 becomes the **bulk timeseries** home for any path that does not
need point lookups against the live row.

## Why split (and why now)

1. **D1 row limits are real.** Cloudflare D1 is sized for low billions of
   rows in practice but each query/scan cost scales with work. A 10-year
   backfill of 4,000 tickers × daily bars is ~10M rows; doable. Add minute
   bars or full short-sale breakdowns and the math stops working.
2. **PIT lookups don't need bulk.** `pit.get_*` reads the *current* row for a
   natural key plus its amendments. That is exactly what D1 + the revisions
   tables already provide. Keeping the high-volume data on R2 protects the
   read path's p99.
3. **Bulk is append-only.** Parquet on R2 has no GC pressure on D1, snapshots
   are immutable, and downstream tools (pandas, duckdb, polars) read it
   natively. Partition prune by `yyyy/mm/dd` for any date window.
4. **Watermarks make sync cheap.** A one-row-per-dataset watermark lets the
   local sync skip clean tables entirely; the same cursor lets a future
   partition dumper avoid re-writing partitions that did not change.

## Watermarks (this PR)

Migration `platform/workers/ingestion-premium/migrations/0002_watermarks.sql`
introduces:

```sql
CREATE TABLE ingestion_watermarks (
    dataset             TEXT    PRIMARY KEY,
    last_event_date     TEXT,            -- YYYY-MM-DD (JST), nullable
    last_ingested_at    TEXT    NOT NULL,-- JST ISO timestamp of last success
    last_export_cursor  INTEGER          -- reserved for server-side pruning
);
```

The Worker upserts one row per successful dataset ingest (see
`upsertWatermark` in `src/index.ts`):

* `last_event_date` — the most recent `Date`/`DateTime`/`DisclosedDate`/...
  observed in the batch. Passed through `COALESCE` on conflict so an empty
  batch never overwrites a known-good value.
* `last_ingested_at` — the JST ISO timestamp at the moment the structured
  write committed. This is the canonical freshness cursor.
* `last_export_cursor` — reserved. The plan is to populate it with the
  highest `jquants_records.rowid` written so a future server-side export
  filter (`WHERE rowid > ?`) can prune everything the local sync has already
  seen.

The Worker also surfaces the table on `/v1/export/d1?table=ingestion_watermarks`
so an operator can ask "when did dataset X last advance?" without touching the
D1 console.

## Local incremental sync

`scripts/sync_d1_to_sqlite.py --incremental` skips rows already mirrored
locally. Important limitation (also called out in `--help`):

> **The export API has no server-side `ingested_at` filter.** It paginates by
> `rowid` only. Incremental mode therefore derives `since =
> MAX(ingested_at)` from the local DB and applies it **client-side after page
> fetch**. Every page is still walked; the savings are upsert work, not
> transfer.

Concretely:

1. For each table, read `SELECT MAX(ingested_at) FROM {table}` from the
   local SQLite (or accept an explicit `--since ISO`).
2. Pull pages from `/v1/export/d1` exactly as in the full sync — same
   cursor, same page size.
3. After each page lands, drop rows whose `ingested_at <= since` before
   handing the batch to `SqliteStore.upsert`. Comparison is lexicographic on
   JST ISO strings (canonical form produced by `validate_available_at`),
   which is also chronological.
4. A single `httpx.Client` is reused across every table and page so the
   TLS handshake + connection pool is amortised.

When the export API gains a real filter (planned with
`last_export_cursor`), step 2 collapses to one page for the common case.

## Migration path (out of the generic `jquants_records` dump)

Today every Premium core dataset lands in `jquants_records`. The path off it
is **incremental**, and nothing in this PR forces the move:

1. **Now (P0-3)** — watermarks advance; incremental sync skips unchanged
   work. Specialised tables (`jquants_daily_bars`, `jquants_listed_info`,
   `jquants_market_calendar`) already exist and remain the read path for
   `pit.get_*`.
2. **Next** — partition dumper: a Worker task (cron or `/v1/run?dump=1`)
   writes any newly-ingested `jquants_records` rows to
   `quant-structured/structured/{dataset}/{yyyy}/{mm}/{dd}/part-{stamp}.parquet`.
   The watermark tells the dumper where to resume; the manifest (a sibling
   `_manifest.json` per partition) records row counts, min/max event dates,
   and the upstream `raw/...` path.
3. **Then** — D1 retains the *current* row per natural key + revisions; the
   parquet dump is the bulk timeseries source for analytics, feature
   research, and backtest seeds. A row is deleted from D1 only once the
   corresponding partition is verified (manifest present + row count
   matches + checksum ok).
4. **Eventually** — high-volume addons (`equities_bars_minute`,
   `equities_trades`, `td_*`) skip D1 entirely and write R2 parquet + a D1
   manifest row. The watermark table is reused so `pit.get_*` can still
   answer "what's the latest?" without scanning parquet.

No step above is required to keep the platform healthy today; the watermarks
and incremental sync in this PR exist so the eventual migration does not
require a flag day.

## What stays on D1

* `jquants_records` and `*_revisions` — point-lookup PIT reads.
* `ingestion_run_log`, `ingestion_validation` — operational dashboards.
* `ingestion_watermarks` — freshness cursors and the future dump manifest
  index.

## What moves to R2 (parquet, future)

* Verbatim source JSON (already there: `quant-raw`).
* Bulk timeseries for analytics workloads (`quant-structured`).
* Anything where the read pattern is "scan a date window across many codes"
  rather than "give me the current value of row X".

## See also

* [phase35_cf_ingest.md](phase35_cf_ingest.md) — closed-loop contract and ops.
* [phase35_validation_matrix.md](phase35_validation_matrix.md) — data-quality
  gates the storage path must keep passing.
* `platform/workers/ingestion-premium/migrations/0002_watermarks.sql` — the
  schema introduced here.
* `scripts/sync_d1_to_sqlite.py --help` — incremental flags.
