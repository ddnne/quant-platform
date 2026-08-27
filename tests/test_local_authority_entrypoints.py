"""Behavioral integration for the C4/C10/R5 local authority handlers."""

from __future__ import annotations

import array
import base64
import json
import os
import socket
import sqlite3
import struct
import threading
from pathlib import Path
from types import MappingProxyType

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from ops import d1_sync_signing, projection_signing
from storage.coverage_transition import CoverageTransitionPublicKeyRegistry

from scripts import authority_protocol_runtime as protocol
from scripts import export_ops_projection as exporter
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
    _owned_mirror_evidence,
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
    *, caller: str, operation: str, purpose: str
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
            environment="production",
        ),
        request_id="direct-handler-test",
        request_digest="sha256:" + "0" * 64,
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
        governed_db_path=database,
        cloudflare_token_path=credential,
        node_executable_path="/protected/node",
        wrangler_cli_path="/protected/wrangler.js",
        wrangler_config_path="/protected/wrangler.toml",
        custody=custody,
        expected_uid=os.geteuid(),
        executor=executor,
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
    sealer = _D1SyncAuditSealer(custody)
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
    assert d1_sync_signing.verify_signed_d1_sync_audit(document)[
        "applied_change_seq"
    ] == 7


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
        lambda: {custody.key_id: private.public_key()},
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
        classmethod(lambda cls: CoverageTransitionPublicKeyRegistry({})),
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
    handler = ReadyPublishProfilePlanBound(snapshot_root=tmp_path, custody=custody)
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
