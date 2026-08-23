"""Contract-driven BackfillPlanner inventory tests."""

from __future__ import annotations

from ops.backfill_planner import (
    BackfillJob,
    BackfillPlanner,
    inventory_governed_jq_datasets,
    load_premium_endpoint_capabilities,
)


def test_inventory_includes_all_premium_including_fins_details():
    ids = inventory_governed_jq_datasets()
    assert "fins_details" in ids
    assert "markets_calendar" in ids
    # 23 JQ governed (26 total governed minus 3 JSDA)
    assert len(ids) == 23
    caps = load_premium_endpoint_capabilities()
    for ds in ids:
        assert ds in caps, f"missing endpoint capability for {ds}"


def test_planner_emits_jobs_without_handwritten_history():
    plan = BackfillPlanner(cutoff=__import__("datetime").date(2024, 1, 31)).plan()
    assert plan.jobs, "expected at least one pending job from empty coverage"
    datasets = {j.dataset for j in plan.jobs}
    assert "fins_details" in datasets
    assert "markets_calendar" in datasets
    # No JSDA in JQ planner
    assert not any(d.startswith("jsda_") for d in datasets)
    assert plan.contract_digest.startswith("sha256:")


def test_worker_summary_partial_not_pass():
    job = BackfillJob(
        dataset="markets_calendar",
        source="jquants",
        segment_id="2024-01",
        requested_from="2024-01-01",
        requested_to="2024-01-31",
        endpoint_query_mode="range",
        priority=10,
    )
    job.apply_worker_summary({"status": "partial", "passed": 0, "failed": 1}, http_status=200)
    assert job.state == "partial"
    job2 = BackfillJob(
        dataset="x",
        source="jquants",
        segment_id="s",
        requested_from="2024-01-01",
        requested_to="2024-01-02",
        endpoint_query_mode="today",
        priority=1,
    )
    job2.apply_worker_summary({"status": "pass"}, http_status=429)
    assert job2.state == "retry"
    assert job2.reason_code == "http_429"
    job3 = BackfillJob(
        dataset="equities_bars_daily",
        source="jquants",
        segment_id="2008-05",
        requested_from="2008-05-01",
        requested_to="2008-05-31",
        endpoint_query_mode="today",
        priority=30,
    )
    job3.apply_worker_summary(
        {"status": "pass", "passed": 1, "failed": 0, "rowsInserted": 1},
        http_status=200,
    )
    assert job3.state == "pass"
    assert job3.state != "COMPLETE"


def test_planner_dataset_and_range_filter():
    # Post observed floor 2008-05-01 (pre-floor Jan–Apr no longer planned).
    plan = BackfillPlanner(cutoff=__import__("datetime").date(2008, 7, 31)).plan(
        datasets=["indices_bars_daily_topix"],
        from_date="2008-05-01",
        to_date="2008-06-30",
    )
    assert plan.jobs
    assert all(j.dataset == "indices_bars_daily_topix" for j in plan.jobs)
    assert all(j.segment_id in {"2008-05", "2008-06"} for j in plan.jobs)
    # Honest evidence expectation: not auto COMPLETE
    assert all("raw" in j.expected_evidence for j in plan.jobs)


def test_planner_clamps_subscription_floor_no_oos_before_live_floor():
    """Official master domain starts 2008-05-07; 2006-08 is not required.

    Subscription floor remains 2006-08-19 (HTTP 400). MISDATE months
    2006-08..2008-04 are excluded_official_unavailable, not COMPLETE.
    """
    from datetime import date

    from ops.backfill_planner import (
        JQUANTS_SUBSCRIPTION_FLOOR,
        BackfillPlanner,
    )

    assert JQUANTS_SUBSCRIPTION_FLOOR == date(2006, 8, 19)
    oos = BackfillPlanner(
        cutoff=date(2006, 8, 31),
        prefer_month_chunks_for_today=False,
        chunk_days_for_today_mode=1,
    ).plan(
        datasets=["equities_master"],
        from_date="2000-07-13",
        to_date="2006-08-31",
    )
    assert oos.jobs == []

    plan = BackfillPlanner(
        cutoff=date(2008, 5, 31),
        prefer_month_chunks_for_today=False,
        chunk_days_for_today_mode=1,
    ).plan(
        datasets=["equities_master"],
        from_date="2008-05-07",
        to_date="2008-05-31",
    )
    assert plan.jobs, "expected jobs on/after official 2008-05-07"
    assert all(j.requested_from >= "2008-05-07" for j in plan.jobs)
    assert all(j.requested_to >= j.requested_from for j in plan.jobs)
    assert not any(j.requested_from == "2006-08-12" for j in plan.jobs)
    assert not any(j.requested_from == "2006-08-13" for j in plan.jobs)
    assert not any(j.requested_from == "2006-08-18" for j in plan.jobs)


