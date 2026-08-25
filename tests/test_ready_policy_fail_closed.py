"""Production READY evidence is fail-closed; fixture compatibility stays private."""

from __future__ import annotations

import base64
import json
import sqlite3
from datetime import datetime, timezone

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from data_contracts.coverage import (
    coverage_policy_binding,
    coverage_policy_set_binding,
)
from ops.projection_content import (
    PROJECTED_CONTENT_TABLES,
    build_projection_content_manifest,
)
from ops.projection_signing import (
    ENVELOPE_SCHEMA,
    OpsProjectionPublicKeyRegistry,
    OpsProjectionSigningKey,
)
from paper_runtime.ready_policy import (
    SyncGenerationEvidence,
    collect_typed_evidence,
)
from paper_runtime.snapshot import ReadySnapshot, SnapshotRejected, _publish_ready_snapshot
import research.research_data_profile as profile_module
from research.readiness import ReadinessPublicKeyRegistry
from research.ready_manifest import (
    VerifiedPilotReadyPublication,
    build_profile_bound_ready_manifest_from_snapshot_document,
    build_ready_manifest,
    canonical_digest,
    load_exact_four_pilot_ready_binding,
    publish_exact_four_pilot_ready_snapshot,
    _verified_production_projection_evidence,
    _verify_exact_four_pit_dependency_scope,
)
from research.research_data_profile import load_core_profile, official_mode
from selection.budget_ledger import MassResearchDisabledError
from tests.readiness_test_support import make_readiness_signer


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
    dataset_ids,
    *,
    cursor: int = 7,
    b0_status: str = "PASS",
    corrupt_policy_dataset: str | None = None,
    key_id: str = "ops-projection-ready-test",
    registry_path=None,
) -> tuple[dict[str, object], OpsProjectionPublicKeyRegistry]:
    private_key = Ed25519PrivateKey.generate()
    raw_public = private_key.public_key().public_bytes(
        serialization.Encoding.Raw,
        serialization.PublicFormat.Raw,
    )
    registry_document = {
        "schema_version": 1,
        "purpose": "ops_projection_verification",
        "keys": [
            {
                "key_id": key_id,
                "algorithm": "Ed25519",
                "public_key_base64": base64.b64encode(raw_public).decode("ascii"),
                "status": "active",
            }
        ],
    }
    registry = OpsProjectionPublicKeyRegistry.from_document(registry_document)
    if registry_path is not None:
        registry_path.write_text(json.dumps(registry_document), encoding="utf-8")
    digest = "sha256:" + ("ab" * 32)
    dataset_ids = tuple(dataset_ids)
    policy_set = coverage_policy_set_binding(list(dataset_ids))
    dataset_coverage = {
        dataset_id: {
            "status": "COMPLETE",
            "coverage_mode": official_mode(dataset_id),
            **dict(coverage_policy_binding(dataset_id)),
            "collection_scope": "test",
            "observed_start": "2023-01-04",
            "observed_end": "2023-10-13",
        }
        for dataset_id in dataset_ids
    }
    if corrupt_policy_dataset is not None:
        dataset_coverage[corrupt_policy_dataset]["policy_digest"] = (
            "sha256:" + ("00" * 32)
        )
    table_rows = {table: [] for table in PROJECTED_CONTENT_TABLES}
    table_rows["dataset_coverage"] = [
        {"dataset": dataset_id, **row}
        for dataset_id, row in dataset_coverage.items()
    ]
    content_manifest, content_digest = build_projection_content_manifest(table_rows)
    envelope = {
        "schema_version": ENVELOPE_SCHEMA,
        "generation_id": "projection-generation-7",
        "content_digest": content_digest,
        "source_db_digest": digest,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "producer_commit_sha": "deadbeef",
        "contract_digest": digest,
        "registry_digest": digest,
        "coverage_policy_version": policy_set["policy_version"],
        "coverage_policy_digest": policy_set["policy_digest"],
        "projection_status": "FRESH",
        "source_generation": cursor,
        "source_snapshot_generation": cursor,
        "source_cursor": cursor,
        "export_cursor": cursor,
        "applied_cursor": cursor,
        "coverage_status_digest": digest,
        "dataset_coverage": dataset_coverage,
        "b0_status": b0_status,
        "b0_evidence_digest": digest,
        "b4_status": "PASS",
        "b4_evidence_digest": digest,
        "evidence_digests": {"ready": digest},
        "content_manifest": content_manifest,
        "row_counts": {
            table: row["row_count"] for table, row in content_manifest.items()
        },
    }
    signed = OpsProjectionSigningKey(key_id, private_key).sign(envelope)
    return signed, registry


