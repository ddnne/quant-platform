"""Fail-closed lifecycle boundary for a Controlled store canary transition.

The production daemon and the (future) bounded canary transition use the same
advisory lifecycle lock.  A durable marker blocks daemon restart after any
partial transition.  The public staged-canary command remains HOLD-only; this
module does not mint canary evidence or authorize research execution.
"""

from __future__ import annotations

import fcntl
import os
import sqlite3
import stat
import threading
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from execution.exact_four_codec import ExactFourAuthorityPending, _canonical_bytes


CONTROLLED_QUIESCENCE_MARKER_FORMAT = (
    "exact-four-controlled-writer-resume-forbidden/v1"
)
CONTROLLED_QUIESCENCE_STATE = "SOURCE_READY_NOT_OPERATIONALLY_ACCEPTED"
_SQLITE_HEADER = b"SQLite format 3\x00"
_DELETE_HEADER_VERSIONS = b"\x01\x01"
_WAL_HEADER_VERSIONS = b"\x02\x02"
_LOCK_SUFFIX = ".lifecycle.lock"
_MARKER_SUFFIX = ".quiescence.json"
_SESSION_TOKEN = object()
_os_write = os.write


class ControlledExecutionQuiescenceV2Error(ExactFourAuthorityPending):
    """The writer cannot be stopped, transitioned, or safely resumed."""


@dataclass(frozen=True, slots=True)
class _ControlledStoreIdentityV2:
    environment: str
    service_uid: int
    store_path: Path


