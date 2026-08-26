"""Receipt trust root is verify-only; production minting stays PENDING."""

from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from research.readiness import (
    ReadinessPublicKeyRegistry,
    ReadyPublicationAuthorityPending,
    require_ready_publication_authority,
)
from ingestion.runtime_authority import (
    ReceiptEvidenceAuthorityPending,
    _open_governed_receipt_service,
)
from storage.receipt_crypto import (
    PINNED_RECEIPT_AUTHORITY_STATUS as COMMITTED_AUTHORITY_STATUS,
    PINNED_RECEIPT_PRIOR_REGISTRY_DIGEST as COMMITTED_PRIOR_REGISTRY_DIGEST,
    PINNED_RECEIPT_REGISTRY_BODY_DIGEST as COMMITTED_REGISTRY_BODY_DIGEST,
    PINNED_RECEIPT_REGISTRY_DOCUMENT_DIGEST as COMMITTED_DOCUMENT_DIGEST,
    PINNED_RECEIPT_REGISTRY_GENERATION as COMMITTED_REGISTRY_GENERATION,
    PINNED_RECEIPT_REGISTRY_RAW_DIGEST as COMMITTED_RAW_DIGEST,
    ReceiptKeyConfigurationError,
    load_verify_keys,
    verify_receipt_signature,
    verify_receipt_signature_values,
    verify_receipt_signature_values_for_audit,
)
from tests.receipt_test_support import (
    generate_test_receipt_keypair,
    write_test_receipt_registry,
)


