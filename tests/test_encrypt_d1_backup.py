from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
from cryptography.exceptions import InvalidTag


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts" / "encrypt_d1_backup.py"
SPEC = importlib.util.spec_from_file_location("encrypt_d1_backup", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
backup = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(backup)


def key(tmp_path: Path) -> Path:
    path = tmp_path / "backup.key"
    backup.generate_key(path)
    return path


def test_encrypt_verify_and_delete_only_after_success(tmp_path: Path) -> None:
    source = tmp_path / "quant-ingest.sql"
    source.write_bytes((b"INSERT INTO facts VALUES (1);\n" * 5000) + b"tail")
    encrypted = tmp_path / "quant-ingest.sql.enc"
    result = backup.encrypt_backup(source, encrypted, key(tmp_path), delete_source=True)
    assert result["verified"] is True
    assert result["plaintext_bytes"] > 0
    assert result["ciphertext_digest"].startswith("sha256:")
    assert not source.exists()
    assert encrypted.stat().st_mode & 0o777 == 0o600


def test_tamper_is_rejected(tmp_path: Path) -> None:
    source = tmp_path / "quant-ingest.sql"
    source.write_bytes(b"governed export")
    encrypted = tmp_path / "quant-ingest.sql.enc"
    key_path = key(tmp_path)
    backup.encrypt_backup(source, encrypted, key_path)
    raw = bytearray(encrypted.read_bytes())
    raw[len(backup.MAGIC) + backup.NONCE_BYTES] ^= 1
    encrypted.chmod(0o600)
    encrypted.write_bytes(raw)
    with pytest.raises(InvalidTag):
        backup.verify_encrypted(encrypted, key_path)


def test_key_permissions_and_target_overwrite_fail_closed(tmp_path: Path) -> None:
    source = tmp_path / "quant-ingest.sql"
    source.write_bytes(b"export")
    target = tmp_path / "quant-ingest.sql.enc"
    target.write_bytes(b"existing")
    key_path = key(tmp_path)
    with pytest.raises(FileExistsError):
        backup.encrypt_backup(source, target, key_path)

    key_path.chmod(0o644)
    target.unlink()
    with pytest.raises(ValueError, match="permissions"):
        backup.encrypt_backup(source, target, key_path)


def test_key_generation_refuses_overwrite(tmp_path: Path) -> None:
    key_path = key(tmp_path)
    original = key_path.read_bytes()
    with pytest.raises(FileExistsError):
        backup.generate_key(key_path)
    assert key_path.read_bytes() == original
