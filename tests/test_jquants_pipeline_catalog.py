"""Pipeline: catalog-driven J-Quants run + proxy-aware key skip.

Offline — a recording HTTP double stands in for the client transport, and an
in-memory store (``:memory:`` SQLite) proves rows land in ``jquants_records``.
"""

from __future__ import annotations

import json
from datetime import datetime

from ingestion.common.http import HttpResponse
from ingestion.pipeline import run_jquants
from storage import read_collection_receipts
from storage.receipt_crypto import (
    PRODUCTION_RECEIPT_AUTHORITY_INSTANCE_DIGEST,
    PRODUCTION_RECEIPT_ENVIRONMENT,
    verify_receipt_signature,
)
from storage.sqlite_store import SqliteStore


def _inject_tmp_receipt_authority(
    monkeypatch, receipt_ed25519_keys, http_factory
):
    """Bind governed writes to the tmp Ed25519 fixture; never production keys."""
    import ingestion.runtime_authority as runtime
    from tests.receipt_test_support import open_test_receipt_service

    monkeypatch.setattr(runtime, "_direct_jquants_http", http_factory)
    monkeypatch.setattr(
        runtime,
        "_open_governed_receipt_service",
        lambda **_kwargs: open_test_receipt_service(
            signing_key=receipt_ed25519_keys.signing_key
        ),
    )


def _assert_verified_success_receipts(store, *, dataset: str | None = None) -> None:
    receipts = read_collection_receipts(store.path, dataset=dataset)
    success = [row for row in receipts if row["status"] == "SUCCESS"]
    assert success, "governed persist SUCCESS requires a signed collection receipt"
    for row in success:
        digests = json.loads(row["digests_json"])
        assert digests.get("eligibility") == "TRUSTED_COLLECTION"
        assert str(digests.get("signature") or "").startswith("ed25519:")
        assert verify_receipt_signature(
            digests,
            expected_environment=PRODUCTION_RECEIPT_ENVIRONMENT,
            expected_authority_instance_digest=(
                PRODUCTION_RECEIPT_AUTHORITY_INSTANCE_DIGEST
            ),
        )


class _CatalogHttp:
    """Returns canned ``data`` for any path; records calls."""

    name = "local"

    def __init__(self, rows):
        self._rows = rows
        self.calls: list[str] = []

    def get(self, url, *, headers=None, params=None, timeout=30.0):
        self.calls.append(url)
        return HttpResponse(
            200,
            {"content-type": "application/json"},
            json.dumps({"data": self._rows}).encode("utf-8"),
            url,
        )


def _proxy_http():
    """An http double whose ``name`` marks it as the CF proxy client."""
    h = _CatalogHttp([{"Code": "8697", "Date": "2025-04-01", "Close": 100}])
    h.name = "cf-jquants-proxy"
    return h


def _store(tmp_path):
    return SqliteStore(tmp_path / "t.sqlite")


def test_run_jquants_catalog_writes_to_generic_table(
    tmp_path, monkeypatch, receipt_ed25519_keys
):
    http = _CatalogHttp([{"Code": "8697", "Date": "2025-04-01", "Close": 100}])
    _inject_tmp_receipt_authority(monkeypatch, receipt_ed25519_keys, lambda: http)
    store = _store(tmp_path)
    today = datetime(2025, 4, 2, 9, 0, 0)
    reports = run_jquants(
        http=http, store=store, api_key="k", data_base=tmp_path, today=today,
        datasets=["equities_bars_daily"], mode="incremental",
    )
    # bars expand to one job per day over the default incremental window
    assert len(reports) >= 1
    assert all(r.kind == "equities_bars_daily" for r in reports)
    assert all(r.registered == 0 for r in reports)
    assert all(r.error for r in reports)
    # The legacy local daily path has neither a verified live collection nor
    # an authority-owned v2 transaction, so it cannot authorize COMPLETE. Raw
    # acquisition remains available for a future governed batch closure.
    assert store.fetch_all("jquants_records") == []
    assert read_collection_receipts(
        store.path, dataset="equities_bars_daily"
    ) == []
    store.close()


