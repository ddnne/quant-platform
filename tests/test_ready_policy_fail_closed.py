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
)
from paper_runtime.ready_policy import (
    CoverageEvidence,
    ReadyPublicationPolicy,
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
from research.universe_contract import EXACT_FOUR_UNIVERSE_RULE_DIGEST
from selection.budget_ledger import MassResearchDisabledError
from storage.coverage_ledger import (
    RequiredCoverageSegment,
    record_collection_receipt,
)
from storage.sqlite_store import SqliteStore
from tests.readiness_test_support import make_readiness_signer
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
    def verify_and_derive(document, required_datasets):
        envelope = registry.verify(document)
        return envelope, registry.verified_dataset_evidence(
            document, required_datasets
        )

    monkeypatch.setattr(
        "ops.projection_signing.verified_pinned_ops_projection_dataset_evidence",
        verify_and_derive,
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
        universe_rule_digest=EXACT_FOUR_UNIVERSE_RULE_DIGEST,
        resolved_universe_digest=proof,
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
    monkeypatch.setattr(
        "paper_runtime.snapshot._immutable_data_snapshot_id",
        lambda _path: snapshot_id,
    )
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
