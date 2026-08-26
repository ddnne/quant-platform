"""Behavioral invariants for the PENDING exact-four v2 authority protocol."""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace

import pytest
from jsonschema import Draft202012Validator, FormatChecker, ValidationError

from execution.exact_four_authority_contract import (
    AUTHORITY_PROTOCOL_STATE,
    CONTROLLED_PILOT_POLICY_DIGEST,
    AuthorizedExactFourExecutionV2,
    ControlledExecutionClaimsV2,
    ExactFourAuthorityContractError,
    ExactFourAuthorityPending,
    PINNED_EXACT_FOUR_AUTHORITY_SCHEMA_DIGEST,
    PINNED_EXACT_FOUR_AUTHORITY_SCHEMA_RAW_DIGEST,
    PilotReadinessAttestationClaimsV2,
    ReadySnapshotLineage,
    TraderAuthorizationClaimsV2,
    VerifiedExactFourTraderAuthorizationV2,
    VerifiedPilotReadinessV2,
    canonical_authority_digest,
    load_controlled_pilot_policy,
    load_exact_four_authority_schema,
    load_exact_four_execution_binding,
    require_authorized_exact_four_execution_v2,
    require_verified_pilot_readiness_v2,
    require_verified_trader_authorization_v2,
)
from qp_paths import repo_root
from research.experiment_plans import PILOT_EXPERIMENT_PLAN_IDS
from research.ready_manifest import load_exact_four_pilot_ready_binding
from selection.controlled_pilot_policy import ControlledPilotPolicyError


def _digest(label: str) -> str:
    return canonical_authority_digest({"test": label})


def _snapshot(**overrides: object) -> ReadySnapshotLineage:
    exact_four = load_exact_four_execution_binding()
    values: dict[str, object] = {
        "snapshot_id": _digest("snapshot"),
        "ready_manifest_digest": _digest("manifest"),
        "immutable_snapshot_digest": _digest("immutable-db"),
        "governed_membership_digest": (
            exact_four.required_dataset_membership_digest
        ),
        "universe_rule_digest": exact_four.universe_rule_digest,
        "resolved_universe_digest": _digest("resolved-universe"),
        "coverage_policy_version": exact_four.coverage_policy_version,
        "coverage_policy_digest": exact_four.coverage_policy_digest,
        "coverage_proof_digest": _digest("coverage"),
        "raw_proof_digest": _digest("raw"),
        "receipt_proof_digest": _digest("receipt"),
        "validation_proof_digest": _digest("validation"),
        "b0_proof_digest": _digest("b0"),
        "b4_proof_digest": _digest("b4"),
        "pit_contract_set_digest": _digest("pit-contracts"),
        "source_generation": "cursor-42",
        "applied_sync_generation": "cursor-42",
        "export_cursor": "cursor-42",
        "applied_cursor": "cursor-42",
        "feature_generation": _digest("features"),
        "catalog_generation": _digest("catalog"),
    }
    values.update(overrides)
    return ReadySnapshotLineage(**values)  # type: ignore[arg-type]


def _claims() -> tuple[
    PilotReadinessAttestationClaimsV2,
    TraderAuthorizationClaimsV2,
    ControlledExecutionClaimsV2,
]:
    exact_four = load_exact_four_execution_binding()
    readiness = PilotReadinessAttestationClaimsV2(
        snapshot=_snapshot(),
        exact_four=exact_four,
        issued_at="2026-08-26T00:00:00+00:00",
        expires_at="2026-08-26T00:30:00+00:00",
    )
    trader = TraderAuthorizationClaimsV2(
        pilot_run_id="pilot-run-20260826-001",
        readiness_attestation_id=readiness.attestation_id,
        exact_four_binding_digest=exact_four.binding_digest,
        controlled_pilot_policy_digest=CONTROLLED_PILOT_POLICY_DIGEST,
        budget_scope_digest=exact_four.budget_scope_digest,
        execution_limit_set_digest=exact_four.execution_limit_set_digest,
        lease_ttl_seconds=exact_four.lease_ttl_seconds,
        human_approval_event_id="human-approval-event-001",
        human_approval_event_digest=_digest("human-approval-event"),
        issued_at="2026-08-26T00:01:00+00:00",
        expires_at="2026-08-26T00:20:00+00:00",
    )
    execution = ControlledExecutionClaimsV2(
        pilot_run_id=trader.pilot_run_id,
        readiness_attestation_id=readiness.attestation_id,
        trader_authorization_id=trader.authorization_id,
        exact_four_binding_digest=exact_four.binding_digest,
        controlled_pilot_policy_digest=CONTROLLED_PILOT_POLICY_DIGEST,
        budget_scope_digest=exact_four.budget_scope_digest,
        execution_limit_set_digest=exact_four.execution_limit_set_digest,
        lease_ttl_seconds=exact_four.lease_ttl_seconds,
        idempotency_key="pilot-run-20260826-001:exact-four:generation-1",
    )
    return readiness, trader, execution


