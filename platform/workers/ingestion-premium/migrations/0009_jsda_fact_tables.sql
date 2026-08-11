-- JSDA fact tables on quant-ingest (control/evidence plane).
-- No local_snapshot_policy triggers (that table is local-research only).

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

CREATE TABLE IF NOT EXISTS jsda_otc_bond_reference_prices_revisions AS
  SELECT * FROM jsda_otc_bond_reference_prices WHERE 0;

CREATE TABLE IF NOT EXISTS jsda_corporate_bond_transactions (
  source                 TEXT NOT NULL,
  publication_label_date TEXT NOT NULL,
  trade_date             TEXT NOT NULL,
  security_code          TEXT NOT NULL DEFAULT '',
  source_record_id       TEXT NOT NULL DEFAULT '',
  issuer_name            TEXT NOT NULL DEFAULT '',
  isin                   TEXT NOT NULL DEFAULT '',
  event_time             TEXT NOT NULL,
  available_at           TEXT NOT NULL,
  ingested_at            TEXT NOT NULL,
  coupon_rate            REAL,
  maturity_date          TEXT,
  price                  REAL,
  yield                  REAL,
  face_value             REAL,
  source_url             TEXT NOT NULL,
  raw_digest             TEXT NOT NULL,
  segment_id             TEXT NOT NULL,
  source_format          TEXT NOT NULL,
  raw_payload            TEXT,
  PRIMARY KEY (source, publication_label_date, security_code, source_record_id)
);

CREATE TABLE IF NOT EXISTS jsda_corporate_bond_transactions_revisions AS
  SELECT * FROM jsda_corporate_bond_transactions WHERE 0;

CREATE TABLE IF NOT EXISTS jsda_repo_rates (
  source          TEXT NOT NULL,
  as_of_date      TEXT NOT NULL,
  tenor           TEXT NOT NULL DEFAULT '',
  rate_type       TEXT NOT NULL DEFAULT '',
  rate            REAL,
  event_time      TEXT NOT NULL,
  available_at    TEXT NOT NULL,
  ingested_at     TEXT NOT NULL,
  source_url      TEXT,
  raw_digest      TEXT,
  segment_id      TEXT,
  source_format   TEXT,
  raw_payload     TEXT,
  PRIMARY KEY (source, as_of_date, tenor, rate_type)
);
