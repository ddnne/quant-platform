-- Phase 3.5 P0-3 — ingestion watermarks for incremental sync + scale path.
--
-- The D1 control plane grows a small `ingestion_watermarks` table: exactly one
-- row per dataset, overwritten on every successful ingest. The local sync
-- client reads this to skip unchanged work; future tooling (parquet dumps,
-- backfill planners) uses it the same way.
--
-- Schema is intentionally narrow:
--   * dataset            — natural key; one row per Premium core dataset id.
--   * last_event_date    — most recent source-side event observed in the
--                          latest successful run (YYYY-MM-DD, JST). Nullable
--                          so a dataset that yields no rows does not fail.
--   * last_ingested_at   — JST ISO timestamp of the successful ingest write.
--                          This is the canonical "freshness" cursor.
--   * last_export_cursor — reserved. Highest `jquants_records.rowid` touched
--                          by the run; lets a future server-side filter prune
--                          pre-watermark pages without a scan. May be NULL
--                          until backfilled.
--
-- Idempotent across redeploys. We do not mirror this table to local sync —
-- `scripts/sync_d1_to_sqlite.py --incremental` derives its own "since" from
-- the local DB's MAX(ingested_at), keeping the source-of-truth on D1 only.

CREATE TABLE IF NOT EXISTS ingestion_watermarks (
    dataset             TEXT    PRIMARY KEY,
    last_event_date     TEXT,
    last_ingested_at    TEXT    NOT NULL,
    last_export_cursor  INTEGER
);

CREATE INDEX IF NOT EXISTS ix_watermarks_last_ingested_at
    ON ingestion_watermarks (last_ingested_at);