def _pin_test_registry(
    crypto: object,
    monkeypatch: pytest.MonkeyPatch,
    path: Path,
) -> None:
    raw = path.read_bytes()
    document = json.loads(raw)
    canonical = json.dumps(
        document,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8")
    monkeypatch.setattr(crypto, "_PINNED_VERIFY_KEYS_PATH", path)
    monkeypatch.setattr(
        crypto,
        "PINNED_RECEIPT_REGISTRY_RAW_DIGEST",
        "sha256:" + hashlib.sha256(raw).hexdigest(),
    )
    monkeypatch.setattr(
        crypto,
        "PINNED_RECEIPT_REGISTRY_DOCUMENT_DIGEST",
        "sha256:" + hashlib.sha256(canonical).hexdigest(),
    )
    monkeypatch.setattr(
        crypto,
        "PINNED_RECEIPT_REGISTRY_GENERATION",
        document["generation"],
    )
    monkeypatch.setattr(
        crypto,
        "PINNED_RECEIPT_AUTHORITY_STATUS",
        document["authority_status"],
    )
    monkeypatch.setattr(
        crypto,
        "PINNED_RECEIPT_PRIOR_REGISTRY_DIGEST",
        document["prior_registry_digest"],
    )
    monkeypatch.setattr(
        crypto,
        "PINNED_RECEIPT_REGISTRY_BODY_DIGEST",
        document["registry_digest"],
    )


def _rewrite_registry(path: Path, document: dict) -> None:
    import storage.receipt_crypto as crypto

    body = {key: value for key, value in document.items() if key != "registry_digest"}
    document["registry_digest"] = crypto.canonical_evidence_digest(body)
    path.write_text(json.dumps(document), encoding="utf-8")


def _plant_host_pem(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    private_pem: bytes | None = None,
) -> tuple[Path, bytes]:
    priv_pem = private_pem or generate_test_receipt_keypair(
        key_id="host-operator-v1"
    )[0]
    fake_home = tmp_path / "fake-home"
    pem_path = fake_home / ".config" / "quant-platform" / "receipt_signing_key.pem"
    pem_path.parent.mkdir(parents=True)
    pem_path.write_bytes(priv_pem)
    monkeypatch.setattr(Path, "home", lambda *args, **kwargs: fake_home)
    monkeypatch.delenv("QUANT_RECEIPT_SIGNING_KEY_PEM", raising=False)
    return pem_path, priv_pem


def test_home_and_environment_private_pem_cannot_open_receipt_authority(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pem_path, private_pem = _plant_host_pem(tmp_path, monkeypatch)
    monkeypatch.setenv(
        "QUANT_RECEIPT_SIGNING_KEY_PEM",
        private_pem.decode("ascii"),
    )
    with pytest.raises(ReceiptEvidenceAuthorityPending, match="PENDING"):
        _open_governed_receipt_service()
    assert pem_path.is_file()


def test_production_receipt_module_exposes_no_minting_primitive() -> None:
    import storage.receipt_crypto as crypto

    assert not hasattr(crypto, "ReceiptSigningKey")
    assert not hasattr(crypto, "load_signing_key")
    assert not hasattr(crypto, "build_signed_digest_fields")
    assert not hasattr(crypto, "Ed25519PrivateKey")


def test_verify_registry_env_and_loader_arguments_cannot_self_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    private_pem, public_raw, key_id = generate_test_receipt_keypair(
        key_id="attacker"
    )
    attacker_registry = write_test_receipt_registry(
        tmp_path / "attacker-registry.json",
        key_id=key_id,
        public_raw=public_raw,
    )
    monkeypatch.setenv("QUANT_RECEIPT_VERIFY_KEYS", str(attacker_registry))
    monkeypatch.setenv("QUANT_RECEIPT_KEY_ID", key_id)
    monkeypatch.setenv("QUANT_RECEIPT_SIGNING_KEY_PEM", private_pem.decode("ascii"))

    with pytest.raises(TypeError, match="unexpected keyword argument 'path'"):
        load_verify_keys(path=attacker_registry)  # type: ignore[call-arg]
    with pytest.raises(TypeError, match="unexpected keyword argument 'extra'"):
        load_verify_keys(extra={key_id: public_raw})  # type: ignore[call-arg]
    with pytest.raises(TypeError, match="unexpected keyword argument 'verify_keys'"):
        verify_receipt_signature(  # type: ignore[call-arg]
            {}, verify_keys={key_id: object()}
        )


def test_matching_pinned_test_key_still_cannot_enable_production_authority(
    monkeypatch: pytest.MonkeyPatch, receipt_ed25519_keys
) -> None:
    monkeypatch.setenv(
        "QUANT_RECEIPT_SIGNING_KEY_PEM",
        receipt_ed25519_keys.private_pem.decode("ascii"),
    )
    monkeypatch.setenv("QUANT_RECEIPT_KEY_ID", "attacker-asserted-id")
    with pytest.raises(ReceiptEvidenceAuthorityPending, match="PENDING"):
        _open_governed_receipt_service()


def test_committed_receipt_registry_has_no_current_signing_authority() -> None:
    import storage.receipt_crypto as crypto

    committed_path = (
        Path(crypto.__file__).resolve().parents[1]
        / "data_contracts"
        / "receipt_verify_public_keys.json"
    )
    committed_raw = committed_path.read_bytes()
    document = json.loads(committed_raw)
    schema_path = (
        Path(crypto.__file__).resolve().parents[3]
        / "specs"
        / "receipts"
        / "receipt_verify_public_keys.schema.json"
    )
    import jsonschema

    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    jsonschema.Draft202012Validator.check_schema(schema)
    jsonschema.Draft202012Validator(schema).validate(document)
    assert document["schema_version"] == 2
    assert document["purpose"] == "receipt_verification"
    assert crypto.body_digest(committed_raw) == COMMITTED_RAW_DIGEST
    assert crypto.canonical_evidence_digest(document) == COMMITTED_DOCUMENT_DIGEST
    assert document["generation"] == COMMITTED_REGISTRY_GENERATION == 2
    assert document["authority_status"] == COMMITTED_AUTHORITY_STATUS == "PENDING"
    body = {key: value for key, value in document.items() if key != "registry_digest"}
    assert (
        document["registry_digest"]
        == crypto.canonical_evidence_digest(body)
        == COMMITTED_REGISTRY_BODY_DIGEST
    )
    assert all(
        row.get("status") in {"active", "pending", "revoked"}
        for row in document["keys"]
    )
    active = [row for row in document["keys"] if row["status"] == "active"]
    assert active == []
    stat = committed_path.stat()
    loaded = crypto._load_verify_key_file(
        str(committed_path), stat.st_mtime_ns, stat.st_size
    )
    assert loaded == ()
    audit_keys = crypto._parse_audit_key_document(committed_raw)
    assert {row.key_id for row in audit_keys} == {
        "receipt-20260825-v1",
        "dev-receipt-v1",
        "phase61-test",
        "k1",
        "test-key",
        "t1",
    }

    prior_path = committed_path.with_name(
        "receipt_verify_public_keys.generation-1.json"
    )
    prior_raw = prior_path.read_bytes()
    prior = json.loads(prior_raw)
    assert crypto.body_digest(prior_raw) == (
        "sha256:de08e72ea133bf4ab876944e27520a5aa7207e7bdfee412b8866131b9e7b1c90"
    )
    assert (
        document["prior_registry_digest"]
        == crypto.canonical_evidence_digest(prior)
        == COMMITTED_PRIOR_REGISTRY_DIGEST
    )


def test_revoked_same_uid_key_cannot_reactivate_receipt_minting(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import storage.receipt_crypto as crypto

    private_pem, public_raw, key_id = generate_test_receipt_keypair(
        key_id="retired-same-uid"
    )
    registry_path = write_test_receipt_registry(
        tmp_path / "retired-registry.json",
        key_id=key_id,
        public_raw=public_raw,
        status="revoked",
    )
    _pin_test_registry(crypto, monkeypatch, registry_path)
    _plant_host_pem(tmp_path, monkeypatch, private_pem=private_pem)
    monkeypatch.delenv("QUANT_RECEIPT_DISABLE_HOST_PEM", raising=False)

    with pytest.raises(ReceiptEvidenceAuthorityPending, match="PENDING"):
        _open_governed_receipt_service()
    assert load_verify_keys() == {}


def test_revoked_receipt_key_is_cryptographic_audit_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import storage.receipt_crypto as crypto

    private_pem, public_raw, key_id = generate_test_receipt_keypair(
        key_id="revoked-audit-only"
    )
    registry_path = write_test_receipt_registry(
        tmp_path / "revoked-audit-registry.json",
        key_id=key_id,
        public_raw=public_raw,
        status="revoked",
    )
    _pin_test_registry(crypto, monkeypatch, registry_path)
    private = serialization.load_pem_private_key(private_pem, password=None)
    assert isinstance(private, Ed25519PrivateKey)
    body = b"historical receipt audit body"
    signature = "ed25519:" + base64.b64encode(private.sign(body)).decode("ascii")

    assert not verify_receipt_signature_values(
        body=body, signature=signature, key_id=key_id
    )
    assert verify_receipt_signature_values_for_audit(
        body=body, signature=signature, key_id=key_id
    )


def test_pending_authority_rejects_an_active_key(
    tmp_path: Path,
) -> None:
    import storage.receipt_crypto as crypto

    _private, public_raw, key_id = generate_test_receipt_keypair()
    path = write_test_receipt_registry(
        tmp_path / "pending-with-active.json",
        key_id=key_id,
        public_raw=public_raw,
    )
    document = json.loads(path.read_text(encoding="utf-8"))
    document["authority_status"] = "PENDING"
    _rewrite_registry(path, document)

    with pytest.raises(
        ReceiptKeyConfigurationError,
        match="active keys do not match authority status",
    ):
        crypto._load_verify_key_file(str(path))


def test_receipt_registry_body_digest_is_self_authenticating(
    tmp_path: Path,
) -> None:
    import storage.receipt_crypto as crypto

    _private, public_raw, key_id = generate_test_receipt_keypair()
    path = write_test_receipt_registry(
        tmp_path / "body-digest-tamper.json",
        key_id=key_id,
        public_raw=public_raw,
    )
    document = json.loads(path.read_text(encoding="utf-8"))
    document["keys"][0]["key_id"] += "-tampered"
    path.write_text(json.dumps(document), encoding="utf-8")

    with pytest.raises(ReceiptKeyConfigurationError, match="body digest mismatch"):
        crypto._load_verify_key_file(str(path))


@pytest.mark.parametrize(
    ("generation", "prior_registry_digest"),
    [
        (1, "sha256:" + "1" * 64),
        (2, None),
    ],
)
def test_receipt_registry_generation_requires_exact_prior_chain_shape(
    tmp_path: Path,
    generation: int,
    prior_registry_digest: str | None,
) -> None:
    import jsonschema
    import storage.receipt_crypto as crypto

    _private, public_raw, key_id = generate_test_receipt_keypair()
    path = write_test_receipt_registry(
        tmp_path / f"invalid-generation-{generation}.json",
        key_id=key_id,
        public_raw=public_raw,
    )
    document = json.loads(path.read_text(encoding="utf-8"))
    document["generation"] = generation
    document["prior_registry_digest"] = prior_registry_digest
    _rewrite_registry(path, document)
    schema_path = (
        Path(crypto.__file__).resolve().parents[3]
        / "specs"
        / "receipts"
        / "receipt_verify_public_keys.schema.json"
    )
    schema = json.loads(schema_path.read_text(encoding="utf-8"))

    with pytest.raises(jsonschema.ValidationError):
        jsonschema.Draft202012Validator(schema).validate(document)
    with pytest.raises(ReceiptKeyConfigurationError, match="registry is invalid"):
        crypto._load_verify_key_file(str(path))


def test_receipt_registry_schema_and_parser_reject_invalid_key_rows(
    tmp_path: Path,
) -> None:
    import jsonschema
    import storage.receipt_crypto as crypto

    _private, public_raw, key_id = generate_test_receipt_keypair()
    base_path = write_test_receipt_registry(
        tmp_path / "valid-row.json",
        key_id=key_id,
        public_raw=public_raw,
        status="pending",
    )
    base = json.loads(base_path.read_text(encoding="utf-8"))
    duplicate_pending = json.loads(json.dumps(base))
    duplicate_pending["keys"].append(
        {**duplicate_pending["keys"][0], "key_id": "second-pending"}
    )
    whitespace_id = json.loads(json.dumps(base))
    whitespace_id["keys"][0]["key_id"] = "   "
    malformed_public_key = json.loads(json.dumps(base))
    malformed_public_key["keys"][0]["public_key_base64"] = "x" * 44
    schema_path = (
        Path(crypto.__file__).resolve().parents[3]
        / "specs"
        / "receipts"
        / "receipt_verify_public_keys.schema.json"
    )
    validator = jsonschema.Draft202012Validator(
        json.loads(schema_path.read_text(encoding="utf-8"))
    )

    for index, document in enumerate(
        (duplicate_pending, whitespace_id, malformed_public_key)
    ):
        path = tmp_path / f"invalid-row-{index}.json"
        _rewrite_registry(path, document)
        with pytest.raises(jsonschema.ValidationError):
            validator.validate(document)
        with pytest.raises(ReceiptKeyConfigurationError):
            crypto._load_verify_key_file(str(path))


def test_pinned_receipt_registry_generation_chain_cannot_drift(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import storage.receipt_crypto as crypto

    _private, public_raw, key_id = generate_test_receipt_keypair()
    path = write_test_receipt_registry(
        tmp_path / "generation-chain.json",
        key_id=key_id,
        public_raw=public_raw,
    )
    _pin_test_registry(crypto, monkeypatch, path)
    monkeypatch.setattr(
        crypto,
        "PINNED_RECEIPT_REGISTRY_GENERATION",
        crypto.PINNED_RECEIPT_REGISTRY_GENERATION + 1,
    )

    with pytest.raises(
        ReceiptKeyConfigurationError, match="generation chain mismatch"
    ):
        load_verify_keys()


def test_receipt_registry_never_defaults_missing_status_to_active(
    tmp_path: Path,
) -> None:
    import storage.receipt_crypto as crypto

    _private, public_raw, key_id = generate_test_receipt_keypair()
    path = write_test_receipt_registry(
        tmp_path / "missing-status.json",
        key_id=key_id,
        public_raw=public_raw,
    )
    document = json.loads(path.read_text(encoding="utf-8"))
    document["keys"][0].pop("status")
    _rewrite_registry(path, document)
    stat = path.stat()
    with pytest.raises(ReceiptKeyConfigurationError, match="not closed"):
        crypto._load_verify_key_file(str(path), stat.st_mtime_ns, stat.st_size)


def test_receipt_registry_rejects_duplicate_json_keys_even_when_last_value_matches(
    tmp_path: Path,
) -> None:
    import storage.receipt_crypto as crypto

    _private, public_raw, key_id = generate_test_receipt_keypair()
    encoded = base64.b64encode(public_raw).decode("ascii")
    path = tmp_path / "duplicate.json"
    path.write_text(
        '{"schema_version":0,"schema_version":2,'
        '"purpose":"receipt_verification","generation":1,'
        '"authority_status":"ACTIVE","prior_registry_digest":null,"keys":[{'
        f'"key_id":"{key_id}","algorithm":"Ed25519",'
        f'"public_key_base64":"{encoded}","status":"active"'
        '}],"registry_digest":"sha256:' + '0' * 64 + '"}',
        encoding="utf-8",
    )
    with pytest.raises(ReceiptKeyConfigurationError, match="duplicate key"):
        crypto._load_verify_key_file(str(path))


def test_receipt_registry_same_stat_content_swap_cannot_reuse_cached_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import os
    import storage.receipt_crypto as crypto

    _private_a, public_a, key_id = generate_test_receipt_keypair(key_id="same-id")
    _private_b, public_b, _ = generate_test_receipt_keypair(key_id="same-id")
    path = write_test_receipt_registry(
        tmp_path / "registry.json", key_id=key_id, public_raw=public_a
    )
    _pin_test_registry(crypto, monkeypatch, path)
    assert set(load_verify_keys()) == {key_id}
    original_stat = path.stat()
    replacement = tmp_path / "replacement.json"
    write_test_receipt_registry(replacement, key_id=key_id, public_raw=public_b)
    assert replacement.stat().st_size == original_stat.st_size
    path.write_bytes(replacement.read_bytes())
    os.utime(
        path,
        ns=(original_stat.st_atime_ns, original_stat.st_mtime_ns),
    )
    with pytest.raises(ReceiptKeyConfigurationError, match="raw digest mismatch"):
        load_verify_keys()


def test_readiness_publisher_never_falls_back_to_receipt_pem(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _plant_host_pem(tmp_path, monkeypatch)
    with pytest.raises(ReadyPublicationAuthorityPending, match="PENDING"):
        require_ready_publication_authority()


def test_same_uid_readiness_key_file_cannot_enable_production_signer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _pem_path, receipt_private_pem = _plant_host_pem(tmp_path, monkeypatch)
    readiness_key = Ed25519PrivateKey.generate()
    readiness_private_pem = readiness_key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    assert readiness_private_pem != receipt_private_pem
    readiness_path = _pem_path.with_name("readiness_signing_key.pem")
    readiness_path.write_bytes(readiness_private_pem)
    with pytest.raises(ReadyPublicationAuthorityPending, match="PENDING"):
        require_ready_publication_authority()


def test_readiness_env_path_key_id_and_registry_cannot_self_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    receipt_path, _ = _plant_host_pem(tmp_path, monkeypatch)
    pinned_key = Ed25519PrivateKey.generate()
    pinned_path = receipt_path.with_name("readiness_signing_key.pem")
    pinned_path.write_bytes(
        pinned_key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    registry = ReadinessPublicKeyRegistry(
        {"pinned-readiness": pinned_key.public_key()}
    )
    monkeypatch.setattr(
        ReadinessPublicKeyRegistry,
        "load_pinned",
        classmethod(lambda cls: registry),
    )

    attacker_key = Ed25519PrivateKey.generate()
    attacker_path = tmp_path / "attacker-readiness.pem"
    attacker_path.write_bytes(
        attacker_key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    monkeypatch.setenv("QUANT_READINESS_SIGNING_KEY_FILE", str(attacker_path))
    monkeypatch.setenv("QUANT_READINESS_SIGNING_KEY_ID", "attacker")
    monkeypatch.setenv(
        "QUANT_READINESS_PUBLIC_KEY_REGISTRY", str(tmp_path / "attacker.json")
    )
    with pytest.raises(ReadyPublicationAuthorityPending, match="PENDING"):
        require_ready_publication_authority()


def test_pytest_current_test_cannot_disable_host_pem(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, receipt_ed25519_keys
) -> None:
    pem_path, _priv_pem = _plant_host_pem(
        tmp_path,
        monkeypatch,
        private_pem=receipt_ed25519_keys.private_pem,
    )
    monkeypatch.setenv("PYTEST_CURRENT_TEST", "caller-controlled")
    monkeypatch.delenv("QUANT_RECEIPT_DISABLE_HOST_PEM", raising=False)
    monkeypatch.delenv("QUANT_READINESS_DISABLE_HOST_PEM", raising=False)

    with pytest.raises(ReceiptEvidenceAuthorityPending, match="PENDING"):
        _open_governed_receipt_service()
    assert pem_path.is_file()

    with pytest.raises(ReadyPublicationAuthorityPending, match="PENDING"):
        require_ready_publication_authority()