def test_run_jquants_catalog_skips_unknown_dataset(tmp_path):
    http = _CatalogHttp([])
    store = _store(tmp_path)
    today = datetime(2025, 4, 2, 9, 0, 0)
    reports = run_jquants(
        http=http, store=store, api_key="k", data_base=tmp_path, today=today,
        datasets=["not_a_real_dataset"], mode="incremental",
    )
    assert reports[0].skipped  # clean skip, not an error
    store.close()


def test_run_jquants_proxy_client_runs_without_api_key(
    tmp_path, monkeypatch, receipt_ed25519_keys
):
    # cf-jquants-proxy http + empty api_key must NOT be skipped.
    http = _proxy_http()
    _inject_tmp_receipt_authority(monkeypatch, receipt_ed25519_keys, lambda: http)
    store = _store(tmp_path)
    today = datetime(2025, 4, 2, 9, 0, 0)
    reports = run_jquants(
        http=http, store=store, api_key="", data_base=tmp_path, today=today,
        datasets=["markets_calendar"], mode="incremental",
    )
    assert len(reports) == 1
    assert not reports[0].skipped
    assert http.calls  # empty API key did not skip acquisition
    assert reports[0].registered == 0
    assert reports[0].error
    store.close()


def test_run_jquants_direct_without_key_is_skipped(tmp_path):
    http = _CatalogHttp([{"Code": "1"}])
    store = _store(tmp_path)
    today = datetime(2025, 4, 2, 9, 0, 0)
    reports = run_jquants(
        http=http, store=store, api_key="", data_base=tmp_path, today=today,
        datasets=["markets_calendar"], mode="incremental",
    )
    assert len(reports) == 1
    assert reports[0].skipped and "JQUANTS_API_KEY" in reports[0].skipped
    store.close()


def test_run_jquants_catalog_incremental_default_window(
    tmp_path, monkeypatch, receipt_ed25519_keys
):
    # incremental + no explicit dates -> a recent from window is applied.
    seen_params: list[dict] = []

    class _P:
        name = "local"

        def get(self, url, *, headers=None, params=None, timeout=30.0):
            seen_params.append(dict(params or {}))
            return HttpResponse(
                200, {"content-type": "application/json"},
                json.dumps({"data": []}).encode("utf-8"), url,
            )

    http = _P()
    _inject_tmp_receipt_authority(monkeypatch, receipt_ed25519_keys, lambda: http)
    store = _store(tmp_path)
    today = datetime(2025, 4, 10, 9, 0, 0)
    run_jquants(
        http=http, store=store, api_key="k", data_base=tmp_path, today=today,
        datasets=["equities_bars_daily"], mode="incremental",
    )
    # bars prefer date= (API needs date or code); window still starts today-5d
    dates = sorted({p.get("date") for p in seen_params if p.get("date")})
    assert "2025-04-05" in dates
    assert "2025-04-10" in dates
    receipts = read_collection_receipts(store.path, dataset="equities_bars_daily")
    for row in receipts:
        if row["status"] != "SUCCESS":
            continue
        digests = json.loads(row["digests_json"])
        # A valid signature preserves provenance, but an empty upstream
        # envelope is deliberately ineligible for Coverage COMPLETE.
        assert digests.get("eligibility") == "RECOVERED_RAW_ONLY"
        assert str(digests.get("signature") or "").startswith("ed25519:")
        assert verify_receipt_signature(
            digests,
            expected_environment=PRODUCTION_RECEIPT_ENVIRONMENT,
            expected_authority_instance_digest=(
                PRODUCTION_RECEIPT_AUTHORITY_INSTANCE_DIGEST
            ),
        )
    store.close()


def test_run_jquants_without_authority_does_not_write_structured(tmp_path):
    """Governed fact upsert is forbidden until SignedReceiptAuthority is verified."""
    http = _CatalogHttp([{"Code": "8697", "Date": "2025-04-01", "Close": 100}])
    store = _store(tmp_path)
    today = datetime(2025, 4, 2, 9, 0, 0)
    reports = run_jquants(
        http=http, store=store, api_key="k", data_base=tmp_path, today=today,
        datasets=["equities_bars_daily"], mode="backfill",
    )
    assert reports
    assert all(r.registered == 0 for r in reports)
    assert all("receipt emit failed (governed)" in r.error for r in reports)
    assert store.fetch_all("jquants_records") == []
    receipts = read_collection_receipts(store.path, dataset="equities_bars_daily")
    assert all(row["status"] != "SUCCESS" for row in receipts)
    store.close()
