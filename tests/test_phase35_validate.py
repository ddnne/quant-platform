"""Phase 3.5 — validation rules (pass/fail classification).

Asserts the closed-loop pass/fail logic in
`cf_platform.ingest_premium.validate`. The CF Worker re-implements the
same rule in TypeScript — this is the Python source of truth.
"""

from __future__ import annotations

import pytest

from cf_platform.ingest_premium.validate import (
    PREMIUM_CORE_DATASETS,
    DatasetResult,
    RunSummary,
    assert_no_addon_in_required,
    classify_dataset,
    classify_run,
    required_dataset_coverage,
)
from ingestion.jquants.catalog import list_datasets


# ---------------------------------------------------------------------------
# classify_dataset
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "kwargs,expected",
    [
        # happy path — rows seen and inserted, available_at present
        (
            dict(
                dataset="equities_master",
                rows_seen=10, rows_inserted=10,
                available_at_min="2025-04-01T00:00:00+09:00",
            ),
            "pass",
        ),
        # empty result is OK (non-trading day)
        (
            dict(dataset="markets_calendar", rows_seen=0, rows_inserted=0),
            "pass",
        ),
        # error -> fail
        (
            dict(
                dataset="equities_master",
                error="HTTP 503",
                rows_seen=0, rows_inserted=0,
            ),
            "fail",
        ),
        # schema miss -> fail (silent failure guard)
        (
            dict(
                dataset="fins_dividend",
                rows_seen=50, rows_inserted=0,
                available_at_min=None,
            ),
            "fail",
        ),
        # rows inserted but PIT column missing -> fail
        (
            dict(
                dataset="markets_calendar",
                rows_seen=5, rows_inserted=5,
                available_at_min=None,
            ),
            "fail",
        ),
        # revisions only (no primary insert) is still acceptable as a pass:
        # the row already existed; the amendment is tracked.
        (
            dict(
                dataset="equities_bars_daily",
                rows_seen=1, rows_inserted=0, rows_revisions=1,
                available_at_min="2025-04-01T00:00:00+09:00",
            ),
            "pass",
        ),
    ],
)
def test_classify_dataset_rule(kwargs, expected):
    assert classify_dataset(**kwargs) == expected


# ---------------------------------------------------------------------------
# classify_run
# ---------------------------------------------------------------------------

def _mk(dataset: str, status: str) -> DatasetResult:
    return DatasetResult(
        dataset=dataset, status=status,
        started_at="2025-04-01T00:00:00+09:00",
        finished_at="2025-04-01T00:01:00+09:00",
    )


def test_classify_run_all_pass():
    assert classify_run([_mk("a", "pass"), _mk("b", "pass")]) == "pass"


def test_classify_run_all_fail():
    assert classify_run([_mk("a", "fail"), _mk("b", "fail")]) == "fail"


def test_classify_run_partial():
    assert classify_run([_mk("a", "pass"), _mk("b", "fail")]) == "partial"


def test_classify_run_empty_is_fail():
    assert classify_run([]) == "fail"


# ---------------------------------------------------------------------------
# coverage helpers
# ---------------------------------------------------------------------------

def test_required_dataset_coverage_complete():
    cov = required_dataset_coverage(list(PREMIUM_CORE_DATASETS))
    assert all(cov.values())
    assert set(cov) == set(PREMIUM_CORE_DATASETS)


def test_required_dataset_coverage_flags_missing():
    implemented = list(PREMIUM_CORE_DATASETS)[:5]
    cov = required_dataset_coverage(implemented)
    missing = [k for k, v in cov.items() if not v]
    assert len(missing) == len(PREMIUM_CORE_DATASETS) - 5


def test_assert_no_addon_in_required_passes_for_clean():
    assert_no_addon_in_required(list(PREMIUM_CORE_DATASETS))


def test_assert_no_addon_in_required_default_matches_catalog_addon_group():
    """The default policy rejects every catalog-owned add-on behaviorally."""
    catalog_addons = tuple(list_datasets("addon"))
    assert catalog_addons
    assert not set(catalog_addons) & set(PREMIUM_CORE_DATASETS)
    for leaked in catalog_addons:
        with pytest.raises(AssertionError, match="addon datasets must not be"):
            assert_no_addon_in_required([*PREMIUM_CORE_DATASETS, leaked])


def test_assert_no_addon_in_required_raises_for_leak():
    leaked = list_datasets("addon")[0]
    with pytest.raises(AssertionError, match="addon datasets must not be"):
        assert_no_addon_in_required(list(PREMIUM_CORE_DATASETS) + [leaked])


# ---------------------------------------------------------------------------
# RunSummary serialization
# ---------------------------------------------------------------------------

def test_run_summary_log_dict_is_json_safe():
    rs = RunSummary(
        started_at="2025-04-01T00:00:00+09:00",
        finished_at="2025-04-01T00:05:00+09:00",
        status="partial",
        dataset_count=23,
        passed=22,
        failed=1,
        rows_inserted=1234,
        triggered_by="cron",
        failures=(("fins_dividend", "HTTP 503"),),
    )
    import json
    s = json.dumps(rs.as_log_dict())
    parsed = json.loads(s)
    assert parsed["status"] == "partial"
    assert parsed["failures"] == [{"dataset": "fins_dividend", "detail": "HTTP 503"}]
