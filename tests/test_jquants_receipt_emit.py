"""Lane H: J-Quants collection receipt helpers are honest and wireable."""
from __future__ import annotations

import json
import hashlib
import sqlite3
from pathlib import Path
from unittest.mock import patch

import pytest

from data_contracts import coverage_contract_for
from storage.coverage_ledger import (
    SYNTHETIC_RECEIPT_MARKER,
    build_collection_receipt,
    build_synthetic_complete_receipt,
    compute_raw_digest,
    is_synthetic_receipt,
    plan_required_segments,
    record_collection_receipt,
    record_required_segments,
    refresh_coverage_ledger,
)
from storage.sqlite_store import SqliteStore


def test_compute_raw_digest_is_sha256():
    raw = b'{"data":[1]}'
    d = compute_raw_digest(raw)
    assert d.startswith("sha256:")
    assert len(d) == len("sha256:") + 64


def test_build_collection_receipt_real_digest(tmp_path: Path):
    policy = coverage_contract_for("markets_calendar")
    segs = list(plan_required_segments(policy, "2026-08-11", source="jquants"))
    assert segs
    req = segs[0]
    raw = b'{"data":[{"Date":"2026-08-11"}]}'
    r = build_collection_receipt(
        required=req,
        run_id=1,
        raw=raw,
        observed_items=1,
        structured_row_count=1,
    )
    assert r.digests["raw"] == compute_raw_digest(raw)
    assert not is_synthetic_receipt(r)


def test_synthetic_receipt_marked(tmp_path: Path):
    policy = coverage_contract_for("markets_calendar")
    segs = list(plan_required_segments(policy, "2026-08-11", source="jquants"))
    req = segs[0]
    r = build_synthetic_complete_receipt(required=req, run_id=1)
    assert is_synthetic_receipt(r)
    assert r.digests.get("origin") == SYNTHETIC_RECEIPT_MARKER["origin"]


def test_record_receipt_into_db(tmp_path: Path):
    db = tmp_path / "t.sqlite"
    store = SqliteStore(db)
    policy = coverage_contract_for("markets_calendar")
    segs = list(plan_required_segments(policy, "2026-08-11", source="jquants"))
    req = segs[0]
    record_required_segments(store._conn, [req])
    raw = b'{"data":[]}'
    r = build_collection_receipt(
        required=req,
        run_id=1,
        raw=raw,
        observed_items=0,
        structured_row_count=0,
    )
    record_collection_receipt(store._conn, r)
    store._conn.commit()
    n = store._conn.execute("select count(*) from collection_receipts").fetchone()[0]
    assert n == 1
    store.close()


class _RawHttp:
    name = "test"

    def __init__(self, raw: bytes, response_url: str) -> None:
        self.raw = raw
        self.response_url = response_url

    def get(self, url, **_kwargs):
        from ingestion.common.http import HttpResponse

        return HttpResponse(200, {}, self.raw, self.response_url)


def _tmp_service(
    receipt_ed25519_keys,
    *,
    raw: bytes | None = None,
    response_url: str = "https://api.jquants.com/v2/markets/calendar",
    clock=None,
):
    """Governed service bound to an ephemeral key; never production keys."""
    from tests.receipt_test_support import open_test_receipt_service

    del raw, response_url
    test_clock = clock or (lambda: "2026-08-11T09:00:00+09:00")
    return open_test_receipt_service(
        signing_key=receipt_ed25519_keys.signing_key,
        clock=test_clock,
    )


def _persisted_market_calendar_row(
    store: SqliteStore, *, event_date: str = "2026-07-31"
) -> dict:
    from ingestion.jquants.normalize import normalize_generic

    row = normalize_generic(
        [{"Date": event_date}],
        dataset="markets_calendar",
        ingested_at="2026-08-11T09:00:00+09:00",
    )[0]
    store.upsert("jquants_records", [row], commit=False)
    return row


def _verified_collection(
    tmp_path: Path,
    raw: bytes,
    *,
    service,
    required,
):
    from tests.jquants_acquisition_test_support import (
        build_live_acquisition,
        verify_live_acquisition,
    )

    fixture = build_live_acquisition(
        tmp_path=tmp_path,
        service=service,
        required=required,
        raw_pages=(raw,),
    )
    return verify_live_acquisition(
        fixture,
        service=service,
        required=required,
    )


def _bound_context(store: SqliteStore, service, required):
    return service.begin_collection(store=store, required=required)


def _assert_no_trusted_effects(store: SqliteStore, service) -> None:
    assert store._conn.execute(
        "SELECT COUNT(*) FROM jquants_records"
    ).fetchone()[0] == 0
    assert store._conn.execute(
        "SELECT COUNT(*) FROM collection_receipts"
    ).fetchone()[0] == 0
    assert store._conn.execute(
        "SELECT COUNT(*) FROM ingestion_run_log"
    ).fetchone()[0] == 0
    assert service._issued_evidence == []


def _persisted_collection(
    tmp_path: Path,
    raw: bytes,
    *,
    service,
    params: dict | None = None,
    response_url: str = "https://api.jquants.com/v2/markets/calendar",
):
    tmp_path.mkdir(parents=True, exist_ok=True)

    request_params = params or {"from": "2026-08-01", "to": "2026-08-11"}
    import ingestion.runtime_authority as runtime

    with patch.object(
        runtime,
        "_direct_jquants_http",
        return_value=_RawHttp(raw, response_url),
    ):
        result = service.open_jquants_client(
            api_key="test", via_cf_proxy=False
        ).fetch_dataset_evidenced("markets_calendar", **request_params)
    raw_path = tmp_path / "market-calendar.json"
    raw_path.write_bytes(result.pages[0].response_body)
    raw_path.chmod(0o444)
    path = tmp_path / "pagination-manifest.json"
    path.write_text(json.dumps({
        "schema_version": "jquants-pagination-evidence/v1",
        "source": "jquants",
        "dataset": "markets_calendar",
        "base_params": request_params,
        "pages": [{
            "index": 0,
            "raw_path": str(raw_path.resolve()),
            "body_digest": "sha256:" + hashlib.sha256(raw).hexdigest(),
            "request_path": result.pages[0].request_path,
            "request_params": request_params,
            "response_url": response_url,
            "response_status": 200,
            "pagination_in": None,
            "pagination_out": None,
        }],
    }, sort_keys=True), encoding="utf-8")
    path.chmod(0o444)
    return service.persist_jquants_collection(
        fetch_result=result,
        raw_paths=(raw_path,),
        manifest_path=path,
    )


def test_emit_segment_receipt_requires_authority(tmp_path: Path):
    from ingestion.jquants.receipts import emit_segment_receipt

    store = SqliteStore(tmp_path / "t.sqlite")
    policy = coverage_contract_for("markets_calendar")
    req = list(plan_required_segments(policy, "2026-07-31", source="jquants"))[-1]
    _persisted_market_calendar_row(store)
    with pytest.raises(TypeError, match="GovernedReceiptService is required"):
        emit_segment_receipt(
            store,
            required=req,
            run_id=1,
            persisted_collection=None,
            collection_context=None,  # type: ignore[arg-type]
            service=None,  # type: ignore[arg-type]
        )
    store.close()


def test_require_governed_receipt_service_fails_closed_without_key(monkeypatch):
    from ingestion.jquants.receipts import require_governed_receipt_service

    with pytest.raises(TypeError, match="implicit issue is removed"):
        require_governed_receipt_service()


def test_persisted_evidence_rejects_bytes_not_minted_by_fetch(
    tmp_path: Path, receipt_ed25519_keys
):
    raw = b'{"data":[{"Date":"2026-07-31"}]}'
    service = _tmp_service(receipt_ed25519_keys, raw=raw)
    import ingestion.runtime_authority as runtime

    with patch.object(
        runtime,
        "_direct_jquants_http",
        return_value=_RawHttp(
            raw, "https://api.jquants.com/v2/markets/calendar"
        ),
    ):
        result = service.open_jquants_client(
            api_key="test", via_cf_proxy=False
        ).fetch_dataset_evidenced("markets_calendar")
    raw_path = tmp_path / "tampered.json"
    raw_path.write_bytes(b"")
    raw_path.chmod(0o444)
    manifest = tmp_path / "manifest.json"
    manifest.write_text("{}", encoding="utf-8")
    manifest.chmod(0o444)
    with pytest.raises(ValueError, match="differs from fetched response"):
        service.persist_jquants_collection(
            fetch_result=result,
            raw_paths=(raw_path,),
            manifest_path=manifest,
        )


