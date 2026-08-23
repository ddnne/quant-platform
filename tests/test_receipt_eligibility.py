"""Signed receipt boundary: only Ed25519-verified receipts can COMPLETE."""
from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace

from data_contracts import coverage_contract_for
from storage.coverage_ledger import (
    build_collection_receipt,
    evaluate_segment,
    plan_required_segments,
)
from storage.trusted_receipt import SignedReceiptAuthority


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


def _authority(keys: SimpleNamespace) -> SignedReceiptAuthority:
    return SignedReceiptAuthority(signing_key=keys.signing_key)


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
    receipt = auth.issue(
        required=req,
        run_id=1,
        raw=raw,
        observed_items=1,
        structured_row_count=1,
        raw_row_count=1,
    )
    assert receipt.digests["signature"].startswith("ed25519:")
    status, detail = evaluate_segment(policy, req, receipt)
    assert status == "COMPLETE", detail
