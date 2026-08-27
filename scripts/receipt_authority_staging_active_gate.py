#!/usr/bin/env python3
"""Narrow fail-closed validator for a Receipt staging ACTIVE transition.

The public validator owns fixed signed-attestation and staging-registry paths
and remeasures live evidence through GET-only isolated Cloudflare clients. It
cannot invoke a positive RPC, accept caller-supplied evidence documents, accept
a Receipt/Coverage claim, inject a verifier, or select another trust root.
"""

from __future__ import annotations

import base64
import copy
import hashlib
import json
import re
import subprocess
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, NoReturn
from urllib.request import urlopen

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from scripts import receipt_authority_pending_live_acceptance as live
from scripts.cloudflare_binding_manifest import build_manifest
from scripts.finding_ledger_gate import load_pinned_finding_ledger
from scripts.receipt_authority_pending_gate import (
    AUTHORITY_INSTANCES_PATH,
    SCOPED_REGISTRY_PATHS,
    _canonical_digest,
)
from storage.receipt_crypto import ReceiptVerifyKey


class ReceiptStagingActiveGateError(RuntimeError):
    """The staged ACTIVE transition is not exact or fully evidenced."""


ROOT = Path(__file__).resolve().parents[1]
STAGING_AUDIT_ATTESTATION_PATH = (
    ROOT
    / "data"
    / "ops"
    / "receipt_authority"
    / "staging_audit_recovery_attestation.json"
)


_REGISTRY_FIELDS = {
    "schema_version",
    "purpose",
    "generation",
    "authority_status",
    "environment",
    "authority_instance_digest",
    "prior_registry_digest",
    "keys",
    "registry_digest",
}
_KEY_FIELDS = {"key_id", "algorithm", "public_key_base64", "status"}
_ATTESTATION_FIELDS = {
    "schema_version",
    "purpose",
    "eligibility",
    "environment",
    "issuer_class",
    "issuer_key_id",
    "authority_instance_digest",
    "signed_claims_base64",
    "signed_claims_digest",
    "signature",
    "issued_at",
}
_CLAIM_FIELDS = {
    "schema_version",
    "purpose",
    "eligibility",
    "environment",
    "authority_instance_digest",
    "authority_source_sha",
    "authority_worker_version_id",
    "authority_worker_version_tag",
    "caller_source_sha",
    "caller_worker_version_id",
    "caller_worker_version_tag",
    "operation_id",
    "request_nonce",
    "initial_state",
    "initial_state_digest",
    "initial_result_digest",
    "initial_created_at",
    "recovery_event",
    "recovery_event_digest",
    "recovery_event_tail_digest",
    "recovered_at",
    "first_recovery_state",
    "first_recovery_result_digest",
    "replay_event",
    "replay_event_digest",
    "replay_event_tail_digest",
    "replay_confirmed_at",
    "replayed",
    "final_state",
    "issuer_key_id",
    "issued_at",
}
_SHA256 = re.compile(r"sha256:[0-9a-f]{64}\Z")
_SOURCE_SHA = re.compile(r"[0-9a-f]{40}\Z")
_NONCE = re.compile(r"[0-9a-f]{64}\Z")
_UUID = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-"
    r"[89ab][0-9a-f]{3}-[0-9a-f]{12}\Z",
    re.IGNORECASE,
)
_CANONICAL_TIMESTAMP = re.compile(
    r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z\Z"
)


def _reject_constant(value: str) -> NoReturn:
    raise ReceiptStagingActiveGateError(
        f"Receipt ACTIVE evidence contains non-finite JSON {value!r}"
    )


def _reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ReceiptStagingActiveGateError(
                f"Receipt ACTIVE evidence duplicates key {key!r}"
            )
        result[key] = value
    return result


def _canonical_bytes(value: Any) -> bytes:
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ReceiptStagingActiveGateError(
            "Receipt ACTIVE evidence is not canonical JSON"
        ) from exc


