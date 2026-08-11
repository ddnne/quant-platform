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
