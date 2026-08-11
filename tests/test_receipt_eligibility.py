"""Trusted receipt boundary: RECOVERED_RAW_ONLY cannot COMPLETE."""
from __future__ import annotations

from dataclasses import replace

from data_contracts import coverage_contract_for
from storage.coverage_ledger import (
    build_collection_receipt,
    evaluate_segment,
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
    assert "trusted" in detail["reason"].lower() or "eligible" in detail["reason"].lower()


def test_trusted_collection_can_complete():
    policy, req = _month_required()
    raw = b'{"data":[{"Date":"2025-01-01"}]}'
    receipt = build_collection_receipt(
        required=req,
        run_id=1,
        raw=raw,
        observed_items=1,
        structured_row_count=1,
        raw_row_count=1,
        # default eligibility TRUSTED_COLLECTION
    )
    status, detail = evaluate_segment(policy, req, receipt)
    assert status == "COMPLETE", detail
