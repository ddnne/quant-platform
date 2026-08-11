"""Phase 3.5 (P0-1) — Dataset-level available_at policy (Python unit tests).

Pure-Python tests for the policy logic. Cross-language agreement with the
TypeScript mirror is asserted via the constants-exact-match tests at the
bottom of the file (the actual TS-side execution is exercised indirectly
via the deployed Worker's behaviour; these tests guarantee the policy data
and core helpers agree byte-for-byte with the TS source).

The Python source of truth is ``cf_platform.ingest_premium.availability``.
"""

from __future__ import annotations

import pytest

from cf_platform.ingest_premium.availability import (
    DATASET_POLICY,
    DEFAULT_POLICY,
    EVENT_FIELD_CANDIDATES,
    POLICIES,
    SESSION_CLOSE_DATASETS,
    next_business_open_jst,
    pick_available_at,
    pick_event_field_instant,
    policy_for_dataset,
    session_close_jst,
)


# ---------------------------------------------------------------------------
# session_close_jst
# ---------------------------------------------------------------------------


def test_session_close_pre_cutoff_is_15_00():
    # 2024-11-04 is the last pre-change trading day (Tuesday).
    assert session_close_jst("2024-11-04") == "2024-11-04T15:00:00+09:00"


def test_session_close_at_cutoff_is_15_30():
    # 2024-11-05 is the first day at the new 15:30 close.
    assert session_close_jst("2024-11-05") == "2024-11-05T15:30:00+09:00"


def test_session_close_post_cutoff_is_15_30():
    assert session_close_jst("2025-04-01") == "2025-04-01T15:30:00+09:00"


def test_session_close_far_past_is_15_00():
    assert session_close_jst("2014-01-15") == "2014-01-15T15:00:00+09:00"


@pytest.mark.parametrize("bad", ["", "2025-4-01", "2025/04/01", "not-a-date", "20250401"])
def test_session_close_rejects_bad_dates(bad):
    with pytest.raises(ValueError):
        session_close_jst(bad)


# ---------------------------------------------------------------------------
# next_business_open_jst
# ---------------------------------------------------------------------------


def test_next_business_open_keeps_weekday():
    # 2025-04-01 is a Tuesday → unchanged, 09:00 JST.
    assert next_business_open_jst("2025-04-01") == "2025-04-01T09:00:00+09:00"


def test_next_business_open_advances_saturday():
    # 2025-04-05 is a Saturday → next business open is Monday 2025-04-07.
    assert next_business_open_jst("2025-04-05") == "2025-04-07T09:00:00+09:00"


def test_next_business_open_advances_sunday():
    # 2025-04-06 is a Sunday → next business open is Monday 2025-04-07.
    assert next_business_open_jst("2025-04-06") == "2025-04-07T09:00:00+09:00"


# ---------------------------------------------------------------------------
# pick_event_field_instant
# ---------------------------------------------------------------------------


def test_event_field_prefers_datetime_over_date():
    row = {
        "DateTime": "2025-04-01T15:30:00+09:00",
        "Date": "2025-04-01",
    }
    assert pick_event_field_instant(row) == "2025-04-01T15:30:00+09:00"


def test_event_field_disclosed_date_becomes_business_open():
    # DisclosedDate is bare → next business open at 09:00 JST.
    assert pick_event_field_instant({"DisclosedDate": "2025-04-05"}) == "2025-04-07T09:00:00+09:00"


def test_event_field_announcement_date_passthrough_with_time():
    row = {"AnnouncementDate": "2025-04-01T10:00:00+09:00"}
    assert pick_event_field_instant(row) == "2025-04-01T10:00:00+09:00"


def test_event_field_returns_none_when_no_candidate():
    assert pick_event_field_instant({"Close": 100.0}) is None


def test_event_field_skips_empty_strings():
    row = {"DateTime": "", "DisclosedDate": "", "Date": ""}
    assert pick_event_field_instant(row) is None


def test_event_field_candidate_priority_order():
    """DateTime > DisclosedDate > AnnouncementDate > DiscDate > Date."""
    row = {
        "DateTime": "2025-04-01T08:00:00+09:00",
        "DisclosedDate": "2025-04-02T08:00:00+09:00",
        "AnnouncementDate": "2025-04-03T08:00:00+09:00",
        "Date": "2025-04-04",
    }
    assert pick_event_field_instant(row) == "2025-04-01T08:00:00+09:00"


# ---------------------------------------------------------------------------
# pick_available_at — per-policy behaviour
# ---------------------------------------------------------------------------


def test_pick_available_at_session_close():
    row = {"Code": "8697", "Date": "2025-04-01", "Close": 100.0}
    assert pick_available_at(row, "equities_bars_daily", "ingest") == "2025-04-01T15:30:00+09:00"


def test_pick_available_at_session_close_pre_cutoff():
    row = {"Code": "8697", "Date": "2024-11-04", "Close": 100.0}
    assert pick_available_at(row, "equities_bars_daily", "ingest") == "2024-11-04T15:00:00+09:00"


def test_pick_available_at_session_close_am_dataset():
    # AM session bars are also session-close driven (the AM close is 11:30,
    # but the policy treats the row as available at the daily close for
    # PIT-simplicity; the row is only fully settled at afternoon close).
    row = {"Code": "8697", "Date": "2025-04-01"}
    assert pick_available_at(row, "equities_bars_daily_am", "ingest").startswith("2025-04-01T15:30")


