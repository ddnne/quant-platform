#!/usr/bin/env python3
"""Fail-closed runtime primitives for separately permissioned local authorities.

This module is deliberately deployment-neutral.  It provides the Unix-domain
transport, peer-credential authentication, exact manifest ACL, protected key
custody, and append-only event transaction required by the local authority
processes.  It does not activate an authority or update a public-key registry.
"""

from __future__ import annotations

import array
import base64
import fcntl
import hashlib
import json
import os
import pwd
import socket
import sqlite3
import stat
import struct
import sys
import threading
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from types import MappingProxyType
from typing import Any, NoReturn

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from scripts.authority_principal_manifest import load_and_validate_manifest
from scripts.finding_ledger_gate import (
    FindingLedgerError,
    require_pinned_finding_ledger_gate,
)

REQUEST_FORMAT = "local-authority-request/v1"
RESPONSE_FORMAT = "local-authority-response/v1"
LEDGER_SCHEMA_VERSION = 1
MAX_FRAME_BYTES = 4 * 1024 * 1024
MAX_FILE_DESCRIPTORS = 1
DEFAULT_IO_TIMEOUT_SECONDS = 5.0
DEFAULT_PROCESSING_TIMEOUT_SECONDS = 30.0
DEFAULT_ACCEPT_POLL_SECONDS = 0.5
DEFAULT_MAX_CONCURRENT_CONNECTIONS = 16


class LocalAuthorityError(RuntimeError):
    """A local authority boundary could not safely complete a request."""


class LocalAuthorityPending(LocalAuthorityError):
    """The declared authority has not been provisioned and activated."""


class PeerAuthenticationError(LocalAuthorityError):
    """The kernel-authenticated peer is absent or not authorized."""


class AuthorityLedgerError(LocalAuthorityError):
    """The append-only event ledger is unavailable, corrupt, or conflicting."""


def _copy_exact_json(value: Any, *, field: str) -> Any:
    if type(value) is dict:
        copied: dict[str, Any] = {}
        for key, item in value.items():
            if type(key) is not str or key in copied:
                raise LocalAuthorityError(f"{field} keys must be unique exact strings")
            copied[key] = _copy_exact_json(item, field=f"{field}.{key}")
        return copied
    if type(value) is list:
        return [
            _copy_exact_json(item, field=f"{field}[{index}]")
            for index, item in enumerate(value)
        ]
    if type(value) in {str, int, bool, type(None)}:
        return value
    raise LocalAuthorityError(
        f"{field} must contain only exact non-floating JSON built-ins"
    )


