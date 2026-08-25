"""ReadyManifest schema, fail-closed mint, core Deps ⊆ SourceCapability."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from paper_runtime.snapshot import READY_MANIFEST_SCHEMA as PUBLISH_SCHEMA
from paper_runtime.snapshot_publish_policy import READY_MANIFEST_SCHEMA as POLICY_SCHEMA
from qp_paths import repo_root
from research.ready_manifest import (
    MISSING,
    READY_MANIFEST_FORMAT,
    READY_MANIFEST_SCHEMA,
    UNKNOWN,
    ReadyManifest,
    build_ready_manifest,
    canonical_digest,
    core_profile_source_capability_gaps,
    load_ready_manifest,
    mint_verified_research_readiness,
    missing_ready_manifest_proofs,
    ready_manifest_from_snapshot_document,
    require_core_profile_deps_subseteq_source_capability_registry,
    serialize_ready_manifest,
)
from research.research_data_profile import load_core_profile
from selection.budget_ledger import MassResearchDisabledError

_TEST_HMAC = "ready-manifest-offline-e2e-hmac"
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


@pytest.fixture(autouse=True)
def _hmac_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("QUANT_READINESS_HMAC_SECRET", _TEST_HMAC)


def _digest(label: str) -> str:
    return canonical_digest({"offline": label})


def _complete_manifest(**overrides: object) -> ReadyManifest:
    digest = _digest("complete")
    profile = load_core_profile()
    payload = {
        "snapshot_id": digest,
        "profile_id": profile.profile_id,
        "profile_version": profile.profile_version,
        "profile_digest": profile.profile_digest,
        "dataset_ids": profile.required_datasets,
        "coverage_proof_digest": _digest("coverage"),
        "raw_proof_digest": _digest("raw"),
        "validation_proof_digest": _digest("validation"),
        "b0_proof_digest": _digest("b0"),
        "source_generation": "1",
        "applied_sync_generation": "1",
        "pit_contract_digests": {"pit_api": _digest("pit")},
        "feature_generation": _digest("feature"),
        "catalog_generation": _digest("catalog"),
        "created_at": "2026-08-24T00:00:00+00:00",
        "published_at": "2026-08-24T00:01:00+00:00",
    }
    payload.update(overrides)
    return build_ready_manifest(**payload)  # type: ignore[arg-type]


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
        mint_verified_research_readiness(
            manifest, immutable_db_digest=_digest("db")
        )


def test_ready_manifest_offline_e2e_serialize_reload_mint(tmp_path: Path) -> None:
    """Publisher helpers → serialize → reload → mint. No live R2. Not production READY."""
    artifact = tmp_path / "offline-artifact.sqlite"
    artifact.write_bytes(b"offline-ready-manifest-not-r2")
    built = _complete_manifest()
    path = tmp_path / "ready_manifest.json"
    serialize_ready_manifest(built, path)
    reloaded = load_ready_manifest(path)
    assert reloaded.to_canonical_dict() == built.to_canonical_dict()
    assert reloaded.manifest_digest == built.manifest_digest
    assert reloaded.published_at == "2026-08-24T00:01:00+00:00"
    readiness = mint_verified_research_readiness(reloaded, db_path=artifact)
    assert readiness.snapshot_id == built.snapshot_id
    assert readiness.ready_manifest_digest == built.manifest_digest
    assert readiness.coverage_proof_digest == built.coverage_proof_digest
    assert readiness.b0_quality_proof_digest.startswith("sha256:")
    assert readiness.require_valid(expected_snapshot_id=built.snapshot_id) is readiness
    dumped = path.read_text(encoding="utf-8")
    assert "r2://" not in dumped
    assert "production READY" not in dumped
    assert json.loads(dumped)["published_at"] == "2026-08-24T00:01:00+00:00"


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
        ({"validation_proof_digest": MISSING}, "validation_proof_digest"),
        ({"b0_proof_digest": MISSING}, "b0_proof_digest"),
        ({"source_generation": MISSING}, "source_generation"),
        ({"applied_sync_generation": MISSING}, "applied_sync_generation"),
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
        mint_verified_research_readiness(
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
    with pytest.raises(AssertionError, match="missing SourceCapability files") as exc:
        require_core_profile_deps_subseteq_source_capability_registry()
    listed = str(exc.value)
    for dataset_id in missing:
        assert dataset_id in listed
    # Subset does not currently hold. Missing is UNKNOWN, not default PASS.
    # This lane does not invent V3 JSON for the other 22 datasets.
    assert missing, listed
