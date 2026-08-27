"""Behavioral integration for the C4/C10/R5 local authority handlers."""

from __future__ import annotations

import array
import base64
import hashlib
import json
import os
import socket
import sqlite3
import stat
import struct
import threading
from collections.abc import Callable
from pathlib import Path
from types import MappingProxyType, SimpleNamespace

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from ops import d1_sync_signing, projection_signing
from storage.coverage_transition import CoverageTransitionPublicKeyRegistry

from scripts import authority_protocol_runtime as protocol
from scripts import export_ops_projection as exporter
from scripts import local_authority_entrypoints as entrypoints
from scripts import local_authority_service as service_runtime
from scripts import sync_d1_to_sqlite as sync_runtime
from scripts.local_authority_entrypoints import (
    CoverageTransitionAuthorize,
    D1FreezeAndRenderOpsProjection,
    D1FreezeAuthorizeApplyCoverage,
    D1SyncNow,
    OpsProjectionRenderAndSign,
    ReadyPublishProfilePlanBound,
    _D1SyncAuditSealer,
    _advance_d1_sync_journal,
    _d1_sync_paths,
    _d1_sync_record_digest,
    _execute_governed_remote_sync,
    _hash_regular_fd,
    _owned_mirror_evidence,
    _read_d1_sync_journal,
    _write_d1_sync_journal,
)
from tests.test_coverage_transition_authority import (
    _BUILD_ID,
    _DATASETS,
    _configure_test_registry,
    _prepare_transition_db,
    _registry_for,
)
from tests.test_d1_sync_signing import _install_external_key_registry
from tests.test_ops_projection_connection_renderer import FIXED_NOW, _projection_source
from tests.test_ops_projection_publish import _test_mirror_identity


def test_owned_mirror_descriptor_rejects_hardlinked_file(tmp_path: Path) -> None:
    mirror = tmp_path / "mirror.sqlite3"
    mirror.write_bytes(b"governed mirror")
    mirror.chmod(0o600)
    hardlink = tmp_path / "mirror-copy.sqlite3"
    os.link(mirror, hardlink)
    fd = os.open(mirror, os.O_RDONLY)
    try:
        with pytest.raises(service_runtime.LocalAuthorityError, match="read-only SQLite"):
            _hash_regular_fd(fd)
    finally:
        os.close(fd)


def _custody(
    tmp_path: Path,
    *,
    key_id: str,
    private: Ed25519PrivateKey | None = None,
) -> tuple[service_runtime.FileEd25519KeyCustody, Ed25519PrivateKey]:
    key = private or Ed25519PrivateKey.generate()
    path = tmp_path / f"{key_id}.key"
    path.write_bytes(
        key.private_bytes(
            serialization.Encoding.Raw,
            serialization.PrivateFormat.Raw,
            serialization.NoEncryption(),
        )
    )
    path.chmod(0o600)
    return (
        service_runtime.FileEd25519KeyCustody(
            path, key_id=key_id, expected_uid=os.geteuid()
        ),
        key,
    )


def _ledger(
    tmp_path: Path, authority_id: str
) -> service_runtime.SQLiteAuthorityEventLedger:
    directory = tmp_path / f"ledger-{authority_id}"
    directory.mkdir(mode=0o700)
    ledger = service_runtime.SQLiteAuthorityEventLedger(
        directory / "events.sqlite3",
        authority_id=authority_id,
        environment="production",
        expected_uid=os.geteuid(),
    )
    ledger.initialize()
    return ledger


def _context(
    *,
    caller: str,
    operation: str,
    purpose: str,
    request_id: str = "direct-handler-test",
    request_digest: str = "sha256:" + "0" * 64,
    deadline_monotonic_ns: int = 2**63 - 1,
    environment: str = "production",
) -> service_runtime.AuthorityRequestContext:
    return service_runtime.AuthorityRequestContext(
        peer=service_runtime.PeerIdentity(
            uid=os.geteuid(), gid=os.getegid(), pid=os.getpid()
        ),
        caller=caller,
        grant=service_runtime.MethodGrant(
            caller=caller,
            operation=operation,
            purpose=purpose,
            environment=environment,
        ),
        request_id=request_id,
        request_digest=request_digest,
        accepted_at_monotonic_ns=1,
        processing_deadline_monotonic_ns=deadline_monotonic_ns,
    )


def _serve_once(
    listener: socket.socket, service: service_runtime.UnixAuthorityService
) -> None:
    channel, _ = listener.accept()
    try:
        service.serve_connection(channel)
    finally:
        channel.close()


def _listener(tmp_path: Path, name: str) -> tuple[Path, socket.socket]:
    del tmp_path
    path = Path("/tmp") / f"qp-{os.getpid()}-{name}.sock"
    path.unlink(missing_ok=True)
    listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    listener.bind(str(path))
    listener.listen(1)
    return path, listener


def _fake_mirror_authority(
    monkeypatch: pytest.MonkeyPatch,
    database: Path,
    identity: dict[str, object],
) -> None:
    token = object()
    monkeypatch.setattr(
        sync_runtime, "open_authenticated_applied_mirror", lambda _path: token
    )

    def consume(handle, consumer):
        assert handle is token
        conn = sqlite3.connect(database, timeout=1)
        conn.execute("BEGIN IMMEDIATE")
        try:
            return consumer(conn, MappingProxyType(identity))
        finally:
            conn.rollback()
            conn.close()

    monkeypatch.setattr(sync_runtime, "_consume_authenticated_applied_mirror", consume)
    monkeypatch.setattr(
        protocol, "_remeasure_applied_mirror_identity", lambda _conn: identity
    )


