"""Structural and attack tests for the narrow local authority canary gate."""

from __future__ import annotations

import base64
import json
import os
import sqlite3
import stat
import subprocess
import sys
import tempfile
import threading
import time
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from scripts import local_authority_service as service
from scripts import local_authority_staged_canary as canary
from scripts import manage_local_authority_staged_canary as manager
from scripts.finding_ledger_gate import (
    FindingLedgerError,
    require_pinned_finding_ledger_gate,
)


def _fake_binding() -> dict[str, str]:
    root = Path(canary.__file__).resolve().parents[1]
    return {
        "source_sha": "1" * 40,
        "bundle_digest": "sha256:" + "2" * 64,
        "bundle_path": str(root),
        "entrypoint_path": str(root / "scripts" / "run_local_authority.py"),
        "entrypoint_digest": "sha256:" + "3" * 64,
        "python_path": "/protected/python",
        "python_digest": "sha256:" + "4" * 64,
    }


def _fake_ledger() -> SimpleNamespace:
    return SimpleNamespace(
        digest="sha256:" + "5" * 64,
        open_p0_ids=("A2", "R5"),
        release_allowed=False,
    )


def _resource_snapshot(private: Ed25519PrivateKey) -> dict[str, object]:
    public = private.public_key().public_bytes(
        serialization.Encoding.Raw,
        serialization.PublicFormat.Raw,
    )
    snapshot: dict[str, object] = {
        "key": {
            "key_id": "ready-staging-canary",
            "public_key_base64": base64.b64encode(public).decode("ascii"),
            "public_key_sha256": (
                "sha256:" + __import__("hashlib").sha256(public).hexdigest()
            ),
        },
    }
    return {**snapshot, "resource_digest": canary._digest(snapshot)}


def _observation(*, inode: int, mode: int) -> dict[str, int]:
    return {
        "device": 1,
        "inode": inode,
        "owner_uid": 501,
        "owner_gid": 20,
        "mode": mode,
        "nlink": 1,
    }


def _archived_ready_resources(
    private: Ed25519PrivateKey,
) -> dict[str, object]:
    public = private.public_key().public_bytes(
        serialization.Encoding.Raw,
        serialization.PublicFormat.Raw,
    )
    ledger_evidence: dict[str, object] = {
        "schema_version": 1,
        "authority_id": "ready",
        "environment": "staging",
        "event_count": 0,
        "tail_event_digest": None,
    }
    policy = canary.load_policy()
    snapshot: dict[str, object] = {
        "format": "local-authority-staged-canary-resources/v1",
        "authority_id": "ready",
        "environment": "staging",
        "action": policy.actions["ready"].action,
        "resource_roles": list(policy.actions["ready"].resource_roles),
        "principal_manifest_digest": canary.PINNED_MANIFEST_DIGEST,
        "source_sha": "1" * 40,
        "runtime_bundle_digest": "sha256:" + "2" * 64,
        "runtime_entrypoint_digest": "sha256:" + "3" * 64,
        "runtime_python_digest": "sha256:" + "4" * 64,
        "service_identity": {
            "service_user": "qp_staging_ready_authority",
            "uid": 501,
            "gid": 20,
            "service_group": "qp_authorities",
            "service_group_gid": 20,
            "caller_group": "qp_ready_callers",
            "caller_group_gid": 21,
            "peer_uids": [502],
            "home": "/var/empty",
            "shell": "/usr/bin/false",
            "service_directory": {
                "path": "/var/db/quant-platform/ready",
                "resolved_path": "/var/db/quant-platform/ready",
                "kind": "directory",
                "digest": None,
                "observation": _observation(inode=10, mode=0o700),
            },
        },
        "runtime_config": {
            "path": "/etc/quant-platform/ready.json",
            "digest": "sha256:" + "6" * 64,
            "observation": _observation(inode=11, mode=0o440),
        },
        "key": {
            "key_id": "ready-staging-canary",
            "public_key_base64": base64.b64encode(public).decode("ascii"),
            "public_key_sha256": canary._digest(public),
            "public_metadata_digest": "sha256:" + "7" * 64,
            "key_observation": _observation(inode=12, mode=0o400),
        },
        "event_ledger": {
            "path": "/var/db/quant-platform/ready/authority-events.sqlite3",
            **ledger_evidence,
            "chain_digest": canary._digest(ledger_evidence),
            "observation": _observation(inode=13, mode=0o600),
        },
        "runtime_resources": [
            {
                "name": "snapshot_root",
                "sensitivity": "IMMUTABLE_INPUT_ROOT_METADATA_ONLY",
                "path": "/var/db/quant-platform/snapshots",
                "resolved_path": "/var/db/quant-platform/snapshots",
                "kind": "directory",
                "digest": None,
                "observation": _observation(inode=14, mode=0o500),
            }
        ],
    }
    return {**snapshot, "resource_digest": canary._digest(snapshot)}


def _challenge(
    *,
    authority_id: str,
    environment: str,
    resources: dict[str, object],
    deadline_monotonic_ns: int,
) -> dict[str, object]:
    policy = canary.load_policy()
    action = policy.actions[authority_id]
    issued = datetime.now(UTC)
    return {
        "format": canary.CHALLENGE_FORMAT,
        "classification": canary.CLASSIFICATION,
        "authority_id": authority_id,
        "environment": environment,
        "action": action.action,
        "proof_kind": action.proof_kind,
        "source_sha": "1" * 40,
        "runtime_bundle_digest": "sha256:" + "2" * 64,
        "policy_digest": policy.digest,
        "principal_manifest_digest": canary.PINNED_MANIFEST_DIGEST,
        "finding_ledger_digest": "sha256:" + "5" * 64,
        "open_p0_ids": ["A2", "R5"],
        "resource_digest": resources["resource_digest"],
        "nonce": "7" * 64,
        "issued_at": issued.isoformat(timespec="microseconds"),
        "expires_at": (issued + timedelta(seconds=canary.LEASE_SECONDS)).isoformat(
            timespec="microseconds"
        ),
        "deadline_monotonic_ns": deadline_monotonic_ns,
        "strict_boundaries": dict(canary.STRICT_BOUNDARIES),
    }


def _signed_result(
    challenge: dict[str, object],
    resources: dict[str, object],
    private: Ed25519PrivateKey,
) -> dict[str, object]:
    key = resources["key"]
    assert isinstance(key, dict)
    body = {
        "format": canary.CANARY_FORMAT,
        "classification": canary.CLASSIFICATION,
        "research_eligible": False,
        "authority_id": challenge["authority_id"],
        "environment": challenge["environment"],
        "action": challenge["action"],
        "proof_kind": challenge["proof_kind"],
        "source_sha": challenge["source_sha"],
        "runtime_bundle_digest": challenge["runtime_bundle_digest"],
        "policy_digest": challenge["policy_digest"],
        "principal_manifest_digest": challenge["principal_manifest_digest"],
        "finding_ledger_digest": challenge["finding_ledger_digest"],
        "open_p0_ids": challenge["open_p0_ids"],
        "resource_digest": resources["resource_digest"],
        "protocol_digest": canary._digest(
            canary._expected_protocol_descriptor(
                authority_id=str(challenge["authority_id"]),
                environment=str(challenge["environment"]),
            )
        ),
        "challenge_digest": canary._digest(
            canary.canonical_json_bytes(dict(challenge))
        ),
        "nonce": challenge["nonce"],
        "observed_at": challenge["issued_at"],
        "strict_boundaries": dict(canary.STRICT_BOUNDARIES),
        "issuer_key_id": key["key_id"],
        "issuer_public_key_base64": key["public_key_base64"],
    }
    signature = private.sign(canary.canonical_json_bytes(body))
    evidence = {
        **body,
        "signature": "ed25519:" + base64.b64encode(signature).decode("ascii"),
    }
    return {**evidence, "canary_digest": canary._digest(evidence)}


