"""JSDA repo-rate (東京レポ・レート / TRR) parser, normalizer and pipeline.

Offline — no network. Mirrors ``test_jsda_parse.py`` for bond trades.
"""

from __future__ import annotations

from pathlib import Path

from ingestion.common.http import HttpResponse
from ingestion.jsda.normalize import normalize_repo_rates
from ingestion.jsda.parse import parse_repo_csv
from ingestion.jsda.urls import (
    pick_repo_file,
    repo_index_url,
    resolve_repo_links,
)
from ingestion.pipeline import decide_exit, run_jsda
from storage.sqlite_store import SqliteStore

_FIXTURE = Path(__file__).parent / "fixtures" / "jsda_repo_sample.csv"


def _repo_sample_text() -> str:
    return _FIXTURE.read_text(encoding="utf-8")


# --------------------------------------------------------------------------- parse (wide)

def test_parse_wide_fixture_yields_day_times_tenors():
    records = parse_repo_csv(_repo_sample_text())
    # 2 days x 8 tenors
    assert len(records) == 16
    first = records[0]
    assert first["as_of_date"] == "2025-04-01"
    assert first["tenor"] == "隔日物"
    assert first["rate"] == -0.05
    # 12-month tenor of day 1
    last_day1 = records[7]
    assert last_day1["tenor"] == "12ヶ月物"
    assert last_day1["rate"] == 0.13
    # second day carried through
    assert records[8]["as_of_date"] == "2025-04-02"
    assert records[8]["tenor"] == "隔日物"


def test_parse_wide_skips_blank_tenor_cell():
    # A blank cell for one tenor on one day -> that (day, tenor) is absent,
    # other tenors still parse.
    text = (
        "年月日,隔日物,1ヶ月物\n"
        "2025-04-01,-0.050,0.000\n"
        "2025-04-02,,-0.001\n"
    )
    records = parse_repo_csv(text)
    assert len(records) == 3  # 2 + 1 (隔日物 on 04-02 is blank)
    assert {r["as_of_date"] for r in records} == {"2025-04-01", "2025-04-02"}


# --------------------------------------------------------------------------- parse (long)

def test_parse_long_layout_with_tenor_column():
    text = (
        "年月日,期間,レート(%)\n"
        "2025-04-01,隔日物,-0.050\n"
        "2025-04-01,1ヶ月物,0.000\n"
        "2025-04-02,1ヶ月物,0.002\n"
    )
    records = parse_repo_csv(text)
    assert len(records) == 3
    assert records[0] == {"as_of_date": "2025-04-01", "tenor": "隔日物", "rate": -0.05}
    assert records[2]["tenor"] == "1ヶ月物" and records[2]["rate"] == 0.002


def test_parse_long_layout_skips_empty_observations():
    text = (
        "年月日,期間,レート(%)\n"
        "2025-04-01,隔日物,-\n"
        "2025-04-01,,0.010\n"
        "2025-04-01,1ヶ月物,\n"
        "2025-04-01,3ヶ月物,0.020\n"
    )
    assert parse_repo_csv(text) == [
        {"as_of_date": "2025-04-01", "tenor": "3ヶ月物", "rate": 0.02}
    ]


def test_parse_handles_bytes_and_cp932():
    cp932_bytes = (
        "年月日,隔日物,1ヶ月物\n"
        "2025-05-01,-0.040,0.001\n"
    ).encode("cp932")
    records = parse_repo_csv(cp932_bytes)
    assert len(records) == 2
    assert records[0]["tenor"] == "隔日物"


def test_parse_ignores_title_rows_without_date():
    text = (
        "# 日本証券業協会 東京レポ・レート\n"
        "（注）サンプルデータです\n"
        "\n"
        "年月日,隔日物,1ヶ月物\n"
        "2025-04-01,-0.050,0.000\n"
    )
    records = parse_repo_csv(text)
    assert len(records) == 2
    assert records[0]["as_of_date"] == "2025-04-01"


def test_parse_strips_percent_and_comma():
    text = (
        "年月日,1ヶ月物\n"
        "2025-04-01,0.020%\n"
        "2025-04-02,0.030\n"
    )
    records = parse_repo_csv(text)
    assert [r["rate"] for r in records] == [0.02, 0.03]


# --------------------------------------------------------------------------- normalize

def test_normalize_adds_pit_columns_and_rate_type():
    records = parse_repo_csv(_repo_sample_text())
    rows = normalize_repo_rates(records, ingested_at="2025-04-02T09:00:00+09:00")
    assert len(rows) == 16
    for r in rows:
        assert r["source"] == "jsda"
        assert r["rate_type"] == "東京レポ・レート"
        for col in ("event_time", "available_at", "source", "ingested_at", "tenor"):
            assert r[col] != ""  # populated
        # available_at defaults to ingested_at (仮)
        assert r["available_at"] == "2025-04-02T09:00:00+09:00"
    # event_time = as_of day at 15:00 JST (market close)
    assert rows[0]["event_time"].startswith("2025-04-01T15:00:00")
    # raw_payload preserves the source record
    assert "隔日物" in rows[0]["raw_payload"]


