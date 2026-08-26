#!/usr/bin/env python3
"""Strict candidate inspection for the PENDING authority protocols.

The functions in this module can reject malformed evidence and independently
remeasure a read-only mirror.  They deliberately do not mint a positive
authority capability: OS peer credentials, dedicated sockets, staging signing
roots, transactional event ledgers, WebAuthn credential verification, and
one-use state are not provisioned yet.
"""

from __future__ import annotations

import array
import base64
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import socket
import sqlite3
import stat
from types import MappingProxyType
from typing import Any, Mapping, Protocol
from urllib.parse import quote
from weakref import WeakKeyDictionary

try:
    from scripts import authority_principal_manifest as _contracts
    from scripts import sync_d1_to_sqlite as _sync
except ImportError:  # pragma: no cover - direct script execution
    import authority_principal_manifest as _contracts
    import sync_d1_to_sqlite as _sync

from packages.data_plane.ops import d1_sync_signing as _d1_signing


AUTHORITY_SPECS = Path(__file__).resolve().parents[1] / "specs" / "authorities"
REQUEST_SCHEMA = AUTHORITY_SPECS / "frozen_mirror_request.schema.json"
HANDOFF_SCHEMA = AUTHORITY_SPECS / "frozen_mirror_handoff.schema.json"
EVENT_SCHEMA = AUTHORITY_SPECS / "authority_event.schema.json"
TRADER_CHALLENGE_SCHEMA = AUTHORITY_SPECS / "trader_webauthn_challenge.schema.json"
TRADER_ASSERTION_SCHEMA = AUTHORITY_SPECS / "trader_webauthn_assertion.schema.json"

_MAX_REQUEST_TTL = timedelta(minutes=2)
_MAX_HANDOFF_TTL = timedelta(minutes=2)
_MAX_WEBAUTHN_TTL = timedelta(minutes=2)
_MAX_EVENT_AGE = timedelta(minutes=5)
_MAX_FUTURE_SKEW = timedelta(seconds=5)
_D1_IDENTITIES = {
    "staging": (
        "quant-ingest-staging",
        "d448d1c6-27c8-4aeb-8702-3e7a8b6bf2bb",
    ),
    "production": (
        "quant-ingest",
        "be6fdcf8-40be-41fc-9535-7facd1fc2ffc",
    ),
}


class AuthorityProtocolError(ValueError):
    """One protocol document or descriptor failed strict inspection."""


class AuthorityProtocolPending(RuntimeError):
    """The positive authority service is intentionally not activated."""


def _copy_exact_json(value: Any, *, field: str) -> Any:
    if type(value) is dict:
        copied: dict[str, Any] = {}
        for key, item in dict.items(value):
            if type(key) is not str or key in copied:
                raise AuthorityProtocolError(f"{field}: keys must be unique strings")
            copied[key] = _copy_exact_json(item, field=f"{field}.{key}")
        return copied
    if type(value) is list:
        return [
            _copy_exact_json(item, field=f"{field}[{index}]")
            for index, item in enumerate(value)
        ]
    if type(value) in {str, int, bool, type(None)}:
        return value
    raise AuthorityProtocolError(
        f"{field}: floats and adapted JSON values are forbidden"
    )


def _strict_json(raw: bytes | str, *, field: str) -> dict[str, Any]:
    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise AuthorityProtocolError(f"{field}: duplicate key {key!r}")
            result[key] = value
        return result

    def reject_nonfinite(value: str) -> None:
        raise AuthorityProtocolError(f"{field}: non-finite value {value!r}")

    def reject_float(value: str) -> None:
        raise AuthorityProtocolError(f"{field}: JSON float is forbidden: {value!r}")

    try:
        value = json.loads(
            raw,
            object_pairs_hook=reject_duplicates,
            parse_constant=reject_nonfinite,
            parse_float=reject_float,
        )
    except AuthorityProtocolError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AuthorityProtocolError(f"{field}: invalid JSON") from exc
    frozen = _copy_exact_json(value, field=field)
    if type(frozen) is not dict:
        raise AuthorityProtocolError(f"{field}: top level must be an object")
    return frozen