def test_public_client_with_fake_http_cannot_mint_trusted_fetch(
    tmp_path: Path, receipt_ed25519_keys,
) -> None:
    """A plausible URL/client name is not network provenance."""
    from ingestion.common.rate_limit import RateLimiter
    from ingestion.jquants.client import JQuantsClient

    raw = b'{"data":[{"Date":"2026-08-11"}]}'
    response_url = "https://api.jquants.com/v2/markets/calendar"
    public_result = JQuantsClient(
        _RawHttp(raw, response_url),
        api_key="fake",
        rate_limiter=RateLimiter(0.0),
    ).fetch_dataset_evidenced(
        "markets_calendar", from_date="2026-08-01", to_date="2026-08-11"
    )
    raw_path = tmp_path / "fake-page.json"
    raw_path.write_bytes(raw)
    raw_path.chmod(0o444)
    manifest = tmp_path / "fake-manifest.json"
    manifest.write_text("{}", encoding="utf-8")
    manifest.chmod(0o444)
    service = _tmp_service(receipt_ed25519_keys)

    with pytest.raises(TypeError, match="governed runtime transport"):
        service.persist_jquants_collection(
            fetch_result=public_result,
            raw_paths=(raw_path,),
            manifest_path=manifest,
        )


def test_emit_segment_receipt_records_verified_signature(
    tmp_path: Path, receipt_ed25519_keys
):
    from ingestion.jquants.receipts import emit_segment_receipt
    from storage.coverage_ledger import is_complete_eligible_receipt
    from storage.receipt_crypto import verify_receipt_signature

    store = SqliteStore(tmp_path / "t.sqlite")
    policy = coverage_contract_for("markets_calendar")
    req = list(plan_required_segments(policy, "2026-07-31", source="jquants"))[-1]
    record_required_segments(store._conn, [req])
    raw = b'{"data":[{"Date":"2026-07-31"}]}'
    service = _tmp_service(receipt_ed25519_keys, raw=raw)
    persisted = _verified_collection(
        tmp_path, raw, service=service, required=req
    )
    _persisted_market_calendar_row(store)
    receipt = emit_segment_receipt(
        store,
        required=req,
        run_id=1,
        persisted_collection=persisted,
        collection_context=_bound_context(store, service, req),
        service=service,
    )
    assert receipt.status == "SUCCESS"
    assert receipt.digests.get("eligibility") == "TRUSTED_COLLECTION"
    assert str(receipt.digests.get("signature") or "").startswith("ed25519:")
    assert verify_receipt_signature(receipt.digests)
    assert is_complete_eligible_receipt(receipt)
    n = store._conn.execute("select count(*) from collection_receipts").fetchone()[0]
    assert n == 1
    store.close()


def test_emit_segment_receipt_rejects_genuine_raw_with_unrelated_structured_row(
    tmp_path: Path, receipt_ed25519_keys
):
    """Genuine raw plus an unrelated same-count DB row cannot be signed."""
    from ingestion.jquants.receipts import emit_segment_receipt
    from ingestion.jquants.normalize import normalize_generic

    store = SqliteStore(tmp_path / "t.sqlite")
    policy = coverage_contract_for("markets_calendar")
    req = list(plan_required_segments(policy, "2026-07-31", source="jquants"))[-1]
    raw = b'{"data":[{"Date":"2026-07-31"}]}'
    service = _tmp_service(receipt_ed25519_keys, raw=raw)
    persisted = _verified_collection(
        tmp_path, raw, service=service, required=req
    )
    forged = normalize_generic(
        [{"Date": "2099-01-01"}],
        dataset="markets_calendar",
        ingested_at="2026-08-11T09:00:00+09:00",
    )[0]
    store.upsert("jquants_records", [forged], commit=False)

    with pytest.raises(ValueError, match="canonical normalization"):
        emit_segment_receipt(
            store,
            required=req,
            run_id=1,
            persisted_collection=persisted,
            collection_context=_bound_context(store, service, req),
            service=service,
        )

    assert store._conn.execute(
        "SELECT COUNT(*) FROM collection_receipts"
    ).fetchone()[0] == 0
    store.close()


def test_persisted_evidence_rejects_redirect_to_untrusted_https_host(
    tmp_path: Path, receipt_ed25519_keys,
) -> None:
    raw = b'{"data":[{"Date":"2026-08-11"}]}'
    service = _tmp_service(
        receipt_ed25519_keys,
        raw=raw,
        response_url="https://attacker.example/v2/markets/calendar",
    )
    with pytest.raises(ValueError, match="direct response URL"):
        _persisted_collection(
            tmp_path,
            raw,
            service=service,
            response_url="https://attacker.example/v2/markets/calendar",
        )


def test_raw_paths_and_caller_manifest_cannot_bypass_opaque_handle(
    tmp_path: Path, receipt_ed25519_keys,
) -> None:
    from ingestion.runtime_authority import _open_governed_receipt_service

    store = SqliteStore(tmp_path / "bypass.sqlite")
    policy = coverage_contract_for("markets_calendar")
    req = list(plan_required_segments(policy, "2026-08-11", source="jquants"))[-1]
    raw_path = tmp_path / "forged.json"
    raw_path.write_bytes(b'{"data":[{"Date":"2026-08-11"}]}')
    raw_path.chmod(0o444)
    service = _tmp_service(receipt_ed25519_keys)
    with pytest.raises(TypeError, match="verified live acquisition collection"):
        service.record_persisted_success(
            store,
            required=req,
            run_id=1,
            collection_context=_bound_context(store, service, req),
            raw_artifact_paths=(raw_path,),
        )
    assert service._issued_evidence == []
    store.close()


@pytest.mark.parametrize(
    "params",
    [
        {"from": "2026-08-01", "to": "2026-08-10"},
        {
            "from": "2026-08-01",
            "to": "2026-08-11",
            "holidaydivision": "1",
        },
    ],
)
def test_v1_query_evidence_is_recovery_only_for_new_complete(
    tmp_path: Path, receipt_ed25519_keys, params: dict,
) -> None:
    from ingestion.jquants.receipts import emit_segment_receipt

    store = SqliteStore(tmp_path / "scope.sqlite")
    req = list(
        plan_required_segments(
            coverage_contract_for("markets_calendar"),
            "2026-07-31",
            source="jquants",
        )
    )[-1]
    raw = b'{"data":[{"Date":"2026-08-11"}]}'
    service = _tmp_service(receipt_ed25519_keys, raw=raw)
    persisted = _persisted_collection(
        tmp_path / "raw",
        raw,
        service=service,
        params=params,
    )
    _persisted_market_calendar_row(store)
    with pytest.raises(TypeError, match="audit/recovery-only"):
        emit_segment_receipt(
            store,
            required=req,
            run_id=1,
            persisted_collection=persisted,
            collection_context=_bound_context(store, service, req),
            service=service,
        )
    assert store._conn.execute(
        "SELECT COUNT(*) FROM collection_receipts"
    ).fetchone()[0] == 0
    assert service._issued_evidence == []
    assert store._conn.execute(
        "SELECT COUNT(*) FROM jquants_records"
    ).fetchone()[0] == 0
    assert store._conn.execute(
        "SELECT COUNT(*) FROM ingestion_run_log"
    ).fetchone()[0] == 0
    store.close()


@pytest.mark.parametrize(
    "invalid_page",
    (
        b'{"data":[\xff]}',
        b'{"data":',
        b'{"data":[],"data":[]}',
        b'{"data":[NaN]}',
        b'{"rows":[]}',
    ),
)
def test_one_malformed_live_page_rolls_back_the_entire_transaction(
    tmp_path: Path, receipt_ed25519_keys, invalid_page: bytes
) -> None:
    from tests.jquants_acquisition_test_support import (
        build_live_acquisition,
        verify_live_acquisition,
    )

    service = _tmp_service(receipt_ed25519_keys)
    store = SqliteStore(tmp_path / "malformed.sqlite")
    req = list(
        plan_required_segments(
            coverage_contract_for("indices_bars_daily_topix"),
            "2026-07-31",
            source="jquants",
        )
    )[-1]
    fixture = build_live_acquisition(
        tmp_path=tmp_path / "capture",
        service=service,
        required=req,
        raw_pages=(
            b'{"data":[{"Date":"2026-07-01"}],"pagination_key":"next"}',
            invalid_page,
        ),
    )
    with pytest.raises(ValueError):
        verify_live_acquisition(
            fixture,
            service=service,
            required=req,
        )
    _assert_no_trusted_effects(store, service)
    store.close()


def test_raw_only_live_capture_rolls_back_before_issuer(
    tmp_path: Path, receipt_ed25519_keys
) -> None:
    from tests.jquants_acquisition_test_support import (
        _metadata_headers,
        build_live_acquisition,
        verify_live_acquisition,
    )

    service = _tmp_service(receipt_ed25519_keys)
    store = SqliteStore(tmp_path / "raw-only.sqlite")
    req = list(
        plan_required_segments(
            coverage_contract_for("markets_calendar"),
            "2026-07-31",
            source="jquants",
        )
    )[-1]
    def mark_raw_only(document):
        metadata = document["pages"][0]["metadata"]
        metadata.update(evidence_state="RAW_ONLY", pagination_state="UNKNOWN")
        document["pages"][0]["headers"] = _metadata_headers(metadata)

    fixture = build_live_acquisition(
        tmp_path=tmp_path / "capture",
        service=service,
        required=req,
        raw_pages=(b'{"data":[{"Date":"2026-07-31"}]}',),
        mutate_document=mark_raw_only,
    )
    with pytest.raises(ValueError, match="only RAW_PAGE"):
        verify_live_acquisition(
            fixture,
            service=service,
            required=req,
        )
    _assert_no_trusted_effects(store, service)
    store.close()


