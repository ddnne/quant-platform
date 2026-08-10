"""SQLite schema for structured ingestion rows.

Every table carries the PIT columns ``event_time`` / ``available_at`` /
``source`` / ``ingested_at`` and a ``raw_payload`` JSON blob for traceability.
Idempotency is structural: the ``PRIMARY KEY`` is the source's natural key,
so ``INSERT OR REPLACE`` makes a same-day re-run non-duplicating.

Future R2/D1 layout (documented, not implemented):
  raw/        -> quant-raw/{source}/{yyyy}/{mm}/{dd}/{file}
  structured/ -> quant-structured/{source}/{table}/  (parquet or D1 rows)
"""

from __future__ import annotations

SCHEMA_SQL = """
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

-- Generic catch-all for every other J-Quants catalog dataset (fins, indices,
-- derivatives, markets analytics, EDINET series, minute/tick/TDnet add-ons).
-- Phase 1 prefers one generic table + ``dataset`` column for ingest speed;
-- the three curated series above keep their specialized tables. The natural
-- key is a JSON object of identity fields (e.g. {"Code":..,"Date":..}) or a
-- row-hash fallback — see ingestion.jquants.normalize._natural_key.
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

CREATE TABLE IF NOT EXISTS edinetdb_companies (
    source        TEXT NOT NULL,
    code          TEXT NOT NULL,
    event_time    TEXT NOT NULL,
    available_at  TEXT NOT NULL,
    ingested_at   TEXT NOT NULL,
    company_name  TEXT,
    edinet_code   TEXT,
    sector        TEXT,
    english_name  TEXT,
    raw_payload   TEXT,
    PRIMARY KEY (source, code)
);

CREATE TABLE IF NOT EXISTS edinetdb_financials (
    source          TEXT NOT NULL,
    code            TEXT NOT NULL,
    period          TEXT NOT NULL,
    statement_type  TEXT NOT NULL DEFAULT '',
    event_time      TEXT NOT NULL,
    available_at    TEXT NOT NULL,
    ingested_at     TEXT NOT NULL,
    revenue         REAL,
    operating_income REAL,
    net_income      REAL,
    total_assets    REAL,
    equity          REAL,
    raw_payload     TEXT,
    PRIMARY KEY (source, code, period, statement_type)
);

CREATE TABLE IF NOT EXISTS jsda_bond_trades (
    source              TEXT NOT NULL,
    trade_date          TEXT NOT NULL,
    isin                TEXT NOT NULL DEFAULT '',
    issuer_name         TEXT NOT NULL DEFAULT '',
    event_time          TEXT NOT NULL,
    available_at        TEXT NOT NULL,
    ingested_at         TEXT NOT NULL,
    coupon_rate         REAL,
    maturity_date       TEXT,
    high_yield          REAL,
    low_yield           REAL,
    close_yield         REAL,
    trade_amount_mil_jpy REAL,
    raw_payload         TEXT,
    PRIMARY KEY (source, trade_date, isin, issuer_name)
);

CREATE TABLE IF NOT EXISTS ingestion_run_log (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    ran_at  TEXT    NOT NULL,
    source  TEXT    NOT NULL,
    runtime TEXT    NOT NULL,
    status  TEXT    NOT NULL,
    detail  TEXT
);

CREATE INDEX IF NOT EXISTS ix_bars_available_at
    ON jquants_daily_bars (code, available_at);
CREATE INDEX IF NOT EXISTS ix_records_dataset_avail
    ON jquants_records (dataset, available_at);
CREATE INDEX IF NOT EXISTS ix_jsda_available_at
    ON jsda_bond_trades (trade_date, available_at);
"""

# Natural keys for documentation / future dedup tooling.
NATURAL_KEYS: dict[str, list[str]] = {
    "jquants_listed_info": ["source", "code", "snapshot_date"],
    "jquants_daily_bars": ["source", "code", "date"],
    "jquants_market_calendar": ["source", "date"],
    "jquants_records": ["source", "dataset", "natural_key"],
    "edinetdb_companies": ["source", "code"],
    "edinetdb_financials": ["source", "code", "period", "statement_type"],
    "jsda_bond_trades": ["source", "trade_date", "isin", "issuer_name"],
}
