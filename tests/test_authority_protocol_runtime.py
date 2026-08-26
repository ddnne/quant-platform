"""Adversarial behavior tests for PENDING authority runtime protocols."""

from __future__ import annotations

import array
import base64
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import socket
import sqlite3
from types import SimpleNamespace

import pytest

from scripts import authority_protocol_runtime as runtime


NOW = datetime(2026, 8, 26, 0, 0, 30, tzinfo=timezone.utc)
TABLES = (
    "jquants_market_calendar",
    "jquants_listed_info",
    "jquants_daily_bars",
    "jquants_records",
    "jquants_market_calendar_revisions",
    "jquants_listed_info_revisions",
    "jquants_daily_bars_revisions",
    "jquants_records_revisions",
    "ingestion_run_log",
    "ingestion_validation",
    "ingestion_watermarks",
    "raw_retention_manifests",
    "coverage_segments",
    "collection_receipts",
)


def _json(value: dict[str, object]) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _sha(character: str) -> str:
    return "sha256:" + character * 64


def _request(environment: str = "production") -> dict[str, object]:
    document: dict[str, object] = {
        "schema_version": "d1-frozen-mirror-request/v2",
        "request_id": "00000000-0000-4000-8000-000000000001",
        "environment": environment,
        "authenticated_caller": "ops_projection",
        "target_authority": "d1_sync",
        "target_operation": "frozen_mirror:readonly_handoff",
        "purpose": "ops_projection",
        "issued_at": "2026-08-26T00:00:00Z",
        "expires_at": "2026-08-26T00:01:00Z",
    }
    document["request_digest"] = runtime._digest(document)  # noqa: SLF001
    return document


def _parsed_request(environment: str = "production"):
    return runtime.inspect_frozen_mirror_request_candidate(
        _json(_request(environment)),
        transport_authenticated_caller="ops_projection",
        expected_environment=environment,
        now=NOW,
    )


def _sqlite_fd(tmp_path: Path, *, writable: bool = False) -> tuple[int, Path]:
    path = tmp_path / ("writable.sqlite3" if writable else "mirror.sqlite3")
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA journal_mode=DELETE")
    conn.execute("CREATE TABLE marker (value INTEGER NOT NULL)")
    conn.execute("INSERT INTO marker VALUES (1)")
    conn.commit()
    conn.close()
    flags = os.O_RDWR if writable else os.O_RDONLY
    return os.open(path, flags), path


def _handoff(fd: int, request, *, environment: str = "production"):
    counts = {table: 0 for table in TABLES}
    digest = _sha("1")
    schema = _sha("2")
    descriptor = runtime._descriptor_identity(fd)  # noqa: SLF001
    d1_name, d1_id = runtime._D1_IDENTITIES[environment]  # noqa: SLF001
    audit = {"test": "canonical"}
    document: dict[str, object] = {
        "schema_version": "authenticated-applied-mirror-handoff/v2",
        "authority_domain": "quant-platform/d1-sync/frozen-mirror/v2",
        "request_id": request.document["request_id"],
        "request_digest": request.digest,
        "environment": environment,
        "authenticated_caller": request.document["authenticated_caller"],
        "target_operation": request.document["target_operation"],
        "purpose": request.document["purpose"],
        "source_d1_name": d1_name,
        "source_d1_id": d1_id,
        "signed_audit_document_json": _json(audit),
        "signed_audit_document_digest": _sha("3"),
        "signed_audit_issuer_key_id": "d1-sync-test-v1",
        "source_change_seq": 7,
        "applied_change_seq": 7,
        "descriptor_open_mode": "O_RDONLY",
        "descriptor_identity": descriptor,
        "source_content_digest": digest,
        "local_content_digest": digest,
        "source_schema_digest": schema,
        "local_schema_digest": schema,
        "table_counts": counts,
        "journal_mode": "delete",
        "opened_at": "2026-08-26T00:00:00Z",
        "expires_at": "2026-08-26T00:01:00Z",
        "fd_count": 1,
    }
    mirror_body = {
        key: document[key]
        for key in (
            "environment",
            "source_d1_name",
            "source_d1_id",
            "signed_audit_document_digest",
            "signed_audit_issuer_key_id",
            "source_change_seq",
            "applied_change_seq",
            "descriptor_open_mode",
            "descriptor_identity",
            "source_content_digest",
            "local_content_digest",
            "source_schema_digest",
            "local_schema_digest",
            "table_counts",
            "journal_mode",
        )
    }
    document["mirror_identity_digest"] = runtime._digest(mirror_body)  # noqa: SLF001
    document["handoff_digest"] = runtime._digest(document)  # noqa: SLF001
    envelope = {
        "d1_name": d1_name,
        "d1_id": d1_id,
        "source_change_seq": 7,
        "applied_change_seq": 7,
        "source_content_digest": digest,
        "local_content_digest": digest,
        "source_schema_digest": schema,
        "schema_digest": schema,
        "table_counts": counts,
    }
    mirror_identity = {
        "audit_digest": document["signed_audit_document_digest"],
        "issuer_key_id": document["signed_audit_issuer_key_id"],
        "export_digest": _sha("4"),
        "source_change_seq": 7,
        "applied_change_seq": 7,
        "source_content_digest": digest,
        "local_content_digest": digest,
        "source_schema_digest": schema,
        "schema_digest": schema,
        "table_counts": counts,
    }
    verified = SimpleNamespace(
        document_digest=document["signed_audit_document_digest"],
        issuer_key_id=document["signed_audit_issuer_key_id"],
        envelope=envelope,
    )
    return document, verified, mirror_identity


