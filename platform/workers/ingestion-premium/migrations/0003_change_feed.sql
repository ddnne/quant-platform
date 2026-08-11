-- Phase 6 F0-I — append-only, monotonically sequenced structured-row feed.
--
-- Local incremental sync consumes ``change_seq > last_applied`` from the
-- Worker.  The full row version is retained in the log so correctness never
-- depends on rescanning a mutable primary table or filtering pages by a
-- client-side timestamp.

CREATE TABLE IF NOT EXISTS ingestion_change_log (
    change_seq  INTEGER PRIMARY KEY AUTOINCREMENT,
    table_name  TEXT    NOT NULL,
    source      TEXT    NOT NULL,
    dataset     TEXT    NOT NULL,
    natural_key TEXT    NOT NULL,
    event_time  TEXT    NOT NULL,
    available_at TEXT   NOT NULL,
    ingested_at TEXT    NOT NULL,
    payload     TEXT    NOT NULL,
    raw_payload TEXT,
    changed_at  TEXT    NOT NULL
);

CREATE INDEX IF NOT EXISTS ix_ingestion_change_log_table_seq
    ON ingestion_change_log (table_name, change_seq);

-- Makes migration replay/backfill idempotent without weakening the monotonic
-- sequence contract for genuinely distinct versions.
CREATE UNIQUE INDEX IF NOT EXISTS ux_ingestion_change_log_version
    ON ingestion_change_log
       (table_name, source, dataset, natural_key, available_at, payload);

-- Seed existing revision history before current rows.  Future writes append
-- through the same table in the Worker's structured upsert transaction.
INSERT OR IGNORE INTO ingestion_change_log
    (table_name, source, dataset, natural_key, event_time, available_at,
     ingested_at, payload, raw_payload, changed_at)
SELECT
    'jquants_records_revisions', source, dataset, natural_key, event_time,
    available_at, ingested_at, COALESCE(payload, 'null'), raw_payload,
    COALESCE(ingested_at, available_at)
FROM jquants_records_revisions
ORDER BY ingested_at, available_at, rowid;

INSERT OR IGNORE INTO ingestion_change_log
    (table_name, source, dataset, natural_key, event_time, available_at,
     ingested_at, payload, raw_payload, changed_at)
SELECT
    'jquants_records', source, dataset, natural_key, event_time, available_at,
    ingested_at, COALESCE(payload, 'null'), raw_payload,
    COALESCE(ingested_at, available_at)
FROM jquants_records
ORDER BY ingested_at, available_at, rowid;