def test_normalize_rate_type_override():
    rows = normalize_repo_rates(
        [{"as_of_date": "2025-04-01", "tenor": "1ヶ月物", "rate": 0.01}],
        ingested_at="2025-04-02T09:00:00+09:00",
        rate_type="GCレポレート",
    )
    assert rows[0]["rate_type"] == "GCレポレート"


# --------------------------------------------------------------------------- urls

def test_resolve_repo_links_absolutizes_against_repo_index():
    html = (
        '<html><body>'
        '<a href="files/trrts.xls">一覧</a>'
        '<a href="files/trr.xls">最新</a>'
        '<a href="/about.html">about</a>'
        '</body></html>'
    )
    links = resolve_repo_links(html)
    assert len(links) == 2
    assert all(l.startswith(repo_index_url()) for l in links)
    assert links[0].endswith("files/trrts.xls")


def test_pick_repo_file_prefers_timeseries_then_trr_then_year():
    ts = pick_repo_file([
        "https://www.jsda.or.jp/shiryoshitsu/toukei/trr/files/trr.xls",
        "https://www.jsda.or.jp/shiryoshitsu/toukei/trr/files/trrts.xls",
    ])
    assert ts.endswith("trrts.xls")

    only_trr = pick_repo_file([
        "https://www.jsda.or.jp/shiryoshitsu/toukei/trr/files/trr.xls",
    ])
    assert only_trr.endswith("trr.xls")

    # reference (別紙) attachments are excluded; falls back to a year file.
    fallback = pick_repo_file([
        "https://www.jsda.or.jp/shiryoshitsu/toukei/trr/files/bessi2-2024reference.xlsx",
        "https://www.jsda.or.jp/shiryoshitsu/toukei/trr/files/2024/repo.csv",
    ])
    assert fallback.endswith("2024/repo.csv")

    # only non-rate docs -> None
    assert pick_repo_file([
        "https://www.jsda.or.jp/shiryoshitsu/toukei/trr/files/bessi2-2025reference.xlsx",
    ]) is None
    assert pick_repo_file([]) is None


# --------------------------------------------------------------------------- pipeline (integration, offline)

def _repo_index_html_with_csv(csv_url: str) -> str:
    return f'<html><body><a href="{csv_url}">東京レポ・レート（一覧）</a></body></html>'


class _RepoClient:
    """Routes the TRR index + a repo CSV file; 404 otherwise."""

    name = "local"

    def __init__(self, csv_url: str, csv_bytes: bytes):
        self.csv_url = csv_url
        self.csv_bytes = csv_bytes
        self.calls: list[str] = []

    def get(self, url, *, headers=None, params=None, timeout=30.0):
        self.calls.append(url)
        if url == repo_index_url():
            return HttpResponse(
                200, {"content-type": "text/html"},
                _repo_index_html_with_csv(self.csv_url).encode("utf-8"), url,
            )
        if url == self.csv_url:
            return HttpResponse(
                200, {"content-type": "text/csv"}, self.csv_bytes, url,
            )
        return HttpResponse(404, {}, b"", url)


def test_run_jsda_repo_end_to_end_idempotent(tmp_path: Path):
    csv_url = "https://www.jsda.or.jp/shiryoshitsu/toukei/trr/files/trr_repo.csv"
    csv_bytes = _repo_sample_text().encode("utf-8")

    store = SqliteStore(tmp_path / "ing.sqlite")
    http = _RepoClient(csv_url, csv_bytes)

    reps = run_jsda(
        http=http, store=store, data_base=tmp_path, today="2025-04-02",
        bond=False, repo=True,
    )
    assert len(reps) == 1 and reps[0].ok
    assert reps[0].registered == 16
    assert store.count("jsda_repo_rates") == 16

    # raw saved under the day partition, filename timestamp-stamped
    raw_dir = tmp_path / "raw" / "jsda" / "2025" / "04" / "02"
    matches = list(raw_dir.glob("trr_repo_*.csv"))
    assert len(matches) == 1 and matches[0].exists()

    # idempotent re-run -> no duplicate rows
    http2 = _RepoClient(csv_url, csv_bytes)
    reps2 = run_jsda(
        http=http2, store=store, data_base=tmp_path, today="2025-04-02",
        bond=False, repo=True,
    )
    assert reps2[0].ok
    assert store.count("jsda_repo_rates") == 16

    # available_at / event_time present on persisted rows
    rows = store.fetch_all("jsda_repo_rates")
    assert all(r["available_at"] for r in rows)
    assert all(r["event_time"] for r in rows)
    assert all(r["rate_type"] == "東京レポ・レート" for r in rows)
    store.close()