def test_request_binds_transport_caller_environment_digest_and_method_acl() -> None:
    request = _request()
    parsed = _parsed_request()
    assert parsed.digest == request["request_digest"]

    with pytest.raises(runtime.AuthorityProtocolError, match="transport-authenticated"):
        runtime.inspect_frozen_mirror_request_candidate(
            _json(request),
            transport_authenticated_caller="coverage_transition",
            expected_environment="production",
            now=NOW,
        )
    request["target_operation"] = "d1_sync:sync_now"
    request["request_digest"] = runtime._digest(  # noqa: SLF001
        runtime._without(request, "request_digest")  # noqa: SLF001
    )
    with pytest.raises(runtime.AuthorityProtocolError):
        runtime.inspect_frozen_mirror_request_candidate(
            _json(request),
            transport_authenticated_caller="ops_projection",
            expected_environment="production",
            now=NOW,
        )


@pytest.mark.parametrize(
    "raw",
    [
        '{"schema_version":"x","schema_version":"y"}',
        '{"schema_version":"x","value":NaN}',
    ],
)
def test_runtime_codec_rejects_duplicate_and_nonfinite_json(raw: str) -> None:
    with pytest.raises(runtime.AuthorityProtocolError):
        runtime.inspect_frozen_mirror_request_candidate(
            raw,
            transport_authenticated_caller="ops_projection",
            expected_environment="production",
            now=NOW,
        )


