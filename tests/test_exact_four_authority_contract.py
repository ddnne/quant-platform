"""Behavioral invariants for the PENDING exact-four v2 authority protocol."""

from __future__ import annotations

import hashlib
import inspect
import json
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, FormatChecker, ValidationError

import execution.exact_four_claims as authority_module
import execution.exact_four_authority_contract as authority_facade
from execution.exact_four_authority_contract import (
    AUTHORITY_PROTOCOL_STATE,
    CONTROLLED_PILOT_POLICY_DIGEST,
    CONTROLLED_PILOT_POLICY_RAW_DIGEST,
    AuthorizedExactFourExecutionV2,
    ControlledExecutionClaimsV2,
    ExactFourExecutionBinding,
    ExactFourAuthorityContractError,
    ExactFourAuthorityPending,
    PINNED_EXACT_FOUR_AUTHORITY_SCHEMA_DIGEST,
    PINNED_EXACT_FOUR_AUTHORITY_SCHEMA_RAW_DIGEST,
    PilotReadinessAttestationClaimsV2,
    PlanExecutionBinding,
    ReadySnapshotLineage,
    TraderAuthorizationClaimsV2,
    VerifiedExactFourTraderAuthorizationV2,
    VerifiedPilotReadinessV2,
    build_controlled_execution_claims_v2,
    build_trader_authorization_claims_v2,
    canonical_authority_digest,
    load_controlled_pilot_policy,
    load_exact_four_authority_schema,
    load_exact_four_execution_binding,
    parse_and_validate_exact_four_authority_document,
    parse_and_validate_controlled_execution_document,
    parse_and_validate_pilot_readiness_document,
    parse_and_validate_trader_authorization_document,
    require_authorized_exact_four_execution_v2,
    require_verified_pilot_readiness_v2,
    require_verified_trader_authorization_v2,
    validate_exact_four_authority_claim_chain_v2,
    validate_exact_four_authority_claims_v2,
)
from qp_paths import repo_root
from research.experiment_plans import PILOT_EXPERIMENT_PLAN_IDS
from research.ready_manifest import load_exact_four_pilot_ready_binding
from selection.controlled_pilot_policy import ControlledPilotPolicyError


def _digest(label: str) -> str:
    return canonical_authority_digest({"test": label})


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat()


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
        "coverage_status": "COMPLETE",
        "coverage_proof_digest": _digest("coverage"),
        "raw_status": "PRESENT",
        "raw_proof_digest": _digest("raw"),
        "trusted_receipt_status": "COMPLETE",
        "receipt_proof_digest": _digest("receipt"),
        "validation_status": "PASS",
        "validation_proof_digest": _digest("validation"),
        "natural_key_status": "PASS",
        "natural_key_proof_digest": _digest("natural-key"),
        "b0_status": "PASS",
        "b0_proof_digest": _digest("b0"),
        "b4_status": "PASS",
        "b4_proof_digest": _digest("b4"),
        "pit_contract_set_digest": _digest("pit-contracts"),
        "projection_status": "FRESH",
        "projection_refresh_success": True,
        "projection_is_current": True,
        "projection_generation": "projection-generation-7",
        "source_generation": 42,
        "applied_sync_generation": 42,
        "source_cursor": 2_891_821,
        "export_cursor": 2_891_821,
        "applied_cursor": 2_891_821,
        "feature_generation": _digest("features"),
        "catalog_generation": _digest("catalog"),
    }
    values.update(overrides)
    return ReadySnapshotLineage(**values)  # type: ignore[arg-type]


