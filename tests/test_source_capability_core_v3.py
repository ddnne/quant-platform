"""Phase 6.3.1 P0-C: official core V3 domain and meta-index authority."""

from __future__ import annotations

import json

from cf_platform.ingest_premium.coverage import EXPECTED_START
from data_contracts.canonical import (
    CANONICAL_REGISTRY_PATH,
    canonical_dataset_for,
    validate_derived_metadata,
)
from data_contracts.coverage import COVERAGE_CONTRACT_PATH, coverage_contract_for
from data_contracts.loader import contract_for
from data_contracts.source_capability import (
    all_source_capability_contracts,
    derive_collection_coverage_v3,
    source_capability_contract_for,
    specs_dir,
)
from qp_paths import repo_root

_CORE_V1 = {
    "equities_master",
    "equities_bars_daily",
    "fins_details",
    "fins_dividend",
    "fins_earnings_date",
    "fins_summary",
    "markets_calendar",
}
_OFFICIAL_STARTS = {
    "equities_master": "2008-05-07",
    "equities_bars_daily": "2008-05-07",
    "fins_summary": "2008-07-07",
    "fins_details": "2009-01-13",
    "fins_dividend": "2013-02-20",
    "fins_earnings_date": "2014-09-01",
    "markets_calendar": "2008-01-01",
}
_EVENT_ROWS = {
    "fins_summary",
    "fins_details",
    "fins_dividend",
    "fins_earnings_date",
}


def test_core_v1_has_exact_official_source_capability_boundaries() -> None:
    profile = json.loads(
        (repo_root() / "specs" / "research_profiles" / "core_v1.json").read_text(
            encoding="utf-8"
        )
    )
    assert set(profile["required_datasets"]) == _CORE_V1
    for dataset_id, official_start in _OFFICIAL_STARTS.items():
        capability = source_capability_contract_for(dataset_id)
        endpoint = contract_for(dataset_id)
        assert capability.earliest_official_availability == official_start
        assert capability.upstream_locator == endpoint.path
        assert set(endpoint.params) <= set(capability.supported_query_parameters)
        assert capability.official_evidence_url.startswith(
            "https://jpx-jquants.com/en/spec/"
        )


def test_exact_four_dependency_profile_has_no_source_capability_gap() -> None:
    from research.ready_manifest import load_exact_four_pilot_ready_binding

    binding = load_exact_four_pilot_ready_binding()
    assert "indices_bars_daily_topix" in binding.required_datasets
    assert all(
        source_capability_contract_for(dataset_id).dataset_id == dataset_id
        for dataset_id in binding.required_datasets
    )


def test_production_validation_uses_governed_coverage_starts() -> None:
    """C6/C7 cannot retain a second V2-era start-date authority."""
    for dataset_id in EXPECTED_START:
        assert EXPECTED_START[dataset_id] == coverage_contract_for(
            dataset_id
        ).history_target_start


def test_earnings_date_uses_official_2014_start_not_observed_2018_floor() -> None:
    dataset_id = "fins_earnings_date"
    capability = source_capability_contract_for(dataset_id)
    coverage = coverage_contract_for(dataset_id)
    canonical = canonical_dataset_for(dataset_id)
    raw = json.loads(
        (specs_dir() / f"{dataset_id}.json").read_text(encoding="utf-8")
    )
    assert capability.earliest_official_availability == "2014-09-01"
    assert coverage.history_target_start == "2014-09-01"
    assert canonical.historical_start == "2014-09-01"
    assert raw["entitlement_semantics"]["rejected_observed_floor"] == "2018-01-01"
    assert raw["publication_calendar"]["official_history_evidence_url"] == (
        "https://jpx-jquants.com/en/spec/data-spec"
    )


