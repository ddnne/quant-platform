"""Immutable exact-four v2 Paper -> Risk -> Selection -> Knowledge evidence.

The values in this module are content-addressed evidence DTOs only.  They do
not persist artifacts, verify external signatures, consume an execution lease,
or mint any positive capability.  Those writer and authority paths remain
explicitly PENDING.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timezone
from typing import Any

from execution.exact_four_binding import load_exact_four_execution_binding
from execution.exact_four_claims import (
    ControlledExecutionClaimsV2,
    PilotReadinessAttestationClaimsV2,
    TraderAuthorizationClaimsV2,
    _validate_claim_chain_structural,
    _validate_current_claim_chain_at,
)
from execution.exact_four_codec import (
    PILOT_EXECUTION_MODE,
    ExactFourAuthorityContractError,
    _parsed_timestamp,
    _require_digest,
    _require_exact_json,
    _require_text,
    _strict_json_loads,
    _trusted_utc_now,
    canonical_authority_digest,
)
from execution.exact_four_protocol import (
    PINNED_EXACT_FOUR_RESULT_SCHEMA_DIGEST,
    PINNED_EXACT_FOUR_RESULT_SCHEMA_RAW_DIGEST,
    exact_four_result_schema_path,
    load_exact_four_result_schema,
)


EXACT_FOUR_RESULT_MANIFEST_FORMAT = "exact-four-pilot-result-manifest/v2"
PAPER_RESULT_EVIDENCE_FORMAT = "paper-result-evidence/v2"
RISK_RESULT_EVIDENCE_FORMAT = "risk-result-evidence/v2"
AGGREGATE_SELECTION_EVIDENCE_FORMAT = "aggregate-selection-evidence/v2"
KNOWLEDGE_ARTIFACT_EVIDENCE_FORMAT = "knowledge-artifact-evidence/v2"
RESULT_AUTHORITY_STATE = "PENDING_RESULT_WRITER_AND_VERIFIER"

def _require_ordinal(value: Any, label: str) -> int:
    if type(value) is not int or not 1 <= value <= 4:
        raise ExactFourAuthorityContractError(
            f"{label} must be an exact integer from one through four"
        )
    return value


@dataclass(frozen=True, slots=True)
class PaperResultEvidenceV2:
    ordinal: int
    plan_id: str
    plan_binding_digest: str
    paper_result_id: str
    paper_artifact_digest: str
    format: str = PAPER_RESULT_EVIDENCE_FORMAT

    def __post_init__(self) -> None:
        _require_ordinal(self.ordinal, "Paper ordinal")
        _require_text(self.plan_id, "Paper plan_id")
        for name in (
            "plan_binding_digest",
            "paper_result_id",
            "paper_artifact_digest",
        ):
            _require_digest(getattr(self, name), f"Paper {name}")
        if type(self.format) is not str or self.format != PAPER_RESULT_EVIDENCE_FORMAT:
            raise ExactFourAuthorityContractError(
                "Paper result evidence format is not canonical"
            )

    def to_canonical_dict(self) -> dict[str, Any]:
        return {
            "format": self.format,
            "ordinal": self.ordinal,
            "plan_id": self.plan_id,
            "plan_binding_digest": self.plan_binding_digest,
            "paper_result_id": self.paper_result_id,
            "paper_artifact_digest": self.paper_artifact_digest,
        }

    @property
    def evidence_id(self) -> str:
        return canonical_authority_digest(self.to_canonical_dict())

    def to_dict(self) -> dict[str, Any]:
        return {**self.to_canonical_dict(), "evidence_id": self.evidence_id}


@dataclass(frozen=True, slots=True)
class RiskResultEvidenceV2:
    ordinal: int
    plan_id: str
    plan_binding_digest: str
    paper_result_id: str
    paper_evidence_id: str
    risk_result_id: str
    risk_artifact_digest: str
    format: str = RISK_RESULT_EVIDENCE_FORMAT

    def __post_init__(self) -> None:
        _require_ordinal(self.ordinal, "Risk ordinal")
        _require_text(self.plan_id, "Risk plan_id")
        for name in (
            "plan_binding_digest",
            "paper_result_id",
            "paper_evidence_id",
            "risk_result_id",
            "risk_artifact_digest",
        ):
            _require_digest(getattr(self, name), f"Risk {name}")
        if type(self.format) is not str or self.format != RISK_RESULT_EVIDENCE_FORMAT:
            raise ExactFourAuthorityContractError(
                "Risk result evidence format is not canonical"
            )

    def to_canonical_dict(self) -> dict[str, Any]:
        return {
            "format": self.format,
            "ordinal": self.ordinal,
            "plan_id": self.plan_id,
            "plan_binding_digest": self.plan_binding_digest,
            "paper_result_id": self.paper_result_id,
            "paper_evidence_id": self.paper_evidence_id,
            "risk_result_id": self.risk_result_id,
            "risk_artifact_digest": self.risk_artifact_digest,
        }

    @property
    def evidence_id(self) -> str:
        return canonical_authority_digest(self.to_canonical_dict())

    def to_dict(self) -> dict[str, Any]:
        return {**self.to_canonical_dict(), "evidence_id": self.evidence_id}


@dataclass(frozen=True, slots=True)
class AggregateSelectionEvidenceV2:
    paper_evidence_ids: tuple[str, ...]
    risk_evidence_ids: tuple[str, ...]
    input_pair_set_digest: str
    selected_plan_ids: tuple[str, ...]
    selection_result_id: str
    selection_artifact_digest: str
    format: str = AGGREGATE_SELECTION_EVIDENCE_FORMAT

    def __post_init__(self) -> None:
        papers = tuple(self.paper_evidence_ids)
        risks = tuple(self.risk_evidence_ids)
        selected = tuple(self.selected_plan_ids)
        if (
            len(papers) != 4
            or len(set(papers)) != 4
            or len(risks) != 4
            or len(set(risks)) != 4
        ):
            raise ExactFourAuthorityContractError(
                "aggregate Selection must bind four unique Paper/Risk pairs"
            )
        for value in (*papers, *risks):
            _require_digest(value, "aggregate Selection evidence id")
        if len(selected) > 4 or len(set(selected)) != len(selected):
            raise ExactFourAuthorityContractError(
                "aggregate Selection selected plans must be unique and bounded"
            )
        for plan_id in selected:
            _require_text(plan_id, "aggregate Selection selected plan_id")
        for name in (
            "input_pair_set_digest",
            "selection_result_id",
            "selection_artifact_digest",
        ):
            _require_digest(getattr(self, name), f"aggregate Selection {name}")
        if (
            type(self.format) is not str
            or self.format != AGGREGATE_SELECTION_EVIDENCE_FORMAT
        ):
            raise ExactFourAuthorityContractError(
                "aggregate Selection evidence format is not canonical"
            )
        object.__setattr__(self, "paper_evidence_ids", papers)
        object.__setattr__(self, "risk_evidence_ids", risks)
        object.__setattr__(self, "selected_plan_ids", selected)

    def to_canonical_dict(self) -> dict[str, Any]:
        return {
            "format": self.format,
            "paper_evidence_ids": list(self.paper_evidence_ids),
            "risk_evidence_ids": list(self.risk_evidence_ids),
            "input_pair_set_digest": self.input_pair_set_digest,
            "selected_plan_ids": list(self.selected_plan_ids),
            "selection_result_id": self.selection_result_id,
            "selection_artifact_digest": self.selection_artifact_digest,
        }

    @property
    def evidence_id(self) -> str:
        return canonical_authority_digest(self.to_canonical_dict())

    def to_dict(self) -> dict[str, Any]:
        return {**self.to_canonical_dict(), "evidence_id": self.evidence_id}


@dataclass(frozen=True, slots=True)
class KnowledgeArtifactEvidenceV2:
    selection_evidence_id: str
    selection_result_id: str
    knowledge_artifact_id: str
    knowledge_artifact_digest: str
    format: str = KNOWLEDGE_ARTIFACT_EVIDENCE_FORMAT

    def __post_init__(self) -> None:
        for name in (
            "selection_evidence_id",
            "selection_result_id",
            "knowledge_artifact_id",
            "knowledge_artifact_digest",
        ):
            _require_digest(getattr(self, name), f"Knowledge {name}")
        if (
            type(self.format) is not str
            or self.format != KNOWLEDGE_ARTIFACT_EVIDENCE_FORMAT
        ):
            raise ExactFourAuthorityContractError(
                "Knowledge artifact evidence format is not canonical"
            )

    def to_canonical_dict(self) -> dict[str, Any]:
        return {
            "format": self.format,
            "selection_evidence_id": self.selection_evidence_id,
            "selection_result_id": self.selection_result_id,
            "knowledge_artifact_id": self.knowledge_artifact_id,
            "knowledge_artifact_digest": self.knowledge_artifact_digest,
        }

    @property
    def evidence_id(self) -> str:
        return canonical_authority_digest(self.to_canonical_dict())

    def to_dict(self) -> dict[str, Any]:
        return {**self.to_canonical_dict(), "evidence_id": self.evidence_id}


def _pair_set_digest(
    papers: tuple[PaperResultEvidenceV2, ...],
    risks: tuple[RiskResultEvidenceV2, ...],
) -> str:
    return canonical_authority_digest(
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


@dataclass(frozen=True, slots=True)
class ExactFourPilotResultManifestV2:
    """One immutable generation-one result batch; never a positive capability."""

    pilot_run_id: str
    readiness_attestation_id: str
    trader_authorization_id: str
    execution_request_id: str
    lease_id: str
    idempotency_key: str
    exact_four_binding_digest: str
    controlled_pilot_policy_digest: str
    budget_scope_digest: str
    plan_set_digest: str
    dependency_closure_set_digest: str
    profile_set_digest: str
    required_dataset_membership_digest: str
    snapshot_id: str
    ready_manifest_digest: str
    immutable_snapshot_digest: str
    execution_issued_at: str
    execution_expires_at: str
    completed_at: str
    paper_results: tuple[PaperResultEvidenceV2, ...]
    risk_results: tuple[RiskResultEvidenceV2, ...]
    aggregate_selection: AggregateSelectionEvidenceV2
    knowledge_artifact: KnowledgeArtifactEvidenceV2
    format: str = EXACT_FOUR_RESULT_MANIFEST_FORMAT
    execution_mode: str = PILOT_EXECUTION_MODE
    generation: int = 1
    one_shot: bool = True
    automatic_promotion: bool = False
    mass_research_enabled: bool = False
    live_trading_enabled: bool = False

    def __post_init__(self) -> None:
        if (
            type(self.format) is not str
            or self.format != EXACT_FOUR_RESULT_MANIFEST_FORMAT
            or type(self.execution_mode) is not str
            or self.execution_mode != PILOT_EXECUTION_MODE
            or type(self.generation) is not int
            or self.generation != 1
            or type(self.one_shot) is not bool
            or not self.one_shot
        ):
            raise ExactFourAuthorityContractError(
                "result manifest must be the one-shot paper generation-one format"
            )
        if (
            self.automatic_promotion is not False
            or self.mass_research_enabled is not False
            or self.live_trading_enabled is not False
        ):
            raise ExactFourAuthorityContractError(
                "result manifest cannot enable Mass, live, or promotion"
            )
        _require_text(self.pilot_run_id, "result manifest pilot_run_id")
        for name in (
            "readiness_attestation_id",
            "trader_authorization_id",
            "execution_request_id",
            "lease_id",
            "idempotency_key",
            "exact_four_binding_digest",
            "controlled_pilot_policy_digest",
            "budget_scope_digest",
            "plan_set_digest",
            "dependency_closure_set_digest",
            "profile_set_digest",
            "required_dataset_membership_digest",
            "snapshot_id",
            "ready_manifest_digest",
            "immutable_snapshot_digest",
        ):
            _require_digest(getattr(self, name), f"result manifest {name}")
        execution_issued = _parsed_timestamp(
            self.execution_issued_at,
            "result manifest execution_issued_at",
        )
        execution_expires = _parsed_timestamp(
            self.execution_expires_at,
            "result manifest execution_expires_at",
        )
        completed = _parsed_timestamp(
            self.completed_at,
            "result manifest completed_at",
        )
        if (
            completed.utcoffset() != timezone.utc.utcoffset(completed)
            or completed.isoformat() != self.completed_at
        ):
            raise ExactFourAuthorityContractError(
                "result completion must be a canonical UTC timestamp"
            )
        if not execution_issued <= completed < execution_expires:
            raise ExactFourAuthorityContractError(
                "result completion must be inside the controlled execution window"
            )
        papers = tuple(self.paper_results)
        risks = tuple(self.risk_results)
        if (
            len(papers) != 4
            or len(risks) != 4
            or any(type(item) is not PaperResultEvidenceV2 for item in papers)
            or any(type(item) is not RiskResultEvidenceV2 for item in risks)
        ):
            raise ExactFourAuthorityContractError(
                "result manifest requires exactly four Paper and four Risk results"
            )
        canonical = load_exact_four_execution_binding()
        if (
            self.exact_four_binding_digest != canonical.binding_digest
            or self.controlled_pilot_policy_digest != canonical.policy.policy_digest
            or self.budget_scope_digest != canonical.budget_scope_digest
            or self.plan_set_digest != canonical.plan_set_digest
            or self.dependency_closure_set_digest
            != canonical.dependency_closure_set_digest
            or self.profile_set_digest != canonical.profile_set_digest
            or self.required_dataset_membership_digest
            != canonical.required_dataset_membership_digest
        ):
            raise ExactFourAuthorityContractError(
                "result manifest governed exact-four lineage is not canonical"
            )
        for paper, risk, plan in zip(
            papers,
            risks,
            canonical.plan_bindings,
            strict=True,
        ):
            paper.__post_init__()
            risk.__post_init__()
            if (
                paper.ordinal != plan.ordinal
                or paper.plan_id != plan.plan_id
                or paper.plan_binding_digest != plan.binding_digest
            ):
                raise ExactFourAuthorityContractError(
                    "Paper results are not the canonical ordered exact four"
                )
            if (
                risk.ordinal != paper.ordinal
                or risk.plan_id != paper.plan_id
                or risk.plan_binding_digest != paper.plan_binding_digest
                or risk.paper_result_id != paper.paper_result_id
                or risk.paper_evidence_id != paper.evidence_id
            ):
                raise ExactFourAuthorityContractError(
                    "Risk result does not bind its corresponding Paper and plan"
                )
        if len({item.paper_result_id for item in papers}) != 4 or len(
            {item.risk_result_id for item in risks}
        ) != 4:
            raise ExactFourAuthorityContractError(
                "Paper and Risk result identities must be unique"
            )
        if type(self.aggregate_selection) is not AggregateSelectionEvidenceV2:
            raise ExactFourAuthorityContractError(
                "one exact aggregate Selection evidence is required"
            )
        self.aggregate_selection.__post_init__()
        expected_plan_order = tuple(plan.plan_id for plan in canonical.plan_bindings)
        selected = self.aggregate_selection.selected_plan_ids
        if selected != tuple(plan for plan in expected_plan_order if plan in selected):
            raise ExactFourAuthorityContractError(
                "aggregate Selection plan ids must preserve canonical plan order"
            )
        if (
            self.aggregate_selection.paper_evidence_ids
            != tuple(item.evidence_id for item in papers)
            or self.aggregate_selection.risk_evidence_ids
            != tuple(item.evidence_id for item in risks)
            or self.aggregate_selection.input_pair_set_digest
            != _pair_set_digest(papers, risks)
        ):
            raise ExactFourAuthorityContractError(
                "aggregate Selection must bind every Paper/Risk pair"
            )
        if type(self.knowledge_artifact) is not KnowledgeArtifactEvidenceV2:
            raise ExactFourAuthorityContractError(
                "one exact Knowledge artifact evidence is required"
            )
        self.knowledge_artifact.__post_init__()
        if (
            self.knowledge_artifact.selection_evidence_id
            != self.aggregate_selection.evidence_id
            or self.knowledge_artifact.selection_result_id
            != self.aggregate_selection.selection_result_id
        ):
            raise ExactFourAuthorityContractError(
                "Knowledge artifact must bind the aggregate Selection"
            )
        object.__setattr__(self, "paper_results", papers)
        object.__setattr__(self, "risk_results", risks)

    def to_canonical_dict(self) -> dict[str, Any]:
        return {
            "format": self.format,
            "execution_mode": self.execution_mode,
            "pilot_run_id": self.pilot_run_id,
            "readiness_attestation_id": self.readiness_attestation_id,
            "trader_authorization_id": self.trader_authorization_id,
            "execution_request_id": self.execution_request_id,
            "lease_id": self.lease_id,
            "idempotency_key": self.idempotency_key,
            "exact_four_binding_digest": self.exact_four_binding_digest,
            "controlled_pilot_policy_digest": self.controlled_pilot_policy_digest,
            "budget_scope_digest": self.budget_scope_digest,
            "plan_set_digest": self.plan_set_digest,
            "dependency_closure_set_digest": self.dependency_closure_set_digest,
            "profile_set_digest": self.profile_set_digest,
            "required_dataset_membership_digest": (
                self.required_dataset_membership_digest
            ),
            "snapshot_id": self.snapshot_id,
            "ready_manifest_digest": self.ready_manifest_digest,
            "immutable_snapshot_digest": self.immutable_snapshot_digest,
            "execution_issued_at": self.execution_issued_at,
            "execution_expires_at": self.execution_expires_at,
            "completed_at": self.completed_at,
            "paper_results": [item.to_dict() for item in self.paper_results],
            "risk_results": [item.to_dict() for item in self.risk_results],
            "aggregate_selection": self.aggregate_selection.to_dict(),
            "knowledge_artifact": self.knowledge_artifact.to_dict(),
            "generation": self.generation,
            "one_shot": self.one_shot,
            "automatic_promotion": self.automatic_promotion,
            "mass_research_enabled": self.mass_research_enabled,
            "live_trading_enabled": self.live_trading_enabled,
        }

    @property
    def manifest_id(self) -> str:
        return canonical_authority_digest(self.to_canonical_dict())

    def to_dict(self) -> dict[str, Any]:
        return {**self.to_canonical_dict(), "manifest_id": self.manifest_id}


def build_exact_four_pilot_result_manifest_v2(
    readiness: PilotReadinessAttestationClaimsV2,
    trader: TraderAuthorizationClaimsV2,
    execution: ControlledExecutionClaimsV2,
    *,
    paper_results: tuple[PaperResultEvidenceV2, ...],
    risk_results: tuple[RiskResultEvidenceV2, ...],
    aggregate_selection: AggregateSelectionEvidenceV2,
    knowledge_artifact: KnowledgeArtifactEvidenceV2,
) -> ExactFourPilotResultManifestV2:
    """Build evidence from a current actual authority-parent chain."""

    completion_clock = _trusted_utc_now().astimezone(timezone.utc)
    _validate_current_claim_chain_at(
        readiness,
        trader,
        execution,
        now=completion_clock,
    )
    completed_at = completion_clock.isoformat()
    exact_four = readiness.exact_four
    snapshot = readiness.snapshot
    manifest = ExactFourPilotResultManifestV2(
        pilot_run_id=readiness.pilot_run_id,
        readiness_attestation_id=readiness.attestation_id,
        trader_authorization_id=trader.authorization_id,
        execution_request_id=execution.request_id,
        lease_id=execution.lease_id,
        idempotency_key=execution.idempotency_key,
        exact_four_binding_digest=exact_four.binding_digest,
        controlled_pilot_policy_digest=exact_four.policy.policy_digest,
        budget_scope_digest=exact_four.budget_scope_digest,
        plan_set_digest=exact_four.plan_set_digest,
        dependency_closure_set_digest=exact_four.dependency_closure_set_digest,
        profile_set_digest=exact_four.profile_set_digest,
        required_dataset_membership_digest=(
            exact_four.required_dataset_membership_digest
        ),
        snapshot_id=snapshot.snapshot_id,
        ready_manifest_digest=snapshot.ready_manifest_digest,
        immutable_snapshot_digest=snapshot.immutable_snapshot_digest,
        execution_issued_at=execution.issued_at,
        execution_expires_at=execution.expires_at,
        completed_at=completed_at,
        paper_results=paper_results,
        risk_results=risk_results,
        aggregate_selection=aggregate_selection,
        knowledge_artifact=knowledge_artifact,
    )
    validate_exact_four_pilot_result_manifest_v2(
        manifest,
        readiness=readiness,
        trader=trader,
        execution=execution,
    )
    return manifest


def validate_exact_four_pilot_result_manifest_v2(
    manifest: Any,
    *,
    readiness: PilotReadinessAttestationClaimsV2,
    trader: TraderAuthorizationClaimsV2,
    execution: ControlledExecutionClaimsV2,
) -> str:
    """Revalidate historical content against its actual authority parents.

    Expired parent windows remain auditable, but a result cannot become
    historical evidence before its module-trusted completion clock has
    actually occurred.
    """

    if type(manifest) is not ExactFourPilotResultManifestV2:
        raise ExactFourAuthorityContractError(
            "an exact ExactFourPilotResultManifestV2 is required"
        )
    _validate_claim_chain_structural(readiness, trader, execution)
    manifest.__post_init__()
    if _parsed_timestamp(
        manifest.completed_at,
        "result manifest completed_at",
    ) > _trusted_utc_now().astimezone(timezone.utc):
        raise ExactFourAuthorityContractError(
            "result completion cannot be in the future at the trusted UTC clock"
        )
    if (
        manifest.pilot_run_id != readiness.pilot_run_id
        or manifest.readiness_attestation_id != readiness.attestation_id
        or manifest.trader_authorization_id != trader.authorization_id
        or manifest.execution_request_id != execution.request_id
        or manifest.lease_id != execution.lease_id
        or manifest.idempotency_key != execution.idempotency_key
        or manifest.snapshot_id != readiness.snapshot.snapshot_id
        or manifest.ready_manifest_digest
        != readiness.snapshot.ready_manifest_digest
        or manifest.immutable_snapshot_digest
        != readiness.snapshot.immutable_snapshot_digest
        or manifest.execution_issued_at != execution.issued_at
        or manifest.execution_expires_at != execution.expires_at
    ):
        raise ExactFourAuthorityContractError(
            "result manifest does not bind the supplied authority parent chain"
        )
    document = manifest.to_dict()
    _validate_result_schema_document(document)
    if manifest.manifest_id != canonical_authority_digest(
        manifest.to_canonical_dict()
    ):
        raise ExactFourAuthorityContractError(
            "result manifest content id is invalid"
        )
    return manifest.manifest_id


def validate_current_exact_four_pilot_result_manifest_v2(
    manifest: Any,
    *,
    readiness: PilotReadinessAttestationClaimsV2,
    trader: TraderAuthorizationClaimsV2,
    execution: ControlledExecutionClaimsV2,
) -> str:
    """Current writer-side validation; historical audit uses the base validator."""

    current = _trusted_utc_now().astimezone(timezone.utc)
    _validate_current_claim_chain_at(
        readiness,
        trader,
        execution,
        now=current,
    )
    content_id = validate_exact_four_pilot_result_manifest_v2(
        manifest,
        readiness=readiness,
        trader=trader,
        execution=execution,
    )
    return content_id


def _validate_result_schema_document(document: dict[str, Any]) -> None:
    _require_exact_json(document)
    try:
        from jsonschema import Draft202012Validator

        errors = sorted(
            Draft202012Validator(load_exact_four_result_schema()).iter_errors(
                document
            ),
            key=lambda item: tuple(str(part) for part in item.path),
        )
    except ExactFourAuthorityContractError:
        raise
    except Exception as exc:
        raise ExactFourAuthorityContractError(
            "cannot validate exact-four result manifest schema"
        ) from exc
    if errors:
        location = "$" + "".join(
            f"[{part}]" if type(part) is int else f".{part}"
            for part in errors[0].path
        )
        raise ExactFourAuthorityContractError(
            f"exact-four result manifest schema violation at {location}: "
            f"{errors[0].message}"
        )


def _evidence_from_document(
    cls: type[
        PaperResultEvidenceV2
        | RiskResultEvidenceV2
        | AggregateSelectionEvidenceV2
        | KnowledgeArtifactEvidenceV2
    ],
    document: Any,
) -> Any:
    if type(document) is not dict:
        raise ExactFourAuthorityContractError("result evidence must be an object")
    body = dict(document)
    declared = body.pop("evidence_id", None)
    if cls is AggregateSelectionEvidenceV2:
        body["paper_evidence_ids"] = tuple(body.get("paper_evidence_ids", ()))
        body["risk_evidence_ids"] = tuple(body.get("risk_evidence_ids", ()))
        body["selected_plan_ids"] = tuple(body.get("selected_plan_ids", ()))
    evidence = cls(**body)
    if declared != evidence.evidence_id or document != evidence.to_dict():
        raise ExactFourAuthorityContractError(
            "result evidence content id or canonical body is invalid"
        )
    return evidence


def parse_and_validate_exact_four_pilot_result_manifest_v2(
    raw: bytes | str,
    *,
    readiness: PilotReadinessAttestationClaimsV2,
    trader: TraderAuthorizationClaimsV2,
    execution: ControlledExecutionClaimsV2,
) -> ExactFourPilotResultManifestV2:
    """Parse an untrusted result manifest with all actual authority parents."""

    document = _strict_json_loads(raw, label="exact-four result manifest")
    _validate_result_schema_document(document)
    body = dict(document)
    declared_manifest_id = body.pop("manifest_id", None)
    papers_document = body.pop("paper_results", None)
    risks_document = body.pop("risk_results", None)
    selection_document = body.pop("aggregate_selection", None)
    knowledge_document = body.pop("knowledge_artifact", None)
    if type(papers_document) is not list or type(risks_document) is not list:
        raise ExactFourAuthorityContractError(
            "result manifest Paper/Risk evidence must be arrays"
        )
    papers = tuple(
        _evidence_from_document(PaperResultEvidenceV2, item)
        for item in papers_document
    )
    risks = tuple(
        _evidence_from_document(RiskResultEvidenceV2, item)
        for item in risks_document
    )
    selection = _evidence_from_document(
        AggregateSelectionEvidenceV2,
        selection_document,
    )
    knowledge = _evidence_from_document(
        KnowledgeArtifactEvidenceV2,
        knowledge_document,
    )
    manifest = ExactFourPilotResultManifestV2(
        paper_results=papers,
        risk_results=risks,
        aggregate_selection=selection,
        knowledge_artifact=knowledge,
        **body,
    )
    if declared_manifest_id != manifest.manifest_id or document != manifest.to_dict():
        raise ExactFourAuthorityContractError(
            "result manifest content id or canonical body is invalid"
        )
    validate_exact_four_pilot_result_manifest_v2(
        manifest,
        readiness=readiness,
        trader=trader,
        execution=execution,
    )
    return manifest


def result_writer_state() -> str:
    """Expose the fail-closed protocol state without implying a writer exists."""

    return RESULT_AUTHORITY_STATE


__all__ = [
    "AGGREGATE_SELECTION_EVIDENCE_FORMAT",
    "AggregateSelectionEvidenceV2",
    "EXACT_FOUR_RESULT_MANIFEST_FORMAT",
    "ExactFourPilotResultManifestV2",
    "KNOWLEDGE_ARTIFACT_EVIDENCE_FORMAT",
    "KnowledgeArtifactEvidenceV2",
    "PAPER_RESULT_EVIDENCE_FORMAT",
    "PINNED_EXACT_FOUR_RESULT_SCHEMA_DIGEST",
    "PINNED_EXACT_FOUR_RESULT_SCHEMA_RAW_DIGEST",
    "PaperResultEvidenceV2",
    "RESULT_AUTHORITY_STATE",
    "RISK_RESULT_EVIDENCE_FORMAT",
    "RiskResultEvidenceV2",
    "build_exact_four_pilot_result_manifest_v2",
    "exact_four_result_schema_path",
    "load_exact_four_result_schema",
    "parse_and_validate_exact_four_pilot_result_manifest_v2",
    "result_writer_state",
    "validate_current_exact_four_pilot_result_manifest_v2",
    "validate_exact_four_pilot_result_manifest_v2",
]