def _digest_bytes(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def _read_object_once(
    path: Path,
    *,
    label: str,
    require_canonical_file: bool = False,
) -> tuple[bytes, dict[str, Any]]:
    if not isinstance(path, Path):
        raise ReceiptStagingActiveGateError(f"{label} path must be a Path")
    try:
        raw = path.read_bytes()
        value = json.loads(
            raw,
            object_pairs_hook=_reject_duplicates,
            parse_constant=_reject_constant,
        )
    except ReceiptStagingActiveGateError:
        raise
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ReceiptStagingActiveGateError(f"{label} is unreadable") from exc
    if type(value) is not dict:
        raise ReceiptStagingActiveGateError(f"{label} must be an object")
    if require_canonical_file and raw != _canonical_bytes(value):
        raise ReceiptStagingActiveGateError(f"{label} file is not canonical")
    return raw, value


def _canonical_base64(value: Any, *, length: int | None = None) -> bytes | None:
    if type(value) is not str:
        return None
    try:
        raw = base64.b64decode(value, validate=True)
    except (TypeError, ValueError):
        return None
    if base64.b64encode(raw).decode("ascii") != value:
        return None
    if length is not None and len(raw) != length:
        return None
    return raw


def _canonical_time(value: Any, *, label: str) -> datetime:
    if type(value) is not str or _CANONICAL_TIMESTAMP.fullmatch(value) is None:
        raise ReceiptStagingActiveGateError(f"{label} is not canonical UTC")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ReceiptStagingActiveGateError(f"{label} is not canonical UTC") from exc
    if parsed.tzinfo is None or parsed.astimezone(UTC).isoformat(
        timespec="milliseconds"
    ).replace("+00:00", "Z") != value:
        raise ReceiptStagingActiveGateError(f"{label} is not canonical UTC")
    return parsed


def _load_active_registry(
    path: Path,
) -> tuple[dict[str, Any], str, ReceiptVerifyKey]:
    _raw, registry = _read_object_once(path, label="staging Receipt ACTIVE registry")
    keys = registry.get("keys")
    if (
        set(registry) != _REGISTRY_FIELDS
        or registry.get("schema_version") != 3
        or registry.get("purpose") != "receipt_verification"
        or type(registry.get("generation")) is not int
        or registry["generation"] < 1
        or registry.get("authority_status") != "ACTIVE"
        or registry.get("environment") != "staging"
        or _SHA256.fullmatch(str(registry.get("authority_instance_digest"))) is None
        or (
            registry["generation"] == 1
            and registry.get("prior_registry_digest") is not None
        )
        or (
            registry["generation"] > 1
            and _SHA256.fullmatch(str(registry.get("prior_registry_digest"))) is None
        )
        or type(keys) is not list
        or not keys
        or len(keys) > 16
        or any(type(row) is not dict or set(row) != _KEY_FIELDS for row in keys)
    ):
        raise ReceiptStagingActiveGateError("staging ACTIVE registry is not closed")
    body = dict(registry)
    observed_digest = body.pop("registry_digest", None)
    if observed_digest != _canonical_digest(body):
        raise ReceiptStagingActiveGateError("staging ACTIVE registry digest drifted")

    active: list[tuple[str, bytes]] = []
    seen: set[str] = set()
    for row in keys:
        public_key = _canonical_base64(row.get("public_key_base64"), length=32)
        expected_key_id = None if public_key is None else (
            "receipt-staging-" + hashlib.sha256(public_key).hexdigest()[:16]
        )
        if (
            row.get("algorithm") != "Ed25519"
            or row.get("status") not in {"active", "revoked"}
            or type(row.get("key_id")) is not str
            or row["key_id"] in seen
            or row.get("key_id") != expected_key_id
        ):
            raise ReceiptStagingActiveGateError(
                "staging ACTIVE registry key identity drifted"
            )
        seen.add(row["key_id"])
        if row["status"] == "active":
            active.append((row["key_id"], public_key))
    if len(active) != 1:
        raise ReceiptStagingActiveGateError(
            "staging registry is not an exact one-key ACTIVE registry"
        )
    key_id, public_key = active[0]
    try:
        verifier = ReceiptVerifyKey(
            key_id=key_id,
            public_key=Ed25519PublicKey.from_public_bytes(public_key),
        )
    except ValueError as exc:
        raise ReceiptStagingActiveGateError(
            "staging ACTIVE Ed25519 key is invalid"
        ) from exc
    return registry, key_id, verifier


def _active_surfaces(
    active_key_id: str,
    active_registry_digest: str,
) -> dict[str, dict[str, Any]]:
    manifest = build_manifest()
    surfaces = {
        role: copy.deepcopy(manifest["workers"][worker]["staging"])
        for role, worker in live.CHAIN
    }
    surfaces["authority"]["vars"] = {
        **surfaces["authority"]["vars"],
        "AUTHORITY_MODE": "ACTIVE",
        "ACTIVATED_KEY_ID": active_key_id,
        "AUTHORITY_REGISTRY_DIGEST": active_registry_digest,
    }
    surfaces["caller"]["vars"] = {
        **surfaces["caller"]["vars"],
        "RECEIPT_AUTHORITY_OPERATION_MODE": "ACTIVE",
        "RECEIPT_AUTHORITY_ACTIVE_KEY_ID": active_key_id,
        "RECEIPT_AUTHORITY_REGISTRY_DIGEST": active_registry_digest,
    }
    return surfaces


def _validate_source_provenance(value: Any, *, role: str) -> dict[str, Any]:
    if type(value) is not dict or set(value) != {
        "live_main_module",
        "live_main_module_bytes",
        "live_main_module_digest",
        "local_main_module",
        "local_main_module_bytes",
        "local_main_module_digest",
    }:
        raise ReceiptStagingActiveGateError(f"{role} module evidence is not closed")
    local_digest = value["local_main_module_digest"]
    live_digest = value["live_main_module_digest"]
    if (
        type(local_digest) is not str
        or type(live_digest) is not str
        or local_digest != live_digest
        or _SHA256.fullmatch(local_digest) is None
        or type(value["local_main_module_bytes"]) is not int
        or value["local_main_module_bytes"] <= 0
        or value["live_main_module_bytes"] != value["local_main_module_bytes"]
        or value["local_main_module"] != "index.js"
        or not str(value["live_main_module"]).endswith("index.js")
    ):
        raise ReceiptStagingActiveGateError(
            f"{role} live module differs from reviewed source bytes"
        )
    return dict(value)


def _authority_instance_digest() -> str:
    _raw, inventory = _read_object_once(
        AUTHORITY_INSTANCES_PATH,
        label="Receipt authority instance inventory",
    )
    if (
        set(inventory) != {"schema_version", "instances"}
        or inventory.get("schema_version") != "receipt-authority-instances/v1"
        or type(inventory.get("instances")) is not dict
        or set(inventory["instances"]) != {"production", "staging"}
    ):
        raise ReceiptStagingActiveGateError(
            "Receipt authority instance inventory is not closed"
        )
    instance = inventory["instances"].get("staging")
    if type(instance) is not dict or instance.get("environment") != "staging":
        raise ReceiptStagingActiveGateError("staging authority scope is invalid")
    return _canonical_digest(instance)


def _verify_audit_attestation(
    attestation: dict[str, Any],
    *,
    verify_key: ReceiptVerifyKey,
    reviewed_sha: str,
    instance_digest: str,
    accepted: Mapping[str, Mapping[str, Any]],
) -> tuple[dict[str, Any], str]:
    signed_claims = _canonical_base64(attestation.get("signed_claims_base64"))
    signature = attestation.get("signature")
    if (
        set(attestation) != _ATTESTATION_FIELDS
        or attestation.get("schema_version")
        != "receipt-audit-recovery-attestation/v1"
        or attestation.get("purpose") != "receipt_authority_recovery_canary"
        or attestation.get("eligibility") != "AUDIT_ONLY"
        or attestation.get("environment") != "staging"
        or attestation.get("issuer_class")
        != "ReceiptEvidenceAuthorityAuditSigner"
        or type(attestation.get("issuer_key_id")) is not str
        or re.fullmatch(
            r"receipt-staging-[0-9a-f]{16}",
            attestation["issuer_key_id"],
        ) is None
        or attestation.get("authority_instance_digest") != instance_digest
        or signed_claims is None
        or _SHA256.fullmatch(str(attestation.get("signed_claims_digest"))) is None
        or type(signature) is not str
        or _canonical_base64(signature.removeprefix("ed25519:"), length=64) is None
        or not signature.startswith("ed25519:")
    ):
        raise ReceiptStagingActiveGateError(
            "Receipt audit recovery attestation is invalid"
        )
    if attestation["issuer_key_id"] != verify_key.key_id:
        raise ReceiptStagingActiveGateError(
            "immutable caller/authority version/key pair drifted"
        )
    issued_at = _canonical_time(attestation.get("issued_at"), label="issued_at")
    try:
        claims = json.loads(
            signed_claims,
            object_pairs_hook=_reject_duplicates,
            parse_constant=_reject_constant,
        )
    except ReceiptStagingActiveGateError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ReceiptStagingActiveGateError(
            "Receipt audit recovery signed claims are unreadable"
        ) from exc
    if type(claims) is not dict or set(claims) != _CLAIM_FIELDS:
        raise ReceiptStagingActiveGateError(
            "Receipt audit recovery signed claims are not closed"
        )
    if signed_claims != _canonical_bytes(claims):
        raise ReceiptStagingActiveGateError(
            "Receipt audit recovery signed claims are not canonical"
        )
    if (
        _digest_bytes(signed_claims) != attestation["signed_claims_digest"]
        or not verify_key.verify(signed_claims, signature)
    ):
        raise ReceiptStagingActiveGateError(
            "Receipt audit recovery signature is invalid"
        )

    authority = accepted["authority"]
    caller = accepted["caller"]
    expected_pair = {
        "authority_source_sha": reviewed_sha,
        "authority_worker_version_id": authority["deployment_version_id"],
        "authority_worker_version_tag": live.version_tag(
            "authority", "staging", reviewed_sha, "ACTIVE"
        ),
        "caller_source_sha": reviewed_sha,
        "caller_worker_version_id": caller["deployment_version_id"],
        "caller_worker_version_tag": live.version_tag(
            "caller", "staging", reviewed_sha, "ACTIVE"
        ),
        "issuer_key_id": verify_key.key_id,
    }
    observed_pair = {name: claims.get(name) for name in expected_pair}
    if observed_pair != expected_pair:
        raise ReceiptStagingActiveGateError(
            "immutable caller/authority version/key pair drifted"
        )
    if (
        claims.get("schema_version")
        != "receipt-audit-recovery-attestation-claims/v1"
        or claims.get("purpose") != "receipt_authority_recovery_canary"
        or claims.get("eligibility") != "AUDIT_ONLY"
        or claims.get("environment") != "staging"
        or claims.get("authority_instance_digest") != instance_digest
        or claims.get("authority_source_sha") != reviewed_sha
        or claims.get("authority_worker_version_id")
        != authority["deployment_version_id"]
        or claims.get("authority_worker_version_tag")
        != live.version_tag("authority", "staging", reviewed_sha, "ACTIVE")
        or claims.get("caller_source_sha") != reviewed_sha
        or claims.get("caller_worker_version_id") != caller["deployment_version_id"]
        or claims.get("caller_worker_version_tag")
        != live.version_tag("caller", "staging", reviewed_sha, "ACTIVE")
        or _SOURCE_SHA.fullmatch(str(claims.get("authority_source_sha"))) is None
        or _SOURCE_SHA.fullmatch(str(claims.get("caller_source_sha"))) is None
        or _UUID.fullmatch(str(claims.get("authority_worker_version_id"))) is None
        or _UUID.fullmatch(str(claims.get("caller_worker_version_id"))) is None
        or _SHA256.fullmatch(str(claims.get("operation_id"))) is None
        or _NONCE.fullmatch(str(claims.get("request_nonce"))) is None
        or claims.get("initial_state") != "RECOVERY_REQUIRED"
        or _SHA256.fullmatch(str(claims.get("initial_state_digest"))) is None
        or _SHA256.fullmatch(str(claims.get("initial_result_digest"))) is None
        or claims.get("recovery_event") != "RECOVERY_COMPLETED"
        or _SHA256.fullmatch(str(claims.get("recovery_event_digest"))) is None
        or _SHA256.fullmatch(str(claims.get("recovery_event_tail_digest"))) is None
        or claims.get("first_recovery_state") != "RECOVERED_PENDING_REPLAY"
        or _SHA256.fullmatch(
            str(claims.get("first_recovery_result_digest"))
        ) is None
        or claims.get("replay_event") != "REPLAY_CONFIRMED"
        or _SHA256.fullmatch(str(claims.get("replay_event_digest"))) is None
        or _SHA256.fullmatch(str(claims.get("replay_event_tail_digest"))) is None
        or claims.get("replayed") is not True
        or claims.get("final_state") != "AUDIT_FINALIZED"
        or claims.get("issuer_key_id") != verify_key.key_id
        or claims.get("issued_at") != attestation["issued_at"]
        or claims.get("replay_confirmed_at") != attestation["issued_at"]
    ):
        raise ReceiptStagingActiveGateError(
            "Receipt audit recovery signed scope drifted"
        )
    initial_created = _canonical_time(
        claims.get("initial_created_at"), label="initial_created_at"
    )
    recovered_at = _canonical_time(claims.get("recovered_at"), label="recovered_at")
    replay_confirmed_at = _canonical_time(
        claims.get("replay_confirmed_at"), label="replay_confirmed_at"
    )
    if (
        replay_confirmed_at != issued_at
        or recovered_at < initial_created
        or replay_confirmed_at < recovered_at
    ):
        raise ReceiptStagingActiveGateError(
            "Receipt audit recovery time order drifted"
        )
    deployment_times: dict[str, datetime] = {}
    for role in ("authority", "caller"):
        deployed_at = datetime.fromisoformat(
            str(accepted[role]["deployment_created_on"]).replace("Z", "+00:00")
        )
        if deployed_at.tzinfo is None:
            raise ReceiptStagingActiveGateError(
                "Receipt ACTIVE deployment time is not timezone-aware"
            )
        deployment_times[role] = deployed_at.astimezone(UTC)
        if replay_confirmed_at <= deployment_times[role]:
            raise ReceiptStagingActiveGateError(
                "Receipt audit recovery predates ACTIVE deployment"
            )
    authority_deployed_at = deployment_times["authority"]
    caller_deployed_at = deployment_times["caller"]
    if caller_deployed_at <= authority_deployed_at:
        raise ReceiptStagingActiveGateError(
            "Premium caller deployment was not coordinated after authority deployment"
        )
    caller_version_created_at = datetime.fromisoformat(
        str(caller["version_created_on"]).replace("Z", "+00:00")
    )
    if (
        caller_version_created_at.tzinfo is None
        or caller_version_created_at.astimezone(UTC) <= authority_deployed_at
    ):
        raise ReceiptStagingActiveGateError(
            "Premium caller version was not uploaded after authority deployment"
        )

    operation_id = _canonical_digest({
        "schema_version": "receipt-audit-recovery-canary-identity/v1",
        "purpose": "receipt_authority_recovery_canary",
        "eligibility": "AUDIT_ONLY",
        "environment": "staging",
        "caller_source_sha": claims["caller_source_sha"],
        "caller_worker_version_id": claims["caller_worker_version_id"],
        "caller_worker_version_tag": claims["caller_worker_version_tag"],
        "request_nonce": claims["request_nonce"],
    })
    initial_state_digest = _canonical_digest({
        "schema_version": "receipt-audit-recovery-initial-state/v1",
        "purpose": "receipt_authority_recovery_canary",
        "eligibility": "AUDIT_ONLY",
        "environment": "staging",
        "operation_id": operation_id,
        "request_digest": operation_id,
        "state": "RECOVERY_REQUIRED",
        "created_at": claims["initial_created_at"],
    })
    initial_result_digest = _canonical_digest({
        "schema_version": "receipt-audit-recovery-initial-result/v1",
        "purpose": "receipt_authority_recovery_canary",
        "eligibility": "AUDIT_ONLY",
        "environment": "staging",
        "operation_id": operation_id,
        "request_nonce": claims["request_nonce"],
        "state": "RECOVERY_REQUIRED",
        "initial_state_digest": initial_state_digest,
        "created_at": claims["initial_created_at"],
    })
    initial_event_digest = _canonical_digest({
        "schema_version": "receipt-audit-recovery-event-link/v1",
        "purpose": "receipt_authority_recovery_canary",
        "eligibility": "AUDIT_ONLY",
        "environment": "staging",
        "operation_id": operation_id,
        "event": "INITIAL_COMMITTED",
        "payload_digest": initial_state_digest,
        "prior_event_digest": None,
        "observed_at": claims["initial_created_at"],
    })
    recovery_event_digest = _canonical_digest({
        "schema_version": "receipt-audit-recovery-event/v1",
        "purpose": "receipt_authority_recovery_canary",
        "eligibility": "AUDIT_ONLY",
        "environment": "staging",
        "operation_id": operation_id,
        "request_nonce": claims["request_nonce"],
        "event": "RECOVERY_COMPLETED",
        "from_state": "RECOVERY_REQUIRED",
        "to_state": "RECOVERED_PENDING_REPLAY",
        "initial_state_digest": initial_state_digest,
        "initial_result_digest": initial_result_digest,
        "recovered_at": claims["recovered_at"],
    })
    recovery_event_tail_digest = _canonical_digest({
        "schema_version": "receipt-audit-recovery-event-link/v1",
        "purpose": "receipt_authority_recovery_canary",
        "eligibility": "AUDIT_ONLY",
        "environment": "staging",
        "operation_id": operation_id,
        "event": "RECOVERY_COMPLETED",
        "payload_digest": recovery_event_digest,
        "prior_event_digest": initial_event_digest,
        "observed_at": claims["recovered_at"],
    })
    first_recovery_result_digest = _canonical_digest({
        "schema_version": "receipt-audit-first-recovery-result/v1",
        "purpose": "receipt_authority_recovery_canary",
        "eligibility": "AUDIT_ONLY",
        "environment": "staging",
        "operation_id": operation_id,
        "request_nonce": claims["request_nonce"],
        "initial_state_digest": initial_state_digest,
        "initial_result_digest": initial_result_digest,
        "recovery_event_digest": recovery_event_digest,
        "recovery_event_tail_digest": recovery_event_tail_digest,
        "recovered_at": claims["recovered_at"],
        "state": "RECOVERED_PENDING_REPLAY",
    })
    replay_event_digest = _canonical_digest({
        "schema_version": "receipt-audit-replay-event/v1",
        "purpose": "receipt_authority_recovery_canary",
        "eligibility": "AUDIT_ONLY",
        "environment": "staging",
        "operation_id": operation_id,
        "request_nonce": claims["request_nonce"],
        "event": "REPLAY_CONFIRMED",
        "from_state": "RECOVERED_PENDING_REPLAY",
        "to_state": "AUDIT_FINALIZED",
        "first_recovery_result_digest": first_recovery_result_digest,
        "recovery_event_digest": recovery_event_digest,
        "recovery_event_tail_digest": recovery_event_tail_digest,
        "replay_confirmed_at": claims["replay_confirmed_at"],
    })
    replay_event_tail_digest = _canonical_digest({
        "schema_version": "receipt-audit-recovery-event-link/v1",
        "purpose": "receipt_authority_recovery_canary",
        "eligibility": "AUDIT_ONLY",
        "environment": "staging",
        "operation_id": operation_id,
        "event": "REPLAY_CONFIRMED",
        "payload_digest": replay_event_digest,
        "prior_event_digest": recovery_event_tail_digest,
        "observed_at": claims["replay_confirmed_at"],
    })
    if (
        claims["operation_id"] != operation_id
        or claims["initial_state_digest"] != initial_state_digest
        or claims["initial_result_digest"] != initial_result_digest
        or claims["recovery_event_digest"] != recovery_event_digest
        or claims["recovery_event_tail_digest"] != recovery_event_tail_digest
        or claims["first_recovery_result_digest"]
        != first_recovery_result_digest
        or claims["replay_event_digest"] != replay_event_digest
        or claims["replay_event_tail_digest"] != replay_event_tail_digest
    ):
        raise ReceiptStagingActiveGateError(
            "Receipt audit recovery digest chain drifted"
        )
    return claims, _canonical_digest(attestation)


def _validate_staging_active_transition_core(
    *,
    source_sha: str,
    account_id: str,
    deployments: Mapping[str, Any],
    versions: Mapping[str, Any],
    public_surfaces: Mapping[str, Any],
    source_provenance: Mapping[str, Any],
    deployment_bracket_after: Mapping[str, Any],
    public_bracket_after: Mapping[str, Any],
    recovery_attestation_path: Path,
    registry_path: Path,
) -> dict[str, Any]:
    reviewed_sha = live._source_sha(source_sha)
    if live._ACCOUNT_ID.fullmatch(account_id) is None:
        raise ReceiptStagingActiveGateError("Cloudflare account id is invalid")
    registry, active_key_id, verify_key = _load_active_registry(registry_path)
    instance_digest = _authority_instance_digest()
    if registry.get("authority_instance_digest") != instance_digest:
        raise ReceiptStagingActiveGateError("ACTIVE registry authority scope drifted")
    surfaces = _active_surfaces(active_key_id, registry["registry_digest"])
    roles = {role for role, _worker in live.CHAIN}
    if any(
        set(document) != roles
        for document in (
            deployments,
            versions,
            public_surfaces,
            source_provenance,
            deployment_bracket_after,
            public_bracket_after,
        )
    ):
        raise ReceiptStagingActiveGateError("ACTIVE chain evidence roles are not closed")

    accepted: dict[str, Any] = {}
    for role, _worker in live.CHAIN:
        if live._canonical_digest(deployments[role]) != live._canonical_digest(
            deployment_bracket_after[role]
        ):
            raise ReceiptStagingActiveGateError(
                f"{role} deployment changed during ACTIVE transition"
            )
        if live._canonical_digest(public_surfaces[role]) != live._canonical_digest(
            public_bracket_after[role]
        ):
            raise ReceiptStagingActiveGateError(
                f"{role} public surface changed during ACTIVE transition"
            )
        deployment_id, version_id, message, deployment_created_on = (
            live._validate_deployment(
                deployments[role],
                role=role,
                environment="staging",
                source_sha=reviewed_sha,
                authority_mode="ACTIVE",
            )
        )
        row = live._validate_version(
            versions[role],
            role=role,
            environment="staging",
            source_sha=reviewed_sha,
            version_id=version_id,
            surface=surfaces[role],
            authority_mode="ACTIVE",
        )
        row["deployment_id"] = deployment_id
        row["deployment_created_on"] = deployment_created_on
        row["deployment_message"] = message
        row["source_provenance"] = _validate_source_provenance(
            source_provenance[role], role=role
        )
        row["public_surface"] = live._validate_public_surface(
            public_surfaces[role], role=role, surface=surfaces[role]
        )
        accepted[role] = row

    _raw, attestation = _read_object_once(
        recovery_attestation_path,
        label="Receipt audit recovery attestation",
        require_canonical_file=True,
    )
    claims, attestation_digest = _verify_audit_attestation(
        attestation,
        verify_key=verify_key,
        reviewed_sha=reviewed_sha,
        instance_digest=instance_digest,
        accepted=accepted,
    )
    ledger = load_pinned_finding_ledger()
    deployment_pair_digest = _canonical_digest({
        "schema_version": "receipt-audit-deployment-pair/v2",
        "environment": "staging",
        "authority_deployment_id": accepted["authority"]["deployment_id"],
        "authority_worker_version_id": accepted["authority"][
            "deployment_version_id"
        ],
        "caller_deployment_id": accepted["caller"]["deployment_id"],
        "caller_worker_version_id": accepted["caller"]["deployment_version_id"],
        "active_key_id": active_key_id,
        "registry_digest": registry["registry_digest"],
    })
    return {
        "format": "receipt-authority-staging-active-transition/v2",
        "environment": "staging",
        "source_sha": reviewed_sha,
        "account_id": account_id,
        "authority_mode": "ACTIVE",
        "active_key_id": active_key_id,
        "active_key_count": 1,
        "authority_instance_digest": instance_digest,
        "registry_digest": registry["registry_digest"],
        "deployment_pair_digest": deployment_pair_digest,
        "workers": accepted,
        "audit_recovery_operation_id": claims["operation_id"],
        "signed_attestation_digest": attestation_digest,
        "signed_claims_digest": attestation["signed_claims_digest"],
        "finding_ledger_digest": ledger.digest,
        "open_p0_ids": list(ledger.open_p0_ids),
        "strict_release_gate_applied": False,
        "positive_operation_invoked_by_gate": False,
        "eligibility": "AUDIT_ONLY",
        "research_eligible": False,
        "authorization_scope": "STAGING_RECEIPT_ACTIVE_TRANSITION_ONLY",
    }


def _collect_staging_active_documents(
    *,
    source_sha: str,
    account_id: str,
    api_token: str,
) -> dict[str, dict[str, Any]]:
    """Collect one GET-only whole-chain bracket in isolated Wrangler homes."""

    reviewed_sha = live._source_sha(source_sha)
    if live._ACCOUNT_ID.fullmatch(account_id) is None or not api_token:
        raise ReceiptStagingActiveGateError(
            "exact Cloudflare account id and API token are required"
        )
    manifest = build_manifest()
    deployments: dict[str, Any] = {}
    versions: dict[str, Any] = {}
    public: dict[str, Any] = {}
    provenance: dict[str, Any] = {}
    deployment_after: dict[str, Any] = {}
    public_after: dict[str, Any] = {}

    for role, worker in live.CHAIN:
        deployments[role] = live._wrangler_json(
            worker=worker,
            environment="staging",
            arguments=("deployments", "status", "--json"),
            account_id=account_id,
            api_token=api_token,
            runner=subprocess.run,
        )
        worker_name = manifest["workers"][worker]["staging"]["name"]
        public[role] = live._live_public_surface(
            worker_name=worker_name,
            account_id=account_id,
            api_token=api_token,
            opener=urlopen,
        )

    for role, worker in live.CHAIN:
        traffic = live._sequence(
            live._mapping(
                deployments[role], label=f"{role} ACTIVE deployment"
            ).get("versions"),
            label=f"{role} ACTIVE deployment versions",
        )
        if len(traffic) != 1 or type(traffic[0]) is not dict:
            raise ReceiptStagingActiveGateError(
                f"{role} ACTIVE deployment must select one version"
            )
        version_id = traffic[0].get("version_id")
        if type(version_id) is not str or _UUID.fullmatch(version_id) is None:
            raise ReceiptStagingActiveGateError(
                f"{role} ACTIVE version id is invalid"
            )
        versions[role] = live._wrangler_json(
            worker=worker,
            environment="staging",
            arguments=("versions", "view", version_id, "--json"),
            account_id=account_id,
            api_token=api_token,
            runner=subprocess.run,
        )
        worker_name = manifest["workers"][worker]["staging"]["name"]
        provenance[role] = live._source_provenance(
            worker=worker,
            worker_name=worker_name,
            environment="staging",
            account_id=account_id,
            api_token=api_token,
            runner=subprocess.run,
        )
        deployment_during = live._wrangler_json(
            worker=worker,
            environment="staging",
            arguments=("deployments", "status", "--json"),
            account_id=account_id,
            api_token=api_token,
            runner=subprocess.run,
        )
        public_during = live._live_public_surface(
            worker_name=worker_name,
            account_id=account_id,
            api_token=api_token,
            opener=urlopen,
        )
        if live._canonical_digest(deployments[role]) != live._canonical_digest(
            deployment_during
        ):
            raise ReceiptStagingActiveGateError(
                f"{role} deployment changed during ACTIVE source measurement"
            )
        if live._canonical_digest(public[role]) != live._canonical_digest(
            public_during
        ):
            raise ReceiptStagingActiveGateError(
                f"{role} public surface changed during ACTIVE source measurement"
            )

    for role, worker in live.CHAIN:
        deployment_after[role] = live._wrangler_json(
            worker=worker,
            environment="staging",
            arguments=("deployments", "status", "--json"),
            account_id=account_id,
            api_token=api_token,
            runner=subprocess.run,
        )
        worker_name = manifest["workers"][worker]["staging"]["name"]
        public_after[role] = live._live_public_surface(
            worker_name=worker_name,
            account_id=account_id,
            api_token=api_token,
            opener=urlopen,
        )
    return {
        "deployments": deployments,
        "versions": versions,
        "public_surfaces": public,
        "source_provenance": provenance,
        "deployment_bracket_after": deployment_after,
        "public_bracket_after": public_after,
    }


def _remeasure_staging_active_tail(
    *,
    account_id: str,
    api_token: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Close the live bracket after the fixed attestation has been verified."""

    manifest = build_manifest()
    deployments: dict[str, Any] = {}
    public: dict[str, Any] = {}
    for role, worker in live.CHAIN:
        deployments[role] = live._wrangler_json(
            worker=worker,
            environment="staging",
            arguments=("deployments", "status", "--json"),
            account_id=account_id,
            api_token=api_token,
            runner=subprocess.run,
        )
        worker_name = manifest["workers"][worker]["staging"]["name"]
        public[role] = live._live_public_surface(
            worker_name=worker_name,
            account_id=account_id,
            api_token=api_token,
            opener=urlopen,
        )
    return deployments, public


def validate_staging_active_transition(
    *,
    source_sha: str,
    account_id: str,
    api_token: str,
) -> dict[str, Any]:
    """Remeasure live ACTIVE evidence against fixed local trust inputs."""

    try:
        live._require_exact_clean_source(source_sha)
        live._require_official_origin_main(source_sha)
        documents = _collect_staging_active_documents(
            source_sha=source_sha,
            account_id=account_id,
            api_token=api_token,
        )
        result = _validate_staging_active_transition_core(
            source_sha=source_sha,
            account_id=account_id,
            **documents,
            recovery_attestation_path=STAGING_AUDIT_ATTESTATION_PATH,
            registry_path=SCOPED_REGISTRY_PATHS["staging"],
        )
        tail_deployments, tail_public = _remeasure_staging_active_tail(
            account_id=account_id,
            api_token=api_token,
        )
        for role, _worker in live.CHAIN:
            if live._canonical_digest(
                documents["deployment_bracket_after"][role]
            ) != live._canonical_digest(tail_deployments[role]):
                raise ReceiptStagingActiveGateError(
                    f"{role} deployment changed after attestation verification"
                )
            if live._canonical_digest(
                documents["public_bracket_after"][role]
            ) != live._canonical_digest(tail_public[role]):
                raise ReceiptStagingActiveGateError(
                    f"{role} public surface changed after attestation verification"
                )
        live._require_exact_clean_source(source_sha)
        live._require_official_origin_main(source_sha)
        return result
    except ReceiptStagingActiveGateError:
        raise
    except (live.ReceiptPendingLiveAcceptanceError, RuntimeError, ValueError) as exc:
        raise ReceiptStagingActiveGateError(str(exc)) from exc


__all__ = [
    "ReceiptStagingActiveGateError",
    "validate_staging_active_transition",
]