def canonical_json_bytes(value: Mapping[str, Any]) -> bytes:
    if type(value) is not dict:
        raise LocalAuthorityError("canonical authority input must be one exact dict")
    frozen = _copy_exact_json(value, field="canonical authority input")
    return json.dumps(
        frozen,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8")


def canonical_json_text(value: Mapping[str, Any]) -> str:
    return canonical_json_bytes(value).decode("utf-8")


def sha256_digest(value: Mapping[str, Any] | bytes) -> str:
    encoded = value if type(value) is bytes else canonical_json_bytes(value)
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def decode_strict_json(raw: bytes, *, field: str) -> dict[str, Any]:
    if type(raw) is not bytes or not raw or len(raw) > MAX_FRAME_BYTES:
        raise LocalAuthorityError(f"{field} has an invalid byte length")

    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise LocalAuthorityError(f"{field} contains duplicate key {key!r}")
            result[key] = value
        return result

    def reject_float(value: str) -> NoReturn:
        raise LocalAuthorityError(f"{field} contains forbidden float {value!r}")

    try:
        value = json.loads(
            raw,
            object_pairs_hook=reject_duplicates,
            parse_float=reject_float,
            parse_constant=reject_float,
        )
    except LocalAuthorityError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise LocalAuthorityError(f"{field} is invalid JSON") from exc
    frozen = _copy_exact_json(value, field=field)
    if type(frozen) is not dict:
        raise LocalAuthorityError(f"{field} must be an object")
    return frozen


def _utc_now_text() -> str:
    return datetime.now(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


@dataclass(frozen=True, slots=True)
class PeerIdentity:
    uid: int
    gid: int
    pid: int | None

    def __post_init__(self) -> None:
        if (
            type(self.uid) is not int
            or self.uid < 0
            or type(self.gid) is not int
            or self.gid < 0
            or self.pid is not None
            and (type(self.pid) is not int or self.pid <= 0)
        ):
            raise PeerAuthenticationError("kernel peer credentials are invalid")


def peer_identity(channel: socket.socket) -> PeerIdentity:
    """Read credentials from the connected Unix socket, never request JSON."""

    if type(channel) is not socket.socket or channel.family != socket.AF_UNIX:
        raise PeerAuthenticationError("authority transport must be an AF_UNIX socket")
    getpeereid = getattr(channel, "getpeereid", None)
    if callable(getpeereid):
        try:
            uid, gid = getpeereid()
        except OSError as exc:
            raise PeerAuthenticationError("getpeereid failed") from exc
        return PeerIdentity(uid=int(uid), gid=int(gid), pid=None)
    option = getattr(socket, "SO_PEERCRED", None)
    if option is not None:
        try:
            raw = channel.getsockopt(socket.SOL_SOCKET, option, struct.calcsize("3i"))
            pid, uid, gid = struct.unpack("3i", raw)
        except (OSError, struct.error) as exc:
            raise PeerAuthenticationError("SO_PEERCRED failed") from exc
        return PeerIdentity(uid=uid, gid=gid, pid=pid)
    local_peercred = getattr(socket, "LOCAL_PEERCRED", None)
    if local_peercred is not None:
        # Darwin exposes struct xucred at protocol level SOL_LOCAL (0) but the
        # Python socket module does not currently export SOL_LOCAL.
        try:
            raw = channel.getsockopt(0, local_peercred, 128)
            version, uid, group_count = struct.unpack_from("=IIh", raw, 0)
            if version != 0 or group_count <= 0 or group_count > 16:
                raise PeerAuthenticationError("LOCAL_PEERCRED identity is invalid")
            group_offset = 12  # xucred aligns the gid_t array to four bytes.
            if len(raw) < group_offset + group_count * 4:
                raise PeerAuthenticationError("LOCAL_PEERCRED identity is truncated")
            gid = struct.unpack_from("=I", raw, group_offset)[0]
        except (OSError, struct.error) as exc:
            raise PeerAuthenticationError("LOCAL_PEERCRED failed") from exc
        return PeerIdentity(uid=uid, gid=gid, pid=None)
    raise PeerAuthenticationError("platform has no supported Unix peer credentials")


@dataclass(frozen=True, slots=True)
class PeerPrincipalRegistry:
    """Exact UID-to-caller mapping provisioned outside request data."""

    callers_by_uid: Mapping[int, str]

    def __post_init__(self) -> None:
        normalized: dict[int, str] = {}
        for uid, caller in self.callers_by_uid.items():
            if (
                type(uid) is not int
                or uid < 0
                or type(caller) is not str
                or not caller
                or uid in normalized
            ):
                raise PeerAuthenticationError("peer principal registry is invalid")
            normalized[uid] = caller
        if not normalized:
            raise PeerAuthenticationError("peer principal registry is empty")
        object.__setattr__(self, "callers_by_uid", MappingProxyType(normalized))

    @classmethod
    def from_usernames(
        cls, callers_by_username: Mapping[str, str]
    ) -> PeerPrincipalRegistry:
        resolved: dict[int, str] = {}
        for username, caller in callers_by_username.items():
            if type(username) is not str or not username:
                raise PeerAuthenticationError("peer username is invalid")
            try:
                uid = pwd.getpwnam(username).pw_uid
            except KeyError as exc:
                raise LocalAuthorityPending(
                    f"peer service user is not provisioned: {username}"
                ) from exc
            if uid in resolved:
                raise PeerAuthenticationError("peer usernames resolve to one UID")
            resolved[uid] = caller
        return cls(resolved)

    def authenticate(self, peer: PeerIdentity) -> str:
        caller = self.callers_by_uid.get(peer.uid)
        if caller is None:
            raise PeerAuthenticationError("peer UID is not a configured caller")
        return caller


@dataclass(frozen=True, slots=True)
class MethodGrant:
    caller: str
    operation: str
    purpose: str
    environment: str


@dataclass(frozen=True, slots=True)
class AuthorityRequestContext:
    """Server-minted identity for one handler invocation.

    No field is sourced from request payload.  The peer comes from kernel
    credentials, caller from the root-provisioned UID registry, and grant from
    the code-pinned exact method ACL.
    """

    peer: PeerIdentity
    caller: str
    grant: MethodGrant
    request_id: str
    request_digest: str
    accepted_at_monotonic_ns: int
    processing_deadline_monotonic_ns: int

    def __post_init__(self) -> None:
        if (
            self.caller != self.grant.caller
            or type(self.request_id) is not str
            or not self.request_id
            or type(self.request_digest) is not str
            or not self.request_digest.startswith("sha256:")
            or type(self.accepted_at_monotonic_ns) is not int
            or self.accepted_at_monotonic_ns <= 0
            or type(self.processing_deadline_monotonic_ns) is not int
            or self.processing_deadline_monotonic_ns
            <= self.accepted_at_monotonic_ns
        ):
            raise PeerAuthenticationError("authority request context is invalid")

    def require_within_processing_deadline(self) -> None:
        """Reject work that crossed the server-minted processing deadline."""

        if time.monotonic_ns() >= self.processing_deadline_monotonic_ns:
            raise LocalAuthorityError("authority processing deadline exceeded")


class ExactMethodAcl:
    """Closed ACL derived from the code-pinned principal manifest."""

    def __init__(self, *, authority_id: str, environment: str) -> None:
        if environment not in {"staging", "production"}:
            raise LocalAuthorityError("authority environment is invalid")
        manifest = load_and_validate_manifest()
        principal = manifest["principals"].get(authority_id)
        if (
            type(principal) is not dict
            or principal.get("runtime") != "local_os_service"
        ):
            raise LocalAuthorityError("local authority is not declared")
        grants: set[MethodGrant] = set()
        for row in principal["method_acl"]:
            if row.get("authentication") in {
                "local_peer_credentials",
                "local_peer_credentials_and_webauthn",
            } and environment in row.get(
                "environments", []
            ):
                grants.add(
                    MethodGrant(
                        caller=row["authenticated_caller"],
                        operation=row["target_operation"],
                        purpose=row["purpose"],
                        environment=environment,
                    )
                )
        if not grants:
            raise LocalAuthorityError("authority has no exact local method grants")
        self.authority_id = authority_id
        self.environment = environment
        self._grants = frozenset(grants)

    def require(self, *, caller: str, operation: str, purpose: str) -> MethodGrant:
        grant = MethodGrant(caller, operation, purpose, self.environment)
        if grant not in self._grants:
            raise PeerAuthenticationError("peer is not authorized for the exact method")
        return grant


class FileEd25519KeyCustody:
    """Sign-only adapter for one protected raw Ed25519 seed file.

    The raw key is read through an O_NOFOLLOW descriptor for each operation and
    never exposed by this API.  Keeping the file owned by the dedicated service
    user is a deployment requirement, not something caller code can override.
    """

    def __init__(self, path: str | Path, *, key_id: str, expected_uid: int) -> None:
        self.path = Path(path)
        if type(key_id) is not str or not key_id:
            raise LocalAuthorityError("authority key id is required")
        if type(expected_uid) is not int or expected_uid < 0:
            raise LocalAuthorityError("authority key owner UID is invalid")
        self.key_id = key_id
        self.expected_uid = expected_uid

    def _load(self) -> Ed25519PrivateKey:
        flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
        try:
            fd = os.open(self.path, flags)
        except OSError as exc:
            raise LocalAuthorityPending(
                "protected authority key is unavailable"
            ) from exc
        try:
            before = os.fstat(fd)
            if (
                not stat.S_ISREG(before.st_mode)
                or before.st_uid != self.expected_uid
                or stat.S_IMODE(before.st_mode) not in {0o400, 0o600}
                or before.st_nlink != 1
            ):
                raise LocalAuthorityError("protected authority key metadata is unsafe")
            raw = os.read(fd, 33)
            after = os.fstat(fd)
            if len(raw) != 32 or (
                before.st_dev,
                before.st_ino,
                before.st_size,
                before.st_mtime_ns,
                before.st_ctime_ns,
            ) != (
                after.st_dev,
                after.st_ino,
                after.st_size,
                after.st_mtime_ns,
                after.st_ctime_ns,
            ):
                raise LocalAuthorityError(
                    "protected authority key changed or is invalid"
                )
            return Ed25519PrivateKey.from_private_bytes(raw)
        finally:
            os.close(fd)

    def sign(self, message: bytes) -> str:
        if type(message) is not bytes:
            raise TypeError("authority signer requires exact bytes")
        signature = self._load().sign(message)
        return "ed25519:" + base64.b64encode(signature).decode("ascii")

    def public_key_base64(self) -> str:
        public = (
            self._load()
            .public_key()
            .public_bytes(
                encoding=serialization.Encoding.Raw,
                format=serialization.PublicFormat.Raw,
            )
        )
        return base64.b64encode(public).decode("ascii")


_LEDGER_SCHEMA = """
CREATE TABLE IF NOT EXISTS authority_ledger_meta (
  singleton INTEGER PRIMARY KEY CHECK (singleton=1),
  schema_version INTEGER NOT NULL CHECK (schema_version=1),
  authority_id TEXT NOT NULL,
  environment TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS authority_events (
  sequence INTEGER PRIMARY KEY,
  request_id TEXT NOT NULL UNIQUE,
  caller TEXT NOT NULL,
  operation TEXT NOT NULL,
  purpose TEXT NOT NULL,
  request_digest TEXT NOT NULL,
  request_json TEXT NOT NULL,
  result_digest TEXT NOT NULL,
  result_json TEXT NOT NULL,
  observed_at TEXT NOT NULL,
  prior_event_digest TEXT,
  event_digest TEXT NOT NULL UNIQUE
);
CREATE TRIGGER IF NOT EXISTS authority_events_no_update
BEFORE UPDATE ON authority_events BEGIN SELECT RAISE(ABORT, 'immutable authority event'); END;
CREATE TRIGGER IF NOT EXISTS authority_events_no_delete
BEFORE DELETE ON authority_events BEGIN SELECT RAISE(ABORT, 'immutable authority event'); END;
"""


class SQLiteAuthorityEventLedger:
    """Append-only, chained, idempotent transaction store for authority results."""

    def __init__(
        self,
        path: str | Path,
        *,
        authority_id: str,
        environment: str,
        expected_uid: int,
    ) -> None:
        self.path = Path(path)
        self.authority_id = authority_id
        self.environment = environment
        self.expected_uid = expected_uid

    def initialize(self) -> None:
        parent = self.path.parent
        try:
            parent_stat = parent.stat()
        except OSError as exc:
            raise LocalAuthorityPending(
                "authority ledger directory is unavailable"
            ) from exc
        if (
            not stat.S_ISDIR(parent_stat.st_mode)
            or parent_stat.st_uid != self.expected_uid
            or stat.S_IMODE(parent_stat.st_mode) & 0o077
        ):
            raise AuthorityLedgerError("authority ledger directory is not protected")
        if self.path.exists() and self.path.is_symlink():
            raise AuthorityLedgerError("authority ledger cannot be a symlink")
        created = not self.path.exists()
        conn = sqlite3.connect(str(self.path), isolation_level=None)
        try:
            conn.execute("PRAGMA journal_mode=DELETE")
            conn.execute("PRAGMA synchronous=FULL")
            conn.executescript(_LEDGER_SCHEMA)
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT schema_version,authority_id,environment "
                "FROM authority_ledger_meta WHERE singleton=1"
            ).fetchone()
            expected = (LEDGER_SCHEMA_VERSION, self.authority_id, self.environment)
            if row is None:
                conn.execute(
                    "INSERT INTO authority_ledger_meta VALUES (1,?,?,?)",
                    expected,
                )
            elif tuple(row) != expected:
                raise AuthorityLedgerError("authority ledger identity mismatch")
            conn.commit()
        except BaseException:
            if conn.in_transaction:
                conn.rollback()
            raise
        finally:
            conn.close()
        if created:
            os.chmod(self.path, 0o600)
        self._require_file_metadata()

    def _require_file_metadata(self) -> None:
        try:
            info = self.path.lstat()
        except OSError as exc:
            raise AuthorityLedgerError("authority ledger disappeared") from exc
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_uid != self.expected_uid
            or stat.S_IMODE(info.st_mode) != 0o600
            or info.st_nlink != 1
        ):
            raise AuthorityLedgerError("authority ledger metadata is unsafe")

    def _connect(self) -> sqlite3.Connection:
        self._require_file_metadata()
        conn = sqlite3.connect(str(self.path), isolation_level=None, timeout=5.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA trusted_schema=OFF")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA synchronous=FULL")
        return conn

    def _validate_chain(self, conn: sqlite3.Connection) -> None:
        meta = conn.execute(
            "SELECT schema_version,authority_id,environment "
            "FROM authority_ledger_meta WHERE singleton=1"
        ).fetchall()
        if [tuple(row) for row in meta] != [
            (LEDGER_SCHEMA_VERSION, self.authority_id, self.environment)
        ]:
            raise AuthorityLedgerError("authority ledger identity is invalid")
        prior: str | None = None
        expected_sequence = 1
        for row in conn.execute("SELECT * FROM authority_events ORDER BY sequence"):
            if (
                row["sequence"] != expected_sequence
                or row["prior_event_digest"] != prior
            ):
                raise AuthorityLedgerError("authority event chain is not contiguous")
            try:
                request = decode_strict_json(
                    row["request_json"].encode("utf-8"), field="stored request"
                )
                result = decode_strict_json(
                    row["result_json"].encode("utf-8"), field="stored result"
                )
            except (AttributeError, UnicodeError) as exc:
                raise AuthorityLedgerError("stored authority JSON is invalid") from exc
            if (
                canonical_json_text(request) != row["request_json"]
                or canonical_json_text(result) != row["result_json"]
                or sha256_digest(request) != row["request_digest"]
                or sha256_digest(result) != row["result_digest"]
            ):
                raise AuthorityLedgerError("stored authority payload digest mismatch")
            event = {
                "schema_version": "local-authority-event/v1",
                "authority_id": self.authority_id,
                "environment": self.environment,
                "sequence": row["sequence"],
                "request_id": row["request_id"],
                "caller": row["caller"],
                "operation": row["operation"],
                "purpose": row["purpose"],
                "request_digest": row["request_digest"],
                "result_digest": row["result_digest"],
                "observed_at": row["observed_at"],
                "prior_event_digest": prior,
            }
            if sha256_digest(event) != row["event_digest"]:
                raise AuthorityLedgerError("stored authority event digest mismatch")
            prior = row["event_digest"]
            expected_sequence += 1

    def execute_once(
        self,
        *,
        request: Mapping[str, Any],
        caller: str,
        operation: str,
        purpose: str,
        produce: Callable[[], Mapping[str, Any]],
    ) -> Mapping[str, Any]:
        frozen_request = _copy_exact_json(request, field="authority request")
        request_json = canonical_json_text(frozen_request)
        request_digest = sha256_digest(frozen_request)
        request_id = frozen_request.get("request_id")
        if type(request_id) is not str or not request_id:
            raise LocalAuthorityError("authority request_id is required")
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            self._validate_chain(conn)
            existing = conn.execute(
                "SELECT * FROM authority_events WHERE request_id=?", (request_id,)
            ).fetchone()
            if existing is not None:
                identity = (
                    existing["caller"],
                    existing["operation"],
                    existing["purpose"],
                    existing["request_digest"],
                    existing["request_json"],
                )
                if identity != (
                    caller,
                    operation,
                    purpose,
                    request_digest,
                    request_json,
                ):
                    raise AuthorityLedgerError("authority request_id collision")
                result = decode_strict_json(
                    existing["result_json"].encode("utf-8"), field="stored result"
                )
                conn.commit()
                return MappingProxyType(result)

            result = _copy_exact_json(produce(), field="authority result")
            if type(result) is not dict:
                raise LocalAuthorityError("authority result must be an exact object")
            result_json = canonical_json_text(result)
            result_digest = sha256_digest(result)
            tail = conn.execute(
                "SELECT sequence,event_digest,observed_at FROM authority_events "
                "ORDER BY sequence DESC LIMIT 1"
            ).fetchone()
            sequence = 1 if tail is None else int(tail["sequence"]) + 1
            prior = None if tail is None else str(tail["event_digest"])
            observed_at = _utc_now_text()
            if tail is not None and observed_at < str(tail["observed_at"]):
                raise AuthorityLedgerError("authority clock moved behind ledger tail")
            event = {
                "schema_version": "local-authority-event/v1",
                "authority_id": self.authority_id,
                "environment": self.environment,
                "sequence": sequence,
                "request_id": request_id,
                "caller": caller,
                "operation": operation,
                "purpose": purpose,
                "request_digest": request_digest,
                "result_digest": result_digest,
                "observed_at": observed_at,
                "prior_event_digest": prior,
            }
            event_digest = sha256_digest(event)
            conn.execute(
                "INSERT INTO authority_events VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    sequence,
                    request_id,
                    caller,
                    operation,
                    purpose,
                    request_digest,
                    request_json,
                    result_digest,
                    result_json,
                    observed_at,
                    prior,
                    event_digest,
                ),
            )
            conn.commit()
            return MappingProxyType(result)
        except BaseException:
            if conn.in_transaction:
                conn.rollback()
            raise
        finally:
            conn.close()


