"""Behavioral tests for the external staged-canary high-water anchor."""

from __future__ import annotations

import base64
import json
import multiprocessing
import os
import subprocess
import sys
import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from jsonschema import Draft202012Validator, FormatChecker

from scripts import local_authority_anchor_authority as anchor_authority
from scripts import local_authority_anchor_contract as anchor_contract
from scripts import local_authority_anchor_protocol as anchor
from scripts import local_authority_anchor_store as anchor_store
from scripts import manage_local_authority_anchor as anchor_manager
from scripts import local_authority_staged_canary as canary


NOW = datetime(2026, 8, 27, 1, 2, 3, tzinfo=UTC)


def test_anchor_modules_import_in_one_direction_without_cycle() -> None:
    program = """
import sys
import scripts.local_authority_anchor_contract
assert 'scripts.local_authority_anchor_authority' not in sys.modules
assert 'scripts.local_authority_anchor_store' not in sys.modules
assert 'scripts.local_authority_anchor_protocol' not in sys.modules
import scripts.local_authority_anchor_authority
assert 'scripts.local_authority_anchor_store' not in sys.modules
assert 'scripts.local_authority_anchor_protocol' not in sys.modules
import scripts.local_authority_anchor_store
assert 'scripts.local_authority_anchor_protocol' not in sys.modules
import scripts.local_authority_anchor_protocol as facade
assert facade.__all__ == [
    'AnchorOperationalHold',
    'AnchorProtocolError',
    'anchor_plan',
    'collect_anchor',
]
"""
    completed = subprocess.run(
        [sys.executable, "-c", program],
        cwd=Path(__file__).resolve().parents[1],
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr


def _snapshot(
    *, instance: str = "journal-instance:" + "1" * 64,
    event_count: int = 0, attempt_count: int = 0,
    branch: str = "a",
) -> dict[str, object]:
    if branch not in "abcdef0123456789":
        raise ValueError("test branch must be hexadecimal")
    if event_count and attempt_count == 0:
        attempt_count = 1
    if attempt_count not in {0, 1, 2}:
        raise ValueError("test snapshot supports at most two attempts")
    if attempt_count == 0 and event_count != 0:
        raise ValueError("events require one attempt")
    if attempt_count == 1 and event_count not in {0, 1, 2, 3}:
        raise ValueError("one-attempt test history is bounded at commit")
    if attempt_count == 2 and event_count not in {3, 4, 5}:
        raise ValueError("two-attempt test history must include recovery and lease")
    canary_id = "sha256:" + "1" * 64
    attempts: list[dict[str, object]] = []
    for attempt in range(1, attempt_count + 1):
        row: dict[str, object] = {
            "canary_id": canary_id,
            "attempt": attempt,
            "challenge_digest": "sha256:" + branch * 64,
            "resource_digest": "sha256:" + "2" * 64,
            "lease_token_digest": "sha256:" + "3" * 64,
            "lease_boot_id": f"boot-{branch}-{attempt}",
            "deadline_monotonic_ns": 1_000_000 + attempt,
            "lease_expires_at": (NOW + timedelta(seconds=60)).isoformat(
                timespec="microseconds"
            ),
            "acquired_at": NOW.isoformat(timespec="microseconds"),
        }
        row["attempt_evidence_digest"] = anchor_contract._digest(
            {"format": anchor_contract._ATTEMPT_EVIDENCE_FORMAT, **row}
        )
        attempts.append(row)
    events: list[dict[str, object]] = []
    prior: str | None = None
    event_plan = (
        [
            ("LEASE_ACQUIRED", 1),
            ("ACTION_STARTED", 1),
            ("CANARY_COMMITTED", 1),
        ]
        if attempt_count <= 1
        else [
            ("LEASE_ACQUIRED", 1),
            ("EXPIRED_LEASE_RECOVERED", 2),
            ("LEASE_ACQUIRED", 2),
            ("ACTION_STARTED", 2),
            ("CANARY_COMMITTED", 2),
        ]
    )
    result_digest = "sha256:" + "5" * 64
    for sequence, (event_type, attempt) in enumerate(
        event_plan[:event_count], start=1
    ):
        detail_digest = (
            result_digest
            if event_type == "CANARY_COMMITTED"
            else attempts[attempt - 1]["attempt_evidence_digest"]
        )
        body = {
            "format": "local-authority-staged-canary-event/v1",
            "sequence": sequence,
            "canary_id": canary_id,
            "event_type": event_type,
            "attempt": attempt,
            "observed_at": (NOW + timedelta(microseconds=sequence)).isoformat(
                timespec="microseconds"
            ),
            "lease_token_digest": attempts[attempt - 1]["lease_token_digest"],
            "detail_digest": detail_digest,
            "prior_event_digest": prior,
        }
        event = {**{name: value for name, value in body.items() if name != "format"}}
        event["event_digest"] = anchor_contract._digest(body)
        events.append(event)
        prior = event["event_digest"]
    runs: list[dict[str, object]] = []
    if attempts:
        latest = attempts[-1]
        committed = bool(events and events[-1]["event_type"] == "CANARY_COMMITTED")
        runs.append(
            {
                "canary_id": canary_id,
                "authority_id": "ready",
                "environment": "staging",
                "action": "ready:publish_profile_plan_bound",
                "source_sha": branch * 40,
                "runtime_bundle_digest": "sha256:" + "4" * 64,
                "resource_digest": latest["resource_digest"],
                "state": "COMMITTED" if committed else "RUNNING",
                "attempt_count": attempt_count,
                "lease_token_digest": None if committed else latest["lease_token_digest"],
                "lease_boot_id": None if committed else latest["lease_boot_id"],
                "deadline_monotonic_ns": (
                    None if committed else latest["deadline_monotonic_ns"]
                ),
                "lease_expires_at": None if committed else latest["lease_expires_at"],
                "challenge_digest": latest["challenge_digest"],
                "result_digest": result_digest if committed else None,
                "failure_class": None,
                "updated_at": (
                    events[-1]["observed_at"]
                    if events
                    else NOW.isoformat(timespec="microseconds")
                ),
            }
        )
    attempt_summary = [
        {
            "canary_id": row["canary_id"],
            "attempt": row["attempt"],
            "attempt_evidence_digest": row["attempt_evidence_digest"],
        }
        for row in attempts
    ]
    candidate = {
        "format": "local-authority-staged-canary-anchor-candidate/v3",
        "journal_schema_version": 4,
        "journal_format": "local-authority-staged-canary-journal/v4",
        "journal_instance_id": instance,
        "environment_set": ["production", "staging"],
        "policy_digest": canary.load_policy().digest,
        "principal_manifest_digest": canary.PINNED_MANIFEST_DIGEST,
        "event_count": event_count,
        "tail_event_sequence": event_count or None,
        "tail_event_digest": prior,
        "attempt_evidence_count": attempt_count,
        "attempt_evidence_set_digest": anchor_contract._digest(
            {
                "format": anchor_contract._ATTEMPT_EVIDENCE_SET_FORMAT,
                "attempts": attempt_summary,
            }
        ),
        "run_state_digest": anchor_contract._digest(
            {"format": anchor_contract._ANCHOR_RUN_STATE_FORMAT, "runs": runs}
        ),
    }
    return {
        "format": anchor_contract._ANCHOR_SNAPSHOT_FORMAT,
        "candidate": candidate,
        "events": events,
        "attempts": attempts,
        "runs": runs,
    }


def _rederive_candidate(snapshot: dict[str, object]) -> None:
    candidate = snapshot["candidate"]
    events = snapshot["events"]
    attempts = snapshot["attempts"]
    runs = snapshot["runs"]
    assert isinstance(candidate, dict)
    assert isinstance(events, list)
    assert isinstance(attempts, list)
    assert isinstance(runs, list)
    candidate["event_count"] = len(events)
    candidate["tail_event_sequence"] = len(events) or None
    candidate["tail_event_digest"] = events[-1]["event_digest"] if events else None
    attempt_summary = [
        {
            "canary_id": row["canary_id"],
            "attempt": row["attempt"],
            "attempt_evidence_digest": row["attempt_evidence_digest"],
        }
        for row in attempts
    ]
    candidate["attempt_evidence_count"] = len(attempts)
    candidate["attempt_evidence_set_digest"] = anchor_contract._digest(
        {"format": anchor_contract._ATTEMPT_EVIDENCE_SET_FORMAT, "attempts": attempt_summary}
    )
    candidate["run_state_digest"] = anchor_contract._digest(
        {"format": anchor_contract._ANCHOR_RUN_STATE_FORMAT, "runs": runs}
    )


def _append_running_canary(
    snapshot: dict[str, object], *, first_event_type: str = "LEASE_ACQUIRED"
) -> dict[str, object]:
    extended = json.loads(json.dumps(snapshot))
    candidate = extended["candidate"]
    events = extended["events"]
    attempts = extended["attempts"]
    runs = extended["runs"]
    canary_id = "sha256:" + "f" * 64
    attempt: dict[str, object] = {
        "canary_id": canary_id,
        "attempt": 1,
        "challenge_digest": "sha256:" + "6" * 64,
        "resource_digest": "sha256:" + "7" * 64,
        "lease_token_digest": "sha256:" + "8" * 64,
        "lease_boot_id": "boot-new-run-1",
        "deadline_monotonic_ns": 2_000_001,
        "lease_expires_at": (NOW + timedelta(seconds=120)).isoformat(
            timespec="microseconds"
        ),
        "acquired_at": (NOW + timedelta(seconds=60)).isoformat(
            timespec="microseconds"
        ),
    }
    attempt["attempt_evidence_digest"] = anchor_contract._digest(
        {"format": anchor_contract._ATTEMPT_EVIDENCE_FORMAT, **attempt}
    )
    attempts.append(attempt)
    sequence = len(events) + 1
    body = {
        "format": "local-authority-staged-canary-event/v1",
        "sequence": sequence,
        "canary_id": canary_id,
        "event_type": first_event_type,
        "attempt": 1,
        "observed_at": (NOW + timedelta(seconds=60, microseconds=sequence)).isoformat(
            timespec="microseconds"
        ),
        "lease_token_digest": attempt["lease_token_digest"],
        "detail_digest": attempt["attempt_evidence_digest"],
        "prior_event_digest": candidate["tail_event_digest"],
    }
    event = {name: value for name, value in body.items() if name != "format"}
    event["event_digest"] = anchor_contract._digest(body)
    events.append(event)
    runs.append(
        {
            "canary_id": canary_id,
            "authority_id": "ready",
            "environment": "production",
            "action": "ready:publish_profile_plan_bound",
            "source_sha": "f" * 40,
            "runtime_bundle_digest": "sha256:" + "9" * 64,
            "resource_digest": attempt["resource_digest"],
            "state": "RUNNING",
            "attempt_count": 1,
            "lease_token_digest": attempt["lease_token_digest"],
            "lease_boot_id": attempt["lease_boot_id"],
            "deadline_monotonic_ns": attempt["deadline_monotonic_ns"],
            "lease_expires_at": attempt["lease_expires_at"],
            "challenge_digest": attempt["challenge_digest"],
            "result_digest": None,
            "failure_class": None,
            "updated_at": event["observed_at"],
        }
    )
    _rederive_candidate(extended)
    return extended


def _many_terminal_snapshot(count: int) -> dict[str, object]:
    """Build a valid history large enough to expose full-inventory payloads."""

    if count < 1:
        raise ValueError("terminal history must be non-empty")
    snapshot = _snapshot()
    attempts = snapshot["attempts"]
    events = snapshot["events"]
    runs = snapshot["runs"]
    assert isinstance(attempts, list)
    assert isinstance(events, list)
    assert isinstance(runs, list)
    prior: str | None = None
    for index in range(1, count + 1):
        canary_id = anchor_contract._digest(
            f"terminal-canary-{index}".encode("ascii")
        )
        challenge_digest = anchor_contract._digest(
            f"challenge-{index}".encode("ascii")
        )
        resource_digest = anchor_contract._digest(
            f"resource-{index}".encode("ascii")
        )
        lease_digest = anchor_contract._digest(
            f"lease-{index}".encode("ascii")
        )
        result_digest = anchor_contract._digest(
            f"result-{index}".encode("ascii")
        )
        attempt: dict[str, object] = {
            "canary_id": canary_id,
            "attempt": 1,
            "challenge_digest": challenge_digest,
            "resource_digest": resource_digest,
            "lease_token_digest": lease_digest,
            "lease_boot_id": f"boot-terminal-{index}",
            "deadline_monotonic_ns": 3_000_000 + index,
            "lease_expires_at": (NOW + timedelta(seconds=60)).isoformat(
                timespec="microseconds"
            ),
            "acquired_at": NOW.isoformat(timespec="microseconds"),
        }
        attempt["attempt_evidence_digest"] = anchor_contract._digest(
            {"format": anchor_contract._ATTEMPT_EVIDENCE_FORMAT, **attempt}
        )
        attempts.append(attempt)
        for event_type in (
            "LEASE_ACQUIRED",
            "ACTION_STARTED",
            "CANARY_COMMITTED",
        ):
            sequence = len(events) + 1
            body = {
                "format": "local-authority-staged-canary-event/v1",
                "sequence": sequence,
                "canary_id": canary_id,
                "event_type": event_type,
                "attempt": 1,
                "observed_at": (NOW + timedelta(microseconds=sequence)).isoformat(
                    timespec="microseconds"
                ),
                "lease_token_digest": lease_digest,
                "detail_digest": (
                    result_digest
                    if event_type == "CANARY_COMMITTED"
                    else attempt["attempt_evidence_digest"]
                ),
                "prior_event_digest": prior,
            }
            event = {
                name: value for name, value in body.items() if name != "format"
            }
            event["event_digest"] = anchor_contract._digest(body)
            events.append(event)
            prior = event["event_digest"]
        runs.append(
            {
                "canary_id": canary_id,
                "authority_id": "ready",
                "environment": "staging",
                "action": "ready:publish_profile_plan_bound",
                "source_sha": f"{index:040x}",
                "runtime_bundle_digest": anchor_contract._digest(
                    f"bundle-{index}".encode("ascii")
                ),
                "resource_digest": resource_digest,
                "state": "COMMITTED",
                "attempt_count": 1,
                "lease_token_digest": None,
                "lease_boot_id": None,
                "deadline_monotonic_ns": None,
                "lease_expires_at": None,
                "challenge_digest": challenge_digest,
                "result_digest": result_digest,
                "failure_class": None,
                "updated_at": events[-1]["observed_at"],
            }
        )
    attempts.sort(key=lambda row: (row["canary_id"], row["attempt"]))
    runs.sort(key=lambda row: row["canary_id"])
    _rederive_candidate(snapshot)
    return snapshot


def _candidate(**kwargs: object) -> dict[str, object]:
    return dict(_snapshot(**kwargs)["candidate"])  # type: ignore[arg-type]


def _event_fork(snapshot: dict[str, object]) -> dict[str, object]:
    forged = json.loads(json.dumps(snapshot))
    prior: str | None = None
    for index, event in enumerate(forged["events"], start=1):
        if index == 1:
            event["observed_at"] = (
                NOW + timedelta(seconds=1, microseconds=index)
            ).isoformat(timespec="microseconds")
        event["prior_event_digest"] = prior
        body = {
            "format": "local-authority-staged-canary-event/v1",
            **{name: value for name, value in event.items() if name != "event_digest"},
        }
        event["event_digest"] = anchor_contract._digest(body)
        prior = event["event_digest"]
    forged["candidate"]["tail_event_digest"] = prior
    return forged


def _active_registry(
    remote_private: Ed25519PrivateKey,
) -> anchor_contract.AnchorKeyRegistry:
    public = remote_private.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw
    )
    document = {
        "format": anchor_contract.REGISTRY_FORMAT,
        "generation": 1,
        "authority_status": "ACTIVE",
        "authority_id": anchor_contract.AUTHORITY_ID,
        "environment_set": list(anchor_contract.ENVIRONMENT_SET),
        "keys": [
            {
                "key_id": "remote-anchor-1",
                "public_key_base64": base64.b64encode(public).decode("ascii"),
                "status": "ACTIVE",
            }
        ],
    }
    document["registry_digest"] = anchor_contract._self_digest(document, "registry_digest")
    return anchor_contract._evaluate_registry(
        document, expected_digest=document["registry_digest"]
    )


