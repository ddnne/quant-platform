"""Behavior tests for no-follow, FD-pinned authority file reads."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from execution.secure_authority_files_v2 import (
    SecureAuthorityFileV2Error,
    open_pinned_authority_file_v2,
    read_pinned_authority_file_v2,
)


def _tree(tmp_path: Path) -> tuple[Path, Path]:
    root = tmp_path / "trusted"
    root.mkdir(mode=0o700)
    authority = root / "authority"
    authority.mkdir(mode=0o700)
    source = authority / "activation.json"
    source.write_bytes(b'{"status":"PENDING"}')
    os.chmod(source, 0o400)
    return root, source


def _policy(root: Path) -> dict[str, object]:
    return {
        "chain_root": root,
        "directory_owner_uids": {os.geteuid()},
        "expected_file_uid": os.geteuid(),
        "allowed_file_modes": frozenset({0o400}),
    }


def test_fd_pinned_read_accepts_exact_chain_and_survives_path_replacement(
    tmp_path: Path,
) -> None:
    root, source = _tree(tmp_path)
    pinned = open_pinned_authority_file_v2(source, **_policy(root))  # type: ignore[arg-type]
    try:
        moved = source.with_suffix(".old")
        source.rename(moved)
        source.write_bytes(b"attacker replacement")
        assert pinned.read_bytes(max_bytes=1024) == b'{"status":"PENDING"}'
    finally:
        os.close(pinned.fd)


def test_symlink_file_or_directory_component_is_rejected(tmp_path: Path) -> None:
    root, source = _tree(tmp_path)
    file_link = source.with_name("activation-link.json")
    file_link.symlink_to(source)
    with pytest.raises(SecureAuthorityFileV2Error):
        read_pinned_authority_file_v2(
            file_link, max_bytes=1024, **_policy(root)  # type: ignore[arg-type]
        )
    linked_directory = root / "linked"
    linked_directory.symlink_to(source.parent, target_is_directory=True)
    with pytest.raises(SecureAuthorityFileV2Error):
        read_pinned_authority_file_v2(
            linked_directory / source.name,
            max_bytes=1024,
            **_policy(root),  # type: ignore[arg-type]
        )


def test_writable_directory_chain_is_rejected(tmp_path: Path) -> None:
    root, source = _tree(tmp_path)
    os.chmod(source.parent, 0o770)
    with pytest.raises(SecureAuthorityFileV2Error, match="directory chain"):
        read_pinned_authority_file_v2(
            source, max_bytes=1024, **_policy(root)  # type: ignore[arg-type]
        )


def test_mutation_during_pinned_lifetime_is_detected(tmp_path: Path) -> None:
    root, source = _tree(tmp_path)
    pinned = open_pinned_authority_file_v2(source, **_policy(root))  # type: ignore[arg-type]
    try:
        os.chmod(source, 0o600)
        source.write_bytes(b"changed authority bytes")
        with pytest.raises(SecureAuthorityFileV2Error, match="changed"):
            pinned.read_bytes(max_bytes=1024)
    finally:
        os.close(pinned.fd)