@dataclass(frozen=True, slots=True)
class AuthorityRequest:
    request_id: str
    operation: str
    purpose: str
    payload: Mapping[str, Any]
    raw: Mapping[str, Any]


def parse_request(raw: bytes) -> AuthorityRequest:
    document = decode_strict_json(raw, field="local authority request")
    if set(document) != {"format", "request_id", "operation", "purpose", "payload"}:
        raise LocalAuthorityError("local authority request fields are not closed")
    if (
        document["format"] != REQUEST_FORMAT
        or any(
            type(document[field]) is not str or not document[field]
            for field in ("request_id", "operation", "purpose")
        )
        or type(document["payload"]) is not dict
    ):
        raise LocalAuthorityError("local authority request identity is invalid")
    return AuthorityRequest(
        request_id=document["request_id"],
        operation=document["operation"],
        purpose=document["purpose"],
        payload=MappingProxyType(document["payload"]),
        raw=MappingProxyType(document),
    )


def _recv_frame(channel: socket.socket) -> tuple[bytes, tuple[int, ...]]:
    item_size = array.array("i").itemsize
    ancillary_space = socket.CMSG_SPACE(item_size * (MAX_FILE_DESCRIPTORS + 1))
    header, ancillary, flags, _ = channel.recvmsg(
        4,
        ancillary_space,
        getattr(socket, "MSG_WAITALL", 0),
    )
    received: list[int] = []
    try:
        if len(header) != 4 or flags & (socket.MSG_TRUNC | socket.MSG_CTRUNC):
            raise LocalAuthorityError("authority frame header is truncated")
        for level, kind, data in ancillary:
            if level != socket.SOL_SOCKET or kind != socket.SCM_RIGHTS:
                raise LocalAuthorityError("unexpected authority ancillary capability")
            if len(data) % item_size:
                raise LocalAuthorityError("malformed authority file descriptor")
            values = array.array("i")
            values.frombytes(data)
            for fd in values:
                os.set_inheritable(fd, False)
                received.append(fd)
        if len(received) > MAX_FILE_DESCRIPTORS:
            raise LocalAuthorityError("too many authority file descriptors")
        length = struct.unpack("!I", header)[0]
        if length <= 0 or length > MAX_FRAME_BYTES:
            raise LocalAuthorityError("authority frame length is invalid")
        chunks: list[bytes] = []
        remaining = length
        while remaining:
            chunk = channel.recv(min(remaining, 64 * 1024))
            if not chunk:
                raise LocalAuthorityError("authority frame body is truncated")
            chunks.append(chunk)
            remaining -= len(chunk)
        return b"".join(chunks), tuple(received)
    except BaseException:
        for fd in received:
            os.close(fd)
        raise


