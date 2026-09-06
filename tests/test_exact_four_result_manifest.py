"""Adversarial invariants for the PENDING exact-four v2 result evidence."""

from __future__ import annotations

import hashlib
import inspect
import json
from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

import execution.exact_four_claims as claims_module
import execution.exact_four_results as results_module
from execution.exact_four_authority_contract import (
    ControlledExecutionClaimsV2,
    ExactFourAuthorityContractError,
    PilotReadinessAttestationClaimsV2,
    ReadySnapshotLineage,
    TraderAuthorizationClaimsV2,
    build_controlled_execution_claims_v2,
    build_trader_authorization_claims_v2,
    canonical_authority_digest,
    load_exact_four_execution_binding,
)
from execution.exact_four_results import (
    RESULT_AUTHORITY_STATE,
    AggregateSelectionEvidenceV2,
    ExactFourPilotResultManifestV2,
    KnowledgeArtifactEvidenceV2,
    PINNED_EXACT_FOUR_RESULT_SCHEMA_DIGEST,
    PINNED_EXACT_FOUR_RESULT_SCHEMA_RAW_DIGEST,
    PaperResultEvidenceV2,
    RiskResultEvidenceV2,
    build_exact_four_pilot_result_manifest_v2,
    exact_four_result_schema_path,
    load_exact_four_result_schema,
    parse_and_validate_exact_four_pilot_result_manifest_v2,
    validate_current_exact_four_pilot_result_manifest_v2,
    validate_exact_four_pilot_result_manifest_v2,
)


def _digest(label: str) -> str:
    return canonical_authority_digest({"test": label})


def _snapshot() -> ReadySnapshotLineage:
    exact_four = load_exact_four_execution_binding()
    return ReadySnapshotLineage(
        snapshot_id=_digest("snapshot"),
        ready_manifest_digest=_digest("ready-manifest"),
        immutable_snapshot_digest=_digest("immutable-snapshot"),
        governed_membership_digest=(
            exact_four.required_dataset_membership_digest
        ),
        universe_rule_digest=exact_four.universe_rule_digest,
        resolved_universe_digest=_digest("resolved-universe"),
        coverage_policy_version=exact_four.coverage_policy_version,
        coverage_policy_digest=exact_four.coverage_policy_digest,
        coverage_status="COMPLETE",
        coverage_proof_digest=_digest("coverage"),
        raw_status="PRESENT",
        raw_proof_digest=_digest("raw"),
        trusted_receipt_status="COMPLETE",
        receipt_proof_digest=_digest("receipt"),
        validation_status="PASS",
        validation_proof_digest=_digest("validation"),
        natural_key_status="PASS",
        natural_key_proof_digest=_digest("natural-key"),
        b0_status="PASS",
        b0_proof_digest=_digest("b0"),
        b4_status="PASS",
        b4_proof_digest=_digest("b4"),
        pit_contract_set_digest=_digest("pit"),
        projection_status="FRESH",
        projection_refresh_success=True,
        projection_is_current=True,
        projection_generation="projection-generation-7",
        source_generation=7,
        applied_sync_generation=7,
        source_cursor=123,
        export_cursor=123,
        applied_cursor=123,
        feature_generation=_digest("feature-generation"),
        catalog_generation=_digest("catalog-generation"),
    )


def _authority_chain() -> tuple[
    PilotReadinessAttestationClaimsV2,
    TraderAuthorizationClaimsV2,
    ControlledExecutionClaimsV2,
]:
    now = datetime.now(timezone.utc)
    exact_four = load_exact_four_execution_binding()
    readiness = PilotReadinessAttestationClaimsV2(
        pilot_run_id="pilot-run-result-manifest-001",
        environment="staging",
        ready_authority_instance_id="ready-authority/staging/v1",
        ready_authority_resource_digest=_digest("ready-resource"),
        snapshot=_snapshot(),
        exact_four=exact_four,
        issued_at=(now - timedelta(minutes=5)).isoformat(),
        expires_at=(now + timedelta(minutes=25)).isoformat(),
    )
    trader = build_trader_authorization_claims_v2(
        readiness,
        human_approval_event_id="human-approval-result-manifest-001",
        human_approval_event_digest=_digest("human-approval"),
        issued_at=(now - timedelta(minutes=4)).isoformat(),
        expires_at=(now + timedelta(minutes=20)).isoformat(),
    )
    execution = build_controlled_execution_claims_v2(
        readiness,
        trader,
        issued_at=(now - timedelta(minutes=3)).isoformat(),
        expires_at=(now + timedelta(minutes=10)).isoformat(),
    )
    return readiness, trader, execution


