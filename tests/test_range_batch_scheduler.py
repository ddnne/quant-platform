"""Unit tests for Track A range-batch scheduler (no network)."""

from __future__ import annotations

from datetime import date
from pathlib import Path

from ops.backfill_planner import BackfillJob, BackfillPlan, BackfillPlanner
from ops.range_batch_scheduler import (
    DEFAULT_FINS_RPM,
    DEFAULT_GENERAL_RPM,
    RATE_POOL_FINS,
    RATE_POOL_GENERAL,
    SCHEDULER_CONFIG,
    TRACK_A_DATASETS,
    RangeBatchScheduler,
    SchedulerConfig,
    build_queue,
    estimate_dispatch_envelope,
    filter_plan_jobs,
    plan_and_queue,
    rate_pool_for_dataset,
    rpm_to_min_interval,
)


def test_rate_pool_fins_isolated():
    assert rate_pool_for_dataset("fins_summary") == RATE_POOL_FINS
    assert rate_pool_for_dataset("fins_details") == RATE_POOL_FINS
    assert rate_pool_for_dataset("equities_bars_daily") == RATE_POOL_GENERAL
    assert rate_pool_for_dataset("markets_margin_interest") == RATE_POOL_GENERAL
    assert rate_pool_for_dataset("edinet_major_shareholders") == RATE_POOL_GENERAL


def test_rpm_and_config_headroom():
    assert DEFAULT_GENERAL_RPM < 500
    assert DEFAULT_FINS_RPM < 500
    assert rpm_to_min_interval(480) == 60.0 / 480.0
    assert rpm_to_min_interval(0) == 0.0
    assert SCHEDULER_CONFIG["date_range_batch_standard"] is True
    assert SCHEDULER_CONFIG["default_mode"] == "dry-run"
    assert "fins_summary" in TRACK_A_DATASETS


def test_filter_track_a_and_focus_range():
    plan = BackfillPlanner(cutoff=date(2024, 1, 31)).plan()
    # Track A bars focus 2004–2023 — January 2024 is outside focus upper bound
    # for equities_bars_daily (to 2023-12-31), so 2024-01 jobs drop.
    track = filter_plan_jobs(plan, track_a=True)
    datasets = {j.dataset for j in track}
    assert datasets <= set(TRACK_A_DATASETS)
    assert "equities_bars_daily" in datasets or "indices_bars_daily_topix" in datasets
    # No JSDA
    assert not any(d.startswith("jsda_") for d in datasets)
    # Date filter
    narrow = filter_plan_jobs(
        plan,
        datasets=["indices_bars_daily_topix"],
        from_date="2008-01-01",
        to_date="2008-03-31",
    )
    assert narrow
    assert all(j.dataset == "indices_bars_daily_topix" for j in narrow)
    assert all(j.requested_from <= "2008-03-31" for j in narrow)


def test_latest_only_one_per_dataset():
    plan = BackfillPlanner(cutoff=date(2010, 6, 30)).plan(
        datasets=["indices_bars_daily_topix", "fins_summary"]
    )
    jobs = filter_plan_jobs(plan, latest_only=True)
    by_ds: dict[str, int] = {}
    for j in jobs:
        by_ds[j.dataset] = by_ds.get(j.dataset, 0) + 1
    assert by_ds
    assert all(v == 1 for v in by_ds.values())


def test_build_queue_assigns_pools_and_cap():
    jobs = [
        BackfillJob(
            dataset="equities_bars_daily",
            source="jquants",
            segment_id="2004-01",
            requested_from="2004-01-01",
            requested_to="2004-01-31",
            endpoint_query_mode="today",
            priority=30,
        ),
        BackfillJob(
            dataset="fins_summary",
            source="jquants",
            segment_id="2008-01",
            requested_from="2008-01-01",
            requested_to="2008-01-31",
            endpoint_query_mode="today",
            priority=70,
        ),
    ]
    q = build_queue(jobs)
    assert q[0].pool == RATE_POOL_GENERAL
    assert q[1].pool == RATE_POOL_FINS
    q1 = build_queue(jobs, max_jobs=1)
    assert len(q1) == 1


