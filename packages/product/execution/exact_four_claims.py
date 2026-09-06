"""READY -> historical unsigned Trader lineage -> Execution validation.

This module is deliberately authority-free.  It can compile immutable claims
and lineage pins, but it cannot sign READY, record human approval, authorize a
Trader, or start execution.  The three positive capability types are nominal
and non-constructible until their separately permissioned verifiers exist.

``TraderAuthorizationClaimsV2`` is retained only so existing result manifests
remain replayable. It is not a production authorization contract. WebAuthn
Trader v2 is a future live-order surface, not an active Pilot dependency.

The existing v1 verification paths remain available for audit compatibility.
Nothing in this module enables Mass, live orders, generation two, or automatic
promotion.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from execution.exact_four_binding import (
    ControlledPilotArtifactCardinality,
    ExactFourExecutionBinding,
    FeatureExecutionPin,
    PlanExecutionBinding,
    load_exact_four_execution_binding,
)
from execution.exact_four_codec import (
    AUTHORITY_PROTOCOL_STATE,
    CONTROLLED_EXECUTION_CLAIMS_FORMAT,
    CONTROLLED_EXECUTION_SCOPE,
    EXACT_FOUR_BINDING_FORMAT,
    HISTORICAL_TRADER_AUTHORIZATION_CLAIMS_FORMAT,
    PILOT_EXECUTION_MODE,
    PILOT_READINESS_CLAIMS_FORMAT,
    PILOT_READINESS_SCOPE,
    PLAN_EXECUTION_BINDING_FORMAT,
    TRADER_AUTHORIZATION_CLAIMS_FORMAT,
    TRADER_AUTHORIZATION_SCOPE,
    ExactFourAuthorityContractError,
    ExactFourAuthorityPending,
    _parsed_timestamp,
    _require_bounded_window,
    _require_current_token,
    _require_current_window,
    _require_date,
    _require_digest,
    _require_exact_json,
    _require_positive_int,
    _require_text,
    _strict_json_loads,
    _trusted_utc_now,
    canonical_authority_digest,
)
from execution.exact_four_protocol import (
    AuthorizedExactFourExecutionV2,
    PINNED_EXACT_FOUR_AUTHORITY_SCHEMA_DIGEST,
    PINNED_EXACT_FOUR_AUTHORITY_SCHEMA_RAW_DIGEST,
    VerifiedExactFourTraderAuthorizationV2,
    VerifiedPilotReadinessV2,
    authority_schema_path,
    load_exact_four_authority_schema,
    require_authorized_exact_four_execution_v2,
    require_verified_pilot_readiness_v2,
    require_verified_trader_authorization_v2,
)
from selection.controlled_pilot_policy import (
    CONTROLLED_PILOT_IDENTITY,
    CONTROLLED_PILOT_POLICY_DIGEST,
    CONTROLLED_PILOT_POLICY_ID,
    CONTROLLED_PILOT_POLICY_RAW_DIGEST,
    ControlledPilotPolicyError,
    ControlledPilotPolicyPin,
    load_controlled_pilot_policy,
    require_controlled_pilot_identity,
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
    environment: str
    ready_authority_instance_id: str
    ready_authority_resource_digest: str
    snapshot: ReadySnapshotLineage
    exact_four: ExactFourExecutionBinding
    issued_at: str
    expires_at: str
    issuer: str = "PilotReadyPublicationService/v2"
    format: str = PILOT_READINESS_CLAIMS_FORMAT
    authority_scope: str = PILOT_READINESS_SCOPE
    identity: str = CONTROLLED_PILOT_IDENTITY

    def __post_init__(self) -> None:
        if type(self.snapshot) is not ReadySnapshotLineage:
            raise ExactFourAuthorityContractError(
                "READY claims require exact ReadySnapshotLineage"
            )
        _require_text(self.pilot_run_id, "pilot_run_id")
        if (
            type(self.environment) is not str
            or self.environment not in {"staging", "production"}
            or self.ready_authority_instance_id
            != f"ready-authority/{self.environment}/v1"
        ):
            raise ExactFourAuthorityContractError(
                "READY claims authority environment/instance is invalid"
            )
        _require_digest(
            self.ready_authority_resource_digest,
            "ready_authority_resource_digest",
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
        self.snapshot.__post_init__()
        self.exact_four.__post_init__()
        try:
            require_controlled_pilot_identity(self.identity)
            require_controlled_pilot_identity(self.exact_four.identity)
        except ControlledPilotPolicyError as exc:
            raise ExactFourAuthorityContractError(str(exc)) from exc
        if self.identity != self.exact_four.identity:
            raise ExactFourAuthorityContractError(
                "READY claims identity does not match execution binding identity"
            )
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
            "identity": self.identity,
            "issuer": self.issuer,
            "authority_scope": self.authority_scope,
            "pilot_run_id": self.pilot_run_id,
            "environment": self.environment,
            "ready_authority_instance_id": self.ready_authority_instance_id,
            "ready_authority_resource_digest": (
                self.ready_authority_resource_digest
            ),
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
    """Historical unsigned lineage DTO; never a verified authorization."""

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
    """Derive the historical unsigned result-lineage DTO from READY.

    The caller-supplied human event fields are why this shape is explicitly
    non-authoritative. The production v2 pre-approval subject does not consume
    them.
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
    identity: str = CONTROLLED_PILOT_IDENTITY

    def __post_init__(self) -> None:
        try:
            require_controlled_pilot_identity(self.identity)
        except ControlledPilotPolicyError as exc:
            raise ExactFourAuthorityContractError(str(exc)) from exc
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
            "identity": self.identity,
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


def _validate_current_claim_chain_at(
    readiness: PilotReadinessAttestationClaimsV2,
    trader: TraderAuthorizationClaimsV2,
    execution: ControlledExecutionClaimsV2,
    *,
    now: datetime,
) -> str:
    chain_digest = _validate_claim_chain_structural(readiness, trader, execution)
    _validate_current_readiness_trader(readiness, trader, now=now)
    _require_current_window(
        execution.issued_at,
        execution.expires_at,
        label="controlled execution lease",
        now=now,
    )
    return chain_digest


def _validate_current_claim_chain(
    readiness: PilotReadinessAttestationClaimsV2,
    trader: TraderAuthorizationClaimsV2,
    execution: ControlledExecutionClaimsV2,
) -> str:
    return _validate_current_claim_chain_at(
        readiness,
        trader,
        execution,
        now=_trusted_utc_now(),
    )


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


__all__ = [
    "AUTHORITY_PROTOCOL_STATE",
    "AuthorizedExactFourExecutionV2",
    "CONTROLLED_EXECUTION_CLAIMS_FORMAT",
    "CONTROLLED_EXECUTION_SCOPE",
    "CONTROLLED_PILOT_IDENTITY",
    "CONTROLLED_PILOT_POLICY_DIGEST",
    "CONTROLLED_PILOT_POLICY_ID",
    "CONTROLLED_PILOT_POLICY_RAW_DIGEST",
    "require_controlled_pilot_identity",
    "ControlledExecutionClaimsV2",
    "ControlledPilotArtifactCardinality",
    "ControlledPilotPolicyPin",
    "EXACT_FOUR_BINDING_FORMAT",
    "ExactFourAuthorityContractError",
    "ExactFourAuthorityPending",
    "ExactFourExecutionBinding",
    "FeatureExecutionPin",
    "HISTORICAL_TRADER_AUTHORIZATION_CLAIMS_FORMAT",
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
