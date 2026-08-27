"""Kernel-authenticated exact-four controlled execution writer v2.

The production entrypoint in this module accepts a committed Trader WebAuthn
handoff only over an AF_UNIX connection.  It authenticates the Trader service
with kernel peer credentials, receives exactly one unlinked read-only
SCM_RIGHTS descriptor, and independently revalidates the canonical challenge,
assertion signature, governed public credential, counter transition, and
append-only Trader event.  No reusable positive Trader capability crosses into
the product process.

Once validation succeeds, the handoff is consumed in the same SQLite
transaction that persists exactly four Paper artifacts, four Risk artifacts,
one aggregate Selection, one Knowledge artifact, a controlled authority event,
and a signed Controlled manifest.  Live construction remains fail closed until
root-owned activation state, the dedicated principals, a protected store, and
the Controlled Ed25519 key are provisioned.
"""

from __future__ import annotations

import array
import base64
import fcntl
import hashlib
import os
import socket
import sqlite3
import stat
import struct
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import MappingProxyType
from typing import Any, Callable, Mapping, NoReturn, Sequence

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

from execution.exact_four_binding import load_exact_four_execution_binding
from execution.exact_four_codec import (
    ExactFourAuthorityContractError,
    ExactFourAuthorityPending,
    _canonical_bytes,
    _parsed_timestamp,
    _strict_json_loads,
    canonical_authority_digest,
)
from execution.exact_four_trader_v2 import (
    _decode_canonical_base64url,
    _require_content_digest,
    _validate_webauthn_bytes,
    derive_exact_four_trader_one_use_key_v2,
    parse_and_validate_unverified_exact_four_trader_approval_subject_v2,
)
from execution.exact_four_results import (
    AggregateSelectionEvidenceV2,
    ExactFourPilotResultManifestV2,
    KnowledgeArtifactEvidenceV2,
    PaperResultEvidenceV2,
    RiskResultEvidenceV2,
    _evidence_from_document,
    load_exact_four_result_schema,
)
from execution.trader_webauthn_authority_v2 import (
    TRADER_ASSERTION_FORMAT,
    TRADER_CHALLENGE_FORMAT,
    TRADER_COMMITTED_HANDOFF_FORMAT,
    TRADER_LEDGER_BACKEND,
    TRADER_LEDGER_EVENT_FORMAT,
    ExactFourTraderCredentialRegistryV2,
    ExactFourTraderCredentialV2,
    ExactFourTraderRelyingPartyRegistryV2,
    ExactFourTraderRelyingPartyV2,
)
from scripts.finding_ledger_gate import require_pinned_finding_ledger_gate
from scripts.local_authority_service import AuthorityRequestContext


CONTROLLED_WRITER_MANIFEST_FORMAT = "controlled-exact-four-artifact-manifest/v2"
CONTROLLED_WRITER_ARTIFACT_FORMAT = "controlled-exact-four-artifact/v2"
CONTROLLED_WRITER_EVENT_FORMAT = "controlled-execution-authority-event/v2"
CONTROLLED_WRITER_ISSUER = "ControlledExactFourExecutionWriter/v2"
CONTROLLED_TRADER_HANDOFF_OPERATION = (
    "controlled_execution:consume_trader_handoff"
)
CONTROLLED_TRADER_HANDOFF_PURPOSE = "exact_four_one_shot_execution"
CONTROLLED_WRITER_LIVE_STATE = (
    "PENDING_PROTECTED_CONTROLLED_EXECUTION_PRINCIPAL_KEY_STORE_AND_TRADER_PEER"
)
CONTROLLED_WRITER_ARTIFACT_TYPES = (
    "Paper",
    "Risk",
    "Selection",
    "Knowledge",
)
CONTROLLED_EXECUTION_ACTIVATION_PATH = Path(
    "/etc/quant-platform/authorities/controlled_execution/activation.json"
)

_MAX_FRAME_BYTES = 1024 * 1024
_MAX_HANDOFF_BYTES = 1024 * 1024
_MAX_CLOCK_SKEW = timedelta(seconds=5)
_WRITER_CONSTRUCTION_TOKEN = object()
_WRITTEN_BUNDLE_TOKEN = object()
_VERIFIED_EXECUTOR_OUTPUT_TOKEN = object()

_REQUEST_FIELDS = frozenset(
    {"format", "request_id", "operation", "purpose", "payload"}
)
_CHALLENGE_FIELDS = frozenset(
    {
        "format",
        "environment",
        "status",
        "challenge_id",
        "challenge_base64url",
        "approval_subject_id",
        "rp_policy_generation",
        "rp_policy_digest",
        "rp_id",
        "origin",
        "user_presence_required",
        "user_verification_required",
        "issued_at",
        "expires_at",
        "one_use_key",
        "challenge_digest",
    }
)
_ASSERTION_FIELDS = frozenset(
    {
        "format",
        "environment",
        "status",
        "challenge_id",
        "challenge_digest",
        "approval_subject_id",
        "rp_policy_generation",
        "rp_policy_digest",
        "credential_id_base64url",
        "authenticator_data_base64url",
        "client_data_json_base64url",
        "signature_base64url",
        "rp_id",
        "origin",
        "user_present",
        "user_verified",
        "sign_count",
        "asserted_at",
        "one_use_key",
        "assertion_digest",
    }
)
_CREDENTIAL_EVIDENCE_FIELDS = frozenset(
    {
        "format",
        "environment",
        "credential_id_base64url",
        "credential_public_key_digest",
        "credential_algorithm",
        "key_backend",
        "credential_registry_generation",
        "credential_registry_digest",
        "rp_policy_digest",
        "counter_mode",
    }
)
_TRADER_EVENT_FIELDS = frozenset(
    {
        "format",
        "environment",
        "ledger_backend_id",
        "sequence",
        "event_id",
        "prior_event_digest",
        "request_digest",
        "approval_subject_id",
        "challenge_id",
        "challenge_digest",
        "assertion_digest",
        "one_use_key",
        "one_use_prior_status",
        "one_use_result_status",
        "one_use_cas_status",
        "credential_id_base64url",
        "credential_registry_generation",
        "credential_registry_digest",
        "counter_mode",
        "prior_sign_count",
        "asserted_sign_count",
        "result_sign_count",
        "counter_cas_status",
        "transaction_status",
        "committed_at",
        "automatic_promotion",
        "mass_research_enabled",
        "live_trading_enabled",
        "event_digest",
    }
)
_HANDOFF_FIELDS = frozenset(
    {
        "format",
        "environment",
        "handoff_status",
        "ready_authority_response_digest",
        "approval_subject_id",
        "approval_subject",
        "challenge_evidence",
        "assertion_evidence",
        "credential_registry_evidence",
        "one_use_counter_event",
        "issued_at",
        "expires_at",
        "automatic_promotion",
        "mass_research_enabled",
        "live_trading_enabled",
        "handoff_id",
    }
)


class ControlledExecutionWriterV2Error(ExactFourAuthorityContractError):
    """A peer, handoff, signature, or immutable transaction was rejected."""


