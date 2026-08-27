"""Fixed collector facade for the external local-authority high-water anchor.

Wire and lineage validation live in the contract module; the reference remote
model and transport/audit store are separate consumers. This compatibility
facade retains only the fixed collector public API.
"""

from __future__ import annotations

import os
import secrets
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from scripts.local_authority_activation import canonical_json_bytes
from scripts.local_authority_anchor_contract import (
    CONFIG_FORMAT,
    ENVIRONMENT_SET,
    AnchorDeployment,
    AnchorKeyRegistry,
    AnchorOperationalHold,
    AnchorProtocolError,
    _build_lineage_proof,
    _challenge_request,
    _commit_request,
    _exact,
    _parse_time,
    _resolution_request,
    _strict_json,
    _validate_challenge,
    _validate_challenge_request,
    _validate_commit_request,
    _validate_receipt,
    _validate_resolution_response,
    _validate_snapshot,
    _verify_lineage_proof,
    load_pinned_deployment,
    load_pinned_registry,
)

from scripts.local_authority_anchor_store import (
    AnchorReceiptAudit,
    AnchorTransport,
    PinnedHTTPSAnchorTransport,
    _reverify_abandonment,
    _reverify_audit_record,
)
from scripts.local_authority_files import (
    ProtectedAuthorityFileError,
    read_protected_authority_file,
)
from scripts.manage_local_authority_staged_canary import (
    _validate_anchor_candidate,
    anchor_lineage_snapshot,
)

def _collect_once(
    *, snapshot: Mapping[str, Any], deployment: AnchorDeployment,
    registry: AnchorKeyRegistry, client_private_key: Ed25519PrivateKey,
    transport: AnchorTransport, audit: AnchorReceiptAudit,
    now: Callable[[], datetime], nonce: Callable[[], str],
) -> Mapping[str, Any]:
    with audit.collector_lock():
        return _collect_once_under_lock(
            snapshot=snapshot,
            deployment=deployment,
            registry=registry,
            client_private_key=client_private_key,
            transport=transport,
            audit=audit,
            now=now,
            nonce=nonce,
        )