def _send_frame(channel: socket.socket, payload: Mapping[str, Any]) -> None:
    body = canonical_json_bytes(payload)
    if len(body) > MAX_FRAME_BYTES:
        raise LocalAuthorityError("authority response exceeds frame limit")
    channel.sendall(struct.pack("!I", len(body)) + body)


def call_unix_authority(
    socket_path: str | Path,
    request: Mapping[str, Any],
    *,
    expected_server_uid: int,
    read_only_fd: int | None = None,
    timeout_seconds: float = DEFAULT_IO_TIMEOUT_SECONDS,
) -> Mapping[str, Any]:
    """Call one authority while authenticating the server by kernel UID."""

    path = Path(socket_path)
    if path.is_symlink():
        raise PeerAuthenticationError("authority socket cannot be a symlink")
    if (
        isinstance(timeout_seconds, bool)
        or not isinstance(timeout_seconds, (int, float))
        or timeout_seconds <= 0
    ):
        raise LocalAuthorityError("authority call timeout is invalid")
    channel = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    channel.settimeout(float(timeout_seconds))
    try:
        channel.connect(str(path))
        peer = peer_identity(channel)
        if peer.uid != expected_server_uid:
            raise PeerAuthenticationError("authority server UID mismatch")
        body = canonical_json_bytes(request)
        if len(body) > MAX_FRAME_BYTES:
            raise LocalAuthorityError("authority request exceeds frame limit")
        header = struct.pack("!I", len(body))
        if read_only_fd is None:
            channel.sendall(header + body)
        else:
            try:
                flags = os.O_ACCMODE & fcntl.fcntl(read_only_fd, fcntl.F_GETFL)
                info = os.fstat(read_only_fd)
            except OSError as exc:
                raise LocalAuthorityError(
                    "authority descriptor is unavailable"
                ) from exc
            if (
                flags != os.O_RDONLY
                or not stat.S_ISREG(info.st_mode)
                or info.st_nlink != 1
            ):
                raise LocalAuthorityError(
                    "authority descriptor must be one-link read-only regular file"
                )
            rights = array.array("i", [read_only_fd])
            sent = channel.sendmsg(
                [header],
                [(socket.SOL_SOCKET, socket.SCM_RIGHTS, rights.tobytes())],
            )
            if sent != len(header):
                raise LocalAuthorityError(
                    "authority descriptor frame header was partial"
                )
            channel.sendall(body)
        raw, received = _recv_frame(channel)
        if received:
            for fd in received:
                os.close(fd)
            raise LocalAuthorityError(
                "authority response returned an unexpected descriptor"
            )
        response = decode_strict_json(raw, field="local authority response")
        if (
            response.get("format") != RESPONSE_FORMAT
            or response.get("request_id") != request.get("request_id")
            or response.get("status") != "COMMITTED"
            or type(response.get("result")) is not dict
            or set(response) != {"format", "request_id", "status", "result"}
        ):
            error_type = response.get("error")
            suffix = error_type if type(error_type) is str else "malformed"
            raise LocalAuthorityError(f"authority response rejected: {suffix}")
        return MappingProxyType(response["result"])
    except socket.timeout as exc:
        raise LocalAuthorityError("authority call I/O deadline exceeded") from exc
    except OSError as exc:
        raise LocalAuthorityError("authority call transport failed") from exc
    finally:
        channel.close()


