"""ReadyManifest schema, fail-closed mint, core Deps ⊆ SourceCapability."""

from __future__ import annotations

import base64
import inspect
import json
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives import serialization

from paper_runtime.snapshot import READY_MANIFEST_SCHEMA as PUBLISH_SCHEMA
from paper_runtime.snapshot_publish_policy import READY_MANIFEST_SCHEMA as POLICY_SCHEMA
from qp_paths import repo_root
from research.ready_manifest import (
    MISSING,
    READY_MANIFEST_FORMAT,
    READY_MANIFEST_SCHEMA,
    UNKNOWN,
    ExactFourPilotReadyBinding,
    ReadyManifest,
    build_ready_manifest,
    canonical_digest,
    core_profile_source_capability_gaps,
    load_exact_four_pilot_ready_binding,
    load_ready_manifest,
    missing_ready_manifest_proofs,
    ready_manifest_from_snapshot_document,
    require_core_profile_deps_subseteq_source_capability_registry,
    serialize_ready_manifest,
)
from research.readiness import (
    GovernedMassReadinessAuthority,
    ReadinessPublicKeyRegistry,
    _ReadyPublicationSigner,
    load_verified_pilot_readiness,
)
from selection.budget_ledger import MassResearchDisabledError
from tests.readiness_test_support import (
    make_readiness_signer,
    mint_pilot_readiness,
)

_SNAPSHOT_PY = (
    repo_root()
    / "packages"
    / "research_runtime"
    / "paper_runtime"
    / "snapshot.py"
)
_POLICY_PY = (
    repo_root()
    / "packages"
    / "research_runtime"
    / "paper_runtime"
    / "snapshot_publish_policy.py"
)


@pytest.fixture
def readiness_publisher() -> _ReadyPublicationSigner:
    return make_readiness_signer(
        key_id="test-readiness-v1",
        private_key=Ed25519PrivateKey.generate(),
    )


def _digest(label: str) -> str:
    return canonical_digest({"offline": label})


def _complete_manifest(**overrides: object) -> ReadyManifest:
    digest = _digest("complete")
    binding = load_exact_four_pilot_ready_binding()
    payload = {
        "snapshot_id": digest,
        "publication_scope": "PILOT",
        "profile_id": binding.profile_id,
        "profile_version": binding.profile_version,
        "profile_digest": binding.profile_digest,
        "plan_ids": binding.plan_ids,
        "plan_set_digest": binding.plan_set_digest,
        "dependency_closure_digest": binding.closure_set_digest,
        "dataset_ids": binding.required_datasets,
        "coverage_proof_digest": _digest("coverage"),
        "raw_proof_digest": _digest("raw"),
        "receipt_proof_digest": _digest("receipt"),
        "validation_proof_digest": _digest("validation"),
        "b0_proof_digest": _digest("b0"),
        "b4_proof_digest": _digest("b4"),
        "source_generation": "1",
        "applied_sync_generation": "1",
        "export_cursor": "1",
        "applied_cursor": "1",
        "pit_contract_digests": {"pit_api": _digest("pit")},
        "feature_generation": _digest("feature"),
        "catalog_generation": _digest("catalog"),
        "created_at": "2026-08-24T00:00:00+00:00",
        "published_at": "2026-08-24T00:01:00+00:00",
    }
    payload.update(overrides)
    return build_ready_manifest(**payload)  # type: ignore[arg-type]