def _collect_once_under_lock(
    *, snapshot: Mapping[str, Any], deployment: AnchorDeployment,
    registry: AnchorKeyRegistry, client_private_key: Ed25519PrivateKey,
    transport: AnchorTransport, audit: AnchorReceiptAudit,
    now: Callable[[], datetime], nonce: Callable[[], str],
) -> Mapping[str, Any]:
    """Private dependency-injected collector used by the fixed public surface."""

    audit._require_collector_lock()
    snapshot_value = _validate_snapshot(snapshot)
    candidate = snapshot_value["candidate"]
    if (
        deployment.activation_status != "ACTIVE"
        or registry.authority_status != "ACTIVE"
        or deployment.remote_key_id not in registry.keys
        or deployment.client_key_id is None
    ):
        raise AnchorOperationalHold("external high-water anchor is not ACTIVE")
    client_public = client_private_key.public_key()
    try:
        records = audit.records()
    except AnchorProtocolError as exc:
        if audit.path.exists():
            raise
        audit._require_directory(create=True)
        records = []
    prior_digest: str | None = None
    previous_candidate: Mapping[str, Any] | None = None
    previous_attempts: list[dict[str, Any]] = []
    previous_runs: list[dict[str, Any]] = []
    previous_events: list[dict[str, Any]] = []
    submissions = audit.submissions()
    abandonments = {
        row["submission_record_digest"]: row for row in audit.abandonments()
    }
    accepted = {
        row["commit_request"]["commit_request_digest"]: row for row in records
    }
    pending: Mapping[str, Any] | None = None
    generation = 1
    for submission in submissions:
        record = accepted.get(
            submission["commit_request"]["commit_request_digest"]
        )
        abandonment = abandonments.get(submission["record_digest"])
        if record is not None:
            (
                receipt,
                stored_candidate,
                stored_attempts,
                stored_runs,
                stored_events,
            ) = _reverify_audit_record(
                record, registry=registry, client_public_key=client_public,
                client_key_id=deployment.client_key_id,
                expected_generation=generation,
                expected_prior_anchor_digest=prior_digest,
                previous_candidate=previous_candidate,
                previous_attempts=previous_attempts,
                previous_runs=previous_runs,
                previous_events=previous_events,
            )
            previous_candidate = stored_candidate
            previous_attempts = stored_attempts
            previous_runs = stored_runs
            previous_events = stored_events
            prior_digest = receipt["accepted_anchor_digest"]
            generation += 1
        elif abandonment is not None:
            _reverify_abandonment(
                abandonment,
                submission=submission,
                registry=registry,
                client_public_key=client_public,
                client_key_id=deployment.client_key_id,
                expected_generation=generation,
                expected_prior_anchor_digest=prior_digest,
                previous_candidate=previous_candidate,
                previous_attempts=previous_attempts,
                previous_runs=previous_runs,
                previous_events=previous_events,
            )
        else:
            pending = submission
    if pending is not None:
        request = _validate_challenge_request(
            canonical_json_bytes(pending["challenge_request"]),
            client_keys={deployment.client_key_id: client_public},
        )
        pending_candidate = _validate_anchor_candidate(
            pending["commit_request"]["anchor_candidate"]
        )
        challenge = _validate_challenge(
            canonical_json_bytes(pending["challenge"]),
            registry=registry,
            challenge_request=request,
            candidate=pending_candidate,
            expected_generation=generation,
            expected_prior_anchor_digest=prior_digest,
            now=_parse_time(pending["challenge"]["issued_at"], label="pending issued_at"),
        )
        commit_request = _validate_commit_request(
            canonical_json_bytes(pending["commit_request"]),
            client_keys={deployment.client_key_id: client_public},
        )
        if (
            commit_request["challenge_digest"] != challenge["challenge_digest"]
            or commit_request["challenge_nonce"] != challenge["nonce"]
        ):
            raise AnchorProtocolError("pending anchor submission lineage drifted")
        _verify_lineage_proof(
            commit_request["lineage_proof"],
            candidate=pending_candidate,
            previous_candidate=previous_candidate,
            previous_attempts=previous_attempts,
            previous_runs=previous_runs,
            previous_events=previous_events,
            prior_anchor_digest=prior_digest,
        )
        resolution_request = _resolution_request(
            commit_request,
            request_nonce=nonce(),
            client_key_id=deployment.client_key_id,
            client_private_key=client_private_key,
        )
        resolution_raw = transport.post(
            deployment.resolution_path,
            canonical_json_bytes(resolution_request),
        )
        resolution = _validate_resolution_response(
            resolution_raw,
            registry=registry,
            resolution_request=resolution_request,
            challenge=challenge,
            commit_request=commit_request,
            candidate=pending_candidate,
            now=now(),
        )
        if resolution["status"] == "ACCEPTED":
            receipt = resolution["receipt"]
            record = audit.append(
                challenge_request=request,
                challenge=challenge,
                commit_request=commit_request,
                receipt=receipt,
            )
            recovered, _, _, _, _ = _reverify_audit_record(
                record,
                registry=registry,
                client_public_key=client_public,
                client_key_id=deployment.client_key_id,
                expected_generation=generation,
                expected_prior_anchor_digest=prior_digest,
                previous_candidate=previous_candidate,
                previous_attempts=previous_attempts,
                previous_runs=previous_runs,
                previous_events=previous_events,
            )
            if recovered != receipt:
                raise AnchorProtocolError(
                    "recovered anchor receipt changed on audit append"
                )
            return receipt
        audit.append_abandonment(
            submission=pending,
            resolution_request=resolution_request,
            resolution_response=resolution,
        )
    lineage_proof = _build_lineage_proof(
        snapshot_value,
        previous_candidate=previous_candidate,
        previous_attempts=previous_attempts,
        previous_runs=previous_runs,
        previous_events=previous_events,
        prior_anchor_digest=prior_digest,
    )
    challenge_request = _challenge_request(
        candidate, client_key_id=deployment.client_key_id,
        client_private_key=client_private_key, request_nonce=nonce(),
    )
    challenge_raw = transport.post(
        deployment.challenge_path, canonical_json_bytes(challenge_request)
    )
    challenge = _validate_challenge(
        challenge_raw, registry=registry, challenge_request=challenge_request,
        candidate=candidate, expected_generation=generation,
        expected_prior_anchor_digest=prior_digest, now=now(),
    )
    commit_request = _commit_request(
        candidate=candidate, challenge=challenge,
        lineage_proof=lineage_proof,
        client_key_id=deployment.client_key_id,
        client_private_key=client_private_key,
    )
    audit.append_submission(
        challenge_request=challenge_request,
        challenge=challenge,
        commit_request=commit_request,
    )
    receipt_raw = transport.post(
        deployment.commit_path, canonical_json_bytes(commit_request)
    )
    receipt = _validate_receipt(
        receipt_raw, registry=registry, challenge=challenge,
        commit_request=commit_request, candidate=candidate, now=now(),
    )
    record = audit.append(
        challenge_request=challenge_request, challenge=challenge,
        commit_request=commit_request, receipt=receipt,
    )
    reread, _, _, _, _ = _reverify_audit_record(
        record, registry=registry, client_public_key=client_public,
        client_key_id=deployment.client_key_id,
        expected_generation=generation,
        expected_prior_anchor_digest=prior_digest,
        previous_candidate=previous_candidate,
        previous_attempts=previous_attempts,
        previous_runs=previous_runs,
        previous_events=previous_events,
    )
    if reread != receipt:
        raise AnchorProtocolError("anchor receipt changed after local audit append")
    return receipt