def _validator() -> Draft202012Validator:
    schema = load_exact_four_authority_schema()
    assert canonical_authority_digest(schema) == (
        PINNED_EXACT_FOUR_AUTHORITY_SCHEMA_DIGEST
    )
    schema_raw = (
        repo_root()
        / "specs"
        / "ready"
        / "exact_four_authority_protocol.schema.json"
    ).read_bytes()
    assert "sha256:" + hashlib.sha256(schema_raw).hexdigest() == (
        PINNED_EXACT_FOUR_AUTHORITY_SCHEMA_RAW_DIGEST
    )
    return Draft202012Validator(schema, format_checker=FormatChecker())


def test_controlled_pilot_policy_digest_excludes_only_its_digest_field() -> None:
    policy = load_controlled_pilot_policy()
    document = json.loads(
        (
            repo_root() / "specs" / "policy" / "controlled_pilot_policy.json"
        ).read_text(encoding="utf-8")
    )
    declared = document.pop("policy_digest")

    assert declared == CONTROLLED_PILOT_POLICY_DIGEST
    assert policy.policy_digest == canonical_authority_digest(document)
    assert policy.policy_digest == canonical_authority_digest(policy.to_digest_body())


def test_constructed_policy_cannot_reuse_digest_with_larger_limits() -> None:
    policy = load_controlled_pilot_policy()
    with pytest.raises(ControlledPilotPolicyError, match="declared digest"):
        replace(policy, max_parallel_experiments=999)
    with pytest.raises(ControlledPilotPolicyError, match="declared digest"):
        replace(policy, max_input_tokens=999_999_999)


def test_exact_four_is_four_ordered_plans_and_one_aggregate_batch() -> None:
    contract = load_exact_four_execution_binding()
    source = load_exact_four_pilot_ready_binding()

    assert tuple(item.plan_id for item in contract.plan_bindings) == (
        PILOT_EXPERIMENT_PLAN_IDS
    )
    assert tuple(item.ordinal for item in contract.plan_bindings) == (1, 2, 3, 4)
    assert tuple(item.plan_digest for item in contract.plan_bindings) == tuple(
        closure.plan_digest for closure in source.closures
    )
    assert tuple(
        item.dependency_closure_digest for item in contract.plan_bindings
    ) == tuple(closure.closure_digest for closure in source.closures)
    assert tuple(item.profile_digest for item in contract.plan_bindings) == tuple(
        profile.profile_digest for profile in source.profiles
    )
    assert all(item.feature_pins for item in contract.plan_bindings)
    assert contract.artifact_cardinality.to_dict() == {
        "batch_authorizations_exactly": 1,
        "paper_results_exactly": 4,
        "risk_results_exactly": 4,
        "aggregate_selection_results_exactly": 1,
        "knowledge_artifacts_exactly": 1,
    }


def test_exact_four_rejects_reorder_and_non_integer_cardinality() -> None:
    contract = load_exact_four_execution_binding()
    reordered = (
        contract.plan_bindings[1],
        contract.plan_bindings[0],
        *contract.plan_bindings[2:],
    )
    with pytest.raises(ExactFourAuthorityContractError, match="ordered exact four"):
        replace(contract, plan_bindings=reordered)
    with pytest.raises(
        ExactFourAuthorityContractError, match="artifact cardinality"
    ):
        replace(
            contract.artifact_cardinality,
            paper_results_exactly=4.0,  # type: ignore[arg-type]
        )


def test_plan_dates_and_risk_limits_are_exact_canonical_values() -> None:
    plan = load_exact_four_execution_binding().plan_bindings[0]
    with pytest.raises(ExactFourAuthorityContractError, match="ISO date"):
        replace(plan, period_start="2023-1-04")
    with pytest.raises(ExactFourAuthorityContractError, match="max gross"):
        replace(plan, max_gross_weight_ppm=500_001)
    with pytest.raises(ExactFourAuthorityContractError, match="paper run limit"):
        replace(plan, max_paper_runs=2.0)  # type: ignore[arg-type]