def test_record_rejects_unverified_live_capture_shortcut(
    tmp_path: Path, receipt_ed25519_keys
) -> None:
    from tests.jquants_acquisition_test_support import build_live_acquisition

    service = _tmp_service(receipt_ed25519_keys)
    store = SqliteStore(tmp_path / "unverified-shortcut.sqlite")
    req = list(
        plan_required_segments(
            coverage_contract_for("markets_calendar"),
            "2026-07-31",
            source="jquants",
        )
    )[-1]
    fixture = build_live_acquisition(
        tmp_path=tmp_path / "capture",
        service=service,
        required=req,
        raw_pages=(b'{"data":[{"Date":"2026-07-31"}]}',),
    )
    context = _bound_context(store, service, req)
    _persisted_market_calendar_row(store)
    with pytest.raises(TypeError, match="fully verified before beginning"):
        service.record_persisted_success(
            store,
            required=req,
            run_id=context.run_id,
            collection_context=context,
            jquants_capture=fixture.capture,
        )
    _assert_no_trusted_effects(store, service)
    store.close()


@pytest.mark.parametrize("forgery", ["scope", "items"])
def test_caller_cannot_substitute_canonical_required_claims(
    tmp_path: Path, receipt_ed25519_keys, forgery: str
) -> None:
    from dataclasses import replace

    service = _tmp_service(receipt_ed25519_keys)
    store = SqliteStore(tmp_path / f"required-{forgery}.sqlite")
    req = list(
        plan_required_segments(
            coverage_contract_for("markets_calendar"),
            "2026-07-31",
            source="jquants",
        )
    )[-1]
    handle = _verified_collection(
        tmp_path / "capture",
        b'{"data":[{"Date":"2026-07-31"}]}',
        service=service,
        required=req,
    )
    context = _bound_context(store, service, req)
    _persisted_market_calendar_row(store)
    forged = (
        replace(req, expected_scope={**req.expected_scope, "universe_rule": "forged"})
        if forgery == "scope"
        else replace(req, expected_items=999)
    )
    with pytest.raises(ValueError, match="canonical Coverage planning"):
        service.record_persisted_success(
            store,
            required=forged,
            run_id=context.run_id,
            collection_context=context,
            jquants_collection=handle,
        )
    _assert_no_trusted_effects(store, service)
    store.close()


def test_verified_month_cannot_be_substituted_at_record_time(
    tmp_path: Path, receipt_ed25519_keys
) -> None:
    from ingestion.jquants.normalize import normalize_generic

    service = _tmp_service(receipt_ed25519_keys)
    store = SqliteStore(tmp_path / "cross-month.sqlite")
    july = list(
        plan_required_segments(
            coverage_contract_for("markets_calendar"),
            "2026-07-31",
            source="jquants",
        )
    )[-1]
    june = list(
        plan_required_segments(
            coverage_contract_for("markets_calendar"),
            "2026-06-30",
            source="jquants",
        )
    )[-1]
    # The downstream transaction is itself valid for June.  Only the opaque
    # acquisition handle is from July, so this reaches the frozen-capability
    # identity check rather than merely failing the context digest check.
    handle = _verified_collection(
        tmp_path / "capture",
        b'{"data":[{"Date":"2026-07-31"}]}',
        service=service,
        required=july,
    )
    context = _bound_context(store, service, june)
    store.upsert(
        "jquants_records",
        normalize_generic(
            [{"Date": "2026-06-30"}],
            dataset=june.dataset,
            ingested_at=context.checked_at,
        ),
        commit=False,
    )
    with pytest.raises(ValueError, match="segment differs from canonical"):
        service.record_persisted_success(
            store,
            required=june,
            run_id=context.run_id,
            collection_context=context,
            jquants_collection=handle,
        )
    _assert_no_trusted_effects(store, service)
    store.close()


def test_post_verify_required_scope_mutation_is_rejected(
    tmp_path: Path, receipt_ed25519_keys
) -> None:
    service = _tmp_service(receipt_ed25519_keys)
    store = SqliteStore(tmp_path / "mutated-required.sqlite")
    req = list(
        plan_required_segments(
            coverage_contract_for("markets_calendar"),
            "2026-07-31",
            source="jquants",
        )
    )[-1]
    handle = _verified_collection(
        tmp_path / "capture",
        b'{"data":[{"Date":"2026-07-31"}]}',
        service=service,
        required=req,
    )
    context = _bound_context(store, service, req)
    _persisted_market_calendar_row(store)
    assert isinstance(req.expected_scope, dict)
    req.expected_scope["universe_rule"] = "caller-mutated-after-verification"
    with pytest.raises(ValueError, match="canonical Coverage planning"):
        service.record_persisted_success(
            store,
            required=req,
            run_id=context.run_id,
            collection_context=context,
            jquants_collection=handle,
        )
    _assert_no_trusted_effects(store, service)
    store.close()


def test_verified_live_handle_expires_before_fresh_record_context(
    tmp_path: Path, receipt_ed25519_keys
) -> None:
    now = {"value": "2026-08-11T05:59:00+00:00"}
    service = _tmp_service(receipt_ed25519_keys, clock=lambda: now["value"])
    store = SqliteStore(tmp_path / "expired-handle.sqlite")
    req = list(
        plan_required_segments(
            coverage_contract_for("markets_calendar"),
            "2026-07-31",
            source="jquants",
        )
    )[-1]
    handle = _verified_collection(
        tmp_path / "capture",
        b'{"data":[{"Date":"2026-07-31"}]}',
        service=service,
        required=req,
    )
    now["value"] = "2026-08-11T06:00:01+00:00"
    context = _bound_context(store, service, req)
    _persisted_market_calendar_row(store)
    with pytest.raises(ValueError, match="session has expired"):
        service.record_persisted_success(
            store,
            required=req,
            run_id=context.run_id,
            collection_context=context,
            jquants_collection=handle,
        )
    _assert_no_trusted_effects(store, service)
    store.close()


def test_context_before_capture_verification_cannot_backdate_pit(
    tmp_path: Path, receipt_ed25519_keys
) -> None:
    now = {"value": "2026-08-11T00:00:00+00:00"}
    service = _tmp_service(receipt_ed25519_keys, clock=lambda: now["value"])
    store = SqliteStore(tmp_path / "pit-backdate.sqlite")
    req = list(
        plan_required_segments(
            coverage_contract_for("markets_calendar"),
            "2026-07-31",
            source="jquants",
        )
    )[-1]
    context = _bound_context(store, service, req)
    _persisted_market_calendar_row(store)
    now["value"] = "2026-08-11T00:14:00+00:00"
    handle = _verified_collection(
        tmp_path / "capture",
        b'{"data":[{"Date":"2026-07-31"}]}',
        service=service,
        required=req,
    )
    with pytest.raises(ValueError, match="predates live acquisition verification"):
        service.record_persisted_success(
            store,
            required=req,
            run_id=context.run_id,
            collection_context=context,
            jquants_collection=handle,
        )
    _assert_no_trusted_effects(store, service)
    store.close()


def test_equal_clock_tick_still_rejects_context_created_before_verification(
    tmp_path: Path, receipt_ed25519_keys
) -> None:
    service = _tmp_service(receipt_ed25519_keys)
    store = SqliteStore(tmp_path / "equal-tick-order.sqlite")
    req = list(
        plan_required_segments(
            coverage_contract_for("markets_calendar"),
            "2026-07-31",
            source="jquants",
        )
    )[-1]
    context = _bound_context(store, service, req)
    _persisted_market_calendar_row(store)
    handle = _verified_collection(
        tmp_path / "capture",
        b'{"data":[{"Date":"2026-07-31"}]}',
        service=service,
        required=req,
    )
    with pytest.raises(ValueError, match="predates live acquisition verification"):
        service.record_persisted_success(
            store,
            required=req,
            run_id=context.run_id,
            collection_context=context,
            jquants_collection=handle,
        )
    _assert_no_trusted_effects(store, service)
    store.close()


