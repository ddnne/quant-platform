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
from datetime import date, datetime
from pathlib import Path
from typing import Any, NoReturn

from qp_paths import repo_root
from research.ready_manifest import load_exact_four_pilot_ready_binding
from research.universe_contract import EXACT_FOUR_UNIVERSE_RULE_DIGEST
from selection.budget_ledger import MassResearchDisabledError
from selection.controlled_pilot_policy import (
    CONTROLLED_PILOT_POLICY_DIGEST,
    CONTROLLED_PILOT_POLICY_ID,
    CONTROLLED_PILOT_POLICY_SCHEMA_URI,
    ControlledPilotPolicyPin,
    load_controlled_pilot_policy,
)


EXACT_FOUR_AUTHORITY_SCHEMA_REL = (
    Path("specs") / "ready" / "exact_four_authority_protocol.schema.json"
)
PINNED_EXACT_FOUR_AUTHORITY_SCHEMA_DIGEST = (
    "sha256:7067a7bf42530485fb8c60db05a494ef43fd842986ba40f21562b7d01958d8a1"
)
PINNED_EXACT_FOUR_AUTHORITY_SCHEMA_RAW_DIGEST = (
    "sha256:19089c9627020bd29cdce4ae61b8a78b12dbb7a2d706d672ac20780d810a4954"
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

_SHA256_RE = re.compile(r"sha256:[0-9a-f]{64}\Z")


class ExactFourAuthorityContractError(MassResearchDisabledError):
    """Raised when immutable exact-four authority claims are not canonical."""


class ExactFourAuthorityPending(ExactFourAuthorityContractError):
    """Raised because no v2 publication/approval/execution principal exists."""


def _canonical_bytes(value: Any) -> bytes:
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
        if type(self.artifact_cardinality) is not ControlledPilotArtifactCardinality:
            raise ExactFourAuthorityContractError(
                "exact ControlledPilotArtifactCardinality is required"
            )
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
            "automatic_promotion": False,
            "mass_research_enabled": False,
            "live_trading_enabled": False,
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
    coverage_proof_digest: str
    raw_proof_digest: str
    receipt_proof_digest: str
    validation_proof_digest: str
    b0_proof_digest: str
    b4_proof_digest: str
    pit_contract_set_digest: str
    source_generation: str
    applied_sync_generation: str
    export_cursor: str
    applied_cursor: str
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
            "b0_proof_digest",
            "b4_proof_digest",
            "pit_contract_set_digest",
            "feature_generation",
            "catalog_generation",
        ):
            _require_digest(getattr(self, name), name)
        for name in (
            "coverage_policy_version",
            "source_generation",
            "applied_sync_generation",
            "export_cursor",
            "applied_cursor",
        ):
            _require_text(getattr(self, name), name)
        if not (
            self.source_generation
            == self.applied_sync_generation
            == self.export_cursor
            == self.applied_cursor
        ):
            raise ExactFourAuthorityContractError(
                "source/export/applied generation and cursor must be current"
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
            "coverage_proof_digest": self.coverage_proof_digest,
            "raw_proof_digest": self.raw_proof_digest,
            "receipt_proof_digest": self.receipt_proof_digest,
            "validation_proof_digest": self.validation_proof_digest,
            "b0_proof_digest": self.b0_proof_digest,
            "b4_proof_digest": self.b4_proof_digest,
            "pit_contract_set_digest": self.pit_contract_set_digest,
            "source_generation": self.source_generation,
            "applied_sync_generation": self.applied_sync_generation,
            "export_cursor": self.export_cursor,
            "applied_cursor": self.applied_cursor,
            "feature_generation": self.feature_generation,
            "catalog_generation": self.catalog_generation,
        }


@dataclass(frozen=True, slots=True)
class PilotReadinessAttestationClaimsV2:
    """Unsigned, content-addressed READY claims; never a verified capability."""

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
        issued = _require_timestamp(self.issued_at, "issued_at")
        expires = _require_timestamp(self.expires_at, "expires_at")
        if datetime.fromisoformat(issued.replace("Z", "+00:00")) >= (
            datetime.fromisoformat(expires.replace("Z", "+00:00"))
        ):
            raise ExactFourAuthorityContractError(
                "READY claims expiry must be after issuance"
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
        issued = _require_timestamp(self.issued_at, "issued_at")
        expires = _require_timestamp(self.expires_at, "expires_at")
        if datetime.fromisoformat(issued.replace("Z", "+00:00")) >= (
            datetime.fromisoformat(expires.replace("Z", "+00:00"))
        ):
            raise ExactFourAuthorityContractError(
                "Trader authorization expiry must be after issuance"
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
            "automatic_promotion": False,
            "mass_research_enabled": False,
            "live_trading_enabled": False,
        }

    @property
    def authorization_id(self) -> str:
        return canonical_authority_digest(self.to_canonical_dict())

    def to_dict(self) -> dict[str, Any]:
        return {**self.to_canonical_dict(), "authorization_id": self.authorization_id}


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
    idempotency_key: str
    format: str = CONTROLLED_EXECUTION_CLAIMS_FORMAT
    authority_scope: str = CONTROLLED_EXECUTION_SCOPE
    execution_mode: str = PILOT_EXECUTION_MODE
    generation: int = 1
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
            "idempotency_key": self.idempotency_key,
            "generation": 1,
            "automatic_promotion": False,
            "mass_research_enabled": False,
            "live_trading_enabled": False,
        }

    @property
    def request_id(self) -> str:
        return canonical_authority_digest(self.to_canonical_dict())

    def to_dict(self) -> dict[str, Any]:
        return {**self.to_canonical_dict(), "request_id": self.request_id}


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
        value = json.loads(raw)
    except (OSError, json.JSONDecodeError) as exc:
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
    "canonical_authority_digest",
    "load_controlled_pilot_policy",
    "load_exact_four_authority_schema",
    "load_exact_four_execution_binding",
    "require_authorized_exact_four_execution_v2",
    "require_verified_pilot_readiness_v2",
    "require_verified_trader_authorization_v2",
]
