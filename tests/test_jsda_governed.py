"""Governed JSDA OTC-reference discovery, parsing and PIT provenance."""

from __future__ import annotations

from io import BytesIO
import json
from pathlib import Path

import pytest

from data_contracts.jsda import all_jsda_contracts, jsda_contract_for
from data_contracts import coverage_contract_for
from ingestion.common.http import HttpResponse
from ingestion.jsda.archive import run_otc_reference_backfill
from ingestion.jsda.normalize import normalize_otc_reference_prices
from ingestion.jsda.parse import (
    parse_otc_reference_csv,
    parse_otc_reference_xlsx,
)
from ingestion.jsda.urls import (
    discover_otc_reference_segments,
    discover_otc_reference_year_indexes,
)
from storage.sqlite_store import SqliteStore
from storage import (
    evaluate_required_segments,
    read_collection_receipts,
    read_coverage_segments,
    read_dataset_coverage,
)
from scripts.run_ingestion_once import _build_parser

_FIXTURES = Path(__file__).parent / "fixtures"


def test_governed_contract_keeps_otc_reference_distinct_and_starts_2002():
    contracts = {contract.dataset_id: contract for contract in all_jsda_contracts()}
    assert set(contracts) == {
        "jsda_otc_bond_reference_prices",
        "jsda_tokyo_repo_rates",
        "jsda_corporate_bond_transactions",
    }
    otc = jsda_contract_for("jsda_otc_bond_reference_prices")
    assert otc.history_target_start == "2002-08-02"
    assert otc.available_at_policy == (
        "ingest_time_conservative_when_publication_timestamp_unknown"
    )
    assert otc.governance_tier == "governed"
    coverage = coverage_contract_for("jsda_otc_bond_reference_prices")
    assert coverage.history_target_start == "2002-08-02"
    assert coverage.segment_granularity == "official_archive_index_day"


def test_jsda_cli_keeps_legacy_default_and_supports_explicit_otc_range():
    parser = _build_parser()
    legacy = parser.parse_args(["--source", "jsda", "--jsda-only", "bond"])
    assert legacy.jsda_only == "bond"
    assert legacy.jsda_dataset is None

    otc = parser.parse_args([
        "--source", "jsda",
        "--jsda-dataset", "otc-reference",
        "--jsda-from-year", "2002",
        "--jsda-to-year", "2004",
        "--jsda-force",
    ])
    assert (otc.jsda_from_year, otc.jsda_to_year, otc.jsda_force) == (
        2002, 2004, True
    )


def test_official_archive_discovery_emits_stable_daily_segments_and_missing_link():
    root = (_FIXTURES / "jsda_otc_reference_root.html").read_text(encoding="utf-8")
    indexes = discover_otc_reference_year_indexes(root)
    assert [(item.year, item.url.rsplit("/", 1)[-1]) for item in indexes] == [
        (2002, "archive2002.html"),
        (2003, "archive2003.html"),
    ]

    archive = (_FIXTURES / "jsda_otc_reference_archive2002.html").read_text(
        encoding="utf-8"
    )
    segments = discover_otc_reference_segments(
        archive, year=2002, index_url=indexes[0].url
    )
    assert [item.segment_id for item in segments] == [
        "2002-08-02", "2002-08-05", "2002-08-06"
    ]
    # Discovery ids are official index publication days, not calendar weekends.
    assert "2002-08-03" not in [item.segment_id for item in segments]
    assert segments[0].period_id == "2002-08"
    assert segments[0].source_url.endswith("20020802_reference.csv")
    assert segments[0].source_format == "csv"
    assert segments[1].source_format == "csv"  # CSV canonical when XLSX also exists
    assert segments[2].source_url is None
    assert segments[2].discovery_status == "MISSING_SOURCE_LINK"


def test_otc_csv_parser_keeps_label_and_effective_dates_separate():
    raw = (_FIXTURES / "jsda_otc_reference_sample.csv").read_bytes()
    records = parse_otc_reference_csv(
        raw,
        publication_label_date="2002-08-02",
        quote_effective_date="2002-08-01",
    )
    assert len(records) == 2
    assert records[0]["publication_label_date"] == "2002-08-02"
    assert records[0]["quote_effective_date"] == "2002-08-01"
    assert records[0]["security_code"] == "JSDA0001"
    assert records[0]["average_price"] == 99.85
    assert records[0]["average_yield"] == 1.225
    assert records[1]["individual_investor_flag"] == "○"


