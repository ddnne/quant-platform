#!/usr/bin/env python3
"""Narrow fail-closed validator for a Receipt staging ACTIVE transition.

The public validator owns fixed Access-manifest and staging-registry paths and
remeasures deployments, Access, D1, and the authenticated observer response.
It cannot invoke a positive RPC, accept caller-supplied evidence documents,
accept a Receipt/Coverage claim, inject a verifier, or select another trust
root.
"""

from __future__ import annotations

import base64
import copy
import hashlib
import json
import os
import re
import secrets
import ssl
import subprocess
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, NoReturn
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import (
    HTTPRedirectHandler,
    HTTPSHandler,
    ProxyHandler,
    Request,
    build_opener,
)

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
ACCESS_MANIFEST_PATH = (
    ROOT / "specs" / "cloudflare" / "receipt_activation_observer_access.json"
)
OUTPUT_DIR = ROOT / "data" / "ops" / "receipt_authority" / "staging_active"
ACCESS_CLIENT_ID_ENV = "RECEIPT_OBSERVER_ACCESS_CLIENT_ID"
ACCESS_CLIENT_SECRET_ENV = "RECEIPT_OBSERVER_ACCESS_CLIENT_SECRET"
OBSERVER_ROLE = ("observer", "receipt-activation-observer")
ACTIVE_CHAIN = (*live.CHAIN, OBSERVER_ROLE)
MAX_OBSERVER_RESPONSE_BYTES = 64 * 1024
RECOVERY_AUDIT_SCHEMA_DIGEST = (
    "sha256:fba0bdada764ff2dc67caa5c11b3a31b2c3c28d673a25712a853e0b0566b5259"
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
_PREMIUM_EVIDENCE_FIELDS = {
    "schema_version",
    "purpose",
    "eligibility",
    "environment",
    "caller_source_sha",
    "caller_worker_version_id",
    "caller_worker_version_tag",
    "d1_schema_digest",
    "reservation_id",
    "authority_operation_id",
    "request_nonce",
    "signed_attestation_digest",
    "signed_attestation_json_utf8_base64",
    "signed_attestation_json_utf8_length",
    "evidence_digest",
}
_OBSERVER_RESPONSE_FIELDS = {
    "schema_version",
    "purpose",
    "eligibility",
    "environment",
    "challenge",
    "observer_source_sha",
    "observer_worker_version_id",
    "observer_worker_version_tag",
    "access_authenticated",
    "access_aud",
    "premium_evidence",
    "premium_evidence_digest",
    "response_digest",
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
    surfaces["observer"] = copy.deepcopy(
        manifest["workers"]["receipt-activation-observer"]["staging"]
    )
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


def _observer_message(source_sha: str) -> str:
    return f"quant-platform receipt-activation-observer staging source {source_sha}"


def _observer_tag(source_sha: str) -> str:
    return f"rao-s-o-{source_sha}"


def _validate_observer_deployment(
    value: Any,
    *,
    source_sha: str,
) -> tuple[str, str, str, str]:
    deployment = live._mapping(value, label="observer deployment")
    annotations = live._mapping(
        deployment.get("annotations"), label="observer deployment annotations"
    )
    expected_message = _observer_message(source_sha)
    if annotations.get("workers/message") != expected_message:
        raise ReceiptStagingActiveGateError(
            "observer deployment is not bound to the reviewed source SHA"
        )
    normalized = copy.deepcopy(deployment)
    normalized["annotations"]["workers/message"] = live.deployment_message(
        "caller", "staging", source_sha, "ACTIVE"
    )
    deployment_id, version_id, _message, created_on = live._validate_deployment(
        normalized,
        role="caller",
        environment="staging",
        source_sha=source_sha,
        authority_mode="ACTIVE",
    )
    return deployment_id, version_id, expected_message, created_on


def _validate_observer_version(
    value: Any,
    *,
    source_sha: str,
    version_id: str,
    surface: Mapping[str, Any],
) -> dict[str, Any]:
    version = live._mapping(value, label="observer version")
    annotations = live._mapping(
        version.get("annotations"), label="observer version annotations"
    )
    if (
        annotations.get("workers/message") != _observer_message(source_sha)
        or annotations.get("workers/tag") != _observer_tag(source_sha)
    ):
        raise ReceiptStagingActiveGateError(
            "observer version annotations are not source-bound"
        )
    normalized = copy.deepcopy(version)
    normalized["annotations"]["workers/message"] = live.deployment_message(
        "caller", "staging", source_sha, "ACTIVE"
    )
    normalized["annotations"]["workers/tag"] = live.version_tag(
        "caller", "staging", source_sha, "ACTIVE"
    )
    accepted = live._validate_version(
        normalized,
        role="caller",
        environment="staging",
        source_sha=source_sha,
        version_id=version_id,
        surface=surface,
        authority_mode="ACTIVE",
    )
    accepted["worker_name"] = surface["name"]
    accepted["version_tag"] = _observer_tag(source_sha)
    return accepted


def _load_access_manifest(
    path: Path,
    *,
    account_id: str,
) -> dict[str, Any]:
    _raw, manifest = _read_object_once(path, label="Receipt observer Access manifest")
    expected_fields = {
        "schema_version", "status", "environment", "account_id", "worker", "endpoint",
        "application", "policy", "service_token", "forbidden",
        "cloudflare_error_9999",
    }
    if set(manifest) != expected_fields:
        raise ReceiptStagingActiveGateError("Receipt observer Access manifest is not closed")
    if manifest.get("status") != "ACTIVE":
        raise ReceiptStagingActiveGateError(
            "OPERATIONAL HOLD: Receipt observer Access is PENDING"
        )
    worker = manifest.get("worker")
    endpoint = manifest.get("endpoint")
    application = manifest.get("application")
    policy = manifest.get("policy")
    token = manifest.get("service_token")
    forbidden = manifest.get("forbidden")
    if type(worker) is not dict or set(worker) != {
        "logical_id", "script_name", "id", "scope"
    }:
        raise ReceiptStagingActiveGateError(
            "Receipt observer Access manifest is not exact Service Auth"
        )
    if (
        manifest.get("schema_version") != "receipt-activation-observer-access/v1"
        or manifest.get("environment") != "staging"
        or manifest.get("account_id") != account_id
        or worker.get("logical_id") != "receipt-activation-observer"
        or worker.get("script_name")
        != "quant-platform-receipt-activation-observer-staging"
        or worker.get("scope") != "worker"
        or re.fullmatch(r"[0-9a-f]{32}", str(worker.get("id"))) is None
        or type(endpoint) is not dict
        or set(endpoint) != {"hostname"}
        or re.fullmatch(
            r"[a-z0-9-]+(?:\.[a-z0-9-]+)*\.workers\.dev",
            str(endpoint.get("hostname")),
        ) is None
        or type(application) is not dict
        or set(application) != {
            "id", "aud", "type", "destinations", "decision", "decision_label"
        }
        or _UUID.fullmatch(str(application.get("id"))) is None
        or re.fullmatch(r"[0-9a-f]{64}", str(application.get("aud"))) is None
        or application.get("type") != "self_hosted"
        or application.get("destinations") != [{
            "type": "worker", "worker_id": worker.get("id")
        }]
        or application.get("decision") != "non_identity"
        or application.get("decision_label") != "Service Auth"
        or type(policy) is not dict
        or set(policy) != {
            "id", "name", "precedence", "decision", "decision_label",
            "include", "exclude", "require",
        }
        or _UUID.fullmatch(str(policy.get("id"))) is None
        or policy.get("name") != "receipt-activation-observer-service-auth"
        or policy.get("precedence") != 1
        or policy.get("decision") != "non_identity"
        or policy.get("decision_label") != "Service Auth"
        or type(token) is not dict
        or set(token) != {"token_id", "name"}
        or _UUID.fullmatch(str(token.get("token_id"))) is None
        or token.get("name") != "receipt-activation-observer-gate"
        or policy.get("include") != [{
            "service_token": {"token_id": token.get("token_id")}
        }]
        or policy.get("exclude") != []
        or policy.get("require") != []
        or forbidden != {
            "decisions": ["allow", "bypass"],
            "selectors": ["any_valid_service_token", "any_valid"],
            "covering_destinations": [
                "worker", "preview_worker", "all_workers",
                "all_preview_workers", "public",
            ],
        }
        or manifest.get("cloudflare_error_9999") != "OPERATIONAL_HOLD"
    ):
        raise ReceiptStagingActiveGateError(
            "Receipt observer Access manifest is not exact Service Auth"
        )
    return manifest


def _validate_access_snapshot(
    value: Any,
    *,
    manifest: Mapping[str, Any],
) -> dict[str, Any]:
    if type(value) is not dict or set(value) != {
        "worker", "application", "policy", "service_token",
        "covering_application_ids"
    }:
        raise ReceiptStagingActiveGateError("Receipt observer Access snapshot is not closed")
    application = value["application"]
    policy = value["policy"]
    token = value["service_token"]
    if (
        type(application) is not dict
        or type(policy) is not dict
        or type(token) is not dict
        or value["worker"] != {
            "id": manifest["worker"]["id"],
            "name": manifest["worker"]["script_name"],
        }
        or
        application != {
            "id": manifest["application"]["id"],
            "aud": manifest["application"]["aud"],
            "type": "self_hosted",
            "destinations": manifest["application"]["destinations"],
        }
        or policy != {
            "id": manifest["policy"]["id"],
            "name": manifest["policy"]["name"],
            "precedence": 1,
            "decision": "non_identity",
            "include": manifest["policy"]["include"],
            "exclude": [],
            "require": [],
        }
        or token != {
            "id": manifest["service_token"]["token_id"],
            "name": manifest["service_token"]["name"],
            "duration": token.get("duration"),
            "enabled": True,
            "expires_at": token.get("expires_at"),
            "updated_at": token.get("updated_at"),
            "client_secret_version": token.get("client_secret_version"),
        }
        or type(token.get("duration")) is not str
        or not token["duration"]
        or type(token.get("expires_at")) is not str
        or not token["expires_at"]
        or token.get("updated_at") is not None
        and type(token.get("updated_at")) is not str
        or token.get("client_secret_version") is not None
        and (
            type(token.get("client_secret_version")) is not int
            or token["client_secret_version"] < 1
        )
        or value["covering_application_ids"] != []
    ):
        raise ReceiptStagingActiveGateError(
            "Receipt observer Access app/policy/token drifted"
        )
    encoded = _canonical_bytes(value).decode("ascii")
    if "any_valid" in encoded or '"decision":"allow"' in encoded or (
        '"decision":"bypass"' in encoded
    ):
        raise ReceiptStagingActiveGateError(
            "Receipt observer Access policy is fail-open"
        )
    return copy.deepcopy(value)


def _validate_observer_response(
    raw: bytes,
    *,
    challenge: str,
    reviewed_sha: str,
    accepted: Mapping[str, Mapping[str, Any]],
    access_manifest: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, Any], str]:
    if type(raw) is not bytes or not raw or len(raw) > MAX_OBSERVER_RESPONSE_BYTES:
        raise ReceiptStagingActiveGateError("Receipt observer response is oversized")
    if _NONCE.fullmatch(challenge) is None:
        raise ReceiptStagingActiveGateError("Receipt observer challenge is invalid")
    try:
        response = json.loads(
            raw,
            object_pairs_hook=_reject_duplicates,
            parse_constant=_reject_constant,
        )
    except ReceiptStagingActiveGateError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ReceiptStagingActiveGateError("Receipt observer response is unreadable") from exc
    if type(response) is not dict or set(response) != _OBSERVER_RESPONSE_FIELDS:
        raise ReceiptStagingActiveGateError("Receipt observer response is not closed")
    if raw != _canonical_bytes(response):
        raise ReceiptStagingActiveGateError("Receipt observer response is not canonical")
    premium = response.get("premium_evidence")
    observer = accepted["observer"]
    caller = accepted["caller"]
    if (
        response.get("schema_version") != "receipt-activation-observer-response/v1"
        or response.get("purpose") != "receipt_authority_recovery_canary"
        or response.get("eligibility") != "AUDIT_ONLY"
        or response.get("environment") != "staging"
        or response.get("challenge") != challenge
        or response.get("observer_source_sha") != reviewed_sha
        or response.get("observer_worker_version_id")
        != observer["deployment_version_id"]
        or response.get("observer_worker_version_tag") != _observer_tag(reviewed_sha)
        or response.get("access_authenticated") is not True
        or response.get("access_aud") != access_manifest["application"]["aud"]
        or type(premium) is not dict
        or set(premium) != _PREMIUM_EVIDENCE_FIELDS
        or response.get("premium_evidence_digest") != premium.get("evidence_digest")
    ):
        raise ReceiptStagingActiveGateError("Receipt observer scope drifted")
    response_body = dict(response)
    response_digest = response_body.pop("response_digest")
    if response_digest != _canonical_digest(response_body):
        raise ReceiptStagingActiveGateError("Receipt observer response digest drifted")
    if (
        premium.get("schema_version") != "receipt-operator-audit-evidence/v1"
        or premium.get("purpose") != "receipt_authority_recovery_canary"
        or premium.get("eligibility") != "AUDIT_ONLY"
        or premium.get("environment") != "staging"
        or premium.get("caller_source_sha") != reviewed_sha
        or premium.get("caller_worker_version_id") != caller["deployment_version_id"]
        or premium.get("caller_worker_version_tag")
        != live.version_tag("caller", "staging", reviewed_sha, "ACTIVE")
        or premium.get("d1_schema_digest") != RECOVERY_AUDIT_SCHEMA_DIGEST
        or _SHA256.fullmatch(str(premium.get("reservation_id"))) is None
        or _SHA256.fullmatch(str(premium.get("authority_operation_id"))) is None
        or _NONCE.fullmatch(str(premium.get("request_nonce"))) is None
        or _SHA256.fullmatch(str(premium.get("signed_attestation_digest"))) is None
        or type(premium.get("signed_attestation_json_utf8_length")) is not int
        or premium["signed_attestation_json_utf8_length"] <= 0
        or premium["signed_attestation_json_utf8_length"] > 48 * 1024
    ):
        raise ReceiptStagingActiveGateError("Premium audit evidence scope drifted")
    premium_body = dict(premium)
    premium_digest = premium_body.pop("evidence_digest", None)
    if premium_digest != _canonical_digest(premium_body):
        raise ReceiptStagingActiveGateError("Premium audit evidence digest drifted")
    attestation_bytes = _canonical_base64(
        premium.get("signed_attestation_json_utf8_base64")
    )
    if (
        attestation_bytes is None
        or len(attestation_bytes) != premium["signed_attestation_json_utf8_length"]
    ):
        raise ReceiptStagingActiveGateError("Premium exact D1 bytes drifted")
    try:
        attestation = json.loads(
            attestation_bytes,
            object_pairs_hook=_reject_duplicates,
            parse_constant=_reject_constant,
        )
    except ReceiptStagingActiveGateError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ReceiptStagingActiveGateError("Premium exact D1 bytes are unreadable") from exc
    if (
        type(attestation) is not dict
        or attestation_bytes != _canonical_bytes(attestation)
        or _canonical_digest(attestation) != premium["signed_attestation_digest"]
    ):
        raise ReceiptStagingActiveGateError("Premium exact D1 bytes drifted")
    return attestation, premium, response_digest


def _validate_d1_snapshot(
    value: Any,
    *,
    premium: Mapping[str, Any],
    attestation: Mapping[str, Any],
) -> str:
    if type(value) is not dict or set(value) != {"schema_rows", "attestation_rows"}:
        raise ReceiptStagingActiveGateError("Receipt audit D1 snapshot is not closed")
    schema_rows = value["schema_rows"]
    attestation_rows = value["attestation_rows"]
    if (
        type(schema_rows) is not list
        or len(schema_rows) != 3
        or any(
            type(row) is not dict
            or set(row) != {"type", "name", "tbl_name", "sql"}
            for row in schema_rows
        )
        or schema_rows != sorted(schema_rows, key=lambda row: (row["type"], row["name"]))
    ):
        raise ReceiptStagingActiveGateError("Receipt audit D1 schema inventory drifted")
    schema_digest = _canonical_digest({
        "schema_version": "receipt-recovery-audit-sqlite-schema/v1",
        "objects": schema_rows,
    })
    if schema_digest != RECOVERY_AUDIT_SCHEMA_DIGEST:
        raise ReceiptStagingActiveGateError("Receipt audit D1 schema digest drifted")
    if type(attestation_rows) is not list or len(attestation_rows) != 1:
        raise ReceiptStagingActiveGateError("Receipt audit D1 row is not exact")
    row = attestation_rows[0]
    row_fields = {
        "reservation_id", "source_sha", "caller_worker_version_id",
        "authority_operation_id", "request_nonce", "state",
        "signed_attestation_digest", "signed_attestation_json",
    }
    exact_text = _canonical_bytes(attestation).decode("utf-8")
    if (
        type(row) is not dict
        or set(row) != row_fields
        or row.get("reservation_id") != premium["reservation_id"]
        or row.get("source_sha") != premium["caller_source_sha"]
        or row.get("caller_worker_version_id") != premium["caller_worker_version_id"]
        or row.get("authority_operation_id") != premium["authority_operation_id"]
        or row.get("request_nonce") != premium["request_nonce"]
        or row.get("state") != "ATTESTED"
        or row.get("signed_attestation_digest") != premium["signed_attestation_digest"]
        or row.get("signed_attestation_json") != exact_text
        or base64.b64encode(exact_text.encode("utf-8")).decode("ascii")
        != premium["signed_attestation_json_utf8_base64"]
    ):
        raise ReceiptStagingActiveGateError("Receipt audit D1 exact bytes/row drifted")
    return schema_digest


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
    observer_response_bytes: bytes,
    observer_challenge: str,
    access_snapshot: Mapping[str, Any],
    d1_snapshot: Mapping[str, Any],
    access_manifest_path: Path,
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
    access_manifest = _load_access_manifest(
        access_manifest_path,
        account_id=account_id,
    )
    accepted_access = _validate_access_snapshot(
        access_snapshot,
        manifest=access_manifest,
    )
    roles = {role for role, _worker in ACTIVE_CHAIN}
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
    for role, _worker in ACTIVE_CHAIN:
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
        if role == "observer":
            deployment_id, version_id, message, deployment_created_on = (
                _validate_observer_deployment(
                    deployments[role],
                    source_sha=reviewed_sha,
                )
            )
            row = _validate_observer_version(
                versions[role],
                source_sha=reviewed_sha,
                version_id=version_id,
                surface=surfaces[role],
            )
        else:
            deployment_id, version_id, message, deployment_created_on = live._validate_deployment(
                deployments[role],
                role=role,
                environment="staging",
                source_sha=reviewed_sha,
                authority_mode="ACTIVE",
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

    attestation, premium_evidence, observer_response_digest = (
        _validate_observer_response(
            observer_response_bytes,
            challenge=observer_challenge,
            reviewed_sha=reviewed_sha,
            accepted=accepted,
            access_manifest=access_manifest,
        )
    )
    d1_schema_digest = _validate_d1_snapshot(
        d1_snapshot,
        premium=premium_evidence,
        attestation=attestation,
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
        "format": "receipt-authority-staging-active-transition/v3",
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
        "observer_challenge": observer_challenge,
        "observer_response_digest": observer_response_digest,
        "access_aud": access_manifest["application"]["aud"],
        "access_snapshot_digest": _canonical_digest(accepted_access),
        "d1_schema_digest": d1_schema_digest,
        "finding_ledger_digest": ledger.digest,
        "open_p0_ids": list(ledger.open_p0_ids),
        "strict_release_gate_applied": False,
        "positive_operation_invoked_by_gate": False,
        "eligibility": "AUDIT_ONLY",
        "research_eligible": False,
        "authorization_scope": "STAGING_RECEIPT_ACTIVE_TRANSITION_ONLY",
    }


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *_args: Any, **_kwargs: Any) -> None:
        return None


def _pinned_https_opener() -> Any:
    """Use system trust directly; never inherit a redirect or proxy setting."""

    return build_opener(
        ProxyHandler({}),
        _NoRedirect(),
        HTTPSHandler(context=ssl.create_default_context()),
    )


def _cloudflare_api(
    path: str,
    *,
    api_token: str,
    method: str = "GET",
    body: Mapping[str, Any] | None = None,
) -> tuple[Any, Mapping[str, Any] | None]:
    raw_body = None if body is None else _canonical_bytes(body)
    request = Request(
        "https://api.cloudflare.com/client/v4" + path,
        data=raw_body,
        method=method,
        headers={
            "accept": "application/json",
            "authorization": f"Bearer {api_token}",
            **({"content-type": "application/json"} if raw_body is not None else {}),
        },
    )
    raw = b""
    try:
        with _pinned_https_opener().open(request, timeout=30) as response:
            raw = response.read(MAX_OBSERVER_RESPONSE_BYTES + 1)
    except HTTPError as exc:
        raw = exc.read(MAX_OBSERVER_RESPONSE_BYTES + 1)
        try:
            envelope = json.loads(raw)
        except (UnicodeDecodeError, json.JSONDecodeError):
            envelope = None
        errors = envelope.get("errors") if type(envelope) is dict else None
        if type(errors) is list and any(
            type(row) is dict and row.get("code") == 9999 for row in errors
        ):
            raise ReceiptStagingActiveGateError(
                "OPERATIONAL HOLD: Cloudflare Zero Trust is not initialized (9999)"
            ) from exc
        raise ReceiptStagingActiveGateError(
            "Cloudflare read-only Receipt activation inventory failed"
        ) from exc
    except (URLError, TimeoutError, OSError) as exc:
        raise ReceiptStagingActiveGateError(
            "Cloudflare read-only Receipt activation inventory failed"
        ) from exc
    if len(raw) > MAX_OBSERVER_RESPONSE_BYTES:
        raise ReceiptStagingActiveGateError("Cloudflare inventory response is oversized")
    try:
        envelope = json.loads(
            raw,
            object_pairs_hook=_reject_duplicates,
            parse_constant=_reject_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ReceiptStagingActiveGateError("Cloudflare inventory is unreadable") from exc
    if (
        type(envelope) is not dict
        or envelope.get("success") is not True
        or envelope.get("errors") not in ([], None)
    ):
        errors = envelope.get("errors") if type(envelope) is dict else None
        if type(errors) is list and any(
            type(row) is dict and row.get("code") == 9999 for row in errors
        ):
            raise ReceiptStagingActiveGateError(
                "OPERATIONAL HOLD: Cloudflare Zero Trust is not initialized (9999)"
            )
        raise ReceiptStagingActiveGateError(
            "Cloudflare read-only Receipt activation inventory was unsuccessful"
        )
    info = envelope.get("result_info")
    if info is not None and type(info) is not dict:
        raise ReceiptStagingActiveGateError("Cloudflare pagination metadata drifted")
    return envelope.get("result"), info


def _hostname_scope_covers(value: Any, *, endpoint: str) -> bool:
    """Match exact/wildcard host scopes without accepting arbitrary URLs."""

    if type(value) is not str or not value:
        return False
    candidate = value.strip().lower()
    if "://" in candidate:
        candidate = candidate.split("://", 1)[1]
    candidate = candidate.split("/", 1)[0].split(":", 1)[0].rstrip(".")
    if candidate == endpoint:
        return True
    return candidate.startswith("*.") and endpoint.endswith(candidate[1:])


def _legacy_app_host_scopes(application: Mapping[str, Any]) -> list[Any]:
    scopes: list[Any] = []
    if application.get("domain") not in (None, ""):
        scopes.append(application.get("domain"))
    legacy = application.get("self_hosted_domains")
    if type(legacy) is list:
        for row in legacy:
            if type(row) is dict:
                scopes.extend(
                    row.get(field) for field in ("hostname", "domain", "uri")
                    if row.get(field) not in (None, "")
                )
            else:
                scopes.append(row)
    elif legacy not in (None, ""):
        scopes.append(legacy)
    return scopes


def _collect_access_snapshot(
    *,
    account_id: str,
    api_token: str,
    access_manifest: Mapping[str, Any],
) -> dict[str, Any]:
    account = quote(account_id, safe="")
    application_id = quote(str(access_manifest["application"]["id"]), safe="")
    worker_result, _ = _cloudflare_api(
        f"/accounts/{account}/workers/workers/"
        f"{quote(str(access_manifest['worker']['script_name']), safe='')}",
        api_token=api_token,
    )
    applications, info = _cloudflare_api(
        f"/accounts/{account}/access/apps?{urlencode({'page': 1, 'per_page': 1000})}",
        api_token=api_token,
    )
    policies, policy_info = _cloudflare_api(
        f"/accounts/{account}/access/apps/{application_id}/policies?"
        + urlencode({"page": 1, "per_page": 1000}),
        api_token=api_token,
    )
    tokens, token_info = _cloudflare_api(
        f"/accounts/{account}/access/service_tokens?"
        + urlencode({"page": 1, "per_page": 1000}),
        api_token=api_token,
    )
    if (
        type(applications) is not list
        or type(policies) is not list
        or type(tokens) is not list
        or type(info) is not dict
        or info.get("total_count") != len(applications)
        or type(policy_info) is not dict
        or policy_info.get("total_count") != len(policies)
        or type(token_info) is not dict
        or token_info.get("total_count") != len(tokens)
    ):
        raise ReceiptStagingActiveGateError("Cloudflare Access inventory is incomplete")
    app_id = access_manifest["application"]["id"]
    policy_id = access_manifest["policy"]["id"]
    token_id = access_manifest["service_token"]["token_id"]
    selected_apps = [row for row in applications if type(row) is dict and row.get("id") == app_id]
    selected_policies = [row for row in policies if type(row) is dict and row.get("id") == policy_id]
    selected_tokens = [row for row in tokens if type(row) is dict and row.get("id") == token_id]
    if len(selected_apps) != 1 or len(selected_policies) != 1 or len(selected_tokens) != 1:
        raise ReceiptStagingActiveGateError("Cloudflare Access identity is absent")
    if len(policies) != 1:
        raise ReceiptStagingActiveGateError(
            "Cloudflare Access has an undeclared covering policy"
        )
    app = selected_apps[0]
    policy = selected_policies[0]
    token = selected_tokens[0]
    expected_client_id = os.environ.get(ACCESS_CLIENT_ID_ENV)
    if (
        not expected_client_id
        or token.get("client_id") != expected_client_id
        or token.get("enabled") is not True
    ):
        raise ReceiptStagingActiveGateError(
            "Cloudflare Access service-token credential identity drifted"
        )
    endpoint = str(access_manifest["endpoint"]["hostname"])
    if _legacy_app_host_scopes(app):
        raise ReceiptStagingActiveGateError(
            "Receipt observer Access app also relies on a hostname scope"
        )
    covering: list[str] = []
    for row in applications:
        if type(row) is not dict or row.get("id") == app_id:
            continue
        destinations = row.get("destinations")
        for destination in destinations if type(destinations) is list else []:
            if type(destination) is not dict:
                continue
            kind = destination.get("type")
            worker_id = access_manifest["worker"]["id"]
            public_covers = kind == "public" and _hostname_scope_covers(
                destination.get("uri"), endpoint=endpoint
            )
            if (
                kind in {"all_workers", "all_preview_workers"}
                or (
                    kind in {"worker", "preview_worker"}
                    and destination.get("worker_id") == worker_id
                )
                or public_covers
            ):
                covering.append(str(row.get("id")))
                break
        else:
            if any(
                _hostname_scope_covers(value, endpoint=endpoint)
                for value in _legacy_app_host_scopes(row)
            ):
                covering.append(str(row.get("id")))
    snapshot = {
        "worker": {
            "id": worker_result.get("id") if type(worker_result) is dict else None,
            "name": worker_result.get("name") if type(worker_result) is dict else None,
        },
        "application": {
            "id": app.get("id"),
            "aud": app.get("aud"),
            "type": app.get("type"),
            "destinations": app.get("destinations"),
        },
        "policy": {
            "id": policy.get("id"),
            "name": policy.get("name"),
            "precedence": policy.get("precedence"),
            "decision": policy.get("decision"),
            "include": policy.get("include"),
            "exclude": policy.get("exclude") or [],
            "require": policy.get("require") or [],
        },
        "service_token": {
            "id": token.get("id"),
            "name": token.get("name"),
            "duration": token.get("duration"),
            "enabled": token.get("enabled"),
            "expires_at": token.get("expires_at"),
            "updated_at": token.get("updated_at"),
            "client_secret_version": token.get("client_secret_version"),
        },
        "covering_application_ids": sorted(covering),
    }
    return _validate_access_snapshot(snapshot, manifest=access_manifest)


def _d1_select(
    *,
    account_id: str,
    api_token: str,
    database_id: str,
    sql: str,
    params: list[str],
) -> list[dict[str, Any]]:
    result, _info = _cloudflare_api(
        f"/accounts/{quote(account_id, safe='')}/d1/database/"
        f"{quote(database_id, safe='')}/query",
        api_token=api_token,
        method="POST",
        body={"sql": sql, "params": params},
    )
    if (
        type(result) is not list
        or len(result) != 1
        or type(result[0]) is not dict
        or result[0].get("success") is not True
        or type(result[0].get("results")) is not list
    ):
        raise ReceiptStagingActiveGateError("Receipt audit D1 SELECT failed")
    rows = result[0]["results"]
    if any(type(row) is not dict for row in rows):
        raise ReceiptStagingActiveGateError("Receipt audit D1 rows are malformed")
    return rows


def _collect_d1_snapshot(
    *,
    account_id: str,
    api_token: str,
    source_sha: str,
    caller_version_id: str,
) -> dict[str, Any]:
    surface = build_manifest()["workers"]["ingestion-premium"]["staging"]
    databases = surface["d1_databases"]
    if len(databases) != 1:
        raise ReceiptStagingActiveGateError("Premium staging D1 identity drifted")
    database_id = str(databases[0]["database_id"])
    schema_rows = _d1_select(
        account_id=account_id,
        api_token=api_token,
        database_id=database_id,
        sql=(
            "SELECT type,name,tbl_name,sql FROM sqlite_schema "
            "WHERE name IN (?,?,?) ORDER BY type,name"
        ),
        params=[
            "receipt_authority_recovery_audit_attestations",
            "receipt_authority_recovery_audit_monotonic",
            "receipt_authority_recovery_audit_no_delete",
        ],
    )
    attestation_rows = _d1_select(
        account_id=account_id,
        api_token=api_token,
        database_id=database_id,
        sql=(
            "SELECT reservation_id,source_sha,caller_worker_version_id,"
            "authority_operation_id,request_nonce,state,"
            "signed_attestation_digest,signed_attestation_json "
            "FROM receipt_authority_recovery_audit_attestations "
            "WHERE source_sha=? AND caller_worker_version_id=?"
        ),
        params=[source_sha, caller_version_id],
    )
    return {"schema_rows": schema_rows, "attestation_rows": attestation_rows}


def _fetch_observer_response(
    *,
    challenge: str,
    access_manifest: Mapping[str, Any],
) -> bytes:
    client_id = os.environ.get(ACCESS_CLIENT_ID_ENV)
    client_secret = os.environ.get(ACCESS_CLIENT_SECRET_ENV)
    if not client_id or not client_secret:
        raise ReceiptStagingActiveGateError(
            "Receipt observer Access credentials are required in process environment"
        )
    domain = access_manifest["endpoint"]["hostname"]
    url = (
        f"https://{domain}/v1/receipt-authority/audit-evidence?"
        + urlencode({"challenge": challenge})
    )
    opener = _pinned_https_opener()
    unauthenticated = Request(url, method="GET", headers={"accept": "application/json"})
    try:
        with opener.open(unauthenticated, timeout=30) as response:
            response.read(MAX_OBSERVER_RESPONSE_BYTES + 1)
            raise ReceiptStagingActiveGateError(
                "Receipt observer accepted an unauthenticated request"
            )
    except HTTPError as exc:
        exc.read(MAX_OBSERVER_RESPONSE_BYTES + 1)
        if exc.code not in {401, 403} or exc.headers.get("location") is not None:
            raise ReceiptStagingActiveGateError(
                "Receipt observer unauthenticated rejection drifted"
            ) from exc
    except ReceiptStagingActiveGateError:
        raise
    except (URLError, TimeoutError, OSError) as exc:
        raise ReceiptStagingActiveGateError(
            "Receipt observer unauthenticated probe failed"
        ) from exc

    authenticated = Request(
        url,
        method="GET",
        headers={
            "accept": "application/json",
            "CF-Access-Client-Id": client_id,
            "CF-Access-Client-Secret": client_secret,
        },
    )
    try:
        with opener.open(authenticated, timeout=30) as response:
            raw = response.read(MAX_OBSERVER_RESPONSE_BYTES + 1)
            headers = response.headers
            if (
                response.getcode() != 200
                or response.geturl() != url
                or headers.get("location") is not None
                or not str(headers.get("content-type") or "").lower().startswith(
                    "application/json"
                )
                or headers.get("cache-control") != "no-store"
                or headers.get("pragma") != "no-cache"
                or headers.get("x-content-type-options") != "nosniff"
            ):
                raise ReceiptStagingActiveGateError(
                    "Receipt observer authenticated response metadata drifted"
                )
    except ReceiptStagingActiveGateError:
        raise
    except (HTTPError, URLError, TimeoutError, OSError) as exc:
        raise ReceiptStagingActiveGateError(
            "Receipt observer authenticated request failed"
        ) from exc
    if len(raw) > MAX_OBSERVER_RESPONSE_BYTES:
        raise ReceiptStagingActiveGateError("Receipt observer response is oversized")
    return raw


def _collect_staging_active_documents(
    *,
    source_sha: str,
    account_id: str,
    api_token: str,
) -> dict[str, dict[str, Any]]:
    """Collect one read-only whole-chain bracket in isolated clients."""

    reviewed_sha = live._source_sha(source_sha)
    if live._ACCOUNT_ID.fullmatch(account_id) is None or not api_token:
        raise ReceiptStagingActiveGateError(
            "exact Cloudflare account id and API token are required"
        )
    manifest = build_manifest()
    access_manifest = _load_access_manifest(
        ACCESS_MANIFEST_PATH,
        account_id=account_id,
    )
    access_snapshot = _collect_access_snapshot(
        account_id=account_id,
        api_token=api_token,
        access_manifest=access_manifest,
    )
    deployments: dict[str, Any] = {}
    versions: dict[str, Any] = {}
    public: dict[str, Any] = {}
    provenance: dict[str, Any] = {}
    deployment_after: dict[str, Any] = {}
    public_after: dict[str, Any] = {}

    for role, worker in ACTIVE_CHAIN:
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
            opener=_pinned_https_opener().open,
        )

    for role, worker in ACTIVE_CHAIN:
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
            opener=_pinned_https_opener().open,
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

    for role, worker in ACTIVE_CHAIN:
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
            opener=_pinned_https_opener().open,
        )
    caller_version_id = str(versions["caller"].get("id"))
    d1_snapshot = _collect_d1_snapshot(
        account_id=account_id,
        api_token=api_token,
        source_sha=reviewed_sha,
        caller_version_id=caller_version_id,
    )
    return {
        "deployments": deployments,
        "versions": versions,
        "public_surfaces": public,
        "source_provenance": provenance,
        "deployment_bracket_after": deployment_after,
        "public_bracket_after": public_after,
        "access_snapshot": access_snapshot,
        "d1_snapshot": d1_snapshot,
    }


