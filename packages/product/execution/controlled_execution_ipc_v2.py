"""AF_UNIX peer and SCM_RIGHTS receive mechanics for Controlled v2."""

from __future__ import annotations

import array
import fcntl
import os
import socket
import stat
import struct

from execution.exact_four_codec import (
    ExactFourAuthorityPending,
)
from execution.controlled_execution_types_v2 import ControlledExecutionWriterV2Error

_MAX_FRAME_BYTES = 1024 * 1024
_MAX_HANDOFF_BYTES = 1024 * 1024


def _unix_peer_uid(channel: socket.socket) -> int:
    if type(channel) is not socket.socket or channel.family != socket.AF_UNIX:
        raise ControlledExecutionWriterV2Error(
            "controlled execution requires an exact AF_UNIX socket"
        )
    getpeereid = getattr(channel, "getpeereid", None)
    if callable(getpeereid):
        uid, _gid = getpeereid()
        return int(uid)
    if hasattr(socket, "SO_PEERCRED"):
        raw = channel.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12)
        _pid, uid, _gid = struct.unpack("3i", raw)
        return int(uid)
    local_peercred = getattr(socket, "LOCAL_PEERCRED", None)
    if local_peercred is not None:
        try:
            raw = channel.getsockopt(0, local_peercred, 128)
            version, uid, group_count = struct.unpack_from("=IIh", raw, 0)
            if version != 0 or not 1 <= group_count <= 16:
                raise ValueError("Darwin peer credential group count is invalid")
        except (OSError, struct.error, ValueError) as exc:
            raise ControlledExecutionWriterV2Error(
                "Darwin AF_UNIX peer credentials are invalid"
            ) from exc
        return int(uid)
    raise ExactFourAuthorityPending(
        "platform cannot authenticate AF_UNIX peer credentials"
    )


def _make_received_fd_close_on_exec(fd: int) -> None:
    try:
        os.set_inheritable(fd, False)
        if os.get_inheritable(fd):
            raise OSError("descriptor remains inheritable")
    except OSError as exc:
        raise ControlledExecutionWriterV2Error(
            "received Trader descriptor could not be made close-on-exec"
        ) from exc


def _recv_framed_request_with_one_fd(channel: socket.socket) -> tuple[bytes, int]:
    item_size = array.array("i").itemsize
    recv_flags = getattr(socket, "MSG_CMSG_CLOEXEC", 0)
    payload, ancillary, message_flags, _address = channel.recvmsg(
        _MAX_FRAME_BYTES + 4,
        socket.CMSG_SPACE(item_size * 2),
        recv_flags,
    )
    received: list[int] = []
    try:
        if message_flags & (socket.MSG_CTRUNC | socket.MSG_TRUNC):
            raise ControlledExecutionWriterV2Error(
                "Trader SCM_RIGHTS request was truncated"
            )
        for level, kind, data in ancillary:
            if level != socket.SOL_SOCKET or kind != socket.SCM_RIGHTS:
                raise ControlledExecutionWriterV2Error(
                    "unexpected ancillary capability on Trader handoff"
                )
            if len(data) % item_size:
                raise ControlledExecutionWriterV2Error(
                    "malformed Trader SCM_RIGHTS capability"
                )
            descriptors = array.array("i")
            descriptors.frombytes(data)
            for descriptor in descriptors.tolist():
                received.append(descriptor)
                _make_received_fd_close_on_exec(descriptor)
        if len(received) != 1:
            raise ControlledExecutionWriterV2Error(
                "Trader handoff requires exactly one descriptor"
            )
        while len(payload) < 4:
            chunk = channel.recv(4 - len(payload))
            if not chunk:
                raise ControlledExecutionWriterV2Error(
                    "Trader local-authority frame ended before its header"
                )
            payload += chunk
        declared = struct.unpack("!I", payload[:4])[0]
        if declared < 2 or declared > _MAX_FRAME_BYTES:
            raise ControlledExecutionWriterV2Error(
                "Trader local-authority frame length is invalid"
            )
        expected = 4 + declared
        if len(payload) > expected:
            raise ControlledExecutionWriterV2Error(
                "Trader connection contains more than one request frame"
            )
        while len(payload) < expected:
            chunk = channel.recv(expected - len(payload))
            if not chunk:
                raise ControlledExecutionWriterV2Error(
                    "Trader local-authority request frame is incomplete"
                )
            payload += chunk
        descriptor = received.pop()
        return payload[4:], descriptor
    finally:
        for descriptor in received:
            os.close(descriptor)


def _read_unlinked_readonly_descriptor(fd: int, *, expected_uid: int) -> bytes:
    before = os.fstat(fd)
    flags = fcntl.fcntl(fd, fcntl.F_GETFL)
    descriptor_flags = fcntl.fcntl(fd, fcntl.F_GETFD)
    if (
        flags & os.O_ACCMODE != os.O_RDONLY
        or descriptor_flags & fcntl.FD_CLOEXEC == 0
        or not stat.S_ISREG(before.st_mode)
        or stat.S_IMODE(before.st_mode) != 0o400
        or before.st_uid != expected_uid
        or before.st_nlink != 0
        or not 0 < before.st_size <= _MAX_HANDOFF_BYTES
    ):
        raise ControlledExecutionWriterV2Error(
            "Trader handoff descriptor is not an unlinked read-only authority file"
        )
    content = os.pread(fd, before.st_size, 0)
    after = os.fstat(fd)
    if (
        len(content) != before.st_size
        or (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
        != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
    ):
        raise ControlledExecutionWriterV2Error(
            "Trader handoff descriptor changed during controlled revalidation"
        )
    return content


__all__: list[str] = []