def test_otc_csv_parser_supports_official_headerless_positional_layout():
    # JSDA publishes the item header as a separate workbook.  Archive CSVs are
    # positional and typically cp932, so exercise both properties here.
    raw = (
        _FIXTURES / "jsda_otc_reference_headerless.csv"
    ).read_text(encoding="utf-8").encode("cp932")
    records = parse_otc_reference_csv(
        raw,
        publication_label_date="2002-08-02",
        quote_effective_date="2002-08-01",
    )
    assert len(records) == 2
    assert records[0]["security_code"] == "123456789"
    assert records[0]["bond_name"] == "10年国債"
    assert records[0]["maturity_date"] == "2012-08-20"
    assert records[0]["average_yield"] == 1.225
    assert records[0]["average_price"] == 99.85
    assert records[0]["high_yield"] == 1.1
    assert records[0]["low_yield"] == 1.35
    assert records[0]["median_price"] == 99.84
    assert records[1]["individual_investor_flag"] == "1"
    assert records[0]["source_row_number"] == 1


def test_otc_xlsx_parser_uses_same_canonical_shape():
    from openpyxl import Workbook

    workbook = Workbook()
    sheet = workbook.active
    sheet.append(["公社債店頭売買参考統計値"])
    sheet.append([
        "銘柄コード", "銘柄名", "利率", "償還期日",
        "平均値（単価）", "平均値（複利）",
    ])
    sheet.append(["JSDA-X1", "XLSX債", 0.5, "2030/01/04", 100.1, 0.49])
    buffer = BytesIO()
    workbook.save(buffer)

    records = parse_otc_reference_xlsx(
        buffer.getvalue(),
        publication_label_date="2025-01-06",
        quote_effective_date="2025-01-04",
    )
    assert records == [{
        "publication_label_date": "2025-01-06",
        "quote_effective_date": "2025-01-04",
        "security_code": "JSDA-X1",
        "bond_name": "XLSX債",
        "coupon_rate": 0.5,
        "maturity_date": "2030-01-04",
        "average_price": 100.1,
        "average_yield": 0.49,
        "median_price": None,
        "median_yield": None,
        "high_price": None,
        "high_yield": None,
        "low_price": None,
        "low_yield": None,
        "individual_investor_flag": None,
        "source_row_number": 3,
    }]


def test_otc_normalize_and_revision_never_backdate_unknown_publication(tmp_path):
    raw = (_FIXTURES / "jsda_otc_reference_sample.csv").read_bytes()
    records = parse_otc_reference_csv(
        raw,
        publication_label_date="2002-08-02",
        quote_effective_date="2002-08-01",
    )[:1]
    original = normalize_otc_reference_prices(
        records,
        ingested_at="2025-04-02T10:00:00+09:00",
        source_url="https://market.jsda.or.jp/archive/20020802.csv",
        raw_digest="sha256:original",
        segment_id="2002-08-02",
    )
    row = original[0]
    assert row["event_time"] == "2002-08-01T15:00:00+09:00"
    assert row["quote_effective_time"] == "2002-08-01T15:00:00+09:00"
    assert row["publication_label_date"] == "2002-08-02"
    assert row["available_at"] == row["ingested_at"]
    assert row["source_url"].startswith("https://market.jsda.or.jp/")
    assert row["raw_digest"] == "sha256:original"

    store = SqliteStore(tmp_path / "jsda.sqlite")
    store.upsert("jsda_otc_bond_reference_prices", original)
    corrected_records = [{**records[0], "average_price": 98.75}]
    correction = normalize_otc_reference_prices(
        corrected_records,
        ingested_at="2025-05-01T12:00:00+09:00",
        source_url="https://market.jsda.or.jp/corrections/20020802.xlsx",
        raw_digest="sha256:correction",
        segment_id="correction-2025-05-01-2002-08-02",
        correction_published_at="2025-05-01",
    )
    store.upsert("jsda_otc_bond_reference_prices", correction)

    current = store.fetch_all("jsda_otc_bond_reference_prices")
    revisions = store.fetch_all("jsda_otc_bond_reference_prices_revisions")
    assert len(current) == len(revisions) == 1
    assert current[0]["average_price"] == 98.75
    assert current[0]["available_at"] == "2025-05-01T12:00:00+09:00"
    assert revisions[0]["average_price"] == 99.85
    assert revisions[0]["available_at"] == "2025-04-02T10:00:00+09:00"
    store.close()


