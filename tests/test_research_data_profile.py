"""ResearchDataProfile v1 — digest-bound READY(P) predicate."""

from __future__ import annotations

import copy
import json

import pytest

from data_contracts import COVERAGE_POLICY_VERSION, coverage_contract_for
from research.research_data_profile import (
    CORE_PROFILE_ID,
    CORE_REQUIRED_DATASETS,
    CORE_TIP_ONLY_EXCLUSIONS,
    COVERAGE_POLICY_DOCUMENT_ROOT,
    COVERAGE_POLICY_V3,
    COVERAGE_V3_DATASETS,
    PROFILE_VERSION,
    ResearchDataProfile,
    ResearchDataProfileError,
    TIP_ONLY_AM_DATASET,
    TIP_ONLY_EARNINGS_CALENDAR_DATASET,
    compute_digest,
    default_contract_versions,
    load_core_profile,
    official_mode,
    profile_ready,
    resolve_deps,
)


def _core_spec(**overrides: object) -> dict:
    spec = load_core_profile().to_dict()
    spec.pop("profile_digest", None)
    spec.update(overrides)
    return spec


def test_omit_dependency_fails() -> None:
    spec = _core_spec(
        feature_dependencies=[
            {
                "id": "am_session_return",
                "version": "1.0.0",
                "datasets": [TIP_ONLY_AM_DATASET],
            }
        ]
    )
    with pytest.raises(ResearchDataProfileError, match="omitted from required_datasets"):
        ResearchDataProfile.from_dict(spec)
    with pytest.raises(ResearchDataProfileError, match="omitted from required_datasets"):
        resolve_deps(spec)

    missing_features = _core_spec()
    missing_features.pop("feature_dependencies")
    with pytest.raises(ResearchDataProfileError, match="missing Deps category"):
        resolve_deps(missing_features)

    missing_required = _core_spec()
    missing_required.pop("required_datasets")
    with pytest.raises(ResearchDataProfileError, match="missing Deps category"):
        resolve_deps(missing_required)


def test_cannot_omit_earnings_calendar_when_strategy_lists_it() -> None:
    spec = _core_spec(
        strategy_dependencies=[
            {
                "strategy_id": "earnings_calendar_drift",
                "rule": {
                    "type": "top_k",
                    "feature": {
                        "id": "earnings_calendar_flag",
                        "version": "1.0.0",
                        "datasets_required": [TIP_ONLY_EARNINGS_CALENDAR_DATASET],
                    },
                    "k": 10,
                },
            }
        ]
    )
    with pytest.raises(ResearchDataProfileError, match="omitted from required_datasets"):
        ResearchDataProfile.from_dict(spec)


def test_tip_only_not_in_core() -> None:
    profile = load_core_profile()
    assert profile.profile_id == CORE_PROFILE_ID
    assert profile.profile_version == PROFILE_VERSION
    assert TIP_ONLY_AM_DATASET not in profile.required_datasets
    assert TIP_ONLY_EARNINGS_CALENDAR_DATASET not in profile.required_datasets
    for dataset in CORE_REQUIRED_DATASETS:
        assert dataset in profile.required_datasets
    assert "equities_master" in profile.required_datasets
    assert "equities_bars_daily" in profile.required_datasets
    assert "fins_summary" in profile.required_datasets
    assert "fins_details" in profile.required_datasets
    assert "fins_dividend" in profile.required_datasets
    assert "fins_earnings_date" in profile.required_datasets
    for dataset, reason in CORE_TIP_ONLY_EXCLUSIONS.items():
        assert dataset not in profile.required_datasets
        assert profile.excluded_datasets_and_reasons[dataset] == reason


def test_digest_stable() -> None:
    profile = load_core_profile()
    body = profile.to_canonical_dict()
    first = compute_digest(body)
    second = compute_digest(copy.deepcopy(body))
    shuffled = {
        "purpose": body["purpose"],
        "required_datasets": list(body["required_datasets"]),
        "profile_id": body["profile_id"],
        "contract_versions": dict(reversed(list(body["contract_versions"].items()))),
        "profile_version": body["profile_version"],
        "required_coverage_mode": body["required_coverage_mode"],
        "feature_dependencies": body["feature_dependencies"],
        "strategy_dependencies": body["strategy_dependencies"],
        "risk_dependencies": body["risk_dependencies"],
        "snapshot_cutoff": body["snapshot_cutoff"],
        "permitted_universe": body["permitted_universe"],
        "excluded_datasets_and_reasons": body["excluded_datasets_and_reasons"],
    }
    assert first == second
    assert first == compute_digest(shuffled)
    assert first == profile.profile_digest
    assert first == (
        "sha256:23508636bbdf8db439b1ecab968a62a4d5ce97970c82048345ab3ea63a9f9bd1"
    )
    assert first.startswith("sha256:")
    assert len(first) == len("sha256:") + 64
    reloaded = ResearchDataProfile.from_dict(profile.to_dict())
    assert reloaded.profile_digest == first


def test_profile_ready_false_when_required_dataset_is_partial() -> None:
    profile = load_core_profile()
    evidence = {
        dataset: {"status": "COMPLETE", "coverage_mode": official_mode(dataset)}
        for dataset in profile.required_datasets
    }
    evidence["equities_bars_daily"] = {
        "status": "PARTIAL",
        "coverage_mode": official_mode("equities_bars_daily"),
    }
    assert profile_ready(profile, evidence) is False
    assert profile_ready(profile, None) is False
    missing = {
        dataset: {"status": "COMPLETE", "coverage_mode": official_mode(dataset)}
        for dataset in profile.required_datasets
        if dataset != "fins_summary"
    }
    assert profile_ready(profile, missing) is False


