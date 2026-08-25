"""SourceCapabilityContract v3 — fail-closed official-availability SoT."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from data_contracts.source_capability import (
    COLLECTION_COVERAGE_V3,
    EMPTY_SUCCESS_POLICIES,
    HISTORY_MODES,
    POLICY_VERSION,
    REQUIRED_DOMAIN_BASES,
    SCHEMA_PATH,
    SourceCapabilityContract,
    all_source_capability_contracts,
    collection_coverage_v3_overrides,
    derive_collection_coverage_v3,
    load_source_capability_dir,
    parse_source_capability_document,
    required_domain_subset_official,
    source_capability_contract_for,
    source_capability_contract_or_none,
    specs_dir,
)

_NESTED_EVIDENCE_FIELDS = (
    "publication_calendar",
    "entitlement_semantics",
    "collection_window",
    "freshness_sla",
    "event_time",
    "available_at",
    "revision_semantics",
    "research_profile_eligibility",
    "required_domain_semantics",
)


def _payload(**overrides: object) -> dict:
    body: dict = {
        "dataset_id": "equities_bars_daily",
        "source": "jquants",
        "upstream_locator": "/v2/equities/bars/daily",
        "official_evidence_url": "https://jpx-jquants.com/en/spec/eq-bars-daily",
        "history_mode": "bounded_history",
        "earliest_official_availability": "2008-05-07",
        "historical_research_eligible": True,
        "tip_only_operational": False,
        "supported_query_parameters": ["code", "from", "to"],
        "publication_calendar": {
            "kind": "trading_day",
            "timezone": "Asia/Tokyo",
        },
        "entitlement_semantics": {
            "clamp_before_earliest": True,
            "subscription_floor": None,
        },
        "collection_window": {
            "grain": "calendar_month",
            "open": "session_open",
            "close": "session_close",
        },
        "freshness_sla": {
            "expected_after": "15:00",
            "usable_by": "16:00",
            "timezone": "Asia/Tokyo",
            "rule": "session_close",
        },
        "event_time": {"policy": "session_close", "fields": ["Date"]},
        "available_at": {
            "policy": "session_close",
            "field": "Date",
            "known_publication_lag": None,
        },
        "revision_semantics": {
            "policy": "new_revision_available_no_earlier_than_ingest",
            "generation_on_revision": True,
        },
        "research_profile_eligibility": {
            "include_in": ["core_historical"],
            "exclude_from": [],
            "exclusion_reason": "none",
        },
        "required_domain_semantics": {
            "basis": "calendar_months_from_official_start",
            "empty_success_policy": "never_complete",
        },
    }
    body.update(overrides)
    return body


def test_policy_version_is_v3() -> None:
    assert POLICY_VERSION == "source-capability/v3"
    assert SCHEMA_PATH.is_file()
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    assert schema["$id"] == "source-capability/v3"
    assert set(schema["$defs"]["dataset"]["properties"]["history_mode"]["enum"]) == HISTORY_MODES
    assert set(schema["$defs"]["required_domain_semantics"]["properties"]["basis"]["enum"]) == REQUIRED_DOMAIN_BASES
    assert set(schema["$defs"]["required_domain_semantics"]["properties"]["empty_success_policy"]["enum"]) == EMPTY_SUCCESS_POLICIES
    for name in _NESTED_EVIDENCE_FIELDS:
        assert schema["$defs"][name].get("additionalProperties", True) is not False
    assert schema["$defs"]["dataset"]["additionalProperties"] is False
    assert schema["$defs"]["bundle"]["additionalProperties"] is False


def test_unknown_dataset_level_keys_fail() -> None:
    with pytest.raises(ValueError, match="unknown field"):
        SourceCapabilityContract.from_dict({**_payload(), "go": True})
    with pytest.raises(ValueError, match="unknown field"):
        SourceCapabilityContract.from_dict({**_payload(), "complete": True})
    with pytest.raises(ValueError, match="unknown field"):
        SourceCapabilityContract.from_dict({**_payload(), "invented_sot": True})


def test_extra_nested_evidence_keys_do_not_fail_load() -> None:
    nested = _payload()
    for field in _NESTED_EVIDENCE_FIELDS:
        nested[field] = {**nested[field], "invented_evidence": "x"}
    contract = SourceCapabilityContract.from_dict(nested)
    assert contract.dataset_id == "equities_bars_daily"
    assert contract.publication_calendar.kind == "trading_day"

    # Existing on-disk rows include extra official-evidence notes.
    loaded = load_source_capability_dir()
    assert loaded["equities_master"].earliest_official_availability == "2008-05-07"
    assert loaded["jsda_otc_bond_reference_prices"].history_mode == "official_archive_index"


def test_core_v1_v3_files_are_present_and_unknown_stays_none() -> None:
    assert source_capability_contract_or_none("does_not_exist") is None
    present = {contract.dataset_id for contract in all_source_capability_contracts()}
    assert {
        "equities_bars_daily",
        "fins_details",
        "fins_dividend",
        "fins_earnings_date",
        "fins_summary",
        "markets_calendar",
    } <= present
    with pytest.raises(KeyError, match="unknown SourceCapabilityContract"):
        source_capability_contract_for("does_not_exist")


def test_missing_dataset_id_rejected() -> None:
    raw = _payload()
    del raw["dataset_id"]
    with pytest.raises(ValueError, match="missing dataset_id"):
        SourceCapabilityContract.from_dict(raw)


def test_history_mode_enum_enforced() -> None:
    with pytest.raises(ValueError, match="history_mode"):
        SourceCapabilityContract.from_dict(_payload(history_mode="full_history"))
    with pytest.raises(ValueError, match="history_mode"):
        SourceCapabilityContract.from_dict(_payload(history_mode="COMPLETE"))
    valid = {
        "bounded_history": {},
        "event_stream": {
            "required_domain_semantics": {
                "basis": "publication_windows_from_official_start",
                "empty_success_policy": "trusted_exhausted_receipt_may_complete",
            },
        },
        "recent_snapshot": {
            "historical_research_eligible": False,
            "tip_only_operational": True,
            "collection_window": {
                "grain": "same_trading_day_am_snapshot",
                "open": "09:00",
                "close": "11:30",
            },
            "required_domain_semantics": {
                "basis": "issued_same_trading_day_snapshot",
                "empty_success_policy": "never_complete",
            },
        },
        "next_business_day_snapshot": {
            "historical_research_eligible": False,
            "tip_only_operational": True,
            "collection_window": {
                "grain": "collection_cutoff_snapshot",
                "open": "generation",
                "close": "cutoff",
            },
            "required_domain_semantics": {
                "basis": "issued_collection_cutoff_snapshot",
                "empty_success_policy": "never_complete",
            },
        },
        "official_archive_index": {
            "collection_window": {
                "grain": "official_archive_index_day",
                "open": "first_index_day",
                "close": "latest_index_day",
            },
            "required_domain_semantics": {
                "basis": "official_archive_publication_days",
                "empty_success_policy": "never_complete",
            },
        },
        "periodic_archive": {
            "collection_window": {
                "grain": "official_archive_year",
                "open": "first_archive",
                "close": "latest_archive",
            },
            "required_domain_semantics": {
                "basis": "official_archive_periods",
                "empty_success_policy": "never_complete",
            },
        },
    }
    assert set(valid) == HISTORY_MODES
    for mode, overrides in valid.items():
        contract = SourceCapabilityContract.from_dict(
            _payload(history_mode=mode, **overrides)
        )
        assert contract.history_mode == mode


def test_required_domain_semantics_fail_closed() -> None:
    with pytest.raises(ValueError, match="requires history_mode"):
        SourceCapabilityContract.from_dict(
            _payload(
                required_domain_semantics={
                    "basis": "publication_windows_from_official_start",
                    "empty_success_policy": "never_complete",
                }
            )
        )
    with pytest.raises(ValueError, match="empty SUCCESS must never COMPLETE"):
        SourceCapabilityContract.from_dict(
            _payload(
                history_mode="recent_snapshot",
                historical_research_eligible=False,
                tip_only_operational=True,
                collection_window={
                    "grain": "same_trading_day_am_snapshot",
                    "open": "09:00",
                    "close": "11:30",
                },
                required_domain_semantics={
                    "basis": "issued_same_trading_day_snapshot",
                    "empty_success_policy": "trusted_exhausted_receipt_may_complete",
                },
            )
        )


def test_empty_specs_dir_loads_empty(tmp_path: Path) -> None:
    empty = tmp_path / "source_capability"
    empty.mkdir()
    loaded = load_source_capability_dir(empty)
    assert dict(loaded) == {}
    missing = load_source_capability_dir(tmp_path / "absent")
    assert dict(missing) == {}
    assert specs_dir() == Path(__file__).resolve().parents[1] / "specs" / "source_capability"
    # Repo dir may be empty; import-time registry must still exist.
    all_source_capability_contracts()
    with pytest.raises(KeyError, match="unknown SourceCapabilityContract"):
        source_capability_contract_for("does_not_exist")


def test_loader_reads_json_and_skips_schema(tmp_path: Path) -> None:
    root = tmp_path / "source_capability"
    root.mkdir()
    (root / "schema.json").write_text("{}", encoding="utf-8")
    (root / "bars.json").write_text(
        json.dumps(_payload()), encoding="utf-8"
    )
    bundle = {
        "policy_version": POLICY_VERSION,
        "schema_version": 3,
        "datasets": [
            _payload(
                dataset_id="equities_earnings_calendar",
                history_mode="next_business_day_snapshot",
                historical_research_eligible=False,
                tip_only_operational=True,
                collection_window={
                    "grain": "collection_cutoff_snapshot",
                    "open": "generation",
                    "close": "cutoff",
                },
                required_domain_semantics={
                    "basis": "issued_collection_cutoff_snapshot",
                    "empty_success_policy": "never_complete",
                },
            )
        ],
    }
    (root / "bundle.json").write_text(json.dumps(bundle), encoding="utf-8")
    loaded = load_source_capability_dir(root)
    assert set(loaded) == {"equities_bars_daily", "equities_earnings_calendar"}


def test_required_domain_subset_official() -> None:
    bounded = SourceCapabilityContract.from_dict(_payload())
    domain = required_domain_subset_official(bounded)
    assert domain.policy_version == POLICY_VERSION
    assert domain.admit_historical_required_segments is True
    assert domain.publication_days_only is False
    assert domain.earliest_official_availability == "2008-05-07"
    assert domain.required_domain_basis == "calendar_months_from_official_start"
    assert domain.empty_success_policy == "never_complete"

    tip = SourceCapabilityContract.from_dict(
        _payload(
            dataset_id="equities_earnings_calendar",
            history_mode="next_business_day_snapshot",
            historical_research_eligible=False,
            tip_only_operational=True,
            collection_window={
                "grain": "collection_cutoff_snapshot",
                "open": "generation",
                "close": "cutoff",
            },
            required_domain_semantics={
                "basis": "issued_collection_cutoff_snapshot",
                "empty_success_policy": "never_complete",
            },
        )
    )
    tip_domain = required_domain_subset_official(tip)
    assert tip_domain.admit_historical_required_segments is False
    assert tip_domain.tip_only_operational is True

    index = SourceCapabilityContract.from_dict(
        _payload(
            dataset_id="jsda_otc_bond_reference_prices",
            source="jsda",
            history_mode="official_archive_index",
            collection_window={
                "grain": "official_archive_index_day",
                "open": "first_index_day",
                "close": "latest_index_day",
            },
            required_domain_semantics={
                "basis": "official_archive_publication_days",
                "empty_success_policy": "never_complete",
            },
        )
    )
    index_domain = required_domain_subset_official(index)
    assert index_domain.publication_days_only is True
    assert index_domain.admit_historical_required_segments is True


def test_derive_collection_coverage_v3_from_capability() -> None:
    bounded = SourceCapabilityContract.from_dict(_payload())
    derived = derive_collection_coverage_v3(bounded)
    assert derived["policy_version"] == COLLECTION_COVERAGE_V3
    assert derived["history_target_start"] == "2008-05-07"
    assert derived["history_mode"] == "bounded_history"
    assert derived["segment_granularity"] == "calendar_month"
    with pytest.raises(TypeError, match="requires SourceCapabilityContract"):
        derive_collection_coverage_v3({"dataset_id": "equities_bars_daily"})
    assert collection_coverage_v3_overrides("fins_summary") == {
        "policy_version": COLLECTION_COVERAGE_V3,
        "history_target_start": "2008-07-07",
        "history_mode": "event_stream",
        "segment_granularity": "calendar_month",
        "required_domain_basis": "publication_windows_from_official_start",
        "empty_success_policy": "trusted_exhausted_receipt_may_complete",
    }


def test_module_docstring_states_planner_authority() -> None:
    from data_contracts import source_capability as mod

    src = Path(mod.__file__).read_text(encoding="utf-8")
    header = src.split('"""', 2)[1]
    assert "does not rewrite" not in header
    assert "official-availability" in header
    assert "plan_required_segments" in header
    assert "required_domain_subset_official" in header
    assert "MUST subset official" in header
    assert "specs/source_capability" in header
    assert "not invented" in header
    assert "Nested evidence maps remain open" in header
    assert "dataset-level keys are closed" in header


def test_bundle_unknown_field_and_wrong_policy_rejected() -> None:
    with pytest.raises(ValueError, match="unknown field"):
        parse_source_capability_document(
            {
                "policy_version": POLICY_VERSION,
                "datasets": [_payload()],
                "ready": True,
            }
        )
    with pytest.raises(ValueError, match="policy_version"):
        parse_source_capability_document(
            {"policy_version": "source-capability/v2", "datasets": [_payload()]}
        )