class _ArchiveClient:
    name = "local"

    def __init__(self):
        self.calls: list[str] = []
        self.root = (
            _FIXTURES / "jsda_otc_reference_root.html"
        ).read_bytes()
        self.archive = (
            _FIXTURES / "jsda_otc_reference_archive2002.html"
        ).read_bytes()
        self.csv = (
            _FIXTURES / "jsda_otc_reference_sample.csv"
        ).read_bytes()

    def get(self, url, *, headers=None, params=None, timeout=30.0):
        self.calls.append(url)
        if url.endswith("/baisanchi/index.html"):
            return HttpResponse(200, {"content-type": "text/html"}, self.root, url)
        if url.endswith("/baisanchi/archive2002.html"):
            return HttpResponse(200, {"content-type": "text/html"}, self.archive, url)
        if url.endswith("20020802_reference.csv") or url.endswith(
            "20020805_reference.csv"
        ):
            return HttpResponse(200, {"content-type": "text/csv"}, self.csv, url)
        return HttpResponse(404, {}, b"", url)


def _inject_tmp_receipt_authority(monkeypatch, receipt_ed25519_keys):
    """Bind governed writes to the tmp Ed25519 fixture; never production keys."""
    monkeypatch.setattr(
        "ingestion.runtime_authority.load_signing_key",
        lambda **kwargs: receipt_ed25519_keys.signing_key,
    )
    from ingestion.runtime_authority import _open_governed_receipt_service

    return _open_governed_receipt_service()


def test_otc_archive_backfill_receipts_raw_resume_and_missing_partial(
    tmp_path, monkeypatch, receipt_ed25519_keys
):
    receipt_service = _inject_tmp_receipt_authority(
        monkeypatch, receipt_ed25519_keys
    )
    store = SqliteStore(tmp_path / "structured.sqlite")
    client = _ArchiveClient()
    report = run_otc_reference_backfill(
        http=client,
        store=store,
        data_base=tmp_path,
        from_year=2002,
        to_year=2002,
        checked_at="2025-04-02T10:00:00+09:00",
        receipt_service=receipt_service,
    )
    assert (report.discovered, report.completed, report.resumed, report.failed) == (
        3, 0, 0, 3
    )
    assert store.count("jsda_otc_bond_reference_prices") == 0

    receipts = read_collection_receipts(
        store.path, dataset="jsda_otc_bond_reference_prices"
    )
    assert len(receipts) == 3
    assert all(row["status"] == "FAILED" for row in receipts)
    acquired = [
        row for row in receipts
        if json.loads(row["digests_json"]).get("raw_path")
    ]
    missing = [
        row for row in receipts
        if json.loads(row["digests_json"]).get("failure_kind")
        == "MISSING_EXPECTED_SEGMENT"
    ]
    assert len(acquired) == 2 and len(missing) == 1
    for row in acquired:
        digests = __import__("json").loads(row["digests_json"])
        assert digests["source_url"].startswith("https://market.jsda.or.jp/")
        assert digests["fetched_at"] == "2025-04-02T10:00:00+09:00"
        assert digests["raw"].startswith("sha256:")
        raw_path = Path(digests["raw_path"])
        assert raw_path.read_bytes() == client.csv
        assert row["observed_items"] == row["expected_items"] == 1
        assert row["structured_row_count"] == 2
        assert digests.get("eligibility") == "RECOVERED_RAW_ONLY"
        assert not str(digests.get("signature") or "").startswith("ed25519:")
    missing_digests = __import__("json").loads(missing[0]["digests_json"])
    assert missing_digests["failure_kind"] == "MISSING_EXPECTED_SEGMENT"

    policy = coverage_contract_for("jsda_otc_bond_reference_prices")
    receipt_objects = []
    from ingestion.jsda.archive import _receipt_objects

    receipt_objects = _receipt_objects(receipts)
    status, evaluated = evaluate_required_segments(
        policy, report.required_segments, receipt_objects
    )
    assert status == "PARTIAL"
    assert [item[2] for item in evaluated] == ["PARTIAL", "PARTIAL", "PARTIAL"]
    coverage = read_dataset_coverage(
        store.path, dataset="jsda_otc_bond_reference_prices"
    )
    assert len(coverage) == 1 and coverage[0]["status"] == "PARTIAL"

    # Recovery-only evidence never becomes a COMPLETE resume checkpoint.
    second = run_otc_reference_backfill(
        http=client,
        store=store,
        data_base=tmp_path,
        from_year=2002,
        to_year=2002,
        checked_at="2025-04-02T10:00:01+09:00",
        receipt_service=receipt_service,
    )
    assert (second.completed, second.resumed, second.failed) == (0, 0, 3)
    assert store.count("jsda_otc_bond_reference_prices") == 0
    assert sum(url.endswith("20020802_reference.csv") for url in client.calls) == 2
    assert sum(url.endswith("20020805_reference.csv") for url in client.calls) == 2
    second_receipts = read_collection_receipts(
        store.path, dataset="jsda_otc_bond_reference_prices"
    )
    assert len(second_receipts) == 6
    store.close()


