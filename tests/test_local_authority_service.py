"""Behavioral invariants for the local authority process boundary."""

from __future__ import annotations

import array
import json
import os
import socket
import sqlite3
import struct
import threading
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from scripts import local_authority_service as authority


def _ledger(
    tmp_path: Path, authority_id: str = "ready"
) -> authority.SQLiteAuthorityEventLedger:
    store = tmp_path / authority_id
    store.mkdir(mode=0o700)
    ledger = authority.SQLiteAuthorityEventLedger(
        store / "authority-events.sqlite3",
        authority_id=authority_id,
        environment="staging",
        expected_uid=os.geteuid(),
    )
    ledger.initialize()
    return ledger


def _request(
    request_id: str = "request-1",
    *,
    operation: str = "ready:publish_profile_plan_bound",
    purpose: str = "profile_plan_closure_ready",
) -> dict[str, object]:
    return {
        "format": authority.REQUEST_FORMAT,
        "request_id": request_id,
        "operation": operation,
        "purpose": purpose,
        "payload": {"snapshot_id": "sha256:" + "1" * 64},
    }


def _serve_one(
    service: authority.UnixAuthorityService,
    request: dict[str, object],
) -> dict[str, object]:
    server, client = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
    worker = threading.Thread(target=service.serve_connection, args=(server,))
    worker.start()
    body = authority.canonical_json_bytes(request)
    client.sendall(struct.pack("!I", len(body)) + body)
    header = client.recv(4, socket.MSG_WAITALL)
    length = struct.unpack("!I", header)[0]
    raw = client.recv(length, socket.MSG_WAITALL)
    worker.join(timeout=5)
    client.close()
    server.close()
    assert not worker.is_alive()
    return json.loads(raw)