def _evidence() -> tuple[
    tuple[PaperResultEvidenceV2, ...],
    tuple[RiskResultEvidenceV2, ...],
    AggregateSelectionEvidenceV2,
    KnowledgeArtifactEvidenceV2,
]:
    exact_four = load_exact_four_execution_binding()
    papers = tuple(
        PaperResultEvidenceV2(
            ordinal=plan.ordinal,
            plan_id=plan.plan_id,
            plan_binding_digest=plan.binding_digest,
            paper_result_id=_digest(f"paper-result-{plan.ordinal}"),
            paper_artifact_digest=_digest(f"paper-artifact-{plan.ordinal}"),
        )
        for plan in exact_four.plan_bindings
    )
    risks = tuple(
        RiskResultEvidenceV2(
            ordinal=paper.ordinal,
            plan_id=paper.plan_id,
            plan_binding_digest=paper.plan_binding_digest,
            paper_result_id=paper.paper_result_id,
            paper_evidence_id=paper.evidence_id,
            risk_result_id=_digest(f"risk-result-{paper.ordinal}"),
            risk_artifact_digest=_digest(f"risk-artifact-{paper.ordinal}"),
        )
        for paper in papers
    )
    pair_set_digest = canonical_authority_digest(
        [
            {
                "ordinal": paper.ordinal,
                "plan_id": paper.plan_id,
                "plan_binding_digest": paper.plan_binding_digest,
                "paper_evidence_id": paper.evidence_id,
                "paper_result_id": paper.paper_result_id,
                "risk_evidence_id": risk.evidence_id,
                "risk_result_id": risk.risk_result_id,
            }
            for paper, risk in zip(papers, risks, strict=True)
        ]
    )
    selection = AggregateSelectionEvidenceV2(
        paper_evidence_ids=tuple(item.evidence_id for item in papers),
        risk_evidence_ids=tuple(item.evidence_id for item in risks),
        input_pair_set_digest=pair_set_digest,
        selected_plan_ids=(papers[0].plan_id, papers[2].plan_id),
        selection_result_id=_digest("selection-result"),
        selection_artifact_digest=_digest("selection-artifact"),
    )
    knowledge = KnowledgeArtifactEvidenceV2(
        selection_evidence_id=selection.evidence_id,
        selection_result_id=selection.selection_result_id,
        knowledge_artifact_id=_digest("knowledge-id"),
        knowledge_artifact_digest=_digest("knowledge-artifact"),
    )
    return papers, risks, selection, knowledge


def _manifest() -> tuple[
    PilotReadinessAttestationClaimsV2,
    TraderAuthorizationClaimsV2,
    ControlledExecutionClaimsV2,
    ExactFourPilotResultManifestV2,
]:
    readiness, trader, execution = _authority_chain()
    papers, risks, selection, knowledge = _evidence()
    manifest = build_exact_four_pilot_result_manifest_v2(
        readiness,
        trader,
        execution,
        paper_results=papers,
        risk_results=risks,
        aggregate_selection=selection,
        knowledge_artifact=knowledge,
    )
    return readiness, trader, execution, manifest


def test_result_manifest_rejects_omitted_or_mutated_identity() -> None:
    _readiness, _trader, execution, manifest = _manifest()
    document = manifest.to_dict()
    assert document["identity"] == "controlled_pilot_v1"
    omitted = dict(document)
    omitted.pop("identity")
    with pytest.raises(ExactFourAuthorityContractError):
        parse_and_validate_exact_four_pilot_result_manifest_v2(
            json.dumps(omitted).encode("utf-8"),
            readiness=_readiness,
            trader=_trader,
            execution=execution,
        )
    mutated = dict(document)
    mutated["identity"] = "draft_factor_cohort_v1"
    with pytest.raises(ExactFourAuthorityContractError):
        parse_and_validate_exact_four_pilot_result_manifest_v2(
            json.dumps(mutated).encode("utf-8"),
            readiness=_readiness,
            trader=_trader,
            execution=execution,
        )


def test_result_manifest_binds_exact_four_authority_and_artifact_chain() -> None:
    readiness, trader, execution, manifest = _manifest()

    assert RESULT_AUTHORITY_STATE == "PENDING_RESULT_WRITER_AND_VERIFIER"
    assert tuple(item.ordinal for item in manifest.paper_results) == (1, 2, 3, 4)
    assert tuple(item.ordinal for item in manifest.risk_results) == (1, 2, 3, 4)
    assert manifest.pilot_run_id == readiness.pilot_run_id
    assert manifest.trader_authorization_id == trader.authorization_id
    assert manifest.execution_request_id == execution.request_id
    assert manifest.lease_id == execution.lease_id
    assert manifest.idempotency_key == execution.idempotency_key
    assert manifest.execution_issued_at == execution.issued_at
    assert manifest.execution_expires_at == execution.expires_at
    assert datetime.fromisoformat(execution.issued_at) <= datetime.fromisoformat(
        manifest.completed_at
    ) <= datetime.fromisoformat(execution.expires_at)
    assert validate_exact_four_pilot_result_manifest_v2(
        manifest,
        readiness=readiness,
        trader=trader,
        execution=execution,
    ) == manifest.manifest_id


