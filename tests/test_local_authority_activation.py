"""Behavioral tests for root-owned local authority activation evidence."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import socket
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from scripts import local_authority_activation as activation
from scripts import local_authority_service as service


def _digest(raw: bytes) -> str:
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def _active_fixture(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[Path, Path, Path, Path, socket.socket]:
    protected = tmp_path / "protected"
    service_dir = protected / "staging" / "ready"
    service_dir.mkdir(parents=True)
    service_dir.chmod(0o700)
    uid = os.geteuid()
    gid = os.getegid()

    private = Ed25519PrivateKey.generate()
    seed = private.private_bytes(
        serialization.Encoding.Raw,
        serialization.PrivateFormat.Raw,
        serialization.NoEncryption(),
    )
    public_raw = private.public_key().public_bytes(
        serialization.Encoding.Raw,
        serialization.PublicFormat.Raw,
    )
    public_b64 = base64.b64encode(public_raw).decode("ascii")
    key_path = service_dir / "ed25519-private-key"
    key_path.write_bytes(seed)
    key_path.chmod(0o600)

    ledger_path = service_dir / "authority-events.sqlite3"
    service.SQLiteAuthorityEventLedger(
        ledger_path,
        authority_id="ready",
        environment="staging",
        expected_uid=uid,
    ).initialize()

    socket_path = Path(tempfile.mkdtemp(prefix="qp-a-", dir="/tmp")) / "r.sock"
    listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    listener.bind(str(socket_path))
    os.chown(socket_path, -1, gid)
    socket_path.chmod(0o660)

    repository = tmp_path / "repository"
    registry_path = repository / "specs/ready/readiness_verify_public_keys.json"
    registry_path.parent.mkdir(parents=True)
    registry = {
        "schema_version": 1,
        "purpose": "readiness_attestation_verification",
        "keys": [
            {
                "key_id": "ready-staging-v1",
                "algorithm": "Ed25519",
                "public_key_b64": public_b64,
                "status": "active",
            }
        ],
    }
    registry_raw = json.dumps(registry, sort_keys=True).encode()
    registry_path.write_bytes(registry_raw)

    runtime_config_path = protected / "runtime-config/staging/ready.json"
    runtime_config_path.parent.mkdir(parents=True)
    runtime_config_raw = b'{"format":"test-runtime-config/v1","resources":{}}'
    runtime_config_path.write_bytes(runtime_config_raw)
    runtime_config_path.chmod(0o444)

    runtime_bundle = tmp_path / "bundle"
    runtime_scripts = runtime_bundle / "scripts"
    runtime_scripts.mkdir(parents=True)
    runtime_entrypoint = runtime_scripts / "run_local_authority.py"
    runtime_entrypoint.write_text("# immutable test entrypoint\n", encoding="utf-8")
    runtime_entrypoint.chmod(0o444)
    runtime_scripts.chmod(0o555)
    runtime_bundle.chmod(0o555)
    runtime_python = Path(sys.executable).resolve(strict=True)

    manifest = {
        "principals": {
            "ready": {
                "registry_path": "specs/ready/readiness_verify_public_keys.json",
                "deployments": {
                    "staging": {
                        "service_user": "qp_test_ready",
                        "key_backend": "protected_local_key",
                        "socket_path": str(socket_path),
                    }
                },
            }
        }
    }
    monkeypatch.setattr(activation, "load_and_validate_manifest", lambda: manifest)
    monkeypatch.setattr(
        activation,
        "require_pinned_finding_ledger_gate",
        lambda: SimpleNamespace(digest="sha256:" + "a" * 64),
    )
    monkeypatch.setattr(
        activation.pwd,
        "getpwnam",
        lambda _username: SimpleNamespace(
            pw_uid=uid,
            pw_gid=gid,
            pw_dir="/var/empty",
            pw_shell="/usr/bin/false",
        ),
    )
    monkeypatch.setattr(
        activation.grp,
        "getgrnam",
        lambda _name: SimpleNamespace(gr_gid=gid),
    )

    row = {
        "authority_id": "ready",
        "environment": "staging",
        "state": "ACTIVE",
        "service_user": "qp_test_ready",
        "service_uid": uid,
        "service_gid": gid,
        "service_home": "/var/empty",
        "service_shell": "/usr/bin/false",
        "hidden_identity": True,
        "caller_group": "qp_staging_ready_callers",
        "caller_group_gid": gid,
        "key_backend": "protected_local_key",
        "key_id": "ready-staging-v1",
        "public_key_base64": public_b64,
        "public_key_sha256": _digest(public_raw),
        "registry_path": "specs/ready/readiness_verify_public_keys.json",
        "registry_file_digest": _digest(registry_raw),
        "runtime_config_path": str(runtime_config_path),
        "runtime_config_file_digest": _digest(runtime_config_raw),
        "runtime_config_observation": activation.stat_observation(
            runtime_config_path.lstat()
        ),
        "runtime_bundle_path": str(runtime_bundle),
        "runtime_bundle_digest": activation.runtime_bundle_tree_digest(
            runtime_bundle, expected_owner_uid=uid
        ),
        "runtime_bundle_observation": activation.stat_observation(
            runtime_bundle.lstat()
        ),
        "runtime_entrypoint_path": str(runtime_entrypoint),
        "runtime_entrypoint_digest": activation.regular_file_digest(runtime_entrypoint),
        "runtime_entrypoint_observation": activation.stat_observation(
            runtime_entrypoint.lstat()
        ),
        "runtime_python_path": str(runtime_python),
        "runtime_python_digest": activation.regular_file_digest(runtime_python),
        "runtime_python_observation": activation.stat_observation(
            runtime_python.lstat()
        ),
        "runtime_resource_bindings": [],
        "key_path": str(key_path),
        "key_observation": activation.stat_observation(key_path.lstat()),
        "ledger_path": str(ledger_path),
        "ledger_observation": activation.stat_observation(ledger_path.lstat()),
        "socket_path": str(socket_path),
        "socket_observation": activation.stat_observation(socket_path.lstat()),
    }
    document = {
        "format": activation.ACTIVATION_STATE_FORMAT,
        "manifest_digest": activation.PINNED_MANIFEST_DIGEST,
        "finding_ledger_digest": "sha256:" + "a" * 64,
        "generated_at": datetime.now(UTC).isoformat(),
        "deployments": [row],
    }
    document["state_digest"] = activation.state_body_digest(document)
    state_path = tmp_path / "activation-state.json"
    state_path.write_bytes(activation.canonical_json_bytes(document))
    state_path.chmod(0o444)
    return state_path, protected, repository, socket_path, listener


def test_active_state_binds_manifest_gate_uid_key_registry_ledger_and_socket(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state_path, protected, repository, socket_path, listener = _active_fixture(
        tmp_path, monkeypatch
    )
    try:
        uid, row = activation.require_active_service_identity(
            authority_id="ready",
            environment="staging",
            path=state_path,
            expected_root_uid=os.geteuid(),
            current_euid=os.geteuid(),
            current_egid=os.getegid(),
            _protected_root=protected,
            _repository_root=repository,
        )
        assert uid == os.geteuid()
        assert row["state"] == "ACTIVE"
    finally:
        listener.close()
        socket_path.unlink(missing_ok=True)
        socket_path.parent.rmdir()


def test_active_state_fails_closed_when_live_key_inode_changes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state_path, protected, repository, socket_path, listener = _active_fixture(
        tmp_path, monkeypatch
    )
    key_path = protected / "staging/ready/ed25519-private-key"
    replacement = key_path.with_suffix(".replacement")
    replacement.write_bytes(key_path.read_bytes())
    replacement.chmod(0o600)
    replacement.replace(key_path)
    try:
        with pytest.raises(
            activation.ActivationStateError, match="observation is stale"
        ):
            activation.require_active_service_identity(
                authority_id="ready",
                environment="staging",
                path=state_path,
                expected_root_uid=os.geteuid(),
                current_euid=os.geteuid(),
                current_egid=os.getegid(),
                _protected_root=protected,
                _repository_root=repository,
            )
    finally:
        listener.close()
        socket_path.unlink(missing_ok=True)
        socket_path.parent.rmdir()


def test_d1_runtime_bindings_pin_node_cli_tree_config_lock_and_inode(
    tmp_path: Path,
) -> None:
    node = tmp_path / "node"
    node.write_bytes(b"reviewed node")
    node.chmod(0o555)
    cli_tree = tmp_path / "wrangler-tree"
    cli_tree.mkdir()
    cli = cli_tree / "wrangler.js"
    cli.write_bytes(b"reviewed wrangler")
    cli.chmod(0o444)
    cli_tree.chmod(0o555)
    config = tmp_path / "wrangler.toml"
    config.write_bytes(b'name = "quant-ingest"\n')
    config.chmod(0o444)
    lock = tmp_path / "package-lock.json"
    lock.write_bytes(b'{"lockfileVersion":3}')
    lock.chmod(0o444)
    resources = {
        "node_executable_path": str(node),
        "wrangler_cli_path": str(cli),
        "wrangler_cli_tree_path": str(cli_tree),
        "wrangler_config_path": str(config),
        "wrangler_lock_path": str(lock),
    }
    recorded = activation.observe_runtime_resource_bindings(
        authority_id="d1_sync",
        resources=resources,
        expected_owner_uid=os.geteuid(),
    )
    assert {row["name"] for row in recorded} == set(resources)
    assert all(row["observation"]["inode"] > 0 for row in recorded)

    replacement = config.with_suffix(".replacement")
    replacement.write_bytes(config.read_bytes())
    replacement.chmod(0o444)
    replacement.replace(config)
    with pytest.raises(activation.ActivationStateError, match="observation is stale"):
        activation._require_live_runtime_resource_bindings(
            authority_id="d1_sync",
            resources=resources,
            recorded=recorded,
            expected_owner_uid=os.geteuid(),
        )


def test_checked_in_state_is_absent_and_pending_contract_stays_unchanged() -> None:
    assert not activation.ACTIVATION_STATE_PATH.exists()
    from scripts.authority_principal_manifest import load_and_validate_manifest

    manifest = load_and_validate_manifest()
    assert all(
        manifest["principals"][authority]["deployments"][environment]["mode"]
        == "PENDING_NO_KEY"
        for authority in (
            "d1_sync",
            "ops_projection",
            "coverage_transition",
            "ready",
            "trader",
            "controlled_execution",
        )
        for environment in ("staging", "production")
    )
