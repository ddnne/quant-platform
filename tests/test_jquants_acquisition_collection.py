"""Behavioral invariants for live J-Quants acquisition reconciliation."""

from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path

import pytest

from data_contracts import coverage_contract_for
from storage.coverage_ledger import plan_required_segments
from tests import jquants_acquisition_test_support as support
from tests.receipt_test_support import open_test_receipt_service


def _required(dataset: str, target_end: str = "2026-07-31"):
    return list(
        plan_required_segments(
            coverage_contract_for(dataset), target_end, source="jquants"
        )
    )[-1]


def _service(receipt_ed25519_keys, clock=None):
    return open_test_receipt_service(
        signing_key=receipt_ed25519_keys.signing_key,
        clock=clock or (lambda: "2026-08-11T09:00:00+09:00"),
    )


def test_rpc_surface_is_available_from_packaged_registry_without_specs() -> None:
    from ingestion.jquants import acquisition_collection as acquisition

    assert not hasattr(acquisition, "_RPC_SCHEMA_PATH")
    surface = acquisition._rpc_surface()
    assert len(surface.request_keys) == 14
    assert len(surface.metadata_keys) == 34
    assert len(surface.header_names) == 37
    assert acquisition._SHARED_REGISTRY_PATH.parent.name == "data_contracts"


def test_live_range_capture_verifies_once(tmp_path: Path, receipt_ed25519_keys) -> None:
    service = _service(receipt_ed25519_keys)
    required = _required("indices_bars_daily_topix")
    fixture = support.build_live_acquisition(
        tmp_path=tmp_path,
        service=service,
        required=required,
        raw_pages=(b'{"data":[{"Date":"2026-07-31"}]}',),
    )
    verified = support.verify_live_acquisition(
        fixture, service=service, required=required
    )
    assert verified is not None
    with pytest.raises(TypeError, match="already been consumed"):
        support.verify_live_acquisition(fixture, service=service, required=required)


def test_live_range_capture_verifies_provider_page_chain(
    tmp_path: Path, receipt_ed25519_keys
) -> None:
    service = _service(receipt_ed25519_keys)
    required = _required("indices_bars_daily_topix")
    fixture = support.build_live_acquisition(
        tmp_path=tmp_path,
        service=service,
        required=required,
        raw_pages=(
            b'{"data":[{"Date":"2026-07-01"}],"pagination_key":"next"}',
            b'{"data":[{"Date":"2026-07-31"}],"pagination_key":null}',
        ),
    )
    assert [
        page["metadata"]["provider_page_ordinal"]
        for page in fixture.document["pages"]
    ] == [0, 1]
    assert support.verify_live_acquisition(
        fixture, service=service, required=required
    )


def test_sliced_capture_enumerates_every_calendar_day(
    tmp_path: Path, receipt_ed25519_keys
) -> None:
    service = _service(receipt_ed25519_keys)
    required = _required("equities_bars_daily")
    fixture = support.build_live_acquisition(
        tmp_path=tmp_path,
        service=service,
        required=required,
    )
    assert len(fixture.document["pages"]) == 31
    verified = support.verify_live_acquisition(
        fixture, service=service, required=required
    )
    assert verified is not None


def test_sliced_day_provider_pages_then_advances_calendar_day(
    tmp_path: Path, receipt_ed25519_keys
) -> None:
    service = _service(receipt_ed25519_keys)
    required = _required("equities_bars_daily")
    days = [f"2026-07-{day:02d}" for day in range(1, 32)]
    page_slices = [days[0], days[0], *days[1:]]
    raw_pages = [
        b'{"data":[],"pagination_key":"same-day-next"}',
        b'{"data":[],"pagination_key":null}',
        *([b'{"data":[]}'] * 30),
    ]
    provider_states = ["CONTINUATION", *(["EXHAUSTED"] * 31)]
    fixture = support.build_live_acquisition(
        tmp_path=tmp_path,
        service=service,
        required=required,
        raw_pages=raw_pages,
        page_slices=page_slices,
        provider_states=provider_states,
    )
    assert [
        (
            page["metadata"]["slice_date"],
            page["metadata"]["provider_page_ordinal"],
        )
        for page in fixture.document["pages"][:3]
    ] == [("2026-07-01", 0), ("2026-07-01", 1), ("2026-07-02", 0)]
    assert support.verify_live_acquisition(
        fixture, service=service, required=required
    )