def test_run_jsda_repo_available_at_required(tmp_path: Path):
    # The store's PIT gate rejects a missing available_at; confirm the table
    # is wired through the same Registrar path.
    store = SqliteStore(tmp_path / "ing.sqlite")
    rows = normalize_repo_rates(
        [{"as_of_date": "2025-04-01", "tenor": "1ヶ月物", "rate": 0.0}],
        ingested_at="2025-04-02T09:00:00+09:00",
    )
    rows[0]["available_at"] = None
    from storage.sqlite_store import MissingAvailableAt

    import pytest

    with pytest.raises(MissingAvailableAt):
        store.upsert("jsda_repo_rates", rows)
    assert store.count("jsda_repo_rates") == 0
    store.close()


def test_run_jsda_repo_legacy_xls_clean_skip(tmp_path: Path):
    # The real TRR source publishes .xls. Ingestion must SKIP cleanly (not
    # error), so a --source jsda run stays green when bond trades succeed.
    xls_url = "https://www.jsda.or.jp/shiryoshitsu/toukei/trr/files/trrts.xls"

    class _XlsClient:
        name = "local"

        def get(self, url, *, headers=None, params=None, timeout=30.0):
            if url == repo_index_url():
                return HttpResponse(
                    200, {"content-type": "text/html"},
                    f'<html><a href="{xls_url}">一覧</a></html>'.encode("utf-8"), url,
                )
            if url == xls_url:
                # legacy XLS (OLE2) magic, not ZIP/PK
                return HttpResponse(200, {}, b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1xls", url)
            return HttpResponse(404, {}, b"", url)

    store = SqliteStore(tmp_path / "ing.sqlite")
    reps = run_jsda(
        http=_XlsClient(), store=store, data_base=tmp_path, today="2025-04-02",
        bond=False, repo=True,
    )
    assert len(reps) == 1
    assert reps[0].skipped and "unsupported" in reps[0].skipped
    assert not reps[0].error
    assert store.count("jsda_repo_rates") == 0
    # a clean skip does not fail the run on its own
    assert decide_exit(reps) == 2
    store.close()


def test_run_jsda_repo_empty_index_clean_skip(tmp_path: Path):
    class _EmptyClient:
        name = "local"

        def get(self, url, *, headers=None, params=None, timeout=30.0):
            if url == repo_index_url():
                return HttpResponse(
                    200, {"content-type": "text/html"},
                    b"<html><body>no links</body></html>", url,
                )
            return HttpResponse(404, {}, b"", url)

    store = SqliteStore(tmp_path / "ing.sqlite")
    reps = run_jsda(
        http=_EmptyClient(), store=store, data_base=tmp_path, today="2025-04-02",
        bond=False, repo=True,
    )
    assert len(reps) == 1 and reps[0].skipped
    store.close()


def test_run_jsda_default_runs_bond_and_repo_independently(tmp_path: Path):
    # Default run_jsda does BOTH. Bond succeeds, repo succeeds -> 2 OK reports.
    bond_url = "https://www.jsda.or.jp/mock/2025/saiken.csv"
    repo_url = "https://www.jsda.or.jp/shiryoshitsu/toukei/trr/files/trr_repo.csv"
    bond_bytes = (
        "銘柄名,ISINコード,利率(%),償還年月日,年月日,終値利回り(%),取引金額(百万円)\n"
        "株式会社A 第5回,JP0000000005,0.45,2030-03-31,2025-04-01,0.410,500\n"
    ).encode("utf-8")
    repo_bytes = _repo_sample_text().encode("utf-8")

    from ingestion.jsda.urls import index_url

    class _BothClient:
        name = "local"

        def get(self, url, *, headers=None, params=None, timeout=30.0):
            if url == index_url():
                return HttpResponse(
                    200, {"content-type": "text/html"},
                    f'<html><a href="{bond_url}">bond</a></html>'.encode("utf-8"), url,
                )
            if url == repo_index_url():
                return HttpResponse(
                    200, {"content-type": "text/html"},
                    f'<html><a href="{repo_url}">repo</a></html>'.encode("utf-8"), url,
                )
            if url == bond_url:
                return HttpResponse(200, {"content-type": "text/csv"}, bond_bytes, url)
            if url == repo_url:
                return HttpResponse(200, {"content-type": "text/csv"}, repo_bytes, url)
            return HttpResponse(404, {}, b"", url)

    store = SqliteStore(tmp_path / "ing.sqlite")
    reps = run_jsda(http=_BothClient(), store=store, data_base=tmp_path, today="2025-04-02")
    by_kind = {r.kind: r for r in reps}
    assert set(by_kind) == {"bond_trades", "repo_rates"}
    assert by_kind["bond_trades"].ok and by_kind["bond_trades"].registered == 1
    assert by_kind["repo_rates"].ok and by_kind["repo_rates"].registered == 16
    assert store.count("jsda_bond_trades") == 1
    assert store.count("jsda_repo_rates") == 16
    # both ok -> exit 0
    assert decide_exit(reps) == 0
    store.close()