def test_profile_ready_rejects_string_complete_labels() -> None:
    profile = load_core_profile()
    assert profile_ready(profile, {"equities_bars_daily": "COMPLETE"}) is False
    evidence = {
        dataset: {"status": "COMPLETE", "coverage_mode": official_mode(dataset)}
        for dataset in profile.required_datasets
    }
    evidence["equities_bars_daily"] = "COMPLETE"
    assert profile_ready(profile, evidence) is False


def test_profile_ready_true_only_when_every_required_is_complete_official() -> None:
    # Combinatorics only: synthetic COMPLETE is not a live READY publish.
    profile = load_core_profile()
    evidence = {
        dataset: {"status": "COMPLETE", "coverage_mode": official_mode(dataset)}
        for dataset in profile.required_datasets
    }
    assert profile_ready(profile, evidence) is True
    wrong_mode = dict(evidence)
    wrong_mode["markets_calendar"] = {
        "status": "COMPLETE",
        "coverage_mode": "not-official",
    }
    assert profile_ready(profile, wrong_mode) is False


def test_listed_dataset_constructs_when_required_includes_it() -> None:
    spec = _core_spec(
        required_datasets=list(CORE_REQUIRED_DATASETS) + [TIP_ONLY_AM_DATASET],
        feature_dependencies=[
            {
                "id": "am_session_return",
                "version": "1.0.0",
                "datasets": [TIP_ONLY_AM_DATASET],
            }
        ],
        excluded_datasets_and_reasons={
            TIP_ONLY_EARNINGS_CALENDAR_DATASET: CORE_TIP_ONLY_EXCLUSIONS[
                TIP_ONLY_EARNINGS_CALENDAR_DATASET
            ]
        },
    )
    profile = ResearchDataProfile.from_dict(spec)
    assert TIP_ONLY_AM_DATASET in profile.required_datasets
    assert TIP_ONLY_AM_DATASET in resolve_deps(spec)


def test_core_json_round_trip_without_live_ready_publish() -> None:
    profile = load_core_profile()
    dumped = json.dumps(profile.to_canonical_dict(), sort_keys=True)
    assert TIP_ONLY_AM_DATASET not in json.loads(dumped)["required_datasets"]
    assert "READY" not in dumped
    assert profile.required_coverage_mode == "official"
    assert profile.contract_versions["coverage_policy"] == COVERAGE_POLICY_DOCUMENT_ROOT


def test_core_coverage_policy_is_mixed_document_root_not_uniform_v3() -> None:
    profile = load_core_profile()
    assert COVERAGE_POLICY_VERSION == COVERAGE_POLICY_DOCUMENT_ROOT
    assert profile.contract_versions["coverage_policy"] == COVERAGE_POLICY_DOCUMENT_ROOT
    assert default_contract_versions()["coverage_policy"] == COVERAGE_POLICY_DOCUMENT_ROOT
    assert profile.contract_versions["coverage_policy"] != COVERAGE_POLICY_V3

    for dataset_id in COVERAGE_V3_DATASETS:
        contract = coverage_contract_for(dataset_id)
        assert contract.policy_version == COVERAGE_POLICY_V3
        assert official_mode(dataset_id) == contract.coverage_mode
    assert official_mode("equities_master") == "scd2_event_sourcing"
    assert official_mode(TIP_ONLY_AM_DATASET) == "recent_snapshot"
    assert official_mode(TIP_ONLY_EARNINGS_CALENDAR_DATASET) == (
        "next_business_day_snapshot"
    )

    for dataset_id in CORE_REQUIRED_DATASETS:
        contract = coverage_contract_for(dataset_id)
        assert official_mode(dataset_id) == contract.coverage_mode
        if dataset_id in COVERAGE_V3_DATASETS:
            assert contract.policy_version == COVERAGE_POLICY_V3
        else:
            assert contract.policy_version == COVERAGE_POLICY_DOCUMENT_ROOT


def test_profile_ready_false_on_stale_v2_live_evidence() -> None:
    profile = load_core_profile()
    # Live MCP: projection STALE, applied_cursor null, master PARTIAL under
    # collection-coverage/v2 2006-08-13 floor (not local v3 2008-05-07).
    evidence = {
        dataset: {"status": "COMPLETE", "coverage_mode": official_mode(dataset)}
        for dataset in profile.required_datasets
    }
    evidence["equities_master"] = {
        "status": "PARTIAL",
        "coverage_mode": official_mode("equities_master"),
        "policy_version": "collection-coverage/v2",
        "history_target_start": "2006-08-13",
        "projection_status": "STALE",
        "applied_cursor": None,
    }
    assert profile_ready(profile, evidence) is False

    stale_complete = {
        dataset: {
            "status": "COMPLETE",
            "coverage_mode": official_mode(dataset),
            "projection_status": "STALE",
            "applied_cursor": None,
        }
        for dataset in profile.required_datasets
    }
    assert profile_ready(profile, stale_complete) is False
    unpinned = {
        dataset: {
            "status": "COMPLETE",
            "coverage_mode": official_mode(dataset),
            "applied_cursor": None,
        }
        for dataset in profile.required_datasets
    }
    assert profile_ready(profile, unpinned) is False
