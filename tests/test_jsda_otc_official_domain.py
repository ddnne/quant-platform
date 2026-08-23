"""JSDA OTC required set is official index listed days, not calendar 8784.

Listed days parse in ingestion.jsda.official_index; ledger re-exports.
Planner and refresh take that set. Missing index text is fail-closed empty
(UNKNOWN/PARTIAL), not a calendar walk or inventory replay.
Does not COMPLETE weekends or PARSE_ZERO days. Does not fetch live HTML.
"""

from __future__ import annotations

from datetime import date, timedelta
import json
from pathlib import Path

import pytest

from data_contracts.coverage import SEGMENT_GRANULARITIES, coverage_contract_for
from data_contracts.permanent_defer import PERMANENT_DEFER_DATASETS, PERMANENT_DEFER_IDS
from data_contracts.source_capability import (
    SourceCapabilityContract,
    required_domain_subset_official,
    source_capability_contract_for,
)
from ingestion.jsda.official_index import (
    official_index_days as sot_official_index_days,
    parse_official_index_publication_days,
    read_local_index_text,
)
from ingestion.jsda.urls import discover_otc_reference_segments
from qp_paths import repo_root
from storage.coverage_ledger import (
    RequiredCoverageSegment,
    evaluate_segment,
    official_index_days,
    plan_required_segments,
    read_coverage_segments,
    record_required_segments,
    refresh_coverage_ledger,
)
from storage.sqlite_store import SqliteStore

_REPO = repo_root()
_CAPABILITY = _REPO / "specs" / "source_capability" / "jsda_otc_bond_reference_prices.json"
_MIGRATION = _REPO / "specs" / "coverage_v3" / "jsda_otc_official_index_migration.json"
_FIXTURE = _REPO / "tests" / "fixtures" / "jsda_otc_official_index_tiny.html"

DATASET = "jsda_otc_bond_reference_prices"
OFFICIAL_START = "2002-08-02"
OFFICIAL_EVIDENCE_URL = (
    "https://market.jsda.or.jp/shijyo/saiken/baibai/baisanchi/index.html"
)
PARSE_ZERO_DAYS = ("2002-08-02", "2002-08-05")
V2_TARGET_END = "2026-08-19"
V2_REQUIRED = 8784
V2_COMPLETE = 5886
V2_PARTIAL = 2898
EXCLUDED_STATUS = "excluded_not_in_official_index"
WEEKEND_IN_TINY_SPAN = "2002-08-03"
LISTED_TINY_DAYS = ("2002-08-02", "2002-08-05", "2002-08-06")


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _listed_index_days(html: str, *, year: int = 2002) -> list[str]:
    segments = discover_otc_reference_segments(html, year=year)
    return [item.segment_id for item in segments]


def _calendar_days(start: str, end: str) -> list[str]:
    cursor = date.fromisoformat(start)
    last = date.fromisoformat(end)
    out: list[str] = []
    while cursor <= last:
        out.append(cursor.isoformat())
        cursor += timedelta(days=1)
    return out


def test_capability_official_archive_index_not_tip_only() -> None:
    cap = _load(_CAPABILITY)
    mig = _load(_MIGRATION)
    assert cap["dataset_id"] == DATASET
    assert cap["policy_version"] == "source-capability/v3"
    assert cap["history_mode"] == "official_archive_index"
    assert cap["earliest_official_availability"] == OFFICIAL_START
    assert cap["official_evidence_url"] == OFFICIAL_EVIDENCE_URL
    assert cap["historical_research_eligible"] is True
    assert cap["tip_only_operational"] is False
    assert cap["research_profile_eligibility"]["dataset_complete_claim"] is False
    assert cap["research_profile_eligibility"]["tip_only"] is False
    assert mig["after"]["historical_research_eligible"] is True
    assert mig["after"]["tip_only_operational"] is False
    assert mig["after"]["history_mode"] == "official_archive_index"


def test_required_set_is_official_index_days_not_calendar_8784() -> None:
    cap = _load(_CAPABILITY)
    mig = _load(_MIGRATION)
    assert mig["before"]["required_segments"] == V2_REQUIRED
    assert mig["before"]["complete_segments"] == V2_COMPLETE
    assert mig["before"]["partial_segments"] == V2_PARTIAL
    assert mig["before"]["required_segments"] == (
        mig["before"]["complete_segments"] + mig["before"]["partial_segments"]
    )
    required_set = mig["after"]["required_set"]
    assert required_set["count_rule"] == "official_index_listed_days_only"
    assert required_set["expand_calendar_days"] is False
    assert required_set["include_weekends"] is False
    assert required_set["publication_days_only"] is True
    assert required_set["not_calendar_day_count"] == V2_REQUIRED
    assert required_set["grain"] == "official_archive_index_day"
    assert cap["collection_window"]["grain"] == "official_archive_index_day"
    assert cap["collection_window"]["grain"] != "official_archive_day"
    assert cap["collection_window"]["expand_calendar_days"] is False
    assert cap["publication_calendar"]["required_days"] == (
        "official_index_listed_days_only"
    )


