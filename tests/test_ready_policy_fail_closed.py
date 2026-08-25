"""Production READY evidence is fail-closed; fixture compatibility stays private."""

from __future__ import annotations

import base64
import sqlite3
from datetime import datetime, timezone

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from data_contracts.coverage import POLICY_VERSION as COVERAGE_POLICY_VERSION
from ops.projection_signing import (
    ENVELOPE_SCHEMA,
    OpsProjectionPublicKeyRegistry,
    OpsProjectionSigningKey,
)
from paper_runtime.ready_policy import (
    SyncGenerationEvidence,
    collect_typed_evidence,
)
from paper_runtime.snapshot import SnapshotRejected, publish_ready_snapshot
import research.research_data_profile as profile_module
from research.ready_manifest import (
    load_exact_four_pilot_ready_binding,
    publish_exact_four_pilot_ready_snapshot,
    publish_profile_bound_ready_snapshot,
)
from research.research_data_profile import load_core_profile, official_mode
from selection.budget_ledger import MassResearchDisabledError


def _unsigned_projection_evidence(dataset_ids) -> dict[str, dict[str, str]]:
    return {
        dataset_id: {
            "status": "COMPLETE",
            "coverage_mode": official_mode(dataset_id),
            "projection_status": "FRESH",
            "source_generation": "cursor-7",
            "export_cursor": "cursor-7",
            "applied_cursor": "cursor-7",
        }
        for dataset_id in dataset_ids
    }


def _signed_projection_evidence(
    dataset_ids, *, cursor: int = 7, b0_status: str = "PASS"
) -> tuple[dict[str, object], OpsProjectionPublicKeyRegistry]:
    private_key = Ed25519PrivateKey.generate()
    key_id = "ops-projection-ready-test"
    raw_public = private_key.public_key().public_bytes(
        serialization.Encoding.Raw,
        serialization.PublicFormat.Raw,
    )
    registry = OpsProjectionPublicKeyRegistry.from_document(
        {
            "schema_version": 1,
            "keys": [
                {
                    "key_id": key_id,
                    "algorithm": "Ed25519",
                    "public_key_base64": base64.b64encode(raw_public).decode("ascii"),
                }
            ],
        }
    )
    digest = "sha256:" + ("ab" * 32)
    envelope = {
        "schema_version": ENVELOPE_SCHEMA,
        "generation_id": "projection-generation-7",
        "content_digest": digest,
        "source_db_digest": digest,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "producer_commit_sha": "deadbeef",
        "contract_digest": digest,
        "registry_digest": digest,
        "coverage_policy_version": COVERAGE_POLICY_VERSION,
        "projection_status": "FRESH",
        "source_generation": cursor,
        "source_snapshot_generation": cursor,
        "source_cursor": cursor,
        "export_cursor": cursor,
        "applied_cursor": cursor,
        "coverage_status_digest": digest,
        "dataset_coverage": {
            dataset_id: {
                "status": "COMPLETE",
                "coverage_mode": official_mode(dataset_id),
                "policy_version": COVERAGE_POLICY_VERSION,
            }
            for dataset_id in dataset_ids
        },
        "b0_status": b0_status,
        "b0_evidence_digest": digest,
        "b4_status": "PASS",
        "b4_evidence_digest": digest,
        "evidence_digests": {"ready": digest},
        "row_counts": {"dataset_coverage": len(tuple(dataset_ids))},
    }
    signed = OpsProjectionSigningKey(key_id, private_key).sign(envelope)
    return signed, registry


def test_missing_production_ledgers_are_not_pass() -> None:
    conn = sqlite3.connect(":memory:")
    evidence = collect_typed_evidence(
        conn,
        ":memory:",
        ("equities_bars_daily",),
        run_id=1,
    )
    by_type = {type(item).__name__: item.to_item() for item in evidence}
    for evidence_type in (
        "CoverageEvidence",
        "RawRetentionEvidence",
        "ValidationEvidence",
        "NaturalKeyEvidence",
        "QualityEvidence",
        "SyncGenerationEvidence",
    ):
        assert by_type[evidence_type].passed is False


