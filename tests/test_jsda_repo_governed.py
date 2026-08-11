"""Governed JSDA-era Tokyo Repo Rate collection and receipts."""

from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path

import xlrd

from data_contracts import coverage_contract_for, jsda_contract_for
from ingestion.common.http import HttpResponse
from ingestion.jsda.parse import parse_repo_xls
from ingestion.jsda.repo_archive import run_tokyo_repo_backfill
from ingestion.jsda.urls import (
    TOKYO_REPO_DATASET,
    discover_repo_timeseries,
    repo_index_url,
)
from scripts.run_ingestion_once import _build_parser
from storage import read_collection_receipts, read_dataset_coverage
from storage.sqlite_store import SqliteStore


class _Cell:
    def __init__(self, value, ctype):
        self.value = value
        self.ctype = ctype


class _Sheet:
    def __init__(self, rows):
        self._rows = rows
        self.nrows = len(rows)
        self.ncols = max(len(row) for row in rows)

    def cell(self, row, column):
        if column >= len(self._rows[row]):
            return _Cell("", xlrd.XL_CELL_EMPTY)
        value = self._rows[row][column]
        if isinstance(value, datetime):
            serial = xlrd.xldate.xldate_from_date_tuple(
                (value.year, value.month, value.day), 0
            )
            return _Cell(serial, xlrd.XL_CELL_DATE)
        if isinstance(value, (int, float)):
            return _Cell(value, xlrd.XL_CELL_NUMBER)
        return _Cell(value, xlrd.XL_CELL_TEXT)


class _Workbook:
    datemode = 0

    def __init__(self, rows):
        self._sheet = _Sheet(rows)
        self.released = False

    def sheet_names(self):
        return ["東京レポ・レート（一覧）"]

    def sheet_by_name(self, _name):
        return self._sheet

    def release_resources(self):
        self.released = True


def _rows(*, include_start: bool = True):
    rows = [
        ["東京レポ・レート（一覧）"],
        ["公表日", "翌日物（T+0）", "翌日物（T+1）"],
    ]
    if include_start:
        rows.append([datetime(2012, 10, 29), 0.101, 0.102])
    for year in range(2013, 2025):
        rows.append([datetime(year, 1, 4), 0.1 + year / 100000, 0.2])
    rows.append([datetime(2025, 4, 2), 0.301, 0.302])
    return rows


def _install_workbook(monkeypatch, *, include_start: bool = True):
    opened: list[bytes] = []

    def open_workbook(*, file_contents, on_demand):
        assert on_demand is True
        opened.append(file_contents)
        return _Workbook(_rows(include_start=include_start))

    monkeypatch.setattr(xlrd, "open_workbook", open_workbook)
    return opened


def _index_html() -> bytes:
    return (
        '<html><body><p>東京レポ・レート（2025.4.2)</p>'
        '<a href="files/trr.xls">東京レポ・レート（2025.4.2)</a>'
        '<a href="files/trrts.xls">東京レポ・レート（一覧）</a>'
        '</body></html>'
    ).encode("utf-8")


class _RepoArchiveClient:
    name = "local"
    timeseries_url = (
        "https://www.jsda.or.jp/shiryoshitsu/toukei/trr/files/trrts.xls"
    )
    workbook_bytes = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1stubbed-trrts"

    def __init__(self):
        self.calls: list[str] = []

    def get(self, url, *, headers=None, params=None, timeout=30.0):
        self.calls.append(url)
        if url == repo_index_url():
            return HttpResponse(200, {"content-type": "text/html"}, _index_html(), url)
        if url == self.timeseries_url:
            return HttpResponse(
                200, {"content-type": "application/vnd.ms-excel"},
                self.workbook_bytes, url,
            )
        return HttpResponse(404, {}, b"", url)


def test_tokyo_repo_contract_discovery_and_cli_are_governed_from_2012():
    contract = jsda_contract_for(TOKYO_REPO_DATASET)
    coverage = coverage_contract_for(TOKYO_REPO_DATASET)
    assert contract.history_target_start == "2012-10-29"
    assert contract.canonical_formats[0] == "xls"
    assert coverage.history_target_start == "2012-10-29"
    assert coverage.segment_granularity == "source_time_series_file"

    source = discover_repo_timeseries(_index_html().decode())
    assert source.source_url.endswith("trrts.xls")
    assert source.latest_publication_date == "2025-04-02"
    assert source.discovery_status == "DISCOVERED"

    args = _build_parser().parse_args([
        "--source", "jsda", "--jsda-dataset", "tokyo-repo", "--jsda-force"
    ])
    assert args.jsda_dataset == "tokyo-repo" and args.jsda_force