@pytest.fixture
def isolated_journal(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    protected = tmp_path / "protected"
    protected.mkdir(mode=0o700)
    state_root = protected / "staged-canary"
    journal = state_root / "journal.sqlite3"
    monkeypatch.setattr(manager, "PROTECTED_ROOT", protected)
    monkeypatch.setattr(manager, "CANONICAL_STATE_ROOT", state_root)
    monkeypatch.setattr(manager, "CANONICAL_JOURNAL_PATH", journal)
    monkeypatch.setattr(manager, "_require_human_root", lambda: None)

    def prepare() -> None:
        state_root.mkdir(mode=0o700, exist_ok=True)

    monkeypatch.setattr(manager, "_prepare_canonical_state_root", prepare)
    monkeypatch.setattr(
        manager,
        "_require_exact_directory",
        lambda path, mode: (
            None
            if path.is_dir() and path.stat().st_mode & 0o777 == mode
            else (_ for _ in ()).throw(
                canary.StagedCanaryError("test state directory is unsafe")
            )
        ),
    )
    monkeypatch.setattr(manager.os, "fchown", lambda *_args: None)

    def journal_metadata(
        *, allow_empty: bool = False, allow_recovery_journal: bool = False
    ) -> None:
        info = journal.lstat()
        wal_path, shm_path, rollback_path = manager._journal_sidecars()
        if (
            not stat.S_ISREG(info.st_mode)
            or stat.S_IMODE(info.st_mode) != 0o600
            or info.st_nlink != 1
            or os.path.lexists(wal_path)
            or os.path.lexists(shm_path)
        ):
            raise canary.StagedCanaryError("test journal metadata is unsafe")
        if os.path.lexists(rollback_path):
            if not allow_recovery_journal:
                raise canary.StagedCanaryError(
                    "canonical canary rollback sidecar is present"
                )
            rollback = rollback_path.lstat()
            if (
                not stat.S_ISREG(rollback.st_mode)
                or stat.S_IMODE(rollback.st_mode) != 0o600
                or rollback.st_nlink != 1
            ):
                raise canary.StagedCanaryError(
                    "canonical canary rollback sidecar is unsafe"
                )
        raw = journal.read_bytes()
        if allow_empty and not raw:
            return
        if (
            len(raw) < 20
            or raw[:16] != b"SQLite format 3\x00"
            or raw[18:20] != b"\x01\x01"
        ):
            raise canary.StagedCanaryError(
                "canonical canary journal is not rollback-journal SQLite"
            )

    monkeypatch.setattr(manager, "_require_journal_metadata", journal_metadata)
    return journal


def _patch_operational_inputs(
    monkeypatch: pytest.MonkeyPatch,
    resources: dict[str, object],
) -> None:
    monkeypatch.setattr(manager, "load_pinned_finding_ledger", _fake_ledger)
    monkeypatch.setattr(
        manager,
        "observe_preflight_resources",
        lambda **_kwargs: resources,
    )


def _archived_challenge(
    *, resources: Mapping[str, object], deadline: int
) -> dict[str, object]:
    policy = canary.load_policy()
    action = policy.actions["ready"]
    ledger = manager.load_pinned_finding_ledger()
    issued = datetime.now(UTC)
    return {
        "format": canary.CHALLENGE_FORMAT,
        "classification": canary.CLASSIFICATION,
        "authority_id": "ready",
        "environment": "staging",
        "action": action.action,
        "proof_kind": action.proof_kind,
        "source_sha": "1" * 40,
        "runtime_bundle_digest": "sha256:" + "2" * 64,
        "policy_digest": policy.digest,
        "principal_manifest_digest": canary.PINNED_MANIFEST_DIGEST,
        "finding_ledger_digest": ledger.digest,
        "open_p0_ids": list(ledger.open_p0_ids),
        "resource_digest": resources["resource_digest"],
        "nonce": "8" * 64,
        "issued_at": issued.isoformat(timespec="microseconds"),
        "expires_at": (issued + timedelta(seconds=canary.LEASE_SECONDS)).isoformat(
            timespec="microseconds"
        ),
        "deadline_monotonic_ns": deadline,
        "strict_boundaries": dict(canary.STRICT_BOUNDARIES),
    }


def _archived_canary_id() -> str:
    return canary._digest(
        {
            "format": "local-authority-staged-canary-attempt-family/v1",
            "authority_id": "ready",
            "environment": "staging",
            "action": canary.load_policy().actions["ready"].action,
            "source_sha": "1" * 40,
            "runtime_bundle_digest": "sha256:" + "2" * 64,
            "policy_digest": canary.load_policy().digest,
        }
    )


def _append_archived_event(
    connection: sqlite3.Connection,
    *,
    canary_id: str,
    event_type: str,
    attempt: int,
    lease_token: str,
    detail_digest: str,
) -> None:
    tail = connection.execute(
        "SELECT sequence,event_digest,observed_at FROM staged_canary_events "
        "ORDER BY sequence DESC LIMIT 1"
    ).fetchone()
    sequence = 1 if tail is None else int(tail["sequence"]) + 1
    prior = None if tail is None else str(tail["event_digest"])
    observed_at = datetime.now(UTC).isoformat(timespec="microseconds")
    if tail is not None and observed_at < str(tail["observed_at"]):
        observed_at = str(tail["observed_at"])
    body = {
        "format": "local-authority-staged-canary-event/v1",
        "sequence": sequence,
        "canary_id": canary_id,
        "event_type": event_type,
        "attempt": attempt,
        "observed_at": observed_at,
        "lease_token_digest": canary._digest(lease_token.encode("ascii")),
        "detail_digest": detail_digest,
        "prior_event_digest": prior,
    }
    connection.execute(
        "INSERT INTO staged_canary_events VALUES(?,?,?,?,?,?,?,?,?)",
        (
            sequence,
            canary_id,
            event_type,
            attempt,
            observed_at,
            body["lease_token_digest"],
            detail_digest,
            prior,
            canary._digest(body),
        ),
    )


def _insert_archived_ready_run(
    private: Ed25519PrivateKey,
    *,
    state: str = "COMMITTED",
) -> tuple[str, dict[str, object], dict[str, object]]:
    resources = _archived_ready_resources(private)
    deadline = time.monotonic_ns() + canary.LEASE_SECONDS * 1_000_000_000
    challenge = _archived_challenge(resources=resources, deadline=deadline)
    canary_id = _archived_canary_id()
    result = _signed_result(challenge, resources, private)
    challenge_json = canary.canonical_json_bytes(challenge).decode("utf-8")
    resource_json = canary.canonical_json_bytes(resources).decode("utf-8")
    result_json = canary.canonical_json_bytes(result).decode("utf-8")
    result_digest = canary._digest(result_json.encode("utf-8"))
    token = "9" * 64
    lease_values: tuple[object, object, object, object]
    result_values: tuple[object, object, object]
    if state == "RUNNING":
        lease_values = (token, "test-boot", deadline, challenge["expires_at"])
        result_values = (None, None, None)
    elif state == "FAILED_RETRYABLE":
        lease_values = (None, None, None, None)
        result_values = (None, None, "SyntheticFailure")
    elif state == "COMMITTED":
        lease_values = (None, None, None, None)
        result_values = (result_json, result_digest, None)
    else:
        raise AssertionError("unsupported archived test state")
    connection = manager._connect_journal(create=True)
    try:
        connection.execute("BEGIN IMMEDIATE")
        connection.execute(
            "INSERT INTO staged_canary_runs VALUES(?,?,?,?,?,?,?,?,?,?,?,?,"
            "?,?,?,?,?,?,?)",
            (
                canary_id,
                "ready",
                "staging",
                canary.load_policy().actions["ready"].action,
                "1" * 40,
                "sha256:" + "2" * 64,
                resources["resource_digest"],
                resource_json,
                state,
                1,
                *lease_values,
                challenge_json,
                *result_values,
                datetime.now(UTC).isoformat(timespec="microseconds"),
            ),
        )
        challenge_digest = canary._digest(challenge)
        lease_token_digest = canary._digest(token.encode("ascii"))
        acquired_at = challenge["issued_at"]
        attempt_evidence_digest = manager._attempt_evidence_digest(
            canary_id=canary_id,
            attempt=1,
            challenge_digest=challenge_digest,
            resource_digest=resources["resource_digest"],
            lease_token_digest=lease_token_digest,
            lease_boot_id="test-boot",
            deadline_monotonic_ns=deadline,
            lease_expires_at=challenge["expires_at"],
            acquired_at=acquired_at,
        )
        connection.execute(
            "INSERT INTO staged_canary_attempts VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                canary_id,
                1,
                challenge_json,
                challenge_digest,
                resource_json,
                resources["resource_digest"],
                lease_token_digest,
                "test-boot",
                deadline,
                challenge["expires_at"],
                acquired_at,
                attempt_evidence_digest,
            ),
        )
        _append_archived_event(
            connection,
            canary_id=canary_id,
            event_type="LEASE_ACQUIRED",
            attempt=1,
            lease_token=token,
            detail_digest=attempt_evidence_digest,
        )
        _append_archived_event(
            connection,
            canary_id=canary_id,
            event_type="ACTION_STARTED",
            attempt=1,
            lease_token=token,
            detail_digest=attempt_evidence_digest,
        )
        if state == "FAILED_RETRYABLE":
            _append_archived_event(
                connection,
                canary_id=canary_id,
                event_type="ACTION_FAILED_RETRYABLE",
                attempt=1,
                lease_token=token,
                detail_digest=canary._digest(b"SyntheticFailure"),
            )
        elif state == "COMMITTED":
            _append_archived_event(
                connection,
                canary_id=canary_id,
                event_type="CANARY_COMMITTED",
                attempt=1,
                lease_token=token,
                detail_digest=result_digest,
            )
        connection.commit()
    finally:
        connection.close()
    return canary_id, challenge, resources


def test_policy_is_pinned_to_signed_canaries_and_exact_pending_exclusions() -> None:
    policy = canary.load_policy()
    assert set(policy.actions) == {
        "d1_sync",
        "ops_projection",
        "coverage_transition",
        "ready",
        "controlled_execution",
    }
    assert all(
        action.action.startswith(action.authority_id + ":inactive_")
        for action in policy.actions.values()
    )
    raw = json.loads(canary.POLICY_PATH.read_text(encoding="utf-8"))
    assert raw["scope"] == "SIGNED_LOCAL_OS_AUTHORITIES_ONLY"
    assert {row["authority_id"] for row in raw["excluded_authorities"]} == {
        "receipt",
        "trader",
    }
    assert raw["strict_boundaries"] == dict.fromkeys(raw["strict_boundaries"], False)

    tampered = dict(raw)
    tampered["journal_path"] = str(Path("/tmp") / "forged.sqlite3")
    with pytest.raises(canary.StagedCanaryError, match="digest"):
        canary._evaluate_policy_bytes(
            json.dumps(tampered, sort_keys=True).encode("utf-8")
        )