def _active_deployment(
    registry: anchor_contract.AnchorKeyRegistry, tmp_path: Path,
) -> anchor_contract.AnchorDeployment:
    document = json.loads(anchor_contract.DEPLOYMENT_PATH.read_text())
    document.update(
        {
            "activation_status": "ACTIVE",
            "provider_id": "behavior-test-abstract-authority",
            "endpoint": "https://anchor.invalid",
            "client_private_key_path": str(
                Path("/Library/Application Support/quant-platform/authorities/staged-canary/client.pem")
            ),
            "client_key_id": "local-collector-1",
            "remote_key_id": "remote-anchor-1",
            "public_key_registry_digest": registry.digest,
            "external_admin_separation_verified": True,
        }
    )
    document["deployment_digest"] = anchor_contract._self_digest(
        document, "deployment_digest"
    )
    return anchor_contract._evaluate_deployment(
        document,
        expected_digest=document["deployment_digest"],
        registry_digest=registry.digest,
    )


class _LoopbackTransport:
    def __init__(
        self, authority: anchor_authority.ReferenceExternalAnchorAuthority,
        *, now: datetime = NOW,
    ) -> None:
        self.authority = authority
        self.now = now
        self.paths: list[str] = []

    def post(self, path: str, raw: bytes) -> bytes:
        self.paths.append(path)
        if path.endswith("/challenge"):
            return self.authority.issue_challenge(raw, now=self.now)
        if path.endswith("/commit"):
            return self.authority.commit(raw, now=self.now + timedelta(seconds=1))
        if path.endswith("/resolve"):
            return self.authority.resolve(raw, now=self.now + timedelta(seconds=2))
        raise AssertionError("unexpected path")


