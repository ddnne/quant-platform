"""Natural-key correctness for multi-observation J-Quants series.

Minute bars, ticks, Nikkei-225 option contracts and TDnet disclosures are
*multi-observation*: many rows share a ``(Code, Date)`` — or just a ``Date``.
Their natural key MUST carry the per-observation discriminator (``DateTime`` /
``Time`` / ``Code`` / ``DiscNo``) or the store's upsert collapses every
observation of that day onto the last row written — the P1 natural-key bug.

These tests pin the behavior at two levels:

* the normalizer — distinct source rows produce distinct ``natural_key`` JSON
  strings; and
* the store — every bar survives an ``upsert`` into ``jquants_records``.

Minute bars add a canonicalization guard: the bulk CSV carries ``DateTime``
while the REST surface splits it into ``Date`` + ``Time``, yet both describe
the *same* observation. The discriminator is canonicalized to a single
``Time`` = ``HH:MM`` so re-ingesting a bar via the other transport upserts
rather than inserting a duplicate (the inverse-collapse bug).

A regression guard confirms daily bars (one observation per ``(Code, Date)``)
still collapse to a single key, so the fix did not over-broaden.
"""

from __future__ import annotations

import json

from ingestion.jquants.normalize import normalize_generic
from storage.sqlite_store import SqliteStore

ING = "2025-04-02T09:00:00+09:00"


def _keys(rows, dataset):
    return [r["natural_key"] for r in
            normalize_generic(rows, dataset=dataset, ingested_at=ING)]


# --------------------------------------------------------------------------- minute bars

def test_minute_bars_distinguish_per_minute_via_datetime():
    """Bulk-CSV minute bars carry ``DateTime``: same Code/Date, different minute
    -> distinct natural keys (no collapse). The discriminator lands in the key
    as the canonical ``Time`` = HH:MM."""
    rows = [
        {"Code": "8697", "Date": "2025-04-01",
         "DateTime": "2025-04-01T09:00:00+09:00", "C": 100},
        {"Code": "8697", "Date": "2025-04-01",
         "DateTime": "2025-04-01T09:01:00+09:00", "C": 101},
    ]
    keys = _keys(rows, "equities_bars_minute")
    assert len(set(keys)) == 2
    nk = json.loads(keys[0])
    assert nk["Code"] == "8697" and nk["Date"] == "2025-04-01"
    assert nk["Time"] == "09:00"  # DateTime canonicalized to HH:MM
    assert "DateTime" not in nk  # folded away, not doubled up


def test_minute_bars_rest_variant_uses_date_plus_time():
    """REST surface splits the timestamp into ``Date`` + ``Time``; two minutes
    still get distinct keys, and ``Time`` is the discriminator."""
    rows = [
        {"Code": "8697", "Date": "2025-04-01", "Time": "09:00", "C": 100},
        {"Code": "8697", "Date": "2025-04-01", "Time": "09:01", "C": 101},
    ]
    keys = _keys(rows, "equities_bars_minute")
    assert len(set(keys)) == 2
    assert json.loads(keys[0])["Time"] == "09:00"


def test_minute_key_tolerates_lowercase_datetime_alias():
    """V2 mixes casing (``datetime``); the canonicalized key records ``Time``."""
    rows = [{"Code": "8697", "Date": "2025-04-01",
             "datetime": "2025-04-01T09:05:00+09:00", "C": 1}]
    nk = json.loads(_keys(rows, "equities_bars_minute")[0])
    assert nk["Time"] == "09:05"  # lowercase datetime -> canonical HH:MM


def test_minute_bar_same_observation_same_key_across_transports():
    """The same bar fetched via bulk (``DateTime``) and REST (``Date``+``Time``)
    MUST produce the identical natural key. Without canonicalization the second
    ingest inserts a duplicate instead of upserting — the inverse-collapse bug.
    """
    bulk = [{"Code": "8697", "Date": "2025-04-01",
             "DateTime": "2025-04-01T09:00:00+09:00", "C": 100}]
    rest = [{"Code": "8697", "Date": "2025-04-01", "Time": "09:00", "C": 100}]
    assert _keys(bulk, "equities_bars_minute") == _keys(rest, "equities_bars_minute")
    nk = json.loads(_keys(bulk, "equities_bars_minute")[0])
    assert nk == {"Code": "8697", "Date": "2025-04-01", "Time": "09:00"}


def test_minute_bar_rest_time_with_seconds_canonicalizes_to_hhmm():
    """A REST ``Time`` carrying seconds still reduces to HH:MM so it matches the
    bulk ``DateTime`` form of the same minute."""
    rows = [{"Code": "8697", "Date": "2025-04-01", "Time": "09:00:00", "C": 1}]
    assert json.loads(_keys(rows, "equities_bars_minute")[0])["Time"] == "09:00"


# --------------------------------------------------------------------------- tick trades

def test_trades_distinguish_per_tick_via_datetime():
    rows = [
        {"Code": "8697", "Date": "2025-04-01",
         "DateTime": "2025-04-01T09:00:03+09:00"},
        {"Code": "8697", "Date": "2025-04-01",
         "DateTime": "2025-04-01T09:00:04+09:00"},
    ]
    keys = _keys(rows, "equities_trades")
    assert len(set(keys)) == 2
    assert "DateTime" in json.loads(keys[0])


# --------------------------------------------------------------------------- options 225