def test_public_cli_has_no_generic_permit_completion_or_identity_inputs() -> None:
    help_text = manager._parser().format_help()
    for forbidden in (
        "--path",
        "--store",
        "--owner",
        "--uid",
        "--action",
        "--source-sha",
        "--resource-digest",
        "--evidence-digest",
    ):
        assert forbidden not in help_text.lower()
    command = next(
        action for action in manager._parser()._actions if action.dest == "command"
    )
    assert set(command.choices) == {"plan", "audit", "run", "initialize-journal"}
    assert not hasattr(manager, "issue_permit")
    assert not hasattr(manager, "complete_permit")
    plan = manager.plan(authority_id="ready", environment="staging")
    assert plan["canonical_journal_path"] == str(canary.CANONICAL_JOURNAL_PATH)
    assert plan["caller_selectable_path"] is False
    assert plan["caller_selectable_owner"] is False
    assert plan["caller_selectable_source_sha"] is False
    assert plan["caller_selectable_resource_digest"] is False
    assert plan["trusted_root_required"] is True
    assert plan["privileged_rollback_evident"] is False
    assert plan["durability_scope"] == ("POST_INITIALIZATION_CRASH_AND_POWER_LOSS_ONLY")
    assert plan["historical_attempt_evidence_complete"] is True
    assert plan["operational_high_water_anchor_required"] is True
    assert plan["operational_state"] == "HOLD"
    assert plan["operational_blockers"] == [
        "EXTERNAL_HIGH_WATER_ANCHOR_NOT_PROVISIONED"
    ]
    assert plan["trusted_root_inside_local_boundary"] is True
    assert plan["external_anchor_admin_separation_required"] is True

    controlled = manager.plan(
        authority_id="controlled_execution", environment="staging"
    )
    assert controlled["operational_blockers"] == [
        "EXTERNAL_HIGH_WATER_ANCHOR_NOT_PROVISIONED",
        "CONTROLLED_WAL_QUIESCENCE_SOURCE_READY_NOT_OPERATIONALLY_ACCEPTED",
    ]


def test_unsigned_trader_is_structurally_excluded_and_remains_pending() -> None:
    assert "trader" not in canary.load_policy().actions
    with pytest.raises(canary.StagedCanaryError, match="excluded.*PENDING"):
        manager.plan(authority_id="trader", environment="staging")
    with pytest.raises(canary.StagedCanaryError, match="excluded.*PENDING"):
        manager.run_canary(authority_id="trader", environment="staging")
    with pytest.raises(canary.StagedCanaryError, match="excluded.*PENDING"):
        manager.plan(authority_id="ready", environment="development")


def test_read_only_event_ledger_audit_does_not_initialize_missing_store(
    tmp_path: Path,
) -> None:
    directory = tmp_path / "authority"
    directory.mkdir(mode=0o700)
    path = directory / "events.sqlite3"
    ledger = service.SQLiteAuthorityEventLedger(
        path,
        authority_id="ready",
        environment="staging",
        expected_uid=os.geteuid(),
    )
    with pytest.raises(service.AuthorityLedgerError):
        ledger.audit_read_only()
    assert not path.exists()

    ledger.initialize()
    audit = ledger.audit_read_only()
    assert audit["event_count"] == 0
    assert audit["tail_event_digest"] is None
    assert audit["chain_digest"].startswith("sha256:")


def test_runner_rejects_wrong_exact_authority_selector_before_preflight() -> None:
    raw = canary.canonical_json_bytes(
        {
            "authority_id": "ready",
            "environment": "staging",
        }
    )
    with pytest.raises(canary.StagedCanaryError, match="identity"):
        canary._run_exact_inactive_preflight(
            raw,
            expected_authority_id="d1_sync",
            expected_environment="staging",
        )


def test_file_authority_runner_itself_produces_only_the_closed_signed_canary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    private = Ed25519PrivateKey.generate()
    resources = _resource_snapshot(private)
    deadline = canary.time.monotonic_ns() + 60_000_000_000
    challenge = _challenge(
        authority_id="ready",
        environment="staging",
        resources=resources,
        deadline_monotonic_ns=deadline,
    )
    monkeypatch.setattr(canary, "_runtime_binding", _fake_binding)
    monkeypatch.setattr(canary, "load_pinned_finding_ledger", _fake_ledger)
    monkeypatch.setattr(
        canary,
        "observe_preflight_resources",
        lambda **_kwargs: resources,
    )
    monkeypatch.setattr(
        canary,
        "_deployment",
        lambda *_args, **_kwargs: {"key_path": "/protected/ready/key"},
    )
    monkeypatch.setattr(
        canary,
        "_run_authority_specific_inactive_adapter",
        lambda **_kwargs: canary._expected_protocol_descriptor(
            authority_id="ready", environment="staging"
        ),
    )

    class ExactTestCustody:
        def __init__(self, *_args: object, **_kwargs: object) -> None:
            pass

        def sign(self, message: bytes) -> str:
            return "ed25519:" + base64.b64encode(private.sign(message)).decode("ascii")

    monkeypatch.setattr(canary, "FileEd25519KeyCustody", ExactTestCustody)
    result = canary._run_exact_inactive_preflight(
        canary.canonical_json_bytes(challenge),
        expected_authority_id="ready",
        expected_environment="staging",
    )
    verified = manager._validate_canary(
        canary.canonical_json_bytes(dict(result)),
        challenge=challenge,
        resources=resources,
    )
    assert verified["signature"].startswith("ed25519:")
    assert verified["classification"] == "CANARY_NOT_RESEARCH_ELIGIBLE"
    assert verified["research_eligible"] is False


def test_forged_research_eligible_or_alternate_key_canary_is_rejected() -> None:
    private = Ed25519PrivateKey.generate()
    resources = _resource_snapshot(private)
    challenge = _challenge(
        authority_id="ready",
        environment="staging",
        resources=resources,
        deadline_monotonic_ns=time.monotonic_ns() + 60_000_000_000,
    )
    valid = _signed_result(challenge, resources, private)
    assert (
        manager._validate_canary(
            canary.canonical_json_bytes(valid),
            challenge=challenge,
            resources=resources,
        )["research_eligible"]
        is False
    )

    forged = dict(valid)
    forged["research_eligible"] = True
    body = {name: forged[name] for name in canary._CANARY_BODY_FIELDS}
    forged["signature"] = "ed25519:" + base64.b64encode(
        private.sign(canary.canonical_json_bytes(body))
    ).decode("ascii")
    forged_body = {
        name: forged[name] for name in canary._CANARY_FIELDS if name != "canary_digest"
    }
    forged["canary_digest"] = canary._digest(forged_body)
    with pytest.raises(canary.StagedCanaryError, match="eligibility"):
        manager._validate_canary(
            canary.canonical_json_bytes(forged),
            challenge=challenge,
            resources=resources,
        )

    alternate = Ed25519PrivateKey.generate()
    alternate_result = _signed_result(challenge, resources, alternate)
    with pytest.raises(canary.StagedCanaryError, match="signature"):
        manager._validate_canary(
            canary.canonical_json_bytes(alternate_result),
            challenge=challenge,
            resources=resources,
        )


def test_hold_surface_exposes_no_minting_primitive_or_callback() -> None:
    import inspect

    from scripts import local_authority_runtime_bundle as runtime_bundle

    assert callable(manager.run_canary)
    assert tuple(inspect.signature(manager.run_canary).parameters) == (
        "authority_id",
        "environment",
    )
    assert manager.run_canary.__closure__ is None
    for forbidden in (
        "_seal_atomic_run_workflow",
        "_acquire_lease",
        "_mark_action_started",
        "_execute_exact_runner",
        "_commit_verified_runner_output",
        "_mark_failed",
        "_require_live_lease_under_lock",
    ):
        assert not hasattr(manager, forbidden)
    archive_command = runtime_bundle._git_runtime_archive_command("a" * 40)
    assert ":(exclude)tests" in archive_command
    assert runtime_bundle._RUNTIME_ARCHIVE_EXCLUSIONS == ("tests",)


@pytest.mark.parametrize(
    "authority_id",
    sorted(canary.load_policy().actions),
)
def test_public_run_is_hold_for_every_declared_authority(
    isolated_journal: Path,
    authority_id: str,
) -> None:
    with pytest.raises(
        canary.StagedCanaryError,
        match="operational HOLD.*EXTERNAL_HIGH_WATER_ANCHOR_NOT_PROVISIONED",
    ) as exc_info:
        manager.run_canary(authority_id=authority_id, environment="staging")
    if authority_id == "controlled_execution":
        assert (
            "CONTROLLED_WAL_QUIESCENCE_SOURCE_READY_NOT_OPERATIONALLY_ACCEPTED"
            in str(exc_info.value)
        )
    else:
        assert (
            "CONTROLLED_WAL_QUIESCENCE_SOURCE_READY_NOT_OPERATIONALLY_ACCEPTED"
            not in str(exc_info.value)
        )
    assert not isolated_journal.exists()


def test_public_cli_run_returns_hold_without_mutation(
    isolated_journal: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert (
        manager.main(
            ["run", "--authority", "ready", "--environment", "staging"]
        )
        == 1
    )
    captured = capsys.readouterr()
    assert "staged authority canary rejected: operational HOLD" in captured.err
    assert captured.out == ""
    assert not isolated_journal.exists()


def test_root_initializer_creates_only_one_fresh_v4_journal(
    isolated_journal: Path,
) -> None:
    first = manager.initialize_journal()
    assert first["status"] == "CREATED_VERIFIED"
    assert first["journal_schema_version"] == 4
    assert first["canary_executed"] is False
    assert first["authority_operation_executed"] is False
    assert first["research_eligible"] is False
    assert first["operational_state"] == "HOLD"
    instance = first["journal_instance_id"]
    assert instance.startswith("journal-instance:")
    second = manager.initialize_journal()
    assert second["status"] == "ALREADY_PRESENT_VERIFIED"
    assert second["journal_instance_id"] == instance
    with sqlite3.connect(isolated_journal) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM staged_canary_runs"
        ).fetchone()[0] == 0
        assert connection.execute(
            "SELECT schema_version,journal_format FROM staged_canary_meta"
        ).fetchone() == (4, canary.JOURNAL_FORMAT)


