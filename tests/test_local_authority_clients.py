"""Behavioral tests for fixed-identity production authority clients."""

from __future__ import annotations

import os
from types import SimpleNamespace

import pytest

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
    calls: list[tuple[object, dict[str, object], int]] = []

    def call(path, request, *, expected_server_uid):
        calls.append((path, request, expected_server_uid))
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
                "signed_document_digest": "sha256:" + "4" * 64,
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
