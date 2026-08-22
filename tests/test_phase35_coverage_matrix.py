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

import re
from pathlib import Path

import pytest

from cf_platform.ingest_premium import matrix

_REPO = Path(__file__).resolve().parents[1]
MATRIX_DOC = _REPO / "docs" / "phase35_validation_matrix.md"


def _doc_check_ids() -> set[str]:
    """Parse the markdown tables for check IDs (C1, M3, X4, etc.)."""
    text = MATRIX_DOC.read_text(encoding="utf-8")
    # IDs are uppercase letter(s) + digits, used as the first column of
    # doc tables. Pull every match in the right-hand tables; ignore stray
    # mentions in prose by requiring a leading ``|`` (table cell) on the
    # same logical line.
    ids: set[str] = set()
    for line in text.splitlines():
        if not line.startswith("|"):
            continue
        # First cell after the leading ``|``.
        first = line[1:].split("|", 1)[0].strip()
        m = re.fullmatch(r"([A-Z]+)(\d+)", first)
        if m:
            ids.add(first)
    return ids


def test_matrix_doc_exists():
    assert MATRIX_DOC.exists(), f"missing {MATRIX_DOC}"


def test_every_doc_id_is_in_matrix():
    doc_ids = _doc_check_ids()
    code_ids = {c.id for c in matrix.CHECKS}
    missing = doc_ids - code_ids
    assert not missing, f"ids in doc but not in matrix.CHECKS: {sorted(missing)}"


def test_every_matrix_id_is_in_doc():
    doc_ids = _doc_check_ids()
    code_ids = {c.id for c in matrix.CHECKS}
    extra = code_ids - doc_ids
    assert not extra, f"ids in matrix.CHECKS but not in doc: {sorted(extra)}"


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


def test_premium_core_datasets_count():
    assert len(matrix.premium_core_datasets()) == 23
