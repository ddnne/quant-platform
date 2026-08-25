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
    from ingestion.runtime_authority import _open_governed_receipt_service

    del raw, response_url
    import ingestion.runtime_authority as runtime

    test_clock = clock or (lambda: "2026-08-11T09:00:00+09:00")
    with patch.object(runtime, "_utc_now", test_clock):
        return _open_governed_receipt_service(
            pem=receipt_ed25519_keys.private_pem,
        )


def _persisted_market_calendar_row(store: SqliteStore) -> dict:
    from ingestion.jquants.normalize import normalize_generic

    row = normalize_generic(
        [{"Date": "2026-08-11"}],
        dataset="markets_calendar",
        ingested_at="2026-08-11T09:00:00+09:00",
    )[0]
    store.upsert("jquants_records", [row], commit=False)
    return row


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
    req = list(plan_required_segments(policy, "2026-08-11", source="jquants"))[-1]
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
    raw = b'{"data":[{"Date":"2026-08-11"}]}'
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
    req = list(plan_required_segments(policy, "2026-08-11", source="jquants"))[-1]
    record_required_segments(store._conn, [req])
    raw = b'{"data":[{"Date":"2026-08-11"}]}'
    service = _tmp_service(receipt_ed25519_keys, raw=raw)
    persisted = _persisted_collection(tmp_path, raw, service=service)
    _persisted_market_calendar_row(store)
    receipt = emit_segment_receipt(
        store,
        required=req,
        run_id=1,
        persisted_collection=persisted,
        collection_context=service.begin_collection(),
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
    req = list(plan_required_segments(policy, "2026-08-11", source="jquants"))[-1]
    raw = b'{"data":[{"Date":"2026-08-11"}]}'
    service = _tmp_service(receipt_ed25519_keys, raw=raw)
    persisted = _persisted_collection(
        tmp_path, raw, service=service
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
            collection_context=service.begin_collection(),
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


def test_post_mint_raw_and_manifest_rewrite_is_rejected(
    tmp_path: Path, receipt_ed25519_keys,
) -> None:
    """chmod-back-to-readonly cannot hide a post-mint byte substitution."""
    from ingestion.jquants.receipts import emit_segment_receipt

    original = b'{"data":[{"Date":"2026-08-11"}]}'
    service = _tmp_service(receipt_ed25519_keys, raw=original)
    persisted = _persisted_collection(
        tmp_path / "raw", original, service=service
    )
    forged = b'{"data":[{"Date":"2099-01-01"}]}'
    raw_path = persisted.raw_paths[0]
    raw_path.chmod(0o644)
    raw_path.write_bytes(forged)
    raw_path.chmod(0o444)
    manifest_path = persisted.manifest_path
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    payload["pages"][0]["body_digest"] = (
        "sha256:" + hashlib.sha256(forged).hexdigest()
    )
    manifest_path.chmod(0o644)
    manifest_path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
    manifest_path.chmod(0o444)

    store = SqliteStore(tmp_path / "toctou.sqlite")
    req = list(
        plan_required_segments(
            coverage_contract_for("markets_calendar"),
            "2026-08-11",
            source="jquants",
        )
    )[-1]
    _persisted_market_calendar_row(store)
    with pytest.raises(ValueError, match="changed after mint"):
        emit_segment_receipt(
            store,
            required=req,
            run_id=1,
            persisted_collection=persisted,
            collection_context=service.begin_collection(),
            service=service,
        )
    assert store._conn.execute(
        "SELECT COUNT(*) FROM collection_receipts"
    ).fetchone()[0] == 0
    store.close()


def test_replaced_persisted_handle_is_not_a_capability(
    tmp_path: Path, receipt_ed25519_keys,
) -> None:
    from dataclasses import replace
    from ingestion.jquants.receipts import emit_segment_receipt

    raw = b'{"data":[{"Date":"2026-08-11"}]}'
    service = _tmp_service(receipt_ed25519_keys, raw=raw)
    persisted = _persisted_collection(
        tmp_path / "raw", raw, service=service
    )
    forged = replace(persisted, manifest_digest="sha256:" + "0" * 64)
    store = SqliteStore(tmp_path / "replaced.sqlite")
    req = list(
        plan_required_segments(
            coverage_contract_for("markets_calendar"),
            "2026-08-11",
            source="jquants",
        )
    )[-1]
    with pytest.raises(TypeError, match="not runtime-registered"):
        emit_segment_receipt(
            store,
            required=req,
            run_id=1,
            persisted_collection=forged,
            collection_context=service.begin_collection(),
            service=service,
        )
    store.close()


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
    with pytest.raises(TypeError, match="runtime-minted persisted evidence"):
        service.record_persisted_success(
            store,
            required=req,
            run_id=1,
            collection_context=service.begin_collection(),
            raw_artifact_paths=(raw_path,),
        )
    store.close()


@pytest.mark.parametrize(
    ("params", "message"),
    [
        ({"from": "2026-08-01", "to": "2026-08-10"}, "exactly equal"),
        (
            {
                "from": "2026-08-01",
                "to": "2026-08-11",
                "holidaydivision": "1",
            },
            "narrowing filter",
        ),
    ],
)
def test_partial_or_narrowed_query_cannot_sign_month_scope(
    tmp_path: Path, receipt_ed25519_keys, params: dict, message: str,
) -> None:
    from ingestion.jquants.receipts import emit_segment_receipt

    store = SqliteStore(tmp_path / "scope.sqlite")
    req = list(
        plan_required_segments(
            coverage_contract_for("markets_calendar"),
            "2026-08-11",
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
    with pytest.raises(ValueError, match=message):
        emit_segment_receipt(
            store,
            required=req,
            run_id=1,
            persisted_collection=persisted,
            collection_context=service.begin_collection(),
            service=service,
        )
    assert store._conn.execute(
        "SELECT COUNT(*) FROM collection_receipts"
    ).fetchone()[0] == 0
    store.close()


def test_caller_expected_empty_override_is_rejected(
    tmp_path: Path, receipt_ed25519_keys,
) -> None:
    from ingestion.jquants.receipts import emit_segment_receipt

    store = SqliteStore(tmp_path / "empty.sqlite")
    req = list(
        plan_required_segments(
            coverage_contract_for("markets_calendar"),
            "2026-08-11",
            source="jquants",
        )
    )[-1]
    raw = b'{"data":[]}'
    service = _tmp_service(receipt_ed25519_keys, raw=raw)
    persisted = _persisted_collection(
        tmp_path / "raw", raw, service=service
    )
    with pytest.raises(ValueError, match="does not accept caller extra_evidence"):
        emit_segment_receipt(
            store,
            required=req,
            run_id=1,
            persisted_collection=persisted,
            collection_context=service.begin_collection(),
            service=service,
            extra_evidence={"EXPECTED_EMPTY_WITH_EVIDENCE": True},
        )
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
            "2026-08-11",
            source="jquants",
        )
    )[-1]
    raw = b'{"data":[{"Date":"2026-08-11"}]}'
    service = _tmp_service(receipt_ed25519_keys, raw=raw)
    persisted = _persisted_collection(
        tmp_path / "raw", raw, service=service
    )
    rows = normalize_generic(
        [{"Date": "2026-08-11"}, {"Date": "2026-08-10"}],
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
            collection_context=service.begin_collection(),
            service=service,
        )
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
    from ingestion.runtime_authority import _open_governed_receipt_service

    monkeypatch.setenv("PYTEST_CURRENT_TEST", "caller-controlled")
    with pytest.raises(TypeError, match="unexpected keyword argument '_clock'"):
        _open_governed_receipt_service(
            pem=receipt_ed25519_keys.private_pem,
            _clock=lambda: "1900-01-01T00:00:00+00:00",  # type: ignore[call-arg]
        )
    with pytest.raises(
        TypeError, match="unexpected keyword argument '_test_jquants_http_factory'"
    ):
        _open_governed_receipt_service(
            pem=receipt_ed25519_keys.private_pem,
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


def test_context_and_persisted_fetch_are_single_use(
    tmp_path: Path, receipt_ed25519_keys,
) -> None:
    from ingestion.jquants.normalize import normalize_generic
    from ingestion.jquants.receipts import emit_segment_receipt

    raw = b'{"data":[{"Date":"2026-08-11"}]}'
    service = _tmp_service(receipt_ed25519_keys)
    store = SqliteStore(tmp_path / "single-use.sqlite")
    req = list(
        plan_required_segments(
            coverage_contract_for("markets_calendar"),
            "2026-08-11",
            source="jquants",
        )
    )[-1]
    context = service.begin_collection()
    row = normalize_generic(
        [{"Date": "2026-08-11"}],
        dataset="markets_calendar",
        ingested_at=context.checked_at,
    )[0]
    store.upsert("jquants_records", [row], commit=False)
    handle = _persisted_collection(tmp_path / "raw-1", raw, service=service)
    emit_segment_receipt(
        store,
        required=req,
        run_id=1,
        persisted_collection=handle,
        collection_context=context,
        service=service,
    )

    fresh_handle = _persisted_collection(
        tmp_path / "raw-2", raw, service=service
    )
    with pytest.raises(TypeError, match="context has already been consumed"):
        emit_segment_receipt(
            store,
            required=req,
            run_id=2,
            persisted_collection=fresh_handle,
            collection_context=context,
            service=service,
        )
    with pytest.raises(TypeError, match="evidence has already been consumed"):
        emit_segment_receipt(
            store,
            required=req,
            run_id=3,
            persisted_collection=handle,
            collection_context=service.begin_collection(),
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
    cross_context = service_a.begin_collection()
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
    stale_context = stale_service.begin_collection()
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
            run_id=2,
            persisted_collection=stale_handle,
            collection_context=stale_context,
            service=stale_service,
        )
    assert store._conn.execute(
        "SELECT COUNT(*) FROM collection_receipts"
    ).fetchone()[0] == 0
    store.close()


def test_all_universe_scope_rejects_code_filter() -> None:
    from ingestion.runtime_authority import _assert_jquants_request_scope
    from storage.coverage_ledger import RequiredCoverageSegment

    required = RequiredCoverageSegment(
        source="jquants",
        dataset="equities_bars_daily",
        segment_id="2026-08",
        segment_start="2026-08-01",
        segment_end="2026-08-31",
        expected_scope={
            "universe": "all_listed",
            "expected_item_unit": "source_query",
        },
        expected_items=1,
    )
    with pytest.raises(ValueError, match="narrowing filter 'code'"):
        _assert_jquants_request_scope(
            required=required,
            base_params={
                "from": "2026-08-01",
                "to": "2026-08-31",
                "code": "8697",
            },
            source_request=None,
        )


def test_same_segment_can_be_idempotently_reproved(
    tmp_path: Path, receipt_ed25519_keys,
) -> None:
    from ingestion.jquants.receipts import emit_segment_receipt
    from ingestion.runtime_authority import _open_governed_receipt_service
    from storage.coverage_ledger import is_complete_eligible_receipt

    ticks = iter(
        [
            "2026-08-11T09:00:00+09:00",
            "2026-08-11T09:00:00+09:00",
            "2026-08-11T09:01:00+09:00",
            "2026-08-11T09:01:00+09:00",
        ]
    )
    service = _tmp_service(
        receipt_ed25519_keys,
        clock=lambda: next(ticks),
    )
    store = SqliteStore(tmp_path / "reproof.sqlite")
    req = list(
        plan_required_segments(
            coverage_contract_for("markets_calendar"),
            "2026-08-11",
            source="jquants",
        )
    )[-1]
    record_required_segments(store._conn, [req])
    receipts = []
    for run_id in (1, 2):
        context = service.begin_collection()
        row = __import__(
            "ingestion.jquants.normalize", fromlist=["normalize_generic"]
        ).normalize_generic(
            [{"Date": "2026-08-11"}],
            dataset="markets_calendar",
            ingested_at=context.checked_at,
        )[0]
        store.upsert("jquants_records", [row], commit=False)
        persisted = _persisted_collection(
            tmp_path / f"raw-{run_id}",
            b'{"data":[{"Date":"2026-08-11"}]}',
            service=service,
        )
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

    ticks = iter(
        [
            "2026-08-11T09:00:00+09:00",
            "2026-08-11T09:00:00+09:00",
            "2026-08-11T09:01:00+09:00",
            "2026-08-11T09:01:00+09:00",
        ]
    )
    raw = b'{"data":[{"Date":"2026-08-11"}]}'
    service = _tmp_service(
        receipt_ed25519_keys,
        clock=lambda: next(ticks),
    )
    store = SqliteStore(tmp_path / "legacy-reproof.sqlite")
    req = list(
        plan_required_segments(
            coverage_contract_for("markets_calendar"),
            "2026-08-11",
            source="jquants",
        )
    )[-1]
    record_required_segments(store._conn, [req])
    first_context = service.begin_collection()
    first_row = normalize_generic(
        [{"Date": "2026-08-11"}],
        dataset="markets_calendar",
        ingested_at=first_context.checked_at,
    )[0]
    store.upsert("jquants_records", [first_row], commit=False)
    first_handle = _persisted_collection(
        tmp_path / "legacy-raw-1", raw, service=service
    )
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

    second_context = service.begin_collection()
    second_row = normalize_generic(
        [{"Date": "2026-08-11"}],
        dataset="markets_calendar",
        ingested_at=second_context.checked_at,
    )[0]
    store.upsert("jquants_records", [second_row], commit=False)
    second_handle = _persisted_collection(
        tmp_path / "legacy-raw-2", raw, service=service
    )
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
