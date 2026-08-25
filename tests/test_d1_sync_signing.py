from __future__ import annotations

import base64
from copy import deepcopy
from datetime import datetime, timezone
import inspect
import json

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from ops import d1_sync_signing as signing


def _install_key_registry(tmp_path, monkeypatch):
    private = Ed25519PrivateKey.generate()
    key_path = tmp_path / "d1-sync.pem"
    key_path.write_bytes(
        private.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    key_path.chmod(0o600)
    public = private.public_key().public_bytes(
        serialization.Encoding.Raw,
        serialization.PublicFormat.Raw,
    )
    registry = {
        "schema_version": 1,
        "purpose": "d1_sync_audit_verification",
        "keys": [
            {
                "key_id": "d1-sync-test-v1",
                "algorithm": "Ed25519",
                "public_key_base64": base64.b64encode(public).decode("ascii"),
                "status": "active",
            }
        ],
    }
    registry_path = tmp_path / "registry.json"
    registry_path.write_text(json.dumps(registry), encoding="utf-8")
    monkeypatch.setattr(signing, "DEFAULT_SIGNING_KEY_PATH", key_path)
    monkeypatch.setattr(signing, "DEFAULT_VERIFY_REGISTRY_PATH", registry_path)
    return key_path, registry_path, registry


def _envelope(signer):
    digest = "sha256:" + "a" * 64
    return {
        "schema_version": signing.AUDIT_ENVELOPE_SCHEMA,
        "authority_id": signing.GOVERNED_AUTHORITY_ID,
        "source_mode": "WRANGLER_REMOTE",
        "d1_name": signing.GOVERNED_D1_NAME,
        "d1_id": signing.GOVERNED_D1_ID,
        "sync_kind": "FULL",
        "export_digest": "sha256:" + "b" * 64,
        "artifact_format": "sql",
        "source_change_seq": 7,
        "applied_change_seq": 7,
        "source_content_digest": digest,
        "local_content_digest": digest,
        "schema_digest": "sha256:" + "c" * 64,
        "table_counts": {"jquants_records": 1},
        "prior_audit_digest": None,
        "registry_digest": signer._registry_digest,
        "issued_at": datetime.now(timezone.utc).isoformat(),
    }


def test_d1_sync_signer_has_no_caller_override_and_verifies_closed_audit(
    tmp_path, monkeypatch
):
    _install_key_registry(tmp_path, monkeypatch)
    assert tuple(inspect.signature(signing._load_pinned_d1_sync_signer).parameters) == ()
    signer = signing._load_pinned_d1_sync_signer()
    document = signer.sign(_envelope(signer))
    verified = signing.verify_signed_d1_sync_audit(document)
    assert verified["source_change_seq"] == verified["applied_change_seq"] == 7

    tampered = deepcopy(document)
    tampered["envelope"]["local_content_digest"] = "sha256:" + "d" * 64
    tampered["envelope"]["source_content_digest"] = "sha256:" + "d" * 64
    with pytest.raises(signing.D1SyncAuditError, match="signature is invalid"):
        signing.verify_signed_d1_sync_audit(tampered)


@pytest.mark.parametrize("mutation", ["missing_status", "wrong_purpose", "two_active"])
def test_d1_sync_registry_requires_purpose_status_and_exactly_one_active(
    tmp_path, monkeypatch, mutation
):
    _key_path, registry_path, registry = _install_key_registry(tmp_path, monkeypatch)
    if mutation == "missing_status":
        registry["keys"][0].pop("status")
    elif mutation == "wrong_purpose":
        registry["purpose"] = "ops_projection_verification"
    else:
        registry["keys"].append(
            {**registry["keys"][0], "key_id": "d1-sync-test-v2"}
        )
    registry_path.write_text(json.dumps(registry), encoding="utf-8")
    with pytest.raises(signing.D1SyncAuditError, match="registry"):
        signing._load_pinned_d1_sync_signer()


def test_d1_sync_private_key_permissions_fail_closed(tmp_path, monkeypatch):
    key_path, _registry_path, _registry = _install_key_registry(tmp_path, monkeypatch)
    key_path.chmod(0o644)
    with pytest.raises(signing.D1SyncAuditError, match="permissions"):
        signing._load_pinned_d1_sync_signer()
