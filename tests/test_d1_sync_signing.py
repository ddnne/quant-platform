from __future__ import annotations

import base64
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sqlite3
from types import MappingProxyType

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from ops import d1_sync_signing as signing


ROOT = Path(__file__).resolve().parents[1]


def _write_and_pin_registry(registry_path, registry, monkeypatch) -> None:
    body = {key: value for key, value in registry.items() if key != "registry_digest"}
    registry["registry_digest"] = signing.d1_sync_digest(body)
    registry_path.write_text(json.dumps(registry), encoding="utf-8")
    monkeypatch.setattr(signing, "_PINNED_VERIFY_REGISTRY_PATH", registry_path)
    monkeypatch.setattr(
        signing, "PINNED_D1_SYNC_REGISTRY_GENERATION", registry["generation"]
    )
    monkeypatch.setattr(
        signing,
        "PINNED_D1_SYNC_PRIOR_REGISTRY_DIGEST",
        registry["prior_registry_digest"],
    )
    monkeypatch.setattr(
        signing,
        "PINNED_D1_SYNC_REGISTRY_BODY_DIGEST",
        registry["registry_digest"],
    )
    monkeypatch.setattr(
        signing,
        "PINNED_D1_SYNC_REGISTRY_DOCUMENT_DIGEST",
        signing.d1_sync_digest(registry),
    )


