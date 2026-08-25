"""Phase 3.5 — validation matrix catalog completeness.

Every id mentioned in ``docs/phase35_validation_matrix.md`` must exist in
``cf_platform.ingest_premium.matrix.CHECKS``, and the daily tier must match
the doc (exactly C1–C5, C8, C12, B2, B4, K3, X4).

Coverage-runner behavior is split by concern:

* ``test_phase35_coverage_daily.py`` — bars / calendar / master daily checks
* ``test_phase35_coverage_weekly.py`` — weekly span / universe checks
* ``test_phase35_coverage_cli.py`` — CLI, B0 gates, validation-log honesty

Shared DB builders live in ``tests/phase35_matrix_util.py``.
Offline-only: no network, no Cloudflare, no API keys.
"""

from __future__ import annotations

import pytest

from cf_platform.ingest_premium import matrix
from ingestion.jquants.catalog import PREMIUM_CORE_DATASETS, list_datasets

def test_check_ids_unique():
    ids = [c.id for c in matrix.CHECKS]
    assert len(ids) == len(set(ids)), "duplicate check ids"


# ---------------------------------------------------------------------------
# 2. Tier membership matches the doc's daily/weekly tables exactly
# ---------------------------------------------------------------------------
EXPECTED_DAILY = frozenset(
    {"C1", "C2", "C3", "C4", "C5", "C8", "C12", "B2", "B4", "K3", "X4"}
)


def test_daily_tier_matches_doc():
    assert matrix.DAILY_IDS == EXPECTED_DAILY


def test_weekly_tier_is_complement_of_daily():
    all_ids = {c.id for c in matrix.CHECKS}
    assert matrix.DAILY_IDS | matrix.WEEKLY_IDS == all_ids
    assert matrix.DAILY_IDS & matrix.WEEKLY_IDS == set()


def test_list_checks_filter():
    daily = matrix.list_checks("daily")
    weekly = matrix.list_checks("weekly")
    all_ = matrix.list_checks()
    assert {c.id for c in daily} == matrix.DAILY_IDS
    assert {c.id for c in weekly} == matrix.WEEKLY_IDS
    assert len(daily) + len(weekly) == len(all_)


def test_list_checks_invalid_tier_raises():
    with pytest.raises(ValueError):
        matrix.list_checks("monthly")


def test_get_check_known_and_unknown():
    c = matrix.get_check("C12")
    assert c.id == "C12"
    assert c.tier == "daily"
    assert c.title == "No addon leak"
    with pytest.raises(KeyError):
        matrix.get_check("ZZ9")


def test_premium_core_datasets_match_catalog_sot():
    """Matrix core ids are the catalog SoT, not a second handwritten list."""
    core_ids = matrix.premium_core_datasets()
    assert core_ids == PREMIUM_CORE_DATASETS
    assert core_ids == tuple(list_datasets("core")) + tuple(list_datasets("edinet"))
