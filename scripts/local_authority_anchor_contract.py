"""Canonical wire, lineage, signature, and pinned-manifest contract.

This module owns deterministic protocol bytes and validation only. It has no
remote authority state, network transport, local audit mutation, or collector
orchestration.
"""

from __future__ import annotations

import base64
import hashlib
import json
import re
import urllib.parse
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

from scripts.local_authority_activation import canonical_json_bytes
from scripts.manage_local_authority_staged_canary import (
    _ANCHOR_ATTEMPT_RECORD_FIELDS,
    _ANCHOR_EVENT_RECORD_FIELDS,
    _ANCHOR_RUN_RECORD_FIELDS,
    _ANCHOR_RUN_STATE_FORMAT,
    _ANCHOR_SNAPSHOT_FORMAT,
    _ATTEMPT_EVIDENCE_FORMAT,
    _ATTEMPT_EVIDENCE_SET_FORMAT,
    _validate_anchor_candidate,
)

ROOT = Path(__file__).resolve().parents[1]
DEPLOYMENT_PATH = (
    ROOT / "specs" / "authorities" / "local-authority-anchor-deployment.json"
)
REGISTRY_PATH = (
    ROOT / "specs" / "authorities" / "local-authority-anchor-public-keys.json"
)
PROTOCOL_SCHEMA_PATH = (
    ROOT / "specs" / "authorities" / "local-authority-anchor-protocol.schema.json"
)
PINNED_DEPLOYMENT_DIGEST = (
    "sha256:03094de5550bac4d60a9db40093187e90d4c83ec65a3f27c7b45e5849a641818"
)
PINNED_REGISTRY_DIGEST = (
    "sha256:702cfdd798d15a396f788c8dabb14332a3dfffa9911058daf830fdad83fee724"
)
PINNED_PROTOCOL_SCHEMA_DIGEST = (
    "sha256:1b4573e6b5a1929e2d3de5333fa2619f6f52b02219eaa5c0b3c95a7c0d0563db"
)

AUTHORITY_ID = "quant-platform-local-authority-high-water-anchor"
ENVIRONMENT_SET = ("production", "staging")
CHALLENGE_REQUEST_FORMAT = "local-authority-high-water-anchor-challenge-request/v1"
CHALLENGE_FORMAT = "local-authority-high-water-anchor-challenge/v1"
COMMIT_REQUEST_FORMAT = "local-authority-high-water-anchor-commit-request/v2"
RECEIPT_FORMAT = "local-authority-high-water-anchor-receipt/v2"
AUDIT_RECORD_FORMAT = "local-authority-high-water-anchor-local-audit/v2"
LINEAGE_PROOF_FORMAT = "local-authority-high-water-anchor-lineage-proof/v2"
SUBMISSION_RECORD_FORMAT = "local-authority-high-water-anchor-submission/v2"
RESOLUTION_REQUEST_FORMAT = "local-authority-high-water-anchor-resolution-request/v1"
RESOLUTION_RESPONSE_FORMAT = "local-authority-high-water-anchor-resolution-response/v1"
ABANDONMENT_RECORD_FORMAT = "local-authority-high-water-anchor-abandonment/v1"
DEPLOYMENT_FORMAT = "local-authority-high-water-anchor-deployment/v1"
REGISTRY_FORMAT = "local-authority-high-water-anchor-public-key-registry/v1"
CONFIG_FORMAT = "local-authority-high-water-anchor-collector-config/v1"
MAX_DOCUMENT_BYTES = 262_144

_DIGEST_RE = re.compile(r"sha256:[0-9a-f]{64}\Z")
_NONCE_RE = re.compile(r"[0-9a-f]{64}\Z")
_INSTANCE_RE = re.compile(r"journal-instance:[0-9a-f]{64}\Z")
_KEY_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}\Z")
_CHALLENGE_REQUEST_BODY_FIELDS = {
    "format",
    "authority_id",
    "journal_instance_id",
    "environment_set",
    "anchor_candidate_digest",
    "request_nonce",
    "client_key_id",
}
_CHALLENGE_REQUEST_FIELDS = _CHALLENGE_REQUEST_BODY_FIELDS | {
    "challenge_request_digest",
    "signature",
}
_CHALLENGE_BODY_FIELDS = {
    "format",
    "authority_id",
    "journal_instance_id",
    "environment_set",
    "anchor_candidate_digest",
    "challenge_request_digest",
    "nonce",
    "issued_at",
    "expires_at",
    "generation",
    "prior_anchor_digest",
    "remote_key_id",
}
_CHALLENGE_FIELDS = _CHALLENGE_BODY_FIELDS | {"challenge_digest", "signature"}
_COMMIT_BODY_FIELDS = {
    "format",
    "authority_id",
    "journal_instance_id",
    "environment_set",
    "generation",
    "prior_anchor_digest",
    "challenge_digest",
    "challenge_nonce",
    "anchor_candidate",
    "anchor_candidate_digest",
    "lineage_proof",
    "lineage_proof_digest",
    "client_key_id",
}
_COMMIT_FIELDS = _COMMIT_BODY_FIELDS | {"commit_request_digest", "signature"}
_ACCEPTED_ANCHOR_FIELDS = {
    "format",
    "authority_id",
    "journal_instance_id",
    "environment_set",
    "generation",
    "prior_anchor_digest",
    "challenge_digest",
    "commit_request_digest",
    "anchor_candidate_digest",
    "lineage_proof_digest",
    "accepted_at",
}
_RECEIPT_BODY_FIELDS = _ACCEPTED_ANCHOR_FIELDS | {
    "remote_key_id",
    "accepted_anchor_digest",
}
_RECEIPT_FIELDS = _RECEIPT_BODY_FIELDS | {"signature", "receipt_digest"}
_LINEAGE_PROOF_FIELDS = {
    "format",
    "journal_instance_id",
    "environment_set",
    "prior_anchor_digest",
    "prior_anchor_candidate_digest",
    "base_event_count",
    "base_tail_event_digest",
    "event_suffix",
    "previous_attempt_evidence_set_digest",
    "new_attempt_records",
    "changed_run_records",
    "anchor_candidate_digest",
}
_SNAPSHOT_FIELDS = {"format", "candidate", "events", "attempts", "runs"}
_RESOLUTION_REQUEST_BODY_FIELDS = {
    "format",
    "authority_id",
    "journal_instance_id",
    "environment_set",
    "generation",
    "prior_anchor_digest",
    "challenge_digest",
    "commit_request_digest",
    "request_nonce",
    "client_key_id",
}
_RESOLUTION_REQUEST_FIELDS = _RESOLUTION_REQUEST_BODY_FIELDS | {
    "resolution_request_digest",
    "signature",
}
_RESOLUTION_RESPONSE_BODY_FIELDS = {
    "format",
    "authority_id",
    "journal_instance_id",
    "environment_set",
    "generation",
    "prior_anchor_digest",
    "challenge_digest",
    "commit_request_digest",
    "resolution_request_digest",
    "status",
    "receipt",
    "current_generation",
    "current_anchor_digest",
    "resolved_at",
    "remote_key_id",
}
_RESOLUTION_RESPONSE_FIELDS = _RESOLUTION_RESPONSE_BODY_FIELDS | {
    "resolution_response_digest",
    "signature",
}

class AnchorProtocolError(RuntimeError):
    """A closed protocol, signature, CAS, transport, or local-audit check failed."""


class AnchorOperationalHold(AnchorProtocolError):
    """The checked-in remote authority deployment is intentionally inactive."""


def _reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise AnchorProtocolError("anchor JSON contains a duplicate key")
        result[key] = value
    return result