def test_premium_rate_constants_documented():
    from ops.backfill_planner import (
        DATE_RANGE_BATCH_STANDARD,
        PREMIUM_DRIVER_FINS_RPM,
        PREMIUM_DRIVER_GENERAL_RPM,
        PREMIUM_FINS_RPM_CAP,
        PREMIUM_GENERAL_RPM_CAP,
    )

    assert DATE_RANGE_BATCH_STANDARD is True
    assert PREMIUM_DRIVER_GENERAL_RPM <= PREMIUM_GENERAL_RPM_CAP
    assert PREMIUM_DRIVER_FINS_RPM <= PREMIUM_FINS_RPM_CAP
    assert PREMIUM_GENERAL_RPM_CAP == 500
    assert PREMIUM_FINS_RPM_CAP == 500
    # Near-ceiling defaults (P0 rate accel); not a deep safety park under 450.
    assert PREMIUM_DRIVER_GENERAL_RPM >= 495
    assert PREMIUM_DRIVER_FINS_RPM >= 495


def _month_ids(start, end):
    months: list[str] = []
    year, month = start.year, start.month
    while (year, month) <= (end.year, end.month):
        months.append(f"{year:04d}-{month:02d}")
        month += 1
        if month == 13:
            month = 1
            year += 1
    return months


def test_planner_am_snapshot_is_not_32_month_densify():
    """AM bars are a same-day snapshot; V3 required set is not 32 monthly shells."""
    from datetime import date

    cutoff = date(2026, 8, 14)
    plan = BackfillPlanner(cutoff=cutoff).plan(
        datasets=["equities_bars_daily_am"],
    )
    ids = [j.segment_id for j in plan.jobs]
    assert len(plan.jobs) != 32
    assert len(plan.jobs) == 1
    assert "2024-01" not in ids
    assert "2026-08" not in ids
    assert ids == [cutoff.isoformat()]
    assert plan.jobs[0].requested_from == cutoff.isoformat()
    assert plan.jobs[0].requested_to == cutoff.isoformat()


def test_planner_earnings_snapshot_is_not_200_month_densify():
    """Earnings calendar is a next-business-day snapshot, not 200 monthly shells."""
    from datetime import date

    cutoff = date(2026, 8, 14)
    plan = BackfillPlanner(cutoff=cutoff).plan(
        datasets=["equities_earnings_calendar"],
    )
    ids = [j.segment_id for j in plan.jobs]
    assert len(plan.jobs) != 200
    assert len(plan.jobs) == 1
    assert "2010-01" not in ids
    assert ids == [cutoff.isoformat()]
    assert plan.jobs[0].requested_from == cutoff.isoformat()
    assert plan.jobs[0].requested_to == cutoff.isoformat()


def test_planner_master_jobs_exclude_pre_official_months():
    """Official master domain starts 2008-05-07; 2006-08..2008-04 are not jobs.

    JQUANTS_SUBSCRIPTION_FLOOR remains 2006-08-19 entitlement, not domain.
    """
    from datetime import date

    from ops.backfill_planner import JQUANTS_SUBSCRIPTION_FLOOR

    assert JQUANTS_SUBSCRIPTION_FLOOR == date(2006, 8, 19)
    excluded = _month_ids(date(2006, 8, 1), date(2008, 4, 1))
    plan = BackfillPlanner(cutoff=date(2008, 6, 30)).plan(
        datasets=["equities_master"],
        from_date="2006-08-19",
        to_date="2008-06-30",
    )
    months = {j.segment_id for j in plan.jobs}
    assert months.isdisjoint(excluded)
    assert "2006-08" not in months
    assert "2008-04" not in months
    assert "2008-05" in months
    assert "2008-06" in months
    assert all(j.requested_from >= "2008-05-07" for j in plan.jobs)
    may = next(j for j in plan.jobs if j.segment_id == "2008-05")
    assert may.requested_from == "2008-05-07"
    assert may.requested_from != "2006-08-13"
    assert all(j.state != "COMPLETE" for j in plan.jobs)


