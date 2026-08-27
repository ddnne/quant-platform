"""Environment-scoped READY public registry used by the local mint authority."""

from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path
from typing import Mapping

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from ops.trust_domain import require_environment


_ROOT = Path(__file__).resolve().parents[1]
_REGISTRIES = {
    "staging": (
        _ROOT / "specs/ready/readiness_verify_public_keys.staging.json",
        "sha256:30a7a04c4cca8ed96f0813423e1ceb049d4d80c36c0db62c01e327354e5c8aae",
    ),
    "production": (
        _ROOT / "specs/ready/readiness_verify_public_keys.json",
        "sha256:17c2978493dc3be0d72f3b94dbefd09aaff91c021f9e3d109464b6a7edcefa50",
    ),
}


class LocalReadyRegistryError(RuntimeError):
    pass


def ready_authority_instance_id(environment: str) -> str:
    selected = require_environment(environment)
    return f"ready-authority/{selected}/v1"


def _canonical(value: object) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def derive_ready_authority_resource_digest(
    *,
    environment: str,
    snapshot_id: str,
    immutable_db_digest: str,
    ready_manifest_digest: str,
    signed_projection_document_digest: str,
) -> str:
    selected = require_environment(environment)
    body = {
        "format": "ready-authority-resource/v1",
        "environment": selected,
        "authority_instance_id": ready_authority_instance_id(selected),
        "snapshot_id": snapshot_id,
        "immutable_db_digest": immutable_db_digest,
        "ready_manifest_digest": ready_manifest_digest,
        "signed_projection_document_digest": signed_projection_document_digest,
    }
    return "sha256:" + hashlib.sha256(_canonical(body)).hexdigest()


def load_scoped_ready_public_keys(
    *, expected_environment: str
) -> Mapping[tuple[str, str, str], Ed25519PublicKey]:
    selected = require_environment(expected_environment)
    path, expected_digest = _REGISTRIES[selected]
    try:
        document = json.loads(path.read_bytes())
    except (OSError, json.JSONDecodeError) as exc:
        raise LocalReadyRegistryError("READY registry is unavailable") from exc
    observed_digest = "sha256:" + hashlib.sha256(_canonical(document)).hexdigest()
    instance = ready_authority_instance_id(selected)
    if (
        type(document) is not dict
        or set(document)
        != {
            "schema_version",
            "purpose",
            "environment",
            "authority_instance_id",
            "keys",
        }
        or document.get("schema_version") != 2
        or document.get("purpose") != "readiness_attestation_verification"
        or document.get("environment") != selected
        or document.get("authority_instance_id") != instance
        or observed_digest != expected_digest
        or type(document.get("keys")) is not list
    ):
        raise LocalReadyRegistryError("READY registry trust domain is invalid")
    active: dict[tuple[str, str, str], Ed25519PublicKey] = {}
    seen: set[str] = set()
    for row in document["keys"]:
        if (
            type(row) is not dict
            or set(row) != {"key_id", "algorithm", "public_key_b64", "status"}
            or type(row.get("key_id")) is not str
            or not row["key_id"]
            or row["key_id"] in seen
            or row.get("algorithm") != "Ed25519"
            or row.get("status") not in {"active", "revoked"}
        ):
            raise LocalReadyRegistryError("READY registry key is invalid")
        seen.add(row["key_id"])
        try:
            public = Ed25519PublicKey.from_public_bytes(
                base64.b64decode(row["public_key_b64"], validate=True)
            )
        except (TypeError, ValueError) as exc:
            raise LocalReadyRegistryError("READY registry key is invalid") from exc
        if row["status"] == "active":
            active[(selected, instance, row["key_id"])] = public
    if len(active) > 1:
        raise LocalReadyRegistryError("READY registry has multiple active keys")
    return active


__all__ = [
    "LocalReadyRegistryError",
    "derive_ready_authority_resource_digest",
    "load_scoped_ready_public_keys",
    "ready_authority_instance_id",
]