def _strict_json(
    raw: bytes, *, label: str, require_canonical: bool = True
) -> dict[str, Any]:
    if type(raw) is not bytes or not raw or len(raw) > MAX_DOCUMENT_BYTES:
        raise AnchorProtocolError(f"{label} size is invalid")
    try:
        value = json.loads(
            raw,
            object_pairs_hook=_reject_duplicates,
            parse_constant=lambda _value: (_ for _ in ()).throw(
                AnchorProtocolError(f"{label} contains a non-finite number")
            ),
        )
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise AnchorProtocolError(f"{label} is not strict JSON") from exc
    if type(value) is not dict or require_canonical and canonical_json_bytes(value) != raw:
        raise AnchorProtocolError(f"{label} is not one canonical object")
    return value


def _exact(value: Mapping[str, Any], fields: set[str], *, label: str) -> dict[str, Any]:
    if type(value) is not dict or set(value) != fields:
        raise AnchorProtocolError(f"{label} fields are not closed")
    return dict(value)


def _digest(value: bytes | Mapping[str, Any]) -> str:
    raw = value if type(value) is bytes else canonical_json_bytes(dict(value))
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def _body(value: Mapping[str, Any], fields: set[str]) -> dict[str, Any]:
    return {name: value[name] for name in fields}


def _require_digest(value: Any, *, label: str, allow_none: bool = False) -> str | None:
    if allow_none and value is None:
        return None
    if type(value) is not str or _DIGEST_RE.fullmatch(value) is None:
        raise AnchorProtocolError(f"{label} is not a canonical digest")
    return value


def _require_key_id(value: Any, *, label: str) -> str:
    if type(value) is not str or _KEY_ID_RE.fullmatch(value) is None:
        raise AnchorProtocolError(f"{label} is invalid")
    return value


def _parse_time(value: Any, *, label: str) -> datetime:
    if type(value) is not str or not value.endswith("+00:00"):
        raise AnchorProtocolError(f"{label} is not canonical UTC time")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise AnchorProtocolError(f"{label} is invalid") from exc
    if parsed.tzinfo != UTC or parsed.isoformat(timespec="microseconds") != value:
        raise AnchorProtocolError(f"{label} is not canonical UTC time")
    return parsed


def _sign(private: Ed25519PrivateKey, body: Mapping[str, Any]) -> str:
    return "ed25519:" + base64.b64encode(
        private.sign(canonical_json_bytes(dict(body)))
    ).decode("ascii")


def _verify_signature(
    public: Ed25519PublicKey, signature: Any, body: Mapping[str, Any], *, label: str
) -> None:
    if type(signature) is not str or not signature.startswith("ed25519:"):
        raise AnchorProtocolError(f"{label} signature encoding is invalid")
    try:
        raw = base64.b64decode(signature.removeprefix("ed25519:"), validate=True)
        if len(raw) != 64:
            raise ValueError("wrong signature length")
        public.verify(raw, canonical_json_bytes(dict(body)))
    except (ValueError, InvalidSignature) as exc:
        raise AnchorProtocolError(f"{label} signature is invalid") from exc


@dataclass(frozen=True)
class AnchorKeyRegistry:
    digest: str
    authority_status: str
    authority_id: str
    environment_set: tuple[str, ...]
    keys: Mapping[str, Ed25519PublicKey]


@dataclass(frozen=True)
class AnchorDeployment:
    digest: str
    activation_status: str
    authority_id: str
    endpoint: str | None
    environment_set: tuple[str, ...]
    challenge_path: str
    commit_path: str
    resolution_path: str
    root_config_path: Path
    client_private_key_path: Path | None
    client_key_id: str | None
    remote_key_id: str | None
    receipt_audit_path: Path
    challenge_ttl_seconds: int
    per_io_timeout_seconds: int
    maximum_document_bytes: int


def _self_digest(document: Mapping[str, Any], field: str) -> str:
    return _digest({name: value for name, value in document.items() if name != field})


def _evaluate_registry(document: dict[str, Any], *, expected_digest: str) -> AnchorKeyRegistry:
    fields = {
        "format", "generation", "authority_status", "authority_id",
        "environment_set", "keys", "registry_digest",
    }
    value = _exact(document, fields, label="anchor public-key registry")
    if (
        value["format"] != REGISTRY_FORMAT
        or value["authority_id"] != AUTHORITY_ID
        or value["environment_set"] != list(ENVIRONMENT_SET)
        or value["authority_status"] not in {"PENDING", "ACTIVE"}
        or type(value["generation"]) is not int
        or value["generation"] < 0
        or value["registry_digest"] != _self_digest(value, "registry_digest")
        or value["registry_digest"] != expected_digest
        or type(value["keys"]) is not list
    ):
        raise AnchorProtocolError("anchor public-key registry identity drifted")
    keys: dict[str, Ed25519PublicKey] = {}
    for entry in value["keys"]:
        if type(entry) is not dict or set(entry) != {
            "key_id", "public_key_base64", "status"
        }:
            raise AnchorProtocolError("anchor registry key fields are not closed")
        key_id = _require_key_id(entry["key_id"], label="remote key id")
        if key_id in keys or entry["status"] != "ACTIVE":
            raise AnchorProtocolError("anchor registry key state is invalid")
        try:
            raw = base64.b64decode(entry["public_key_base64"], validate=True)
            if len(raw) != 32:
                raise ValueError("wrong key length")
            keys[key_id] = Ed25519PublicKey.from_public_bytes(raw)
        except (TypeError, ValueError) as exc:
            raise AnchorProtocolError("anchor registry public key is invalid") from exc
    if (value["authority_status"] == "PENDING" and (value["generation"] != 0 or keys)) or (
        value["authority_status"] == "ACTIVE" and (value["generation"] < 1 or len(keys) != 1)
    ):
        raise AnchorProtocolError("anchor registry activation state is invalid")
    return AnchorKeyRegistry(
        digest=value["registry_digest"],
        authority_status=value["authority_status"],
        authority_id=value["authority_id"],
        environment_set=tuple(value["environment_set"]),
        keys=keys,
    )


def load_pinned_registry() -> AnchorKeyRegistry:
    return _evaluate_registry(
        _strict_json(
            REGISTRY_PATH.read_bytes(), label="pinned anchor registry",
            require_canonical=False,
        ),
        expected_digest=PINNED_REGISTRY_DIGEST,
    )


