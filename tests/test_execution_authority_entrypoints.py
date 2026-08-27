"""Behavior tests for the R10/R11 local AuthorityServer adapters."""

from __future__ import annotations

import array
import base64
import hashlib
import os
import socket
import struct
import tempfile
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
import pytest

import execution.controlled_execution_writer_v2 as writer_module
from execution.controlled_execution_writer_v2 import (
    CONTROLLED_TRADER_HANDOFF_OPERATION,
    CONTROLLED_TRADER_HANDOFF_PURPOSE,
    _create_test_controlled_execution_writer_v2,
)
from execution.exact_four_codec import canonical_authority_digest
from execution.trader_webauthn_authority_v2 import (
    ExactFourTraderCredentialRegistryV2,
    ExactFourTraderRelyingPartyRegistryV2,
    IssuedExactFourTraderChallengeV2,
)
from scripts.execution_authority_entrypoints import (
    TRADER_AUTHORIZE_OPERATION,
    TRADER_AUTHORIZE_PURPOSE,
    TRADER_PHASE_ISSUE_CHALLENGE,
    TRADER_PHASE_VERIFY_ASSERTION,
    ControlledExecutionConsumeTraderHandoffV2,
    TraderAuthorizeExactFourBatchHumanPresentV2,
)
from scripts.finding_ledger_gate import FindingLedgerError
import scripts.local_authority_service as local_service_module
from scripts.local_authority_service import (
    MethodGrant,
    PeerPrincipalRegistry,
    SQLiteAuthorityEventLedger,
    UnixAuthorityService,
    canonical_json_bytes,
    decode_strict_json,
)
from tests.test_controlled_execution_writer_v2 import _bounded_output
from tests.test_trader_webauthn_authority_v2 import (
    _assertion,
    _authority,
    _canonical,
    _ready_evidence,
)


class _TestExactMethodAcl:
    """Test-only ACL preserving the exact caller graph in environment test."""

    def __init__(self, *, authority_id: str, environment: str) -> None:
        assert authority_id in {"trader", "controlled_execution"}
        assert environment == "test"
        self.authority_id = authority_id
        self.environment = environment

    def require(self, *, caller: str, operation: str, purpose: str) -> MethodGrant:
        expected = {
            "trader": (
                "controlled_pilot_orchestrator",
                TRADER_AUTHORIZE_OPERATION,
                TRADER_AUTHORIZE_PURPOSE,
            ),
            "controlled_execution": (
                "trader",
                CONTROLLED_TRADER_HANDOFF_OPERATION,
                CONTROLLED_TRADER_HANDOFF_PURPOSE,
            ),
        }[self.authority_id]
        if (caller, operation, purpose) != expected:
            raise local_service_module.PeerAuthenticationError(
                "test exact method ACL rejected the request"
            )
        return MethodGrant(caller, operation, purpose, self.environment)


def _service(
    tmp_path: Path,
    *,
    authority_id: str,
    caller: str,
    handler: Any,
) -> UnixAuthorityService:
    ledger_dir = tmp_path / f"{authority_id}-service-ledger"
    ledger_dir.mkdir(mode=0o700)
    os.chmod(ledger_dir, 0o700)
    ledger = SQLiteAuthorityEventLedger(
        ledger_dir / "events.sqlite3",
        authority_id=authority_id,
        environment="test",
        expected_uid=os.geteuid(),
    )
    ledger.initialize()
    return UnixAuthorityService(
        authority_id=authority_id,
        environment="test",
        peers=PeerPrincipalRegistry({os.geteuid(): caller}),
        ledger=ledger,
        handlers={handler.operation: handler},
    )


def _call_socketpair(
    service: UnixAuthorityService,
    request: dict[str, Any],
    *,
    descriptor: int | None = None,
) -> dict[str, Any]:
    client, server = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
    errors: list[BaseException] = []

    def serve() -> None:
        try:
            service.serve_connection(server)
        except BaseException as exc:  # pragma: no cover - asserted below
            errors.append(exc)

    worker = threading.Thread(target=serve, daemon=True)
    worker.start()
    try:
        body = canonical_json_bytes(request)
        header = struct.pack("!I", len(body))
        if descriptor is None:
            client.sendall(header + body)
        else:
            rights = array.array("i", [descriptor])
            sent = client.sendmsg(
                [header],
                [(socket.SOL_SOCKET, socket.SCM_RIGHTS, rights.tobytes())],
            )
            assert sent == len(header)
            client.sendall(body)
        response_header = client.recv(4, socket.MSG_WAITALL)
        length = struct.unpack("!I", response_header)[0]
        response = client.recv(length, socket.MSG_WAITALL)
        worker.join(timeout=5)
        assert not worker.is_alive()
        assert errors == []
        return decode_strict_json(response, field="test authority response")
    finally:
        client.close()
        server.close()