def test_capture_completion_clock_becomes_pit_available_at(
    tmp_path: Path, receipt_ed25519_keys
) -> None:
    from ingestion.jquants.normalize import normalize_generic

    calls = {"count": 0}

    def verification_clock() -> str:
        calls["count"] += 1
        if calls["count"] == 1:
            return "2026-08-11T09:00:00+09:00"
        return "2026-08-11T09:14:00+09:00"

    service = _tmp_service(receipt_ed25519_keys, clock=verification_clock)
    store = SqliteStore(tmp_path / "capture-completion-pit.sqlite")
    req = list(
        plan_required_segments(
            coverage_contract_for("markets_calendar"),
            "2026-07-31",
            source="jquants",
        )
    )[-1]
    handle = _verified_collection(
        tmp_path / "capture",
        b'{"data":[{"Date":"2026-07-31"}]}',
        service=service,
        required=req,
    )
    context = _bound_context(store, service, req)
    assert context.checked_at == "2026-08-11T09:14:00+09:00"
    store.upsert(
        "jquants_records",
        normalize_generic(
            [{"Date": "2026-07-31"}],
            dataset=req.dataset,
            ingested_at=context.checked_at,
        ),
        commit=False,
    )
    receipt = service.record_persisted_success(
        store,
        required=req,
        run_id=context.run_id,
        collection_context=context,
        jquants_collection=handle,
    )
    assert receipt.checked_at == context.checked_at
    stored = store._conn.execute(
        "SELECT available_at FROM jquants_records WHERE dataset=?",
        (req.dataset,),
    ).fetchone()
    assert stored is not None and stored["available_at"] == context.checked_at
    store.close()


def test_substituted_run_id_rolls_back_before_collection_or_issuer(
    tmp_path: Path, receipt_ed25519_keys
) -> None:
    service = _tmp_service(receipt_ed25519_keys)
    store = SqliteStore(tmp_path / "run-substitution.sqlite")
    req = list(
        plan_required_segments(
            coverage_contract_for("markets_calendar"),
            "2026-07-31",
            source="jquants",
        )
    )[-1]
    handle = _verified_collection(
        tmp_path / "capture",
        b'{"data":[{"Date":"2026-07-31"}]}',
        service=service,
        required=req,
    )
    context = _bound_context(store, service, req)
    _persisted_market_calendar_row(store)
    assert context.run_id is not None
    with pytest.raises(ValueError, match="caller run_id differs"):
        service.record_persisted_success(
            store,
            required=req,
            run_id=context.run_id + 1,
            collection_context=context,
            jquants_collection=handle,
        )
    _assert_no_trusted_effects(store, service)
    store.close()


def test_in_place_context_timestamp_mutation_cannot_change_signed_claims(
    tmp_path: Path, receipt_ed25519_keys
) -> None:
    service = _tmp_service(receipt_ed25519_keys)
    store = SqliteStore(tmp_path / "context-time-substitution.sqlite")
    req = list(
        plan_required_segments(
            coverage_contract_for("markets_calendar"),
            "2026-07-31",
            source="jquants",
        )
    )[-1]
    handle = _verified_collection(
        tmp_path / "capture",
        b'{"data":[{"Date":"2026-07-31"}]}',
        service=service,
        required=req,
    )
    context = _bound_context(store, service, req)
    _persisted_market_calendar_row(store)
    object.__setattr__(context, "checked_at", "2026-08-11T08:00:00+09:00")
    with pytest.raises(ValueError, match="timestamp was mutated"):
        service.record_persisted_success(
            store,
            required=req,
            run_id=context.run_id,
            collection_context=context,
            jquants_collection=handle,
        )
    _assert_no_trusted_effects(store, service)
    store.close()


def test_post_verify_raw_mutation_rolls_back_staged_facts(
    tmp_path: Path, receipt_ed25519_keys
) -> None:
    service = _tmp_service(receipt_ed25519_keys)
    store = SqliteStore(tmp_path / "mutated-raw.sqlite")
    req = list(
        plan_required_segments(
            coverage_contract_for("markets_calendar"),
            "2026-07-31",
            source="jquants",
        )
    )[-1]
    from tests.jquants_acquisition_test_support import build_live_acquisition

    fixture = build_live_acquisition(
        tmp_path=tmp_path / "capture",
        service=service,
        required=req,
        raw_pages=(b'{"data":[{"Date":"2026-07-31"}]}',),
    )
    handle = service.verify_live_jquants_collection(
        capture=fixture.capture, required=req
    )
    context = _bound_context(store, service, req)
    _persisted_market_calendar_row(store)
    raw_path = fixture.raw_paths[0]
    raw_path.chmod(0o644)
    raw_path.write_bytes(b'{"data":[{"Date":"2099-01-01"}]}')
    raw_path.chmod(0o444)
    with pytest.raises(ValueError, match="changed after verification"):
        service.record_persisted_success(
            store,
            required=req,
            run_id=context.run_id,
            collection_context=context,
            jquants_collection=handle,
        )
    _assert_no_trusted_effects(store, service)
    store.close()


def test_context_is_bound_to_the_exact_store_connection(
    tmp_path: Path, receipt_ed25519_keys
) -> None:
    service = _tmp_service(receipt_ed25519_keys)
    original = SqliteStore(tmp_path / "original.sqlite")
    other = SqliteStore(tmp_path / "other.sqlite")
    req = list(
        plan_required_segments(
            coverage_contract_for("markets_calendar"),
            "2026-07-31",
            source="jquants",
        )
    )[-1]
    handle = _verified_collection(
        tmp_path / "capture",
        b'{"data":[{"Date":"2026-07-31"}]}',
        service=service,
        required=req,
    )
    context = _bound_context(original, service, req)
    _persisted_market_calendar_row(other)
    with pytest.raises(TypeError, match="another store"):
        service.record_persisted_success(
            other,
            required=req,
            run_id=context.run_id,
            collection_context=context,
            jquants_collection=handle,
        )
    _assert_no_trusted_effects(other, service)
    assert original._conn.execute(
        "SELECT COUNT(*) FROM ingestion_run_log"
    ).fetchone()[0] == 0
    original.close()
    other.close()


def test_begin_collection_cannot_self_assert_raw_stored(
    tmp_path: Path, receipt_ed25519_keys
) -> None:
    service = _tmp_service(receipt_ed25519_keys)
    store = SqliteStore(tmp_path / "acquired-only.sqlite")
    req = list(
        plan_required_segments(
            coverage_contract_for("markets_calendar"),
            "2026-07-31",
            source="jquants",
        )
    )[-1]
    context = _bound_context(store, service, req)
    store._conn.commit()
    row = store._conn.execute(
        "SELECT status FROM ingestion_run_log WHERE id=?", (context.run_id,)
    ).fetchone()
    assert row is not None and row["status"] == "ACQUIRED"
    assert store._conn.execute(
        "SELECT COUNT(*) FROM collection_receipts"
    ).fetchone()[0] == 0
    store.close()


def test_autocommit_is_rejected_before_authority_run_creation(
    tmp_path: Path, receipt_ed25519_keys
) -> None:
    service = _tmp_service(receipt_ed25519_keys)
    store = SqliteStore(tmp_path / "autocommit-before-begin.sqlite")
    req = list(
        plan_required_segments(
            coverage_contract_for("markets_calendar"),
            "2026-07-31",
            source="jquants",
        )
    )[-1]
    store._conn.isolation_level = None
    with pytest.raises(TypeError, match="rejects SQLite autocommit"):
        service.begin_collection(store=store, required=req)
    assert store._conn.execute(
        "SELECT COUNT(*) FROM ingestion_run_log"
    ).fetchone()[0] == 0
    assert service._issued_evidence == []
    store.close()


def test_caller_enabling_autocommit_after_begin_cannot_reach_issuer(
    tmp_path: Path, receipt_ed25519_keys
) -> None:
    service = _tmp_service(receipt_ed25519_keys)
    store = SqliteStore(tmp_path / "autocommit-after-begin.sqlite")
    req = list(
        plan_required_segments(
            coverage_contract_for("markets_calendar"),
            "2026-07-31",
            source="jquants",
        )
    )[-1]
    handle = _verified_collection(
        tmp_path / "capture",
        b'{"data":[{"Date":"2026-07-31"}]}',
        service=service,
        required=req,
    )
    context = _bound_context(store, service, req)
    _persisted_market_calendar_row(store)
    # sqlite3 commits the caller-owned transaction when autocommit is enabled.
    # The authority cannot undo that caller action, but it must not sign it.
    store._conn.isolation_level = None
    with pytest.raises(TypeError, match="explicit SQLite transaction"):
        service.record_persisted_success(
            store,
            required=req,
            run_id=context.run_id,
            collection_context=context,
            jquants_collection=handle,
        )
    assert store._conn.execute(
        "SELECT COUNT(*) FROM collection_receipts"
    ).fetchone()[0] == 0
    assert store._conn.execute(
        "SELECT status FROM ingestion_run_log WHERE id=?", (context.run_id,)
    ).fetchone()["status"] == "ACQUIRED"
    assert service._issued_evidence == []
    store.close()