def _remeasure_staging_active_tail(
    *,
    source_sha: str,
    account_id: str,
    api_token: str,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    """Close the live bracket after the fixed attestation has been verified."""

    manifest = build_manifest()
    deployments: dict[str, Any] = {}
    public: dict[str, Any] = {}
    for role, worker in ACTIVE_CHAIN:
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
            opener=_pinned_https_opener().open,
        )
    traffic = live._sequence(
        live._mapping(
            deployments["caller"], label="caller ACTIVE deployment"
        ).get("versions"),
        label="caller ACTIVE deployment versions",
    )
    if len(traffic) != 1 or type(traffic[0]) is not dict:
        raise ReceiptStagingActiveGateError("caller ACTIVE deployment drifted")
    caller_version_id = str(traffic[0].get("version_id"))
    access_manifest = _load_access_manifest(
        ACCESS_MANIFEST_PATH,
        account_id=account_id,
    )
    access = _collect_access_snapshot(
        account_id=account_id,
        api_token=api_token,
        access_manifest=access_manifest,
    )
    d1 = _collect_d1_snapshot(
        account_id=account_id,
        api_token=api_token,
        source_sha=live._source_sha(source_sha),
        caller_version_id=caller_version_id,
    )
    return deployments, public, access, d1


def _write_content_addressed_result(result: Mapping[str, Any]) -> dict[str, Any]:
    body = copy.deepcopy(dict(result))
    evidence_digest = _canonical_digest(body)
    document = {**body, "evidence_digest": evidence_digest}
    raw = _canonical_bytes(document)
    try:
        OUTPUT_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
        resolved_output = OUTPUT_DIR.resolve(strict=True)
        resolved_root = ROOT.resolve(strict=True)
    except OSError as exc:
        raise ReceiptStagingActiveGateError(
            "Receipt activation output store is unsafe"
        ) from exc
    if (
        OUTPUT_DIR.is_symlink()
        or not OUTPUT_DIR.is_dir()
        or not resolved_output.is_relative_to(resolved_root)
    ):
        raise ReceiptStagingActiveGateError("Receipt activation output store is unsafe")
    path = OUTPUT_DIR / f"{evidence_digest.removeprefix('sha256:')}.json"
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags, 0o600)
    except FileExistsError:
        try:
            existing = path.read_bytes()
        except OSError as exc:
            raise ReceiptStagingActiveGateError(
                "Receipt activation evidence collision is unreadable"
            ) from exc
        if existing != raw:
            raise ReceiptStagingActiveGateError(
                "Receipt activation evidence content-address collision"
            )
        return document
    except OSError as exc:
        raise ReceiptStagingActiveGateError(
            "Receipt activation evidence cannot be created"
        ) from exc
    try:
        with os.fdopen(descriptor, "wb", closefd=True) as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        directory_fd = os.open(OUTPUT_DIR, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    except Exception:
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass
        raise
    return document


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
        access_manifest = _load_access_manifest(
            ACCESS_MANIFEST_PATH,
            account_id=account_id,
        )
        documents = _collect_staging_active_documents(
            source_sha=source_sha,
            account_id=account_id,
            api_token=api_token,
        )
        challenge = secrets.token_hex(32)
        observer_response = _fetch_observer_response(
            challenge=challenge,
            access_manifest=access_manifest,
        )
        result = _validate_staging_active_transition_core(
            source_sha=source_sha,
            account_id=account_id,
            **documents,
            observer_response_bytes=observer_response,
            observer_challenge=challenge,
            access_manifest_path=ACCESS_MANIFEST_PATH,
            registry_path=SCOPED_REGISTRY_PATHS["staging"],
        )
        tail_deployments, tail_public, tail_access, tail_d1 = (
            _remeasure_staging_active_tail(
            source_sha=source_sha,
            account_id=account_id,
            api_token=api_token,
            )
        )
        for role, _worker in ACTIVE_CHAIN:
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
        if _canonical_digest(documents["access_snapshot"]) != _canonical_digest(
            tail_access
        ):
            raise ReceiptStagingActiveGateError(
                "Access app/policy/token changed during observer request"
            )
        if _canonical_digest(documents["d1_snapshot"]) != _canonical_digest(tail_d1):
            raise ReceiptStagingActiveGateError(
                "Receipt audit D1 evidence changed during observer request"
            )
        live._require_exact_clean_source(source_sha)
        live._require_official_origin_main(source_sha)
        return _write_content_addressed_result(result)
    except ReceiptStagingActiveGateError:
        raise
    except (live.ReceiptPendingLiveAcceptanceError, RuntimeError, ValueError) as exc:
        raise ReceiptStagingActiveGateError(str(exc)) from exc


__all__ = [
    "ReceiptStagingActiveGateError",
    "validate_staging_active_transition",
]
