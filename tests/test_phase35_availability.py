"""Canonical dataset-contract availability policy tests.

The Premium-core JSON document is the policy authority for both Python and
the Cloudflare Worker. Compatibility constants are derived views, not a
second hand-maintained catalog.

Worker wrapper policy (unknown dataset / missing contract field →
ingest_time_conservative) is executed in
``platform/workers/ingestion-premium/src/availability.test.ts``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from cf_platform.ingest_premium.availability import (
    DATASET_POLICY,
    DEFAULT_POLICY,
    EVENT_FIELD_CANDIDATES,
    POLICIES,
    SESSION_CLOSE_DATASETS,
    next_business_open_jst,
    pick_available_at,
    policy_for_dataset,
    session_close_jst,
)
from data_contracts.loader import (
    AVAILABLE_AT_POLICIES,
    all_contracts,
    contract_for,
)


ROOT = Path(__file__).resolve().parents[1]
IDENTITY_TS = ROOT / "platform/workers/ingestion-premium/src/identity.ts"


def test_session_close_honors_tse_cutoff_and_morning_session():
    assert session_close_jst("2024-11-04") == "2024-11-04T15:00:00+09:00"
    assert session_close_jst("2024-11-05") == "2024-11-05T15:30:00+09:00"
    assert session_close_jst("2025-04-01") == "2025-04-01T15:30:00+09:00"
    assert session_close_jst("2025-04-01", session="morning") == (
        "2025-04-01T11:30:00+09:00"
    )


@pytest.mark.parametrize(
    "bad",
    ["", "2025-4-01", "2025/04/01", "not-a-date", "20250401", "2025-02-30"],
)
def test_session_close_rejects_bad_dates(bad):
    with pytest.raises(ValueError):
        session_close_jst(bad)


def test_deprecated_business_open_helper_remains_stable_for_callers():
    assert next_business_open_jst("2025-04-01") == "2025-04-01T09:00:00+09:00"
    assert next_business_open_jst("2025-04-05") == "2025-04-07T09:00:00+09:00"
    assert next_business_open_jst("2025-04-06") == "2025-04-07T09:00:00+09:00"


def test_session_close_policy_uses_dataset_session():
    row = {"Code": "8697", "Date": "2025-04-01"}
    assert pick_available_at(row, "equities_bars_daily", "ingest") == (
        "2025-04-01T15:30:00+09:00"
    )
    assert pick_available_at(row, "equities_bars_daily_am", "ingest") == (
        "2025-04-01T11:30:00+09:00"
    )


def test_session_close_policy_missing_date_fails_safe_to_ingest():
    ingested = "2025-04-01T16:00:00+09:00"
    row = {"Code": "8697", "DisclosedDate": "2025-04-05"}
    assert pick_available_at(row, "equities_bars_daily", ingested) == ingested


def test_explicit_timestamp_policy_uses_contract_fields_and_aliases():
    row = {
        "Code": "8697",
        "DisclosedDate": "2025-04-01",
        "DisclosedTime": "10:30",
        "DiscNo": "1",
    }
    assert pick_available_at(row, "fins_details", "ingest") == (
        "2025-04-01T10:30:00+09:00"
    )


def test_explicit_timestamp_policy_requires_a_complete_timestamp():
    ingested = "2025-04-02T09:00:00+09:00"
    row = {"Code": "8697", "DiscDate": "2025-04-01", "DiscNo": "1"}
    assert pick_available_at(row, "fins_details", ingested) == ingested


def test_explicit_disclosure_date_uses_conservative_next_calendar_start():
    row = {"Code": "8697", "PubDate": "2025-04-05", "SchDate": "2025-05-01"}
    assert pick_available_at(row, "fins_earnings_date", "ingest") == (
        "2025-04-06T00:00:00+09:00"
    )


@pytest.mark.parametrize("dataset", ["markets_breakdown", "markets_calendar"])
def test_unknown_publication_instant_uses_ingest_time(dataset):
    ingested = "2025-04-02T09:00:00+09:00"
    row = {"Code": "8697", "Date": "2025-04-01"}
    assert pick_available_at(row, dataset, ingested) == ingested


def test_unknown_dataset_fails_safe_like_worker_wrapper():
    ingested = "2025-04-02T09:00:00+09:00"
    assert policy_for_dataset("not_a_dataset") == DEFAULT_POLICY
    assert pick_available_at({"Date": "2025-04-01"}, "not_a_dataset", ingested) == (
        ingested
    )


def test_policy_views_are_derived_from_all_23_contracts():
    contracts = all_contracts()
    expected = {contract.dataset_id: contract.available_at_policy for contract in contracts}
    assert len(contracts) == 23
    assert DATASET_POLICY == expected
    assert set(POLICIES) == AVAILABLE_AT_POLICIES
    assert DEFAULT_POLICY == "ingest_time_conservative"
    assert set(SESSION_CLOSE_DATASETS) == {
        contract.dataset_id
        for contract in contracts
        if contract.available_at_policy == "session_close"
    }


def test_session_close_dataset_set_matches_canonical_handoff():
    assert set(SESSION_CLOSE_DATASETS) == {
        "equities_bars_daily",
        "equities_bars_daily_am",
        "indices_bars_daily",
        "indices_bars_daily_topix",
        "derivatives_bars_daily_options_225",
        "derivatives_bars_daily_futures",
        "derivatives_bars_daily_options",
    }
    assert contract_for("equities_bars_daily_am").session == "morning"


def test_compatibility_field_union_is_derived_not_a_priority_policy():
    expected = tuple(
        dict.fromkeys(
            field
            for contract in all_contracts()
            for field in (
                *contract.event_time_fields,
                *(contract.availability_field or "").split("+"),
            )
            if field
        )
    )
    assert EVENT_FIELD_CANDIDATES == expected


def test_worker_wrappers_delegate_contract_policy_and_identity_constants():
    identity = IDENTITY_TS.read_text(encoding="utf-8")
    assert "2024-11-05" in identity
    assert "15:30:00" in identity
    assert "15:00:00" in identity
    assert "11:30:00" in identity