def test_structured_commit_is_visible_before_issuer_invocation(
    tmp_path: Path, receipt_ed25519_keys
) -> None:
    service = _tmp_service(receipt_ed25519_keys)
    store = SqliteStore(tmp_path / "commit-before-issuer.sqlite")
    req = list(
        plan_required_segments(
            coverage_contract_for("markets_calendar"),
            "2026-07-31",
            source="jquants",
        )
    )[-1]
    handle = _verified_collection(
        tmp_path / "capture",
        b'{"data":[{"Date":"2026-07-31"}]}',
        service=service,
        required=req,
    )
    context = _bound_context(store, service, req)
    _persisted_market_calendar_row(store)
    service_type = type(service)
    original = service_type._issue_reconciled_evidence
    observed: list[str] = []

    def assert_committed(bound_service, evidence):
        observer = sqlite3.connect(str(store.path))
        try:
            assert observer.execute(
                "SELECT COUNT(*) FROM jquants_records"
            ).fetchone()[0] == 1
            status = observer.execute(
                "SELECT status FROM ingestion_run_log WHERE id=?", (context.run_id,)
            ).fetchone()[0]
            assert status == "STRUCTURED_COMMITTED"
        finally:
            observer.close()
        observed.append("committed")
        return original(bound_service, evidence)

    with patch.object(
        service_type, "_issue_reconciled_evidence", new=assert_committed
    ):
        receipt = service.record_persisted_success(
            store,
            required=req,
            run_id=context.run_id,
            collection_context=context,
            jquants_collection=handle,
        )
    assert observed == ["committed"]
    assert receipt.status == "SUCCESS"
    store.close()


def test_post_commit_row_substitution_is_caught_before_issuer(
    tmp_path: Path, receipt_ed25519_keys
) -> None:
    import ingestion.runtime_authority as runtime

    service = _tmp_service(receipt_ed25519_keys)
    store = SqliteStore(tmp_path / "post-commit-substitution.sqlite")
    req = list(
        plan_required_segments(
            coverage_contract_for("markets_calendar"),
            "2026-07-31",
            source="jquants",
        )
    )[-1]
    handle = _verified_collection(
        tmp_path / "capture",
        b'{"data":[{"Date":"2026-07-31"}]}',
        service=service,
        required=req,
    )
    context = _bound_context(store, service, req)
    _persisted_market_calendar_row(store)
    original = runtime._begin_receipt_verification_transaction

    def substitute_then_begin(target_store):
        attacker = sqlite3.connect(str(target_store.path))
        try:
            attacker.execute(
                "DELETE FROM jquants_records WHERE dataset=?", (req.dataset,)
            )
            attacker.commit()
        finally:
            attacker.close()
        original(target_store)

    with patch.object(
        runtime,
        "_begin_receipt_verification_transaction",
        side_effect=substitute_then_begin,
    ):
        with pytest.raises(ValueError, match="natural keys differ"):
            service.record_persisted_success(
                store,
                required=req,
                run_id=context.run_id,
                collection_context=context,
                jquants_collection=handle,
            )
    assert service._issued_evidence == []
    assert store._conn.execute(
        "SELECT COUNT(*) FROM collection_receipts"
    ).fetchone()[0] == 0
    assert store._conn.execute(
        "SELECT status FROM ingestion_run_log WHERE id=?", (context.run_id,)
    ).fetchone()["status"] == "STRUCTURED_COMMITTED"
    store.close()


def test_acquisition_expiry_crossed_after_commit_stops_before_issuer(
    tmp_path: Path, receipt_ed25519_keys
) -> None:
    import ingestion.runtime_authority as runtime
    from ingestion.jquants.normalize import normalize_generic
    from tests.jquants_acquisition_test_support import build_live_acquisition

    now = {"value": "2026-08-11T14:59:59+09:00"}
    service = _tmp_service(receipt_ed25519_keys, clock=lambda: now["value"])
    store = SqliteStore(tmp_path / "expiry-after-commit.sqlite")
    req = list(
        plan_required_segments(
            coverage_contract_for("markets_calendar"),
            "2026-07-31",
            source="jquants",
        )
    )[-1]
    fixture = build_live_acquisition(
        tmp_path=tmp_path / "capture",
        service=service,
        required=req,
        raw_pages=(b'{"data":[{"Date":"2026-07-31"}]}',),
        expires_at="2026-08-11T06:00:00.000Z",
    )
    handle = service.verify_live_jquants_collection(
        capture=fixture.capture, required=req
    )
    context = _bound_context(store, service, req)
    store.upsert(
        "jquants_records",
        normalize_generic(
            [{"Date": "2026-07-31"}],
            dataset=req.dataset,
            ingested_at=context.checked_at,
        ),
        commit=False,
    )
    original = runtime._begin_receipt_verification_transaction

    def advance_past_expiry(target_store):
        now["value"] = "2026-08-11T15:00:01+09:00"
        original(target_store)

    with patch.object(
        runtime,
        "_begin_receipt_verification_transaction",
        side_effect=advance_past_expiry,
    ):
        with pytest.raises(ValueError, match="session has expired"):
            service.record_persisted_success(
                store,
                required=req,
                run_id=context.run_id,
                collection_context=context,
                jquants_collection=handle,
            )
    assert store._conn.execute(
        "SELECT COUNT(*) FROM jquants_records"
    ).fetchone()[0] == 1
    assert store._conn.execute(
        "SELECT COUNT(*) FROM collection_receipts"
    ).fetchone()[0] == 0
    assert store._conn.execute(
        "SELECT status FROM ingestion_run_log WHERE id=?", (context.run_id,)
    ).fetchone()["status"] == "STRUCTURED_COMMITTED"
    assert service._issued_evidence == []
    store.close()


def test_context_staleness_crossed_after_commit_stops_before_issuer(
    tmp_path: Path, receipt_ed25519_keys
) -> None:
    import ingestion.runtime_authority as runtime

    now = {"value": "2026-08-11T09:00:00+09:00"}
    service = _tmp_service(receipt_ed25519_keys, clock=lambda: now["value"])
    store = SqliteStore(tmp_path / "stale-after-commit.sqlite")
    req = list(
        plan_required_segments(
            coverage_contract_for("markets_calendar"),
            "2026-07-31",
            source="jquants",
        )
    )[-1]
    handle = _verified_collection(
        tmp_path / "capture",
        b'{"data":[{"Date":"2026-07-31"}]}',
        service=service,
        required=req,
    )
    context = _bound_context(store, service, req)
    _persisted_market_calendar_row(store)
    original = runtime._begin_receipt_verification_transaction

    def advance_past_context_age(target_store):
        now["value"] = "2026-08-11T09:16:01+09:00"
        original(target_store)

    with patch.object(
        runtime,
        "_begin_receipt_verification_transaction",
        side_effect=advance_past_context_age,
    ):
        with pytest.raises(ValueError, match="context is stale"):
            service.record_persisted_success(
                store,
                required=req,
                run_id=context.run_id,
                collection_context=context,
                jquants_collection=handle,
            )
    assert store._conn.execute(
        "SELECT COUNT(*) FROM jquants_records"
    ).fetchone()[0] == 1
    assert store._conn.execute(
        "SELECT COUNT(*) FROM collection_receipts"
    ).fetchone()[0] == 0
    assert store._conn.execute(
        "SELECT status FROM ingestion_run_log WHERE id=?", (context.run_id,)
    ).fetchone()["status"] == "STRUCTURED_COMMITTED"
    assert service._issued_evidence == []
    store.close()


def test_expiry_after_measurement_stops_at_immediate_preissuer_check(
    tmp_path: Path, receipt_ed25519_keys
) -> None:
    import ingestion.runtime_authority as runtime
    from ingestion.jquants.normalize import normalize_generic
    from tests.jquants_acquisition_test_support import build_live_acquisition

    now = {"value": "2026-08-11T14:59:59+09:00"}
    service = _tmp_service(receipt_ed25519_keys, clock=lambda: now["value"])
    store = SqliteStore(tmp_path / "expiry-preissuer.sqlite")
    req = list(
        plan_required_segments(
            coverage_contract_for("markets_calendar"),
            "2026-07-31",
            source="jquants",
        )
    )[-1]
    fixture = build_live_acquisition(
        tmp_path=tmp_path / "capture",
        service=service,
        required=req,
        raw_pages=(b'{"data":[{"Date":"2026-07-31"}]}',),
        expires_at="2026-08-11T06:00:00.000Z",
    )
    handle = service.verify_live_jquants_collection(
        capture=fixture.capture, required=req
    )
    context = _bound_context(store, service, req)
    store.upsert(
        "jquants_records",
        normalize_generic(
            [{"Date": "2026-07-31"}],
            dataset=req.dataset,
            ingested_at=context.checked_at,
        ),
        commit=False,
    )
    original = runtime._measure_collection_claims

    def measure_then_expire(*args, **kwargs):
        measured = original(*args, **kwargs)
        now["value"] = "2026-08-11T15:00:01+09:00"
        return measured

    with patch.object(
        runtime,
        "_measure_collection_claims",
        side_effect=measure_then_expire,
    ):
        with pytest.raises(ValueError, match="session has expired"):
            service.record_persisted_success(
                store,
                required=req,
                run_id=context.run_id,
                collection_context=context,
                jquants_collection=handle,
            )
    assert store._conn.execute(
        "SELECT COUNT(*) FROM jquants_records"
    ).fetchone()[0] == 1
    assert store._conn.execute(
        "SELECT COUNT(*) FROM collection_receipts"
    ).fetchone()[0] == 0
    assert store._conn.execute(
        "SELECT status FROM ingestion_run_log WHERE id=?", (context.run_id,)
    ).fetchone()["status"] == "STRUCTURED_COMMITTED"
    assert service._issued_evidence == []
    store.close()


