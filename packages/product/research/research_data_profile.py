"""Versioned ResearchDataProfile — digest-bound READY(P) predicate.

READY(P) = AND Complete(d, official_mode(d)) for d in Deps(P).
Deps(P) = transitive StrategySpec + FeatureRef + Universe + Evaluation
protocol + Risk inputs.

official_mode(d) is coverage_contract_for(d).coverage_mode (per-dataset), not
contract_versions.coverage_policy. That key is the collection_coverage.json
document root (collection-coverage/v2). SourceCapability JSON rows overlay
collection-coverage/v3 on their coverage catalog entries. Do not bump the
profile key to v3 while live MCP projection is STALE V2. A
FeatureRef/StrategySpec that lists a dataset must include that dataset in
required_datasets or construction fails. Core does not unconditionally
include tip-only AM bars or earnings calendar. This module does not publish
READY, arm Mass, or start Phase 7.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from data_contracts import (
    COLLECTION_COVERAGE_V3,
    COVERAGE_POLICY_VERSION,
    JSDA_CONTRACT_VERSION,
    REGISTRY_VERSION,
    canonical_dataset_for,
    coverage_contract_for,
    coverage_v3_dataset_ids,
    source_capability_contract_or_none,
)
from qp_paths import repo_root
from research.evaluation_ir import EVALUATION_IR_VERSION
from strategies.spec import FeatureRef, STRATEGY_SPEC_VERSION, StrategySpec

PROFILE_VERSION: str = "research-data-profile/v1"
CORE_PROFILE_ID: str = "core"
CORE_PROFILE_REL: Path = Path("specs") / "research_profiles" / "core_v1.json"
REQUIRED_COVERAGE_MODE_OFFICIAL: str = "official"

# Tip-only residuals. Core historical research must not require these unless a
# FeatureRef/StrategySpec lists them (construction then fails if omitted).
TIP_ONLY_AM_DATASET: str = "equities_bars_daily_am"
TIP_ONLY_EARNINGS_CALENDAR_DATASET: str = "equities_earnings_calendar"
CORE_TIP_ONLY_EXCLUSIONS: Mapping[str, str] = {
    TIP_ONLY_AM_DATASET: (
        "PD-D4-BARS-AM tip-only AM bars; history DEFER; not a core historical input"
    ),
    TIP_ONLY_EARNINGS_CALENDAR_DATASET: (
        "PD-D4-EARN-CAL vendor tip-only earnings calendar; use fins_earnings_date"
    ),
}

# Governed historical-research baseline. equities_master is PIT listed-name
# membership from official 2008-05-07. fins_* here are history-eligible names;
# earnings calendar is excluded (see CORE_TIP_ONLY_EXCLUSIONS).
CORE_REQUIRED_DATASETS: tuple[str, ...] = (
    "equities_master",
    "equities_bars_daily",
    "fins_details",
    "fins_dividend",
    "fins_earnings_date",
    "fins_summary",
    "markets_calendar",
)

# Document-root policy. Per-dataset V3 ids come from SourceCapability JSON,
# not a second hand list. core_v1.json contract_versions.coverage_policy stays
# v2; live MCP is STALE V2 with applied_cursor null and is not a READY publish.
COVERAGE_POLICY_DOCUMENT_ROOT: str = "collection-coverage/v2"
COVERAGE_POLICY_V3: str = COLLECTION_COVERAGE_V3
COVERAGE_V3_DATASETS: frozenset[str] = coverage_v3_dataset_ids()

_PROFILE_FIELDS: frozenset[str] = frozenset(
    {
        "profile_id",
        "profile_version",
        "profile_digest",
        "purpose",
        "required_datasets",
        "required_coverage_mode",
        "contract_versions",
        "feature_dependencies",
        "strategy_dependencies",
        "risk_dependencies",
        "snapshot_cutoff",
        "permitted_universe",
        "excluded_datasets_and_reasons",
    }
)
_DEPS_REQUIRED_KEYS: tuple[str, ...] = (
    "required_datasets",
    "feature_dependencies",
    "strategy_dependencies",
    "risk_dependencies",
    "permitted_universe",
    "contract_versions",
)
_DATASET_LIST_KEYS: tuple[str, ...] = (
    "datasets",
    "datasets_required",
    "required_datasets",
)
_FEATURE_REF_KEYS: tuple[str, ...] = (
    "feature",
    "value_feature",
    "momentum_feature",
)
_CONTRACT_VERSION_REQUIRED: tuple[str, ...] = (
    "canonical_registry",
    "coverage_policy",
    "evaluation_ir",
    "strategy_spec",
)


class ResearchDataProfileError(ValueError):
    """Raised when a ResearchDataProfile spec is incomplete or inconsistent."""


def official_mode(dataset_id: str) -> str:
    """Per-dataset coverage_mode from ``coverage_contract_for``.

    READY(P) requires this mode. It is not SourceCapabilityContract and not
    ``contract_versions.coverage_policy`` (document-root collection-coverage/v2).
    """
    return coverage_contract_for(dataset_id).coverage_mode


def compute_digest(payload: Mapping[str, Any]) -> str:
    """Canonical JSON SHA-256 of a profile body (excludes ``profile_digest``)."""
    raw = _canonical_json(payload).encode("utf-8")
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def resolve_deps(spec: Mapping[str, Any] | ResearchDataProfile) -> tuple[str, ...]:
    """Return Deps(P) dataset ids. Fail-closed if a required category is missing.

    Listed FeatureRef/StrategySpec datasets must already appear in
    ``required_datasets``; they are not silently added.
    """
    payload = spec.to_dict() if isinstance(spec, ResearchDataProfile) else spec
    if not isinstance(payload, Mapping):
        raise ResearchDataProfileError("profile spec must be an object")
    missing = [key for key in _DEPS_REQUIRED_KEYS if key not in payload]
    if missing:
        raise ResearchDataProfileError(
            f"profile spec missing Deps category: {missing}"
        )

    required = _require_dataset_ids(payload.get("required_datasets"), "required_datasets")
    required_set = set(required)

    listed = _datasets_listed_on_deps(payload)
    omitted = sorted(listed - required_set)
    if omitted:
        raise ResearchDataProfileError(
            "FeatureRef/StrategySpec listed dataset(s) omitted from "
            f"required_datasets: {omitted}"
        )

    universe = _require_str_tuple(payload.get("permitted_universe"), "permitted_universe")
    if not universe:
        raise ResearchDataProfileError("permitted_universe must be non-empty")

    risk = _require_str_tuple(payload.get("risk_dependencies"), "risk_dependencies")
    if not risk:
        raise ResearchDataProfileError("risk_dependencies must be non-empty")

    _require_feature_deps(payload.get("feature_dependencies"))
    _require_strategy_deps(payload.get("strategy_dependencies"))
    _evaluation_protocol(payload.get("contract_versions"))
    return required


def profile_ready(
    profile: ResearchDataProfile,
    evidence_by_dataset: Mapping[str, Any] | None,
) -> bool:
    """True iff every required dataset is COMPLETE under official_mode(d).

    Missing SourceCapability V3, missing evidence, PARTIAL, a string
    COMPLETE label, a coverage_mode other than official_mode,
    projection_status STALE, or applied_cursor null is false. Missing V3
    is not official-complete. Does not publish a READY snapshot.
    """
    if not profile.required_datasets:
        return False
    if not isinstance(evidence_by_dataset, Mapping):
        return False
    for dataset in profile.required_datasets:
        if not _complete_under_official(dataset, evidence_by_dataset):
            return False
    return True


@dataclass(frozen=True)
class ResearchDataProfile:
    """Closed, digest-bound research data profile. Not a live READY publish."""

    profile_id: str
    profile_version: str
    profile_digest: str
    purpose: str
    required_datasets: tuple[str, ...]
    required_coverage_mode: str
    contract_versions: Mapping[str, str]
    feature_dependencies: tuple[Mapping[str, Any], ...]
    strategy_dependencies: tuple[Mapping[str, Any], ...]
    risk_dependencies: tuple[str, ...]
    snapshot_cutoff: str | None
    permitted_universe: tuple[str, ...]
    excluded_datasets_and_reasons: Mapping[str, str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "profile_id": self.profile_id,
            "profile_version": self.profile_version,
            "profile_digest": self.profile_digest,
            "purpose": self.purpose,
            "required_datasets": list(self.required_datasets),
            "required_coverage_mode": self.required_coverage_mode,
            "contract_versions": dict(self.contract_versions),
            "feature_dependencies": [dict(item) for item in self.feature_dependencies],
            "strategy_dependencies": [dict(item) for item in self.strategy_dependencies],
            "risk_dependencies": list(self.risk_dependencies),
            "snapshot_cutoff": self.snapshot_cutoff,
            "permitted_universe": list(self.permitted_universe),
            "excluded_datasets_and_reasons": dict(self.excluded_datasets_and_reasons),
        }

    def to_canonical_dict(self) -> dict[str, Any]:
        body = self.to_dict()
        body.pop("profile_digest", None)
        return body

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "ResearchDataProfile":
        if not isinstance(payload, Mapping):
            raise ResearchDataProfileError("ResearchDataProfile must be an object")
        unknown = sorted(set(payload) - _PROFILE_FIELDS)
        if unknown:
            raise ResearchDataProfileError(
                f"unknown ResearchDataProfile field(s): {unknown}"
            )
        missing_fields = sorted(
            key
            for key in _PROFILE_FIELDS
            if key not in payload and key != "profile_digest"
        )
        if missing_fields:
            raise ResearchDataProfileError(
                f"ResearchDataProfile missing field(s): {missing_fields}"
            )

        profile_id = _require_str(payload.get("profile_id"), "profile_id")
        profile_version = _require_str(payload.get("profile_version"), "profile_version")
        if profile_version != PROFILE_VERSION:
            raise ResearchDataProfileError(
                f"unsupported profile_version {profile_version!r}; "
                f"expected {PROFILE_VERSION!r}"
            )
        purpose = _require_str(payload.get("purpose"), "purpose")
        required_coverage_mode = _require_str(
            payload.get("required_coverage_mode"), "required_coverage_mode"
        )
        if required_coverage_mode != REQUIRED_COVERAGE_MODE_OFFICIAL:
            raise ResearchDataProfileError(
                "required_coverage_mode must be "
                f"{REQUIRED_COVERAGE_MODE_OFFICIAL!r}"
            )

        snapshot_cutoff = payload.get("snapshot_cutoff")
        if snapshot_cutoff is not None:
            snapshot_cutoff = _require_str(snapshot_cutoff, "snapshot_cutoff")

        contract_versions = _require_contract_versions(payload.get("contract_versions"))
        feature_dependencies = _require_feature_deps(payload.get("feature_dependencies"))
        strategy_dependencies = _require_strategy_deps(
            payload.get("strategy_dependencies")
        )
        excluded = _require_str_map(
            payload.get("excluded_datasets_and_reasons"),
            "excluded_datasets_and_reasons",
        )

        # resolve_deps fail-closed on missing Deps / omitted listed datasets.
        required_datasets = resolve_deps(payload)

        body = {
            "profile_id": profile_id,
            "profile_version": profile_version,
            "purpose": purpose,
            "required_datasets": list(required_datasets),
            "required_coverage_mode": required_coverage_mode,
            "contract_versions": dict(contract_versions),
            "feature_dependencies": [dict(item) for item in feature_dependencies],
            "strategy_dependencies": [dict(item) for item in strategy_dependencies],
            "risk_dependencies": list(
                _require_str_tuple(payload.get("risk_dependencies"), "risk_dependencies")
            ),
            "snapshot_cutoff": snapshot_cutoff,
            "permitted_universe": list(
                _require_str_tuple(payload.get("permitted_universe"), "permitted_universe")
            ),
            "excluded_datasets_and_reasons": dict(excluded),
        }
        digest = compute_digest(body)
        declared = payload.get("profile_digest")
        if declared is not None:
            declared_text = _require_str(declared, "profile_digest")
            if declared_text != digest:
                raise ResearchDataProfileError(
                    "profile_digest mismatch with canonical body"
                )
        return cls(
            profile_id=profile_id,
            profile_version=profile_version,
            profile_digest=digest,
            purpose=purpose,
            required_datasets=required_datasets,
            required_coverage_mode=required_coverage_mode,
            contract_versions=contract_versions,
            feature_dependencies=feature_dependencies,
            strategy_dependencies=strategy_dependencies,
            risk_dependencies=tuple(body["risk_dependencies"]),
            snapshot_cutoff=snapshot_cutoff,
            permitted_universe=tuple(body["permitted_universe"]),
            excluded_datasets_and_reasons=excluded,
        )


def load_core_profile(*, path: Path | None = None) -> ResearchDataProfile:
    """Load the baseline/core historical-research profile from specs."""
    source = path or (repo_root() / CORE_PROFILE_REL)
    raw = json.loads(source.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ResearchDataProfileError("core profile JSON must be an object")
    profile = ResearchDataProfile.from_dict(raw)
    _assert_core_exclusions(profile)
    return profile


def default_contract_versions() -> dict[str, str]:
    """Pinned contract versions for a ResearchDataProfile.

    coverage_policy is the collection_coverage.json document root, not a claim
    that every dataset row is that version. Per-dataset policy_version is v3
    for master/AM/earnings when those JSON rows say so.
    """
    return {
        "canonical_registry": REGISTRY_VERSION,
        "coverage_policy": COVERAGE_POLICY_VERSION,
        "evaluation_ir": EVALUATION_IR_VERSION,
        "jsda_governed": JSDA_CONTRACT_VERSION,
        "strategy_spec": STRATEGY_SPEC_VERSION,
    }


def _assert_core_exclusions(profile: ResearchDataProfile) -> None:
    required = set(profile.required_datasets)
    for dataset in (TIP_ONLY_AM_DATASET, TIP_ONLY_EARNINGS_CALENDAR_DATASET):
        if dataset in required:
            raise ResearchDataProfileError(
                f"core profile must not require tip-only dataset {dataset!r}"
            )
        if dataset not in profile.excluded_datasets_and_reasons:
            raise ResearchDataProfileError(
                f"core profile must exclude tip-only dataset {dataset!r}"
            )
    for dataset in CORE_REQUIRED_DATASETS:
        if dataset not in required:
            raise ResearchDataProfileError(
                f"core profile missing historical-research dataset {dataset!r}"
            )


def _complete_under_official(
    dataset_id: str, evidence_by_dataset: Mapping[str, Any]
) -> bool:
    """True iff mapping evidence is COMPLETE under official_mode(dataset_id).

    A string COMPLETE label is not official-mode proof. Missing V3 is not
    official-complete.
    """
    if source_capability_contract_or_none(dataset_id) is None:
        return False
    if dataset_id not in evidence_by_dataset:
        return False
    evidence = evidence_by_dataset[dataset_id]
    if not isinstance(evidence, Mapping):
        return False
    if evidence.get("projection_status") == "STALE":
        return False
    if "applied_cursor" in evidence and evidence.get("applied_cursor") in (None, ""):
        return False
    if evidence.get("status") != "COMPLETE":
        return False
    required_mode = official_mode(dataset_id)
    if "coverage_mode" in evidence:
        return evidence.get("coverage_mode") == required_mode
    return evidence.get("official") is True


def _evaluation_protocol(raw: Any) -> str:
    versions = _require_contract_versions(raw)
    return versions["evaluation_ir"]


def _require_contract_versions(raw: Any) -> dict[str, str]:
    if not isinstance(raw, Mapping) or not raw:
        raise ResearchDataProfileError("contract_versions must be a non-empty object")
    out: dict[str, str] = {}
    for key, value in raw.items():
        if not isinstance(key, str) or not key.strip():
            raise ResearchDataProfileError("contract_versions keys must be strings")
        if not isinstance(value, str) or not value.strip():
            raise ResearchDataProfileError(
                f"contract_versions.{key} must be a non-empty string"
            )
        out[key.strip()] = value.strip()
    missing = [key for key in _CONTRACT_VERSION_REQUIRED if key not in out]
    if missing:
        raise ResearchDataProfileError(
            f"contract_versions missing {missing}"
        )
    return out


def _require_feature_deps(raw: Any) -> tuple[dict[str, Any], ...]:
    if raw is None or not isinstance(raw, Sequence) or isinstance(raw, (str, bytes)):
        raise ResearchDataProfileError("feature_dependencies must be an array")
    out: list[dict[str, Any]] = []
    for index, item in enumerate(raw):
        out.append(_normalize_feature_dep(item, f"feature_dependencies[{index}]"))
    return tuple(out)


def _require_strategy_deps(raw: Any) -> tuple[dict[str, Any], ...]:
    if raw is None or not isinstance(raw, Sequence) or isinstance(raw, (str, bytes)):
        raise ResearchDataProfileError("strategy_dependencies must be an array")
    out: list[dict[str, Any]] = []
    for index, item in enumerate(raw):
        out.append(_normalize_strategy_dep(item, f"strategy_dependencies[{index}]"))
    return tuple(out)


def _normalize_feature_dep(item: Any, where: str) -> dict[str, Any]:
    if isinstance(item, FeatureRef):
        payload = item.to_dict()
    elif isinstance(item, Mapping):
        payload = dict(item)
    else:
        raise ResearchDataProfileError(f"{where} must be a FeatureRef object")
    if not str(payload.get("id") or "").strip():
        raise ResearchDataProfileError(f"{where}.id is required")
    if not str(payload.get("version") or "").strip():
        raise ResearchDataProfileError(f"{where}.version is required")
    return payload


def _normalize_strategy_dep(item: Any, where: str) -> dict[str, Any]:
    if isinstance(item, StrategySpec):
        payload = item.to_dict()
    elif isinstance(item, Mapping):
        payload = dict(item)
    else:
        raise ResearchDataProfileError(f"{where} must be a StrategySpec object")
    if not str(payload.get("strategy_id") or "").strip():
        raise ResearchDataProfileError(f"{where}.strategy_id is required")
    if "rule" not in payload:
        raise ResearchDataProfileError(f"{where}.rule is required")
    return payload


def _datasets_listed_on_deps(payload: Mapping[str, Any]) -> set[str]:
    listed: set[str] = set()
    for item in payload.get("feature_dependencies") or ():
        listed.update(_datasets_listed_on_node(item))
    for item in payload.get("strategy_dependencies") or ():
        listed.update(_datasets_listed_on_node(item))
    return listed


def _datasets_listed_on_node(node: Any) -> set[str]:
    listed: set[str] = set()
    if isinstance(node, FeatureRef):
        node = node.to_dict()
    elif isinstance(node, StrategySpec):
        node = node.to_dict()
    if isinstance(node, Mapping):
        for key in _DATASET_LIST_KEYS:
            if key in node:
                listed.update(_optional_dataset_ids(node.get(key), key))
        params = node.get("params")
        if isinstance(params, Mapping):
            for key in _DATASET_LIST_KEYS:
                if key in params:
                    listed.update(_optional_dataset_ids(params.get(key), f"params.{key}"))
        for key in _FEATURE_REF_KEYS:
            if key in node:
                listed.update(_datasets_listed_on_node(node.get(key)))
        if "rule" in node:
            listed.update(_datasets_listed_on_node(node.get("rule")))
    elif isinstance(node, Sequence) and not isinstance(node, (str, bytes)):
        for item in node:
            listed.update(_datasets_listed_on_node(item))
    return listed


def _require_dataset_ids(raw: Any, where: str) -> tuple[str, ...]:
    values = _require_str_tuple(raw, where)
    if not values:
        raise ResearchDataProfileError(f"{where} must be non-empty")
    seen: set[str] = set()
    out: list[str] = []
    for dataset_id in values:
        if dataset_id in seen:
            raise ResearchDataProfileError(f"{where} has duplicate {dataset_id!r}")
        try:
            canonical_dataset_for(dataset_id)
        except KeyError as exc:
            raise ResearchDataProfileError(
                f"{where}: unknown dataset {dataset_id!r}"
            ) from exc
        seen.add(dataset_id)
        out.append(dataset_id)
    return tuple(out)


def _optional_dataset_ids(raw: Any, where: str) -> set[str]:
    values = _require_str_tuple(raw, where)
    out: set[str] = set()
    for dataset_id in values:
        try:
            canonical_dataset_for(dataset_id)
        except KeyError as exc:
            raise ResearchDataProfileError(
                f"{where}: unknown dataset {dataset_id!r}"
            ) from exc
        out.add(dataset_id)
    return out


def _require_str_tuple(raw: Any, where: str) -> tuple[str, ...]:
    if raw is None or not isinstance(raw, Sequence) or isinstance(raw, (str, bytes)):
        raise ResearchDataProfileError(f"{where} must be an array of strings")
    out: list[str] = []
    for item in raw:
        if not isinstance(item, str) or not item.strip():
            raise ResearchDataProfileError(f"{where} entries must be non-empty strings")
        out.append(item.strip())
    return tuple(out)


def _require_str_map(raw: Any, where: str) -> dict[str, str]:
    if not isinstance(raw, Mapping):
        raise ResearchDataProfileError(f"{where} must be an object")
    out: dict[str, str] = {}
    for key, value in raw.items():
        if not isinstance(key, str) or not key.strip():
            raise ResearchDataProfileError(f"{where} keys must be non-empty strings")
        if not isinstance(value, str) or not value.strip():
            raise ResearchDataProfileError(
                f"{where}.{key} must be a non-empty string"
            )
        out[key.strip()] = value.strip()
    return out


def _require_str(value: Any, where: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ResearchDataProfileError(f"{where} must be a non-empty string")
    return value.strip()


def _jsonable(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_jsonable(item) for item in value]
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    return value


def _canonical_json(payload: Mapping[str, Any]) -> str:
    body = {
        key: _jsonable(value)
        for key, value in payload.items()
        if key != "profile_digest"
    }
    return json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


__all__ = [
    "CORE_PROFILE_ID",
    "CORE_PROFILE_REL",
    "CORE_REQUIRED_DATASETS",
    "CORE_TIP_ONLY_EXCLUSIONS",
    "COVERAGE_POLICY_DOCUMENT_ROOT",
    "COVERAGE_POLICY_V3",
    "COVERAGE_V3_DATASETS",
    "PROFILE_VERSION",
    "REQUIRED_COVERAGE_MODE_OFFICIAL",
    "ResearchDataProfile",
    "ResearchDataProfileError",
    "TIP_ONLY_AM_DATASET",
    "TIP_ONLY_EARNINGS_CALENDAR_DATASET",
    "compute_digest",
    "default_contract_versions",
    "load_core_profile",
    "official_mode",
    "profile_ready",
    "resolve_deps",
]
