"""Sticky COMPLETE is scope-bound and cannot survive an unsigned day-roll."""

from __future__ import annotations

from data_contracts import coverage_contract_for
from tests.receipt_test_support import (
    _SignedReceiptAuthority,
    _reconcile_collection_evidence,
)
from storage.coverage_ledger import (
    RequiredCoverageSegment,
    _latest_complete_receipt_for_required,
)


def test_segment_id_fallback_rejects_end_drift(receipt_ed25519_keys):
    policy = coverage_contract_for("markets_calendar")
    old_required = RequiredCoverageSegment(
        source="jquants",
        dataset="markets_calendar",
        segment_id="2026-08",
        segment_start="2026-08-01",
        segment_end="2026-08-11",
        expected_scope={
            "segment_start": "2026-08-01",
            "segment_end": "2026-08-11",
            "expected_item_unit": "source_query",
        },
        expected_items=1,
    )
    record = {"Date": "2026-08-11", "HolidayDivision": "1"}
    evidence = _reconcile_collection_evidence(
        required=old_required,
        run_id=10,
        raw_pages=(b'[{"Date":"2026-08-11","HolidayDivision":"1"}]',),
        raw_records=(record,),
        structured_records=(record,),
        checked_at="2026-08-12T00:00:00+00:00",
    )
    old_receipt = _SignedReceiptAuthority(
        signing_key=receipt_ed25519_keys.signing_key
    ).issue(evidence)
    rolled_required = RequiredCoverageSegment(
        source=old_required.source,
        dataset=old_required.dataset,
        segment_id=old_required.segment_id,
        segment_start=old_required.segment_start,
        segment_end="2026-08-12",
        expected_scope={
            **old_required.expected_scope,
            "segment_end": "2026-08-12",
        },
        expected_items=old_required.expected_items,
    )

    assert _latest_complete_receipt_for_required(
        (old_receipt,), policy=policy, required=rolled_required
    ) is None
