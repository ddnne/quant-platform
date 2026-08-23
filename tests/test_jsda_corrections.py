"""Official JSDA corrections become later, revision-safe PIT versions."""

from __future__ import annotations

from pathlib import Path

from ingestion.common.http import HttpResponse
from ingestion.jsda.corrections import _available_at, run_otc_reference_corrections
from ingestion.jsda.normalize import (
    normalize_otc_reference_prices,
    normalize_repo_rates,
)
from ingestion.jsda.parse import parse_otc_reference_csv
from ingestion.jsda.urls import (
    discover_otc_reference_corrections,
    otc_reference_corrections_index_url,
    otc_reference_index_url,
)
from pit.api import get_jsda_repo_rates
from pit.query import run_query
from storage import read_collection_receipts
from storage.sqlite_store import SqliteStore

_FIXTURES = Path(__file__).parent / "fixtures"


def _fixture(name: str) -> bytes:
    return (_FIXTURES / name).read_bytes()


def test_correction_discovery_excludes_comparison_only_and_keeps_exact_time():
    items = discover_otc_reference_corrections(
        _fixture("jsda_otc_corrections_index.html").decode("utf-8")
    )
    assert len(items) == 2
    assert all("comparison_only" not in item.source_url for item in items)
    first = next(item for item in items if item.affected_start == "2022-06-15")
    assert first.correction_publication_label == "2022-08-29"
    assert first.correction_published_at is None
    exact = next(item for item in items if item.affected_start == "2026-07-15")
    assert exact.correction_published_at == "2026-07-14T18:30:00+09:00"


def test_correction_availability_never_precedes_known_official_publication():
    assert _available_at(
        "2026-07-14T18:00:00+09:00",
        "2026-07-14T18:30:00+09:00",
    ) == "2026-07-14T18:30:00+09:00"
    assert _available_at(
        "2026-07-14T19:00:00+09:00",
        "2026-07-14T18:30:00+09:00",
    ) == "2026-07-14T19:00:00+09:00"


class _CorrectionClient:
    name = "local"
    artifact_url = (
        "https://market.jsda.or.jp/shijyo/saiken/baibai/"
        "baisanchi/reki/files/dif20220615.xls"
    )
    annual_url = (
        "https://market.jsda.or.jp/shijyo/saiken/baibai/"
        "baisanchi/archive2022.html"
    )
    corrected_url = (
        "https://market.jsda.or.jp/shijyo/saiken/baibai/"
        "baisanchi/files/2022/20220615_reference.csv"
    )
    artifact = b"\xd0\xcf\x11\xe0official-correction-comparison"

    def __init__(self):
        self.calls: list[str] = []

    def get(self, url, *, headers=None, params=None, timeout=30.0):
        self.calls.append(url)
        if url == otc_reference_corrections_index_url():
            return HttpResponse(
                200, {"content-type": "text/html"},
                _fixture("jsda_otc_corrections_index.html"), url,
            )
        if url == otc_reference_index_url():
            return HttpResponse(
                200, {"content-type": "text/html"},
                _fixture("jsda_otc_correction_root.html"), url,
            )
        if url == self.annual_url:
            return HttpResponse(
                200, {"content-type": "text/html"},
                _fixture("jsda_otc_correction_archive2022.html"), url,
            )
        if url == self.artifact_url:
            return HttpResponse(
                200, {"content-type": "application/vnd.ms-excel"},
                self.artifact, url,
            )
        if url == self.corrected_url:
            return HttpResponse(
                200, {"content-type": "text/csv"},
                _fixture("jsda_otc_correction_corrected.csv"), url,
            )
        return HttpResponse(404, {}, b"", url)


def _seed_original(store):
    parsed = parse_otc_reference_csv(
        _fixture("jsda_otc_correction_original.csv"),
        publication_label_date="2022-06-15",
        quote_effective_date="2022-06-14",
    )
    rows = normalize_otc_reference_prices(
        parsed,
        ingested_at="2022-06-15T18:00:00+09:00",
        source_url=_CorrectionClient.corrected_url,
        raw_digest="sha256:original",
        segment_id="2022-06-15",
    )
    store.upsert("jsda_otc_bond_reference_prices", rows)