def test_otc_archive_refresh_reuses_fetched_index_html_not_weekends(
    tmp_path, monkeypatch, receipt_ed25519_keys
):
    """Year-index HTML already fetched is passed as index_text; weekends stay out."""
    from ingestion.jsda import archive as archive_mod
    from ingestion.jsda.official_index import parse_official_index_publication_days

    receipt_service = _inject_tmp_receipt_authority(
        monkeypatch, receipt_ed25519_keys
    )
    captured: dict[str, object] = {}
    real_refresh = archive_mod.refresh_coverage_ledger

    def _capture_refresh(*args, **kwargs):
        captured["index_text"] = kwargs.get("index_text")
        return real_refresh(*args, **kwargs)

    monkeypatch.setattr(archive_mod, "refresh_coverage_ledger", _capture_refresh)
    store = SqliteStore(tmp_path / "index-text.sqlite")
    client = _ArchiveClient()
    report = run_otc_reference_backfill(
        http=client,
        store=store,
        data_base=tmp_path,
        from_year=2002,
        to_year=2002,
        checked_at="2025-04-02T10:00:00+09:00",
        receipt_service=receipt_service,
    )
    listed = ["2002-08-02", "2002-08-05", "2002-08-06"]
    weekend = "2002-08-03"
    assert [seg.segment_id for seg in report.required_segments] == listed
    assert weekend not in {seg.segment_id for seg in report.required_segments}
    html = captured.get("index_text")
    assert isinstance(html, str) and html.strip()
    assert parse_official_index_publication_days(html) == tuple(listed)
    assert weekend not in parse_official_index_publication_days(html)
    after = read_coverage_segments(
        store.path, dataset="jsda_otc_bond_reference_prices"
    )
    ids = [row["segment_id"] for row in after]
    assert ids == listed
    assert weekend not in ids
    missing = next(row for row in after if row["segment_id"] == "2002-08-06")
    assert missing["status"] != "COMPLETE"
    coverage = read_dataset_coverage(
        store.path, dataset="jsda_otc_bond_reference_prices"
    )
    assert coverage and coverage[0]["status"] != "COMPLETE"
    store.close()


