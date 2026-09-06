"""Atomic publication boundary for signed pilot readiness sidecars."""

from __future__ import annotations

import hashlib
import inspect
import json
import os
import sqlite3
from pathlib import Path

import pytest

import paper_runtime
import paper_runtime.snapshot as snapshot_module
import paper_runtime.snapshot_read as snapshot_read_module
from data_contracts.coverage import coverage_policy_binding
from paper_runtime.snapshot import SnapshotRejected
from paper_runtime.snapshot_coverage_proof import (
    _coverage_proof,
    _publication_cutoff_for_build,
    persist_coverage_proof,
)
from paper_runtime.snapshot_read import describe_snapshot, latest_ready_snapshot
from research.ready_manifest import (
    VerifiedPilotReadyPublication,
    build_profile_bound_ready_manifest_from_snapshot_document,
    load_exact_four_pilot_ready_binding,
    publish_exact_four_pilot_ready_snapshot,
    ready_manifest_from_snapshot_document,
)
from selection.budget_ledger import MassResearchDisabledError
from research.research_data_profile import official_mode
from research.universe_contract import EXACT_FOUR_UNIVERSE_RULE_DIGEST
from tests.readiness_test_support import (
    make_readiness_signer,
    mint_pilot_readiness,
)
from tests.ready_snapshot_test_support import publish_ready_snapshot_fixture
from tests.ready_snapshot_test_support import _evaluate_ready_publication_fixture
from tests.test_phase6_snapshot_publication import (
    _jquants_coverage_contracts,
    _seed_publishable_db,
)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def _writable_database(path: Path) -> None:
    conn = sqlite3.connect(path)
    try:
        conn.execute("CREATE TABLE marker(value TEXT NOT NULL)")
        conn.execute("INSERT INTO marker(value) VALUES ('verified-A')")
        conn.commit()
    finally:
        conn.close()