def test_otc_correction_revision_no_lookahead_provenance_and_idempotency(
    tmp_path,
):
    store = SqliteStore(tmp_path / "corrections.sqlite")
    _seed_original(store)
    client = _CorrectionClient()
    correction_id = "2022-08-29:dif20220615.xls"
    report = run_otc_reference_corrections(
        http=client,
        store=store,
        data_base=tmp_path,
        checked_at="2022-08-30T10:00:00+09:00",
        correction_ids=[correction_id],
    )
    assert (
        report.discovered, report.applied, report.resumed,
        report.deferred, report.failed, report.changed_rows, report.revision_rows,
    ) == (1, 1, 0, 0, 0, 1, 1)

    current = store.fetch_all("jsda_otc_bond_reference_prices")
    revisions = store.fetch_all("jsda_otc_bond_reference_prices_revisions")
    assert len(current) == len(revisions) == 1
    assert current[0]["average_price"] == 98.75
    assert current[0]["publication_label_date"] == "2022-06-15"
    assert current[0]["quote_effective_date"] == "2022-06-14"
    assert current[0]["available_at"] == "2022-08-30T10:00:00+09:00"
    assert current[0]["ingested_at"] == "2022-08-30T10:00:00+09:00"
    assert current[0]["correction_publication_label"] == "2022-08-29"
    assert current[0]["correction_published_at"] is None
    assert current[0]["correction_source_url"] == client.artifact_url
    assert current[0]["correction_raw_digest"].startswith("sha256:")
    assert revisions[0]["average_price"] == 99.8
    assert revisions[0]["available_at"] == "2022-06-15T18:00:00+09:00"
    assert revisions[0]["correction_publication_label"] is None
    assert revisions[0]["correction_published_at"] is None

    before = run_query(
        store.path,
        as_of="2022-08-30T09:59:59+09:00",
        table="jsda_otc_bond_reference_prices",
        order_by="security_code",
    )
    after = run_query(
        store.path,
        as_of="2022-08-30T10:00:00+09:00",
        table="jsda_otc_bond_reference_prices",
        order_by="security_code",
    )
    assert before[0]["average_price"] == 99.8
    assert before[0]["correction_published_at"] is None
    assert after[0]["average_price"] == 98.75
    assert after[0]["correction_publication_label"] == "2022-08-29"
    assert after[0]["correction_published_at"] is None

    receipts = read_collection_receipts(
        store.path, dataset="jsda_otc_bond_reference_prices",
        segment_id=f"correction:{correction_id}",
    )
    assert len(receipts) == 1 and receipts[0]["status"] == "SUCCESS"
    assert receipts[0]["raw_row_count"] == receipts[0]["structured_row_count"] == 1

    rerun = run_otc_reference_corrections(
        http=client,
        store=store,
        data_base=tmp_path,
        checked_at="2022-08-30T10:01:00+09:00",
        correction_ids=[correction_id],
    )
    assert (rerun.applied, rerun.resumed, rerun.revision_rows) == (0, 1, 0)
    assert store.count("jsda_otc_bond_reference_prices_revisions") == 1
    assert client.calls.count(client.artifact_url) == 1
    store.close()


def test_otc_correction_without_authority_does_not_apply(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "storage.trusted_receipt.load_signing_key",
        lambda **kwargs: None,
    )
    store = SqliteStore(tmp_path / "corrections-unsigned.sqlite")
    _seed_original(store)
    client = _CorrectionClient()
    correction_id = "2022-08-29:dif20220615.xls"
    report = run_otc_reference_corrections(
        http=client,
        store=store,
        data_base=tmp_path,
        checked_at="2022-08-30T10:00:00+09:00",
        correction_ids=[correction_id],
    )
    assert report.applied == 0
    assert report.failed == 1
    current = store.fetch_all("jsda_otc_bond_reference_prices")
    assert len(current) == 1
    assert current[0]["average_price"] == 99.8
    assert store.count("jsda_otc_bond_reference_prices_revisions") == 0
    receipts = read_collection_receipts(
        store.path, dataset="jsda_otc_bond_reference_prices",
        segment_id=f"correction:{correction_id}",
    )
    assert receipts and receipts[0]["status"] == "FAILED"
    store.close()


def test_otc_correction_rerun_does_not_double_apply_when_not_complete(
    tmp_path, monkeypatch,
):
    store = SqliteStore(tmp_path / "corrections-resume.sqlite")
    _seed_original(store)
    client = _CorrectionClient()
    correction_id = "2022-08-29:dif20220615.xls"
    report = run_otc_reference_corrections(
        http=client,
        store=store,
        data_base=tmp_path,
        checked_at="2022-08-30T10:00:00+09:00",
        correction_ids=[correction_id],
    )
    assert (report.applied, report.revision_rows) == (1, 1)
    monkeypatch.setattr(
        "ingestion.jsda.corrections.evaluate_segment",
        lambda *args, **kwargs: ("PARTIAL", {"reason": "forced"}),
    )
    rerun = run_otc_reference_corrections(
        http=client,
        store=store,
        data_base=tmp_path,
        checked_at="2022-08-30T10:01:00+09:00",
        correction_ids=[correction_id],
    )
    assert (rerun.applied, rerun.resumed, rerun.revision_rows) == (0, 1, 0)
    assert store.count("jsda_otc_bond_reference_prices_revisions") == 1
    assert client.calls.count(client.artifact_url) == 1
    store.close()


def test_tokyo_repo_reingest_is_revision_safe_without_official_correction_time(
    tmp_path,
):
    store = SqliteStore(tmp_path / "repo-correction.sqlite")
    original = normalize_repo_rates(
        [{"as_of_date": "2025-04-01", "tenor": "1ヶ月物", "rate": 0.01}],
        ingested_at="2025-04-01T12:30:00+09:00",
    )
    corrected = normalize_repo_rates(
        [{"as_of_date": "2025-04-01", "tenor": "1ヶ月物", "rate": 0.02}],
        ingested_at="2025-04-02T09:00:00+09:00",
    )
    store.upsert("jsda_repo_rates", original)
    store.upsert("jsda_repo_rates", corrected)

    before = get_jsda_repo_rates(
        as_of="2025-04-02T08:59:59+09:00", db_path=store.path
    )
    after = get_jsda_repo_rates(
        as_of="2025-04-02T09:00:00+09:00", db_path=store.path
    )
    assert before.rows[0]["rate"] == 0.01
    assert after.rows[0]["rate"] == 0.02
    assert store.count("jsda_repo_rates_revisions") == 1

    # Same corrected payload is an idempotent observation, not a third version.
    again = normalize_repo_rates(
        [{"as_of_date": "2025-04-01", "tenor": "1ヶ月物", "rate": 0.02}],
        ingested_at="2025-04-03T09:00:00+09:00",
    )
    store.upsert("jsda_repo_rates", again)
    assert store.count("jsda_repo_rates_revisions") == 1
    still_visible = get_jsda_repo_rates(
        as_of="2025-04-02T09:00:00+09:00", db_path=store.path
    )
    assert still_visible.rows[0]["rate"] == 0.02
    store.close()