def test_tiny_offline_index_lists_three_dates_and_excludes_weekend() -> None:
    html = _FIXTURE.read_text(encoding="utf-8")
    listed = _listed_index_days(html)
    assert listed == list(LISTED_TINY_DAYS)
    assert len(listed) == 3
    calendar = _calendar_days("2002-08-02", "2002-08-06")
    assert len(calendar) == 5
    assert WEEKEND_IN_TINY_SPAN in calendar
    assert WEEKEND_IN_TINY_SPAN not in listed
    assert date.fromisoformat(WEEKEND_IN_TINY_SPAN).weekday() >= 5
    overhang = [day for day in calendar if day not in listed]
    assert overhang == ["2002-08-03", "2002-08-04"]
    assert all(date.fromisoformat(day).weekday() >= 5 for day in overhang)
    assert "https://" not in html


def test_calendar_overhang_2898_is_not_converted_to_complete() -> None:
    mig = _load(_MIGRATION)
    overhang = mig["old_new_required_segment_mapping"]["calendar_overhang_excluded"]
    assert overhang["v2_partial_segments"] == V2_PARTIAL
    assert overhang["converted_to_complete"] is False
    assert overhang["v3_status"] == EXCLUDED_STATUS
    assert overhang["v3_status"] != "COMPLETE"
    assert overhang["empty_complete"] is False
    assert overhang["weekend_empty_complete"] == "FORBIDDEN"
    assert mig["weekend_empty_complete"] == "FORBIDDEN"
    assert mig["invent_complete"] is False
    assert mig["empty_complete_forbidden"] is True


def test_parse_zero_2002_08_02_and_05_remain_genuine_gaps() -> None:
    mig = _load(_MIGRATION)
    gaps = mig["old_new_required_segment_mapping"]["genuine_parse_zero_gaps"]
    ids = [row["segment_id"] for row in gaps]
    assert ids == list(PARSE_ZERO_DAYS)
    for row in gaps:
        assert row["raw_exists"] is True
        assert row["column_count"] == 23
        assert row["parser_min_columns"] == 29
        assert row["outcome"] == "PARSE_ZERO"
        assert row["v2_status"] == "PARTIAL"
        assert row["v3_status"] == "stay_PARTIAL"
        assert row["v3_status"] != "COMPLETE"
        assert row["invent_complete"] is False
    remaining = mig["remaining_genuine_gaps"]
    assert remaining["items"] == list(PARSE_ZERO_DAYS)
    assert remaining["classification"] == "stay_PARTIAL"
    assert remaining["dataset_complete_claim"] is False
    assert remaining["parse_zero_invent_complete"] == "FORBIDDEN"
    assert mig["parse_zero_invent_complete"] == "FORBIDDEN"
    assert mig["after"]["history_target_start"] == OFFICIAL_START
    assert mig["behavior_change"]["history_target_start"] == OFFICIAL_START


def test_5886_complete_days_map_into_required_set_not_recomplete() -> None:
    mig = _load(_MIGRATION)
    mapped = mig["old_new_required_segment_mapping"]["mapped_existing_complete"]
    assert mapped["count"] == V2_COMPLETE
    assert mapped["v2_status"] == "COMPLETE"
    assert mapped["v3_action"] == "map_into_required_set"
    assert mapped["re_complete"] is False
    assert mapped["not_re_complete"] is True
    assert mig["behavior_change"]["mapped_complete_not_recomplete"] is True
    assert mig["invent_complete"] is False
    assert mig["dataset_complete_claim"] is False


def test_read_local_index_text_fail_closed_empty(tmp_path: Path) -> None:
    assert read_local_index_text(None) is None
    assert read_local_index_text("") is None
    assert read_local_index_text("   ") is None
    blank = tmp_path / "blank.html"
    blank.write_text("   \n", encoding="utf-8")
    assert read_local_index_text(blank) is None
    missing = tmp_path / "no_such_official_index.html"
    assert not missing.exists()
    with pytest.raises(FileNotFoundError):
        read_local_index_text(missing)
    assert read_local_index_text(missing, missing_ok=True) is None
    html = read_local_index_text(_FIXTURE)
    assert html is not None
    assert html.strip() != ""
    assert "https://" not in html
    assert "2002.8.2" in html
    listed = parse_official_index_publication_days(html)
    assert listed == LISTED_TINY_DAYS
    assert WEEKEND_IN_TINY_SPAN not in listed
    assert len(listed) != V2_REQUIRED
    assert "COMPLETE" not in listed