def test_issuer_failure_leaves_structured_commit_without_receipt(
    tmp_path: Path, receipt_ed25519_keys
) -> None:
    service = _tmp_service(receipt_ed25519_keys)
    store = SqliteStore(tmp_path / "issuer-failure.sqlite")
    req = list(
        plan_required_segments(
            coverage_contract_for("markets_calendar"),
            "2026-07-31",
            source="jquants",
        )
    )[-1]
    handle = _verified_collection(
        tmp_path / "capture",
        b'{"data":[{"Date":"2026-07-31"}]}',
        service=service,
        required=req,
    )
    context = _bound_context(store, service, req)
    _persisted_market_calendar_row(store)
    with patch.object(
        type(service),
        "_issue_reconciled_evidence",
        side_effect=RuntimeError("injected issuer failure"),
    ):
        with pytest.raises(RuntimeError, match="injected issuer"):
            service.record_persisted_success(
                store,
                required=req,
                run_id=context.run_id,
                collection_context=context,
                jquants_collection=handle,
            )
    assert store._conn.execute(
        "SELECT COUNT(*) FROM jquants_records"
    ).fetchone()[0] == 1
    assert store._conn.execute(
        "SELECT COUNT(*) FROM collection_receipts"
    ).fetchone()[0] == 0
    assert store._conn.execute(
        "SELECT status FROM ingestion_run_log WHERE id=?", (context.run_id,)
    ).fetchone()["status"] == "STRUCTURED_COMMITTED"
    store.close()


def test_receipt_insert_failure_keeps_structured_commit_without_local_receipt(
    tmp_path: Path, receipt_ed25519_keys
) -> None:
    import ingestion.runtime_authority as runtime

    service = _tmp_service(receipt_ed25519_keys)
    store = SqliteStore(tmp_path / "receipt-insert-failure.sqlite")
    req = list(
        plan_required_segments(
            coverage_contract_for("markets_calendar"),
            "2026-07-31",
            source="jquants",
        )
    )[-1]
    handle = _verified_collection(
        tmp_path / "capture",
        b'{"data":[{"Date":"2026-07-31"}]}',
        service=service,
        required=req,
    )
    context = _bound_context(store, service, req)
    _persisted_market_calendar_row(store)
    with patch.object(
        runtime,
        "record_collection_receipt",
        side_effect=sqlite3.OperationalError("injected receipt insert failure"),
    ):
        with pytest.raises(sqlite3.OperationalError, match="injected"):
            service.record_persisted_success(
                store,
                required=req,
                run_id=context.run_id,
                collection_context=context,
                jquants_collection=handle,
            )
    assert store._conn.execute(
        "SELECT COUNT(*) FROM jquants_records"
    ).fetchone()[0] == 1
    assert store._conn.execute(
        "SELECT COUNT(*) FROM collection_receipts"
    ).fetchone()[0] == 0
    run = store._conn.execute(
        "SELECT status FROM ingestion_run_log WHERE id=?", (context.run_id,)
    ).fetchone()
    assert run is not None and run["status"] == "STRUCTURED_COMMITTED"
    # The signed envelope is truthful and recoverable, but append/finalize is
    # not cross-service atomic.  D2/D3 remain PENDING until a separate authority
    # ledger/recovery protocol exists.
    assert len(service._issued_evidence) == 1
    store.close()


def test_final_status_failure_rolls_back_receipt_but_not_structured_commit(
    tmp_path: Path, receipt_ed25519_keys
) -> None:
    service = _tmp_service(receipt_ed25519_keys)
    store = SqliteStore(tmp_path / "final-status-failure.sqlite")
    store._conn.executescript(
        """
        CREATE TRIGGER reject_receipt_verified
        BEFORE UPDATE OF status ON ingestion_run_log
        WHEN NEW.status = 'RECEIPT_VERIFIED'
        BEGIN
          SELECT RAISE(ABORT, 'injected final transition failure');
        END;
        """
    )
    store._conn.commit()
    req = list(
        plan_required_segments(
            coverage_contract_for("markets_calendar"),
            "2026-07-31",
            source="jquants",
        )
    )[-1]
    handle = _verified_collection(
        tmp_path / "capture",
        b'{"data":[{"Date":"2026-07-31"}]}',
        service=service,
        required=req,
    )
    context = _bound_context(store, service, req)
    _persisted_market_calendar_row(store)
    with pytest.raises(sqlite3.IntegrityError, match="final transition"):
        service.record_persisted_success(
            store,
            required=req,
            run_id=context.run_id,
            collection_context=context,
            jquants_collection=handle,
        )
    assert store._conn.execute(
        "SELECT COUNT(*) FROM jquants_records"
    ).fetchone()[0] == 1
    assert store._conn.execute(
        "SELECT COUNT(*) FROM collection_receipts"
    ).fetchone()[0] == 0
    assert store._conn.execute(
        "SELECT status FROM ingestion_run_log WHERE id=?", (context.run_id,)
    ).fetchone()["status"] == "STRUCTURED_COMMITTED"
    # This emitted-but-not-locally-finalized envelope is the explicit D2/D3
    # cross-service atomicity residual; production activation remains PENDING.
    assert len(service._issued_evidence) == 1
    store.close()


@pytest.mark.parametrize("mode", ["garbage", "valid_different_claims"])
def test_unverified_or_mismatched_signer_response_never_marks_receipt_verified(
    tmp_path: Path, receipt_ed25519_keys, mode: str
) -> None:
    from storage.receipt_crypto import canonical_evidence_digest
    from tests.receipt_test_support import build_test_signed_digest_fields

    service = _tmp_service(receipt_ed25519_keys)
    store = SqliteStore(tmp_path / f"wrong-signer-{mode}.sqlite")
    req = list(
        plan_required_segments(
            coverage_contract_for("markets_calendar"),
            "2026-07-31",
            source="jquants",
        )
    )[-1]
    handle = _verified_collection(
        tmp_path / "capture",
        b'{"data":[{"Date":"2026-07-31"}]}',
        service=service,
        required=req,
    )
    context = _bound_context(store, service, req)
    _persisted_market_calendar_row(store)

    def wrong_response(bound_service, evidence):
        if mode == "garbage":
            return {"garbage": "not-a-closed-signed-envelope"}
        claims = dict(bound_service._consume_reconciled_evidence(evidence))
        claims["raw_count"] = int(claims["raw_count"]) + 1
        observation = {
            key: value for key, value in claims.items() if key != "observation_digest"
        }
        claims["observation_digest"] = canonical_evidence_digest(observation)
        return build_test_signed_digest_fields(
            signing_key=receipt_ed25519_keys.signing_key,
            closure_claims=claims,
        )

    with patch.object(
        type(service), "_issue_reconciled_evidence", new=wrong_response
    ):
        with pytest.raises(ValueError):
            service.record_persisted_success(
                store,
                required=req,
                run_id=context.run_id,
                collection_context=context,
                jquants_collection=handle,
            )
    assert store._conn.execute(
        "SELECT COUNT(*) FROM collection_receipts"
    ).fetchone()[0] == 0
    assert store._conn.execute(
        "SELECT status FROM ingestion_run_log WHERE id=?", (context.run_id,)
    ).fetchone()["status"] == "STRUCTURED_COMMITTED"
    store.close()


def test_standard_raw_manifest_and_acquisition_chain_digests_are_distinct(
    tmp_path: Path, receipt_ed25519_keys
) -> None:
    from storage.receipt_crypto import canonical_evidence_digest
    from tests.jquants_acquisition_test_support import build_live_acquisition

    service = _tmp_service(receipt_ed25519_keys)
    store = SqliteStore(tmp_path / "digest-semantics.sqlite")
    req = list(
        plan_required_segments(
            coverage_contract_for("markets_calendar"),
            "2026-07-31",
            source="jquants",
        )
    )[-1]
    raw = b'{"data":[{"Date":"2026-07-31"}]}'
    fixture = build_live_acquisition(
        tmp_path=tmp_path / "capture",
        service=service,
        required=req,
        raw_pages=(raw,),
    )
    handle = service.verify_live_jquants_collection(
        capture=fixture.capture, required=req
    )
    context = _bound_context(store, service, req)
    _persisted_market_calendar_row(store)
    receipt = service.record_persisted_success(
        store,
        required=req,
        run_id=context.run_id,
        collection_context=context,
        jquants_collection=handle,
    )
    page_digest = canonical_evidence_digest(raw)
    expected_page_manifest = canonical_evidence_digest(
        {"pages": [{"index": 0, "digest": page_digest, "size": len(raw)}]}
    )
    assert receipt.digests["raw_manifest_digest"] == expected_page_manifest
    assert receipt.digests["acquisition_collection_manifest_file_digest"] == (
        canonical_evidence_digest(fixture.manifest_path.read_bytes())
    )
    assert receipt.digests["acquisition_collection_digest"] == (
        fixture.document["collection_digest"]
    )
    assert receipt.digests["acquisition_terminal_chain_digest"] == (
        fixture.document["pages"][-1]["metadata"]["chain_digest"]
    )
    assert (
        receipt.digests["raw_manifest_digest"]
        != receipt.digests["acquisition_collection_manifest_file_digest"]
    )
    store.close()


