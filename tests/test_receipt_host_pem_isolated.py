"""Receipt key resolution has no caller-spoofable test-runner branch."""

from __future__ import annotations

from pathlib import Path

import pytest

from research.readiness import (
    READINESS_PRIVATE_KEY_ENV,
    READINESS_SIGNING_KEY_ID_ENV,
    _load_ready_publication_signer_from_config,
)
from selection.budget_ledger import MassResearchDisabledError
from storage.receipt_crypto import generate_keypair, load_signing_key


def _plant_host_pem(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, bytes]:
    import storage.receipt_crypto as rc

    priv_pem, _, _ = generate_keypair(key_id="host-operator-v1")
    fake_home = tmp_path / "fake-home"
    pem_path = fake_home / ".config" / "quant-platform" / "receipt_signing_key.pem"
    pem_path.parent.mkdir(parents=True)
    pem_path.write_bytes(priv_pem)
    monkeypatch.setattr(rc, "PRIVATE_KEY_FILE", pem_path)
    monkeypatch.setattr(rc, "CONFIG_DIR", pem_path.parent)
    monkeypatch.setattr(Path, "home", lambda *args, **kwargs: fake_home)
    monkeypatch.delenv("QUANT_RECEIPT_SIGNING_KEY_PEM", raising=False)
    monkeypatch.delenv(READINESS_PRIVATE_KEY_ENV, raising=False)
    monkeypatch.delenv(READINESS_SIGNING_KEY_ID_ENV, raising=False)
    return pem_path, priv_pem


def test_explicit_operator_policy_can_disable_host_pem(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _plant_host_pem(tmp_path, monkeypatch)
    monkeypatch.setenv("QUANT_RECEIPT_DISABLE_HOST_PEM", "1")
    assert load_signing_key() is None


def test_load_signing_key_explicit_inject_still_works(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pem_path, priv_pem = _plant_host_pem(tmp_path, monkeypatch)
    monkeypatch.setenv("QUANT_RECEIPT_DISABLE_HOST_PEM", "1")
    assert load_signing_key() is None

    by_pem = load_signing_key(pem=priv_pem)
    assert by_pem is not None

    by_path = load_signing_key(path=pem_path)
    assert by_path is not None

    monkeypatch.setenv("QUANT_RECEIPT_SIGNING_KEY_PEM", priv_pem.decode("ascii"))
    by_env = load_signing_key()
    assert by_env is not None


def test_readiness_publisher_never_falls_back_to_receipt_pem(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _plant_host_pem(tmp_path, monkeypatch)
    monkeypatch.setenv(READINESS_SIGNING_KEY_ID_ENV, "readiness-v1")
    with pytest.raises(MassResearchDisabledError, match="dedicated readiness"):
        _load_ready_publication_signer_from_config()


def test_explicit_dedicated_readiness_key_file_works(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _pem_path, receipt_private_pem = _plant_host_pem(tmp_path, monkeypatch)
    readiness_private_pem, _, _ = generate_keypair(key_id="readiness-v1")
    assert readiness_private_pem != receipt_private_pem
    readiness_path = tmp_path / "readiness_signing_key.pem"
    readiness_path.write_bytes(readiness_private_pem)
    monkeypatch.setenv(READINESS_PRIVATE_KEY_ENV, str(readiness_path))
    monkeypatch.setenv(READINESS_SIGNING_KEY_ID_ENV, "readiness-v1")
    publisher = _load_ready_publication_signer_from_config()
    assert publisher.key_id == "readiness-v1"


def test_pytest_current_test_cannot_disable_host_pem(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pem_path, _priv_pem = _plant_host_pem(tmp_path, monkeypatch)
    monkeypatch.setenv("PYTEST_CURRENT_TEST", "caller-controlled")
    monkeypatch.delenv("QUANT_RECEIPT_DISABLE_HOST_PEM", raising=False)
    monkeypatch.delenv("QUANT_READINESS_DISABLE_HOST_PEM", raising=False)
    monkeypatch.setenv(READINESS_SIGNING_KEY_ID_ENV, "readiness-v1")

    key = load_signing_key()
    assert key is not None
    assert pem_path.is_file()

    with pytest.raises(MassResearchDisabledError, match="dedicated readiness"):
        _load_ready_publication_signer_from_config()
