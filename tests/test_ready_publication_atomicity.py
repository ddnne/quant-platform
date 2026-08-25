"""Atomic publication boundary for signed pilot readiness sidecars."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

import paper_runtime.snapshot as snapshot_module
from paper_runtime.snapshot import SnapshotRejected
from tests.ready_snapshot_test_support import publish_ready_snapshot_fixture
from tests.test_phase6_snapshot_publication import (
    _jquants_coverage_contracts,
    _seed_publishable_db,
)


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
    source = sqlite3.connect(staging)
    try:
        state = source.execute(
            "SELECT state FROM snapshot_publications "
            "ORDER BY created_at DESC LIMIT 1"
        ).fetchone()[0]
        assert state == "REJECTED"
    finally:
        source.close()


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

    def mint_fixture_sidecar(ready):
        sidecar = ready.db_path.with_suffix(".readiness.json")
        sidecar.write_text('{"signature":"fixture"}\n', encoding="utf-8")
        minted_sidecars.append(sidecar)
        return sidecar

    with pytest.raises(sqlite3.IntegrityError, match="database publication failure"):
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