def test_public_ready_sqlite_open_stays_closed_with_retained_writer(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    snapshot_dir = tmp_path / "snapshots"
    snapshot_dir.mkdir()
    artifact = snapshot_dir / "verified.sqlite"
    _writable_database(artifact)
    retained_writer = os.open(
        artifact,
        os.O_RDWR | getattr(os, "O_CLOEXEC", 0),
    )
    artifact.chmod(0o444)
    fake_connection = sqlite3.connect(":memory:")
    calls: list[str] = []

    def patched_builder(*_args, **_kwargs):
        calls.append("builder")
        return object()

    def patched_opener(*_args, **_kwargs):
        calls.append("opener")
        return fake_connection

    monkeypatch.setattr(
        snapshot_read_module,
        "latest_ready_snapshot",
        patched_builder,
    )
    monkeypatch.setattr(
        snapshot_read_module,
        "describe_snapshot",
        patched_builder,
    )
    monkeypatch.setattr(
        snapshot_read_module,
        "_open_fixture_snapshot_connection",
        patched_opener,
    )
    monkeypatch.setattr(
        snapshot_read_module,
        "_open_pinned_sqlite",
        patched_opener,
    )

    try:
        assert artifact.stat().st_mode & 0o777 == 0o444
        offset = artifact.stat().st_size - 1
        original = os.pread(retained_writer, 1, offset)
        assert len(original) == 1
        changed = bytes([original[0] ^ 1])
        assert os.pwrite(retained_writer, changed, offset) == 1
        assert os.pread(retained_writer, 1, offset) == changed
        assert os.pwrite(retained_writer, original, offset) == 1
        os.fsync(retained_writer)

        with pytest.raises(
            SnapshotRejected,
            match="public production READY SQLite open is disabled",
        ):
            snapshot_read_module.open_ready_snapshot(
                snapshot_dir,
                "sha256:" + "ab" * 32,
            )

        assert calls == []
        assert not hasattr(paper_runtime, "open_ready_snapshot")
        assert not hasattr(snapshot_module, "open_ready_snapshot")
        assert fake_connection.execute("SELECT 1").fetchone() == (1,)
    finally:
        fake_connection.close()
        os.close(retained_writer)


def _replace_fixture_with_coherent_exact_four_artifact(ready, binding):
    """Retain one exact publisher document inside and outside the artifact."""
    outer = json.loads(json.dumps(ready.manifest))
    required = list(binding.required_datasets)
    required_set = set(required)
    outer["required_datasets"] = required
    outer["dataset_watermarks"] = [
        row
        for row in outer["dataset_watermarks"]
        if row["dataset"] in required_set
    ]
    outer["coverage"] = [
        row for row in outer["coverage"] if row["dataset"] in required_set
    ]

    ready.db_path.chmod(0o644)
    conn = sqlite3.connect(ready.db_path)
    conn.row_factory = sqlite3.Row
    try:
        coverage_rows = [
            dict(row)
            for row in conn.execute(
                "SELECT * FROM dataset_coverage ORDER BY dataset"
            )
            if str(row["dataset"]) in required_set
        ]
        build_id = str(outer["build_id"])
        # This fixture deliberately derives a new profile-scoped artifact from
        # an existing fixture. Re-enter the same active VALIDATING boundary the
        # product publisher uses; product proof minting never occurs from READY.
        conn.execute(
            "UPDATE snapshot_publications SET state='VALIDATING',staging_path=? "
            "WHERE build_id=?",
            (str(ready.db_path.resolve()), build_id),
        )
        conn.execute(
            "UPDATE local_snapshot_policy SET publication_state='VALIDATING',"
            "snapshot_ready=0,active_build_id=?,active_snapshot_id=NULL "
            "WHERE singleton=1",
            (build_id,),
        )
        conn.commit()
        coverage_proof = _coverage_proof(
            conn,
            tuple(required),
            coverage_rows,
            publication_cutoff=_publication_cutoff_for_build(conn, build_id),
        )
        outer["coverage_proof"] = coverage_proof
        outer["coverage_proof_id"] = persist_coverage_proof(
            conn, tuple(required), build_id=build_id
        )
        outer["coverage_policy_version"] = coverage_proof["policy_version"]
        outer["coverage_policy_digest"] = coverage_proof["policy_digest"]

        coverage_by_dataset = {
            row["dataset"]: row for row in outer["coverage"]
        }
        generation = str(outer["change_seq"])
        profile_evidence = {}
        for dataset_id in required:
            policy = coverage_policy_binding(dataset_id)
            row = coverage_by_dataset[dataset_id]
            profile_evidence[dataset_id] = {
                "status": "COMPLETE",
                "projection_status": "FRESH",
                "coverage_mode": official_mode(dataset_id),
                "policy_id": policy["policy_id"],
                "policy_version": policy["policy_version"],
                "policy_digest": policy["policy_digest"],
                "source_generation": generation,
                "export_cursor": generation,
                "applied_sync_generation": generation,
                "observed_start": row["observed_start"],
                "observed_end": row["observed_end"],
            }
        outer["profile_coverage_evidence"] = profile_evidence

        scope_body = {
            "format": "pit-dependency-scope-proof/v1",
            "status": "PASS",
            "profile_digest": binding.profile_digest,
            "plan_set_digest": binding.plan_set_digest,
            "dependency_closure_digest": binding.closure_set_digest,
            "universe_rule_digest": EXACT_FOUR_UNIVERSE_RULE_DIGEST,
            "resolved_universe_digest": "sha256:" + ("ab" * 32),
            "product_materialization_digest": "sha256:" + ("cd" * 32),
        }
        outer["dependency_scope_evidence"] = {
            **scope_body,
            "proof_digest": snapshot_module._canonical_digest(scope_body),
        }
        for field in (
            "snapshot_id",
            "artifact",
            "manifest_digest",
            "ready_manifest",
        ):
            outer.pop(field, None)
        snapshot_id = snapshot_module._research_manifest_id(outer)
        stem = snapshot_module._artifact_stem(snapshot_id)
        artifact_name = f"{stem}.sqlite"
        outer["snapshot_id"] = snapshot_id
        outer["artifact"] = artifact_name
        nested = build_profile_bound_ready_manifest_from_snapshot_document(
            outer,
            profile=binding,
        )
        outer["ready_manifest"] = nested.to_dict()
        outer["manifest_digest"] = snapshot_module._research_manifest_digest(
            outer
        )
        # Exercise the same full reconstruction used by the product reader.
        assert ready_manifest_from_snapshot_document(outer) == nested

        manifest_json = json.dumps(
            outer,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        conn.execute("DELETE FROM local_snapshot_manifests")
        conn.execute(
            "INSERT INTO local_snapshot_manifests "
            "(snapshot_id,format,committed_at,source_run_id,change_seq,manifest_json) "
            "VALUES (?,?,?,?,?,?)",
            (
                snapshot_id,
                snapshot_module.RESEARCH_SNAPSHOT_MANIFEST_FORMAT,
                outer["committed_at"],
                outer["source_run"]["id"],
                outer["change_seq"],
                manifest_json,
            ),
        )
        conn.execute(
            "UPDATE local_snapshot_policy SET active_snapshot_id=?, "
            "snapshot_ready=1, publication_state='READY' WHERE singleton=1",
            (snapshot_id,),
        )
        conn.execute(
            "UPDATE snapshot_publications SET state='READY',snapshot_id=?, artifact_path=?, "
            "manifest_path=?, committed_at=?, change_seq=?, manifest_json=? "
            "WHERE build_id=?",
            (
                snapshot_id,
                str(ready.db_path.with_name(artifact_name).resolve()),
                str(ready.db_path.with_name(f"{stem}.manifest.json").resolve()),
                outer["committed_at"],
                outer["change_seq"],
                manifest_json,
                build_id,
            ),
        )
        conn.commit()
    finally:
        conn.close()

    artifact_path = ready.db_path.with_name(artifact_name)
    ready.db_path.replace(artifact_path)
    artifact_path.chmod(0o444)
    ready.manifest_path.unlink()
    ready.db_path.with_suffix(".publication.json").unlink(missing_ok=True)
    manifest_path = artifact_path.with_suffix(".manifest.json")
    snapshot_module._atomic_json(manifest_path, outer, mode=0o444)
    return artifact_path, manifest_path, outer, nested


def test_rejected_pointer_finalization_removes_already_minted_sidecar(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        snapshot_module, "all_coverage_contracts", _jquants_coverage_contracts
    )
    staging = tmp_path / "atomic-sidecar.sqlite"
    required = _seed_publishable_db(staging)
    snapshot_dir = tmp_path / "snapshots"
    minted_sidecars: list[Path] = []

    def mint_fixture_sidecar(ready):
        source = sqlite3.connect(staging)
        try:
            assert source.execute(
                "SELECT state FROM snapshot_publications "
                "ORDER BY created_at DESC LIMIT 1"
            ).fetchone()[0] == "READY"
        finally:
            source.close()
        sidecar = ready.db_path.with_suffix(".readiness.json")
        sidecar.write_text('{"signature":"fixture"}\n', encoding="utf-8")
        sidecar.chmod(0o444)
        minted_sidecars.append(sidecar)
        return sidecar

    write_json = snapshot_module._atomic_json

    def fail_latest_pointer(target, payload, *, mode):
        if target.name == "latest-ready.json":
            raise OSError("simulated pointer write failure after attestation")
        return write_json(target, payload, mode=mode)

    monkeypatch.setattr(snapshot_module, "_atomic_json", fail_latest_pointer)
    with pytest.raises(SnapshotRejected, match="finalization failed"):
        publish_ready_snapshot_fixture(
            staging,
            snapshot_dir,
            required_datasets=required,
            profile_coverage_evidence={dataset: {} for dataset in required},
            ready_manifest_builder=lambda _document: {"fixture": "ready"},
            ready_attestation_builder=mint_fixture_sidecar,
        )

    assert minted_sidecars
    assert all(not sidecar.exists() for sidecar in minted_sidecars)
    assert not (snapshot_dir / "latest-ready.json").exists()
    assert snapshot_module.list_ready_snapshots(snapshot_dir) == []
    with pytest.raises(FileNotFoundError, match="no READY"):
        snapshot_module.latest_ready_snapshot(snapshot_dir)
    assert not list(snapshot_dir.glob("sha256_*.sqlite"))
    assert not list(snapshot_dir.glob("sha256_*.manifest.json"))
    assert not list(snapshot_dir.glob("sha256_*.publication.json"))
    quarantined = list((snapshot_dir / "rejected").glob("build-*"))
    assert len(quarantined) == 1
    source = sqlite3.connect(staging)
    try:
        state = source.execute(
            "SELECT state FROM snapshot_publications "
            "ORDER BY created_at DESC LIMIT 1"
        ).fetchone()[0]
        assert state == "REJECTED"
    finally:
        source.close()


def test_production_reader_binds_nested_ready_manifest_and_artifact_bytes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        snapshot_module, "all_coverage_contracts", _jquants_coverage_contracts
    )
    staging = tmp_path / "production-reader.sqlite"
    required = _seed_publishable_db(staging)
    snapshot_dir = tmp_path / "snapshots"
    ready = publish_ready_snapshot_fixture(
        staging,
        snapshot_dir,
        required_datasets=required,
    )

    binding = load_exact_four_pilot_ready_binding()
    artifact_path, manifest_path, outer, nested = (
        _replace_fixture_with_coherent_exact_four_artifact(ready, binding)
    )
    assert outer["manifest_digest"] != nested.to_dict()["manifest_digest"]

    signer = make_readiness_signer(
        key_id="r7-production-reader-test", environment="production"
    )
    artifact_digest = _sha256_file(artifact_path)
    readiness = mint_pilot_readiness(
        nested,
        publisher=signer,
        immutable_db_digest=artifact_digest,
        profile_binding=binding,
    )
    attestation_path = artifact_path.with_name(
        f"{artifact_path.stem}.{readiness.attestation_id}.readiness.json"
    )
    snapshot_module._atomic_json(
        attestation_path,
        readiness.to_dict(),
        mode=0o444,
    )
    publication_body = {
        "format": "research-snapshot-publication/v1",
        "snapshot_id": outer["snapshot_id"],
        "manifest_digest": outer["manifest_digest"],
        "committed_at": outer["committed_at"],
        "change_seq": outer["change_seq"],
        "artifact_digest": artifact_digest,
        "publication_scope": "PRODUCTION",
        "readiness_attestation": attestation_path.name,
        "readiness_attestation_digest": _sha256_file(attestation_path),
        "readiness_attestation_id": readiness.attestation_id,
    }
    publication = {
        **publication_body,
        "publication_digest": snapshot_module._canonical_digest(
            publication_body
        ),
    }
    snapshot_module._atomic_json(
        artifact_path.with_suffix(".publication.json"),
        publication,
        mode=0o444,
    )
    snapshot_module._atomic_json(
        snapshot_dir / "latest-ready.json",
        {
            "format": "research-snapshot-pointer/v1",
            "snapshot_id": outer["snapshot_id"],
            "manifest": manifest_path.name,
            "committed_at": outer["committed_at"],
            "change_seq": outer["change_seq"],
            "publication_digest": publication["publication_digest"],
        },
        mode=0o444,
    )
    monkeypatch.setattr(
        "paper_runtime.readiness_attestation._load_pinned_readiness_public_keys",
        signer.public_keys,
    )

    observed = describe_snapshot(snapshot_dir, outer["snapshot_id"])
    assert observed.snapshot_id == outer["snapshot_id"]
    assert observed.readiness_path == attestation_path
    assert observed.readiness_attestation_id == readiness.attestation_id
    assert observed.readiness_digest == _sha256_file(attestation_path)
    assert observed.readiness_bytes == attestation_path.read_bytes()
    assert latest_ready_snapshot(snapshot_dir).snapshot_id == outer["snapshot_id"]

    alternate = mint_pilot_readiness(
        nested,
        publisher=signer,
        immutable_db_digest=artifact_digest,
        profile_binding=binding,
        signed_projection_document_digest="sha256:" + "ab" * 32,
    )
    alternate_path = artifact_path.with_name(
        f"{artifact_path.stem}.{alternate.attestation_id}.readiness.json"
    )
    snapshot_module._atomic_json(alternate_path, alternate.to_dict(), mode=0o444)
    snapshot_module._atomic_json(
        attestation_path,
        alternate.to_dict(),
        mode=0o444,
    )
    with pytest.raises(
        MassResearchDisabledError,
        match="cannot be independently reopened",
    ):
        VerifiedPilotReadyPublication(
            snapshot=observed,
            readiness=readiness,
            readiness_path=attestation_path,
        )
    snapshot_module._atomic_json(
        attestation_path,
        readiness.to_dict(),
        mode=0o444,
    )
    forged_snapshot = snapshot_module.ReadySnapshot(
        observed.snapshot_id,
        observed.db_path,
        observed.manifest_path,
        observed.manifest,
        publication_path=observed.publication_path,
        readiness_path=alternate_path,
        readiness_digest=_sha256_file(alternate_path),
        readiness_attestation_id=alternate.attestation_id,
        readiness_bytes=alternate_path.read_bytes(),
    )
    with pytest.raises(
        MassResearchDisabledError,
        match="caller snapshot differs",
    ):
        VerifiedPilotReadyPublication(
            snapshot=forged_snapshot,
            readiness=alternate,
            readiness_path=alternate_path,
        )

    mismatched_body = {
        **publication_body,
        "readiness_attestation": alternate_path.name,
        "readiness_attestation_digest": _sha256_file(alternate_path),
    }
    snapshot_module._atomic_json(
        artifact_path.with_suffix(".publication.json"),
        {
            **mismatched_body,
            "publication_digest": snapshot_module._canonical_digest(
                mismatched_body
            ),
        },
        mode=0o444,
    )
    with pytest.raises(RuntimeError, match="exact attestation id"):
        describe_snapshot(snapshot_dir, outer["snapshot_id"])
    snapshot_module._atomic_json(
        artifact_path.with_suffix(".publication.json"),
        publication,
        mode=0o444,
    )

    rewritten = dict(outer)
    rewritten["committed_at"] = "2099-12-31T23:59:59+00:00"
    rewritten["manifest_digest"] = snapshot_module._research_manifest_digest(
        rewritten
    )
    snapshot_module._atomic_json(manifest_path, rewritten, mode=0o444)
    rewritten_body = {
        **publication_body,
        "manifest_digest": rewritten["manifest_digest"],
        "committed_at": rewritten["committed_at"],
    }
    rewritten_publication = {
        **rewritten_body,
        "publication_digest": snapshot_module._canonical_digest(
            rewritten_body
        ),
    }
    snapshot_module._atomic_json(
        artifact_path.with_suffix(".publication.json"),
        rewritten_publication,
        mode=0o444,
    )
    snapshot_module._atomic_json(
        snapshot_dir / "latest-ready.json",
        {
            "format": "research-snapshot-pointer/v1",
            "snapshot_id": outer["snapshot_id"],
            "manifest": manifest_path.name,
            "committed_at": rewritten["committed_at"],
            "change_seq": rewritten["change_seq"],
            "publication_digest": rewritten_publication["publication_digest"],
        },
        mode=0o444,
    )
    with pytest.raises(RuntimeError, match="does not match embedded"):
        describe_snapshot(snapshot_dir, outer["snapshot_id"])
    with pytest.raises(RuntimeError, match="does not match embedded"):
        latest_ready_snapshot(snapshot_dir)

    snapshot_module._atomic_json(manifest_path, outer, mode=0o444)
    snapshot_module._atomic_json(
        artifact_path.with_suffix(".publication.json"),
        publication,
        mode=0o444,
    )
    snapshot_module._atomic_json(
        snapshot_dir / "latest-ready.json",
        {
            "format": "research-snapshot-pointer/v1",
            "snapshot_id": outer["snapshot_id"],
            "manifest": manifest_path.name,
            "committed_at": outer["committed_at"],
            "change_seq": outer["change_seq"],
            "publication_digest": publication["publication_digest"],
        },
        mode=0o444,
    )

    artifact_path.chmod(0o644)
    with artifact_path.open("ab") as handle:
        handle.write(b"tamper")
    artifact_path.chmod(0o444)
    with pytest.raises(RuntimeError, match="artifact digest mismatch"):
        describe_snapshot(snapshot_dir, outer["snapshot_id"])


def test_fixture_gate_cannot_publish_a_production_scope(tmp_path: Path) -> None:
    """A tests-owned gate is rejected before source or artifact mutation."""
    staging = tmp_path / "mixed-scope.sqlite"
    staging.touch()
    snapshot_dir = tmp_path / "snapshots"

    with pytest.raises(SnapshotRejected, match="authority is PENDING"):
        snapshot_module._publish_ready_snapshot_impl(
            staging,
            snapshot_dir,
            required_datasets=("equities_bars_daily",),
            publication_gate=_evaluate_ready_publication_fixture,
            fixture_compatibility=False,
        )

    assert not snapshot_dir.exists()
    assert not list(tmp_path.glob("**/*.publication.json"))
    assert not list(tmp_path.glob("**/latest-ready.json"))
    assert not hasattr(snapshot_module, "_snapshot_candidate_engine")
    assert not hasattr(
        snapshot_module,
        "_publish_exact_four_pilot_ready_snapshot_via_authority_impl",
    )
    assert set(
        inspect.signature(
            publish_exact_four_pilot_ready_snapshot
        ).parameters
    ) == {"staging_db", "snapshot_dir", "signed_projection_document"}


def test_publication_marker_post_replace_failure_is_not_discoverable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        snapshot_module, "all_coverage_contracts", _jquants_coverage_contracts
    )
    staging = tmp_path / "marker-post-replace.sqlite"
    required = _seed_publishable_db(staging)
    snapshot_dir = tmp_path / "snapshots"
    write_json = snapshot_module._atomic_json

    def fail_after_publication_replace(target, payload, *, mode):
        write_json(target, payload, mode=mode)
        if target.name.endswith(".publication.json"):
            raise OSError("simulated post-replace marker failure")

    monkeypatch.setattr(
        snapshot_module, "_atomic_json", fail_after_publication_replace
    )
    with pytest.raises(
        SnapshotRejected,
        match="rejected immutable evidence quarantined.*post-replace",
    ):
        publish_ready_snapshot_fixture(
            staging,
            snapshot_dir,
            required_datasets=required,
        )

    assert not (snapshot_dir / "latest-ready.json").exists()
    assert not list(snapshot_dir.glob("sha256_*.publication.json"))
    assert not list(snapshot_dir.glob("sha256_*.sqlite"))
    assert not list(snapshot_dir.glob("sha256_*.manifest.json"))
    assert len(list((snapshot_dir / "rejected").glob("build-*"))) == 1