def test_manifest_or_imported_seal_is_not_a_live_capability(
    tmp_path: Path, receipt_ed25519_keys
) -> None:
    from ingestion.jquants import acquisition_collection as acquisition

    service = _service(receipt_ed25519_keys)
    required = _required("markets_calendar")
    with pytest.raises(TypeError, match="minted by receipt authority"):
        acquisition._LiveJQuantsAcquisitionCapture(_seal=object())
    forged = acquisition._LiveJQuantsAcquisitionCapture(
        _seal=acquisition._LIVE_CAPTURE_SEAL
    )
    with pytest.raises(TypeError, match="not receipt-authority registered"):
        service.verify_live_jquants_collection(capture=forged, required=required)


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda doc: doc["pages"].pop(), "ends before terminal"),
        (
            lambda doc: doc["pages"].insert(1, doc["pages"][0]),
            "raw_path is non-canonical or duplicated",
        ),
        (
            lambda doc: doc["pages"].reverse(),
            "page ordinals are missing, duplicate, or reordered",
        ),
        (
            lambda doc: (
                doc["pages"][1]["metadata"].update(
                    previous_request_digest="sha256:" + "f" * 64
                ),
                doc["pages"][1].update(
                    headers=support._metadata_headers(doc["pages"][1]["metadata"])
                ),
            ),
            "request chain is missing, reordered, or spliced",
        ),
        (
            lambda doc: (
                doc["pages"][0]["metadata"].update(
                    pagination_state="EXHAUSTED", continuation_token=None
                ),
                doc["pages"][0].update(
                    headers=support._metadata_headers(doc["pages"][0]["metadata"])
                ),
            ),
            "terminated before the final calendar slice",
        ),
        (
            lambda doc: (
                doc["pages"][0]["metadata"].update(
                    evidence_state="RAW_ONLY", pagination_state="UNKNOWN"
                ),
                doc["pages"][0].update(
                    headers=support._metadata_headers(doc["pages"][0]["metadata"])
                ),
            ),
            "only RAW_PAGE",
        ),
        (
            lambda doc: doc["pages"][0].update(response_status=206),
            "non-200 target/upstream",
        ),
        (
            lambda doc: doc["initial_request"].update(
                url="https://attacker.invalid"
            ),
            "closed v2 field set",
        ),
    ],
)
def test_collection_state_machine_fails_closed(
    tmp_path: Path,
    receipt_ed25519_keys,
    mutation,
    message: str,
) -> None:
    service = _service(receipt_ed25519_keys)
    required = _required("equities_bars_daily")
    fixture = support.build_live_acquisition(
        tmp_path=tmp_path,
        service=service,
        required=required,
        mutate_document=mutation,
    )
    with pytest.raises(ValueError, match=message):
        support.verify_live_acquisition(fixture, service=service, required=required)


def test_repeated_query_digest_stops_chain(
    tmp_path: Path, receipt_ed25519_keys
) -> None:
    service = _service(receipt_ed25519_keys)
    required = _required("equities_bars_daily")

    def repeat_query(document):
        first = document["pages"][0]["metadata"]["query_digest"]
        metadata = document["pages"][1]["metadata"]
        metadata["query_digest"] = first
        document["pages"][1]["headers"] = support._metadata_headers(metadata)

    fixture = support.build_live_acquisition(
        tmp_path=tmp_path,
        service=service,
        required=required,
        mutate_document=repeat_query,
    )
    with pytest.raises(ValueError, match="query digest repeated"):
        support.verify_live_acquisition(fixture, service=service, required=required)