AuthorityHandler = Callable[
    [AuthorityRequestContext, Mapping[str, Any], Sequence[int]], Mapping[str, Any]
]


class UnixAuthorityService:
    """One-request Unix service boundary with kernel peer authentication."""

    def __init__(
        self,
        *,
        authority_id: str,
        environment: str,
        peers: PeerPrincipalRegistry,
        ledger: SQLiteAuthorityEventLedger,
        handlers: Mapping[str, AuthorityHandler],
        io_timeout_seconds: float = DEFAULT_IO_TIMEOUT_SECONDS,
        processing_timeout_seconds: float = DEFAULT_PROCESSING_TIMEOUT_SECONDS,
    ) -> None:
        self.authority_id = authority_id
        self.environment = environment
        self.peers = peers
        self.ledger = ledger
        for name, value in {
            "I/O": io_timeout_seconds,
            "processing": processing_timeout_seconds,
        }.items():
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or value <= 0
            ):
                raise LocalAuthorityError(f"authority {name} timeout is invalid")
        self.io_timeout_seconds = float(io_timeout_seconds)
        self.processing_timeout_ns = int(float(processing_timeout_seconds) * 1e9)
        self.acl = ExactMethodAcl(
            authority_id=authority_id,
            environment=environment,
        )
        frozen_handlers: dict[str, AuthorityHandler] = {}
        for operation, handler in handlers.items():
            if type(operation) is not str or not operation or not callable(handler):
                raise LocalAuthorityError("authority handler map is invalid")
            frozen_handlers[operation] = handler
        if not frozen_handlers:
            raise LocalAuthorityError("authority handler map is empty")
        self.handlers = MappingProxyType(frozen_handlers)

    def serve_connection(self, channel: socket.socket) -> None:
        accepted_at = time.monotonic_ns()
        channel.settimeout(self.io_timeout_seconds)
        fds: tuple[int, ...] = ()
        request_id = "UNKNOWN"
        try:
            peer = peer_identity(channel)
            caller = self.peers.authenticate(peer)
            raw, fds = _recv_frame(channel)
            request = parse_request(raw)
            request_id = request.request_id
            grant = self.acl.require(
                caller=caller,
                operation=request.operation,
                purpose=request.purpose,
            )
            # Source CI may validate an OPEN ledger, but no positive authority
            # operation may execute until the independently reviewed production
            # release ledger is fully closed.
            require_pinned_finding_ledger_gate()
            handler = self.handlers.get(request.operation)
            if handler is None:
                raise LocalAuthorityError("authorized operation has no handler")
            context = AuthorityRequestContext(
                peer=peer,
                caller=caller,
                grant=grant,
                request_id=request.request_id,
                request_digest=sha256_digest(dict(request.raw)),
                accepted_at_monotonic_ns=accepted_at,
                processing_deadline_monotonic_ns=(
                    accepted_at + self.processing_timeout_ns
                ),
            )

            def produce() -> Mapping[str, Any]:
                context.require_within_processing_deadline()
                produced = handler(context, request.payload, fds)
                # A result that outlived its processing lease is neither
                # committed nor returned. Handlers receive this unforgeable
                # context for checks around their own blocking side effects.
                context.require_within_processing_deadline()
                return produced

            result = self.ledger.execute_once(
                request=dict(request.raw),
                caller=caller,
                operation=request.operation,
                purpose=request.purpose,
                produce=produce,
            )
            response = {
                "format": RESPONSE_FORMAT,
                "request_id": request.request_id,
                "status": "COMMITTED",
                "result": dict(result),
            }
        except (LocalAuthorityError, FindingLedgerError, socket.timeout) as exc:
            response = {
                "format": RESPONSE_FORMAT,
                "request_id": request_id,
                "status": "REJECTED",
                "error": type(exc).__name__,
            }
        finally:
            for fd in fds:
                os.close(fd)
        channel.settimeout(self.io_timeout_seconds)
        try:
            _send_frame(channel, response)
        except (OSError, socket.timeout):
            # Abandoned/non-reading peers cannot hold the daemon and transport
            # failure never creates a positive authority event.
            return