def test_planner_fins_summary_without_v3_uses_coverage_json_not_invented_domain():
    """No-V3 governed datasets keep official domain None; start is coverage JSON.

    Missing SourceCapability V3 is not an invented official domain.
    plan_required_segments and BackfillPlanner both start at
    collection_coverage.json history_target_start. evaluate_segment
    without a receipt is PARTIAL, not COMPLETE.
    """
    from datetime import date

    from data_contracts.coverage import coverage_contract_for
    from data_contracts.source_capability import source_capability_contract_or_none
    from ops.backfill_planner import _official_domain_start
    from storage.coverage_ledger import evaluate_segment, plan_required_segments

    dataset = "fins_summary"
    assert source_capability_contract_or_none(dataset) is None
    assert _official_domain_start(dataset) is None

    policy = coverage_contract_for(dataset)
    assert policy.history_target_start == "2008-07-01"
    assert policy.earliest_official_availability is None

    cutoff = date(2008, 8, 31)
    planned = plan_required_segments(policy, cutoff.isoformat())
    assert [segment.segment_id for segment in planned] == ["2008-07", "2008-08"]
    assert planned[0].segment_start == policy.history_target_start
    for segment in planned:
        assert segment.expected_scope["coverage_mode"] == policy.coverage_mode
        assert "earliest_official_availability" not in segment.expected_scope
        assert "history_mode" not in segment.expected_scope

    status, detail = evaluate_segment(policy, planned[0], None)
    assert status == "PARTIAL"
    assert status != "COMPLETE"
    assert detail["reason"] == "missing collection receipt"

    plan = BackfillPlanner(cutoff=cutoff).plan(datasets=[dataset])
    assert [job.segment_id for job in plan.jobs] == ["2008-07", "2008-08"]
    assert plan.jobs[0].requested_from == policy.history_target_start
    assert all(
        job.requested_from >= policy.history_target_start for job in plan.jobs
    )
    assert not any(
        job.segment_id in {"2006-08", "2008-05", "2008-06"} for job in plan.jobs
    )


def test_planner_skips_complete_tip_snapshot_segment(tmp_path):
    """Already-COMPLETE cutoff ids are skipped; planner does not invent COMPLETE."""
    import sqlite3
    from datetime import date

    cutoff = date(2026, 8, 14)
    db = tmp_path / "coverage.sqlite"
    conn = sqlite3.connect(db)
    conn.execute(
        "CREATE TABLE coverage_segments (dataset TEXT, segment_id TEXT, status TEXT)"
    )
    conn.execute(
        "INSERT INTO coverage_segments VALUES (?, ?, ?)",
        ("equities_bars_daily_am", cutoff.isoformat(), "COMPLETE"),
    )
    conn.commit()
    conn.close()
    plan = BackfillPlanner(cutoff=cutoff, db_path=db).plan(
        datasets=["equities_bars_daily_am"],
    )
    assert plan.jobs == []
    assert all(j.state != "COMPLETE" for j in plan.jobs)


def test_planner_never_emits_complete_status():
    """Ops job state is not Coverage COMPLETE; planner does not mint it."""
    from datetime import date
    from typing import get_args

    from ops.backfill_planner import JobState

    assert "COMPLETE" not in get_args(JobState)
    plan = BackfillPlanner(cutoff=date(2008, 7, 31)).plan(
        datasets=["equities_master", "equities_bars_daily", "fins_summary"],
    )
    assert plan.jobs
    states = {j.state for j in plan.jobs}
    assert "COMPLETE" not in states
    assert states <= {"pending", "running", "pass", "partial", "fail", "retry"}
    assert all(j.expected_evidence != "COMPLETE" for j in plan.jobs)