def test_d1_sync_entrypoint_uses_only_configured_resources_and_exact_cursor(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database = tmp_path / "governed.sqlite"
    sqlite3.connect(database).close()
    database.chmod(0o600)
    credential = tmp_path / "cloudflare-token"
    credential.write_text("x" * 32 + "\n", encoding="ascii")
    credential.chmod(0o400)
    custody, _private = _custody(tmp_path, key_id="d1-sync-test-v1")
    observed: dict[str, object] = {}

    def executor(**kwargs):
        observed.update(kwargs)
        return {
            "status": "SYNCED",
            "source_change_seq": 11,
            "applied_change_seq": 11,
        }

    handler = D1SyncNow(
        environment="production",
        governed_db_path=database,
        cloudflare_token_path=credential,
        node_executable_path="/protected/node",
        wrangler_cli_path="/protected/wrangler.js",
        wrangler_cli_tree_path="/protected/wrangler-tree",
        wrangler_config_path="/protected/wrangler.toml",
        wrangler_lock_path="/protected/package-lock.json",
        custody=custody,
        expected_uid=os.geteuid(),
        source_sha="sha256:" + "1" * 64,
        tool_digest="sha256:" + "2" * 64,
        event_ledger=_ledger(tmp_path, "d1_sync"),
        executor=executor,
    )
    monkeypatch.setattr(
        entrypoints,
        "_observe_d1_sync_tool_digest",
        lambda _resources: "sha256:" + "2" * 64,
    )
    result = handler(
        _context(
            caller="ops_scheduler",
            operation=D1SyncNow.operation,
            purpose="sync_current",
        ),
        {"expected_applied_cursor": 7},
        (),
    )
    assert result["status"] == "SYNCED"
    assert observed["governed_db_path"] == database
    assert observed["expected_applied_cursor"] == 7
    assert observed["credential_token"] == "x" * 32
    assert observed["node_executable_path"] == Path("/protected/node")
    assert observed["source_sha"] == "sha256:" + "1" * 64
    assert observed["tool_digest"] == "sha256:" + "2" * 64
    assert isinstance(observed["sealer"], _D1SyncAuditSealer)
    assert "credential_token" not in result

    with pytest.raises(service_runtime.LocalAuthorityError, match="not closed"):
        handler(
            _context(
                caller="ops_scheduler",
                operation=D1SyncNow.operation,
                purpose="sync_current",
            ),
            {"expected_applied_cursor": 7, "environment": "production"},
            (),
        )

    monkeypatch.setattr(
        entrypoints,
        "_observe_d1_sync_tool_digest",
        lambda _resources: "sha256:" + "9" * 64,
    )
    with pytest.raises(service_runtime.LocalAuthorityError, match="tool binding changed"):
        handler(
            _context(
                caller="ops_scheduler",
                operation=D1SyncNow.operation,
                purpose="sync_current",
            ),
            {"expected_applied_cursor": 7},
            (),
        )


def test_d1_sync_sealer_rejects_forged_evidence_and_signs_only_bound_facts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    private, _registry_path, registry = _install_external_key_registry(
        tmp_path, monkeypatch
    )
    custody, _ = _custody(
        tmp_path,
        key_id="d1-sync-test-v1",
        private=private,
    )
    sealer = _D1SyncAuditSealer(custody, environment="production")
    monkeypatch.setattr(sealer, "preflight", lambda: None)
    with pytest.raises(service_runtime.LocalAuthorityError, match="opaque"):
        sealer(object())

    digest = "sha256:" + "a" * 64
    facts = {
        "sync_kind": "FULL",
        "export_digest": "sha256:" + "b" * 64,
        "artifact_format": "sql",
        "source_change_seq": 7,
        "applied_change_seq": 7,
        "source_content_digest": digest,
        "local_content_digest": digest,
        "source_schema_digest": "sha256:" + "c" * 64,
        "schema_digest": "sha256:" + "d" * 64,
        "table_counts": {"jquants_records": 1},
        "prior_audit_digest": None,
        "exported_at": d1_sync_signing._utc_now().isoformat(),
    }
    capability = object()

    def consume(observed):
        assert observed is capability
        return facts

    monkeypatch.setattr(
        sync_runtime._private_export,
        "_consume_authenticated_export_for_authority",
        consume,
    )
    monkeypatch.setattr(sealer, "preflight", lambda: None)
    sealed = sealer(capability)
    audit_digest, key_id, signature, document = sealed._consume_for_persistence()
    assert audit_digest == d1_sync_signing.d1_sync_digest(document)
    assert key_id == "d1-sync-test-v1"
    assert signature.startswith("ed25519:")
    assert document["envelope"]["registry_digest"] == d1_sync_signing.d1_sync_digest(
        registry
    )
    assert d1_sync_signing.verify_signed_d1_sync_audit(
        document, expected_environment="production"
    )[
        "applied_change_seq"
    ] == 7


class _SimulatedD1SyncCrash(BaseException):
    """Bypass ordinary exception cleanup exactly like process termination."""


class _FakeD1SyncSealer:
    def preflight(self) -> None:
        return None

    def __call__(self, _capability: object) -> object:
        return object()


def _read_atomic_marker(path: Path) -> str:
    with sqlite3.connect(path) as conn:
        row = conn.execute("SELECT value FROM atomic_sync_marker").fetchone()
    assert row is not None
    return str(row[0])


def _install_atomic_sync_harness(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[Path, Callable[..., object], dict[str, int]]:
    live = tmp_path / "governed.sqlite3"
    with sqlite3.connect(live) as conn:
        conn.execute("CREATE TABLE atomic_sync_marker (value TEXT NOT NULL)")
        conn.execute("INSERT INTO atomic_sync_marker VALUES ('old')")
    live.chmod(0o600)
    export_digest = "sha256:" + "e" * 64
    calls = {"acquire": 0}

    class Acquired:
        artifact_format = "sql"

        def __init__(self) -> None:
            self.export_digest = export_digest
            self._source = sqlite3.connect(":memory:")
            self._opened = False

        def open_source(self) -> sqlite3.Connection:
            assert not self._opened
            self._opened = True
            return self._source

    def acquire(*_args, **_kwargs):
        calls["acquire"] += 1
        return Acquired()

    def run_sync(
        store,
        _source,
        _tables,
        _args,
        *,
        seal_authenticated_export,
        **_kwargs,
    ):
        if sync_runtime._last_change_seq(store) == 1:
            return 0, 0, 0, []
        store._conn.execute("UPDATE atomic_sync_marker SET value='new'")
        sync_runtime._record_change_seq(store, 1)
        store._conn.commit()
        seal_authenticated_export(object())
        return 9, 8, 1, []

    def identity(conn: sqlite3.Connection) -> dict[str, object]:
        marker = conn.execute("SELECT value FROM atomic_sync_marker").fetchone()
        assert marker is not None and marker[0] == "new"
        return {
            "environment": "production",
            "resource_identity": {"test": "governed-d1"},
            "audit_digest": "sha256:" + "a" * 64,
            "issuer_key_id": "d1-sync-test-v1",
            "export_digest": export_digest,
            "source_change_seq": 1,
            "applied_change_seq": 1,
            "source_content_digest": "sha256:" + "b" * 64,
            "local_content_digest": "sha256:" + "b" * 64,
            "source_schema_digest": "sha256:" + "c" * 64,
            "schema_digest": "sha256:" + "d" * 64,
            "table_counts": {"atomic_sync_marker": 1},
        }

    def freeze(store) -> None:
        store._conn.commit()
        sync_runtime._freeze_authenticated_applied_mirror_storage(store._conn)

    monkeypatch.setattr(
        sync_runtime._private_export,
        "_acquire_pinned_wrangler_export_with_preflight",
        acquire,
    )
    monkeypatch.setattr(sync_runtime, "_run_private_export_sync", run_sync)
    monkeypatch.setattr(sync_runtime, "_finalize_sync_policy", lambda *_a, **_k: None)
    monkeypatch.setattr(
        sync_runtime,
        "_freeze_authenticated_current_applied_mirror",
        freeze,
    )
    monkeypatch.setattr(
        sync_runtime,
        "_authenticated_applied_mirror_identity_from_conn",
        identity,
    )

    def read_candidate(path: Path, *, require_fresh: bool = True):
        del require_fresh
        entrypoints._require_no_sqlite_sidecars(path)
        with sqlite3.connect(path) as conn:
            return identity(conn)

    monkeypatch.setattr(entrypoints, "_read_candidate_sync_identity", read_candidate)

    def execute(
        *,
        environment: str = "production",
        source_sha: str = "sha256:" + "1" * 64,
        tool_digest: str = "sha256:" + "2" * 64,
        expected_applied_cursor: int = 0,
        request_context: service_runtime.AuthorityRequestContext | None = None,
        runtime_identity_observer: Callable[[], object] | None = None,
        committed_event_verifier: Callable[..., bool] | None = None,
        fault=None,
    ):
        request = {
            "format": service_runtime.REQUEST_FORMAT,
            "request_id": f"atomic-sync-{expected_applied_cursor}",
            "operation": "d1_sync:sync_now",
            "purpose": "sync_current",
            "payload": {"expected_applied_cursor": expected_applied_cursor},
        }
        context = request_context or _context(
            caller="ops_scheduler",
            operation="d1_sync:sync_now",
            purpose="sync_current",
            request_id=request["request_id"],
            request_digest=service_runtime.sha256_digest(request),
        )
        observer = runtime_identity_observer or (
            lambda: {
                "source_sha": source_sha,
                "tool_digest": tool_digest,
                "policy_digest": entrypoints._d1_sync_policy_digest(
                    environment=environment,
                    source_sha=source_sha,
                    tool_digest=tool_digest,
                ),
            }
        )
        return _execute_governed_remote_sync(
            governed_db_path=live,
            expected_applied_cursor=expected_applied_cursor,
            credential_token="x" * 32,
            node_executable_path=tmp_path / "node",
            wrangler_cli_path=tmp_path / "wrangler.js",
            wrangler_config_path=tmp_path / "wrangler.toml",
            sealer=_FakeD1SyncSealer(),
            environment=environment,
            source_sha=source_sha,
            tool_digest=tool_digest,
            request_context=context,
            runtime_identity_observer=observer,
            committed_event_verifier=(
                committed_event_verifier or (lambda **_kwargs: True)
            ),
            _fault_inject=fault,
        )

    return live, execute, calls


@pytest.mark.parametrize(
    "crash_point,live_after_crash,expected_acquisitions",
    [
        ("after_prepared", "old", 1),
        ("after_acquisition", "old", 2),
        ("after_temp_apply", "old", 2),
        ("after_signed_audit", "old", 2),
        ("after_file_fsync", "old", 1),
        ("after_replace_before_dir_fsync", "new", 1),
    ],
)
def test_d1_sync_crash_recovery_preserves_or_completes_exact_candidate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    crash_point: str,
    live_after_crash: str,
    expected_acquisitions: int,
) -> None:
    live, execute, calls = _install_atomic_sync_harness(tmp_path, monkeypatch)

    def crash(point: str) -> None:
        if point == crash_point:
            raise _SimulatedD1SyncCrash(point)

    with pytest.raises(_SimulatedD1SyncCrash, match=crash_point):
        execute(fault=crash)
    assert _read_atomic_marker(live) == live_after_crash

    result = execute()
    assert result == {
        "status": "SYNCED",
        "prior_applied_cursor": 0,
        "source_change_seq": 1,
        "applied_change_seq": 1,
        "audit_digest": "sha256:" + "a" * 64,
        "export_digest": "sha256:" + "e" * 64,
        "issuer_key_id": "d1-sync-test-v1",
        "seen": 9,
        "registered": 8,
        "skipped": 1,
    }
    assert _read_atomic_marker(live) == "new"
    assert calls["acquire"] == expected_acquisitions
    journal, _lock = _d1_sync_paths(live)
    assert _read_d1_sync_journal(journal)["phase"] == "COMMITTED"
    assert execute() == result
    assert _read_d1_sync_journal(journal)["phase"] == "COMMITTED"
    assert execute() == result
    assert _read_d1_sync_journal(journal)["phase"] == "COMMITTED"
    execute(expected_applied_cursor=1)
    assert not journal.exists()
    assert not list(tmp_path.glob(f".{live.name}.d1-sync-*.sqlite3"))


@pytest.mark.parametrize("publication_state", ["unpublished", "linked"])
def test_d1_sync_recovers_every_initial_journal_publication_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    publication_state: str,
) -> None:
    live, execute, calls = _install_atomic_sync_harness(tmp_path, monkeypatch)

    def crash(point: str) -> None:
        if point == "after_prepared":
            raise _SimulatedD1SyncCrash(point)

    with pytest.raises(_SimulatedD1SyncCrash):
        execute(fault=crash)
    journal, _lock = _d1_sync_paths(live)
    staging = entrypoints._d1_sync_create_staging_path(journal)
    if publication_state == "unpublished":
        os.replace(journal, staging)
    else:
        os.link(journal, staging)
    entrypoints._fsync_directory(tmp_path)

    assert execute()["applied_change_seq"] == 1
    assert _read_atomic_marker(live) == "new"
    assert not staging.exists()
    assert calls["acquire"] == 1