def _load_fixed_config(deployment: AnchorDeployment) -> dict[str, Any]:
    try:
        raw = read_protected_authority_file(
            deployment.root_config_path, expected_owner_uids={0},
            allowed_modes={0o400, 0o440}, max_bytes=16_384,
        ).raw
    except ProtectedAuthorityFileError as exc:
        raise AnchorOperationalHold("root-owned anchor collector config is unavailable") from exc
    value = _exact(
        _strict_json(raw, label="root-owned anchor collector config"),
        {
            "format", "deployment_digest", "endpoint", "client_key_id",
            "client_private_key_path", "remote_key_id",
        },
        label="root-owned anchor collector config",
    )
    expected = {
        "format": CONFIG_FORMAT,
        "deployment_digest": deployment.digest,
        "endpoint": deployment.endpoint,
        "client_key_id": deployment.client_key_id,
        "client_private_key_path": (
            None if deployment.client_private_key_path is None
            else str(deployment.client_private_key_path)
        ),
        "remote_key_id": deployment.remote_key_id,
    }
    if value != expected:
        raise AnchorProtocolError("root-owned anchor collector config drifted")
    return value


def _load_fixed_client_key(path: Path) -> Ed25519PrivateKey:
    try:
        protected = read_protected_authority_file(
            path, expected_owner_uids={0}, allowed_modes={0o400}, max_bytes=4096
        )
        key = serialization.load_pem_private_key(protected.raw, password=None)
    except (ProtectedAuthorityFileError, TypeError, ValueError) as exc:
        raise AnchorOperationalHold("fixed anchor client key is unavailable") from exc
    if not isinstance(key, Ed25519PrivateKey):
        raise AnchorProtocolError("fixed anchor client key type is invalid")
    return key


def anchor_plan() -> Mapping[str, Any]:
    registry = load_pinned_registry()
    deployment = load_pinned_deployment(registry)
    return {
        "format": "local-authority-high-water-anchor-plan/v1",
        "source_state": "SOURCE_READY",
        "operational_state": "HOLD",
        "activation_status": deployment.activation_status,
        "provider_selected": deployment.endpoint is not None,
        "active_remote_keys": len(registry.keys),
        "environment_set": list(ENVIRONMENT_SET),
        "caller_selectable_endpoint": False,
        "caller_selectable_key": False,
        "caller_selectable_candidate": False,
        "caller_selectable_generation": False,
        "remote_rederives_event_lineage": True,
        "remote_rederives_attempt_set": True,
        "remote_rederives_run_state_digest": True,
        "authority_signature_provenance_verified_by_anchor": False,
        "remote_key_rotation_supported": False,
        "client_key_rotation_supported": False,
        "historical_verification_keys_required": True,
        "commit_recovery": (
            "ATOMIC_ACCEPTED_OR_NOT_ACCEPTED_RESOLUTION_FROM_DURABLE_SUBMISSION"
        ),
        "transport_timeout_scope": "PER_BLOCKING_IO_NOT_TOTAL_DEADLINE",
        "research_eligible": False,
        "blockers": [
            "EXTERNAL_ANCHOR_PROVIDER_NOT_SELECTED",
            "EXTERNAL_ANCHOR_ADMIN_SEPARATION_NOT_VERIFIED",
            "EXTERNAL_ANCHOR_KEY_REGISTRY_PENDING",
            "ROOT_OWNED_COLLECTOR_CONFIG_NOT_PROVISIONED",
            "HISTORICAL_KEY_REGISTRIES_NOT_IMPLEMENTED",
        ],
    }


def collect_anchor() -> Mapping[str, Any]:
    """Collect one anchor from fixed state; currently always operational HOLD."""

    registry = load_pinned_registry()
    deployment = load_pinned_deployment(registry)
    if deployment.activation_status != "ACTIVE" or registry.authority_status != "ACTIVE":
        raise AnchorOperationalHold("external high-water anchor is operational HOLD")
    if os.geteuid() != 0:
        raise AnchorOperationalHold("external anchor collector requires human root")
    _load_fixed_config(deployment)
    assert deployment.endpoint is not None
    assert deployment.client_private_key_path is not None
    assert deployment.remote_key_id is not None
    if deployment.remote_key_id not in registry.keys:
        raise AnchorProtocolError("deployment remote key is not registry-pinned")
    client_key = _load_fixed_client_key(deployment.client_private_key_path)
    transport = PinnedHTTPSAnchorTransport(
        endpoint=deployment.endpoint,
        per_io_timeout_seconds=deployment.per_io_timeout_seconds,
        maximum_document_bytes=deployment.maximum_document_bytes,
    )
    snapshot = anchor_lineage_snapshot()
    audit = AnchorReceiptAudit(deployment.receipt_audit_path)
    return _collect_once(
        snapshot=snapshot, deployment=deployment, registry=registry,
        client_private_key=client_key, transport=transport, audit=audit,
        now=lambda: datetime.now(UTC), nonce=lambda: secrets.token_hex(32),
    )


__all__ = [
    "AnchorOperationalHold", "AnchorProtocolError", "anchor_plan", "collect_anchor"
]
