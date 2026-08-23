"""equities_bars_daily_am is a same-day AM snapshot, not 32 months of history.

V3 planner does not require 2024-01.. months as historical COMPLETE.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from data_contracts.coverage import coverage_contract_for
from data_contracts.permanent_defer import TIP_ONLY_POLICY
from storage.coverage_ledger import evaluate_segment, plan_required_segments

_REPO = Path(__file__).resolve().parents[1]
_CAPABILITY = _REPO / "specs" / "source_capability" / "equities_bars_daily_am.json"
_MIGRATION = _REPO / "specs" / "coverage_v3" / "equities_bars_daily_am_migration.json"

DATASET = "equities_bars_daily_am"
SUBSTITUTE = "equities_bars_daily"
EXCLUDED_STATUS = "excluded_official_unavailable"
FULL_DAY = "equities_bars_daily"


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


V2_REQUIRED_MONTHS = _month_ids(date(2024, 1, 1), date(2026, 8, 1))
V2_PARTIAL_MONTHS = _month_ids(date(2024, 1, 1), date(2026, 7, 1))


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_tip_only_operational_true():
    cap = _load(_CAPABILITY)
    mig = _load(_MIGRATION)
    assert cap["dataset_id"] == DATASET
    assert cap["policy_version"] == "source-capability/v3"
    assert cap["tip_only_operational"] is True
    assert cap["historical_research_eligible"] is False
    assert cap["history_mode"] == "recent_snapshot"
    assert mig["after"]["tip_only_operational"] is True
    assert TIP_ONLY_POLICY[DATASET]["mode"] == "tip_continuous"


def test_32_monthly_historical_segments_not_required():
    mig = _load(_MIGRATION)
    cap = _load(_CAPABILITY)
    assert len(V2_REQUIRED_MONTHS) == 32
    assert mig["before"]["required_segments"] == 32
    assert mig["before"]["required_months"] == V2_REQUIRED_MONTHS
    assert mig["after"]["required_monthly_segments"] == 0
    assert mig["after"]["required_historical_months"] == []
    assert mig["old_new_required_segment_mapping"]["abolished_required_months"] == 32
    assert mig["old_new_required_segment_mapping"]["required_historical_months_after"] == []
    assert cap["collection_window"]["grain"] == "same_trading_day_am_snapshot"
    assert cap["collection_window"]["grain"] != "calendar_month"
    assert V2_REQUIRED_MONTHS[0] == "2024-01"
    assert V2_REQUIRED_MONTHS[-1] == "2026-08"
    for month in V2_REQUIRED_MONTHS:
        assert month not in mig["after"]["required_historical_months"]


def test_sla_1130_1230_jst_present():
    cap = _load(_CAPABILITY)
    sla = cap["freshness_sla"]
    assert sla["expected_after"] == "11:30"
    assert sla["usable_by"] == "12:30"
    assert sla["timezone"] == "Asia/Tokyo"
    assert sla["rule"] == "same_trading_day_am"
    mig_sla = _load(_MIGRATION)["after"]["freshness_sla"]
    assert mig_sla["expected_after"] == "11:30"
    assert mig_sla["usable_by"] == "12:30"
    assert mig_sla["timezone"] == "Asia/Tokyo"
    assert cap["collection_window"]["close"] == "11:30"


def test_historical_substitute_is_equities_bars_daily():
    cap = _load(_CAPABILITY)
    mig = _load(_MIGRATION)
    reason = cap["research_profile_eligibility"]["exclusion_reason"]
    assert SUBSTITUTE in reason
    assert mig["after"]["historical_research_substitute_dataset"] == SUBSTITUTE
    assert mig["behavior_change"]["general_historical_research"] == SUBSTITUTE
    assert cap["dataset_id"] != SUBSTITUTE
    assert cap["upstream_locator"] != "/v2/equities/bars/daily"
    assert "general_historical_research" in cap["research_profile_eligibility"]["exclude_from"]


def test_not_the_same_as_full_day_bars():
    cap = _load(_CAPABILITY)
    mig = _load(_MIGRATION)
    assert cap["dataset_id"] == DATASET
    assert cap["dataset_id"] != FULL_DAY
    assert cap["history_mode"] == "recent_snapshot"
    assert cap["upstream_locator"] == "/v2/equities/bars/daily/am"
    assert mig["after"]["not_same_dataset_as"] == FULL_DAY
    assert mig["behavior_change"]["not_same_as_full_day_bars"] is True
    assert "code" in cap["supported_query_parameters"]
    assert "pagination_key" in cap["supported_query_parameters"]
    assert "from" not in cap["supported_query_parameters"]
    assert "to" not in cap["supported_query_parameters"]
    assert "date" not in cap["supported_query_parameters"]


def test_31_history_months_are_not_empty_complete():
    mig = _load(_MIGRATION)
    excluded = mig["old_new_required_segment_mapping"]["excluded_official_unavailable"]
    ids = [row["segment_id"] for row in excluded]
    assert ids == V2_PARTIAL_MONTHS
    assert len(ids) == 31
    assert "2026-08" not in ids
    for row in excluded:
        assert row["v2_status"] == "PARTIAL"
        assert row["v3_status"] == EXCLUDED_STATUS
        assert row["v3_status"] != "COMPLETE"
        assert row["empty_complete"] is False
    assert mig["empty_complete_forbidden"] is True
    assert mig["invent_complete"] is False
    assert mig["dataset_complete_claim"] is False
    demoted = mig["old_new_required_segment_mapping"]["demoted_monthly_complete_to_snapshot"]
    assert demoted[0]["segment_id"] == "2026-08"
    assert demoted[0]["monthly_historical_required"] is False
    assert demoted[0]["keep_collected_history"] is True


def test_outcome_classes_distinguish_session_and_errors():
    mig = _load(_MIGRATION)
    outcomes = mig["outcome_classes"]
    assert set(outcomes) == {
        "trading_day",
        "holiday",
        "unpublished",
        "api_error",
        "entitlement_error",
    }
    assert outcomes["holiday"].startswith("holiday_")
    assert "not_a_gap" in outcomes["holiday"]
    assert outcomes["unpublished"].startswith("unpublished_")
    assert outcomes["api_error"].startswith("api_error_")
    assert "not_unpublished" in outcomes["api_error"]
    assert outcomes["entitlement_error"].startswith("entitlement_error_")
    assert "not_missing_history" in outcomes["entitlement_error"]
    assert "snapshot" in outcomes["trading_day"]


def test_dedicated_historical_am_profile_uses_stored_periods_only():
    cap = _load(_CAPABILITY)
    mig = _load(_MIGRATION)
    include = cap["research_profile_eligibility"]["include_in"]
    assert "historical_am_stored_only" in include
    assert "ops_same_day_am" in include
    assert "core" in cap["research_profile_eligibility"]["exclude_from"]
    retained = mig["after"]["retained_collected_history"]
    assert retained["action"] == "keep"
    assert retained["grain"] == "actually_stored_periods_only"
    assert retained["invent_fill"] == "FORBIDDEN"
    assert retained["does_not_expand_required_domain"] is True
    assert mig["behavior_change"]["dedicated_historical_am_profile"] == (
        "actually_stored_periods_only"
    )


def test_remaining_gaps_are_not_invented_complete_23():
    mig = _load(_MIGRATION)
    gaps = mig["remaining_genuine_gaps"]
    assert gaps["dataset_complete_claim"] is False
    assert gaps["empty_complete_claim"] is False
    assert gaps["excluded_history_months_are_not_gaps"] is True
    assert mig["invent_complete"] is False
    assert mig["behavior_change"]["dataset_complete_23"] == "FORBIDDEN"
    assert mig["affected_ready_generations"] == []


def test_planner_required_count_is_not_32_months():
    """V3 planner requires the current AM snapshot, not 32 monthly history shells."""
    policy = coverage_contract_for(DATASET)
    assert policy.history_target_start == "2024-01-04"
    assert policy.segment_granularity == "same_trading_day_am_snapshot"
    assert policy.policy_version == "collection-coverage/v3"
    assert policy.history_mode == "recent_snapshot"
    planned = plan_required_segments(policy, "2026-08-14")
    ids = [seg.segment_id for seg in planned]
    assert len(planned) != 32
    assert len(planned) == 1
    assert "2024-01" not in ids
    assert "2026-08" not in ids
    assert planned[0].segment_id == "2026-08-14"
    assert planned[0].expected_scope["segment_granularity"] != "calendar_month"
    sla = planned[0].expected_scope["freshness_sla"]
    assert sla["expected_after"] == "11:30"
    assert sla["usable_by"] == "12:30"
    assert sla["timezone"] == "Asia/Tokyo"
    assert sla["rule"] == "same_trading_day_am"

    cap = _load(_CAPABILITY)
    assert cap["earliest_official_availability"] == "2024-01-04"
    assert cap["official_evidence_url"] == (
        "https://jpx-jquants.com/en/spec/eq-bars-daily-am"
    )
    mig = _load(_MIGRATION)
    assert mig["behavior_change"]["collection_coverage_json"] == "wired_v3_planner"
    assert "For historical data" in mig["official_evidence"]["quote"]
    assert mig["official_evidence"]["history_endpoint"] == "/v2/equities/bars/daily"


def test_empty_receipt_is_partial_not_event_zero_complete():
    """recent_snapshot AM never COMPLETEs from a trusted empty SUCCESS receipt."""
    from tests.test_phase61_coverage_v2 import _receipt

    policy = coverage_contract_for(DATASET)
    assert policy.history_mode == "recent_snapshot"
    assert policy.coverage_mode == "recent_snapshot"
    required = plan_required_segments(policy, "2026-08-14")[0]
    status, detail = evaluate_segment(
        policy, required, _receipt(required, observed=0)
    )
    assert status == "PARTIAL"
    assert status != "COMPLETE"
    assert detail.get("event_zero") is not True
    assert "empty" in detail["reason"]
