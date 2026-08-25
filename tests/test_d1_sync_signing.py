from __future__ import annotations

import base64
from copy import deepcopy
from datetime import datetime, timedelta, timezone
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
    return private, key_path, registry_path, registry


def _envelope(registry: dict, *, issued_at: datetime) -> dict:
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
        "source_schema_digest": "sha256:" + "e" * 64,
        "schema_digest": "sha256:" + "c" * 64,
        "table_counts": {"jquants_records": 1},
        "prior_audit_digest": None,
        "registry_digest": signing.d1_sync_digest(registry),
        "exported_at": issued_at.isoformat(),
        "issued_at": issued_at.isoformat(),
    }


def _signed_document(
    private: Ed25519PrivateKey,
    registry: dict,
    *,
    issued_at: datetime,
) -> dict:
    body = {
        "schema_version": signing.SIGNED_DOCUMENT_SCHEMA,
        "algorithm": "Ed25519",
        "issuer_key_id": "d1-sync-test-v1",
        "envelope": _envelope(registry, issued_at=issued_at),
    }
    return {
        **body,
        "signature": "ed25519:"
        + base64.b64encode(
            private.sign(signing.canonical_d1_sync_bytes(body))
        ).decode("ascii"),
    }


def test_d1_sync_authority_exposes_no_generic_mapping_signer(
    tmp_path, monkeypatch
):
    _private, _key_path, _registry_path, _registry = _install_key_registry(
        tmp_path, monkeypatch
    )
    assert tuple(
        inspect.signature(signing._preflight_d1_sync_signing_authority).parameters
    ) == ()
    assert signing._preflight_d1_sync_signing_authority() is None
    assert not hasattr(signing, "_load_pinned_d1_sync_signer")
    with pytest.raises(
        signing.D1SyncAuditError,
        match="authenticated Wrangler export capability",
    ):
        signing._seal_authenticated_wrangler_export(
            {"authority_id": signing.GOVERNED_AUTHORITY_ID}
        )


def test_pinned_verifier_accepts_current_closed_audit_and_rejects_tampering(
    tmp_path, monkeypatch
):
    private, _key_path, _registry_path, registry = _install_key_registry(
        tmp_path, monkeypatch
    )
    now = datetime(2026, 8, 25, 12, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(signing, "_utc_now", lambda: now)
    document = _signed_document(private, registry, issued_at=now)
    verified = signing.verify_signed_d1_sync_audit(document)
    assert verified["source_change_seq"] == verified["applied_change_seq"] == 7

    tampered = deepcopy(document)
    tampered["envelope"]["local_content_digest"] = "sha256:" + "d" * 64
    tampered["envelope"]["source_content_digest"] = "sha256:" + "d" * 64
    with pytest.raises(signing.D1SyncAuditError, match="signature is invalid"):
        signing.verify_signed_d1_sync_audit(tampered)


@pytest.mark.parametrize(
    ("offset", "message"),
    [
        (-signing.D1_SYNC_AUDIT_MAX_AGE_SECONDS - 1, "stale"),
        (signing.D1_SYNC_AUDIT_MAX_FUTURE_SKEW_SECONDS + 1, "future"),
    ],
)
def test_pinned_verifier_rejects_old_or_future_signed_audit(
    tmp_path, monkeypatch, offset, message
):
    private, _key_path, _registry_path, registry = _install_key_registry(
        tmp_path, monkeypatch
    )
    now = datetime(2026, 8, 25, 12, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(signing, "_utc_now", lambda: now)
    document = _signed_document(
        private,
        registry,
        issued_at=now + timedelta(seconds=offset),
    )
    with pytest.raises(signing.D1SyncAuditError, match=message):
        signing.verify_signed_d1_sync_audit(document)


@pytest.mark.parametrize("mutation", ["missing_status", "wrong_purpose", "two_active"])
def test_d1_sync_registry_requires_purpose_status_and_exactly_one_active(
    tmp_path, monkeypatch, mutation
):
    _private, _key_path, registry_path, registry = _install_key_registry(
        tmp_path, monkeypatch
    )
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
        signing._preflight_d1_sync_signing_authority()


def test_d1_sync_private_key_permissions_fail_closed(tmp_path, monkeypatch):
    _private, key_path, _registry_path, _registry = _install_key_registry(
        tmp_path, monkeypatch
    )
    key_path.chmod(0o644)
    with pytest.raises(signing.D1SyncAuditError, match="permissions"):
        signing._preflight_d1_sync_signing_authority()


def test_current_verifier_rejects_retired_and_revoked_keys_historical_does_not(
    tmp_path, monkeypatch
):
    private, _key_path, registry_path, registry = _install_key_registry(
        tmp_path, monkeypatch
    )
    now = datetime(2026, 8, 25, 12, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(signing, "_utc_now", lambda: now)
    document = _signed_document(private, registry, issued_at=now)
    assert signing.verify_signed_d1_sync_audit(document)["source_change_seq"] == 7

    replacement = Ed25519PrivateKey.generate()
    public = replacement.public_key().public_bytes(
        serialization.Encoding.Raw,
        serialization.PublicFormat.Raw,
    )
    retired = dict(registry)
    retired["keys"] = [
        {**registry["keys"][0], "status": "retired"},
        {
            "key_id": "d1-sync-test-v2",
            "algorithm": "Ed25519",
            "public_key_base64": base64.b64encode(public).decode("ascii"),
            "status": "active",
        },
    ]
    registry_path.write_text(json.dumps(retired), encoding="utf-8")
    with pytest.raises(signing.D1SyncAuditError, match="not active"):
        signing.verify_signed_d1_sync_audit(document)
    historical = signing._verify_signed_d1_sync_audit(
        document, require_fresh=False, eligibility="historical"
    )
    assert historical["source_change_seq"] == 7

    revoked = dict(retired)
    revoked["keys"] = [
        {**registry["keys"][0], "status": "revoked"},
        retired["keys"][1],
    ]
    registry_path.write_text(json.dumps(revoked), encoding="utf-8")
    with pytest.raises(signing.D1SyncAuditError, match="revoked"):
        signing._verify_signed_d1_sync_audit(
            document, require_fresh=False, eligibility="historical"
        )
    with pytest.raises(signing.D1SyncAuditError, match="not active"):
        signing.verify_signed_d1_sync_audit(document)
