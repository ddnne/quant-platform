"""Receipt trust root is verify-only; production minting stays PENDING."""

from __future__ import annotations

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
    ReceiptKeyConfigurationError,
    load_verify_keys,
    verify_receipt_signature,
)
from tests.receipt_test_support import (
    generate_test_receipt_keypair,
    write_test_receipt_registry,
)


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
    document = json.loads(committed_path.read_text(encoding="utf-8"))
    assert document["purpose"] == "receipt_verification"
    assert all(
        row.get("status") in {"active", "revoked"}
        for row in document["keys"]
    )
    active = [row for row in document["keys"] if row["status"] == "active"]
    assert active == []
    stat = committed_path.stat()
    loaded = crypto._load_verify_key_file(
        str(committed_path), stat.st_mtime_ns, stat.st_size
    )
    assert loaded == ()


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
    )
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    registry["keys"][0]["status"] = "revoked"
    registry_path.write_text(json.dumps(registry), encoding="utf-8")
    monkeypatch.setattr(crypto, "_PINNED_VERIFY_KEYS_PATH", registry_path)
    crypto._load_verify_key_file.cache_clear()
    _plant_host_pem(tmp_path, monkeypatch, private_pem=private_pem)
    monkeypatch.delenv("QUANT_RECEIPT_DISABLE_HOST_PEM", raising=False)

    with pytest.raises(ReceiptEvidenceAuthorityPending, match="PENDING"):
        _open_governed_receipt_service()
    assert load_verify_keys() == {}


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
    path.write_text(json.dumps(document), encoding="utf-8")
    stat = path.stat()
    with pytest.raises(ReceiptKeyConfigurationError, match="explicit active/revoked"):
        crypto._load_verify_key_file(str(path), stat.st_mtime_ns, stat.st_size)


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
