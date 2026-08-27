"""Behavioral crypto/transport/execution tests for Controlled exact-four v2."""

from __future__ import annotations

import array
import base64
import hashlib
import os
import socket
import sqlite3
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
    ControlledExecutionWriterV2Error,
    _create_test_controlled_execution_writer_v2,
    open_live_controlled_execution_writer_v2,
)
from execution.exact_four_codec import (
    ExactFourAuthorityPending,
    canonical_authority_digest,
)
from execution.exact_four_results import (
    AggregateSelectionEvidenceV2,
    ExactFourPilotResultManifestV2,
    KnowledgeArtifactEvidenceV2,
    PaperResultEvidenceV2,
    RiskResultEvidenceV2,
    _pair_set_digest,
)
from execution.trader_webauthn_authority_v2 import (
    ExactFourTraderCredentialRegistryV2,
    ExactFourTraderRelyingPartyRegistryV2,
)
from tests.test_trader_webauthn_authority_v2 import (
    _assertion,
    _authority,
    _canonical,
    _ready_evidence,
)


def _artifact_contents(suffix: bytes = b"") -> dict[str, bytes]:
    return {
        **{
            f"Paper:{ordinal}": f"paper-{ordinal}".encode("ascii") + suffix
            for ordinal in range(1, 5)
        },
        **{
            f"Risk:{ordinal}": f"risk-{ordinal}".encode("ascii") + suffix
            for ordinal in range(1, 5)
        },
        "Selection:0": b"selection" + suffix,
        "Knowledge:0": b"knowledge" + suffix,
    }


