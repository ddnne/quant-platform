"""Sticky COMPLETE must survive segment_end day-roll when eligible SUCCESS exists."""

from __future__ import annotations

from storage.coverage_ledger import (
    CollectionReceipt,
    RequiredCoverageSegment,
    _latest_eligible_success_for_segment_id,
    is_complete_eligible_receipt,
)


def _signed_success(
    *,
    dataset: str,
    segment_id: str,
    start: str,
    end: str,
    run_id: int,
) -> CollectionReceipt:
    # Minimal shape; eligibility mocked via digests + monkeypatch if needed.
    return CollectionReceipt(
        source="jquants",
        dataset=dataset,
        segment_id=segment_id,
        segment_start=start,
        segment_end=end,
        expected_scope={"segment_start": start, "segment_end": end},
        expected_items=1,
        observed_items=1,
        raw_page_count=1,
        raw_row_count=1,
        structured_row_count=1,
        pagination_exhausted=True,
        digests={
            "eligibility": "TRUSTED_COLLECTION",
            "raw": "sha256:dead",
            "signature": "sig",
            "public_key_id": "dev-receipt-v1",
        },
        run_id=run_id,
        status="SUCCESS",
        error=None,
        checked_at="2026-08-12T00:00:00+00:00",
    )


def test_segment_id_fallback_finds_eligible_despite_end_drift(monkeypatch):
    from storage import coverage_ledger as cl

    monkeypatch.setattr(cl, "is_complete_eligible_receipt", lambda r: r.status == "SUCCESS")
    old = _signed_success(
        dataset="markets_calendar",
        segment_id="2026-08",
        start="2026-08-01",
        end="2026-08-11",
        run_id=10,
    )
    found = _latest_eligible_success_for_segment_id(
        [old],
        source="jquants",
        dataset="markets_calendar",
        segment_id="2026-08",
    )
    assert found is not None
    assert found.run_id == 10
    assert found.segment_end == "2026-08-11"