def _sha256_bytes(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def _require_digest(value: Any, label: str) -> str:
    if (
        type(value) is not str
        or len(value) != 71
        or not value.startswith("sha256:")
        or any(character not in "0123456789abcdef" for character in value[7:])
    ):
        raise ControlledExecutionWriterV2Error(
            f"{label} must be a canonical sha256 digest"
        )
    return value


def _require_uuid4(value: Any, label: str) -> str:
    if type(value) is not str:
        raise ControlledExecutionWriterV2Error(f"{label} must be canonical UUID4")
    try:
        parsed = uuid.UUID(value)
    except (ValueError, AttributeError) as exc:
        raise ControlledExecutionWriterV2Error(
            f"{label} must be canonical UUID4"
        ) from exc
    if parsed.version != 4 or str(parsed) != value:
        raise ControlledExecutionWriterV2Error(f"{label} must be canonical UUID4")
    return value


def _require_bytes(value: Any, label: str) -> bytes:
    if type(value) is not bytes or not value:
        raise ControlledExecutionWriterV2Error(
            f"{label} must be exact non-empty bytes"
        )
    return value


def _aware_utc(clock: Callable[[], datetime], label: str) -> datetime:
    value = clock()
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise ControlledExecutionWriterV2Error(
            f"{label} must return an exact aware datetime"
        )
    return value.astimezone(timezone.utc)


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


class _OneCallControlledPilotAuthorizationV2:
    """Stack-local executor permit invalidated immediately after one callback."""

    __slots__ = ("_context", "_active", "_used")

    def __init__(self, context: Mapping[str, Any]) -> None:
        self._context = MappingProxyType(dict(context))
        self._active = True
        self._used = False

    def invoke(
        self,
        bounded_executor: Callable[[Mapping[str, Any]], Mapping[str, Any]],
    ) -> Mapping[str, Any]:
        if not self._active or self._used or not callable(bounded_executor):
            raise ControlledExecutionWriterV2Error(
                "bounded Controlled executor authorization is not available"
            )
        self._used = True
        try:
            result = bounded_executor(self._context)
            if type(result) is not dict:
                raise ControlledExecutionWriterV2Error(
                    "bounded Controlled executor must return one exact output object"
                )
            return result
        finally:
            self._active = False


@dataclass(frozen=True, slots=True, init=False)
class _VerifiedBoundedExecutionOutputV2:
    manifest: ExactFourPilotResultManifestV2
    contents: Mapping[str, bytes]

    def __init__(
        self,
        manifest: ExactFourPilotResultManifestV2,
        contents: Mapping[str, bytes],
        *,
        _token: object,
    ) -> None:
        if _token is not _VERIFIED_EXECUTOR_OUTPUT_TOKEN:
            raise ControlledExecutionWriterV2Error(
                "bounded executor output requires canonical result revalidation"
            )
        object.__setattr__(self, "manifest", manifest)
        object.__setattr__(
            self,
            "contents",
            MappingProxyType({key: bytes(value) for key, value in contents.items()}),
        )


class WrittenExactFourControlledArtifactsV2:
    """Immutable signed Controlled result returned after the atomic commit."""

    __slots__ = ("_manifest", "_contents")

    def __setattr__(self, name: str, value: Any) -> NoReturn:
        del name, value
        raise AttributeError("written exact-four controlled artifacts are immutable")

    def __delattr__(self, name: str) -> NoReturn:
        del name
        raise AttributeError("written exact-four controlled artifacts are immutable")

    def __init__(
        self,
        manifest: bytes,
        contents: Mapping[str, bytes],
        *,
        _token: object,
    ) -> None:
        if _token is not _WRITTEN_BUNDLE_TOKEN:
            raise ControlledExecutionWriterV2Error(
                "written artifacts require a committed Controlled transaction"
            )
        copied: dict[str, bytes] = {}
        for key, value in contents.items():
            if type(key) is not str or type(value) is not bytes:
                raise ControlledExecutionWriterV2Error(
                    "written artifact content map is invalid"
                )
            copied[key] = bytes(value)
        object.__setattr__(self, "_manifest", bytes(manifest))
        object.__setattr__(self, "_contents", MappingProxyType(copied))

    @property
    def canonical_manifest(self) -> bytes:
        return self._manifest

    @property
    def contents(self) -> Mapping[str, bytes]:
        return self._contents

    def to_dict(self) -> dict[str, Any]:
        return _strict_json_loads(
            self._manifest,
            label="written exact-four Controlled manifest",
        )

    @property
    def manifest_id(self) -> str:
        return self.to_dict()["manifest_id"]

    def verify_signature(self, public_key: Ed25519PublicKey) -> bool:
        if not isinstance(public_key, Ed25519PublicKey):
            return False
        document = self.to_dict()
        signature_text = document.pop("signature", None)
        if type(signature_text) is not str or not signature_text.startswith(
            "ed25519:"
        ):
            return False
        signed_body = dict(document)
        declared_manifest_id = signed_body.pop("manifest_id", None)
        if declared_manifest_id != canonical_authority_digest(signed_body):
            return False
        try:
            signature = base64.b64decode(
                signature_text[len("ed25519:") :], validate=True
            )
            if len(signature) != 64:
                return False
            public_key.verify(signature, _canonical_bytes(document))
        except (InvalidSignature, TypeError, ValueError):
            return False
        return True


@dataclass(frozen=True, slots=True)
class _ControlledWriterSignerV2:
    key_id: str
    private_key: Ed25519PrivateKey

    def __post_init__(self) -> None:
        if (
            type(self.key_id) is not str
            or not self.key_id
            or self.key_id != self.key_id.strip()
            or not isinstance(self.private_key, Ed25519PrivateKey)
        ):
            raise ControlledExecutionWriterV2Error(
                "Controlled writer signer identity is invalid"
            )

    def sign(self, document: dict[str, Any]) -> str:
        return "ed25519:" + base64.b64encode(
            self.private_key.sign(_canonical_bytes(document))
        ).decode("ascii")


class SQLiteControlledExecutionWriterV2:
    """Peer-authenticated, verify-again, atomic one-shot Controlled service."""

    __slots__ = (
        "_path",
        "environment",
        "_signer",
        "_clock",
        "_trader_uid",
        "_rps",
        "_credentials",
        "_server_bound",
    )

    def __init__(
        self,
        path: Path,
        *,
        environment: str,
        signer: _ControlledWriterSignerV2,
        clock: Callable[[], datetime],
        trader_uid: int,
        relying_parties: ExactFourTraderRelyingPartyRegistryV2,
        credentials: ExactFourTraderCredentialRegistryV2,
        server_bound: bool,
        _token: object,
    ) -> None:
        if _token is not _WRITER_CONSTRUCTION_TOKEN:
            raise ExactFourAuthorityPending(CONTROLLED_WRITER_LIVE_STATE)
        if not isinstance(path, Path) or not path.is_absolute():
            raise ControlledExecutionWriterV2Error(
                "Controlled writer requires an absolute authority-owned store path"
            )
        if type(environment) is not str or not environment:
            raise ControlledExecutionWriterV2Error(
                "Controlled writer environment is invalid"
            )
        if type(trader_uid) is not int or trader_uid < 0:
            raise ControlledExecutionWriterV2Error("Trader peer UID is invalid")
        if type(server_bound) is not bool:
            raise ControlledExecutionWriterV2Error(
                "Controlled AuthorityServer binding is invalid"
            )
        rp = relying_parties.require(environment)
        for credential in credentials.credentials:
            if credential.environment == environment and (
                credential.rp_policy_digest != rp.policy_digest
            ):
                raise ControlledExecutionWriterV2Error(
                    "Controlled credential registry is not bound to its RP policy"
                )
        self._path = path
        self.environment = environment
        self._signer = signer
        self._clock = clock
        self._trader_uid = trader_uid
        self._rps = relying_parties
        self._credentials = credentials
        self._server_bound = server_bound
        self._initialize()

    def _require_positive_operation(self) -> None:
        if self._server_bound is not True:
            raise ExactFourAuthorityPending(
                "positive Controlled operations require the local AuthorityServer "
                "entrypoint"
            )
        require_pinned_finding_ledger_gate()

    @property
    def public_key(self) -> Ed25519PublicKey:
        return self._signer.private_key.public_key()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(
            str(self._path),
            isolation_level=None,
            timeout=10.0,
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 10000")
        return connection

    def _initialize(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.executescript(
                """
                PRAGMA journal_mode = WAL;
                PRAGMA synchronous = FULL;
                CREATE TABLE IF NOT EXISTS controlled_authority_metadata (
                    environment TEXT PRIMARY KEY,
                    trader_uid INTEGER NOT NULL,
                    rp_registry_digest TEXT NOT NULL,
                    credential_registry_digest TEXT NOT NULL,
                    writer_key_id TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS controlled_credential_counters (
                    environment TEXT NOT NULL,
                    credential_id TEXT NOT NULL,
                    public_key_digest TEXT NOT NULL,
                    registry_digest TEXT NOT NULL,
                    counter_mode TEXT NOT NULL,
                    sign_count INTEGER NOT NULL CHECK(sign_count >= 0),
                    PRIMARY KEY(environment, credential_id)
                );
                CREATE TABLE IF NOT EXISTS controlled_handoffs (
                    environment TEXT NOT NULL,
                    handoff_id TEXT NOT NULL,
                    handoff_digest TEXT NOT NULL UNIQUE,
                    trader_event_digest TEXT NOT NULL UNIQUE,
                    trader_event_sequence INTEGER NOT NULL,
                    assertion_digest TEXT NOT NULL UNIQUE,
                    one_use_key TEXT NOT NULL UNIQUE,
                    credential_id TEXT NOT NULL,
                    prior_sign_count INTEGER NOT NULL,
                    result_sign_count INTEGER NOT NULL,
                    consume_request_digest TEXT NOT NULL UNIQUE,
                    authority_request_digest TEXT NOT NULL UNIQUE,
                    authenticated_trader_uid INTEGER NOT NULL,
                    authenticated_trader_caller TEXT NOT NULL,
                    canonical_handoff BLOB NOT NULL,
                    status TEXT NOT NULL CHECK(status = 'CONSUMED'),
                    consumed_at TEXT NOT NULL,
                    PRIMARY KEY(environment, handoff_id)
                );
                CREATE TABLE IF NOT EXISTS controlled_execution_attempts (
                    environment TEXT NOT NULL,
                    handoff_id TEXT NOT NULL,
                    outcome TEXT NOT NULL CHECK(outcome IN ('SUCCEEDED','FAILED')),
                    retry_policy TEXT NOT NULL CHECK(retry_policy = 'DENY'),
                    artifact_set_digest TEXT,
                    error_class TEXT,
                    completed_at TEXT NOT NULL,
                    PRIMARY KEY(environment, handoff_id),
                    FOREIGN KEY(environment, handoff_id)
                        REFERENCES controlled_handoffs(environment, handoff_id)
                );
                CREATE TABLE IF NOT EXISTS controlled_artifacts (
                    environment TEXT NOT NULL,
                    handoff_id TEXT NOT NULL,
                    artifact_type TEXT NOT NULL,
                    ordinal INTEGER NOT NULL,
                    artifact_id TEXT NOT NULL UNIQUE,
                    content_digest TEXT NOT NULL,
                    canonical_metadata BLOB NOT NULL,
                    immutable_content BLOB NOT NULL,
                    PRIMARY KEY(environment, handoff_id, artifact_type, ordinal),
                    FOREIGN KEY(environment, handoff_id)
                        REFERENCES controlled_handoffs(environment, handoff_id)
                );
                CREATE TABLE IF NOT EXISTS controlled_writer_events (
                    environment TEXT NOT NULL,
                    sequence INTEGER NOT NULL,
                    event_id TEXT NOT NULL UNIQUE,
                    event_digest TEXT NOT NULL UNIQUE,
                    prior_event_digest TEXT,
                    handoff_id TEXT NOT NULL UNIQUE,
                    write_request_digest TEXT NOT NULL UNIQUE,
                    canonical_event BLOB NOT NULL,
                    PRIMARY KEY(environment, sequence),
                    FOREIGN KEY(environment, handoff_id)
                        REFERENCES controlled_handoffs(environment, handoff_id)
                );
                CREATE TABLE IF NOT EXISTS controlled_manifests (
                    environment TEXT NOT NULL,
                    handoff_id TEXT NOT NULL,
                    manifest_id TEXT NOT NULL UNIQUE,
                    write_request_digest TEXT NOT NULL UNIQUE,
                    controlled_event_digest TEXT NOT NULL UNIQUE,
                    canonical_manifest BLOB NOT NULL,
                    PRIMARY KEY(environment, handoff_id),
                    FOREIGN KEY(controlled_event_digest)
                        REFERENCES controlled_writer_events(event_digest)
                );
                CREATE TRIGGER IF NOT EXISTS controlled_metadata_no_update
                    BEFORE UPDATE ON controlled_authority_metadata BEGIN
                    SELECT RAISE(ABORT, 'Controlled metadata is immutable');
                    END;
                CREATE TRIGGER IF NOT EXISTS controlled_metadata_no_delete
                    BEFORE DELETE ON controlled_authority_metadata BEGIN
                    SELECT RAISE(ABORT, 'Controlled metadata is immutable');
                    END;
                CREATE TRIGGER IF NOT EXISTS controlled_counters_no_delete
                    BEFORE DELETE ON controlled_credential_counters BEGIN
                    SELECT RAISE(ABORT, 'Controlled credential counters cannot be deleted');
                    END;
                CREATE TRIGGER IF NOT EXISTS controlled_handoffs_no_update
                    BEFORE UPDATE ON controlled_handoffs BEGIN
                    SELECT RAISE(ABORT, 'Controlled handoffs are immutable');
                    END;
                CREATE TRIGGER IF NOT EXISTS controlled_handoffs_no_delete
                    BEFORE DELETE ON controlled_handoffs BEGIN
                    SELECT RAISE(ABORT, 'Controlled handoffs are immutable');
                    END;
                CREATE TRIGGER IF NOT EXISTS controlled_attempts_no_update
                    BEFORE UPDATE ON controlled_execution_attempts BEGIN
                    SELECT RAISE(ABORT, 'Controlled execution attempts are immutable');
                    END;
                CREATE TRIGGER IF NOT EXISTS controlled_attempts_no_delete
                    BEFORE DELETE ON controlled_execution_attempts BEGIN
                    SELECT RAISE(ABORT, 'Controlled execution attempts are immutable');
                    END;
                CREATE TRIGGER IF NOT EXISTS controlled_artifacts_no_update
                    BEFORE UPDATE ON controlled_artifacts BEGIN
                    SELECT RAISE(ABORT, 'Controlled artifacts are immutable');
                    END;
                CREATE TRIGGER IF NOT EXISTS controlled_artifacts_no_delete
                    BEFORE DELETE ON controlled_artifacts BEGIN
                    SELECT RAISE(ABORT, 'Controlled artifacts are immutable');
                    END;
                CREATE TRIGGER IF NOT EXISTS controlled_writer_events_no_update
                    BEFORE UPDATE ON controlled_writer_events BEGIN
                    SELECT RAISE(ABORT, 'Controlled writer events are immutable');
                    END;
                CREATE TRIGGER IF NOT EXISTS controlled_writer_events_no_delete
                    BEFORE DELETE ON controlled_writer_events BEGIN
                    SELECT RAISE(ABORT, 'Controlled writer events are immutable');
                    END;
                CREATE TRIGGER IF NOT EXISTS controlled_manifests_no_update
                    BEFORE UPDATE ON controlled_manifests BEGIN
                    SELECT RAISE(ABORT, 'Controlled manifests are immutable');
                    END;
                CREATE TRIGGER IF NOT EXISTS controlled_manifests_no_delete
                    BEFORE DELETE ON controlled_manifests BEGIN
                    SELECT RAISE(ABORT, 'Controlled manifests are immutable');
                    END;
                """
            )
            expected = (
                self._trader_uid,
                self._rps.registry_digest,
                self._credentials.registry_digest,
                self._signer.key_id,
            )
            row = connection.execute(
                "SELECT trader_uid, rp_registry_digest, "
                "credential_registry_digest, writer_key_id FROM "
                "controlled_authority_metadata WHERE environment = ?",
                (self.environment,),
            ).fetchone()
            if row is None:
                connection.execute(
                    "INSERT INTO controlled_authority_metadata VALUES (?, ?, ?, ?, ?)",
                    (self.environment, *expected),
                )
            elif tuple(row) != expected:
                raise ControlledExecutionWriterV2Error(
                    "Controlled authority identity changed without store migration"
                )
            for credential in self._credentials.credentials:
                if credential.environment != self.environment:
                    continue
                existing_counter = connection.execute(
                    "SELECT public_key_digest, registry_digest, counter_mode "
                    "FROM controlled_credential_counters WHERE environment = ? "
                    "AND credential_id = ?",
                    (self.environment, credential.credential_id_base64url),
                ).fetchone()
                counter_identity = (
                    credential.public_key_digest,
                    self._credentials.registry_digest,
                    credential.counter_mode,
                )
                if existing_counter is None:
                    connection.execute(
                        "INSERT INTO controlled_credential_counters VALUES "
                        "(?, ?, ?, ?, ?, ?)",
                        (
                            self.environment,
                            credential.credential_id_base64url,
                            *counter_identity,
                            credential.initial_sign_count,
                        ),
                    )
                elif tuple(existing_counter) != counter_identity:
                    raise ControlledExecutionWriterV2Error(
                        "Controlled credential counter identity changed without migration"
                    )

    def _verify_handoff(
        self,
        handoff_bytes: bytes,
        *,
        expected_handoff_id: str,
    ) -> dict[str, Any]:
        document = _strict_json_loads(
            handoff_bytes,
            label="committed exact-four Trader handoff",
        )
        if set(document) != set(_HANDOFF_FIELDS):
            raise ControlledExecutionWriterV2Error(
                "Trader committed handoff fields are not closed"
            )
        body = dict(document)
        declared_handoff_id = body.pop("handoff_id", None)
        if (
            document.get("format") != TRADER_COMMITTED_HANDOFF_FORMAT
            or document.get("environment") != self.environment
            or document.get("handoff_status") != "COMMITTED"
            or declared_handoff_id != expected_handoff_id
            or declared_handoff_id != canonical_authority_digest(body)
            or document.get("automatic_promotion") is not False
            or document.get("mass_research_enabled") is not False
            or document.get("live_trading_enabled") is not False
        ):
            raise ControlledExecutionWriterV2Error(
                "Trader committed handoff identity or policy is invalid"
            )
        _require_digest(
            document["ready_authority_response_digest"],
            "READY authority response digest",
        )

        subject_document = document["approval_subject"]
        if type(subject_document) is not dict:
            raise ControlledExecutionWriterV2Error(
                "Trader approval subject must be an exact object"
            )
        subject = parse_and_validate_unverified_exact_four_trader_approval_subject_v2(
            _canonical_bytes(subject_document)
        )
        if (
            document["approval_subject_id"] != subject.approval_subject_id
            or subject_document != subject.to_dict()
        ):
            raise ControlledExecutionWriterV2Error(
                "Trader handoff approval subject content id is invalid"
            )

        challenge = document["challenge_evidence"]
        assertion = document["assertion_evidence"]
        credential_evidence = document["credential_registry_evidence"]
        event = document["one_use_counter_event"]
        if (
            type(challenge) is not dict
            or set(challenge) != set(_CHALLENGE_FIELDS)
            or type(assertion) is not dict
            or set(assertion) != set(_ASSERTION_FIELDS)
            or type(credential_evidence) is not dict
            or set(credential_evidence) != set(_CREDENTIAL_EVIDENCE_FIELDS)
            or type(event) is not dict
            or set(event) != set(_TRADER_EVENT_FIELDS)
        ):
            raise ControlledExecutionWriterV2Error(
                "Trader handoff nested evidence fields are not closed"
            )
        challenge_digest = _require_content_digest(
            challenge,
            digest_field="challenge_digest",
            label="Controlled-reverified WebAuthn challenge",
        )
        assertion_digest = _require_content_digest(
            assertion,
            digest_field="assertion_digest",
            label="Controlled-reverified WebAuthn assertion",
        )
        event_digest = _require_content_digest(
            event,
            digest_field="event_digest",
            label="Controlled-reverified Trader event",
        )
        if (
            challenge["format"] != TRADER_CHALLENGE_FORMAT
            or challenge["status"] != "ISSUED"
            or challenge["environment"] != self.environment
            or challenge["approval_subject_id"] != subject.approval_subject_id
            or challenge["user_presence_required"] is not True
            or challenge["user_verification_required"] is not True
        ):
            raise ControlledExecutionWriterV2Error(
                "Controlled-reverified WebAuthn challenge identity is invalid"
            )
        challenge_body = dict(challenge)
        challenge_body.pop("challenge_digest")
        one_use_key = challenge_body.pop("one_use_key")
        if one_use_key != derive_exact_four_trader_one_use_key_v2(challenge_body):
            raise ControlledExecutionWriterV2Error(
                "Controlled-reverified challenge one-use key is invalid"
            )

        rp = self._rps.require(self.environment)
        if (
            challenge["rp_policy_generation"] != rp.policy_generation
            or challenge["rp_policy_digest"] != rp.policy_digest
            or challenge["rp_id"] != rp.rp_id
            or challenge["origin"] != rp.origin
        ):
            raise ControlledExecutionWriterV2Error(
                "Trader challenge is not bound to Controlled's governed RP registry"
            )
        if assertion["format"] != TRADER_ASSERTION_FORMAT or assertion[
            "status"
        ] != "VERIFIED":
            raise ControlledExecutionWriterV2Error(
                "Controlled-reverified WebAuthn assertion identity is invalid"
            )
        for field in (
            "environment",
            "challenge_id",
            "approval_subject_id",
            "rp_policy_generation",
            "rp_policy_digest",
            "rp_id",
            "origin",
            "one_use_key",
        ):
            if assertion[field] != challenge[field]:
                raise ControlledExecutionWriterV2Error(
                    f"Controlled-reverified assertion {field} is not challenge-bound"
                )
        if assertion["challenge_digest"] != challenge_digest:
            raise ControlledExecutionWriterV2Error(
                "Controlled-reverified assertion challenge digest mismatch"
            )
        _validate_webauthn_bytes(challenge, assertion)

        credential = self._credentials.require(
            self.environment,
            assertion["credential_id_base64url"],
        )
        if (
            credential_evidence["format"]
            != "exact-four-trader-credential-evidence/v2"
            or credential_evidence["environment"] != self.environment
            or credential_evidence["credential_id_base64url"]
            != credential.credential_id_base64url
            or credential_evidence["credential_public_key_digest"]
            != credential.public_key_digest
            or credential_evidence["credential_algorithm"] != credential.algorithm
            or credential_evidence["key_backend"] != credential.key_backend
            or credential_evidence["credential_registry_generation"]
            != self._credentials.generation
            or credential_evidence["credential_registry_digest"]
            != self._credentials.registry_digest
            or credential_evidence["rp_policy_digest"] != credential.rp_policy_digest
            or credential_evidence["counter_mode"] != credential.counter_mode
        ):
            raise ControlledExecutionWriterV2Error(
                "Trader credential evidence is not bound to Controlled's public registry"
            )
        authenticator_data = _decode_canonical_base64url(
            assertion["authenticator_data_base64url"],
            label="Controlled authenticatorData",
            minimum_bytes=37,
            maximum_bytes=4096,
        )
        client_data = _decode_canonical_base64url(
            assertion["client_data_json_base64url"],
            label="Controlled clientDataJSON",
            minimum_bytes=32,
            maximum_bytes=8192,
        )
        signature = _decode_canonical_base64url(
            assertion["signature_base64url"],
            label="Controlled WebAuthn signature",
            minimum_bytes=32,
            maximum_bytes=1024,
        )
        try:
            credential.public_key.verify(
                signature,
                authenticator_data + hashlib.sha256(client_data).digest(),
                ec.ECDSA(hashes.SHA256()),
            )
        except (InvalidSignature, ValueError) as exc:
            raise ControlledExecutionWriterV2Error(
                "Controlled WebAuthn ES256 signature revalidation failed"
            ) from exc

        request_body = {
            "format": "exact-four-trader-authority-request/v2",
            "environment": self.environment,
            "approval_subject_id": subject.approval_subject_id,
            "ready_authority_response_digest": document[
                "ready_authority_response_digest"
            ],
            "challenge_digest": challenge_digest,
            "assertion_digest": assertion_digest,
            "credential_registry_digest": self._credentials.registry_digest,
            "credential_public_key_digest": credential.public_key_digest,
        }
        expected_request_digest = canonical_authority_digest(request_body)
        sequence = event["sequence"]
        prior_event_digest = event["prior_event_digest"]
        if (
            event["format"] != TRADER_LEDGER_EVENT_FORMAT
            or event["environment"] != self.environment
            or event["ledger_backend_id"] != TRADER_LEDGER_BACKEND
            or type(sequence) is not int
            or sequence < 1
            or (sequence == 1 and prior_event_digest is not None)
            or (
                sequence > 1
                and _require_digest(prior_event_digest, "prior Trader event digest")
                != prior_event_digest
            )
            or event["request_digest"] != expected_request_digest
            or event["approval_subject_id"] != subject.approval_subject_id
            or event["challenge_id"] != challenge["challenge_id"]
            or event["challenge_digest"] != challenge_digest
            or event["assertion_digest"] != assertion_digest
            or event["one_use_key"] != challenge["one_use_key"]
            or event["one_use_prior_status"] != "AVAILABLE"
            or event["one_use_result_status"] != "CONSUMED"
            or event["one_use_cas_status"] != "APPLIED"
            or event["credential_id_base64url"]
            != credential.credential_id_base64url
            or event["credential_registry_generation"]
            != self._credentials.generation
            or event["credential_registry_digest"]
            != self._credentials.registry_digest
            or event["counter_mode"] != credential.counter_mode
            or event["asserted_sign_count"] != assertion["sign_count"]
            or event["result_sign_count"] != assertion["sign_count"]
            or event["transaction_status"] != "COMMITTED"
            or event["automatic_promotion"] is not False
            or event["mass_research_enabled"] is not False
            or event["live_trading_enabled"] is not False
        ):
            raise ControlledExecutionWriterV2Error(
                "Controlled-reverified Trader one-use/counter event is invalid"
            )
        _require_uuid4(event["event_id"], "Trader event_id")
        prior_count = event["prior_sign_count"]
        asserted_count = event["asserted_sign_count"]
        if (
            type(prior_count) is not int
            or prior_count < 0
            or type(asserted_count) is not int
            or asserted_count < 0
            or (
                credential.counter_mode == "COUNTING"
                and (
                    asserted_count <= prior_count
                    or event["counter_cas_status"] != "APPLIED"
                )
            )
            or (
                credential.counter_mode == "COUNTERLESS"
                and (
                    prior_count != 0
                    or asserted_count != 0
                    or event["counter_cas_status"] != "NOT_APPLICABLE"
                )
            )
        ):
            raise ControlledExecutionWriterV2Error(
                "Controlled-reverified WebAuthn counter transition is invalid"
            )

        now = _aware_utc(self._clock, "Controlled authority clock")
        challenge_issued = _parsed_timestamp(
            challenge["issued_at"], "Controlled challenge issued_at"
        ).astimezone(timezone.utc)
        challenge_expires = _parsed_timestamp(
            challenge["expires_at"], "Controlled challenge expires_at"
        ).astimezone(timezone.utc)
        asserted_at = _parsed_timestamp(
            assertion["asserted_at"], "Controlled assertion asserted_at"
        ).astimezone(timezone.utc)
        committed_at = _parsed_timestamp(
            event["committed_at"], "Controlled Trader event committed_at"
        ).astimezone(timezone.utc)
        handoff_issued = _parsed_timestamp(
            document["issued_at"], "Controlled handoff issued_at"
        ).astimezone(timezone.utc)
        handoff_expires = _parsed_timestamp(
            document["expires_at"], "Controlled handoff expires_at"
        ).astimezone(timezone.utc)
        ready_issued = _parsed_timestamp(
            subject.ready_issued_at, "Controlled READY issued_at"
        ).astimezone(timezone.utc)
        ready_expires = _parsed_timestamp(
            subject.ready_expires_at, "Controlled READY expires_at"
        ).astimezone(timezone.utc)
        credential_effective = _parsed_timestamp(
            credential.effective_at, "Controlled credential effective_at"
        ).astimezone(timezone.utc)
        rp_effective = _parsed_timestamp(
            rp.effective_at, "Controlled RP effective_at"
        ).astimezone(timezone.utc)
        if not (
            ready_issued <= challenge_issued
            and credential_effective <= asserted_at
            and rp_effective <= asserted_at
            and challenge_issued <= asserted_at <= committed_at + _MAX_CLOCK_SKEW
            and committed_at == handoff_issued
            and handoff_expires == challenge_expires
            and challenge_expires <= ready_expires
            and committed_at <= now + _MAX_CLOCK_SKEW
            and now < handoff_expires
        ):
            raise ControlledExecutionWriterV2Error(
                "Controlled-reverified Trader handoff is outside its authority window"
            )
        document["_controlled_event_digest"] = event_digest
        return document

    @staticmethod
    def _content_digest(content: bytes) -> str:
        return _sha256_bytes(content)

    def _execution_context(
        self,
        handoff: Mapping[str, Any],
        *,
        canonical_handoff: bytes,
    ) -> dict[str, Any]:
        binding = load_exact_four_execution_binding()
        request_id = canonical_authority_digest(
            {
                "format": "controlled-exact-four-execution-request/v2",
                "environment": self.environment,
                "handoff_id": handoff["handoff_id"],
                "approval_subject_id": handoff["approval_subject_id"],
                "exact_four_binding_digest": binding.binding_digest,
            }
        )
        lease_id = canonical_authority_digest(
            {
                "format": "controlled-exact-four-execution-lease/v2",
                "environment": self.environment,
                "handoff_id": handoff["handoff_id"],
                "one_use_key": handoff["challenge_evidence"]["one_use_key"],
            }
        )
        idempotency_key = canonical_authority_digest(
            {
                "format": "controlled-exact-four-execution-idempotency/v2",
                "environment": self.environment,
                "lease_id": lease_id,
            }
        )
        subject = handoff["approval_subject"]
        return {
            "format": "bounded-controlled-pilot-execution-context/v2",
            "environment": self.environment,
            "pilot_run_id": subject["pilot_run_id"],
            "readiness_attestation_id": subject["readiness_attestation_id"],
            "trader_authorization_id": handoff["handoff_id"],
            "trader_handoff_digest": _sha256_bytes(canonical_handoff),
            "execution_request_id": request_id,
            "lease_id": lease_id,
            "idempotency_key": idempotency_key,
            "exact_four_binding_digest": binding.binding_digest,
            "controlled_pilot_policy_digest": binding.policy.policy_digest,
            "budget_scope_digest": binding.budget_scope_digest,
            "plan_set_digest": binding.plan_set_digest,
            "dependency_closure_set_digest": (
                binding.dependency_closure_set_digest
            ),
            "profile_set_digest": binding.profile_set_digest,
            "required_dataset_membership_digest": (
                binding.required_dataset_membership_digest
            ),
            "snapshot_id": subject["snapshot_id"],
            "ready_manifest_digest": subject["ready_manifest_digest"],
            "immutable_snapshot_digest": subject["immutable_snapshot_digest"],
            "execution_issued_at": handoff["issued_at"],
            "execution_expires_at": handoff["expires_at"],
            "plan_bindings": [item.to_dict() for item in binding.plan_bindings],
            "automatic_promotion": False,
            "mass_research_enabled": False,
            "live_trading_enabled": False,
        }

    def _verify_executor_output(
        self,
        raw: Mapping[str, Any],
        *,
        context: Mapping[str, Any],
    ) -> _VerifiedBoundedExecutionOutputV2:
        if type(raw) is not dict or set(raw) != {"manifest", "contents"}:
            raise ControlledExecutionWriterV2Error(
                "bounded executor output fields are not closed"
            )
        manifest_raw = raw["manifest"]
        contents_raw = raw["contents"]
        if type(manifest_raw) is not bytes or type(contents_raw) is not dict:
            raise ControlledExecutionWriterV2Error(
                "bounded executor manifest and content container types are invalid"
            )
        manifest_document = _strict_json_loads(
            manifest_raw,
            label="bounded exact-four result manifest",
        )
        try:
            from jsonschema import Draft202012Validator, FormatChecker

            errors = sorted(
                Draft202012Validator(
                    load_exact_four_result_schema(),
                    format_checker=FormatChecker(),
                ).iter_errors(manifest_document),
                key=lambda item: tuple(str(part) for part in item.path),
            )
        except ExactFourAuthorityContractError:
            raise
        except Exception as exc:
            raise ControlledExecutionWriterV2Error(
                "cannot validate bounded exact-four result schema"
            ) from exc
        if errors:
            raise ControlledExecutionWriterV2Error(
                "bounded executor result violates the canonical exact-four schema"
            )
        body = dict(manifest_document)
        declared_manifest_id = body.pop("manifest_id", None)
        paper_rows = body.pop("paper_results", None)
        risk_rows = body.pop("risk_results", None)
        selection_row = body.pop("aggregate_selection", None)
        knowledge_row = body.pop("knowledge_artifact", None)
        if type(paper_rows) is not list or type(risk_rows) is not list:
            raise ControlledExecutionWriterV2Error(
                "bounded result Paper/Risk evidence must be exact arrays"
            )
        try:
            papers = tuple(
                _evidence_from_document(PaperResultEvidenceV2, item)
                for item in paper_rows
            )
            risks = tuple(
                _evidence_from_document(RiskResultEvidenceV2, item)
                for item in risk_rows
            )
            selection = _evidence_from_document(
                AggregateSelectionEvidenceV2, selection_row
            )
            knowledge = _evidence_from_document(
                KnowledgeArtifactEvidenceV2, knowledge_row
            )
            manifest = ExactFourPilotResultManifestV2(
                paper_results=papers,
                risk_results=risks,
                aggregate_selection=selection,
                knowledge_artifact=knowledge,
                **body,
            )
        except (ExactFourAuthorityContractError, TypeError) as exc:
            raise ControlledExecutionWriterV2Error(
                "bounded executor result evidence is not canonical exact-four"
            ) from exc
        if (
            declared_manifest_id != manifest.manifest_id
            or manifest_document != manifest.to_dict()
        ):
            raise ControlledExecutionWriterV2Error(
                "bounded result manifest content id is invalid"
            )
        expected_fields = (
            "pilot_run_id",
            "readiness_attestation_id",
            "trader_authorization_id",
            "execution_request_id",
            "lease_id",
            "idempotency_key",
            "exact_four_binding_digest",
            "controlled_pilot_policy_digest",
            "budget_scope_digest",
            "plan_set_digest",
            "dependency_closure_set_digest",
            "profile_set_digest",
            "required_dataset_membership_digest",
            "snapshot_id",
            "ready_manifest_digest",
            "immutable_snapshot_digest",
            "execution_issued_at",
            "execution_expires_at",
        )
        if any(
            getattr(manifest, field) != context[field] for field in expected_fields
        ):
            raise ControlledExecutionWriterV2Error(
                "bounded result does not bind plan/profile/closure/snapshot/Trader chain"
            )
        completed = _parsed_timestamp(
            manifest.completed_at, "bounded execution completed_at"
        ).astimezone(timezone.utc)
        if completed > _aware_utc(self._clock, "bounded result clock") + _MAX_CLOCK_SKEW:
            raise ControlledExecutionWriterV2Error(
                "bounded result completion is in the future"
            )
        expected_keys = {
            *(f"Paper:{ordinal}" for ordinal in range(1, 5)),
            *(f"Risk:{ordinal}" for ordinal in range(1, 5)),
            "Selection:0",
            "Knowledge:0",
        }
        if set(contents_raw) != expected_keys:
            raise ControlledExecutionWriterV2Error(
                "bounded executor must return exact four/four/one/one contents"
            )
        contents: dict[str, bytes] = {}
        for key, value in contents_raw.items():
            contents[key] = _require_bytes(value, f"bounded executor {key}")
        if len(set(contents.values())) != 10:
            raise ControlledExecutionWriterV2Error(
                "bounded executor artifact contents must be non-duplicated"
            )
        for paper, risk in zip(papers, risks, strict=True):
            paper_digest = _sha256_bytes(contents[f"Paper:{paper.ordinal}"])
            risk_digest = _sha256_bytes(contents[f"Risk:{risk.ordinal}"])
            if (
                paper.paper_result_id != paper_digest
                or paper.paper_artifact_digest != paper_digest
                or risk.risk_result_id != risk_digest
                or risk.risk_artifact_digest != risk_digest
            ):
                raise ControlledExecutionWriterV2Error(
                    "bounded Paper/Risk content digest does not match its evidence"
                )
        selection_digest = _sha256_bytes(contents["Selection:0"])
        knowledge_digest = _sha256_bytes(contents["Knowledge:0"])
        if (
            selection.selection_result_id != selection_digest
            or selection.selection_artifact_digest != selection_digest
            or knowledge.knowledge_artifact_id != knowledge_digest
            or knowledge.knowledge_artifact_digest != knowledge_digest
        ):
            raise ControlledExecutionWriterV2Error(
                "bounded Selection/Knowledge content digest does not match evidence"
            )
        return _VerifiedBoundedExecutionOutputV2(
            manifest,
            contents,
            _token=_VERIFIED_EXECUTOR_OUTPUT_TOKEN,
        )

    def _materialize_artifacts(
        self,
        *,
        handoff: Mapping[str, Any],
        output: _VerifiedBoundedExecutionOutputV2,
    ) -> tuple[tuple[dict[str, Any], bytes], ...]:
        if type(output) is not _VerifiedBoundedExecutionOutputV2:
            raise ControlledExecutionWriterV2Error(
                "internally reverified bounded execution output is required"
            )
        artifacts: list[tuple[dict[str, Any], bytes]] = []
        paper_ids: list[str] = []
        risk_ids: list[str] = []
        common = {
            "environment": self.environment,
            "handoff_id": handoff["handoff_id"],
            "approval_subject_id": handoff["approval_subject_id"],
        }
        for evidence in output.manifest.paper_results:
            content = output.contents[f"Paper:{evidence.ordinal}"]
            body = {
                "format": CONTROLLED_WRITER_ARTIFACT_FORMAT,
                "artifact_type": "Paper",
                "ordinal": evidence.ordinal,
                "plan_id": evidence.plan_id,
                "plan_binding_digest": evidence.plan_binding_digest,
                **common,
                "parent_artifact_ids": [handoff["handoff_id"]],
                "content_digest": self._content_digest(content),
                "result_evidence": evidence.to_dict(),
            }
            metadata = {**body, "artifact_id": canonical_authority_digest(body)}
            paper_ids.append(metadata["artifact_id"])
            artifacts.append((metadata, content))
        for evidence, paper_id in zip(
            output.manifest.risk_results, paper_ids, strict=True
        ):
            content = output.contents[f"Risk:{evidence.ordinal}"]
            body = {
                "format": CONTROLLED_WRITER_ARTIFACT_FORMAT,
                "artifact_type": "Risk",
                "ordinal": evidence.ordinal,
                "plan_id": evidence.plan_id,
                "plan_binding_digest": evidence.plan_binding_digest,
                **common,
                "parent_artifact_ids": [paper_id],
                "content_digest": self._content_digest(content),
                "result_evidence": evidence.to_dict(),
            }
            metadata = {**body, "artifact_id": canonical_authority_digest(body)}
            risk_ids.append(metadata["artifact_id"])
            artifacts.append((metadata, content))
        selection_body = {
            "format": CONTROLLED_WRITER_ARTIFACT_FORMAT,
            "artifact_type": "Selection",
            "ordinal": 0,
            "plan_id": "aggregate-exact-four",
            "plan_binding_digest": output.manifest.exact_four_binding_digest,
            **common,
            "parent_artifact_ids": [*paper_ids, *risk_ids],
            "content_digest": self._content_digest(output.contents["Selection:0"]),
            "result_evidence": output.manifest.aggregate_selection.to_dict(),
        }
        selection = {
            **selection_body,
            "artifact_id": canonical_authority_digest(selection_body),
        }
        artifacts.append((selection, output.contents["Selection:0"]))
        knowledge_body = {
            "format": CONTROLLED_WRITER_ARTIFACT_FORMAT,
            "artifact_type": "Knowledge",
            "ordinal": 0,
            "plan_id": "aggregate-exact-four",
            "plan_binding_digest": selection["plan_binding_digest"],
            **common,
            "parent_artifact_ids": [selection["artifact_id"]],
            "content_digest": self._content_digest(output.contents["Knowledge:0"]),
            "result_evidence": output.manifest.knowledge_artifact.to_dict(),
        }
        knowledge = {
            **knowledge_body,
            "artifact_id": canonical_authority_digest(knowledge_body),
        }
        artifacts.append((knowledge, output.contents["Knowledge:0"]))
        return tuple(artifacts)

    @staticmethod
    def _content_map(
        artifacts: tuple[tuple[dict[str, Any], bytes], ...]
    ) -> dict[str, bytes]:
        return {
            f"{metadata['artifact_type']}:{metadata['ordinal']}": content
            for metadata, content in artifacts
        }

    def _load_committed_result(
        self,
        connection: sqlite3.Connection,
        *,
        handoff_id: str,
    ) -> WrittenExactFourControlledArtifactsV2 | None:
        manifest_row = connection.execute(
            "SELECT canonical_manifest FROM controlled_manifests WHERE "
            "environment = ? AND handoff_id = ?",
            (self.environment, handoff_id),
        ).fetchone()
        rows = connection.execute(
            "SELECT artifact_type, ordinal, immutable_content FROM "
            "controlled_artifacts WHERE environment = ? AND handoff_id = ? "
            "ORDER BY CASE artifact_type WHEN 'Paper' THEN 1 WHEN 'Risk' THEN 2 "
            "WHEN 'Selection' THEN 3 ELSE 4 END, ordinal",
            (self.environment, handoff_id),
        ).fetchall()
        if manifest_row is None:
            return None
        if len(rows) != 10:
            raise ControlledExecutionWriterV2Error(
                "stored exact-four Controlled transaction is incomplete"
            )
        contents = {
            f"{row['artifact_type']}:{row['ordinal']}": bytes(
                row["immutable_content"]
            )
            for row in rows
        }
        return WrittenExactFourControlledArtifactsV2(
            bytes(manifest_row["canonical_manifest"]),
            contents,
            _token=_WRITTEN_BUNDLE_TOKEN,
        )

    def _reserve_handoff(
        self,
        *,
        peer_uid: int,
        authenticated_caller: str,
        authority_request_digest: str,
        handoff: Mapping[str, Any],
        canonical_handoff: bytes,
    ) -> WrittenExactFourControlledArtifactsV2 | None:
        if (
            authenticated_caller != "trader"
            or type(authority_request_digest) is not str
            or not authority_request_digest.startswith("sha256:")
        ):
            raise ControlledExecutionWriterV2Error(
                "Controlled handoff requires the authenticated Trader request"
            )
        handoff_digest = _sha256_bytes(canonical_handoff)
        trader_event_digest = handoff["_controlled_event_digest"]
        consume_body = {
            "format": "controlled-exact-four-handoff-consume/v2",
            "environment": self.environment,
            "handoff_id": handoff["handoff_id"],
            "handoff_digest": handoff_digest,
            "trader_event_digest": trader_event_digest,
            "authority_request_digest": authority_request_digest,
            "authenticated_trader_uid": peer_uid,
            "authenticated_trader_caller": authenticated_caller,
        }
        consume_digest = canonical_authority_digest(consume_body)
        consumed_at = _aware_utc(
            self._clock, "Controlled handoff reservation clock"
        ).isoformat()
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                "SELECT handoff_digest, trader_event_digest, "
                "consume_request_digest, authority_request_digest, "
                "authenticated_trader_uid, authenticated_trader_caller, "
                "canonical_handoff "
                "FROM controlled_handoffs WHERE environment = ? AND handoff_id = ?",
                (self.environment, handoff["handoff_id"]),
            ).fetchone()
            if existing is not None:
                if (
                    existing["handoff_digest"] != handoff_digest
                    or existing["trader_event_digest"] != trader_event_digest
                    or existing["consume_request_digest"] != consume_digest
                    or existing["authority_request_digest"]
                    != authority_request_digest
                    or existing["authenticated_trader_uid"] != peer_uid
                    or existing["authenticated_trader_caller"]
                    != authenticated_caller
                    or bytes(existing["canonical_handoff"]) != canonical_handoff
                ):
                    raise ControlledExecutionWriterV2Error(
                        "one-shot Trader handoff was already consumed by different bytes"
                    )
                stored = self._load_committed_result(
                    connection,
                    handoff_id=handoff["handoff_id"],
                )
                if stored is not None:
                    connection.execute("COMMIT")
                    return stored
                raise ControlledExecutionWriterV2Error(
                    "one-shot Trader handoff is consumed and retry policy is DENY"
                )
            trader_event = handoff["one_use_counter_event"]
            assertion = handoff["assertion_evidence"]
            challenge = handoff["challenge_evidence"]
            credential_evidence = handoff["credential_registry_evidence"]
            counter = connection.execute(
                "SELECT public_key_digest, registry_digest, counter_mode, sign_count "
                "FROM controlled_credential_counters WHERE environment = ? "
                "AND credential_id = ?",
                (self.environment, assertion["credential_id_base64url"]),
            ).fetchone()
            if (
                counter is None
                or counter["public_key_digest"]
                != credential_evidence["credential_public_key_digest"]
                or counter["registry_digest"]
                != credential_evidence["credential_registry_digest"]
                or counter["counter_mode"] != credential_evidence["counter_mode"]
                or int(counter["sign_count"]) != trader_event["prior_sign_count"]
            ):
                raise ControlledExecutionWriterV2Error(
                    "Controlled-owned credential counter does not match Trader prior state"
                )
            if counter["counter_mode"] == "COUNTING":
                advanced = connection.execute(
                    "UPDATE controlled_credential_counters SET sign_count = ? "
                    "WHERE environment = ? AND credential_id = ? AND sign_count = ?",
                    (
                        trader_event["result_sign_count"],
                        self.environment,
                        assertion["credential_id_base64url"],
                        trader_event["prior_sign_count"],
                    ),
                ).rowcount
                if advanced != 1:
                    raise ControlledExecutionWriterV2Error(
                        "Controlled-owned WebAuthn counter CAS failed"
                    )
            connection.execute(
                "INSERT INTO controlled_handoffs VALUES "
                "(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, "
                "'CONSUMED', ?)",
                (
                    self.environment,
                    handoff["handoff_id"],
                    handoff_digest,
                    trader_event_digest,
                    trader_event["sequence"],
                    assertion["assertion_digest"],
                    challenge["one_use_key"],
                    assertion["credential_id_base64url"],
                    trader_event["prior_sign_count"],
                    trader_event["result_sign_count"],
                    consume_digest,
                    authority_request_digest,
                    peer_uid,
                    authenticated_caller,
                    canonical_handoff,
                    consumed_at,
                ),
            )
            connection.execute("COMMIT")
            return None
        except ControlledExecutionWriterV2Error:
            connection.execute("ROLLBACK")
            raise
        except sqlite3.Error as exc:
            connection.execute("ROLLBACK")
            raise ControlledExecutionWriterV2Error(
                "atomic Controlled handoff reservation failed"
            ) from exc
        finally:
            connection.close()

    def _record_failed_attempt(self, handoff_id: str, error: BaseException) -> None:
        completed_at = _aware_utc(
            self._clock, "Controlled failed attempt clock"
        ).isoformat()
        error_class = type(error).__name__
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                "SELECT outcome FROM controlled_execution_attempts WHERE "
                "environment = ? AND handoff_id = ?",
                (self.environment, handoff_id),
            ).fetchone()
            if existing is None:
                connection.execute(
                    "INSERT INTO controlled_execution_attempts VALUES "
                    "(?, ?, 'FAILED', 'DENY', NULL, ?, ?)",
                    (self.environment, handoff_id, error_class, completed_at),
                )
            connection.execute("COMMIT")
        except sqlite3.Error as exc:
            connection.execute("ROLLBACK")
            raise ControlledExecutionWriterV2Error(
                "failed Controlled attempt could not be recorded fail closed"
            ) from exc
        finally:
            connection.close()

    def _commit_verified_handoff(
        self,
        *,
        handoff: dict[str, Any],
        canonical_handoff: bytes,
        output: _VerifiedBoundedExecutionOutputV2,
    ) -> WrittenExactFourControlledArtifactsV2:
        controlled_event_digest = handoff["_controlled_event_digest"]
        handoff_digest = _sha256_bytes(canonical_handoff)
        artifacts = self._materialize_artifacts(handoff=handoff, output=output)
        artifact_metadata = [metadata for metadata, _content in artifacts]
        artifact_set_digest = canonical_authority_digest(artifact_metadata)
        request_body = {
            "format": "controlled-exact-four-write-request/v2",
            "environment": self.environment,
            "handoff_id": handoff["handoff_id"],
            "handoff_digest": handoff_digest,
            "trader_event_digest": controlled_event_digest,
            "artifact_set_digest": artifact_set_digest,
        }
        write_request_digest = canonical_authority_digest(request_body)
        written_at = _aware_utc(self._clock, "Controlled commit clock").isoformat()
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            reservation = connection.execute(
                "SELECT canonical_handoff FROM controlled_handoffs WHERE "
                "environment = ? AND handoff_id = ? AND handoff_digest = ? "
                "AND trader_event_digest = ? AND status = 'CONSUMED'",
                (
                    self.environment,
                    handoff["handoff_id"],
                    handoff_digest,
                    controlled_event_digest,
                ),
            ).fetchone()
            attempt = connection.execute(
                "SELECT outcome FROM controlled_execution_attempts WHERE "
                "environment = ? AND handoff_id = ?",
                (self.environment, handoff["handoff_id"]),
            ).fetchone()
            if (
                reservation is None
                or bytes(reservation["canonical_handoff"]) != canonical_handoff
                or attempt is not None
            ):
                raise ControlledExecutionWriterV2Error(
                    "Controlled execution requires one uncompleted reserved handoff"
                )
            for metadata, content in artifacts:
                connection.execute(
                    "INSERT INTO controlled_artifacts VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        self.environment,
                        handoff["handoff_id"],
                        metadata["artifact_type"],
                        metadata["ordinal"],
                        metadata["artifact_id"],
                        metadata["content_digest"],
                        _canonical_bytes(metadata),
                        content,
                    ),
                )
            tail = connection.execute(
                "SELECT sequence, event_digest FROM controlled_writer_events "
                "WHERE environment = ? ORDER BY sequence DESC LIMIT 1",
                (self.environment,),
            ).fetchone()
            sequence = 1 if tail is None else int(tail["sequence"]) + 1
            prior_event_digest = None if tail is None else tail["event_digest"]
            event_body = {
                "format": CONTROLLED_WRITER_EVENT_FORMAT,
                "environment": self.environment,
                "authority_id": "controlled_execution",
                "issuer": CONTROLLED_WRITER_ISSUER,
                "sequence": sequence,
                "event_id": str(uuid.uuid4()),
                "prior_event_digest": prior_event_digest,
                "handoff_id": handoff["handoff_id"],
                "trader_event_digest": controlled_event_digest,
                "write_request_digest": write_request_digest,
                "artifact_set_digest": artifact_set_digest,
                "artifact_count": 10,
                "transaction_status": "COMMITTED",
                "observed_at": written_at,
                "automatic_promotion": False,
                "mass_research_enabled": False,
                "live_trading_enabled": False,
            }
            event = {
                **event_body,
                "event_digest": canonical_authority_digest(event_body),
            }
            connection.execute(
                "INSERT INTO controlled_writer_events VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    self.environment,
                    sequence,
                    event["event_id"],
                    event["event_digest"],
                    prior_event_digest,
                    handoff["handoff_id"],
                    write_request_digest,
                    _canonical_bytes(event),
                ),
            )
            manifest_body = {
                "format": CONTROLLED_WRITER_MANIFEST_FORMAT,
                "environment": self.environment,
                "issuer": CONTROLLED_WRITER_ISSUER,
                "writer_key_id": self._signer.key_id,
                "handoff_id": handoff["handoff_id"],
                "handoff_digest": handoff_digest,
                "approval_subject_id": handoff["approval_subject_id"],
                "ready_authority_response_digest": handoff[
                    "ready_authority_response_digest"
                ],
                "trader_event_digest": controlled_event_digest,
                "write_request_digest": write_request_digest,
                "artifact_set_digest": artifact_set_digest,
                "controlled_event_digest": event["event_digest"],
                "result_manifest": output.manifest.to_dict(),
                "artifacts": artifact_metadata,
                "written_at": written_at,
                "generation": 1,
                "one_shot": True,
                "automatic_promotion": False,
                "mass_research_enabled": False,
                "live_trading_enabled": False,
            }
            signed_body = {
                **manifest_body,
                "manifest_id": canonical_authority_digest(manifest_body),
            }
            manifest = {
                **signed_body,
                "signature": self._signer.sign(signed_body),
            }
            connection.execute(
                "INSERT INTO controlled_manifests VALUES (?, ?, ?, ?, ?, ?)",
                (
                    self.environment,
                    handoff["handoff_id"],
                    signed_body["manifest_id"],
                    write_request_digest,
                    event["event_digest"],
                    _canonical_bytes(manifest),
                ),
            )
            connection.execute(
                "INSERT INTO controlled_execution_attempts VALUES "
                "(?, ?, 'SUCCEEDED', 'DENY', ?, NULL, ?)",
                (
                    self.environment,
                    handoff["handoff_id"],
                    artifact_set_digest,
                    written_at,
                ),
            )
            connection.execute("COMMIT")
            return WrittenExactFourControlledArtifactsV2(
                _canonical_bytes(manifest),
                self._content_map(artifacts),
                _token=_WRITTEN_BUNDLE_TOKEN,
            )
        except ControlledExecutionWriterV2Error:
            connection.execute("ROLLBACK")
            raise
        except sqlite3.Error as exc:
            connection.execute("ROLLBACK")
            raise ControlledExecutionWriterV2Error(
                "atomic Controlled handoff/artifact/event transaction failed"
            ) from exc
        finally:
            connection.close()

    def _execute_authenticated_handoff(
        self,
        *,
        peer_uid: int,
        authenticated_caller: str,
        authority_request_digest: str,
        request_id: str,
        payload: Mapping[str, Any],
        handoff_bytes: bytes,
        bounded_executor: Callable[[Mapping[str, Any]], Mapping[str, Any]],
    ) -> WrittenExactFourControlledArtifactsV2:
        if (
            peer_uid != self._trader_uid
            or authenticated_caller != "trader"
            or type(payload) not in {dict, MappingProxyType}
            or set(payload) != {"handoff_id", "handoff_digest"}
            or request_id != payload.get("handoff_id")
            or payload.get("handoff_digest") != _sha256_bytes(handoff_bytes)
        ):
            raise ControlledExecutionWriterV2Error(
                "authenticated Trader request or handoff digest is invalid"
            )
        _require_digest(payload["handoff_id"], "Trader handoff_id")
        handoff = self._verify_handoff(
            handoff_bytes,
            expected_handoff_id=payload["handoff_id"],
        )
        stored = self._reserve_handoff(
            peer_uid=peer_uid,
            authenticated_caller=authenticated_caller,
            authority_request_digest=authority_request_digest,
            handoff=handoff,
            canonical_handoff=handoff_bytes,
        )
        if stored is not None:
            return stored
        context = self._execution_context(
            handoff,
            canonical_handoff=handoff_bytes,
        )
        one_call = _OneCallControlledPilotAuthorizationV2(context)
        try:
            raw_output = one_call.invoke(bounded_executor)
            output = self._verify_executor_output(raw_output, context=context)
            return self._commit_verified_handoff(
                handoff=handoff,
                canonical_handoff=handoff_bytes,
                output=output,
            )
        except BaseException as exc:
            self._record_failed_attempt(handoff["handoff_id"], exc)
            raise

    def consume_authority_server_handoff(
        self,
        context: AuthorityRequestContext,
        payload: Mapping[str, Any],
        fds: Sequence[int],
        bounded_executor: Callable[[Mapping[str, Any]], Mapping[str, Any]],
    ) -> WrittenExactFourControlledArtifactsV2:
        """Consume only a server-authenticated Trader request and one SCM FD."""

        self._require_positive_operation()
        if (
            type(context) is not AuthorityRequestContext
            or context.caller != "trader"
            or context.peer.uid != self._trader_uid
            or context.grant.caller != "trader"
            or context.grant.operation != CONTROLLED_TRADER_HANDOFF_OPERATION
            or context.grant.purpose != CONTROLLED_TRADER_HANDOFF_PURPOSE
            or context.grant.environment != self.environment
            or len(fds) != 1
        ):
            raise ControlledExecutionWriterV2Error(
                "Controlled handoff lacks the exact server-authenticated Trader context"
            )
        exact_payload = dict(payload)
        reconstructed_request = {
            "format": "local-authority-request/v1",
            "request_id": context.request_id,
            "operation": context.grant.operation,
            "purpose": context.grant.purpose,
            "payload": exact_payload,
        }
        if canonical_authority_digest(reconstructed_request) != context.request_digest:
            raise ControlledExecutionWriterV2Error(
                "Controlled server request context digest is inconsistent"
            )
        handoff_bytes = _read_unlinked_readonly_descriptor(
            fds[0],
            expected_uid=context.peer.uid,
        )
        return self._execute_authenticated_handoff(
            peer_uid=context.peer.uid,
            authenticated_caller=context.caller,
            authority_request_digest=context.request_digest,
            request_id=context.request_id,
            payload=exact_payload,
            handoff_bytes=handoff_bytes,
            bounded_executor=bounded_executor,
        )

    def receive_and_execute(
        self,
        channel: socket.socket,
        bounded_executor: Callable[[Mapping[str, Any]], Mapping[str, Any]],
    ) -> WrittenExactFourControlledArtifactsV2:
        """Compatibility transport used by tests; live launch requires the server."""

        self._require_positive_operation()
        peer_uid = _unix_peer_uid(channel)
        if peer_uid != self._trader_uid:
            raise ControlledExecutionWriterV2Error(
                "Trader AF_UNIX peer UID mismatch"
            )
        request_raw, descriptor = _recv_framed_request_with_one_fd(channel)
        try:
            handoff_bytes = _read_unlinked_readonly_descriptor(
                descriptor,
                expected_uid=peer_uid,
            )
        finally:
            os.close(descriptor)
        request = _strict_json_loads(
            request_raw,
            label="Trader local-authority handoff request",
        )
        payload = request.get("payload") if type(request) is dict else None
        if (
            set(request) != set(_REQUEST_FIELDS)
            or request.get("format") != "local-authority-request/v1"
            or request.get("operation") != CONTROLLED_TRADER_HANDOFF_OPERATION
            or request.get("purpose") != CONTROLLED_TRADER_HANDOFF_PURPOSE
            or type(payload) is not dict
        ):
            raise ControlledExecutionWriterV2Error(
                "Trader local-authority request fields are invalid"
            )
        return self._execute_authenticated_handoff(
            peer_uid=peer_uid,
            authenticated_caller="trader",
            authority_request_digest=canonical_authority_digest(request),
            request_id=request["request_id"],
            payload=payload,
            handoff_bytes=handoff_bytes,
            bounded_executor=bounded_executor,
        )

    def artifact_count(self) -> int:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT COUNT(*) AS count FROM controlled_artifacts "
                "WHERE environment = ?",
                (self.environment,),
            ).fetchone()
            assert row is not None
            return int(row["count"])

    def event_count(self) -> int:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT COUNT(*) AS count FROM controlled_writer_events "
                "WHERE environment = ?",
                (self.environment,),
            ).fetchone()
            assert row is not None
            return int(row["count"])

    def handoff_count(self) -> int:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT COUNT(*) AS count FROM controlled_handoffs "
                "WHERE environment = ?",
                (self.environment,),
            ).fetchone()
            assert row is not None
            return int(row["count"])

    def attempt_outcome(self, handoff_id: str) -> str | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT outcome FROM controlled_execution_attempts WHERE "
                "environment = ? AND handoff_id = ?",
                (self.environment, handoff_id),
            ).fetchone()
            return None if row is None else str(row["outcome"])

    def credential_sign_count(self, credential_id: str) -> int | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT sign_count FROM controlled_credential_counters WHERE "
                "environment = ? AND credential_id = ?",
                (self.environment, credential_id),
            ).fetchone()
            return None if row is None else int(row["sign_count"])