def _digest_bytes(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def _bounded_output(
    context: Mapping[str, Any],
    *,
    contents: dict[str, bytes] | None = None,
) -> dict[str, Any]:
    exact_contents = _artifact_contents() if contents is None else contents
    bindings = context["plan_bindings"]
    papers = tuple(
        PaperResultEvidenceV2(
            ordinal=binding["ordinal"],
            plan_id=binding["plan_id"],
            plan_binding_digest=binding["binding_digest"],
            paper_result_id=_digest_bytes(
                exact_contents[f"Paper:{binding['ordinal']}"]
            ),
            paper_artifact_digest=_digest_bytes(
                exact_contents[f"Paper:{binding['ordinal']}"]
            ),
        )
        for binding in bindings
    )
    risks = tuple(
        RiskResultEvidenceV2(
            ordinal=binding["ordinal"],
            plan_id=binding["plan_id"],
            plan_binding_digest=binding["binding_digest"],
            paper_result_id=paper.paper_result_id,
            paper_evidence_id=paper.evidence_id,
            risk_result_id=_digest_bytes(
                exact_contents[f"Risk:{binding['ordinal']}"]
            ),
            risk_artifact_digest=_digest_bytes(
                exact_contents[f"Risk:{binding['ordinal']}"]
            ),
        )
        for binding, paper in zip(bindings, papers, strict=True)
    )
    selection_digest = _digest_bytes(exact_contents["Selection:0"])
    selection = AggregateSelectionEvidenceV2(
        paper_evidence_ids=tuple(item.evidence_id for item in papers),
        risk_evidence_ids=tuple(item.evidence_id for item in risks),
        input_pair_set_digest=_pair_set_digest(papers, risks),
        selected_plan_ids=tuple(binding["plan_id"] for binding in bindings),
        selection_result_id=selection_digest,
        selection_artifact_digest=selection_digest,
    )
    knowledge_digest = _digest_bytes(exact_contents["Knowledge:0"])
    knowledge = KnowledgeArtifactEvidenceV2(
        selection_evidence_id=selection.evidence_id,
        selection_result_id=selection.selection_result_id,
        knowledge_artifact_id=knowledge_digest,
        knowledge_artifact_digest=knowledge_digest,
    )
    manifest = ExactFourPilotResultManifestV2(
        pilot_run_id=context["pilot_run_id"],
        readiness_attestation_id=context["readiness_attestation_id"],
        trader_authorization_id=context["trader_authorization_id"],
        execution_request_id=context["execution_request_id"],
        lease_id=context["lease_id"],
        idempotency_key=context["idempotency_key"],
        exact_four_binding_digest=context["exact_four_binding_digest"],
        controlled_pilot_policy_digest=context[
            "controlled_pilot_policy_digest"
        ],
        budget_scope_digest=context["budget_scope_digest"],
        plan_set_digest=context["plan_set_digest"],
        dependency_closure_set_digest=context[
            "dependency_closure_set_digest"
        ],
        profile_set_digest=context["profile_set_digest"],
        required_dataset_membership_digest=context[
            "required_dataset_membership_digest"
        ],
        snapshot_id=context["snapshot_id"],
        ready_manifest_digest=context["ready_manifest_digest"],
        immutable_snapshot_digest=context["immutable_snapshot_digest"],
        execution_issued_at=context["execution_issued_at"],
        execution_expires_at=context["execution_expires_at"],
        completed_at=(
            datetime.fromisoformat(context["execution_issued_at"])
            + timedelta(milliseconds=1)
        ).isoformat(),
        paper_results=papers,
        risk_results=risks,
        aggregate_selection=selection,
        knowledge_artifact=knowledge,
    )
    return {
        "manifest": _canonical(manifest.to_dict()),
        "contents": exact_contents,
    }


def _allow_positive_gate(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        writer_module,
        "require_pinned_finding_ledger_gate",
        lambda: object(),
    )


def _committed_system(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    writer_trader_uid: int | None = None,
) -> tuple[Any, Any, Any, list[datetime]]:
    now_box = [datetime.now(timezone.utc) - timedelta(seconds=3)]
    trader, webauthn_private, rp, credential = _authority(tmp_path, now_box)
    ready = _ready_evidence(now_box[0], monkeypatch)
    challenge = trader.issue_challenge(ready)
    now_box[0] += timedelta(seconds=1)
    assertion = _assertion(
        challenge=challenge,
        private_key=webauthn_private,
        credential=credential,
        now=now_box[0],
        sign_count=7,
    )
    handoff = trader.authorize(
        readiness=ready,
        challenge=challenge,
        assertion_raw=_canonical(assertion),
    )
    rps = ExactFourTraderRelyingPartyRegistryV2((rp,), generation=1)
    credentials = ExactFourTraderCredentialRegistryV2(
        (credential,), generation=1
    )
    writer = _create_test_controlled_execution_writer_v2(
        store_path=(tmp_path / "controlled-writer.sqlite").resolve(),
        private_key=Ed25519PrivateKey.generate(),
        clock=lambda: now_box[0],
        relying_parties=rps,
        credentials=credentials,
        trader_uid=writer_trader_uid,
    )
    return trader, handoff, writer, now_box


def _serve(
    trader: Any,
    handoff: Any,
    writer: Any,
    executor: Any,
) -> Any:
    trader_side, controlled_side = socket.socketpair(
        socket.AF_UNIX, socket.SOCK_STREAM
    )
    try:
        trader.send_handoff(trader_side, handoff)
        return writer.receive_and_execute(controlled_side, executor)
    finally:
        trader_side.close()
        controlled_side.close()


def _readonly_unlinked_descriptor(tmp_path: Path, content: bytes) -> int:
    descriptor, name = tempfile.mkstemp(dir=tmp_path)
    path = Path(name)
    try:
        os.write(descriptor, content)
        os.fsync(descriptor)
        os.fchmod(descriptor, 0o400)
    finally:
        os.close(descriptor)
    readonly = os.open(path, os.O_RDONLY | getattr(os, "O_CLOEXEC", 0))
    os.unlink(path)
    return readonly


def _send_raw_handoff(
    channel: socket.socket,
    tmp_path: Path,
    handoff: dict[str, Any],
) -> None:
    handoff_raw = _canonical(handoff)
    request = {
        "format": "local-authority-request/v1",
        "request_id": handoff["handoff_id"],
        "operation": CONTROLLED_TRADER_HANDOFF_OPERATION,
        "purpose": CONTROLLED_TRADER_HANDOFF_PURPOSE,
        "payload": {
            "handoff_id": handoff["handoff_id"],
            "handoff_digest": _digest_bytes(handoff_raw),
        },
    }
    frame_body = _canonical(request)
    frame = struct.pack("!I", len(frame_body)) + frame_body
    descriptor = _readonly_unlinked_descriptor(tmp_path, handoff_raw)
    try:
        channel.sendmsg(
            [frame],
            [
                (
                    socket.SOL_SOCKET,
                    socket.SCM_RIGHTS,
                    array.array("i", [descriptor]),
                )
            ],
        )
    finally:
        os.close(descriptor)


def test_valid_handoff_is_reserved_before_executor_and_executor_runs_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    trader, handoff, writer, _now = _committed_system(tmp_path, monkeypatch)
    _allow_positive_gate(monkeypatch)
    calls = 0

    def execute(context: Mapping[str, Any]) -> Mapping[str, Any]:
        nonlocal calls
        calls += 1
        assert writer.handoff_count() == 1
        assert writer.attempt_outcome(handoff.handoff_id) is None
        return _bounded_output(context)

    written = _serve(trader, handoff, writer, execute)
    assert calls == 1
    assert writer.handoff_count() == 1
    assert writer.attempt_outcome(handoff.handoff_id) == "SUCCEEDED"
    assert writer.artifact_count() == 10
    assert writer.event_count() == 1
    assert len(written.contents) == 10
    assert written.verify_signature(writer.public_key)
    manifest = written.to_dict()
    assert manifest["handoff_id"] == handoff.handoff_id
    assert manifest["result_manifest"]["trader_authorization_id"] == handoff.handoff_id
    assert manifest["generation"] == 1
    assert manifest["one_shot"] is True
    assert manifest["automatic_promotion"] is False
    assert manifest["mass_research_enabled"] is False
    assert manifest["live_trading_enabled"] is False

    def must_not_run(_context: Mapping[str, Any]) -> Mapping[str, Any]:
        raise AssertionError("successful handoff retry must not execute again")

    retry = _serve(trader, handoff, writer, must_not_run)
    assert retry.canonical_manifest == written.canonical_manifest
    assert dict(retry.contents) == dict(written.contents)


def test_open_p0_gate_rejects_before_executor_or_reservation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    trader, handoff, writer, _now = _committed_system(tmp_path, monkeypatch)
    calls = 0

    def execute(_context: Mapping[str, Any]) -> Mapping[str, Any]:
        nonlocal calls
        calls += 1
        return {}

    with pytest.raises(Exception, match="finding ledger release gate blocked"):
        _serve(trader, handoff, writer, execute)
    assert calls == 0
    assert writer.handoff_count() == 0


def test_bad_peer_and_bad_fd_never_invoke_executor(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    trader, handoff, wrong_peer_writer, _now = _committed_system(
        tmp_path,
        monkeypatch,
        writer_trader_uid=os.geteuid() + 1,
    )
    _allow_positive_gate(monkeypatch)
    calls = 0

    def execute(_context: Mapping[str, Any]) -> Mapping[str, Any]:
        nonlocal calls
        calls += 1
        return {}

    with pytest.raises(ControlledExecutionWriterV2Error, match="peer UID"):
        _serve(trader, handoff, wrong_peer_writer, execute)
    assert calls == 0
    assert wrong_peer_writer.handoff_count() == 0

    other = tmp_path / "other"
    other.mkdir()
    trader2, handoff2, writer2, _now2 = _committed_system(other, monkeypatch)
    body = _canonical(
        {
            "format": "local-authority-request/v1",
            "request_id": handoff2.handoff_id,
            "operation": CONTROLLED_TRADER_HANDOFF_OPERATION,
            "purpose": CONTROLLED_TRADER_HANDOFF_PURPOSE,
            "payload": {
                "handoff_id": handoff2.handoff_id,
                "handoff_digest": _digest_bytes(handoff2.canonical_bytes),
            },
        }
    )
    trader_side, controlled_side = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        trader_side.sendall(struct.pack("!I", len(body)) + body)
        with pytest.raises(ControlledExecutionWriterV2Error, match="exactly one"):
            writer2.receive_and_execute(controlled_side, execute)
    finally:
        trader_side.close()
        controlled_side.close()
    assert calls == 0
    assert writer2.handoff_count() == 0


def test_bad_webauthn_signature_never_invokes_executor(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _trader, handoff, writer, _now = _committed_system(tmp_path, monkeypatch)
    _allow_positive_gate(monkeypatch)
    attacked = handoff.to_dict()
    assertion = attacked["assertion_evidence"]
    signature_text = assertion["signature_base64url"]
    signature = base64.urlsafe_b64decode(
        signature_text + "=" * (-len(signature_text) % 4)
    )
    signature = signature[:-1] + bytes([signature[-1] ^ 1])
    assertion["signature_base64url"] = base64.urlsafe_b64encode(signature).decode(
        "ascii"
    ).rstrip("=")
    assertion_body = dict(assertion)
    assertion_body.pop("assertion_digest")
    assertion["assertion_digest"] = canonical_authority_digest(assertion_body)
    event = attacked["one_use_counter_event"]
    event["assertion_digest"] = assertion["assertion_digest"]
    credential = attacked["credential_registry_evidence"]
    event["request_digest"] = canonical_authority_digest(
        {
            "format": "exact-four-trader-authority-request/v2",
            "environment": attacked["environment"],
            "approval_subject_id": attacked["approval_subject_id"],
            "ready_authority_response_digest": attacked[
                "ready_authority_response_digest"
            ],
            "challenge_digest": attacked["challenge_evidence"][
                "challenge_digest"
            ],
            "assertion_digest": assertion["assertion_digest"],
            "credential_registry_digest": credential[
                "credential_registry_digest"
            ],
            "credential_public_key_digest": credential[
                "credential_public_key_digest"
            ],
        }
    )
    event_body = dict(event)
    event_body.pop("event_digest")
    event["event_digest"] = canonical_authority_digest(event_body)
    handoff_body = dict(attacked)
    handoff_body.pop("handoff_id")
    attacked["handoff_id"] = canonical_authority_digest(handoff_body)
    calls = 0

    def execute(_context: Mapping[str, Any]) -> Mapping[str, Any]:
        nonlocal calls
        calls += 1
        return {}

    trader_side, controlled_side = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        _send_raw_handoff(trader_side, tmp_path, attacked)
        with pytest.raises(ControlledExecutionWriterV2Error, match="signature"):
            writer.receive_and_execute(controlled_side, execute)
    finally:
        trader_side.close()
        controlled_side.close()
    assert calls == 0
    assert writer.handoff_count() == 0


def test_same_assertion_rewrapped_as_new_trader_event_is_rejected_by_controlled_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    trader, handoff, writer, _now = _committed_system(tmp_path, monkeypatch)
    _allow_positive_gate(monkeypatch)
    _serve(trader, handoff, writer, _bounded_output)
    attacked = handoff.to_dict()
    attacked_event = attacked["one_use_counter_event"]
    attacked_event["event_id"] = "6e361809-c047-497b-a0f0-c46a5d9e91aa"
    event_body = dict(attacked_event)
    event_body.pop("event_digest")
    attacked_event["event_digest"] = canonical_authority_digest(event_body)
    attacked_body = dict(attacked)
    attacked_body.pop("handoff_id")
    attacked["handoff_id"] = canonical_authority_digest(attacked_body)
    calls = 0

    def must_not_run(_context: Mapping[str, Any]) -> Mapping[str, Any]:
        nonlocal calls
        calls += 1
        return {}

    trader_side, controlled_side = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        _send_raw_handoff(trader_side, tmp_path, attacked)
        with pytest.raises(
            ControlledExecutionWriterV2Error,
            match="counter|reservation",
        ):
            writer.receive_and_execute(controlled_side, must_not_run)
    finally:
        trader_side.close()
        controlled_side.close()
    assert calls == 0
    assert writer.handoff_count() == 1


@pytest.mark.parametrize("prior_count,result_count", [(7, 7), (7, 6)])
def test_equal_or_rollback_counter_event_is_rejected_before_reservation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    prior_count: int,
    result_count: int,
) -> None:
    _trader, handoff, writer, _now = _committed_system(tmp_path, monkeypatch)
    _allow_positive_gate(monkeypatch)
    attacked = handoff.to_dict()
    event = attacked["one_use_counter_event"]
    event["prior_sign_count"] = prior_count
    event["result_sign_count"] = result_count
    event_body = dict(event)
    event_body.pop("event_digest")
    event["event_digest"] = canonical_authority_digest(event_body)
    attacked_body = dict(attacked)
    attacked_body.pop("handoff_id")
    attacked["handoff_id"] = canonical_authority_digest(attacked_body)
    trader_side, controlled_side = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        _send_raw_handoff(trader_side, tmp_path, attacked)
        with pytest.raises(ControlledExecutionWriterV2Error, match="counter"):
            writer.receive_and_execute(controlled_side, _bounded_output)
    finally:
        trader_side.close()
        controlled_side.close()
    assert writer.handoff_count() == 0


def test_concurrent_same_handoff_reservations_invoke_only_one_executor(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    trader, handoff, writer, _now = _committed_system(tmp_path, monkeypatch)
    _allow_positive_gate(monkeypatch)
    reserved = threading.Event()
    release = threading.Event()
    calls = 0
    first_errors: list[BaseException] = []

    def first_executor(context: Mapping[str, Any]) -> Mapping[str, Any]:
        nonlocal calls
        calls += 1
        reserved.set()
        assert release.wait(timeout=5)
        return _bounded_output(context)

    def first_request() -> None:
        try:
            _serve(trader, handoff, writer, first_executor)
        except BaseException as exc:  # pragma: no cover - asserted below
            first_errors.append(exc)

    worker = threading.Thread(target=first_request)
    worker.start()
    assert reserved.wait(timeout=5)
    with pytest.raises(ControlledExecutionWriterV2Error, match="retry policy is DENY"):
        _serve(trader, handoff, writer, _bounded_output)
    release.set()
    worker.join(timeout=5)
    assert not worker.is_alive()
    assert first_errors == []
    assert calls == 1
    assert writer.handoff_count() == 1
    assert writer.attempt_outcome(handoff.handoff_id) == "SUCCEEDED"


@pytest.mark.parametrize(
    "attack",
    ["wrong_schema", "swapped_ordinal", "digest_mismatch", "empty", "duplicate"],
)
def test_executor_output_requires_existing_canonical_schema_and_unique_contents(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    attack: str,
) -> None:
    trader, handoff, writer, _now = _committed_system(tmp_path, monkeypatch)
    _allow_positive_gate(monkeypatch)
    calls = 0

    def execute(context: Mapping[str, Any]) -> Mapping[str, Any]:
        nonlocal calls
        calls += 1
        output = _bounded_output(context)
        if attack == "wrong_schema":
            manifest = writer_module._strict_json_loads(
                output["manifest"], label="test manifest"
            )
            manifest["format"] = "not-exact-four/v0"
            output["manifest"] = _canonical(manifest)
        elif attack == "swapped_ordinal":
            manifest = writer_module._strict_json_loads(
                output["manifest"], label="test manifest"
            )
            manifest["paper_results"][0], manifest["paper_results"][1] = (
                manifest["paper_results"][1],
                manifest["paper_results"][0],
            )
            identity = dict(manifest)
            identity.pop("manifest_id")
            manifest["manifest_id"] = canonical_authority_digest(identity)
            output["manifest"] = _canonical(manifest)
        elif attack == "digest_mismatch":
            output["contents"]["Paper:1"] = b"digest-mismatch"
        elif attack == "empty":
            output["contents"]["Risk:2"] = b""
        else:
            output["contents"]["Risk:2"] = output["contents"]["Risk:1"]
        return output

    with pytest.raises(ControlledExecutionWriterV2Error):
        _serve(trader, handoff, writer, execute)
    assert calls == 1
    assert writer.handoff_count() == 1
    assert writer.attempt_outcome(handoff.handoff_id) == "FAILED"
    assert writer.artifact_count() == 0
    assert writer.event_count() == 0

    with pytest.raises(ControlledExecutionWriterV2Error, match="retry policy is DENY"):
        _serve(trader, handoff, writer, execute)
    assert calls == 1


def test_manifest_failure_keeps_handoff_consumed_and_records_failed_attempt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    trader, handoff, writer, _now = _committed_system(tmp_path, monkeypatch)
    _allow_positive_gate(monkeypatch)
    store = (tmp_path / "controlled-writer.sqlite").resolve()
    with sqlite3.connect(store) as connection:
        connection.execute(
            "CREATE TRIGGER fail_test_manifest BEFORE INSERT ON controlled_manifests "
            "BEGIN SELECT RAISE(ABORT, 'test manifest failure'); END"
        )
    calls = 0

    def execute(context: Mapping[str, Any]) -> Mapping[str, Any]:
        nonlocal calls
        calls += 1
        return _bounded_output(context)

    with pytest.raises(ControlledExecutionWriterV2Error, match="transaction failed"):
        _serve(trader, handoff, writer, execute)
    assert calls == 1
    assert writer.handoff_count() == 1
    assert writer.attempt_outcome(handoff.handoff_id) == "FAILED"
    assert writer.artifact_count() == 0
    assert writer.event_count() == 0

    with sqlite3.connect(store) as connection:
        connection.execute("DROP TRIGGER fail_test_manifest")
    with pytest.raises(ControlledExecutionWriterV2Error, match="retry policy is DENY"):
        _serve(trader, handoff, writer, execute)
    assert calls == 1


def test_committed_rows_are_immutable_and_live_opener_is_pending(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    trader, handoff, writer, _now = _committed_system(tmp_path, monkeypatch)
    _allow_positive_gate(monkeypatch)
    _serve(trader, handoff, writer, _bounded_output)
    store = (tmp_path / "controlled-writer.sqlite").resolve()
    with sqlite3.connect(store) as connection:
        for statement in (
            "DELETE FROM controlled_handoffs",
            "DELETE FROM controlled_execution_attempts",
            "DELETE FROM controlled_artifacts",
            "DELETE FROM controlled_writer_events",
            "DELETE FROM controlled_manifests",
        ):
            with pytest.raises(sqlite3.IntegrityError, match="immutable"):
                connection.execute(statement)
    with pytest.raises(ExactFourAuthorityPending, match="PENDING_PROTECTED"):
        open_live_controlled_execution_writer_v2()
