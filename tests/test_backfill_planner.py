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
