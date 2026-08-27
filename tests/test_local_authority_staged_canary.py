"""Structural and attack tests for the narrow local authority canary gate."""

from __future__ import annotations

import base64
import json
import os
import sqlite3
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
    return {
        "resource_digest": "sha256:" + "6" * 64,
        "key": {
            "key_id": "ready-staging-canary",
            "public_key_base64": base64.b64encode(public).decode("ascii"),
            "public_key_sha256": (
                "sha256:" + __import__("hashlib").sha256(public).hexdigest()
            ),
        },
    }


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

    def journal_metadata() -> None:
        info = journal.lstat()
        if not info.st_mode & 0o100000 or info.st_mode & 0o777 != 0o600:
            raise canary.StagedCanaryError("test journal metadata is unsafe")

    monkeypatch.setattr(manager, "_require_journal_metadata", journal_metadata)
    return journal


def _patch_operational_inputs(
    monkeypatch: pytest.MonkeyPatch,
    resources: dict[str, object],
) -> None:
    monkeypatch.setattr(manager, "_runtime_binding", _fake_binding)
    monkeypatch.setattr(manager, "load_pinned_finding_ledger", _fake_ledger)
    monkeypatch.setattr(manager, "_boot_id", lambda: "test-boot")
    monkeypatch.setattr(
        manager,
        "observe_preflight_resources",
        lambda **_kwargs: resources,
    )


def test_policy_is_independently_pinned_and_excludes_cloudflare_receipt() -> None:
    policy = canary.load_policy()
    assert set(policy.actions) == {
        "d1_sync",
        "ops_projection",
        "coverage_transition",
        "ready",
        "trader",
        "controlled_execution",
    }
    assert all(
        action.action.startswith(action.authority_id + ":inactive_")
        for action in policy.actions.values()
    )
    raw = json.loads(canary.POLICY_PATH.read_text(encoding="utf-8"))
    assert raw["scope"] == "LOCAL_OS_AUTHORITIES_ONLY"
    assert raw["excluded_authorities"][0]["authority_id"] == "receipt"
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
    assert set(command.choices) == {"plan", "audit", "run"}
    assert not hasattr(manager, "issue_permit")
    assert not hasattr(manager, "complete_permit")
    plan = manager.plan(authority_id="ready", environment="staging")
    assert plan["canonical_journal_path"] == str(canary.CANONICAL_JOURNAL_PATH)
    assert plan["caller_selectable_path"] is False
    assert plan["caller_selectable_owner"] is False
    assert plan["caller_selectable_source_sha"] is False
    assert plan["caller_selectable_resource_digest"] is False


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
        canary.run_exact_inactive_preflight(
            raw,
            expected_authority_id="d1_sync",
            expected_environment="staging",
        )


