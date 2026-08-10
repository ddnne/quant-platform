"""JSDA parser, normalizer and end-to-end pipeline (offline)."""

from __future__ import annotations

import json
from pathlib import Path

from ingestion.jsda.normalize import normalize_bond_trades
from ingestion.jsda.parse import parse_csv
from ingestion.jsda.urls import index_url, pick_latest, resolve_download_links
from ingestion.pipeline import run_jsda
from storage.sqlite_store import SqliteStore


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

    reps = run_jsda(http=http, store=store, data_base=tmp_path, today="2025-04-02")
    assert len(reps) == 1 and reps[0].ok
    assert reps[0].registered == 3
    assert store.count("jsda_bond_trades") == 3

    # Raw saved under partitioned path.
    raw_file = tmp_path / "raw" / "jsda" / "2025" / "04" / "02" / "saiken.csv"
    assert raw_file.exists()

    # Re-running the same day is idempotent: no duplicate rows.
    http2 = _Client()
    reps2 = run_jsda(http=http2, store=store, data_base=tmp_path, today="2025-04-02")
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