def test_planner_bars_and_fins_month_chunks_match_required_segments():
    """Bounded-history bars/fins stay calendar_month jobs via required segments."""
    from datetime import date

    from data_contracts.coverage import coverage_contract_for
    from data_contracts.source_capability import source_capability_contract_or_none
    from storage.coverage_ledger import plan_required_segments

    cutoff = date(2008, 7, 31)
    for dataset, expected_ids in (
        ("equities_bars_daily", {"2008-05", "2008-06", "2008-07"}),
        ("fins_summary", {"2008-07"}),
    ):
        assert source_capability_contract_or_none(dataset) is None
        required = plan_required_segments(
            coverage_contract_for(dataset), cutoff.isoformat()
        )
        plan = BackfillPlanner(cutoff=cutoff).plan(datasets=[dataset])
        assert [j.segment_id for j in plan.jobs] == [s.segment_id for s in required]
        assert [j.requested_from for j in plan.jobs] == [
            s.segment_start for s in required
        ]
        assert [j.requested_to for j in plan.jobs] == [s.segment_end for s in required]
        assert {j.segment_id for j in plan.jobs} == expected_ids
        assert all(j.state == "pending" for j in plan.jobs)
        assert all(j.state != "COMPLETE" for j in plan.jobs)


def test_planner_empty_missing_v3_does_not_mint_complete(tmp_path):
    """Empty ledger + no V3 row still month-chunks; never COMPLETE."""
    import sqlite3
    from datetime import date

    from data_contracts.source_capability import source_capability_contract_or_none
    from ops.backfill_planner import backfill_status_rows

    assert source_capability_contract_or_none("fins_summary") is None
    db = tmp_path / "coverage.sqlite"
    conn = sqlite3.connect(db)
    conn.execute(
        "CREATE TABLE coverage_segments (dataset TEXT, segment_id TEXT, status TEXT)"
    )
    conn.commit()
    conn.close()
    plan = BackfillPlanner(cutoff=date(2008, 8, 31), db_path=db).plan(
        datasets=["fins_summary"],
    )
    assert plan.jobs
    assert {j.segment_id for j in plan.jobs} == {"2008-07", "2008-08"}
    assert all(j.state == "pending" for j in plan.jobs)
    assert all(j.state != "COMPLETE" for j in plan.jobs)
    assert all(j.expected_evidence != "COMPLETE" for j in plan.jobs)

    rows = backfill_status_rows(db_path=db)
    fins = next(row for row in rows if row["dataset"] == "fins_summary")
    assert fins["complete_segments"] == 0
    assert fins["state"] != "COVERAGE_COMPLETE"
    assert fins["state"] != "COMPLETE"


def test_planner_missing_v3_invented_official_domain_is_fail_closed(monkeypatch):
    """A no-V3 dataset must not treat invented official domain as required."""
    from datetime import date

    from data_contracts.source_capability import source_capability_contract_or_none
    from ops.backfill_planner import _invented_official_domain_without_v3
    from storage.coverage_ledger import RequiredCoverageSegment

    assert source_capability_contract_or_none("fins_summary") is None
    invented = {"earliest_official_availability": "2008-07-01"}
    assert _invented_official_domain_without_v3("fins_summary", invented) is True
    assert _invented_official_domain_without_v3("fins_summary", {}) is False
    assert (
        _invented_official_domain_without_v3(
            "equities_master", {"earliest_official_availability": "2008-05-07"}
        )
        is False
    )

    def _invent(_policy, _end, **_kwargs):
        return (
            RequiredCoverageSegment(
                source="jquants",
                dataset="fins_summary",
                segment_id="2008-07",
                segment_start="2008-07-01",
                segment_end="2008-07-31",
                expected_scope={
                    "coverage_mode": "event_reconciled",
                    "segment_granularity": "calendar_month",
                    "earliest_official_availability": "2008-07-01",
                },
                expected_items=1,
            ),
        )

    monkeypatch.setattr("ops.backfill_planner.plan_required_segments", _invent)
    plan = BackfillPlanner(cutoff=date(2008, 7, 31)).plan(
        datasets=["fins_summary"],
    )
    assert plan.jobs
    assert all(j.segment_id == "UNPLANNABLE" for j in plan.jobs)
    assert all(j.state == "fail" for j in plan.jobs)
    assert all(j.state != "COMPLETE" for j in plan.jobs)
    assert all("invented official domain" in j.detail for j in plan.jobs)
