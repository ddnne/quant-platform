#!/usr/bin/env python3
"""Concrete C4/C10/R5 handlers for the isolated local authority runtime.

The classes here are authority-process code.  They accept only the narrow
payload selected by their exact Unix method ACL, derive governed values from
configured or descriptor-bound evidence, sign with protected key custody, and
return evidence consumable by the existing public-key-only product boundaries.
The checked-in key registries remain PENDING, so these handlers cannot produce
a usable positive capability in the current checkout.
"""

from __future__ import annotations

import base64
import fcntl
import hashlib
import json
import os
import sqlite3
import stat
import tempfile
from collections.abc import Callable, Mapping, Sequence
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import MappingProxyType
from typing import Any
from urllib.parse import quote
from uuid import uuid4

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from ops import d1_sync_signing, projection_signing, trust_domain
from paper_runtime import begin_snapshot_sync, readiness_attestation
from storage import coverage_transition

from scripts import authority_protocol_runtime, export_ops_projection, sync_d1_to_sqlite
from scripts.local_ready_registry import (
    LocalReadyRegistryError,
    derive_ready_authority_resource_digest,
    load_scoped_ready_public_keys,
    ready_authority_instance_id,
)
from scripts.local_authority_files import (
    ProtectedAuthorityFileError,
    read_protected_authority_file,
)
from scripts.local_authority_service import (
    REQUEST_FORMAT,
    AuthorityRequestContext,
    FileEd25519KeyCustody,
    LocalAuthorityError,
    LocalAuthorityPending,
    SQLiteAuthorityEventLedger,
    call_unix_authority,
    decode_strict_json,
    require_declared_service_identity,
    sha256_digest,
)

_READY_TTL_SECONDS = 60 * 60
OWNED_MIRROR_EVIDENCE_FORMAT = "d1-owned-frozen-mirror/v1"
_OWNED_MIRROR_FIELDS = {
    "format",
    "environment",
    "purpose",
    "governed_db_path",
    "descriptor",
    "sync_identity",
    "sync_identity_digest",
}
_DESCRIPTOR_FIELDS = {
    "owner_uid",
    "device",
    "inode",
    "size",
    "mtime_ns",
    "mode",
    "content_digest",
}
_D1_RECONCILED_FACT_FIELDS = {
    "sync_kind",
    "export_digest",
    "artifact_format",
    "source_change_seq",
    "applied_change_seq",
    "source_content_digest",
    "local_content_digest",
    "source_schema_digest",
    "schema_digest",
    "table_counts",
    "prior_audit_digest",
    "exported_at",
}
_D1_SYNC_OPERATION = "d1_sync:sync_now"
_D1_SYNC_JOURNAL_FORMAT = "d1-sync-atomic-replace/v2"
_D1_SYNC_JOURNAL_MAX_AGE_SECONDS = 60 * 60
_D1_SYNC_PHASES = (
    "PREPARED",
    "ACQUIRED",
    "TEMP_APPLIED",
    "SIGNED_AUDIT",
    "FILE_FSYNCED",
    "COMMITTED",
)
_D1_SYNC_FILE_IDENTITY_FIELDS = {
    "owner_uid",
    "owner_gid",
    "device",
    "inode",
    "size",
    "mtime_ns",
    "mode",
    "nlink",
    "content_digest",
}
_D1_SYNC_JOURNAL_FIELDS = {
    "format",
    "operation_id",
    "phase",
    "environment",
    "resource_identity",
    "governed_db_path",
    "prior_applied_cursor",
    "prior_mirror_identity",
    "prior_sync_identity",
    "policy_digest",
    "tool_digest",
    "source_sha",
    "outer_request_id",
    "outer_request_digest",
    "outer_caller",
    "outer_operation",
    "outer_purpose",
    "outer_result_digest",
    "candidate_path",
    "export_digest",
    "artifact_format",
    "candidate_file_identity",
    "candidate_sync_identity",
    "sync_result",
    "prepared_at",
    "updated_at",
    "previous_record_digest",
    "record_digest",
}
_D1_SYNC_RESULT_FIELDS = {
    "status",
    "prior_applied_cursor",
    "source_change_seq",
    "applied_change_seq",
    "audit_digest",
    "export_digest",
    "issuer_key_id",
    "seen",
    "registered",
    "skipped",
}


def _d1_sync_now() -> datetime:
    return datetime.now(UTC)


def _is_sha256_digest(value: object) -> bool:
    return (
        type(value) is str
        and value.startswith("sha256:")
        and len(value) == 71
        and all(character in "0123456789abcdef" for character in value[7:])
    )


def _d1_sync_paths(governed_db_path: Path) -> tuple[Path, Path]:
    name = governed_db_path.name
    return (
        governed_db_path.with_name(f".{name}.d1-sync-journal.json"),
        governed_db_path.with_name(f".{name}.d1-sync.lock"),
    )


def _d1_sync_create_staging_path(journal_path: Path) -> Path:
    """Return the one protocol-reserved unpublished journal pathname."""

    return journal_path.with_name(f"{journal_path.name}.create.tmp")


def _fsync_directory(directory: Path) -> None:
    flags = (
        os.O_RDONLY
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    try:
        fd = os.open(directory, flags)
    except OSError as exc:
        raise LocalAuthorityError("D1 sync parent directory is unavailable") from exc
    try:
        os.fsync(fd)
    except OSError as exc:
        raise LocalAuthorityError("D1 sync parent directory fsync failed") from exc
    finally:
        os.close(fd)


def _require_d1_sync_parent(directory: Path) -> None:
    try:
        info = directory.lstat()
    except OSError as exc:
        raise LocalAuthorityError("D1 sync parent directory is unavailable") from exc
    if (
        not directory.is_absolute()
        or not stat.S_ISDIR(info.st_mode)
        or info.st_uid != os.geteuid()
        or stat.S_IMODE(info.st_mode) & 0o022
    ):
        raise LocalAuthorityError("D1 sync parent directory is unsafe")


@contextmanager
def _exclusive_d1_sync_lock(lock_path: Path):
    """Serialize recovery and replacement without using the product DB."""

    _require_d1_sync_parent(lock_path.parent)
    flags = (
        os.O_RDWR
        | os.O_CREAT
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    try:
        fd = os.open(lock_path, flags, 0o600)
    except OSError as exc:
        raise LocalAuthorityError("D1 sync operation lock is unavailable") from exc
    try:
        info = os.fstat(fd)
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_uid != os.geteuid()
            or info.st_nlink != 1
            or stat.S_IMODE(info.st_mode) != 0o600
        ):
            raise LocalAuthorityError("D1 sync operation lock is unsafe")
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise LocalAuthorityPending("another governed D1 sync is in progress") from exc
        yield
    finally:
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)


def _measure_d1_sync_file(path: Path) -> dict[str, Any]:
    """Bind one protected path to stable bytes and one exact inode."""

    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(
        os, "O_NOFOLLOW", 0
    )
    try:
        fd = os.open(path, flags)
    except OSError as exc:
        raise LocalAuthorityError("D1 sync mirror cannot be opened") from exc
    try:
        before = os.fstat(fd)
        path_before = path.lstat()
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_uid != os.geteuid()
            or before.st_nlink != 1
            or stat.S_IMODE(before.st_mode) != 0o600
            or before.st_size <= 0
            or (path_before.st_dev, path_before.st_ino)
            != (before.st_dev, before.st_ino)
        ):
            raise LocalAuthorityError("D1 sync mirror identity is unsafe")
        digest = hashlib.sha256()
        offset = 0
        while offset < before.st_size:
            chunk = os.pread(fd, min(1024 * 1024, before.st_size - offset), offset)
            if not chunk:
                raise LocalAuthorityError("D1 sync mirror changed while hashing")
            digest.update(chunk)
            offset += len(chunk)
        after = os.fstat(fd)
        path_after = path.lstat()
        stable = (
            before.st_dev,
            before.st_ino,
            before.st_size,
            before.st_mtime_ns,
            before.st_ctime_ns,
            before.st_nlink,
        )
        if stable != (
            after.st_dev,
            after.st_ino,
            after.st_size,
            after.st_mtime_ns,
            after.st_ctime_ns,
            after.st_nlink,
        ) or (path_after.st_dev, path_after.st_ino) != (
            before.st_dev,
            before.st_ino,
        ):
            raise LocalAuthorityError("D1 sync mirror changed while hashing")
        return {
            "owner_uid": int(after.st_uid),
            "owner_gid": int(after.st_gid),
            "device": int(after.st_dev),
            "inode": int(after.st_ino),
            "size": int(after.st_size),
            "mtime_ns": int(after.st_mtime_ns),
            "mode": stat.S_IMODE(after.st_mode),
            "nlink": int(after.st_nlink),
            "content_digest": "sha256:" + digest.hexdigest(),
        }
    finally:
        os.close(fd)


def _require_no_sqlite_sidecars(path: Path) -> None:
    for suffix in ("-wal", "-shm", "-journal"):
        sidecar = Path(f"{path}{suffix}")
        try:
            sidecar.lstat()
        except FileNotFoundError:
            continue
        except OSError as exc:
            raise LocalAuthorityError(
                "D1 sync mirror sidecar state is unavailable"
            ) from exc
        # ``Path.exists`` follows links and therefore misses a dangling
        # symlink.  Any directory entry here means the pathname is not one
        # closed, immutable SQLite file and must block handoff/recovery.
        raise LocalAuthorityError("D1 sync mirror has a live SQLite sidecar")


def _read_prior_d1_sync_identity(
    path: Path, *, expected_applied_cursor: int
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    """Read the prior mirror without creating tables, WAL, or policy state."""

    _require_no_sqlite_sidecars(path)
    before = _measure_d1_sync_file(path)
    uri = f"file:{quote(str(path), safe='/')}?mode=ro&immutable=1"
    try:
        conn = sqlite3.connect(uri, uri=True)
    except sqlite3.Error as exc:
        raise LocalAuthorityError("governed D1 mirror is not readable SQLite") from exc
    try:
        integrity = conn.execute("PRAGMA integrity_check").fetchall()
        if integrity != [("ok",)]:
            raise LocalAuthorityError("governed D1 mirror integrity check failed")
        has_cursor = conn.execute(
            "SELECT 1 FROM main.sqlite_schema WHERE type='table' "
            "AND name='sync_change_state'"
        ).fetchone()
        if has_cursor is None:
            observed_cursor = 0
        else:
            row = conn.execute(
                "SELECT last_applied_change_seq FROM main.sync_change_state "
                "WHERE feed='jquants_records'"
            ).fetchone()
            observed_cursor = int(row[0]) if row is not None else 0
        if observed_cursor != expected_applied_cursor:
            raise LocalAuthorityError(
                "D1 sync expected applied cursor does not match the governed mirror"
            )
        sync_identity = None
        if observed_cursor > 0:
            sync_identity = _json_materialize(
                sync_d1_to_sqlite._authenticated_applied_mirror_identity_from_conn(
                    conn
                )
            )
            if type(sync_identity) is not dict:
                raise LocalAuthorityError("prior D1 sync identity is invalid")
    except sqlite3.Error as exc:
        raise LocalAuthorityError("governed D1 mirror cannot be inspected") from exc
    finally:
        conn.close()
    after = _measure_d1_sync_file(path)
    if after != before:
        raise LocalAuthorityError("governed D1 mirror changed during preparation")
    return before, sync_identity


def _copy_prior_mirror_to_candidate(
    governed_db_path: Path,
    candidate_path: Path,
    *,
    prior_identity: Mapping[str, Any],
) -> None:
    """Create a same-directory O_EXCL SQLite backup; never edit the live DB."""

    if candidate_path.parent != governed_db_path.parent:
        raise LocalAuthorityError("D1 sync candidate is not in the mirror directory")
    flags = (
        os.O_RDWR
        | os.O_CREAT
        | os.O_EXCL
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    try:
        fd = os.open(candidate_path, flags, 0o600)
    except FileExistsError as exc:
        raise LocalAuthorityError("D1 sync candidate already exists") from exc
    except OSError as exc:
        raise LocalAuthorityError("D1 sync candidate cannot be created") from exc
    else:
        os.close(fd)
    source_uri = f"file:{quote(str(governed_db_path), safe='/')}?mode=ro&immutable=1"
    source: sqlite3.Connection | None = None
    target: sqlite3.Connection | None = None
    try:
        source = sqlite3.connect(source_uri, uri=True)
        target = sqlite3.connect(str(candidate_path))
        source.backup(target)
        target.commit()
        target.close()
        target = None
        source.close()
        source = None
        if _measure_d1_sync_file(governed_db_path) != dict(prior_identity):
            raise LocalAuthorityError("governed D1 mirror changed during backup")
        _fsync_file(candidate_path)
    except BaseException:
        if target is not None:
            target.close()
        if source is not None:
            source.close()
        _remove_d1_sync_candidate(candidate_path, allow_missing=True)
        raise


def _fsync_file(path: Path) -> None:
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(
        os, "O_NOFOLLOW", 0
    )
    try:
        fd = os.open(path, flags)
    except OSError as exc:
        raise LocalAuthorityError("D1 sync candidate cannot be opened for fsync") from exc
    try:
        info = os.fstat(fd)
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_uid != os.geteuid()
            or info.st_nlink != 1
            or stat.S_IMODE(info.st_mode) != 0o600
        ):
            raise LocalAuthorityError("D1 sync candidate fsync identity is unsafe")
        os.fsync(fd)
    except OSError as exc:
        raise LocalAuthorityError("D1 sync candidate fsync failed") from exc
    finally:
        os.close(fd)


def _remove_d1_sync_candidate(path: Path, *, allow_missing: bool) -> None:
    removed = False
    for selected in (Path(f"{path}-wal"), Path(f"{path}-shm"), Path(f"{path}-journal"), path):
        try:
            info = selected.lstat()
        except FileNotFoundError:
            if selected == path and not allow_missing:
                raise LocalAuthorityError("D1 sync candidate is missing")
            continue
        except OSError as exc:
            raise LocalAuthorityError("D1 sync candidate cleanup failed") from exc
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_uid != os.geteuid()
            or info.st_nlink != 1
        ):
            raise LocalAuthorityError("D1 sync candidate cleanup identity is unsafe")
        try:
            selected.unlink()
        except OSError as exc:
            raise LocalAuthorityError("D1 sync candidate cleanup failed") from exc
        removed = True
    if removed:
        _fsync_directory(path.parent)