def _request(
    *,
    request_id: str,
    operation: str,
    purpose: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    return {
        "format": "local-authority-request/v1",
        "request_id": request_id,
        "operation": operation,
        "purpose": purpose,
        "payload": payload,
    }


def test_open_p0_gate_rejects_before_trader_handler_or_challenge(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        local_service_module,
        "ExactMethodAcl",
        _TestExactMethodAcl,
    )
    now_box = [datetime.now(timezone.utc) - timedelta(seconds=2)]
    authority_dir = tmp_path / "trader-authority"
    authority_dir.mkdir()
    authority, _private, _rp, _credential = _authority(authority_dir, now_box)
    adapter = TraderAuthorizeExactFourBatchHumanPresentV2(
        authority=authority,
        controlled_socket_path=(tmp_path / "controlled.sock").resolve(),
        controlled_execution_uid=os.geteuid(),
    )
    calls = 0

    class CountingHandler:
        operation = adapter.operation

        def __call__(self, context: Any, payload: Any, fds: Any) -> Mapping[str, Any]:
            nonlocal calls
            calls += 1
            return adapter(context, payload, fds)

    service = _service(
        tmp_path,
        authority_id="trader",
        caller="controlled_pilot_orchestrator",
        handler=CountingHandler(),
    )

    def blocked() -> object:
        raise FindingLedgerError("strict all-P0 finding gate is OPEN")

    monkeypatch.setattr(
        local_service_module,
        "require_pinned_finding_ledger_gate",
        blocked,
    )
    response = _call_socketpair(
        service,
        _request(
            request_id="blocked-challenge",
            operation=TRADER_AUTHORIZE_OPERATION,
            purpose=TRADER_AUTHORIZE_PURPOSE,
            payload={"phase": TRADER_PHASE_ISSUE_CHALLENGE},
        ),
    )
    assert response["status"] == "REJECTED"
    assert response["error"] == "FindingLedgerError"
    assert calls == 0
    assert authority.ledger.event_count() == 0


def test_bad_controlled_peer_or_missing_fd_never_invokes_executor(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        local_service_module,
        "ExactMethodAcl",
        _TestExactMethodAcl,
    )
    monkeypatch.setattr(
        local_service_module,
        "require_pinned_finding_ledger_gate",
        lambda: object(),
    )
    monkeypatch.setattr(writer_module, "require_pinned_finding_ledger_gate", lambda: object())
    committed_dir = tmp_path / "committed"
    committed_dir.mkdir()
    now_box = [datetime.now(timezone.utc) - timedelta(seconds=3)]
    trader, private_key, rp, credential = _authority(committed_dir, now_box)
    ready = _ready_evidence(now_box[0], monkeypatch)
    challenge = trader.issue_challenge(ready)
    now_box[0] += timedelta(seconds=1)
    assertion = _assertion(
        challenge=challenge,
        private_key=private_key,
        credential=credential,
        now=now_box[0],
        sign_count=7,
    )
    handoff = trader.authorize(
        readiness=ready,
        challenge=challenge,
        assertion_raw=_canonical(assertion),
    )
    writer = _create_test_controlled_execution_writer_v2(
        store_path=(tmp_path / "controlled.sqlite3").resolve(),
        private_key=Ed25519PrivateKey.generate(),
        clock=lambda: now_box[0],
        relying_parties=ExactFourTraderRelyingPartyRegistryV2((rp,), generation=1),
        credentials=ExactFourTraderCredentialRegistryV2(
            (credential,), generation=1
        ),
    )
    calls = 0

    def executor(context: Mapping[str, Any]) -> Mapping[str, Any]:
        nonlocal calls
        calls += 1
        return _bounded_output(context)

    adapter = ControlledExecutionConsumeTraderHandoffV2(
        writer=writer,
        bounded_executor=executor,
    )
    missing_fd_service = _service(
        tmp_path,
        authority_id="controlled_execution",
        caller="trader",
        handler=adapter,
    )
    payload = {
        "handoff_id": handoff.handoff_id,
        "handoff_digest": "sha256:"
        + hashlib.sha256(handoff.canonical_bytes).hexdigest(),
    }
    response = _call_socketpair(
        missing_fd_service,
        _request(
            request_id=handoff.handoff_id,
            operation=CONTROLLED_TRADER_HANDOFF_OPERATION,
            purpose=CONTROLLED_TRADER_HANDOFF_PURPOSE,
            payload=payload,
        ),
    )
    assert response["status"] == "REJECTED"
    assert calls == 0
    assert writer.handoff_count() == 0

    wrong_peer_service = UnixAuthorityService(
        authority_id="controlled_execution",
        environment="test",
        peers=PeerPrincipalRegistry({os.geteuid() + 1: "trader"}),
        ledger=missing_fd_service.ledger,
        handlers={adapter.operation: adapter},
    )
    response = _call_socketpair(
        wrong_peer_service,
        _request(
            request_id="wrong-peer",
            operation=CONTROLLED_TRADER_HANDOFF_OPERATION,
            purpose=CONTROLLED_TRADER_HANDOFF_PURPOSE,
            payload=payload,
        ),
    )
    assert response["status"] == "REJECTED"
    assert response["error"] == "PeerAuthenticationError"
    assert calls == 0
    assert writer.handoff_count() == 0


def test_two_phase_trader_to_controlled_authority_executes_once_after_reservation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        local_service_module,
        "ExactMethodAcl",
        _TestExactMethodAcl,
    )
    monkeypatch.setattr(
        local_service_module,
        "require_pinned_finding_ledger_gate",
        lambda: object(),
    )
    monkeypatch.setattr(writer_module, "require_pinned_finding_ledger_gate", lambda: object())
    now_box = [datetime.now(timezone.utc) - timedelta(seconds=3)]
    authority_dir = tmp_path / "trader-authority"
    authority_dir.mkdir()
    authority, private_key, rp, credential = _authority(authority_dir, now_box)
    ready = _ready_evidence(now_box[0], monkeypatch)
    writer = _create_test_controlled_execution_writer_v2(
        store_path=(tmp_path / "controlled-writer.sqlite3").resolve(),
        private_key=Ed25519PrivateKey.generate(),
        clock=lambda: now_box[0],
        relying_parties=ExactFourTraderRelyingPartyRegistryV2((rp,), generation=1),
        credentials=ExactFourTraderCredentialRegistryV2(
            (credential,), generation=1
        ),
    )
    calls = 0

    def executor(context: Mapping[str, Any]) -> Mapping[str, Any]:
        nonlocal calls
        calls += 1
        assert writer.handoff_count() == 1
        return _bounded_output(context)

    controlled_adapter = ControlledExecutionConsumeTraderHandoffV2(
        writer=writer,
        bounded_executor=executor,
    )
    controlled_service = _service(
        tmp_path,
        authority_id="controlled_execution",
        caller="trader",
        handler=controlled_adapter,
    )
    socket_directory = tempfile.TemporaryDirectory(
        prefix="qp-controlled-test-",
        dir="/tmp",
    )
    controlled_path = Path(socket_directory.name) / "controlled.sock"
    listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    listener.bind(str(controlled_path))
    listener.listen(1)
    trader_adapter = TraderAuthorizeExactFourBatchHumanPresentV2(
        authority=authority,
        controlled_socket_path=controlled_path,
        controlled_execution_uid=os.geteuid(),
    )
    trader_service = _service(
        tmp_path,
        authority_id="trader",
        caller="controlled_pilot_orchestrator",
        handler=trader_adapter,
    )
    ready_base64 = base64.b64encode(ready.canonical_response).decode("ascii")
    issue_response = _call_socketpair(
        trader_service,
        _request(
            request_id="issue-exact-four-challenge",
            operation=TRADER_AUTHORIZE_OPERATION,
            purpose=TRADER_AUTHORIZE_PURPOSE,
            payload={
                "phase": TRADER_PHASE_ISSUE_CHALLENGE,
                "ready_response_base64": ready_base64,
            },
        ),
    )
    assert issue_response["status"] == "COMMITTED"
    issue_result = issue_response["result"]
    assert issue_result["status"] == "CHALLENGE_ISSUED"
    assert issue_result["human_presence_still_required"] is True
    assert issue_result["controlled_execution_started"] is False
    assert calls == 0
    challenge = IssuedExactFourTraderChallengeV2.from_document(
        issue_result["challenge"]
    )
    now_box[0] += timedelta(seconds=1)
    assertion = _assertion(
        challenge=challenge,
        private_key=private_key,
        credential=credential,
        now=now_box[0],
        sign_count=7,
    )
    verify_request = _request(
        request_id="verify-human-present-assertion",
        operation=TRADER_AUTHORIZE_OPERATION,
        purpose=TRADER_AUTHORIZE_PURPOSE,
        payload={
            "phase": TRADER_PHASE_VERIFY_ASSERTION,
            "ready_response_base64": ready_base64,
            "challenge": challenge.to_dict(),
            "assertion_base64": base64.b64encode(_canonical(assertion)).decode(
                "ascii"
            ),
        },
    )
    server_errors: list[BaseException] = []

    def serve_controlled_once() -> None:
        try:
            channel, _ = listener.accept()
            try:
                controlled_service.serve_connection(channel)
            finally:
                channel.close()
        except BaseException as exc:  # pragma: no cover - asserted below
            server_errors.append(exc)

    thread = threading.Thread(target=serve_controlled_once, daemon=True)
    thread.start()
    verify_response = _call_socketpair(trader_service, verify_request)
    thread.join(timeout=5)
    listener.close()
    assert not thread.is_alive()
    assert server_errors == []
    assert verify_response["status"] == "COMMITTED"
    result = verify_response["result"]
    assert result["status"] == "CONTROLLED_EXECUTION_COMMITTED"
    assert result["reusable_trader_capability_returned"] is False
    assert result["controlled_result"]["status"] == (
        "CONTROLLED_ARTIFACTS_COMMITTED"
    )
    assert result["controlled_result"]["artifact_count"] == 10
    assert calls == 1
    assert writer.handoff_count() == 1
    assert writer.attempt_outcome(result["handoff_id"]) == "SUCCEEDED"
    assert authority.ledger.event_count() == 1

    # The outer Trader AuthorityServer ledger returns the committed audit result
    # for an identical request without re-running Controlled or its executor.
    retry = _call_socketpair(trader_service, verify_request)
    assert retry == verify_response
    assert calls == 1
    socket_directory.cleanup()