def test_caller_expected_empty_override_is_rejected(
    tmp_path: Path, receipt_ed25519_keys,
) -> None:
    from ingestion.jquants.receipts import emit_segment_receipt

    store = SqliteStore(tmp_path / "empty.sqlite")
    req = list(
        plan_required_segments(
            coverage_contract_for("markets_calendar"),
            "2026-07-31",
            source="jquants",
        )
    )[-1]
    raw = b'{"data":[]}'
    service = _tmp_service(receipt_ed25519_keys, raw=raw)
    persisted = _verified_collection(
        tmp_path / "raw", raw, service=service, required=req
    )
    with pytest.raises(ValueError, match="does not accept caller extra_evidence"):
        emit_segment_receipt(
            store,
            required=req,
            run_id=1,
            persisted_collection=persisted,
            collection_context=_bound_context(store, service, req),
            service=service,
            extra_evidence={"EXPECTED_EMPTY_WITH_EVIDENCE": True},
        )
    assert service._issued_evidence == []
    store.close()


def test_extra_structured_key_inside_segment_is_rejected(
    tmp_path: Path, receipt_ed25519_keys,
) -> None:
    from ingestion.jquants.normalize import normalize_generic
    from ingestion.jquants.receipts import emit_segment_receipt

    store = SqliteStore(tmp_path / "extra.sqlite")
    req = list(
        plan_required_segments(
            coverage_contract_for("markets_calendar"),
            "2026-07-31",
            source="jquants",
        )
    )[-1]
    raw = b'{"data":[{"Date":"2026-07-31"}]}'
    service = _tmp_service(receipt_ed25519_keys, raw=raw)
    persisted = _verified_collection(
        tmp_path / "raw", raw, service=service, required=req
    )
    rows = normalize_generic(
        [{"Date": "2026-07-31"}, {"Date": "2026-07-30"}],
        dataset="markets_calendar",
        ingested_at="2026-08-11T09:00:00+09:00",
    )
    store.upsert("jquants_records", rows, commit=False)
    with pytest.raises(ValueError, match="natural keys differ"):
        emit_segment_receipt(
            store,
            required=req,
            run_id=1,
            persisted_collection=persisted,
            collection_context=_bound_context(store, service, req),
            service=service,
        )
    assert service._issued_evidence == []
    store.close()


def test_reconciled_evidence_direct_import_is_not_a_capability(
    receipt_ed25519_keys,
) -> None:
    import ingestion.runtime_authority as runtime

    assert not hasattr(runtime, "_mint_reconciled_collection_evidence")
    service = _tmp_service(receipt_ed25519_keys)
    with pytest.raises(TypeError, match="minted by ingestion runtime"):
        runtime._ReconciledCollectionEvidence(
            _seal=object(),
            _authority_id=service._authority_id,
        )

    # Even importing the implementation seal cannot register arbitrary claims.
    forged = runtime._ReconciledCollectionEvidence(
        _seal=runtime._RECONCILED_COLLECTION_SEAL,
        _authority_id=service._authority_id,
    )
    with pytest.raises(TypeError, match="not runtime-registered"):
        service._consume_reconciled_evidence(forged)


@pytest.mark.parametrize(
    "claim",
    (
        "observed_items",
        "raw_row_count",
        "structured_row_count",
        "structured_digest",
        "pagination_exhausted",
        "discovery_exhausted",
        "receipt_digests",
    ),
)
def test_record_persisted_success_rejects_caller_claims(
    claim: str,
    receipt_ed25519_keys,
) -> None:
    service = _tmp_service(receipt_ed25519_keys)
    store = SqliteStore(":memory:")
    required = list(
        plan_required_segments(
            coverage_contract_for("markets_calendar"),
            "2026-08-11",
            source="jquants",
        )
    )[-1]
    with pytest.raises(TypeError, match=claim):
        service.record_persisted_success(
            store,
            required=required,
            run_id=1,
            collection_context=_bound_context(store, service, required),
            **{claim: "caller-asserted"},  # type: ignore[arg-type]
        )
    assert service._issued_evidence == []
    assert store._conn.execute(
        "SELECT COUNT(*) FROM collection_receipts"
    ).fetchone()[0] == 0
    store.close()


def test_authority_context_cannot_be_caller_timestamp(
    receipt_ed25519_keys,
) -> None:
    from ingestion.runtime_authority import (
        _GovernedCollectionContext,
        _open_governed_receipt_service,
    )

    with pytest.raises(TypeError, match="minted by receipt authority"):
        _GovernedCollectionContext(
            _seal=object(),
            _authority_id=object(),
            checked_at="1900-01-01T00:00:00+00:00",
        )
    service = _tmp_service(receipt_ed25519_keys)
    assert service.begin_collection().checked_at == "2026-08-11T09:00:00+09:00"
    from dataclasses import replace

    forged = replace(
        service.begin_collection(), checked_at="1900-01-01T00:00:00+00:00"
    )
    store = SqliteStore(":memory:")
    req = list(
        plan_required_segments(
            coverage_contract_for("markets_calendar"),
            "2026-08-11",
            source="jquants",
        )
    )[-1]
    with pytest.raises(TypeError, match="registered collection context"):
        service.record_persisted_success(
            store,
            required=req,
            run_id=1,
            collection_context=forged,
        )
    store.close()


def test_production_opener_rejects_clock_and_transport_injection_even_under_pytest_env(
    receipt_ed25519_keys, monkeypatch,
) -> None:
    from ingestion.runtime_authority import (
        ReceiptEvidenceAuthorityPending,
        _open_governed_receipt_service,
    )

    monkeypatch.setenv("PYTEST_CURRENT_TEST", "caller-controlled")
    with pytest.raises(ReceiptEvidenceAuthorityPending, match="PENDING"):
        _open_governed_receipt_service()
    with pytest.raises(TypeError, match="unexpected keyword argument 'pem'"):
        _open_governed_receipt_service(  # type: ignore[call-arg]
            pem=receipt_ed25519_keys.private_pem
        )
    with pytest.raises(TypeError, match="unexpected keyword argument 'path'"):
        _open_governed_receipt_service(path=Path("attacker.pem"))  # type: ignore[call-arg]
    with pytest.raises(TypeError, match="unexpected keyword argument 'key_id'"):
        _open_governed_receipt_service(key_id="attacker")  # type: ignore[call-arg]
    with pytest.raises(TypeError, match="unexpected keyword argument '_clock'"):
        _open_governed_receipt_service(
            _clock=lambda: "1900-01-01T00:00:00+00:00",  # type: ignore[call-arg]
        )
    with pytest.raises(
        TypeError, match="unexpected keyword argument '_test_jquants_http_factory'"
    ):
        _open_governed_receipt_service(
            _test_jquants_http_factory=lambda: _RawHttp(  # type: ignore[call-arg]
                b'{"data":[{"Date":"2026-08-11"}]}',
                "https://api.jquants.com/v2/markets/calendar",
            ),
        )


def test_governed_client_constructs_direct_verified_transport(
    receipt_ed25519_keys,
) -> None:
    import ingestion.common.http as http_module

    service = _tmp_service(receipt_ed25519_keys)
    fake = _RawHttp(
        b'{"data":[{"Date":"2026-08-11"}]}',
        "https://api.jquants.com/v2/markets/calendar",
    )
    with patch.object(http_module, "LocalHttpClient", return_value=fake) as ctor:
        service.open_jquants_client(api_key="test", via_cf_proxy=False)
    ctor.assert_called_once_with(verify=True, trust_env=False)


