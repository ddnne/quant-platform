"""Production READY evidence is fail-closed; fixture compatibility stays private."""

from __future__ import annotations

import json
import sqlite3
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from data_contracts.coverage import (
    coverage_policy_binding,
    coverage_policy_set_binding,
)
from ingestion.jquants.normalize import normalize_generic
from ops.projection_content import (
    PROJECTED_CONTENT_TABLES,
    build_projection_content_manifest,
)
from ops.projection_signing import (
    ENVELOPE_SCHEMA,
    sha256_digest,
)
from paper_runtime.ready_policy import (
    CoverageEvidence,
    ReadyPublicationPolicy,
    SyncGenerationEvidence,
    collect_typed_evidence,
)
from paper_runtime.snapshot import SnapshotRejected, _publish_ready_snapshot
from paper_runtime.snapshot_publish_policy import _raw_manifests_for
import research.research_data_profile as profile_module
import research.ready_manifest as ready_module
from research.readiness import (
    ReadyPublicationAuthorityPending,
    ready_publication_authority_status,
)
from research.ready_manifest import (
    build_profile_bound_ready_manifest_from_snapshot_document,
    canonical_digest,
    load_exact_four_pilot_ready_binding,
    publish_exact_four_pilot_ready_snapshot,
    _verified_production_projection_evidence,
    _verify_exact_four_pit_dependency_scope,
)
from research.research_data_profile import load_core_profile, official_mode
from selection.budget_ledger import MassResearchDisabledError
from storage.coverage_ledger import (
    RequiredCoverageSegment,
    record_collection_receipt,
)
from storage.sqlite_store import SqliteStore
from tests.ops_projection_signing_support import (
    TestOpsProjectionSigningKey,
    TestOpsProjectionVerifier,
    make_test_ops_projection_verifier,
)
from tests.receipt_test_support import (
    TestSignedReceiptAuthority as _TestSignedReceiptAuthority,
    reconcile_test_evidence,
)


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
) -> tuple[dict[str, object], TestOpsProjectionVerifier]:
    private_key = Ed25519PrivateKey.generate()
    registry = make_test_ops_projection_verifier(private_key, key_id=key_id)
    if registry_path is not None:
        registry_path.write_text(
            json.dumps({"attacker_selected_key_id": key_id}), encoding="utf-8"
        )
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
    signed = TestOpsProjectionSigningKey(key_id, private_key).sign(envelope)
    return signed, registry


def _configure_projection_registry_for_test(
    monkeypatch: pytest.MonkeyPatch,
    registry: TestOpsProjectionVerifier,
) -> None:
    monkeypatch.setattr(
        "ops.projection_signing._load_pinned_active_keys",
        lambda: {registry.key_id: registry.public_key},
    )