def test_historical_result_audit_survives_parent_expiry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    readiness, trader, execution, manifest = _manifest()
    monkeypatch.setattr(
        results_module,
        "_trusted_utc_now",
        lambda: datetime(2099, 1, 1, tzinfo=timezone.utc),
    )

    assert validate_exact_four_pilot_result_manifest_v2(
        manifest,
        readiness=readiness,
        trader=trader,
        execution=execution,
    ) == manifest.manifest_id
    parsed = parse_and_validate_exact_four_pilot_result_manifest_v2(
        json.dumps(manifest.to_dict(), separators=(",", ":")),
        readiness=readiness,
        trader=trader,
        execution=execution,
    )
    assert parsed == manifest
    with pytest.raises(ExactFourAuthorityContractError, match="expired"):
        validate_current_exact_four_pilot_result_manifest_v2(
            manifest,
            readiness=readiness,
            trader=trader,
            execution=execution,
        )


def test_historical_validators_reject_future_ready_trader_execution_chain(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    trusted_present = datetime.now(timezone.utc)
    future_clock = trusted_present + timedelta(hours=1)
    exact_four = load_exact_four_execution_binding()
    readiness = PilotReadinessAttestationClaimsV2(
        pilot_run_id="pilot-run-future-result-manifest-001",
        environment="staging",
        ready_authority_instance_id="ready-authority/staging/v1",
        ready_authority_resource_digest=_digest("ready-resource-future"),
        snapshot=_snapshot(),
        exact_four=exact_four,
        issued_at=(future_clock - timedelta(minutes=5)).isoformat(),
        expires_at=(future_clock + timedelta(minutes=25)).isoformat(),
    )
    monkeypatch.setattr(claims_module, "_trusted_utc_now", lambda: future_clock)
    trader = build_trader_authorization_claims_v2(
        readiness,
        human_approval_event_id="human-approval-future-result-manifest-001",
        human_approval_event_digest=_digest("human-approval-future"),
        issued_at=(future_clock - timedelta(minutes=4)).isoformat(),
        expires_at=(future_clock + timedelta(minutes=20)).isoformat(),
    )
    execution = build_controlled_execution_claims_v2(
        readiness,
        trader,
        issued_at=(future_clock - timedelta(minutes=3)).isoformat(),
        expires_at=(future_clock + timedelta(minutes=10)).isoformat(),
    )
    monkeypatch.setattr(results_module, "_trusted_utc_now", lambda: future_clock)
    papers, risks, selection, knowledge = _evidence()
    manifest = build_exact_four_pilot_result_manifest_v2(
        readiness,
        trader,
        execution,
        paper_results=papers,
        risk_results=risks,
        aggregate_selection=selection,
        knowledge_artifact=knowledge,
    )

    monkeypatch.setattr(results_module, "_trusted_utc_now", lambda: trusted_present)
    with pytest.raises(ExactFourAuthorityContractError, match="future"):
        validate_exact_four_pilot_result_manifest_v2(
            manifest,
            readiness=readiness,
            trader=trader,
            execution=execution,
        )
    with pytest.raises(ExactFourAuthorityContractError, match="future"):
        parse_and_validate_exact_four_pilot_result_manifest_v2(
            json.dumps(manifest.to_dict(), separators=(",", ":")),
            readiness=readiness,
            trader=trader,
            execution=execution,
        )


def test_historical_validators_have_no_future_completion_grace(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    readiness, trader, execution, manifest = _manifest()
    completion = datetime.fromisoformat(manifest.completed_at)
    monkeypatch.setattr(
        results_module,
        "_trusted_utc_now",
        lambda: completion - timedelta(microseconds=1),
    )

    with pytest.raises(ExactFourAuthorityContractError, match="future"):
        validate_exact_four_pilot_result_manifest_v2(
            manifest,
            readiness=readiness,
            trader=trader,
            execution=execution,
        )
    with pytest.raises(ExactFourAuthorityContractError, match="future"):
        parse_and_validate_exact_four_pilot_result_manifest_v2(
            json.dumps(manifest.to_dict(), separators=(",", ":")),
            readiness=readiness,
            trader=trader,
            execution=execution,
        )


def test_result_completion_is_writer_clock_derived_and_inside_execution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    readiness, trader, execution, manifest = _manifest()
    before = (
        datetime.fromisoformat(execution.issued_at) - timedelta(microseconds=1)
    ).isoformat()
    after = (
        datetime.fromisoformat(execution.expires_at) + timedelta(microseconds=1)
    ).isoformat()

    for completed_at in (before, execution.expires_at, after):
        with pytest.raises(ExactFourAuthorityContractError, match="execution window"):
            replace(manifest, completed_at=completed_at)
    with pytest.raises(ExactFourAuthorityContractError, match="canonical UTC"):
        replace(manifest, completed_at=manifest.completed_at.replace("+00:00", "Z"))

    fixed = datetime.now(timezone.utc)
    monkeypatch.setattr(results_module, "_trusted_utc_now", lambda: fixed)
    papers, risks, selection, knowledge = _evidence()
    rebuilt = build_exact_four_pilot_result_manifest_v2(
        readiness,
        trader,
        execution,
        paper_results=papers,
        risk_results=risks,
        aggregate_selection=selection,
        knowledge_artifact=knowledge,
    )
    assert rebuilt.completed_at == fixed.isoformat()
    assert "completed_at" not in inspect.signature(
        build_exact_four_pilot_result_manifest_v2
    ).parameters


def test_result_schema_is_pinned_and_untrusted_round_trip_is_parent_bound() -> None:
    readiness, trader, execution, manifest = _manifest()
    schema = load_exact_four_result_schema()
    raw = exact_four_result_schema_path().read_bytes()
    assert schema["title"] == "Exact-four controlled-pilot v2 result manifest"
    assert canonical_authority_digest(schema) == (
        PINNED_EXACT_FOUR_RESULT_SCHEMA_DIGEST
    )
    assert "sha256:" + hashlib.sha256(raw).hexdigest() == (
        PINNED_EXACT_FOUR_RESULT_SCHEMA_RAW_DIGEST
    )

    parsed = parse_and_validate_exact_four_pilot_result_manifest_v2(
        json.dumps(manifest.to_dict(), separators=(",", ":")),
        readiness=readiness,
        trader=trader,
        execution=execution,
    )
    assert parsed == manifest


def test_result_manifest_rejects_missing_duplicate_and_reordered_results() -> None:
    _readiness, _trader, _execution, manifest = _manifest()
    with pytest.raises(ExactFourAuthorityContractError, match="exactly four"):
        replace(manifest, paper_results=manifest.paper_results[:3])
    with pytest.raises(ExactFourAuthorityContractError, match="canonical ordered"):
        replace(
            manifest,
            paper_results=(
                manifest.paper_results[1],
                manifest.paper_results[0],
                *manifest.paper_results[2:],
            ),
        )
    with pytest.raises(ExactFourAuthorityContractError):
        replace(
            manifest,
            risk_results=(
                manifest.risk_results[0],
                manifest.risk_results[0],
                *manifest.risk_results[2:],
            ),
        )


def test_result_manifest_rejects_cross_plan_risk_and_aggregate_omission() -> None:
    readiness, trader, execution, manifest = _manifest()
    cross_plan = replace(
        manifest.risk_results[0],
        plan_id=manifest.paper_results[1].plan_id,
        plan_binding_digest=manifest.paper_results[1].plan_binding_digest,
    )
    with pytest.raises(ExactFourAuthorityContractError, match="corresponding Paper"):
        replace(
            manifest,
            risk_results=(cross_plan, *manifest.risk_results[1:]),
        )

    omitted = manifest.to_dict()
    omitted.pop("aggregate_selection")
    with pytest.raises(ExactFourAuthorityContractError, match="schema violation"):
        parse_and_validate_exact_four_pilot_result_manifest_v2(
            json.dumps(omitted, separators=(",", ":")),
            readiness=readiness,
            trader=trader,
            execution=execution,
        )


def test_nested_mutation_changes_content_id_and_is_semantically_rejected() -> None:
    readiness, trader, execution, manifest = _manifest()
    manifest_id = manifest.manifest_id
    object.__setattr__(
        manifest.paper_results[0],
        "plan_id",
        manifest.paper_results[1].plan_id,
    )
    assert manifest.manifest_id != manifest_id
    with pytest.raises(ExactFourAuthorityContractError, match="canonical ordered"):
        validate_exact_four_pilot_result_manifest_v2(
            manifest,
            readiness=readiness,
            trader=trader,
            execution=execution,
        )


def test_result_manifest_rejects_split_brain_authority_parent() -> None:
    readiness, trader, execution, manifest = _manifest()
    other_ready = replace(readiness, pilot_run_id="pilot-run-other-parent")
    with pytest.raises(ExactFourAuthorityContractError):
        validate_exact_four_pilot_result_manifest_v2(
            manifest,
            readiness=other_ready,
            trader=trader,
            execution=execution,
        )