def test_context_and_verified_collection_are_single_use(
    tmp_path: Path, receipt_ed25519_keys,
) -> None:
    from dataclasses import replace
    from ingestion.jquants.normalize import normalize_generic
    from ingestion.jquants.receipts import emit_segment_receipt

    raw = b'{"data":[{"Date":"2026-07-31"}]}'
    service = _tmp_service(receipt_ed25519_keys)
    store = SqliteStore(tmp_path / "single-use.sqlite")
    req = list(
        plan_required_segments(
            coverage_contract_for("markets_calendar"),
            "2026-07-31",
            source="jquants",
        )
    )[-1]
    handle = _verified_collection(
        tmp_path / "raw-1", raw, service=service, required=req
    )
    context = _bound_context(store, service, req)
    row = normalize_generic(
        [{"Date": "2026-07-31"}],
        dataset="markets_calendar",
        ingested_at=context.checked_at,
    )[0]
    store.upsert("jquants_records", [row], commit=False)
    emit_segment_receipt(
        store,
        required=req,
        run_id=1,
        persisted_collection=handle,
        collection_context=context,
        service=service,
    )

    assert len(service._issued_evidence) == 1
    evidence = service._issued_evidence[0]
    with pytest.raises(TypeError, match="already been consumed"):
        service._consume_reconciled_evidence(evidence)
    copied = replace(evidence)
    with pytest.raises(TypeError, match="not runtime-registered"):
        service._consume_reconciled_evidence(copied)
    other_service = _tmp_service(receipt_ed25519_keys)
    with pytest.raises(TypeError, match="another authority"):
        other_service._consume_reconciled_evidence(evidence)

    fresh_handle = _verified_collection(
        tmp_path / "raw-2", raw, service=service, required=req
    )
    with pytest.raises(TypeError, match="context has already been consumed"):
        emit_segment_receipt(
            store,
            required=req,
            run_id=1,
            persisted_collection=fresh_handle,
            collection_context=context,
            service=service,
        )
    with pytest.raises(TypeError, match="collection has already been consumed"):
        emit_segment_receipt(
            store,
            required=req,
            run_id=2,
            persisted_collection=handle,
            collection_context=_bound_context(store, service, req),
            service=service,
        )
    assert store._conn.execute(
        "SELECT COUNT(*) FROM collection_receipts"
    ).fetchone()[0] == 1
    store.close()


def test_context_is_authority_bound_and_stale_context_fails_closed(
    tmp_path: Path, receipt_ed25519_keys,
) -> None:
    from ingestion.jquants.normalize import normalize_generic
    from ingestion.jquants.receipts import emit_segment_receipt

    raw = b'{"data":[{"Date":"2026-08-11"}]}'
    service_a = _tmp_service(receipt_ed25519_keys)
    service_b = _tmp_service(receipt_ed25519_keys)
    store = SqliteStore(tmp_path / "authority-bound.sqlite")
    req = list(
        plan_required_segments(
            coverage_contract_for("markets_calendar"),
            "2026-08-11",
            source="jquants",
        )
    )[-1]
    cross_context = _bound_context(store, service_a, req)
    cross_handle = _persisted_collection(
        tmp_path / "cross-raw", raw, service=service_b
    )
    with pytest.raises(TypeError, match="another authority"):
        emit_segment_receipt(
            store,
            required=req,
            run_id=1,
            persisted_collection=cross_handle,
            collection_context=cross_context,
            service=service_b,
        )

    stale_ticks = iter(
        [
            "2026-08-11T09:00:00+09:00",
            "2026-08-11T09:16:01+09:00",
        ]
    )
    stale_service = _tmp_service(
        receipt_ed25519_keys, clock=lambda: next(stale_ticks)
    )
    stale_context = _bound_context(store, stale_service, req)
    stale_row = normalize_generic(
        [{"Date": "2026-08-11"}],
        dataset="markets_calendar",
        ingested_at=stale_context.checked_at,
    )[0]
    store.upsert("jquants_records", [stale_row], commit=False)
    stale_handle = _persisted_collection(
        tmp_path / "stale-raw", raw, service=stale_service
    )
    with pytest.raises(ValueError, match="context is stale"):
        emit_segment_receipt(
            store,
            required=req,
            run_id=stale_context.run_id,
            persisted_collection=stale_handle,
            collection_context=stale_context,
            service=stale_service,
        )
    assert store._conn.execute(
        "SELECT COUNT(*) FROM collection_receipts"
    ).fetchone()[0] == 0
    store.close()


def test_same_segment_can_be_idempotently_reproved(
    tmp_path: Path, receipt_ed25519_keys,
) -> None:
    from ingestion.jquants.receipts import emit_segment_receipt
    from ingestion.runtime_authority import _open_governed_receipt_service
    from storage.coverage_ledger import is_complete_eligible_receipt

    now = {"value": "2026-08-11T09:00:00+09:00"}
    service = _tmp_service(
        receipt_ed25519_keys,
        clock=lambda: now["value"],
    )
    store = SqliteStore(tmp_path / "reproof.sqlite")
    req = list(
        plan_required_segments(
            coverage_contract_for("markets_calendar"),
            "2026-07-31",
            source="jquants",
        )
    )[-1]
    record_required_segments(store._conn, [req])
    receipts = []
    for run_id in (1, 2):
        now["value"] = f"2026-08-11T09:0{run_id - 1}:00+09:00"
        persisted = _verified_collection(
            tmp_path / f"raw-{run_id}",
            b'{"data":[{"Date":"2026-07-31"}]}',
            service=service,
            required=req,
        )
        context = _bound_context(store, service, req)
        row = __import__(
            "ingestion.jquants.normalize", fromlist=["normalize_generic"]
        ).normalize_generic(
            [{"Date": "2026-07-31"}],
            dataset="markets_calendar",
            ingested_at=context.checked_at,
        )[0]
        store.upsert("jquants_records", [row], commit=False)
        receipts.append(
            emit_segment_receipt(
                store,
                required=req,
                run_id=run_id,
                persisted_collection=persisted,
                collection_context=context,
                service=service,
            )
        )
    assert all(is_complete_eligible_receipt(item) for item in receipts)
    assert store._conn.execute(
        "SELECT COUNT(*) FROM collection_receipts"
    ).fetchone()[0] == 2
    store.close()


def test_legacy_v3_receipt_cannot_supply_available_at_for_v4_reproof(
    tmp_path: Path, receipt_ed25519_keys,
) -> None:
    """A first v4 proof must not inherit PIT time from insecure legacy proof."""
    import base64
    from ingestion.jquants.normalize import normalize_generic
    from ingestion.jquants.receipts import emit_segment_receipt
    from ingestion.runtime_authority import _open_governed_receipt_service
    from storage.receipt_crypto import body_digest, canonical_receipt_body

    now = {"value": "2026-08-11T09:00:00+09:00"}
    raw = b'{"data":[{"Date":"2026-07-31"}]}'
    service = _tmp_service(
        receipt_ed25519_keys,
        clock=lambda: now["value"],
    )
    store = SqliteStore(tmp_path / "legacy-reproof.sqlite")
    req = list(
        plan_required_segments(
            coverage_contract_for("markets_calendar"),
            "2026-07-31",
            source="jquants",
        )
    )[-1]
    record_required_segments(store._conn, [req])
    first_handle = _verified_collection(
        tmp_path / "legacy-raw-1",
        raw,
        service=service,
        required=req,
    )
    first_context = _bound_context(store, service, req)
    first_row = normalize_generic(
        [{"Date": "2026-07-31"}],
        dataset="markets_calendar",
        ingested_at=first_context.checked_at,
    )[0]
    store.upsert("jquants_records", [first_row], commit=False)
    first = emit_segment_receipt(
        store,
        required=req,
        run_id=1,
        persisted_collection=first_handle,
        collection_context=first_context,
        service=service,
    )

    claims = json.loads(base64.b64decode(first.digests["signed_body_b64"]))
    claims["parser_normalizer_version"] = "coverage-receipt/v3-ed25519-closure"
    legacy_body = canonical_receipt_body(claims)
    legacy_digests = dict(first.digests)
    legacy_digests.update(
        {
            "parser_normalizer_version": claims["parser_normalizer_version"],
            "signed_body_b64": base64.b64encode(legacy_body).decode("ascii"),
            "signature": receipt_ed25519_keys.signing_key.sign(legacy_body),
            "body_digest": body_digest(legacy_body),
        }
    )
    store._conn.execute(
        "UPDATE collection_receipts SET digests_json=? WHERE run_id=1",
        (json.dumps(legacy_digests, sort_keys=True),),
    )
    store._conn.commit()

    now["value"] = "2026-08-11T09:01:00+09:00"
    second_handle = _verified_collection(
        tmp_path / "legacy-raw-2",
        raw,
        service=service,
        required=req,
    )
    second_context = _bound_context(store, service, req)
    second_row = normalize_generic(
        [{"Date": "2026-07-31"}],
        dataset="markets_calendar",
        ingested_at=second_context.checked_at,
    )[0]
    store.upsert("jquants_records", [second_row], commit=False)
    with pytest.raises(ValueError, match="canonical normalization"):
        emit_segment_receipt(
            store,
            required=req,
            run_id=2,
            persisted_collection=second_handle,
            collection_context=second_context,
            service=service,
        )
    assert store._conn.execute(
        "SELECT COUNT(*) FROM collection_receipts"
    ).fetchone()[0] == 1
    store.close()
