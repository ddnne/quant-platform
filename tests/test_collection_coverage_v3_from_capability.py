"""collection_coverage.json V3 rows compile from SourceCapability JSON.

One SoT: specs/source_capability/*.json. Missing V3 stays None. Does not
invent COMPLETE 23, calendar-walk OTC, or claim live MCP FRESH.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from data_contracts.coverage import (
    COVERAGE_CONTRACT_PATH,
    POLICY_VERSION as COVERAGE_DOCUMENT_ROOT,
    coverage_contract_for,
)
from data_contracts.source_capability import (
    COLLECTION_COVERAGE_V3,
    all_source_capability_contracts,
    collection_coverage_v3_overrides,
    coverage_v3_dataset_ids,
    derive_collection_coverage_v3,
    required_domain_subset_official,
    source_capability_contract_or_none,
)
from qp_paths import repo_root
from storage.coverage_ledger import evaluate_segment, plan_required_segments

_FIXTURE = (
    repo_root() / "tests" / "fixtures" / "jsda_otc_official_index_tiny.html"
)
_MASTER = "equities_master"
_AM = "equities_bars_daily_am"
_EARNINGS = "equities_earnings_calendar"
_OTC = "jsda_otc_bond_reference_prices"
_NO_V3 = "fins_summary"
_MASTER_START = "2008-05-07"
_PARSE_ZERO = ("2002-08-02", "2002-08-05")
_WEEKEND = "2002-08-03"
_LISTED_TINY = ("2002-08-02", "2002-08-05", "2002-08-06")


def _coverage_json_merged(dataset_id: str) -> dict:
    document = json.loads(COVERAGE_CONTRACT_PATH.read_text(encoding="utf-8"))
    defaults = document["defaults"]
    row = document["datasets"][dataset_id]
    return {**defaults, "policy_version": document["policy_version"], **row}


def test_four_source_capability_contracts_load() -> None:
    loaded = all_source_capability_contracts()
    ids = coverage_v3_dataset_ids()
    assert ids == {contract.dataset_id for contract in loaded}
    assert ids == {_MASTER, _AM, _EARNINGS, _OTC}
    assert len(ids) == 4
    assert len(ids) != 23
    for dataset_id in sorted(ids):
        contract = source_capability_contract_or_none(dataset_id)
        assert contract is not None
        assert contract.dataset_id == dataset_id
        policy = coverage_contract_for(dataset_id)
        assert policy.policy_version == COLLECTION_COVERAGE_V3


def test_master_history_target_start_is_2008_05_07() -> None:
    contract = source_capability_contract_or_none(_MASTER)
    assert contract is not None
    derived = derive_collection_coverage_v3(contract)
    policy = coverage_contract_for(_MASTER)
    assert derived["history_target_start"] == _MASTER_START
    assert policy.history_target_start == _MASTER_START
    assert policy.history_target_start != "2006-08-13"
    assert contract.earliest_official_availability == _MASTER_START


def test_missing_v3_overrides_stay_none() -> None:
    assert source_capability_contract_or_none(_NO_V3) is None
    assert source_capability_contract_or_none("equities_bars_daily") is None
    assert collection_coverage_v3_overrides(_NO_V3) is None
    assert collection_coverage_v3_overrides("equities_bars_daily") is None
    assert collection_coverage_v3_overrides("does_not_exist") is None
    with pytest.raises(TypeError, match="requires SourceCapabilityContract"):
        derive_collection_coverage_v3(None)  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="requires SourceCapabilityContract"):
        required_domain_subset_official(None)  # type: ignore[arg-type]


def test_coverage_json_rows_equal_derived_v3() -> None:
    document = json.loads(COVERAGE_CONTRACT_PATH.read_text(encoding="utf-8"))
    assert document["policy_version"] == COVERAGE_DOCUMENT_ROOT
    assert COVERAGE_DOCUMENT_ROOT == "collection-coverage/v2"
    for contract in all_source_capability_contracts():
        derived = derive_collection_coverage_v3(contract)
        merged = _coverage_json_merged(contract.dataset_id)
        for key, value in derived.items():
            assert merged[key] == value, f"{contract.dataset_id}.{key}"
        policy = coverage_contract_for(contract.dataset_id)
        assert policy.policy_version == derived["policy_version"]
        assert policy.history_target_start == derived["history_target_start"]
        assert policy.history_mode == derived["history_mode"]
        assert policy.segment_granularity == derived["segment_granularity"]
        assert collection_coverage_v3_overrides(contract.dataset_id) == derived


def test_required_domain_subset_official_for_v3_rows() -> None:
    for contract in all_source_capability_contracts():
        domain = required_domain_subset_official(contract)
        policy = coverage_contract_for(contract.dataset_id)
        derived = derive_collection_coverage_v3(contract)
        assert policy.history_target_start >= domain.earliest_official_availability
        assert derived["history_target_start"] == domain.earliest_official_availability
        assert policy.history_mode == domain.history_mode
        assert policy.segment_granularity == domain.collection_window_grain
        if domain.tip_only_operational:
            assert domain.admit_historical_required_segments is False
            planned = plan_required_segments(policy, "2026-08-14")
            assert len(planned) == 1
            assert planned[0].segment_id == "2026-08-14"
            assert planned[0].segment_start >= domain.earliest_official_availability
            assert "2024-01" not in [seg.segment_id for seg in planned]
            assert "2010-01" not in [seg.segment_id for seg in planned]
        else:
            planned = plan_required_segments(
                policy,
                policy.history_target_start,
                source="jsda" if domain.publication_days_only else "jquants",
                index_text=None,
            )
            for seg in planned:
                assert seg.segment_start >= domain.earliest_official_availability


def test_am_and_earnings_are_tip_only() -> None:
    am = source_capability_contract_or_none(_AM)
    earnings = source_capability_contract_or_none(_EARNINGS)
    assert am is not None and earnings is not None
    am_domain = required_domain_subset_official(am)
    earn_domain = required_domain_subset_official(earnings)
    assert am.tip_only_operational is True
    assert earnings.tip_only_operational is True
    assert am.historical_research_eligible is False
    assert earnings.historical_research_eligible is False
    assert am_domain.admit_historical_required_segments is False
    assert earn_domain.admit_historical_required_segments is False
    assert am.history_mode == "recent_snapshot"
    assert earnings.history_mode == "next_business_day_snapshot"


def test_otc_required_set_is_official_index_not_calendar() -> None:
    contract = source_capability_contract_or_none(_OTC)
    assert contract is not None
    domain = required_domain_subset_official(contract)
    policy = coverage_contract_for(_OTC)
    assert domain.publication_days_only is True
    assert domain.tip_only_operational is False
    assert policy.segment_granularity == "official_archive_index_day"
    empty = plan_required_segments(policy, "2002-08-06", source="jsda")
    assert empty == ()
    html = _FIXTURE.read_text(encoding="utf-8")
    planned = plan_required_segments(
        policy, "2002-08-06", source="jsda", index_text=html,
    )
    ids = [seg.segment_id for seg in planned]
    assert ids == list(_LISTED_TINY)
    assert _WEEKEND not in ids
    assert len(ids) != 8784
    for day in _PARSE_ZERO:
        required = next(seg for seg in planned if seg.segment_id == day)
        status, _detail = evaluate_segment(policy, required, None)
        assert status == "PARTIAL"
        assert status != "COMPLETE"


def test_local_v3_does_not_claim_live_mcp_fresh() -> None:
    assert COVERAGE_DOCUMENT_ROOT == "collection-coverage/v2"
    assert COLLECTION_COVERAGE_V3 == "collection-coverage/v3"
    assert COVERAGE_DOCUMENT_ROOT != COLLECTION_COVERAGE_V3
    for contract in all_source_capability_contracts():
        policy = coverage_contract_for(contract.dataset_id)
        dumped = policy.to_dict()
        assert dumped.get("status") not in {"FRESH", "COMPLETE", "READY"}
        assert "FRESH" not in str(dumped)
        assert policy.policy_version == COLLECTION_COVERAGE_V3
    # Live projection remains V2 STALE until HUMAN refresh; this tree is local.
    assert Path(COVERAGE_CONTRACT_PATH).name == "collection_coverage.json"
