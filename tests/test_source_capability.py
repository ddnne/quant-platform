"""Missing SourceCapability V3 rows are fail-closed, not invented COMPLETE."""

from __future__ import annotations

from pathlib import Path

import pytest

from data_contracts.canonical import governed_datasets
from data_contracts.coverage import (
    coverage_contract_for,
    coverage_policy_binding,
)
from data_contracts.source_capability import (
    all_source_capability_contracts,
    coverage_v3_dataset_ids,
    load_source_capability_dir,
    required_domain_subset_official,
    source_capability_contract_for,
    source_capability_contract_or_none,
    specs_dir,
)
from research.research_data_profile import (
    ResearchDataProfile,
    load_core_profile,
    official_mode,
    profile_ready,
)
from storage.coverage_ledger import evaluate_segment, plan_required_segments

_V3_DATASETS = coverage_v3_dataset_ids()
_NO_V3_DATASET = "indices_bars_daily"


def _complete_evidence(dataset_id: str) -> dict[str, str]:
    return {
        "status": "COMPLETE",
        "coverage_mode": official_mode(dataset_id),
        **dict(coverage_policy_binding(dataset_id)),
    }


def test_on_disk_v3_has_core_v1_plus_tip_and_otc_rows() -> None:
    on_disk = sorted(
        path.name
        for path in specs_dir().glob("*.json")
        if path.name != "schema.json"
    )
    assert on_disk == [
        "equities_bars_daily.json",
        "equities_bars_daily_am.json",
        "equities_earnings_calendar.json",
        "equities_master.json",
        "fins_details.json",
        "fins_dividend.json",
        "fins_earnings_date.json",
        "fins_summary.json",
        "indices_bars_daily_topix.json",
        "jsda_otc_bond_reference_prices.json",
        "markets_calendar.json",
    ]
    loaded = {contract.dataset_id for contract in all_source_capability_contracts()}
    assert loaded == _V3_DATASETS
    assert loaded == {name.removesuffix(".json") for name in on_disk}


def test_empty_dir_is_valid_and_does_not_invent_rows(tmp_path: Path) -> None:
    empty = tmp_path / "source_capability"
    empty.mkdir()
    assert dict(load_source_capability_dir(empty)) == {}
    assert dict(load_source_capability_dir(tmp_path / "absent")) == {}


def test_governed_datasets_without_v3_load_as_none() -> None:
    missing = []
    for dataset in governed_datasets():
        contract = source_capability_contract_or_none(dataset.dataset_id)
        if dataset.dataset_id in _V3_DATASETS:
            assert contract is not None
            assert contract.dataset_id == dataset.dataset_id
            continue
        assert contract is None
        missing.append(dataset.dataset_id)
        with pytest.raises(KeyError, match="unknown SourceCapabilityContract"):
            source_capability_contract_for(dataset.dataset_id)
    assert _NO_V3_DATASET in missing
    assert "equities_bars_daily" not in missing
    assert "fins_summary" not in missing
    assert missing


def test_plan_required_segments_without_v3_uses_coverage_json() -> None:
    assert source_capability_contract_or_none(_NO_V3_DATASET) is None
    with pytest.raises(TypeError, match="requires SourceCapabilityContract"):
        required_domain_subset_official(None)  # type: ignore[arg-type]

    policy = coverage_contract_for(_NO_V3_DATASET)
    assert policy.history_target_start == "2008-05-01"
    planned = plan_required_segments(policy, "2008-06-30")
    assert [segment.segment_id for segment in planned] == ["2008-05", "2008-06"]
    assert planned[0].segment_start == policy.history_target_start
    for segment in planned:
        assert segment.expected_scope["coverage_mode"] == policy.coverage_mode
        assert "earliest_official_availability" not in segment.expected_scope
        assert "history_mode" not in segment.expected_scope

    status, detail = evaluate_segment(policy, planned[0], None)
    assert status == "PARTIAL"
    assert status != "COMPLETE"
    assert detail["reason"] == "missing collection receipt"


def test_core_profile_has_source_capability_closure() -> None:
    profile = load_core_profile()
    missing_v3 = [
        dataset
        for dataset in profile.required_datasets
        if source_capability_contract_or_none(dataset) is None
    ]
    assert missing_v3 == []
    evidence = {
        dataset: _complete_evidence(dataset)
        for dataset in profile.required_datasets
    }
    assert profile_ready(profile, evidence) is True

    spec = profile.to_dict()
    spec.pop("profile_digest", None)
    spec["required_datasets"] = ["equities_master"]
    v3_profile = ResearchDataProfile.from_dict(spec)
    v3_evidence = {"equities_master": _complete_evidence("equities_master")}
    assert source_capability_contract_or_none("equities_master") is not None
    assert profile_ready(v3_profile, v3_evidence) is True

    spec["required_datasets"] = [_NO_V3_DATASET]
    missing_profile = ResearchDataProfile.from_dict(spec)
    missing_evidence = {_NO_V3_DATASET: _complete_evidence(_NO_V3_DATASET)}
    assert source_capability_contract_or_none(_NO_V3_DATASET) is None
    assert profile_ready(missing_profile, missing_evidence) is False
