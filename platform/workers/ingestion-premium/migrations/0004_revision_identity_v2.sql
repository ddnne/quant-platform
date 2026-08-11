-- Phase 6 F0-F — a publication timestamp is not a revision identifier.
-- Vendors can amend a row more than once without changing its declared
-- available_at. Include ingestion time so every displaced value survives,
-- while an exact replay remains idempotent.

DROP INDEX IF EXISTS ux_listed_info_revisions_version;
CREATE UNIQUE INDEX ux_listed_info_revisions_version
    ON jquants_listed_info_revisions
       (source, code, snapshot_date, available_at, ingested_at);

DROP INDEX IF EXISTS ux_daily_bars_revisions_version;
CREATE UNIQUE INDEX ux_daily_bars_revisions_version
    ON jquants_daily_bars_revisions
       (source, code, date, available_at, ingested_at);

DROP INDEX IF EXISTS ux_market_calendar_revisions_version;
CREATE UNIQUE INDEX ux_market_calendar_revisions_version
    ON jquants_market_calendar_revisions
       (source, date, available_at, ingested_at);

DROP INDEX IF EXISTS ux_records_revisions_version;
CREATE UNIQUE INDEX ux_records_revisions_version
    ON jquants_records_revisions
       (source, dataset, natural_key, available_at, ingested_at);

DROP INDEX IF EXISTS ux_ingestion_change_log_version;
CREATE UNIQUE INDEX ux_ingestion_change_log_version
    ON ingestion_change_log
       (table_name, source, dataset, natural_key, available_at, ingested_at,
        payload);