def test_manifest_post_replace_failure_quarantines_all_immutable_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        snapshot_module, "all_coverage_contracts", _jquants_coverage_contracts
    )
    staging = tmp_path / "manifest-post-replace.sqlite"
    required = _seed_publishable_db(staging)
    snapshot_dir = tmp_path / "snapshots"
    write_json = snapshot_module._atomic_json

    def fail_after_manifest_replace(target, payload, *, mode):
        write_json(target, payload, mode=mode)
        if target.name.endswith(".manifest.json"):
            raise OSError("simulated post-replace manifest failure")

    monkeypatch.setattr(
        snapshot_module, "_atomic_json", fail_after_manifest_replace
    )
    with pytest.raises(
        SnapshotRejected,
        match="rejected immutable evidence quarantined.*post-replace",
    ):
        publish_ready_snapshot_fixture(
            staging,
            snapshot_dir,
            required_datasets=required,
        )

    assert not (snapshot_dir / "latest-ready.json").exists()
    assert not list(snapshot_dir.glob("sha256_*.publication.json"))
    assert not list(snapshot_dir.glob("sha256_*.sqlite"))
    assert not list(snapshot_dir.glob("sha256_*.manifest.json"))
    quarantined = list((snapshot_dir / "rejected").glob("build-*"))
    assert len(quarantined) == 1
    assert len(list(quarantined[0].glob("sha256_*.sqlite"))) == 1
    assert len(list(quarantined[0].glob("sha256_*.manifest.json"))) == 1