def _create_test_controlled_execution_writer_v2(
    *,
    store_path: Path,
    private_key: Ed25519PrivateKey,
    clock: Callable[[], datetime],
    relying_parties: ExactFourTraderRelyingPartyRegistryV2,
    credentials: ExactFourTraderCredentialRegistryV2,
    trader_uid: int | None = None,
    key_id: str = "test-controlled-writer.invalid/v2",
    server_bound: bool = True,
) -> SQLiteControlledExecutionWriterV2:
    """Construct a test-environment writer with an ephemeral Controlled key."""

    if ".invalid" not in key_id:
        raise ControlledExecutionWriterV2Error(
            "test Controlled writer key id must use .invalid"
        )
    rp = relying_parties.require("test")
    if not rp.rp_id.endswith(".invalid"):
        raise ControlledExecutionWriterV2Error(
            "test Controlled writer RP must use the reserved .invalid suffix"
        )
    signer = _ControlledWriterSignerV2(key_id=key_id, private_key=private_key)
    return SQLiteControlledExecutionWriterV2(
        store_path,
        environment="test",
        signer=signer,
        clock=clock,
        trader_uid=os.geteuid() if trader_uid is None else trader_uid,
        relying_parties=relying_parties,
        credentials=credentials,
        server_bound=server_bound,
        _token=_WRITER_CONSTRUCTION_TOKEN,
    )