class UnixAuthorityConnectionServer:
    """Bounded connection dispatcher with peer-level failure isolation."""

    def __init__(
        self,
        service: UnixAuthorityService,
        *,
        max_concurrent_connections: int = DEFAULT_MAX_CONCURRENT_CONNECTIONS,
        accept_poll_seconds: float = DEFAULT_ACCEPT_POLL_SECONDS,
    ) -> None:
        if (
            type(max_concurrent_connections) is not int
            or max_concurrent_connections <= 0
            or isinstance(accept_poll_seconds, bool)
            or not isinstance(accept_poll_seconds, (int, float))
            or accept_poll_seconds <= 0
        ):
            raise LocalAuthorityError("authority connection limits are invalid")
        self.service = service
        self.accept_poll_seconds = float(accept_poll_seconds)
        self._slots = threading.BoundedSemaphore(max_concurrent_connections)

    def _serve_isolated(self, channel: socket.socket) -> None:
        try:
            self.service.serve_connection(channel)
        finally:
            channel.close()
            self._slots.release()

    def serve(
        self,
        listener: socket.socket,
        *,
        stop_event: threading.Event | None = None,
    ) -> None:
        if listener.family != socket.AF_UNIX:
            raise LocalAuthorityError("authority listener must be AF_UNIX")
        listener.settimeout(self.accept_poll_seconds)
        while stop_event is None or not stop_event.is_set():
            try:
                channel, _ = listener.accept()
            except socket.timeout:
                continue
            if not self._slots.acquire(blocking=False):
                channel.close()
                continue
            threading.Thread(
                target=self._serve_isolated,
                args=(channel,),
                name=f"{self.service.authority_id}-authority-peer",
                daemon=True,
            ).start()


