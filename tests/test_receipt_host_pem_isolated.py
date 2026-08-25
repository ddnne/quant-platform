"""Pytest never loads operator ~/.config receipt_signing_key.pem."""

from __future__ import annotations

from pathlib import Path

import pytest

from research.readiness import (
    READINESS_PRIVATE_KEY_ENV,
    ReadinessAttestationPublisher,
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
    return pem_path, priv_pem


def test_load_signing_key_ignores_host_pem_under_pytest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _plant_host_pem(tmp_path, monkeypatch)
    assert load_signing_key() is None


def test_load_signing_key_explicit_inject_still_works(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pem_path, priv_pem = _plant_host_pem(tmp_path, monkeypatch)
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
    with pytest.raises(MassResearchDisabledError, match="dedicated readiness"):
        ReadinessAttestationPublisher.from_config(key_id="readiness-v1")


def test_explicit_dedicated_readiness_key_file_works(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _pem_path, receipt_private_pem = _plant_host_pem(tmp_path, monkeypatch)
    readiness_private_pem, _, _ = generate_keypair(key_id="readiness-v1")
    assert readiness_private_pem != receipt_private_pem
    readiness_path = tmp_path / "readiness_signing_key.pem"
    readiness_path.write_bytes(readiness_private_pem)
    monkeypatch.setenv(READINESS_PRIVATE_KEY_ENV, str(readiness_path))
    publisher = ReadinessAttestationPublisher.from_config(key_id="readiness-v1")
    assert publisher.key_id == "readiness-v1"


def test_host_pem_used_when_not_under_pytest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pem_path, priv_pem = _plant_host_pem(tmp_path, monkeypatch)
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.delenv("QUANT_RECEIPT_DISABLE_HOST_PEM", raising=False)
    monkeypatch.delenv("QUANT_READINESS_DISABLE_HOST_PEM", raising=False)

    key = load_signing_key()
    assert key is not None
    assert pem_path.is_file()

    with pytest.raises(MassResearchDisabledError, match="dedicated readiness"):
        ReadinessAttestationPublisher.from_config(key_id="readiness-v1")