def test_official_index_days_fail_closed_without_index_text() -> None:
    assert official_index_days(DATASET, None) == ()
    assert official_index_days(DATASET, "") == ()
    assert official_index_days(DATASET, "   ") == ()
    html = _FIXTURE.read_text(encoding="utf-8")
    assert official_index_days("equities_master", html) == ()


def test_official_index_html_parser_is_one_sot() -> None:
    assert official_index_days is sot_official_index_days
    html = _FIXTURE.read_text(encoding="utf-8")
    assert "https://" not in html
    listed = parse_official_index_publication_days(html)
    assert listed == LISTED_TINY_DAYS
    assert listed == official_index_days(DATASET, html)
    assert WEEKEND_IN_TINY_SPAN not in listed
    assert parse_official_index_publication_days(None) == ()
    assert parse_official_index_publication_days("") == ()
    assert parse_official_index_publication_days("   ") == ()
    assert parse_official_index_publication_days("no publication dates") == ()
    calendar = _calendar_days("2002-08-02", "2002-08-06")
    assert len(calendar) == 5
    assert len(listed) == 3
    assert len(listed) != V2_REQUIRED


def test_official_index_days_tiny_fixture_lists_publication_days_only() -> None:
    html = _FIXTURE.read_text(encoding="utf-8")
    listed = official_index_days(DATASET, html)
    assert listed == LISTED_TINY_DAYS
    assert WEEKEND_IN_TINY_SPAN not in listed
    calendar = _calendar_days("2002-08-02", "2002-08-06")
    assert len(calendar) == 5
    assert len(listed) == 3
    assert len(listed) != V2_REQUIRED


def test_plan_required_segments_fail_closed_without_index_text() -> None:
    policy = coverage_contract_for(DATASET)
    assert policy.coverage_mode == "official_archive_index_reconciled"
    planned = plan_required_segments(policy, V2_TARGET_END, source="jsda")
    assert planned == ()
    assert len(planned) != V2_REQUIRED
    mig = _load(_MIGRATION)
    assert mig["before"]["required_segments"] == V2_REQUIRED
    assert mig["after"]["required_set"]["expand_calendar_days"] is False
    assert mig["behavior_change"]["required_calendar_days"] is False


def test_plan_required_segments_uses_official_index_not_calendar() -> None:
    policy = coverage_contract_for(DATASET)
    assert policy.segment_granularity == "official_archive_index_day"
    assert "official_archive_index_day" in SEGMENT_GRANULARITIES
    html = _FIXTURE.read_text(encoding="utf-8")
    planned = plan_required_segments(
        policy, "2002-08-06", source="jsda", index_text=html,
    )
    ids = [seg.segment_id for seg in planned]
    calendar = _calendar_days("2002-08-02", "2002-08-06")
    assert ids == list(LISTED_TINY_DAYS)
    assert WEEKEND_IN_TINY_SPAN not in ids
    assert len(ids) != len(calendar)
    assert len(ids) != V2_REQUIRED
    for day in PARSE_ZERO_DAYS:
        assert day in ids
    for seg in planned:
        assert seg.expected_scope["segment_granularity"] == (
            "official_archive_index_day"
        )


def test_plan_required_segments_clips_index_days_to_window() -> None:
    policy = coverage_contract_for(DATASET)
    html = _FIXTURE.read_text(encoding="utf-8")
    planned = plan_required_segments(
        policy, "2002-08-05", source="jsda", index_text=html,
    )
    assert [seg.segment_id for seg in planned] == ["2002-08-02", "2002-08-05"]


def test_weekend_and_parse_zero_are_not_invented_complete() -> None:
    policy = coverage_contract_for(DATASET)
    html = _FIXTURE.read_text(encoding="utf-8")
    planned = plan_required_segments(
        policy, "2002-08-06", source="jsda", index_text=html,
    )
    ids = {seg.segment_id for seg in planned}
    assert WEEKEND_IN_TINY_SPAN not in ids
    for day in PARSE_ZERO_DAYS:
        required = next(seg for seg in planned if seg.segment_id == day)
        status, _detail = evaluate_segment(policy, required, None)
        assert status == "PARTIAL"
        assert status != "COMPLETE"


def _calendar_inventory_segments(days: tuple[str, ...] | list[str]) -> list[RequiredCoverageSegment]:
    policy = coverage_contract_for(DATASET)
    segments: list[RequiredCoverageSegment] = []
    for day_s in days:
        day = date.fromisoformat(day_s)
        segments.append(RequiredCoverageSegment(
            source="jsda",
            dataset=DATASET,
            segment_id=day_s,
            segment_start=day_s,
            segment_end=day_s,
            expected_scope={
                "coverage_mode": policy.coverage_mode,
                "expected_frequency": policy.expected_frequency,
                "expected_item_unit": "source_query",
                "segment_end": day.isoformat(),
                "segment_start": day.isoformat(),
                "universe_rule": policy.universe_rule,
                "segment_granularity": policy.segment_granularity,
            },
            expected_items=1,
        ))
    return segments