def test_parse_repo_xls_uses_xlrd_and_excel_serial_dates(monkeypatch):
    opened = _install_workbook(monkeypatch)
    records = parse_repo_xls(_RepoArchiveClient.workbook_bytes)
    assert opened == [_RepoArchiveClient.workbook_bytes]
    assert records[0] == {
        "as_of_date": "2012-10-29",
        "tenor": "翌日物（T+0）",
        "rate": 0.101,
    }
    assert records[-1]["as_of_date"] == "2025-04-02"


def test_tokyo_repo_runner_raw_receipt_coverage_and_resume(tmp_path, monkeypatch):
    _install_workbook(monkeypatch)
    client = _RepoArchiveClient()
    store = SqliteStore(tmp_path / "repo.sqlite")
    report = run_tokyo_repo_backfill(
        http=client,
        store=store,
        data_base=tmp_path,
        checked_at="2025-04-02T13:00:00+09:00",
    )
    assert (report.completed, report.resumed, report.deferred, report.failed) == (
        1, 0, 0, 0
    )
    assert report.raw_rows == report.structured_rows == 28
    assert store.count("jsda_repo_rates") == 28

    receipts = read_collection_receipts(store.path, dataset=TOKYO_REPO_DATASET)
    assert len(receipts) == 1
    receipt = receipts[0]
    evidence = json.loads(receipt["digests_json"])
    assert receipt["segment_start"] == "2012-10-29"
    assert receipt["segment_end"] == "2025-04-02"
    assert receipt["expected_items"] == receipt["observed_items"] == 1
    assert receipt["raw_row_count"] == receipt["structured_row_count"] == 28
    assert evidence["raw"].startswith("sha256:")
    assert evidence["source_url"].endswith("trrts.xls")
    assert evidence["fetched_at"] == "2025-04-02T13:00:00+09:00"
    assert Path(evidence["raw_path"]).read_bytes() == client.workbook_bytes
    coverage = read_dataset_coverage(store.path, dataset=TOKYO_REPO_DATASET)
    assert len(coverage) == 1 and coverage[0]["status"] == "COMPLETE"

    second = run_tokyo_repo_backfill(
        http=client,
        store=store,
        data_base=tmp_path,
        checked_at="2025-04-02T13:00:01+09:00",
    )
    assert (second.completed, second.resumed) == (0, 1)
    assert store.count("jsda_repo_rates") == 28
    assert client.calls.count(client.timeseries_url) == 1
    assert len(read_collection_receipts(
        store.path, dataset=TOKYO_REPO_DATASET
    )) == 1
    store.close()


def test_tokyo_repo_legacy_gap_is_explicit_deferred_partial(tmp_path, monkeypatch):
    _install_workbook(monkeypatch, include_start=False)
    client = _RepoArchiveClient()
    store = SqliteStore(tmp_path / "repo-gap.sqlite")
    report = run_tokyo_repo_backfill(
        http=client,
        store=store,
        data_base=tmp_path,
        checked_at="2025-04-02T13:00:00+09:00",
    )
    assert (report.completed, report.deferred, report.failed) == (0, 1, 0)
    assert store.count("jsda_repo_rates") == 0
    receipts = read_collection_receipts(store.path, dataset=TOKYO_REPO_DATASET)
    assert len(receipts) == 1 and receipts[0]["status"] == "FAILED"
    evidence = json.loads(receipts[0]["digests_json"])
    assert evidence["failure_kind"] == "DEFERRED_SOURCE_GAP"
    assert "first JSDA-era observation" in receipts[0]["error"]
    assert Path(evidence["raw_path"]).read_bytes() == client.workbook_bytes
    coverage = read_dataset_coverage(store.path, dataset=TOKYO_REPO_DATASET)
    assert len(coverage) == 1 and coverage[0]["status"] == "PARTIAL"
    store.close()