def test_trader_preflight_cannot_claim_a_signing_or_human_present_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    resources: dict[str, object] = {
        "resource_digest": "sha256:" + "6" * 64,
        "key": None,
    }
    deadline = canary.time.monotonic_ns() + 60_000_000_000
    challenge = _challenge(
        authority_id="trader",
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
    from execution import trader_webauthn_activation_v2 as trader_activation

    monkeypatch.setattr(
        trader_activation,
        "open_live_exact_four_trader_authority_v2",
        lambda: SimpleNamespace(environment="staging"),
    )
    result = canary.run_exact_inactive_preflight(
        canary.canonical_json_bytes(challenge),
        expected_authority_id="trader",
        expected_environment="staging",
    )
    assert result["proof_kind"] == ("ROOT_EXEC_EXACT_UID_WEBAUTHN_REGISTRY_PREFLIGHT")
    assert result["signature"] is None
    assert result["issuer_key_id"] is None
    assert result["research_eligible"] is False
    assert all(value is False for value in result["strict_boundaries"].values())


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

    class ExactTestCustody:
        def __init__(self, *_args: object, **_kwargs: object) -> None:
            pass

        def sign(self, message: bytes) -> str:
            return "ed25519:" + base64.b64encode(private.sign(message)).decode("ascii")

    monkeypatch.setattr(canary, "FileEd25519KeyCustody", ExactTestCustody)
    result = canary.run_exact_inactive_preflight(
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
        deadline_monotonic_ns=manager.time.monotonic_ns() + 60_000_000_000,
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


def test_atomic_run_commits_only_verified_ineligible_evidence_and_is_idempotent(
    isolated_journal: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    private = Ed25519PrivateKey.generate()
    resources = _resource_snapshot(private)
    _patch_operational_inputs(monkeypatch, resources)
    monkeypatch.setattr(manager, "_require_protected_manager_binding", lambda: None)

    def execute(**kwargs: object) -> bytes:
        challenge = kwargs["challenge"]
        assert isinstance(challenge, dict)
        result = _signed_result(challenge, resources, private)
        return canary.canonical_json_bytes(result)

    monkeypatch.setattr(manager, "_execute_exact_runner", execute)
    first = manager.run_canary(authority_id="ready", environment="staging")
    second = manager.run_canary(authority_id="ready", environment="staging")
    assert first["status"] == "COMMITTED_RESEARCH_INELIGIBLE_CANARY"
    assert second["status"] == "ALREADY_COMMITTED_RESEARCH_INELIGIBLE_CANARY"
    assert first["canary_id"] == second["canary_id"]
    assert first["canary_digest"] == second["canary_digest"]
    assert first["research_eligible"] is False
    assert all(value is False for value in first["strict_boundaries"].values())

    with sqlite3.connect(isolated_journal) as connection:
        run = connection.execute(
            "SELECT state,attempt_count,result_digest FROM staged_canary_runs"
        ).fetchone()
        events = connection.execute(
            "SELECT event_type FROM staged_canary_events ORDER BY sequence"
        ).fetchall()
    assert run[0] == "COMMITTED"
    assert run[1] == 1
    assert run[2].startswith("sha256:")
    assert [row[0] for row in events] == [
        "LEASE_ACQUIRED",
        "ACTION_STARTED",
        "CANARY_COMMITTED",
    ]


def test_expired_crash_lease_is_recoverable_and_retries_are_bounded(
    isolated_journal: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    private = Ed25519PrivateKey.generate()
    resources = _resource_snapshot(private)
    _patch_operational_inputs(monkeypatch, resources)
    canary_id, token, _challenge_doc, _ = manager._acquire_lease(
        authority_id="ready", environment="staging"
    )
    assert token
    with sqlite3.connect(isolated_journal) as connection:
        connection.execute(
            "UPDATE staged_canary_runs SET deadline_monotonic_ns=0 WHERE canary_id=?",
            (canary_id,),
        )
        connection.commit()
    second_id, second_token, _challenge_doc, _ = manager._acquire_lease(
        authority_id="ready", environment="staging"
    )
    assert second_id == canary_id
    assert second_token != token
    manager._mark_failed(
        canary_id=canary_id,
        token=second_token,
        failure_class="SyntheticFailure",
    )
    third_id, third_token, _challenge_doc, _ = manager._acquire_lease(
        authority_id="ready", environment="staging"
    )
    assert third_id == canary_id
    manager._mark_failed(
        canary_id=canary_id,
        token=third_token,
        failure_class="SyntheticFailure",
    )
    with pytest.raises(canary.StagedCanaryError, match="bounded retries"):
        manager._acquire_lease(authority_id="ready", environment="staging")
    with sqlite3.connect(isolated_journal) as connection:
        state, attempts = connection.execute(
            "SELECT state,attempt_count FROM staged_canary_runs"
        ).fetchone()
        events = [
            row[0]
            for row in connection.execute(
                "SELECT event_type FROM staged_canary_events ORDER BY sequence"
            )
        ]
    assert (state, attempts) == ("FAILED_FINAL", 3)
    assert "EXPIRED_LEASE_RECOVERED" in events


def test_monotonic_deadline_is_rechecked_under_lock_before_action(
    isolated_journal: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    private = Ed25519PrivateKey.generate()
    resources = _resource_snapshot(private)
    _patch_operational_inputs(monkeypatch, resources)
    canary_id, token, challenge, _ = manager._acquire_lease(
        authority_id="ready", environment="staging"
    )
    monkeypatch.setattr(
        manager.time,
        "monotonic_ns",
        lambda: int(challenge["deadline_monotonic_ns"]),
    )
    with pytest.raises(canary.StagedCanaryError, match="stale or expired"):
        manager._mark_action_started(canary_id=canary_id, token=token)


def test_monotonic_deadline_is_rechecked_immediately_before_durable_commit(
    isolated_journal: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    private = Ed25519PrivateKey.generate()
    resources = _resource_snapshot(private)
    _patch_operational_inputs(monkeypatch, resources)
    canary_id, token, challenge, _ = manager._acquire_lease(
        authority_id="ready", environment="staging"
    )
    manager._mark_action_started(canary_id=canary_id, token=token)
    result = _signed_result(challenge, resources, private)
    deadline = int(challenge["deadline_monotonic_ns"])
    observations = iter((deadline - 2, deadline - 1, deadline))
    monkeypatch.setattr(manager.time, "monotonic_ns", lambda: next(observations))
    with pytest.raises(canary.StagedCanaryError, match="durable commit"):
        manager._commit_canary(
            canary_id=canary_id,
            token=token,
            challenge=challenge,
            result=result,
        )
    with sqlite3.connect(isolated_journal) as connection:
        state, result_json = connection.execute(
            "SELECT state,result_json FROM staged_canary_runs"
        ).fetchone()
        tail = connection.execute(
            "SELECT event_type FROM staged_canary_events ORDER BY sequence DESC LIMIT 1"
        ).fetchone()[0]
    assert state == "RUNNING"
    assert result_json is None
    assert tail == "ACTION_STARTED"


def test_mutating_a_committed_run_without_a_matching_event_is_detected(
    isolated_journal: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    private = Ed25519PrivateKey.generate()
    resources = _resource_snapshot(private)
    _patch_operational_inputs(monkeypatch, resources)
    monkeypatch.setattr(manager, "_require_protected_manager_binding", lambda: None)
    monkeypatch.setattr(
        manager,
        "_execute_exact_runner",
        lambda **kwargs: canary.canonical_json_bytes(
            _signed_result(kwargs["challenge"], resources, private)
        ),
    )
    manager.run_canary(authority_id="ready", environment="staging")
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


def test_canary_does_not_change_the_strict_all_p0_gate() -> None:
    with pytest.raises(FindingLedgerError):
        require_pinned_finding_ledger_gate()