class ControlledWriterLifecycleLeaseV2:
    """One pinned, process-held lifecycle lock for daemon or transition use."""

    __slots__ = (
        "_closed",
        "_creator_pid",
        "_descriptor",
        "_descriptor_guard",
        "_identity",
        "_lock_identity",
        "_lock_path",
        "_ofd_cookie",
        "_require_marker_absent",
        "_validation_lock",
    )

    def __init__(
        self,
        *,
        identity: _ControlledStoreIdentityV2,
        descriptor: int,
        lock_path: Path,
        lock_identity: tuple[int, int],
        require_marker_absent: bool,
        _token: object,
    ) -> None:
        if _token is not _SESSION_TOKEN:
            raise ControlledExecutionQuiescenceV2Error(
                "Controlled lifecycle lease construction is private"
            )
        self._identity = identity
        self._creator_pid = os.getpid()
        self._descriptor = descriptor
        try:
            self._descriptor_guard = os.dup(descriptor)
            # A duplicated descriptor proves that the two numbers initially
            # name one OFD, but equality alone is insufficient: if both
            # numbers are later closed and reused by a fresh open+dup pair,
            # they would again share an OFD and could silently reacquire the
            # flock.  Keep an unpredictable, OFD-scoped seek position as a
            # continuity cookie.  A fresh open starts at offset zero.
            self._ofd_cookie = 3 + int.from_bytes(os.urandom(8), "big") % (
                (1 << 62) - 4
            )
            os.lseek(self._descriptor, self._ofd_cookie, os.SEEK_SET)
            if (
                os.lseek(self._descriptor_guard, 0, os.SEEK_CUR)
                != self._ofd_cookie
            ):
                raise OSError("Controlled lifecycle descriptors do not share an OFD")
        except OSError as exc:
            guard = getattr(self, "_descriptor_guard", -1)
            if guard >= 0:
                os.close(guard)
            raise ControlledExecutionQuiescenceV2Error(
                "Controlled lifecycle descriptor cannot be guarded"
            ) from exc
        self._lock_path = lock_path
        self._lock_identity = lock_identity
        self._require_marker_absent = require_marker_absent
        self._validation_lock = threading.Lock()
        self._closed = False

    @property
    def environment(self) -> str:
        return self._identity.environment

    @property
    def service_uid(self) -> int:
        return self._identity.service_uid

    @property
    def store_path(self) -> Path:
        return self._identity.store_path

    def _require_held(self) -> None:
        if os.getpid() != self._creator_pid:
            raise ControlledExecutionQuiescenceV2Error(
                "Controlled lifecycle lease cannot cross a process boundary"
            )
        with self._validation_lock:
            if self._closed:
                raise ControlledExecutionQuiescenceV2Error(
                    "Controlled lifecycle lease is already closed"
                )
            for descriptor in (self._descriptor, self._descriptor_guard):
                _require_pinned_regular_file(
                    self._lock_path,
                    descriptor=descriptor,
                    expected_uid=self.service_uid,
                    expected_identity=self._lock_identity,
                    label="Controlled lifecycle lock",
                )
            if not self._descriptors_share_open_file_description():
                raise ControlledExecutionQuiescenceV2Error(
                    "Controlled lifecycle descriptor was closed or replaced"
                )
            try:
                fcntl.flock(
                    self._descriptor,
                    fcntl.LOCK_EX | fcntl.LOCK_NB,
                )
            except OSError as exc:
                raise ControlledExecutionQuiescenceV2Error(
                    "Controlled lifecycle descriptor does not own the lock"
                ) from exc
            if self._require_marker_absent:
                _lock_path, marker_path = _transition_paths(self.store_path)
                if os.path.lexists(marker_path):
                    raise ControlledExecutionQuiescenceV2Error(
                        "Controlled writer resume is forbidden by an unfinished "
                        "transition"
                    )

    def _descriptors_share_open_file_description(self) -> bool:
        """Use the shared seek offset to reject closed-and-reused fd numbers."""

        descriptor_offset: int | None = None
        guard_offset: int | None = None
        try:
            descriptor_offset = os.lseek(self._descriptor, 0, os.SEEK_CUR)
            guard_offset = os.lseek(self._descriptor_guard, 0, os.SEEK_CUR)
            if (
                descriptor_offset != self._ofd_cookie
                or guard_offset != self._ofd_cookie
            ):
                return False
            probe_offset = self._ofd_cookie + 1
            os.lseek(self._descriptor, probe_offset, os.SEEK_SET)
            return (
                os.lseek(self._descriptor_guard, 0, os.SEEK_CUR)
                == probe_offset
            )
        except OSError:
            return False
        finally:
            if descriptor_offset is not None:
                try:
                    os.lseek(self._descriptor, descriptor_offset, os.SEEK_SET)
                except OSError:
                    pass
            if guard_offset is not None:
                try:
                    os.lseek(self._descriptor_guard, guard_offset, os.SEEK_SET)
                except OSError:
                    pass

    def close(self) -> None:
        if self._closed:
            return
        if os.getpid() != self._creator_pid:
            # A forked child inherited the same open-file description.  An
            # explicit LOCK_UN here would release the creator's live lock.
            try:
                os.close(self._descriptor)
            finally:
                try:
                    os.close(self._descriptor_guard)
                finally:
                    self._closed = True
            return
        with self._validation_lock:
            if self._closed:
                return
            first_error: OSError | None = None
            try:
                if self._descriptors_share_open_file_description():
                    fcntl.flock(self._descriptor, fcntl.LOCK_UN)
            except OSError as exc:
                first_error = exc
            finally:
                for descriptor in (self._descriptor, self._descriptor_guard):
                    try:
                        os.close(descriptor)
                    except OSError as exc:
                        if first_error is None:
                            first_error = exc
                self._closed = True
            if first_error is not None:
                raise first_error

    def __enter__(self) -> ControlledWriterLifecycleLeaseV2:
        self._require_held()
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()