def _install_external_key_registry(tmp_path, monkeypatch):
    """Install public verification material; keep the private key test-local."""
    private = Ed25519PrivateKey.generate()
    public = private.public_key().public_bytes(
        serialization.Encoding.Raw,
        serialization.PublicFormat.Raw,
    )
    registry = {
        "schema_version": 2,
        "purpose": "d1_sync_audit_verification",
        "generation": 2,
        "authority_status": "ACTIVE",
        "prior_registry_digest": "sha256:" + "9" * 64,
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
    _write_and_pin_registry(registry_path, registry, monkeypatch)
    return private, registry_path, registry


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


def _resign(private: Ed25519PrivateKey, document: dict) -> None:
    body = {key: value for key, value in document.items() if key != "signature"}
    document["signature"] = "ed25519:" + base64.b64encode(
        private.sign(signing.canonical_d1_sync_bytes(body))
    ).decode("ascii")


def test_committed_d1_registry_has_no_trusted_same_uid_authority() -> None:
    registry = json.loads(
        signing._PINNED_VERIFY_REGISTRY_PATH.read_text(encoding="utf-8")
    )
    assert registry["purpose"] == signing.REGISTRY_PURPOSE
    assert registry["authority_status"] == "PENDING"
    assert [row for row in registry["keys"] if row["status"] == "active"] == []
    assert all(row["status"] == "revoked" for row in registry["keys"])
    assert not hasattr(signing, "DEFAULT_VERIFY_REGISTRY_PATH")


def test_pinned_registry_binds_document_body_generation_and_prior_audit() -> None:
    current_path = ROOT / "specs/d1_sync/verify_public_keys.json"
    audit_path = ROOT / "specs/d1_sync/verify_public_keys.generation-1.json"
    current = json.loads(current_path.read_text(encoding="utf-8"))
    audit = json.loads(audit_path.read_text(encoding="utf-8"))
    assert current["generation"] == signing.PINNED_D1_SYNC_REGISTRY_GENERATION
    assert (
        current["prior_registry_digest"]
        == signing.PINNED_D1_SYNC_PRIOR_REGISTRY_DIGEST
        == signing.d1_sync_digest(audit)
    )
    assert (
        current["registry_digest"]
        == signing.PINNED_D1_SYNC_REGISTRY_BODY_DIGEST
        == signing.d1_sync_digest(
            {key: value for key, value in current.items() if key != "registry_digest"}
        )
    )
    assert (
        signing.d1_sync_digest(current)
        == signing.PINNED_D1_SYNC_REGISTRY_DOCUMENT_DIGEST
    )
    assert audit["purpose"] == "d1_sync_registry_audit"
    assert audit["authority_status"] == "REVOKED"


def test_same_uid_home_key_cannot_enable_preflight_or_sealing(
    tmp_path, monkeypatch
):
    private, _registry_path, _registry = _install_external_key_registry(
        tmp_path, monkeypatch
    )
    fake_home = tmp_path / "home"
    old_key_path = (
        fake_home / ".config" / "quant-platform" / "d1_sync_signing_key.pem"
    )
    old_key_path.parent.mkdir(parents=True)
    old_key_path.write_bytes(
        private.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    old_key_path.chmod(0o600)
    monkeypatch.setenv("HOME", str(fake_home))

    with pytest.raises(
        signing.D1SyncAuditError,
        match="full-source authority is not provisioned",
    ):
        signing._preflight_d1_sync_signing_authority()
    with pytest.raises(
        signing.D1SyncAuditError,
        match="full-source authority is not provisioned",
    ):
        signing._seal_authenticated_wrangler_export(
            {"authority_id": signing.GOVERNED_AUTHORITY_ID}
        )


def test_pinned_verifier_accepts_current_closed_audit_and_rejects_tampering(
    tmp_path, monkeypatch
):
    private, _registry_path, registry = _install_external_key_registry(
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


def test_verifier_rejects_a_signed_b_cursor_and_stateful_document(
    tmp_path, monkeypatch
):
    private, _registry_path, registry = _install_external_key_registry(
        tmp_path, monkeypatch
    )
    now = datetime(2026, 8, 25, 12, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(signing, "_utc_now", lambda: now)
    signed_a = _signed_document(private, registry, issued_at=now)
    unsigned_b = deepcopy(signed_a)
    unsigned_b["envelope"]["source_change_seq"] = 999
    unsigned_b["envelope"]["applied_change_seq"] = 999

    with pytest.raises(signing.D1SyncAuditError, match="signature is invalid"):
        signing.verify_signed_d1_sync_audit(unsigned_b)

    class StatefulDocument(dict):
        def __init__(self, first: dict, second: dict):
            super().__init__(second)
            self.first = first
            self.second = second
            self.observations = 0

        def items(self):
            self.observations += 1
            selected = self.first if self.observations == 1 else self.second
            return selected.items()

    attacker = StatefulDocument(signed_a, unsigned_b)
    with pytest.raises(signing.D1SyncAuditError, match="exact finite JSON"):
        signing.verify_signed_d1_sync_audit(attacker)
    assert attacker.observations == 0


def test_verifier_rejects_nested_and_scalar_subclasses(tmp_path, monkeypatch):
    private, _registry_path, registry = _install_external_key_registry(
        tmp_path, monkeypatch
    )
    now = datetime(2026, 8, 25, 12, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(signing, "_utc_now", lambda: now)

    class DictSubclass(dict):
        pass

    class ListSubclass(list):
        pass

    class StrSubclass(str):
        pass

    documents = []
    nested_mapping = _signed_document(private, registry, issued_at=now)
    nested_mapping["envelope"]["table_counts"] = DictSubclass(
        nested_mapping["envelope"]["table_counts"]
    )
    documents.append(nested_mapping)
    nested_list = _signed_document(private, registry, issued_at=now)
    nested_list["envelope"]["table_counts"] = ListSubclass([1])
    documents.append(nested_list)
    scalar = _signed_document(private, registry, issued_at=now)
    scalar["issuer_key_id"] = StrSubclass(scalar["issuer_key_id"])
    documents.append(scalar)
    documents.append(
        StrSubclass(json.dumps(_signed_document(private, registry, issued_at=now)))
    )

    for document in documents:
        with pytest.raises(signing.D1SyncAuditError, match="exact finite JSON"):
            signing.verify_signed_d1_sync_audit(document)


def test_verified_envelope_is_deep_immutable_and_retained_once(
    tmp_path, monkeypatch
):
    private, _registry_path, registry = _install_external_key_registry(
        tmp_path, monkeypatch
    )
    now = datetime(2026, 8, 25, 12, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(signing, "_utc_now", lambda: now)
    document = _signed_document(private, registry, issued_at=now)

    verified = signing.verify_signed_d1_sync_audit(document)
    document["envelope"]["source_change_seq"] = 999
    document["envelope"]["applied_change_seq"] = 999
    document["envelope"]["table_counts"]["jquants_records"] = 999

    assert isinstance(verified, MappingProxyType)
    assert isinstance(verified["table_counts"], MappingProxyType)
    assert verified["source_change_seq"] == verified["applied_change_seq"] == 7
    assert verified["table_counts"]["jquants_records"] == 1
    with pytest.raises(TypeError):
        verified["source_change_seq"] = 999
    with pytest.raises(TypeError):
        verified["table_counts"]["jquants_records"] = 999
    with pytest.raises(TypeError, match="exact dict"):
        signing.d1_sync_digest(verified)


def test_verified_d1_cursor_chain_reaches_sync_boundary_without_mutable_alias(
    tmp_path, monkeypatch
):
    from scripts import sync_d1_to_sqlite as sync

    private, _registry_path, registry = _install_external_key_registry(
        tmp_path, monkeypatch
    )
    now = datetime(2026, 8, 25, 12, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(signing, "_utc_now", lambda: now)
    document = _signed_document(private, registry, issued_at=now)
    counts = {table: 0 for table in sync.DEFAULT_TABLES}
    document["envelope"]["table_counts"] = counts
    _resign(private, document)
    envelope = document["envelope"]
    row = {
        "signed_evidence_json": json.dumps(document),
        "status": "COMPLETE",
        "audit_digest": signing.d1_sync_digest(document),
        "issuer_key_id": document["issuer_key_id"],
        "signature": document["signature"],
        "table_counts_json": json.dumps(counts),
        **{
            field: envelope[field]
            for field in (
                "export_digest",
                "artifact_format",
                "source_mode",
                "sync_kind",
                "source_change_seq",
                "applied_change_seq",
                "source_content_digest",
                "local_content_digest",
                "schema_digest",
                "authority_id",
                "prior_audit_digest",
            )
        },
    }
    with sqlite3.connect(":memory:") as conn:
        verified = sync._verified_sync_envelope_from_row(
            conn, row, recompute_local=False
        )
    document["envelope"]["source_change_seq"] = 999
    document["envelope"]["applied_change_seq"] = 999

    assert verified["source_change_seq"] == verified["applied_change_seq"] == 7
    assert (
        verified["registry_digest"]
        == signing.PINNED_D1_SYNC_REGISTRY_DOCUMENT_DIGEST
    )
    with pytest.raises(TypeError):
        verified["source_change_seq"] = 999

    valid_text = row["signed_evidence_json"]
    assert isinstance(valid_text, str)
    duplicate_text = valid_text.replace(
        '"schema_version": "d1-sync-signed-audit/v1",',
        '"schema_version": "attacker", "schema_version": "d1-sync-signed-audit/v1",',
        1,
    )
    duplicate_row = {**row, "signed_evidence_json": duplicate_text}
    with sqlite3.connect(":memory:") as conn:
        with pytest.raises(signing.D1SyncAuditError, match="duplicate key"):
            sync._verified_sync_envelope_from_row(
                conn, duplicate_row, recompute_local=False
            )

    class StatefulRow(dict):
        def items(self):
            raise AssertionError("stateful row must not be observed")

    with sqlite3.connect(":memory:") as conn:
        with pytest.raises(TypeError, match="exact dict"):
            sync._verified_sync_envelope_from_row(
                conn, StatefulRow(row), recompute_local=False
            )


def test_strict_json_rejects_duplicate_and_nonfinite_signed_documents(
    tmp_path, monkeypatch
):
    private, _registry_path, registry = _install_external_key_registry(
        tmp_path, monkeypatch
    )
    now = datetime(2026, 8, 25, 12, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(signing, "_utc_now", lambda: now)
    text = json.dumps(_signed_document(private, registry, issued_at=now))
    duplicate = text.replace(
        '"schema_version": "d1-sync-signed-audit/v1",',
        '"schema_version": "attacker", "schema_version": "d1-sync-signed-audit/v1",',
        1,
    )
    nonfinite = text.replace('"jquants_records": 1', '"jquants_records": NaN')

    with pytest.raises(signing.D1SyncAuditError, match="duplicate key"):
        signing.verify_signed_d1_sync_audit(duplicate)
    with pytest.raises(signing.D1SyncAuditError, match="non-finite"):
        signing.verify_signed_d1_sync_audit(nonfinite)


@pytest.mark.parametrize("location", ["document", "envelope", "table_counts"])
def test_signed_d1_schema_is_closed(tmp_path, monkeypatch, location):
    private, _registry_path, registry = _install_external_key_registry(
        tmp_path, monkeypatch
    )
    now = datetime(2026, 8, 25, 12, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(signing, "_utc_now", lambda: now)
    document = _signed_document(private, registry, issued_at=now)
    if location == "document":
        document["unsigned_extra"] = "attacker"
    elif location == "envelope":
        document["envelope"]["unsigned_extra"] = "attacker"
    else:
        document["envelope"]["table_counts"][""] = 1
        _resign(private, document)

    message = "shape" if location == "document" else "fields|table counts"
    with pytest.raises(signing.D1SyncAuditError, match=message):
        signing.verify_signed_d1_sync_audit(document)


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
    private, _registry_path, registry = _install_external_key_registry(
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


def test_freshness_is_rechecked_at_final_verified_return(tmp_path, monkeypatch):
    private, _registry_path, registry = _install_external_key_registry(
        tmp_path, monkeypatch
    )
    issued_at = datetime(2026, 8, 25, 12, 0, tzinfo=timezone.utc)
    clock = {
        "now": issued_at + timedelta(seconds=signing.D1_SYNC_AUDIT_MAX_AGE_SECONDS)
    }
    monkeypatch.setattr(signing, "_utc_now", lambda: clock["now"])
    load_registry = signing._load_registry_document

    def advance_while_verifying():
        registry_document = load_registry()
        clock["now"] += timedelta(seconds=1)
        return registry_document

    monkeypatch.setattr(
        signing, "_load_registry_document", advance_while_verifying
    )
    document = _signed_document(private, registry, issued_at=issued_at)

    with pytest.raises(signing.D1SyncAuditError, match="stale"):
        signing.verify_signed_d1_sync_audit(document)


@pytest.mark.parametrize("mutation", ["missing_status", "wrong_purpose", "two_active"])
def test_d1_sync_registry_rejects_invalid_shape_or_multiple_active_keys(
    tmp_path, monkeypatch, mutation
):
    private, registry_path, registry = _install_external_key_registry(
        tmp_path, monkeypatch
    )
    now = datetime(2026, 8, 25, 12, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(signing, "_utc_now", lambda: now)
    document = _signed_document(private, registry, issued_at=now)
    if mutation == "missing_status":
        registry["keys"][0].pop("status")
    elif mutation == "wrong_purpose":
        registry["purpose"] = "ops_projection_verification"
    else:
        registry["keys"].append(
            {**registry["keys"][0], "key_id": "d1-sync-test-v2"}
        )
    _write_and_pin_registry(registry_path, registry, monkeypatch)
    document = _signed_document(private, registry, issued_at=now)
    with pytest.raises(signing.D1SyncAuditError, match="registry"):
        signing.verify_signed_d1_sync_audit(document)


@pytest.mark.parametrize("field", ["schema_version", "generation"])
def test_d1_sync_registry_rejects_float_integer_fields(
    tmp_path, monkeypatch, field
):
    private, registry_path, registry = _install_external_key_registry(
        tmp_path, monkeypatch
    )
    now = datetime(2026, 8, 25, 12, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(signing, "_utc_now", lambda: now)
    registry[field] = 2.0
    _write_and_pin_registry(registry_path, registry, monkeypatch)
    document = _signed_document(private, registry, issued_at=now)

    with pytest.raises(signing.D1SyncAuditError, match="registry policy"):
        signing.verify_signed_d1_sync_audit(document)


def test_attacker_path_and_legacy_public_global_cannot_replace_registry(
    tmp_path, monkeypatch
):
    private, registry_path, registry = _install_external_key_registry(
        tmp_path, monkeypatch
    )
    now = datetime(2026, 8, 25, 12, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(signing, "_utc_now", lambda: now)
    document = _signed_document(private, registry, issued_at=now)

    attacker = deepcopy(registry)
    attacker["purpose"] = "attacker_selected_verification"
    attacker["registry_digest"] = signing.d1_sync_digest(
        {key: value for key, value in attacker.items() if key != "registry_digest"}
    )
    attacker_path = tmp_path / "attacker-registry.json"
    attacker_path.write_text(json.dumps(attacker), encoding="utf-8")

    monkeypatch.setattr(
        signing, "DEFAULT_VERIFY_REGISTRY_PATH", attacker_path, raising=False
    )
    assert signing.verify_signed_d1_sync_audit(document)["source_change_seq"] == 7

    monkeypatch.setattr(signing, "_PINNED_VERIFY_REGISTRY_PATH", attacker_path)
    with pytest.raises(signing.D1SyncAuditError, match="digest mismatch"):
        signing.verify_signed_d1_sync_audit(document)
    assert registry_path != attacker_path


def test_registry_strict_decoder_rejects_duplicate_canonical_collision(
    tmp_path, monkeypatch
):
    private, registry_path, registry = _install_external_key_registry(
        tmp_path, monkeypatch
    )
    now = datetime(2026, 8, 25, 12, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(signing, "_utc_now", lambda: now)
    document = _signed_document(private, registry, issued_at=now)
    duplicate = registry_path.read_text(encoding="utf-8").replace(
        '"schema_version": 2,',
        '"schema_version": 1, "schema_version": 2,',
        1,
    )
    duplicate_path = tmp_path / "duplicate-registry.json"
    duplicate_path.write_text(duplicate, encoding="utf-8")
    monkeypatch.setattr(signing, "_PINNED_VERIFY_REGISTRY_PATH", duplicate_path)

    with pytest.raises(signing.D1SyncAuditError, match="cannot load"):
        signing.verify_signed_d1_sync_audit(document)


def test_zero_active_revoked_registry_rejects_current_and_backdated_history(
    tmp_path, monkeypatch
):
    private, registry_path, registry = _install_external_key_registry(
        tmp_path, monkeypatch
    )
    now = datetime(2020, 1, 2, 12, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(signing, "_utc_now", lambda: now)
    document = _signed_document(private, registry, issued_at=now)
    registry["keys"][0]["status"] = "revoked"
    registry["authority_status"] = "PENDING"
    _write_and_pin_registry(registry_path, registry, monkeypatch)
    document = _signed_document(private, registry, issued_at=now)

    with pytest.raises(signing.D1SyncAuditError, match="not active"):
        signing.verify_signed_d1_sync_audit(document)
    with pytest.raises(signing.D1SyncAuditError, match="revoked"):
        signing._verify_signed_d1_sync_audit(
            document, require_fresh=False, eligibility="historical"
        )


def test_current_verifier_rejects_retired_and_revoked_keys_historical_does_not(
    tmp_path, monkeypatch
):
    private, registry_path, registry = _install_external_key_registry(
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
    _write_and_pin_registry(registry_path, retired, monkeypatch)
    retired_document = _signed_document(private, retired, issued_at=now)
    with pytest.raises(signing.D1SyncAuditError, match="not active"):
        signing.verify_signed_d1_sync_audit(retired_document)
    historical = signing._verify_signed_d1_sync_audit(
        retired_document, require_fresh=False, eligibility="historical"
    )
    assert historical["source_change_seq"] == 7

    revoked = dict(retired)
    revoked["keys"] = [
        {**registry["keys"][0], "status": "revoked"},
        retired["keys"][1],
    ]
    _write_and_pin_registry(registry_path, revoked, monkeypatch)
    revoked_document = _signed_document(private, revoked, issued_at=now)
    with pytest.raises(signing.D1SyncAuditError, match="revoked"):
        signing._verify_signed_d1_sync_audit(
            revoked_document, require_fresh=False, eligibility="historical"
        )
    with pytest.raises(signing.D1SyncAuditError, match="not active"):
        signing.verify_signed_d1_sync_audit(revoked_document)