def _fixture(tmp_path: Path) -> SimpleNamespace:
    client = Ed25519PrivateKey.generate()
    remote = Ed25519PrivateKey.generate()
    registry = _active_registry(remote)
    deployment = _active_deployment(registry, tmp_path)
    authority = anchor_authority.ReferenceExternalAnchorAuthority(
        remote_key_id="remote-anchor-1",
        remote_private_key=remote,
        client_keys={"local-collector-1": client.public_key()},
    )
    audit = anchor_store.AnchorReceiptAudit(
        tmp_path / "audit",
        expected_owner_uid=os.getuid(),
        expected_owner_gid=os.getgid(),
    )
    return SimpleNamespace(
        client=client,
        remote=remote,
        registry=registry,
        deployment=deployment,
        authority=authority,
        transport=_LoopbackTransport(authority),
        audit=audit,
    )


def _collect(
    fixture: SimpleNamespace, snapshot: dict[str, object],
    *, request_nonce: str = "5" * 64,
) -> dict[str, object]:
    return dict(
        anchor._collect_once(
            snapshot=snapshot,
            deployment=fixture.deployment,
            registry=fixture.registry,
            client_private_key=fixture.client,
            transport=fixture.transport,
            audit=fixture.audit,
            now=lambda: NOW + timedelta(seconds=2),
            nonce=lambda: request_nonce,
        )
    )


def _direct_commit(
    fixture: SimpleNamespace, snapshot: dict[str, object], *, nonce: str
) -> dict[str, object]:
    candidate = snapshot["candidate"]
    request = anchor_contract._challenge_request(
        candidate,
        client_key_id="local-collector-1",
        client_private_key=fixture.client,
        request_nonce=nonce,
    )
    challenge_raw = fixture.authority.issue_challenge(
        canary.canonical_json_bytes(request), now=NOW
    )
    challenge = anchor_contract._validate_challenge(
        challenge_raw,
        registry=fixture.registry,
        challenge_request=request,
        candidate=candidate,
        expected_generation=fixture.authority.generation + 1,
        expected_prior_anchor_digest=fixture.authority.accepted_anchor_digest,
        now=NOW,
    )
    commit = anchor_contract._commit_request(
        candidate=candidate,
        challenge=challenge,
        lineage_proof=_caller_supplied_proof(fixture, snapshot),
        client_key_id="local-collector-1",
        client_private_key=fixture.client,
    )
    return json.loads(
        fixture.authority.commit(
            canary.canonical_json_bytes(commit), now=NOW + timedelta(seconds=1)
        )
    )


def _caller_supplied_proof(
    fixture: SimpleNamespace, snapshot: dict[str, object]
) -> dict[str, object]:
    """Build closed bytes without trusting the local lineage verifier."""

    previous = fixture.authority._accepted_candidate
    candidate = snapshot["candidate"]
    base_count = 0 if previous is None else previous["event_count"]
    retained_attempts = {
        (row["canary_id"], row["attempt"]): row
        for row in fixture.authority._accepted_attempts
    }
    retained_runs = {
        row["canary_id"]: row for row in fixture.authority._accepted_runs
    }
    return {
        "format": anchor_contract.LINEAGE_PROOF_FORMAT,
        "journal_instance_id": candidate["journal_instance_id"],
        "environment_set": list(anchor_contract.ENVIRONMENT_SET),
        "prior_anchor_digest": fixture.authority.accepted_anchor_digest,
        "prior_anchor_candidate_digest": (
            None if previous is None else anchor_contract._digest(previous)
        ),
        "base_event_count": base_count,
        "base_tail_event_digest": (
            None if previous is None else previous["tail_event_digest"]
        ),
        "event_suffix": snapshot["events"][base_count:],
        "previous_attempt_evidence_set_digest": (
            None if previous is None else previous["attempt_evidence_set_digest"]
        ),
        "new_attempt_records": [
            row
            for row in snapshot["attempts"]
            if (row["canary_id"], row["attempt"]) not in retained_attempts
        ],
        "changed_run_records": [
            row
            for row in snapshot["runs"]
            if retained_runs.get(row["canary_id"]) != row
        ],
        "anchor_candidate_digest": anchor_contract._digest(candidate),
    }