def test_source_and_applied_generation_must_match() -> None:
    assert SyncGenerationEvidence(7, 7).to_item().passed is True
    mismatch = SyncGenerationEvidence(7, 6).to_item()
    assert mismatch.passed is False
    assert mismatch.detail == {
        "source_generation": 7,
        "applied_sync_generation": 6,
    }


def test_unsigned_projection_mapping_cannot_publish_profile_ready(tmp_path) -> None:
    profile = load_core_profile()
    with pytest.raises(MassResearchDisabledError, match="signed projection"):
        publish_profile_bound_ready_snapshot(
            tmp_path / "current.sqlite",
            tmp_path / "snapshots",
            profile_id=profile.profile_id,
            evidence_by_dataset=_unsigned_projection_evidence(
                profile.required_datasets
            ),
        )


def test_unsigned_projection_mapping_cannot_publish_pilot_ready(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # This test exercises the production authority boundary, not the
    # independently governed SourceCapability inventory.  Keep every
    # dependency otherwise eligible so the unsigned-envelope rejection is the
    # first and decisive failure.
    monkeypatch.setattr(
        profile_module,
        "source_capability_contract_or_none",
        lambda _dataset_id: object(),
    )
    binding = load_exact_four_pilot_ready_binding()
    with pytest.raises(MassResearchDisabledError, match="signed projection"):
        publish_exact_four_pilot_ready_snapshot(
            tmp_path / "current.sqlite",
            tmp_path / "snapshots",
            binding=binding,
            evidence_by_dataset=_unsigned_projection_evidence(
                binding.required_datasets
            ),
        )


def test_signed_projection_is_the_only_production_pilot_input(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        profile_module,
        "source_capability_contract_or_none",
        lambda _dataset_id: object(),
    )
    binding = load_exact_four_pilot_ready_binding()
    signed, registry = _signed_projection_evidence(binding.required_datasets)
    captured: dict[str, object] = {}

    def fake_publish(_db, _snapshot_dir, **kwargs):
        captured.update(kwargs)
        return "verified-signed-envelope"

    monkeypatch.setattr("paper_runtime.snapshot.publish_ready_snapshot", fake_publish)
    result = publish_exact_four_pilot_ready_snapshot(
        tmp_path / "current.sqlite",
        tmp_path / "snapshots",
        binding=binding,
        signed_projection_document=signed,
        projection_verifier=registry,
    )
    assert result == "verified-signed-envelope"
    evidence = captured["_profile_coverage_evidence"]
    assert set(evidence) == set(binding.required_datasets)  # type: ignore[arg-type]
    assert all(
        row["signed_projection_document_digest"].startswith("sha256:")
        for row in evidence.values()  # type: ignore[union-attr]
    )


def test_signed_projection_still_rejects_nonpass_gates(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        profile_module,
        "source_capability_contract_or_none",
        lambda _dataset_id: object(),
    )
    binding = load_exact_four_pilot_ready_binding()
    signed, registry = _signed_projection_evidence(
        binding.required_datasets, b0_status="UNKNOWN"
    )
    with pytest.raises(MassResearchDisabledError, match="B0/B4"):
        publish_exact_four_pilot_ready_snapshot(
            tmp_path / "current.sqlite",
            tmp_path / "snapshots",
            binding=binding,
            signed_projection_document=signed,
            projection_verifier=registry,
        )


def test_tampered_signed_projection_is_rejected(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        profile_module,
        "source_capability_contract_or_none",
        lambda _dataset_id: object(),
    )
    binding = load_exact_four_pilot_ready_binding()
    signed, registry = _signed_projection_evidence(binding.required_datasets)
    signed["envelope"]["applied_cursor"] = 8  # type: ignore[index]
    with pytest.raises(MassResearchDisabledError, match="signature is invalid"):
        publish_exact_four_pilot_ready_snapshot(
            tmp_path / "current.sqlite",
            tmp_path / "snapshots",
            binding=binding,
            signed_projection_document=signed,
            projection_verifier=registry,
        )


def test_fixture_ready_switch_is_unavailable_outside_pytest(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    with pytest.raises(SnapshotRejected, match="test-only"):
        publish_ready_snapshot(
            tmp_path / "current.sqlite",
            tmp_path / "snapshots",
            required_datasets=("equities_bars_daily",),
            _fixture_policy=True,
        )
