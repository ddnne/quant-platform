"""SQLite schema for structured ingestion rows.

Every fact table carries the PIT columns ``event_time`` / ``available_at`` /
``source`` / ``ingested_at`` and a ``raw_payload`` JSON blob for traceability.
The primary table keeps one current row per source natural key, while a
matching ``*_revisions`` table retains values displaced by amendments.  PIT
reads union both tables and select the newest revision that was available at
the requested instant.

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

-- Generic catch-all for catalog-mode J-Quants ingestion, including the three
-- datasets that also have legacy specialized tables above.  The natural key
-- is a JSON object of identity fields (e.g. {"Code":..,"Date":..}) or a
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

-- Governed 公社債店頭売買参考統計値 archive (2002 -> current). This is
-- intentionally separate from the legacy ``jsda_bond_trades`` table, whose
-- historical implementation used the corporate-transaction index while
-- normalizing reference-price-like columns. No legacy row is rewritten.
CREATE TABLE IF NOT EXISTS jsda_otc_bond_reference_prices (
    source                   TEXT NOT NULL,
    publication_label_date   TEXT NOT NULL,
    quote_effective_date     TEXT NOT NULL,
    security_code            TEXT NOT NULL DEFAULT '',
    bond_name                TEXT NOT NULL DEFAULT '',
    quote_effective_time     TEXT NOT NULL,
    event_time               TEXT NOT NULL,
    available_at             TEXT NOT NULL,
    ingested_at              TEXT NOT NULL,
    coupon_rate              REAL,
    maturity_date            TEXT,
    average_price            REAL,
    average_yield            REAL,
    median_price             REAL,
    median_yield             REAL,
    high_price               REAL,
    high_yield               REAL,
    low_price                REAL,
    low_yield                REAL,
    individual_investor_flag TEXT,
    source_row_number        INTEGER,
    source_url               TEXT NOT NULL,
    raw_digest               TEXT NOT NULL,
    segment_id               TEXT NOT NULL,
    source_format            TEXT NOT NULL,
    correction_published_at  TEXT,
    raw_payload              TEXT,
    PRIMARY KEY (source, publication_label_date, security_code, bond_name)
);

-- 東京レポ・レート (Tokyo Repo Rate, "TRR"). One row per (as-of day, tenor,
-- rate_type). ``rate`` is the published rate (%). The full source record is
-- kept in ``raw_payload``. See ``docs/data_sources.md`` (JSDA repo section).
CREATE TABLE IF NOT EXISTS jsda_repo_rates (
    source       TEXT NOT NULL,
    as_of_date   TEXT NOT NULL,
    tenor        TEXT NOT NULL DEFAULT '',
    rate_type    TEXT NOT NULL DEFAULT '',
    event_time   TEXT NOT NULL,
    available_at TEXT NOT NULL,
    ingested_at  TEXT NOT NULL,
    rate         REAL,
    raw_payload  TEXT,
    PRIMARY KEY (source, as_of_date, tenor, rate_type)
);

-- Amendment history.  These tables deliberately mirror their
-- primary fact table.  A unique business-key + available_at index makes
-- retries idempotent while allowing multiple published revisions of one
-- observation to coexist.  ``CREATE ... AS SELECT ... WHERE 0`` also upgrades
-- existing databases without rebuilding or rewriting their primary tables.
CREATE TABLE IF NOT EXISTS jquants_listed_info_revisions AS
    SELECT * FROM jquants_listed_info WHERE 0;
CREATE UNIQUE INDEX IF NOT EXISTS ux_listed_info_revisions_version
    ON jquants_listed_info_revisions
       (source, code, snapshot_date, available_at);

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
    ON jquants_records_revisions
       (source, dataset, natural_key, available_at);

CREATE TABLE IF NOT EXISTS jsda_bond_trades_revisions AS
    SELECT * FROM jsda_bond_trades WHERE 0;
CREATE UNIQUE INDEX IF NOT EXISTS ux_bond_trades_revisions_version
    ON jsda_bond_trades_revisions
       (source, trade_date, isin, issuer_name, available_at);

CREATE TABLE IF NOT EXISTS jsda_otc_bond_reference_prices_revisions AS
    SELECT * FROM jsda_otc_bond_reference_prices WHERE 0;
CREATE UNIQUE INDEX IF NOT EXISTS ux_otc_bond_reference_revisions_version
    ON jsda_otc_bond_reference_prices_revisions
       (source, publication_label_date, security_code, bond_name,
        available_at, ingested_at);

CREATE TABLE IF NOT EXISTS jsda_repo_rates_revisions AS
    SELECT * FROM jsda_repo_rates WHERE 0;
CREATE UNIQUE INDEX IF NOT EXISTS ux_repo_rates_revisions_version
    ON jsda_repo_rates_revisions
       (source, as_of_date, tenor, rate_type, available_at);

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
CREATE INDEX IF NOT EXISTS ix_jsda_otc_reference_available_at
    ON jsda_otc_bond_reference_prices
       (quote_effective_date, available_at, security_code);
CREATE INDEX IF NOT EXISTS ix_jsda_repo_available_at
    ON jsda_repo_rates (as_of_date, available_at);
"""

# Natural keys for documentation / future dedup tooling.
NATURAL_KEYS: dict[str, list[str]] = {
    "jquants_listed_info": ["source", "code", "snapshot_date"],
    "jquants_daily_bars": ["source", "code", "date"],
    "jquants_market_calendar": ["source", "date"],
    "jquants_records": ["source", "dataset", "natural_key"],
    "jsda_bond_trades": ["source", "trade_date", "isin", "issuer_name"],
    "jsda_otc_bond_reference_prices": [
        "source", "publication_label_date", "security_code", "bond_name"
    ],
    "jsda_repo_rates": ["source", "as_of_date", "tenor", "rate_type"],
}

# Fact table -> amendment history table.  Kept separate from
# ``NATURAL_KEYS`` because primary-table idempotency is still defined solely by
# the business key; ``available_at`` identifies a version only in history.
REVISION_TABLES: dict[str, str] = {
    table: f"{table}_revisions" for table in NATURAL_KEYS
}
