-- Phase 3.5 D1 schema — PIT-shaped structured rows mirroring storage/schema.py.
-- Every fact table carries the PIT columns event_time / available_at /
-- source / ingested_at and a raw_payload JSON blob for traceability.
--
-- D1 (SQLite) notes:
--   * `IF NOT EXISTS` keeps this idempotent across redeploys.
--   * We intentionally do NOT use AUTOINCREMENT — natural keys are
--     authoritative; rowid is sufficient for any synthetic identity needs.
--   * Revisions tables are kept (matching the SQLite layout) so the future
--     local sync script can mirror amendments verbatim.

-- Equity master (snapshot per code/date) ------------------------------------
CREATE TABLE IF NOT EXISTS jquants_listed_info (
    source          TEXT    NOT NULL,
    code            TEXT    NOT NULL,
    snapshot_date   TEXT    NOT NULL,
    event_time      TEXT    NOT NULL,
    available_at    TEXT    NOT NULL,
    ingested_at     TEXT    NOT NULL,
    company_name    TEXT,
    company_name_en TEXT,
    sector_17_code  TEXT,
    sector_17_name  TEXT,
    sector_33_code  TEXT,
    sector_33_name  TEXT,
    scale_category  TEXT,
    market_code     TEXT,
    market_name     TEXT,
    listing_date    TEXT,
    raw_payload     TEXT,
    PRIMARY KEY (source, code, snapshot_date)
);

-- Daily OHLCV bars ----------------------------------------------------------
CREATE TABLE IF NOT EXISTS jquants_daily_bars (
    source           TEXT NOT NULL,
    code             TEXT NOT NULL,
    date             TEXT NOT NULL,
    event_time       TEXT NOT NULL,
    available_at     TEXT NOT NULL,
    ingested_at      TEXT NOT NULL,
    open             REAL,
    high             REAL,
    low              REAL,
    close            REAL,
    volume           REAL,
    turnover_value   REAL,
    adjustment_open  REAL,
    adjustment_high  REAL,
    adjustment_low   REAL,
    adjustment_close REAL,
    adjustment_volume REAL,
    raw_payload      TEXT,
    PRIMARY KEY (source, code, date)
);

-- Market calendar ----------------------------------------------------------
CREATE TABLE IF NOT EXISTS jquants_market_calendar (
    source           TEXT NOT NULL,
    date             TEXT NOT NULL,
    event_time       TEXT NOT NULL,
    available_at     TEXT NOT NULL,
    ingested_at      TEXT NOT NULL,
    holiday_division TEXT,
    raw_payload      TEXT,
    PRIMARY KEY (source, date)
);

-- Generic catch-all for catalog-mode ingestion (all Premium core datasets
-- that don't have a specialized table). natural_key is a JSON object of
-- identity fields (e.g. {"Code":..,"Date":..}).
CREATE TABLE IF NOT EXISTS jquants_records (
    source       TEXT NOT NULL,
    dataset      TEXT NOT NULL,
    natural_key  TEXT NOT NULL,
    event_time   TEXT NOT NULL,
    available_at TEXT NOT NULL,
    ingested_at  TEXT NOT NULL,
    payload      TEXT,
    raw_payload  TEXT,
    PRIMARY KEY (source, dataset, natural_key)
);

-- Amendment history (mirrors primary fact tables).
CREATE TABLE IF NOT EXISTS jquants_listed_info_revisions AS
    SELECT * FROM jquants_listed_info WHERE 0;
CREATE UNIQUE INDEX IF NOT EXISTS ux_listed_info_revisions_version
    ON jquants_listed_info_revisions (source, code, snapshot_date, available_at);

CREATE TABLE IF NOT EXISTS jquants_daily_bars_revisions AS
    SELECT * FROM jquants_daily_bars WHERE 0;
CREATE UNIQUE INDEX IF NOT EXISTS ux_daily_bars_revisions_version
    ON jquants_daily_bars_revisions (source, code, date, available_at);

CREATE TABLE IF NOT EXISTS jquants_market_calendar_revisions AS
    SELECT * FROM jquants_market_calendar WHERE 0;
CREATE UNIQUE INDEX IF NOT EXISTS ux_market_calendar_revisions_version
    ON jquants_market_calendar_revisions (source, date, available_at);

CREATE TABLE IF NOT EXISTS jquants_records_revisions AS
    SELECT * FROM jquants_records WHERE 0;
CREATE UNIQUE INDEX IF NOT EXISTS ux_records_revisions_version
    ON jquants_records_revisions (source, dataset, natural_key, available_at);

-- Run log + validation results (CF-specific, not mirrored to local sync).
CREATE TABLE IF NOT EXISTS ingestion_run_log (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    ran_at    TEXT    NOT NULL,
    source    TEXT    NOT NULL,
    runtime   TEXT    NOT NULL,
    status    TEXT    NOT NULL,
    detail    TEXT
);

CREATE TABLE IF NOT EXISTS ingestion_validation (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id          INTEGER,
    dataset         TEXT NOT NULL,
    started_at      TEXT NOT NULL,
    finished_at     TEXT NOT NULL,
    status          TEXT NOT NULL,           -- 'pass' | 'fail'
    rows_seen       INTEGER NOT NULL DEFAULT 0,
    rows_inserted   INTEGER NOT NULL DEFAULT 0,
    rows_revisions  INTEGER NOT NULL DEFAULT 0,
    available_at_min TEXT,
    available_at_max TEXT,
    detail          TEXT,
    FOREIGN KEY (run_id) REFERENCES ingestion_run_log(id)
);

CREATE INDEX IF NOT EXISTS ix_bars_available_at
    ON jquants_daily_bars (code, available_at);
CREATE INDEX IF NOT EXISTS ix_records_dataset_avail
    ON jquants_records (dataset, available_at);
CREATE INDEX IF NOT EXISTS ix_calendar_available_at
    ON jquants_market_calendar (date, available_at);
CREATE INDEX IF NOT EXISTS ix_master_available_at
    ON jquants_listed_info (code, available_at);
CREATE INDEX IF NOT EXISTS ix_validation_dataset
    ON ingestion_validation (dataset, started_at);
