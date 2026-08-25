#!/usr/bin/env python3
"""Encrypt and verify a Cloudflare D1 export without exposing key material."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import tempfile
from typing import BinaryIO

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes


MAGIC = b"QPDBENC1"
NONCE_BYTES = 12
TAG_BYTES = 16
KEY_BYTES = 32
CHUNK_BYTES = 4 * 1024 * 1024


def _digest_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(CHUNK_BYTES):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def generate_key(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(os.urandom(KEY_BYTES))
            handle.flush()
            os.fsync(handle.fileno())
    except BaseException:
        path.unlink(missing_ok=True)
        raise


def _load_key(path: Path) -> bytes:
    if not path.is_file() or path.is_symlink():
        raise ValueError("backup encryption key must be a regular file")
    if path.stat().st_mode & 0o077:
        raise ValueError("backup encryption key permissions must be 0600 or stricter")
    key = path.read_bytes()
    if len(key) != KEY_BYTES:
        raise ValueError("backup encryption key must contain exactly 32 raw bytes")
    return key


def _resolved_distinct(*paths: Path) -> None:
    resolved = [path.resolve() for path in paths]
    if len(resolved) != len(set(resolved)):
        raise ValueError("source, encrypted target, and key must be distinct files")


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _encrypt_stream(source: BinaryIO, target: BinaryIO, key: bytes) -> tuple[str, int]:
    nonce = os.urandom(NONCE_BYTES)
    encryptor = Cipher(algorithms.AES(key), modes.GCM(nonce)).encryptor()
    encryptor.authenticate_additional_data(MAGIC)
    target.write(MAGIC)
    target.write(nonce)
    plaintext_digest = hashlib.sha256()
    plaintext_bytes = 0
    while chunk := source.read(CHUNK_BYTES):
        plaintext_digest.update(chunk)
        plaintext_bytes += len(chunk)
        target.write(encryptor.update(chunk))
    target.write(encryptor.finalize())
    target.write(encryptor.tag)
    return "sha256:" + plaintext_digest.hexdigest(), plaintext_bytes


def verify_encrypted(path: Path, key_path: Path) -> dict[str, object]:
    _resolved_distinct(path, key_path)
    key = _load_key(key_path)
    size = path.stat().st_size
    header_bytes = len(MAGIC) + NONCE_BYTES
    if size < header_bytes + TAG_BYTES:
        raise ValueError("encrypted backup is truncated")
    plaintext_digest = hashlib.sha256()
    plaintext_bytes = 0
    with path.open("rb") as handle:
        if handle.read(len(MAGIC)) != MAGIC:
            raise ValueError("encrypted backup magic is invalid")
        nonce = handle.read(NONCE_BYTES)
        ciphertext_bytes = size - header_bytes - TAG_BYTES
        handle.seek(size - TAG_BYTES)
        tag = handle.read(TAG_BYTES)
        handle.seek(header_bytes)
        decryptor = Cipher(algorithms.AES(key), modes.GCM(nonce, tag)).decryptor()
        decryptor.authenticate_additional_data(MAGIC)
        remaining = ciphertext_bytes
        while remaining:
            chunk = handle.read(min(CHUNK_BYTES, remaining))
            if not chunk:
                raise ValueError("encrypted backup ciphertext is truncated")
            remaining -= len(chunk)
            plaintext = decryptor.update(chunk)
            plaintext_digest.update(plaintext)
            plaintext_bytes += len(plaintext)
        final = decryptor.finalize()
        plaintext_digest.update(final)
        plaintext_bytes += len(final)
    return {
        "format": "quant-platform-d1-backup/aes-256-gcm-v1",
        "cipher": "AES-256-GCM",
        "encrypted": True,
        "plaintext_bytes": plaintext_bytes,
        "plaintext_digest": "sha256:" + plaintext_digest.hexdigest(),
        "ciphertext_bytes": size,
        "ciphertext_digest": _digest_file(path),
        "verified": True,
    }


def encrypt_backup(
    source: Path,
    target: Path,
    key_path: Path,
    *,
    delete_source: bool = True,
) -> dict[str, object]:
    _resolved_distinct(source, target, key_path)
    if not source.is_file() or source.is_symlink():
        raise ValueError("D1 backup source must be a regular file")
    if target.exists():
        raise FileExistsError(f"encrypted backup target already exists: {target.name}")
    key = _load_key(key_path)
    target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    descriptor, temporary_name = tempfile.mkstemp(
        dir=target.parent,
        prefix=f".{target.name}.",
        suffix=".partial",
    )
    temporary = Path(temporary_name)
    os.chmod(temporary, 0o600)
    try:
        with source.open("rb") as source_handle, os.fdopen(descriptor, "wb") as target_handle:
            source_digest, source_bytes = _encrypt_stream(source_handle, target_handle, key)
            target_handle.flush()
            os.fsync(target_handle.fileno())
        # Authenticate the complete temporary ciphertext before it becomes the
        # durable target.  A verification failure leaves both the plaintext
        # source and target pathname untouched, so a retry cannot be blocked by
        # a corrupt artifact.
        observed = verify_encrypted(temporary, key_path)
        if (
            observed["plaintext_digest"] != source_digest
            or observed["plaintext_bytes"] != source_bytes
        ):
            raise ValueError("encrypted backup verification did not reproduce the source")
        os.replace(temporary, target)
        _fsync_directory(target.parent)
        if delete_source:
            source.unlink()
            _fsync_directory(source.parent)
        return observed
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)

    keygen = subparsers.add_parser("keygen")
    keygen.add_argument("key", type=Path)

    encrypt = subparsers.add_parser("encrypt")
    encrypt.add_argument("source", type=Path)
    encrypt.add_argument("target", type=Path)
    encrypt.add_argument("--key", type=Path, required=True)
    encrypt.add_argument(
        "--keep-source",
        action="store_true",
        help="retain the plaintext after verified encryption (unsafe opt-in)",
    )

    verify = subparsers.add_parser("verify")
    verify.add_argument("encrypted", type=Path)
    verify.add_argument("--key", type=Path, required=True)

    args = parser.parse_args(argv)
    if args.command == "keygen":
        generate_key(args.key)
        print(json.dumps({"created": True}))
        return 0
    if args.command == "encrypt":
        result = encrypt_backup(
            args.source,
            args.target,
            args.key,
            delete_source=not args.keep_source,
        )
    else:
        result = verify_encrypted(args.encrypted, args.key)
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