def _configure_projection_registry_for_test(
    monkeypatch: pytest.MonkeyPatch,
    registry: OpsProjectionPublicKeyRegistry,
) -> None:
    monkeypatch.setattr(
        OpsProjectionPublicKeyRegistry,
        "load_pinned",
        classmethod(lambda cls, path=None: registry),
    )


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


@pytest.mark.parametrize(
    "unsafe_keyword",
    ("binding", "evidence_by_dataset", "_fixture_policy", "projection_verifier"),
)
def test_public_ready_surface_has_no_generic_or_fixture_bypass(
    unsafe_keyword: str,
) -> None:
    import paper_runtime
    import research.ready_manifest as ready_module

    assert not hasattr(paper_runtime, "publish_ready_snapshot")
    assert not hasattr(ready_module, "publish_profile_bound_ready_snapshot")
    with pytest.raises(TypeError, match="unexpected keyword argument"):
        publish_exact_four_pilot_ready_snapshot(
            "current.sqlite",
            "snapshots",
            signed_projection_document={},
            **{unsafe_keyword: object()},
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
    signed, registry = _signed_projection_evidence(
        (*binding.required_datasets, "markets_margin_alert")
    )
    _configure_projection_registry_for_test(monkeypatch, registry)
    assert str(signed["envelope"]["coverage_policy_version"]).startswith(  # type: ignore[index]
        "mixed:sha256:"
    )
    captured: dict[str, object] = {}
    proof = canonical_digest({"production": "proof"})
    snapshot_id = canonical_digest({"production": "snapshot"})
    manifest = build_ready_manifest(
        snapshot_id=snapshot_id,
        publication_scope="PILOT",
        profile_id=binding.profile_id,
        profile_version=binding.profile_version,
        profile_digest=binding.profile_digest,
        plan_ids=binding.plan_ids,
        plan_set_digest=binding.plan_set_digest,
        dependency_closure_digest=binding.closure_set_digest,
        dataset_ids=binding.required_datasets,
        coverage_proof_digest=proof,
        raw_proof_digest=proof,
        receipt_proof_digest=proof,
        validation_proof_digest=proof,
        b0_proof_digest=proof,
        b4_proof_digest=proof,
        source_generation="7",
        applied_sync_generation="7",
        export_cursor="7",
        applied_cursor="7",
        pit_contract_digests={"pit_api": proof, "dependency_scope": proof},
        feature_generation=proof,
        catalog_generation=proof,
        created_at="2026-08-25T00:00:00+00:00",
        published_at="2026-08-25T00:01:00+00:00",
    )
    artifact = tmp_path / "immutable.sqlite"
    artifact.write_bytes(b"immutable-snapshot-fixture")
    artifact.chmod(0o444)
    manifest_path = tmp_path / "immutable.manifest.json"
    manifest_path.write_text("{}", encoding="utf-8")
    ready = ReadySnapshot(
        snapshot_id=snapshot_id,
        db_path=artifact,
        manifest_path=manifest_path,
        manifest={},
    )
    readiness_key = Ed25519PrivateKey.generate()
    readiness_signer = make_readiness_signer(
        key_id="configured-ready-test",
        private_key=readiness_key,
    )
    monkeypatch.setattr(
        "research.readiness._load_pinned_ready_publication_signer",
        lambda: readiness_signer,
    )
    monkeypatch.setattr("paper_runtime.data_snapshot_id", lambda _path: snapshot_id)
    monkeypatch.setattr(
        "research.ready_manifest.ready_manifest_from_snapshot_document",
        lambda _document: manifest,
    )
    monkeypatch.setattr(
        "research.ready_manifest._verify_exact_four_pit_dependency_scope",
        lambda _path, _binding: {"proof_digest": proof},
    )

    def fake_publish(_db, _snapshot_dir, **kwargs):
        captured.update(kwargs)
        kwargs["_ready_attestation_builder"](ready)
        return ready

    monkeypatch.setattr("paper_runtime.snapshot._publish_ready_snapshot", fake_publish)
    result = publish_exact_four_pilot_ready_snapshot(
        tmp_path / "current.sqlite",
        tmp_path / "snapshots",
        signed_projection_document=signed,
    )
    assert isinstance(result, VerifiedPilotReadyPublication)
    assert result.snapshot is ready
    assert result.readiness.snapshot_id == snapshot_id
    assert result.readiness_path.is_file()
    assert result.readiness_path.stat().st_mode & 0o222 == 0
    sidecar = json.loads(result.readiness_path.read_text(encoding="utf-8"))
    assert sidecar["format"] == "verified-readiness-attestation/v1"
    assert sidecar["signature"].startswith("ed25519:")
    assert result.readiness.require_valid(
        expected_snapshot_id=snapshot_id,
        verifier=ReadinessPublicKeyRegistry(
            {"configured-ready-test": readiness_key.public_key()}
        ),
    ) is result.readiness
    evidence = captured["_profile_coverage_evidence"]
    assert set(evidence) == set(binding.required_datasets)  # type: ignore[arg-type]
    assert all(
        row["signed_projection_document_digest"].startswith("sha256:")
        for row in evidence.values()  # type: ignore[union-attr]
    )


def test_ops_projection_environment_registry_cannot_self_root_ready(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    binding = load_exact_four_pilot_ready_binding()
    attacker_registry = tmp_path / "attacker-ops-registry.json"
    signed, _ = _signed_projection_evidence(
        binding.required_datasets,
        key_id="attacker-ops-projection",
        registry_path=attacker_registry,
    )
    monkeypatch.setenv(
        "QUANT_OPS_PROJECTION_VERIFY_REGISTRY", str(attacker_registry)
    )
    with pytest.raises(MassResearchDisabledError, match="issuer is not trusted"):
        _verified_production_projection_evidence(
            signed, binding.required_datasets
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
    _configure_projection_registry_for_test(monkeypatch, registry)
    with pytest.raises(MassResearchDisabledError, match="B0/B4"):
        publish_exact_four_pilot_ready_snapshot(
            tmp_path / "current.sqlite",
            tmp_path / "snapshots",
            signed_projection_document=signed,
        )


def test_signed_projection_rejects_signed_per_dataset_policy_drift(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        profile_module,
        "source_capability_contract_or_none",
        lambda _dataset_id: object(),
    )
    binding = load_exact_four_pilot_ready_binding()
    victim = binding.required_datasets[0]
    signed, registry = _signed_projection_evidence(
        binding.required_datasets,
        corrupt_policy_dataset=victim,
    )
    _configure_projection_registry_for_test(monkeypatch, registry)
    with pytest.raises(MassResearchDisabledError, match="governed policy binding"):
        publish_exact_four_pilot_ready_snapshot(
            tmp_path / "current.sqlite",
            tmp_path / "snapshots",
            signed_projection_document=signed,
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
    _configure_projection_registry_for_test(monkeypatch, registry)
    signed["envelope"]["applied_cursor"] = 8  # type: ignore[index]
    with pytest.raises(MassResearchDisabledError, match="signature is invalid"):
        publish_exact_four_pilot_ready_snapshot(
            tmp_path / "current.sqlite",
            tmp_path / "snapshots",
            signed_projection_document=signed,
        )


def test_tampered_signed_dependency_period_scope_is_rejected(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        profile_module,
        "source_capability_contract_or_none",
        lambda _dataset_id: object(),
    )
    binding = load_exact_four_pilot_ready_binding()
    signed, registry = _signed_projection_evidence(binding.required_datasets)
    _configure_projection_registry_for_test(monkeypatch, registry)
    signed["envelope"]["dataset_coverage"]["equities_master"][  # type: ignore[index]
        "observed_start"
    ] = "2026-08-25"
    with pytest.raises(MassResearchDisabledError, match="signature is invalid"):
        publish_exact_four_pilot_ready_snapshot(
            tmp_path / "current.sqlite",
            tmp_path / "snapshots",
            signed_projection_document=signed,
        )


def test_caller_owned_projection_registry_cannot_authorize_ready(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A correctly signed attacker envelope is not a production trust root."""
    monkeypatch.setattr(
        profile_module,
        "source_capability_contract_or_none",
        lambda _dataset_id: object(),
    )
    binding = load_exact_four_pilot_ready_binding()
    attacker_signed, _attacker_registry = _signed_projection_evidence(
        binding.required_datasets,
        key_id="caller-owned-ops-projection-key",
    )
    _trusted_signed, trusted_registry = _signed_projection_evidence(
        binding.required_datasets,
        key_id="configured-ops-projection-key",
    )
    _configure_projection_registry_for_test(monkeypatch, trusted_registry)

    with pytest.raises(MassResearchDisabledError, match="issuer is not trusted"):
        publish_exact_four_pilot_ready_snapshot(
            tmp_path / "current.sqlite",
            tmp_path / "snapshots",
            signed_projection_document=attacker_signed,
        )


def test_signed_projection_cursor_must_equal_local_snapshot_generation() -> None:
    binding = load_exact_four_pilot_ready_binding()
    policy_set = coverage_policy_set_binding(list(binding.required_datasets))
    signed_digest = canonical_digest({"signed": "projection"})
    profile_evidence = {}
    for dataset_id in binding.required_datasets:
        policy = coverage_policy_binding(dataset_id)
        profile_evidence[dataset_id] = {
            "status": "COMPLETE",
            "coverage_mode": official_mode(dataset_id),
            "projection_status": "FRESH",
            "policy_id": policy["policy_id"],
            "policy_version": policy["policy_version"],
            "policy_digest": policy["policy_digest"],
            "source_generation": "7",
            "export_cursor": "7",
            "applied_cursor": "7",
            "signed_projection_document_digest": signed_digest,
        }
    document = {
        "state": "READY",
        "snapshot_id": canonical_digest({"snapshot": "local"}),
        "change_seq": 8,
        "required_datasets": list(binding.required_datasets),
        "coverage_policy_version": policy_set["policy_version"],
        "coverage_policy_digest": policy_set["policy_digest"],
        "coverage_proof": {
            "proof_digest": canonical_digest({"coverage": "proof"}),
            "policy_version": policy_set["policy_version"],
            "policy_digest": policy_set["policy_digest"],
        },
        "profile_coverage_evidence": profile_evidence,
    }
    with pytest.raises(
        MassResearchDisabledError,
        match="signed Ops Projection applied cursor does not match",
    ):
        build_profile_bound_ready_manifest_from_snapshot_document(
            document,
            profile=binding,
        )


@pytest.mark.parametrize("victim", ("equities_master", "markets_calendar"))
def test_pit_dependency_scope_rejects_history_refetched_after_plan_as_of(
    tmp_path, victim: str,
) -> None:
    binding = load_exact_four_pilot_ready_binding()
    db_path = tmp_path / "pit-scope.sqlite"
    conn = sqlite3.connect(db_path)
    conn.execute(
        "CREATE TABLE jquants_records ("
        "dataset TEXT, event_time TEXT, available_at TEXT)"
    )
    pre_dates = [f"2022-12-{day:02d}" for day in range(12, 32)]
    for dataset_id in binding.required_datasets:
        for event_date in pre_dates:
            conn.execute(
                "INSERT INTO jquants_records VALUES (?,?,?)",
                (
                    dataset_id,
                    f"{event_date}T15:00:00+09:00",
                    f"{event_date}T16:00:00+09:00",
                ),
            )
        conn.execute(
            "INSERT INTO jquants_records VALUES (?,?,?)",
            (
                dataset_id,
                "2023-01-05T15:00:00+09:00",
                "2023-01-05T16:00:00+09:00",
            ),
        )
    conn.commit()
    conn.close()

    proof = _verify_exact_four_pit_dependency_scope(db_path, binding)
    assert proof["status"] == "PASS"
    assert proof["proof_digest"].startswith("sha256:")

    conn = sqlite3.connect(db_path)
    conn.execute(
        "UPDATE jquants_records SET available_at='2026-08-25T00:00:00+09:00' "
        "WHERE dataset=?",
        (victim,),
    )
    conn.commit()
    conn.close()
    with pytest.raises(MassResearchDisabledError, match="PIT dependency scope"):
        _verify_exact_four_pit_dependency_scope(db_path, binding)


def test_caller_controlled_pytest_environment_cannot_enable_fixture_ready(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PYTEST_CURRENT_TEST", "caller-controlled")
    with pytest.raises(TypeError, match="unexpected keyword argument"):
        _publish_ready_snapshot(
            tmp_path / "current.sqlite",
            tmp_path / "snapshots",
            required_datasets=("equities_bars_daily",),
            _fixture_policy=True,
        )  # type: ignore[call-arg]