def test_missing_production_ledgers_are_not_pass() -> None:
    conn = sqlite3.connect(":memory:")
    evidence = collect_typed_evidence(
        conn,
        ":memory:",
        ("equities_bars_daily",),
        run_id=1,
        coverage_proof_id="sha256:" + ("ab" * 32),
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


@pytest.mark.parametrize(
    ("missing_table", "evidence_type"),
    (
        ("raw_retention_manifests", "RawRetentionEvidence"),
        ("ingestion_validation", "ValidationEvidence"),
        ("natural_key_migrations", "NaturalKeyEvidence"),
        ("snapshot_quality_results", "QualityEvidence"),
        ("ingestion_change_log", "SyncGenerationEvidence"),
        ("sync_change_state", "SyncGenerationEvidence"),
    ),
)
def test_each_missing_production_ledger_fails_its_evidence(
    missing_table: str,
    evidence_type: str,
) -> None:
    conn = sqlite3.connect(":memory:")
    conn.executescript(
        """
        CREATE TABLE raw_retention_manifests (
            dataset TEXT, run_id INTEGER, completeness TEXT
        );
        INSERT INTO raw_retention_manifests
        VALUES ('equities_bars_daily', 1, 'COMPLETE');
        CREATE TABLE ingestion_validation (
            run_id INTEGER, dataset TEXT, status TEXT
        );
        INSERT INTO ingestion_validation
        VALUES (1, 'equities_bars_daily', 'PASS');
        CREATE TABLE natural_key_migrations (state TEXT);
        INSERT INTO natural_key_migrations VALUES ('READY');
        CREATE TABLE snapshot_quality_results (
            build_id TEXT, status TEXT, results_json TEXT
        );
        INSERT INTO snapshot_quality_results VALUES (
            'build-1', 'PASS',
            '[{"check_id":"B0","status":"pass"},{"check_id":"B4","status":"pass"}]'
        );
        CREATE TABLE ingestion_change_log (change_seq INTEGER);
        INSERT INTO ingestion_change_log VALUES (7);
        CREATE TABLE sync_change_state (
            feed TEXT PRIMARY KEY,
            last_applied_change_seq INTEGER
        );
        INSERT INTO sync_change_state VALUES ('jquants_records', 7);
        """
    )
    conn.execute(f"DROP TABLE {missing_table}")

    evidence = collect_typed_evidence(
        conn,
        ":memory:",
        ("equities_bars_daily",),
        run_id=1,
        build_id="build-1",
        coverage_proof_id="sha256:" + ("ab" * 32),
    )
    by_type = {type(item).__name__: item.to_item() for item in evidence}

    assert by_type[evidence_type].passed is False


@pytest.mark.parametrize(
    "validation_rows",
    (
        ((1, "unrelated", "PASS"),),
        (
            (1, "equities_bars_daily", "PASS"),
            (1, "equities_bars_daily", "PASS"),
        ),
        ((1, "equities_bars_daily", "FAIL"),),
        ((2, "equities_bars_daily", "PASS"),),
    ),
)
def test_validation_requires_one_exact_passing_row_per_required_dataset(
    validation_rows: tuple[tuple[int, str, str], ...],
) -> None:
    conn = sqlite3.connect(":memory:")
    conn.execute(
        "CREATE TABLE ingestion_validation "
        "(run_id INTEGER, dataset TEXT, status TEXT)"
    )
    conn.executemany(
        "INSERT INTO ingestion_validation VALUES (?,?,?)",
        validation_rows,
    )

    evidence = collect_typed_evidence(
        conn,
        ":memory:",
        ("equities_bars_daily",),
        run_id=1,
        coverage_proof_id="sha256:" + ("ab" * 32),
    )
    validation = next(
        item for item in evidence if type(item).__name__ == "ValidationEvidence"
    )

    assert validation.to_item().passed is False


@pytest.mark.parametrize(
    "quality_rows",
    (
        (),
        (("other-build", "PASS", '[{"check_id":"B0","status":"pass"},'
          ' {"check_id":"B4","status":"pass"}]'),),
        (
            ("build-1", "PASS", '[{"check_id":"B0","status":"pass"},'
             ' {"check_id":"B4","status":"pass"}]'),
            ("build-1", "FAIL", '[{"check_id":"B0","status":"pass"},'
             ' {"check_id":"B4","status":"pass"}]'),
        ),
        (("build-1", "PASS", '[{"check_id":"B4","status":"pass"}]'),),
        (("build-1", "PASS", '[{"check_id":"B0","status":"pass"}]'),),
        (("build-1", "PASS", '[{"check_id":"B0","status":"fail"},'
          ' {"check_id":"B4","status":"pass"}]'),),
        (("build-1", "PASS", '[{"check_id":"B0","status":"pass"},'
          ' {"check_id":"B4","status":"fail"}]'),),
    ),
)
def test_quality_requires_one_exact_build_with_passing_b0_and_b4(
    quality_rows: tuple[tuple[str, str, str], ...],
) -> None:
    conn = sqlite3.connect(":memory:")
    conn.execute(
        "CREATE TABLE snapshot_quality_results "
        "(build_id TEXT, status TEXT, results_json TEXT)"
    )
    conn.executemany(
        "INSERT INTO snapshot_quality_results VALUES (?,?,?)",
        quality_rows,
    )

    evidence = collect_typed_evidence(
        conn,
        ":memory:",
        ("equities_bars_daily",),
        build_id="build-1",
        coverage_proof_id="sha256:" + ("ab" * 32),
    )
    quality = next(
        item for item in evidence if type(item).__name__ == "QualityEvidence"
    )

    assert quality.to_item().passed is False


def test_raw_retention_rejects_duplicate_required_rows() -> None:
    conn = sqlite3.connect(":memory:")
    conn.execute(
        "CREATE TABLE raw_retention_manifests "
        "(dataset TEXT, run_id INTEGER, completeness TEXT)"
    )
    conn.executemany(
        "INSERT INTO raw_retention_manifests VALUES (?,?,?)",
        (
            ("equities_bars_daily", 1, "COMPLETE"),
            ("equities_bars_daily", 1, "COMPLETE"),
        ),
    )

    evidence = collect_typed_evidence(
        conn,
        ":memory:",
        ("equities_bars_daily",),
        run_id=1,
        coverage_proof_id="sha256:" + ("ab" * 32),
    )
    raw = next(
        item for item in evidence if type(item).__name__ == "RawRetentionEvidence"
    )

    assert raw.to_item().passed is False


@pytest.mark.parametrize(
    ("raw_status", "expected_pass"),
    (("ACQUIRED", True), ("COMPLETE", True), ("FAILED", False)),
)
def test_raw_retention_uses_raw_plane_acquisition_semantics(
    raw_status: str,
    expected_pass: bool,
) -> None:
    conn = sqlite3.connect(":memory:")
    conn.execute(
        "CREATE TABLE raw_retention_manifests "
        "(dataset TEXT, run_id INTEGER, completeness TEXT)"
    )
    conn.execute(
        "INSERT INTO raw_retention_manifests VALUES (?,?,?)",
        ("equities_bars_daily", 1, raw_status),
    )

    evidence = collect_typed_evidence(
        conn,
        ":memory:",
        ("equities_bars_daily",),
        run_id=1,
        coverage_proof_id="sha256:" + ("ab" * 32),
    )
    raw = next(
        item for item in evidence if type(item).__name__ == "RawRetentionEvidence"
    )

    assert raw.to_item().passed is expected_pass


@pytest.mark.parametrize(
    ("raw_status", "expected_pass"),
    (("ACQUIRED", True), ("COMPLETE", True), ("FAILED", False)),
)
def test_publication_raw_gate_uses_raw_plane_acquisition_semantics(
    raw_status: str,
    expected_pass: bool,
) -> None:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute(
        "CREATE TABLE raw_retention_manifests ("
        "dataset TEXT, run_id INTEGER, manifest_key TEXT, page_count INTEGER, "
        "row_count INTEGER, raw_bytes INTEGER, data_digest TEXT, "
        "completeness TEXT, created_at TEXT)"
    )
    conn.execute(
        "INSERT INTO raw_retention_manifests VALUES (?,?,?,?,?,?,?,?,?)",
        (
            "equities_bars_daily",
            1,
            "raw/manifest.json",
            1,
            1,
            1,
            "sha256:" + ("ab" * 32),
            raw_status,
            "2026-08-26T00:00:00Z",
        ),
    )

    if expected_pass:
        manifests = _raw_manifests_for(
            conn,
            1,
            ("equities_bars_daily",),
        )
        assert manifests["equities_bars_daily"]["completeness"] == raw_status
    else:
        with pytest.raises(SnapshotRejected, match="raw retention incomplete"):
            _raw_manifests_for(conn, 1, ("equities_bars_daily",))


@pytest.mark.parametrize(
    "coverage_proof_id",
    (
        None,
        "",
        "UNKNOWN",
        "sha256:" + ("AB" * 32),
        "sha256:" + ("ab" * 32),
    ),
)
def test_coverage_evidence_rejects_missing_arbitrary_or_unknown_proof_ids(
    coverage_proof_id,
) -> None:
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE dataset_coverage(dataset TEXT, status TEXT)")
    conn.execute(
        "INSERT INTO dataset_coverage VALUES (?, 'COMPLETE')",
        ("equities_bars_daily",),
    )
    evidence = collect_typed_evidence(
        conn,
        ":memory:",
        ("equities_bars_daily",),
        coverage_proof_id=coverage_proof_id,
    )
    coverage = next(item for item in evidence if isinstance(item, CoverageEvidence))

    assert coverage.to_item().passed is False


def test_coverage_evidence_cannot_be_directly_forged_into_pass() -> None:
    conn = sqlite3.connect(":memory:")
    forged = CoverageEvidence(
        conn,
        ("equities_bars_daily",),
        "sha256:" + ("ab" * 32),
    )
    assert forged.to_item().passed is False
    with pytest.raises(TypeError, match="unexpected keyword argument"):
        CoverageEvidence(  # type: ignore[call-arg]
            governed_complete=1,
            governed_total=1,
            status="COMPLETE",
            proof_digest="sha256:" + ("ab" * 32),
        )


def test_old_proof_dict_and_typed_evidence_injection_kwargs_are_removed() -> None:
    conn = sqlite3.connect(":memory:")
    with pytest.raises(TypeError, match="coverage_proof"):
        collect_typed_evidence(  # type: ignore[call-arg]
            conn,
            ":memory:",
            ("equities_bars_daily",),
            coverage_proof={"status": "COMPLETE"},
        )
    with pytest.raises(TypeError, match="typed_evidence"):
        ReadyPublicationPolicy().evaluate(  # type: ignore[call-arg]
            conn,
            ":memory:",
            ("equities_bars_daily",),
            coverage_proof_id="sha256:" + ("ab" * 32),
            typed_evidence=[object()],
        )
    with pytest.raises(TypeError, match="fixture_compatibility"):
        collect_typed_evidence(  # type: ignore[call-arg]
            conn,
            ":memory:",
            ("equities_bars_daily",),
            coverage_proof_id="sha256:" + ("ab" * 32),
            fixture_compatibility=True,
        )
    for removed_override in ("raw_manifest_ok", "quality_status"):
        with pytest.raises(TypeError, match=removed_override):
            collect_typed_evidence(  # type: ignore[call-arg]
                conn,
                ":memory:",
                ("equities_bars_daily",),
                coverage_proof_id="sha256:" + ("ab" * 32),
                **{removed_override: True if removed_override == "raw_manifest_ok" else "PASS"},
            )


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
    import paper_runtime.snapshot as snapshot_module
    import research.ready_manifest as ready_module

    assert not hasattr(paper_runtime, "publish_ready_snapshot")
    assert not hasattr(paper_runtime, "commit_snapshot_manifest")
    assert not hasattr(snapshot_module, "commit_snapshot_manifest")
    assert not hasattr(ready_module, "publish_profile_bound_ready_snapshot")
    with pytest.raises(TypeError, match="unexpected keyword argument"):
        publish_exact_four_pilot_ready_snapshot(
            "current.sqlite",
            "snapshots",
            signed_projection_document={},
            **{unsafe_keyword: object()},
        )


def test_unprovisioned_ready_authority_is_pending_before_local_mutation(
    tmp_path,
) -> None:
    staging = tmp_path / "current.sqlite"
    staging.write_bytes(b"caller-owned-current-db")
    before = staging.read_bytes()
    snapshots = tmp_path / "snapshots"

    status = ready_publication_authority_status()
    assert status.state == "PENDING"
    assert status.evidence_state == "UNKNOWN"
    assert status.required_checks == (
        "authenticated_immutable_ops_mirror",
        "canonical_exact_four_plan_closure_profile",
        "trusted_coverage_proof",
        "b0_b4_pass",
        "source_export_applied_generation_coherence",
        "independently_reopened_immutable_snapshot_copy",
    )
    with pytest.raises(ReadyPublicationAuthorityPending, match="PENDING"):
        publish_exact_four_pilot_ready_snapshot(
            staging,
            snapshots,
            signed_projection_document={"caller": "cannot become authority"},
        )
    assert staging.read_bytes() == before
    assert not snapshots.exists()


def test_signed_projection_verifier_derives_only_exact_closure_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    binding = load_exact_four_pilot_ready_binding()
    signed, registry = _signed_projection_evidence(
        (*binding.required_datasets, "markets_margin_alert")
    )
    _configure_projection_registry_for_test(monkeypatch, registry)
    evidence = _verified_production_projection_evidence(
        signed, binding.required_datasets
    )
    assert set(evidence) == set(binding.required_datasets)
    assert all(
        row["signed_projection_document_digest"].startswith("sha256:")
        and row["signed_projection_issuer_key_id"]
        == "ops-projection-ready-test"
        and row["source_generation"] == row["export_cursor"]
        and row["export_cursor"] == row["applied_cursor"]
        and type(row) is dict
        for row in evidence.values()
    )


def test_ready_uses_verified_projection_identity_after_caller_mutation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    binding = load_exact_four_pilot_ready_binding()
    signed, registry = _signed_projection_evidence(binding.required_datasets)
    _configure_projection_registry_for_test(monkeypatch, registry)
    expected_digest = sha256_digest(signed)
    expected_issuer = signed["issuer_key_id"]
    observed_now = ready_module._now()

    def mutate_after_verification() -> datetime:
        signed["issuer_key_id"] = "unsigned-B-issuer"
        signed["envelope"][  # type: ignore[index]
            "generation_id"
        ] = "unsigned-B-generation"
        return observed_now

    monkeypatch.setattr(ready_module, "_now", mutate_after_verification)
    evidence = _verified_production_projection_evidence(
        signed, binding.required_datasets
    )

    assert signed["issuer_key_id"] == "unsigned-B-issuer"
    assert all(
        row["signed_projection_document_digest"] == expected_digest
        and row["signed_projection_issuer_key_id"] == expected_issuer
        and row["projection_generation"] == "projection-generation-7"
        for row in evidence.values()
    )


def test_ready_freshness_is_checked_after_policy_postconditions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from ops.projection_meta import DEFAULT_MAX_AGE_SECONDS
    import data_contracts.coverage as coverage_module

    binding = load_exact_four_pilot_ready_binding()
    signed, registry = _signed_projection_evidence(binding.required_datasets)
    _configure_projection_registry_for_test(monkeypatch, registry)
    generated_at = datetime.fromisoformat(
        signed["envelope"]["generated_at"]  # type: ignore[index]
    )
    clock = {
        "now": generated_at + timedelta(seconds=DEFAULT_MAX_AGE_SECONDS)
    }
    governed_binding = coverage_module.coverage_policy_binding

    def advance_during_postconditions(dataset_id: str):
        result = governed_binding(dataset_id)
        clock["now"] += timedelta(seconds=1)
        return result

    monkeypatch.setattr(
        coverage_module,
        "coverage_policy_binding",
        advance_during_postconditions,
    )
    monkeypatch.setattr(ready_module, "_now", lambda: clock["now"])

    with pytest.raises(MassResearchDisabledError, match="freshness SLA"):
        _verified_production_projection_evidence(
            signed, binding.required_datasets
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
        _verified_production_projection_evidence(
            signed, binding.required_datasets
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
        _verified_production_projection_evidence(
            signed, binding.required_datasets
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
        _verified_production_projection_evidence(
            signed, binding.required_datasets
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
        _verified_production_projection_evidence(
            signed, binding.required_datasets
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
        _verified_production_projection_evidence(
            attacker_signed, binding.required_datasets
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
        "coverage_proof_id": canonical_digest({"coverage": "record"}),
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


_SCOPE_DATASETS = (
    "equities_bars_daily",
    "equities_master",
    "fins_summary",
    "indices_bars_daily_topix",
    "markets_calendar",
)


def _mini_exact_scope_binding() -> SimpleNamespace:
    scope = {"required_lookback_trading_days": 2}
    profile = SimpleNamespace(
        period_start="2023-01-04",
        period_end="2023-01-06",
        dataset_scopes=tuple(scope for _ in _SCOPE_DATASETS),
    )
    return SimpleNamespace(
        profiles=(profile,),
        required_datasets=_SCOPE_DATASETS,
        profile_digest=canonical_digest({"profile": "mini-exact-four"}),
        plan_set_digest=canonical_digest({"plans": "mini-exact-four"}),
        closure_set_digest=canonical_digest({"closure": "mini-exact-four"}),
    )


def _seed_exact_pit_scope(
    tmp_path,
    receipt_ed25519_keys,
) -> tuple[object, object]:
    """Five-day exact natural-key closure with governed v4 receipts."""
    db_path = tmp_path / "pit-scope.sqlite"
    calendar_dates: list[str] = []
    cursor = date(2023, 1, 2)
    while cursor <= date(2023, 1, 6):
        calendar_dates.append(cursor.isoformat())
        cursor += timedelta(days=1)
    payloads: dict[str, list[dict[str, object]]] = {
        "markets_calendar": [
            {"Date": day, "HolidayDivision": "1"}
            for day in calendar_dates
        ],
        "equities_master": [
            {
                "Code": "1332",
                "Date": "2023-01-02",
                "CompanyName": "Prime With Fins",
                "MarketCode": "0111",
            }
        ],
        "fins_summary": [
            {
                "Code": "1332",
                "DiscDate": "2023-01-03",
                "DiscTime": "08:00:00",
                "DiscNo": "disc-1332",
            }
        ],
        "equities_bars_daily": [
            {
                "Code": "1332",
                "Date": day,
                "Open": 100.0,
                "High": 101.0,
                "Low": 99.0,
                "Close": 100.0,
                "Volume": 1000.0,
            }
            for day in calendar_dates
        ],
        "indices_bars_daily_topix": [
            {
                "Date": day,
                "Open": 1900.0,
                "High": 1910.0,
                "Low": 1890.0,
                "Close": 1900.0,
            }
            for day in calendar_dates
        ],
    }
    ingestion_clocks = {
        "markets_calendar": "2022-12-01T00:00:00+09:00",
        "equities_master": "2023-01-02T08:00:00+09:00",
        "fins_summary": "2023-01-03T08:00:00+09:00",
        "equities_bars_daily": "2023-01-06T16:00:00+09:00",
        "indices_bars_daily_topix": "2023-01-06T16:00:00+09:00",
    }
    with SqliteStore(db_path) as store:
        for dataset_id in _SCOPE_DATASETS:
            store.upsert(
                "jquants_records",
                normalize_generic(
                    payloads[dataset_id],
                    dataset=dataset_id,
                    ingested_at=ingestion_clocks[dataset_id],
                ),
            )
        authority = _TestSignedReceiptAuthority(
            signing_key=receipt_ed25519_keys.signing_key
        )
        for run_id, dataset_id in enumerate(_SCOPE_DATASETS, start=1):
            structured = [
                dict(row)
                for row in store._conn.execute(  # noqa: SLF001
                    "SELECT * FROM jquants_records "
                    "WHERE source='jquants' AND dataset=? "
                    "ORDER BY natural_key",
                    (dataset_id,),
                ).fetchall()
            ]
            required = RequiredCoverageSegment(
                source="jquants",
                dataset=dataset_id,
                segment_id=f"mini-scope-{dataset_id}",
                segment_start="2023-01-02",
                segment_end="2023-01-06",
                expected_scope={
                    "period_start": "2023-01-02",
                    "period_end": "2023-01-06",
                    "expected_item_unit": "source_event",
                },
                expected_items=len(structured),
            )
            evidence = reconcile_test_evidence(
                required=required,
                run_id=run_id,
                raw_pages=[
                    json.dumps(
                        {"data": payloads[dataset_id]},
                        sort_keys=True,
                    ).encode("utf-8")
                ],
                raw_records=payloads[dataset_id],
                structured_records=structured,
                checked_at="2026-08-25T00:00:00+00:00",
                source_request={"fixture": "exact-pit-scope"},
            )
            record_collection_receipt(store._conn, authority.issue(evidence))  # noqa: SLF001
        store._conn.commit()  # noqa: SLF001
    return db_path, _mini_exact_scope_binding()


def test_exact_pit_dependency_scope_accepts_complete_receipt_bound_fixture(
    tmp_path,
    receipt_ed25519_keys,
) -> None:
    db_path, binding = _seed_exact_pit_scope(
        tmp_path, receipt_ed25519_keys
    )
    proof = _verify_exact_four_pit_dependency_scope(db_path, binding)
    assert proof["status"] == "PASS"
    assert proof["period_start"] == "2023-01-04"
    assert proof["period_end"] == "2023-01-06"
    assert proof["lookback_trading_days"] == 2
    assert {row["dataset_id"] for row in proof["entries"]} == set(
        _SCOPE_DATASETS
    )
    assert all(row["receipt_digests"] for row in proof["entries"])


@pytest.mark.parametrize(
    ("victim", "event_date"),
    (
        ("markets_calendar", "2023-01-05"),
        ("equities_master", "2023-01-02"),
        ("fins_summary", "2023-01-03"),
        ("equities_bars_daily", "2023-01-05"),
        ("indices_bars_daily_topix", "2023-01-05"),
    ),
)
def test_exact_pit_dependency_scope_rejects_each_missing_or_late_dependency(
    tmp_path,
    receipt_ed25519_keys,
    victim: str,
    event_date: str,
) -> None:
    db_path, binding = _seed_exact_pit_scope(
        tmp_path, receipt_ed25519_keys
    )
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "UPDATE jquants_records "
            "SET available_at='2026-08-25T00:00:00+09:00' "
            "WHERE dataset=? AND substr(event_time,1,10)=?",
            (victim, event_date),
        )
    with pytest.raises(MassResearchDisabledError):
        _verify_exact_four_pit_dependency_scope(db_path, binding)


def test_exact_pit_dependency_scope_rejects_one_visible_row_and_late_rest(
    tmp_path,
    receipt_ed25519_keys,
) -> None:
    db_path, binding = _seed_exact_pit_scope(
        tmp_path, receipt_ed25519_keys
    )
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "UPDATE jquants_records "
            "SET available_at='2026-08-25T00:00:00+09:00' "
            "WHERE dataset='equities_bars_daily' "
            "AND substr(event_time,1,10) <> '2023-01-02'"
        )
    with pytest.raises(MassResearchDisabledError, match="closure missing/late"):
        _verify_exact_four_pit_dependency_scope(db_path, binding)


def test_exact_pit_dependency_scope_rejects_unreceipted_natural_keys(
    tmp_path,
    receipt_ed25519_keys,
) -> None:
    db_path, binding = _seed_exact_pit_scope(
        tmp_path, receipt_ed25519_keys
    )
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "DELETE FROM collection_receipts "
            "WHERE dataset='indices_bars_daily_topix'"
        )
    with pytest.raises(MassResearchDisabledError, match="signed receipt"):
        _verify_exact_four_pit_dependency_scope(db_path, binding)


def test_exact_pit_dependency_scope_rejects_noncanonical_natural_key(
    tmp_path,
    receipt_ed25519_keys,
) -> None:
    db_path, binding = _seed_exact_pit_scope(
        tmp_path, receipt_ed25519_keys
    )
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "UPDATE jquants_records SET natural_key='caller-supplied' "
            "WHERE dataset='equities_bars_daily' "
            "AND substr(event_time,1,10)='2023-01-05'"
        )
    with pytest.raises(MassResearchDisabledError, match="natural key"):
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
