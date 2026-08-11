"""Contract-selected natural-key and event-time extraction tests."""

from __future__ import annotations

import json

import pytest

from cf_platform.ingest_premium.natural_key import (
    EVENT_TIME_FIELDS,
    KEY_FIELDS,
    natural_key,
    pick_event_time,
)
from data_contracts.loader import all_contracts


def test_daily_bar_key_uses_only_its_contract_fields():
    row = {"Code": "8697", "Date": "2025-04-01", "Close": 100.0}
    assert json.loads(natural_key(row, "equities_bars_daily")) == {
        "Code": "8697",
        "Date": "2025-04-01",
    }


def test_different_datasets_select_different_identity_fields():
    row = {
        "Code": "8697",
        "Date": "2025-04-01",
        "S33": "0050",
        "Close": 100.0,
    }
    assert json.loads(natural_key(row, "equities_bars_daily")) == {
        "Code": "8697",
        "Date": "2025-04-01",
    }
    assert json.loads(natural_key(row, "markets_short_ratio")) == {
        "Date": "2025-04-01",
        "S33": "0050",
    }


def test_incomplete_composite_key_falls_back_instead_of_collapsing_rows():
    row = {"Code": "8697", "Date": "", "Close": 1.0}
    key = natural_key(row, "equities_bars_daily")
    assert key.startswith("hash:sha256:")
    assert len(key.removeprefix("hash:sha256:")) == 64


def test_hash_fallback_is_stable_distinct_and_order_independent():
    first = {"Close": 100.0, "Volume": 1000}
    reordered = {"Volume": 1000, "Close": 100.0}
    distinct = {"Close": 200.0, "Volume": 1000}
    first_key = natural_key(first, "markets_breakdown")
    assert first_key == natural_key(reordered, "markets_breakdown")
    assert first_key != natural_key(distinct, "markets_breakdown")


def test_source_aliases_are_canonicalized_in_key():
    row = {
        "Code": "8697",
        "DisclosedDate": "2025-04-01",
        "DiscNo": "1",
    }
    assert json.loads(natural_key(row, "fins_details")) == {
        "Code": "8697",
        "DiscDate": "2025-04-01",
        "DiscNo": "1",
    }


def test_compatibility_field_unions_are_derived_from_contracts():
    contracts = all_contracts()
    expected_keys = tuple(
        dict.fromkeys(field for contract in contracts for field in contract.natural_key_fields)
    )
    expected_event_fields = tuple(
        dict.fromkeys(field for contract in contracts for field in contract.event_time_fields)
    )
    assert KEY_FIELDS == expected_keys
    assert EVENT_TIME_FIELDS == expected_event_fields


@pytest.mark.parametrize(
    "dataset,row,expected",
    [
        (
            "equities_bars_daily",
            {"Date": "2025-04-01"},
            "2025-04-01T15:30:00+09:00",
        ),
        (
            "equities_bars_daily_am",
            {"Date": "2025-04-01"},
            "2025-04-01T11:30:00+09:00",
        ),
        (
            "markets_breakdown",
            {"Date": "2025-04-01"},
            "2025-04-01T00:00:00+09:00",
        ),
        (
            "fins_details",
            {"DiscDate": "2025-04-01", "DiscTime": "10:30"},
            "2025-04-01T10:30:00+09:00",
        ),
        (
            "fins_details",
            {"DiscDate": "2025-04-01"},
            "2025-04-01T00:00:00+09:00",
        ),
        ("markets_breakdown", {"Close": 100.0}, None),
    ],
)
def test_pick_event_time_uses_dataset_policy(dataset, row, expected):
    assert pick_event_time(row, dataset) == expected


def test_dataset_policy_ignores_uncontracted_global_candidates():
    row = {
        "DateTime": "2025-04-01T10:00:00+09:00",
        "Date": "2025-04-01",
    }
    assert pick_event_time(row, "equities_bars_daily") == (
        "2025-04-01T15:30:00+09:00"
    )


def test_unknown_dataset_is_rejected_by_identity_contract():
    with pytest.raises(KeyError, match="unknown Premium-core dataset contract"):
        natural_key({"Date": "2025-04-01"}, "not_a_dataset")
