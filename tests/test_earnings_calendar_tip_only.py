"""equities_earnings_calendar is a tip snapshot, not 200 monthly history.

V3 planner does not mint empty COMPLETE shells for past months.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from data_contracts.coverage import coverage_contract_for
from qp_paths import repo_root
from storage.coverage_ledger import plan_required_segments

_REPO = repo_root()
_CAPABILITY = _REPO / "specs" / "source_capability" / "equities_earnings_calendar.json"
_MIGRATION = _REPO / "specs" / "coverage_v3" / "equities_earnings_calendar_migration.json"

DATASET = "equities_earnings_calendar"
HISTORY_SUBSTITUTE = "fins_earnings_date"
V2_TARGET_END = "2026-08-14"
V2_START_MONTH = date(2010, 1, 1)
V2_END_MONTH = date(2026, 8, 1)


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _month_ids(start: date, end: date) -> list[str]:
    months: list[str] = []
    year, month = start.year, start.month
    while (year, month) <= (end.year, end.month):
        months.append(f"{year:04d}-{month:02d}")
        month += 1
        if month == 13:
            month = 1
            year += 1
    return months


V2_REQUIRED_MONTHS = _month_ids(V2_START_MONTH, V2_END_MONTH)


def test_historical_research_eligible_is_false() -> None:
    cap = _load(_CAPABILITY)
    mig = _load(_MIGRATION)
    assert cap["dataset_id"] == DATASET
    assert cap["policy_version"] == "source-capability/v3"
    assert cap["history_mode"] == "next_business_day_snapshot"
    assert cap["historical_research_eligible"] is False
    assert cap["tip_only_operational"] is True
    assert mig["after"]["historical_research_eligible"] is False
    assert mig["after"]["tip_only_operational"] is True
    profiles = cap["research_profile_eligibility"]
    assert "historical_research" in profiles["exclude_from"]
    assert "core_historical" in profiles["exclude_from"]
    assert "tip_operational" in profiles["include_in"]


def test_required_set_is_not_200_calendar_months() -> None:
    cap = _load(_CAPABILITY)
    mig = _load(_MIGRATION)
    assert len(V2_REQUIRED_MONTHS) == 200
    assert V2_REQUIRED_MONTHS[0] == "2010-01"
    assert V2_REQUIRED_MONTHS[-1] == "2026-08"

    assert mig["before"]["required_segments"] == 200
    assert mig["before"]["segment_granularity"] == "calendar_month"
    assert mig["before"]["partial_segments"] == 199
    assert cap["collection_window"]["grain"] != "calendar_month"
    assert cap["collection_window"]["grain"] == "collection_cutoff_snapshot"
    assert mig["after"]["segment_granularity"] == "collection_cutoff_snapshot"
    assert mig["after"]["required_calendar_months"] is False
    assert mig["after"]["abolish_monthly_required_from"] == "2010-01"
    assert mig["after"]["evaluate_via"] == [
        "collection_generation",
        "collection_cutoff",
        "freshness_sla",
    ]

    required_set = mig["after"]["required_set"]
    assert required_set["expand_calendar_months"] is False
    assert required_set["not_calendar_month_count"] == 200
    assert required_set["grain"] == "collection_cutoff_snapshot"
    assert required_set["segment_ids"] != V2_REQUIRED_MONTHS
    assert len(required_set["segment_ids"]) != 200
    assert required_set["count_rule"] == "issued_collection_windows_at_cutoff"


def test_planner_required_count_is_not_200_months() -> None:
    """V3 planner yields the current cutoff snapshot, not 200 monthly shells."""
    policy = coverage_contract_for(DATASET)
    assert policy.history_target_start == "2010-01-04"
    assert policy.segment_granularity == "collection_cutoff_snapshot"
    assert policy.policy_version == "collection-coverage/v3"
    assert policy.history_mode == "next_business_day_snapshot"
    planned = plan_required_segments(policy, V2_TARGET_END)
    ids = [seg.segment_id for seg in planned]
    assert ids != V2_REQUIRED_MONTHS
    assert len(planned) != 200
    assert len(planned) == 1
    assert "2010-01" not in ids
    assert planned[0].expected_scope["segment_granularity"] == (
        "collection_cutoff_snapshot"
    )
    assert planned[0].expected_scope["history_mode"] == (
        "next_business_day_snapshot"
    )
    assert planned[0].expected_scope["evaluate_via"] == [
        "collection_generation",
        "collection_cutoff",
        "freshness_sla",
    ]

    mig = _load(_MIGRATION)
    assert mig["before"]["required_segments"] == 200
    assert mig["after"]["required_calendar_months"] is False
    assert len(mig["after"]["required_set"]["segment_ids"]) != 200
    assert mig["behavior_change"]["collection_coverage_json"] == "wired_v3_planner"


def test_fins_earnings_date_is_the_history_substitute() -> None:
    cap = _load(_CAPABILITY)
    mig = _load(_MIGRATION)
    reason = cap["research_profile_eligibility"]["exclusion_reason"]
    assert HISTORY_SUBSTITUTE in reason
    assert mig["after"]["history_substitute_dataset"] == HISTORY_SUBSTITUTE
    assert mig["behavior_change"]["history_substitute_dataset"] == HISTORY_SUBSTITUTE
    substitute = mig["official_evidence"]["history_substitute"]
    assert substitute["dataset_id"] == HISTORY_SUBSTITUTE
    assert substitute["path"] == "/v2/fins/earnings-date"
    assert substitute["url"] == "https://jpx-jquants.com/en/spec/fin-earnings-date"


def test_empty_complete_for_past_200_months_is_forbidden() -> None:
    mig = _load(_MIGRATION)
    assert mig["invent_complete"] is False
    assert mig["dataset_complete_claim"] is False
    assert mig["empty_complete_past_months"] == "FORBIDDEN"
    excluded = mig["old_new_required_segment_mapping"]["excluded_vendor_tip_only"]
    assert excluded["count"] == 199
    assert excluded["v2_status"] == "PARTIAL"
    assert excluded["v3_status"] == "excluded_vendor_tip_only"
    assert excluded["v3_status"] != "COMPLETE"
    assert excluded["not_empty_complete"] is True
    assert excluded["not_source_gap"] is True
    assert mig["old_new_required_segment_mapping"]["retained_tip_snapshot"][
        "empty_complete"
    ] == "FORBIDDEN"
    gaps = mig["remaining_genuine_gaps"]
    assert gaps["items"] == []
    assert gaps["dataset_complete_claim"] is False
    assert gaps["excluded_199_months_are_not_gaps"] is True


def test_official_evidence_is_next_business_day_recent_only() -> None:
    cap = _load(_CAPABILITY)
    mig = _load(_MIGRATION)
    assert cap["official_evidence_url"] == "https://jpx-jquants.com/en/spec/eq-earnings-cal"
    assert cap["supported_query_parameters"] == ["pagination_key"]
    assert cap["freshness_sla"]["expected_after"] == "19:00"
    assert cap["freshness_sla"]["timezone"] == "Asia/Tokyo"
    assert cap["freshness_sla"]["rule"] == "next_business_day_snapshot"
    evidence = mig["official_evidence"]
    assert evidence["plan_data_period"].endswith("Recent data only (all plans)")
    assert any("next business day" in quote for quote in evidence["quotes"])
    assert evidence["query_parameters"] == ["pagination_key"]


def test_capability_validates_against_v3_loader_when_present() -> None:
    cap = _load(_CAPABILITY)
    try:
        from data_contracts.source_capability import (
            SourceCapabilityContract,
            required_domain_subset_official,
        )
    except ImportError:
        pytest.skip("source_capability loader is a parallel lane")
    contract = SourceCapabilityContract.from_dict(cap)
    assert contract.historical_research_eligible is False
    assert contract.tip_only_operational is True
    assert contract.history_mode == "next_business_day_snapshot"
    domain = required_domain_subset_official(contract)
    assert domain.admit_historical_required_segments is False
    assert domain.collection_window_grain == "collection_cutoff_snapshot"