def test_checked_in_deployment_is_source_ready_but_operational_hold(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = anchor.anchor_plan()
    assert plan["source_state"] == "SOURCE_READY"
    assert plan["operational_state"] == "HOLD"
    assert plan["provider_selected"] is False
    assert plan["active_remote_keys"] == 0
    assert plan["commit_recovery"] == (
        "ATOMIC_ACCEPTED_OR_NOT_ACCEPTED_RESOLUTION_FROM_DURABLE_SUBMISSION"
    )
    assert plan["transport_timeout_scope"] == "PER_BLOCKING_IO_NOT_TOTAL_DEADLINE"
    assert plan["authority_signature_provenance_verified_by_anchor"] is False
    assert plan["remote_key_rotation_supported"] is False
    assert plan["client_key_rotation_supported"] is False
    assert plan["historical_verification_keys_required"] is True
    assert "HISTORICAL_KEY_REGISTRIES_NOT_IMPLEMENTED" in plan["blockers"]
    monkeypatch.setattr(
        anchor,
        "anchor_lineage_snapshot",
        lambda: pytest.fail("HOLD must precede journal or network access"),
    )
    with pytest.raises(anchor.AnchorOperationalHold, match="operational HOLD"):
        anchor.collect_anchor()
    assert anchor_manager.main(["plan"]) == 0
    assert anchor_manager.main(["collect"]) == 1
    with pytest.raises(TypeError):
        anchor.collect_anchor(endpoint="https://attacker.invalid")  # type: ignore[call-arg]
    with pytest.raises(SystemExit):
        anchor_manager.main(["collect", "--endpoint", "https://attacker.invalid"])


def test_two_generations_bind_exact_candidate_and_append_reverified_audit(
    tmp_path: Path,
) -> None:
    fixture = _fixture(tmp_path)
    first_snapshot = _snapshot()
    first_candidate = first_snapshot["candidate"]
    first = _collect(fixture, first_snapshot)
    assert first["generation"] == 1
    assert first["prior_anchor_digest"] is None
    assert first["anchor_candidate_digest"] == anchor_contract._digest(first_candidate)
    second_snapshot = _snapshot(event_count=2, attempt_count=1)
    second_candidate = second_snapshot["candidate"]
    second = _collect(fixture, second_snapshot)
    assert second["generation"] == 2
    assert second["prior_anchor_digest"] == first["accepted_anchor_digest"]
    assert fixture.authority.generation == 2
    assert fixture.transport.paths == [
        fixture.deployment.challenge_path,
        fixture.deployment.commit_path,
        fixture.deployment.challenge_path,
        fixture.deployment.commit_path,
    ]
    records = fixture.audit.records()
    assert len(records) == 2
    assert records[-1]["receipt"] == second
    schema = json.loads(anchor_contract.PROTOCOL_SCHEMA_PATH.read_text())
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    for name in ("challenge_request", "challenge", "commit_request", "receipt"):
        assert list(validator.iter_errors(records[-1][name])) == []


def test_lineage_v2_delta_payload_stays_bounded_after_large_retained_history() -> None:
    retained = _many_terminal_snapshot(160)
    current = _append_running_canary(retained)
    assert len(canary.canonical_json_bytes(retained)) > anchor_contract.MAX_DOCUMENT_BYTES
    prior_anchor_digest = "sha256:" + "a" * 64
    proof = anchor_contract._build_lineage_proof(
        current,
        previous_candidate=retained["candidate"],
        previous_attempts=retained["attempts"],
        previous_runs=retained["runs"],
        previous_events=retained["events"],
        prior_anchor_digest=prior_anchor_digest,
    )
    assert proof["format"] == "local-authority-high-water-anchor-lineage-proof/v2"
    assert len(proof["event_suffix"]) == 1
    assert len(proof["new_attempt_records"]) == 1
    assert len(proof["changed_run_records"]) == 1
    client = Ed25519PrivateKey.generate()
    commit = anchor_contract._commit_request(
        candidate=current["candidate"],
        challenge={
            "generation": 2,
            "prior_anchor_digest": prior_anchor_digest,
            "challenge_digest": "sha256:" + "b" * 64,
            "nonce": "c" * 64,
        },
        lineage_proof=proof,
        client_key_id="local-collector-1",
        client_private_key=client,
    )
    assert len(canary.canonical_json_bytes(commit)) < anchor_contract.MAX_DOCUMENT_BYTES
    attempts, runs, events = anchor_contract._verify_lineage_proof(
        proof,
        candidate=current["candidate"],
        previous_candidate=retained["candidate"],
        previous_attempts=retained["attempts"],
        previous_runs=retained["runs"],
        previous_events=retained["events"],
        prior_anchor_digest=prior_anchor_digest,
    )
    assert attempts == current["attempts"]
    assert runs == current["runs"]
    assert events == current["events"]


def test_lineage_v2_rejects_nonminimal_or_prior_record_deltas() -> None:
    retained = _snapshot(event_count=3, attempt_count=1)
    current = _append_running_canary(retained)
    prior_anchor_digest = "sha256:" + "d" * 64
    proof = anchor_contract._build_lineage_proof(
        current,
        previous_candidate=retained["candidate"],
        previous_attempts=retained["attempts"],
        previous_runs=retained["runs"],
        previous_events=retained["events"],
        prior_anchor_digest=prior_anchor_digest,
    )
    replayed_attempt = json.loads(json.dumps(proof))
    replayed_attempt["new_attempt_records"].insert(0, retained["attempts"][0])
    with pytest.raises(anchor_contract.AnchorProtocolError, match="rewrote immutable"):
        anchor_contract._verify_lineage_proof(
            replayed_attempt,
            candidate=current["candidate"],
            previous_candidate=retained["candidate"],
            previous_attempts=retained["attempts"],
            previous_runs=retained["runs"],
            previous_events=retained["events"],
            prior_anchor_digest=prior_anchor_digest,
        )
    unchanged_run = json.loads(json.dumps(proof))
    unchanged_run["changed_run_records"].insert(0, retained["runs"][0])
    unchanged_run["changed_run_records"].sort(key=lambda row: row["canary_id"])
    with pytest.raises(anchor_contract.AnchorProtocolError, match="not minimal"):
        anchor_contract._verify_lineage_proof(
            unchanged_run,
            candidate=current["candidate"],
            previous_candidate=retained["candidate"],
            previous_attempts=retained["attempts"],
            previous_runs=retained["runs"],
            previous_events=retained["events"],
            prior_anchor_digest=prior_anchor_digest,
        )


def test_challenge_replay_is_rejected_and_exact_commit_is_idempotent(
    tmp_path: Path,
) -> None:
    fixture = _fixture(tmp_path)
    snapshot = _snapshot()
    candidate = snapshot["candidate"]
    request = anchor_contract._challenge_request(
        candidate,
        client_key_id="local-collector-1",
        client_private_key=fixture.client,
        request_nonce="9" * 64,
    )
    raw_request = canary.canonical_json_bytes(request)
    challenge_raw = fixture.authority.issue_challenge(raw_request, now=NOW)
    with pytest.raises(anchor_contract.AnchorProtocolError, match="replay"):
        fixture.authority.issue_challenge(raw_request, now=NOW)
    challenge = anchor_contract._validate_challenge(
        challenge_raw,
        registry=fixture.registry,
        challenge_request=request,
        candidate=candidate,
        expected_generation=1,
        expected_prior_anchor_digest=None,
        now=NOW,
    )
    commit = anchor_contract._commit_request(
        candidate=candidate,
        challenge=challenge,
        lineage_proof=anchor_contract._build_lineage_proof(
            snapshot,
            previous_candidate=None,
            previous_attempts=[],
            previous_runs=[],
            previous_events=[],
            prior_anchor_digest=None,
        ),
        client_key_id="local-collector-1",
        client_private_key=fixture.client,
    )
    raw_commit = canary.canonical_json_bytes(commit)
    first = fixture.authority.commit(raw_commit, now=NOW + timedelta(seconds=1))
    recovered = fixture.authority.commit(
        raw_commit, now=NOW + timedelta(seconds=120)
    )
    assert recovered == first


def test_concurrent_challenges_cannot_fork_one_generation(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    snapshot = _snapshot()
    candidate = snapshot["candidate"]
    proof = anchor_contract._build_lineage_proof(
        snapshot,
        previous_candidate=None,
        previous_attempts=[],
        previous_runs=[],
        previous_events=[],
        prior_anchor_digest=None,
    )
    requests = [
        anchor_contract._challenge_request(
            candidate,
            client_key_id="local-collector-1",
            client_private_key=fixture.client,
            request_nonce=character * 64,
        )
        for character in ("a", "b")
    ]
    challenges = [
        anchor_contract._validate_challenge(
            fixture.authority.issue_challenge(
                canary.canonical_json_bytes(request), now=NOW
            ),
            registry=fixture.registry,
            challenge_request=request,
            candidate=candidate,
            expected_generation=1,
            expected_prior_anchor_digest=None,
            now=NOW,
        )
        for request in requests
    ]
    commits = [
        anchor_contract._commit_request(
            candidate=candidate,
            challenge=challenge,
            lineage_proof=proof,
            client_key_id="local-collector-1",
            client_private_key=fixture.client,
        )
        for challenge in challenges
    ]
    fixture.authority.commit(
        canary.canonical_json_bytes(commits[0]), now=NOW + timedelta(seconds=1)
    )
    with pytest.raises(anchor_contract.AnchorProtocolError, match="compare-and-swap"):
        fixture.authority.commit(
            canary.canonical_json_bytes(commits[1]), now=NOW + timedelta(seconds=1)
        )


@pytest.mark.parametrize(
    "second",
    [
        _snapshot(event_count=1, branch="a"),
        _snapshot(
            instance="journal-instance:" + "f" * 64,
            event_count=3,
            branch="b",
        ),
    ],
)
def test_rollback_and_journal_instance_substitution_are_rejected(
    tmp_path: Path, second: dict[str, object],
) -> None:
    fixture = _fixture(tmp_path)
    _collect(
        fixture,
        _snapshot(event_count=2, attempt_count=1, branch="c"),
    )
    with pytest.raises(anchor_contract.AnchorProtocolError, match="accepted base|substitution"):
        _collect(fixture, second)


def test_equal_high_water_with_changed_digest_is_a_fork(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    _collect(
        fixture,
        _snapshot(event_count=1, branch="a"),
    )
    with pytest.raises(
        anchor_contract.AnchorProtocolError,
        match="base|fork|contiguous|latest attempt",
    ):
        _collect(
            fixture,
            _snapshot(event_count=1, branch="b"),
        )


def test_remote_authority_itself_rejects_rollback_and_equal_height_fork(
    tmp_path: Path,
) -> None:
    fixture = _fixture(tmp_path)
    _direct_commit(
        fixture,
        _snapshot(event_count=2, branch="a"),
        nonce="1" * 64,
    )
    with pytest.raises(anchor_contract.AnchorProtocolError, match="rollback"):
        _direct_commit(
            fixture,
            _snapshot(event_count=1, branch="a"),
            nonce="2" * 64,
        )
    with pytest.raises(anchor_contract.AnchorProtocolError, match="base|fork|contiguous"):
        _direct_commit(
            fixture,
            _event_fork(_snapshot(event_count=2, branch="a")),
            nonce="3" * 64,
        )


def test_remote_rejects_higher_height_fork_with_caller_signed_proof(
    tmp_path: Path,
) -> None:
    fixture = _fixture(tmp_path)
    _direct_commit(fixture, _snapshot(event_count=2, branch="a"), nonce="1" * 64)
    malicious = _event_fork(_snapshot(event_count=3, branch="a"))
    with pytest.raises(anchor_contract.AnchorProtocolError, match="contiguous|fork"):
        _direct_commit(fixture, malicious, nonce="2" * 64)
    assert fixture.authority.generation == 1


def test_remote_rejects_rewritten_attempt_even_when_attempt_count_increases(
    tmp_path: Path,
) -> None:
    fixture = _fixture(tmp_path)
    _direct_commit(
        fixture,
        _snapshot(event_count=1, attempt_count=1, branch="a"),
        nonce="1" * 64,
    )
    malicious = _snapshot(event_count=3, attempt_count=2, branch="a")
    first_attempt = malicious["attempts"][0]
    first_attempt["resource_digest"] = "sha256:" + "9" * 64
    first_attempt["attempt_evidence_digest"] = anchor_contract._digest(
        {
            "format": anchor_contract._ATTEMPT_EVIDENCE_FORMAT,
            **{
                name: first_attempt[name]
                for name in (
                    "canary_id",
                    "attempt",
                    "challenge_digest",
                    "resource_digest",
                    "lease_token_digest",
                    "lease_boot_id",
                    "deadline_monotonic_ns",
                    "lease_expires_at",
                    "acquired_at",
                )
            },
        }
    )
    _rederive_candidate(malicious)
    with pytest.raises(
        anchor_contract.AnchorProtocolError,
        match="attempt history forked|does not rederive candidate",
    ):
        _direct_commit(fixture, malicious, nonce="2" * 64)
    assert fixture.authority.generation == 1


def test_remote_rejects_new_attempt_without_exact_suffix_lease(
    tmp_path: Path,
) -> None:
    fixture = _fixture(tmp_path)
    accepted = _snapshot(event_count=1, attempt_count=1)
    _direct_commit(fixture, accepted, nonce="1" * 64)
    malicious = json.loads(json.dumps(accepted))
    first = malicious["attempts"][0]
    second = {
        **first,
        "attempt": 2,
        "lease_boot_id": "boot-unproven-attempt-2",
        "deadline_monotonic_ns": 3_000_002,
        "lease_expires_at": (NOW + timedelta(seconds=180)).isoformat(
            timespec="microseconds"
        ),
        "acquired_at": (NOW + timedelta(seconds=120)).isoformat(
            timespec="microseconds"
        ),
    }
    second["attempt_evidence_digest"] = anchor_contract._digest(
        {
            "format": anchor_contract._ATTEMPT_EVIDENCE_FORMAT,
            **{
                name: second[name]
                for name in (
                    "canary_id",
                    "attempt",
                    "challenge_digest",
                    "resource_digest",
                    "lease_token_digest",
                    "lease_boot_id",
                    "deadline_monotonic_ns",
                    "lease_expires_at",
                    "acquired_at",
                )
            },
        }
    )
    malicious["attempts"].append(second)
    run = malicious["runs"][0]
    run.update(
        {
            "attempt_count": 2,
            "lease_boot_id": second["lease_boot_id"],
            "deadline_monotonic_ns": second["deadline_monotonic_ns"],
            "lease_expires_at": second["lease_expires_at"],
            "updated_at": (NOW + timedelta(seconds=121)).isoformat(
                timespec="microseconds"
            ),
        }
    )
    prior = malicious["events"][-1]["event_digest"]
    event_body = {
        "format": "local-authority-staged-canary-event/v1",
        "sequence": 2,
        "canary_id": first["canary_id"],
        "event_type": "ACTION_STARTED",
        "attempt": 1,
        "observed_at": (NOW + timedelta(seconds=121)).isoformat(
            timespec="microseconds"
        ),
        "lease_token_digest": first["lease_token_digest"],
        "detail_digest": first["attempt_evidence_digest"],
        "prior_event_digest": prior,
    }
    event = {
        name: value for name, value in event_body.items() if name != "format"
    }
    event["event_digest"] = anchor_contract._digest(event_body)
    malicious["events"].append(event)
    _rederive_candidate(malicious)
    with pytest.raises(
        anchor_contract.AnchorProtocolError,
        match="new attempt inventory lacks exact lease-acquired lineage",
    ):
        _direct_commit(fixture, malicious, nonce="2" * 64)
    assert fixture.authority.generation == 1


def test_remote_rejects_new_run_without_first_lease_event(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    _direct_commit(fixture, _snapshot(), nonce="1" * 64)
    malicious = _append_running_canary(
        _snapshot(), first_event_type="ACTION_STARTED"
    )
    with pytest.raises(
        anchor_contract.AnchorProtocolError,
        match="new attempt inventory lacks exact lease-acquired lineage|new run lacks first lease lineage",
    ):
        _direct_commit(fixture, malicious, nonce="2" * 64)
    assert fixture.authority.generation == 1


def test_remote_rejects_terminal_run_rewrite_hidden_by_unrelated_suffix(
    tmp_path: Path,
) -> None:
    fixture = _fixture(tmp_path)
    terminal = _snapshot(event_count=3, attempt_count=1)
    _direct_commit(fixture, terminal, nonce="1" * 64)
    malicious = _append_running_canary(terminal)
    malicious["runs"][0]["result_digest"] = "sha256:" + "0" * 64
    _rederive_candidate(malicious)
    with pytest.raises(
        anchor_contract.AnchorProtocolError,
        match="terminal run was rewritten|committed event result is inconsistent",
    ):
        _direct_commit(fixture, malicious, nonce="2" * 64)
    assert fixture.authority.generation == 1


def test_remote_rejects_nonterminal_run_rewrite_hidden_by_unrelated_suffix(
    tmp_path: Path,
) -> None:
    fixture = _fixture(tmp_path)
    running = _snapshot(event_count=1, attempt_count=1)
    _direct_commit(fixture, running, nonce="1" * 64)
    malicious = _append_running_canary(running)
    old_run = malicious["runs"][0]
    old_run.update(
        {
            "state": "FAILED_FINAL",
            "lease_token_digest": None,
            "lease_boot_id": None,
            "deadline_monotonic_ns": None,
            "lease_expires_at": None,
            "failure_class": "rewritten-without-event",
            "updated_at": (NOW + timedelta(seconds=61)).isoformat(
                timespec="microseconds"
            ),
        }
    )
    _rederive_candidate(malicious)
    with pytest.raises(
        anchor_contract.AnchorProtocolError, match="changed without a suffix transition"
    ):
        _direct_commit(fixture, malicious, nonce="2" * 64)
    assert fixture.authority.generation == 1


def test_zero_to_first_and_unchanged_snapshot_are_both_closed_lineages(
    tmp_path: Path,
) -> None:
    fixture = _fixture(tmp_path)
    first = _collect(fixture, _snapshot())
    second = _collect(fixture, _snapshot(), request_nonce="6" * 64)
    assert first["generation"] == 1
    assert second["generation"] == 2
    assert fixture.audit.records()[1]["commit_request"]["lineage_proof"][
        "event_suffix"
    ] == []


def test_remote_accept_then_local_audit_crash_recovers_exact_receipt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = _fixture(tmp_path)
    real_append = fixture.audit.append
    crashed = False

    def crash_once(**kwargs: object) -> dict[str, object]:
        nonlocal crashed
        if not crashed:
            crashed = True
            raise RuntimeError("simulated local crash after remote accept")
        return real_append(**kwargs)

    monkeypatch.setattr(fixture.audit, "append", crash_once)
    with pytest.raises(RuntimeError, match="simulated local crash"):
        _collect(fixture, _snapshot())
    assert fixture.authority.generation == 1
    assert fixture.audit.records() == []
    assert len(fixture.audit.submissions()) == 1

    recovered = _collect(fixture, _snapshot(), request_nonce="6" * 64)
    assert recovered["generation"] == 1
    assert fixture.authority.generation == 1
    assert len(fixture.audit.records()) == 1
    assert fixture.transport.paths == [
        fixture.deployment.challenge_path,
        fixture.deployment.commit_path,
        fixture.deployment.resolution_path,
    ]


def test_lost_before_send_is_atomically_abandoned_then_same_generation_retried(
    tmp_path: Path,
) -> None:
    fixture = _fixture(tmp_path)

    class DropBeforeSendTransport:
        def __init__(self) -> None:
            self.clock = NOW
            self.dropped = False
            self.paths: list[str] = []

        def post(self, path: str, raw: bytes) -> bytes:
            self.paths.append(path)
            if path == fixture.deployment.challenge_path:
                return fixture.authority.issue_challenge(raw, now=self.clock)
            if path == fixture.deployment.resolution_path:
                return fixture.authority.resolve(raw, now=self.clock)
            if path == fixture.deployment.commit_path and not self.dropped:
                self.dropped = True
                raise anchor_contract.AnchorProtocolError("simulated loss before remote receive")
            if path == fixture.deployment.commit_path:
                return fixture.authority.commit(
                    raw, now=self.clock + timedelta(seconds=1)
                )
            raise AssertionError("unexpected path")

    transport = DropBeforeSendTransport()
    with pytest.raises(anchor_contract.AnchorProtocolError, match="loss before remote receive"):
        anchor._collect_once(
            snapshot=_snapshot(),
            deployment=fixture.deployment,
            registry=fixture.registry,
            client_private_key=fixture.client,
            transport=transport,
            audit=fixture.audit,
            now=lambda: transport.clock + timedelta(seconds=2),
            nonce=lambda: "5" * 64,
        )
    assert fixture.authority.generation == 0
    assert len(fixture.audit.submissions()) == 1
    assert fixture.audit.records() == []

    transport.clock = NOW + timedelta(seconds=120)
    receipt = anchor._collect_once(
        snapshot=_snapshot(),
        deployment=fixture.deployment,
        registry=fixture.registry,
        client_private_key=fixture.client,
        transport=transport,
        audit=fixture.audit,
        now=lambda: transport.clock + timedelta(seconds=2),
        nonce=lambda: "6" * 64,
    )
    assert receipt["generation"] == 1
    assert fixture.authority.generation == 1
    assert len(fixture.audit.submissions()) == 2
    abandonments = fixture.audit.abandonments()
    assert len(abandonments) == 1
    assert len(fixture.audit.records()) == 1
    validator = Draft202012Validator(
        json.loads(anchor_contract.PROTOCOL_SCHEMA_PATH.read_text()),
        format_checker=FormatChecker(),
    )
    assert list(
        validator.iter_errors(abandonments[0]["resolution_request"])
    ) == []
    assert list(
        validator.iter_errors(abandonments[0]["resolution_response"])
    ) == []
    assert transport.paths == [
        fixture.deployment.challenge_path,
        fixture.deployment.commit_path,
        fixture.deployment.resolution_path,
        fixture.deployment.challenge_path,
        fixture.deployment.commit_path,
    ]


def test_lost_commit_response_is_recovered_by_signed_resolution(
    tmp_path: Path,
) -> None:
    fixture = _fixture(tmp_path)

    class LoseAcceptedResponseTransport:
        def __init__(self) -> None:
            self.lost = False
            self.paths: list[str] = []

        def post(self, path: str, raw: bytes) -> bytes:
            self.paths.append(path)
            if path == fixture.deployment.challenge_path:
                return fixture.authority.issue_challenge(raw, now=NOW)
            if path == fixture.deployment.resolution_path:
                return fixture.authority.resolve(
                    raw, now=NOW + timedelta(seconds=3)
                )
            if path == fixture.deployment.commit_path:
                accepted = fixture.authority.commit(
                    raw, now=NOW + timedelta(seconds=1)
                )
                if not self.lost:
                    self.lost = True
                    raise anchor_contract.AnchorProtocolError(
                        "simulated loss after remote acceptance"
                    )
                return accepted
            raise AssertionError("unexpected path")

    transport = LoseAcceptedResponseTransport()
    with pytest.raises(anchor_contract.AnchorProtocolError, match="remote acceptance"):
        anchor._collect_once(
            snapshot=_snapshot(),
            deployment=fixture.deployment,
            registry=fixture.registry,
            client_private_key=fixture.client,
            transport=transport,
            audit=fixture.audit,
            now=lambda: NOW + timedelta(seconds=2),
            nonce=lambda: "5" * 64,
        )
    assert fixture.authority.generation == 1
    receipt = anchor._collect_once(
        snapshot=_snapshot(),
        deployment=fixture.deployment,
        registry=fixture.registry,
        client_private_key=fixture.client,
        transport=transport,
        audit=fixture.audit,
        now=lambda: NOW + timedelta(seconds=4),
        nonce=lambda: "6" * 64,
    )
    assert receipt["generation"] == 1
    assert len(fixture.audit.records()) == 1
    assert fixture.audit.abandonments() == []
    assert transport.paths == [
        fixture.deployment.challenge_path,
        fixture.deployment.commit_path,
        fixture.deployment.resolution_path,
    ]


def test_commit_and_resolution_are_one_atomic_remote_decision(
    tmp_path: Path,
) -> None:
    fixture = _fixture(tmp_path)
    snapshot = _snapshot()
    candidate = snapshot["candidate"]
    challenge_request = anchor_contract._challenge_request(
        candidate,
        client_key_id="local-collector-1",
        client_private_key=fixture.client,
        request_nonce="7" * 64,
    )
    challenge = anchor_contract._validate_challenge(
        fixture.authority.issue_challenge(
            canary.canonical_json_bytes(challenge_request), now=NOW
        ),
        registry=fixture.registry,
        challenge_request=challenge_request,
        candidate=candidate,
        expected_generation=1,
        expected_prior_anchor_digest=None,
        now=NOW,
    )
    commit = anchor_contract._commit_request(
        candidate=candidate,
        challenge=challenge,
        lineage_proof=anchor_contract._build_lineage_proof(
            snapshot,
            previous_candidate=None,
            previous_attempts=[],
            previous_runs=[],
            previous_events=[],
            prior_anchor_digest=None,
        ),
        client_key_id="local-collector-1",
        client_private_key=fixture.client,
    )
    resolution_request = anchor_contract._resolution_request(
        commit,
        request_nonce="8" * 64,
        client_key_id="local-collector-1",
        client_private_key=fixture.client,
    )
    barrier = threading.Barrier(3)
    outcomes: dict[str, object] = {}

    def invoke_commit() -> None:
        barrier.wait(timeout=5)
        try:
            outcomes["commit"] = json.loads(
                fixture.authority.commit(
                    canary.canonical_json_bytes(commit),
                    now=NOW + timedelta(seconds=1),
                )
            )
        except anchor_contract.AnchorProtocolError as exc:
            outcomes["commit"] = str(exc)

    def invoke_resolution() -> None:
        barrier.wait(timeout=5)
        outcomes["resolution"] = json.loads(
            fixture.authority.resolve(
                canary.canonical_json_bytes(resolution_request),
                now=NOW + timedelta(seconds=1),
            )
        )

    threads = [
        threading.Thread(target=invoke_commit),
        threading.Thread(target=invoke_resolution),
    ]
    for thread in threads:
        thread.start()
    barrier.wait(timeout=5)
    for thread in threads:
        thread.join(timeout=5)
        assert not thread.is_alive()
    resolution = outcomes["resolution"]
    if fixture.authority.generation == 1:
        assert isinstance(outcomes["commit"], dict)
        assert resolution["status"] == "ACCEPTED"
        assert resolution["receipt"] == outcomes["commit"]
    else:
        assert fixture.authority.generation == 0
        assert "atomically abandoned" in outcomes["commit"]
        assert resolution["status"] == "NOT_ACCEPTED"


def test_process_collectors_share_one_pinned_nonblocking_lock(
    tmp_path: Path,
) -> None:
    if "fork" not in multiprocessing.get_all_start_methods():
        pytest.skip("POSIX fork is required for the process-lock behavior test")
    fixture = _fixture(tmp_path)
    context = multiprocessing.get_context("fork")
    rpc_started = context.Event()
    release_rpc = context.Event()
    outcomes = context.Queue()

    def winner() -> None:
        class BlockingTransport:
            def post(self, path: str, raw: bytes) -> bytes:
                if path == fixture.deployment.challenge_path:
                    outcomes.put(("winner_rpc", path))
                    rpc_started.set()
                    if not release_rpc.wait(timeout=5):
                        raise RuntimeError("test release was not delivered")
                    return fixture.authority.issue_challenge(raw, now=NOW)
                if path == fixture.deployment.commit_path:
                    return fixture.authority.commit(
                        raw, now=NOW + timedelta(seconds=1)
                    )
                if path == fixture.deployment.resolution_path:
                    return fixture.authority.resolve(
                        raw, now=NOW + timedelta(seconds=2)
                    )
                raise AssertionError("unexpected path")

        try:
            receipt = anchor._collect_once(
                snapshot=_snapshot(),
                deployment=fixture.deployment,
                registry=fixture.registry,
                client_private_key=fixture.client,
                transport=BlockingTransport(),
                audit=fixture.audit,
                now=lambda: NOW + timedelta(seconds=2),
                nonce=lambda: "a" * 64,
            )
        except Exception as exc:  # pragma: no cover - reported to parent
            outcomes.put(("winner_error", repr(exc)))
        else:
            outcomes.put(("winner", receipt["generation"]))

    def loser() -> None:
        class NoRpcTransport:
            def post(self, path: str, _raw: bytes) -> bytes:
                outcomes.put(("loser_rpc", path))
                raise AssertionError("losing collector reached remote RPC")

        try:
            anchor._collect_once(
                snapshot=_snapshot(),
                deployment=fixture.deployment,
                registry=fixture.registry,
                client_private_key=fixture.client,
                transport=NoRpcTransport(),
                audit=fixture.audit,
                now=lambda: NOW + timedelta(seconds=2),
                nonce=lambda: "b" * 64,
            )
        except anchor_contract.AnchorProtocolError as exc:
            outcomes.put(("loser", str(exc)))
        except Exception as exc:  # pragma: no cover - reported to parent
            outcomes.put(("loser_error", repr(exc)))
        else:
            outcomes.put(("loser_accepted", None))

    winner_process = context.Process(target=winner)
    winner_process.start()
    assert rpc_started.wait(timeout=5)
    loser_process = context.Process(target=loser)
    loser_process.start()
    loser_process.join(timeout=5)
    assert not loser_process.is_alive()
    release_rpc.set()
    winner_process.join(timeout=5)
    assert not winner_process.is_alive()
    assert winner_process.exitcode == 0
    assert loser_process.exitcode == 0
    observed = [outcomes.get(timeout=5) for _ in range(3)]
    assert ("winner_rpc", fixture.deployment.challenge_path) in observed
    assert ("winner", 1) in observed
    loser_outcome = next(value for key, value in observed if key == "loser")
    assert "already running" in loser_outcome
    assert not any(key == "loser_rpc" for key, _value in observed)
    assert len(fixture.audit.submissions()) == 1
    assert len(fixture.audit.records()) == 1


def test_forked_child_cannot_reuse_parent_collector_lock(tmp_path: Path) -> None:
    if "fork" not in multiprocessing.get_all_start_methods():
        pytest.skip("POSIX fork is required for the inherited-lock behavior test")
    fixture = _fixture(tmp_path)
    context = multiprocessing.get_context("fork")
    outcome = context.Queue()

    def child() -> None:
        try:
            fixture.audit._require_collector_lock()
        except anchor_contract.AnchorProtocolError as exc:
            outcome.put(str(exc))
        else:
            outcome.put("INHERITED")

    with fixture.audit.collector_lock():
        process = context.Process(target=child)
        process.start()
        process.join(timeout=5)
        assert not process.is_alive()
        assert process.exitcode == 0
        assert "ownership is absent" in outcome.get(timeout=5)
        fixture.audit._require_collector_lock()


def test_collector_lock_check_proves_the_exact_ofd_owns_flock(
    tmp_path: Path,
) -> None:
    """A same-UID independently opened fd is not a lock capability."""

    if "fork" not in multiprocessing.get_all_start_methods():
        pytest.skip("POSIX fork is required for the process-lock behavior test")
    path = tmp_path / "audit"
    context = multiprocessing.get_context("fork")
    held = context.Event()
    release = context.Event()

    def holder() -> None:
        audit = anchor_store.AnchorReceiptAudit(
            path,
            expected_owner_uid=os.getuid(),
            expected_owner_gid=os.getgid(),
        )
        with audit.collector_lock():
            held.set()
            if not release.wait(timeout=5):
                raise RuntimeError("test release was not delivered")

    process = context.Process(target=holder)
    process.start()
    assert held.wait(timeout=5)
    directory_fd = os.open(path, os.O_RDONLY)
    lock_fd = os.open(path / ".collector.lock", os.O_RDWR)
    guard_fd = os.dup(lock_fd)
    cookie = 97
    os.lseek(lock_fd, cookie, os.SEEK_SET)
    forged = anchor_store.AnchorReceiptAudit(
        path,
        expected_owner_uid=os.getuid(),
        expected_owner_gid=os.getgid(),
    )
    forged._collector_lock_fd = lock_fd
    forged._collector_lock_guard_fd = guard_fd
    forged._collector_directory_fd = directory_fd
    forged._collector_lock_owner_pid = os.getpid()
    forged._collector_lock_ofd_cookie = cookie
    try:
        with pytest.raises(
            anchor_contract.AnchorProtocolError,
            match="does not own the lock",
        ):
            forged._require_collector_lock()
    finally:
        os.close(guard_fd)
        os.close(lock_fd)
        os.close(directory_fd)
        release.set()
        process.join(timeout=5)
        if process.is_alive():
            process.terminate()
            process.join(timeout=5)
    assert process.exitcode == 0


def test_closed_collector_lock_fd_number_reuse_is_rejected(
    tmp_path: Path,
) -> None:
    fixture = _fixture(tmp_path)
    reused_descriptor: int | None = None
    with pytest.raises(
        anchor_contract.AnchorProtocolError,
        match="descriptor drifted",
    ):
        with fixture.audit.collector_lock():
            reused_descriptor = fixture.audit._collector_lock_fd
            assert reused_descriptor is not None
            os.close(reused_descriptor)
            replacement = os.open(
                fixture.audit.path / ".collector.lock",
                os.O_RDWR
                | getattr(os, "O_CLOEXEC", 0)
                | getattr(os, "O_NOFOLLOW", 0),
            )
            assert replacement == reused_descriptor
            fixture.audit._require_collector_lock()
    assert reused_descriptor is not None
    with fixture.audit.collector_lock():
        fixture.audit._require_collector_lock()


def test_both_closed_collector_fd_numbers_cannot_revive_stale_lock(
    tmp_path: Path,
) -> None:
    fixture = _fixture(tmp_path)
    fresh: int | None = None
    descriptor: int | None = None
    guard: int | None = None
    with pytest.raises(
        anchor_contract.AnchorProtocolError,
        match="descriptor drifted",
    ):
        with fixture.audit.collector_lock():
            descriptor = fixture.audit._collector_lock_fd
            guard = fixture.audit._collector_lock_guard_fd
            assert descriptor is not None and guard is not None
            os.close(descriptor)
            os.close(guard)
            fresh = os.open(
                fixture.audit.path / ".collector.lock",
                os.O_RDWR
                | getattr(os, "O_CLOEXEC", 0)
                | getattr(os, "O_NOFOLLOW", 0),
            )
            if fresh == descriptor:
                os.dup2(fresh, guard)
            elif fresh == guard:
                os.dup2(fresh, descriptor)
            else:
                os.dup2(fresh, descriptor)
                os.dup2(fresh, guard)
            fixture.audit._require_collector_lock()
    if fresh is not None and fresh not in {descriptor, guard}:
        os.close(fresh)
    with fixture.audit.collector_lock():
        fixture.audit._require_collector_lock()


def test_collector_lock_rejects_mode_and_hardlink_drift_before_rpc(
    tmp_path: Path,
) -> None:
    fixture = _fixture(tmp_path)
    _collect(fixture, _snapshot())
    lock_path = fixture.audit.path / ".collector.lock"
    before = list(fixture.transport.paths)
    lock_path.chmod(0o644)
    with pytest.raises(anchor_contract.AnchorProtocolError, match="lock file is unsafe"):
        _collect(fixture, _snapshot(), request_nonce="6" * 64)
    assert fixture.transport.paths == before
    lock_path.chmod(0o600)
    hardlink = fixture.audit.path / "lock-hardlink"
    os.link(lock_path, hardlink)
    with pytest.raises(anchor_contract.AnchorProtocolError, match="lock file is unsafe"):
        _collect(fixture, _snapshot(), request_nonce="7" * 64)
    assert fixture.transport.paths == before


def test_reference_commit_compare_and_swap_is_atomic_under_real_threads(
    tmp_path: Path,
) -> None:
    fixture = _fixture(tmp_path)
    snapshot = _snapshot()
    candidate = snapshot["candidate"]
    proof = anchor_contract._build_lineage_proof(
        snapshot,
        previous_candidate=None,
        previous_attempts=[],
        previous_runs=[],
        previous_events=[],
        prior_anchor_digest=None,
    )
    commits: list[dict[str, object]] = []
    for request_nonce in ("a" * 64, "b" * 64):
        request = anchor_contract._challenge_request(
            candidate,
            client_key_id="local-collector-1",
            client_private_key=fixture.client,
            request_nonce=request_nonce,
        )
        challenge = anchor_contract._validate_challenge(
            fixture.authority.issue_challenge(
                canary.canonical_json_bytes(request), now=NOW
            ),
            registry=fixture.registry,
            challenge_request=request,
            candidate=candidate,
            expected_generation=1,
            expected_prior_anchor_digest=None,
            now=NOW,
        )
        commits.append(
            anchor_contract._commit_request(
                candidate=candidate,
                challenge=challenge,
                lineage_proof=proof,
                client_key_id="local-collector-1",
                client_private_key=fixture.client,
            )
        )
    barrier = threading.Barrier(3)
    results: list[str] = []

    def invoke(commit: dict[str, object]) -> None:
        barrier.wait(timeout=5)
        try:
            fixture.authority.commit(
                canary.canonical_json_bytes(commit),
                now=NOW + timedelta(seconds=1),
            )
        except anchor_contract.AnchorProtocolError as exc:
            results.append(str(exc))
        else:
            results.append("ACCEPTED")

    threads = [threading.Thread(target=invoke, args=(commit,)) for commit in commits]
    for thread in threads:
        thread.start()
    barrier.wait(timeout=5)
    for thread in threads:
        thread.join(timeout=5)
        assert not thread.is_alive()
    assert results.count("ACCEPTED") == 1
    assert sum("compare-and-swap" in result for result in results) == 1
    assert fixture.authority.generation == 1


def test_remote_high_water_detects_local_receipt_audit_rollback(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    _collect(fixture, _snapshot())
    for path in fixture.audit.path.iterdir():
        path.unlink()
    fixture.audit.path.rmdir()
    with pytest.raises(anchor_contract.AnchorProtocolError, match="freshness"):
        _collect(fixture, _snapshot(), request_nonce="6" * 64)


def test_environment_or_go_field_substitution_is_rejected(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    candidate = _candidate()
    request = anchor_contract._challenge_request(
        candidate,
        client_key_id="local-collector-1",
        client_private_key=fixture.client,
        request_nonce="d" * 64,
    )
    request["environment_set"] = ["staging"]
    with pytest.raises(anchor_contract.AnchorProtocolError, match="identity"):
        fixture.authority.issue_challenge(
            canary.canonical_json_bytes(request), now=NOW
        )
    request = anchor_contract._challenge_request(
        candidate,
        client_key_id="local-collector-1",
        client_private_key=fixture.client,
        request_nonce="e" * 64,
    )
    request["go"] = True
    with pytest.raises(anchor_contract.AnchorProtocolError, match="fields are not closed"):
        fixture.authority.issue_challenge(
            canary.canonical_json_bytes(request), now=NOW
        )


def test_expired_or_wrongly_signed_challenge_is_rejected(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    candidate = _candidate()
    request = anchor_contract._challenge_request(
        candidate,
        client_key_id="local-collector-1",
        client_private_key=fixture.client,
        request_nonce="f" * 64,
    )
    raw = fixture.authority.issue_challenge(
        canary.canonical_json_bytes(request), now=NOW
    )
    with pytest.raises(anchor_contract.AnchorProtocolError, match="freshness"):
        anchor_contract._validate_challenge(
            raw,
            registry=fixture.registry,
            challenge_request=request,
            candidate=candidate,
            expected_generation=1,
            expected_prior_anchor_digest=None,
            now=NOW + timedelta(seconds=60),
        )
    document = json.loads(raw)
    document["anchor_candidate_digest"] = "sha256:" + "0" * 64
    with pytest.raises(anchor_contract.AnchorProtocolError, match="lineage|signature"):
        anchor_contract._validate_challenge(
            canary.canonical_json_bytes(document),
            registry=fixture.registry,
            challenge_request=request,
            candidate=candidate,
            expected_generation=1,
            expected_prior_anchor_digest=None,
            now=NOW,
        )


def test_local_audit_rejects_mode_and_content_tampering(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    _collect(fixture, _snapshot())
    record_path = next(
        path for path in fixture.audit.path.iterdir() if path.name[:1].isdigit()
    )
    record_path.chmod(0o644)
    with pytest.raises(anchor_contract.AnchorProtocolError, match="unsafe"):
        fixture.audit.records()
    record_path.chmod(0o600)
    raw = bytearray(record_path.read_bytes())
    raw[-1] = ord(" ")
    record_path.write_bytes(raw)
    record_path.chmod(0o600)
    with pytest.raises(anchor_contract.AnchorProtocolError, match="strict JSON|canonical|digest"):
        fixture.audit.records()


def test_https_transport_rejects_redirect_oversize_and_ambient_proxy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured_handlers: list[object] = []

    class Response:
        status = 200
        headers = SimpleNamespace(get_content_type=lambda: "application/json")

        def __enter__(self) -> "Response":
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def read(self, _limit: int) -> bytes:
            return b"{}"

        def geturl(self) -> str:
            return "https://other.invalid/v1/local-authority-anchor/challenge"

    class Opener:
        def open(self, *_args: object, **_kwargs: object) -> Response:
            return Response()

    def build(*handlers: object) -> Opener:
        captured_handlers.extend(handlers)
        return Opener()

    monkeypatch.setenv("HTTPS_PROXY", "https://ambient-credential.invalid")
    monkeypatch.setattr(anchor_store.urllib.request, "build_opener", build)
    transport = anchor_store.PinnedHTTPSAnchorTransport(
        endpoint="https://anchor.invalid",
        per_io_timeout_seconds=5,
        maximum_document_bytes=anchor_contract.MAX_DOCUMENT_BYTES,
    )
    proxy_handlers = [
        handler for handler in captured_handlers
        if isinstance(handler, anchor_store.urllib.request.ProxyHandler)
    ]
    assert len(proxy_handlers) == 1
    assert proxy_handlers[0].proxies == {}
    redirect_handlers = [
        handler for handler in captured_handlers
        if isinstance(handler, anchor_store._RejectRedirect)
    ]
    assert len(redirect_handlers) == 1
    with pytest.raises(anchor_contract.AnchorProtocolError, match="redirect"):
        redirect_handlers[0].redirect_request(
            None, None, 302, "redirect", {}, "https://other.invalid"
        )
    with pytest.raises(anchor_contract.AnchorProtocolError, match="boundary"):
        transport.post(
            "/v1/local-authority-anchor/challenge", b"{}"
        )
    with pytest.raises(anchor_contract.AnchorProtocolError, match="outside policy"):
        transport.post(
            "/v1/local-authority-anchor/challenge",
            b"x" * (anchor_contract.MAX_DOCUMENT_BYTES + 1),
        )
