"""equities_master official domain starts 2008-05-07 (coverage v3).

Not a Dataset COMPLETE claim. V2 collection_coverage.json is unwired.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from data_contracts.coverage import coverage_contract_for
from data_contracts.permanent_defer import (
    MASTER_JQ_SCOPE,
    PERMANENT_DEFER_DATASETS,
    PERMANENT_DEFER_IDS,
)

_REPO = Path(__file__).resolve().parents[1]
_CAPABILITY = _REPO / "specs" / "source_capability" / "equities_master.json"
_MIGRATION = _REPO / "specs" / "coverage_v3" / "equities_master_migration.json"

OFFICIAL_START = "2008-05-07"
OFFICIAL_START_MONTH = "2008-05"
NOT_REQUIRED_START = "2006-08-13"
EXCLUDED_STATUS = "excluded_official_unavailable"


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


OLD_MISDATE_MONTHS = _month_ids(date(2006, 8, 1), date(2008, 4, 1))


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_capability_required_start_is_official_provision_date():
    cap = _load(_CAPABILITY)
    assert cap["dataset_id"] == "equities_master"
    assert cap["policy_version"] == "source-capability/v3"
    assert cap["history_mode"] == "bounded_history"
    assert cap["earliest_official_availability"] == OFFICIAL_START
    assert cap["official_evidence_url"] == "https://jpx-jquants.com/en/spec/eq-master"
    assert cap["collection_window"]["required_domain_start"] == OFFICIAL_START
    assert cap["historical_research_eligible"] is True
    assert cap["tip_only_operational"] is False
    assert cap["research_profile_eligibility"]["dataset_complete_claim"] is False


def test_2006_08_is_not_historical_required_start():
    cap = _load(_CAPABILITY)
    entitlement = cap["entitlement_semantics"]
    assert entitlement["not_historical_required_start"] == NOT_REQUIRED_START
    assert entitlement["subscription_floor_is_not_historical_required_start"] is True
    assert entitlement["official_data_provision_start"] == OFFICIAL_START
    assert cap["earliest_official_availability"] != NOT_REQUIRED_START
    assert cap["collection_window"]["required_segment_start_month"] != "2006-08"


def test_monthly_segments_start_2008_05():
    cap = _load(_CAPABILITY)
    mig = _load(_MIGRATION)
    assert cap["collection_window"]["grain"] == "calendar_month"
    assert cap["collection_window"]["required_segment_start_month"] == OFFICIAL_START_MONTH
    assert mig["after"]["required_segment_start_month"] == OFFICIAL_START_MONTH
    assert mig["behavior_change"]["monthly_segments_start"] == OFFICIAL_START_MONTH
    assert month_in_required_domain("2006-08", cap) is False
    assert month_in_required_domain("2008-04", cap) is False
    assert month_in_required_domain("2008-05", cap) is True


def test_pit_history_starts_2008_05_07():
    cap = _load(_CAPABILITY)
    mig = _load(_MIGRATION)
    assert cap["collection_window"]["pit_history_start"] == OFFICIAL_START
    assert cap["research_profile_eligibility"]["pit_history_start"] == OFFICIAL_START
    assert mig["after"]["pit_history_start"] == OFFICIAL_START


def test_pre_official_queries_clamp_not_missing_backfill():
    cap = _load(_CAPABILITY)
    clamp = cap["collection_window"]["query_before_official_start"]
    assert clamp["behavior"] == "clamp_to_earliest_official_availability"
    assert clamp["clamped_date"] == OFFICIAL_START
    assert clamp["classification"] == "vendor_misdate_clamp"
    assert clamp["not_missing_backfill"] is True
    assert apply_official_query_clamp("2006-08-13", cap) == OFFICIAL_START
    assert apply_official_query_clamp("2008-04-30", cap) == OFFICIAL_START
    assert apply_official_query_clamp("2008-05-07", cap) == OFFICIAL_START
    assert apply_official_query_clamp("2008-05-08", cap) == "2008-05-08"


def test_migration_excludes_21_old_partial_months_as_official_unavailable():
    mig = _load(_MIGRATION)
    assert mig["dataset_id"] == "equities_master"
    assert mig["kind"] == "official_domain_correction"
    assert mig["invent_complete"] is False
    assert mig["dataset_complete_claim"] is False
    assert mig["official_evidence"]["vendor_data_provision_start"] == OFFICIAL_START
    assert mig["official_evidence"]["url"] == "https://jpx-jquants.com/en/spec/eq-master"
    assert mig["before"]["history_target_start"] == NOT_REQUIRED_START
    assert mig["after"]["history_target_start"] == OFFICIAL_START
    assert mig["after"]["not_historical_required_start"] == NOT_REQUIRED_START

    mapping = mig["old_new_required_segment_mapping"]["excluded_official_unavailable"]
    ids = [row["segment_id"] for row in mapping]
    assert ids == OLD_MISDATE_MONTHS
    assert len(ids) == 21
    assert "2006-08" in ids
    assert "2008-04" in ids
    assert "2008-05" not in ids
    for row in mapping:
        assert row["v2_status"] == "PARTIAL"
        assert row["v3_status"] == EXCLUDED_STATUS
        assert row["v3_status"] != "COMPLETE"

    assert mig["before"]["partial_months"] == OLD_MISDATE_MONTHS
    assert mapping[0]["v3_status"] != "COMPLETE"
    assert "COMPLETE" not in {row["v3_status"] for row in mapping}


def test_remaining_genuine_gaps_stay_partial_no_dataset_complete():
    cap = _load(_CAPABILITY)
    mig = _load(_MIGRATION)
    gaps = mig["remaining_genuine_gaps"]
    assert gaps["classification"] == "stay_PARTIAL"
    assert gaps["dataset_complete_claim"] is False
    assert gaps["excluded_misdate_months_are_not_gaps"] is True
    assert cap["research_profile_eligibility"]["dataset_complete_claim"] is False
    assert mig["dataset_complete_claim"] is False
    assert mig["invent_complete"] is False


def test_v2_coverage_floor_not_rewritten_here():
    """collection_coverage.json stays V2 until a later wire; this lane does not invent COMPLETE."""
    v2 = coverage_contract_for("equities_master")
    assert v2.history_target_start == NOT_REQUIRED_START
    assert MASTER_JQ_SCOPE["history_target_start"] == NOT_REQUIRED_START
    assert MASTER_JQ_SCOPE["vendor_data_provision_start"] == OFFICIAL_START
    assert MASTER_JQ_SCOPE["invent_complete_via_floor_to_2008_05"] == "FORBIDDEN"
    assert MASTER_JQ_SCOPE["dataset_complete_invent"] == "FORBIDDEN"


def test_pd_d2_master_defer_retained_reason_records_official_start():
    assert "equities_master" in PERMANENT_DEFER_DATASETS
    assert PERMANENT_DEFER_IDS["equities_master"] == "PD-D2-MASTER"
    bands = MASTER_JQ_SCOPE["bands"]
    assert isinstance(bands, dict)
    assert bands["MISDATE"]["coverage"] == "REQUIRED_PARTIAL"  # V2 inventory until wire
    reason = str(bands["MISDATE"]["reason"])
    assert OFFICIAL_START in reason
    assert EXCLUDED_STATUS in reason
    assert "not COMPLETE" in reason
    assert "Do not invent Dataset COMPLETE" in reason
    assert MASTER_JQ_SCOPE["dataset_complete_invent"] == "FORBIDDEN"


def apply_official_query_clamp(query_date: str, cap: dict) -> str:
    start = str(cap["earliest_official_availability"])
    if query_date < start:
        clamp = cap["collection_window"]["query_before_official_start"]
        assert clamp["not_missing_backfill"] is True
        return str(clamp["clamped_date"])
    return query_date


def month_in_required_domain(month: str, cap: dict) -> bool:
    start_month = str(cap["collection_window"]["required_segment_start_month"])
    return month >= start_month