def test_handoff_remeasures_audit_mirror_and_exact_readonly_fd(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fd, _ = _sqlite_fd(tmp_path)
    try:
        request = _parsed_request()
        handoff, verified, identity = _handoff(fd, request)
        calls: list[tuple[bool, str]] = []

        def verify(document, *, require_fresh, eligibility):
            assert document == {"test": "canonical"}
            calls.append((require_fresh, eligibility))
            return verified

        monkeypatch.setattr(
            runtime._d1_signing, "_verify_signed_d1_sync_audit_document", verify
        )
        monkeypatch.setattr(
            runtime,
            "_remeasure_applied_mirror_identity",
            lambda conn: identity,
        )
        candidate = runtime.inspect_frozen_mirror_handoff_candidate(
            _json(handoff), request=request, received_fd=fd, now=NOW
        )
        assert candidate.audit_document_digest == handoff[
            "signed_audit_document_digest"
        ]
        assert calls == [(True, "current")]
        swap_path = tmp_path / "swap.sqlite3"
        swap_conn = sqlite3.connect(swap_path)
        swap_conn.execute("CREATE TABLE swapped (value INTEGER)")
        swap_conn.commit()
        swap_conn.close()
        swap_fd = os.open(swap_path, os.O_RDONLY)
        try:
            with pytest.raises(runtime.AuthorityProtocolError, match="descriptor identity"):
                runtime.inspect_frozen_mirror_handoff_candidate(
                    _json(handoff), request=request, received_fd=swap_fd, now=NOW
                )
        finally:
            os.close(swap_fd)
        with pytest.raises(runtime.AuthorityProtocolPending, match="OS peer"):
            runtime.activate_frozen_mirror_handoff(
                _json(handoff), request=request, received_fd=fd, now=NOW
            )
    finally:
        os.close(fd)


def test_shape_valid_staging_handoff_never_becomes_verified(
    tmp_path: Path,
) -> None:
    fd, _ = _sqlite_fd(tmp_path)
    try:
        request = _parsed_request("staging")
        handoff, _, _ = _handoff(fd, request, environment="staging")
        with pytest.raises(runtime.AuthorityProtocolPending, match="staging"):
            runtime.inspect_frozen_mirror_handoff_candidate(
                _json(handoff), request=request, received_fd=fd, now=NOW
            )
    finally:
        os.close(fd)


def test_initial_zero_cursor_remains_a_valid_remeasured_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    counts = {table: 0 for table in TABLES}
    monkeypatch.setattr(
        runtime._sync,
        "_latest_export_sync_row",
        lambda conn: {"audit_digest": _sha("1"), "issuer_key_id": "key-v1"},
    )
    monkeypatch.setattr(
        runtime._sync,
        "_verified_sync_envelope_from_row",
        lambda *args, **kwargs: {
            "export_digest": _sha("2"),
            "source_change_seq": 0,
            "applied_change_seq": 0,
            "source_content_digest": _sha("3"),
            "local_content_digest": _sha("3"),
            "source_schema_digest": _sha("4"),
            "schema_digest": _sha("4"),
            "table_counts": counts,
        },
    )
    identity = runtime._remeasure_applied_mirror_identity(object())  # noqa: SLF001
    assert identity["source_change_seq"] == 0
    assert identity["applied_change_seq"] == 0


def test_descriptor_swap_or_write_capability_is_rejected(tmp_path: Path) -> None:
    first, _ = _sqlite_fd(tmp_path)
    second_path = tmp_path / "second.sqlite3"
    second_conn = sqlite3.connect(second_path)
    second_conn.execute("CREATE TABLE other (value TEXT)")
    second_conn.commit()
    second_conn.close()
    second = os.open(second_path, os.O_RDONLY)
    try:
        claimed = runtime._descriptor_identity(first)  # noqa: SLF001
        assert runtime._descriptor_identity(second) != claimed  # noqa: SLF001
    finally:
        os.close(first)
        os.close(second)

    write_path = tmp_path / "write.sqlite3"
    write_path.write_bytes(b"not-empty")
    write_fd = os.open(write_path, os.O_RDWR)
    try:
        with pytest.raises(runtime.AuthorityProtocolError, match="O_RDONLY"):
            runtime._descriptor_identity(write_fd)  # noqa: SLF001
    finally:
        os.close(write_fd)


def test_scm_rights_requires_exactly_one_descriptor(tmp_path: Path) -> None:
    fd, _ = _sqlite_fd(tmp_path)
    sender, receiver = socket.socketpair()
    try:
        sender.sendmsg(
            [b"{}"],
            [(socket.SOL_SOCKET, socket.SCM_RIGHTS, array.array("i", [fd]))],
        )
        payload, received = runtime._recv_exactly_one_fd(receiver)  # noqa: SLF001
        try:
            assert payload == b"{}"
            assert os.fstat(received).st_ino == os.fstat(fd).st_ino
        finally:
            os.close(received)
    finally:
        sender.close()
        receiver.close()
        os.close(fd)


def test_scm_rights_rejects_multiple_descriptors(tmp_path: Path) -> None:
    fd, _ = _sqlite_fd(tmp_path)
    sender, receiver = socket.socketpair()
    try:
        sender.sendmsg(
            [b"{}"],
            [(socket.SOL_SOCKET, socket.SCM_RIGHTS, array.array("i", [fd, fd]))],
        )
        with pytest.raises(runtime.AuthorityProtocolError, match="exactly one"):
            runtime._recv_exactly_one_fd(receiver)  # noqa: SLF001
    finally:
        sender.close()
        receiver.close()
        os.close(fd)


def _event() -> dict[str, object]:
    payload: dict[str, object] = {"result": "PENDING"}
    document: dict[str, object] = {
        "schema_version": "authority-event/v2",
        "environment": "staging",
        "authority_id": "d1_sync",
        "sequence": 1,
        "event_id": "00000000-0000-4000-8000-000000000002",
        "request_id": "00000000-0000-4000-8000-000000000001",
        "event_type": "PREPARED",
        "subject_id": "mirror-1",
        "prior_event_digest": None,
        "payload_schema": "d1-sync-event/v1",
        "payload_digest": runtime._digest(payload),  # noqa: SLF001
        "payload_json": _json(payload),
        "observed_at": "2026-08-26T00:00:00Z",
    }
    idempotency_body = {
        key: document[key]
        for key in (
            "environment",
            "authority_id",
            "request_id",
            "event_type",
            "subject_id",
            "payload_schema",
            "payload_digest",
        )
    }
    document["idempotency_key"] = runtime._digest(idempotency_body)  # noqa: SLF001
    document["event_digest"] = runtime._digest(document)  # noqa: SLF001
    return document


def test_authority_event_canonical_chain_and_ledger_pending() -> None:
    event = _event()
    candidate = runtime.inspect_authority_event_candidate(
        _json(event),
        expected_authority="d1_sync",
        expected_environment="staging",
        expected_sequence=1,
        expected_prior_event_digest=None,
    )
    assert candidate.payload["result"] == "PENDING"
    with pytest.raises(runtime.AuthorityProtocolPending, match="transactional"):
        runtime.append_authority_event(
            _json(event),
            expected_authority="d1_sync",
            expected_environment="staging",
            expected_sequence=1,
            expected_prior_event_digest=None,
        )
    event["payload_json"] = '{"result": "PENDING"}'
    with pytest.raises(runtime.AuthorityProtocolError, match="not canonical"):
        runtime.inspect_authority_event_candidate(
            _json(event),
            expected_authority="d1_sync",
            expected_environment="staging",
            expected_sequence=1,
            expected_prior_event_digest=None,
        )


def _b64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode().rstrip("=")


def _webauthn_pair() -> tuple[dict[str, object], dict[str, object]]:
    exact_four = _sha("8")
    challenge: dict[str, object] = {
        "schema_version": "trader-webauthn-challenge/v1",
        "environment": "production",
        "challenge_id": "00000000-0000-4000-8000-000000000003",
        "challenge_base64url": _b64(b"c" * 32),
        "exact_four_authorization_digest": exact_four,
        "rp_id": "quant-platform.local",
        "origin": "https://quant-platform.local",
        "user_presence_required": True,
        "user_verification_required": True,
        "issued_at": "2026-08-26T00:00:00Z",
        "expires_at": "2026-08-26T00:01:00Z",
    }
    one_use_body = {
        key: challenge[key]
        for key in (
            "environment",
            "challenge_id",
            "challenge_base64url",
            "exact_four_authorization_digest",
            "expires_at",
        )
    }
    challenge["one_use_key"] = runtime._digest(one_use_body)  # noqa: SLF001
    challenge["challenge_digest"] = runtime._digest(challenge)  # noqa: SLF001
    client = {
        "type": "webauthn.get",
        "challenge": challenge["challenge_base64url"],
        "origin": challenge["origin"],
        "crossOrigin": False,
    }
    authenticator = (
        hashlib.sha256(str(challenge["rp_id"]).encode()).digest()
        + bytes([0x05])
        + (7).to_bytes(4, "big")
    )
    assertion: dict[str, object] = {
        "schema_version": "trader-webauthn-assertion/v1",
        "environment": challenge["environment"],
        "challenge_id": challenge["challenge_id"],
        "challenge_digest": challenge["challenge_digest"],
        "exact_four_authorization_digest": exact_four,
        "credential_id_base64url": _b64(b"credential"),
        "authenticator_data_base64url": _b64(authenticator),
        "client_data_json_base64url": _b64(_json(client).encode()),
        "signature_base64url": _b64(b"signature"),
        "rp_id": challenge["rp_id"],
        "origin": challenge["origin"],
        "user_present": True,
        "user_verified": True,
        "sign_count": 7,
        "asserted_at": "2026-08-26T00:00:30Z",
        "one_use_key": challenge["one_use_key"],
    }
    assertion["assertion_digest"] = runtime._digest(assertion)  # noqa: SLF001
    return challenge, assertion


def test_webauthn_inspection_binds_exact_four_up_uv_counter_and_stays_pending() -> None:
    challenge, assertion = _webauthn_pair()
    expected = {
        "expected_environment": "production",
        "expected_exact_four_authorization_digest": challenge[
            "exact_four_authorization_digest"
        ],
        "stored_sign_count": 6,
        "one_use_key_available": True,
        "now": NOW,
    }
    candidate = runtime.inspect_trader_webauthn_assertion_candidate(
        _json(challenge), _json(assertion), **expected
    )
    assert candidate.sign_count == 7
    with pytest.raises(runtime.AuthorityProtocolPending, match="credential signature"):
        runtime.authorize_trader_webauthn_assertion(
            _json(challenge), _json(assertion), **expected
        )
    encoded_authenticator = str(assertion["authenticator_data_base64url"])
    assertion["authenticator_data_base64url"] = _b64(
        base64.urlsafe_b64decode(
            encoded_authenticator + "=" * (-len(encoded_authenticator) % 4)
        )[:32]
        + bytes([0x01])
        + (8).to_bytes(4, "big")
    )
    assertion["sign_count"] = 8
    assertion["assertion_digest"] = runtime._digest(  # noqa: SLF001
        runtime._without(assertion, "assertion_digest")  # noqa: SLF001
    )
    with pytest.raises(runtime.AuthorityProtocolError, match="UP and UV"):
        runtime.inspect_trader_webauthn_assertion_candidate(
            _json(challenge), _json(assertion), **expected
        )
