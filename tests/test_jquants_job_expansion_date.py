from ingestion.jquants.parallel import expand_jobs

def test_equities_bars_daily_uses_date_not_from_to():
    jobs = expand_jobs(
        ["equities_bars_daily"],
        from_date="2026-08-01",
        to_date="2026-08-03",
        chunk_days=30,
    )
    assert len(jobs) == 3
    for j in jobs:
        assert "date" in j.params
        assert "from" not in j.params
        assert "to" not in j.params

def test_markets_calendar_still_uses_from_to_range():
    jobs = expand_jobs(
        ["markets_calendar"],
        from_date="2026-08-01",
        to_date="2026-08-11",
        chunk_days=30,
    )
    assert len(jobs) == 1
    assert jobs[0].params["from"] == "2026-08-01"
    assert jobs[0].params["to"] == "2026-08-11"