def _evaluate_deployment(
    document: dict[str, Any], *, expected_digest: str, registry_digest: str
) -> AnchorDeployment:
    fields = {
        "format", "activation_status", "authority_id", "provider_id", "endpoint",
        "environment_set", "challenge_path", "commit_path", "resolution_path",
        "root_config_path",
        "client_private_key_path", "client_key_id", "remote_key_id",
        "public_key_registry_path", "public_key_registry_digest",
        "protocol_schema_path", "protocol_schema_digest", "receipt_audit_path",
        "challenge_ttl_seconds", "per_io_timeout_seconds",
        "maximum_document_bytes", "redirects_allowed", "ambient_proxy_allowed",
        "ambient_credentials_allowed", "local_root_control_plane_credentials_prohibited",
        "external_admin_separation_required", "external_admin_separation_verified",
        "deployment_digest",
    }
    value = _exact(document, fields, label="anchor deployment")
    if (
        value["format"] != DEPLOYMENT_FORMAT
        or value["authority_id"] != AUTHORITY_ID
        or value["environment_set"] != list(ENVIRONMENT_SET)
        or value["challenge_path"] != "/v1/local-authority-anchor/challenge"
        or value["commit_path"] != "/v1/local-authority-anchor/commit"
        or value["resolution_path"] != "/v1/local-authority-anchor/resolve"
        or value["root_config_path"]
        != "/Library/Application Support/quant-platform/authorities/staged-canary/external-anchor.json"
        or value["receipt_audit_path"]
        != "/Library/Application Support/quant-platform/authorities/staged-canary/external-anchor-receipts"
        or value["public_key_registry_path"]
        != "specs/authorities/local-authority-anchor-public-keys.json"
        or value["public_key_registry_digest"] != registry_digest
        or value["protocol_schema_path"]
        != "specs/authorities/local-authority-anchor-protocol.schema.json"
        or value["protocol_schema_digest"] != PINNED_PROTOCOL_SCHEMA_DIGEST
        or value["challenge_ttl_seconds"] != 60
        or value["per_io_timeout_seconds"] != 5
        or value["maximum_document_bytes"] != MAX_DOCUMENT_BYTES
        or value["redirects_allowed"] is not False
        or value["ambient_proxy_allowed"] is not False
        or value["ambient_credentials_allowed"] is not False
        or value["local_root_control_plane_credentials_prohibited"] is not True
        or value["external_admin_separation_required"] is not True
        or value["deployment_digest"] != _self_digest(value, "deployment_digest")
        or value["deployment_digest"] != expected_digest
    ):
        raise AnchorProtocolError("anchor deployment identity drifted")
    status = value["activation_status"]
    if status == "PENDING_PROVIDER_SELECTION":
        if any(
            value[name] is not None
            for name in (
                "provider_id", "endpoint", "client_private_key_path",
                "client_key_id", "remote_key_id",
            )
        ) or value["external_admin_separation_verified"] is not False:
            raise AnchorProtocolError("pending anchor deployment claims active material")
    elif status == "ACTIVE":
        if (
            type(value["provider_id"]) is not str
            or not value["provider_id"]
            or type(value["endpoint"]) is not str
            or type(value["client_private_key_path"]) is not str
            or not str(value["client_private_key_path"]).startswith(
                "/Library/Application Support/quant-platform/authorities/staged-canary/"
            )
            or _KEY_ID_RE.fullmatch(str(value["client_key_id"])) is None
            or _KEY_ID_RE.fullmatch(str(value["remote_key_id"])) is None
            or value["external_admin_separation_verified"] is not True
        ):
            raise AnchorProtocolError("active anchor deployment is incomplete")
        parsed = urllib.parse.urlsplit(value["endpoint"])
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
            or parsed.path not in {"", "/"}
            or parsed.port not in {None, 443}
        ):
            raise AnchorProtocolError("anchor endpoint is not one pinned HTTPS origin")
    else:
        raise AnchorProtocolError("anchor deployment status is invalid")
    return AnchorDeployment(
        digest=value["deployment_digest"], activation_status=status,
        authority_id=value["authority_id"], endpoint=value["endpoint"],
        environment_set=tuple(value["environment_set"]),
        challenge_path=value["challenge_path"], commit_path=value["commit_path"],
        resolution_path=value["resolution_path"],
        root_config_path=Path(value["root_config_path"]),
        client_private_key_path=(
            None if value["client_private_key_path"] is None
            else Path(value["client_private_key_path"])
        ),
        client_key_id=value["client_key_id"], remote_key_id=value["remote_key_id"],
        receipt_audit_path=Path(value["receipt_audit_path"]),
        challenge_ttl_seconds=value["challenge_ttl_seconds"],
        per_io_timeout_seconds=value["per_io_timeout_seconds"],
        maximum_document_bytes=value["maximum_document_bytes"],
    )


def load_pinned_deployment(registry: AnchorKeyRegistry) -> AnchorDeployment:
    schema = _strict_json(
        PROTOCOL_SCHEMA_PATH.read_bytes(), label="pinned anchor protocol schema",
        require_canonical=False,
    )
    if _digest(schema) != PINNED_PROTOCOL_SCHEMA_DIGEST:
        raise AnchorProtocolError("anchor protocol schema digest drifted")
    return _evaluate_deployment(
        _strict_json(
            DEPLOYMENT_PATH.read_bytes(), label="pinned anchor deployment",
            require_canonical=False,
        ),
        expected_digest=PINNED_DEPLOYMENT_DIGEST,
        registry_digest=registry.digest,
    )