def test_d1_sync_discards_torn_unpublished_journal_without_touching_live(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    live, execute, calls = _install_atomic_sync_harness(tmp_path, monkeypatch)
    journal, _lock = _d1_sync_paths(live)
    staging = entrypoints._d1_sync_create_staging_path(journal)
    staging.write_bytes(b'{"format":"d1-sync-atomic-replace/v2"')
    staging.chmod(0o600)
    entrypoints._fsync_file(staging)
    entrypoints._fsync_directory(tmp_path)

    assert _read_atomic_marker(live) == "old"
    assert execute()["applied_change_seq"] == 1
    assert _read_atomic_marker(live) == "new"
    assert not staging.exists()
    assert calls["acquire"] == 1


@pytest.mark.parametrize("changed_field", ["source_sha", "tool_digest", "policy_digest"])
def test_d1_sync_rejects_activation_drift_after_acquisition_without_live_mutation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    changed_field: str,
) -> None:
    live, execute, calls = _install_atomic_sync_harness(tmp_path, monkeypatch)
    expected = {
        "source_sha": "sha256:" + "1" * 64,
        "tool_digest": "sha256:" + "2" * 64,
        "policy_digest": entrypoints._d1_sync_policy_digest(
            environment="production",
            source_sha="sha256:" + "1" * 64,
            tool_digest="sha256:" + "2" * 64,
        ),
    }

    def drifted() -> dict[str, str]:
        observed = dict(expected)
        observed[changed_field] = "sha256:" + "9" * 64
        return observed

    with pytest.raises(
        service_runtime.LocalAuthorityError, match="activation identity changed"
    ):
        execute(runtime_identity_observer=drifted)
    assert _read_atomic_marker(live) == "old"
    journal, _lock = _d1_sync_paths(live)
    assert not journal.exists()
    assert calls["acquire"] == 1