def test_provider_page_splice_stops_range_chain(
    tmp_path: Path, receipt_ed25519_keys
) -> None:
    service = _service(receipt_ed25519_keys)
    required = _required("indices_bars_daily_topix")

    def splice(document):
        metadata = document["pages"][1]["metadata"]
        metadata["provider_page_ordinal"] = 2
        document["pages"][1]["headers"] = support._metadata_headers(metadata)

    fixture = support.build_live_acquisition(
        tmp_path=tmp_path,
        service=service,
        required=required,
        raw_pages=(b'{"data":[],"pagination_key":"next"}', b'{"data":[]}'),
        mutate_document=splice,
    )
    with pytest.raises(ValueError, match="provider page ordinal"):
        support.verify_live_acquisition(fixture, service=service, required=required)


def test_exact_raw_pagination_cannot_be_hidden_by_terminal_metadata(
    tmp_path: Path, receipt_ed25519_keys
) -> None:
    service = _service(receipt_ed25519_keys)
    required = _required("indices_bars_daily_topix")
    fixture = support.build_live_acquisition(
        tmp_path=tmp_path,
        service=service,
        required=required,
        raw_pages=(b'{"data":[],"pagination_key":"hidden-next"}',),
    )
    with pytest.raises(ValueError, match="differs from exact raw response"):
        support.verify_live_acquisition(fixture, service=service, required=required)


def test_null_provider_pagination_is_terminal(
    tmp_path: Path, receipt_ed25519_keys
) -> None:
    service = _service(receipt_ed25519_keys)
    required = _required("indices_bars_daily_topix")
    fixture = support.build_live_acquisition(
        tmp_path=tmp_path,
        service=service,
        required=required,
        raw_pages=(b'{"data":[],"pagination_key":null}',),
    )
    assert support.verify_live_acquisition(
        fixture, service=service, required=required
    )


@pytest.mark.parametrize(
    "raw",
    (
        b'{"data":[],"pagination_key":17}',
        b'{"data":[],"pagination_token":"legacy"}',
        b'{"data":[],"cursor":"unauthorized"}',
        b'{"data":[],"next_page":"unknown"}',
        b'{"data":[],"data":[]}',
    ),
)
def test_invalid_or_unauthorized_provider_fields_fail_closed(
    tmp_path: Path, receipt_ed25519_keys, raw: bytes
) -> None:
    service = _service(receipt_ed25519_keys)
    required = _required("indices_bars_daily_topix")
    fixture = support.build_live_acquisition(
        tmp_path=tmp_path,
        service=service,
        required=required,
        raw_pages=(raw,),
    )
    with pytest.raises(
        ValueError, match="pagination cursor|unknown envelope|duplicate key"
    ):
        support.verify_live_acquisition(fixture, service=service, required=required)


def test_informational_cursor_cannot_coexist_with_history_pagination(
    tmp_path: Path, receipt_ed25519_keys
) -> None:
    service = _service(receipt_ed25519_keys)
    required = _required("fins_summary")
    pages = [b'{"data":[]}'] * 31
    pages[0] = b'{"data":[],"pagination_key":"next","cursor":"delta"}'
    fixture = support.build_live_acquisition(
        tmp_path=tmp_path,
        service=service,
        required=required,
        raw_pages=pages,
    )
    with pytest.raises(ValueError, match="differential cursor contradicts"):
        support.verify_live_acquisition(fixture, service=service, required=required)


def test_informational_cursor_is_allowed_but_never_drives_history_navigation(
    tmp_path: Path, receipt_ed25519_keys
) -> None:
    service = _service(receipt_ed25519_keys)
    required = _required("fins_summary")
    pages = [b'{"data":[]}'] * 31
    pages[0] = b'{"data":[],"cursor":"informational-delta"}'
    fixture = support.build_live_acquisition(
        tmp_path=tmp_path,
        service=service,
        required=required,
        raw_pages=pages,
    )
    assert support.verify_live_acquisition(
        fixture, service=service, required=required
    )