def test_dry_run_scheduler_no_network():
    plan = BackfillPlanner(cutoff=date(2008, 3, 31)).plan(
        datasets=["indices_bars_daily_topix"]
    )
    calls: list[tuple] = []

    def _fake_run(**kwargs):
        calls.append(kwargs)
        return 200, {"status": "pass", "passed": 1, "failed": 0, "rowsInserted": 0}

    sched = RangeBatchScheduler(
        plan,
        config=SchedulerConfig(execute=False, max_jobs=5),
        run_job=_fake_run,
        premium_url="https://example.invalid",
        token="SECRET_SHOULD_NOT_APPEAR",
    )
    result = sched.run(datasets=["indices_bars_daily_topix"])
    assert result.mode == "dry-run"
    assert result.queued
    assert result.executed == []
    assert calls == []
    blob = result.to_dict()
    assert "SECRET" not in str(blob)
    assert "token" not in blob
    assert blob["config"]["mode"] == "dry-run"


def test_execute_uses_run_job_and_never_logs_token():
    plan = BackfillPlan(
        plan_version="t",
        coverage_policy_version="t",
        contract_digest="sha256:dead",
        cutoff="2008-01-31",
        created_at="t",
        jobs=[
            BackfillJob(
                dataset="indices_bars_daily_topix",
                source="jquants",
                segment_id="2008-01",
                requested_from="2008-01-01",
                requested_to="2008-01-31",
                endpoint_query_mode="range",
                priority=20,
            ),
            BackfillJob(
                dataset="fins_summary",
                source="jquants",
                segment_id="2008-01",
                requested_from="2008-01-01",
                requested_to="2008-01-31",
                endpoint_query_mode="today",
                priority=70,
            ),
        ],
    )
    seen_tokens: list[str] = []

    def _fake_run(**kwargs):
        seen_tokens.append(kwargs.get("token", ""))
        return 200, {"status": "pass", "passed": 1, "failed": 0, "rowsInserted": 1}

    sched = RangeBatchScheduler(
        plan,
        config=SchedulerConfig(
            execute=True,
            general_rpm=10_000,
            fins_rpm=10_000,
            general_workers=2,
            fins_workers=1,
            sleep_on_retry_s=0.0,
        ),
        run_job=_fake_run,
        premium_url="https://example.invalid",
        token="SUPERSECRET",
    )
    result = sched.run()
    assert result.mode == "execute"
    assert len(result.executed) == 2
    assert all(r["state"] == "pass" for r in result.executed)
    assert seen_tokens and all(t == "SUPERSECRET" for t in seen_tokens)
    # Result serialization must not include the secret
    assert "SUPERSECRET" not in str(result.to_dict())


def test_execute_http_429_maps_retry():
    plan = BackfillPlan(
        plan_version="t",
        coverage_policy_version="t",
        contract_digest="sha256:dead",
        cutoff="2008-01-31",
        created_at="t",
        jobs=[
            BackfillJob(
                dataset="markets_calendar",
                source="jquants",
                segment_id="2008-01",
                requested_from="2008-01-01",
                requested_to="2008-01-31",
                endpoint_query_mode="range",
                priority=10,
            )
        ],
    )

    def _fake_run(**kwargs):
        return 429, {"status": "fail", "error": "rate"}

    sched = RangeBatchScheduler(
        plan,
        config=SchedulerConfig(
            execute=True, general_rpm=10_000, sleep_on_retry_s=0.0, max_jobs=1
        ),
        run_job=_fake_run,
        premium_url="https://example.invalid",
        token="x",
    )
    result = sched.run()
    assert result.executed[0]["state"] == "retry"
    assert result.executed[0]["reason_code"] == "http_429"


def test_plan_and_queue_and_envelope():
    plan, queued = plan_and_queue(
        cutoff=date(2008, 2, 28),
        datasets=["indices_bars_daily_topix"],
        max_jobs=3,
    )
    assert plan.jobs
    assert len(queued) <= 3
    env = estimate_dispatch_envelope(queued, general_rpm=480, fins_rpm=480)
    assert "host_dispatch_floor_minutes_if_parallel_pools" in env
    assert env["queued_general"] + env["queued_fins"] == len(queued)


def test_planner_range_filter_and_month_standard():
    plan = BackfillPlanner(cutoff=date(2008, 6, 30)).plan(
        datasets=["indices_bars_daily_topix"],
        from_date="2008-02-01",
        to_date="2008-04-30",
    )
    assert plan.jobs
    months = {j.segment_id for j in plan.jobs}
    assert "2008-02" in months
    assert "2008-01" not in months
    # Date-range batch: each job is a range, not a single day
    for j in plan.jobs:
        assert j.requested_from <= j.requested_to
        assert len(j.requested_from) == 10
