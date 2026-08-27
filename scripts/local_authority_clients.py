#!/usr/bin/env python3
"""Closed production clients for the scheduler/publisher authority identities.

These adapters never accept a caller name, target authority, socket, server
UID, operation, or purpose from product data.  Those capabilities are derived
from the code-pinned principal manifest and the process's kernel UID.  The
checked-in deployments remain inactive until the root-owned activation audit
and strict release gate permit the corresponding daemons to load.
"""

from __future__ import annotations

import base64
import os
import pwd
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any

from ops.trust_domain import require_environment

from scripts.authority_principal_manifest import load_and_validate_manifest
from scripts.local_authority_service import (
    LocalAuthorityError,
    LocalAuthorityPending,
    REQUEST_FORMAT,
    call_unix_authority,
    sha256_digest,
)

_EVENT_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,255}\Z")


def _exact_result(
    result: Mapping[str, Any], *, fields: set[str], status: str
) -> Mapping[str, Any]:
    if type(result) not in {dict, MappingProxyType} or set(result) != fields:
        raise LocalAuthorityError("local authority returned a non-closed result")
    if result.get("status") != status:
        raise LocalAuthorityError("local authority returned a non-positive result")
    return result


@dataclass(frozen=True, slots=True)
class _PinnedLocalAuthorityClient:
    environment: str
    caller: str
    authority_id: str
    socket_path: Path
    server_uid: int

    @classmethod
    def bind(
        cls, *, environment: str, caller: str, authority_id: str
    ) -> _PinnedLocalAuthorityClient:
        selected = require_environment(environment)
        manifest = load_and_validate_manifest()
        try:
            caller_deployment = manifest["local_peer_identities"][caller][
                "deployments"
            ][selected]
            principal = manifest["principals"][authority_id]
            target_deployment = principal["deployments"][selected]
        except (KeyError, TypeError) as exc:
            raise LocalAuthorityError(
                "local authority client identity is not declared"
            ) from exc
        grants = [
            row
            for row in principal["method_acl"]
            if row["authenticated_caller"] == caller
            and selected in row["environments"]
            and row["authentication"] == "local_peer_credentials"
        ]
        if not grants:
            raise LocalAuthorityError("local authority client has no kernel-peer ACL")
        try:
            caller_account = pwd.getpwnam(caller_deployment["service_user"])
            target_account = pwd.getpwnam(target_deployment["service_user"])
        except KeyError as exc:
            raise LocalAuthorityPending(
                "local authority scheduler/publisher identity is not provisioned"
            ) from exc
        if (
            caller_account.pw_uid == 0
            or target_account.pw_uid in {0, caller_account.pw_uid}
            or caller_account.pw_dir != "/var/empty"
            or caller_account.pw_shell != "/usr/bin/false"
            or os.geteuid() != caller_account.pw_uid
        ):
            raise LocalAuthorityError(
                "process is not the declared isolated scheduler/publisher UID"
            )
        socket_path = Path(target_deployment["socket_path"])
        if not socket_path.is_absolute():
            raise LocalAuthorityError("declared local authority socket is not absolute")
        return cls(
            environment=selected,
            caller=caller,
            authority_id=authority_id,
            socket_path=socket_path,
            server_uid=target_account.pw_uid,
        )

    def call(
        self,
        *,
        event_id: str,
        operation: str,
        purpose: str,
        payload: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        if type(event_id) is not str or _EVENT_ID_RE.fullmatch(event_id) is None:
            raise LocalAuthorityError("scheduler/publisher event id is invalid")
        manifest = load_and_validate_manifest()
        grants = [
            row
            for row in manifest["principals"][self.authority_id]["method_acl"]
            if row["authenticated_caller"] == self.caller
            and row["target_operation"] == operation
            and row["purpose"] == purpose
            and self.environment in row["environments"]
            and row["authentication"] == "local_peer_credentials"
        ]
        if len(grants) != 1:
            raise LocalAuthorityError("client operation is not one exact manifest grant")
        request_id = sha256_digest(
            {
                "format": "local-authority-client-event/v1",
                "environment": self.environment,
                "caller": self.caller,
                "authority_id": self.authority_id,
                "event_id": event_id,
                "operation": operation,
                "purpose": purpose,
                "payload": dict(payload),
            }
        )
        request = {
            "format": REQUEST_FORMAT,
            "request_id": request_id,
            "operation": operation,
            "purpose": purpose,
            "payload": dict(payload),
        }
        return call_unix_authority(
            self.socket_path,
            request,
            expected_server_uid=self.server_uid,
        )


class OpsSchedulerAuthorityClient:
    """Only the dedicated Ops scheduler can sync and render signed Ops state."""

    def __init__(self, *, environment: str) -> None:
        self._client = _PinnedLocalAuthorityClient.bind(
            environment=environment,
            caller="ops_scheduler",
            authority_id="d1_sync",
        )

    def sync_now(
        self, *, event_id: str, expected_applied_cursor: int
    ) -> Mapping[str, Any]:
        if (
            type(expected_applied_cursor) is not int
            or expected_applied_cursor < 0
        ):
            raise LocalAuthorityError("expected applied cursor is invalid")
        result = self._client.call(
            event_id=event_id,
            operation="d1_sync:sync_now",
            purpose="sync_current",
            payload={"expected_applied_cursor": expected_applied_cursor},
        )
        return _exact_result(
            result,
            fields={
                "status",
                "prior_applied_cursor",
                "source_change_seq",
                "applied_change_seq",
                "audit_digest",
                "export_digest",
                "issuer_key_id",
                "seen",
                "registered",
                "skipped",
            },
            status="SYNCED",
        )

    def render_current_projection(self, *, event_id: str) -> Mapping[str, Any]:
        result = self._client.call(
            event_id=event_id,
            operation="d1_sync:freeze_and_render_ops_projection",
            purpose="ops_projection_from_owned_mirror",
            payload={},
        )
        return _exact_result(
            result,
            fields={
                "status",
                "signed_artifact",
                "signed_store_digest",
                "signed_document_base64",
                "signed_document_digest",
                "issuer_key_id",
            },
            status="SIGNED",
        )


class CoverageSchedulerAuthorityClient:
    """Only the dedicated Coverage scheduler can request signed CAS apply."""

    def __init__(self, *, environment: str) -> None:
        self._client = _PinnedLocalAuthorityClient.bind(
            environment=environment,
            caller="coverage_scheduler",
            authority_id="d1_sync",
        )

    def authorize_and_apply(
        self,
        *,
        event_id: str,
        build_id: str,
        datasets: Sequence[str],
    ) -> Mapping[str, Any]:
        if type(datasets) not in {list, tuple}:
            raise LocalAuthorityError("Coverage scheduler selector is invalid")
        selected = list(datasets)
        if (
            type(build_id) is not str
            or not build_id
            or not selected
            or any(type(item) is not str or not item for item in selected)
            or selected != sorted(set(selected))
        ):
            raise LocalAuthorityError("Coverage scheduler selector is invalid")
        result = self._client.call(
            event_id=event_id,
            operation="d1_sync:freeze_authorize_apply_coverage",
            purpose="coverage_transition_from_owned_mirror",
            payload={"build_id": build_id, "datasets": selected},
        )
        return _exact_result(
            result,
            fields={
                "status",
                "transition_id",
                "build_id",
                "publication_cutoff",
                "dataset_set_digest",
                "signed_transition_digest",
                "issuer_key_id",
            },
            status="COMPLETE",
        )


class ReadyPublisherAuthorityClient:
    """Only the dedicated READY publisher can request profile-bound signing."""

    def __init__(self, *, environment: str) -> None:
        self._client = _PinnedLocalAuthorityClient.bind(
            environment=environment,
            caller="ready_publisher",
            authority_id="ready",
        )

    def publish_profile_plan_bound(
        self,
        *,
        event_id: str,
        snapshot_id: str,
        signed_projection_document: bytes,
    ) -> Mapping[str, Any]:
        if (
            type(snapshot_id) is not str
            or not snapshot_id.startswith("sha256:")
            or type(signed_projection_document) is not bytes
            or not signed_projection_document
        ):
            raise LocalAuthorityError("READY publication input is invalid")
        result = self._client.call(
            event_id=event_id,
            operation="ready:publish_profile_plan_bound",
            purpose="profile_plan_closure_ready",
            payload={
                "snapshot_id": snapshot_id,
                "signed_projection_base64": base64.b64encode(
                    signed_projection_document
                ).decode("ascii"),
            },
        )
        return _exact_result(
            result,
            fields={
                "status",
                "snapshot_id",
                "environment",
                "authority_instance_id",
                "authority_resource_digest",
                "attestation_id",
                "attestation_base64",
                "attestation_digest",
                "ready_manifest_digest",
                "immutable_db_digest",
                "signed_projection_document_digest",
                "issuer_key_id",
            },
            status="SIGNED",
        )


__all__ = [
    "CoverageSchedulerAuthorityClient",
    "OpsSchedulerAuthorityClient",
    "ReadyPublisherAuthorityClient",
]