def test_context_digest_is_bound_to_payload_before_controlled_execution(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A payload cannot be swapped beneath an authenticated server context."""

    monkeypatch.setattr(writer_module, "require_pinned_finding_ledger_gate", lambda: object())
    committed_dir = tmp_path / "committed"
    committed_dir.mkdir()
    now_box = [datetime.now(timezone.utc) - timedelta(seconds=3)]
    trader, private_key, rp, credential = _authority(committed_dir, now_box)
    ready = _ready_evidence(now_box[0], monkeypatch)
    challenge = trader.issue_challenge(ready)
    now_box[0] += timedelta(seconds=1)
    assertion = _assertion(
        challenge=challenge,
        private_key=private_key,
        credential=credential,
        now=now_box[0],
        sign_count=7,
    )
    handoff = trader.authorize(
        readiness=ready,
        challenge=challenge,
        assertion_raw=_canonical(assertion),
    )
    writer = _create_test_controlled_execution_writer_v2(
        store_path=(tmp_path / "controlled.sqlite3").resolve(),
        private_key=Ed25519PrivateKey.generate(),
        clock=lambda: now_box[0],
        relying_parties=ExactFourTraderRelyingPartyRegistryV2((rp,), generation=1),
        credentials=ExactFourTraderCredentialRegistryV2(
            (credential,), generation=1
        ),
    )
    calls = 0

    def executor(context: Mapping[str, Any]) -> Mapping[str, Any]:
        nonlocal calls
        calls += 1
        return _bounded_output(context)

    adapter = ControlledExecutionConsumeTraderHandoffV2(
        writer=writer,
        bounded_executor=executor,
    )
    original_payload = {
        "handoff_id": handoff.handoff_id,
        "handoff_digest": "sha256:"
        + hashlib.sha256(handoff.canonical_bytes).hexdigest(),
    }
    request = _request(
        request_id=handoff.handoff_id,
        operation=CONTROLLED_TRADER_HANDOFF_OPERATION,
        purpose=CONTROLLED_TRADER_HANDOFF_PURPOSE,
        payload=original_payload,
    )
    context = local_service_module.AuthorityRequestContext(
        peer=local_service_module.PeerIdentity(os.geteuid(), os.getegid(), None),
        caller="trader",
        grant=MethodGrant(
            "trader",
            CONTROLLED_TRADER_HANDOFF_OPERATION,
            CONTROLLED_TRADER_HANDOFF_PURPOSE,
            "test",
        ),
        request_id=handoff.handoff_id,
        request_digest=canonical_authority_digest(request),
    )
    swapped = dict(original_payload)
    swapped["handoff_digest"] = canonical_authority_digest({"swapped": True})
    with pytest.raises(local_service_module.LocalAuthorityError, match="differs"):
        adapter(context, swapped, ())
    assert calls == 0
    assert writer.handoff_count() == 0