def test_per_row_required_domain_semantics_are_frozen() -> None:
    expected = {
        "equities_master": (
            "calendar_months_from_official_start",
            "never_complete",
        ),
        "equities_bars_daily": (
            "calendar_months_from_official_start",
            "never_complete",
        ),
        "indices_bars_daily_topix": (
            "calendar_months_from_official_start",
            "never_complete",
        ),
        "equities_bars_daily_am": (
            "issued_same_trading_day_snapshot",
            "never_complete",
        ),
        "equities_earnings_calendar": (
            "issued_collection_cutoff_snapshot",
            "never_complete",
        ),
        "markets_calendar": (
            "calendar_months_from_official_start",
            "never_complete",
        ),
        "jsda_otc_bond_reference_prices": (
            "official_archive_publication_days",
            "never_complete",
        ),
        **{
            dataset_id: (
                "publication_windows_from_official_start",
                "trusted_exhausted_receipt_may_complete",
            )
            for dataset_id in _EVENT_ROWS
        },
    }
    assert {c.dataset_id for c in all_source_capability_contracts()} == set(expected)
    for dataset_id, (basis, empty_policy) in expected.items():
        capability = source_capability_contract_for(dataset_id)
        coverage = coverage_contract_for(dataset_id)
        assert capability.required_domain_semantics.basis == basis
        assert capability.required_domain_semantics.empty_success_policy == empty_policy
        assert coverage.required_domain_basis == basis
        assert coverage.empty_success_policy == empty_policy
        assert derive_collection_coverage_v3(capability) == {
            "policy_version": coverage.policy_version,
            "history_target_start": coverage.history_target_start,
            "history_mode": coverage.history_mode,
            "segment_granularity": coverage.segment_granularity,
            "required_domain_basis": coverage.required_domain_basis,
            "empty_success_policy": coverage.empty_success_policy,
        }


def test_tip_cutoff_master_and_otc_publication_semantics_are_explicit() -> None:
    am = json.loads(
        (specs_dir() / "equities_bars_daily_am.json").read_text(encoding="utf-8")
    )
    earnings = json.loads(
        (specs_dir() / "equities_earnings_calendar.json").read_text(
            encoding="utf-8"
        )
    )
    master = json.loads(
        (specs_dir() / "equities_master.json").read_text(encoding="utf-8")
    )
    otc = json.loads(
        (specs_dir() / "jsda_otc_bond_reference_prices.json").read_text(
            encoding="utf-8"
        )
    )
    assert am["publication_calendar"]["issuance_scope"] == "same_trading_day_only"
    assert am["publication_calendar"]["official_update_around"] == "12:00"
    assert earnings["publication_calendar"]["issuance_scope"] == (
        "next_business_day_only"
    )
    assert "collection cutoff" in earnings["publication_calendar"][
        "cutoff_semantics"
    ]
    assert master["earliest_official_availability"] == "2008-05-07"
    assert otc["publication_calendar"]["publication_days_only"] is True
    assert "publication day" in otc["publication_calendar"][
        "publication_label_semantics"
    ]
    assert otc["freshness_sla"]["expected_after"] == "17:30"
    assert otc["freshness_sla"]["usable_by"] == "18:30"


def test_static_v3_contracts_mint_no_coverage_status() -> None:
    document = json.loads(COVERAGE_CONTRACT_PATH.read_text(encoding="utf-8"))
    for capability in all_source_capability_contracts():
        row = document["datasets"][capability.dataset_id]
        assert "status" not in row
        assert "complete" not in row
        source_raw = json.loads(
            (specs_dir() / f"{capability.dataset_id}.json").read_text(
                encoding="utf-8"
            )
        )
        assert "status" not in source_raw
        if "dataset_complete_claim" in source_raw["research_profile_eligibility"]:
            assert (
                source_raw["research_profile_eligibility"]["dataset_complete_claim"]
                is False
            )


def test_canonical_is_meta_index_without_duplicate_authority_fields() -> None:
    validate_derived_metadata()
    raw_rows = json.loads(
        CANONICAL_REGISTRY_PATH.read_text(encoding="utf-8")
    )["datasets"]
    forbidden = {
        "available_at",
        "collection_window",
        "coverage_segment_granularity",
        "expected_frequency",
        "historical_start",
        "natural_key_fields",
        "research_eligible",
    }
    assert all(forbidden.isdisjoint(row) for row in raw_rows)
    for dataset_id in _OFFICIAL_STARTS:
        canonical = canonical_dataset_for(dataset_id)
        coverage = coverage_contract_for(dataset_id)
        capability = source_capability_contract_for(dataset_id)
        primary = contract_for(dataset_id)
        assert canonical.natural_key_fields == primary.natural_key_fields
        assert canonical.historical_start == coverage.history_target_start
        assert (
            canonical.coverage_segment_granularity
            == coverage.segment_granularity
        )
        assert canonical.expected_frequency == coverage.expected_frequency
        assert canonical.research_eligible == (
            capability.historical_research_eligible
        )
        assert canonical.available_at == capability.available_at
