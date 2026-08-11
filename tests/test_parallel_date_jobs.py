"""Tests for per-day ``date`` job expansion of date-only datasets.

Date-only datasets (``date`` param, no ``from``/``to``) previously dropped a
``from_date``..``to_date`` request and ran a single filterless job. They now
expand into one job per day so the requested span is actually fetched.
"""

from __future__ import annotations

import pytest

from ingestion.jquants.parallel import expand_jobs, iter_dates


def test_iter_dates_inclusive_range():
    assert iter_dates("2020-01-31", "2020-02-02") == [
        "2020-01-31",
        "2020-02-01",
        "2020-02-02",
    ]


def test_iter_dates_single_day():
    assert iter_dates("2020-01-05", "2020-01-05") == ["2020-01-05"]


def test_iter_dates_rejects_reversed_range():
    with pytest.raises(ValueError):
        iter_dates("2020-02-01", "2020-01-01")


def test_date_only_dataset_expands_per_day():
    """equities_master has `date` but no from/to → one job per day."""
    jobs = expand_jobs(
        ["equities_master"],
        from_date="2020-01-01",
        to_date="2020-01-04",
    )
    assert [j.dataset_id for j in jobs] == ["equities_master"] * 4
    dates = [j.params.get("date") for j in jobs]
    assert dates == ["2020-01-01", "2020-01-02", "2020-01-03", "2020-01-04"]
    # No filter dropped: every job carries a `date`, none carries from/to.
    assert all("date" in j.params for j in jobs)
    assert all("from" not in j.params and "to" not in j.params for j in jobs)


def test_date_only_dataset_no_dates_is_single_job():
    """Without a date range, a date-only dataset stays a single filterless job."""
    jobs = expand_jobs(["td_list"])
    assert len(jobs) == 1
    assert jobs[0].dataset_id == "td_list"
    assert "date" not in jobs[0].params
    assert "from" not in jobs[0].params and "to" not in jobs[0].params


def test_date_only_dataset_with_codes_fans_out():
    """date × codes → one (code, date) job per combination."""
    jobs = expand_jobs(
        ["fins_details"],
        from_date="2020-01-01",
        to_date="2020-01-02",
        codes=["7203", "6758"],
    )
    assert len(jobs) == 4  # 2 codes × 2 days
    pairs = {(j.params.get("code"), j.params.get("date")) for j in jobs}
    assert pairs == {
        ("7203", "2020-01-01"),
        ("7203", "2020-01-02"),
        ("6758", "2020-01-01"),
        ("6758", "2020-01-02"),
    }


def test_single_sided_date_not_dropped():
    """A single date on a date-only dataset becomes one job carrying that date."""
    jobs = expand_jobs(["td_list"], from_date="2020-03-01")
    assert len(jobs) == 1
    assert jobs[0].params.get("date") == "2020-03-01"


def test_mixed_range_and_date_only_datasets():
    """A range dataset grids; a date-only dataset fans per day — side by side."""
    jobs = expand_jobs(
        ["markets_calendar", "td_list"],
        from_date="2020-01-01",
        to_date="2020-01-03",
        chunk_days=30,
    )
    by_ds: dict[str, list] = {}
    for j in jobs:
        by_ds.setdefault(j.dataset_id, []).append(j)
    # Range dataset → one gridded window with from/to.
    assert len(by_ds["markets_calendar"]) == 1
    mc = by_ds["markets_calendar"][0]
    assert mc.params["from"] == "2020-01-01" and mc.params["to"] == "2020-01-03"
    # Date-only dataset → three per-day jobs.
    assert [j.params["date"] for j in by_ds["td_list"]] == [
        "2020-01-01",
        "2020-01-02",
        "2020-01-03",
    ]


def test_range_dataset_unaffected_by_date_expansion():
    """Pure range datasets (no date param) still use from/to windows."""
    jobs = expand_jobs(
        ["markets_calendar"],
        from_date="2020-01-01",
        to_date="2020-03-01",
        chunk_days=30,
    )
    assert len(jobs) >= 2
    assert all("from" in j.params and "to" in j.params for j in jobs)
    assert all("date" not in j.params for j in jobs)


def test_dual_date_and_range_prefers_date_for_bars():
    """Bars accept date|from/to but API needs date or code — use date=."""
    jobs = expand_jobs(
        ["equities_bars_daily"],
        from_date="2020-01-01",
        to_date="2020-01-03",
        chunk_days=30,
    )
    assert len(jobs) == 3
    assert all("date" in j.params for j in jobs)