def test_d1_sync_rechecks_activation_and_deadline_at_irreversible_handoff(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    live, execute, _calls = _install_atomic_sync_harness(tmp_path, monkeypatch)
    source_sha = "sha256:" + "1" * 64
    tool_digest = "sha256:" + "2" * 64
    expected = {
        "source_sha": source_sha,
        "tool_digest": tool_digest,
        "policy_digest": entrypoints._d1_sync_policy_digest(
            environment="production",
            source_sha=source_sha,
            tool_digest=tool_digest,
        ),
    }
    observations = 0

    def drift_before_handoff() -> dict[str, str]:
        nonlocal observations
        observations += 1
        observed = dict(expected)
        if observations == 2:
            observed["policy_digest"] = "sha256:" + "8" * 64
        return observed

    with pytest.raises(
        service_runtime.LocalAuthorityError, match="activation identity changed"
    ):
        execute(runtime_identity_observer=drift_before_handoff)
    assert _read_atomic_marker(live) == "old"
    journal, _lock = _d1_sync_paths(live)
    assert _read_d1_sync_journal(journal)["phase"] == "FILE_FSYNCED"
    assert observations == 2

    clock = {"now": 2}
    monkeypatch.setattr(
        service_runtime.time, "monotonic_ns", lambda: clock["now"]
    )
    request = {
        "format": service_runtime.REQUEST_FORMAT,
        "request_id": "atomic-sync-0",
        "operation": "d1_sync:sync_now",
        "purpose": "sync_current",
        "payload": {"expected_applied_cursor": 0},
    }
    expired = _context(
        caller="ops_scheduler",
        operation="d1_sync:sync_now",
        purpose="sync_current",
        request_id=request["request_id"],
        request_digest=service_runtime.sha256_digest(request),
        deadline_monotonic_ns=100,
    )
    clock["now"] = 101
    with pytest.raises(
        service_runtime.LocalAuthorityError, match="processing deadline exceeded"
    ):
        execute(request_context=expired)
    assert _read_atomic_marker(live) == "old"
    assert _read_d1_sync_journal(journal)["phase"] == "FILE_FSYNCED"


def test_d1_sync_main_handoff_rejects_expired_request_lease(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    live, execute, _calls = _install_atomic_sync_harness(tmp_path, monkeypatch)
    clock = {"now": 2}
    monkeypatch.setattr(
        service_runtime.time, "monotonic_ns", lambda: clock["now"]
    )
    request = {
        "format": service_runtime.REQUEST_FORMAT,
        "request_id": "atomic-sync-0",
        "operation": "d1_sync:sync_now",
        "purpose": "sync_current",
        "payload": {"expected_applied_cursor": 0},
    }
    context = _context(
        caller="ops_scheduler",
        operation="d1_sync:sync_now",
        purpose="sync_current",
        request_id=request["request_id"],
        request_digest=service_runtime.sha256_digest(request),
        deadline_monotonic_ns=100,
    )

    def expire_after_file_fsync(point: str) -> None:
        if point == "after_file_fsync":
            clock["now"] = 101

    with pytest.raises(
        service_runtime.LocalAuthorityError, match="processing deadline exceeded"
    ):
        execute(request_context=context, fault=expire_after_file_fsync)
    assert _read_atomic_marker(live) == "old"
    journal, _lock = _d1_sync_paths(live)
    assert _read_d1_sync_journal(journal)["phase"] == "FILE_FSYNCED"


@pytest.mark.parametrize("target", ["live", "candidate"])
def test_d1_sync_rejects_dangling_sqlite_sidecar_symlinks(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    target: str,
) -> None:
    live, execute, calls = _install_atomic_sync_harness(tmp_path, monkeypatch)
    journal, _lock = _d1_sync_paths(live)
    if target == "candidate":
        def crash(point: str) -> None:
            if point == "after_file_fsync":
                raise _SimulatedD1SyncCrash(point)

        with pytest.raises(_SimulatedD1SyncCrash):
            execute(fault=crash)
        record = _read_d1_sync_journal(journal)
        assert record is not None
        sidecar_base = Path(record["candidate_path"])
    else:
        sidecar_base = live
    dangling = Path(f"{sidecar_base}-wal")
    dangling.symlink_to(tmp_path / "does-not-exist")

    with pytest.raises(
        service_runtime.LocalAuthorityError, match="live SQLite sidecar"
    ):
        execute()
    assert os.path.lexists(dangling)
    assert _read_atomic_marker(live) == "old"
    assert calls["acquire"] == (1 if target == "candidate" else 0)


def test_d1_sync_committed_replay_survives_repeated_outer_ledger_crashes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    live, execute, calls = _install_atomic_sync_harness(tmp_path, monkeypatch)
    ledger = _ledger(tmp_path, "d1_sync")
    request = {
        "format": service_runtime.REQUEST_FORMAT,
        "request_id": "d1-sync-outer-crash-replay",
        "operation": "d1_sync:sync_now",
        "purpose": "sync_current",
        "payload": {"expected_applied_cursor": 0},
    }
    context = _context(
        caller="ops_scheduler",
        operation="d1_sync:sync_now",
        purpose="sync_current",
        request_id=request["request_id"],
        request_digest=service_runtime.sha256_digest(request),
    )
    next_request = {
        "format": service_runtime.REQUEST_FORMAT,
        "request_id": "d1-sync-after-outer-crash",
        "operation": "d1_sync:sync_now",
        "purpose": "sync_current",
        "payload": {"expected_applied_cursor": 1},
    }
    next_context = _context(
        caller="ops_scheduler",
        operation="d1_sync:sync_now",
        purpose="sync_current",
        request_id=next_request["request_id"],
        request_digest=service_runtime.sha256_digest(next_request),
    )

    def crash_after_handler_effect() -> object:
        execute(
            request_context=context,
            committed_event_verifier=ledger.has_exact_committed_event,
        )
        raise _SimulatedD1SyncCrash("after handler effect")

    for _attempt in range(3):
        with pytest.raises(_SimulatedD1SyncCrash, match="after handler effect"):
            ledger.execute_once(
                request=request,
                caller="ops_scheduler",
                operation="d1_sync:sync_now",
                purpose="sync_current",
                produce=crash_after_handler_effect,
            )
        journal, _lock = _d1_sync_paths(live)
        assert _read_d1_sync_journal(journal)["phase"] == "COMMITTED"

    # A different request cannot use the new cursor as a forged acknowledgement
    # while A's outer transaction is still absent.
    with pytest.raises(
        service_runtime.LocalAuthorityPending,
        match="awaits its exact outer event commit",
    ):
        ledger.execute_once(
            request=next_request,
            caller="ops_scheduler",
            operation="d1_sync:sync_now",
            purpose="sync_current",
            produce=lambda: execute(
                expected_applied_cursor=1,
                request_context=next_context,
                committed_event_verifier=ledger.has_exact_committed_event,
            ),
        )
    assert _read_d1_sync_journal(journal)["phase"] == "COMMITTED"
    assert _read_atomic_marker(live) == "new"

    result = ledger.execute_once(
        request=request,
        caller="ops_scheduler",
        operation="d1_sync:sync_now",
        purpose="sync_current",
        produce=lambda: execute(
            request_context=context,
            committed_event_verifier=ledger.has_exact_committed_event,
        ),
    )
    assert result["applied_change_seq"] == 1
    assert calls["acquire"] == 1
    assert _read_d1_sync_journal(journal)["phase"] == "COMMITTED"

    # Once A's exact request/result event is committed, B may consume the
    # receipt and perform its own no-change acquisition.
    next_result = ledger.execute_once(
        request=next_request,
        caller="ops_scheduler",
        operation="d1_sync:sync_now",
        purpose="sync_current",
        produce=lambda: execute(
            expected_applied_cursor=1,
            request_context=next_context,
            committed_event_verifier=ledger.has_exact_committed_event,
        ),
    )
    assert next_result["applied_change_seq"] == 1
    assert not journal.exists()


def test_d1_sync_file_fsynced_recovery_rejects_live_wal_without_mutation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    live, execute, calls = _install_atomic_sync_harness(tmp_path, monkeypatch)

    def crash(point: str) -> None:
        if point == "after_file_fsync":
            raise _SimulatedD1SyncCrash(point)

    with pytest.raises(_SimulatedD1SyncCrash, match="after_file_fsync"):
        execute(fault=crash)
    journal_path, _lock_path = _d1_sync_paths(live)
    journal = _read_d1_sync_journal(journal_path)
    assert journal is not None and journal["phase"] == "FILE_FSYNCED"
    candidate = Path(journal["candidate_path"])
    prior_live_identity = entrypoints._measure_d1_sync_file(live)
    candidate_identity = entrypoints._measure_d1_sync_file(candidate)

    wal = Path(f"{live}-wal")
    wal.write_bytes(b"stale-or-concurrent-wal")
    wal.chmod(0o600)
    with pytest.raises(
        service_runtime.LocalAuthorityError, match="live SQLite sidecar"
    ):
        execute()

    assert entrypoints._measure_d1_sync_file(live) == prior_live_identity
    assert entrypoints._measure_d1_sync_file(candidate) == candidate_identity
    assert _read_d1_sync_journal(journal_path) == journal
    assert wal.read_bytes() == b"stale-or-concurrent-wal"
    assert calls["acquire"] == 1

    wal.unlink()
    assert execute()["applied_change_seq"] == 1
    assert _read_atomic_marker(live) == "new"


def test_d1_sync_file_fsynced_recovery_rejects_dangling_candidate_symlink(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    live, execute, calls = _install_atomic_sync_harness(tmp_path, monkeypatch)

    def crash(point: str) -> None:
        if point == "after_file_fsync":
            raise _SimulatedD1SyncCrash(point)

    with pytest.raises(_SimulatedD1SyncCrash, match="after_file_fsync"):
        execute(fault=crash)
    journal_path, _lock_path = _d1_sync_paths(live)
    journal = _read_d1_sync_journal(journal_path)
    assert journal is not None and journal["phase"] == "FILE_FSYNCED"
    candidate = Path(journal["candidate_path"])
    candidate.unlink()
    candidate.symlink_to(tmp_path / "does-not-exist")
    prior_live_identity = entrypoints._measure_d1_sync_file(live)

    with pytest.raises(
        service_runtime.LocalAuthorityError, match="mirror cannot be opened"
    ):
        execute()

    assert candidate.is_symlink()
    assert entrypoints._measure_d1_sync_file(live) == prior_live_identity
    assert _read_d1_sync_journal(journal_path) == journal
    assert calls["acquire"] == 1


def _rewrite_sync_journal(path: Path, **updates: object) -> None:
    journal = _read_d1_sync_journal(path)
    assert journal is not None
    journal.update(updates)
    journal["record_digest"] = None
    _write_d1_sync_journal(path, journal, create_only=False)


def test_d1_sync_journal_transition_orders_file_fsync_replace_and_dir_fsync(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    live, execute, _calls = _install_atomic_sync_harness(tmp_path, monkeypatch)

    def crash(point: str) -> None:
        if point == "after_prepared":
            raise _SimulatedD1SyncCrash(point)

    with pytest.raises(_SimulatedD1SyncCrash):
        execute(fault=crash)
    journal_path, _lock_path = _d1_sync_paths(live)
    journal = _read_d1_sync_journal(journal_path)
    assert journal is not None

    events: list[str] = []
    real_fsync = os.fsync
    real_replace = os.replace

    def traced_fsync(fd: int) -> None:
        kind = "dir-fsync" if stat.S_ISDIR(os.fstat(fd).st_mode) else "file-fsync"
        events.append(kind)
        real_fsync(fd)

    def traced_replace(source, destination) -> None:
        events.append("replace")
        real_replace(source, destination)

    monkeypatch.setattr(entrypoints.os, "fsync", traced_fsync)
    monkeypatch.setattr(entrypoints.os, "replace", traced_replace)
    _advance_d1_sync_journal(
        journal_path,
        journal,
        phase="ACQUIRED",
        export_digest="sha256:" + "e" * 64,
        artifact_format="sql",
    )
    assert events == ["file-fsync", "replace", "dir-fsync"]


@pytest.mark.parametrize(
    "tamper,expected_message",
    [
        ("environment", "environment binding differs"),
        ("source", "source_sha binding differs"),
        ("tool", "tool_digest binding differs"),
        ("policy", "policy_digest binding differs"),
        ("export", "candidate identity differs"),
        ("live", "ambiguous live mirror"),
        ("candidate", "candidate identity differs"),
        ("stale", "journal is stale"),
    ],
)
def test_d1_sync_recovery_rejects_stale_or_cross_bound_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    tamper: str,
    expected_message: str,
) -> None:
    live, execute, _calls = _install_atomic_sync_harness(tmp_path, monkeypatch)

    def crash(point: str) -> None:
        if point == "after_file_fsync":
            raise _SimulatedD1SyncCrash(point)

    with pytest.raises(_SimulatedD1SyncCrash):
        execute(fault=crash)
    journal_path, _lock_path = _d1_sync_paths(live)
    journal = _read_d1_sync_journal(journal_path)
    assert journal is not None
    candidate = Path(journal["candidate_path"])

    kwargs: dict[str, object] = {}
    if tamper == "environment":
        kwargs["environment"] = "staging"
        kwargs["request_context"] = _context(
            caller="ops_scheduler",
            operation="d1_sync:sync_now",
            purpose="sync_current",
            request_id="atomic-sync-0",
            request_digest=service_runtime.sha256_digest(
                {
                    "format": service_runtime.REQUEST_FORMAT,
                    "request_id": "atomic-sync-0",
                    "operation": "d1_sync:sync_now",
                    "purpose": "sync_current",
                    "payload": {"expected_applied_cursor": 0},
                }
            ),
            environment="staging",
        )
    elif tamper == "source":
        kwargs["source_sha"] = "sha256:" + "3" * 64
    elif tamper == "tool":
        kwargs["tool_digest"] = "sha256:" + "4" * 64
    elif tamper == "policy":
        monkeypatch.setattr(
            "scripts.local_authority_entrypoints._d1_sync_policy_digest",
            lambda **_kwargs: "sha256:" + "5" * 64,
        )
    elif tamper == "export":
        tampered_result = dict(journal["sync_result"])
        tampered_result["export_digest"] = "sha256:" + "6" * 64
        _rewrite_sync_journal(
            journal_path,
            export_digest="sha256:" + "6" * 64,
            sync_result=tampered_result,
            outer_result_digest=service_runtime.sha256_digest(tampered_result),
        )
    elif tamper == "live":
        with sqlite3.connect(live) as conn:
            conn.execute("UPDATE atomic_sync_marker SET value='tampered-live'")
    elif tamper == "candidate":
        with sqlite3.connect(candidate) as conn:
            conn.execute("UPDATE atomic_sync_marker SET value='tampered-candidate'")
    elif tamper == "stale":
        stale = "2000-01-01T00:00:00+00:00"
        journal.update(prepared_at=stale, updated_at=stale)
        journal["record_digest"] = _d1_sync_record_digest(journal)
        journal_path.write_text(
            json.dumps(
                journal,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            )
            + "\n",
            encoding="utf-8",
        )
    else:  # pragma: no cover - closed parametrization
        raise AssertionError(tamper)

    with pytest.raises(service_runtime.LocalAuthorityError, match=expected_message):
        execute(**kwargs)
    assert journal_path.exists()
    assert _read_atomic_marker(live) in {"old", "tampered-live"}


def test_d1_owned_ops_flow_renders_and_signs_exact_received_inode(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "applied.sqlite"
    _projection_source(source)
    source.chmod(0o600)
    with sqlite3.connect(source) as conn:
        identity = _test_mirror_identity()(conn)
    _fake_mirror_authority(monkeypatch, source, identity)
    custody, private = _custody(tmp_path, key_id="ops-authority-test-v1")
    artifact_store = tmp_path / "ops-artifacts"
    artifact_store.mkdir(mode=0o700)
    monkeypatch.setattr(exporter, "_now", lambda: FIXED_NOW)
    monkeypatch.setattr(
        projection_signing,
        "_load_pinned_active_keys",
        lambda _environment="production": {custody.key_id: private.public_key()},
    )
    monkeypatch.setattr(
        service_runtime, "require_pinned_finding_ledger_gate", lambda: object()
    )
    socket_path, listener = _listener(tmp_path, "ops")
    service = service_runtime.UnixAuthorityService(
        authority_id="ops_projection",
        environment="production",
        peers=service_runtime.PeerPrincipalRegistry({os.geteuid(): "d1_sync"}),
        ledger=_ledger(tmp_path, "ops_projection"),
        handlers={
            OpsProjectionRenderAndSign.operation: OpsProjectionRenderAndSign(
                environment="production",
                custody=custody,
                artifact_store=artifact_store,
                expected_d1_uid=os.geteuid(),
            )
        },
    )
    worker = threading.Thread(target=_serve_once, args=(listener, service))
    worker.start()
    try:
        result = D1FreezeAndRenderOpsProjection(
            environment="production",
            governed_db_path=source,
            ops_socket_path=socket_path,
            ops_uid=os.geteuid(),
        )(
            _context(
                caller="ops_scheduler",
                operation=D1FreezeAndRenderOpsProjection.operation,
                purpose="ops_projection_from_owned_mirror",
            ),
            {},
            (),
        )
    finally:
        worker.join(timeout=10)
        listener.close()
        socket_path.unlink(missing_ok=True)
    assert not worker.is_alive()
    assert result["status"] == "SIGNED"
    assert (artifact_store / result["signed_artifact"]).is_file()
    assert not list(artifact_store.glob("ops-projection-candidate-*.json"))
    assert not any(key.startswith("candidate_") for key in result)
    signed = base64.b64decode(result["signed_document_base64"], validate=True)
    envelope = projection_signing._verify_document(
        signed, {custody.key_id: private.public_key()}
    )
    assert (envelope["source_cursor"], envelope["applied_cursor"]) == (7, 7)


def test_ops_service_rejects_scheduler_self_crafted_fd_before_handler(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "forged.sqlite"
    sqlite3.connect(source).close()
    source.chmod(0o600)
    fd = os.open(source, os.O_RDONLY)
    called = False

    def handler(_context, _payload, _fds):
        nonlocal called
        called = True
        return {"status": "UNSAFE"}

    monkeypatch.setattr(
        service_runtime, "require_pinned_finding_ledger_gate", lambda: object()
    )
    service = service_runtime.UnixAuthorityService(
        authority_id="ops_projection",
        environment="production",
        peers=service_runtime.PeerPrincipalRegistry({os.geteuid(): "ops_scheduler"}),
        ledger=_ledger(tmp_path, "ops_projection"),
        handlers={OpsProjectionRenderAndSign.operation: handler},
    )
    server, client = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
    worker = threading.Thread(target=service.serve_connection, args=(server,))
    worker.start()
    request = {
        "format": service_runtime.REQUEST_FORMAT,
        "request_id": "forged-scheduler-request",
        "operation": OpsProjectionRenderAndSign.operation,
        "purpose": "render_owned_mirror_projection",
        "payload": {"owned_mirror_evidence": {}, "selector": {}},
    }
    body = service_runtime.canonical_json_bytes(request)
    rights = array.array("i", [fd])
    client.sendmsg(
        [struct.pack("!I", len(body))],
        [(socket.SOL_SOCKET, socket.SCM_RIGHTS, rights.tobytes())],
    )
    client.sendall(body)
    size = struct.unpack("!I", client.recv(4, socket.MSG_WAITALL))[0]
    response = json.loads(client.recv(size, socket.MSG_WAITALL))
    worker.join(timeout=5)
    client.close()
    server.close()
    os.close(fd)
    assert response["status"] == "REJECTED"
    assert response["request_id"] == "forged-scheduler-request"
    assert called is False


def test_d1_handoff_never_accepts_unsigned_projection_candidate_as_authority_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "applied.sqlite"
    _projection_source(source)
    source.chmod(0o600)
    with sqlite3.connect(source) as conn:
        identity = _test_mirror_identity()(conn)
    _fake_mirror_authority(monkeypatch, source, identity)
    monkeypatch.setattr(
        service_runtime, "require_pinned_finding_ledger_gate", lambda: object()
    )
    socket_path, listener = _listener(tmp_path, "unsigned-ops")
    service = service_runtime.UnixAuthorityService(
        authority_id="ops_projection",
        environment="production",
        peers=service_runtime.PeerPrincipalRegistry({os.geteuid(): "d1_sync"}),
        ledger=_ledger(tmp_path, "ops-projection-unsigned"),
        handlers={
            OpsProjectionRenderAndSign.operation: (
                lambda _context, _payload, _fds: {
                    "status": "CANDIDATE",
                    "projection": {"ordinary": True},
                }
            )
        },
    )
    worker = threading.Thread(target=_serve_once, args=(listener, service))
    worker.start()
    try:
        with pytest.raises(
            service_runtime.LocalAuthorityError,
            match="closed signed document",
        ):
            D1FreezeAndRenderOpsProjection(
                environment="production",
                governed_db_path=source,
                ops_socket_path=socket_path,
                ops_uid=os.geteuid(),
            )(
                _context(
                    caller="ops_scheduler",
                    operation=D1FreezeAndRenderOpsProjection.operation,
                    purpose="ops_projection_from_owned_mirror",
                ),
                {},
                (),
            )
    finally:
        worker.join(timeout=10)
        listener.close()
        socket_path.unlink(missing_ok=True)
    assert not worker.is_alive()


def test_d1_coverage_flow_signs_then_cas_applies_without_nested_callback(
    tmp_path: Path,
    receipt_ed25519_keys,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database = tmp_path / "coverage.sqlite"
    _prepare_transition_db(
        database,
        datasets=_DATASETS,
        receipt_signing_key=receipt_ed25519_keys.signing_key,
    )
    database.chmod(0o600)
    identity = _synthetic_sync_identity()
    _fake_mirror_authority(monkeypatch, database, identity)
    private = Ed25519PrivateKey.generate()
    custody, _ = _custody(
        tmp_path, key_id="coverage-authority-test-v1", private=private
    )
    _configure_test_registry(monkeypatch, _registry_for(custody.key_id, private))
    monkeypatch.setattr(
        service_runtime, "require_pinned_finding_ledger_gate", lambda: object()
    )
    socket_path, listener = _listener(tmp_path, "coverage")
    service = service_runtime.UnixAuthorityService(
        authority_id="coverage_transition",
        environment="production",
        peers=service_runtime.PeerPrincipalRegistry({os.geteuid(): "d1_sync"}),
        ledger=_ledger(tmp_path, "coverage_transition"),
        handlers={
            CoverageTransitionAuthorize.operation: CoverageTransitionAuthorize(
                environment="production",
                custody=custody,
                expected_d1_uid=os.geteuid(),
            )
        },
    )
    worker = threading.Thread(target=_serve_once, args=(listener, service))
    worker.start()
    try:
        result = D1FreezeAuthorizeApplyCoverage(
            environment="production",
            governed_db_path=database,
            coverage_socket_path=socket_path,
            coverage_uid=os.geteuid(),
        )(
            _context(
                caller="coverage_scheduler",
                operation=D1FreezeAuthorizeApplyCoverage.operation,
                purpose="coverage_transition_from_owned_mirror",
            ),
            {"build_id": _BUILD_ID, "datasets": list(_DATASETS)},
            (),
        )
    finally:
        worker.join(timeout=10)
        listener.close()
        socket_path.unlink(missing_ok=True)
    assert not worker.is_alive()
    assert result["status"] == "COMPLETE"
    with sqlite3.connect(database) as conn:
        assert conn.execute(
            "SELECT status FROM dataset_coverage WHERE dataset=?", _DATASETS
        ).fetchone() == ("COMPLETE",)
        assert conn.execute(
            "SELECT COUNT(*) FROM coverage_complete_transition_tombstones"
        ).fetchone() == (1,)


def _synthetic_sync_identity() -> dict[str, object]:
    return {
        "environment": "production",
        "resource_identity": {
            "provider": "cloudflare",
            "kind": "d1",
            "name": "quant-ingest",
            "database_id": "be6fdcf8-40be-41fc-9535-7facd1fc2ffc",
            "authority_id": "cloudflare-d1:be6fdcf8-40be-41fc-9535-7facd1fc2ffc",
        },
        "audit_digest": "sha256:" + "1" * 64,
        "issuer_key_id": "d1-test-v1",
        "export_digest": "sha256:" + "2" * 64,
        "source_change_seq": 9,
        "applied_change_seq": 9,
        "source_content_digest": "sha256:" + "3" * 64,
        "local_content_digest": "sha256:" + "3" * 64,
        "source_schema_digest": "sha256:" + "4" * 64,
        "schema_digest": "sha256:" + "4" * 64,
        "table_counts": {},
    }


def test_coverage_authority_binds_fd_owner_inode_digest_and_purpose(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database = tmp_path / "identity.sqlite"
    with sqlite3.connect(database) as conn:
        conn.execute("CREATE TABLE marker(value INTEGER)")
    database.chmod(0o600)
    fd = os.open(database, os.O_RDONLY)
    identity = _synthetic_sync_identity()
    monkeypatch.setattr(
        protocol, "_remeasure_applied_mirror_identity", lambda _conn: identity
    )
    evidence = _owned_mirror_evidence(
        fd,
        environment="production",
        purpose="coverage_transition",
        governed_db_path=database.absolute(),
        sync_identity=identity,
    )
    evidence["purpose"] = "ops_projection"
    custody, _ = _custody(tmp_path, key_id="coverage-pending-v1")
    handler = CoverageTransitionAuthorize(
        environment="production", custody=custody, expected_d1_uid=os.geteuid()
    )
    try:
        with pytest.raises(service_runtime.LocalAuthorityError, match="identity"):
            handler(
                _context(
                    caller="d1_sync",
                    operation=CoverageTransitionAuthorize.operation,
                    purpose="coverage_v3_transition",
                ),
                {
                    "owned_mirror_evidence": evidence,
                    "selector": {"build_id": _BUILD_ID, "datasets": list(_DATASETS)},
                },
                (fd,),
            )
    finally:
        os.close(fd)


def test_coverage_pending_registry_does_not_mutate_live_state(
    tmp_path: Path,
    receipt_ed25519_keys,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database = tmp_path / "pending.sqlite"
    _prepare_transition_db(
        database,
        datasets=_DATASETS,
        receipt_signing_key=receipt_ed25519_keys.signing_key,
    )
    database.chmod(0o600)
    fd = os.open(database, os.O_RDONLY)
    identity = _synthetic_sync_identity()
    monkeypatch.setattr(
        protocol, "_remeasure_applied_mirror_identity", lambda _conn: identity
    )
    evidence = _owned_mirror_evidence(
        fd,
        environment="production",
        purpose="coverage_transition",
        governed_db_path=database.absolute(),
        sync_identity=identity,
    )
    custody, _ = _custody(tmp_path, key_id="coverage-pending-v1")
    monkeypatch.setattr(
        CoverageTransitionPublicKeyRegistry,
        "load_pinned",
            classmethod(
                lambda cls, **_kwargs: CoverageTransitionPublicKeyRegistry({})
            ),
    )
    handler = CoverageTransitionAuthorize(
        environment="production", custody=custody, expected_d1_uid=os.geteuid()
    )
    try:
        with pytest.raises(service_runtime.LocalAuthorityPending, match="activate"):
            handler(
                _context(
                    caller="d1_sync",
                    operation=CoverageTransitionAuthorize.operation,
                    purpose="coverage_v3_transition",
                ),
                {
                    "owned_mirror_evidence": evidence,
                    "selector": {"build_id": _BUILD_ID, "datasets": list(_DATASETS)},
                },
                (fd,),
            )
    finally:
        os.close(fd)
    with sqlite3.connect(database) as conn:
        assert conn.execute(
            "SELECT status FROM dataset_coverage WHERE dataset=?", _DATASETS
        ).fetchone() == ("PARTIAL",)


def test_ready_authority_rejects_caller_paths_and_unsigned_projection(
    tmp_path: Path,
) -> None:
    custody, _ = _custody(tmp_path, key_id="ready-pending-v1")
    handler = ReadyPublishProfilePlanBound(
        environment="production", snapshot_root=tmp_path, custody=custody
    )
    with pytest.raises(
        service_runtime.LocalAuthorityError, match="fields are not closed"
    ):
        handler(
            _context(
                caller="ready_publisher",
                operation=ReadyPublishProfilePlanBound.operation,
                purpose="profile_plan_closure_ready",
            ),
            {
                "snapshot_id": "sha256:" + "1" * 64,
                "signed_projection_base64": base64.b64encode(b"{}").decode(),
                "snapshot_path": "/tmp/caller-selected.sqlite",
            },
            (),
        )
    with pytest.raises(service_runtime.LocalAuthorityError):
        handler(
            _context(
                caller="ready_publisher",
                operation=ReadyPublishProfilePlanBound.operation,
                purpose="profile_plan_closure_ready",
            ),
            {
                "snapshot_id": "sha256:" + "1" * 64,
                "signed_projection_base64": base64.b64encode(b"{}").decode(),
            },
            (),
        )


def test_ready_authority_replays_ready_state_and_rejects_forged_scope(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The closed verifier accepts exact replay and rejects caller proof drift."""

    from cf_platform.ingest_premium import coverage as quality_runtime
    from data_contracts.coverage import coverage_policy_set_binding
    from paper_runtime import ready_policy, snapshot as snapshot_runtime
    from paper_runtime import snapshot_coverage_proof as coverage_runtime
    from paper_runtime import snapshot_publish_policy as publish_runtime
    from research import ready_manifest as manifest_runtime
    from research import research_data_profile as profile_runtime

    binding = manifest_runtime.load_exact_four_pilot_ready_binding()
    required = tuple(binding.required_datasets)
    projection_rows = {
        dataset_id: {
            "status": "COMPLETE",
            "observed_start": "1900-01-01",
            "observed_end": "9999-12-31",
            "source_generation": "7",
            "export_cursor": "7",
            "applied_cursor": "7",
        }
        for dataset_id in required
    }
    projection = SimpleNamespace(
        rows=projection_rows,
        signed_document_digest="sha256:" + "91" * 32,
    )
    dependency_scope = {
        "proof_digest": "sha256:" + "92" * 32,
        "universe_rule_digest": "sha256:" + "93" * 32,
        "resolved_universe_digest": "sha256:" + "94" * 32,
        "product_materialization_digest": "sha256:" + "95" * 32,
    }
    coverage_rows = [
        {
            "dataset": dataset_id,
            "status": "COMPLETE",
            "history_target_start": "1900-01-01",
            "history_target_end_rule": "tip",
            "coverage_mode": "TIP",
            "expected_frequency": "daily",
            "universe_rule": "governed",
            "governance_tier": "governed",
            "observed_start": "1900-01-01",
            "observed_end": "9999-12-31",
            "row_count": 1,
        }
        for dataset_id in required
    ]
    watermarks = [
        {
            "dataset": dataset_id,
            "last_event_date": "2026-08-25",
            "last_ingested_at": "2026-08-25T00:00:00Z",
        }
        for dataset_id in required
    ]
    coverage_proof = {
        "status": "COMPLETE",
        "proof_digest": "sha256:" + "96" * 32,
    }
    coverage_proof_id = "sha256:" + "97" * 32
    validations = [{"dataset": dataset_id, "status": "PASS"} for dataset_id in required]
    raw_manifests = {
        dataset_id: {"dataset": dataset_id, "completeness": "ACQUIRED"}
        for dataset_id in required
    }
    quality_results = [
        {"check_id": "B0", "dataset": "all", "status": "pass"},
        {"check_id": "B4", "dataset": "all", "status": "pass"},
    ]
    quality_summary = {"pass": 2, "fail": 0}
    ready_evidence = {"passed": True, "items": []}
    policy_set = coverage_policy_set_binding(list(required))
    build_id = "build-ready-replay"
    snapshot_id = "sha256:" + "98" * 32
    outer = {
        "build_id": build_id,
        "snapshot_id": snapshot_id,
        "source_run": {
            "id": 11,
            "started_at": "2026-08-25T00:00:00Z",
            "finished_at": "2026-08-25T00:01:00Z",
        },
        "coverage_policy_version": policy_set["policy_version"],
        "coverage_policy_digest": policy_set["policy_digest"],
        "quality_policy_version": snapshot_runtime.QUALITY_POLICY_VERSION,
        "required_datasets": list(required),
        "dataset_watermarks": watermarks,
        "coverage": coverage_rows,
        "coverage_proof": coverage_proof,
        "coverage_proof_id": coverage_proof_id,
        "quality": {
            "status": "PASS",
            "summary": quality_summary,
            "failures": [],
            "results": quality_results,
        },
        "ready_evidence": ready_evidence,
        "raw_manifests": raw_manifests,
        "validations": validations,
        "profile_coverage_evidence": projection_rows,
        "dependency_scope_evidence": dependency_scope,
    }
    retained_manifest = {
        "dataset_ids": list(required),
        "manifest_digest": "sha256:" + "99" * 32,
    }
    scratch = tmp_path / "ready-replay.sqlite"
    with sqlite3.connect(scratch) as connection:
        connection.execute(
            "CREATE TABLE snapshot_publications ("
            "build_id TEXT PRIMARY KEY,state TEXT,snapshot_id TEXT,"
            "manifest_json TEXT,artifact_path TEXT)"
        )
        connection.execute(
            "INSERT INTO snapshot_publications VALUES (?,?,?,?,?)",
            (
                build_id,
                "READY",
                snapshot_id,
                json.dumps(outer, sort_keys=True),
                "/original/immutable.sqlite",
            ),
        )

    monkeypatch.setattr(
        manifest_runtime,
        "load_exact_four_pilot_ready_binding",
        lambda: binding,
    )
    monkeypatch.setattr(
        manifest_runtime,
        "_verified_projection_evidence",
        lambda *_args, **_kwargs: projection,
    )
    monkeypatch.setattr(
        manifest_runtime,
        "_verify_exact_four_pit_dependency_scope",
        lambda *_args, **_kwargs: dependency_scope,
    )
    monkeypatch.setattr(
        manifest_runtime,
        "build_profile_bound_ready_manifest_from_snapshot_document",
        lambda *_args, **_kwargs: SimpleNamespace(
            to_dict=lambda: retained_manifest
        ),
    )
    monkeypatch.setattr(profile_runtime, "profile_ready", lambda *_args: True)
    monkeypatch.setattr(
        snapshot_runtime,
        "_latest_complete_run",
        lambda *_args: (
            11,
            {
                "startedAt": "2026-08-25T00:00:00Z",
                "finishedAt": "2026-08-25T00:01:00Z",
            },
            validations,
        ),
    )
    monkeypatch.setattr(snapshot_runtime, "_watermarks_for", lambda *_args: watermarks)
    monkeypatch.setattr(
        publish_runtime,
        "_raw_manifests_for",
        lambda *_args: raw_manifests,
    )
    monkeypatch.setattr(
        coverage_runtime,
        "_coverage_rows_for",
        lambda *_args: coverage_rows,
    )
    monkeypatch.setattr(
        coverage_runtime,
        "require_persisted_coverage_proof",
        lambda *_args, **_kwargs: SimpleNamespace(
            proof=coverage_proof,
            publication_cutoff="2026-08-25",
        ),
    )

    class _PolicyBundle:
        passed = True

        @staticmethod
        def failures() -> list[object]:
            return []

        @staticmethod
        def to_dict() -> dict[str, object]:
            return ready_evidence

    class _Policy:
        @staticmethod
        def evaluate(*_args, **_kwargs) -> _PolicyBundle:
            return _PolicyBundle()

    class _QualityCheck:
        def __init__(self, row: dict[str, str]) -> None:
            self._row = row

        def as_log_dict(self) -> dict[str, str]:
            return dict(self._row)

    monkeypatch.setattr(ready_policy, "ReadyPublicationPolicy", _Policy)
    monkeypatch.setattr(
        quality_runtime,
        "run_coverage",
        lambda *_args, **_kwargs: [_QualityCheck(row) for row in quality_results],
    )
    monkeypatch.setattr(
        quality_runtime,
        "summarize",
        lambda _checks: quality_summary,
    )

    request_context = _context(
        caller="ready_publisher",
        operation=ReadyPublishProfilePlanBound.operation,
        purpose="profile_plan_closure_ready",
    )
    replayed, observed_projection = (
        entrypoints._recompute_exact_four_ready_authority_proof(
            scratch,
            outer,
            retained_manifest,
            b"signed-projection",
            environment="production",
            request_context=request_context,
        )
    )
    assert replayed == retained_manifest
    assert observed_projection is projection
    with sqlite3.connect(scratch) as connection:
        state, locator = connection.execute(
            "SELECT state,artifact_path FROM snapshot_publications"
        ).fetchone()
    assert state == "READY"
    assert Path(locator) == scratch.resolve()

    forged = json.loads(json.dumps(outer))
    forged["dependency_scope_evidence"]["proof_digest"] = "sha256:" + "aa" * 32
    with sqlite3.connect(scratch) as connection:
        connection.execute(
            "UPDATE snapshot_publications SET manifest_json=?",
            (json.dumps(forged, sort_keys=True),),
        )
    with pytest.raises(
        service_runtime.LocalAuthorityError,
        match="dependency_scope_evidence differs",
    ):
        entrypoints._recompute_exact_four_ready_authority_proof(
            scratch,
            forged,
            retained_manifest,
            b"signed-projection",
            environment="production",
            request_context=request_context,
        )


def test_ready_handler_rejects_forged_proof_before_custody_sign(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    snapshot_id = "sha256:" + "ad" * 32
    artifact = tmp_path / f"sha256_{'ad' * 32}.sqlite"
    with sqlite3.connect(artifact) as connection:
        connection.execute("CREATE TABLE retained(value TEXT)")
    artifact.chmod(0o444)
    raw = artifact.read_bytes()
    digest = "sha256:" + hashlib.sha256(raw).hexdigest()
    info = artifact.stat()
    identity = (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns)
    forged_outer = {
        "dependency_scope_evidence": {"proof_digest": "sha256:" + "fe" * 32}
    }
    retained_manifest = {"dataset_ids": ["caller-forged"]}

    monkeypatch.setattr(
        entrypoints,
        "_load_ready_snapshot",
        lambda *_args, **_kwargs: (
            forged_outer,
            retained_manifest,
            digest,
            identity,
        ),
    )

    def reject_forgery(*_args, **_kwargs):
        raise service_runtime.LocalAuthorityError(
            "READY retained dependency_scope_evidence differs"
        )

    monkeypatch.setattr(
        entrypoints,
        "_recompute_exact_four_ready_authority_proof",
        reject_forgery,
    )

    def forbidden_sign(*_args, **_kwargs):
        raise AssertionError("custody must not sign caller-generated proof")

    monkeypatch.setattr(
        service_runtime.FileEd25519KeyCustody,
        "sign",
        forbidden_sign,
    )
    custody, _ = _custody(tmp_path, key_id="ready-forge-test-v1")
    handler = ReadyPublishProfilePlanBound(
        environment="production",
        snapshot_root=tmp_path,
        custody=custody,
    )
    with pytest.raises(
        service_runtime.LocalAuthorityError,
        match="dependency_scope_evidence differs",
    ):
        handler(
            _context(
                caller="ready_publisher",
                operation=ReadyPublishProfilePlanBound.operation,
                purpose="profile_plan_closure_ready",
            ),
            {
                "snapshot_id": snapshot_id,
                "signed_projection_base64": base64.b64encode(
                    b"signed projection"
                ).decode("ascii"),
            },
            (),
        )