def _load_root_owned_activation() -> dict[str, Any]:
    path = CONTROLLED_EXECUTION_ACTIVATION_PATH
    try:
        metadata = path.lstat()
        raw = path.read_bytes()
    except OSError as exc:
        raise ExactFourAuthorityPending(CONTROLLED_WRITER_LIVE_STATE) from exc
    if (
        not stat.S_ISREG(metadata.st_mode)
        or metadata.st_uid != 0
        or metadata.st_mode & 0o022
    ):
        raise ExactFourAuthorityPending(
            "Controlled activation state is not a root-owned non-writable file"
        )
    document = _strict_json_loads(raw, label="Controlled authority activation state")
    required = {
        "format",
        "environment",
        "service_uid",
        "trader_uid",
        "store_path",
        "signer_key_id",
        "private_key_path",
        "protected_store_observed",
        "protected_signing_key_observed",
        "rp_registry",
        "credential_registry",
    }
    if set(document) != required or document.get("format") != (
        "exact-four-controlled-execution-activation/v2"
    ):
        raise ExactFourAuthorityPending(
            "Controlled activation state fields or format are invalid"
        )
    return document


def _activation_registries(
    document: dict[str, Any],
) -> tuple[
    ExactFourTraderRelyingPartyRegistryV2,
    ExactFourTraderCredentialRegistryV2,
]:
    rp_document = document["rp_registry"]
    if (
        type(rp_document) is not dict
        or set(rp_document) != {"generation", "entries"}
        or type(rp_document["entries"]) is not list
    ):
        raise ExactFourAuthorityPending("Controlled RP activation registry is invalid")
    rp_rows: list[ExactFourTraderRelyingPartyV2] = []
    rp_fields = {
        "environment",
        "policy_id",
        "policy_generation",
        "rp_id",
        "origin",
        "effective_at",
        "status",
        "user_presence_required",
        "user_verification_required",
    }
    for row in rp_document["entries"]:
        if type(row) is not dict or set(row) != rp_fields:
            raise ExactFourAuthorityPending("Controlled RP activation row is not closed")
        rp_rows.append(ExactFourTraderRelyingPartyV2(**row))
    rps = ExactFourTraderRelyingPartyRegistryV2(
        tuple(rp_rows), generation=rp_document["generation"]
    )

    credential_document = document["credential_registry"]
    if (
        type(credential_document) is not dict
        or set(credential_document) != {"registry_id", "generation", "credentials"}
        or type(credential_document["credentials"]) is not list
    ):
        raise ExactFourAuthorityPending(
            "Controlled credential activation registry is invalid"
        )
    credential_fields = {
        "environment",
        "credential_id_base64url",
        "public_key_spki_der_base64",
        "rp_policy_digest",
        "effective_at",
        "initial_sign_count",
        "counter_mode",
        "status",
        "algorithm",
        "key_backend",
    }
    credentials: list[ExactFourTraderCredentialV2] = []
    for row in credential_document["credentials"]:
        if type(row) is not dict or set(row) != credential_fields:
            raise ExactFourAuthorityPending(
                "Controlled credential activation row is not closed"
            )
        try:
            credential_id = _decode_canonical_base64url(
                row["credential_id_base64url"],
                label="Controlled activation credential id",
                minimum_bytes=16,
                maximum_bytes=1024,
            )
            key_text = row["public_key_spki_der_base64"]
            key_bytes = base64.b64decode(key_text, validate=True)
            if base64.b64encode(key_bytes).decode("ascii") != key_text:
                raise ValueError("non-canonical public key base64")
            public_key = serialization.load_der_public_key(key_bytes)
        except (TypeError, ValueError) as exc:
            raise ExactFourAuthorityPending(
                "Controlled activation credential public material is invalid"
            ) from exc
        credentials.append(
            ExactFourTraderCredentialV2(
                environment=row["environment"],
                credential_id=credential_id,
                public_key=public_key,  # type: ignore[arg-type]
                rp_policy_digest=row["rp_policy_digest"],
                effective_at=row["effective_at"],
                initial_sign_count=row["initial_sign_count"],
                counter_mode=row["counter_mode"],
                status=row["status"],
                algorithm=row["algorithm"],
                key_backend=row["key_backend"],
            )
        )
    registry = ExactFourTraderCredentialRegistryV2(
        tuple(credentials),
        generation=credential_document["generation"],
        registry_id=credential_document["registry_id"],
    )
    return rps, registry