def test_journal_initializer_requires_root_before_creating_any_path(
    isolated_journal: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        manager,
        "_require_human_root",
        lambda: (_ for _ in ()).throw(
            canary.StagedCanaryError("human root is required")
        ),
    )
    with pytest.raises(canary.StagedCanaryError, match="root"):
        manager.initialize_journal()
    assert not isolated_journal.exists()


def test_initialize_journal_cli_has_no_selectors_and_never_runs_canary(
    isolated_journal: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        manager,
        "run_canary",
        lambda **_kwargs: pytest.fail("initializer must not dispatch a canary"),
    )
    assert manager.main(["initialize-journal"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "CREATED_VERIFIED"
    assert result["canary_executed"] is False
    assert manager.main(
        ["initialize-journal", "--authority", "ready"]
    ) == 2
    assert "does not accept selectors" in capsys.readouterr().err



def test_attempt_snapshot_is_immutable_and_anchor_candidate_binds_the_tail(
    isolated_journal: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    private = Ed25519PrivateKey.generate()
    resources = _archived_ready_resources(private)
    _patch_operational_inputs(monkeypatch, resources)
    canary_id, _challenge, _resources = _insert_archived_ready_run(private)

    result = manager.audit()
    assert result["historical_attempt_evidence_complete"] is True
    assert result["attempt_evidence_count"] == 1
    assert result["event_count"] == 3
    assert result["tail_event_digest"].startswith("sha256:")
    assert result["anchor_candidate"]["tail_event_digest"] == result[
        "tail_event_digest"
    ]
    assert result["anchor_candidate"]["tail_event_sequence"] == result[
        "event_count"
    ]
    assert result["anchor_candidate"]["attempt_evidence_set_digest"] == result[
        "attempt_evidence_set_digest"
    ]
    assert result["anchor_candidate_digest"] == canary._digest(
        result["anchor_candidate"]
    )

    with sqlite3.connect(isolated_journal) as connection:
        attempts = connection.execute(
            "SELECT attempt,challenge_json,resource_digest "
            "FROM staged_canary_attempts WHERE canary_id=? ORDER BY attempt",
            (canary_id,),
        ).fetchall()
        assert [row[0] for row in attempts] == [1]
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            connection.execute(
                "UPDATE staged_canary_attempts SET resource_digest=? "
                "WHERE canary_id=? AND attempt=1",
                ("sha256:" + "f" * 64, canary_id),
            )


def test_attempt_primary_key_rejects_replace_and_upsert(
    isolated_journal: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    private = Ed25519PrivateKey.generate()
    resources = _archived_ready_resources(private)
    _patch_operational_inputs(monkeypatch, resources)
    _insert_archived_ready_run(private)
    with sqlite3.connect(isolated_journal) as connection:
        row = connection.execute(
            "SELECT * FROM staged_canary_attempts"
        ).fetchone()
        assert row is not None
        placeholders = ",".join("?" for _ in row)
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            connection.execute(
                f"INSERT OR REPLACE INTO staged_canary_attempts "
                f"VALUES({placeholders})",
                tuple(row),
            )
        connection.rollback()
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            connection.execute(
                f"INSERT INTO staged_canary_attempts VALUES({placeholders}) "
                "ON CONFLICT(canary_id,attempt) DO UPDATE SET "
                "lease_boot_id=excluded.lease_boot_id",
                tuple(row),
            )
        connection.rollback()
    assert manager.audit()["attempt_evidence_count"] == 1


@pytest.mark.parametrize(
    ("column", "replacement"),
    (
        ("lease_boot_id", "forged-boot-id"),
        ("acquired_at", "2030-01-01T00:00:00.000000+00:00"),
        ("resource_json", "{}"),
        ("challenge_json", "{}"),
    ),
)
def test_attempt_field_tampering_is_detected_after_trigger_replay(
    isolated_journal: Path,
    monkeypatch: pytest.MonkeyPatch,
    column: str,
    replacement: str,
) -> None:
    private = Ed25519PrivateKey.generate()
    resources = _archived_ready_resources(private)
    _patch_operational_inputs(monkeypatch, resources)
    _insert_archived_ready_run(private)
    with sqlite3.connect(isolated_journal) as connection:
        trigger_sql = connection.execute(
            "SELECT sql FROM sqlite_master WHERE type='trigger' "
            "AND name='staged_canary_attempts_no_update'"
        ).fetchone()[0]
        connection.execute("DROP TRIGGER staged_canary_attempts_no_update")
        connection.execute(
            f'UPDATE staged_canary_attempts SET "{column}"=?',
            (replacement,),
        )
        connection.execute(trigger_sql)
        connection.commit()
    with pytest.raises(canary.StagedCanaryError):
        manager.audit()


def test_coherent_attempt_rewrite_changes_external_anchor_candidate(
    isolated_journal: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    private = Ed25519PrivateKey.generate()
    resources = _archived_ready_resources(private)
    _patch_operational_inputs(monkeypatch, resources)
    _insert_archived_ready_run(private)
    before = manager.audit()

    with sqlite3.connect(isolated_journal) as connection:
        connection.row_factory = sqlite3.Row
        trigger_rows = connection.execute(
            "SELECT name,sql FROM sqlite_master WHERE type='trigger' ORDER BY name"
        ).fetchall()
        for trigger in trigger_rows:
            connection.execute(f'DROP TRIGGER "{trigger["name"]}"')
        attempt = connection.execute(
            "SELECT * FROM staged_canary_attempts"
        ).fetchone()
        assert attempt is not None
        forged_boot_id = "forged-boot-id"
        forged_attempt_digest = manager._attempt_evidence_digest(
            canary_id=attempt["canary_id"],
            attempt=attempt["attempt"],
            challenge_digest=attempt["challenge_digest"],
            resource_digest=attempt["resource_digest"],
            lease_token_digest=attempt["lease_token_digest"],
            lease_boot_id=forged_boot_id,
            deadline_monotonic_ns=attempt["deadline_monotonic_ns"],
            lease_expires_at=attempt["lease_expires_at"],
            acquired_at=attempt["acquired_at"],
        )
        connection.execute(
            "UPDATE staged_canary_attempts SET lease_boot_id=?,"
            "attempt_evidence_digest=?",
            (forged_boot_id, forged_attempt_digest),
        )
        prior = None
        events = connection.execute(
            "SELECT * FROM staged_canary_events ORDER BY sequence"
        ).fetchall()
        for event in events:
            detail_digest = (
                forged_attempt_digest
                if event["event_type"]
                in {"LEASE_ACQUIRED", "EXPIRED_LEASE_RECOVERED", "ACTION_STARTED"}
                else event["detail_digest"]
            )
            body = {
                "format": "local-authority-staged-canary-event/v1",
                "sequence": event["sequence"],
                "canary_id": event["canary_id"],
                "event_type": event["event_type"],
                "attempt": event["attempt"],
                "observed_at": event["observed_at"],
                "lease_token_digest": event["lease_token_digest"],
                "detail_digest": detail_digest,
                "prior_event_digest": prior,
            }
            event_digest = canary._digest(body)
            connection.execute(
                "UPDATE staged_canary_events SET detail_digest=?,"
                "prior_event_digest=?,event_digest=? WHERE sequence=?",
                (detail_digest, prior, event_digest, event["sequence"]),
            )
            prior = event_digest
        for trigger in trigger_rows:
            connection.execute(trigger["sql"])
        connection.commit()

    after = manager.audit()
    assert after["historical_attempt_evidence_complete"] is True
    assert after["attempt_evidence_set_digest"] != before[
        "attempt_evidence_set_digest"
    ]
    assert after["anchor_candidate_digest"] != before["anchor_candidate_digest"]


@pytest.mark.parametrize(
    ("field", "replacement"),
    (
        ("lease_boot_id", "other-boot"),
        ("acquired_at", "2030-01-01T00:00:00.000000+00:00"),
        ("resource_digest", "sha256:" + "a" * 64),
        ("challenge_digest", "sha256:" + "b" * 64),
    ),
)
def test_full_attempt_digest_and_candidate_bind_each_evidence_dimension(
    isolated_journal: Path,
    monkeypatch: pytest.MonkeyPatch,
    field: str,
    replacement: str,
) -> None:
    private = Ed25519PrivateKey.generate()
    resources = _archived_ready_resources(private)
    _patch_operational_inputs(monkeypatch, resources)
    _insert_archived_ready_run(private)
    audit = manager.audit()
    with sqlite3.connect(isolated_journal) as connection:
        connection.row_factory = sqlite3.Row
        attempt = connection.execute(
            "SELECT * FROM staged_canary_attempts"
        ).fetchone()
    assert attempt is not None
    evidence = {
        "canary_id": attempt["canary_id"],
        "attempt": attempt["attempt"],
        "challenge_digest": attempt["challenge_digest"],
        "resource_digest": attempt["resource_digest"],
        "lease_token_digest": attempt["lease_token_digest"],
        "lease_boot_id": attempt["lease_boot_id"],
        "deadline_monotonic_ns": attempt["deadline_monotonic_ns"],
        "lease_expires_at": attempt["lease_expires_at"],
        "acquired_at": attempt["acquired_at"],
    }
    evidence[field] = replacement
    forged_attempt_digest = manager._attempt_evidence_digest(**evidence)
    assert forged_attempt_digest != attempt["attempt_evidence_digest"]
    forged_set_digest = canary._digest(
        {
            "format": manager._ATTEMPT_EVIDENCE_SET_FORMAT,
            "attempts": [
                {
                    "canary_id": attempt["canary_id"],
                    "attempt": attempt["attempt"],
                    "attempt_evidence_digest": forged_attempt_digest,
                }
            ],
        }
    )
    forged_candidate = {
        **audit["anchor_candidate"],
        "attempt_evidence_set_digest": forged_set_digest,
    }
    assert forged_set_digest != audit["attempt_evidence_set_digest"]
    assert canary._digest(forged_candidate) != audit["anchor_candidate_digest"]


def test_audit_anchor_candidate_uses_one_read_snapshot_during_concurrent_write(
    isolated_journal: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    private = Ed25519PrivateKey.generate()
    resources = _archived_ready_resources(private)
    _patch_operational_inputs(monkeypatch, resources)
    canary_id, _challenge, _resources = _insert_archived_ready_run(
        private, state="RUNNING"
    )
    token = "9" * 64

    release_writer = threading.Event()
    writer_inserted = threading.Event()
    writer_errors: list[BaseException] = []

    def append_started() -> None:
        release_writer.wait(timeout=5)
        try:
            connection = sqlite3.connect(
                isolated_journal,
                isolation_level=None,
                timeout=10.0,
            )
            connection.row_factory = sqlite3.Row
            try:
                connection.execute("PRAGMA busy_timeout=10000")
                connection.execute("BEGIN IMMEDIATE")
                failure_class = "SyntheticFailure"
                connection.execute(
                    "UPDATE staged_canary_runs SET state='FAILED_RETRYABLE',"
                    "lease_token=NULL,lease_boot_id=NULL,deadline_monotonic_ns=NULL,"
                    "lease_expires_at=NULL,failure_class=?,updated_at=? "
                    "WHERE canary_id=?",
                    (
                        failure_class,
                        datetime.now(UTC).isoformat(timespec="microseconds"),
                        canary_id,
                    ),
                )
                _append_archived_event(
                    connection,
                    canary_id=canary_id,
                    event_type="ACTION_FAILED_RETRYABLE",
                    attempt=1,
                    lease_token=token,
                    detail_digest=canary._digest(failure_class.encode("ascii")),
                )
                writer_inserted.set()
                connection.commit()
            finally:
                connection.close()
        except BaseException as exc:  # pragma: no cover - asserted below
            writer_errors.append(exc)
            writer_inserted.set()

    writer = threading.Thread(target=append_started, daemon=True)
    writer.start()
    real_connect = manager._connect_journal

    class _AuditConnectionProxy:
        def __init__(self, connection: sqlite3.Connection) -> None:
            self._connection = connection

        def execute(self, sql: str, *args: object):
            cursor = self._connection.execute(sql, *args)
            if sql == "SELECT COUNT(*) FROM staged_canary_events":
                release_writer.set()
                assert writer_inserted.wait(timeout=5)
            return cursor

        def __getattr__(self, name: str) -> object:
            return getattr(self._connection, name)

    def connect_with_audit_probe(*, create: bool, read_only: bool = False):
        connection = real_connect(create=create, read_only=read_only)
        return _AuditConnectionProxy(connection) if read_only else connection

    monkeypatch.setattr(manager, "_connect_journal", connect_with_audit_probe)
    during = manager.audit()
    writer.join(timeout=10)
    assert not writer.is_alive()
    assert writer_errors == []
    assert during["event_count"] == 2
    assert during["tail_event_sequence"] == 2
    assert during["anchor_candidate"]["tail_event_sequence"] == 2

    monkeypatch.setattr(manager, "_connect_journal", real_connect)
    after = manager.audit()
    assert after["event_count"] == 3
    assert after["tail_event_sequence"] == 3


def test_missing_immutable_retry_snapshot_is_detected(
    isolated_journal: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    private = Ed25519PrivateKey.generate()
    resources = _archived_ready_resources(private)
    _patch_operational_inputs(monkeypatch, resources)
    _insert_archived_ready_run(private)
    with sqlite3.connect(isolated_journal) as connection:
        trigger_sql = connection.execute(
            "SELECT sql FROM sqlite_master WHERE type='trigger' "
            "AND name='staged_canary_attempts_no_delete'"
        ).fetchone()[0]
        connection.execute("DROP TRIGGER staged_canary_attempts_no_delete")
        connection.execute("DELETE FROM staged_canary_attempts")
        connection.execute(trigger_sql)
        connection.commit()
    with pytest.raises(canary.StagedCanaryError, match="attempt history"):
        manager.audit()



def test_corrupt_existing_journal_is_never_repaired_on_create(
    isolated_journal: Path,
) -> None:
    manager._connect_journal(create=True).close()
    with sqlite3.connect(isolated_journal) as connection:
        connection.execute("DROP TRIGGER staged_canary_events_no_update")
        connection.commit()
    with pytest.raises(canary.StagedCanaryError, match="schema"):
        manager._connect_journal(create=True)
    with sqlite3.connect(isolated_journal) as connection:
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM sqlite_master WHERE type='trigger' "
                "AND name='staged_canary_events_no_update'"
            ).fetchone()[0]
            == 0
        )


def test_wal_mode_journal_is_rejected_before_read_only_audit_can_mutate_it(
    isolated_journal: Path,
) -> None:
    manager._connect_journal(create=True).close()
    with sqlite3.connect(isolated_journal) as connection:
        assert connection.execute("PRAGMA journal_mode=WAL").fetchone()[0] == "wal"
        connection.execute("PRAGMA user_version=7")
        connection.commit()
    for sidecar in manager._journal_sidecars():
        if os.path.lexists(sidecar):
            sidecar.unlink()
    before = (isolated_journal.read_bytes(), isolated_journal.stat())
    assert before[0][18:20] == b"\x02\x02"
    with pytest.raises(canary.StagedCanaryError, match="rollback-journal SQLite"):
        manager.audit()
    after = (isolated_journal.read_bytes(), isolated_journal.stat())
    assert after[0] == before[0]
    assert (after[1].st_ino, after[1].st_size, after[1].st_mtime_ns) == (
        before[1].st_ino,
        before[1].st_size,
        before[1].st_mtime_ns,
    )
    assert not any(os.path.lexists(path) for path in manager._journal_sidecars())


def test_journal_sidecar_is_rejected_without_following_it(
    isolated_journal: Path, tmp_path: Path
) -> None:
    manager._connect_journal(create=True).close()
    rollback = Path(f"{isolated_journal}-journal")
    rollback.symlink_to(tmp_path / "missing")
    with pytest.raises(canary.StagedCanaryError, match="rollback sidecar is present"):
        manager.audit()
    assert rollback.is_symlink()
    with pytest.raises(canary.StagedCanaryError, match="rollback sidecar is unsafe"):
        manager._connect_journal(create=True)
    rollback.unlink()
    rollback.write_bytes(b"not a protected SQLite rollback journal")
    rollback.chmod(0o644)
    with pytest.raises(canary.StagedCanaryError, match="rollback sidecar is unsafe"):
        manager._connect_journal(create=True)


def test_rw_open_recovers_a_real_hot_delete_journal_after_process_crash(
    isolated_journal: Path,
) -> None:
    manager._connect_journal(create=True).close()
    crashed = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import os,sqlite3,sys;"
                "connection=sqlite3.connect(sys.argv[1],isolation_level=None);"
                "connection.execute('PRAGMA cache_size=1');"
                "connection.execute('PRAGMA cache_spill=ON');"
                "connection.execute('BEGIN IMMEDIATE');"
                "connection.execute('CREATE TABLE crash_probe(value BLOB)');"
                "connection.execute('INSERT INTO crash_probe VALUES(randomblob(1000000))');"
                'connection.execute("UPDATE staged_canary_meta SET '
                "journal_format='forged' WHERE singleton=1\");"
                "os._exit(23)"
            ),
            str(isolated_journal),
        ],
        check=False,
    )
    assert crashed.returncode == 23
    rollback = Path(f"{isolated_journal}-journal")
    assert rollback.is_file()
    assert stat.S_IMODE(rollback.lstat().st_mode) == 0o600
    manager._connect_journal(create=True).close()
    assert not os.path.lexists(rollback)
    with sqlite3.connect(isolated_journal) as connection:
        assert connection.execute(
            "SELECT journal_format FROM staged_canary_meta WHERE singleton=1"
        ).fetchone() == (manager.JOURNAL_FORMAT,)


def test_rw_open_cleans_a_real_cold_delete_journal_after_process_crash(
    isolated_journal: Path,
) -> None:
    manager._connect_journal(create=True).close()
    crashed = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import os,sqlite3,sys;"
                "connection=sqlite3.connect(sys.argv[1],isolation_level=None);"
                "connection.execute('BEGIN IMMEDIATE');"
                'connection.execute("UPDATE staged_canary_meta SET '
                "journal_format='forged' WHERE singleton=1\");"
                "os._exit(23)"
            ),
            str(isolated_journal),
        ],
        check=False,
    )
    assert crashed.returncode == 23
    rollback = Path(f"{isolated_journal}-journal")
    assert rollback.is_file()
    assert rollback.read_bytes()[:8] == b"\x00" * 8
    manager._connect_journal(create=True).close()
    assert not os.path.lexists(rollback)
    with sqlite3.connect(isolated_journal) as connection:
        assert connection.execute(
            "SELECT journal_format FROM staged_canary_meta WHERE singleton=1"
        ).fetchone() == (manager.JOURNAL_FORMAT,)


