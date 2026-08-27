"""Behavioral tests for fixed-identity production authority clients."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import stat
from types import SimpleNamespace

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from scripts import local_authority_clients as clients


def _activate_declared_test_identities(monkeypatch: pytest.MonkeyPatch) -> None:
    current_uid = os.geteuid()
    manifest = clients.load_and_validate_manifest()
    caller_users = {
        row["deployments"][environment]["service_user"]
        for row in manifest["local_peer_identities"].values()
        for environment in ("staging", "production")
    }

    def account(username: str):
        return SimpleNamespace(
            pw_uid=(current_uid if username in caller_users else current_uid + 1000),
            pw_gid=os.getegid(),
            pw_dir="/var/empty",
            pw_shell="/usr/bin/false",
        )

    monkeypatch.setattr(clients.pwd, "getpwnam", account)


def test_fixed_clients_emit_only_manifest_granted_operations(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _activate_declared_test_identities(monkeypatch)
    monkeypatch.setattr(
        clients.projection_signing,
        "_verify_pinned_document",
        lambda _raw, *, expected_environment: SimpleNamespace(
            issuer_key_id="ops-production-v1",
            environment=expected_environment,
        ),
    )
    monkeypatch.setattr(
        clients,
        "_verify_ready_authority_result",
        lambda _result, **_expected: None,
    )
    calls: list[tuple[object, dict[str, object], int, float]] = []

    def call(path, request, *, expected_server_uid, timeout_seconds):
        calls.append((path, request, expected_server_uid, timeout_seconds))
        operation = request["operation"]
        if operation == "d1_sync:sync_now":
            return {
                "status": "SYNCED",
                "prior_applied_cursor": 7,
                "source_change_seq": 8,
                "applied_change_seq": 8,
                "audit_digest": "sha256:" + "1" * 64,
                "export_digest": "sha256:" + "2" * 64,
                "issuer_key_id": "d1-production-v1",
                "seen": 1,
                "registered": 1,
                "skipped": 0,
            }
        if operation == "d1_sync:freeze_and_render_ops_projection":
            return {
                "status": "SIGNED",
                "signed_artifact": "projection.json",
                "signed_store_digest": "sha256:" + "3" * 64,
                "signed_document_base64": "e30=",
                "signed_document_digest": "sha256:"
                + hashlib.sha256(b"{}").hexdigest(),
                "issuer_key_id": "ops-production-v1",
            }
        if operation == "d1_sync:freeze_authorize_apply_coverage":
            return {
                "status": "COMPLETE",
                "transition_id": "sha256:" + "5" * 64,
                "build_id": "build-1",
                "publication_cutoff": "2026-08-27T00:00:00Z",
                "dataset_set_digest": "sha256:" + "6" * 64,
                "signed_transition_digest": "sha256:" + "7" * 64,
                "issuer_key_id": "coverage-production-v1",
            }
        return {
            "status": "SIGNED",
            "snapshot_id": "sha256:" + "8" * 64,
            "environment": "production",
            "authority_instance_id": "ready-authority/production/v1",
            "authority_resource_digest": "sha256:" + "9" * 64,
            "attestation_id": "sha256:" + "a" * 64,
            "attestation_base64": "e30=",
            "attestation_digest": "sha256:" + "b" * 64,
            "ready_manifest_digest": "sha256:" + "c" * 64,
            "immutable_db_digest": "sha256:" + "d" * 64,
            "signed_projection_document_digest": "sha256:" + "e" * 64,
            "issuer_key_id": "ready-production-v1",
        }

    monkeypatch.setattr(clients, "call_unix_authority", call)
    ops = clients.OpsSchedulerAuthorityClient(environment="production")
    assert ops.sync_now(event_id="cron/14357", expected_applied_cursor=7)[
        "status"
    ] == "SYNCED"
    assert ops.render_current_projection(event_id="cron/14357")["status"] == "SIGNED"
    coverage = clients.CoverageSchedulerAuthorityClient(environment="production")
    assert coverage.authorize_and_apply(
        event_id="coverage/14357",
        build_id="build-1",
        datasets=["equities_bars_daily"],
    )["status"] == "COMPLETE"
    ready = clients.ReadyPublisherAuthorityClient(environment="production")
    assert ready.publish_profile_plan_bound(
        event_id="ready/exact-four/1",
        snapshot_id="sha256:" + "8" * 64,
        signed_projection_document=b"signed projection",
    )["status"] == "SIGNED"

    assert [item[1]["operation"] for item in calls] == [
        "d1_sync:sync_now",
        "d1_sync:freeze_and_render_ops_projection",
        "d1_sync:freeze_authorize_apply_coverage",
        "ready:publish_profile_plan_bound",
    ]
    assert [item[1]["purpose"] for item in calls] == [
        "sync_current",
        "ops_projection_from_owned_mirror",
        "coverage_transition_from_owned_mirror",
        "profile_plan_closure_ready",
    ]
    assert all(item[2] == os.geteuid() + 1000 for item in calls)
    assert [item[3] for item in calls] == [905.0, 5.0, 5.0, 905.0]


def test_client_identity_and_result_shape_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_uid = os.geteuid()
    _activate_declared_test_identities(monkeypatch)
    monkeypatch.setattr(
        clients,
        "call_unix_authority",
        lambda *_args, **_kwargs: {"status": "SIGNED", "unsigned": True},
    )
    ops = clients.OpsSchedulerAuthorityClient(environment="production")
    with pytest.raises(clients.LocalAuthorityError, match="non-closed"):
        ops.render_current_projection(event_id="cron/1")
    with pytest.raises(clients.LocalAuthorityError, match="event id"):
        ops.render_current_projection(event_id="caller supplied spaces")

    monkeypatch.setattr(clients.os, "geteuid", lambda: original_uid + 2)
    with pytest.raises(clients.LocalAuthorityError, match="declared isolated"):
        clients.ReadyPublisherAuthorityClient(environment="production")


def test_ready_client_reverifies_scoped_signature_and_resource_digest(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    private = Ed25519PrivateKey.generate()
    environment = "production"
    instance = clients.ready_authority_instance_id(environment)
    snapshot_id = "sha256:" + "1" * 64
    immutable_db_digest = "sha256:" + "2" * 64
    manifest_digest = "sha256:" + "3" * 64
    projection = b'{"signed":"projection"}'
    projection_digest = "sha256:" + hashlib.sha256(projection).hexdigest()
    resource_digest = clients.derive_ready_authority_resource_digest(
        environment=environment,
        snapshot_id=snapshot_id,
        immutable_db_digest=immutable_db_digest,
        ready_manifest_digest=manifest_digest,
        signed_projection_document_digest=projection_digest,
    )
    key_id = "ready-production-v1"
    body = {
        "format": "verified-readiness-attestation/v1",
        "environment": environment,
        "authority_instance_id": instance,
        "authority_resource_digest": resource_digest,
        "snapshot_id": snapshot_id,
        "attestation_id": "sha256:" + "4" * 64,
        "ready_manifest_digest": manifest_digest,
        "immutable_db_digest": immutable_db_digest,
        "key_id": key_id,
    }
    body["signature"] = "ed25519:" + base64.b64encode(
        private.sign(clients.canonical_json_bytes(body))
    ).decode("ascii")
    raw = clients.canonical_json_bytes(body)
    result = {
        "status": "SIGNED",
        "snapshot_id": snapshot_id,
        "environment": environment,
        "authority_instance_id": instance,
        "authority_resource_digest": resource_digest,
        "attestation_id": body["attestation_id"],
        "attestation_base64": base64.b64encode(raw).decode("ascii"),
        "attestation_digest": "sha256:" + hashlib.sha256(raw).hexdigest(),
        "ready_manifest_digest": manifest_digest,
        "immutable_db_digest": immutable_db_digest,
        "signed_projection_document_digest": projection_digest,
        "issuer_key_id": key_id,
    }
    monkeypatch.setattr(
        clients,
        "load_scoped_ready_public_keys",
        lambda *, expected_environment: {
            (expected_environment, instance, key_id): private.public_key()
        },
    )
    clients._verify_ready_authority_result(
        result,
        expected_environment=environment,
        expected_snapshot_id=snapshot_id,
        signed_projection_document=projection,
    )
    spliced = json.loads(json.dumps(result))
    spliced["environment"] = "staging"
    with pytest.raises(clients.LocalAuthorityError, match="trust-domain"):
        clients._verify_ready_authority_result(
            spliced,
            expected_environment=environment,
            expected_snapshot_id=snapshot_id,
            signed_projection_document=projection,
        )


def test_ready_preflight_requires_one_active_key_and_exact_socket(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _activate_declared_test_identities(monkeypatch)
    ready = clients.ReadyPublisherAuthorityClient(environment="production")
    server_uid = ready._client.server_uid
    endpoint = SimpleNamespace(
        st_mode=stat.S_IFSOCK | 0o660,
        st_uid=server_uid,
    )
    socket_path = SimpleNamespace(lstat=lambda: endpoint)
    object.__setattr__(ready._client, "socket_path", socket_path)
    private = Ed25519PrivateKey.generate()
    key_id = "ready-production-v1"
    instance = clients.ready_authority_instance_id("production")
    monkeypatch.setattr(
        clients,
        "load_scoped_ready_public_keys",
        lambda *, expected_environment: {
            (expected_environment, instance, key_id): private.public_key()
        },
    )

    assert ready.require_available() == key_id

    endpoint.st_uid = server_uid + 1
    with pytest.raises(clients.LocalAuthorityError, match="socket identity"):
        ready.require_available()
    endpoint.st_uid = server_uid
    monkeypatch.setattr(
        clients,
        "load_scoped_ready_public_keys",
        lambda *, expected_environment: {},
    )
    with pytest.raises(clients.LocalAuthorityPending, match="no exact active"):
        ready.require_available()
