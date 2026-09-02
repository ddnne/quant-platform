"""controlled_pilot_v1 is a required serialized digest-bound discriminant."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from agents.types import AuthorizedPaperExecutionRequest
from execution.exact_four_binding import load_exact_four_execution_binding
from execution.exact_four_claims import ExactFourAuthorityContractError
from execution.paper_service import (
    ControlledPilotExecutionService,
    PaperExecutionRejected,
    PaperExecutionService,
)
from research.artifacts import ExperimentPlan
from research.experiment_plans import (
    CONTROLLED_PILOT_PLAN_IDENTITY,
    load_experiment_plans,
)
from research.factor_cohorts import (
    DEFAULT_FACTOR_COHORT_ID,
    DRAFT_AM_PM_SMILE_COHORT_PURPOSE_ID,
    DRAFT_FACTOR_COHORT_PURPOSE_ID,
    DRAFT_RESEARCH_PURPOSE_IDS,
    DRAFT_VOL_OVERLAY_COHORT_PURPOSE_ID,
)
from research.ready_manifest import (
    ReadyManifest,
    build_ready_manifest,
    load_exact_four_pilot_ready_binding,
)
from research.universe_contract import EXACT_FOUR_UNIVERSE_RULE_DIGEST
from selection.budget_ledger import MassResearchDisabledError
from selection.controlled_pilot_policy import (
    CONTROLLED_PILOT_IDENTITY,
    ControlledPilotPolicyError,
    require_controlled_pilot_identity,
)
from strategies.paper import Lifecycle, PaperRunConfig
from strategies.spec import FeatureRef, ThresholdRule, StrategySpec


_REPO = Path(__file__).resolve().parents[1]
_ACTIVE_SCAN_ROOTS = (
    _REPO / "packages" / "product" / "research",
    _REPO / "packages" / "product" / "agents",
    _REPO / "packages" / "product" / "selection",
    _REPO / "packages" / "research_runtime" / "paper_runtime",
    _REPO / "packages" / "product" / "execution",
)
_LIVE_ORDER_MODULE_STEMS = frozenset(
    {
        "controlled_execution_activation_v2",
        "controlled_execution_budget_v2",
        "controlled_execution_ipc_v2",
        "controlled_execution_quiescence_v2",
        "controlled_execution_runtime_v2",
        "controlled_execution_store_v2",
        "controlled_execution_types_v2",
        "controlled_execution_validation_v2",
        "controlled_execution_writer_v2",
        "controlled_ready_custody_v2",
        "exact_four_trader_v2",
        "secure_authority_files_v2",
        "trader_authority_ipc_v2",
        "trader_webauthn_activation_v2",
        "trader_webauthn_authority_core_v2",
        "trader_webauthn_authority_v2",
        "trader_webauthn_enrollment_ledger_v2",
        "trader_webauthn_enrollment_v2",
        "trader_webauthn_ledger_v2",
        "trader_webauthn_registry_v2",
    }
)
_FORBIDDEN_IMPORTS = (
    "scripts.local_authority_clients",
    "scripts.local_authority_service",
    "scripts.local_authority_files",
    "tests.archive.live_order",
    "execution.trader_webauthn",
    "execution.controlled_execution_quiescence",
    "execution.controlled_ready_custody",
    "execution.controlled_execution_activation",
    "execution.controlled_execution_store",
    "execution.controlled_execution_validation",
    "execution.controlled_execution_runtime",
    "execution.controlled_execution_writer",
    "execution.controlled_execution_ipc",
    "execution.exact_four_trader_v2",
    "execution.secure_authority_files",
    "execution.trader_authority_ipc",
)


def _draft_spec() -> StrategySpec:
    return StrategySpec(
        strategy_id="identity-draft",
        version="strategy-spec/v2",
        rebalance="daily",
        rule=ThresholdRule(
            feature=FeatureRef(id="momentum_n", version="1.0.0", params={"n": 5}),
            threshold=0.0,
        ),
        rationale="identity negative test",
    )


def _pilot_ready_manifest() -> ReadyManifest:
    binding = load_exact_four_pilot_ready_binding()
    digest = "sha256:" + ("ab" * 32)
    return build_ready_manifest(
        snapshot_id=digest,
        publication_scope="PILOT",
        profile_id=binding.profile_id,
        profile_version=binding.profile_version,
        profile_digest=binding.profile_digest,
        plan_ids=binding.plan_ids,
        plan_set_digest=binding.plan_set_digest,
        dependency_closure_digest=binding.closure_set_digest,
        universe_rule_digest=EXACT_FOUR_UNIVERSE_RULE_DIGEST,
        resolved_universe_digest=digest,
        dataset_ids=binding.required_datasets,
        coverage_proof_digest=digest,
        raw_proof_digest=digest,
        receipt_proof_digest=digest,
        validation_proof_digest=digest,
        b0_proof_digest=digest,
        b4_proof_digest=digest,
        source_generation="g1",
        applied_sync_generation="g1",
        export_cursor="g1",
        applied_cursor="g1",
        pit_contract_digests={"pit_api": digest},
    )


def test_active_facade_does_not_reexport_webauthn_trader() -> None:
    import execution.exact_four_authority_contract as facade

    assert not hasattr(facade, "authorize_controlled_exact_four_execution_v2")
    assert not hasattr(
        facade, "PINNED_EXACT_FOUR_TRADER_AUTHORIZATION_SCHEMA_DIGEST"
    )


_FORBIDDEN_LIVE_ORDER_PATHS = (
    "tests/archive",
    "scripts/run_local_authority.py",
    "scripts/bootstrap_local_authorities.py",
    "scripts/execution_authority_entrypoints.py",
    "scripts/trader_webauthn_enrollment.py",
    "scripts/local_authority_service.py",
    "scripts/local_authority_clients.py",
    "scripts/authority_principal_manifest.py",
    "scripts/authority_protocol_runtime.py",
    "specs/authorities/authority-principal-manifest.json",
    "specs/ready/exact_four_trader_authorization_v2.schema.json",
    "docs/operations/local_authority_staged_canary.md",
)


def test_deleted_live_order_modules_are_not_importable() -> None:
    for name in _FORBIDDEN_IMPORTS:
        with pytest.raises(ImportError):
            __import__(name)


def test_live_order_modules_and_clis_are_absent_from_the_working_tree() -> None:
    execution_dir = _REPO / "packages" / "product" / "execution"
    present = sorted(
        path.name
        for path in execution_dir.glob("*.py")
        if path.stem in _LIVE_ORDER_MODULE_STEMS
    )
    present.extend(
        rel for rel in _FORBIDDEN_LIVE_ORDER_PATHS if (_REPO / rel).exists()
    )
    assert present == []


def test_controlled_pilot_identity_is_closed() -> None:
    assert CONTROLLED_PILOT_IDENTITY == "controlled_pilot_v1"
    assert require_controlled_pilot_identity(CONTROLLED_PILOT_IDENTITY) == (
        CONTROLLED_PILOT_IDENTITY
    )
    assert CONTROLLED_PILOT_PLAN_IDENTITY == CONTROLLED_PILOT_IDENTITY
    plans = load_experiment_plans()
    assert {plan.identity for plan in plans} == {CONTROLLED_PILOT_IDENTITY}
    assert load_exact_four_pilot_ready_binding().identity == CONTROLLED_PILOT_IDENTITY
    binding = load_exact_four_execution_binding()
    assert binding.identity == CONTROLLED_PILOT_IDENTITY
    assert binding.to_canonical_dict()["identity"] == CONTROLLED_PILOT_IDENTITY
    assert ControlledPilotExecutionService.identity == CONTROLLED_PILOT_IDENTITY
    ready_binding = load_exact_four_pilot_ready_binding()
    assert ready_binding.to_dict()["identity"] == CONTROLLED_PILOT_IDENTITY


@pytest.mark.parametrize(
    "value",
    (
        DRAFT_FACTOR_COHORT_PURPOSE_ID,
        DRAFT_VOL_OVERLAY_COHORT_PURPOSE_ID,
        DRAFT_AM_PM_SMILE_COHORT_PURPOSE_ID,
        DEFAULT_FACTOR_COHORT_ID,
        "controlled-pilot/exact-four",
        "personal-factor-cohorts/v2",
        "exact_four",
        True,
        "",
    ),
)
def test_draft_and_personal_identities_cannot_be_controlled_pilot(
    value: object,
) -> None:
    with pytest.raises(ControlledPilotPolicyError, match="controlled_pilot_v1"):
        require_controlled_pilot_identity(value)


def test_serialized_plan_rejects_omitted_or_mutated_identity() -> None:
    plan = load_experiment_plans()[0]
    payload = plan.to_dict()
    assert payload["identity"] == CONTROLLED_PILOT_IDENTITY
    omitted = dict(payload)
    omitted.pop("identity")
    with pytest.raises(ValueError, match="identity"):
        ExperimentPlan.from_dict(omitted)
    mutated = dict(payload)
    mutated["identity"] = DRAFT_FACTOR_COHORT_PURPOSE_ID
    with pytest.raises(ValueError, match="identity"):
        ExperimentPlan.from_dict(mutated)


def test_serialized_ready_manifest_binds_identity_into_digest() -> None:
    manifest = _pilot_ready_manifest()
    document = manifest.to_dict()
    assert document["identity"] == CONTROLLED_PILOT_IDENTITY
    digest = document["manifest_digest"]
    omitted = dict(document)
    omitted.pop("identity")
    omitted.pop("manifest_digest")
    with pytest.raises(MassResearchDisabledError):
        ReadyManifest.from_dict(omitted)
    mutated = dict(document)
    mutated["identity"] = DRAFT_VOL_OVERLAY_COHORT_PURPOSE_ID
    mutated.pop("manifest_digest")
    with pytest.raises(MassResearchDisabledError, match="identity"):
        ReadyManifest.from_dict(mutated)
    relabeled = dict(document)
    relabeled["identity"] = CONTROLLED_PILOT_IDENTITY
    relabeled["manifest_digest"] = digest
    assert ReadyManifest.from_dict(relabeled).manifest_digest == digest
    tampered = dict(document)
    tampered["identity"] = CONTROLLED_PILOT_IDENTITY
    tampered["manifest_digest"] = "sha256:" + ("00" * 32)
    with pytest.raises(MassResearchDisabledError, match="manifest_digest"):
        ReadyManifest.from_dict(tampered)


def test_serialized_execution_binding_rejects_omitted_or_mutated_identity() -> None:
    document = load_exact_four_execution_binding().to_dict()
    from execution.exact_four_authority_contract import (
        parse_and_validate_exact_four_authority_document,
    )

    omitted = dict(document)
    omitted.pop("identity")
    with pytest.raises(ExactFourAuthorityContractError):
        parse_and_validate_exact_four_authority_document(
            __import__("json").dumps(omitted).encode("utf-8")
        )
    mutated = dict(document)
    mutated["identity"] = DRAFT_AM_PM_SMILE_COHORT_PURPOSE_ID
    with pytest.raises(ExactFourAuthorityContractError):
        parse_and_validate_exact_four_authority_document(
            __import__("json").dumps(mutated).encode("utf-8")
        )


def test_draft_authorization_cannot_mint_controlled_identity() -> None:
    with pytest.raises(TypeError):
        AuthorizedPaperExecutionRequest(
            mode="paper",
            authorization_id="sha256:" + ("ab" * 32),
            strategy_id="x",
            strategy_spec_hash="sha256:" + ("cd" * 32),
            max_gross_weight=1.0,
            instructions=(),
            controlled_pilot_identity=CONTROLLED_PILOT_IDENTITY,
        )
    with pytest.raises(ValueError, match="controlled_pilot_identity"):
        AuthorizedPaperExecutionRequest.from_dict(
            {
                "mode": "paper",
                "authorization_id": "sha256:" + ("ab" * 32),
                "strategy_id": "x",
                "strategy_spec_hash": "sha256:" + ("cd" * 32),
                "max_gross_weight": 1.0,
                "instructions": [],
                "controlled_pilot_identity": CONTROLLED_PILOT_IDENTITY,
            }
        )


def test_ready_bound_authorization_requires_controlled_identity() -> None:
    with pytest.raises(TypeError):
        AuthorizedPaperExecutionRequest(
            mode="paper",
            authorization_id="sha256:" + ("ab" * 32),
            strategy_id="x",
            strategy_spec_hash="sha256:" + ("cd" * 32),
            max_gross_weight=1.0,
            instructions=(),
            ready_snapshot_id="sha256:" + ("11" * 32),
            ready_manifest_digest="sha256:" + ("22" * 32),
        )
    with pytest.raises(ValueError, match="READY"):
        AuthorizedPaperExecutionRequest.from_dict(
            {
                "mode": "paper",
                "authorization_id": "sha256:" + ("ab" * 32),
                "strategy_id": "x",
                "strategy_spec_hash": "sha256:" + ("cd" * 32),
                "max_gross_weight": 1.0,
                "instructions": [],
                "ready_snapshot_id": "sha256:" + ("11" * 32),
                "ready_manifest_digest": "sha256:" + ("22" * 32),
            }
        )


def test_mass_start_rejects_pilot_readiness_type() -> None:
    from agents.mass_research import start_mass_research
    from research.readiness import VerifiedPilotReadiness

    forged = object.__new__(VerifiedPilotReadiness)
    with pytest.raises(MassResearchDisabledError, match="VerifiedPilotReadiness"):
        start_mass_research(budget=None, readiness=forged)  # type: ignore[arg-type]


def test_offline_fixture_service_rejects_ready_fields(tmp_path) -> None:
    spec = _draft_spec()
    with pytest.raises(ValueError, match="READY"):
        AuthorizedPaperExecutionRequest.from_dict(
            {
                "mode": "paper",
                "authorization_id": "sha256:" + ("ab" * 32),
                "strategy_id": spec.strategy_id,
                "strategy_spec_hash": "sha256:" + ("cd" * 32),
                "max_gross_weight": 1.0,
                "instructions": [],
                "ready_snapshot_id": "sha256:" + ("11" * 32),
            }
        )
    draft = AuthorizedPaperExecutionRequest(
        mode="paper",
        authorization_id="sha256:" + ("ab" * 32),
        strategy_id=spec.strategy_id,
        strategy_spec_hash="sha256:" + ("cd" * 32),
        max_gross_weight=1.0,
        instructions=(),
    )
    config = PaperRunConfig(
        start="2026-01-01",
        end="2026-01-02",
        db_path=tmp_path / "missing.sqlite",
        lifecycle=Lifecycle.DRAFT,
    )
    with pytest.raises(PaperExecutionRejected):
        PaperExecutionService().execute(draft, spec, config)


def test_serialized_draft_authorization_has_no_controlled_identity() -> None:
    draft = AuthorizedPaperExecutionRequest(
        mode="paper",
        authorization_id="sha256:" + ("ab" * 32),
        strategy_id="x",
        strategy_spec_hash="sha256:" + ("cd" * 32),
        max_gross_weight=1.0,
        instructions=(),
    )
    assert "identity" not in draft.to_dict()
    assert "controlled_pilot_identity" not in draft.to_dict()


def test_draft_cohort_cannot_mint_controlled_identity() -> None:
    from research.factor_cohorts import RESEARCH_COHORTS

    cohort = next(iter(RESEARCH_COHORTS.values()))
    with pytest.raises(ValueError, match="draft research purpose"):
        replace(cohort, purpose_id=CONTROLLED_PILOT_IDENTITY)
    document = cohort.to_dict()
    assert document["purpose_id"] in DRAFT_RESEARCH_PURPOSE_IDS
    assert "identity" not in document
    assert CONTROLLED_PILOT_IDENTITY not in document.values()


def test_mass_constructor_rejects_pilot_readiness_type() -> None:
    from research.phase7_pilot import MassResearchScheduler
    from research.readiness import VerifiedPilotReadiness

    forged = object.__new__(VerifiedPilotReadiness)
    with pytest.raises(MassResearchDisabledError, match="VerifiedPilotReadiness"):
        MassResearchScheduler(readiness=forged)  # type: ignore[arg-type]


def test_personal_paper_service_rejects_paper_lifecycle(tmp_path) -> None:
    from execution.personal_paper_service import (
        PersonalPaperExecutionRejected,
        PersonalPaperExecutionService,
    )

    spec = _draft_spec()
    config = PaperRunConfig(
        start="2026-01-01",
        end="2026-01-02",
        db_path=tmp_path / "missing.sqlite",
        lifecycle=Lifecycle.PAPER,
    )
    with pytest.raises(PersonalPaperExecutionRejected, match="DRAFT-only"):
        PersonalPaperExecutionService().execute(
            spec,
            config,
            expected_snapshot_id="sha256:" + ("11" * 32),
            approved_feature_refs=(),
        )