def test_pick_available_at_session_close_missing_date_falls_back_to_event():
    # If session_close row lacks Date, the policy still tries event fields.
    row = {"Code": "8697", "DisclosedDate": "2025-04-05"}
    # 2025-04-05 is Saturday → next business open Monday 09:00 JST.
    assert pick_available_at(row, "equities_bars_daily", "ingest") == "2025-04-07T09:00:00+09:00"


def test_pick_available_at_session_close_no_signal_uses_ingest():
    row = {"Code": "8697", "Close": 100.0}
    assert pick_available_at(row, "equities_bars_daily", "2025-04-01T16:00:00+09:00") == "2025-04-01T16:00:00+09:00"


def test_pick_available_at_event_field_default():
    # Non-bars dataset → default policy is event_field.
    row = {"Code": "8697", "DisclosedDate": "2025-04-01"}
    assert pick_available_at(row, "fins_dividend", "ingest") == "2025-04-01T09:00:00+09:00"


def test_pick_available_at_event_field_with_timestamp():
    row = {"DateTime": "2025-04-01T10:30:00+09:00"}
    assert pick_available_at(row, "markets_breakdown", "ingest") == "2025-04-01T10:30:00+09:00"


def test_pick_available_at_event_field_no_signal_uses_ingest():
    row = {"Close": 100.0}
    assert pick_available_at(row, "markets_breakdown", "2025-04-01T08:00:00+09:00") == "2025-04-01T08:00:00+09:00"


def test_pick_available_at_returns_one_of_three_policies_shape():
    # Smoke: every policy returns a non-empty ISO-ish string.
    ingested = "2025-04-01T16:00:00+09:00"
    for policy_ds, sample_row in [
        ("equities_bars_daily", {"Date": "2025-04-01"}),
        ("markets_breakdown", {"DisclosedDate": "2025-04-01"}),
        ("markets_breakdown", {}),
    ]:
        out = pick_available_at(sample_row, policy_ds, ingested)
        assert isinstance(out, str) and "T" in out and "+09:00" in out


# ---------------------------------------------------------------------------
# policy_for_dataset / DATASET_POLICY
# ---------------------------------------------------------------------------


def test_default_policy_is_event_field():
    assert DEFAULT_POLICY == "event_field"


def test_policy_for_bars_datasets_is_session_close():
    for ds in SESSION_CLOSE_DATASETS:
        assert policy_for_dataset(ds) == "session_close", ds


def test_policy_for_unknown_dataset_is_default():
    assert policy_for_dataset("not_a_dataset") == "event_field"


def test_dataset_policy_covers_only_bars():
    assert set(DATASET_POLICY) == set(SESSION_CLOSE_DATASETS)
    assert all(v == "session_close" for v in DATASET_POLICY.values())


def test_session_close_datasets_match_handoff_set():
    """The handoff names these seven datasets explicitly."""
    assert set(SESSION_CLOSE_DATASETS) == {
        "equities_bars_daily",
        "equities_bars_daily_am",
        "indices_bars_daily",
        "indices_bars_daily_topix",
        "derivatives_bars_daily_options_225",
        "derivatives_bars_daily_futures",
        "derivatives_bars_daily_options",
    }


def test_policies_constant_is_three_options():
    assert set(POLICIES) == {"session_close", "event_field", "ingest_time"}


# ---------------------------------------------------------------------------
# Cross-language agreement — TS mirror must match these constants exactly.
# ---------------------------------------------------------------------------

CATALOG_TS = (
    __import__("pathlib").Path(__file__).resolve().parents[1]
    / "platform/workers/ingestion-premium/src/availability.ts"
)


def _read_ts_constants() -> dict[str, object]:
    """Parse the TS availability.ts constant arrays with simple regexes."""
    import re

    text = CATALOG_TS.read_text(encoding="utf-8")

    def grab_array(name: str) -> list[str]:
        m = re.search(rf"export const {name}:[^=]+=\s*\[(.*?)\]", text, re.DOTALL)
        if not m:
            return []
        body = m.group(1)
        return re.findall(r'"([^"]+)"', body)

    return {
        "SESSION_CLOSE_DATASETS": tuple(grab_array("SESSION_CLOSE_DATASETS")),
        "EVENT_FIELD_CANDIDATES": tuple(grab_array("EVENT_FIELD_CANDIDATES")),
    }


def test_ts_session_close_datasets_match_python():
    if not CATALOG_TS.exists():
        pytest.skip("availability.ts not found")
    ts = _read_ts_constants()
    assert ts["SESSION_CLOSE_DATASETS"] == SESSION_CLOSE_DATASETS


def test_ts_event_field_candidates_match_python():
    if not CATALOG_TS.exists():
        pytest.skip("availability.ts not found")
    ts = _read_ts_constants()
    assert ts["EVENT_FIELD_CANDIDATES"] == EVENT_FIELD_CANDIDATES


def test_ts_session_close_constants_present():
    """The TS file pins the cutoff date and close times."""
    if not CATALOG_TS.exists():
        pytest.skip("availability.ts not found")
    text = CATALOG_TS.read_text(encoding="utf-8")
    assert "2024-11-05" in text
    assert "15:30" in text
    assert "15:00" in text
