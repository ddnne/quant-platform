"""Pytest never loads operator ~/.config receipt_signing_key.pem."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from research.readiness import _attestation_secret
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
    monkeypatch.delenv("QUANT_READINESS_HMAC_SECRET", raising=False)
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


def test_attestation_secret_ignores_host_pem_under_pytest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _plant_host_pem(tmp_path, monkeypatch)
    with pytest.raises(MassResearchDisabledError, match="HMAC secret not configured"):
        _attestation_secret()


def test_attestation_secret_env_still_works(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _plant_host_pem(tmp_path, monkeypatch)
    monkeypatch.setenv("QUANT_READINESS_HMAC_SECRET", "isolated-hmac")
    assert _attestation_secret() == b"isolated-hmac"


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

    secret = _attestation_secret()
    assert secret == hashlib.sha256(priv_pem + b"|readiness-v2").digest()
