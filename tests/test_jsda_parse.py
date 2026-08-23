"""JSDA parser, normalizer and end-to-end pipeline (offline)."""

from __future__ import annotations

import csv
import inspect
import io
from pathlib import Path

from ingestion.jsda.normalize import normalize_bond_trades
from ingestion.jsda.parse import parse_csv, parse_otc_reference_csv
from ingestion.jsda.urls import index_url, pick_latest, resolve_download_links
from ingestion.pipeline import run_jsda
from storage.sqlite_store import SqliteStore

_FIXTURES = Path(__file__).parent / "fixtures"


# --------------------------------------------------------------------------- parse

def test_parse_fixture_yields_three_records(jsda_sample_text):
    records = parse_csv(jsda_sample_text)
    assert len(records) == 3
    first = records[0]
    assert first["trade_date"] == "2025-04-01"
    assert first["isin"] == "JP0000000005"
    assert first["issuer_name"].startswith("株式会社A")
    assert first["close_yield"] == 0.410
    assert first["trade_amount"] == 500.0
    # different date on the third row
    assert records[2]["trade_date"] == "2025-04-02"


def test_parse_handles_bytes_and_cp932():
    cp932_bytes = (
        "銘柄名,ISINコード,利率(%),償還年月日,年月日,終値利回り(%),取引金額(百万円)\n"
        "株式会社Z 第9回,JP0000000099,0.50,2029-12-31,2025-05-01,0.470,800\n"
    ).encode("cp932")
    records = parse_csv(cp932_bytes)
    assert len(records) == 1
    assert records[0]["isin"] == "JP0000000099"
    assert records[0]["issuer_name"].startswith("株式会社Z")


def test_parse_ignores_title_rows_without_date():
    text = (
        "# 日本証券業協会 情報\n"
        "（注）サンプルデータです\n"
        "\n"
        "銘柄名,年月日,終値利回り(%)\n"
        "株式会社A,2025-04-01,0.410\n"
    )
    records = parse_csv(text)
    assert len(records) == 1
    assert records[0]["trade_date"] == "2025-04-01"


def _otc_raw_row_count(text: str) -> int:
    return sum(1 for row in csv.reader(io.StringIO(text)) if any(c.strip() for c in row))


def test_otc_headerless_23col_maps_overlapping_positional_fields():
    # Synthetic prefix of the 29-col fixture; not a live 2002-08-02 COMPLETE seal.
    text = (_FIXTURES / "jsda_otc_reference_headerless_23col.csv").read_text(
        encoding="utf-8"
    )
    raw_count = _otc_raw_row_count(text)
    records = parse_otc_reference_csv(
        text.encode("cp932"),
        publication_label_date="2002-08-02",
        quote_effective_date="2002-08-01",
    )
    assert records, "23-col adapter must yield nz parse"
    assert len(records) == raw_count == 2
    first = records[0]
    assert first["publication_label_date"] == "2002-08-02"
    assert first["quote_effective_date"] == "2002-08-01"
    assert first["security_code"] == "123456789"
    assert first["bond_name"] == "10年国債"
    assert first["maturity_date"] == "2012-08-20"
    assert first["coupon_rate"] == 1.5
    assert first["average_yield"] == 1.225
    assert first["average_price"] == 99.85
    assert first["individual_investor_flag"] == "0"
    assert first["high_price"] == 100.0
    assert first["low_price"] == 99.5
    assert first["high_yield"] == 1.1
    assert first["low_yield"] is None
    assert first["median_yield"] is None
    assert first["median_price"] is None
    assert first["source_row_number"] == 1
    assert records[1]["security_code"] == "987654321"
    assert records[1]["individual_investor_flag"] == "1"
    for rec in records:
        assert rec.get("status") != "COMPLETE"
        assert "COMPLETE" not in rec.values()


def test_otc_headerless_23col_overlapping_fields_match_29col_prefix():
    full = (_FIXTURES / "jsda_otc_reference_headerless.csv").read_text(encoding="utf-8")
    early = (_FIXTURES / "jsda_otc_reference_headerless_23col.csv").read_text(
        encoding="utf-8"
    )
    kwargs = {
        "publication_label_date": "2002-08-02",
        "quote_effective_date": "2002-08-01",
    }
    full_records = parse_otc_reference_csv(full, **kwargs)
    early_records = parse_otc_reference_csv(early, **kwargs)
    overlapping = (
        "publication_label_date",
        "quote_effective_date",
        "security_code",
        "bond_name",
        "coupon_rate",
        "maturity_date",
        "average_price",
        "average_yield",
        "high_price",
        "high_yield",
        "low_price",
        "individual_investor_flag",
        "source_row_number",
    )
    assert len(full_records) == len(early_records) == 2
    for full_row, early_row in zip(full_records, early_records):
        for field in overlapping:
            assert early_row[field] == full_row[field]
        for field in ("low_yield", "median_yield", "median_price"):
            assert early_row[field] is None
            assert full_row[field] is not None


def test_otc_headerless_short_non_identity_stays_parse_zero():
    text = "not-a-date,x,code,name,20020820,1.5,1.2,99.8\n"
    assert parse_otc_reference_csv(text) == []


def test_otc_headerless_23col_nz_parse_is_not_coverage_complete():
    text = (_FIXTURES / "jsda_otc_reference_headerless_23col.csv").read_text(
        encoding="utf-8"
    )
    records = parse_otc_reference_csv(
        text.encode("cp932"),
        publication_label_date="2002-08-02",
        quote_effective_date="2002-08-01",
    )
    assert records, "23-col adapter must yield nz parse"
    assert len(records) == _otc_raw_row_count(text) == 2
    for rec in records:
        assert rec.get("status") != "COMPLETE"
        assert "COMPLETE" not in rec.values()