def test_database_publication_failure_aborts_before_readiness_is_minted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        snapshot_module, "all_coverage_contracts", _jquants_coverage_contracts
    )
    staging = tmp_path / "database-publication-failure.sqlite"
    required = _seed_publishable_db(staging)
    snapshot_dir = tmp_path / "snapshots"
    minted_sidecars: list[Path] = []

    source = sqlite3.connect(staging)
    try:
        source.execute(
            """
            CREATE TRIGGER reject_ready_publication
            BEFORE UPDATE OF state ON snapshot_publications
            WHEN NEW.state = 'READY'
            BEGIN
                SELECT RAISE(ABORT, 'simulated database publication failure');
            END
            """
        )
        source.commit()
    finally:
        source.close()
    copy_sqlite = snapshot_module._copy_sqlite

    def copy_without_source_failure_trigger(source, target):
        copy_sqlite(source, target)
        copied = sqlite3.connect(target)
        try:
            copied.execute("DROP TRIGGER reject_ready_publication")
            copied.commit()
        finally:
            copied.close()

    monkeypatch.setattr(
        snapshot_module, "_copy_sqlite", copy_without_source_failure_trigger
    )

    def mint_fixture_sidecar(ready):
        sidecar = ready.db_path.with_suffix(".readiness.json")
        sidecar.write_text('{"signature":"fixture"}\n', encoding="utf-8")
        minted_sidecars.append(sidecar)
        return sidecar

    with pytest.raises(
        SnapshotRejected,
        match="rejected immutable evidence quarantined.*database publication failure",
    ):
        publish_ready_snapshot_fixture(
            staging,
            snapshot_dir,
            required_datasets=required,
            profile_coverage_evidence={dataset: {} for dataset in required},
            ready_manifest_builder=lambda _document: {"fixture": "ready"},
            ready_attestation_builder=mint_fixture_sidecar,
        )

    assert minted_sidecars == []
    assert not (snapshot_dir / "latest-ready.json").exists()
    assert list(snapshot_dir.glob("*.readiness.json")) == []
    assert snapshot_module.list_ready_snapshots(snapshot_dir) == []
    with pytest.raises(FileNotFoundError, match="no READY"):
        snapshot_module.latest_ready_snapshot(snapshot_dir)
    assert not list(snapshot_dir.glob("sha256_*.sqlite"))
    assert not list(snapshot_dir.glob("sha256_*.manifest.json"))
    assert not list(snapshot_dir.glob("sha256_*.publication.json"))
    quarantined = list((snapshot_dir / "rejected").glob("build-*"))
    assert len(quarantined) == 1
    assert len(list(quarantined[0].glob("sha256_*.sqlite"))) == 1
    assert len(list(quarantined[0].glob("sha256_*.manifest.json"))) == 1
    source = sqlite3.connect(staging)
    try:
        publication = source.execute(
            "SELECT state, rejection_reason FROM snapshot_publications "
            "ORDER BY created_at DESC LIMIT 1"
        ).fetchone()
        assert publication is not None
        assert publication[0] == "REJECTED"
        assert "database publication failure" in publication[1]
        policy = source.execute(
            "SELECT snapshot_ready, publication_state, active_snapshot_id "
            "FROM local_snapshot_policy WHERE singleton=1"
        ).fetchone()
        assert policy == (0, "REJECTED", None)
    finally:
        source.close()
