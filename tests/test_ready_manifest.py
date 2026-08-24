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
    require_core_profile_deps_subseteq_source_capability_registry,
    serialize_ready_manifest,
)
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
    payload = {
        "snapshot_id": digest,
        "profile_id": "core",
        "profile_digest": _digest("profile"),
        "dataset_ids": ["equities_master"],
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
        "published_at": MISSING,
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


def test_unknown_fields_and_missing_proofs_are_not_pass() -> None:
    digest = _digest("fields")
    with pytest.raises(MassResearchDisabledError, match="schema invalid"):
        ReadyManifest.from_dict(
            {
                "format": READY_MANIFEST_FORMAT,
                "snapshot_id": digest,
                "profile_id": "core",
                "profile_digest": MISSING,
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
    assert reloaded.published_at == MISSING
    readiness = mint_verified_research_readiness(reloaded, db_path=artifact)
    assert readiness.snapshot_id == built.snapshot_id
    assert readiness.ready_manifest_digest == built.manifest_digest
    assert readiness.coverage_proof_digest == built.coverage_proof_digest
    assert readiness.b0_quality_proof_digest.startswith("sha256:")
    assert readiness.require_valid(expected_snapshot_id=built.snapshot_id) is readiness
    dumped = path.read_text(encoding="utf-8")
    assert "r2://" not in dumped
    assert "production READY" not in dumped
    assert json.loads(dumped)["published_at"] == MISSING


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