def require_declared_service_identity(
    *, authority_id: str, environment: str
) -> tuple[int, Mapping[str, Any]]:
    """Resolve one service through the root-owned live activation overlay.

    The checked-in declaration remains ``PENDING_NO_KEY``.  Operational state
    is an independently audited local observation bound to the pinned manifest
    and strict finding-ledger gate; no code or manifest edit is needed after a
    human provisions and audits the actual OS resources.
    """

    from scripts.local_authority_activation import (
        ActivationStateError,
        require_active_service_identity,
    )

    try:
        return require_active_service_identity(
            authority_id=authority_id,
            environment=environment,
        )
    except ActivationStateError as exc:
        raise LocalAuthorityPending(str(exc)) from exc


__all__ = [
    "LEDGER_SCHEMA_VERSION",
    "REQUEST_FORMAT",
    "RESPONSE_FORMAT",
    "AuthorityLedgerError",
    "AuthorityRequest",
    "AuthorityRequestContext",
    "ExactMethodAcl",
    "FileEd25519KeyCustody",
    "LocalAuthorityError",
    "LocalAuthorityPending",
    "MethodGrant",
    "PeerAuthenticationError",
    "PeerIdentity",
    "PeerPrincipalRegistry",
    "SQLiteAuthorityEventLedger",
    "UnixAuthorityService",
    "call_unix_authority",
    "canonical_json_bytes",
    "canonical_json_text",
    "decode_strict_json",
    "parse_request",
    "peer_identity",
    "require_declared_service_identity",
    "sha256_digest",
]
