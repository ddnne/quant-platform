"""Signed receipt boundary: only Ed25519-verified receipts can COMPLETE."""
from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace

from data_contracts import coverage_contract_for
from tests.receipt_test_support import (
    _SignedReceiptAuthority,
    _reconcile_collection_evidence,
)
from storage.coverage_ledger import (
    build_collection_receipt,
    evaluate_segment,
    is_complete_eligible_receipt,
    plan_required_segments,
)


def _month_required():
    policy = replace(
        coverage_contract_for("markets_calendar"),
        history_target_start="2025-01-01",
    )
    return policy, plan_required_segments(
        policy,
        "2025-01-31",
        expected_items_by_segment={"2025-01": 1},
    )[0]


def _authority(keys: SimpleNamespace) -> _SignedReceiptAuthority:
    return _SignedReceiptAuthority(signing_key=keys.signing_key)


def _issue(authority, required, raw, records):
    evidence = _reconcile_collection_evidence(
        required=required,
        run_id=1,
        raw_pages=(raw,),
        raw_records=records,
        structured_records=records,
        checked_at="2025-02-01T00:00:00+00:00",
    )
    return authority.issue(evidence)


def test_recovered_raw_only_cannot_complete():
    policy, req = _month_required()
    raw = b'{"data":[{"Date":"2025-01-01"}]}'
    receipt = build_collection_receipt(
        required=req,
        run_id=1,
        raw=raw,
        observed_items=1,
        structured_row_count=1,
        raw_row_count=1,
        extra_digests={
            "eligibility": "RECOVERED_RAW_ONLY",
            "origin": "recovered-raw-only",
        },
    )
    status, detail = evaluate_segment(policy, req, receipt)
    assert status == "PARTIAL"


def test_string_issuer_cannot_complete():
    policy, req = _month_required()
    raw = b'{"data":[{"Date":"2025-01-01"}]}'
    receipt = build_collection_receipt(
        required=req,
        run_id=1,
        raw=raw,
        observed_items=1,
        structured_row_count=1,
        raw_row_count=1,
        extra_digests={
            "eligibility": "TRUSTED_COLLECTION",
            "issuer_class": "TrustedReceiptIssuer",
            "issuer_id": "forged",
        },
    )
    assert receipt.digests.get("eligibility") == "RECOVERED_RAW_ONLY"
    status, _ = evaluate_segment(policy, req, receipt)
    assert status == "PARTIAL"


def test_signed_receipt_can_complete(receipt_ed25519_keys: SimpleNamespace):
    policy, req = _month_required()
    raw = b'{"data":[{"Date":"2025-01-01"}]}'
    auth = _authority(receipt_ed25519_keys)
    receipt = _issue(auth, req, raw, [{"Date": "2025-01-01"}])
    assert receipt.digests["signature"].startswith("ed25519:")
    status, detail = evaluate_segment(policy, req, receipt)
    assert status == "COMPLETE", detail


def test_signed_empty_data_envelope_is_not_complete(
    receipt_ed25519_keys: SimpleNamespace,
) -> None:
    """Signed SUCCESS over ``{"data":[]}`` is PARTIAL, not Coverage COMPLETE."""
    policy, req = _month_required()
    raw = b'{"data":[]}'
    auth = _authority(receipt_ed25519_keys)
    import pytest

    with pytest.raises(ValueError, match="zero-row SUCCESS"):
        _issue(auth, req, raw, [])