@pytest.mark.parametrize("cold_bytes", (b"", b"\x01\x02\x03"))
def test_rw_open_recovers_a_short_cold_rollback_sidecar(
    isolated_journal: Path, cold_bytes: bytes
) -> None:
    manager._connect_journal(create=True).close()
    rollback = Path(f"{isolated_journal}-journal")
    rollback.write_bytes(cold_bytes)
    rollback.chmod(0o600)
    manager._connect_journal(create=True).close()
    assert not os.path.lexists(rollback)


def test_journal_exact_schema_rejects_an_extra_object(
    isolated_journal: Path,
) -> None:
    manager._connect_journal(create=True).close()
    with sqlite3.connect(isolated_journal) as connection:
        connection.execute("CREATE TABLE attacker_reset_counter(value INTEGER)")
        connection.commit()
    with pytest.raises(canary.StagedCanaryError, match="schema"):
        manager.audit()


def test_pre_v4_journal_identity_fails_closed_without_in_place_upgrade(
    isolated_journal: Path,
) -> None:
    manager._prepare_canonical_state_root()
    legacy_schema = manager._SCHEMA.replace(
        "CHECK(schema_version=4)",
        "CHECK(schema_version=3)",
    ).replace("  journal_instance_id TEXT NOT NULL UNIQUE,\n", "")
    with sqlite3.connect(isolated_journal) as connection:
        connection.executescript(legacy_schema)
        connection.execute(
            "INSERT INTO staged_canary_meta VALUES(1,?,?,?,?,?)",
            (
                3,
                "local-authority-staged-canary-journal/v3",
                canary.load_policy().digest,
                canary.PINNED_MANIFEST_DIGEST,
                str(isolated_journal),
            ),
        )
        connection.commit()
    isolated_journal.chmod(0o600)
    with pytest.raises(canary.StagedCanaryError, match="schema"):
        manager.audit()