def test_options_225_distinguishes_contracts_per_date():
    """A date yields one row per Nikkei-225 option contract; ``Date`` alone
    would collapse the whole chain — ``Code`` must disambiguate."""
    rows = [
        {"Date": "2025-04-01", "Code": "180000018", "Strike": 40000, "PCDiv": "2"},
        {"Date": "2025-04-01", "Code": "180000026", "Strike": 40500, "PCDiv": "2"},
        {"Date": "2025-04-01", "Code": "190000018", "Strike": 40000, "PCDiv": "1"},
    ]
    keys = _keys(rows, "derivatives_bars_daily_options_225")
    assert len(set(keys)) == 3
    nk = json.loads(keys[0])
    assert nk["Date"] == "2025-04-01" and "Code" in nk


# --------------------------------------------------------------------------- TDnet

def test_tdnet_distinguishes_disclosures_via_discno():
    """Many disclosures share a date; ``DiscNo`` is the unique per-disclosure id
    and the date field is ``DiscDate`` (not ``Date``)."""
    rows = [
        {"DiscDate": "2025-04-01", "DiscNo": "20250401000001", "Code": "8697",
         "Title": "業績予想の修正"},
        {"DiscDate": "2025-04-01", "DiscNo": "20250401000002", "Code": "8697",
         "Title": "自己株式の取得"},
    ]
    keys = _keys(rows, "td_list")
    assert len(set(keys)) == 2
    nk0 = json.loads(keys[0])
    assert nk0["DiscDate"] == "2025-04-01" and "DiscNo" in nk0


def test_tdnet_files_and_bulk_share_discno_key():
    for ds in ("td_files", "td_bulk"):
        rows = [
            {"DiscDate": "2025-04-01", "DiscNo": "20250401000001"},
            {"DiscDate": "2025-04-01", "DiscNo": "20250401000002"},
        ]
        keys = _keys(rows, ds)
        assert len(set(keys)) == 2, ds


# --------------------------------------------------------------------------- regression

def test_daily_bars_still_collapse_on_code_date():
    """Daily bars are one-observation-per-(Code,Date): identical key -> upsert,
    NOT a new row. Guards against over-broadening the fix."""
    rows = [
        {"Code": "8697", "Date": "2025-04-01", "Close": 100},
        {"Code": "8697", "Date": "2025-04-01", "Close": 101},
    ]
    keys = _keys(rows, "equities_bars_daily")
    assert len(set(keys)) == 1


# --------------------------------------------------------------------------- store upsert

def test_upsert_keeps_all_minute_bars(tmp_path):
    """End-to-end: two minute bars sharing (Code, Date) both survive an upsert
    into jquants_records — the behavior the fix restores."""
    store = SqliteStore(tmp_path / "ing.sqlite")
    rows = [
        {"Code": "8697", "Date": "2025-04-01",
         "DateTime": "2025-04-01T09:00:00+09:00", "C": 100},
        {"Code": "8697", "Date": "2025-04-01",
         "DateTime": "2025-04-01T09:01:00+09:00", "C": 101},
    ]
    norm = normalize_generic(rows, dataset="equities_bars_minute", ingested_at=ING)
    assert store.upsert("jquants_records", norm) == 2
    assert store.count("jquants_records") == 2
    # re-upsert of the same data is idempotent — still 2, not 4
    store.upsert("jquants_records", norm)
    assert store.count("jquants_records") == 2
    store.close()


def test_upsert_collapses_cross_transport_duplicate(tmp_path):
    """The same minute bar ingested via bulk (``DateTime``) then REST (``Time``)
    upserts to ONE row, not two — the canonicalized key makes the second ingest
    an update rather than an insert (the inverse-collapse regression)."""
    store = SqliteStore(tmp_path / "ing.sqlite")
    bulk = [{"Code": "8697", "Date": "2025-04-01",
             "DateTime": "2025-04-01T09:00:00+09:00", "C": 100}]
    rest = [{"Code": "8697", "Date": "2025-04-01", "Time": "09:00", "C": 100}]
    store.upsert("jquants_records",
                 normalize_generic(bulk, dataset="equities_bars_minute", ingested_at=ING))
    store.upsert("jquants_records",
                 normalize_generic(rest, dataset="equities_bars_minute", ingested_at=ING))
    assert store.count("jquants_records") == 1
    store.close()


def test_upsert_keeps_all_option_contracts(tmp_path):
    store = SqliteStore(tmp_path / "ing.sqlite")
    rows = [
        {"Date": "2025-04-01", "Code": "180000018", "C": 50},
        {"Date": "2025-04-01", "Code": "180000026", "C": 51},
        {"Date": "2025-04-01", "Code": "190000018", "C": 12},
    ]
    norm = normalize_generic(
        rows, dataset="derivatives_bars_daily_options_225", ingested_at=ING
    )
    assert store.upsert("jquants_records", norm) == 3
    assert store.count("jquants_records") == 3
    store.close()


def test_upsert_keeps_all_tdnet_disclosures(tmp_path):
    store = SqliteStore(tmp_path / "ing.sqlite")
    rows = [
        {"DiscDate": "2025-04-01", "DiscNo": "20250401000001", "Code": "8697"},
        {"DiscDate": "2025-04-01", "DiscNo": "20250401000002", "Code": "8697"},
    ]
    norm = normalize_generic(rows, dataset="td_list", ingested_at=ING)
    assert store.upsert("jquants_records", norm) == 2
    assert store.count("jquants_records") == 2
    store.close()