def test_ready_snapshot_requires_complete_current_evidence_chain() -> None:
    snapshot = _snapshot()
    assert snapshot.source_generation == snapshot.applied_cursor
    assert snapshot.raw_proof_digest.startswith("sha256:")
    assert snapshot.validation_proof_digest.startswith("sha256:")
    assert snapshot.b0_proof_digest.startswith("sha256:")
    assert snapshot.b4_proof_digest.startswith("sha256:")

    with pytest.raises(ExactFourAuthorityContractError, match="must be current"):
        _snapshot(applied_cursor="cursor-41")
    with pytest.raises(ExactFourAuthorityContractError, match="sha256"):
        _snapshot(raw_proof_digest="UNKNOWN")


def test_ready_attestation_id_is_content_addressed_and_tamper_evident() -> None:
    readiness, _trader, _execution = _claims()
    assert readiness.attestation_id == canonical_authority_digest(
        readiness.to_canonical_dict()
    )

    changed = replace(readiness, expires_at="2026-08-26T00:29:59+00:00")
    assert changed.attestation_id != readiness.attestation_id

    with pytest.raises(ExactFourAuthorityContractError, match="governed"):
        replace(
            readiness,
            snapshot=_snapshot(governed_membership_digest=_digest("alternate")),
        )


def test_trader_and_execution_claims_bind_canonical_limits() -> None:
    _readiness, trader, execution = _claims()
    assert trader.execution_limit_set_digest == execution.execution_limit_set_digest
    assert trader.budget_scope_digest == execution.budget_scope_digest
    assert trader.lease_ttl_seconds == 1800

    with pytest.raises(ExactFourAuthorityContractError, match="limits"):
        replace(trader, execution_limit_set_digest=_digest("higher-limits"))
    with pytest.raises(ExactFourAuthorityContractError, match="limits"):
        replace(trader, lease_ttl_seconds=1801)
    with pytest.raises(ExactFourAuthorityContractError, match="limits"):
        replace(execution, budget_scope_digest=_digest("larger-budget"))


def test_closed_schema_accepts_three_scopes_and_rejects_substitution() -> None:
    readiness, trader, execution = _claims()
    validator = _validator()
    for claims in (readiness, trader, execution):
        validator.validate(claims.to_dict())

    extra = readiness.to_dict()
    extra["go_override"] = True
    with pytest.raises(ValidationError):
        validator.validate(extra)

    wrong_scope = trader.to_dict()
    wrong_scope["authority_scope"] = readiness.authority_scope
    with pytest.raises(ValidationError):
        validator.validate(wrong_scope)

    reordered = readiness.to_dict()
    reordered["exact_four"]["plan_bindings"][0], reordered["exact_four"][
        "plan_bindings"
    ][1] = (
        reordered["exact_four"]["plan_bindings"][1],
        reordered["exact_four"]["plan_bindings"][0],
    )
    with pytest.raises(ValidationError):
        validator.validate(reordered)

    wrong_topology = readiness.to_dict()
    wrong_topology["exact_four"]["artifact_cardinality"][
        "paper_results_exactly"
    ] = 1
    with pytest.raises(ValidationError):
        validator.validate(wrong_topology)


def test_pending_capabilities_cannot_be_constructed_or_object_new_bypassed() -> None:
    readiness, trader, execution = _claims()
    assert AUTHORITY_PROTOCOL_STATE == "PENDING_EXTERNAL_AUTHORITIES"

    for capability_type in (
        VerifiedPilotReadinessV2,
        VerifiedExactFourTraderAuthorizationV2,
        AuthorizedExactFourExecutionV2,
    ):
        with pytest.raises(ExactFourAuthorityPending):
            capability_type()

    forged_ready = object.__new__(VerifiedPilotReadinessV2)
    forged_trader = object.__new__(VerifiedExactFourTraderAuthorizationV2)
    forged_execution = object.__new__(AuthorizedExactFourExecutionV2)
    for gate, value in (
        (require_verified_pilot_readiness_v2, readiness),
        (require_verified_pilot_readiness_v2, forged_ready),
        (require_verified_trader_authorization_v2, trader),
        (require_verified_trader_authorization_v2, forged_trader),
        (require_authorized_exact_four_execution_v2, execution),
        (require_authorized_exact_four_execution_v2, forged_execution),
    ):
        with pytest.raises(ExactFourAuthorityPending):
            gate(value)
