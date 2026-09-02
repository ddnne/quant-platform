"""Production READY evidence is fail-closed; fixture compatibility stays private."""

from __future__ import annotations

import json
import sqlite3
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from types import MappingProxyType, SimpleNamespace

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from data_contracts.coverage import (
    all_coverage_contracts,
    coverage_policy_binding,
    coverage_policy_set_binding,
)
from ingestion.jquants.normalize import normalize_generic
from ops.projection_content import (
    PROJECTED_CONTENT_TABLES,
    build_projection_content_manifest,
)
from ops.receipt_product import (
    canonical_product_artifact_bytes,
    product_artifact_digest,
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
    _verified_projection_evidence,
    _verified_production_projection_evidence,
    _verify_exact_four_pit_dependency_scope,
)
from research.research_data_profile import load_core_profile, official_mode
from selection.budget_ledger import MassResearchDisabledError
from scripts import sync_d1_to_sqlite as sync_script
from storage.coverage_ledger import (
    RequiredCoverageSegment,
    record_collection_receipt,
)
from storage.sqlite_store import SqliteStore
from tests.ops_projection_signing_support import (
    TestOpsProjectionSigningKey,
    TestOpsProjectionVerifier,
    make_test_ops_projection_verifier,
    render_projection_bundle_for_test,
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
        lambda _environment="production": {registry.key_id: registry.public_key},
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
    assert set(evidence.rows) == set(binding.required_datasets)
    assert isinstance(evidence.rows, MappingProxyType)
    assert all(
        row["signed_projection_document_digest"].startswith("sha256:")
        and row["signed_projection_issuer_key_id"]
        == "ops-projection-ready-test"
        and row["source_generation"] == row["export_cursor"]
        and row["export_cursor"] == row["applied_cursor"]
        and isinstance(row, MappingProxyType)
        for row in evidence.rows.values()
    )
    with pytest.raises(TypeError):
        evidence.rows[binding.required_datasets[0]] = {}  # type: ignore[index]


def test_ready_projection_verifier_requires_the_authority_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    binding = load_exact_four_pilot_ready_binding()
    signed, registry = _signed_projection_evidence(binding.required_datasets)
    _configure_projection_registry_for_test(monkeypatch, registry)

    production = _verified_projection_evidence(
        signed,
        binding.required_datasets,
        expected_environment="production",
    )
    assert set(production.rows) == set(binding.required_datasets)
    with pytest.raises(MassResearchDisabledError, match="environment mismatch"):
        _verified_projection_evidence(
            signed,
            binding.required_datasets,
            expected_environment="staging",
        )


def test_verified_projection_result_is_opaque_final_and_alias_free(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    binding = load_exact_four_pilot_ready_binding()
    signed, registry = _signed_projection_evidence(binding.required_datasets)
    _configure_projection_registry_for_test(monkeypatch, registry)
    evidence_type = ready_module._VerifiedProductionProjectionEvidence

    with pytest.raises(RuntimeError, match="no public constructor"):
        evidence_type()
    with pytest.raises(TypeError, match="is final"):
        class ForgedEvidence(evidence_type):
            pass

    forged = object.__new__(evidence_type)
    with pytest.raises(RuntimeError, match="not verifier-minted"):
        _ = forged.rows

    evidence = _verified_production_projection_evidence(
        signed, binding.required_datasets
    )
    victim = binding.required_datasets[0]
    expected_status = evidence.rows[victim]["status"]
    signed["envelope"]["dataset_coverage"][victim]["status"] = "PARTIAL"  # type: ignore[index]

    assert evidence.rows[victim]["status"] == expected_status == "COMPLETE"
    with pytest.raises(AttributeError, match="immutable"):
        evidence.rows = {}  # type: ignore[misc]
    with pytest.raises(AttributeError):
        object.__setattr__(evidence, "_rows", {})


def test_ready_rejects_dataset_identifier_coercion_and_container_subclasses(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    binding = load_exact_four_pilot_ready_binding()
    signed, registry = _signed_projection_evidence(binding.required_datasets)
    _configure_projection_registry_for_test(monkeypatch, registry)

    class DatasetId(str):
        pass

    class DatasetList(list):
        pass

    with pytest.raises(MassResearchDisabledError, match="exact unique"):
        _verified_production_projection_evidence(
            signed,
            [DatasetId(binding.required_datasets[0]), *binding.required_datasets[1:]],
        )
    with pytest.raises(MassResearchDisabledError, match="exact unique"):
        _verified_production_projection_evidence(
            signed, DatasetList(binding.required_datasets)
        )


@pytest.mark.parametrize(
    ("attack", "message"),
    [(None, None), ("duplicate", "duplicate key"), ("nonfinite", "non-finite")],
)
def test_pilot_evidence_file_uses_real_strict_ops_decoder(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
    attack: str | None,
    message: str | None,
) -> None:
    binding = load_exact_four_pilot_ready_binding()
    signed, registry = _signed_projection_evidence(binding.required_datasets)
    _configure_projection_registry_for_test(monkeypatch, registry)
    raw = json.dumps(signed, separators=(",", ":"))
    if attack == "duplicate":
        raw = raw.replace(
            "{",
            '{"schema_version":"attacker",',
            1,
        )
    elif attack == "nonfinite":
        raw = raw.replace(
            '"schema_version"',
            '"unsigned_probe":NaN,"schema_version"',
            1,
        )
    evidence_path = tmp_path / f"pilot-{attack or 'valid'}.json"
    evidence_path.write_text(raw, encoding="utf-8")
    observed: list[object] = []

    def verify_then_publish(
        _db, _snapshot_dir, *, signed_projection_document
    ):
        observed.append(signed_projection_document)
        verified = _verified_production_projection_evidence(
            signed_projection_document, binding.required_datasets
        )
        assert isinstance(verified.rows, MappingProxyType)
        return SimpleNamespace(snapshot_id="strict-file-test")

    monkeypatch.setattr(
        ready_module,
        "publish_exact_four_pilot_ready_snapshot",
        verify_then_publish,
    )
    store = SqliteStore(tmp_path / f"pilot-{attack or 'valid'}.sqlite")
    failures: list[str] = []
    args = SimpleNamespace(
        table=[],
        pilot_ready_evidence=str(evidence_path),
        snapshot_dir=str(tmp_path / "snapshots"),
        db=str(tmp_path / "mirror.sqlite"),
    )
    try:
        sync_script._finalize_sync_policy(
            store, args, failures, source_mode="WRANGLER_REMOTE"
        )
    finally:
        store.close()

    assert len(observed) == 1
    assert type(observed[0]) is bytes
    if message is None:
        assert failures == []
    else:
        assert len(failures) == 1
        assert message in failures[0]


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
    assert evidence.signed_document_digest == expected_digest
    assert evidence.issuer_key_id == expected_issuer
    assert all(
        row["signed_projection_document_digest"] == expected_digest
        and row["signed_projection_issuer_key_id"] == expected_issuer
        and row["projection_generation"] == "projection-generation-7"
        for row in evidence.rows.values()
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
    "equities_bars_daily_am",
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
    binding = SimpleNamespace(
        profiles=(profile,),
        required_datasets=_SCOPE_DATASETS,
        profile_id="mini-exact-four-v1",
        profile_version="1",
        profile_digest=canonical_digest({"profile": "mini-exact-four"}),
        plan_ids=("mini-plan-1", "mini-plan-2", "mini-plan-3", "mini-plan-4"),
        plan_set_digest=canonical_digest({"plans": "mini-exact-four"}),
        closure_set_digest=canonical_digest({"closure": "mini-exact-four"}),
        publication_scope="PILOT",
        feature_dependencies=(),
        contract_versions={},
    )
    binding.to_dict = lambda: {
        "feature_dependencies": [],
        "contract_versions": {},
    }
    return binding


def _seed_exact_pit_scope(
    tmp_path,
    receipt_ed25519_keys,
) -> tuple[object, object]:
    """Synthetic five-day exact natural-key closure with governed v4 receipts."""
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
        "equities_bars_daily_am": [
            {
                "Code": "1332",
                "Date": day,
                "MAdjC": 100.0,
                "trusted_receipt_digest": "sha256:" + ("ab" * 32),
                "product_snapshot_id": "sha256:" + ("cd" * 32),
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
        "equities_bars_daily_am": "2023-01-06T11:30:00+09:00",
        "indices_bars_daily_topix": "2023-01-06T16:00:00+09:00",
    }
    with SqliteStore(db_path) as store:
        store._conn.execute(  # noqa: SLF001
            "ALTER TABLE ingestion_run_log ADD COLUMN authority_operation_id TEXT"
        )
        store._conn.execute(  # noqa: SLF001
            "CREATE TABLE IF NOT EXISTS snapshot_observation_clock "
            "(observed_through TEXT NOT NULL)"
        )
        store._conn.execute(  # noqa: SLF001
            "INSERT INTO snapshot_observation_clock VALUES ('2023-01-06T11:30:00+09:00')"
        )
        store._conn.executescript(  # noqa: SLF001
            """
            CREATE TABLE ingestion_change_log (
                change_seq INTEGER PRIMARY KEY AUTOINCREMENT,
                table_name TEXT NOT NULL,
                source TEXT NOT NULL,
                dataset TEXT NOT NULL,
                natural_key TEXT NOT NULL,
                event_time TEXT NOT NULL,
                available_at TEXT NOT NULL,
                ingested_at TEXT NOT NULL,
                payload TEXT NOT NULL,
                raw_payload TEXT,
                changed_at TEXT NOT NULL
            );
            CREATE UNIQUE INDEX ux_ingestion_change_log_version
                ON ingestion_change_log
                   (table_name,source,dataset,natural_key,available_at,
                    ingested_at,payload);
            """
        )
        for dataset_id in _SCOPE_DATASETS:
            rows = payloads[dataset_id]
            if dataset_id == "equities_bars_daily_am":
                for row in rows:
                    day = str(row["Date"])
                    store.upsert(
                        "jquants_records",
                        normalize_generic(
                            [row],
                            dataset=dataset_id,
                            ingested_at=f"{day}T11:30:00+09:00",
                        ),
                    )
            else:
                store.upsert(
                    "jquants_records",
                    normalize_generic(
                        rows,
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
            artifact_body = canonical_product_artifact_bytes(structured).decode(
                "utf-8"
            )
            artifact_digest = product_artifact_digest(structured)
            operation_id = canonical_digest(
                {"operation": "exact-pit-scope", "dataset": dataset_id}
            )
            checked_at = "2026-08-25T00:00:00+00:00"
            store._conn.executemany(  # noqa: SLF001
                "INSERT OR IGNORE INTO ingestion_change_log "
                "(table_name,source,dataset,natural_key,event_time,available_at,"
                "ingested_at,payload,raw_payload,changed_at) "
                "VALUES ('jquants_records',?,?,?,?,?,?,?,?,?)",
                [
                    (
                        row["source"],
                        row["dataset"],
                        row["natural_key"],
                        row["event_time"],
                        row["available_at"],
                        row["ingested_at"],
                        row["payload"],
                        row["raw_payload"],
                        row["ingested_at"],
                    )
                    for row in structured
                ],
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
                checked_at=checked_at,
                source_request={"fixture": "exact-pit-scope"},
                structured_digest=artifact_digest,
            )
            record_collection_receipt(store._conn, authority.issue(evidence))  # noqa: SLF001
            raw_manifest_digest = str(evidence.claims["raw_manifest_digest"])
            raw_body = json.dumps(
                {"data": payloads[dataset_id]}, sort_keys=True
            ).encode("utf-8")
            store._conn.execute(  # noqa: SLF001
                "INSERT INTO ingestion_run_log "
                "(id,ran_at,source,runtime,status,detail,authority_operation_id) "
                "VALUES (?,?,'jquants','receipt-evidence-authority','SUCCESS','{}',?)",
                (run_id, checked_at, operation_id),
            )
            store._conn.execute(  # noqa: SLF001
                "INSERT INTO raw_retention_manifests "
                "(dataset,run_id,manifest_key,page_count,row_count,raw_bytes,"
                "data_digest,completeness,created_at) "
                "VALUES (?,?,?,?,?,?,?,'COMPLETE',?)",
                (
                    dataset_id,
                    run_id,
                    f"raw/{dataset_id}/{run_id}.manifest.json",
                    1,
                    len(payloads[dataset_id]),
                    len(raw_body),
                    raw_manifest_digest,
                    checked_at,
                ),
            )
            store._conn.execute(  # noqa: SLF001
                "INSERT INTO receipt_product_materializations "
                "(operation_id,run_id,source,dataset,segment_id,artifact_key,"
                "artifact_digest,artifact_body,row_count,byte_count,manifest_key,"
                "manifest_digest,raw_manifest_key,raw_manifest_digest,"
                "raw_page_count,raw_row_count,raw_bytes,committed_at) "
                "VALUES (?,?,'jquants',?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    operation_id,
                    run_id,
                    dataset_id,
                    required.segment_id,
                    f"structured/{dataset_id}/{run_id}.jsonl",
                    artifact_digest,
                    artifact_body,
                    len(structured),
                    len(artifact_body.encode("utf-8")),
                    f"structured/{dataset_id}/{run_id}.manifest.json",
                    canonical_digest({"artifact_digest": artifact_digest}),
                    f"raw/{dataset_id}/{run_id}.manifest.json",
                    raw_manifest_digest,
                    1,
                    len(payloads[dataset_id]),
                    len(raw_body),
                    checked_at,
                ),
            )
        store._conn.commit()  # noqa: SLF001
    return db_path, _mini_exact_scope_binding()


AUTHENTICATED_EXPORT_AT = "2026-08-25T12:00:00+00:00"


def authenticate_applied_mirror(
    path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    exported_at: str = AUTHENTICATED_EXPORT_AT,
) -> str:
    """Seal one existing SQLite file as the current authenticated applied mirror."""
    from ops import d1_sync_signing as signing
    from scripts import sync_d1_to_sqlite as sync
    from storage.sqlite_store import SqliteStore
    from tests.test_d1_sync_signing import (
        _install_external_key_registry,
        _install_test_sealed_audit,
        _resign,
        _signed_document,
    )

    now = datetime.fromisoformat(exported_at)
    private, _registry_path, registry = _install_external_key_registry(
        path.parent, monkeypatch
    )
    monkeypatch.setattr(signing, "_utc_now", lambda: now)
    store = SqliteStore(path)
    store._conn.execute("DROP TABLE IF EXISTS personal_history_manifest")  # noqa: SLF001
    sync._ensure_control_tables(store._conn)  # noqa: SLF001
    sync._ensure_export_sync_audit(store)
    existing = {
        row[0]
        for row in store._conn.execute(  # noqa: SLF001
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
    }
    for table in sync.DEFAULT_TABLES:
        if table not in existing:
            store._conn.execute(  # noqa: SLF001
                f'CREATE TABLE "{table}" (placeholder TEXT)'
            )
    applied = sync._last_change_seq(store)
    if applied <= 0:
        sync._record_change_seq(store, 7)
        applied = 7
    store._conn.commit()  # noqa: SLF001
    content, schema, counts = sync._private_export.governed_content_identity(
        store._conn, sync.DEFAULT_TABLES  # noqa: SLF001
    )
    document = _signed_document(private, registry, issued_at=now)
    document["envelope"].update(
        {
            "source_content_digest": content,
            "local_content_digest": content,
            "source_schema_digest": schema,
            "schema_digest": schema,
            "table_counts": counts,
            "source_change_seq": applied,
            "applied_change_seq": applied,
            "exported_at": exported_at,
            "issued_at": exported_at,
        }
    )
    _resign(private, document)
    _install_test_sealed_audit(monkeypatch, document)
    sync._mark_authenticated_export_complete(store, object())
    sync._freeze_authenticated_current_applied_mirror(store)
    store.close()
    return exported_at


def _open_ready_handle(
    path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    exported_at: str = AUTHENTICATED_EXPORT_AT,
):
    from scripts import sync_d1_to_sqlite as sync

    authenticate_applied_mirror(path, monkeypatch, exported_at=exported_at)
    return sync.open_authenticated_applied_mirror(path)


def _verify_scope(
    path: Path,
    binding,
    monkeypatch: pytest.MonkeyPatch,
    *,
    exported_at: str = AUTHENTICATED_EXPORT_AT,
):
    handle = _open_ready_handle(path, monkeypatch, exported_at=exported_at)
    return _verify_exact_four_pit_dependency_scope(handle, binding)


def _mutate_sqlite(path: Path, sql: str, params: tuple[object, ...] = ()) -> None:
    connection = sqlite3.connect(path)
    try:
        connection.execute(sql, params)
        connection.commit()
    finally:
        connection.close()


def test_exact_pit_dependency_scope_accepts_complete_receipt_bound_fixture(
    tmp_path,
    receipt_ed25519_keys,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_path, binding = _seed_exact_pit_scope(
        tmp_path, receipt_ed25519_keys
    )
    proof = _verify_scope(db_path, binding, monkeypatch)
    assert proof["status"] == "PASS"
    assert proof["period_start"] == "2023-01-04"
    assert proof["period_end"] == "2023-01-06"
    assert proof["lookback_trading_days"] == 2
    assert {row["dataset_id"] for row in proof["entries"]} == set(
        _SCOPE_DATASETS
    )
    assert all(row["receipt_digests"] for row in proof["entries"])
    assert proof["exported_at"] == AUTHENTICATED_EXPORT_AT
    assert proof["observed_through"] == AUTHENTICATED_EXPORT_AT
    listing_conn = sqlite3.connect(db_path)
    try:
        listing = listing_conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' "
            "AND name='personal_history_manifest'"
        ).fetchone()
    finally:
        listing_conn.close()
    assert listing is None


def test_product_jsonl_vector_matches_authority_utf8_order() -> None:
    rows = [
        {
            "source": "jquants",
            "dataset": "indices_bars_daily_topix",
            "natural_key": natural_key,
            "event_time": "2024-02-01T00:00:00Z",
            "available_at": "2024-02-01T00:00:00Z",
            "ingested_at": "2024-02-02T00:00:00Z",
            "payload": f'{{"key":"{natural_key}"}}',
            "raw_payload": f'{{"key":"{natural_key}"}}',
        }
        for natural_key in ("z-key", "a-key")
    ]
    body = canonical_product_artifact_bytes(rows)
    assert body.index(b"a-key") < body.index(b"z-key")
    assert product_artifact_digest(rows) == (
        "sha256:fc5f92e255656fa9c17298cc492b6f72"
        "ee1c647fa47a749174ea66c290f9dc8e"
    )


def test_signed_product_digest_survives_sync_projection_and_ready(
    tmp_path,
    receipt_ed25519_keys,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_path, binding = _seed_exact_pit_scope(
        tmp_path, receipt_ed25519_keys
    )
    mirror_path = tmp_path / "receipt-product-mirror.sqlite"
    with SqliteStore(mirror_path) as mirror, sqlite3.connect(source_path) as source:
        source.row_factory = sqlite3.Row
        sync_script._ensure_control_tables(mirror._conn)  # noqa: SLF001
        source_max = sync_script._source_change_seq(source)
        _pages, seen_changes, registered_changes, applied_cursor = (
            sync_script._sync_export_changes(
                mirror,
                source,
                page_limit=5,
                source_max_seq=source_max,
            )
        )
        assert seen_changes == registered_changes
        assert applied_cursor == source_max > 0
        for table in (
            "ingestion_run_log",
            "raw_retention_manifests",
            "collection_receipts",
            "receipt_product_materializations",
        ):
            rows = [
                dict(row)
                for row in source.execute(f"SELECT * FROM {table}").fetchall()
            ]
            seen, registered = sync_script._sync_one(mirror, table, rows)
            assert (seen, registered) == (len(rows), len(rows))

        coverage_rows = []
        for contract in all_coverage_contracts():
            policy = coverage_policy_binding(contract.dataset_id)
            coverage_rows.append(
                (
                    contract.dataset_id,
                    "COMPLETE",
                    policy["policy_version"],
                    contract.collection_scope,
                    contract.history_target_start,
                    contract.history_target_end_rule,
                    contract.coverage_mode,
                    contract.expected_frequency,
                    contract.universe_rule,
                    int(contract.raw_retention_required),
                    int(contract.structured_reconciliation_required),
                    contract.governance_tier,
                    "2023-01-02",
                    "2023-01-06",
                    1,
                    5,
                    "2026-08-25T00:00:00Z",
                    "{}",
                )
            )
        mirror._conn.execute(  # noqa: SLF001
            "CREATE TABLE IF NOT EXISTS snapshot_observation_clock "
            "(observed_through TEXT NOT NULL)"
        )
        mirror._conn.execute(  # noqa: SLF001
            "DELETE FROM snapshot_observation_clock"
        )
        mirror._conn.execute(  # noqa: SLF001
            "INSERT INTO snapshot_observation_clock VALUES ('2023-01-06T11:30:00+09:00')"
        )
        mirror._conn.executemany(  # noqa: SLF001
            "INSERT INTO dataset_coverage "
            "(dataset,status,policy_version,collection_scope,"
            "history_target_start,history_target_end_rule,coverage_mode,"
            "expected_frequency,universe_rule,raw_retention_required,"
            "structured_reconciliation_required,governance_tier,"
            "observed_start,observed_end,row_count,source_run_id,evaluated_at,"
            "detail_json) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            coverage_rows,
        )
        mirror._conn.commit()  # noqa: SLF001

    dependency_proof = _verify_scope(mirror_path, binding, monkeypatch)
    product_digests = {
        digest
        for entry in dependency_proof["entries"]
        for digest in entry["product_artifact_digests"]
    }
    assert len(product_digests) == len(_SCOPE_DATASETS)

    bundle = render_projection_bundle_for_test(
        mirror_path,
        generation_id="projgen-receipt-product-e2e",
        producer_commit_sha="e" * 40,
        source_cursor=source_max,
        export_cursor=source_max,
        refresh_status="success",
        last_success_at="2026-08-25T00:00:00Z",
    )
    target = sqlite3.connect(":memory:")
    migration_dir = (
        Path(__file__).resolve().parents[1]
        / "platform/workers/quant-ops-mcp/migrations/projection"
    )
    for migration in sorted(migration_dir.glob("*.sql")):
        target.executescript(migration.read_text(encoding="utf-8"))
    target.executescript(bundle.sql)
    projected_digests = {
        str(row[0])
        for row in target.execute(
            "SELECT artifact_digest FROM receipt_product_materializations "
            "WHERE projection_generation_id=?",
            (bundle.generation_id,),
        )
    }
    target.close()
    assert projected_digests == product_digests

    policy_set = coverage_policy_set_binding(list(binding.required_datasets))
    profile_evidence = {
        dataset_id: {
            "status": "COMPLETE",
            "coverage_mode": official_mode(dataset_id),
            **dict(coverage_policy_binding(dataset_id)),
            "projection_status": "FRESH",
            "source_generation": str(source_max),
            "export_cursor": str(source_max),
            "applied_cursor": str(source_max),
            "signed_projection_document_digest": bundle.content_digest,
        }
        for dataset_id in binding.required_datasets
    }
    coverage_proof_id = canonical_digest({"coverage": "e2e-record"})
    coverage_proof_digest = canonical_digest({"coverage": "e2e-proof"})
    ready_document = {
        "state": "READY",
        "snapshot_id": canonical_digest({"snapshot": "e2e"}),
        "required_datasets": list(binding.required_datasets),
        "coverage_policy_version": policy_set["policy_version"],
        "coverage_policy_digest": policy_set["policy_digest"],
        "coverage_proof": {
            "proof_digest": coverage_proof_digest,
            "policy_version": policy_set["policy_version"],
            "policy_digest": policy_set["policy_digest"],
            "receipt_count": len(product_digests),
        },
        "coverage_proof_id": coverage_proof_id,
        "profile_coverage_evidence": profile_evidence,
        "dependency_scope_evidence": dependency_proof,
        "raw_manifests": {digest: "verified" for digest in product_digests},
        "validations": [{"status": "PASS"}],
        "quality": {
            "status": "PASS",
            "failures": [],
            "results": [{"check_id": "B4", "status": "pass"}],
        },
        "ready_evidence": {
            "passed": True,
            "items": [
                {
                    "name": name,
                    "passed": True,
                    "detail": (
                        {"b0_status": "PASS", "quality_status": "PASS"}
                        if name == "QualityEvidence"
                        else {
                            "source_generation": source_max,
                            "applied_sync_generation": source_max,
                        }
                        if name == "SyncGenerationEvidence"
                        else {}
                    ),
                }
                for name in (
                    "CoverageEvidence",
                    "RawRetentionEvidence",
                    "ValidationEvidence",
                    "NaturalKeyEvidence",
                    "QualityEvidence",
                    "SyncGenerationEvidence",
                )
            ],
        },
        "change_seq": source_max,
        "created_at": "2026-08-25T00:00:00Z",
        "committed_at": "2026-08-25T00:00:01Z",
        "quality_policy_version": "test-b0-b4/v1",
    }
    manifest = build_profile_bound_ready_manifest_from_snapshot_document(
        ready_document,
        profile=binding,
    )
    assert manifest.receipt_proof_digest == canonical_digest(
        {
            "coverage_receipt_count": len(product_digests),
            "trusted_receipt_proof_digest": coverage_proof_digest,
            "coverage_proof_id": coverage_proof_id,
            "product_materialization_digest": dependency_proof[
                "product_materialization_digest"
            ],
        }
    )


@pytest.mark.parametrize(
    ("victim", "event_date"),
    (
        ("markets_calendar", "2023-01-05"),
        ("equities_master", "2023-01-02"),
        ("fins_summary", "2023-01-03"),
        ("equities_bars_daily", "2023-01-05"),
        ("equities_bars_daily_am", "2023-01-05"),
        ("indices_bars_daily_topix", "2023-01-05"),
    ),
)
def test_exact_pit_dependency_scope_rejects_each_missing_or_late_dependency(
    tmp_path,
    receipt_ed25519_keys,
    monkeypatch: pytest.MonkeyPatch,
    victim: str,
    event_date: str,
) -> None:
    db_path, binding = _seed_exact_pit_scope(
        tmp_path, receipt_ed25519_keys
    )
    _mutate_sqlite(
        db_path,
        "UPDATE jquants_records "
        "SET available_at='2026-08-25T00:00:00+09:00' "
        "WHERE dataset=? AND substr(event_time,1,10)=?",
        (victim, event_date),
    )
    with pytest.raises(MassResearchDisabledError):
        _verify_scope(db_path, binding, monkeypatch)


def test_exact_pit_dependency_scope_rejects_am_captured_after_operational_deadline(
    tmp_path,
    receipt_ed25519_keys,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_path, binding = _seed_exact_pit_scope(tmp_path, receipt_ed25519_keys)
    _mutate_sqlite(
        db_path,
        "UPDATE jquants_records "
        "SET ingested_at='2023-01-05T12:31:00+09:00' "
        "WHERE dataset='equities_bars_daily_am' "
        "AND substr(event_time,1,10)='2023-01-05'",
    )
    with pytest.raises(
        MassResearchDisabledError,
        match="equities_bars_daily_am same-day operational closure missing/late",
    ):
        _verify_scope(db_path, binding, monkeypatch)


def test_exact_pit_dependency_scope_rejects_one_visible_row_and_late_rest(
    tmp_path,
    receipt_ed25519_keys,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_path, binding = _seed_exact_pit_scope(
        tmp_path, receipt_ed25519_keys
    )
    _mutate_sqlite(
        db_path,
        "UPDATE jquants_records "
        "SET available_at='2026-08-25T00:00:00+09:00' "
        "WHERE dataset='equities_bars_daily' "
        "AND substr(event_time,1,10) <> '2023-01-02'",
    )
    with pytest.raises(MassResearchDisabledError, match="closure missing/late"):
        _verify_scope(db_path, binding, monkeypatch)


def test_exact_pit_dependency_scope_rejects_unreceipted_natural_keys(
    tmp_path,
    receipt_ed25519_keys,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_path, binding = _seed_exact_pit_scope(
        tmp_path, receipt_ed25519_keys
    )
    _mutate_sqlite(
        db_path,
        "DELETE FROM collection_receipts "
        "WHERE dataset='indices_bars_daily_topix'",
    )
    with pytest.raises(MassResearchDisabledError, match="signed receipt"):
        _verify_scope(db_path, binding, monkeypatch)


@pytest.mark.parametrize("attack", ("missing", "r2_readback_body", "product_row"))
def test_exact_pit_dependency_scope_rejects_missing_or_tampered_product(
    tmp_path,
    receipt_ed25519_keys,
    monkeypatch: pytest.MonkeyPatch,
    attack: str,
) -> None:
    db_path, binding = _seed_exact_pit_scope(tmp_path, receipt_ed25519_keys)
    if attack == "missing":
        _mutate_sqlite(
            db_path,
            "DELETE FROM receipt_product_materializations "
            "WHERE dataset='indices_bars_daily_topix'",
        )
    elif attack == "r2_readback_body":
        _mutate_sqlite(
            db_path,
            "UPDATE receipt_product_materializations "
            "SET artifact_body=artifact_body || ' ' "
            "WHERE dataset='indices_bars_daily_topix'",
        )
    else:
        _mutate_sqlite(
            db_path,
            "UPDATE jquants_records SET raw_payload='{}' "
            "WHERE dataset='indices_bars_daily_topix'",
        )
    with pytest.raises(MassResearchDisabledError, match="signed receipt"):
        _verify_scope(db_path, binding, monkeypatch)


def test_exact_pit_dependency_scope_rejects_noncanonical_natural_key(
    tmp_path,
    receipt_ed25519_keys,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_path, binding = _seed_exact_pit_scope(
        tmp_path, receipt_ed25519_keys
    )
    _mutate_sqlite(
        db_path,
        "UPDATE jquants_records SET natural_key='caller-supplied' "
        "WHERE dataset='equities_bars_daily' "
        "AND substr(event_time,1,10)='2023-01-05'",
    )
    with pytest.raises(MassResearchDisabledError, match="natural key"):
        _verify_scope(db_path, binding, monkeypatch)


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
