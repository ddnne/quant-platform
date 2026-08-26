-- Forward-only definition for specialized J-Quants schema repair.
--
-- The canonical chain is 0012 -> 0013. Migration 0001 defines these tables and
-- indexes; migration 0004 drops and recreates the revision indexes so their
-- unique identity also includes `ingested_at`. The statements below reproduce
-- that final 0001+0004 specialized schema and do not modify data.
--
-- A `d1_migrations` history row is not structural proof and must never skip
-- exact postflight. `IF NOT EXISTS` is unsafe without a governed sequence that
-- authenticates the D1 identity, takes a recoverable backup/bookmark, rejects
-- malformed or shadow/deputy objects in exact preflight, applies this exact
-- checksum, and independently repeats exact postflight. Generic application of
-- 0013 is quarantined until that sequence exists. This file does not mint
-- Coverage, Receipt, READY, or release evidence and does not close A2 or A6.

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

CREATE TABLE IF NOT EXISTS jquants_listed_info_revisions AS
    SELECT * FROM jquants_listed_info WHERE 0;
CREATE UNIQUE INDEX IF NOT EXISTS ux_listed_info_revisions_version
    ON jquants_listed_info_revisions
       (source, code, snapshot_date, available_at, ingested_at);

CREATE TABLE IF NOT EXISTS jquants_daily_bars_revisions AS
    SELECT * FROM jquants_daily_bars WHERE 0;
CREATE UNIQUE INDEX IF NOT EXISTS ux_daily_bars_revisions_version
    ON jquants_daily_bars_revisions
       (source, code, date, available_at, ingested_at);

CREATE TABLE IF NOT EXISTS jquants_market_calendar_revisions AS
    SELECT * FROM jquants_market_calendar WHERE 0;
CREATE UNIQUE INDEX IF NOT EXISTS ux_market_calendar_revisions_version
    ON jquants_market_calendar_revisions
       (source, date, available_at, ingested_at);

CREATE INDEX IF NOT EXISTS ix_bars_available_at
    ON jquants_daily_bars (code, available_at);
CREATE INDEX IF NOT EXISTS ix_calendar_available_at
    ON jquants_market_calendar (date, available_at);
CREATE INDEX IF NOT EXISTS ix_master_available_at
    ON jquants_listed_info (code, available_at);