class ControlledCanaryStoreTransitionSessionV2:
    """Pinned DELETE-mode session; release alone never resumes the writer."""

    __slots__ = (
        "_closed",
        "_db_descriptor",
        "_identity",
        "_lease",
        "_marker_bytes",
        "_marker_descriptor",
        "_marker_identity",
        "_marker_path",
        "_parent_descriptor",
        "_parent_identity",
        "_session_id",
        "_store_identity",
    )

    def __init__(
        self,
        *,
        identity: _ControlledStoreIdentityV2,
        lease: ControlledWriterLifecycleLeaseV2,
        db_descriptor: int,
        parent_descriptor: int,
        parent_identity: tuple[int, int],
        store_identity: tuple[int, int],
        marker_path: Path,
        marker_descriptor: int,
        marker_identity: tuple[int, int],
        marker_bytes: bytes,
        session_id: str,
        _token: object,
    ) -> None:
        if _token is not _SESSION_TOKEN:
            raise ControlledExecutionQuiescenceV2Error(
                "Controlled transition session construction is private"
            )
        self._identity = identity
        self._lease = lease
        self._db_descriptor = db_descriptor
        self._parent_descriptor = parent_descriptor
        self._parent_identity = parent_identity
        self._store_identity = store_identity
        self._marker_path = marker_path
        self._marker_descriptor = marker_descriptor
        self._marker_identity = marker_identity
        self._marker_bytes = marker_bytes
        self._session_id = session_id
        self._closed = False

    @property
    def environment(self) -> str:
        return self._identity.environment

    @property
    def store_path(self) -> Path:
        return self._identity.store_path

    @property
    def store_identity(self) -> tuple[int, int]:
        return self._store_identity

    @property
    def session_id(self) -> str:
        return self._session_id

    def _require_active(self, *, expected_header: bytes) -> None:
        if self._closed:
            raise ControlledExecutionQuiescenceV2Error(
                "Controlled transition session is already closed"
            )
        self._lease._require_held()
        _require_pinned_directory(
            self.store_path.parent,
            descriptor=self._parent_descriptor,
            expected_uid=self._identity.service_uid,
            expected_identity=self._parent_identity,
            label="Controlled store directory",
        )
        _require_pinned_regular_file(
            self.store_path,
            descriptor=self._db_descriptor,
            expected_uid=self._identity.service_uid,
            expected_identity=self._store_identity,
            label="Controlled store",
        )
        _require_pinned_regular_file(
            self._marker_path,
            descriptor=self._marker_descriptor,
            expected_uid=self._identity.service_uid,
            expected_identity=self._marker_identity,
            label="Controlled quiescence marker",
        )
        try:
            marker_stat = os.fstat(self._marker_descriptor)
            marker_contents = os.pread(
                self._marker_descriptor, len(self._marker_bytes), 0
            )
        except OSError as exc:
            raise ControlledExecutionQuiescenceV2Error(
                "Controlled quiescence marker cannot be reread"
            ) from exc
        if (
            marker_stat.st_size != len(self._marker_bytes)
            or marker_contents != self._marker_bytes
        ):
            raise ControlledExecutionQuiescenceV2Error(
                "Controlled quiescence marker changed during the session"
            )
        _require_sqlite_header(
            self._db_descriptor,
            expected_versions=expected_header,
            label="Controlled store",
        )
        _require_no_sidecars(self.store_path)

    def restore_wal_after_bounded_canary(self) -> None:
        """Fail closed until an external-anchor completion verifier is wired.

        A same-UID Python object or caller-supplied digest is not a completion
        capability.  The public canary workflow therefore cannot restore WAL
        or remove the durable restart marker in this source revision.
        """

        self._require_active(expected_header=_DELETE_HEADER_VERSIONS)
        raise ControlledExecutionQuiescenceV2Error(
            "Controlled WAL restore is unavailable until an externally anchored "
            "completion verifier is wired"
        )

    def close(self) -> None:
        """Release descriptors; an unrestored marker deliberately remains."""

        if self._closed:
            return
        first_error: OSError | None = None
        try:
            for descriptor in (
                self._marker_descriptor,
                self._db_descriptor,
                self._parent_descriptor,
            ):
                try:
                    os.close(descriptor)
                except OSError as exc:
                    if first_error is None:
                        first_error = exc
        finally:
            try:
                self._lease.close()
            finally:
                self._closed = True
        if first_error is not None:
            raise ControlledExecutionQuiescenceV2Error(
                "Controlled transition descriptors did not all close cleanly"
            ) from first_error

    def __enter__(self) -> ControlledCanaryStoreTransitionSessionV2:
        self._require_active(expected_header=_DELETE_HEADER_VERSIONS)
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()


def _transition_paths(store_path: Path) -> tuple[Path, Path]:
    return (
        store_path.with_name(f".{store_path.name}{_LOCK_SUFFIX}"),
        store_path.with_name(f".{store_path.name}{_MARKER_SUFFIX}"),
    )