def test_seal_complete_is_separate_function_parser_output_is_not_complete():
    parse_src = inspect.getsource(parse_otc_reference_csv)
    assert "COMPLETE" not in parse_src
    root = Path(__file__).resolve().parents[1]
    seal_src = (root / "scripts" / "jsda_otc_seal_official.py").read_text(
        encoding="utf-8"
    )
    assert "def seal_day" in seal_src
    assert "int(structured) != int(raw_count)" in seal_src
    assert "raw_manifest_digest=digest" in seal_src
    # Live 2002-08-02/05 stay unsealed without in-repo digest+count proof.
    live_names = {
        "S020802.csv",
        "S020805.csv",
        "20020802.csv",
        "20020805.csv",
        "2002-08-02.csv",
        "2002-08-05.csv",
    }
    assert {p.name for p in _FIXTURES.iterdir()}.isdisjoint(live_names)


# --------------------------------------------------------------------------- normalize

def test_normalize_adds_pit_columns(jsda_sample_text):
    records = parse_csv(jsda_sample_text)
    rows = normalize_bond_trades(records, ingested_at="2025-04-02T09:00:00+09:00")
    assert len(rows) == 3
    for r in rows:
        assert r["source"] == "jsda"
        for col in ("event_time", "available_at", "source", "ingested_at"):
            assert r[col]  # non-empty
        # available_at defaults to ingested_at
        assert r["available_at"] == "2025-04-02T09:00:00+09:00"
    assert rows[0]["event_time"].startswith("2025-04-01T15:00:00")
    # isin/issuer_name default to '' when absent (PK safety)
    assert isinstance(rows[0]["isin"], str)


# --------------------------------------------------------------------------- urls

def test_resolve_links_absolutizes():
    html = (
        '<html><body>'
        '<a href="docs/r0701/ksaiki.csv">CSV</a>'
        '<a href="/files/2024/saiken.xlsx">XLSX</a>'
        '<a href="/about.html">about</a>'
        '</body></html>'
    )
    links = resolve_download_links(html)
    assert len(links) == 2
    assert links[0].endswith("ksaiki.csv")
    assert links[1].endswith("saiken.xlsx")
    assert all(l.startswith("https://") for l in links)


def test_pick_latest_prefers_newer_year():
    links = [
        "https://www.jsda.or.jp/a/2023/saiken.csv",
        "https://www.jsda.or.jp/a/2025/saiken.csv",
        "https://www.jsda.or.jp/a/2024/saiken.csv",
    ]
    assert pick_latest(links).endswith("2025/saiken.csv")
    assert pick_latest([]) is None


# --------------------------------------------------------------------------- pipeline (integration, offline)

def _index_html_with_csv(csv_url: str) -> str:
    return f'<html><body><a href="{csv_url}">最新データ</a></body></html>'


def test_run_jsda_end_to_end_idempotent(tmp_path: Path, jsda_sample_text: str):
    csv_url = "https://www.jsda.or.jp/mock/2025/saiken.csv"

    # Minimal in-memory client: index page -> links, file -> fixture bytes.
    class _Client:
        name = "local"

        def __init__(self):
            self.calls = []

        def get(self, url, *, headers=None, params=None, timeout=30.0):
            from ingestion.common.http import HttpResponse

            self.calls.append(url)
            if url == index_url():
                return HttpResponse(
                    200, {"content-type": "text/html"},
                    _index_html_with_csv(csv_url).encode("utf-8"), url,
                )
            if url == csv_url:
                return HttpResponse(
                    200, {"content-type": "text/csv"},
                    jsda_sample_text.encode("utf-8"), url,
                )
            return HttpResponse(404, {}, b"", url)

    store = SqliteStore(tmp_path / "ing.sqlite")
    http = _Client()

    # repo=False keeps this a focused bond-trade test (its _Client only mocks
    # the bond index). Repo rates have their own offline tests.
    reps = run_jsda(
        http=http, store=store, data_base=tmp_path, today="2025-04-02", repo=False,
    )
    assert len(reps) == 1 and reps[0].ok
    assert reps[0].registered == 3
    assert store.count("jsda_bond_trades") == 3

    # Raw saved under partitioned path (filename is timestamp-stamped so
    # same-day re-fetches do not clobber each other).
    raw_dir = tmp_path / "raw" / "jsda" / "2025" / "04" / "02"
    matches = list(raw_dir.glob("saiken_*.csv"))
    assert len(matches) == 1 and matches[0].exists()

    # Re-running the same day is idempotent: no duplicate rows.
    http2 = _Client()
    reps2 = run_jsda(
        http=http2, store=store, data_base=tmp_path, today="2025-04-02", repo=False,
    )
    assert reps2[0].ok
    assert store.count("jsda_bond_trades") == 3

    # available_at present on persisted rows.
    rows = store.fetch_all("jsda_bond_trades")
    assert all(r["available_at"] for r in rows)
    assert all(r["event_time"] for r in rows)
    store.close()


def test_run_jsda_missing_key_not_required_but_cloudflare_skips(tmp_path: Path):
    # JSDA needs no key; only cloudflare runtime skips.
    from ingestion.common.http import HttpResponse

    class _Client:
        name = "cloudflare"

        def get(self, *a, **k):
            raise AssertionError("cloudflare must not fetch")

    store = SqliteStore(tmp_path / "ing.sqlite")
    reps = run_jsda(
        http=_Client(), store=store, data_base=tmp_path,
        today="2025-04-02", runtime="cloudflare",
    )
    assert len(reps) == 1
    assert reps[0].skipped
    store.close()