def test_target_continuation_without_raw_cursor_is_rejected(
    tmp_path: Path, receipt_ed25519_keys
) -> None:
    service = _service(receipt_ed25519_keys)
    required = _required("indices_bars_daily_topix")

    def false_continuation(document):
        metadata = document["pages"][0]["metadata"]
        metadata.update(
            provider_pagination_state="CONTINUATION",
            pagination_state="CONTINUATION",
            continuation_token=support._token(1),
        )
        document["pages"][0]["headers"] = support._metadata_headers(metadata)

    fixture = support.build_live_acquisition(
        tmp_path=tmp_path,
        service=service,
        required=required,
        raw_pages=(b'{"data":[],"pagination_key":null}',),
        mutate_document=false_continuation,
    )
    with pytest.raises(ValueError, match="differs from exact raw response"):
        support.verify_live_acquisition(fixture, service=service, required=required)


def test_repeated_raw_provider_cursor_stops_chain(
    tmp_path: Path, receipt_ed25519_keys
) -> None:
    service = _service(receipt_ed25519_keys)
    required = _required("indices_bars_daily_topix")
    fixture = support.build_live_acquisition(
        tmp_path=tmp_path,
        service=service,
        required=required,
        raw_pages=(
            b'{"data":[],"pagination_key":"same"}',
            b'{"data":[],"pagination_key":"same"}',
            b'{"data":[]}',
        ),
    )
    with pytest.raises(ValueError, match="provider pagination cursor repeated"):
        support.verify_live_acquisition(fixture, service=service, required=required)


def test_query_digest_is_independently_resolved(
    tmp_path: Path, receipt_ed25519_keys
) -> None:
    service = _service(receipt_ed25519_keys)
    required = _required("markets_calendar")

    def replace_query(document):
        metadata = document["pages"][0]["metadata"]
        metadata["query_digest"] = "sha256:" + "f" * 64
        document["pages"][0]["headers"] = support._metadata_headers(metadata)

    fixture = support.build_live_acquisition(
        tmp_path=tmp_path,
        service=service,
        required=required,
        mutate_document=replace_query,
    )
    with pytest.raises(ValueError, match="receipt-side resolution"):
        support.verify_live_acquisition(fixture, service=service, required=required)


def test_verified_capability_rechecks_post_verify_mutation(
    tmp_path: Path, receipt_ed25519_keys
) -> None:
    from ingestion.jquants import acquisition_collection as acquisition

    service = _service(receipt_ed25519_keys)
    required = _required("markets_calendar")
    fixture = support.build_live_acquisition(
        tmp_path=tmp_path,
        service=service,
        required=required,
        raw_pages=(b'{"data":[{"Date":"2026-07-31"}]}',),
    )
    verified = support.verify_live_acquisition(
        fixture, service=service, required=required
    )
    raw_path = fixture.raw_paths[0]
    raw_path.chmod(0o644)
    raw_path.write_bytes(b'{"data":[{"Date":"2099-01-01"}]}')
    raw_path.chmod(0o444)
    with pytest.raises(ValueError, match="changed after verification"):
        acquisition._consume_verified_jquants_collection(
            verified,
            authority_id=service._authority_id,
            now=acquisition._parse_clock("2026-08-11T09:00:00+09:00"),
        )
    copied = replace(verified)
    with pytest.raises(TypeError, match="not runtime-registered"):
        acquisition._consume_verified_jquants_collection(
            copied,
            authority_id=service._authority_id,
            now=acquisition._parse_clock("2026-08-11T09:00:00+09:00"),
        )


