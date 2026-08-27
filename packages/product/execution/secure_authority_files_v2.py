"""FD-pinned, no-symlink reads through a validated directory chain."""

from __future__ import annotations

import fcntl
import os
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


class SecureAuthorityFileV2Error(OSError):
    """A file or one of its path components was not an authority-owned object."""


@dataclass(frozen=True, slots=True)
class PinnedAuthorityFileV2:
    fd: int
    size: int
    uid: int
    mode: int
    identity: tuple[int, int, int, int]

    def read_bytes(self, *, max_bytes: int) -> bytes:
        if self.size <= 0 or self.size > max_bytes:
            raise SecureAuthorityFileV2Error(
                "authority file size is empty or exceeds its bound"
            )
        raw = os.pread(self.fd, self.size, 0)
        after = os.fstat(self.fd)
        identity = (
            after.st_dev,
            after.st_ino,
            after.st_size,
            after.st_mtime_ns,
        )
        if len(raw) != self.size or identity != self.identity:
            raise SecureAuthorityFileV2Error(
                "authority file changed during its pinned read"
            )
        return raw


def _open_directory_at(parent_fd: int, name: str) -> int:
    nofollow = getattr(os, "O_NOFOLLOW", 0)
    directory = getattr(os, "O_DIRECTORY", 0)
    if nofollow == 0 or directory == 0:
        raise SecureAuthorityFileV2Error(
            "platform lacks O_NOFOLLOW or O_DIRECTORY"
        )
    return os.open(
        name,
        os.O_RDONLY | os.O_CLOEXEC | nofollow | directory,
        dir_fd=parent_fd,
    )


def open_pinned_authority_file_v2(
    path: Path,
    *,
    chain_root: Path,
    directory_owner_uids: Iterable[int],
    expected_file_uid: int,
    allowed_file_modes: frozenset[int],
) -> PinnedAuthorityFileV2:
    """Open one absolute path through no-follow directory descriptors."""

    if (
        not isinstance(path, Path)
        or not path.is_absolute()
        or not isinstance(chain_root, Path)
        or not chain_root.is_absolute()
        or type(expected_file_uid) is not int
        or not allowed_file_modes
    ):
        raise SecureAuthorityFileV2Error("authority file policy is invalid")
    try:
        relative = path.relative_to(chain_root)
    except ValueError as exc:
        raise SecureAuthorityFileV2Error(
            "authority file is outside its trusted directory root"
        ) from exc
    parts = relative.parts
    if not parts or any(part in {"", ".", ".."} for part in parts):
        raise SecureAuthorityFileV2Error("authority file path is not canonical")
    owner_uids = frozenset(directory_owner_uids)
    if not owner_uids or any(type(uid) is not int or uid < 0 for uid in owner_uids):
        raise SecureAuthorityFileV2Error(
            "authority directory owner policy is invalid"
        )
    root_flags = os.O_RDONLY | os.O_CLOEXEC
    root_flags |= getattr(os, "O_DIRECTORY", 0)
    root_flags |= getattr(os, "O_NOFOLLOW", 0)
    directory_fds: list[int] = []
    file_fd: int | None = None
    try:
        root_fd = os.open(chain_root, root_flags)
        directory_fds.append(root_fd)
        root_metadata = os.fstat(root_fd)
        if (
            not stat.S_ISDIR(root_metadata.st_mode)
            or root_metadata.st_uid not in owner_uids
            or root_metadata.st_mode & 0o022
        ):
            raise SecureAuthorityFileV2Error(
                "trusted authority directory root ownership or mode is invalid"
            )
        current_fd = root_fd
        for component in parts[:-1]:
            next_fd = _open_directory_at(current_fd, component)
            directory_fds.append(next_fd)
            metadata = os.fstat(next_fd)
            if (
                not stat.S_ISDIR(metadata.st_mode)
                or metadata.st_uid not in owner_uids
                or metadata.st_mode & 0o022
            ):
                raise SecureAuthorityFileV2Error(
                    "authority directory chain ownership or mode is invalid"
                )
            current_fd = next_fd
        nofollow = getattr(os, "O_NOFOLLOW", 0)
        if nofollow == 0:
            raise SecureAuthorityFileV2Error("platform lacks O_NOFOLLOW")
        file_fd = os.open(
            parts[-1],
            os.O_RDONLY | os.O_CLOEXEC | nofollow,
            dir_fd=current_fd,
        )
        metadata = os.fstat(file_fd)
        descriptor_flags = fcntl.fcntl(file_fd, fcntl.F_GETFD)
        status_flags = fcntl.fcntl(file_fd, fcntl.F_GETFL)
        mode = stat.S_IMODE(metadata.st_mode)
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_uid != expected_file_uid
            or mode not in allowed_file_modes
            or status_flags & os.O_ACCMODE != os.O_RDONLY
            or descriptor_flags & fcntl.FD_CLOEXEC == 0
        ):
            raise SecureAuthorityFileV2Error(
                "authority file ownership, mode, or descriptor flags are invalid"
            )
        result = PinnedAuthorityFileV2(
            fd=file_fd,
            size=metadata.st_size,
            uid=metadata.st_uid,
            mode=mode,
            identity=(
                metadata.st_dev,
                metadata.st_ino,
                metadata.st_size,
                metadata.st_mtime_ns,
            ),
        )
        file_fd = None
        return result
    except OSError as exc:
        if isinstance(exc, SecureAuthorityFileV2Error):
            raise
        raise SecureAuthorityFileV2Error(
            "authority path could not be opened without following links"
        ) from exc
    finally:
        if file_fd is not None:
            os.close(file_fd)
        for descriptor in reversed(directory_fds):
            os.close(descriptor)


def read_pinned_authority_file_v2(
    path: Path,
    *,
    chain_root: Path,
    directory_owner_uids: Iterable[int],
    expected_file_uid: int,
    allowed_file_modes: frozenset[int],
    max_bytes: int,
) -> bytes:
    pinned = open_pinned_authority_file_v2(
        path,
        chain_root=chain_root,
        directory_owner_uids=directory_owner_uids,
        expected_file_uid=expected_file_uid,
        allowed_file_modes=allowed_file_modes,
    )
    try:
        return pinned.read_bytes(max_bytes=max_bytes)
    finally:
        os.close(pinned.fd)


__all__ = [
    "PinnedAuthorityFileV2",
    "SecureAuthorityFileV2Error",
    "open_pinned_authority_file_v2",
    "read_pinned_authority_file_v2",
]