def _canonical_bytes(value: dict[str, Any]) -> bytes:
    frozen = _copy_exact_json(value, field="canonical input")
    assert type(frozen) is dict
    return json.dumps(
        frozen,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def _digest(value: dict[str, Any]) -> str:
    return "sha256:" + hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _without(document: dict[str, Any], field: str) -> dict[str, Any]:
    return {key: value for key, value in document.items() if key != field}


def _deep_immutable(value: Any) -> Any:
    if type(value) is dict:
        return MappingProxyType(
            {key: _deep_immutable(item) for key, item in value.items()}
        )
    if type(value) is list:
        return tuple(_deep_immutable(item) for item in value)
    return value


def _validate_schema(document: dict[str, Any], path: Path) -> None:
    # Loading the code-pinned manifest first prevents a schema file swap plus a
    # matching self-declared digest from becoming a runtime contract.
    _contracts.load_and_validate_manifest()
    schema = _contracts._load_strict_json(path)  # noqa: SLF001
    try:
        _contracts._schema_validate(document, schema)  # noqa: SLF001
    except ValueError as exc:
        raise AuthorityProtocolError(str(exc)) from exc


def _timestamp(value: object, *, field: str) -> datetime:
    if type(value) is not str:
        raise AuthorityProtocolError(f"{field}: timestamp must be a string")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise AuthorityProtocolError(f"{field}: invalid timestamp") from exc
    if parsed.tzinfo is None:
        raise AuthorityProtocolError(f"{field}: timezone is required")
    return parsed.astimezone(timezone.utc)


def _require_window(
    issued: object,
    expires: object,
    *,
    now: datetime,
    max_ttl: timedelta,
    field: str,
) -> None:
    issued_at = _timestamp(issued, field=f"{field}.issued_at")
    expires_at = _timestamp(expires, field=f"{field}.expires_at")
    if now.tzinfo is None:
        raise TypeError("trusted clock must be timezone-aware")
    current = now.astimezone(timezone.utc)
    if issued_at > current + _MAX_FUTURE_SKEW:
        raise AuthorityProtocolError(f"{field}: issued in the future")
    if expires_at <= current or expires_at <= issued_at:
        raise AuthorityProtocolError(f"{field}: expired or inverted window")
    if expires_at - issued_at > max_ttl:
        raise AuthorityProtocolError(f"{field}: TTL exceeds contract")


def _trusted_now() -> datetime:
    """Return the service-owned clock; tests may replace this before activation."""
    return datetime.now(timezone.utc)


def _trusted_now_utc() -> datetime:
    current = _trusted_now()
    if (
        type(current) is not datetime
        or current.tzinfo is None
        or current.utcoffset() is None
    ):
        raise TypeError("authority trusted clock must be an exact aware datetime")
    return current.astimezone(timezone.utc)


_CANDIDATE_SEAL = object()


@dataclass(frozen=True, slots=True)
class _CandidateProvenance:
    kind: str
    document: Mapping[str, Any]
    canonical_bytes: bytes
    digest: str
    context: tuple[tuple[str, Any], ...]
    payload: Mapping[str, Any] | None = None


_CANDIDATE_PROVENANCE: WeakKeyDictionary[object, _CandidateProvenance] = (
    WeakKeyDictionary()
)


@dataclass(frozen=True, slots=True, eq=False, weakref_slot=True)
class _FrozenMirrorRequestCandidate:
    document: Mapping[str, Any]
    digest: str
    _seal: object = field(repr=False)

    def __post_init__(self) -> None:
        if self._seal is not _CANDIDATE_SEAL:
            raise AuthorityProtocolError("request candidate lacks verifier provenance")


@dataclass(frozen=True, slots=True, eq=False, weakref_slot=True)
class _FrozenMirrorHandoffCandidate:
    document: Mapping[str, Any]
    audit_document_digest: str
    descriptor_digest: str
    _seal: object = field(repr=False)

    def __post_init__(self) -> None:
        if self._seal is not _CANDIDATE_SEAL:
            raise AuthorityProtocolError("handoff candidate lacks verifier provenance")


@dataclass(frozen=True, slots=True, eq=False, weakref_slot=True)
class _AuthorityEventCandidate:
    document: Mapping[str, Any]
    payload: Mapping[str, Any]
    _seal: object = field(repr=False)

    def __post_init__(self) -> None:
        if self._seal is not _CANDIDATE_SEAL:
            raise AuthorityProtocolError("event candidate lacks verifier provenance")


@dataclass(frozen=True, slots=True, eq=False, weakref_slot=True)
class _TraderAssertionCandidate:
    document: Mapping[str, Any]
    sign_count: int
    _seal: object = field(repr=False)

    def __post_init__(self) -> None:
        if self._seal is not _CANDIDATE_SEAL:
            raise AuthorityProtocolError("Trader candidate lacks verifier provenance")


def _register_candidate(
    candidate: object,
    *,
    kind: str,
    document: Mapping[str, Any],
    canonical_bytes: bytes,
    digest: str,
    context: Mapping[str, Any],
    payload: Mapping[str, Any] | None = None,
) -> None:
    _CANDIDATE_PROVENANCE[candidate] = _CandidateProvenance(
        kind=kind,
        document=document,
        canonical_bytes=canonical_bytes,
        digest=digest,
        context=tuple(sorted(context.items())),
        payload=payload,
    )


def _require_candidate_provenance(
    candidate: object,
    *,
    expected_type: type,
    kind: str,
) -> _CandidateProvenance:
    if type(candidate) is not expected_type:
        raise AuthorityProtocolError(f"{kind} requires the exact inspected candidate")
    if getattr(candidate, "_seal", None) is not _CANDIDATE_SEAL:
        raise AuthorityProtocolError(f"{kind} candidate seal mismatch")
    provenance = _CANDIDATE_PROVENANCE.get(candidate)
    if provenance is None or provenance.kind != kind:
        raise AuthorityProtocolError(f"{kind} candidate was not issued by this verifier")
    if getattr(candidate, "document", None) is not provenance.document:
        raise AuthorityProtocolError(f"{kind} candidate document was replaced")
    return provenance


class AuthorityEventStore(Protocol):
    """Required transactional append contract; no implementation is active.

    One transaction must enforce `(environment, authority_id, sequence)` and
    `idempotency_key` uniqueness, compare `prior_event_digest` with the current
    tail, call `_require_authority_event_candidate_provenance` against that
    tail including its monotonic `observed_at`, append the exact canonical
    event, and durably commit before returning.
    """

    def append_if_current(
        self,
        candidate: _AuthorityEventCandidate,
        *,
        expected_sequence: int,
        expected_prior_event_digest: str | None,
        expected_prior_observed_at: str | None,
    ) -> str: ...


def _validate_frozen_mirror_request_document(
    document: dict[str, Any],
    *,
    transport_authenticated_caller: str,
    expected_environment: str,
    now: datetime,
) -> str:
    _validate_schema(document, REQUEST_SCHEMA)
    if document["authenticated_caller"] != transport_authenticated_caller:
        raise AuthorityProtocolError("request caller is not transport-authenticated")
    if document["environment"] != expected_environment:
        raise AuthorityProtocolError("request crosses deployment environment")
    expected_digest = _digest(_without(document, "request_digest"))
    if document["request_digest"] != expected_digest:
        raise AuthorityProtocolError("request digest mismatch")
    _require_window(
        document["issued_at"],
        document["expires_at"],
        now=now,
        max_ttl=_MAX_REQUEST_TTL,
        field="frozen mirror request",
    )
    manifest = _contracts.load_and_validate_manifest()
    matching_acl = [
        row
        for row in manifest["principals"]["d1_sync"]["method_acl"]
        if row["authenticated_caller"] == document["authenticated_caller"]
        and row["target_operation"] == document["target_operation"]
        and row["purpose"] == document["purpose"]
        and document["environment"] in row["environments"]
    ]
    if len(matching_acl) != 1:
        raise AuthorityProtocolError("request is not authorized by exact method ACL")
    return expected_digest


def inspect_frozen_mirror_request_candidate(
    raw: bytes | str,
    *,
    transport_authenticated_caller: str,
    expected_environment: str,
) -> _FrozenMirrorRequestCandidate:
    document = _strict_json(raw, field="frozen mirror request")
    expected_digest = _validate_frozen_mirror_request_document(
        document,
        transport_authenticated_caller=transport_authenticated_caller,
        expected_environment=expected_environment,
        now=_trusted_now_utc(),
    )
    immutable = _deep_immutable(document)
    candidate = _FrozenMirrorRequestCandidate(
        immutable, expected_digest, _CANDIDATE_SEAL
    )
    _register_candidate(
        candidate,
        kind="frozen mirror request",
        document=immutable,
        canonical_bytes=_canonical_bytes(document),
        digest=expected_digest,
        context={
            "transport_authenticated_caller": transport_authenticated_caller,
            "expected_environment": expected_environment,
        },
    )
    return candidate


def _require_frozen_mirror_request_candidate(
    request: object,
    *,
    now: datetime,
) -> dict[str, Any]:
    provenance = _require_candidate_provenance(
        request,
        expected_type=_FrozenMirrorRequestCandidate,
        kind="frozen mirror request",
    )
    context = dict(provenance.context)
    document = _strict_json(
        provenance.canonical_bytes,
        field="provenance-bound frozen mirror request",
    )
    digest = _validate_frozen_mirror_request_document(
        document,
        transport_authenticated_caller=context["transport_authenticated_caller"],
        expected_environment=context["expected_environment"],
        now=now,
    )
    if (
        getattr(request, "digest", None) != digest
        or provenance.digest != digest
        or document["request_digest"] != digest
    ):
        raise AuthorityProtocolError("request candidate digest provenance mismatch")
    return document


def _descriptor_identity(fd: int) -> dict[str, Any]:
    try:
        flags = fcntl.fcntl(fd, fcntl.F_GETFL)
        before = os.fstat(fd)
    except OSError as exc:
        raise AuthorityProtocolError("mirror descriptor is not open") from exc
    if flags & os.O_ACCMODE != os.O_RDONLY:
        raise AuthorityProtocolError("mirror descriptor is not O_RDONLY")
    if not stat.S_ISREG(before.st_mode) or before.st_size <= 0:
        raise AuthorityProtocolError("mirror descriptor is not a non-empty regular file")
    digest = hashlib.sha256()
    offset = 0
    while offset < before.st_size:
        chunk = os.pread(fd, min(1024 * 1024, before.st_size - offset), offset)
        if not chunk:
            raise AuthorityProtocolError("mirror descriptor shortened during digest")
        digest.update(chunk)
        offset += len(chunk)
    after = os.fstat(fd)
    stable = (
        before.st_dev,
        before.st_ino,
        before.st_size,
        before.st_mtime_ns,
        before.st_ctime_ns,
    ) == (
        after.st_dev,
        after.st_ino,
        after.st_size,
        after.st_mtime_ns,
        after.st_ctime_ns,
    )
    if not stable:
        raise AuthorityProtocolError("mirror descriptor changed during digest")
    return {
        "device": before.st_dev,
        "inode": before.st_ino,
        "size": before.st_size,
        "sha256": "sha256:" + digest.hexdigest(),
    }


def _connect_readonly_fd(fd: int) -> sqlite3.Connection:
    candidates = [f"/proc/self/fd/{fd}", f"/dev/fd/{fd}"]
    path = next((candidate for candidate in candidates if Path(candidate).exists()), None)
    if path is None:
        raise AuthorityProtocolPending("platform cannot reopen an exact received FD")
    uri = f"file:{quote(path, safe='/')}?mode=ro&immutable=1"
    conn: sqlite3.Connection | None = None
    try:
        conn = sqlite3.connect(uri, uri=True, timeout=1.0)
        conn.execute("PRAGMA query_only=ON")
    except sqlite3.Error as exc:
        if conn is not None:
            conn.close()
        raise AuthorityProtocolError("mirror descriptor is not readable SQLite") from exc
    return conn


def _remeasure_applied_mirror_identity(
    conn: sqlite3.Connection,
) -> dict[str, object]:
    """Reuse the verified row/audit path while preserving valid generation zero."""
    row = _sync._latest_export_sync_row(conn)  # noqa: SLF001
    if row is None:
        raise ValueError("applied mirror has no current signed D1 sync audit")
    envelope = _sync._verified_sync_envelope_from_row(  # noqa: SLF001
        conn,
        row,
        recompute_local=True,
        require_fresh=True,
        eligibility="current",
    )
    source = envelope["source_change_seq"]
    applied = envelope["applied_change_seq"]
    counts = envelope["table_counts"]
    if (
        type(source) is not int
        or source < 0
        or type(applied) is not int
        or applied != source
        or not isinstance(counts, Mapping)
        or set(counts) != set(_sync.DEFAULT_TABLES)
    ):
        raise ValueError("applied mirror identity is incomplete")
    return {
        "audit_digest": row["audit_digest"],
        "issuer_key_id": row["issuer_key_id"],
        "export_digest": envelope["export_digest"],
        "source_change_seq": source,
        "applied_change_seq": applied,
        "source_content_digest": envelope["source_content_digest"],
        "local_content_digest": envelope["local_content_digest"],
        "source_schema_digest": envelope["source_schema_digest"],
        "schema_digest": envelope["schema_digest"],
        "table_counts": dict(counts),
    }


def inspect_frozen_mirror_handoff_candidate(
    raw: bytes | str,
    *,
    request: _FrozenMirrorRequestCandidate,
    received_fd: int,
) -> _FrozenMirrorHandoffCandidate:
    document = _strict_json(raw, field="frozen mirror handoff")
    _validate_schema(document, HANDOFF_SCHEMA)
    current = _trusted_now_utc()
    request_document = _require_frozen_mirror_request_candidate(
        request,
        now=current,
    )
    for field in (
        "request_id",
        "request_digest",
        "environment",
        "authenticated_caller",
        "target_operation",
        "purpose",
    ):
        if document[field] != request_document[field]:
            raise AuthorityProtocolError(f"handoff is not bound to request {field}")
    expected_d1 = _D1_IDENTITIES[document["environment"]]
    if (document["source_d1_name"], document["source_d1_id"]) != expected_d1:
        raise AuthorityProtocolError("handoff D1 identity drift")
    _require_window(
        request_document["issued_at"],
        request_document["expires_at"],
        now=current,
        max_ttl=_MAX_REQUEST_TTL,
        field="frozen mirror request",
    )
    _require_window(
        document["opened_at"],
        document["expires_at"],
        now=current,
        max_ttl=_MAX_HANDOFF_TTL,
        field="frozen mirror handoff",
    )
    if (
        _timestamp(document["opened_at"], field="handoff.opened_at")
        < _timestamp(request_document["issued_at"], field="request.issued_at")
        or _timestamp(document["expires_at"], field="handoff.expires_at")
        > _timestamp(request_document["expires_at"], field="request.expires_at")
    ):
        raise AuthorityProtocolError("handoff lifetime exceeds its request")
    if document["handoff_digest"] != _digest(_without(document, "handoff_digest")):
        raise AuthorityProtocolError("handoff digest mismatch")

    audit_document = _strict_json(
        document["signed_audit_document_json"], field="signed D1 audit"
    )
    canonical_audit = _d1_signing.canonical_d1_sync_bytes(audit_document).decode()
    if document["signed_audit_document_json"] != canonical_audit:
        raise AuthorityProtocolError("signed D1 audit JSON is not canonical")
    if document["environment"] == "staging":
        raise AuthorityProtocolPending("staging D1 signing registry is not provisioned")
    try:
        verified = _d1_signing._verify_signed_d1_sync_audit_document(  # noqa: SLF001
            audit_document,
            require_fresh=True,
            eligibility="current",
        )
    except _d1_signing.D1SyncAuditError as exc:
        raise AuthorityProtocolError("signed D1 audit is not current and verified") from exc
    if (
        document["signed_audit_document_digest"] != verified.document_digest
        or document["signed_audit_issuer_key_id"] != verified.issuer_key_id
    ):
        raise AuthorityProtocolError("handoff signed-audit identity mismatch")
    envelope = verified.envelope
    envelope_pairs = {
        "source_d1_name": envelope["d1_name"],
        "source_d1_id": envelope["d1_id"],
        "source_change_seq": envelope["source_change_seq"],
        "applied_change_seq": envelope["applied_change_seq"],
        "source_content_digest": envelope["source_content_digest"],
        "local_content_digest": envelope["local_content_digest"],
        "source_schema_digest": envelope["source_schema_digest"],
        "local_schema_digest": envelope["schema_digest"],
        "table_counts": dict(envelope["table_counts"]),
    }
    for field, expected in envelope_pairs.items():
        if document[field] != expected:
            raise AuthorityProtocolError(f"handoff/audit {field} mismatch")

    descriptor = _descriptor_identity(received_fd)
    if document["descriptor_identity"] != descriptor:
        raise AuthorityProtocolError("handoff descriptor identity mismatch")
    conn = _connect_readonly_fd(received_fd)
    try:
        journal_mode = str(conn.execute("PRAGMA journal_mode").fetchone()[0]).lower()
        if journal_mode != "delete" or document["journal_mode"] != journal_mode:
            raise AuthorityProtocolError("mirror journal mode is not frozen")
        identity = _remeasure_applied_mirror_identity(conn)
    except (sqlite3.Error, ValueError) as exc:
        raise AuthorityProtocolError("mirror governed identity remeasurement failed") from exc
    finally:
        conn.close()
    descriptor_after = _descriptor_identity(received_fd)
    if descriptor_after != descriptor:
        raise AuthorityProtocolError("mirror descriptor changed during remeasurement")
    mirror_pairs = {
        "signed_audit_document_digest": identity["audit_digest"],
        "signed_audit_issuer_key_id": identity["issuer_key_id"],
        "source_change_seq": identity["source_change_seq"],
        "applied_change_seq": identity["applied_change_seq"],
        "source_content_digest": identity["source_content_digest"],
        "local_content_digest": identity["local_content_digest"],
        "source_schema_digest": identity["source_schema_digest"],
        "local_schema_digest": identity["schema_digest"],
        "table_counts": identity["table_counts"],
    }
    for field, expected in mirror_pairs.items():
        if document[field] != expected:
            raise AuthorityProtocolError(f"handoff/mirror {field} mismatch")
    mirror_body = {
        key: document[key]
        for key in (
            "environment",
            "source_d1_name",
            "source_d1_id",
            "signed_audit_document_digest",
            "signed_audit_issuer_key_id",
            "source_change_seq",
            "applied_change_seq",
            "descriptor_open_mode",
            "descriptor_identity",
            "source_content_digest",
            "local_content_digest",
            "source_schema_digest",
            "local_schema_digest",
            "table_counts",
            "journal_mode",
        )
    }
    expected_mirror_digest = _digest(mirror_body)
    if document["mirror_identity_digest"] != expected_mirror_digest:
        raise AuthorityProtocolError("mirror identity digest mismatch")
    immutable = _deep_immutable(document)
    candidate = _FrozenMirrorHandoffCandidate(
        immutable,
        verified.document_digest,
        descriptor["sha256"],
        _CANDIDATE_SEAL,
    )
    _register_candidate(
        candidate,
        kind="frozen mirror handoff",
        document=immutable,
        canonical_bytes=_canonical_bytes(document),
        digest=document["handoff_digest"],
        context={
            "request_digest": request.digest,
            "descriptor_digest": descriptor["sha256"],
            "audit_document_digest": verified.document_digest,
        },
    )
    return candidate


def _make_received_fd_non_inheritable(fd: int) -> None:
    try:
        os.set_inheritable(fd, False)
        if os.get_inheritable(fd):
            raise OSError("descriptor remains inheritable")
    except OSError as exc:
        raise AuthorityProtocolError(
            "received descriptor could not be made close-on-exec"
        ) from exc


def _recv_exactly_one_fd(channel: socket.socket) -> tuple[bytes, int]:
    item_size = array.array("i").itemsize
    recv_flags = getattr(socket, "MSG_CMSG_CLOEXEC", 0)
    payload, ancillary, flags, _ = channel.recvmsg(
        1024 * 1024,
        socket.CMSG_SPACE(item_size * 2),
        recv_flags,
    )
    received: list[int] = []
    try:
        if flags & (socket.MSG_CTRUNC | socket.MSG_TRUNC):
            raise AuthorityProtocolError("SCM_RIGHTS message was truncated")
        for level, kind, data in ancillary:
            if level != socket.SOL_SOCKET or kind != socket.SCM_RIGHTS:
                raise AuthorityProtocolError("unexpected ancillary capability")
            if len(data) % item_size:
                raise AuthorityProtocolError("malformed SCM_RIGHTS capability")
            values = array.array("i")
            values.frombytes(data)
            for fd in values.tolist():
                received.append(fd)
                _make_received_fd_non_inheritable(fd)
        if len(received) != 1:
            raise AuthorityProtocolError("handoff requires exactly one descriptor")
        return payload, received.pop()
    finally:
        for fd in received:
            os.close(fd)


def activate_frozen_mirror_handoff(
    raw: bytes | str,
    *,
    request: _FrozenMirrorRequestCandidate,
    received_fd: int,
) -> None:
    inspect_frozen_mirror_handoff_candidate(
        raw, request=request, received_fd=received_fd
    )
    raise AuthorityProtocolPending(
        "OS peer credentials, dedicated sockets, and transactional handoff ledger "
        "are not provisioned"
    )


def receive_and_activate_frozen_mirror_handoff(
    channel: socket.socket,
    *,
    request: _FrozenMirrorRequestCandidate,
) -> None:
    raw, fd = _recv_exactly_one_fd(channel)
    try:
        activate_frozen_mirror_handoff(
            raw, request=request, received_fd=fd
        )
    finally:
        os.close(fd)


def _validate_authority_event_document(
    document: dict[str, Any],
    *,
    expected_authority: str,
    expected_environment: str,
    expected_sequence: int,
    expected_prior_event_digest: str | None,
    expected_prior_observed_at: str | None,
    trusted_now: datetime,
) -> dict[str, Any]:
    _validate_schema(document, EVENT_SCHEMA)
    if type(expected_sequence) is not int or expected_sequence < 1:
        raise TypeError("trusted authority event sequence must be a positive integer")
    if expected_sequence == 1:
        if (
            expected_prior_event_digest is not None
            or expected_prior_observed_at is not None
        ):
            raise AuthorityProtocolError("first authority event cannot have a tail")
    elif (
        type(expected_prior_event_digest) is not str
        or expected_prior_observed_at is None
    ):
        raise AuthorityProtocolError(
            "non-first authority event requires the exact ledger tail"
        )
    if document["authority_id"] != expected_authority:
        raise AuthorityProtocolError("authority event principal mismatch")
    if document["environment"] != expected_environment:
        raise AuthorityProtocolError("authority event environment mismatch")
    if document["sequence"] != expected_sequence:
        raise AuthorityProtocolError("authority event sequence mismatch")
    if document["prior_event_digest"] != expected_prior_event_digest:
        raise AuthorityProtocolError("authority event prior-chain mismatch")
    observed_at = _timestamp(document["observed_at"], field="event.observed_at")
    if observed_at > trusted_now + _MAX_FUTURE_SKEW:
        raise AuthorityProtocolError("authority event observed_at is in the future")
    if observed_at < trusted_now - _MAX_EVENT_AGE:
        raise AuthorityProtocolError(
            "authority event is too old; historical reconcile requires its "
            "separate PENDING protocol"
        )
    if expected_prior_observed_at is not None:
        prior_observed_at = _timestamp(
            expected_prior_observed_at,
            field="trusted ledger tail observed_at",
        )
        if observed_at < prior_observed_at:
            raise AuthorityProtocolError(
                "authority event observed_at moved behind the ledger tail"
            )
    payload = _strict_json(document["payload_json"], field="authority event payload")
    canonical_payload = _canonical_bytes(payload).decode()
    if document["payload_json"] != canonical_payload:
        raise AuthorityProtocolError("authority event payload is not canonical")
    if document["payload_digest"] != _digest(payload):
        raise AuthorityProtocolError("authority event payload digest mismatch")
    idempotency_body = {
        key: document[key]
        for key in (
            "environment",
            "authority_id",
            "request_id",
            "event_type",
            "subject_id",
            "payload_schema",
            "payload_digest",
        )
    }
    if document["idempotency_key"] != _digest(idempotency_body):
        raise AuthorityProtocolError("authority event idempotency key mismatch")
    if document["event_digest"] != _digest(_without(document, "event_digest")):
        raise AuthorityProtocolError("authority event digest mismatch")
    return payload


def inspect_authority_event_candidate(
    raw: bytes | str,
    *,
    expected_authority: str,
    expected_environment: str,
    expected_sequence: int,
    expected_prior_event_digest: str | None,
    expected_prior_observed_at: str | None = None,
) -> _AuthorityEventCandidate:
    document = _strict_json(raw, field="authority event")
    payload = _validate_authority_event_document(
        document,
        expected_authority=expected_authority,
        expected_environment=expected_environment,
        expected_sequence=expected_sequence,
        expected_prior_event_digest=expected_prior_event_digest,
        expected_prior_observed_at=expected_prior_observed_at,
        trusted_now=_trusted_now_utc(),
    )
    immutable_document = _deep_immutable(document)
    immutable_payload = _deep_immutable(payload)
    candidate = _AuthorityEventCandidate(
        immutable_document,
        immutable_payload,
        _CANDIDATE_SEAL,
    )
    _register_candidate(
        candidate,
        kind="authority event",
        document=immutable_document,
        canonical_bytes=_canonical_bytes(document),
        digest=document["event_digest"],
        context={
            "expected_authority": expected_authority,
            "expected_environment": expected_environment,
            "expected_sequence": expected_sequence,
            "expected_prior_event_digest": expected_prior_event_digest,
            "expected_prior_observed_at": expected_prior_observed_at,
        },
        payload=immutable_payload,
    )
    return candidate


def _require_authority_event_candidate_provenance(
    candidate: object,
    *,
    expected_authority: str,
    expected_environment: str,
    expected_sequence: int,
    expected_prior_event_digest: str | None,
    expected_prior_observed_at: str | None = None,
) -> None:
    provenance = _require_candidate_provenance(
        candidate,
        expected_type=_AuthorityEventCandidate,
        kind="authority event",
    )
    expected_context = tuple(
        sorted(
            {
                "expected_authority": expected_authority,
                "expected_environment": expected_environment,
                "expected_sequence": expected_sequence,
                "expected_prior_event_digest": expected_prior_event_digest,
                "expected_prior_observed_at": expected_prior_observed_at,
            }.items()
        )
    )
    if provenance.context != expected_context:
        raise AuthorityProtocolError("authority event verifier context mismatch")
    if getattr(candidate, "payload", None) is not provenance.payload:
        raise AuthorityProtocolError("authority event candidate payload was replaced")
    document = _strict_json(
        provenance.canonical_bytes,
        field="provenance-bound authority event",
    )
    _validate_authority_event_document(
        document,
        expected_authority=expected_authority,
        expected_environment=expected_environment,
        expected_sequence=expected_sequence,
        expected_prior_event_digest=expected_prior_event_digest,
        expected_prior_observed_at=expected_prior_observed_at,
        trusted_now=_trusted_now_utc(),
    )
    if document["event_digest"] != provenance.digest:
        raise AuthorityProtocolError("authority event candidate digest provenance mismatch")


def append_authority_event(raw: bytes | str, **expected: Any) -> None:
    candidate = inspect_authority_event_candidate(raw, **expected)
    _require_authority_event_candidate_provenance(candidate, **expected)
    raise AuthorityProtocolPending(
        "transactional append-only authority event ledger is not provisioned"
    )


def _decode_base64url(value: object, *, field: str) -> bytes:
    if type(value) is not str or "=" in value:
        raise AuthorityProtocolError(f"{field}: non-canonical base64url")
    try:
        decoded = base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
    except (ValueError, TypeError) as exc:
        raise AuthorityProtocolError(f"{field}: invalid base64url") from exc
    if base64.urlsafe_b64encode(decoded).decode().rstrip("=") != value:
        raise AuthorityProtocolError(f"{field}: non-canonical base64url")
    return decoded


def inspect_trader_webauthn_assertion_candidate(
    challenge_raw: bytes | str,
    assertion_raw: bytes | str,
    *,
    expected_environment: str,
    expected_exact_four_authorization_digest: str,
    stored_sign_count: int,
    one_use_key_available: bool,
) -> _TraderAssertionCandidate:
    challenge = _strict_json(challenge_raw, field="Trader WebAuthn challenge")
    assertion = _strict_json(assertion_raw, field="Trader WebAuthn assertion")
    _validate_schema(challenge, TRADER_CHALLENGE_SCHEMA)
    _validate_schema(assertion, TRADER_ASSERTION_SCHEMA)
    current = _trusted_now_utc()
    if challenge["environment"] != expected_environment:
        raise AuthorityProtocolError("WebAuthn challenge environment mismatch")
    if challenge["challenge_digest"] != _digest(
        _without(challenge, "challenge_digest")
    ):
        raise AuthorityProtocolError("WebAuthn challenge digest mismatch")
    one_use_body = {
        key: challenge[key]
        for key in (
            "environment",
            "challenge_id",
            "challenge_base64url",
            "exact_four_authorization_digest",
            "expires_at",
        )
    }
    if challenge["one_use_key"] != _digest(one_use_body):
        raise AuthorityProtocolError("WebAuthn one-use key mismatch")
    _require_window(
        challenge["issued_at"],
        challenge["expires_at"],
        now=current,
        max_ttl=_MAX_WEBAUTHN_TTL,
        field="Trader WebAuthn challenge",
    )
    bound_fields = (
        "environment",
        "challenge_id",
        "challenge_digest",
        "exact_four_authorization_digest",
        "rp_id",
        "origin",
        "one_use_key",
    )
    for field in bound_fields:
        if assertion[field] != challenge[field]:
            raise AuthorityProtocolError(f"WebAuthn assertion {field} mismatch")
    if challenge["exact_four_authorization_digest"] != (
        expected_exact_four_authorization_digest
    ):
        raise AuthorityProtocolError("WebAuthn exact-four authorization mismatch")
    if type(stored_sign_count) is not int or stored_sign_count < 0:
        raise TypeError("trusted WebAuthn sign count must be a non-negative integer")
    if one_use_key_available is not True:
        raise AuthorityProtocolError("WebAuthn challenge is used or unavailable")
    asserted_at = _timestamp(assertion["asserted_at"], field="assertion.asserted_at")
    if asserted_at > current.astimezone(timezone.utc) + _MAX_FUTURE_SKEW:
        raise AuthorityProtocolError("WebAuthn assertion is in the future")
    if asserted_at < _timestamp(challenge["issued_at"], field="challenge.issued_at"):
        raise AuthorityProtocolError("WebAuthn assertion predates its challenge")
    if asserted_at > _timestamp(challenge["expires_at"], field="challenge.expires_at"):
        raise AuthorityProtocolError("WebAuthn assertion is expired")
    client_raw = _decode_base64url(
        assertion["client_data_json_base64url"], field="clientDataJSON"
    )
    _decode_base64url(assertion["credential_id_base64url"], field="credential id")
    _decode_base64url(assertion["signature_base64url"], field="signature")
    client = _strict_json(client_raw, field="clientDataJSON")
    if set(client) != {"type", "challenge", "origin", "crossOrigin"}:
        raise AuthorityProtocolError("clientDataJSON fields are not closed")
    if (
        client["type"] != "webauthn.get"
        or client["challenge"] != challenge["challenge_base64url"]
        or client["origin"] != challenge["origin"]
        or client["crossOrigin"] is not False
    ):
        raise AuthorityProtocolError("clientDataJSON binding mismatch")
    authenticator = _decode_base64url(
        assertion["authenticator_data_base64url"], field="authenticatorData"
    )
    if len(authenticator) < 37:
        raise AuthorityProtocolError("authenticatorData is truncated")
    expected_rp_hash = hashlib.sha256(challenge["rp_id"].encode()).digest()
    flags = authenticator[32]
    sign_count = int.from_bytes(authenticator[33:37], "big")
    if authenticator[:32] != expected_rp_hash:
        raise AuthorityProtocolError("WebAuthn RP hash mismatch")
    if flags & 0x01 == 0 or flags & 0x04 == 0:
        raise AuthorityProtocolError("WebAuthn UP and UV are required")
    if assertion["user_present"] is not True or assertion["user_verified"] is not True:
        raise AuthorityProtocolError("WebAuthn asserted flags mismatch")
    if assertion["sign_count"] != sign_count:
        raise AuthorityProtocolError("WebAuthn counter claim mismatch")
    if stored_sign_count > 0 and sign_count == 0:
        raise AuthorityProtocolError("WebAuthn counter rolled back to counterless mode")
    if sign_count == 0 and stored_sign_count != 0:
        raise AuthorityProtocolError(
            "counterless WebAuthn credentials require a counterless stored state"
        )
    if sign_count != 0 and sign_count <= stored_sign_count:
        raise AuthorityProtocolError("WebAuthn counter did not advance")
    if assertion["assertion_digest"] != _digest(
        _without(assertion, "assertion_digest")
    ):
        raise AuthorityProtocolError("WebAuthn assertion digest mismatch")
    immutable = _deep_immutable(assertion)
    candidate = _TraderAssertionCandidate(
        immutable,
        sign_count,
        _CANDIDATE_SEAL,
    )
    _register_candidate(
        candidate,
        kind="Trader WebAuthn assertion",
        document=immutable,
        canonical_bytes=_canonical_bytes(assertion),
        digest=assertion["assertion_digest"],
        context={
            "expected_environment": expected_environment,
            "expected_exact_four_authorization_digest": (
                expected_exact_four_authorization_digest
            ),
            "stored_sign_count": stored_sign_count,
            "one_use_key_available": one_use_key_available,
            "challenge_digest": challenge["challenge_digest"],
        },
    )
    return candidate


def _require_trader_assertion_candidate_provenance(
    candidate: object,
    *,
    expected_environment: str,
    expected_exact_four_authorization_digest: str,
    stored_sign_count: int,
    one_use_key_available: bool,
    challenge_digest: str,
) -> None:
    provenance = _require_candidate_provenance(
        candidate,
        expected_type=_TraderAssertionCandidate,
        kind="Trader WebAuthn assertion",
    )
    expected_context = tuple(
        sorted(
            {
                "expected_environment": expected_environment,
                "expected_exact_four_authorization_digest": (
                    expected_exact_four_authorization_digest
                ),
                "stored_sign_count": stored_sign_count,
                "one_use_key_available": one_use_key_available,
                "challenge_digest": challenge_digest,
            }.items()
        )
    )
    if provenance.context != expected_context:
        raise AuthorityProtocolError("Trader candidate verifier context mismatch")
    document = _strict_json(
        provenance.canonical_bytes,
        field="provenance-bound Trader assertion",
    )
    if (
        document["assertion_digest"] != provenance.digest
        or getattr(candidate, "sign_count", None) != document["sign_count"]
    ):
        raise AuthorityProtocolError("Trader candidate digest provenance mismatch")


def authorize_trader_webauthn_assertion(
    challenge_raw: bytes | str,
    assertion_raw: bytes | str,
    **expected: Any,
) -> None:
    candidate = inspect_trader_webauthn_assertion_candidate(
        challenge_raw, assertion_raw, **expected
    )
    challenge = _strict_json(challenge_raw, field="Trader WebAuthn challenge")
    provenance_expected = {
        key: expected[key]
        for key in (
            "expected_environment",
            "expected_exact_four_authorization_digest",
            "stored_sign_count",
            "one_use_key_available",
        )
    }
    _require_trader_assertion_candidate_provenance(
        candidate,
        challenge_digest=challenge["challenge_digest"],
        **provenance_expected,
    )
    raise AuthorityProtocolPending(
        "WebAuthn credential signature verifier and transactional one-use ledger "
        "are not provisioned"
    )
