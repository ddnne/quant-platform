"""available_at_for consults official start; ingest-time fail-safe stays.

PIT query clamp (not available_at_for) is the membership gate for as_of
before earliest_official_availability. This function must not invent a
historical publication instant for master, AM, or earnings.
"""

from __future__ import annotations

from data_contracts.identity import available_at_for, session_close_jst
from data_contracts.source_capability import source_capability_contract_for

INGESTED = "2026-08-15T09:00:00+09:00"
OFFICIAL_START = "2008-05-07"
PRE_OFFICIAL = "2006-08-13"


def test_master_capability_official_start_is_2008_05_07():
    capability = source_capability_contract_for("equities_master")
    assert capability.earliest_official_availability == OFFICIAL_START
    assert capability.available_at.policy == "ingest_time_conservative"


def test_available_at_for_consults_source_capability(monkeypatch):
    seen: list[str] = []
    real = source_capability_contract_for

    def wrapped(dataset_id: str):
        seen.append(dataset_id)
        return real(dataset_id)

    monkeypatch.setattr(
        "data_contracts.identity.source_capability_contract_for", wrapped
    )
    row = {"Code": "8697", "Date": PRE_OFFICIAL}
    assert available_at_for(row, "equities_master", INGESTED) == INGESTED
    assert seen == ["equities_master"]


def test_master_pre_official_and_official_rows_fail_safe_to_ingested_at():
    """Unknown publication instant stays ingest-time; Date is not eligibility."""
    pre = {"Code": "8697", "Date": PRE_OFFICIAL, "available_at": "2006-08-13T00:00:00+09:00"}
    at_start = {"Code": "8697", "Date": OFFICIAL_START}
    after = {"Code": "8697", "Date": "2008-05-08"}
    for row in (pre, at_start, after):
        got = available_at_for(row, "equities_master", INGESTED)
        assert got == INGESTED
        assert got != f"{row['Date']}T00:00:00+09:00"
        assert got != session_close_jst(row["Date"])
        # V3 nested calendar (next business day after 17:30 JST) is not minted.
        assert not got.startswith("2008-05-08T17:30")
        assert not got.startswith("2008-05-07T17:30")


def test_am_tip_only_session_close_is_not_rewritten_into_history():
    """AM stays session_close; do not invent historical tip eligibility."""
    capability = source_capability_contract_for("equities_bars_daily_am")
    assert capability.tip_only_operational is True
    assert capability.historical_research_eligible is False
    assert capability.earliest_official_availability == "2024-01-04"
    ingested = "2026-08-15T12:00:00+09:00"
    in_window = {"Code": "8697", "Date": "2025-04-01"}
    pre_official = {"Code": "8697", "Date": "2023-12-29"}
    assert available_at_for(in_window, "equities_bars_daily_am", ingested) == (
        "2025-04-01T11:30:00+09:00"
    )
    # Pre-official stored AM still uses session_close, not a minted calendar.
    assert available_at_for(pre_official, "equities_bars_daily_am", ingested) == (
        session_close_jst("2023-12-29", session="morning")
    )
    assert available_at_for(pre_official, "equities_bars_daily_am", ingested) != ingested


def test_earnings_tip_only_stays_ingest_time_not_invented_history():
    capability = source_capability_contract_for("equities_earnings_calendar")
    assert capability.tip_only_operational is True
    assert capability.historical_research_eligible is False
    assert capability.available_at.policy == "calendar_prepublished"
    row = {"Code": "8697", "Date": "2009-12-30"}
    official = {"Code": "8697", "Date": "2010-01-04"}
    assert available_at_for(row, "equities_earnings_calendar", INGESTED) == INGESTED
    assert available_at_for(official, "equities_earnings_calendar", INGESTED) == INGESTED
    assert available_at_for(row, "equities_earnings_calendar", INGESTED) != (
        "2009-12-30T00:00:00+09:00"
    )