def test_verified_capability_rechecks_manifest_mutation(
    tmp_path: Path, receipt_ed25519_keys
) -> None:
    from ingestion.jquants import acquisition_collection as acquisition

    service = _service(receipt_ed25519_keys)
    required = _required("markets_calendar")
    fixture = support.build_live_acquisition(
        tmp_path=tmp_path,
        service=service,
        required=required,
        raw_pages=(b'{"data":[{"Date":"2026-07-31"}]}',),
    )
    verified = support.verify_live_acquisition(
        fixture, service=service, required=required
    )
    fixture.manifest_path.chmod(0o644)
    fixture.manifest_path.write_text("{}", encoding="utf-8")
    fixture.manifest_path.chmod(0o444)
    with pytest.raises(ValueError, match="manifest (size differs|changed)"):
        acquisition._consume_verified_jquants_collection(
            verified,
            authority_id=service._authority_id,
            now=acquisition._parse_clock("2026-08-11T09:00:00+09:00"),
        )


def test_collection_digest_is_recomputed_from_full_document(
    tmp_path: Path, receipt_ed25519_keys
) -> None:
    from ingestion.jquants import acquisition_collection as acquisition
    from storage.receipt_crypto import canonical_evidence_digest

    service = _service(receipt_ed25519_keys)
    required = _required("markets_calendar")
    fixture = support.build_live_acquisition(
        tmp_path=tmp_path,
        service=service,
        required=required,
        raw_pages=(b'{"data":[{"Date":"2026-07-31"}]}',),
    )
    document = dict(fixture.document)
    document["pages"] = [dict(page) for page in fixture.document["pages"]]
    document["pages"][0]["raw_size"] += 1
    fixture.manifest_path.chmod(0o644)
    fixture.manifest_path.write_text(
        json.dumps(document, sort_keys=True, separators=(",", ":")),
        encoding="utf-8",
    )
    fixture.manifest_path.chmod(0o444)
    with acquisition._CAPABILITY_LOCK:
        acquisition._LIVE_CAPTURES[fixture.capture]["manifest_digest"] = (
            canonical_evidence_digest(fixture.manifest_path.read_bytes())
        )
    with pytest.raises(ValueError, match="canonical digest does not reconcile"):
        support.verify_live_acquisition(fixture, service=service, required=required)


@pytest.mark.parametrize("target_end", ["2026-08-31", "2026-09-30"])
def test_current_and_future_months_are_rejected(
    tmp_path: Path, receipt_ed25519_keys, target_end: str
) -> None:
    service = _service(receipt_ed25519_keys)
    required = _required("markets_calendar", target_end)
    fixture = support.build_live_acquisition(
        tmp_path=tmp_path,
        service=service,
        required=required,
    )
    with pytest.raises(ValueError, match="current or future month"):
        support.verify_live_acquisition(fixture, service=service, required=required)


def test_prior_month_requires_first_day_0100_jst_cutoff(
    tmp_path: Path, receipt_ed25519_keys
) -> None:
    required = _required("markets_calendar", "2026-08-31")
    before = _service(
        receipt_ed25519_keys, clock=lambda: "2026-09-01T00:59:00+09:00"
    )
    before_fixture = support.build_live_acquisition(
        tmp_path=tmp_path / "before",
        service=before,
        required=required,
        issued_at="2026-08-31T15:50:00.000Z",
        expires_at="2026-08-31T21:50:00.000Z",
    )
    with pytest.raises(ValueError, match="01:00 JST"):
        support.verify_live_acquisition(
            before_fixture, service=before, required=required
        )

    after = _service(
        receipt_ed25519_keys, clock=lambda: "2026-09-01T01:00:00+09:00"
    )
    after_fixture = support.build_live_acquisition(
        tmp_path=tmp_path / "after",
        service=after,
        required=required,
        issued_at="2026-08-31T15:50:00.000Z",
        expires_at="2026-08-31T21:50:00.000Z",
    )
    assert support.verify_live_acquisition(
        after_fixture, service=after, required=required
    )