def test_archived_validator_rejects_a_coherent_no_a2_rewrite(
    isolated_journal: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    private = Ed25519PrivateKey.generate()
    resources = _archived_ready_resources(private)
    _patch_operational_inputs(monkeypatch, resources)
    canary_id, challenge, _ = _insert_archived_ready_run(private)
    assert [row["state"] for row in manager.audit()["runs"]] == ["COMMITTED"]

    forged_challenge = {**challenge, "open_p0_ids": []}
    forged_result = _signed_result(forged_challenge, resources, private)
    challenge_json = canary.canonical_json_bytes(forged_challenge).decode("utf-8")
    result_json = canary.canonical_json_bytes(forged_result).decode("utf-8")
    result_digest = canary._digest(result_json.encode("utf-8"))
    with sqlite3.connect(isolated_journal) as connection:
        connection.row_factory = sqlite3.Row
        trigger_rows = connection.execute(
            "SELECT name,sql FROM sqlite_master WHERE type='trigger' ORDER BY name"
        ).fetchall()
        for trigger in trigger_rows:
            connection.execute(f'DROP TRIGGER "{trigger["name"]}"')
        connection.execute(
            "UPDATE staged_canary_runs SET challenge_json=?,result_json=?,"
            "result_digest=? WHERE canary_id=?",
            (challenge_json, result_json, result_digest, canary_id),
        )
        prior = None
        events = connection.execute(
            "SELECT * FROM staged_canary_events ORDER BY sequence"
        ).fetchall()
        for event in events:
            detail = (
                result_digest
                if event["event_type"] == "CANARY_COMMITTED"
                else canary._digest(forged_challenge)
            )
            body = {
                "format": "local-authority-staged-canary-event/v1",
                "sequence": event["sequence"],
                "canary_id": event["canary_id"],
                "event_type": event["event_type"],
                "attempt": event["attempt"],
                "observed_at": event["observed_at"],
                "lease_token_digest": event["lease_token_digest"],
                "detail_digest": detail,
                "prior_event_digest": prior,
            }
            event_digest = canary._digest(body)
            connection.execute(
                "UPDATE staged_canary_events SET detail_digest=?,"
                "prior_event_digest=?,event_digest=? WHERE sequence=?",
                (detail, prior, event_digest, event["sequence"]),
            )
            prior = event_digest
        for trigger in trigger_rows:
            connection.execute(trigger["sql"])
        connection.commit()
    with pytest.raises(canary.StagedCanaryError, match="challenge authority"):
        manager.audit()


def test_archived_running_deadline_and_bounded_attempts_fail_closed(
    isolated_journal: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    private = Ed25519PrivateKey.generate()
    resources = _archived_ready_resources(private)
    _patch_operational_inputs(monkeypatch, resources)
    _insert_archived_ready_run(private, state="RUNNING")
    assert [row["state"] for row in manager.audit()["runs"]] == ["RUNNING"]
    with sqlite3.connect(isolated_journal) as connection:
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute("UPDATE staged_canary_runs SET attempt_count=4")
        connection.rollback()
        connection.execute(
            "UPDATE staged_canary_runs SET deadline_monotonic_ns="
            "deadline_monotonic_ns+1"
        )
        connection.commit()
    with pytest.raises(canary.StagedCanaryError, match="run state"):
        manager.audit()


def test_mutating_a_committed_run_without_a_matching_event_is_detected(
    isolated_journal: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    private = Ed25519PrivateKey.generate()
    resources = _archived_ready_resources(private)
    _patch_operational_inputs(monkeypatch, resources)
    _insert_archived_ready_run(private)
    with sqlite3.connect(isolated_journal) as connection:
        connection.execute(
            "UPDATE staged_canary_runs SET result_digest=?",
            ("sha256:" + "f" * 64,),
        )
        connection.commit()
    with pytest.raises(canary.StagedCanaryError, match="committed.*invalid"):
        manager.audit()


def test_alternate_store_cannot_be_selected_and_audit_never_creates_one(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with pytest.raises(SystemExit):
        manager._parser().parse_args(
            [
                "run",
                "--authority",
                "ready",
                "--environment",
                "staging",
                "--store",
                str(tmp_path / "forged.sqlite3"),
            ]
        )
    state = tmp_path / "absent"
    journal = state / "journal.sqlite3"
    monkeypatch.setattr(manager, "CANONICAL_STATE_ROOT", state)
    monkeypatch.setattr(manager, "CANONICAL_JOURNAL_PATH", journal)
    with pytest.raises(canary.StagedCanaryError):
        manager.audit()
    assert not state.exists()
    assert not journal.exists()


def test_audit_opens_the_existing_canonical_journal_in_sqlite_read_only_mode(
    isolated_journal: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager._connect_journal(create=True).close()
    observed: list[tuple[object, bool]] = []
    connect = manager.sqlite3.connect

    def record(database: object, *args: object, **kwargs: object):
        observed.append((database, kwargs.get("uri") is True))
        return connect(database, *args, **kwargs)

    monkeypatch.setattr(manager.sqlite3, "connect", record)
    result = manager.audit()
    assert len(observed) == 1
    assert observed[0][1] is True
    assert "?mode=ro" in str(observed[0][0])
    assert result["trusted_root_required"] is True
    assert result["privileged_rollback_evident"] is False
    assert result["durability_scope"] == (
        "POST_INITIALIZATION_CRASH_AND_POWER_LOSS_ONLY"
    )
    assert result["historical_attempt_evidence_complete"] is True
    assert result["operational_high_water_anchor_required"] is True
    assert result["operational_state"] == "HOLD"
    assert result["operational_blockers"] == [
        "EXTERNAL_HIGH_WATER_ANCHOR_NOT_PROVISIONED",
        "CONTROLLED_WAL_QUIESCENCE_SOURCE_READY_NOT_OPERATIONALLY_ACCEPTED",
    ]


def test_governed_resource_below_writable_ancestor_is_rejected(
    tmp_path: Path,
) -> None:
    unsafe = tmp_path / "renameable"
    unsafe.mkdir(mode=0o700)
    unsafe.chmod(0o777)
    resource = unsafe / "artifact"
    resource.write_bytes(b"fixed")
    resource.chmod(0o600)
    with pytest.raises(canary.StagedCanaryError, match="ancestor is unsafe"):
        canary._safe_observation(
            resource,
            label="attack resource",
            owner_uids={os.geteuid()},
            kinds={"file"},
            allowed_modes={0o600},
            include_digest=True,
        )


def test_governed_resource_path_swap_during_digest_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # pytest's Linux base directory is normally below world-writable /tmp,
    # which the governed-resource contract correctly rejects before reaching
    # the descriptor/path swap check.  A private directory below the user's
    # home has a non-writeable ancestor chain on both macOS and Linux.
    with tempfile.TemporaryDirectory(
        prefix="quant-platform-canary-",
        dir=Path.home(),
    ) as directory:
        safe_root = Path(directory)
        safe_root.chmod(0o700)
        resource = safe_root / "resource"
        displaced = safe_root / "displaced"
        resource.write_bytes(b"fixed")
        resource.chmod(0o600)
        read = canary.os.read
        swapped = False

        def swap_then_read(descriptor: int, length: int) -> bytes:
            nonlocal swapped
            if not swapped:
                swapped = True
                resource.rename(displaced)
                resource.write_bytes(b"fixed")
                resource.chmod(0o600)
            return read(descriptor, length)

        monkeypatch.setattr(canary.os, "read", swap_then_read)
        with pytest.raises(
            canary.StagedCanaryError,
            match="changed during observation|path changed",
        ):
            canary._safe_observation(
                resource,
                label="swapped resource",
                owner_uids={os.geteuid()},
                kinds={"file"},
                allowed_modes={0o600},
                include_digest=True,
            )


def test_controlled_read_only_preflight_never_initializes_or_changes_store(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from execution import controlled_execution_activation_v2 as activation

    service_dir = tmp_path / "controlled"
    service_dir.mkdir(mode=0o700)
    store = service_dir / "controlled.sqlite3"
    key = Ed25519PrivateKey.generate()
    key_raw = key.private_bytes(
        serialization.Encoding.Raw,
        serialization.PrivateFormat.Raw,
        serialization.NoEncryption(),
    )
    document = {
        "environment": "staging",
        "service_uid": os.geteuid(),
        "trader_uid": os.geteuid() + 1,
        "store_path": str(store.resolve()),
        "private_key_path": str((service_dir / "key").resolve()),
        "signer_key_id": "controlled-staging",
        "protected_store_observed": True,
        "protected_signing_key_observed": True,
    }
    monkeypatch.setattr(activation, "_load_root_owned_activation", lambda: document)
    monkeypatch.setattr(
        activation,
        "read_pinned_authority_file_v2",
        lambda *_args, **_kwargs: key_raw,
    )
    monkeypatch.setattr(
        activation,
        "_activation_registries",
        lambda _document: (object(), object()),
    )

    observed = activation._preflight_live_controlled_execution_writer_v2()
    assert observed[0] == "staging"
    assert not store.exists()
    assert not Path(str(store) + "-wal").exists()
    assert not Path(str(store) + "-shm").exists()

    store.write_bytes(b"existing-product-store")
    store.chmod(0o600)
    before = (store.read_bytes(), store.stat())
    activation._preflight_live_controlled_execution_writer_v2()
    after = (store.read_bytes(), store.stat())
    assert after[0] == before[0]
    assert (after[1].st_ino, after[1].st_size, after[1].st_mtime_ns) == (
        before[1].st_ino,
        before[1].st_size,
        before[1].st_mtime_ns,
    )
    assert not Path(str(store) + "-wal").exists()
    assert not Path(str(store) + "-shm").exists()


def test_trader_read_only_preflight_never_initializes_or_changes_store(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from execution import trader_webauthn_activation_v2 as activation

    service_dir = tmp_path / "trader"
    service_dir.mkdir(mode=0o700)
    store = service_dir / "trader.sqlite3"
    socket_path = tmp_path / "controlled.sock"
    socket_path.write_bytes(b"socket-placeholder")
    resolved_socket = socket_path.resolve()
    service_uid = os.geteuid()
    controlled_uid = service_uid + 1
    controlled_caller_gid = os.getegid() + 1
    socket_identity = {"gid": controlled_caller_gid}
    digest = "sha256:" + "9" * 64
    document = {
        "environment": "staging",
        "service_uid": service_uid,
        "controlled_execution_uid": controlled_uid,
        "controlled_execution_socket_path": str(resolved_socket),
        "store_path": str(store.resolve()),
        "registration_payload_validated": True,
        "attestation_state": "UNATTESTED",
        "human_enrollment_witness_digest": digest,
        "trusted_attestation_evidence_digest": None,
        "protected_store_observed": True,
        "enrollment_transcript_digest": digest,
        "rp_registry": {"generation": 1, "entries": [{"closed": True}]},
        "credential_registry": {
            "registry_id": "registry",
            "generation": 1,
            "credentials": [{"closed": True}],
        },
    }
    monkeypatch.setattr(activation, "_load_live_activation_document", lambda: document)
    monkeypatch.setattr(
        activation,
        "_deployments",
        lambda _environment: [
            {
                "authority_id": "controlled_execution",
                "caller_group": "qp_staging_controlled_execution_callers",
            }
        ],
    )
    monkeypatch.setattr(
        activation.grp,
        "getgrnam",
        lambda _name: SimpleNamespace(gr_gid=controlled_caller_gid),
    )
    monkeypatch.setattr(
        activation,
        "ExactFourTraderRelyingPartyV2",
        lambda **_kwargs: object(),
    )
    monkeypatch.setattr(
        activation,
        "ExactFourTraderRelyingPartyRegistryV2",
        lambda *_args, **_kwargs: object(),
    )
    monkeypatch.setattr(
        activation,
        "ExactFourTraderCredentialV2",
        lambda **_kwargs: object(),
    )
    monkeypatch.setattr(
        activation,
        "ExactFourTraderCredentialRegistryV2",
        lambda *_args, **_kwargs: object(),
    )
    monkeypatch.setattr(
        activation, "_decode_canonical_base64url", lambda *_a, **_k: b"x" * 16
    )
    monkeypatch.setattr(
        activation.serialization, "load_der_public_key", lambda _raw: object()
    )
    original_lstat = Path.lstat

    def controlled_socket_lstat(path: Path):
        observed = original_lstat(path)
        if path == resolved_socket:
            return SimpleNamespace(
                st_mode=stat.S_IFSOCK | 0o660,
                st_uid=controlled_uid,
                st_gid=socket_identity["gid"],
            )
        return observed

    monkeypatch.setattr(Path, "lstat", controlled_socket_lstat)
    rp_fields = {
        "environment",
        "policy_id",
        "policy_generation",
        "rp_id",
        "origin",
        "effective_at",
        "status",
        "user_presence_required",
        "user_verification_required",
    }
    document["rp_registry"]["entries"] = [dict.fromkeys(rp_fields, "fixed")]
    credential_fields = {
        "environment",
        "credential_id_base64url",
        "public_key_spki_der_base64",
        "rp_policy_digest",
        "effective_at",
        "initial_sign_count",
        "counter_mode",
        "status",
        "algorithm",
        "key_backend",
    }
    credential = dict.fromkeys(credential_fields, "fixed")
    credential["status"] = "ACTIVE"
    credential["key_backend"] = "UNATTESTED"
    credential["public_key_spki_der_base64"] = base64.b64encode(b"key").decode("ascii")
    document["credential_registry"]["credentials"] = [credential]

    observed = activation._preflight_live_exact_four_trader_authority_v2()
    assert observed[0] == "staging"
    assert not store.exists()
    assert not Path(str(store) + "-wal").exists()
    assert not Path(str(store) + "-shm").exists()

    socket_identity["gid"] = controlled_caller_gid + 1
    with pytest.raises(Exception, match="socket identity or permissions"):
        activation._preflight_live_exact_four_trader_authority_v2()
    socket_identity["gid"] = controlled_caller_gid

    store.write_bytes(b"existing-product-store")
    store.chmod(0o600)
    before = (store.read_bytes(), store.stat())
    activation._preflight_live_exact_four_trader_authority_v2()
    after = (store.read_bytes(), store.stat())
    assert after[0] == before[0]
    assert (after[1].st_ino, after[1].st_size, after[1].st_mtime_ns) == (
        before[1].st_ino,
        before[1].st_size,
        before[1].st_mtime_ns,
    )
    assert not Path(str(store) + "-wal").exists()
    assert not Path(str(store) + "-shm").exists()


def test_controlled_inactive_canary_audits_exact_store_via_pinned_descriptor(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from execution import controlled_execution_activation_v2 as activation
    from execution.controlled_execution_store_v2 import (
        _WRITER_CONSTRUCTION_TOKEN,
        SQLiteControlledExecutionWriterV2,
    )
    from execution.controlled_execution_types_v2 import _ControlledWriterSignerV2

    store = tmp_path / "controlled.sqlite3"
    signer = _ControlledWriterSignerV2(
        key_id="controlled-staging",
        private_key=Ed25519PrivateKey.generate(),
    )
    rp = SimpleNamespace(policy_digest="sha256:" + "b" * 64)
    relying_parties = SimpleNamespace(
        registry_digest="sha256:" + "c" * 64,
        require=lambda _environment: rp,
    )
    credentials = SimpleNamespace(
        registry_digest="sha256:" + "d" * 64,
        credentials=(),
    )
    SQLiteControlledExecutionWriterV2(
        store,
        environment="staging",
        signer=signer,
        clock=lambda: datetime.now(UTC),
        trader_uid=502,
        relying_parties=relying_parties,
        credentials=credentials,
        server_bound=False,
        test_mode=True,
        lifecycle=None,
        _token=_WRITER_CONSTRUCTION_TOKEN,
    )
    __import__("gc").collect()
    provisioning = sqlite3.connect(store)
    provisioning.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    provisioning.execute("PRAGMA journal_mode=DELETE")
    provisioning.close()
    store.chmod(0o600)
    before = (store.read_bytes(), store.stat())
    observed_targets: list[str] = []
    connect = activation.sqlite3.connect

    def record(database: object, *args: object, **kwargs: object):
        observed_targets.append(str(database))
        return connect(database, *args, **kwargs)

    monkeypatch.setattr(activation.sqlite3, "connect", record)
    audit = activation._audit_live_controlled_store_read_only_v2(
        store,
        environment="staging",
        trader_uid=502,
        signer_key_id=signer.key_id,
        relying_parties=relying_parties,
        credentials=credentials,
        expected_uid=os.geteuid(),
    )
    after = (store.read_bytes(), store.stat())
    assert audit["schema"] == "exact-four-controlled-writer-store/v2"
    assert observed_targets == [
        next(target for target in observed_targets if "/dev/fd/" in target)
    ]
    assert after[0] == before[0]
    assert (after[1].st_ino, after[1].st_size, after[1].st_mtime_ns) == (
        before[1].st_ino,
        before[1].st_size,
        before[1].st_mtime_ns,
    )
    assert not os.path.lexists(f"{store}-wal")
    assert not os.path.lexists(f"{store}-shm")

    broken_rollback = Path(f"{store}-journal")
    broken_rollback.symlink_to(tmp_path / "missing")
    with pytest.raises(Exception, match="inactive private SQLite"):
        activation._audit_live_controlled_store_read_only_v2(
            store,
            environment="staging",
            trader_uid=502,
            signer_key_id=signer.key_id,
            relying_parties=relying_parties,
            credentials=credentials,
            expected_uid=os.geteuid(),
        )
    broken_rollback.unlink()

    with sqlite3.connect(store) as connection:
        assert connection.execute("PRAGMA journal_mode=WAL").fetchone()[0] == "wal"
    for suffix in ("-wal", "-shm"):
        sidecar = Path(f"{store}{suffix}")
        if sidecar.exists():
            sidecar.unlink()
    wal_before = (store.read_bytes(), store.stat())
    with pytest.raises(Exception, match="DELETE-mode"):
        activation._audit_live_controlled_store_read_only_v2(
            store,
            environment="staging",
            trader_uid=502,
            signer_key_id=signer.key_id,
            relying_parties=relying_parties,
            credentials=credentials,
            expected_uid=os.geteuid(),
        )
    wal_after = (store.read_bytes(), store.stat())
    assert wal_after[0] == wal_before[0]
    assert (wal_after[1].st_ino, wal_after[1].st_size, wal_after[1].st_mtime_ns) == (
        wal_before[1].st_ino,
        wal_before[1].st_size,
        wal_before[1].st_mtime_ns,
    )
    with sqlite3.connect(store) as connection:
        connection.execute("PRAGMA journal_mode=DELETE")

    with sqlite3.connect(store) as connection:
        connection.execute("CREATE TABLE attacker_extra(value INTEGER)")
        connection.commit()
    with pytest.raises(Exception, match="schema inventory"):
        activation._audit_live_controlled_store_read_only_v2(
            store,
            environment="staging",
            trader_uid=502,
            signer_key_id=signer.key_id,
            relying_parties=relying_parties,
            credentials=credentials,
            expected_uid=os.geteuid(),
        )


@pytest.mark.parametrize("unsafe_kind", ("symlink", "fifo", "wrong_mode"))
def test_controlled_live_writer_rejects_unsafe_store_before_writer_construction(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    unsafe_kind: str,
) -> None:
    from execution import controlled_execution_activation_v2 as activation
    from execution import controlled_execution_quiescence_v2 as quiescence

    store = tmp_path / "controlled.sqlite3"
    target = tmp_path / "attacker.sqlite3"
    tmp_path.chmod(0o700)
    target.write_bytes(b"attacker")
    target.chmod(0o600)
    if unsafe_kind == "symlink":
        store.symlink_to(target)
    elif unsafe_kind == "fifo":
        os.mkfifo(store, 0o600)
    else:
        store.write_bytes(b"unsafe-mode")
        store.chmod(0o640)
    monkeypatch.setattr(
        activation,
        "_load_live_controlled_execution_writer_material_v2",
        lambda: (
            "staging",
            store,
            object(),
            502,
            object(),
            object(),
        ),
    )
    opened = False

    def unexpected_writer(*_args: object, **_kwargs: object) -> object:
        nonlocal opened
        opened = True
        return object()

    monkeypatch.setattr(
        activation,
        "SQLiteControlledExecutionWriterV2",
        unexpected_writer,
    )
    lease = quiescence._acquire_lifecycle_lock(
        quiescence._ControlledStoreIdentityV2(
            environment="staging",
            service_uid=os.geteuid(),
            store_path=store,
        ),
        require_marker_absent=True,
    )
    try:
        with pytest.raises(Exception, match="private single-link"):
            activation._load_live_controlled_execution_writer_v2(
                server_bound=True,
                lifecycle=lease,
            )
    finally:
        lease.close()
    assert opened is False


def test_controlled_live_writer_provisions_private_store_and_pins_initial_inode(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from execution import controlled_execution_activation_v2 as activation
    from execution import controlled_execution_quiescence_v2 as quiescence

    store = tmp_path / "controlled.sqlite3"
    tmp_path.chmod(0o700)
    material = (
        "staging",
        store,
        object(),
        502,
        object(),
        object(),
    )
    monkeypatch.setattr(
        activation,
        "_load_live_controlled_execution_writer_material_v2",
        lambda: material,
    )
    marker = object()

    def observe_private_store(*_args: object, **_kwargs: object) -> object:
        observed = store.lstat()
        assert stat.S_ISREG(observed.st_mode)
        assert observed.st_uid == os.geteuid()
        assert stat.S_IMODE(observed.st_mode) == 0o600
        assert observed.st_nlink == 1
        return marker

    monkeypatch.setattr(
        activation,
        "SQLiteControlledExecutionWriterV2",
        observe_private_store,
    )
    lease = quiescence._acquire_lifecycle_lock(
        quiescence._ControlledStoreIdentityV2(
            environment="staging",
            service_uid=os.geteuid(),
            store_path=store,
        ),
        require_marker_absent=True,
    )
    try:
        assert (
            activation._load_live_controlled_execution_writer_v2(
                server_bound=True,
                lifecycle=lease,
            )
            is marker
        )

        initial = store.lstat()

        def swap_store(*_args: object, **_kwargs: object) -> object:
            store.unlink()
            store.write_bytes(b"replacement")
            store.chmod(0o600)
            return marker

        monkeypatch.setattr(
            activation,
            "SQLiteControlledExecutionWriterV2",
            swap_store,
        )
        with pytest.raises(
            Exception,
            match="changed during live writer initialization",
        ):
            activation._load_live_controlled_execution_writer_v2(
                server_bound=True,
                lifecycle=lease,
            )
        assert store.lstat().st_ino != initial.st_ino
    finally:
        lease.close()


@pytest.mark.parametrize(
    ("authority_id", "constructor_name"),
    (
        ("d1_sync", "D1SyncNow"),
        ("ops_projection", "OpsProjectionRenderAndSign"),
        ("coverage_transition", "CoverageTransitionAuthorize"),
        ("ready", "ReadyPublishProfilePlanBound"),
    ),
)
def test_file_authority_protocol_adapter_fails_if_exact_handler_wiring_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    authority_id: str,
    constructor_name: str,
) -> None:
    from scripts import local_authority_entrypoints as entrypoints
    from scripts import run_local_authority as runner

    service_dir = tmp_path / authority_id
    service_dir.mkdir(mode=0o700)
    service_uid = os.geteuid()
    row = {
        "service_user": "authority-user",
        "runtime_config_path": str(tmp_path / "runtime.json"),
        "ledger_path": str(service_dir / "events.sqlite3"),
        "service_dir": str(service_dir),
        "key_path": str(service_dir / "key"),
    }
    resources = {
        "d1_sync": {
            "governed_db_path": str(service_dir / "mirror.sqlite3"),
            "cloudflare_token_path": str(service_dir / "token"),
            "node_executable_path": "/fixed/node",
            "wrangler_cli_path": "/fixed/wrangler",
            "wrangler_cli_tree_path": "/fixed/wrangler-tree",
            "wrangler_config_path": "/fixed/wrangler.toml",
            "wrangler_lock_path": "/fixed/package-lock.json",
        },
        "ops_projection": {"artifact_store": str(service_dir)},
        "coverage_transition": {},
        "ready": {"snapshot_root": str(service_dir)},
    }[authority_id]
    manifest = {
        "principals": {
            name: {
                "deployments": {
                    "staging": {
                        "service_user": name + "-user",
                        "socket_path": str(tmp_path / (name + ".sock")),
                    }
                }
            }
            for name in (
                "d1_sync",
                "ops_projection",
                "coverage_transition",
                "ready",
            )
        }
    }
    monkeypatch.setattr(canary, "_deployment", lambda *_a, **_k: row)
    monkeypatch.setattr(canary, "load_and_validate_manifest", lambda: manifest)
    monkeypatch.setattr(canary, "_runtime_binding", _fake_binding)
    monkeypatch.setattr(
        canary,
        "observe_runtime_resource_bindings",
        lambda **_kwargs: [],
    )
    monkeypatch.setattr(
        canary.pwd,
        "getpwnam",
        lambda name: SimpleNamespace(
            pw_uid=service_uid if name == "authority-user" else service_uid + 1
        ),
    )
    monkeypatch.setattr(
        canary,
        "read_protected_authority_file",
        lambda *_a, **_k: SimpleNamespace(raw=b"{}"),
    )
    monkeypatch.setattr(
        runner,
        "decode_runtime_config",
        lambda *_a, **_k: {"resources": resources},
    )
    monkeypatch.setattr(
        canary,
        "_load_public_metadata",
        lambda *_a, **_k: {
            "key_id": "fixed-key",
            "public_key_base64": "fixed-public",
        },
    )

    class TestCustody:
        def __init__(self, *_args: object, **_kwargs: object) -> None:
            pass

        def public_key_base64(self) -> str:
            return "fixed-public"

    monkeypatch.setattr(canary, "FileEd25519KeyCustody", TestCustody)

    def broken_handler(*_args: object, **_kwargs: object) -> None:
        raise service.LocalAuthorityError("synthetic broken wiring")

    monkeypatch.setattr(entrypoints, constructor_name, broken_handler)
    with pytest.raises(canary.StagedCanaryError, match="handler preflight"):
        canary._run_authority_specific_inactive_adapter(
            authority_id=authority_id,
            environment="staging",
        )


def test_canary_does_not_change_the_strict_all_p0_gate() -> None:
    with pytest.raises(FindingLedgerError):
        require_pinned_finding_ledger_gate()