def test_refresh_does_not_rerequire_weekend_absent_from_official_index(
    tmp_path: Path,
) -> None:
    html = _FIXTURE.read_text(encoding="utf-8")
    calendar = _calendar_days("2002-08-02", "2002-08-06")
    assert WEEKEND_IN_TINY_SPAN in calendar
    assert len(calendar) != V2_REQUIRED
    db = tmp_path / "otc-refresh-index.sqlite"
    store = SqliteStore(db)
    record_required_segments(store._conn, _calendar_inventory_segments(calendar))
    store._conn.execute(
        "UPDATE coverage_segments SET status='COMPLETE' "
        "WHERE dataset=? AND segment_id=?",
        (DATASET, WEEKEND_IN_TINY_SPAN),
    )
    store._conn.commit()
    before = {
        row["segment_id"] for row in read_coverage_segments(db, dataset=DATASET)
    }
    assert WEEKEND_IN_TINY_SPAN in before
    rows = refresh_coverage_ledger(
        store._conn,
        db,
        datasets=(DATASET,),
        today=V2_TARGET_END,
        index_text=html,
    )
    after = read_coverage_segments(db, dataset=DATASET)
    ids = [row["segment_id"] for row in after]
    assert ids == list(LISTED_TINY_DAYS)
    assert WEEKEND_IN_TINY_SPAN not in ids
    assert len(ids) != V2_REQUIRED
    assert len(ids) != len(calendar)
    for day in PARSE_ZERO_DAYS:
        row = next(item for item in after if item["segment_id"] == day)
        assert row["status"] == "PARTIAL"
        assert row["status"] != "COMPLETE"
    assert all(row["status"] != "COMPLETE" for row in after)
    assert rows[0]["status"] != "COMPLETE"
    store.close()


def test_refresh_without_index_text_is_fail_closed_empty_not_calendar(
    tmp_path: Path,
) -> None:
    calendar = _calendar_days("2002-08-02", "2002-08-06")
    db = tmp_path / "otc-refresh-empty.sqlite"
    store = SqliteStore(db)
    record_required_segments(store._conn, _calendar_inventory_segments(calendar))
    store._conn.commit()
    for blank in (None, "", "   "):
        rows = refresh_coverage_ledger(
            store._conn,
            db,
            datasets=(DATASET,),
            today=V2_TARGET_END,
            index_text=blank,
        )
        ids = [
            row["segment_id"]
            for row in read_coverage_segments(db, dataset=DATASET)
        ]
        assert ids == []
        assert WEEKEND_IN_TINY_SPAN not in ids
        assert len(ids) != V2_REQUIRED
        assert rows[0]["status"] != "COMPLETE"
        detail = json.loads(rows[0]["detail_json"])
        assert detail["coverage_v2"]["required_segments"] == 0
        assert detail["coverage_v2"]["required_segments"] != V2_REQUIRED
    store.close()


def test_v2_coverage_floor_not_rewritten_here() -> None:
    v2 = coverage_contract_for(DATASET)
    assert v2.history_target_start == OFFICIAL_START
    assert v2.coverage_mode == "official_archive_index_reconciled"
    assert v2.segment_granularity == "official_archive_index_day"
    assert v2.segment_granularity in SEGMENT_GRANULARITIES
    cap = _load(_CAPABILITY)
    assert cap["earliest_official_availability"] == OFFICIAL_START
    assert cap["official_evidence_url"] == OFFICIAL_EVIDENCE_URL
    mig = _load(_MIGRATION)
    assert mig["official_evidence"]["url"] == OFFICIAL_EVIDENCE_URL
    assert mig["official_evidence"]["do_not_raise_floor_to_hide_parse_zero"] is True
    assert DATASET in PERMANENT_DEFER_DATASETS
    assert PERMANENT_DEFER_IDS[DATASET] == "PD-D5-JSDA-OTC"


def test_capability_validates_against_v3_loader() -> None:
    cap = _load(_CAPABILITY)
    contract = SourceCapabilityContract.from_dict(cap)
    assert contract.dataset_id == DATASET
    assert contract.history_mode == "official_archive_index"
    assert contract.historical_research_eligible is True
    assert contract.tip_only_operational is False
    assert contract.official_evidence_url == OFFICIAL_EVIDENCE_URL
    domain = required_domain_subset_official(contract)
    assert domain.publication_days_only is True
    assert domain.admit_historical_required_segments is True
    assert domain.collection_window_grain == "official_archive_index_day"
    loaded = source_capability_contract_for(DATASET)
    assert loaded.history_mode == "official_archive_index"
    assert loaded.tip_only_operational is False