def _claims(*, at: datetime | None = None) -> tuple[
    PilotReadinessAttestationClaimsV2,
    TraderAuthorizationClaimsV2,
    ControlledExecutionClaimsV2,
]:
    exact_four = load_exact_four_execution_binding()
    now = at or datetime.now(timezone.utc)
    readiness = PilotReadinessAttestationClaimsV2(
        pilot_run_id="pilot-run-20260826-001",
        environment="staging",
        ready_authority_instance_id="ready-authority/staging/v1",
        ready_authority_resource_digest=_digest("ready-resource"),
        snapshot=_snapshot(),
        exact_four=exact_four,
        issued_at=_iso(now - timedelta(minutes=5)),
        expires_at=_iso(now + timedelta(minutes=25)),
    )
    trader = build_trader_authorization_claims_v2(
        readiness,
        human_approval_event_id="human-approval-event-001",
        human_approval_event_digest=_digest("human-approval-event"),
        issued_at=_iso(now - timedelta(minutes=4)),
        expires_at=_iso(now + timedelta(minutes=20)),
    )
    execution = build_controlled_execution_claims_v2(
        readiness,
        trader,
        issued_at=_iso(now - timedelta(minutes=3)),
        expires_at=_iso(now + timedelta(minutes=10)),
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
    raw = (
        repo_root() / "specs" / "policy" / "controlled_pilot_policy.json"
    ).read_bytes()
    assert "sha256:" + hashlib.sha256(raw).hexdigest() == (
        CONTROLLED_PILOT_POLICY_RAW_DIGEST
    )


def test_compatibility_facade_preserves_public_api_but_not_private_validators() -> None:
    assert ExactFourExecutionBinding.__module__ == "execution.exact_four_binding"
    assert PlanExecutionBinding.__module__ == "execution.exact_four_binding"
    assert PilotReadinessAttestationClaimsV2.__module__ == (
        "execution.exact_four_claims"
    )
    assert VerifiedPilotReadinessV2.__module__ == "execution.exact_four_protocol"
    assert authority_facade.ExactFourPilotResultManifestV2.__module__ == (
        "execution.exact_four_results"
    )
    assert not hasattr(authority_facade, "_validate_claim_chain_structural")
    assert not hasattr(
        authority_facade,
        "_validate_exact_four_authority_document_structural",
    )


@pytest.mark.parametrize(
    ("replacement", "message"),
    [
        (
            '"plans_exactly": 4,\n  "plans_exactly": 4,',
            "duplicate key",
        ),
        ('"max_cost_usd": NaN', "non-finite"),
    ],
)
def test_controlled_pilot_policy_loader_rejects_ambiguous_json(
    tmp_path: Path,
    replacement: str,
    message: str,
) -> None:
    source = (
        repo_root() / "specs" / "policy" / "controlled_pilot_policy.json"
    ).read_text(encoding="utf-8")
    if "plans_exactly" in replacement:
        source = source.replace('"plans_exactly": 4,', replacement, 1)
    else:
        source = source.replace('"max_cost_usd": 20', replacement, 1)
    target = tmp_path / "specs" / "policy" / "controlled_pilot_policy.json"
    target.parent.mkdir(parents=True)
    target.write_text(source, encoding="utf-8")
    with pytest.raises(ControlledPilotPolicyError, match=message):
        load_controlled_pilot_policy(root=tmp_path)


def test_controlled_pilot_policy_loader_rejects_raw_byte_drift(
    tmp_path: Path,
) -> None:
    source = (
        repo_root() / "specs" / "policy" / "controlled_pilot_policy.json"
    ).read_bytes()
    target = tmp_path / "specs" / "policy" / "controlled_pilot_policy.json"
    target.parent.mkdir(parents=True)
    target.write_bytes(source + b"\n")
    with pytest.raises(ControlledPilotPolicyError, match="raw digest"):
        load_controlled_pilot_policy(root=tmp_path)


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
    assert snapshot.source_generation == snapshot.applied_sync_generation
    assert snapshot.source_cursor == snapshot.export_cursor == snapshot.applied_cursor
    assert snapshot.projection_generation != snapshot.source_generation
    assert snapshot.coverage_status == "COMPLETE"
    assert snapshot.trusted_receipt_status == "COMPLETE"
    assert snapshot.natural_key_status == "PASS"
    assert snapshot.projection_status == "FRESH"
    assert snapshot.raw_proof_digest.startswith("sha256:")
    assert snapshot.validation_proof_digest.startswith("sha256:")
    assert snapshot.b0_proof_digest.startswith("sha256:")
    assert snapshot.b4_proof_digest.startswith("sha256:")

    with pytest.raises(ExactFourAuthorityContractError, match="cursor chain"):
        _snapshot(applied_cursor=2_891_820)
    with pytest.raises(ExactFourAuthorityContractError, match="sync generation"):
        _snapshot(applied_sync_generation=41)
    with pytest.raises(ExactFourAuthorityContractError, match="production evidence"):
        _snapshot(coverage_status="PARTIAL")
    with pytest.raises(ExactFourAuthorityContractError, match="refreshed"):
        _snapshot(projection_refresh_success=False)
    for sentinel in ("UNKNOWN", "null", "None", "stale"):
        with pytest.raises(ExactFourAuthorityContractError, match="positive integer"):
            _snapshot(source_cursor=sentinel)
    with pytest.raises(ExactFourAuthorityContractError, match="sha256"):
        _snapshot(raw_proof_digest="UNKNOWN")


def test_ready_attestation_id_is_content_addressed_and_tamper_evident() -> None:
    readiness, _trader, _execution = _claims()
    assert readiness.attestation_id == canonical_authority_digest(
        readiness.to_canonical_dict()
    )

    changed = replace(
        readiness,
        expires_at=_iso(
            datetime.fromisoformat(readiness.expires_at) - timedelta(seconds=1)
        ),
    )
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


def test_claim_lifetimes_are_bounded_by_policy_and_parent_authority() -> None:
    readiness, trader, execution = _claims()
    ready_issued = datetime.fromisoformat(readiness.issued_at)
    ready_expires = datetime.fromisoformat(readiness.expires_at)
    trader_issued = datetime.fromisoformat(trader.issued_at)
    trader_expires = datetime.fromisoformat(trader.expires_at)
    execution_issued = datetime.fromisoformat(execution.issued_at)
    with pytest.raises(ExactFourAuthorityContractError, match="policy TTL"):
        replace(readiness, expires_at=_iso(ready_issued + timedelta(seconds=1801)))
    with pytest.raises(ExactFourAuthorityContractError, match="policy TTL"):
        replace(trader, expires_at=_iso(trader_issued + timedelta(seconds=1801)))
    with pytest.raises(ExactFourAuthorityContractError, match="policy TTL"):
        replace(
            execution,
            expires_at=_iso(execution_issued + timedelta(seconds=1801)),
        )
    with pytest.raises(ExactFourAuthorityContractError, match="READY lifetime"):
        build_trader_authorization_claims_v2(
            readiness,
            human_approval_event_id="human-approval-event-late",
            human_approval_event_digest=_digest("human-approval-event-late"),
            issued_at=_iso(ready_expires - timedelta(minutes=1)),
            expires_at=_iso(ready_expires + timedelta(minutes=1)),
        )
    with pytest.raises(ExactFourAuthorityContractError, match="Trader authorization"):
        build_controlled_execution_claims_v2(
            readiness,
            trader,
            issued_at=_iso(trader_expires - timedelta(minutes=1)),
            expires_at=_iso(trader_expires + timedelta(minutes=1)),
        )


def test_safe_factories_and_chain_validator_bind_actual_claim_objects() -> None:
    readiness, trader, execution = _claims()
    chain_digest = validate_exact_four_authority_claim_chain_v2(
        readiness, trader, execution
    )
    assert chain_digest.startswith("sha256:")
    assert readiness.pilot_run_id == trader.pilot_run_id == execution.pilot_run_id
    assert trader.readiness_attestation_id == readiness.attestation_id
    assert execution.trader_authorization_id == trader.authorization_id
    assert execution.one_shot is True

    same_authority_new_window = build_controlled_execution_claims_v2(
        readiness,
        trader,
        issued_at=_iso(datetime.fromisoformat(execution.issued_at) + timedelta(seconds=1)),
        expires_at=_iso(datetime.fromisoformat(execution.expires_at) + timedelta(seconds=1)),
    )
    assert same_authority_new_window.lease_id == execution.lease_id
    assert same_authority_new_window.idempotency_key == execution.idempotency_key
    assert same_authority_new_window.request_id != execution.request_id

    unrelated_ready = replace(
        readiness,
        pilot_run_id="pilot-run-20260826-unrelated",
    )
    with pytest.raises(ExactFourAuthorityContractError, match="supplied READY"):
        validate_exact_four_authority_claim_chain_v2(
            unrelated_ready, trader, execution
        )
    other_trader = replace(
        trader,
        human_approval_event_id="human-approval-event-002",
        human_approval_event_digest=_digest("human-approval-event-002"),
    )
    with pytest.raises(
        ExactFourAuthorityContractError, match="supplied READY and Trader"
    ):
        validate_exact_four_authority_claim_chain_v2(
            readiness, other_trader, execution
        )


@pytest.mark.parametrize(
    ("claimed_now", "message"),
    [
        (datetime(2000, 1, 1, 12, tzinfo=timezone.utc), "expired"),
        (datetime(2099, 1, 1, 12, tzinfo=timezone.utc), "not yet valid"),
    ],
)
def test_public_chain_uses_module_clock_and_rejects_2000_or_2099_claims(
    monkeypatch: pytest.MonkeyPatch,
    claimed_now: datetime,
    message: str,
) -> None:
    monkeypatch.setattr(authority_module, "_trusted_utc_now", lambda: claimed_now)
    readiness, trader, execution = _claims(at=claimed_now)

    actual_now = datetime.now(timezone.utc)
    monkeypatch.setattr(authority_module, "_trusted_utc_now", lambda: actual_now)
    with pytest.raises(ExactFourAuthorityContractError, match=message):
        validate_exact_four_authority_claim_chain_v2(
            readiness,
            trader,
            execution,
        )
    assert "now" not in inspect.signature(
        validate_exact_four_authority_claim_chain_v2
    ).parameters


def test_public_chain_rejects_near_future_issuance_without_clock_grace(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    actual_now = datetime.now(timezone.utc)
    claimed_now = actual_now + timedelta(minutes=5, seconds=10)
    monkeypatch.setattr(authority_module, "_trusted_utc_now", lambda: claimed_now)
    readiness, trader, execution = _claims(at=claimed_now)

    monkeypatch.setattr(authority_module, "_trusted_utc_now", lambda: actual_now)
    with pytest.raises(ExactFourAuthorityContractError, match="not yet valid"):
        validate_exact_four_authority_claim_chain_v2(
            readiness,
            trader,
            execution,
        )


def test_downstream_parsers_reject_split_brain_parent_claims() -> None:
    readiness, trader, execution = _claims()
    other_ready = replace(readiness, pilot_run_id="pilot-run-split-brain")
    other_trader = build_trader_authorization_claims_v2(
        other_ready,
        human_approval_event_id="human-approval-split-brain",
        human_approval_event_digest=_digest("human-approval-split-brain"),
        issued_at=trader.issued_at,
        expires_at=trader.expires_at,
    )
    trader_raw = json.dumps(trader.to_dict(), separators=(",", ":"))
    execution_raw = json.dumps(execution.to_dict(), separators=(",", ":"))

    with pytest.raises(ExactFourAuthorityContractError, match="supplied READY"):
        parse_and_validate_trader_authorization_document(
            trader_raw,
            readiness=other_ready,
        )
    with pytest.raises(
        ExactFourAuthorityContractError,
        match="supplied READY and Trader",
    ):
        parse_and_validate_controlled_execution_document(
            execution_raw,
            readiness=other_ready,
            trader=other_trader,
        )


def test_serialization_exposes_mutation_and_semantic_revalidation_rejects_it() -> None:
    readiness, trader, execution = _claims()
    trader_id = trader.authorization_id
    object.__setattr__(trader, "automatic_promotion", True)
    assert trader.authorization_id != trader_id
    with pytest.raises(ExactFourAuthorityContractError):
        validate_exact_four_authority_claims_v2(trader, readiness=readiness)

    execution_id = execution.request_id
    object.__setattr__(execution, "generation", 2)
    assert execution.request_id != execution_id
    with pytest.raises(ExactFourAuthorityContractError):
        validate_exact_four_authority_claims_v2(
            execution,
            readiness=readiness,
            trader=trader,
        )

    ready_id = readiness.attestation_id
    object.__setattr__(readiness.exact_four, "mass_research_enabled", True)
    assert readiness.attestation_id != ready_id
    with pytest.raises(ExactFourAuthorityContractError):
        validate_exact_four_authority_claims_v2(readiness)


def test_strict_parser_and_schema_are_lockstep_with_semantic_content_ids() -> None:
    readiness, trader, execution = _claims()
    schema_only = _validator()
    ready_raw = json.dumps(readiness.to_dict(), separators=(",", ":"))
    trader_raw = json.dumps(trader.to_dict(), separators=(",", ":"))
    execution_raw = json.dumps(execution.to_dict(), separators=(",", ":"))
    assert parse_and_validate_pilot_readiness_document(ready_raw) == (
        readiness.to_dict()
    )
    assert parse_and_validate_trader_authorization_document(
        trader_raw,
        readiness=readiness,
    ) == trader.to_dict()
    assert parse_and_validate_controlled_execution_document(
        execution_raw,
        readiness=readiness,
        trader=trader,
    ) == execution.to_dict()
    assert parse_and_validate_exact_four_authority_document(
        execution_raw,
        readiness=readiness,
        trader=trader,
    ) == execution.to_dict()

    with pytest.raises(ExactFourAuthorityContractError, match="READY parent"):
        parse_and_validate_exact_four_authority_document(trader_raw)
    with pytest.raises(ExactFourAuthorityContractError, match="READY and Trader"):
        parse_and_validate_exact_four_authority_document(execution_raw)

    duplicate = json.dumps(readiness.to_dict(), separators=(",", ":")).replace(
        '"format":"pilot-readiness-attestation-claims/v2",',
        '"format":"pilot-readiness-attestation-claims/v2",'
        '"format":"pilot-readiness-attestation-claims/v2",',
        1,
    )
    with pytest.raises(ExactFourAuthorityContractError, match="duplicate JSON key"):
        parse_and_validate_exact_four_authority_document(duplicate)

    nonfinite = json.dumps(execution.to_dict(), separators=(",", ":")).replace(
        '"lease_ttl_seconds":1800', '"lease_ttl_seconds":NaN', 1
    )
    with pytest.raises(ExactFourAuthorityContractError, match="non-finite"):
        parse_and_validate_exact_four_authority_document(nonfinite)

    float_integer = execution.to_dict()
    float_integer["generation"] = 1.0
    schema_only.validate(float_integer)
    with pytest.raises(ExactFourAuthorityContractError, match="exact JSON built-in"):
        parse_and_validate_exact_four_authority_document(
            json.dumps(float_integer, separators=(",", ":")),
            readiness=readiness,
            trader=trader,
        )

    self_reported = execution.to_dict()
    self_reported["request_id"] = _digest("self-reported-request")
    schema_only.validate(self_reported)
    with pytest.raises(ExactFourAuthorityContractError, match="content id"):
        parse_and_validate_exact_four_authority_document(
            json.dumps(self_reported, separators=(",", ":")),
            readiness=readiness,
            trader=trader,
        )


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
