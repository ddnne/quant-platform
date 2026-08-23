"""ResearchDataProfile v1 — digest-bound READY(P) predicate."""

from __future__ import annotations

import copy
import json

import pytest

from research.research_data_profile import (
    CORE_PROFILE_ID,
    CORE_REQUIRED_DATASETS,
    CORE_TIP_ONLY_EXCLUSIONS,
    PROFILE_VERSION,
    ResearchDataProfile,
    ResearchDataProfileError,
    TIP_ONLY_AM_DATASET,
    TIP_ONLY_EARNINGS_CALENDAR_DATASET,
    compute_digest,
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


def test_profile_ready_true_only_when_every_required_is_complete_official() -> None:
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
