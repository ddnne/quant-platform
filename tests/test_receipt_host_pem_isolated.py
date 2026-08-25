"""Receipt key resolution has no caller-spoofable test-runner branch."""

from __future__ import annotations

from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from research.readiness import (
    ReadinessPublicKeyRegistry,
    _load_pinned_ready_publication_signer,
)
from selection.budget_ledger import MassResearchDisabledError
from storage.receipt_crypto import (
    ReceiptKeyConfigurationError,
    load_signing_key,
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
    import storage.receipt_crypto as rc

    priv_pem = private_pem or generate_test_receipt_keypair(
        key_id="host-operator-v1"
    )[0]
    fake_home = tmp_path / "fake-home"
    pem_path = fake_home / ".config" / "quant-platform" / "receipt_signing_key.pem"
    pem_path.parent.mkdir(parents=True)
    pem_path.write_bytes(priv_pem)
    monkeypatch.setattr(rc, "PRIVATE_KEY_FILE", pem_path)
    monkeypatch.setattr(rc, "CONFIG_DIR", pem_path.parent)
    monkeypatch.setattr(Path, "home", lambda *args, **kwargs: fake_home)
    monkeypatch.delenv("QUANT_RECEIPT_SIGNING_KEY_PEM", raising=False)
    return pem_path, priv_pem


def test_explicit_operator_policy_can_disable_host_pem(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _plant_host_pem(tmp_path, monkeypatch)
    monkeypatch.setenv("QUANT_RECEIPT_DISABLE_HOST_PEM", "1")
    assert load_signing_key() is None


def test_production_signer_factory_is_argless_and_rejects_foreign_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pem_path, priv_pem = _plant_host_pem(tmp_path, monkeypatch)
    monkeypatch.setenv("QUANT_RECEIPT_DISABLE_HOST_PEM", "1")
    assert load_signing_key() is None

    with pytest.raises(TypeError, match="unexpected keyword argument 'pem'"):
        load_signing_key(pem=priv_pem)  # type: ignore[call-arg]
    with pytest.raises(TypeError, match="unexpected keyword argument 'path'"):
        load_signing_key(path=pem_path)  # type: ignore[call-arg]
    with pytest.raises(TypeError, match="unexpected keyword argument 'key_id'"):
        load_signing_key(key_id="attacker")  # type: ignore[call-arg]

    monkeypatch.setenv("QUANT_RECEIPT_SIGNING_KEY_PEM", priv_pem.decode("ascii"))
    with pytest.raises(ReceiptKeyConfigurationError, match="exactly one active"):
        load_signing_key()


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

    with pytest.raises(ReceiptKeyConfigurationError, match="exactly one active"):
        load_signing_key()
    with pytest.raises(TypeError, match="unexpected keyword argument 'path'"):
        load_verify_keys(path=attacker_registry)  # type: ignore[call-arg]
    with pytest.raises(TypeError, match="unexpected keyword argument 'extra'"):
        load_verify_keys(extra={key_id: public_raw})  # type: ignore[call-arg]
    with pytest.raises(TypeError, match="unexpected keyword argument 'verify_keys'"):
        verify_receipt_signature(  # type: ignore[call-arg]
            {}, verify_keys={key_id: object()}
        )


def test_production_signer_derives_id_from_exact_pinned_public_key(
    monkeypatch: pytest.MonkeyPatch, receipt_ed25519_keys
) -> None:
    monkeypatch.setenv(
        "QUANT_RECEIPT_SIGNING_KEY_PEM",
        receipt_ed25519_keys.private_pem.decode("ascii"),
    )
    monkeypatch.setenv("QUANT_RECEIPT_KEY_ID", "attacker-asserted-id")
    signing_key = load_signing_key()
    assert signing_key is not None
    assert signing_key.key_id == receipt_ed25519_keys.key_id


def test_readiness_publisher_never_falls_back_to_receipt_pem(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _plant_host_pem(tmp_path, monkeypatch)
    with pytest.raises(MassResearchDisabledError, match="dedicated readiness"):
        _load_pinned_ready_publication_signer()


def test_explicit_dedicated_readiness_key_file_works(
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
    registry = ReadinessPublicKeyRegistry(
        {"readiness-v1": readiness_key.public_key()}
    )
    monkeypatch.setattr(
        ReadinessPublicKeyRegistry,
        "load_pinned",
        classmethod(lambda cls: registry),
    )
    publisher = _load_pinned_ready_publication_signer()
    assert publisher.key_id == "readiness-v1"


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
    publisher = _load_pinned_ready_publication_signer()
    assert publisher.key_id == "pinned-readiness"


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

    key = load_signing_key()
    assert key is not None
    assert pem_path.is_file()

    with pytest.raises(MassResearchDisabledError, match="dedicated readiness"):
        _load_pinned_ready_publication_signer()
