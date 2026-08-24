"""Vendor annotations on CollectionCoverageContract do not rewrite history start."""

from __future__ import annotations

from data_contracts.coverage import (
    CollectionCoverageContract,
    VENDOR_ANNOTATION_FIELDS,
    coverage_contract_for,
)

ENTITLEMENT_FLOOR = "2006-08-13"
OFFICIAL_START = "2008-05-07"


def _raw(**overrides: object) -> dict:
    body: dict = {
        "collection_scope": "jquants_premium_core",
        "history_target_start": OFFICIAL_START,
        "history_target_end_rule": "latest_published_before_collection_cutoff",
        "coverage_mode": "scd2_event_sourcing",
        "expected_frequency": "trading_day",
        "universe_rule": "all_listed_equities_at_event_date",
        "raw_retention_required": True,
        "structured_reconciliation_required": True,
        "segment_granularity": "calendar_month",
        "governance_tier": "governed",
    }
    body.update(overrides)
    return body


def test_vendor_annotation_keys_survive_from_dict_to_dict() -> None:
    raw = _raw(
        not_historical_required_start=ENTITLEMENT_FLOOR,
        earliest_official_availability=OFFICIAL_START,
        official_mode="bounded_history",
        vendor_data_provision_start=OFFICIAL_START,
        vendor_history_policy="listed_info_from_official_start",
        vendor_data_provision_citation="https://jpx-jquants.com/en/spec/eq-master",
        vendor_history_policy_citation="https://jpx-jquants.com/en/spec/eq-master",
    )
    contract = CollectionCoverageContract.from_dict("equities_master", raw)
    dumped = contract.to_dict()
    for name in VENDOR_ANNOTATION_FIELDS:
        assert dumped[name] == raw[name]
        assert getattr(contract, name) == raw[name]
    roundtrip = CollectionCoverageContract.from_dict("equities_master", dumped)
    assert roundtrip == contract
    assert roundtrip.to_dict() == dumped


def test_missing_vendor_annotation_keys_stay_none() -> None:
    contract = CollectionCoverageContract.from_dict(
        "equities_bars_daily",
        _raw(
            history_target_start="2008-05-01",
            coverage_mode="trading_calendar",
        ),
    )
    for name in VENDOR_ANNOTATION_FIELDS:
        assert getattr(contract, name) is None
        assert contract.to_dict()[name] is None


def test_history_target_start_is_not_replaced_by_entitlement_floor() -> None:
    v2_floor = CollectionCoverageContract.from_dict(
        "equities_master",
        _raw(
            history_target_start=ENTITLEMENT_FLOOR,
            not_historical_required_start=ENTITLEMENT_FLOOR,
            earliest_official_availability=OFFICIAL_START,
            vendor_data_provision_start=OFFICIAL_START,
        ),
    )
    assert v2_floor.history_target_start == ENTITLEMENT_FLOOR
    assert v2_floor.earliest_official_availability == OFFICIAL_START
    assert v2_floor.vendor_data_provision_start == OFFICIAL_START
    assert v2_floor.to_dict()["history_target_start"] == ENTITLEMENT_FLOOR

    official = CollectionCoverageContract.from_dict(
        "equities_master",
        _raw(
            history_target_start=OFFICIAL_START,
            not_historical_required_start=ENTITLEMENT_FLOOR,
            earliest_official_availability=OFFICIAL_START,
        ),
    )
    assert official.history_target_start == OFFICIAL_START
    assert official.not_historical_required_start == ENTITLEMENT_FLOOR
    assert official.history_target_start != official.not_historical_required_start


def test_loaded_catalog_keeps_json_history_target_start() -> None:
    master = coverage_contract_for("equities_master")
    assert master.history_target_start == OFFICIAL_START
    assert master.history_target_start != ENTITLEMENT_FLOOR
    assert master.vendor_data_provision_start == OFFICIAL_START
    assert master.not_historical_required_start is None
    assert master.earliest_official_availability is None
    assert master.official_mode is None

    am = coverage_contract_for("equities_bars_daily_am")
    assert am.history_target_start == "2024-01-04"
    assert am.vendor_history_policy == "recent_data_only"
    assert am.not_historical_required_start is None

    earnings = coverage_contract_for("equities_earnings_calendar")
    assert earnings.history_target_start == "2010-01-04"
    assert earnings.vendor_history_policy == "recent_data_only_next_business_day"
    assert earnings.earliest_official_availability is None