def _validate_attempt_records(value: Any) -> list[dict[str, Any]]:
    if type(value) is not list:
        raise AnchorProtocolError("anchor attempt records are not a list")
    records: list[dict[str, Any]] = []
    prior_key: tuple[str, int] | None = None
    for raw in value:
        row = _exact(raw, _ANCHOR_ATTEMPT_RECORD_FIELDS, label="anchor attempt record")
        key = (row["canary_id"], row["attempt"])
        if (
            type(key[0]) is not str
            or _DIGEST_RE.fullmatch(key[0]) is None
            or type(key[1]) is not int
            or key[1] < 1
            or prior_key is not None
            and key <= prior_key
            or type(row["lease_boot_id"]) is not str
            or not row["lease_boot_id"]
            or type(row["deadline_monotonic_ns"]) is not int
            or row["deadline_monotonic_ns"] <= 0
        ):
            raise AnchorProtocolError("anchor attempt record identity is invalid")
        for name in (
            "challenge_digest",
            "resource_digest",
            "lease_token_digest",
            "attempt_evidence_digest",
        ):
            _require_digest(row[name], label=f"attempt {name}")
        _parse_time(row["lease_expires_at"], label="attempt lease_expires_at")
        _parse_time(row["acquired_at"], label="attempt acquired_at")
        expected = _digest(
            {
                "format": _ATTEMPT_EVIDENCE_FORMAT,
                **{
                    name: row[name]
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
        if row["attempt_evidence_digest"] != expected:
            raise AnchorProtocolError("anchor attempt record digest is invalid")
        records.append(row)
        prior_key = key
    return records


def _validate_run_records(
    value: Any, *, attempts: list[dict[str, Any]],
    complete_inventory: bool = True,
) -> list[dict[str, Any]]:
    if type(value) is not list:
        raise AnchorProtocolError("anchor run records are not a list")
    attempt_index = {
        (row["canary_id"], row["attempt"]): row for row in attempts
    }
    records: list[dict[str, Any]] = []
    prior_canary: str | None = None
    for raw in value:
        row = _exact(raw, _ANCHOR_RUN_RECORD_FIELDS, label="anchor run record")
        canary_id = row["canary_id"]
        attempt_count = row["attempt_count"]
        if (
            type(canary_id) is not str
            or _DIGEST_RE.fullmatch(canary_id) is None
            or prior_canary is not None
            and canary_id <= prior_canary
            or row["environment"] not in ENVIRONMENT_SET
            or row["state"] not in {"RUNNING", "FAILED_RETRYABLE", "FAILED_FINAL", "COMMITTED"}
            or type(attempt_count) is not int
            or attempt_count < 1
            or (canary_id, attempt_count) not in attempt_index
            or type(row["authority_id"]) is not str
            or not row["authority_id"]
            or type(row["action"]) is not str
            or not row["action"]
            or type(row["source_sha"]) is not str
            or re.fullmatch(r"[0-9a-f]{40}", row["source_sha"]) is None
            or type(row["updated_at"]) is not str
        ):
            raise AnchorProtocolError("anchor run record identity is invalid")
        for name in ("runtime_bundle_digest", "resource_digest", "challenge_digest"):
            _require_digest(row[name], label=f"run {name}")
        _require_digest(row["result_digest"], label="run result_digest", allow_none=True)
        _require_digest(
            row["lease_token_digest"], label="run lease_token_digest", allow_none=True
        )
        _parse_time(row["updated_at"], label="run updated_at")
        latest = attempt_index[(canary_id, attempt_count)]
        if (
            row["challenge_digest"] != latest["challenge_digest"]
            or row["resource_digest"] != latest["resource_digest"]
        ):
            raise AnchorProtocolError("anchor run does not match its latest attempt")
        if row["state"] == "RUNNING":
            if (
                row["lease_token_digest"] != latest["lease_token_digest"]
                or row["lease_boot_id"] != latest["lease_boot_id"]
                or row["deadline_monotonic_ns"] != latest["deadline_monotonic_ns"]
                or row["lease_expires_at"] != latest["lease_expires_at"]
                or row["result_digest"] is not None
                or row["failure_class"] is not None
            ):
                raise AnchorProtocolError("anchor running state is inconsistent")
        else:
            if any(
                row[name] is not None
                for name in (
                    "lease_token_digest",
                    "lease_boot_id",
                    "deadline_monotonic_ns",
                    "lease_expires_at",
                )
            ):
                raise AnchorProtocolError("anchor terminal run retained a lease")
            if row["state"] == "COMMITTED" and (
                row["result_digest"] is None or row["failure_class"] is not None
            ):
                raise AnchorProtocolError("anchor committed run result is invalid")
            if row["state"] in {"FAILED_RETRYABLE", "FAILED_FINAL"} and (
                row["result_digest"] is not None
                or type(row["failure_class"]) is not str
                or not row["failure_class"]
            ):
                raise AnchorProtocolError("anchor failed run result is invalid")
        records.append(row)
        prior_canary = canary_id
    if complete_inventory and (
        {row["canary_id"] for row in attempts}
        != {row["canary_id"] for row in records}
    ):
        raise AnchorProtocolError("anchor attempt and run inventories differ")
    for row in records:
        observed = sorted(
            attempt["attempt"]
            for attempt in attempts
            if attempt["canary_id"] == row["canary_id"]
        )
        if observed != list(range(1, row["attempt_count"] + 1)):
            raise AnchorProtocolError("anchor run attempt history is not contiguous")
    return records


def _validate_event_chain(
    value: Any, *, base_count: int, base_tail: str | None,
    attempts: list[dict[str, Any]], runs: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if type(value) is not list:
        raise AnchorProtocolError("anchor event suffix is not a list")
    attempt_index = {
        (row["canary_id"], row["attempt"]): row for row in attempts
    }
    run_index = {row["canary_id"]: row for row in runs}
    prior = base_tail
    prior_observed: datetime | None = None
    expected_sequence = base_count + 1
    records: list[dict[str, Any]] = []
    for raw in value:
        row = _exact(raw, _ANCHOR_EVENT_RECORD_FIELDS, label="anchor event record")
        key = (row["canary_id"], row["attempt"])
        if (
            row["sequence"] != expected_sequence
            or row["prior_event_digest"] != prior
            or key not in attempt_index
            or row["canary_id"] not in run_index
            or row["event_type"]
            not in {
                "LEASE_ACQUIRED",
                "EXPIRED_LEASE_RECOVERED",
                "ACTION_STARTED",
                "ACTION_FAILED_RETRYABLE",
                "ACTION_FAILED_FINAL",
                "CANARY_COMMITTED",
            }
        ):
            raise AnchorProtocolError("anchor event suffix is not contiguous")
        for name in ("lease_token_digest", "detail_digest", "event_digest"):
            _require_digest(row[name], label=f"event {name}")
        _require_digest(row["prior_event_digest"], label="event prior", allow_none=True)
        observed = _parse_time(row["observed_at"], label="event observed_at")
        if prior_observed is not None and observed < prior_observed:
            raise AnchorProtocolError("anchor event time moved backwards")
        body = {
            "format": "local-authority-staged-canary-event/v1",
            **{name: row[name] for name in _ANCHOR_EVENT_RECORD_FIELDS if name != "event_digest"},
        }
        if row["event_digest"] != _digest(body):
            raise AnchorProtocolError("anchor event suffix digest is invalid")
        if row["event_type"] in {
            "LEASE_ACQUIRED",
            "EXPIRED_LEASE_RECOVERED",
            "ACTION_STARTED",
        } and row["detail_digest"] != attempt_index[key]["attempt_evidence_digest"]:
            raise AnchorProtocolError("anchor event attempt evidence is inconsistent")
        if row["event_type"] == "CANARY_COMMITTED" and (
            run_index[row["canary_id"]]["result_digest"] != row["detail_digest"]
        ):
            raise AnchorProtocolError("anchor committed event result is inconsistent")
        records.append(row)
        prior = row["event_digest"]
        prior_observed = observed
        expected_sequence += 1
    return records


def _validate_complete_run_histories(
    *, events: list[dict[str, Any]], attempts: list[dict[str, Any]],
    runs: list[dict[str, Any]],
) -> None:
    """Recheck the complete journal state machine from canonical evidence rows."""

    attempt_index = {
        (row["canary_id"], row["attempt"]): row for row in attempts
    }
    events_by_canary: dict[str, list[dict[str, Any]]] = {
        row["canary_id"]: [] for row in runs
    }
    for event in events:
        if event["canary_id"] not in events_by_canary:
            raise AnchorProtocolError("anchor event has no run lineage")
        events_by_canary[event["canary_id"]].append(event)
    for run in runs:
        canary_id = run["canary_id"]
        run_events = events_by_canary[canary_id]
        if not run_events:
            raise AnchorProtocolError("anchor run has no event lineage")
        by_attempt: dict[int, list[dict[str, Any]]] = {}
        for event in run_events:
            by_attempt.setdefault(event["attempt"], []).append(event)
        expected_attempts = set(range(1, run["attempt_count"] + 1))
        if set(by_attempt) != expected_attempts:
            raise AnchorProtocolError("anchor run event attempts are not contiguous")
        for attempt in range(1, run["attempt_count"] + 1):
            history = by_attempt[attempt]
            immutable_attempt = attempt_index[(canary_id, attempt)]
            if any(
                event["lease_token_digest"]
                != immutable_attempt["lease_token_digest"]
                for event in history
            ):
                raise AnchorProtocolError("anchor attempt changed lease identity")
            event_types = [event["event_type"] for event in history]
            if attempt == 1:
                prefix = ["LEASE_ACQUIRED"]
            elif event_types[0] == "EXPIRED_LEASE_RECOVERED":
                prefix = ["EXPIRED_LEASE_RECOVERED", "LEASE_ACQUIRED"]
            else:
                prefix = ["LEASE_ACQUIRED"]
            if event_types[: len(prefix)] != prefix:
                raise AnchorProtocolError("anchor attempt lacks one lease acquisition")
            suffix_types = event_types[len(prefix) :]
            if suffix_types and suffix_types[0] == "ACTION_STARTED":
                suffix_types = suffix_types[1:]
            if (
                len(suffix_types) > 1
                or suffix_types
                and suffix_types[0]
                not in {
                    "ACTION_FAILED_RETRYABLE",
                    "ACTION_FAILED_FINAL",
                    "CANARY_COMMITTED",
                }
            ):
                raise AnchorProtocolError("anchor attempt event history is invalid")
            if attempt < run["attempt_count"]:
                next_types = [
                    event["event_type"] for event in by_attempt[attempt + 1]
                ]
                recovered = next_types[0] == "EXPIRED_LEASE_RECOVERED"
                if recovered and suffix_types:
                    raise AnchorProtocolError(
                        "anchor recovered attempt was not stranded"
                    )
                if not recovered and suffix_types != ["ACTION_FAILED_RETRYABLE"]:
                    raise AnchorProtocolError(
                        "anchor retried attempt lacks retryable failure"
                    )

        last = run_events[-1]
        expected_tail = {
            "RUNNING": {"LEASE_ACQUIRED", "ACTION_STARTED"},
            "FAILED_RETRYABLE": {"ACTION_FAILED_RETRYABLE"},
            "FAILED_FINAL": {"ACTION_FAILED_FINAL"},
            "COMMITTED": {"CANARY_COMMITTED"},
        }
        if last["event_type"] not in expected_tail[run["state"]]:
            raise AnchorProtocolError("anchor run state lacks an exact event tail")
        if run["state"] in {"FAILED_RETRYABLE", "FAILED_FINAL"} and (
            last["detail_digest"]
            != _digest(str(run["failure_class"]).encode("ascii", "strict"))
        ):
            raise AnchorProtocolError("anchor failed run class changed")
        if run["state"] == "COMMITTED" and (
            last["detail_digest"] != run["result_digest"]
            or [
                event["event_type"]
                for event in by_attempt[run["attempt_count"]][-2:]
            ]
            != ["ACTION_STARTED", "CANARY_COMMITTED"]
        ):
            raise AnchorProtocolError("anchor committed run result is invalid")


def _validate_run_lineage(
    *, previous_runs: list[dict[str, Any]], previous_attempts: list[dict[str, Any]],
    current_runs: list[dict[str, Any]], current_attempts: list[dict[str, Any]],
    suffix: list[dict[str, Any]],
) -> None:
    """Require every mutable run transition and new attempt to have suffix evidence."""

    prior_run_index = {
        row["canary_id"]: row
        for row in _validate_run_records(previous_runs, attempts=previous_attempts)
    }
    current_run_index = {row["canary_id"]: row for row in current_runs}
    prior_attempt_keys = {
        (row["canary_id"], row["attempt"]) for row in previous_attempts
    }
    current_attempt_keys = {
        (row["canary_id"], row["attempt"]) for row in current_attempts
    }
    new_attempt_keys = current_attempt_keys - prior_attempt_keys
    suffix_by_canary: dict[str, list[dict[str, Any]]] = {}
    lease_keys: list[tuple[str, int]] = []
    expired_keys: list[tuple[str, int]] = []
    for event in suffix:
        suffix_by_canary.setdefault(event["canary_id"], []).append(event)
        key = (event["canary_id"], event["attempt"])
        if event["event_type"] == "LEASE_ACQUIRED":
            lease_keys.append(key)
        elif event["event_type"] == "EXPIRED_LEASE_RECOVERED":
            expired_keys.append(key)
    if len(lease_keys) != len(set(lease_keys)) or set(lease_keys) != new_attempt_keys:
        raise AnchorProtocolError(
            "anchor new attempt inventory lacks exact lease-acquired lineage"
        )
    if any(key not in new_attempt_keys for key in expired_keys):
        raise AnchorProtocolError("anchor recovery event does not introduce an attempt")

    immutable_identity = {
        "canary_id",
        "authority_id",
        "environment",
        "action",
        "source_sha",
        "runtime_bundle_digest",
    }
    for canary_id, current in current_run_index.items():
        previous = prior_run_index.get(canary_id)
        events = suffix_by_canary.get(canary_id, [])
        if previous is None:
            if not events or (
                events[0]["event_type"] != "LEASE_ACQUIRED"
                or events[0]["attempt"] != 1
            ):
                raise AnchorProtocolError("anchor new run lacks first lease lineage")
        else:
            if any(current[name] != previous[name] for name in immutable_identity):
                raise AnchorProtocolError("anchor run immutable identity changed")
            if previous["state"] in {"COMMITTED", "FAILED_FINAL"}:
                if current != previous or events:
                    raise AnchorProtocolError("anchor terminal run was rewritten")
                continue
            if not events:
                if current != previous:
                    raise AnchorProtocolError(
                        "anchor run changed without a suffix transition"
                    )
                continue
            if current["attempt_count"] < previous["attempt_count"] or (
                current["attempt_count"] - previous["attempt_count"]
                != sum(1 for key in new_attempt_keys if key[0] == canary_id)
            ):
                raise AnchorProtocolError("anchor run attempt count transition is invalid")
            if _parse_time(
                current["updated_at"], label="current run updated_at"
            ) < _parse_time(
                previous["updated_at"], label="previous run updated_at"
            ):
                raise AnchorProtocolError("anchor run update time rolled back")

        if not events:
            continue
        last = events[-1]
        expected_state = {
            "ACTION_FAILED_RETRYABLE": "FAILED_RETRYABLE",
            "ACTION_FAILED_FINAL": "FAILED_FINAL",
            "CANARY_COMMITTED": "COMMITTED",
        }.get(last["event_type"], "RUNNING")
        if current["state"] != expected_state:
            raise AnchorProtocolError("anchor run state lacks matching suffix evidence")
        if expected_state == "COMMITTED" and current["result_digest"] != last[
            "detail_digest"
        ]:
            raise AnchorProtocolError("anchor committed run digest changed")
        if expected_state in {"FAILED_RETRYABLE", "FAILED_FINAL"} and (
            _digest(str(current["failure_class"]).encode("ascii", "strict"))
            != last["detail_digest"]
        ):
            raise AnchorProtocolError("anchor failed run class changed")

    if set(prior_run_index) - set(current_run_index):
        raise AnchorProtocolError("anchor run inventory rolled back")


def _validate_snapshot(snapshot: Mapping[str, Any]) -> dict[str, Any]:
    value = _exact(snapshot, _SNAPSHOT_FIELDS, label="anchor journal snapshot")
    if value["format"] != _ANCHOR_SNAPSHOT_FORMAT:
        raise AnchorProtocolError("anchor journal snapshot format is invalid")
    candidate = _validate_anchor_candidate(value["candidate"])
    attempts = _validate_attempt_records(value["attempts"])
    runs = _validate_run_records(value["runs"], attempts=attempts)
    events = _validate_event_chain(
        value["events"], base_count=0, base_tail=None, attempts=attempts, runs=runs
    )
    _validate_complete_run_histories(events=events, attempts=attempts, runs=runs)
    attempt_summary = [
        {
            "canary_id": row["canary_id"],
            "attempt": row["attempt"],
            "attempt_evidence_digest": row["attempt_evidence_digest"],
        }
        for row in attempts
    ]
    if (
        len(events) != candidate["event_count"]
        or (events[-1]["event_digest"] if events else None)
        != candidate["tail_event_digest"]
        or len(attempts) != candidate["attempt_evidence_count"]
        or _digest(
            {"format": _ATTEMPT_EVIDENCE_SET_FORMAT, "attempts": attempt_summary}
        )
        != candidate["attempt_evidence_set_digest"]
        or _digest({"format": _ANCHOR_RUN_STATE_FORMAT, "runs": runs})
        != candidate["run_state_digest"]
    ):
        raise AnchorProtocolError("anchor snapshot does not rederive its candidate")
    return {
        "format": value["format"],
        "candidate": candidate,
        "events": events,
        "attempts": attempts,
        "runs": runs,
    }


def _build_lineage_proof(
    snapshot: Mapping[str, Any], *, previous_candidate: Mapping[str, Any] | None,
    previous_attempts: list[dict[str, Any]], previous_runs: list[dict[str, Any]],
    previous_events: list[dict[str, Any]],
    prior_anchor_digest: str | None,
) -> dict[str, Any]:
    snapshot_value = _validate_snapshot(snapshot)
    candidate = snapshot_value["candidate"]
    previous = (
        None if previous_candidate is None else _validate_anchor_candidate(previous_candidate)
    )
    base_count = 0 if previous is None else previous["event_count"]
    base_tail = None if previous is None else previous["tail_event_digest"]
    if previous is not None and (
        candidate["journal_instance_id"] != previous["journal_instance_id"]
        or candidate["environment_set"] != previous["environment_set"]
        or candidate["event_count"] < base_count
    ):
        raise AnchorProtocolError("anchor snapshot rolls back its accepted base")
    previous_attempt_index = {
        (row["canary_id"], row["attempt"]): row
        for row in _validate_attempt_records(previous_attempts)
    }
    previous_run_index = {
        row["canary_id"]: row
        for row in _validate_run_records(
            previous_runs,
            attempts=list(previous_attempt_index.values()),
        )
    }
    new_attempt_records = [
        row
        for row in snapshot_value["attempts"]
        if (row["canary_id"], row["attempt"]) not in previous_attempt_index
    ]
    changed_run_records = [
        row
        for row in snapshot_value["runs"]
        if previous_run_index.get(row["canary_id"]) != row
    ]
    proof = {
        "format": LINEAGE_PROOF_FORMAT,
        "journal_instance_id": candidate["journal_instance_id"],
        "environment_set": list(ENVIRONMENT_SET),
        "prior_anchor_digest": prior_anchor_digest,
        "prior_anchor_candidate_digest": (
            None if previous is None else _digest(previous)
        ),
        "base_event_count": base_count,
        "base_tail_event_digest": base_tail,
        "event_suffix": snapshot_value["events"][base_count:],
        "previous_attempt_evidence_set_digest": (
            None if previous is None else previous["attempt_evidence_set_digest"]
        ),
        "new_attempt_records": new_attempt_records,
        "changed_run_records": changed_run_records,
        "anchor_candidate_digest": _digest(candidate),
    }
    _verify_lineage_proof(
        proof,
        candidate=candidate,
        previous_candidate=previous,
        previous_attempts=previous_attempts,
        previous_runs=previous_runs,
        previous_events=previous_events,
        prior_anchor_digest=prior_anchor_digest,
    )
    return proof


def _verify_lineage_proof(
    proof: Mapping[str, Any], *, candidate: Mapping[str, Any],
    previous_candidate: Mapping[str, Any] | None,
    previous_attempts: list[dict[str, Any]], previous_runs: list[dict[str, Any]],
    previous_events: list[dict[str, Any]],
    prior_anchor_digest: str | None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    value = _exact(proof, _LINEAGE_PROOF_FIELDS, label="anchor lineage proof")
    candidate = _validate_anchor_candidate(candidate)
    previous = (
        None if previous_candidate is None else _validate_anchor_candidate(previous_candidate)
    )
    base_count = 0 if previous is None else previous["event_count"]
    base_tail = None if previous is None else previous["tail_event_digest"]
    if (
        value["format"] != LINEAGE_PROOF_FORMAT
        or value["journal_instance_id"] != candidate["journal_instance_id"]
        or value["environment_set"] != list(ENVIRONMENT_SET)
        or value["prior_anchor_digest"] != prior_anchor_digest
        or value["prior_anchor_candidate_digest"]
        != (None if previous is None else _digest(previous))
        or value["base_event_count"] != base_count
        or value["base_tail_event_digest"] != base_tail
        or value["previous_attempt_evidence_set_digest"]
        != (None if previous is None else previous["attempt_evidence_set_digest"])
        or value["anchor_candidate_digest"] != _digest(candidate)
    ):
        raise AnchorProtocolError("anchor lineage proof base is invalid")
    if (
        previous is not None
        and (
            candidate["journal_instance_id"] != previous["journal_instance_id"]
            or candidate["environment_set"] != previous["environment_set"]
            or candidate["event_count"] < base_count
            or candidate["attempt_evidence_count"]
            < previous["attempt_evidence_count"]
        )
    ):
        raise AnchorProtocolError("anchor lineage rollback or substitution rejected")
    retained_attempts = _validate_attempt_records(previous_attempts)
    retained_attempt_index = {
        (row["canary_id"], row["attempt"]): row
        for row in retained_attempts
    }
    retained_runs = _validate_run_records(
        previous_runs,
        attempts=retained_attempts,
    )
    retained_events = _validate_event_chain(
        previous_events,
        base_count=0,
        base_tail=None,
        attempts=retained_attempts,
        runs=retained_runs,
    )
    _validate_complete_run_histories(
        events=retained_events,
        attempts=retained_attempts,
        runs=retained_runs,
    )
    retained_attempt_summary = [
        {
            "canary_id": row["canary_id"],
            "attempt": row["attempt"],
            "attempt_evidence_digest": row["attempt_evidence_digest"],
        }
        for row in retained_attempts
    ]
    if previous is None:
        if retained_attempts or retained_runs or retained_events:
            raise AnchorProtocolError("anchor retained state lacks a prior candidate")
    elif (
        len(retained_events) != previous["event_count"]
        or (retained_events[-1]["event_digest"] if retained_events else None)
        != previous["tail_event_digest"]
        or len(retained_attempts) != previous["attempt_evidence_count"]
        or _digest(
            {
                "format": _ATTEMPT_EVIDENCE_SET_FORMAT,
                "attempts": retained_attempt_summary,
            }
        )
        != previous["attempt_evidence_set_digest"]
        or _digest({"format": _ANCHOR_RUN_STATE_FORMAT, "runs": retained_runs})
        != previous["run_state_digest"]
    ):
        raise AnchorProtocolError("anchor retained state disagrees with its candidate")

    new_attempts = _validate_attempt_records(value["new_attempt_records"])
    new_attempt_index = {
        (row["canary_id"], row["attempt"]): row for row in new_attempts
    }
    if set(new_attempt_index) & set(retained_attempt_index):
        raise AnchorProtocolError("anchor delta rewrote immutable attempt history")
    attempts = _validate_attempt_records(
        sorted(
            [*retained_attempts, *new_attempts],
            key=lambda row: (row["canary_id"], row["attempt"]),
        )
    )

    changed_runs = _validate_run_records(
        value["changed_run_records"],
        attempts=attempts,
        complete_inventory=False,
    )
    retained_run_index = {row["canary_id"]: row for row in retained_runs}
    changed_run_index = {row["canary_id"]: row for row in changed_runs}
    if any(
        retained_run_index.get(canary_id) == row
        for canary_id, row in changed_run_index.items()
    ):
        raise AnchorProtocolError("anchor changed-run delta is not minimal")
    merged_run_index = {**retained_run_index, **changed_run_index}
    runs = _validate_run_records(
        sorted(merged_run_index.values(), key=lambda row: row["canary_id"]),
        attempts=attempts,
    )
    suffix = _validate_event_chain(
        value["event_suffix"], base_count=base_count, base_tail=base_tail,
        attempts=attempts, runs=runs,
    )
    events = _validate_event_chain(
        [*previous_events, *suffix], base_count=0, base_tail=None,
        attempts=attempts, runs=runs,
    )
    if len(previous_events) != base_count:
        raise AnchorProtocolError("anchor authority event snapshot is inconsistent")
    _validate_run_lineage(
        previous_runs=previous_runs,
        previous_attempts=previous_attempts,
        current_runs=runs,
        current_attempts=attempts,
        suffix=suffix,
    )
    _validate_complete_run_histories(events=events, attempts=attempts, runs=runs)
    expected_event_count = base_count + len(suffix)
    expected_tail = suffix[-1]["event_digest"] if suffix else base_tail
    attempt_summary = [
        {
            "canary_id": row["canary_id"],
            "attempt": row["attempt"],
            "attempt_evidence_digest": row["attempt_evidence_digest"],
        }
        for row in attempts
    ]
    if not suffix and (
        candidate["event_count"] != base_count
        or candidate["tail_event_digest"] != base_tail
    ):
        raise AnchorProtocolError("anchor equal-height event fork rejected")
    if (
        candidate["event_count"] != expected_event_count
        or candidate["tail_event_sequence"]
        != (expected_event_count if expected_event_count else None)
        or candidate["tail_event_digest"] != expected_tail
        or candidate["attempt_evidence_count"] != len(attempts)
        or candidate["attempt_evidence_set_digest"]
        != _digest(
            {"format": _ATTEMPT_EVIDENCE_SET_FORMAT, "attempts": attempt_summary}
        )
        or candidate["run_state_digest"]
        != _digest({"format": _ANCHOR_RUN_STATE_FORMAT, "runs": runs})
    ):
        raise AnchorProtocolError("anchor lineage proof does not rederive candidate")
    return attempts, runs, events


def _challenge_request(
    candidate: Mapping[str, Any], *, client_key_id: str,
    client_private_key: Ed25519PrivateKey, request_nonce: str,
) -> dict[str, Any]:
    candidate = _validate_anchor_candidate(candidate)
    if _NONCE_RE.fullmatch(request_nonce) is None:
        raise AnchorProtocolError("challenge request nonce is invalid")
    body = {
        "format": CHALLENGE_REQUEST_FORMAT,
        "authority_id": AUTHORITY_ID,
        "journal_instance_id": candidate["journal_instance_id"],
        "environment_set": list(ENVIRONMENT_SET),
        "anchor_candidate_digest": _digest(candidate),
        "request_nonce": request_nonce,
        "client_key_id": _require_key_id(client_key_id, label="client key id"),
    }
    request_digest = _digest(body)
    return {
        **body,
        "challenge_request_digest": request_digest,
        "signature": _sign(client_private_key, body),
    }


def _validate_challenge_request(
    raw: bytes, *, client_keys: Mapping[str, Ed25519PublicKey]
) -> dict[str, Any]:
    value = _exact(
        _strict_json(raw, label="anchor challenge request"),
        _CHALLENGE_REQUEST_FIELDS,
        label="anchor challenge request",
    )
    body = _body(value, _CHALLENGE_REQUEST_BODY_FIELDS)
    key_id = _require_key_id(value["client_key_id"], label="client key id")
    if (
        value["format"] != CHALLENGE_REQUEST_FORMAT
        or value["authority_id"] != AUTHORITY_ID
        or type(value["journal_instance_id"]) is not str
        or _INSTANCE_RE.fullmatch(value["journal_instance_id"]) is None
        or value["environment_set"] != list(ENVIRONMENT_SET)
        or type(value["request_nonce"]) is not str
        or _NONCE_RE.fullmatch(value["request_nonce"]) is None
        or value["challenge_request_digest"] != _digest(body)
        or _require_digest(value["anchor_candidate_digest"], label="candidate digest")
        is None
        or key_id not in client_keys
    ):
        raise AnchorProtocolError("anchor challenge request identity drifted")
    _verify_signature(client_keys[key_id], value["signature"], body, label="challenge request")
    return value


def _validate_challenge(
    raw: bytes, *, registry: AnchorKeyRegistry,
    challenge_request: Mapping[str, Any], candidate: Mapping[str, Any],
    expected_generation: int, expected_prior_anchor_digest: str | None,
    now: datetime,
) -> dict[str, Any]:
    value = _exact(
        _strict_json(raw, label="anchor challenge"),
        _CHALLENGE_FIELDS,
        label="anchor challenge",
    )
    body = _body(value, _CHALLENGE_BODY_FIELDS)
    candidate = _validate_anchor_candidate(candidate)
    key_id = _require_key_id(value["remote_key_id"], label="remote key id")
    issued = _parse_time(value["issued_at"], label="challenge issued_at")
    expires = _parse_time(value["expires_at"], label="challenge expires_at")
    if (
        value["format"] != CHALLENGE_FORMAT
        or value["authority_id"] != AUTHORITY_ID
        or value["journal_instance_id"] != candidate["journal_instance_id"]
        or value["environment_set"] != list(ENVIRONMENT_SET)
        or value["anchor_candidate_digest"] != _digest(candidate)
        or value["challenge_request_digest"]
        != challenge_request["challenge_request_digest"]
        or type(value["nonce"]) is not str
        or _NONCE_RE.fullmatch(value["nonce"]) is None
        or type(value["generation"]) is not int
        or value["generation"] != expected_generation
        or value["prior_anchor_digest"] != expected_prior_anchor_digest
        or expires - issued != timedelta(seconds=60)
        or not (issued <= now < expires)
        or value["challenge_digest"] != _digest(body)
        or registry.authority_status != "ACTIVE"
        or key_id not in registry.keys
    ):
        raise AnchorProtocolError("anchor challenge lineage or freshness is invalid")
    _verify_signature(registry.keys[key_id], value["signature"], body, label="challenge")
    return value


def _commit_request(
    *, candidate: Mapping[str, Any], challenge: Mapping[str, Any],
    lineage_proof: Mapping[str, Any], client_key_id: str,
    client_private_key: Ed25519PrivateKey,
) -> dict[str, Any]:
    candidate = _validate_anchor_candidate(candidate)
    proof = _exact(
        lineage_proof, _LINEAGE_PROOF_FIELDS, label="anchor lineage proof"
    )
    body = {
        "format": COMMIT_REQUEST_FORMAT,
        "authority_id": AUTHORITY_ID,
        "journal_instance_id": candidate["journal_instance_id"],
        "environment_set": list(ENVIRONMENT_SET),
        "generation": challenge["generation"],
        "prior_anchor_digest": challenge["prior_anchor_digest"],
        "challenge_digest": challenge["challenge_digest"],
        "challenge_nonce": challenge["nonce"],
        "anchor_candidate": candidate,
        "anchor_candidate_digest": _digest(candidate),
        "lineage_proof": proof,
        "lineage_proof_digest": _digest(proof),
        "client_key_id": _require_key_id(client_key_id, label="client key id"),
    }
    return {
        **body,
        "commit_request_digest": _digest(body),
        "signature": _sign(client_private_key, body),
    }


def _validate_commit_request(
    raw: bytes, *, client_keys: Mapping[str, Ed25519PublicKey]
) -> dict[str, Any]:
    value = _exact(
        _strict_json(raw, label="anchor commit request"),
        _COMMIT_FIELDS,
        label="anchor commit request",
    )
    body = _body(value, _COMMIT_BODY_FIELDS)
    candidate = _validate_anchor_candidate(value["anchor_candidate"])
    proof = _exact(
        value["lineage_proof"], _LINEAGE_PROOF_FIELDS, label="anchor lineage proof"
    )
    key_id = _require_key_id(value["client_key_id"], label="client key id")
    if (
        value["format"] != COMMIT_REQUEST_FORMAT
        or value["authority_id"] != AUTHORITY_ID
        or value["journal_instance_id"] != candidate["journal_instance_id"]
        or value["environment_set"] != list(ENVIRONMENT_SET)
        or type(value["generation"]) is not int
        or value["generation"] < 1
        or _require_digest(
            value["prior_anchor_digest"], label="prior anchor", allow_none=True
        )
        != value["prior_anchor_digest"]
        or _require_digest(value["challenge_digest"], label="challenge digest") is None
        or type(value["challenge_nonce"]) is not str
        or _NONCE_RE.fullmatch(value["challenge_nonce"]) is None
        or value["anchor_candidate_digest"] != _digest(candidate)
        or value["lineage_proof_digest"] != _digest(proof)
        or proof["anchor_candidate_digest"] != value["anchor_candidate_digest"]
        or proof["prior_anchor_digest"] != value["prior_anchor_digest"]
        or value["commit_request_digest"] != _digest(body)
        or key_id not in client_keys
    ):
        raise AnchorProtocolError("anchor commit request identity drifted")
    _verify_signature(client_keys[key_id], value["signature"], body, label="commit request")
    return value


def _resolution_request(
    commit_request: Mapping[str, Any], *, request_nonce: str,
    client_key_id: str, client_private_key: Ed25519PrivateKey,
) -> dict[str, Any]:
    if type(request_nonce) is not str or _NONCE_RE.fullmatch(request_nonce) is None:
        raise AnchorProtocolError("anchor resolution request nonce is invalid")
    body = {
        "format": RESOLUTION_REQUEST_FORMAT,
        "authority_id": AUTHORITY_ID,
        "journal_instance_id": commit_request["journal_instance_id"],
        "environment_set": list(ENVIRONMENT_SET),
        "generation": commit_request["generation"],
        "prior_anchor_digest": commit_request["prior_anchor_digest"],
        "challenge_digest": commit_request["challenge_digest"],
        "commit_request_digest": commit_request["commit_request_digest"],
        "request_nonce": request_nonce,
        "client_key_id": _require_key_id(client_key_id, label="client key id"),
    }
    return {
        **body,
        "resolution_request_digest": _digest(body),
        "signature": _sign(client_private_key, body),
    }


def _validate_resolution_request(
    raw: bytes, *, client_keys: Mapping[str, Ed25519PublicKey]
) -> dict[str, Any]:
    value = _exact(
        _strict_json(raw, label="anchor resolution request"),
        _RESOLUTION_REQUEST_FIELDS,
        label="anchor resolution request",
    )
    body = _body(value, _RESOLUTION_REQUEST_BODY_FIELDS)
    key_id = _require_key_id(value["client_key_id"], label="client key id")
    if (
        value["format"] != RESOLUTION_REQUEST_FORMAT
        or value["authority_id"] != AUTHORITY_ID
        or type(value["journal_instance_id"]) is not str
        or _INSTANCE_RE.fullmatch(value["journal_instance_id"]) is None
        or value["environment_set"] != list(ENVIRONMENT_SET)
        or type(value["generation"]) is not int
        or value["generation"] < 1
        or type(value["request_nonce"]) is not str
        or _NONCE_RE.fullmatch(value["request_nonce"]) is None
        or value["resolution_request_digest"] != _digest(body)
        or _require_digest(
            value["prior_anchor_digest"], label="resolution prior anchor", allow_none=True
        ) is None
        and value["prior_anchor_digest"] is not None
        or _require_digest(
            value["challenge_digest"], label="resolution challenge digest"
        ) is None
        or _require_digest(
            value["commit_request_digest"], label="resolution commit digest"
        ) is None
        or key_id not in client_keys
    ):
        raise AnchorProtocolError("anchor resolution request identity drifted")
    _verify_signature(
        client_keys[key_id], value["signature"], body, label="resolution request"
    )
    return value


def _validate_resolution_response(
    raw: bytes, *, registry: AnchorKeyRegistry,
    resolution_request: Mapping[str, Any], challenge: Mapping[str, Any],
    commit_request: Mapping[str, Any], candidate: Mapping[str, Any], now: datetime,
) -> dict[str, Any]:
    value = _exact(
        _strict_json(raw, label="anchor resolution response"),
        _RESOLUTION_RESPONSE_FIELDS,
        label="anchor resolution response",
    )
    body = _body(value, _RESOLUTION_RESPONSE_BODY_FIELDS)
    key_id = _require_key_id(value["remote_key_id"], label="remote key id")
    resolved_at = _parse_time(value["resolved_at"], label="resolution resolved_at")
    if (
        value["format"] != RESOLUTION_RESPONSE_FORMAT
        or value["authority_id"] != AUTHORITY_ID
        or value["journal_instance_id"] != commit_request["journal_instance_id"]
        or value["environment_set"] != list(ENVIRONMENT_SET)
        or value["generation"] != commit_request["generation"]
        or value["prior_anchor_digest"] != commit_request["prior_anchor_digest"]
        or value["challenge_digest"] != commit_request["challenge_digest"]
        or value["commit_request_digest"]
        != commit_request["commit_request_digest"]
        or value["resolution_request_digest"]
        != resolution_request["resolution_request_digest"]
        or value["status"] not in {"ACCEPTED", "NOT_ACCEPTED"}
        or type(value["current_generation"]) is not int
        or value["current_generation"] < 0
        or resolved_at > now
        or resolved_at
        < _parse_time(challenge["issued_at"], label="challenge issued_at")
        or value["resolution_response_digest"] != _digest(body)
        or registry.authority_status != "ACTIVE"
        or key_id not in registry.keys
    ):
        raise AnchorProtocolError("anchor resolution response lineage is invalid")
    _verify_signature(
        registry.keys[key_id], value["signature"], body, label="resolution response"
    )
    if value["status"] == "ACCEPTED":
        if type(value["receipt"]) is not dict:
            raise AnchorProtocolError("accepted anchor resolution lacks a receipt")
        receipt = _validate_receipt(
            canonical_json_bytes(value["receipt"]),
            registry=registry,
            challenge=challenge,
            commit_request=commit_request,
            candidate=candidate,
            now=now,
        )
        if (
            value["current_generation"] != receipt["generation"]
            or value["current_anchor_digest"] != receipt["accepted_anchor_digest"]
        ):
            raise AnchorProtocolError("accepted anchor resolution state drifted")
    elif (
        value["receipt"] is not None
        or value["current_generation"] != commit_request["generation"] - 1
        or value["current_anchor_digest"] != commit_request["prior_anchor_digest"]
    ):
        raise AnchorProtocolError("negative anchor resolution is not CAS safe")
    return value


def _require_monotonic_candidate(
    previous: Mapping[str, Any] | None, current: Mapping[str, Any]
) -> None:
    current = _validate_anchor_candidate(current)
    if previous is None:
        return
    previous = _validate_anchor_candidate(previous)
    if (
        current["journal_instance_id"] != previous["journal_instance_id"]
        or current["environment_set"] != previous["environment_set"]
        or current["event_count"] < previous["event_count"]
        or current["attempt_evidence_count"] < previous["attempt_evidence_count"]
    ):
        raise AnchorProtocolError("anchor candidate rollback or substitution rejected")
    if current["event_count"] == previous["event_count"] and (
        current["tail_event_sequence"] != previous["tail_event_sequence"]
        or current["tail_event_digest"] != previous["tail_event_digest"]
    ):
        raise AnchorProtocolError("anchor candidate event-chain fork rejected")
    if current["attempt_evidence_count"] == previous["attempt_evidence_count"] and (
        current["attempt_evidence_set_digest"]
        != previous["attempt_evidence_set_digest"]
    ):
        raise AnchorProtocolError("anchor candidate attempt-set fork rejected")
    if (
        current["event_count"] == previous["event_count"]
        and current["attempt_evidence_count"] == previous["attempt_evidence_count"]
        and current["run_state_digest"] != previous["run_state_digest"]
    ):
        raise AnchorProtocolError("anchor candidate run-state fork rejected")

def _validate_receipt(
    raw: bytes, *, registry: AnchorKeyRegistry, challenge: Mapping[str, Any],
    commit_request: Mapping[str, Any], candidate: Mapping[str, Any], now: datetime,
) -> dict[str, Any]:
    value = _exact(
        _strict_json(raw, label="anchor receipt"),
        _RECEIPT_FIELDS,
        label="anchor receipt",
    )
    body = _body(value, _RECEIPT_BODY_FIELDS)
    accepted_record = _body(value, _ACCEPTED_ANCHOR_FIELDS)
    candidate = _validate_anchor_candidate(candidate)
    key_id = _require_key_id(value["remote_key_id"], label="remote key id")
    accepted_at = _parse_time(value["accepted_at"], label="receipt accepted_at")
    if (
        value["format"] != RECEIPT_FORMAT
        or value["authority_id"] != AUTHORITY_ID
        or value["journal_instance_id"] != candidate["journal_instance_id"]
        or value["environment_set"] != list(ENVIRONMENT_SET)
        or value["generation"] != challenge["generation"]
        or value["prior_anchor_digest"] != challenge["prior_anchor_digest"]
        or value["challenge_digest"] != challenge["challenge_digest"]
        or value["commit_request_digest"]
        != commit_request["commit_request_digest"]
        or value["anchor_candidate_digest"] != _digest(candidate)
        or value["lineage_proof_digest"] != commit_request["lineage_proof_digest"]
        or value["accepted_anchor_digest"] != _digest(accepted_record)
        or accepted_at < _parse_time(challenge["issued_at"], label="challenge issued_at")
        or accepted_at
        >= _parse_time(challenge["expires_at"], label="challenge expires_at")
        or accepted_at > now
        or value["receipt_digest"]
        != _digest({name: value[name] for name in _RECEIPT_FIELDS if name != "receipt_digest"})
        or registry.authority_status != "ACTIVE"
        or key_id not in registry.keys
    ):
        raise AnchorProtocolError("anchor receipt lineage is invalid")
    _verify_signature(registry.keys[key_id], value["signature"], body, label="receipt")
    return value
