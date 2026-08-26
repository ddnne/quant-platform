"""Frozen v2 protocol contract for exact-four pilot authorities.

This module is deliberately authority-free.  It can compile immutable claims
and lineage pins, but it cannot sign READY, record human approval, authorize a
Trader, or start execution.  The three positive capability types are nominal
and non-constructible until their separately permissioned verifiers exist.

The existing v1 verification paths remain available for audit compatibility.
Nothing in this module enables Mass, live orders, generation two, or automatic
promotion.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, NoReturn

from qp_paths import repo_root
from research.ready_manifest import load_exact_four_pilot_ready_binding
from research.universe_contract import EXACT_FOUR_UNIVERSE_RULE_DIGEST
from selection.budget_ledger import MassResearchDisabledError
from selection.controlled_pilot_policy import (
    CONTROLLED_PILOT_POLICY_DIGEST,
    CONTROLLED_PILOT_POLICY_ID,
    CONTROLLED_PILOT_POLICY_RAW_DIGEST,
    CONTROLLED_PILOT_POLICY_SCHEMA_URI,
    ControlledPilotPolicyPin,
    load_controlled_pilot_policy,
)


EXACT_FOUR_AUTHORITY_SCHEMA_REL = (
    Path("specs") / "ready" / "exact_four_authority_protocol.schema.json"
)
PINNED_EXACT_FOUR_AUTHORITY_SCHEMA_DIGEST = (
    "sha256:5654d2e8c5e19ac96de7eda23fcb54ded9194e533c68bb1fe4fbdd14cdb12b53"
)
PINNED_EXACT_FOUR_AUTHORITY_SCHEMA_RAW_DIGEST = (
    "sha256:39f8d317da87c0658d536e90594a0fd3d762bd1e622b13c079d0bcad2e8dca05"
)

PLAN_EXECUTION_BINDING_FORMAT = "plan-execution-binding/v1"
EXACT_FOUR_BINDING_FORMAT = "exact-four-execution-binding/v1"
PILOT_READINESS_CLAIMS_FORMAT = "pilot-readiness-attestation-claims/v2"
TRADER_AUTHORIZATION_CLAIMS_FORMAT = "exact-four-trader-authorization-claims/v2"
CONTROLLED_EXECUTION_CLAIMS_FORMAT = "exact-four-execution-request-claims/v2"

PILOT_READINESS_SCOPE = "VERIFIED_PILOT_READINESS"
TRADER_AUTHORIZATION_SCOPE = "EXACT_FOUR_TRADER_AUTHORIZATION"
CONTROLLED_EXECUTION_SCOPE = "EXACT_FOUR_CONTROLLED_PAPER_EXECUTION"
PILOT_EXECUTION_MODE = "paper"
AUTHORITY_PROTOCOL_STATE = "PENDING_EXTERNAL_AUTHORITIES"
_CURRENT_CLOCK_SKEW = timedelta(seconds=30)

_SHA256_RE = re.compile(r"sha256:[0-9a-f]{64}\Z")
_UNAVAILABLE_CURRENT_VALUES = frozenset(
    {
        "n/a",
        "na",
        "none",
        "not-declared",
        "not_declared",
        "null",
        "pending",
        "stale",
        "unknown",
        "unset",
    }
)


class ExactFourAuthorityContractError(MassResearchDisabledError):
    """Raised when immutable exact-four authority claims are not canonical."""


class ExactFourAuthorityPending(ExactFourAuthorityContractError):
    """Raised because no v2 publication/approval/execution principal exists."""


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    document: dict[str, Any] = {}
    for key, value in pairs:
        if key in document:
            raise ExactFourAuthorityContractError(
                f"authority contract contains duplicate JSON key: {key}"
            )
        document[key] = value
    return document


def _reject_nonfinite(value: str) -> Any:
    raise ExactFourAuthorityContractError(
        f"authority contract contains non-finite JSON number: {value}"
    )


def _require_exact_json(value: Any, *, path: str = "$") -> None:
    if type(value) is dict:
        for key, item in value.items():
            if type(key) is not str:
                raise ExactFourAuthorityContractError(
                    f"{path}: JSON object keys must be exact strings"
                )
            _require_exact_json(item, path=f"{path}.{key}")
        return
    if type(value) is list:
        for ordinal, item in enumerate(value):
            _require_exact_json(item, path=f"{path}[{ordinal}]")
        return
    if type(value) not in {str, int, bool, type(None)}:
        raise ExactFourAuthorityContractError(
            f"{path}: value must be an exact JSON built-in"
        )


def _strict_json_loads(raw: bytes | str, *, label: str) -> dict[str, Any]:
    try:
        text = raw.decode("utf-8") if type(raw) is bytes else raw
        if type(text) is not str:
            raise TypeError("raw authority document must be bytes or str")
        value = json.loads(
            text,
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_nonfinite,
        )
    except (TypeError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ExactFourAuthorityContractError(f"cannot decode {label}") from exc
    if type(value) is not dict:
        raise ExactFourAuthorityContractError(f"{label} must be one JSON object")
    _require_exact_json(value)
    return value


def _canonical_bytes(value: Any) -> bytes:
    _require_exact_json(value)
    try:
        return json.dumps(
            value,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ExactFourAuthorityContractError(
            "authority contract value is not canonical JSON"
        ) from exc


def canonical_authority_digest(value: Any) -> str:
    """Return the common content address used by every v2 protocol body."""
    return "sha256:" + hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _require_text(value: Any, label: str) -> str:
    if type(value) is not str or not value.strip() or value != value.strip():
        raise ExactFourAuthorityContractError(
            f"{label} must be an exact non-empty string"
        )
    return value


def _require_digest(value: Any, label: str) -> str:
    text = _require_text(value, label)
    if _SHA256_RE.fullmatch(text) is None:
        raise ExactFourAuthorityContractError(
            f"{label} must be a canonical sha256 digest"
        )
    return text


def _require_timestamp(value: Any, label: str) -> str:
    text = _require_text(value, label)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ExactFourAuthorityContractError(
            f"{label} must be an ISO-8601 timestamp"
        ) from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ExactFourAuthorityContractError(f"{label} must include a timezone")
    return text


def _parsed_timestamp(value: Any, label: str) -> datetime:
    text = _require_timestamp(value, label)
    return datetime.fromisoformat(text.replace("Z", "+00:00"))


def _require_bounded_window(
    issued_at: Any,
    expires_at: Any,
    *,
    ttl_seconds: Any,
    label: str,
) -> tuple[datetime, datetime]:
    if type(ttl_seconds) is not int or ttl_seconds < 1:
        raise ExactFourAuthorityContractError(f"{label} TTL must be a positive integer")
    issued = _parsed_timestamp(issued_at, f"{label} issued_at")
    expires = _parsed_timestamp(expires_at, f"{label} expires_at")
    lifetime = (expires - issued).total_seconds()
    if lifetime <= 0:
        raise ExactFourAuthorityContractError(
            f"{label} expiry must be after issuance"
        )
    if lifetime > ttl_seconds:
        raise ExactFourAuthorityContractError(
            f"{label} lifetime exceeds the controlled-pilot policy TTL"
        )
    return issued, expires


def _trusted_utc_now() -> datetime:
    """Read the module-owned system clock used by public current validators."""

    return datetime.now(timezone.utc)


def _require_current_window(
    issued_at: Any,
    expires_at: Any,
    *,
    label: str,
    now: datetime,
) -> None:
    """Reject claims that are expired or not yet valid at the trusted clock."""

    issued = _parsed_timestamp(issued_at, f"{label} issued_at")
    expires = _parsed_timestamp(expires_at, f"{label} expires_at")
    current = now.astimezone(timezone.utc)
    if issued > current + _CURRENT_CLOCK_SKEW:
        raise ExactFourAuthorityContractError(
            f"{label} is not yet valid at the trusted UTC clock"
        )
    if expires <= current:
        raise ExactFourAuthorityContractError(
            f"{label} is expired at the trusted UTC clock"
        )


def _require_current_token(value: Any, label: str) -> str:
    text = _require_text(value, label)
    if text.casefold() in _UNAVAILABLE_CURRENT_VALUES:
        raise ExactFourAuthorityContractError(
            f"{label} must identify a current non-sentinel value"
        )
    return text


def _require_positive_int(value: Any, label: str) -> int:
    if type(value) is not int or value < 1:
        raise ExactFourAuthorityContractError(
            f"{label} must be an exact positive integer"
        )
    return value


def _require_date(value: Any, label: str) -> str:
    text = _require_text(value, label)
    try:
        parsed = date.fromisoformat(text)
    except ValueError as exc:
        raise ExactFourAuthorityContractError(
            f"{label} must be an ISO date (YYYY-MM-DD)"
        ) from exc
    if parsed.isoformat() != text:
        raise ExactFourAuthorityContractError(
            f"{label} must be an ISO date (YYYY-MM-DD)"
        )
    return text


@dataclass(frozen=True, slots=True)
class FeatureExecutionPin:
    ordinal: int
    feature_id: str
    feature_version: str
    definition_digest: str
    params_digest: str
    dataset_membership_digest: str

    def __post_init__(self) -> None:
        if type(self.ordinal) is not int or self.ordinal < 0:
            raise ExactFourAuthorityContractError(
                "feature ordinal must be a non-negative integer"
            )
        _require_text(self.feature_id, "feature_id")
        _require_text(self.feature_version, "feature_version")
        _require_digest(self.definition_digest, "definition_digest")
        _require_digest(self.params_digest, "params_digest")
        _require_digest(
            self.dataset_membership_digest, "feature dataset_membership_digest"
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "ordinal": self.ordinal,
            "feature_id": self.feature_id,
            "feature_version": self.feature_version,
            "definition_digest": self.definition_digest,
            "params_digest": self.params_digest,
            "dataset_membership_digest": self.dataset_membership_digest,
        }


@dataclass(frozen=True, slots=True)
class PlanExecutionBinding:
    """Authority-free immutable lineage for one ordered exact-four plan."""

    ordinal: int
    plan_id: str
    plan_digest: str
    dependency_closure_digest: str
    profile_id: str
    profile_version: str
    profile_digest: str
    strategy_spec_id: str
    strategy_spec_version: str
    strategy_spec_hash: str
    feature_pins: tuple[FeatureExecutionPin, ...]
    feature_dependency_set_digest: str
    universe_dependency_set_digest: str
    evaluation_dependency_digest: str
    risk_dependency_digest: str
    cost_dependency_digest: str
    required_dataset_membership_digest: str
    max_gross_weight_ppm: int
    max_paper_runs: int
    risk_execution_limit_digest: str
    period_start: str
    period_end: str
    cost_scenario: str
    format: str = PLAN_EXECUTION_BINDING_FORMAT

    def __post_init__(self) -> None:
        if type(self.ordinal) is not int or not 1 <= self.ordinal <= 4:
            raise ExactFourAuthorityContractError(
                "plan ordinal must be an integer from one through four"
            )
        if type(self.format) is not str or (
            self.format != PLAN_EXECUTION_BINDING_FORMAT
        ):
            raise ExactFourAuthorityContractError(
                "plan execution binding format is not canonical"
            )
        for name in (
            "plan_id",
            "profile_id",
            "profile_version",
            "strategy_spec_id",
            "strategy_spec_version",
            "period_start",
            "period_end",
            "cost_scenario",
        ):
            _require_text(getattr(self, name), name)
        for name in (
            "plan_digest",
            "dependency_closure_digest",
            "profile_digest",
            "strategy_spec_hash",
            "feature_dependency_set_digest",
            "universe_dependency_set_digest",
            "evaluation_dependency_digest",
            "risk_dependency_digest",
            "cost_dependency_digest",
            "required_dataset_membership_digest",
            "risk_execution_limit_digest",
        ):
            _require_digest(getattr(self, name), name)
        if type(self.max_gross_weight_ppm) is not int or (
            self.max_gross_weight_ppm != 500_000
        ):
            raise ExactFourAuthorityContractError(
                "per-plan max gross weight must remain pinned at 500000 ppm"
            )
        if type(self.max_paper_runs) is not int or self.max_paper_runs != 2:
            raise ExactFourAuthorityContractError(
                "per-plan paper run limit must remain pinned at two"
            )
        expected_limit_digest = canonical_authority_digest(
            {
                "plan_id": self.plan_id,
                "max_gross_weight_ppm": self.max_gross_weight_ppm,
                "max_paper_runs": self.max_paper_runs,
            }
        )
        if self.risk_execution_limit_digest != expected_limit_digest:
            raise ExactFourAuthorityContractError(
                "per-plan risk/execution limit digest mismatch"
            )
        pins = tuple(self.feature_pins)
        if not pins or any(type(pin) is not FeatureExecutionPin for pin in pins):
            raise ExactFourAuthorityContractError(
                "feature_pins must contain exact FeatureExecutionPin values"
            )
        if tuple(pin.ordinal for pin in pins) != tuple(range(len(pins))):
            raise ExactFourAuthorityContractError(
                "feature_pins must preserve canonical ordinal order"
            )
        if canonical_authority_digest([pin.to_dict() for pin in pins]) != (
            self.feature_dependency_set_digest
        ):
            raise ExactFourAuthorityContractError(
                "feature dependency set digest mismatch"
            )
        period_start = _require_date(self.period_start, "period_start")
        period_end = _require_date(self.period_end, "period_end")
        if period_start > period_end:
            raise ExactFourAuthorityContractError("plan period is reversed")
        object.__setattr__(self, "feature_pins", pins)

    def to_canonical_dict(self) -> dict[str, Any]:
        return {
            "format": self.format,
            "ordinal": self.ordinal,
            "plan_id": self.plan_id,
            "plan_digest": self.plan_digest,
            "dependency_closure_digest": self.dependency_closure_digest,
            "profile_id": self.profile_id,
            "profile_version": self.profile_version,
            "profile_digest": self.profile_digest,
            "strategy_spec_id": self.strategy_spec_id,
            "strategy_spec_version": self.strategy_spec_version,
            "strategy_spec_hash": self.strategy_spec_hash,
            "feature_pins": [pin.to_dict() for pin in self.feature_pins],
            "feature_dependency_set_digest": self.feature_dependency_set_digest,
            "universe_dependency_set_digest": self.universe_dependency_set_digest,
            "evaluation_dependency_digest": self.evaluation_dependency_digest,
            "risk_dependency_digest": self.risk_dependency_digest,
            "cost_dependency_digest": self.cost_dependency_digest,
            "required_dataset_membership_digest": (
                self.required_dataset_membership_digest
            ),
            "max_gross_weight_ppm": self.max_gross_weight_ppm,
            "max_paper_runs": self.max_paper_runs,
            "risk_execution_limit_digest": self.risk_execution_limit_digest,
            "period_start": self.period_start,
            "period_end": self.period_end,
            "cost_scenario": self.cost_scenario,
        }

    @property
    def binding_digest(self) -> str:
        return canonical_authority_digest(self.to_canonical_dict())

    def to_dict(self) -> dict[str, Any]:
        return {**self.to_canonical_dict(), "binding_digest": self.binding_digest}


@dataclass(frozen=True, slots=True)
class ControlledPilotArtifactCardinality:
    """One batch: 4 Paper, 4 Risk, then one aggregate Selection/Knowledge."""

    batch_authorizations_exactly: int = 1
    paper_results_exactly: int = 4
    risk_results_exactly: int = 4
    aggregate_selection_results_exactly: int = 1
    knowledge_artifacts_exactly: int = 1

    def __post_init__(self) -> None:
        expected = {
            "batch_authorizations_exactly": 1,
            "paper_results_exactly": 4,
            "risk_results_exactly": 4,
            "aggregate_selection_results_exactly": 1,
            "knowledge_artifacts_exactly": 1,
        }
        actual = self.to_dict()
        if (
            any(type(actual[name]) is not int for name in expected)
            or actual != expected
        ):
            raise ExactFourAuthorityContractError(
                "controlled pilot artifact cardinality is not canonical"
            )

    def to_dict(self) -> dict[str, int]:
        return {
            "batch_authorizations_exactly": self.batch_authorizations_exactly,
            "paper_results_exactly": self.paper_results_exactly,
            "risk_results_exactly": self.risk_results_exactly,
            "aggregate_selection_results_exactly": (
                self.aggregate_selection_results_exactly
            ),
            "knowledge_artifacts_exactly": self.knowledge_artifacts_exactly,
        }


def _compiled_plan_bindings() -> tuple[PlanExecutionBinding, ...]:
    binding = load_exact_four_pilot_ready_binding()
    compiled: list[PlanExecutionBinding] = []
    for ordinal, (closure, profile) in enumerate(
        zip(binding.closures, binding.profiles, strict=True), start=1
    ):
        features = tuple(
            FeatureExecutionPin(
                ordinal=feature.ordinal,
                feature_id=feature.feature_id,
                feature_version=feature.feature_version,
                definition_digest=feature.definition_digest,
                params_digest=canonical_authority_digest(dict(feature.params)),
                dataset_membership_digest=canonical_authority_digest(
                    list(feature.dataset_dependencies)
                ),
            )
            for feature in closure.feature_dependencies
        )
        limit_body = {
            "plan_id": closure.plan_id,
            "max_gross_weight_ppm": 500_000,
            "max_paper_runs": 2,
        }
        compiled.append(
            PlanExecutionBinding(
                ordinal=ordinal,
                plan_id=closure.plan_id,
                plan_digest=closure.plan_digest,
                dependency_closure_digest=closure.closure_digest,
                profile_id=profile.profile_id,
                profile_version=profile.profile_version,
                profile_digest=profile.profile_digest,
                strategy_spec_id=closure.strategy_spec_id,
                strategy_spec_version=closure.strategy_spec_version,
                strategy_spec_hash=closure.strategy_spec_hash,
                feature_pins=features,
                feature_dependency_set_digest=canonical_authority_digest(
                    [feature.to_dict() for feature in features]
                ),
                universe_dependency_set_digest=canonical_authority_digest(
                    [item.to_dict() for item in closure.universe_dependencies]
                ),
                evaluation_dependency_digest=(
                    closure.evaluation_dependency.contract_digest
                ),
                risk_dependency_digest=closure.risk_dependency.contract_digest,
                cost_dependency_digest=closure.cost_dependency.contract_digest,
                required_dataset_membership_digest=canonical_authority_digest(
                    list(closure.required_datasets)
                ),
                max_gross_weight_ppm=500_000,
                max_paper_runs=2,
                risk_execution_limit_digest=canonical_authority_digest(limit_body),
                period_start=closure.period_start,
                period_end=closure.period_end,
                cost_scenario=closure.cost_dependency.dependency_id,
            )
        )
    return tuple(compiled)


@dataclass(frozen=True, slots=True)
class ExactFourExecutionBinding:
    """Canonical ordered plan set.  It carries lineage, never authority."""

    plan_bindings: tuple[PlanExecutionBinding, ...]
    policy: ControlledPilotPolicyPin
    artifact_cardinality: ControlledPilotArtifactCardinality
    publication_profile_id: str
    publication_profile_version: str
    plan_set_digest: str
    dependency_closure_set_digest: str
    profile_set_digest: str
    required_dataset_membership_digest: str
    universe_rule_digest: str
    coverage_policy_version: str
    coverage_policy_digest: str
    budget_scope_digest: str
    execution_limit_set_digest: str
    lease_ttl_seconds: int
    format: str = EXACT_FOUR_BINDING_FORMAT
    execution_mode: str = PILOT_EXECUTION_MODE
    automatic_promotion: bool = False
    mass_research_enabled: bool = False
    live_trading_enabled: bool = False

    def __post_init__(self) -> None:
        if type(self.format) is not str or self.format != EXACT_FOUR_BINDING_FORMAT:
            raise ExactFourAuthorityContractError(
                "exact-four execution binding format is not canonical"
            )
        if type(self.execution_mode) is not str or (
            self.execution_mode != PILOT_EXECUTION_MODE
        ):
            raise ExactFourAuthorityContractError("only paper execution is permitted")
        if (
            type(self.automatic_promotion) is not bool
            or type(self.mass_research_enabled) is not bool
            or type(self.live_trading_enabled) is not bool
            or self.automatic_promotion
            or self.mass_research_enabled
            or self.live_trading_enabled
        ):
            raise ExactFourAuthorityContractError(
                "Mass, live trading, and automatic promotion are disabled"
            )
        if type(self.policy) is not ControlledPilotPolicyPin:
            raise ExactFourAuthorityContractError(
                "exact ControlledPilotPolicyPin is required"
            )
        self.policy.__post_init__()
        if type(self.artifact_cardinality) is not ControlledPilotArtifactCardinality:
            raise ExactFourAuthorityContractError(
                "exact ControlledPilotArtifactCardinality is required"
            )
        self.artifact_cardinality.__post_init__()
        plans = tuple(self.plan_bindings)
        expected = _compiled_plan_bindings()
        if (
            len(plans) != self.policy.plans_exactly
            or any(type(item) is not PlanExecutionBinding for item in plans)
            or tuple(item.ordinal for item in plans) != (1, 2, 3, 4)
            or tuple(item.to_dict() for item in plans)
            != tuple(item.to_dict() for item in expected)
        ):
            raise ExactFourAuthorityContractError(
                "plan bindings are not the canonical ordered exact four"
            )
        for name in (
            "publication_profile_id",
            "publication_profile_version",
            "coverage_policy_version",
        ):
            _require_text(getattr(self, name), name)
        for name in (
            "plan_set_digest",
            "dependency_closure_set_digest",
            "profile_set_digest",
            "required_dataset_membership_digest",
            "universe_rule_digest",
            "coverage_policy_digest",
            "budget_scope_digest",
            "execution_limit_set_digest",
        ):
            _require_digest(getattr(self, name), name)
        source = load_exact_four_pilot_ready_binding()
        if (
            self.publication_profile_id != source.profile_id
            or self.publication_profile_version != source.profile_version
            or self.plan_set_digest != source.plan_set_digest
            or self.dependency_closure_set_digest != source.closure_set_digest
            or self.profile_set_digest != source.profile_digest
            or self.required_dataset_membership_digest
            != canonical_authority_digest(list(source.required_datasets))
            or self.universe_rule_digest != EXACT_FOUR_UNIVERSE_RULE_DIGEST
            or self.coverage_policy_version
            != source.contract_versions["coverage_policy"]
            or self.coverage_policy_digest
            != source.contract_versions["coverage_policy_digest"]
            or self.budget_scope_digest != self.policy.budget_scope_digest
            or self.execution_limit_set_digest
            != canonical_authority_digest(
                [
                    {
                        "ordinal": item.ordinal,
                        "plan_id": item.plan_id,
                        "risk_execution_limit_digest": (
                            item.risk_execution_limit_digest
                        ),
                    }
                    for item in plans
                ]
            )
            or type(self.lease_ttl_seconds) is not int
            or self.lease_ttl_seconds != self.policy.lease_ttl_seconds
        ):
            raise ExactFourAuthorityContractError(
                "exact-four aggregate lineage does not match governed compiler output"
            )
        object.__setattr__(self, "plan_bindings", plans)

    def to_canonical_dict(self) -> dict[str, Any]:
        return {
            "format": self.format,
            "execution_mode": self.execution_mode,
            "policy": self.policy.to_dict(),
            "artifact_cardinality": self.artifact_cardinality.to_dict(),
            "publication_profile_id": self.publication_profile_id,
            "publication_profile_version": self.publication_profile_version,
            "plan_bindings": [item.to_dict() for item in self.plan_bindings],
            "plan_set_digest": self.plan_set_digest,
            "dependency_closure_set_digest": self.dependency_closure_set_digest,
            "profile_set_digest": self.profile_set_digest,
            "required_dataset_membership_digest": (
                self.required_dataset_membership_digest
            ),
            "universe_rule_digest": self.universe_rule_digest,
            "coverage_policy_version": self.coverage_policy_version,
            "coverage_policy_digest": self.coverage_policy_digest,
            "budget_scope_digest": self.budget_scope_digest,
            "execution_limit_set_digest": self.execution_limit_set_digest,
            "lease_ttl_seconds": self.lease_ttl_seconds,
            "automatic_promotion": self.automatic_promotion,
            "mass_research_enabled": self.mass_research_enabled,
            "live_trading_enabled": self.live_trading_enabled,
        }

    @property
    def binding_digest(self) -> str:
        return canonical_authority_digest(self.to_canonical_dict())

    def to_dict(self) -> dict[str, Any]:
        return {**self.to_canonical_dict(), "binding_digest": self.binding_digest}


def load_exact_four_execution_binding() -> ExactFourExecutionBinding:
    source = load_exact_four_pilot_ready_binding()
    policy = load_controlled_pilot_policy()
    plan_bindings = _compiled_plan_bindings()
    return ExactFourExecutionBinding(
        plan_bindings=plan_bindings,
        policy=policy,
        artifact_cardinality=ControlledPilotArtifactCardinality(),
        publication_profile_id=source.profile_id,
        publication_profile_version=source.profile_version,
        plan_set_digest=source.plan_set_digest,
        dependency_closure_set_digest=source.closure_set_digest,
        profile_set_digest=source.profile_digest,
        required_dataset_membership_digest=canonical_authority_digest(
            list(source.required_datasets)
        ),
        universe_rule_digest=EXACT_FOUR_UNIVERSE_RULE_DIGEST,
        coverage_policy_version=source.contract_versions["coverage_policy"],
        coverage_policy_digest=source.contract_versions["coverage_policy_digest"],
        budget_scope_digest=policy.budget_scope_digest,
        execution_limit_set_digest=canonical_authority_digest(
            [
                {
                    "ordinal": item.ordinal,
                    "plan_id": item.plan_id,
                    "risk_execution_limit_digest": item.risk_execution_limit_digest,
                }
                for item in plan_bindings
            ]
        ),
        lease_ttl_seconds=policy.lease_ttl_seconds,
    )


@dataclass(frozen=True, slots=True)
class ReadySnapshotLineage:
    """Immutable READY snapshot pins measured by the future issuer."""

    snapshot_id: str
    ready_manifest_digest: str
    immutable_snapshot_digest: str
    governed_membership_digest: str
    universe_rule_digest: str
    resolved_universe_digest: str
    coverage_policy_version: str
    coverage_policy_digest: str
    coverage_status: str
    coverage_proof_digest: str
    raw_status: str
    raw_proof_digest: str
    trusted_receipt_status: str
    receipt_proof_digest: str
    validation_status: str
    validation_proof_digest: str
    natural_key_status: str
    natural_key_proof_digest: str
    b0_status: str
    b0_proof_digest: str
    b4_status: str
    b4_proof_digest: str
    pit_contract_set_digest: str
    projection_status: str
    projection_refresh_success: bool
    projection_is_current: bool
    projection_generation: str
    source_generation: int
    applied_sync_generation: int
    source_cursor: int
    export_cursor: int
    applied_cursor: int
    feature_generation: str
    catalog_generation: str

    def __post_init__(self) -> None:
        for name in (
            "snapshot_id",
            "ready_manifest_digest",
            "immutable_snapshot_digest",
            "governed_membership_digest",
            "universe_rule_digest",
            "resolved_universe_digest",
            "coverage_policy_digest",
            "coverage_proof_digest",
            "raw_proof_digest",
            "receipt_proof_digest",
            "validation_proof_digest",
            "natural_key_proof_digest",
            "b0_proof_digest",
            "b4_proof_digest",
            "pit_contract_set_digest",
            "feature_generation",
            "catalog_generation",
        ):
            _require_digest(getattr(self, name), name)
        expected_statuses = {
            "coverage_status": "COMPLETE",
            "raw_status": "PRESENT",
            "trusted_receipt_status": "COMPLETE",
            "validation_status": "PASS",
            "natural_key_status": "PASS",
            "b0_status": "PASS",
            "b4_status": "PASS",
            "projection_status": "FRESH",
        }
        for name, expected in expected_statuses.items():
            value = getattr(self, name)
            if type(value) is not str or value != expected:
                raise ExactFourAuthorityContractError(
                    f"{name} must be exact production evidence state {expected}"
                )
        if (
            type(self.projection_refresh_success) is not bool
            or not self.projection_refresh_success
            or type(self.projection_is_current) is not bool
            or not self.projection_is_current
        ):
            raise ExactFourAuthorityContractError(
                "READY projection must be refreshed successfully and current"
            )
        for name in (
            "coverage_policy_version",
            "projection_generation",
        ):
            _require_current_token(getattr(self, name), name)
        for name in (
            "source_generation",
            "applied_sync_generation",
            "source_cursor",
            "export_cursor",
            "applied_cursor",
        ):
            _require_positive_int(getattr(self, name), name)
        if self.source_generation != self.applied_sync_generation:
            raise ExactFourAuthorityContractError(
                "source and applied sync generation must be current"
            )
        if not (
            self.source_cursor == self.export_cursor == self.applied_cursor
        ):
            raise ExactFourAuthorityContractError(
                "source/export/applied cursor chain must be current"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "snapshot_id": self.snapshot_id,
            "ready_manifest_digest": self.ready_manifest_digest,
            "immutable_snapshot_digest": self.immutable_snapshot_digest,
            "governed_membership_digest": self.governed_membership_digest,
            "universe_rule_digest": self.universe_rule_digest,
            "resolved_universe_digest": self.resolved_universe_digest,
            "coverage_policy_version": self.coverage_policy_version,
            "coverage_policy_digest": self.coverage_policy_digest,
            "coverage_status": self.coverage_status,
            "coverage_proof_digest": self.coverage_proof_digest,
            "raw_status": self.raw_status,
            "raw_proof_digest": self.raw_proof_digest,
            "trusted_receipt_status": self.trusted_receipt_status,
            "receipt_proof_digest": self.receipt_proof_digest,
            "validation_status": self.validation_status,
            "validation_proof_digest": self.validation_proof_digest,
            "natural_key_status": self.natural_key_status,
            "natural_key_proof_digest": self.natural_key_proof_digest,
            "b0_status": self.b0_status,
            "b0_proof_digest": self.b0_proof_digest,
            "b4_status": self.b4_status,
            "b4_proof_digest": self.b4_proof_digest,
            "pit_contract_set_digest": self.pit_contract_set_digest,
            "projection_status": self.projection_status,
            "projection_refresh_success": self.projection_refresh_success,
            "projection_is_current": self.projection_is_current,
            "projection_generation": self.projection_generation,
            "source_generation": self.source_generation,
            "applied_sync_generation": self.applied_sync_generation,
            "source_cursor": self.source_cursor,
            "export_cursor": self.export_cursor,
            "applied_cursor": self.applied_cursor,
            "feature_generation": self.feature_generation,
            "catalog_generation": self.catalog_generation,
        }


@dataclass(frozen=True, slots=True)
class PilotReadinessAttestationClaimsV2:
    """Unsigned, content-addressed READY claims; never a verified capability."""

    pilot_run_id: str
    snapshot: ReadySnapshotLineage
    exact_four: ExactFourExecutionBinding
    issued_at: str
    expires_at: str
    issuer: str = "PilotReadyPublicationService/v2"
    format: str = PILOT_READINESS_CLAIMS_FORMAT
    authority_scope: str = PILOT_READINESS_SCOPE

    def __post_init__(self) -> None:
        if type(self.snapshot) is not ReadySnapshotLineage:
            raise ExactFourAuthorityContractError(
                "READY claims require exact ReadySnapshotLineage"
            )
        _require_text(self.pilot_run_id, "pilot_run_id")
        if type(self.exact_four) is not ExactFourExecutionBinding:
            raise ExactFourAuthorityContractError(
                "READY claims require exact ExactFourExecutionBinding"
            )
        if (
            type(self.format) is not str
            or self.format != PILOT_READINESS_CLAIMS_FORMAT
            or type(self.authority_scope) is not str
            or self.authority_scope != PILOT_READINESS_SCOPE
            or type(self.issuer) is not str
            or self.issuer != "PilotReadyPublicationService/v2"
        ):
            raise ExactFourAuthorityContractError(
                "READY claims authority identity is not canonical"
            )
        self.snapshot.__post_init__()
        self.exact_four.__post_init__()
        _require_bounded_window(
            self.issued_at,
            self.expires_at,
            ttl_seconds=self.exact_four.lease_ttl_seconds,
            label="READY claims",
        )
        canonical = load_exact_four_execution_binding()
        if self.exact_four.binding_digest != canonical.binding_digest:
            raise ExactFourAuthorityContractError(
                "READY claims exact-four binding is not canonical"
            )
        if (
            self.snapshot.governed_membership_digest
            != self.exact_four.required_dataset_membership_digest
            or self.snapshot.universe_rule_digest
            != self.exact_four.universe_rule_digest
            or self.snapshot.coverage_policy_version
            != self.exact_four.coverage_policy_version
            or self.snapshot.coverage_policy_digest
            != self.exact_four.coverage_policy_digest
        ):
            raise ExactFourAuthorityContractError(
                "READY snapshot does not match governed exact-four lineage"
            )

    def to_canonical_dict(self) -> dict[str, Any]:
        return {
            "format": self.format,
            "issuer": self.issuer,
            "authority_scope": self.authority_scope,
            "pilot_run_id": self.pilot_run_id,
            "snapshot": self.snapshot.to_dict(),
            "exact_four": self.exact_four.to_dict(),
            "issued_at": self.issued_at,
            "expires_at": self.expires_at,
        }

    @property
    def attestation_id(self) -> str:
        """Content address of the full unsigned v2 body (signature excluded)."""
        return canonical_authority_digest(self.to_canonical_dict())

    def to_dict(self) -> dict[str, Any]:
        return {**self.to_canonical_dict(), "attestation_id": self.attestation_id}


@dataclass(frozen=True, slots=True)
class TraderAuthorizationClaimsV2:
    """Unsigned human-approval subject, distinct from READY and execution."""

    pilot_run_id: str
    readiness_attestation_id: str
    exact_four_binding_digest: str
    controlled_pilot_policy_digest: str
    budget_scope_digest: str
    execution_limit_set_digest: str
    lease_ttl_seconds: int
    human_approval_event_id: str
    human_approval_event_digest: str
    issued_at: str
    expires_at: str
    format: str = TRADER_AUTHORIZATION_CLAIMS_FORMAT
    authority_scope: str = TRADER_AUTHORIZATION_SCOPE
    execution_mode: str = PILOT_EXECUTION_MODE
    automatic_promotion: bool = False
    mass_research_enabled: bool = False
    live_trading_enabled: bool = False

    def __post_init__(self) -> None:
        if (
            type(self.format) is not str
            or self.format != TRADER_AUTHORIZATION_CLAIMS_FORMAT
            or type(self.authority_scope) is not str
            or self.authority_scope != TRADER_AUTHORIZATION_SCOPE
            or type(self.execution_mode) is not str
            or self.execution_mode != PILOT_EXECUTION_MODE
        ):
            raise ExactFourAuthorityContractError(
                "Trader authorization scope is not canonical"
            )
        _require_text(self.pilot_run_id, "pilot_run_id")
        _require_text(self.human_approval_event_id, "human_approval_event_id")
        for name in (
            "readiness_attestation_id",
            "exact_four_binding_digest",
            "controlled_pilot_policy_digest",
            "budget_scope_digest",
            "execution_limit_set_digest",
            "human_approval_event_digest",
        ):
            _require_digest(getattr(self, name), name)
        if self.controlled_pilot_policy_digest != CONTROLLED_PILOT_POLICY_DIGEST:
            raise ExactFourAuthorityContractError("Trader policy digest mismatch")
        canonical = load_exact_four_execution_binding()
        if (
            self.exact_four_binding_digest != canonical.binding_digest
            or self.budget_scope_digest != canonical.budget_scope_digest
            or self.execution_limit_set_digest
            != canonical.execution_limit_set_digest
            or type(self.lease_ttl_seconds) is not int
            or self.lease_ttl_seconds != canonical.lease_ttl_seconds
        ):
            raise ExactFourAuthorityContractError(
                "Trader risk, execution, or budget limits are not canonical"
            )
        _require_bounded_window(
            self.issued_at,
            self.expires_at,
            ttl_seconds=self.lease_ttl_seconds,
            label="Trader authorization",
        )
        if (
            self.automatic_promotion is not False
            or self.mass_research_enabled is not False
            or self.live_trading_enabled is not False
        ):
            raise ExactFourAuthorityContractError(
                "Trader authorization cannot enable Mass, live, or promotion"
            )

    def to_canonical_dict(self) -> dict[str, Any]:
        return {
            "format": self.format,
            "authority_scope": self.authority_scope,
            "execution_mode": self.execution_mode,
            "pilot_run_id": self.pilot_run_id,
            "readiness_attestation_id": self.readiness_attestation_id,
            "exact_four_binding_digest": self.exact_four_binding_digest,
            "controlled_pilot_policy_digest": (
                self.controlled_pilot_policy_digest
            ),
            "budget_scope_digest": self.budget_scope_digest,
            "execution_limit_set_digest": self.execution_limit_set_digest,
            "lease_ttl_seconds": self.lease_ttl_seconds,
            "human_approval_event_id": self.human_approval_event_id,
            "human_approval_event_digest": self.human_approval_event_digest,
            "issued_at": self.issued_at,
            "expires_at": self.expires_at,
            "automatic_promotion": self.automatic_promotion,
            "mass_research_enabled": self.mass_research_enabled,
            "live_trading_enabled": self.live_trading_enabled,
        }

    @property
    def authorization_id(self) -> str:
        return canonical_authority_digest(self.to_canonical_dict())

    def to_dict(self) -> dict[str, Any]:
        return {**self.to_canonical_dict(), "authorization_id": self.authorization_id}


def build_trader_authorization_claims_v2(
    readiness: PilotReadinessAttestationClaimsV2,
    *,
    human_approval_event_id: str,
    human_approval_event_digest: str,
    issued_at: str,
    expires_at: str,
) -> TraderAuthorizationClaimsV2:
    """Derive unsigned Trader claims from the actual READY object.

    The human event remains an input for the future isolated Trader verifier;
    this authority-free builder neither verifies presence nor signs approval.
    """

    if type(readiness) is not PilotReadinessAttestationClaimsV2:
        raise ExactFourAuthorityContractError("exact READY claims are required")
    exact_four = readiness.exact_four
    claims = TraderAuthorizationClaimsV2(
        pilot_run_id=readiness.pilot_run_id,
        readiness_attestation_id=readiness.attestation_id,
        exact_four_binding_digest=exact_four.binding_digest,
        controlled_pilot_policy_digest=exact_four.policy.policy_digest,
        budget_scope_digest=exact_four.budget_scope_digest,
        execution_limit_set_digest=exact_four.execution_limit_set_digest,
        lease_ttl_seconds=exact_four.lease_ttl_seconds,
        human_approval_event_id=human_approval_event_id,
        human_approval_event_digest=human_approval_event_digest,
        issued_at=issued_at,
        expires_at=expires_at,
    )
    _validate_current_readiness_trader(
        readiness,
        claims,
        now=_trusted_utc_now(),
    )
    return claims


def _controlled_execution_lease_id(
    *,
    pilot_run_id: str,
    readiness_attestation_id: str,
    trader_authorization_id: str,
    exact_four_binding_digest: str,
) -> str:
    return canonical_authority_digest(
        {
            "authority_scope": CONTROLLED_EXECUTION_SCOPE,
            "pilot_run_id": pilot_run_id,
            "readiness_attestation_id": readiness_attestation_id,
            "trader_authorization_id": trader_authorization_id,
            "exact_four_binding_digest": exact_four_binding_digest,
            "generation": 1,
        }
    )


def _controlled_execution_idempotency_key(lease_id: str) -> str:
    return canonical_authority_digest(
        {
            "authority_scope": CONTROLLED_EXECUTION_SCOPE,
            "lease_id": lease_id,
            "one_shot": True,
        }
    )


@dataclass(frozen=True, slots=True)
class ControlledExecutionClaimsV2:
    """Unsigned one-shot execution subject; never an execution capability."""

    pilot_run_id: str
    readiness_attestation_id: str
    trader_authorization_id: str
    exact_four_binding_digest: str
    controlled_pilot_policy_digest: str
    budget_scope_digest: str
    execution_limit_set_digest: str
    lease_ttl_seconds: int
    lease_id: str
    idempotency_key: str
    issued_at: str
    expires_at: str
    format: str = CONTROLLED_EXECUTION_CLAIMS_FORMAT
    authority_scope: str = CONTROLLED_EXECUTION_SCOPE
    execution_mode: str = PILOT_EXECUTION_MODE
    generation: int = 1
    one_shot: bool = True
    automatic_promotion: bool = False
    mass_research_enabled: bool = False
    live_trading_enabled: bool = False

    def __post_init__(self) -> None:
        if (
            type(self.format) is not str
            or self.format != CONTROLLED_EXECUTION_CLAIMS_FORMAT
            or type(self.authority_scope) is not str
            or self.authority_scope != CONTROLLED_EXECUTION_SCOPE
            or type(self.execution_mode) is not str
            or self.execution_mode != PILOT_EXECUTION_MODE
        ):
            raise ExactFourAuthorityContractError(
                "controlled execution scope is not canonical"
            )
        _require_text(self.pilot_run_id, "pilot_run_id")
        _require_text(self.idempotency_key, "idempotency_key")
        for name in (
            "readiness_attestation_id",
            "trader_authorization_id",
            "exact_four_binding_digest",
            "controlled_pilot_policy_digest",
            "budget_scope_digest",
            "execution_limit_set_digest",
            "lease_id",
            "idempotency_key",
        ):
            _require_digest(getattr(self, name), name)
        if self.controlled_pilot_policy_digest != CONTROLLED_PILOT_POLICY_DIGEST:
            raise ExactFourAuthorityContractError("execution policy digest mismatch")
        canonical = load_exact_four_execution_binding()
        if (
            self.exact_four_binding_digest != canonical.binding_digest
            or self.budget_scope_digest != canonical.budget_scope_digest
            or self.execution_limit_set_digest
            != canonical.execution_limit_set_digest
            or type(self.lease_ttl_seconds) is not int
            or self.lease_ttl_seconds != canonical.lease_ttl_seconds
        ):
            raise ExactFourAuthorityContractError(
                "execution risk, budget, or lease limits are not canonical"
            )
        if type(self.generation) is not int or self.generation != 1:
            raise ExactFourAuthorityContractError("generation two is disabled")
        if type(self.one_shot) is not bool or not self.one_shot:
            raise ExactFourAuthorityContractError(
                "controlled execution lease must be one-shot"
            )
        expected_lease_id = _controlled_execution_lease_id(
            pilot_run_id=self.pilot_run_id,
            readiness_attestation_id=self.readiness_attestation_id,
            trader_authorization_id=self.trader_authorization_id,
            exact_four_binding_digest=self.exact_four_binding_digest,
        )
        if self.lease_id != expected_lease_id:
            raise ExactFourAuthorityContractError(
                "controlled execution lease id is not content-bound"
            )
        if self.idempotency_key != _controlled_execution_idempotency_key(
            self.lease_id
        ):
            raise ExactFourAuthorityContractError(
                "controlled execution idempotency key is not one-shot bound"
            )
        _require_bounded_window(
            self.issued_at,
            self.expires_at,
            ttl_seconds=self.lease_ttl_seconds,
            label="controlled execution lease",
        )
        if (
            self.automatic_promotion is not False
            or self.mass_research_enabled is not False
            or self.live_trading_enabled is not False
        ):
            raise ExactFourAuthorityContractError(
                "controlled execution cannot enable Mass, live, or promotion"
            )

    def to_canonical_dict(self) -> dict[str, Any]:
        return {
            "format": self.format,
            "authority_scope": self.authority_scope,
            "execution_mode": self.execution_mode,
            "pilot_run_id": self.pilot_run_id,
            "readiness_attestation_id": self.readiness_attestation_id,
            "trader_authorization_id": self.trader_authorization_id,
            "exact_four_binding_digest": self.exact_four_binding_digest,
            "controlled_pilot_policy_digest": (
                self.controlled_pilot_policy_digest
            ),
            "budget_scope_digest": self.budget_scope_digest,
            "execution_limit_set_digest": self.execution_limit_set_digest,
            "lease_ttl_seconds": self.lease_ttl_seconds,
            "lease_id": self.lease_id,
            "idempotency_key": self.idempotency_key,
            "issued_at": self.issued_at,
            "expires_at": self.expires_at,
            "generation": self.generation,
            "one_shot": self.one_shot,
            "automatic_promotion": self.automatic_promotion,
            "mass_research_enabled": self.mass_research_enabled,
            "live_trading_enabled": self.live_trading_enabled,
        }

    @property
    def request_id(self) -> str:
        return canonical_authority_digest(self.to_canonical_dict())

    def to_dict(self) -> dict[str, Any]:
        return {**self.to_canonical_dict(), "request_id": self.request_id}


def _claims_from_document(
    document: dict[str, Any],
) -> (
    PilotReadinessAttestationClaimsV2
    | TraderAuthorizationClaimsV2
    | ControlledExecutionClaimsV2
):
    format_value = document.get("format")
    body = dict(document)
    if format_value == PILOT_READINESS_CLAIMS_FORMAT:
        body.pop("attestation_id", None)
        snapshot_document = body.pop("snapshot", None)
        exact_four_document = body.pop("exact_four", None)
        if type(snapshot_document) is not dict or type(exact_four_document) is not dict:
            raise ExactFourAuthorityContractError(
                "READY document must carry closed snapshot and exact-four objects"
            )
        exact_four = load_exact_four_execution_binding()
        if exact_four_document != exact_four.to_dict():
            raise ExactFourAuthorityContractError(
                "READY document exact-four body is not the canonical compiler output"
            )
        snapshot = ReadySnapshotLineage(**snapshot_document)
        return PilotReadinessAttestationClaimsV2(
            snapshot=snapshot,
            exact_four=exact_four,
            **body,
        )
    if format_value == TRADER_AUTHORIZATION_CLAIMS_FORMAT:
        body.pop("authorization_id", None)
        return TraderAuthorizationClaimsV2(**body)
    if format_value == CONTROLLED_EXECUTION_CLAIMS_FORMAT:
        body.pop("request_id", None)
        return ControlledExecutionClaimsV2(**body)
    raise ExactFourAuthorityContractError("unknown exact-four authority claims format")


def _validate_exact_four_authority_document_structural(document: Any) -> str:
    """Validate syntax and semantics without asserting current authority time.

    This deliberately private helper exists for constructors, fixture creation,
    and protocol replay.  Callers processing an untrusted downstream document
    must use one of the parent-required public parsers below.
    """

    if type(document) is not dict:
        raise ExactFourAuthorityContractError(
            "exact-four authority document must be one exact dict"
        )
    _require_exact_json(document)
    try:
        from jsonschema import Draft202012Validator, FormatChecker

        validator = Draft202012Validator(
            load_exact_four_authority_schema(),
            format_checker=FormatChecker(),
        )
        errors = sorted(
            validator.iter_errors(document),
            key=lambda item: tuple(str(part) for part in item.path),
        )
    except ExactFourAuthorityContractError:
        raise
    except Exception as exc:
        raise ExactFourAuthorityContractError(
            "cannot validate exact-four authority document schema"
        ) from exc
    if errors:
        location = "$" + "".join(
            f"[{part}]" if type(part) is int else f".{part}"
            for part in errors[0].path
        )
        raise ExactFourAuthorityContractError(
            f"exact-four authority schema violation at {location}: "
            f"{errors[0].message}"
        )
    claims = _claims_from_document(document)
    rebuilt = claims.to_dict()
    if rebuilt != document:
        raise ExactFourAuthorityContractError(
            "exact-four authority document content id or canonical body is invalid"
        )
    if type(claims) is PilotReadinessAttestationClaimsV2:
        return claims.attestation_id
    if type(claims) is TraderAuthorizationClaimsV2:
        return claims.authorization_id
    return claims.request_id


def _parse_exact_four_authority_document_structural(
    raw: bytes | str,
) -> tuple[dict[str, Any], Any]:
    document = _strict_json_loads(raw, label="exact-four authority document")
    _validate_exact_four_authority_document_structural(document)
    return document, _claims_from_document(document)


def parse_and_validate_pilot_readiness_document(
    raw: bytes | str,
) -> dict[str, Any]:
    """Parse one READY document and require it to be current now."""

    document, claims = _parse_exact_four_authority_document_structural(raw)
    if type(claims) is not PilotReadinessAttestationClaimsV2:
        raise ExactFourAuthorityContractError("a READY document is required")
    _validate_current_readiness(claims, now=_trusted_utc_now())
    return document


def parse_and_validate_trader_authorization_document(
    raw: bytes | str,
    *,
    readiness: PilotReadinessAttestationClaimsV2,
) -> dict[str, Any]:
    """Parse Trader claims only in the context of their actual READY parent."""

    document, claims = _parse_exact_four_authority_document_structural(raw)
    if type(claims) is not TraderAuthorizationClaimsV2:
        raise ExactFourAuthorityContractError(
            "a Trader authorization document is required"
        )
    _validate_current_readiness_trader(
        readiness,
        claims,
        now=_trusted_utc_now(),
    )
    return document


def parse_and_validate_controlled_execution_document(
    raw: bytes | str,
    *,
    readiness: PilotReadinessAttestationClaimsV2,
    trader: TraderAuthorizationClaimsV2,
) -> dict[str, Any]:
    """Parse execution claims only with their actual READY and Trader parents."""

    document, claims = _parse_exact_four_authority_document_structural(raw)
    if type(claims) is not ControlledExecutionClaimsV2:
        raise ExactFourAuthorityContractError(
            "a controlled execution document is required"
        )
    _validate_current_claim_chain(readiness, trader, claims)
    return document


def parse_and_validate_exact_four_authority_document(
    raw: bytes | str,
    *,
    readiness: PilotReadinessAttestationClaimsV2 | None = None,
    trader: TraderAuthorizationClaimsV2 | None = None,
) -> dict[str, Any]:
    """Compatibility dispatcher with mandatory parents for downstream claims.

    A READY body is self-contained.  Trader and execution bodies are not; they
    are rejected unless their actual parent claims are supplied and the entire
    resulting chain is current at the module-owned UTC clock.
    """

    document, claims = _parse_exact_four_authority_document_structural(raw)
    if type(claims) is PilotReadinessAttestationClaimsV2:
        _validate_current_readiness(claims, now=_trusted_utc_now())
        return document
    if type(claims) is TraderAuthorizationClaimsV2:
        if type(readiness) is not PilotReadinessAttestationClaimsV2:
            raise ExactFourAuthorityContractError(
                "Trader document validation requires the actual READY parent"
            )
        _validate_current_readiness_trader(
            readiness,
            claims,
            now=_trusted_utc_now(),
        )
        return document
    if (
        type(readiness) is not PilotReadinessAttestationClaimsV2
        or type(trader) is not TraderAuthorizationClaimsV2
    ):
        raise ExactFourAuthorityContractError(
            "execution document validation requires actual READY and Trader parents"
        )
    _validate_current_claim_chain(readiness, trader, claims)
    return document


def validate_exact_four_authority_claims_v2(
    claims: Any,
    *,
    readiness: PilotReadinessAttestationClaimsV2 | None = None,
    trader: TraderAuthorizationClaimsV2 | None = None,
) -> str:
    """Revalidate current claims, requiring actual parents downstream."""

    if type(claims) not in {
        PilotReadinessAttestationClaimsV2,
        TraderAuthorizationClaimsV2,
        ControlledExecutionClaimsV2,
    }:
        raise ExactFourAuthorityContractError(
            "an exact unsigned v2 claims object is required"
        )
    content_id = _validate_exact_four_authority_document_structural(claims.to_dict())
    if type(claims) is PilotReadinessAttestationClaimsV2:
        _validate_current_readiness(claims, now=_trusted_utc_now())
    elif type(claims) is TraderAuthorizationClaimsV2:
        if type(readiness) is not PilotReadinessAttestationClaimsV2:
            raise ExactFourAuthorityContractError(
                "Trader claims validation requires the actual READY parent"
            )
        _validate_current_readiness_trader(
            readiness,
            claims,
            now=_trusted_utc_now(),
        )
    else:
        if (
            type(readiness) is not PilotReadinessAttestationClaimsV2
            or type(trader) is not TraderAuthorizationClaimsV2
        ):
            raise ExactFourAuthorityContractError(
                "execution claims validation requires actual READY and Trader parents"
            )
        _validate_current_claim_chain(readiness, trader, claims)
    return content_id


def _validate_readiness_trader_link(
    readiness: PilotReadinessAttestationClaimsV2,
    trader: TraderAuthorizationClaimsV2,
) -> None:
    _validate_exact_four_authority_document_structural(readiness.to_dict())
    _validate_exact_four_authority_document_structural(trader.to_dict())
    exact_four = readiness.exact_four
    if (
        trader.pilot_run_id != readiness.pilot_run_id
        or trader.readiness_attestation_id != readiness.attestation_id
        or trader.exact_four_binding_digest != exact_four.binding_digest
        or trader.controlled_pilot_policy_digest != exact_four.policy.policy_digest
        or trader.budget_scope_digest != exact_four.budget_scope_digest
        or trader.execution_limit_set_digest != exact_four.execution_limit_set_digest
        or trader.lease_ttl_seconds != exact_four.lease_ttl_seconds
    ):
        raise ExactFourAuthorityContractError(
            "Trader authorization does not bind the supplied READY object"
        )
    readiness_issued = _parsed_timestamp(readiness.issued_at, "READY issued_at")
    readiness_expires = _parsed_timestamp(readiness.expires_at, "READY expires_at")
    trader_issued = _parsed_timestamp(trader.issued_at, "Trader issued_at")
    trader_expires = _parsed_timestamp(trader.expires_at, "Trader expires_at")
    if trader_issued < readiness_issued or trader_expires > readiness_expires:
        raise ExactFourAuthorityContractError(
            "Trader authorization lifetime is outside the supplied READY lifetime"
        )


def _validate_current_readiness(
    readiness: PilotReadinessAttestationClaimsV2,
    *,
    now: datetime,
) -> None:
    if type(readiness) is not PilotReadinessAttestationClaimsV2:
        raise ExactFourAuthorityContractError("exact READY claims are required")
    _validate_exact_four_authority_document_structural(readiness.to_dict())
    _require_current_window(
        readiness.issued_at,
        readiness.expires_at,
        label="READY claims",
        now=now,
    )


def _validate_current_readiness_trader(
    readiness: PilotReadinessAttestationClaimsV2,
    trader: TraderAuthorizationClaimsV2,
    *,
    now: datetime,
) -> None:
    _validate_readiness_trader_link(readiness, trader)
    _require_current_window(
        readiness.issued_at,
        readiness.expires_at,
        label="READY claims",
        now=now,
    )
    _require_current_window(
        trader.issued_at,
        trader.expires_at,
        label="Trader authorization",
        now=now,
    )


def _validate_claim_chain_structural(
    readiness: PilotReadinessAttestationClaimsV2,
    trader: TraderAuthorizationClaimsV2,
    execution: ControlledExecutionClaimsV2,
) -> str:
    """Private replay validator; it intentionally makes no current-time claim."""

    if type(readiness) is not PilotReadinessAttestationClaimsV2:
        raise ExactFourAuthorityContractError("exact READY claims are required")
    if type(trader) is not TraderAuthorizationClaimsV2:
        raise ExactFourAuthorityContractError("exact Trader claims are required")
    if type(execution) is not ControlledExecutionClaimsV2:
        raise ExactFourAuthorityContractError("exact execution claims are required")
    _validate_readiness_trader_link(readiness, trader)
    _validate_exact_four_authority_document_structural(execution.to_dict())
    if (
        execution.pilot_run_id != readiness.pilot_run_id
        or execution.readiness_attestation_id != readiness.attestation_id
        or execution.trader_authorization_id != trader.authorization_id
        or execution.exact_four_binding_digest != readiness.exact_four.binding_digest
        or execution.controlled_pilot_policy_digest
        != readiness.exact_four.policy.policy_digest
        or execution.budget_scope_digest != readiness.exact_four.budget_scope_digest
        or execution.execution_limit_set_digest
        != readiness.exact_four.execution_limit_set_digest
        or execution.lease_ttl_seconds != readiness.exact_four.lease_ttl_seconds
    ):
        raise ExactFourAuthorityContractError(
            "execution claims do not bind the supplied READY and Trader objects"
        )
    trader_issued = _parsed_timestamp(trader.issued_at, "Trader issued_at")
    trader_expires = _parsed_timestamp(trader.expires_at, "Trader expires_at")
    execution_issued = _parsed_timestamp(execution.issued_at, "execution issued_at")
    execution_expires = _parsed_timestamp(execution.expires_at, "execution expires_at")
    if execution_issued < trader_issued or execution_expires > trader_expires:
        raise ExactFourAuthorityContractError(
            "execution lease lifetime is outside the human Trader authorization"
        )
    return canonical_authority_digest(
        {
            "pilot_run_id": readiness.pilot_run_id,
            "readiness_attestation_id": readiness.attestation_id,
            "trader_authorization_id": trader.authorization_id,
            "execution_request_id": execution.request_id,
            "lease_id": execution.lease_id,
        }
    )


def _validate_current_claim_chain(
    readiness: PilotReadinessAttestationClaimsV2,
    trader: TraderAuthorizationClaimsV2,
    execution: ControlledExecutionClaimsV2,
) -> str:
    chain_digest = _validate_claim_chain_structural(readiness, trader, execution)
    now = _trusted_utc_now()
    _validate_current_readiness_trader(readiness, trader, now=now)
    _require_current_window(
        execution.issued_at,
        execution.expires_at,
        label="controlled execution lease",
        now=now,
    )
    return chain_digest


def validate_exact_four_authority_claim_chain_v2(
    readiness: PilotReadinessAttestationClaimsV2,
    trader: TraderAuthorizationClaimsV2,
    execution: ControlledExecutionClaimsV2,
) -> str:
    """Validate one READY -> human Trader -> one-shot execution claims chain.

    The returned digest is only a diagnostic content address.  It is not a
    verified readiness, Trader authorization, or execution capability.
    """

    return _validate_current_claim_chain(readiness, trader, execution)


def build_controlled_execution_claims_v2(
    readiness: PilotReadinessAttestationClaimsV2,
    trader: TraderAuthorizationClaimsV2,
    *,
    issued_at: str,
    expires_at: str,
) -> ControlledExecutionClaimsV2:
    """Build unsigned, PENDING one-shot claims from the actual READY/Trader pair."""

    if type(readiness) is not PilotReadinessAttestationClaimsV2:
        raise ExactFourAuthorityContractError("exact READY claims are required")
    if type(trader) is not TraderAuthorizationClaimsV2:
        raise ExactFourAuthorityContractError("exact Trader claims are required")
    _validate_readiness_trader_link(readiness, trader)
    exact_four = readiness.exact_four
    lease_id = _controlled_execution_lease_id(
        pilot_run_id=readiness.pilot_run_id,
        readiness_attestation_id=readiness.attestation_id,
        trader_authorization_id=trader.authorization_id,
        exact_four_binding_digest=exact_four.binding_digest,
    )
    claims = ControlledExecutionClaimsV2(
        pilot_run_id=readiness.pilot_run_id,
        readiness_attestation_id=readiness.attestation_id,
        trader_authorization_id=trader.authorization_id,
        exact_four_binding_digest=exact_four.binding_digest,
        controlled_pilot_policy_digest=exact_four.policy.policy_digest,
        budget_scope_digest=exact_four.budget_scope_digest,
        execution_limit_set_digest=exact_four.execution_limit_set_digest,
        lease_ttl_seconds=exact_four.lease_ttl_seconds,
        lease_id=lease_id,
        idempotency_key=_controlled_execution_idempotency_key(lease_id),
        issued_at=issued_at,
        expires_at=expires_at,
    )
    validate_exact_four_authority_claim_chain_v2(readiness, trader, claims)
    return claims


class _PendingCapability:
    __slots__ = ()

    def __new__(cls, *args: Any, **kwargs: Any) -> NoReturn:
        del args, kwargs
        raise ExactFourAuthorityPending(
            f"{cls.__name__} is unavailable: {AUTHORITY_PROTOCOL_STATE}"
        )


class VerifiedPilotReadinessV2(_PendingCapability):
    """Opaque future output of the isolated READY verifier."""

    def __init_subclass__(cls, **kwargs: Any) -> None:
        raise TypeError("VerifiedPilotReadinessV2 is final")


class VerifiedExactFourTraderAuthorizationV2(_PendingCapability):
    """Opaque future output of the isolated human Trader verifier."""

    def __init_subclass__(cls, **kwargs: Any) -> None:
        raise TypeError("VerifiedExactFourTraderAuthorizationV2 is final")


class AuthorizedExactFourExecutionV2(_PendingCapability):
    """Opaque future output of the controlled one-shot execution writer."""

    def __init_subclass__(cls, **kwargs: Any) -> None:
        raise TypeError("AuthorizedExactFourExecutionV2 is final")


def authority_schema_path() -> Path:
    return repo_root() / EXACT_FOUR_AUTHORITY_SCHEMA_REL


def load_exact_four_authority_schema() -> dict[str, Any]:
    try:
        raw = authority_schema_path().read_bytes()
        value = _strict_json_loads(raw, label="exact-four authority protocol schema")
    except (OSError, ExactFourAuthorityContractError) as exc:
        raise ExactFourAuthorityContractError(
            "cannot load exact-four authority protocol schema"
        ) from exc
    raw_digest = "sha256:" + hashlib.sha256(raw).hexdigest()
    if raw_digest != PINNED_EXACT_FOUR_AUTHORITY_SCHEMA_RAW_DIGEST:
        raise ExactFourAuthorityContractError(
            "pinned exact-four authority protocol schema raw digest mismatch"
        )
    if type(value) is not dict:
        raise ExactFourAuthorityContractError(
            "exact-four authority protocol schema must be an object"
        )
    if set(value) != {"$schema", "$id", "title", "oneOf", "$defs"} or (
        value.get("$schema") != CONTROLLED_PILOT_POLICY_SCHEMA_URI
        or value.get("$id")
        != "https://quant-platform.local/specs/ready/"
        "exact_four_authority_protocol.schema.json"
        or value.get("title")
        != "Exact-four controlled-pilot v2 authority protocol"
    ):
        raise ExactFourAuthorityContractError(
            "exact-four authority protocol schema identity is not closed"
        )
    if canonical_authority_digest(value) != PINNED_EXACT_FOUR_AUTHORITY_SCHEMA_DIGEST:
        raise ExactFourAuthorityContractError(
            "pinned exact-four authority protocol schema digest mismatch"
        )
    try:
        from jsonschema import Draft202012Validator

        Draft202012Validator.check_schema(value)
    except Exception as exc:
        raise ExactFourAuthorityContractError(
            "exact-four authority protocol schema is invalid"
        ) from exc
    return value


def require_verified_pilot_readiness_v2(value: Any) -> VerifiedPilotReadinessV2:
    """Nominal gate: claims/booleans/Trader tokens can never substitute READY."""
    del value
    raise ExactFourAuthorityPending("isolated v2 READY verification is not active")


def require_verified_trader_authorization_v2(
    value: Any,
) -> VerifiedExactFourTraderAuthorizationV2:
    """Nominal gate: READY or execution claims cannot authorize a Trader."""
    del value
    raise ExactFourAuthorityPending(
        "isolated v2 human Trader authorization is not active"
    )


def require_authorized_exact_four_execution_v2(
    value: Any,
) -> AuthorizedExactFourExecutionV2:
    """Nominal gate: only the future one-shot writer can return this type."""
    del value
    raise ExactFourAuthorityPending(
        "isolated v2 controlled execution writer is not active"
    )


__all__ = [
    "AUTHORITY_PROTOCOL_STATE",
    "AuthorizedExactFourExecutionV2",
    "CONTROLLED_EXECUTION_CLAIMS_FORMAT",
    "CONTROLLED_EXECUTION_SCOPE",
    "CONTROLLED_PILOT_POLICY_DIGEST",
    "CONTROLLED_PILOT_POLICY_ID",
    "CONTROLLED_PILOT_POLICY_RAW_DIGEST",
    "ControlledExecutionClaimsV2",
    "ControlledPilotArtifactCardinality",
    "ControlledPilotPolicyPin",
    "EXACT_FOUR_BINDING_FORMAT",
    "ExactFourAuthorityContractError",
    "ExactFourAuthorityPending",
    "ExactFourExecutionBinding",
    "FeatureExecutionPin",
    "PILOT_EXECUTION_MODE",
    "PILOT_READINESS_CLAIMS_FORMAT",
    "PILOT_READINESS_SCOPE",
    "PLAN_EXECUTION_BINDING_FORMAT",
    "PINNED_EXACT_FOUR_AUTHORITY_SCHEMA_DIGEST",
    "PINNED_EXACT_FOUR_AUTHORITY_SCHEMA_RAW_DIGEST",
    "PilotReadinessAttestationClaimsV2",
    "PlanExecutionBinding",
    "ReadySnapshotLineage",
    "TRADER_AUTHORIZATION_CLAIMS_FORMAT",
    "TRADER_AUTHORIZATION_SCOPE",
    "TraderAuthorizationClaimsV2",
    "VerifiedExactFourTraderAuthorizationV2",
    "VerifiedPilotReadinessV2",
    "authority_schema_path",
    "build_controlled_execution_claims_v2",
    "build_trader_authorization_claims_v2",
    "canonical_authority_digest",
    "load_controlled_pilot_policy",
    "load_exact_four_authority_schema",
    "load_exact_four_execution_binding",
    "parse_and_validate_exact_four_authority_document",
    "parse_and_validate_controlled_execution_document",
    "parse_and_validate_pilot_readiness_document",
    "parse_and_validate_trader_authorization_document",
    "require_authorized_exact_four_execution_v2",
    "require_verified_pilot_readiness_v2",
    "require_verified_trader_authorization_v2",
    "validate_exact_four_authority_claim_chain_v2",
    "validate_exact_four_authority_claims_v2",
]
