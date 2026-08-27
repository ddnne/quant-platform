"""Behavioral invariants for descriptor-relative protected authority reads."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from scripts.local_authority_files import (
    ProtectedAuthorityFileError,
    read_protected_authority_file,
)


def test_protected_read_binds_exact_inode_and_rejects_replacement(
    tmp_path: Path,
) -> None:
    protected = tmp_path / "runtime.json"
    protected.write_bytes(b'{"governed":true}')
    protected.chmod(0o444)
    first = read_protected_authority_file(
        protected,
        expected_owner_uids={os.geteuid()},
        allowed_modes={0o444},
        max_bytes=1024,
    )
    assert first.raw == b'{"governed":true}'

    replacement = tmp_path / "replacement.json"
    replacement.write_bytes(first.raw)
    replacement.chmod(0o444)
    replacement.replace(protected)
    with pytest.raises(ProtectedAuthorityFileError, match="unsafe or stale"):
        read_protected_authority_file(
            protected,
            expected_owner_uids={os.geteuid()},
            allowed_modes={0o444},
            max_bytes=1024,
            expected_observation=first.observation,
        )


def test_protected_read_rejects_file_links_and_linked_parent(tmp_path: Path) -> None:
    protected = tmp_path / "runtime.json"
    protected.write_bytes(b"governed")
    protected.chmod(0o444)
    hardlink = tmp_path / "hardlink.json"
    os.link(protected, hardlink)
    with pytest.raises(ProtectedAuthorityFileError, match="unsafe or stale"):
        read_protected_authority_file(
            protected,
            expected_owner_uids={os.geteuid()},
            allowed_modes={0o444},
            max_bytes=1024,
        )
    hardlink.unlink()

    linked_parent = tmp_path.parent / f"qp-linked-parent-{os.getpid()}"
    linked_parent.unlink(missing_ok=True)
    linked_parent.symlink_to(tmp_path, target_is_directory=True)
    try:
        with pytest.raises(ProtectedAuthorityFileError, match="parent"):
            read_protected_authority_file(
                linked_parent / protected.name,
                expected_owner_uids={os.geteuid()},
                allowed_modes={0o444},
                max_bytes=1024,
            )
    finally:
        linked_parent.unlink(missing_ok=True)