def _strict_d1_sync_json(raw: bytes) -> dict[str, Any]:
    def reject_duplicate(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise LocalAuthorityError("D1 sync journal contains duplicate keys")
            result[key] = value
        return result

    def reject_number(value: str) -> None:
        raise LocalAuthorityError(f"D1 sync journal contains forbidden number {value}")

    try:
        document = json.loads(
            raw,
            object_pairs_hook=reject_duplicate,
            parse_float=reject_number,
            parse_constant=reject_number,
        )
    except LocalAuthorityError:
        raise
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise LocalAuthorityError("D1 sync journal is invalid JSON") from exc
    if type(document) is not dict:
        raise LocalAuthorityError("D1 sync journal must be one object")
    return document


def _d1_sync_record_digest(document: Mapping[str, Any]) -> str:
    return sha256_digest(
        {key: value for key, value in document.items() if key != "record_digest"}
    )


def _validate_d1_sync_journal(document: dict[str, Any]) -> dict[str, Any]:
    if set(document) != _D1_SYNC_JOURNAL_FIELDS:
        raise LocalAuthorityError("D1 sync journal fields are not closed")
    if (
        document["format"] != _D1_SYNC_JOURNAL_FORMAT
        or document["phase"] not in _D1_SYNC_PHASES
        or type(document["operation_id"]) is not str
        or not document["operation_id"].startswith("d1-sync-")
        or type(document["governed_db_path"]) is not str
        or not Path(document["governed_db_path"]).is_absolute()
        or type(document["candidate_path"]) is not str
        or not Path(document["candidate_path"]).is_absolute()
        or type(document["prior_applied_cursor"]) is not int
        or document["prior_applied_cursor"] < 0
        or type(document["prior_mirror_identity"]) is not dict
        or set(document["prior_mirror_identity"])
        != _D1_SYNC_FILE_IDENTITY_FIELDS
        or type(document["prior_sync_identity"]) not in {dict, type(None)}
        or not all(
            _is_sha256_digest(document[field])
            for field in ("policy_digest", "tool_digest", "source_sha")
        )
        or type(document["outer_request_id"]) is not str
        or not document["outer_request_id"]
        or not _is_sha256_digest(document["outer_request_digest"])
        or type(document["outer_caller"]) is not str
        or not document["outer_caller"]
        or document["outer_operation"] != _D1_SYNC_OPERATION
        or type(document["outer_purpose"]) is not str
        or not document["outer_purpose"]
        or type(document["prepared_at"]) is not str
        or type(document["updated_at"]) is not str
        or type(document["previous_record_digest"]) not in {str, type(None)}
        or (
            document["phase"] == "PREPARED"
            and document["previous_record_digest"] is not None
        )
        or (
            document["phase"] != "PREPARED"
            and not _is_sha256_digest(document["previous_record_digest"])
        )
        or not _is_sha256_digest(document["record_digest"])
        or document["record_digest"] != _d1_sync_record_digest(document)
    ):
        raise LocalAuthorityError("D1 sync journal identity is invalid")
    expected_candidate = Path(document["governed_db_path"]).with_name(
        f".{Path(document['governed_db_path']).name}."
        f"{document['operation_id']}.sqlite3"
    )
    if Path(document["candidate_path"]) != expected_candidate:
        raise LocalAuthorityError("D1 sync journal candidate identity is invalid")
    try:
        prepared = datetime.fromisoformat(document["prepared_at"].replace("Z", "+00:00"))
        updated = datetime.fromisoformat(document["updated_at"].replace("Z", "+00:00"))
    except ValueError as exc:
        raise LocalAuthorityError("D1 sync journal timestamp is invalid") from exc
    now = _d1_sync_now()
    if (
        prepared.tzinfo is None
        or updated.tzinfo is None
        or updated < prepared
        or updated > now + timedelta(seconds=60)
        or (
            document["phase"] != "COMMITTED"
            and now - updated
            > timedelta(seconds=_D1_SYNC_JOURNAL_MAX_AGE_SECONDS)
        )
    ):
        raise LocalAuthorityError("D1 sync journal is stale")
    phase_index = _D1_SYNC_PHASES.index(document["phase"])
    acquired = phase_index >= _D1_SYNC_PHASES.index("ACQUIRED")
    signed = phase_index >= _D1_SYNC_PHASES.index("SIGNED_AUDIT")
    fsynced = phase_index >= _D1_SYNC_PHASES.index("FILE_FSYNCED")
    result = document["sync_result"]
    if (
        (acquired and not _is_sha256_digest(document["export_digest"]))
        or (not acquired and document["export_digest"] is not None)
        or (acquired and document["artifact_format"] not in {"sql", "sqlite"})
        or (not acquired and document["artifact_format"] is not None)
        or (signed and type(document["candidate_sync_identity"]) is not dict)
        or (not signed and document["candidate_sync_identity"] is not None)
        or (signed and type(document["sync_result"]) is not dict)
        or (not signed and document["sync_result"] is not None)
        or (signed and not _is_sha256_digest(document["outer_result_digest"]))
        or (not signed and document["outer_result_digest"] is not None)
        or (
            type(result) is dict
            and (
                set(result) != _D1_SYNC_RESULT_FIELDS
                or result.get("status") != "SYNCED"
                or result.get("prior_applied_cursor")
                != document["prior_applied_cursor"]
                or type(result.get("source_change_seq")) is not int
                or result.get("source_change_seq", -1) < 0
                or result.get("applied_change_seq")
                != result.get("source_change_seq")
                or result.get("export_digest") != document["export_digest"]
                or not _is_sha256_digest(result.get("audit_digest"))
                or type(result.get("issuer_key_id")) is not str
                or not result.get("issuer_key_id")
                or any(
                    type(result.get(field)) is not int
                    or result.get(field, -1) < 0
                    for field in ("seen", "registered", "skipped")
                )
            )
        )
        or (
            type(result) is dict
            and document["outer_result_digest"] != sha256_digest(result)
        )
        or (fsynced and type(document["candidate_file_identity"]) is not dict)
        or (not fsynced and document["candidate_file_identity"] is not None)
        or (
            type(document["candidate_file_identity"]) is dict
            and set(document["candidate_file_identity"])
            != _D1_SYNC_FILE_IDENTITY_FIELDS
        )
    ):
        raise LocalAuthorityError("D1 sync journal phase evidence is invalid")
    return document


def _read_d1_sync_journal(path: Path) -> dict[str, Any] | None:
    try:
        info = path.lstat()
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise LocalAuthorityError("D1 sync journal is unavailable") from exc
    if (
        not stat.S_ISREG(info.st_mode)
        or info.st_uid != os.geteuid()
        or info.st_nlink != 1
        or stat.S_IMODE(info.st_mode) != 0o600
        or info.st_size <= 0
        or info.st_size > 1024 * 1024
    ):
        raise LocalAuthorityError("D1 sync journal metadata is unsafe")
    try:
        protected = read_protected_authority_file(
            path,
            expected_owner_uids={os.geteuid()},
            allowed_modes={0o600},
            max_bytes=1024 * 1024,
        )
    except ProtectedAuthorityFileError as exc:
        raise LocalAuthorityError("D1 sync journal changed while read") from exc
    return _validate_d1_sync_journal(_strict_d1_sync_json(protected.raw))


def _remove_unpublished_d1_sync_journal(path: Path) -> None:
    """Remove only the reserved, never-published create staging inode."""

    try:
        info = path.lstat()
    except FileNotFoundError:
        return
    except OSError as exc:
        raise LocalAuthorityError(
            "D1 sync journal create staging is unavailable"
        ) from exc
    if (
        not stat.S_ISREG(info.st_mode)
        or info.st_uid != os.geteuid()
        or info.st_nlink != 1
        or stat.S_IMODE(info.st_mode) != 0o600
    ):
        raise LocalAuthorityError("D1 sync journal create staging is unsafe")
    try:
        path.unlink()
    except OSError as exc:
        raise LocalAuthorityError(
            "D1 sync journal create staging cleanup failed"
        ) from exc
    _fsync_directory(path.parent)


def _recover_d1_sync_journal_publication(path: Path) -> None:
    """Finish or discard only an unpublished PREPARED journal.

    Initial creation never writes the canonical pathname.  The fully-fsynced
    staging inode is first made durable, then hard-linked create-only to the
    canonical name.  These two names make every power-loss point recoverable
    without ever exposing a partial canonical journal.
    """

    staging = _d1_sync_create_staging_path(path)
    try:
        staging_info = staging.lstat()
    except FileNotFoundError:
        return
    except OSError as exc:
        raise LocalAuthorityError(
            "D1 sync journal create staging is unavailable"
        ) from exc
    try:
        journal_info = path.lstat()
    except FileNotFoundError:
        journal_info = None
    except OSError as exc:
        raise LocalAuthorityError("D1 sync journal is unavailable") from exc

    if journal_info is not None:
        if (
            not stat.S_ISREG(staging_info.st_mode)
            or not stat.S_ISREG(journal_info.st_mode)
            or staging_info.st_uid != os.geteuid()
            or journal_info.st_uid != os.geteuid()
            or stat.S_IMODE(staging_info.st_mode) != 0o600
            or stat.S_IMODE(journal_info.st_mode) != 0o600
            or (staging_info.st_dev, staging_info.st_ino)
            != (journal_info.st_dev, journal_info.st_ino)
            or staging_info.st_nlink != 2
            or journal_info.st_nlink != 2
        ):
            raise LocalAuthorityError(
                "D1 sync journal create publication is ambiguous"
            )
        try:
            staging.unlink()
        except OSError as exc:
            raise LocalAuthorityError(
                "D1 sync journal create publication cleanup failed"
            ) from exc
        _fsync_directory(path.parent)
        # Validate only after returning the canonical inode to its required
        # single-link state.  Our publisher never links before a successful
        # file fsync, so an invalid body remains fail-closed.
        if _read_d1_sync_journal(path) is None:  # pragma: no cover - defensive
            raise LocalAuthorityError("D1 sync journal publication disappeared")
        return

    try:
        staged = _read_d1_sync_journal(staging)
    except LocalAuthorityError:
        # A crash while writing/fsyncing the unpublished inode cannot have
        # created a candidate or touched the live DB.  The reserved staging
        # pathname may therefore be discarded after strict inode checks.
        _remove_unpublished_d1_sync_journal(staging)
        return
    if staged["phase"] != "PREPARED":
        raise LocalAuthorityError(
            "D1 sync unpublished journal phase is not PREPARED"
        )
    try:
        os.link(staging, path, follow_symlinks=False)
    except FileExistsError as exc:
        raise LocalAuthorityError(
            "D1 sync journal create publication raced"
        ) from exc
    except OSError as exc:
        raise LocalAuthorityError(
            "D1 sync journal create publication failed"
        ) from exc
    _fsync_directory(path.parent)
    try:
        staging.unlink()
    except OSError as exc:
        raise LocalAuthorityError(
            "D1 sync journal create publication cleanup failed"
        ) from exc
    _fsync_directory(path.parent)


def _write_d1_sync_journal(
    path: Path, document: Mapping[str, Any], *, create_only: bool
) -> dict[str, Any]:
    body = dict(document)
    body["record_digest"] = _d1_sync_record_digest(body)
    frozen = _validate_d1_sync_journal(body)
    raw = json.dumps(
        frozen,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8") + b"\n"
    flags = (
        os.O_WRONLY
        | os.O_CREAT
        | os.O_EXCL
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    selected = (
        _d1_sync_create_staging_path(path)
        if create_only
        else path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    )
    try:
        fd = os.open(selected, flags, 0o600)
    except FileExistsError as exc:
        raise LocalAuthorityError("D1 sync journal already exists") from exc
    except OSError as exc:
        raise LocalAuthorityError("D1 sync journal cannot be created") from exc
    try:
        offset = 0
        while offset < len(raw):
            offset += os.write(fd, raw[offset:])
        os.fchmod(fd, 0o600)
        os.fsync(fd)
    except BaseException:
        os.close(fd)
        selected.unlink(missing_ok=True)
        raise
    else:
        os.close(fd)
    try:
        if create_only:
            # Persist the only recoverable pre-publication name before making
            # the canonical journal visible.  The link itself is O_EXCL.
            _fsync_directory(path.parent)
            os.link(selected, path, follow_symlinks=False)
            _fsync_directory(path.parent)
            selected.unlink()
        else:
            os.replace(selected, path)
        _fsync_directory(path.parent)
    except BaseException:
        if selected != path:
            selected.unlink(missing_ok=True)
        raise
    return frozen


def _advance_d1_sync_journal(
    path: Path,
    current: Mapping[str, Any],
    *,
    phase: str,
    **updates: Any,
) -> dict[str, Any]:
    observed = _read_d1_sync_journal(path)
    if observed is None or observed["record_digest"] != current["record_digest"]:
        raise LocalAuthorityError("D1 sync journal changed during operation")
    if (
        phase not in _D1_SYNC_PHASES
        or _D1_SYNC_PHASES.index(phase) <= _D1_SYNC_PHASES.index(current["phase"])
    ):
        raise LocalAuthorityError("D1 sync journal phase did not advance")
    if not set(updates).issubset(_D1_SYNC_JOURNAL_FIELDS - {"record_digest"}):
        raise LocalAuthorityError("D1 sync journal update fields are invalid")
    next_document = dict(current)
    next_document.update(updates)
    next_document["phase"] = phase
    next_document["updated_at"] = _d1_sync_now().isoformat()
    next_document["previous_record_digest"] = current["record_digest"]
    next_document["record_digest"] = None
    return _write_d1_sync_journal(path, next_document, create_only=False)


def _remove_d1_sync_journal(path: Path, *, expected_digest: str) -> None:
    current = _read_d1_sync_journal(path)
    if current is None or current["record_digest"] != expected_digest:
        raise LocalAuthorityError("D1 sync journal changed before completion")
    try:
        path.unlink()
    except OSError as exc:
        raise LocalAuthorityError("D1 sync journal cleanup failed") from exc
    _fsync_directory(path.parent)


def _read_candidate_sync_identity(
    path: Path, *, require_fresh: bool = True
) -> dict[str, Any]:
    _require_no_sqlite_sidecars(path)
    uri = f"file:{quote(str(path), safe='/')}?mode=ro&immutable=1"
    try:
        conn = sqlite3.connect(uri, uri=True)
    except sqlite3.Error as exc:
        raise LocalAuthorityError("D1 sync candidate is not readable SQLite") from exc
    try:
        if require_fresh:
            identity = _json_materialize(
                sync_d1_to_sqlite._authenticated_applied_mirror_identity_from_conn(
                    conn
                )
            )
        else:
            row = sync_d1_to_sqlite._latest_export_sync_row(conn)
            if row is None:
                raise ValueError("D1 sync candidate has no signed audit")
            envelope = sync_d1_to_sqlite._verified_sync_envelope_from_row(
                conn,
                row,
                recompute_local=True,
                require_fresh=False,
            )
            identity = _json_materialize(
                {
                    "environment": envelope["environment"],
                    "resource_identity": dict(envelope["resource_identity"]),
                    "audit_digest": row.get("audit_digest"),
                    "issuer_key_id": row.get("issuer_key_id"),
                    "export_digest": envelope["export_digest"],
                    "source_change_seq": envelope["source_change_seq"],
                    "applied_change_seq": envelope["applied_change_seq"],
                    "source_content_digest": envelope["source_content_digest"],
                    "local_content_digest": envelope["local_content_digest"],
                    "source_schema_digest": envelope["source_schema_digest"],
                    "schema_digest": envelope["schema_digest"],
                    "table_counts": dict(envelope["table_counts"]),
                }
            )
    except (sqlite3.Error, ValueError, TypeError, RuntimeError) as exc:
        raise LocalAuthorityError("D1 sync candidate audit is invalid") from exc
    finally:
        conn.close()
    if type(identity) is not dict:
        raise LocalAuthorityError("D1 sync candidate identity is invalid")
    return identity


def _d1_sync_policy_digest(
    *, environment: str, source_sha: str, tool_digest: str
) -> str:
    return sha256_digest(
        {
            "format": "d1-sync-atomic-policy/v1",
            "environment": environment,
            "resource_identity": dict(trust_domain.d1_resource_identity(environment)),
            "inventory": list(sync_d1_to_sqlite.DEFAULT_TABLES),
            "page_limit": sync_d1_to_sqlite.DEFAULT_PAGE_LIMIT,
            "max_pages": sync_d1_to_sqlite.DEFAULT_MAX_PAGES,
            "registry_digest": d1_sync_signing.registry_document_digest(environment),
            "journal_format": _D1_SYNC_JOURNAL_FORMAT,
            "source_sha": source_sha,
            "tool_digest": tool_digest,
        }
    )


def _observe_d1_sync_tool_digest(resources: Mapping[str, Any]) -> str:
    """Remeasure every activation-pinned Wrangler resource before each use."""

    from scripts.local_authority_activation import (
        ActivationStateError,
        observe_runtime_resource_bindings,
    )

    try:
        observed = observe_runtime_resource_bindings(
            authority_id="d1_sync",
            resources=resources,
            expected_owner_uid=0,
        )
    except ActivationStateError as exc:
        raise LocalAuthorityError(
            "D1 sync Wrangler tool binding cannot be remeasured"
        ) from exc
    return _d1_sync_tool_bindings_digest(observed)


def _observe_d1_sync_activation_identity(
    *,
    environment: str,
    expected_uid: int,
) -> dict[str, str]:
    """Remeasure the root-pinned runtime bundle, tools, registry, and policy."""

    uid, activation = require_declared_service_identity(
        authority_id="d1_sync", environment=environment
    )
    if uid != expected_uid:
        raise LocalAuthorityError("D1 sync activation service identity changed")
    source_sha = activation.get("runtime_bundle_digest")
    tool_digest = _d1_sync_tool_bindings_digest(
        activation.get("runtime_resource_bindings")
    )
    if not _is_sha256_digest(source_sha) or not _is_sha256_digest(tool_digest):
        raise LocalAuthorityError("D1 sync activation digest is invalid")
    return {
        "source_sha": source_sha,
        "tool_digest": tool_digest,
        "policy_digest": _d1_sync_policy_digest(
            environment=environment,
            source_sha=source_sha,
            tool_digest=tool_digest,
        ),
    }


def _d1_sync_tool_bindings_digest(bindings: object) -> str:
    materialized = _json_materialize(bindings)
    if type(materialized) is not list:
        raise LocalAuthorityError("D1 sync tool bindings are not one exact list")
    return sha256_digest(
        {
            "format": "d1-sync-tool-bindings/v1",
            "bindings": materialized,
        }
    )


def _d1_sync_request_binding(
    context: AuthorityRequestContext, *, environment: str
) -> dict[str, str]:
    if (
        type(context) is not AuthorityRequestContext
        or context.grant.environment != environment
        or context.grant.operation != _D1_SYNC_OPERATION
        or context.caller != context.grant.caller
        or not _is_sha256_digest(context.request_digest)
    ):
        raise LocalAuthorityError("D1 sync request context binding is invalid")
    return {
        "outer_request_id": context.request_id,
        "outer_request_digest": context.request_digest,
        "outer_caller": context.caller,
        "outer_operation": context.grant.operation,
        "outer_purpose": context.grant.purpose,
    }


def _require_d1_sync_runtime_identity(
    observer: Callable[[], Mapping[str, Any]],
    *,
    source_sha: str,
    tool_digest: str,
    policy_digest: str,
) -> None:
    try:
        observed = dict(observer())
    except LocalAuthorityError:
        raise
    except Exception as exc:
        raise LocalAuthorityError(
            "D1 sync activation identity cannot be remeasured"
        ) from exc
    expected = {
        "source_sha": source_sha,
        "tool_digest": tool_digest,
        "policy_digest": policy_digest,
    }
    if observed != expected:
        raise LocalAuthorityError("D1 sync activation identity changed")


def _recover_d1_sync_journal(
    *,
    journal_path: Path,
    governed_db_path: Path,
    expected_applied_cursor: int,
    environment: str,
    source_sha: str,
    tool_digest: str,
    policy_digest: str,
    request_context: AuthorityRequestContext,
    runtime_identity_observer: Callable[[], Mapping[str, Any]],
    committed_event_verifier: Callable[..., bool],
) -> Mapping[str, Any] | None:
    """Roll back an unfinished candidate or finish one exact durable replace."""

    journal = _read_d1_sync_journal(journal_path)
    if journal is None:
        return None
    expected_resource = dict(trust_domain.d1_resource_identity(environment))
    bindings = {
        "environment": environment,
        "resource_identity": expected_resource,
        "governed_db_path": str(governed_db_path),
        "source_sha": source_sha,
        "tool_digest": tool_digest,
        "policy_digest": policy_digest,
    }
    for field, expected in bindings.items():
        if journal[field] != expected:
            raise LocalAuthorityError(f"D1 sync journal {field} binding differs")
    request_binding = _d1_sync_request_binding(
        request_context, environment=environment
    )
    same_outer_request = all(
        journal[field] == expected for field, expected in request_binding.items()
    )
    committed = journal["phase"] == "COMMITTED"
    final_cursor = (
        journal["sync_result"].get("applied_change_seq")
        if type(journal["sync_result"]) is dict
        else None
    )
    allowed_cursors = (
        {journal["prior_applied_cursor"], final_cursor}
        if committed
        else {journal["prior_applied_cursor"]}
    )
    if expected_applied_cursor not in allowed_cursors:
        raise LocalAuthorityError(
            "D1 sync journal prior_applied_cursor binding differs"
        )
    candidate_path = Path(journal["candidate_path"])
    # A WAL/SHM/rollback-journal entry means the pathname is not the single
    # frozen SQLite file recorded by this protocol.  Reject it before any
    # recovery cleanup or replacement can mutate state.  This check is also
    # repeated at the FILE_FSYNCED handoff below to close the recovery window.
    _require_no_sqlite_sidecars(governed_db_path)
    live_identity = _measure_d1_sync_file(governed_db_path)
    prior_identity = journal["prior_mirror_identity"]
    if journal["phase"] not in {"FILE_FSYNCED", "COMMITTED"}:
        if live_identity != prior_identity:
            raise LocalAuthorityError("D1 sync recovery found an ambiguous live mirror")
        _remove_d1_sync_candidate(candidate_path, allow_missing=True)
        _remove_d1_sync_journal(
            journal_path, expected_digest=journal["record_digest"]
        )
        return None

    candidate_exists = candidate_path.exists()
    expected_candidate_file = journal["candidate_file_identity"]
    expected_candidate_sync = journal["candidate_sync_identity"]
    if committed:
        if candidate_exists or live_identity != expected_candidate_file:
            raise LocalAuthorityError("D1 sync committed mirror identity differs")
        live_sync = _read_candidate_sync_identity(
            governed_db_path, require_fresh=False
        )
        if live_sync != expected_candidate_sync:
            raise LocalAuthorityError("D1 sync committed mirror audit differs")
        _fsync_directory(governed_db_path.parent)
        result = dict(journal["sync_result"])
        if (
            same_outer_request
            and expected_applied_cursor == journal["prior_applied_cursor"]
        ):
            # The governed mirror and this receipt commit before the outer
            # authority event ledger.  A crash in that gap can repeat any
            # number of times.  Only the exact original request may replay the
            # durable receipt while its outer event is absent.
            return result
        try:
            outer_committed = committed_event_verifier(
                request_id=journal["outer_request_id"],
                caller=journal["outer_caller"],
                operation=journal["outer_operation"],
                purpose=journal["outer_purpose"],
                request_digest=journal["outer_request_digest"],
                result_digest=journal["outer_result_digest"],
            )
        except LocalAuthorityError:
            raise
        except Exception as exc:
            raise LocalAuthorityError(
                "D1 sync outer event commitment cannot be verified"
            ) from exc
        if outer_committed is not True:
            raise LocalAuthorityPending(
                "prior D1 sync result awaits its exact outer event commit"
            )
        _remove_d1_sync_journal(
            journal_path, expected_digest=journal["record_digest"]
        )
        return None
    if candidate_exists:
        candidate_file = _measure_d1_sync_file(candidate_path)
        if candidate_file != expected_candidate_file:
            raise LocalAuthorityError("D1 sync recovery candidate identity differs")
        candidate_sync = _read_candidate_sync_identity(candidate_path)
        if (
            candidate_sync != expected_candidate_sync
            or candidate_sync.get("export_digest") != journal["export_digest"]
        ):
            raise LocalAuthorityError("D1 sync recovery candidate identity differs")
    if live_identity == prior_identity:
        if not candidate_exists:
            _remove_d1_sync_journal(
                journal_path, expected_digest=journal["record_digest"]
            )
            return None
        _require_no_sqlite_sidecars(governed_db_path)
        if _measure_d1_sync_file(governed_db_path) != prior_identity:
            raise LocalAuthorityError(
                "D1 sync recovery found an ambiguous live mirror"
            )
        _require_no_sqlite_sidecars(governed_db_path)
        _require_d1_sync_runtime_identity(
            runtime_identity_observer,
            source_sha=source_sha,
            tool_digest=tool_digest,
            policy_digest=policy_digest,
        )
        request_context.require_within_processing_deadline()
        os.replace(candidate_path, governed_db_path)
        _fsync_directory(governed_db_path.parent)
    elif live_identity == expected_candidate_file:
        if candidate_exists:
            raise LocalAuthorityError("D1 sync recovery has duplicate candidate identity")
        live_sync = _read_candidate_sync_identity(governed_db_path)
        if live_sync != expected_candidate_sync:
            raise LocalAuthorityError("D1 sync replaced mirror audit identity differs")
        _fsync_directory(governed_db_path.parent)
    else:
        raise LocalAuthorityError("D1 sync recovery found an ambiguous live mirror")
    committed_file = _measure_d1_sync_file(governed_db_path)
    committed_sync = _read_candidate_sync_identity(governed_db_path)
    if (
        committed_file != expected_candidate_file
        or committed_sync != expected_candidate_sync
    ):
        raise LocalAuthorityError("D1 sync replacement postcondition differs")
    committed_journal = _advance_d1_sync_journal(
        journal_path,
        journal,
        phase="COMMITTED",
    )
    return dict(committed_journal["sync_result"])


def _require_payload_fields(
    payload: Mapping[str, Any], *, fields: set[str], operation: str
) -> dict[str, Any]:
    if type(payload) not in {dict, MappingProxyType}:
        raise LocalAuthorityError(f"{operation} payload must be an object")
    frozen = dict(payload)
    if set(frozen) != fields:
        raise LocalAuthorityError(f"{operation} payload fields are not closed")
    return frozen


def _decode_standard_base64(value: object, *, field: str) -> bytes:
    if type(value) is not str or not value:
        raise LocalAuthorityError(f"{field} must be base64 text")
    try:
        decoded = base64.b64decode(value, validate=True)
    except (TypeError, ValueError) as exc:
        raise LocalAuthorityError(f"{field} is invalid base64") from exc
    if base64.b64encode(decoded).decode("ascii") != value:
        raise LocalAuthorityError(f"{field} is not canonical base64")
    return decoded


def _custody_public_key(custody: FileEd25519KeyCustody) -> Ed25519PublicKey:
    try:
        return Ed25519PublicKey.from_public_bytes(
            base64.b64decode(custody.public_key_base64(), validate=True)
        )
    except (TypeError, ValueError) as exc:  # pragma: no cover - adapter invariant
        raise LocalAuthorityError("authority custody public key is invalid") from exc


def _append_content_addressed(
    directory: Path,
    *,
    prefix: str,
    content: bytes,
) -> tuple[str, str]:
    """Create one immutable authority artifact without replace semantics."""

    if type(content) is not bytes or not content:
        raise LocalAuthorityError("authority artifact must be non-empty bytes")
    try:
        info = directory.lstat()
    except OSError as exc:
        raise LocalAuthorityPending("authority artifact store is unavailable") from exc
    if (
        not stat.S_ISDIR(info.st_mode)
        or info.st_uid != os.geteuid()
        or stat.S_IMODE(info.st_mode) & 0o027
    ):
        raise LocalAuthorityError("authority artifact store is not protected")
    digest = "sha256:" + hashlib.sha256(content).hexdigest()
    name = f"{prefix}-{digest.removeprefix('sha256:')}.json"
    path = directory / name
    flags = (
        os.O_WRONLY
        | os.O_CREAT
        | os.O_EXCL
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    try:
        fd = os.open(path, flags, 0o440)
    except FileExistsError:
        try:
            existing = read_protected_authority_file(
                path,
                expected_owner_uids={os.geteuid()},
                allowed_modes={0o440},
                max_bytes=len(content),
            ).raw
        except ProtectedAuthorityFileError as exc:
            raise LocalAuthorityError(
                "authority artifact collision is unreadable"
            ) from exc
        if existing != content:
            raise LocalAuthorityError("authority artifact digest collision")
        return name, digest
    except OSError as exc:
        raise LocalAuthorityError("authority artifact create failed") from exc
    try:
        offset = 0
        while offset < len(content):
            offset += os.write(fd, content[offset:])
        os.fsync(fd)
        os.fchmod(fd, 0o440)
    except BaseException:
        os.close(fd)
        path.unlink(missing_ok=True)
        raise
    else:
        os.close(fd)
    directory_fd = os.open(directory, os.O_RDONLY | getattr(os, "O_CLOEXEC", 0))
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)
    return name, digest


def _json_materialize(value: object) -> object:
    if isinstance(value, Mapping):
        return {str(key): _json_materialize(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_json_materialize(item) for item in value]
    if type(value) in {str, int, bool, type(None)}:
        return value
    raise LocalAuthorityError("owned mirror identity is not exact JSON")


def _hash_regular_fd(fd: int) -> tuple[str, os.stat_result]:
    try:
        flags = fcntl.fcntl(fd, fcntl.F_GETFL) & os.O_ACCMODE
        before = os.fstat(fd)
    except OSError as exc:
        raise LocalAuthorityError("owned mirror descriptor is unavailable") from exc
    if (
        flags != os.O_RDONLY
        or not stat.S_ISREG(before.st_mode)
        or before.st_size <= 0
        or before.st_nlink != 1
    ):
        raise LocalAuthorityError("owned mirror descriptor is not read-only SQLite")
    digest = hashlib.sha256()
    offset = 0
    while offset < before.st_size:
        chunk = os.pread(fd, min(1024 * 1024, before.st_size - offset), offset)
        if not chunk:
            raise LocalAuthorityError("owned mirror descriptor changed while hashing")
        digest.update(chunk)
        offset += len(chunk)
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
        raise LocalAuthorityError("owned mirror descriptor changed while hashing")
    return "sha256:" + digest.hexdigest(), after


def _open_d1_owned_readonly_fd(db_path: Path) -> int:
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(db_path, flags)
        info = os.fstat(fd)
    except OSError as exc:
        raise LocalAuthorityError("d1_sync governed mirror cannot be opened") from exc
    if (
        not stat.S_ISREG(info.st_mode)
        or info.st_uid != os.geteuid()
        or stat.S_IMODE(info.st_mode) & 0o077
        or info.st_nlink != 1
    ):
        os.close(fd)
        raise LocalAuthorityError("d1_sync governed mirror ownership is unsafe")
    return fd


def _owned_mirror_evidence(
    fd: int,
    *,
    environment: str,
    purpose: str,
    governed_db_path: Path,
    sync_identity: Mapping[str, object],
) -> dict[str, Any]:
    content_digest, info = _hash_regular_fd(fd)
    identity = _json_materialize(sync_identity)
    if type(identity) is not dict:
        raise LocalAuthorityError("owned mirror sync identity is invalid")
    return {
        "format": OWNED_MIRROR_EVIDENCE_FORMAT,
        "environment": environment,
        "purpose": purpose,
        "governed_db_path": str(governed_db_path),
        "descriptor": {
            "owner_uid": info.st_uid,
            "device": info.st_dev,
            "inode": info.st_ino,
            "size": info.st_size,
            "mtime_ns": info.st_mtime_ns,
            "mode": stat.S_IMODE(info.st_mode),
            "content_digest": content_digest,
        },
        "sync_identity": identity,
        "sync_identity_digest": sha256_digest(identity),
    }


def _validate_owned_mirror(
    payload: Mapping[str, Any],
    fds: Sequence[int],
    *,
    environment: str,
    purpose: str,
    expected_d1_uid: int,
) -> tuple[
    sqlite3.Connection,
    dict[str, Any],
    str,
    dict[str, Any],
    tuple[int, int, int],
]:
    values = _require_payload_fields(
        payload,
        fields={"owned_mirror_evidence", "selector"},
        operation=purpose,
    )
    if len(fds) != 1 or type(values["owned_mirror_evidence"]) is not dict:
        raise LocalAuthorityError("authority requires one d1-owned mirror descriptor")
    evidence = values["owned_mirror_evidence"]
    if (
        set(evidence) != _OWNED_MIRROR_FIELDS
        or evidence["format"] != OWNED_MIRROR_EVIDENCE_FORMAT
        or evidence["environment"] != environment
        or evidence["purpose"] != purpose
        or type(evidence["governed_db_path"]) is not str
        or not Path(evidence["governed_db_path"]).is_absolute()
        or type(evidence["descriptor"]) is not dict
        or set(evidence["descriptor"]) != _DESCRIPTOR_FIELDS
        or type(evidence["sync_identity"]) is not dict
        or evidence["sync_identity_digest"] != sha256_digest(evidence["sync_identity"])
        or type(values["selector"]) is not dict
    ):
        raise LocalAuthorityError("owned mirror evidence identity is invalid")
    digest, info = _hash_regular_fd(fds[0])
    descriptor = evidence["descriptor"]
    observed = {
        "owner_uid": info.st_uid,
        "device": info.st_dev,
        "inode": info.st_ino,
        "size": info.st_size,
        "mtime_ns": info.st_mtime_ns,
        "mode": stat.S_IMODE(info.st_mode),
        "content_digest": digest,
    }
    if observed != descriptor or info.st_uid != expected_d1_uid:
        raise LocalAuthorityError("mirror descriptor is not owned by d1_sync")
    governed_path = Path(evidence["governed_db_path"])
    try:
        governed_lstat = governed_path.lstat()
        governed_stat = governed_path.stat()
    except OSError as exc:
        raise LocalAuthorityError("owned governed mirror path is unavailable") from exc
    if stat.S_ISLNK(governed_lstat.st_mode) or (
        governed_stat.st_dev,
        governed_stat.st_ino,
    ) != (info.st_dev, info.st_ino):
        raise LocalAuthorityError("owned governed mirror path differs from descriptor")
    conn = authority_protocol_runtime._connect_readonly_fd(fds[0])
    try:
        conn.execute("BEGIN")
        measured = authority_protocol_runtime._remeasure_applied_mirror_identity(conn)
        if _json_materialize(measured) != evidence["sync_identity"]:
            raise LocalAuthorityError("owned mirror sync identity changed")
        final_digest, final_info = _hash_regular_fd(fds[0])
        if final_digest != digest or final_info.st_ino != info.st_ino:
            raise LocalAuthorityError("owned mirror changed during verification")
    except BaseException:
        conn.close()
        raise
    return (
        conn,
        dict(values["selector"]),
        evidence["governed_db_path"],
        dict(evidence),
        (int(info.st_dev), int(info.st_ino), int(info.st_size)),
    )


class OpsProjectionRenderAndSign:
    """C4: render from an authenticated read-only mirror FD, then sign."""

    operation = "ops_projection:render_and_sign"

    def __init__(
        self,
        *,
        environment: str,
        custody: FileEd25519KeyCustody,
        artifact_store: str | Path,
        expected_d1_uid: int,
    ) -> None:
        if environment not in {"staging", "production"}:
            raise LocalAuthorityError("Ops Projection environment is invalid")
        self.environment = environment
        self.custody = custody
        self.artifact_store = Path(artifact_store)
        self.expected_d1_uid = expected_d1_uid

    def __call__(
        self,
        _context: AuthorityRequestContext,
        payload: Mapping[str, Any],
        fds: Sequence[int],
    ) -> Mapping[str, Any]:
        conn, selector, _, _evidence, authority_file_identity = (
            _validate_owned_mirror(
                payload,
                fds,
                environment=self.environment,
                purpose="ops_projection",
                expected_d1_uid=self.expected_d1_uid,
            )
        )
        if selector:
            conn.close()
            raise LocalAuthorityError("Ops Projection selector must be empty")
        try:
            sync_identity = (
                authority_protocol_runtime._remeasure_applied_mirror_identity(conn)
            )
            frozen_sync_identity = authority_protocol_runtime._deep_immutable(
                sync_identity
            )
            candidate = (
                export_ops_projection._render_projection_candidate_from_authority_connection(
                    conn,
                    frozen_sync_identity,
                    authority_file_identity=authority_file_identity,
                )
            )
        finally:
            conn.close()
        candidate_document = json.loads(candidate.candidate_bytes)
        envelope = dict(candidate_document["projection"]["envelope"])
        sync_identity = candidate_document["sync_identity"]
        envelope.update(
            {
                "environment": self.environment,
                "resource_identity": trust_domain.projection_resource_identity(
                    environment=self.environment,
                    source=sync_identity,
                ),
            }
        )
        projection_signing._validate_envelope(
            envelope, expected_environment=self.environment
        )
        body = projection_signing._signed_body(
            key_id=self.custody.key_id,
            envelope=envelope,
        )
        signed_document = {
            **body,
            "signature": self.custody.sign(
                projection_signing.canonical_json_bytes(body)
            ),
        }
        public = _custody_public_key(self.custody)
        projection_signing._verify_document(
            signed_document,
            {self.custody.key_id: public},
            expected_environment=self.environment,
        )
        active = projection_signing._load_pinned_active_keys(self.environment)
        active_public = active.get(self.custody.key_id)
        if (
            active_public is None
            or active_public.public_bytes_raw() != public.public_bytes_raw()
        ):
            raise LocalAuthorityPending(
                "Ops Projection public registry does not activate the custody key"
            )
        projection_signing.verify_pinned_ops_projection(
            signed_document, expected_environment=self.environment
        )
        signed_bytes = projection_signing.canonical_json_bytes(signed_document)
        signed_name, signed_store_digest = _append_content_addressed(
            self.artifact_store,
            prefix="ops-projection-signed",
            content=signed_bytes,
        )
        return {
            "status": "SIGNED",
            "signed_artifact": signed_name,
            "signed_store_digest": signed_store_digest,
            "signed_document_base64": base64.b64encode(signed_bytes).decode("ascii"),
            "signed_document_digest": "sha256:"
            + hashlib.sha256(signed_bytes).hexdigest(),
            "issuer_key_id": self.custody.key_id,
        }


class CoverageTransitionAuthorize:
    """C10 signer: derive from the d1-owned FD and return, never callback."""

    operation = "coverage_transition:authorize"

    def __init__(
        self,
        *,
        environment: str,
        custody: FileEd25519KeyCustody,
        expected_d1_uid: int,
    ) -> None:
        if environment not in {"staging", "production"}:
            raise LocalAuthorityError("Coverage environment is invalid")
        self.environment = environment
        self.custody = custody
        self.expected_d1_uid = expected_d1_uid

    def __call__(
        self,
        _context: AuthorityRequestContext,
        payload: Mapping[str, Any],
        fds: Sequence[int],
    ) -> Mapping[str, Any]:
        conn, selector, governed_db_path, evidence, _authority_file_identity = (
            _validate_owned_mirror(
                payload,
                fds,
                environment=self.environment,
                purpose="coverage_transition",
                expected_d1_uid=self.expected_d1_uid,
            )
        )
        build_id = selector.get("build_id")
        datasets = selector.get("datasets")
        if (
            type(build_id) is not str
            or not build_id
            or type(datasets) is not list
            or not datasets
            or any(type(item) is not str or not item for item in datasets)
        ):
            conn.close()
            raise LocalAuthorityError("Coverage authorization selector is invalid")
        issued = datetime.now(UTC).replace(microsecond=0)
        expires = issued + timedelta(
            seconds=min(300, coverage_transition.MAX_AUTHORIZATION_SECONDS)
        )
        try:
            request = dict(
                coverage_transition.build_coverage_transition_request_from_owned_connection(
                    conn,
                    governed_db_path=governed_db_path,
                    build_id=build_id,
                    datasets=datasets,
                    issued_at=issued.isoformat().replace("+00:00", "Z"),
                    expires_at=expires.isoformat().replace("+00:00", "Z"),
                )
            )
            body = dict(request["body"])
            sync_identity = evidence["sync_identity"]
            body.update(
                {
                    "environment": self.environment,
                    "resource_identity": {
                        "environment": self.environment,
                        "source_d1": sync_identity["resource_identity"],
                        "source_audit_digest": sync_identity["audit_digest"],
                        "source_export_digest": sync_identity["export_digest"],
                        "source_change_seq": sync_identity["source_change_seq"],
                        "governed_db_content_digest": evidence["descriptor"][
                            "content_digest"
                        ],
                    },
                }
            )
            request = coverage_transition._unsigned_request(body)
        finally:
            conn.close()
        document = {
            "format": request["format"],
            "authority_domain": request["authority_domain"],
            "issuer": coverage_transition.COVERAGE_TRANSITION_ISSUER,
            "issuer_key_id": self.custody.key_id,
            "algorithm": coverage_transition.COVERAGE_TRANSITION_ALGORITHM,
            "transition_id": request["transition_id"],
            "body": request["body"],
        }
        message = coverage_transition._signature_message(document)
        document["signature"] = self.custody.sign(
            coverage_transition._canonical_bytes(message)
        )
        frozen = coverage_transition._validate_signed_document(
            document, expected_environment=self.environment
        )
        registry = coverage_transition.CoverageTransitionPublicKeyRegistry.load_pinned(
            expected_environment=self.environment
        )
        if not registry.provisioned or not registry.verify(
            key_id=self.custody.key_id,
            message=message,
            signature=frozen["signature"],
        ):
            raise LocalAuthorityPending(
                "Coverage transition public registry does not activate the custody key"
            )
        return {
            "status": "SIGNED",
            "transition_id": frozen["transition_id"],
            "build_id": frozen["body"]["build_id"],
            "dataset_set_digest": frozen["body"]["dataset_set_digest"],
            "signed_transition_digest": sha256_digest(frozen),
            "signed_transition": frozen,
            "issuer_key_id": self.custody.key_id,
        }


class D1FreezeAndRenderOpsProjection:
    operation = "d1_sync:freeze_and_render_ops_projection"

    def __init__(
        self,
        *,
        environment: str,
        governed_db_path: str | Path,
        ops_socket_path: str | Path,
        ops_uid: int,
    ) -> None:
        self.environment = environment
        self.environment = trust_domain.require_environment(environment)
        self.governed_db_path = Path(governed_db_path).absolute()
        self.ops_socket_path = Path(ops_socket_path)
        self.ops_uid = ops_uid

    def __call__(
        self,
        _context: AuthorityRequestContext,
        payload: Mapping[str, Any],
        fds: Sequence[int],
    ) -> Mapping[str, Any]:
        if payload or fds:
            raise LocalAuthorityError("d1 Ops freeze accepts no caller evidence")
        handle = sync_d1_to_sqlite.open_authenticated_applied_mirror(
            self.governed_db_path
        )

        def consume(
            _conn: sqlite3.Connection, identity: Mapping[str, object]
        ) -> Mapping[str, Any]:
            fd = _open_d1_owned_readonly_fd(self.governed_db_path)
            try:
                evidence = _owned_mirror_evidence(
                    fd,
                    environment=self.environment,
                    purpose="ops_projection",
                    governed_db_path=self.governed_db_path,
                    sync_identity=identity,
                )
                request = {
                    "format": REQUEST_FORMAT,
                    "request_id": sha256_digest(
                        {"operation": self.operation, "evidence": evidence}
                    ),
                    "operation": OpsProjectionRenderAndSign.operation,
                    "purpose": "render_owned_mirror_projection",
                    "payload": {"owned_mirror_evidence": evidence, "selector": {}},
                }
                result = call_unix_authority(
                    self.ops_socket_path,
                    request,
                    expected_server_uid=self.ops_uid,
                    read_only_fd=fd,
                )
                expected_fields = {
                    "status",
                    "signed_artifact",
                    "signed_store_digest",
                    "signed_document_base64",
                    "signed_document_digest",
                    "issuer_key_id",
                }
                if type(result) not in {dict, MappingProxyType} or set(result) != expected_fields:
                    raise LocalAuthorityError(
                        "Ops authority response is not one closed signed document"
                    )
                signed_bytes = _decode_standard_base64(
                    result["signed_document_base64"],
                    field="signed_document_base64",
                )
                if (
                    result["status"] != "SIGNED"
                    or result["signed_document_digest"]
                    != "sha256:" + hashlib.sha256(signed_bytes).hexdigest()
                ):
                    raise LocalAuthorityError(
                        "Ops authority response is not signed evidence"
                    )
                verified = projection_signing._verify_pinned_document(
                    signed_bytes, expected_environment=self.environment
                )
                if verified.issuer_key_id != result["issuer_key_id"]:
                    raise LocalAuthorityError(
                        "Ops authority response issuer identity differs"
                    )
                return result
            finally:
                os.close(fd)

        return sync_d1_to_sqlite._consume_authenticated_applied_mirror(handle, consume)


class _SealedD1SyncAudit:
    """Single-use result passed only from D1 authority signing to persistence."""

    __slots__ = ("_consumed", "_document")

    def __init__(self, document: dict[str, Any]) -> None:
        self._document = document
        self._consumed = False

    def _consume_for_persistence(self) -> tuple[str, str, str, dict[str, Any]]:
        if self._consumed:
            raise LocalAuthorityError("sealed D1 sync audit was already consumed")
        self._consumed = True
        document = self._document
        return (
            d1_sync_signing.d1_sync_digest(document),
            document["issuer_key_id"],
            document["signature"],
            document,
        )


class _D1SyncAuditSealer:
    """Consume only the opaque exact-reconciliation capability and sign it."""

    def __init__(self, custody: FileEd25519KeyCustody, *, environment: str) -> None:
        self.custody = custody
        self.environment = trust_domain.require_environment(environment)

    def preflight(self) -> None:
        try:
            registry = d1_sync_signing._load_registry_document(self.environment)
        except d1_sync_signing.D1SyncAuditError as exc:
            raise LocalAuthorityPending(
                "D1 sync public registry is unavailable"
            ) from exc
        matches = [
            row
            for row in registry["keys"]
            if row["key_id"] == self.custody.key_id
            and row["status"] == "active"
            and row["public_key_base64"] == self.custody.public_key_base64()
        ]
        if registry["authority_status"] != "ACTIVE" or len(matches) != 1:
            raise LocalAuthorityPending(
                "D1 sync public registry does not activate the custody key"
            )

    def __call__(self, reconciled_export: object) -> _SealedD1SyncAudit:
        self.preflight()
        try:
            facts = (
                sync_d1_to_sqlite._private_export.
                _consume_authenticated_export_for_authority(
                    reconciled_export
                )
            )
        except RuntimeError as exc:
            raise LocalAuthorityError(
                "D1 sync signer requires opaque reconciled export evidence"
            ) from exc
        if type(facts) is not dict or set(facts) != _D1_RECONCILED_FACT_FIELDS:
            raise LocalAuthorityError("D1 reconciled export facts are not closed")
        issued_at = d1_sync_signing._utc_now().isoformat()
        resource = dict(trust_domain.d1_resource_identity(self.environment))
        envelope = {
            "schema_version": d1_sync_signing.AUDIT_ENVELOPE_SCHEMA,
            "authority_id": resource["authority_id"],
            "source_mode": "WRANGLER_REMOTE",
            "environment": self.environment,
            "resource_identity": resource,
            "d1_name": resource["name"],
            "d1_id": resource["database_id"],
            **facts,
            "registry_digest": (
                d1_sync_signing.registry_document_digest(self.environment)
            ),
            "issued_at": issued_at,
        }
        body = {
            "schema_version": d1_sync_signing.SIGNED_DOCUMENT_SCHEMA,
            "algorithm": "Ed25519",
            "issuer_key_id": self.custody.key_id,
            "envelope": envelope,
        }
        document = {
            **body,
            "signature": self.custody.sign(
                d1_sync_signing.canonical_d1_sync_bytes(body)
            ),
        }
        d1_sync_signing.verify_signed_d1_sync_audit(
            document, expected_environment=self.environment
        )
        return _SealedD1SyncAudit(document)


def _read_protected_cloudflare_token(path: Path, *, expected_uid: int) -> str:
    try:
        before = path.lstat()
    except OSError as exc:
        raise LocalAuthorityPending(
            "D1 sync Cloudflare credential file is unavailable"
        ) from exc
    if (
        not path.is_absolute()
        or not stat.S_ISREG(before.st_mode)
        or before.st_uid != expected_uid
        or before.st_nlink != 1
        or stat.S_IMODE(before.st_mode) != 0o400
    ):
        raise LocalAuthorityError("D1 sync Cloudflare credential file is unsafe")
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(path, flags)
        raw = os.read(fd, 514)
        after = os.fstat(fd)
    except OSError as exc:
        raise LocalAuthorityPending(
            "D1 sync Cloudflare credential cannot be read"
        ) from exc
    finally:
        if "fd" in locals():
            os.close(fd)
    if (
        (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
        != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
        or len(raw) > 513
    ):
        raise LocalAuthorityError("D1 sync Cloudflare credential changed while read")
    if raw.endswith(b"\n"):
        raw = raw[:-1]
    try:
        token = raw.decode("ascii")
    except UnicodeDecodeError as exc:
        raise LocalAuthorityError("D1 sync Cloudflare credential is invalid") from exc
    if (
        not 20 <= len(token) <= 512
        or any(character.isspace() for character in token)
    ):
        raise LocalAuthorityError("D1 sync Cloudflare credential is invalid")
    return token


def _execute_governed_remote_sync(
    *,
    governed_db_path: Path,
    expected_applied_cursor: int,
    credential_token: str,
    node_executable_path: Path,
    wrangler_cli_path: Path,
    wrangler_config_path: Path,
    sealer: _D1SyncAuditSealer,
    environment: str,
    source_sha: str,
    tool_digest: str,
    request_context: AuthorityRequestContext,
    runtime_identity_observer: Callable[[], Mapping[str, Any]],
    committed_event_verifier: Callable[..., bool],
    _fault_inject: Callable[[str], None] | None = None,
) -> Mapping[str, Any]:
    """Build one signed candidate and atomically replace the governed mirror.

    Remote acquisition and reconciliation never hold a transaction on the
    live mirror.  A protected phase journal makes every crash point either an
    exact rollback to the prior inode or completion of one already-fsynced,
    signed candidate.
    """

    from types import SimpleNamespace

    from storage.sqlite_store import SqliteStore

    environment = trust_domain.require_environment(environment)
    if not _is_sha256_digest(source_sha) or not _is_sha256_digest(tool_digest):
        raise LocalAuthorityError("D1 sync runtime source/tool identity is invalid")
    request_binding = _d1_sync_request_binding(
        request_context, environment=environment
    )
    governed_db_path = governed_db_path.absolute()
    journal_path, lock_path = _d1_sync_paths(governed_db_path)
    policy_digest = _d1_sync_policy_digest(
        environment=environment,
        source_sha=source_sha,
        tool_digest=tool_digest,
    )

    def fault(point: str) -> None:
        if _fault_inject is not None:
            _fault_inject(point)

    with _exclusive_d1_sync_lock(lock_path):
        _recover_d1_sync_journal_publication(journal_path)
        recovered = _recover_d1_sync_journal(
            journal_path=journal_path,
            governed_db_path=governed_db_path,
            expected_applied_cursor=expected_applied_cursor,
            environment=environment,
            source_sha=source_sha,
            tool_digest=tool_digest,
            policy_digest=policy_digest,
            request_context=request_context,
            runtime_identity_observer=runtime_identity_observer,
            committed_event_verifier=committed_event_verifier,
        )
        if recovered is not None:
            return recovered

        prior_file_identity, prior_sync_identity = _read_prior_d1_sync_identity(
            governed_db_path,
            expected_applied_cursor=expected_applied_cursor,
        )
        operation_id = "d1-sync-" + uuid4().hex
        candidate_path = governed_db_path.with_name(
            f".{governed_db_path.name}.{operation_id}.sqlite3"
        )
        prepared_at = _d1_sync_now().isoformat()
        journal = _write_d1_sync_journal(
            journal_path,
            {
                "format": _D1_SYNC_JOURNAL_FORMAT,
                "operation_id": operation_id,
                "phase": "PREPARED",
                "environment": environment,
                "resource_identity": dict(
                    trust_domain.d1_resource_identity(environment)
                ),
                "governed_db_path": str(governed_db_path),
                "prior_applied_cursor": expected_applied_cursor,
                "prior_mirror_identity": prior_file_identity,
                "prior_sync_identity": prior_sync_identity,
                "policy_digest": policy_digest,
                "tool_digest": tool_digest,
                "source_sha": source_sha,
                **request_binding,
                "outer_result_digest": None,
                "candidate_path": str(candidate_path),
                "export_digest": None,
                "artifact_format": None,
                "candidate_file_identity": None,
                "candidate_sync_identity": None,
                "sync_result": None,
                "prepared_at": prepared_at,
                "updated_at": prepared_at,
                "previous_record_digest": None,
                "record_digest": None,
            },
            create_only=True,
        )
        fault("after_prepared")

        store: SqliteStore | None = None
        temporary: tempfile.TemporaryDirectory[str] | None = None
        source_conn: sqlite3.Connection | None = None
        handoff_guard_failed = False
        try:
            _copy_prior_mirror_to_candidate(
                governed_db_path,
                candidate_path,
                prior_identity=prior_file_identity,
            )
            sealer.preflight()
            temporary = tempfile.TemporaryDirectory(
                prefix="quant-authority-d1-sync-"
            )
            acquired = (
                sync_d1_to_sqlite._private_export.
                _acquire_pinned_wrangler_export_with_preflight(
                    Path(temporary.name),
                    authority_preflight=sealer.preflight,
                    credential_token=credential_token,
                    authority_node_path=node_executable_path,
                    authority_wrangler_cli_path=wrangler_cli_path,
                    authority_wrangler_config_path=wrangler_config_path,
                    authority_environment=environment,
                )
            )
            if (
                not _is_sha256_digest(acquired.export_digest)
                or acquired.artifact_format not in {"sql", "sqlite"}
            ):
                raise LocalAuthorityError("acquired D1 export identity is invalid")
            _require_d1_sync_runtime_identity(
                runtime_identity_observer,
                source_sha=source_sha,
                tool_digest=tool_digest,
                policy_digest=policy_digest,
            )
            journal = _advance_d1_sync_journal(
                journal_path,
                journal,
                phase="ACQUIRED",
                export_digest=acquired.export_digest,
                artifact_format=acquired.artifact_format,
            )
            fault("after_acquisition")

            source_conn = acquired.open_source()
            store = SqliteStore(candidate_path)
            sync_d1_to_sqlite._ensure_control_tables(store._conn)
            sync_d1_to_sqlite._ensure_export_sync_audit(store)
            store._conn.commit()
            if sync_d1_to_sqlite._last_change_seq(store) != expected_applied_cursor:
                raise LocalAuthorityError(
                    "D1 sync candidate cursor differs from its prior mirror"
                )
            incremental = (
                sync_d1_to_sqlite._latest_trusted_sync_audit(store) is not None
            )
            args = SimpleNamespace(
                table=None,
                incremental=incremental,
                since=None,
                page_limit=sync_d1_to_sqlite.DEFAULT_PAGE_LIMIT,
                max_pages=sync_d1_to_sqlite.DEFAULT_MAX_PAGES,
                pilot_ready_evidence=None,
                snapshot_dir=None,
                db=str(candidate_path),
            )
            begin_snapshot_sync(
                store._conn,
                started_at=_d1_sync_now().isoformat(),
            )
            seal_invoked = False

            def seal_after_temp_apply(capability: object) -> _SealedD1SyncAudit:
                nonlocal journal, seal_invoked
                if seal_invoked:
                    raise LocalAuthorityError(
                        "D1 sync candidate requested more than one signed audit"
                    )
                seal_invoked = True
                journal = _advance_d1_sync_journal(
                    journal_path,
                    journal,
                    phase="TEMP_APPLIED",
                )
                fault("after_temp_apply")
                return sealer(capability)

            seen, registered, skipped, failures = (
                sync_d1_to_sqlite._run_private_export_sync(
                    store,
                    source_conn,
                    list(sync_d1_to_sqlite.DEFAULT_TABLES),
                    args,
                    export_digest=acquired.export_digest,
                    artifact_format=acquired.artifact_format,
                    authenticated_acquisition=acquired,
                    seal_authenticated_export=seal_after_temp_apply,
                )
            )
            if failures:
                raise LocalAuthorityError(
                    "governed D1 reconciliation failed: " + "; ".join(failures)
                )
            identity = _json_materialize(
                sync_d1_to_sqlite._authenticated_applied_mirror_identity_from_conn(
                    store._conn
                )
            )
            if type(identity) is not dict:
                raise LocalAuthorityError("signed D1 candidate identity is invalid")
            result = {
                "status": "SYNCED",
                "prior_applied_cursor": expected_applied_cursor,
                "source_change_seq": identity["source_change_seq"],
                "applied_change_seq": identity["applied_change_seq"],
                "audit_digest": identity["audit_digest"],
                "export_digest": identity["export_digest"],
                "issuer_key_id": identity["issuer_key_id"],
                "seen": seen,
                "registered": registered,
                "skipped": skipped,
            }
            if not seal_invoked:
                if (
                    prior_sync_identity is None
                    or identity != prior_sync_identity
                    or identity["source_change_seq"] != expected_applied_cursor
                ):
                    raise LocalAuthorityError(
                        "D1 sync completed without one signed candidate audit"
                    )
                store.close()
                store = None
                source_conn.close()
                source_conn = None
                _remove_d1_sync_candidate(candidate_path, allow_missing=False)
                _remove_d1_sync_journal(
                    journal_path, expected_digest=journal["record_digest"]
                )
                return result
            if identity["export_digest"] != acquired.export_digest:
                raise LocalAuthorityError(
                    "signed D1 candidate does not bind the acquired export"
                )
            journal = _advance_d1_sync_journal(
                journal_path,
                journal,
                phase="SIGNED_AUDIT",
                candidate_sync_identity=identity,
                sync_result=result,
                outer_result_digest=sha256_digest(result),
            )
            fault("after_signed_audit")

            sync_d1_to_sqlite._finalize_sync_policy(
                store,
                args,
                failures,
                source_mode="WRANGLER_REMOTE",
            )
            sync_d1_to_sqlite._freeze_authenticated_current_applied_mirror(store)
            final_identity = _json_materialize(
                sync_d1_to_sqlite._authenticated_applied_mirror_identity_from_conn(
                    store._conn
                )
            )
            if final_identity != identity:
                raise LocalAuthorityError(
                    "D1 sync candidate identity changed while freezing"
                )
            store.close()
            store = None
            source_conn.close()
            source_conn = None
            _require_no_sqlite_sidecars(candidate_path)
            _fsync_file(candidate_path)
            candidate_file_identity = _measure_d1_sync_file(candidate_path)
            if _read_candidate_sync_identity(candidate_path) != identity:
                raise LocalAuthorityError(
                    "D1 sync candidate changed after durable close"
                )
            journal = _advance_d1_sync_journal(
                journal_path,
                journal,
                phase="FILE_FSYNCED",
                candidate_file_identity=candidate_file_identity,
            )
            fault("after_file_fsync")

            try:
                if _measure_d1_sync_file(governed_db_path) != prior_file_identity:
                    raise LocalAuthorityError(
                        "governed D1 mirror changed before atomic replacement"
                    )
                _require_no_sqlite_sidecars(governed_db_path)
                _require_d1_sync_runtime_identity(
                    runtime_identity_observer,
                    source_sha=source_sha,
                    tool_digest=tool_digest,
                    policy_digest=policy_digest,
                )
                request_context.require_within_processing_deadline()
            except Exception:
                # Once a live-handoff guard has observed drift or lease expiry,
                # this invocation must not turn that rejection into a replace
                # by immediately entering generic recovery.
                handoff_guard_failed = True
                raise
            os.replace(candidate_path, governed_db_path)
            fault("after_replace_before_dir_fsync")
            _fsync_directory(governed_db_path.parent)
            if (
                _measure_d1_sync_file(governed_db_path)
                != candidate_file_identity
                or _read_candidate_sync_identity(governed_db_path) != identity
            ):
                raise LocalAuthorityError(
                    "governed D1 replacement postcondition differs"
                )
            journal = _advance_d1_sync_journal(
                journal_path,
                journal,
                phase="COMMITTED",
            )
            return result
        except Exception:
            if store is not None:
                store.close()
                store = None
            if source_conn is not None:
                source_conn.close()
                source_conn = None
            if handoff_guard_failed:
                raise
            recovered_after_error = _recover_d1_sync_journal(
                journal_path=journal_path,
                governed_db_path=governed_db_path,
                expected_applied_cursor=expected_applied_cursor,
                environment=environment,
                source_sha=source_sha,
                tool_digest=tool_digest,
                policy_digest=policy_digest,
                request_context=request_context,
                runtime_identity_observer=runtime_identity_observer,
                committed_event_verifier=committed_event_verifier,
            )
            if recovered_after_error is not None:
                return recovered_after_error
            raise
        finally:
            if store is not None:
                store.close()
            if source_conn is not None:
                source_conn.close()
            if temporary is not None:
                temporary.cleanup()


class D1SyncNow:
    """Sync only the configured D1 through authenticated acquisition/reconciliation."""

    operation = _D1_SYNC_OPERATION

    def __init__(
        self,
        *,
        environment: str,
        governed_db_path: str | Path,
        cloudflare_token_path: str | Path,
        node_executable_path: str | Path,
        wrangler_cli_path: str | Path,
        wrangler_cli_tree_path: str | Path,
        wrangler_config_path: str | Path,
        wrangler_lock_path: str | Path,
        custody: FileEd25519KeyCustody,
        expected_uid: int,
        source_sha: str,
        tool_digest: str,
        event_ledger: SQLiteAuthorityEventLedger,
        executor: Callable[..., Mapping[str, Any]] = _execute_governed_remote_sync,
    ) -> None:
        self.environment = trust_domain.require_environment(environment)
        self.governed_db_path = Path(governed_db_path).absolute()
        self.cloudflare_token_path = Path(cloudflare_token_path).absolute()
        self.node_executable_path = Path(node_executable_path).absolute()
        self.wrangler_cli_path = Path(wrangler_cli_path).absolute()
        self.wrangler_cli_tree_path = Path(wrangler_cli_tree_path).absolute()
        self.wrangler_config_path = Path(wrangler_config_path).absolute()
        self.wrangler_lock_path = Path(wrangler_lock_path).absolute()
        self.custody = custody
        self.expected_uid = expected_uid
        self.source_sha = source_sha
        self.tool_digest = tool_digest
        if type(event_ledger) is not SQLiteAuthorityEventLedger:
            raise LocalAuthorityError("D1 sync outer event ledger is invalid")
        self.event_ledger = event_ledger
        if not _is_sha256_digest(self.source_sha) or not _is_sha256_digest(
            self.tool_digest
        ):
            raise LocalAuthorityError("D1 sync runtime binding digest is invalid")
        self.executor = executor

    def __call__(
        self,
        _context: AuthorityRequestContext,
        payload: Mapping[str, Any],
        fds: Sequence[int],
    ) -> Mapping[str, Any]:
        values = _require_payload_fields(
            payload,
            fields={"expected_applied_cursor"},
            operation=self.operation,
        )
        expected = values["expected_applied_cursor"]
        if type(expected) is not int or expected < 0 or fds:
            raise LocalAuthorityError(
                "d1 sync requires one exact non-negative expected cursor"
            )
        try:
            info = self.governed_db_path.lstat()
        except OSError as exc:
            raise LocalAuthorityPending("governed D1 mirror is unavailable") from exc
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_uid != self.expected_uid
            or info.st_nlink != 1
            or stat.S_IMODE(info.st_mode) & 0o077
        ):
            raise LocalAuthorityError("governed D1 mirror ownership is unsafe")
        observed_tool_digest = _observe_d1_sync_tool_digest(
            {
                "node_executable_path": str(self.node_executable_path),
                "wrangler_cli_path": str(self.wrangler_cli_path),
                "wrangler_cli_tree_path": str(self.wrangler_cli_tree_path),
                "wrangler_config_path": str(self.wrangler_config_path),
                "wrangler_lock_path": str(self.wrangler_lock_path),
            }
        )
        if observed_tool_digest != self.tool_digest:
            raise LocalAuthorityError("D1 sync Wrangler tool binding changed")
        token = _read_protected_cloudflare_token(
            self.cloudflare_token_path,
            expected_uid=self.expected_uid,
        )
        result = self.executor(
            governed_db_path=self.governed_db_path,
            expected_applied_cursor=expected,
            credential_token=token,
            node_executable_path=self.node_executable_path,
            wrangler_cli_path=self.wrangler_cli_path,
            wrangler_config_path=self.wrangler_config_path,
            sealer=_D1SyncAuditSealer(
                self.custody, environment=self.environment
            ),
            environment=self.environment,
            source_sha=self.source_sha,
            tool_digest=self.tool_digest,
            request_context=_context,
            runtime_identity_observer=lambda: _observe_d1_sync_activation_identity(
                environment=self.environment,
                expected_uid=self.expected_uid,
            ),
            committed_event_verifier=self.event_ledger.has_exact_committed_event,
        )
        if type(result) is not dict or result.get("status") != "SYNCED":
            raise LocalAuthorityError("D1 sync executor returned invalid evidence")
        return result


class D1FreezeAuthorizeApplyCoverage:
    operation = "d1_sync:freeze_authorize_apply_coverage"

    def __init__(
        self,
        *,
        environment: str,
        governed_db_path: str | Path,
        coverage_socket_path: str | Path,
        coverage_uid: int,
    ) -> None:
        self.environment = environment
        self.governed_db_path = Path(governed_db_path).absolute()
        self.coverage_socket_path = Path(coverage_socket_path)
        self.coverage_uid = coverage_uid

    def __call__(
        self,
        _context: AuthorityRequestContext,
        payload: Mapping[str, Any],
        fds: Sequence[int],
    ) -> Mapping[str, Any]:
        selector = _require_payload_fields(
            payload, fields={"build_id", "datasets"}, operation=self.operation
        )
        if fds:
            raise LocalAuthorityError("d1 Coverage freeze accepts no caller descriptor")
        handle = sync_d1_to_sqlite.open_authenticated_applied_mirror(
            self.governed_db_path
        )

        def consume(
            _conn: sqlite3.Connection, identity: Mapping[str, object]
        ) -> Mapping[str, Any]:
            fd = _open_d1_owned_readonly_fd(self.governed_db_path)
            try:
                evidence = _owned_mirror_evidence(
                    fd,
                    environment=self.environment,
                    purpose="coverage_transition",
                    governed_db_path=self.governed_db_path,
                    sync_identity=identity,
                )
                request = {
                    "format": REQUEST_FORMAT,
                    "request_id": sha256_digest(
                        {
                            "operation": self.operation,
                            "evidence": evidence,
                            "selector": selector,
                        }
                    ),
                    "operation": CoverageTransitionAuthorize.operation,
                    "purpose": "coverage_v3_transition",
                    "payload": {
                        "owned_mirror_evidence": evidence,
                        "selector": selector,
                    },
                }
                return call_unix_authority(
                    self.coverage_socket_path,
                    request,
                    expected_server_uid=self.coverage_uid,
                    read_only_fd=fd,
                )
            finally:
                os.close(fd)

        signed = sync_d1_to_sqlite._consume_authenticated_applied_mirror(
            handle, consume
        )
        document = signed.get("signed_transition")
        if type(document) is not dict or signed.get("status") != "SIGNED":
            raise LocalAuthorityError(
                "Coverage authority did not return one signed transition"
            )
        applied = coverage_transition.apply_signed_coverage_transition(
            str(self.governed_db_path),
            document,
            expected_environment=self.environment,
        )
        return {
            **dict(applied),
            "signed_transition_digest": signed["signed_transition_digest"],
            "issuer_key_id": signed["issuer_key_id"],
        }


def _hash_open_file(fd: int) -> tuple[str, os.stat_result]:
    before = os.fstat(fd)
    if (
        not stat.S_ISREG(before.st_mode)
        or before.st_size <= 0
        or before.st_nlink != 1
    ):
        raise LocalAuthorityError("READY snapshot artifact is not a regular file")
    digest = hashlib.sha256()
    offset = 0
    while offset < before.st_size:
        chunk = os.pread(fd, min(1024 * 1024, before.st_size - offset), offset)
        if not chunk:
            raise LocalAuthorityError("READY snapshot changed while hashing")
        digest.update(chunk)
        offset += len(chunk)
    after = os.fstat(fd)
    identity = (
        before.st_dev,
        before.st_ino,
        before.st_size,
        before.st_mtime_ns,
        before.st_ctime_ns,
        before.st_nlink,
    )
    if identity != (
        after.st_dev,
        after.st_ino,
        after.st_size,
        after.st_mtime_ns,
        after.st_ctime_ns,
        after.st_nlink,
    ):
        raise LocalAuthorityError("READY snapshot changed while hashing")
    return "sha256:" + digest.hexdigest(), after


def _load_ready_snapshot(
    snapshot_root: Path,
    snapshot_id: str,
) -> tuple[dict[str, Any], dict[str, Any], str, tuple[int, int, int, int]]:
    from paper_runtime.snapshot import (
        RESEARCH_SNAPSHOT_MANIFEST_FORMAT,
        _artifact_stem,
        _immutable_data_snapshot_id,
        _research_manifest_digest,
        _research_manifest_id,
    )

    stem = _artifact_stem(snapshot_id)
    artifact = snapshot_root / f"{stem}.sqlite"
    manifest_path = snapshot_root / f"{stem}.manifest.json"
    if artifact.is_symlink() or manifest_path.is_symlink():
        raise LocalAuthorityError("READY snapshot paths cannot be symlinks")
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(artifact, flags)
    except OSError as exc:
        raise LocalAuthorityError("READY snapshot artifact cannot be opened") from exc
    try:
        artifact_digest, info = _hash_open_file(fd)
        if stat.S_IMODE(info.st_mode) & 0o222:
            raise LocalAuthorityError("READY snapshot artifact is writable")
        descriptor_path = Path(f"/dev/fd/{fd}")
        if not descriptor_path.exists():
            descriptor_path = Path(f"/proc/self/fd/{fd}")
        conn = sqlite3.connect(f"file:{descriptor_path}?mode=ro&immutable=1", uri=True)
        try:
            rows = conn.execute(
                "SELECT format,manifest_json FROM local_snapshot_manifests "
                "WHERE snapshot_id=?",
                (snapshot_id,),
            ).fetchall()
        finally:
            conn.close()
        if len(rows) != 1 or rows[0][0] != RESEARCH_SNAPSHOT_MANIFEST_FORMAT:
            raise LocalAuthorityError("READY embedded research manifest is missing")
        embedded = decode_strict_json(
            rows[0][1].encode("utf-8"), field="embedded research manifest"
        )
        try:
            manifest_file = read_protected_authority_file(
                manifest_path,
                expected_owner_uids={info.st_uid},
                allowed_modes={0o400, 0o440, 0o444},
                max_bytes=4 * 1024 * 1024,
            )
            external_raw = manifest_file.raw
        except ProtectedAuthorityFileError as exc:
            raise LocalAuthorityError(
                "READY external research manifest is missing"
            ) from exc
        external = decode_strict_json(external_raw, field="external research manifest")
        if external != embedded:
            raise LocalAuthorityError("READY embedded/external manifest mismatch")
        if (
            external.get("state") != "READY"
            or external.get("snapshot_id") != snapshot_id
            or _research_manifest_id(external) != snapshot_id
            or external.get("manifest_digest") != _research_manifest_digest(external)
            or _immutable_data_snapshot_id(descriptor_path) != snapshot_id
        ):
            raise LocalAuthorityError("READY research snapshot identity is invalid")
        ready_manifest = external.get("ready_manifest")
        if type(ready_manifest) is not dict:
            raise LocalAuthorityError("READY snapshot has no embedded ReadyManifest")
        readiness_attestation._validate_exact_four_ready_manifest(
            ready_manifest,
            expected_snapshot_id=snapshot_id,
        )
        final_digest, final_info = _hash_open_file(fd)
        if final_digest != artifact_digest:
            raise LocalAuthorityError("READY snapshot changed during validation")
        identity = (
            final_info.st_dev,
            final_info.st_ino,
            final_info.st_size,
            final_info.st_mtime_ns,
        )
        return external, ready_manifest, artifact_digest, identity
    finally:
        os.close(fd)


class ReadyPublishProfilePlanBound:
    """R5: independently reopen exact-four artifact/evidence and sign READY."""

    operation = "ready:publish_profile_plan_bound"

    def __init__(
        self,
        *,
        environment: str,
        snapshot_root: str | Path,
        custody: FileEd25519KeyCustody,
    ) -> None:
        self.environment = trust_domain.require_environment(environment)
        self.snapshot_root = Path(snapshot_root).resolve(strict=True)
        self.custody = custody

    def __call__(
        self,
        _context: AuthorityRequestContext,
        payload: Mapping[str, Any],
        fds: Sequence[int],
    ) -> Mapping[str, Any]:
        values = _require_payload_fields(
            payload,
            fields={"snapshot_id", "signed_projection_base64"},
            operation=self.operation,
        )
        if fds:
            raise LocalAuthorityError("READY publication reopens its governed store")
        snapshot_id = values["snapshot_id"]
        if type(snapshot_id) is not str:
            raise LocalAuthorityError("READY snapshot id is invalid")
        signed_projection = _decode_standard_base64(
            values["signed_projection_base64"],
            field="signed_projection_base64",
        )
        outer, manifest, artifact_digest, initial_identity = _load_ready_snapshot(
            self.snapshot_root,
            snapshot_id,
        )
        from research.ready_manifest import _verified_projection_evidence

        verified_projection = _verified_projection_evidence(
            signed_projection,
            list(manifest["dataset_ids"]),
            expected_environment=self.environment,
        )
        retained_rows = outer.get("profile_coverage_evidence")
        if type(retained_rows) is not dict or set(retained_rows) != set(
            verified_projection.rows
        ):
            raise LocalAuthorityError("READY retained projection membership mismatch")
        for dataset_id, signed_row in verified_projection.rows.items():
            retained = retained_rows.get(dataset_id)
            if type(retained) is not dict:
                raise LocalAuthorityError("READY retained projection row is missing")
            expected = dict(signed_row)
            expected["applied_sync_generation"] = expected["applied_cursor"]
            if any(retained.get(key) != value for key, value in expected.items()):
                raise LocalAuthorityError(
                    f"READY retained projection evidence mismatch: {dataset_id}"
                )
        if any(
            row.get("signed_projection_document_digest")
            != verified_projection.signed_document_digest
            or row.get("signed_projection_issuer_key_id")
            != verified_projection.issuer_key_id
            for row in retained_rows.values()
        ):
            raise LocalAuthorityError("READY signed projection identity mismatch")

        verified_at = datetime.now(UTC)
        expires_at = verified_at + timedelta(seconds=_READY_TTL_SECONDS)
        evidence_digest = readiness_attestation._digest(
            {"manifest": manifest, "immutable_db_digest": artifact_digest}
        )
        attestation_id = sha256_digest(
            {
                "snapshot_id": snapshot_id,
                "ready_manifest_digest": manifest["manifest_digest"],
                "immutable_db_digest": artifact_digest,
                "verified_at": verified_at.isoformat(),
                "nonce": str(uuid4()),
            }
        )
        document = {
            "format": readiness_attestation.READINESS_ATTESTATION_FORMAT,
            "environment": self.environment,
            "authority_instance_id": ready_authority_instance_id(self.environment),
            "attestation_id": attestation_id,
            "readiness_scope": "PILOT",
            "snapshot_id": snapshot_id,
            "profile_id": manifest["profile_id"],
            "profile_version": manifest["profile_version"],
            "profile_digest": manifest["profile_digest"],
            "plan_ids": manifest["plan_ids"],
            "plan_set_digest": manifest["plan_set_digest"],
            "dependency_closure_digest": manifest["dependency_closure_digest"],
            "universe_rule_digest": manifest["universe_rule_digest"],
            "resolved_universe_digest": manifest["resolved_universe_digest"],
            "dataset_ids": manifest["dataset_ids"],
            "ready_state": "READY",
            "ready_manifest_digest": manifest["manifest_digest"],
            "immutable_db_digest": artifact_digest,
            "coverage_policy_version": manifest["coverage_policy_version"],
            "coverage_policy_digest": manifest["coverage_policy_digest"],
            "coverage_proof_digest": manifest["coverage_proof_digest"],
            "governed_membership_digest": manifest["dataset_membership_digest"],
            "raw_proof_digest": manifest["raw_proof_digest"],
            "receipt_proof_digest": manifest["receipt_proof_digest"],
            "validation_proof_digest": manifest["validation_proof_digest"],
            "b0_quality_proof_digest": manifest["b0_proof_digest"],
            "b4_quality_proof_digest": manifest["b4_proof_digest"],
            "source_generation": manifest["source_generation"],
            "export_cursor": manifest["export_cursor"],
            "applied_cursor": manifest["applied_cursor"],
            "verified_at": verified_at.isoformat(),
            "expires_at": expires_at.isoformat(),
            "evidence_digest": evidence_digest,
            "key_id": self.custody.key_id,
            "issuer": "ReadyPublicationService/v3",
        }
        document["authority_resource_digest"] = derive_ready_authority_resource_digest(
            environment=self.environment,
            snapshot_id=snapshot_id,
            immutable_db_digest=artifact_digest,
            ready_manifest_digest=manifest["manifest_digest"],
            signed_projection_document_digest=(
                verified_projection.signed_document_digest
            ),
        )
        document["signed_projection_document_digest"] = (
            verified_projection.signed_document_digest
        )
        document["signature"] = self.custody.sign(
            readiness_attestation._canonical_bytes(document)
        )
        attestation_bytes = readiness_attestation._canonical_bytes(document)
        try:
            scoped_keys = load_scoped_ready_public_keys(
                expected_environment=self.environment
            )
        except LocalReadyRegistryError as exc:
            raise LocalAuthorityPending("READY public registry is unavailable") from exc
        scoped_key = scoped_keys.get(
            (
                self.environment,
                document["authority_instance_id"],
                self.custody.key_id,
            )
        )
        public = _custody_public_key(self.custody)
        if (
            scoped_key is None
            or scoped_key.public_bytes_raw() != public.public_bytes_raw()
        ):
            raise LocalAuthorityPending(
                "READY public registry does not activate the custody key"
            )
        _, _, final_digest, final_identity = _load_ready_snapshot(
            self.snapshot_root,
            snapshot_id,
        )
        if final_digest != artifact_digest or final_identity != initial_identity:
            raise LocalAuthorityError("READY snapshot changed before issuance")
        return {
            "status": "SIGNED",
            "snapshot_id": snapshot_id,
            "environment": self.environment,
            "authority_instance_id": document["authority_instance_id"],
            "authority_resource_digest": document["authority_resource_digest"],
            "attestation_id": attestation_id,
            "attestation_base64": base64.b64encode(attestation_bytes).decode("ascii"),
            "attestation_digest": "sha256:"
            + hashlib.sha256(attestation_bytes).hexdigest(),
            "ready_manifest_digest": manifest["manifest_digest"],
            "immutable_db_digest": artifact_digest,
            "signed_projection_document_digest": (
                verified_projection.signed_document_digest
            ),
            "issuer_key_id": self.custody.key_id,
        }


__all__ = [
    "OWNED_MIRROR_EVIDENCE_FORMAT",
    "CoverageTransitionAuthorize",
    "D1FreezeAndRenderOpsProjection",
    "D1FreezeAuthorizeApplyCoverage",
    "D1SyncNow",
    "OpsProjectionRenderAndSign",
    "ReadyPublishProfilePlanBound",
]