def test_otc_archive_without_authority_does_not_write_structured(tmp_path, monkeypatch):
    """Governed fact upsert is forbidden until SignedReceiptAuthority is verified."""
    monkeypatch.setattr(
        "ingestion.runtime_authority.load_signing_key",
        lambda **kwargs: None,
    )
    store = SqliteStore(tmp_path / "unsigned.sqlite")
    client = _ArchiveClient()
    report = run_otc_reference_backfill(
        http=client,
        store=store,
        data_base=tmp_path,
        from_year=2002,
        to_year=2002,
        checked_at="2025-04-02T10:00:00+09:00",
    )
    assert report.completed == 0
    assert report.failed == 3
    assert store.count("jsda_otc_bond_reference_prices") == 0
    receipts = read_collection_receipts(
        store.path, dataset="jsda_otc_bond_reference_prices"
    )
    assert receipts and all(row["status"] == "FAILED" for row in receipts)
    assert all(row["structured_row_count"] == 0 for row in receipts)
    for row in receipts:
        digests = __import__("json").loads(row["digests_json"])
        assert digests.get("eligibility") != "TRUSTED_COLLECTION"
        assert not str(digests.get("signature") or "").startswith("ed25519:")
    coverage = read_dataset_coverage(
        store.path, dataset="jsda_otc_bond_reference_prices"
    )
    assert coverage and coverage[0]["status"] != "COMPLETE"
    store.close()


def test_otc_archive_unsigned_stays_partial_without_complete_resume(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(
        "ingestion.runtime_authority.load_signing_key",
        lambda **kwargs: None,
    )
    store = SqliteStore(tmp_path / "unsigned-resume.sqlite")
    client = _ArchiveClient()
    report = run_otc_reference_backfill(
        http=client,
        store=store,
        data_base=tmp_path,
        from_year=2002,
        to_year=2002,
        checked_at="2025-04-02T10:00:00+09:00",
    )
    assert (report.completed, report.resumed, report.failed) == (0, 0, 3)
    assert store.count("jsda_otc_bond_reference_prices") == 0
    receipts = read_collection_receipts(
        store.path, dataset="jsda_otc_bond_reference_prices"
    )
    from ingestion.jsda.archive import _receipt_objects

    policy = coverage_contract_for("jsda_otc_bond_reference_prices")
    status, evaluated = evaluate_required_segments(
        policy, report.required_segments, _receipt_objects(receipts)
    )
    assert status == "PARTIAL"
    assert [item[2] for item in evaluated] == ["PARTIAL", "PARTIAL", "PARTIAL"]
    coverage = read_dataset_coverage(
        store.path, dataset="jsda_otc_bond_reference_prices"
    )
    assert coverage and coverage[0]["status"] == "PARTIAL"

    second = run_otc_reference_backfill(
        http=client,
        store=store,
        data_base=tmp_path,
        from_year=2002,
        to_year=2002,
        checked_at="2025-04-02T10:00:01+09:00",
    )
    assert (second.completed, second.resumed, second.failed) == (0, 0, 3)
    assert store.count("jsda_otc_bond_reference_prices") == 0
    assert sum(url.endswith("20020802_reference.csv") for url in client.calls) == 2
    assert sum(url.endswith("20020805_reference.csv") for url in client.calls) == 2
    store.close()


def test_governed_jsda_receipt_rejects_fake_local_raw_success(
    tmp_path, receipt_ed25519_keys
):
    from ingestion.jsda.receipts import record_governed_receipt
    from ingestion.runtime_authority import _open_governed_receipt_service
    from storage.coverage_ledger import RequiredCoverageSegment

    receipt_service = _open_governed_receipt_service(
        pem=receipt_ed25519_keys.private_pem
    )
    store = SqliteStore(tmp_path / "empty-raw.sqlite")
    required = RequiredCoverageSegment(
        source="jsda",
        dataset="jsda_otc_bond_reference_prices",
        segment_id="2002-08-02",
        segment_start="2002-08-02",
        segment_end="2002-08-02",
        expected_scope={"coverage_mode": "official_archive_index_reconciled"},
        expected_items=1,
    )
    raw_path = tmp_path / "caller-forged.csv"
    raw_path.write_bytes(b"security_code,price\nFAKE,100\n")
    raw_path.chmod(0o444)
    with pytest.raises(RuntimeError, match="JSDA SUCCESS is disabled"):
        record_governed_receipt(
            store,
            required=required,
            run_id=1,
            checked_at="2025-04-02T10:00:00+09:00",
            status="SUCCESS",
            error=None,
            pagination_exhausted=True,
            digests={"origin": "test"},
            receipt_service=receipt_service,
            raw_artifact_paths=(raw_path,),
        )
    n = store._conn.execute("select count(*) from collection_receipts").fetchone()[0]
    assert n == 0
    store.close()
