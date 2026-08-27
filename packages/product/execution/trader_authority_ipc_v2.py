"""Unix peer authentication and immutable SCM_RIGHTS transport for Trader v2."""

from __future__ import annotations

import array
import fcntl
import os
import socket
import stat
import struct
import tempfile
from pathlib import Path

from execution.trader_webauthn_registry_v2 import ExactFourTraderAuthorityV2Error


def unix_peer_uid(channel: socket.socket) -> int:
    if type(channel) is not socket.socket or channel.family != socket.AF_UNIX:
        raise ExactFourTraderAuthorityV2Error(
            "Trader handoff requires an AF_UNIX socket"
        )
    getpeereid = getattr(channel, "getpeereid", None)
    if callable(getpeereid):
        try:
            uid, _gid = getpeereid()
        except OSError as exc:
            raise ExactFourTraderAuthorityV2Error(
                "cannot authenticate controlled execution peer"
            ) from exc
        return int(uid)
    option = getattr(socket, "SO_PEERCRED", None)
    if option is not None:
        try:
            raw = channel.getsockopt(
                socket.SOL_SOCKET,
                option,
                struct.calcsize("3i"),
            )
            _pid, uid, _gid = struct.unpack("3i", raw)
        except (OSError, struct.error) as exc:
            raise ExactFourTraderAuthorityV2Error(
                "cannot authenticate controlled execution peer"
            ) from exc
        return uid
    local_peercred = getattr(socket, "LOCAL_PEERCRED", None)
    if local_peercred is not None:
        try:
            raw = channel.getsockopt(0, local_peercred, 128)
            version, uid, group_count = struct.unpack_from("=IIh", raw, 0)
            if version != 0 or not 1 <= group_count <= 16:
                raise ValueError("Darwin peer credential group count is invalid")
        except (OSError, struct.error, ValueError) as exc:
            raise ExactFourTraderAuthorityV2Error(
                "Darwin AF_UNIX peer credentials are invalid"
            ) from exc
        return int(uid)
    raise ExactFourTraderAuthorityV2Error(
        "platform has no kernel Unix peer credential API"
    )


def open_immutable_handoff_descriptor(directory: Path, payload: bytes) -> int:
    """Materialize bytes as one unlinked O_RDONLY, CLOEXEC regular FD."""

    if (
        not isinstance(directory, Path)
        or not directory.is_absolute()
        or type(payload) is not bytes
        or not payload
    ):
        raise ExactFourTraderAuthorityV2Error(
            "Trader handoff descriptor inputs are invalid"
        )
    fd, name = tempfile.mkstemp(
        prefix="trader-handoff-",
        suffix=".json",
        dir=str(directory),
    )
    path = Path(name)
    readonly_fd: int | None = None
    try:
        offset = 0
        while offset < len(payload):
            written = os.write(fd, payload[offset:])
            if written <= 0:
                raise ExactFourTraderAuthorityV2Error(
                    "cannot materialize committed Trader handoff bytes"
                )
            offset += written
        os.fsync(fd)
        os.fchmod(fd, 0o400)
        os.close(fd)
        fd = -1
        readonly_fd = os.open(
            path,
            os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | os.O_NOFOLLOW,
        )
        os.unlink(path)
        flags = fcntl.fcntl(readonly_fd, fcntl.F_GETFL)
        descriptor_flags = fcntl.fcntl(readonly_fd, fcntl.F_GETFD)
        measured = os.fstat(readonly_fd)
        if (
            flags & os.O_ACCMODE != os.O_RDONLY
            or descriptor_flags & fcntl.FD_CLOEXEC == 0
            or not stat.S_ISREG(measured.st_mode)
            or measured.st_size != len(payload)
            or os.pread(readonly_fd, len(payload), 0) != payload
        ):
            raise ExactFourTraderAuthorityV2Error(
                "committed Trader handoff descriptor is not immutable/read-only"
            )
        result = readonly_fd
        readonly_fd = None
        return result
    finally:
        if fd >= 0:
            os.close(fd)
        if path.exists():
            path.unlink()
        if readonly_fd is not None:
            os.close(readonly_fd)


def send_descriptor_frame(
    channel: socket.socket,
    *,
    descriptor: int,
    canonical_request: bytes,
) -> None:
    if type(canonical_request) is not bytes or not canonical_request:
        raise ExactFourTraderAuthorityV2Error("Trader handoff frame is empty")
    frame = struct.pack("!I", len(canonical_request)) + canonical_request
    sent = channel.sendmsg(
        [frame],
        [
            (
                socket.SOL_SOCKET,
                socket.SCM_RIGHTS,
                array.array("i", [descriptor]),
            )
        ],
    )
    if sent != len(frame):
        raise ExactFourTraderAuthorityV2Error(
            "controlled execution handoff frame was not sent atomically"
        )


__all__ = [
    "open_immutable_handoff_descriptor",
    "send_descriptor_frame",
    "unix_peer_uid",
]