def test_pilot_readiness_sidecar_loader_is_strict_public_key_only(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    private_key = Ed25519PrivateKey.generate()
    publisher = make_readiness_signer(
        key_id="sidecar-loader-test",
        private_key=private_key,
    )
    manifest = _complete_manifest()
    readiness = mint_pilot_readiness(
        manifest,
        publisher=publisher,
        immutable_db_digest=_digest("immutable-db"),
    )
    sidecar = tmp_path / "pilot.readiness.json"
    sidecar.write_text(json.dumps(readiness.to_dict()), encoding="utf-8")
    public_raw = private_key.public_key().public_bytes(
        serialization.Encoding.Raw,
        serialization.PublicFormat.Raw,
    )
    registry = tmp_path / "readiness-public-keys.json"
    registry.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "keys": [
                    {
                        "key_id": "sidecar-loader-test",
                        "algorithm": "Ed25519",
                        "public_key_b64": base64.b64encode(public_raw).decode("ascii"),
                        "status": "active",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    trusted_registry = ReadinessPublicKeyRegistry.from_file(registry)
    monkeypatch.setattr(
        ReadinessPublicKeyRegistry,
        "load_pinned",
        classmethod(lambda cls: trusted_registry),
    )
    loaded = load_verified_pilot_readiness(
        sidecar,
        expected_snapshot_id=manifest.snapshot_id,
        expected_ready_manifest_digest=manifest.to_dict()["manifest_digest"],
    )
    assert loaded == readiness

    tampered = readiness.to_dict()
    tampered["caller_override"] = True
    sidecar.write_text(json.dumps(tampered), encoding="utf-8")
    with pytest.raises(MassResearchDisabledError, match="fields are not closed"):
        load_verified_pilot_readiness(sidecar)

    expired = mint_pilot_readiness(
        manifest,
        publisher=publisher,
        immutable_db_digest=_digest("immutable-db"),
        now=datetime(2020, 1, 1, tzinfo=timezone.utc),
        ttl_seconds=60,
    )
    sidecar.write_text(json.dumps(expired.to_dict()), encoding="utf-8")
    with pytest.raises(MassResearchDisabledError, match="expired"):
        load_verified_pilot_readiness(sidecar)


def test_readiness_registry_requires_explicit_status_and_exactly_one_active() -> None:
    public_raw = Ed25519PrivateKey.generate().public_key().public_bytes(
        serialization.Encoding.Raw,
        serialization.PublicFormat.Raw,
    )
    encoded = base64.b64encode(public_raw).decode("ascii")
    row = {
        "key_id": "readiness-a",
        "algorithm": "Ed25519",
        "public_key_b64": encoded,
    }
    with pytest.raises(MassResearchDisabledError, match="explicit active/revoked"):
        ReadinessPublicKeyRegistry.from_document(
            {"schema_version": 1, "keys": [row]}
        )
    with pytest.raises(MassResearchDisabledError, match="exactly one active"):
        ReadinessPublicKeyRegistry.from_document(
            {
                "schema_version": 1,
                "keys": [
                    {**row, "status": "active"},
                    {**row, "key_id": "readiness-b", "status": "active"},
                ],
            }
        )


def test_caller_environment_registry_cannot_self_root_pilot_readiness(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    attacker_key = Ed25519PrivateKey.generate()
    attacker = make_readiness_signer(
        key_id="attacker-readiness",
        private_key=attacker_key,
    )
    manifest = _complete_manifest()
    readiness = mint_pilot_readiness(
        manifest,
        publisher=attacker,
        immutable_db_digest=_digest("attacker-db"),
    )
    sidecar = tmp_path / "attacker.readiness.json"
    sidecar.write_text(json.dumps(readiness.to_dict()), encoding="utf-8")
    public_raw = attacker_key.public_key().public_bytes(
        serialization.Encoding.Raw,
        serialization.PublicFormat.Raw,
    )
    attacker_registry = tmp_path / "attacker-registry.json"
    attacker_registry.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "purpose": "readiness_attestation_verification",
                "keys": [
                    {
                        "key_id": "attacker-readiness",
                        "algorithm": "Ed25519",
                        "public_key_b64": base64.b64encode(public_raw).decode("ascii"),
                        "status": "active",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv(
        "QUANT_READINESS_PUBLIC_KEY_REGISTRY", str(attacker_registry)
    )
    with pytest.raises(MassResearchDisabledError, match="untrusted"):
        load_verified_pilot_readiness(sidecar)


def test_single_ready_manifest_schema_is_the_publish_gate() -> None:
    assert READY_MANIFEST_SCHEMA["$id"] == READY_MANIFEST_FORMAT
    assert POLICY_SCHEMA["$id"] == READY_MANIFEST_FORMAT
    assert PUBLISH_SCHEMA["$id"] == READY_MANIFEST_FORMAT
    assert POLICY_SCHEMA == READY_MANIFEST_SCHEMA
    assert PUBLISH_SCHEMA == READY_MANIFEST_SCHEMA
    snapshot_src = _SNAPSHOT_PY.read_text(encoding="utf-8")
    policy_src = _POLICY_PY.read_text(encoding="utf-8")
    assert "evaluate_ready_publication" in snapshot_src
    assert "ReadyPublicationPolicy" not in snapshot_src
    assert "ready_manifest.schema.json" in policy_src
    assert "def evaluate_ready_publication" in policy_src


def test_ready_private_key_and_mint_are_not_public_control_plane_api() -> None:
    import research
    import research.readiness as readiness_module
    import research.ready_manifest as manifest_module

    assert not hasattr(research, "ReadinessAttestationPublisher")
    assert not hasattr(readiness_module, "ReadinessAttestationPublisher")
    assert not hasattr(manifest_module, "mint_verified_research_readiness")
    assert not hasattr(manifest_module, "mint_verified_pilot_readiness")
    with pytest.raises(MassResearchDisabledError, match="publication service"):
        _ReadyPublicationSigner(
            key_id="caller-key",
            private_key=Ed25519PrivateKey.generate(),
        )


def test_profile_manifest_builder_has_one_product_owned_call_site() -> None:
    allowed = repo_root() / "packages" / "product" / "research" / "ready_manifest.py"
    callers = []
    for path in (repo_root() / "packages").rglob("*.py"):
        if path in (allowed, _SNAPSHOT_PY):
            continue
        if "_ready_manifest_builder=" in path.read_text(encoding="utf-8"):
            callers.append(path.relative_to(repo_root()).as_posix())
    assert callers == []
    assert "_ready_manifest_builder=_build" in allowed.read_text(encoding="utf-8")


def test_unknown_fields_and_missing_proofs_are_not_pass() -> None:
    digest = _digest("fields")
    with pytest.raises(MassResearchDisabledError, match="schema invalid"):
        ReadyManifest.from_dict(
            {
                "format": READY_MANIFEST_FORMAT,
                "snapshot_id": digest,
                "profile_id": "core",
                "profile_version": MISSING,
                "profile_digest": MISSING,
                "dataset_ids": [],
                "dataset_membership_digest": MISSING,
                "coverage_proof_digest": MISSING,
                "raw_proof_digest": MISSING,
                "validation_proof_digest": MISSING,
                "b0_proof_digest": MISSING,
                "source_generation": MISSING,
                "applied_sync_generation": MISSING,
                "pit_contract_digests": {"pit_api": MISSING},
                "feature_generation": MISSING,
                "catalog_generation": MISSING,
                "created_at": "2026-08-24T00:00:00+00:00",
                "published_at": MISSING,
                "complete": True,
            }
        )
    manifest = build_ready_manifest(
        snapshot_id=digest,
        profile_id="core",
        coverage_proof_digest=UNKNOWN,
        b0_proof_digest=None,
    )
    missing = missing_ready_manifest_proofs(manifest)
    assert "coverage_proof_digest" in missing
    assert "b0_proof_digest" in missing
    assert "PASS" not in missing
    with pytest.raises(MassResearchDisabledError, match="UNKNOWN/MISSING"):
        mint_pilot_readiness(
            manifest, immutable_db_digest=_digest("db")
        )


def test_ready_manifest_offline_e2e_serialize_reload_mint(
    tmp_path: Path, readiness_publisher: _ReadyPublicationSigner
) -> None:
    """Publisher helpers → serialize → reload → mint. No live R2. Not production READY."""
    built = _complete_manifest()
    path = tmp_path / "ready_manifest.json"
    serialize_ready_manifest(built, path)
    reloaded = load_ready_manifest(path)
    assert reloaded.to_canonical_dict() == built.to_canonical_dict()
    assert reloaded.manifest_digest == built.manifest_digest
    assert reloaded.published_at == "2026-08-24T00:01:00+00:00"
    readiness = mint_pilot_readiness(
        reloaded,
        immutable_db_digest=_digest("offline-fixture-db"),
        publisher=readiness_publisher,
    )
    assert readiness.snapshot_id == built.snapshot_id
    assert readiness.ready_manifest_digest == built.manifest_digest
    assert readiness.coverage_proof_digest == built.coverage_proof_digest
    assert readiness.b0_quality_proof_digest.startswith("sha256:")
    assert readiness.require_valid(
        expected_snapshot_id=built.snapshot_id,
        verifier=readiness_publisher._public_registry(),
    ) is readiness
    dumped = path.read_text(encoding="utf-8")
    assert "r2://" not in dumped
    assert "production READY" not in dumped
    assert json.loads(dumped)["published_at"] == "2026-08-24T00:01:00+00:00"


def test_production_mint_cannot_accept_caller_supplied_artifact_digest_or_clock(
    readiness_publisher: _ReadyPublicationSigner,
) -> None:
    parameters = inspect.signature(readiness_publisher._mint_pilot).parameters
    assert "immutable_db_digest" not in parameters
    assert "now" not in parameters
    with pytest.raises(TypeError, match="unexpected keyword argument"):
        readiness_publisher._mint_pilot(
            _complete_manifest(),
            immutable_db_digest=_digest("caller-asserted-db"),
        )  # type: ignore[call-arg]


def test_mass_mint_requires_unavailable_governed_authority_and_stays_disabled(
    readiness_publisher: _ReadyPublicationSigner,
) -> None:
    manifest = _complete_manifest(publication_scope="MASS")
    with pytest.raises(
        MassResearchDisabledError,
        match="GovernedMassReadinessAuthority",
    ):
        readiness_publisher._mint_mass(manifest)
    with pytest.raises(MassResearchDisabledError, match="no public issuer"):
        GovernedMassReadinessAuthority(
            policy_id="mass-policy/v1",
            profile_id="mass/governed-v1",
            policy_digest=_digest("mass-policy"),
        )


def test_ready_manifest_rejects_caller_asserted_coverage_policy_binding() -> None:
    manifest = replace(
        _complete_manifest(),
        coverage_policy_digest=_digest("caller-asserted-policy"),
        manifest_digest="",
    )
    missing = missing_ready_manifest_proofs(manifest)
    assert "coverage_policy_digest.binding" in missing
    with pytest.raises(MassResearchDisabledError, match="Coverage policy-set"):
        from research.ready_manifest import validate_ready_manifest_profile_binding

        validate_ready_manifest_profile_binding(manifest)


def test_exact_four_binding_rejects_self_consistent_caller_substitution() -> None:
    from research.dependency_closure import build_plan_dependency_closure
    from research.research_data_profile import profile_from_dependency_closure

    canonical = load_exact_four_pilot_ready_binding()
    substituted = replace(
        canonical.plans[0], hypothesis="caller-controlled alternate hypothesis"
    )
    substituted_closure = build_plan_dependency_closure(substituted)
    substituted_profile = profile_from_dependency_closure(substituted_closure)
    with pytest.raises(MassResearchDisabledError):
        ExactFourPilotReadyBinding(
            plans=(substituted, *canonical.plans[1:]),
            closures=(substituted_closure, *canonical.closures[1:]),
            profiles=(substituted_profile, *canonical.profiles[1:]),
        )


def test_private_signer_cannot_mint_generic_caller_pilot_manifest(
    readiness_publisher: _ReadyPublicationSigner,
) -> None:
    caller_manifest = _complete_manifest(
        profile_id="caller/generic-pilot",
        profile_digest=_digest("caller-profile"),
    )
    with pytest.raises(MassResearchDisabledError, match="profile_id mismatch"):
        readiness_publisher._mint_pilot(
            caller_manifest,
            db_path=Path("/nonexistent/caller-db.sqlite"),
            profile_binding=load_exact_four_pilot_ready_binding(),
        )


@pytest.mark.parametrize(
    ("override", "expected"),
    [
        ({"dataset_ids": ["equities_master"]}, "exactly match"),
        ({"profile_id": MISSING}, "profile_id"),
        ({"profile_version": MISSING}, "profile_version"),
        ({"profile_digest": MISSING}, "profile_digest"),
        ({"dataset_membership_digest": _digest("wrong-membership")}, "binding"),
        ({"published_at": MISSING}, "published_at"),
        ({"created_at": MISSING}, "created_at"),
        ({"coverage_proof_digest": MISSING}, "coverage_proof_digest"),
        ({"raw_proof_digest": MISSING}, "raw_proof_digest"),
        ({"receipt_proof_digest": MISSING}, "receipt_proof_digest"),
        ({"validation_proof_digest": MISSING}, "validation_proof_digest"),
        ({"b0_proof_digest": MISSING}, "b0_proof_digest"),
        ({"b4_proof_digest": MISSING}, "b4_proof_digest"),
        ({"source_generation": MISSING}, "source_generation"),
        ({"applied_sync_generation": MISSING}, "applied_sync_generation"),
        ({"export_cursor": MISSING}, "export_cursor"),
        ({"applied_cursor": MISSING}, "applied_cursor"),
        ({"pit_contract_digests": {"pit_api": MISSING}}, "pit_contract_digests"),
        (
            {"source_generation": "source-2", "applied_sync_generation": "source-1"},
            "current_sync",
        ),
    ],
)
def test_manifest_mint_rejects_profile_or_evidence_gaps(
    override: dict[str, object], expected: str
) -> None:
    manifest = _complete_manifest(**override)
    with pytest.raises(MassResearchDisabledError, match=expected):
        mint_pilot_readiness(
            manifest, immutable_db_digest=_digest("immutable-db")
        )


def test_snapshot_adapter_requires_publisher_owned_outer_bindings() -> None:
    manifest = _complete_manifest()
    outer = {
        "format": "research-snapshot-manifest/v2",
        "state": "READY",
        "snapshot_id": manifest.snapshot_id,
        "required_datasets": list(manifest.dataset_ids),
        "committed_at": manifest.published_at,
        "ready_manifest": manifest.to_dict(),
    }
    with pytest.raises(MassResearchDisabledError, match="coverage proof missing"):
        ready_manifest_from_snapshot_document(outer)
    with pytest.raises(MassResearchDisabledError, match="no publisher-owned"):
        ready_manifest_from_snapshot_document({key: value for key, value in outer.items() if key != "ready_manifest"})
    tampered = dict(outer)
    tampered["required_datasets"] = ["equities_master"]
    with pytest.raises(MassResearchDisabledError, match="membership binding"):
        ready_manifest_from_snapshot_document(tampered)


def test_core_profile_deps_subseteq_source_capability_registry() -> None:
    """Build invariant: every core_v1 dataset has a SourceCapability file.

    Missing ids are listed. They are UNKNOWN, not invented PASS.
    This lane does not add V3 JSON for the other 22 datasets.
    """
    spec = json.loads(
        (repo_root() / "specs" / "research_profiles" / "core_v1.json").read_text(
            encoding="utf-8"
        )
    )
    required = spec["required_datasets"]
    missing = core_profile_source_capability_gaps()
    for dataset_id in missing:
        assert dataset_id in required
        cap = repo_root() / "specs" / "source_capability" / f"{dataset_id}.json"
        assert not cap.is_file()
    require_core_profile_deps_subseteq_source_capability_registry()
    assert missing == ()