def test_ledger_commits_once_and_returns_byte_identical_retry(tmp_path: Path) -> None:
    ledger = _ledger(tmp_path)
    request = _request()
    calls = 0

    def produce() -> dict[str, object]:
        nonlocal calls
        calls += 1
        return {"status": "SIGNED", "artifact_digest": "sha256:" + "2" * 64}

    first = ledger.execute_once(
        request=request,
        caller="ready_publisher",
        operation="ready:publish_profile_plan_bound",
        purpose="profile_plan_closure_ready",
        produce=produce,
    )
    second = ledger.execute_once(
        request=request,
        caller="ready_publisher",
        operation="ready:publish_profile_plan_bound",
        purpose="profile_plan_closure_ready",
        produce=produce,
    )
    assert dict(first) == dict(second)
    assert calls == 1
    with sqlite3.connect(ledger.path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM authority_events").fetchone() == (1,)
        with pytest.raises(sqlite3.IntegrityError, match="immutable authority event"):
            conn.execute("DELETE FROM authority_events")


def test_ledger_rejects_request_id_rewrap_and_tampered_chain(tmp_path: Path) -> None:
    ledger = _ledger(tmp_path)
    original = _request()
    ledger.execute_once(
        request=original,
        caller="ready_publisher",
        operation="ready:publish_profile_plan_bound",
        purpose="profile_plan_closure_ready",
        produce=lambda: {"status": "SIGNED"},
    )
    changed = _request()
    changed["payload"] = {"snapshot_id": "sha256:" + "9" * 64}
    with pytest.raises(authority.AuthorityLedgerError, match="request_id collision"):
        ledger.execute_once(
            request=changed,
            caller="ready_publisher",
            operation="ready:publish_profile_plan_bound",
            purpose="profile_plan_closure_ready",
            produce=lambda: {"status": "MUST_NOT_RUN"},
        )

    with sqlite3.connect(ledger.path) as conn:
        conn.execute("DROP TRIGGER authority_events_no_update")
        conn.execute(
            "UPDATE authority_events SET event_digest=?", ("sha256:" + "0" * 64,)
        )
        conn.commit()
    with pytest.raises(authority.AuthorityLedgerError, match="event digest mismatch"):
        ledger.execute_once(
            request=_request("request-2"),
            caller="ready_publisher",
            operation="ready:publish_profile_plan_bound",
            purpose="profile_plan_closure_ready",
            produce=lambda: {"status": "MUST_NOT_RUN"},
        )


def test_file_key_custody_requires_single_protected_owner_path(tmp_path: Path) -> None:
    private = Ed25519PrivateKey.generate()
    raw = private.private_bytes(
        serialization.Encoding.Raw,
        serialization.PrivateFormat.Raw,
        serialization.NoEncryption(),
    )
    key_path = tmp_path / "ed25519-private-key"
    key_path.write_bytes(raw)
    key_path.chmod(0o600)
    custody = authority.FileEd25519KeyCustody(
        key_path,
        key_id="ready-test-v1",
        expected_uid=os.geteuid(),
    )
    signature = custody.sign(b"governed message")
    assert signature.startswith("ed25519:")
    assert custody.public_key_base64()

    hardlink = tmp_path / "hardlink"
    os.link(key_path, hardlink)
    with pytest.raises(authority.LocalAuthorityError, match="metadata is unsafe"):
        custody.sign(b"must fail")


def test_exact_acl_binds_peer_operation_purpose_and_environment() -> None:
    acl = authority.ExactMethodAcl(authority_id="ready", environment="production")
    grant = acl.require(
        caller="ready_publisher",
        operation="ready:publish_profile_plan_bound",
        purpose="profile_plan_closure_ready",
    )
    assert grant.environment == "production"
    with pytest.raises(authority.PeerAuthenticationError):
        acl.require(
            caller="ops_scheduler",
            operation="ready:publish_profile_plan_bound",
            purpose="profile_plan_closure_ready",
        )
    with pytest.raises(authority.PeerAuthenticationError):
        acl.require(
            caller="ready_publisher",
            operation="ready:publish_profile_plan_bound",
            purpose="render_current_projection",
        )


def test_service_authenticates_kernel_peer_and_commits_only_after_strict_gate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ledger = _ledger(tmp_path)
    calls = 0

    def handler(payload, fds):
        nonlocal calls
        calls += 1
        assert not fds
        return {"snapshot_id": payload["snapshot_id"], "status": "SIGNED"}

    service = authority.UnixAuthorityService(
        authority_id="ready",
        environment="staging",
        peers=authority.PeerPrincipalRegistry({os.geteuid(): "ready_publisher"}),
        ledger=ledger,
        handlers={"ready:publish_profile_plan_bound": handler},
    )

    # The checked-in finding ledger is OPEN, so the positive handler remains
    # unreachable and no event is appended.
    rejected = _serve_one(service, _request())
    assert rejected["status"] == "REJECTED"
    assert rejected["request_id"] == "request-1"
    assert calls == 0
    with sqlite3.connect(ledger.path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM authority_events").fetchone() == (0,)

    monkeypatch.setattr(
        authority,
        "require_pinned_finding_ledger_gate",
        lambda: object(),
    )
    committed = _serve_one(service, _request())
    assert committed["status"] == "COMMITTED"
    assert committed["result"]["status"] == "SIGNED"
    retry = _serve_one(service, _request())
    assert retry == committed
    assert calls == 1


def test_service_rejects_unmapped_peer_before_handler(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        authority,
        "require_pinned_finding_ledger_gate",
        lambda: object(),
    )
    called = False

    def handler(_payload, _fds):
        nonlocal called
        called = True
        return {"status": "UNSAFE"}

    service = authority.UnixAuthorityService(
        authority_id="ready",
        environment="staging",
        peers=authority.PeerPrincipalRegistry({os.geteuid() + 1: "ready_publisher"}),
        ledger=_ledger(tmp_path),
        handlers={"ready:publish_profile_plan_bound": handler},
    )
    response = _serve_one(service, _request())
    assert response["status"] == "REJECTED"
    assert called is False


def test_frame_rejects_multiple_descriptors_and_closes_them() -> None:
    sender, receiver = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
    first, first_peer = socket.socketpair()
    second, second_peer = socket.socketpair()
    try:
        body = authority.canonical_json_bytes(_request())
        rights = array.array("i", [first.fileno(), second.fileno()])
        sender.sendmsg(
            [struct.pack("!I", len(body))],
            [(socket.SOL_SOCKET, socket.SCM_RIGHTS, rights.tobytes())],
        )
        sender.sendall(body)
        with pytest.raises(authority.LocalAuthorityError, match="too many"):
            authority._recv_frame(receiver)
    finally:
        sender.close()
        receiver.close()
        first.close()
        first_peer.close()
        second.close()
        second_peer.close()


def test_strict_request_rejects_floats_and_undeclared_fields() -> None:
    with pytest.raises(authority.LocalAuthorityError, match="forbidden float"):
        authority.parse_request(
            b'{"format":"local-authority-request/v1","operation":"x",'
            b'"payload":{"count":1.5},"purpose":"p","request_id":"r"}'
        )
    invalid = _request()
    invalid["caller"] = "ready_publisher"
    with pytest.raises(authority.LocalAuthorityError, match="fields are not closed"):
        authority.parse_request(authority.canonical_json_bytes(invalid))
