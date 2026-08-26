"""equities_master official domain starts 2008-05-07 (coverage v3).

Not a Dataset COMPLETE claim. 2006-08..2008-04 stay excluded_official_unavailable.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from cf_platform.ingest_premium.coverage import EXPECTED_START
from data_contracts.canonical import canonical_dataset_for
from data_contracts.coverage import coverage_contract_for
from data_contracts.permanent_defer import (
    MASTER_JQ_SCOPE,
    PERMANENT_DEFER_DATASETS,
    PERMANENT_DEFER_IDS,
)
from data_contracts.source_capability import (
    apply_official_query_clamp,
    source_capability_contract_for,
    specs_dir,
)
from ops.range_batch_scheduler import TRACK_A_FOCUS_RANGES
from pit import get_equity_master
from storage.coverage_ledger import plan_required_segments
from storage.sqlite_store import SqliteStore

_REPO = Path(__file__).resolve().parents[1]
_CAPABILITY = specs_dir() / "equities_master.json"
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
    contract = source_capability_contract_for("equities_master")
    assert contract.earliest_official_availability == OFFICIAL_START
    assert apply_official_query_clamp("2006-08-13", contract) == OFFICIAL_START
    assert apply_official_query_clamp("2008-04-30", contract) == OFFICIAL_START
    assert apply_official_query_clamp("2008-05-07", contract) == OFFICIAL_START
    assert apply_official_query_clamp("2008-05-08", contract) == "2008-05-08"


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


def test_v3_planner_required_start_is_official_not_entitlement_floor():
    """Official 2008-05-07 is required start; 2006-08..2008-04 stay excluded, not COMPLETE."""
    policy = coverage_contract_for("equities_master")
    assert policy.history_target_start == OFFICIAL_START
    assert policy.policy_version == "collection-coverage/v3"
    planned = plan_required_segments(policy, "2008-06-30")
    ids = [segment.segment_id for segment in planned]
    assert ids == ["2008-05", "2008-06"]
    assert planned[0].segment_start == OFFICIAL_START
    for month in OLD_MISDATE_MONTHS:
        assert month not in ids

    # Entitlement floor remains recorded; it is not historical required start.
    assert MASTER_JQ_SCOPE["history_target_start"] == OFFICIAL_START
    assert MASTER_JQ_SCOPE["not_historical_required_start"] == NOT_REQUIRED_START
    assert MASTER_JQ_SCOPE["vendor_data_provision_start"] == OFFICIAL_START
    assert MASTER_JQ_SCOPE["invent_complete_via_floor_to_2008_05"] == "FORBIDDEN"
    assert MASTER_JQ_SCOPE["dataset_complete_invent"] == "FORBIDDEN"

    mig = _load(_MIGRATION)
    mapping = mig["old_new_required_segment_mapping"]["excluded_official_unavailable"]
    excluded_ids = [row["segment_id"] for row in mapping]
    assert excluded_ids == OLD_MISDATE_MONTHS
    for row in mapping:
        assert row["v3_status"] == EXCLUDED_STATUS
        assert row["v3_status"] != "COMPLETE"


def test_parallel_sot_master_historical_start_is_official_domain():
    """canonical + scheduler + EXPECTED_START align to 2008-05-07.

    2006-08-13 remains the entitlement floor / excluded_official_unavailable
    marker, not historical required start. Not a Dataset COMPLETE claim.
    """
    assert canonical_dataset_for("equities_master").historical_start == OFFICIAL_START
    assert TRACK_A_FOCUS_RANGES["equities_master"][0] == OFFICIAL_START
    assert EXPECTED_START["equities_master"] == OFFICIAL_START
    assert EXPECTED_START["equities_master"] != NOT_REQUIRED_START
    assert TRACK_A_FOCUS_RANGES["equities_master"][0] != NOT_REQUIRED_START

    # V3 tip modes are not EXPECTED_START history floors; dates stay vendor
    # provision starts, not TODAY, and must not densify phantom months.
    assert EXPECTED_START["equities_bars_daily_am"] == "2024-01-04"
    assert EXPECTED_START["equities_earnings_calendar"] == "2010-01-04"

    mapping = _load(_MIGRATION)["old_new_required_segment_mapping"][
        "excluded_official_unavailable"
    ]
    excluded_ids = [row["segment_id"] for row in mapping]
    assert "2006-08" in excluded_ids
    assert excluded_ids == OLD_MISDATE_MONTHS
    for row in mapping:
        assert row["v3_status"] == EXCLUDED_STATUS
        assert row["v3_status"] != "COMPLETE"


def test_pd_d2_master_defer_retained_reason_records_official_start():
    assert "equities_master" in PERMANENT_DEFER_DATASETS
    assert PERMANENT_DEFER_IDS["equities_master"] == "PD-D2-MASTER"
    bands = MASTER_JQ_SCOPE["bands"]
    assert isinstance(bands, dict)
    assert bands["MISDATE"]["coverage"] == EXCLUDED_STATUS
    assert bands["MISDATE"]["densify"] == "FORBIDDEN"
    assert bands["MISDATE"]["seal"] == "FORBIDDEN"
    reason = str(bands["MISDATE"]["reason"])
    assert OFFICIAL_START in reason
    assert EXCLUDED_STATUS in reason
    assert "not REQUIRED_PARTIAL" in reason
    assert "not COMPLETE" in reason
    assert "Do not invent Dataset COMPLETE" in reason
    assert NOT_REQUIRED_START in reason
    assert MASTER_JQ_SCOPE["not_historical_required_start"] == NOT_REQUIRED_START
    assert MASTER_JQ_SCOPE["dataset_complete_invent"] == "FORBIDDEN"


def month_in_required_domain(month: str, cap: dict) -> bool:
    start_month = str(cap["collection_window"]["required_segment_start_month"])
    return month >= start_month


def _master_row(snapshot_date: str, available_at: str, company_name: str) -> dict:
    return {
        "source": "jquants",
        "code": "8697",
        "snapshot_date": snapshot_date,
        "event_time": f"{snapshot_date}T09:00:00+09:00",
        "available_at": available_at,
        "ingested_at": available_at,
        "company_name": company_name,
    }


def test_get_equity_master_excludes_pre_official_keeps_available_at_gate(tmp_path):
    """Official domain floor is 2008-05-07; available_at <= as_of is unchanged."""
    path = tmp_path / "ing.sqlite"
    store = SqliteStore(path)
    store.upsert(
        "jquants_listed_info",
        [
            _master_row(
                "2006-08-13", "2006-08-13T09:00:00+09:00", "misdate"
            ),
            _master_row(
                "2008-04-30", "2008-04-30T09:00:00+09:00", "misdate"
            ),
            _master_row(
                OFFICIAL_START, "2008-05-07T09:00:00+09:00", "official"
            ),
            _master_row(
                "2008-05-08", "2008-05-08T09:00:00+09:00", "later"
            ),
        ],
    )
    store.close()

    late = get_equity_master(
        as_of="2026-08-01T00:00:00+09:00", code="8697", db_path=path
    )
    assert {row["snapshot_date"] for row in late.rows} == {
        OFFICIAL_START,
        "2008-05-08",
    }
    assert late.metadata["as_of"] == "2026-08-01T00:00:00+09:00"

    # Do not rewrite as_of up to official start (would leak 2008 at 2006 as_of).
    pre_official = get_equity_master(
        as_of="2006-08-13T09:00:00+09:00", code="8697", db_path=path
    )
    assert pre_official.rows == []
    assert pre_official.metadata["as_of"] == "2006-08-13T09:00:00+09:00"

    before_pub = get_equity_master(
        as_of="2008-05-07T08:59:59+09:00", code="8697", db_path=path
    )
    assert before_pub.rows == []

    on_official = get_equity_master(
        as_of="2008-05-07T09:00:00+09:00", code="8697", db_path=path
    )
    assert {row["snapshot_date"] for row in on_official.rows} == {OFFICIAL_START}


def test_feature_context_equity_master_pit_path_clamps_pre_official(tmp_path):
    """FeatureContext uses PIT after official start; pre-official rows stay out."""
    from features.runtime import FeatureContext

    path = tmp_path / "ing.sqlite"
    store = SqliteStore(path)
    store.upsert(
        "jquants_listed_info",
        [
            _master_row("2006-08-13", "2026-08-01T00:00:00+09:00", "misdate"),
            _master_row(OFFICIAL_START, "2008-05-07T09:00:00+09:00", "official"),
        ],
    )
    store.close()

    post = FeatureContext(
        as_of="2026-08-01T15:30:00+09:00",
        _input_values={},
        _pit_reader=lambda resource, kwargs: get_equity_master(
            as_of="2026-08-01T15:30:00+09:00", db_path=path, **dict(kwargs)
        ),
    )
    late = post.get_equity_master(code="8697")
    assert {row["snapshot_date"] for row in late.rows} == {OFFICIAL_START}
    assert all(row["available_at"] <= post.as_of for row in late.rows)

    pre = FeatureContext(
        as_of="2006-08-13T09:00:00+09:00",
        _input_values={},
        _pit_reader=lambda resource, kwargs: (_ for _ in ()).throw(
            AssertionError("pre-official FeatureContext must not call PIT")
        ),
    )
    empty = pre.get_equity_master(code="8697")
    assert list(empty) == []
    assert empty.metadata["pd_id"] == "PD-D2-MASTER"


def test_feature_context_jquants_records_master_official_island(tmp_path):
    """get_jquants_records(equities_master) shares get_equity_master island path."""
    from features.runtime import FeatureContext

    path = tmp_path / "ing.sqlite"
    store = SqliteStore(path)
    store.upsert(
        "jquants_listed_info",
        [
            _master_row("2006-08-13", "2026-08-01T00:00:00+09:00", "misdate"),
            _master_row(OFFICIAL_START, "2008-05-07T09:00:00+09:00", "official"),
        ],
    )
    store.close()

    post = FeatureContext(
        as_of="2026-08-01T15:30:00+09:00",
        _input_values={},
        _pit_reader=lambda resource, kwargs: get_equity_master(
            as_of="2026-08-01T15:30:00+09:00", db_path=path, **dict(kwargs)
        ),
    )
    late = post.get_jquants_records(dataset="equities_master", code="8697")
    assert {row["snapshot_date"] for row in late.rows} == {OFFICIAL_START}
    assert all(row["available_at"] <= post.as_of for row in late.rows)

    pre = FeatureContext(
        as_of="2006-08-13T09:00:00+09:00",
        _input_values={},
        _pit_reader=lambda resource, kwargs: (_ for _ in ()).throw(
            AssertionError("pre-official FeatureContext must not call PIT")
        ),
    )
    empty = pre.get_jquants_records(dataset="equities_master", code="8697")
    assert list(empty) == []
    assert empty.metadata["pd_id"] == "PD-D2-MASTER"
    assert empty.metadata["official_start"] == OFFICIAL_START