def _open_parent(path: Path, *, expected_uid: int) -> int:
    flags = (
        os.O_RDONLY
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    descriptor = -1
    try:
        descriptor = os.open(path, flags)
        observed = os.fstat(descriptor)
        lexical = path.lstat()
    except OSError as exc:
        if descriptor >= 0:
            os.close(descriptor)
        raise ControlledExecutionQuiescenceV2Error(
            "Controlled store directory cannot be pinned"
        ) from exc
    if (
        not stat.S_ISDIR(observed.st_mode)
        or observed.st_uid != expected_uid
        or stat.S_IMODE(observed.st_mode) != 0o700
        or (observed.st_dev, observed.st_ino) != (lexical.st_dev, lexical.st_ino)
    ):
        os.close(descriptor)
        raise ControlledExecutionQuiescenceV2Error(
            "Controlled store directory is not service-owned mode 0700"
        )
    return descriptor


def _open_or_create_private_file(path: Path, *, expected_uid: int) -> int:
    common = (
        os.O_RDWR
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_NONBLOCK", 0)
    )
    descriptor = -1
    created = False
    try:
        try:
            descriptor = os.open(path, common | os.O_CREAT | os.O_EXCL, 0o600)
            created = True
        except FileExistsError:
            descriptor = os.open(path, common)
        if created:
            os.fchmod(descriptor, 0o600)
            os.fsync(descriptor)
        observed = os.fstat(descriptor)
        lexical = path.lstat()
    except OSError as exc:
        if descriptor >= 0:
            os.close(descriptor)
        raise ControlledExecutionQuiescenceV2Error(
            "Controlled lifecycle lock cannot be opened safely"
        ) from exc
    if (
        not stat.S_ISREG(observed.st_mode)
        or observed.st_uid != expected_uid
        or stat.S_IMODE(observed.st_mode) != 0o600
        or observed.st_nlink != 1
        or (observed.st_dev, observed.st_ino) != (lexical.st_dev, lexical.st_ino)
    ):
        os.close(descriptor)
        raise ControlledExecutionQuiescenceV2Error(
            "Controlled lifecycle lock is not a private single-link file"
        )
    return descriptor


def _require_pinned_regular_file(
    path: Path,
    *,
    descriptor: int,
    expected_uid: int,
    expected_identity: tuple[int, int],
    label: str,
) -> None:
    try:
        pinned = os.fstat(descriptor)
        lexical = path.lstat()
    except OSError as exc:
        raise ControlledExecutionQuiescenceV2Error(
            f"{label} identity cannot be revalidated"
        ) from exc
    if (
        not stat.S_ISREG(pinned.st_mode)
        or pinned.st_uid != expected_uid
        or stat.S_IMODE(pinned.st_mode) != 0o600
        or pinned.st_nlink != 1
        or (pinned.st_dev, pinned.st_ino) != expected_identity
        or (lexical.st_dev, lexical.st_ino) != expected_identity
        or lexical.st_uid != expected_uid
        or stat.S_IMODE(lexical.st_mode) != 0o600
        or lexical.st_nlink != 1
    ):
        raise ControlledExecutionQuiescenceV2Error(
            f"{label} changed or is not a private single-link file"
        )


def _require_pinned_directory(
    path: Path,
    *,
    descriptor: int,
    expected_uid: int,
    expected_identity: tuple[int, int],
    label: str,
) -> None:
    try:
        pinned = os.fstat(descriptor)
        lexical = path.lstat()
    except OSError as exc:
        raise ControlledExecutionQuiescenceV2Error(
            f"{label} identity cannot be revalidated"
        ) from exc
    if (
        not stat.S_ISDIR(pinned.st_mode)
        or pinned.st_uid != expected_uid
        or stat.S_IMODE(pinned.st_mode) != 0o700
        or (pinned.st_dev, pinned.st_ino) != expected_identity
        or (lexical.st_dev, lexical.st_ino) != expected_identity
        or not stat.S_ISDIR(lexical.st_mode)
        or lexical.st_uid != expected_uid
        or stat.S_IMODE(lexical.st_mode) != 0o700
    ):
        raise ControlledExecutionQuiescenceV2Error(
            f"{label} changed or is not service-owned mode 0700"
        )


def _require_path_matches_descriptor(
    path: Path,
    descriptor: int,
    *,
    expected_uid: int,
    expected_identity: tuple[int, int],
) -> None:
    _require_pinned_regular_file(
        path,
        descriptor=descriptor,
        expected_uid=expected_uid,
        expected_identity=expected_identity,
        label="Controlled store",
    )


def _require_sqlite_header(
    descriptor: int, *, expected_versions: bytes, label: str
) -> None:
    try:
        header = os.pread(descriptor, 100, 0)
    except OSError as exc:
        raise ControlledExecutionQuiescenceV2Error(
            f"{label} header cannot be read"
        ) from exc
    if (
        len(header) < 20
        or header[:16] != _SQLITE_HEADER
        or header[18:20] != expected_versions
    ):
        raise ControlledExecutionQuiescenceV2Error(
            f"{label} journal header is not the required mode"
        )


def _require_no_sidecars(store_path: Path) -> None:
    if any(
        os.path.lexists(f"{store_path}{suffix}")
        for suffix in ("-wal", "-shm", "-journal")
    ):
        raise ControlledExecutionQuiescenceV2Error(
            "Controlled store retained a SQLite sidecar"
        )


def _validate_existing_sidecars(store_path: Path, *, expected_uid: int) -> None:
    for suffix in ("-wal", "-shm"):
        path = Path(f"{store_path}{suffix}")
        if not os.path.lexists(path):
            continue
        try:
            observed = path.lstat()
        except OSError as exc:
            raise ControlledExecutionQuiescenceV2Error(
                "Controlled WAL sidecar identity cannot be inspected"
            ) from exc
        if (
            not stat.S_ISREG(observed.st_mode)
            or observed.st_uid != expected_uid
            or stat.S_IMODE(observed.st_mode) != 0o600
            or observed.st_nlink != 1
        ):
            raise ControlledExecutionQuiescenceV2Error(
                "Controlled WAL sidecar is unsafe"
            )
    if os.path.lexists(f"{store_path}-journal"):
        raise ControlledExecutionQuiescenceV2Error(
            "Controlled store has an unexpected rollback journal"
        )


def _open_exclusive_connection(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(str(path), isolation_level=None, timeout=10.0)
    try:
        connection.execute("PRAGMA busy_timeout=10000")
        connection.execute("PRAGMA trusted_schema=OFF")
        result = connection.execute("PRAGMA locking_mode=EXCLUSIVE").fetchone()
        if result is None or str(result[0]).lower() != "exclusive":
            raise ControlledExecutionQuiescenceV2Error(
                "Controlled store did not enter exclusive locking mode"
            )
        connection.execute("BEGIN EXCLUSIVE")
        connection.execute("COMMIT")
    except BaseException:
        connection.close()
        raise
    return connection


def _acquire_lifecycle_lock(
    identity: _ControlledStoreIdentityV2,
    *,
    require_marker_absent: bool,
    monitor_marker_absent: bool | None = None,
) -> ControlledWriterLifecycleLeaseV2:
    lock_path, marker_path = _transition_paths(identity.store_path)
    parent_descriptor = _open_parent(
        identity.store_path.parent, expected_uid=identity.service_uid
    )
    descriptor = -1
    lease: ControlledWriterLifecycleLeaseV2 | None = None
    try:
        descriptor = _open_or_create_private_file(
            lock_path, expected_uid=identity.service_uid
        )
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            os.close(descriptor)
            descriptor = -1
            raise ControlledExecutionQuiescenceV2Error(
                "Controlled writer lifecycle is already held"
            ) from exc
        observed = os.fstat(descriptor)
        lease = ControlledWriterLifecycleLeaseV2(
            identity=identity,
            descriptor=descriptor,
            lock_path=lock_path,
            lock_identity=(observed.st_dev, observed.st_ino),
            require_marker_absent=(
                require_marker_absent
                if monitor_marker_absent is None
                else monitor_marker_absent
            ),
            _token=_SESSION_TOKEN,
        )
        lease._require_held()
        if require_marker_absent and os.path.lexists(marker_path):
            lease.close()
            raise ControlledExecutionQuiescenceV2Error(
                "Controlled writer resume is forbidden by an unfinished transition"
            )
        os.fsync(parent_descriptor)
        return lease
    except BaseException:
        if lease is not None:
            lease.close()
        elif descriptor >= 0:
            os.close(descriptor)
        raise
    finally:
        os.close(parent_descriptor)


def _live_identity_from_activation() -> _ControlledStoreIdentityV2:
    from execution.controlled_execution_activation_v2 import (
        _activation_absolute_path,
        _load_root_owned_activation,
        _require_live_controlled_store_identity_v2,
    )

    document = _load_root_owned_activation()
    environment = document.get("environment")
    service_uid = document.get("service_uid")
    if (
        environment not in {"staging", "production"}
        or type(service_uid) is not int
        or service_uid <= 0
        or os.geteuid() != service_uid
        or document.get("protected_store_observed") is not True
    ):
        raise ControlledExecutionQuiescenceV2Error(
            "Controlled transition principal or activation is absent"
        )
    store_path = _activation_absolute_path(document, "store_path")
    _require_live_controlled_store_identity_v2(
        store_path, expected_uid=service_uid, allow_missing=False
    )
    return _ControlledStoreIdentityV2(
        environment=environment,
        service_uid=service_uid,
        store_path=store_path,
    )


def acquire_live_controlled_writer_lifecycle_v2(
    *, expected_environment: str
) -> ControlledWriterLifecycleLeaseV2:
    """Daemon entrypoint: lock before build_service or any SQLite open."""

    identity = _live_identity_from_activation()
    if identity.environment != expected_environment:
        raise ControlledExecutionQuiescenceV2Error(
            "Controlled lifecycle environment differs from activation"
        )
    return _acquire_lifecycle_lock(identity, require_marker_absent=True)


def require_held_controlled_writer_lifecycle_v2(
    lifecycle: object,
    *,
    expected_environment: str | None,
    expected_store_path: Path | None = None,
) -> ControlledWriterLifecycleLeaseV2:
    """Validate the exact daemon-held capability without opening SQLite."""

    if type(lifecycle) is not ControlledWriterLifecycleLeaseV2:
        raise ControlledExecutionQuiescenceV2Error(
            "Controlled live SQLite access requires the exact lifecycle lease"
        )
    lifecycle._require_held()
    if (
        lifecycle.service_uid != os.geteuid()
        or (
            expected_environment is not None
            and lifecycle.environment != expected_environment
        )
        or (
            expected_store_path is not None
            and lifecycle.store_path != expected_store_path
        )
    ):
        raise ControlledExecutionQuiescenceV2Error(
            "Controlled lifecycle does not match the live principal, environment, "
            "and store"
        )
    return lifecycle


def _create_transition_marker(
    identity: _ControlledStoreIdentityV2,
    *,
    store_identity: tuple[int, int],
    session_id: str,
    parent_descriptor: int,
) -> tuple[Path, int, tuple[int, int], bytes]:
    _lock_path, marker_path = _transition_paths(identity.store_path)
    marker = {
        "format": CONTROLLED_QUIESCENCE_MARKER_FORMAT,
        "state": "WRITER_RESUME_FORBIDDEN",
        "environment": identity.environment,
        "service_uid": identity.service_uid,
        "store_device": store_identity[0],
        "store_inode": store_identity[1],
        "session_id": session_id,
    }
    marker_bytes = _canonical_bytes(marker)
    flags = (
        os.O_RDWR
        | os.O_CREAT
        | os.O_EXCL
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_NONBLOCK", 0)
    )
    descriptor = -1
    try:
        descriptor = os.open(marker_path, flags, 0o600)
        os.fchmod(descriptor, 0o600)
        offset = 0
        while offset < len(marker_bytes):
            written = _os_write(descriptor, marker_bytes[offset:])
            if written <= 0:
                raise OSError("Controlled quiescence marker write made no progress")
            offset += written
        os.fsync(descriptor)
        os.fsync(parent_descriptor)
        observed = os.fstat(descriptor)
        _require_pinned_regular_file(
            marker_path,
            descriptor=descriptor,
            expected_uid=identity.service_uid,
            expected_identity=(observed.st_dev, observed.st_ino),
            label="Controlled quiescence marker",
        )
        if observed.st_size != len(marker_bytes):
            raise ControlledExecutionQuiescenceV2Error(
                "Controlled quiescence marker size is not exact"
            )
    except FileExistsError as exc:
        raise ControlledExecutionQuiescenceV2Error(
            "Controlled writer resume is already forbidden by a transition"
        ) from exc
    except ControlledExecutionQuiescenceV2Error:
        if descriptor >= 0:
            os.close(descriptor)
        raise
    except OSError as exc:
        if descriptor >= 0:
            os.close(descriptor)
        raise ControlledExecutionQuiescenceV2Error(
            "Controlled quiescence marker cannot be created durably"
        ) from exc
    return (
        marker_path,
        descriptor,
        (observed.st_dev, observed.st_ino),
        marker_bytes,
    )


def _begin_transition(
    identity: _ControlledStoreIdentityV2,
) -> ControlledCanaryStoreTransitionSessionV2:
    lease = _acquire_lifecycle_lock(
        identity,
        require_marker_absent=True,
        monitor_marker_absent=False,
    )
    db_descriptor = -1
    parent_descriptor = -1
    marker_descriptor = -1
    try:
        parent_descriptor = _open_parent(
            identity.store_path.parent, expected_uid=identity.service_uid
        )
        parent_observed = os.fstat(parent_descriptor)
        parent_identity = (parent_observed.st_dev, parent_observed.st_ino)
        flags = (
            os.O_RDWR
            | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_NOFOLLOW", 0)
            | getattr(os, "O_NONBLOCK", 0)
        )
        try:
            db_descriptor = os.open(identity.store_path, flags)
        except OSError as exc:
            raise ControlledExecutionQuiescenceV2Error(
                "Controlled store cannot be pinned for transition"
            ) from exc
        observed = os.fstat(db_descriptor)
        store_identity = (observed.st_dev, observed.st_ino)
        _require_pinned_regular_file(
            identity.store_path,
            descriptor=db_descriptor,
            expected_uid=identity.service_uid,
            expected_identity=store_identity,
            label="Controlled store",
        )
        _require_sqlite_header(
            db_descriptor,
            expected_versions=_WAL_HEADER_VERSIONS,
            label="Controlled store",
        )
        _validate_existing_sidecars(
            identity.store_path, expected_uid=identity.service_uid
        )
        session_id = str(uuid.uuid4())
        (
            marker_path,
            marker_descriptor,
            marker_identity,
            marker_bytes,
        ) = _create_transition_marker(
            identity,
            store_identity=store_identity,
            session_id=session_id,
            parent_descriptor=parent_descriptor,
        )
        connection: sqlite3.Connection | None = None
        try:
            connection = _open_exclusive_connection(identity.store_path)
            _require_path_matches_descriptor(
                identity.store_path,
                db_descriptor,
                expected_uid=identity.service_uid,
                expected_identity=store_identity,
            )
            checkpoint = connection.execute(
                "PRAGMA wal_checkpoint(TRUNCATE)"
            ).fetchone()
            if checkpoint is None or tuple(checkpoint) != (0, 0, 0):
                raise ControlledExecutionQuiescenceV2Error(
                    "Controlled WAL checkpoint was not exactly empty and complete"
                )
            mode = connection.execute("PRAGMA journal_mode=DELETE").fetchone()
            if mode is None or str(mode[0]).lower() != "delete":
                raise ControlledExecutionQuiescenceV2Error(
                    "Controlled store did not enter exact DELETE mode"
                )
        except sqlite3.Error as exc:
            raise ControlledExecutionQuiescenceV2Error(
                "Controlled store exclusive WAL-to-DELETE transition failed"
            ) from exc
        finally:
            if connection is not None:
                try:
                    connection.close()
                except sqlite3.Error as exc:
                    raise ControlledExecutionQuiescenceV2Error(
                        "Controlled SQLite connection did not close cleanly"
                    ) from exc
        _require_path_matches_descriptor(
            identity.store_path,
            db_descriptor,
            expected_uid=identity.service_uid,
            expected_identity=store_identity,
        )
        _require_sqlite_header(
            db_descriptor,
            expected_versions=_DELETE_HEADER_VERSIONS,
            label="Controlled store",
        )
        os.fsync(db_descriptor)
        os.fsync(parent_descriptor)
        _require_no_sidecars(identity.store_path)
        session = ControlledCanaryStoreTransitionSessionV2(
            identity=identity,
            lease=lease,
            db_descriptor=db_descriptor,
            parent_descriptor=parent_descriptor,
            parent_identity=parent_identity,
            store_identity=store_identity,
            marker_path=marker_path,
            marker_descriptor=marker_descriptor,
            marker_identity=marker_identity,
            marker_bytes=marker_bytes,
            session_id=session_id,
            _token=_SESSION_TOKEN,
        )
        session._require_active(expected_header=_DELETE_HEADER_VERSIONS)
        return session
    except BaseException:
        for descriptor in (marker_descriptor, db_descriptor, parent_descriptor):
            if descriptor >= 0:
                os.close(descriptor)
        lease.close()
        # Once the marker is durable, every failure intentionally leaves it in
        # place.  The daemon observes it before opening any SQLite database.
        raise


def begin_live_controlled_canary_store_transition_v2(
) -> ControlledCanaryStoreTransitionSessionV2:
    """Future workflow hook; derives every resource from protected activation."""

    return _begin_transition(_live_identity_from_activation())


__all__ = [
    "CONTROLLED_QUIESCENCE_STATE",
    "ControlledCanaryStoreTransitionSessionV2",
    "ControlledExecutionQuiescenceV2Error",
    "ControlledWriterLifecycleLeaseV2",
    "acquire_live_controlled_writer_lifecycle_v2",
    "begin_live_controlled_canary_store_transition_v2",
    "require_held_controlled_writer_lifecycle_v2",
]