def _load_live_controlled_execution_writer_v2(
    *, server_bound: bool
) -> SQLiteControlledExecutionWriterV2:
    """Load fixed activation for observation or the AuthorityServer entrypoint."""

    document = _load_root_owned_activation()
    environment = document["environment"]
    service_uid = document["service_uid"]
    trader_uid = document["trader_uid"]
    if (
        environment not in {"staging", "production"}
        or type(service_uid) is not int
        or service_uid <= 0
        or type(trader_uid) is not int
        or trader_uid <= 0
        or trader_uid == service_uid
        or os.geteuid() != service_uid
        or document["protected_store_observed"] is not True
        or document["protected_signing_key_observed"] is not True
    ):
        raise ExactFourAuthorityPending(
            "Controlled principal, protected store, key, or Trader peer is absent"
        )
    store_path = Path(document["store_path"])
    key_path = Path(document["private_key_path"])
    if (
        not store_path.is_absolute()
        or not key_path.is_absolute()
        or not store_path.parent.exists()
    ):
        raise ExactFourAuthorityPending(
            "Controlled protected paths are absent or not absolute"
        )
    parent = store_path.parent.lstat()
    if (
        not stat.S_ISDIR(parent.st_mode)
        or parent.st_uid != service_uid
        or parent.st_mode & 0o077
    ):
        raise ExactFourAuthorityPending(
            "Controlled store directory is not service-owned mode 0700"
        )
    if store_path.exists():
        stored = store_path.lstat()
        if (
            not stat.S_ISREG(stored.st_mode)
            or stored.st_uid != service_uid
            or stored.st_mode & 0o077
        ):
            raise ExactFourAuthorityPending(
                "Controlled store is not service-owned and private"
            )
    try:
        key_metadata = key_path.lstat()
        key_bytes = key_path.read_bytes()
    except OSError as exc:
        raise ExactFourAuthorityPending(
            "Controlled protected signing key is absent"
        ) from exc
    if (
        not stat.S_ISREG(key_metadata.st_mode)
        or key_metadata.st_uid != service_uid
        or stat.S_IMODE(key_metadata.st_mode) not in {0o400, 0o600}
    ):
        raise ExactFourAuthorityPending(
            "Controlled signing key ownership or mode is invalid"
        )
    try:
        private_key = serialization.load_pem_private_key(key_bytes, password=None)
    except (TypeError, ValueError) as exc:
        raise ExactFourAuthorityPending(
            "Controlled protected signing key cannot be decoded"
        ) from exc
    if not isinstance(private_key, Ed25519PrivateKey):
        raise ExactFourAuthorityPending(
            "Controlled protected signing key is not Ed25519"
        )
    key_id = document["signer_key_id"]
    if type(key_id) is not str or not key_id or key_id != key_id.strip():
        raise ExactFourAuthorityPending("Controlled signer key id is invalid")
    rps, credentials = _activation_registries(document)
    return SQLiteControlledExecutionWriterV2(
        store_path,
        environment=environment,
        signer=_ControlledWriterSignerV2(key_id=key_id, private_key=private_key),
        clock=lambda: datetime.now(timezone.utc),
        trader_uid=trader_uid,
        relying_parties=rps,
        credentials=credentials,
        server_bound=server_bound,
        _token=_WRITER_CONSTRUCTION_TOKEN,
    )


def open_live_controlled_execution_writer_v2() -> SQLiteControlledExecutionWriterV2:
    """Observe activated state; the returned object cannot launch positive ops."""

    return _load_live_controlled_execution_writer_v2(server_bound=False)


def _open_server_bound_controlled_execution_writer_v2(
) -> SQLiteControlledExecutionWriterV2:
    """Execution adapter hook used only inside UnixAuthorityService."""

    return _load_live_controlled_execution_writer_v2(server_bound=True)


__all__ = [
    "CONTROLLED_EXECUTION_ACTIVATION_PATH",
    "CONTROLLED_TRADER_HANDOFF_OPERATION",
    "CONTROLLED_TRADER_HANDOFF_PURPOSE",
    "CONTROLLED_WRITER_ARTIFACT_TYPES",
    "CONTROLLED_WRITER_LIVE_STATE",
    "ControlledExecutionWriterV2Error",
    "SQLiteControlledExecutionWriterV2",
    "WrittenExactFourControlledArtifactsV2",
    "open_live_controlled_execution_writer_v2",
]
