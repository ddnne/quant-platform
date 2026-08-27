"""Descriptor-relative protected file reads for local authority startup."""

from __future__ import annotations

import os
import stat
from collections.abc import Mapping, Set
from dataclasses import dataclass
from pathlib import Path


class ProtectedAuthorityFileError(RuntimeError):
    """A protected authority file could not be read without path races."""


@dataclass(frozen=True, slots=True)
class ProtectedAuthorityFile:
    raw: bytes
    observation: Mapping[str, int]


def stat_observation(info: os.stat_result) -> dict[str, int]:
    return {
        "device": int(info.st_dev),
        "inode": int(info.st_ino),
        "owner_uid": int(info.st_uid),
        "owner_gid": int(info.st_gid),
        "mode": stat.S_IMODE(info.st_mode),
        "nlink": int(info.st_nlink),
    }


def read_protected_authority_file(
    path: str | Path,
    *,
    expected_owner_uids: Set[int],
    allowed_modes: Set[int],
    max_bytes: int,
    expected_observation: Mapping[str, int] | None = None,
) -> ProtectedAuthorityFile:
    """Open through a directory FD, reject links, and bind one stable inode."""

    selected = Path(path)
    if (
        not selected.is_absolute()
        or not expected_owner_uids
        or any(type(uid) is not int or uid < 0 for uid in expected_owner_uids)
        or not allowed_modes
        or any(type(mode) is not int or mode < 0 for mode in allowed_modes)
        or type(max_bytes) is not int
        or max_bytes <= 0
    ):
        raise ProtectedAuthorityFileError("protected file policy is invalid")
    directory_flags = (
        os.O_RDONLY
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    file_flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(
        os, "O_NOFOLLOW", 0
    )
    try:
        directory_fd = os.open(selected.parent, directory_flags)
    except OSError as exc:
        raise ProtectedAuthorityFileError(
            "protected file parent is unavailable"
        ) from exc
    try:
        try:
            fd = os.open(selected.name, file_flags, dir_fd=directory_fd)
        except OSError as exc:
            raise ProtectedAuthorityFileError("protected file is unavailable") from exc
        try:
            before = os.fstat(fd)
            observation = stat_observation(before)
            if (
                not stat.S_ISREG(before.st_mode)
                or before.st_uid not in expected_owner_uids
                or stat.S_IMODE(before.st_mode) not in allowed_modes
                or before.st_nlink != 1
                or before.st_size <= 0
                or before.st_size > max_bytes
                or expected_observation is not None
                and observation != dict(expected_observation)
            ):
                raise ProtectedAuthorityFileError(
                    "protected file metadata is unsafe or stale"
                )
            chunks: list[bytes] = []
            remaining = before.st_size
            while remaining:
                chunk = os.read(fd, min(remaining, 1024 * 1024))
                if not chunk:
                    raise ProtectedAuthorityFileError(
                        "protected file was truncated while read"
                    )
                chunks.append(chunk)
                remaining -= len(chunk)
            after = os.fstat(fd)
            if (
                before.st_dev,
                before.st_ino,
                before.st_size,
                before.st_mtime_ns,
                before.st_ctime_ns,
                before.st_nlink,
            ) != (
                after.st_dev,
                after.st_ino,
                after.st_size,
                after.st_mtime_ns,
                after.st_ctime_ns,
                after.st_nlink,
            ):
                raise ProtectedAuthorityFileError(
                    "protected file changed while read"
                )
            return ProtectedAuthorityFile(
                raw=b"".join(chunks), observation=observation
            )
        finally:
            os.close(fd)
    finally:
        os.close(directory_fd)


__all__ = [
    "ProtectedAuthorityFile",
    "ProtectedAuthorityFileError",
    "read_protected_authority_file",
    "stat_observation",
]
