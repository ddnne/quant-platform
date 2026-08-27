"""Root-owned READY to Controlled custody transition.

The READY authority proves an exact snapshot and signed Ops Projection, but it
does not grant the Controlled service a pathname capability.  This module is
the deliberately small bridge between those principals.  A privileged
installer re-verifies the READY response, pins the source files, copies them
into a root-owned content-addressed directory, and commits one immutable
manifest last.  Orphaned content files are harmless; only the manifest is an
activation input.
"""

from __future__ import annotations

import base64
import fcntl
import hashlib
import os
import sqlite3
import stat
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import quote

from execution.exact_four_codec import (
    _canonical_bytes,
    _strict_json_loads,
    canonical_authority_digest,
)
from execution.secure_authority_files_v2 import read_pinned_authority_file_v2
from execution.trader_webauthn_authority_v2 import (
    verify_ready_authority_response_v2,
)
from paper_runtime.snapshot_persist import (
    _READY_COPY_BUDGET_SECONDS,
    _READY_COPY_FREE_SPACE_MARGIN_BYTES,
)


CONTROLLED_READY_CUSTODY_FORMAT = "controlled-ready-custody-manifest/v2"
_MAX_READY_BYTES = 64 * 1024 * 1024 * 1024
_MAX_PROJECTION_BYTES = 16 * 1024 * 1024
_MAX_MANIFEST_BYTES = 8 * 1024 * 1024
_MAX_READY_RESPONSE_BYTES = 4 * 1024 * 1024
_MAX_EMBEDDED_READY_MANIFEST_BYTES = 4 * 1024 * 1024
_COPY_CHUNK_BYTES = 1024 * 1024


class ControlledReadyCustodyV2Error(RuntimeError):
    """The READY-to-Controlled custody transition failed closed."""


def _sha256_bytes(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def _is_sha256_digest(value: object) -> bool:
    return (
        type(value) is str
        and len(value) == 71
        and value.startswith("sha256:")
        and all(character in "0123456789abcdef" for character in value[7:])
    )


def _require_io_budget(deadline_monotonic: float) -> None:
    if time.monotonic() >= deadline_monotonic:
        raise ControlledReadyCustodyV2Error(
            "READY-to-Controlled custody I/O deadline exceeded"
        )


def _digest_fd(
    fd: int,
    *,
    expected_size: int,
    label: str,
    deadline_monotonic: float,
) -> str:
    digest = hashlib.sha256()
    offset = 0
    while offset < expected_size:
        _require_io_budget(deadline_monotonic)
        try:
            block = os.pread(fd, min(_COPY_CHUNK_BYTES, expected_size - offset), offset)
        except OSError as exc:
            raise ControlledReadyCustodyV2Error(f"{label} cannot be read") from exc
        if not block:
            raise ControlledReadyCustodyV2Error(
                f"{label} ended before its pinned size"
            )
        digest.update(block)
        offset += len(block)
    return "sha256:" + digest.hexdigest()


def _read_fd(
    fd: int,
    *,
    expected_size: int,
    label: str,
    deadline_monotonic: float,
) -> bytes:
    chunks: list[bytes] = []
    offset = 0
    while offset < expected_size:
        _require_io_budget(deadline_monotonic)
        try:
            block = os.pread(
                fd,
                min(_COPY_CHUNK_BYTES, expected_size - offset),
                offset,
            )
        except OSError as exc:
            raise ControlledReadyCustodyV2Error(f"{label} cannot be read") from exc
        if not block:
            raise ControlledReadyCustodyV2Error(
                f"{label} ended before its pinned size"
            )
        chunks.append(block)
        offset += len(block)
    return b"".join(chunks)


def _require_ready_response_bytes(value: object) -> bytes:
    if (
        type(value) is not bytes
        or not value
        or len(value) > _MAX_READY_RESPONSE_BYTES
    ):
        raise ControlledReadyCustodyV2Error(
            "READY authority response must be bounded exact non-empty bytes"
        )
    return value


def _require_copy_capacity(
    root_fd: int,
    artifacts: tuple[tuple[str, int], ...],
) -> None:
    if any(
        type(name) is not str or not name or type(size) is not int or size < 0
        for name, size in artifacts
    ):
        raise ControlledReadyCustodyV2Error(
            "Controlled custody copy capacity request is invalid"
        )
    required = _MAX_MANIFEST_BYTES
    for name, size in artifacts:
        try:
            os.stat(name, dir_fd=root_fd, follow_symlinks=False)
        except FileNotFoundError:
            required += size
        except OSError as exc:
            raise ControlledReadyCustodyV2Error(
                "Controlled custody destination cannot be inspected"
            ) from exc
    try:
        filesystem = os.fstatvfs(root_fd)
    except OSError as exc:
        raise ControlledReadyCustodyV2Error(
            "Controlled custody free space cannot be measured"
        ) from exc
    block_size = filesystem.f_frsize or filesystem.f_bsize
    available = filesystem.f_bavail * block_size
    if available < required + _READY_COPY_FREE_SPACE_MARGIN_BYTES:
        raise ControlledReadyCustodyV2Error(
            "Controlled custody destination has insufficient free space"
        )


def _identity(metadata: os.stat_result) -> tuple[int, ...]:
    return (
        metadata.st_dev,
        metadata.st_ino,
        metadata.st_size,
        metadata.st_mtime_ns,
        metadata.st_ctime_ns,
        metadata.st_uid,
        metadata.st_gid,
        stat.S_IMODE(metadata.st_mode),
        metadata.st_nlink,
    )


def _require_pinned_source(
    path: Path,
    *,
    expected_uid: int,
    maximum_bytes: int,
    label: str,
    parent_fd: int | None = None,
) -> tuple[int, os.stat_result]:
    if not path.is_absolute():
        raise ControlledReadyCustodyV2Error(f"{label} path must be absolute")
    try:
        parent = os.fstat(parent_fd) if parent_fd is not None else path.parent.lstat()
    except OSError as exc:
        raise ControlledReadyCustodyV2Error(
            f"{label} parent cannot be inspected"
        ) from exc
    if (
        not stat.S_ISDIR(parent.st_mode)
        or parent.st_uid != expected_uid
        or stat.S_IMODE(parent.st_mode) & 0o022
    ):
        raise ControlledReadyCustodyV2Error(
            f"{label} parent is not owned by the expected protected principal"
        )
    flags = (
        os.O_RDONLY
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_NONBLOCK", 0)
    )
    try:
        if parent_fd is not None:
            if path.name in {"", ".", ".."} or Path(path.name).name != path.name:
                raise ControlledReadyCustodyV2Error(
                    f"{label} filename is unsafe"
                )
            descriptor = os.open(path.name, flags, dir_fd=parent_fd)
        else:
            descriptor = os.open(path, flags)
    except OSError as exc:
        raise ControlledReadyCustodyV2Error(
            f"{label} cannot be opened without following links"
        ) from exc
    try:
        pinned = os.fstat(descriptor)
        lexical = (
            os.stat(path.name, dir_fd=parent_fd, follow_symlinks=False)
            if parent_fd is not None
            else path.lstat()
        )
        if (
            not stat.S_ISREG(pinned.st_mode)
            or pinned.st_uid != expected_uid
            or stat.S_IMODE(pinned.st_mode) not in {0o400, 0o440, 0o444}
            or pinned.st_nlink != 1
            or pinned.st_size <= 0
            or pinned.st_size > maximum_bytes
            or _identity(pinned) != _identity(lexical)
        ):
            raise ControlledReadyCustodyV2Error(
                f"{label} is not one protected immutable regular file"
            )
    except BaseException:
        os.close(descriptor)
        raise
    return descriptor, pinned


def _require_production_custody_root(path: Path, *, reader_gid: int) -> int:
    """Pin and return the validated production custody directory."""

    if not path.is_absolute() or type(reader_gid) is not int or reader_gid < 0:
        raise ControlledReadyCustodyV2Error(
            "production custody root policy is invalid"
        )
    flags = (
        os.O_RDONLY
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    descriptors: list[int] = []
    try:
        current = os.open(Path("/"), flags)
        descriptors.append(current)
        components = path.relative_to(Path("/")).parts
        if not components or any(item in {"", ".", ".."} for item in components):
            raise ControlledReadyCustodyV2Error(
                "production custody root path is not canonical"
            )
        for index, component in enumerate(components):
            current = os.open(component, flags, dir_fd=current)
            descriptors.append(current)
            metadata = os.fstat(current)
            final = index == len(components) - 1
            if (
                not stat.S_ISDIR(metadata.st_mode)
                or metadata.st_uid != 0
                or metadata.st_mode & 0o022
                or (
                    final
                    and (
                        metadata.st_gid != reader_gid
                        or stat.S_IMODE(metadata.st_mode) != 0o750
                    )
                )
            ):
                raise ControlledReadyCustodyV2Error(
                    "production custody directory chain is not root-owned and protected"
                )
        return descriptors.pop()
    except OSError as exc:
        raise ControlledReadyCustodyV2Error(
            "production custody directory chain cannot be pinned"
        ) from exc
    finally:
        for descriptor in reversed(descriptors):
            os.close(descriptor)


def _require_protected_source_root(path: Path, *, owner_uid: int) -> int:
    """Pin and return an authority-owned source directory."""

    if not path.is_absolute() or type(owner_uid) is not int or owner_uid < 0:
        raise ControlledReadyCustodyV2Error("protected source root is invalid")
    flags = (
        os.O_RDONLY
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    descriptors: list[int] = []
    try:
        current = os.open(Path("/"), flags)
        descriptors.append(current)
        components = path.relative_to(Path("/")).parts
        if not components or any(item in {"", ".", ".."} for item in components):
            raise ControlledReadyCustodyV2Error(
                "protected source root path is not canonical"
            )
        for index, component in enumerate(components):
            current = os.open(component, flags, dir_fd=current)
            descriptors.append(current)
            metadata = os.fstat(current)
            final = index == len(components) - 1
            if (
                not stat.S_ISDIR(metadata.st_mode)
                or metadata.st_uid not in {0, owner_uid}
                or metadata.st_mode & 0o022
                or (final and metadata.st_uid != owner_uid)
            ):
                raise ControlledReadyCustodyV2Error(
                    "protected source directory chain ownership or mode is invalid"
                )
        return descriptors.pop()
    except OSError as exc:
        raise ControlledReadyCustodyV2Error(
            "protected source directory chain cannot be pinned"
        ) from exc
    finally:
        for descriptor in reversed(descriptors):
            os.close(descriptor)


def read_root_owned_controlled_ready_input_v2(path: str | Path) -> bytes:
    """Read one bounded root-owned regular install input without blocking."""

    if os.geteuid() != 0:
        raise ControlledReadyCustodyV2Error(
            "root-owned custody input requires human-authorized root"
        )
    candidate = Path(path)
    deadline = time.monotonic() + _READY_COPY_BUDGET_SECONDS
    parent_fd = _require_protected_source_root(candidate.parent, owner_uid=0)
    descriptor = -1
    try:
        descriptor, metadata = _require_pinned_source(
            candidate,
            expected_uid=0,
            maximum_bytes=_MAX_READY_RESPONSE_BYTES,
            label="READY response",
            parent_fd=parent_fd,
        )
        raw = _read_fd(
            descriptor,
            expected_size=metadata.st_size,
            label="READY response",
            deadline_monotonic=deadline,
        )
        if _identity(os.fstat(descriptor)) != _identity(metadata):
            raise ControlledReadyCustodyV2Error(
                "READY response changed during pinned read"
            )
        return raw
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        os.close(parent_fd)


def _artifact_stem(snapshot_id: str) -> str:
    if (
        type(snapshot_id) is not str
        or not snapshot_id.startswith("sha256:")
        or len(snapshot_id) != 71
        or any(character not in "0123456789abcdef" for character in snapshot_id[7:])
    ):
        raise ControlledReadyCustodyV2Error("READY snapshot id is invalid")
    return "sha256_" + snapshot_id[7:]


def _attested_projection_digest(ready_response: bytes) -> str:
    response = _strict_json_loads(
        ready_response,
        label="READY authority response",
    )
    if _canonical_bytes(response) != ready_response:
        raise ControlledReadyCustodyV2Error(
            "READY authority response bytes are not canonical"
        )
    try:
        encoded = response["result"]["attestation_base64"]
        attestation = base64.b64decode(encoded, validate=True)
        if base64.b64encode(attestation).decode("ascii") != encoded:
            raise ValueError("non-canonical READY attestation base64")
        document = _strict_json_loads(
            attestation,
            label="READY attestation",
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ControlledReadyCustodyV2Error(
            "READY attestation cannot be independently decoded"
        ) from exc
    if _canonical_bytes(document) != attestation:
        raise ControlledReadyCustodyV2Error(
            "READY attestation bytes are not canonical"
        )
    digest = document.get("signed_projection_document_digest")
    if not _is_sha256_digest(digest):
        raise ControlledReadyCustodyV2Error(
            "READY attestation projection digest is invalid"
        )
    return digest


def _verify_embedded_ready_manifest(
    snapshot_fd: int,
    *,
    snapshot_id: str,
    expected_ready_manifest_digest: str,
    deadline_monotonic: float,
) -> None:
    _require_io_budget(deadline_monotonic)
    descriptor_path = Path(f"/dev/fd/{snapshot_fd}")
    if not descriptor_path.exists():
        descriptor_path = Path(f"/proc/self/fd/{snapshot_fd}")
    if not descriptor_path.exists():
        raise ControlledReadyCustodyV2Error(
            "descriptor-backed READY SQLite verification is unavailable"
        )
    uri = "file:" + quote(str(descriptor_path)) + "?mode=ro&immutable=1"
    try:
        connection = sqlite3.connect(uri, uri=True)
        try:
            connection.set_progress_handler(
                lambda: int(time.monotonic() >= deadline_monotonic),
                1_000,
            )
            metadata_rows = connection.execute(
                "SELECT format,typeof(manifest_json),"
                "length(CAST(manifest_json AS BLOB)) "
                "FROM local_snapshot_manifests "
                "WHERE snapshot_id=?",
                (snapshot_id,),
            ).fetchall()
            if (
                len(metadata_rows) != 1
                or metadata_rows[0][0] != "research-snapshot-manifest/v2"
                or metadata_rows[0][1] != "text"
                or type(metadata_rows[0][2]) is not int
                or not 0 < metadata_rows[0][2]
                <= _MAX_EMBEDDED_READY_MANIFEST_BYTES
            ):
                raise ControlledReadyCustodyV2Error(
                    "READY embedded manifest metadata is invalid"
                )
            rows = connection.execute(
                "SELECT manifest_json FROM local_snapshot_manifests "
                "WHERE snapshot_id=?",
                (snapshot_id,),
            ).fetchall()
            _require_io_budget(deadline_monotonic)
        finally:
            connection.close()
    except ControlledReadyCustodyV2Error:
        raise
    except sqlite3.Error as exc:
        raise ControlledReadyCustodyV2Error(
            "READY embedded manifest cannot be independently reopened"
        ) from exc
    if len(rows) != 1 or type(rows[0][0]) is not str:
        raise ControlledReadyCustodyV2Error("READY embedded manifest is missing")
    manifest_text = rows[0][0]
    try:
        embedded = _strict_json_loads(
            manifest_text.encode("utf-8"),
            label="READY embedded research manifest",
        )
    except Exception as exc:
        raise ControlledReadyCustodyV2Error(
            "READY embedded manifest is not canonical JSON"
        ) from exc
    if _canonical_bytes(embedded) != manifest_text.encode("utf-8"):
        raise ControlledReadyCustodyV2Error(
            "READY embedded manifest bytes are not canonical"
        )
    ready_manifest = embedded.get("ready_manifest")
    if (
        embedded.get("state") != "READY"
        or embedded.get("snapshot_id") != snapshot_id
        or type(ready_manifest) is not dict
        or ready_manifest.get("snapshot_id") != snapshot_id
        or ready_manifest.get("manifest_digest")
        != expected_ready_manifest_digest
    ):
        raise ControlledReadyCustodyV2Error(
            "READY embedded manifest does not bind the signed authority response"
        )


def _copy_fd_to_create_only_file(
    source_fd: int,
    source: os.stat_result,
    *,
    root_fd: int,
    final_name: str,
    expected_digest: str,
    owner_uid: int,
    reader_gid: int,
    deadline_monotonic: float,
) -> None:
    temporary_name = f".{final_name}.partial"
    _discard_stale_partial(
        root_fd=root_fd,
        name=temporary_name,
        owner_uid=owner_uid,
    )
    flags = (
        os.O_RDWR
        | os.O_CREAT
        | os.O_EXCL
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    output = os.open(temporary_name, flags, 0o600, dir_fd=root_fd)
    try:
        os.fchown(output, owner_uid, reader_gid)
        offset = 0
        while offset < source.st_size:
            _require_io_budget(deadline_monotonic)
            block = os.pread(
                source_fd,
                min(_COPY_CHUNK_BYTES, source.st_size - offset),
                offset,
            )
            if not block:
                raise ControlledReadyCustodyV2Error(
                    "pinned custody source ended during copy"
                )
            written = 0
            while written < len(block):
                _require_io_budget(deadline_monotonic)
                count = os.write(output, block[written:])
                if count <= 0:
                    raise ControlledReadyCustodyV2Error(
                        "custody copy made no write progress"
                    )
                written += count
            offset += len(block)
        os.fchmod(output, 0o440)
        os.fsync(output)
        copied = os.fstat(output)
        if (
            copied.st_size != source.st_size
            or copied.st_uid != owner_uid
            or copied.st_gid != reader_gid
            or stat.S_IMODE(copied.st_mode) != 0o440
            or _digest_fd(
                output,
                expected_size=copied.st_size,
                label="custody copy",
                deadline_monotonic=deadline_monotonic,
            )
            != expected_digest
        ):
            raise ControlledReadyCustodyV2Error(
                "root-owned custody copy failed exact verification"
            )
    except BaseException:
        os.close(output)
        try:
            os.unlink(temporary_name, dir_fd=root_fd)
        except FileNotFoundError:
            pass
        raise
    os.close(output)
    try:
        os.link(
            temporary_name,
            final_name,
            src_dir_fd=root_fd,
            dst_dir_fd=root_fd,
            follow_symlinks=False,
        )
    except FileExistsError:
        # A retry may observe the exact content-addressed file committed by an
        # earlier attempt.  Any other identity fails below.
        pass
    finally:
        os.unlink(temporary_name, dir_fd=root_fd)
    _verify_installed_file(
        root_fd=root_fd,
        name=final_name,
        expected_digest=expected_digest,
        expected_size=source.st_size,
        owner_uid=owner_uid,
        reader_gid=reader_gid,
        deadline_monotonic=deadline_monotonic,
    )
    # The content links must be durable before a later manifest can become a
    # durable commit marker after a crash or abrupt restart.
    os.fsync(root_fd)


def _write_create_only_bytes(
    value: bytes,
    *,
    root_fd: int,
    final_name: str,
    owner_uid: int,
    reader_gid: int,
    deadline_monotonic: float,
) -> None:
    temporary_name = f".{final_name}.partial"
    _discard_stale_partial(
        root_fd=root_fd,
        name=temporary_name,
        owner_uid=owner_uid,
    )
    flags = (
        os.O_WRONLY
        | os.O_CREAT
        | os.O_EXCL
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    output = os.open(temporary_name, flags, 0o600, dir_fd=root_fd)
    try:
        os.fchown(output, owner_uid, reader_gid)
        offset = 0
        while offset < len(value):
            _require_io_budget(deadline_monotonic)
            count = os.write(output, value[offset:])
            if count <= 0:
                raise ControlledReadyCustodyV2Error(
                    "custody manifest write made no progress"
                )
            offset += count
        os.fchmod(output, 0o440)
        os.fsync(output)
    except BaseException:
        os.close(output)
        try:
            os.unlink(temporary_name, dir_fd=root_fd)
        except FileNotFoundError:
            pass
        raise
    os.close(output)
    try:
        os.link(
            temporary_name,
            final_name,
            src_dir_fd=root_fd,
            dst_dir_fd=root_fd,
            follow_symlinks=False,
        )
    except FileExistsError:
        pass
    finally:
        os.unlink(temporary_name, dir_fd=root_fd)
    _verify_installed_file(
        root_fd=root_fd,
        name=final_name,
        expected_digest=_sha256_bytes(value),
        expected_size=len(value),
        owner_uid=owner_uid,
        reader_gid=reader_gid,
        deadline_monotonic=deadline_monotonic,
    )
    os.fsync(root_fd)


def _discard_stale_partial(*, root_fd: int, name: str, owner_uid: int) -> None:
    """Remove only a prior crash residue while the custody root is locked.

    Content is committed through a hard link followed by unlinking the
    deterministic partial name.  A process crash in that narrow window leaves
    the final file with two links.  The next installer can safely remove the
    protected, installer-owned partial and re-verify the create-only final.
    Special files, links owned by another principal, and unexpected modes fail
    closed instead of being deleted by a privileged process.
    """

    try:
        metadata = os.stat(name, dir_fd=root_fd, follow_symlinks=False)
    except FileNotFoundError:
        return
    except OSError as exc:
        raise ControlledReadyCustodyV2Error(
            "custody partial residue cannot be inspected"
        ) from exc
    if (
        not stat.S_ISREG(metadata.st_mode)
        or metadata.st_uid != owner_uid
        or stat.S_IMODE(metadata.st_mode) not in {0o600, 0o440}
        or metadata.st_nlink not in {1, 2}
    ):
        raise ControlledReadyCustodyV2Error(
            "custody partial residue is not a recoverable installer file"
        )
    try:
        os.unlink(name, dir_fd=root_fd)
    except OSError as exc:
        raise ControlledReadyCustodyV2Error(
            "custody partial residue cannot be removed"
        ) from exc


def _verify_installed_file(
    *,
    root_fd: int,
    name: str,
    expected_digest: str,
    expected_size: int,
    owner_uid: int,
    reader_gid: int,
    deadline_monotonic: float,
) -> None:
    flags = (
        os.O_RDONLY
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    try:
        descriptor = os.open(name, flags, dir_fd=root_fd)
    except OSError as exc:
        raise ControlledReadyCustodyV2Error(
            "committed custody file cannot be pinned"
        ) from exc
    try:
        observed = os.fstat(descriptor)
        lexical = os.stat(name, dir_fd=root_fd, follow_symlinks=False)
        digest = _digest_fd(
            descriptor,
            expected_size=observed.st_size,
            label="committed custody file",
            deadline_monotonic=deadline_monotonic,
        )
        final = os.fstat(descriptor)
        final_lexical = os.stat(name, dir_fd=root_fd, follow_symlinks=False)
        if (
            not stat.S_ISREG(observed.st_mode)
            or observed.st_uid != owner_uid
            or observed.st_gid != reader_gid
            or stat.S_IMODE(observed.st_mode) != 0o440
            or observed.st_nlink != 1
            or observed.st_size != expected_size
            or _identity(observed) != _identity(lexical)
            or digest != expected_digest
            or _identity(final) != _identity(observed)
            or _identity(final_lexical) != _identity(observed)
        ):
            raise ControlledReadyCustodyV2Error(
                "committed custody file identity or content differs"
            )
    finally:
        os.close(descriptor)


@dataclass(frozen=True, slots=True)
class InstalledControlledReadyCustodyV2:
    manifest_path: Path
    manifest_digest: str
    snapshot_path: Path
    projection_path: Path
    snapshot_digest: str
    projection_digest: str
    snapshot_id: str
    ready_authority_resource_digest: str
    controlled_reader_gid: int


def _install_controlled_ready_custody_v2(
    *,
    environment: str,
    ready_response: bytes,
    ready_snapshot_root: Path,
    signed_projection_path: Path,
    controlled_root: Path,
    expected_ready_uid: int,
    expected_projection_uid: int,
    controlled_owner_uid: int,
    controlled_reader_gid: int,
    ready_snapshot_root_fd: int | None = None,
    signed_projection_parent_fd: int | None = None,
    controlled_root_fd: int | None = None,
) -> InstalledControlledReadyCustodyV2:
    # This private helper exists only for adversarial tests.  Python name
    # privacy is not an authority boundary; the public root check and the
    # root-owned activation/custody verification are the production boundary.
    ready_response = _require_ready_response_bytes(ready_response)
    deadline = time.monotonic() + _READY_COPY_BUDGET_SECONDS
    if environment not in {"staging", "production"}:
        raise ControlledReadyCustodyV2Error("custody environment is invalid")
    for value, label in (
        (expected_ready_uid, "READY uid"),
        (expected_projection_uid, "projection uid"),
    ):
        if type(value) is not int or value <= 0:
            raise ControlledReadyCustodyV2Error(f"{label} is invalid")
    if type(controlled_owner_uid) is not int or controlled_owner_uid < 0:
        raise ControlledReadyCustodyV2Error("Controlled owner uid is invalid")
    if type(controlled_reader_gid) is not int or controlled_reader_gid <= 0:
        raise ControlledReadyCustodyV2Error(
            "Controlled reader group must not be the root group"
        )

    try:
        evidence = verify_ready_authority_response_v2(
            ready_response,
            expected_environment=environment,
        )
    except Exception as exc:
        raise ControlledReadyCustodyV2Error(
            "READY authority response does not verify"
        ) from exc
    subject = evidence.subject
    stem = _artifact_stem(subject.snapshot_id)
    snapshot_path = ready_snapshot_root / f"{stem}.sqlite"
    snapshot_fd, snapshot_metadata = _require_pinned_source(
        snapshot_path,
        expected_uid=expected_ready_uid,
        maximum_bytes=_MAX_READY_BYTES,
        label="READY snapshot",
        parent_fd=ready_snapshot_root_fd,
    )
    projection_fd = -1
    root_fd = -1
    try:
        snapshot_digest = _digest_fd(
            snapshot_fd,
            expected_size=snapshot_metadata.st_size,
            label="READY snapshot",
            deadline_monotonic=deadline,
        )
        if snapshot_digest != subject.immutable_snapshot_digest:
            raise ControlledReadyCustodyV2Error(
                "READY snapshot digest differs from the signed authority response"
            )
        _verify_embedded_ready_manifest(
            snapshot_fd,
            snapshot_id=subject.snapshot_id,
            expected_ready_manifest_digest=subject.ready_manifest_digest,
            deadline_monotonic=deadline,
        )
        projection_fd, projection_metadata = _require_pinned_source(
            signed_projection_path,
            expected_uid=expected_projection_uid,
            maximum_bytes=_MAX_PROJECTION_BYTES,
            label="signed projection",
            parent_fd=signed_projection_parent_fd,
        )
        projection_digest = _digest_fd(
            projection_fd,
            expected_size=projection_metadata.st_size,
            label="signed projection",
            deadline_monotonic=deadline,
        )
        if projection_digest != _attested_projection_digest(ready_response):
            raise ControlledReadyCustodyV2Error(
                "signed projection bytes differ from READY authority evidence"
            )
        # Re-run the projection verifier at the custody boundary; a digest of
        # caller-supplied bytes alone is not evidence of an authorized source.
        from research.ready_manifest import (
            _verified_projection_evidence,
            load_exact_four_pilot_ready_binding,
        )

        binding = load_exact_four_pilot_ready_binding()
        projection_raw = _read_fd(
            projection_fd,
            expected_size=projection_metadata.st_size,
            label="signed projection",
            deadline_monotonic=deadline,
        )
        verified_projection = _verified_projection_evidence(
            projection_raw,
            list(binding.required_datasets),
            expected_environment=environment,
        )
        _require_io_budget(deadline)
        if verified_projection.signed_document_digest != projection_digest:
            raise ControlledReadyCustodyV2Error(
                "signed projection verifier digest differs from pinned bytes"
            )

        if not controlled_root.is_absolute():
            raise ControlledReadyCustodyV2Error(
                "Controlled custody root must be absolute"
            )
        root_flags = (
            os.O_RDONLY
            | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_DIRECTORY", 0)
            | getattr(os, "O_NOFOLLOW", 0)
        )
        try:
            root_fd = (
                os.dup(controlled_root_fd)
                if controlled_root_fd is not None
                else os.open(controlled_root, root_flags)
            )
        except OSError as exc:
            raise ControlledReadyCustodyV2Error(
                "Controlled custody root cannot be pinned"
            ) from exc
        try:
            fcntl.flock(root_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise ControlledReadyCustodyV2Error(
                "another Controlled custody installer holds the root lock"
            ) from exc
        root_metadata = os.fstat(root_fd)
        lexical_root = controlled_root.lstat()
        if (
            not stat.S_ISDIR(root_metadata.st_mode)
            or root_metadata.st_uid != controlled_owner_uid
            or root_metadata.st_gid != controlled_reader_gid
            or stat.S_IMODE(root_metadata.st_mode) != 0o750
            or _identity(root_metadata) != _identity(lexical_root)
        ):
            raise ControlledReadyCustodyV2Error(
                "Controlled custody root is not the pinned owner/group mode-0750 directory"
            )

        snapshot_name = f"snapshot-{snapshot_digest[7:]}.sqlite3"
        projection_name = f"projection-{projection_digest[7:]}.json"
        _require_copy_capacity(
            root_fd,
            (
                (snapshot_name, snapshot_metadata.st_size),
                (projection_name, projection_metadata.st_size),
            ),
        )
        _copy_fd_to_create_only_file(
            snapshot_fd,
            snapshot_metadata,
            root_fd=root_fd,
            final_name=snapshot_name,
            expected_digest=snapshot_digest,
            owner_uid=controlled_owner_uid,
            reader_gid=controlled_reader_gid,
            deadline_monotonic=deadline,
        )
        if _identity(os.fstat(snapshot_fd)) != _identity(snapshot_metadata):
            raise ControlledReadyCustodyV2Error(
                "READY snapshot changed during custody copy"
            )
        _copy_fd_to_create_only_file(
            projection_fd,
            projection_metadata,
            root_fd=root_fd,
            final_name=projection_name,
            expected_digest=projection_digest,
            owner_uid=controlled_owner_uid,
            reader_gid=controlled_reader_gid,
            deadline_monotonic=deadline,
        )
        if _identity(os.fstat(projection_fd)) != _identity(projection_metadata):
            raise ControlledReadyCustodyV2Error(
                "signed projection changed during custody copy"
            )

        body: dict[str, Any] = {
            "format": CONTROLLED_READY_CUSTODY_FORMAT,
            "environment": environment,
            "publication_scope": "PILOT",
            "source_ready_uid": expected_ready_uid,
            "source_projection_uid": expected_projection_uid,
            "controlled_owner_uid": controlled_owner_uid,
            "controlled_reader_gid": controlled_reader_gid,
            "ready_authority_response_base64": base64.b64encode(
                ready_response
            ).decode("ascii"),
            "ready_authority_response_digest": evidence.response_digest,
            "ready_authority_instance_id": subject.ready_authority_instance_id,
            "ready_authority_resource_digest": (
                subject.ready_authority_resource_digest
            ),
            "readiness_attestation_id": subject.readiness_attestation_id,
            "snapshot_id": subject.snapshot_id,
            "ready_manifest_digest": subject.ready_manifest_digest,
            "immutable_snapshot_file": snapshot_name,
            "immutable_snapshot_digest": snapshot_digest,
            "signed_projection_file": projection_name,
            "signed_projection_document_digest": projection_digest,
            "exact_four_binding_digest": subject.exact_four_binding_digest,
            "controlled_pilot_policy_digest": (
                subject.controlled_pilot_policy_digest
            ),
            "automatic_promotion": False,
            "mass_research_enabled": False,
            "live_trading_enabled": False,
        }
        manifest_digest = canonical_authority_digest(body)
        document = {**body, "manifest_digest": manifest_digest}
        manifest_bytes = _canonical_bytes(document)
        if len(manifest_bytes) > _MAX_MANIFEST_BYTES:
            raise ControlledReadyCustodyV2Error(
                "Controlled custody manifest exceeds its activation bound"
            )
        manifest_name = f"custody-{manifest_digest[7:]}.json"
        _write_create_only_bytes(
            manifest_bytes,
            root_fd=root_fd,
            final_name=manifest_name,
            owner_uid=controlled_owner_uid,
            reader_gid=controlled_reader_gid,
            deadline_monotonic=deadline,
        )
        final_root = os.fstat(root_fd)
        final_lexical_root = controlled_root.lstat()
        if (
            final_root.st_uid != controlled_owner_uid
            or final_root.st_gid != controlled_reader_gid
            or stat.S_IMODE(final_root.st_mode) != 0o750
            or _identity(final_root) != _identity(final_lexical_root)
        ):
            raise ControlledReadyCustodyV2Error(
                "Controlled custody root identity drifted during install"
            )
        return InstalledControlledReadyCustodyV2(
            manifest_path=controlled_root / manifest_name,
            manifest_digest=manifest_digest,
            snapshot_path=controlled_root / snapshot_name,
            projection_path=controlled_root / projection_name,
            snapshot_digest=snapshot_digest,
            projection_digest=projection_digest,
            snapshot_id=subject.snapshot_id,
            ready_authority_resource_digest=subject.ready_authority_resource_digest,
            controlled_reader_gid=controlled_reader_gid,
        )
    finally:
        if root_fd >= 0:
            os.close(root_fd)
        if projection_fd >= 0:
            os.close(projection_fd)
        os.close(snapshot_fd)


def install_controlled_ready_custody_v2(
    *,
    environment: str,
    ready_response: bytes,
    ready_snapshot_root: str | Path,
    signed_projection_path: str | Path,
    controlled_root: str | Path,
    expected_ready_uid: int,
    expected_projection_uid: int,
    controlled_reader_gid: int,
) -> InstalledControlledReadyCustodyV2:
    """Install one verified bundle; production ownership is always root.

    Directory/user/group provisioning remains an explicit administrator
    ceremony.  This function never creates or relaxes that boundary.
    """

    if os.geteuid() != 0:
        raise ControlledReadyCustodyV2Error(
            "READY-to-Controlled custody install requires human-authorized root"
        )
    ready_response = _require_ready_response_bytes(ready_response)
    if type(controlled_reader_gid) is not int or controlled_reader_gid <= 0:
        raise ControlledReadyCustodyV2Error(
            "Controlled reader group must be one dedicated non-root group"
        )
    controlled_path = Path(controlled_root)
    ready_path = Path(ready_snapshot_root)
    projection_path = Path(signed_projection_path)
    controlled_fd = -1
    ready_fd = -1
    projection_parent_fd = -1
    try:
        controlled_fd = _require_production_custody_root(
            controlled_path,
            reader_gid=controlled_reader_gid,
        )
        ready_fd = _require_protected_source_root(
            ready_path,
            owner_uid=expected_ready_uid,
        )
        projection_parent_fd = _require_protected_source_root(
            projection_path.parent,
            owner_uid=expected_projection_uid,
        )
        return _install_controlled_ready_custody_v2(
            environment=environment,
            ready_response=ready_response,
            ready_snapshot_root=ready_path,
            signed_projection_path=projection_path,
            controlled_root=controlled_path,
            expected_ready_uid=expected_ready_uid,
            expected_projection_uid=expected_projection_uid,
            controlled_owner_uid=0,
            controlled_reader_gid=controlled_reader_gid,
            ready_snapshot_root_fd=ready_fd,
            signed_projection_parent_fd=projection_parent_fd,
            controlled_root_fd=controlled_fd,
        )
    finally:
        for descriptor in (projection_parent_fd, ready_fd, controlled_fd):
            if descriptor >= 0:
                os.close(descriptor)


def load_controlled_ready_custody_v2(
    path: Path,
    *,
    expected_environment: str,
    expected_owner_uid: int = 0,
    expected_reader_gid: int | None = None,
) -> InstalledControlledReadyCustodyV2:
    """Reopen and verify the exact manifest and both installed resources."""

    deadline = time.monotonic() + _READY_COPY_BUDGET_SECONDS
    if (
        not isinstance(path, Path)
        or not path.is_absolute()
        or expected_environment not in {"staging", "production"}
        or type(expected_owner_uid) is not int
        or expected_owner_uid < 0
        or (
            expected_reader_gid is not None
            and (
                type(expected_reader_gid) is not int
                or expected_reader_gid <= 0
            )
        )
    ):
        raise ControlledReadyCustodyV2Error(
            "Controlled custody loader policy is invalid"
        )

    try:
        raw = read_pinned_authority_file_v2(
            path,
            chain_root=Path("/"),
            directory_owner_uids={0, expected_owner_uid},
            expected_file_uid=expected_owner_uid,
            allowed_file_modes=frozenset({0o440}),
            max_bytes=_MAX_MANIFEST_BYTES,
        )
    except OSError as exc:
        raise ControlledReadyCustodyV2Error(
            "Controlled custody manifest is unavailable"
        ) from exc
    document = _strict_json_loads(raw, label="Controlled READY custody manifest")
    required = {
        "format",
        "environment",
        "publication_scope",
        "source_ready_uid",
        "source_projection_uid",
        "controlled_owner_uid",
        "controlled_reader_gid",
        "ready_authority_response_base64",
        "ready_authority_response_digest",
        "ready_authority_instance_id",
        "ready_authority_resource_digest",
        "readiness_attestation_id",
        "snapshot_id",
        "ready_manifest_digest",
        "immutable_snapshot_file",
        "immutable_snapshot_digest",
        "signed_projection_file",
        "signed_projection_document_digest",
        "exact_four_binding_digest",
        "controlled_pilot_policy_digest",
        "automatic_promotion",
        "mass_research_enabled",
        "live_trading_enabled",
        "manifest_digest",
    }
    if (
        set(document) != required
        or document.get("format") != CONTROLLED_READY_CUSTODY_FORMAT
        or document.get("environment") != expected_environment
        or document.get("publication_scope") != "PILOT"
        or type(document.get("controlled_owner_uid")) is not int
        or document.get("controlled_owner_uid") != expected_owner_uid
        or type(document.get("source_ready_uid")) is not int
        or int(document["source_ready_uid"]) <= 0
        or type(document.get("source_projection_uid")) is not int
        or int(document["source_projection_uid"]) <= 0
        or type(document.get("controlled_reader_gid")) is not int
        or int(document["controlled_reader_gid"]) <= 0
        or (
            expected_reader_gid is not None
            and document.get("controlled_reader_gid") != expected_reader_gid
        )
        or document.get("automatic_promotion") is not False
        or document.get("mass_research_enabled") is not False
        or document.get("live_trading_enabled") is not False
    ):
        raise ControlledReadyCustodyV2Error(
            "Controlled custody manifest shape or policy is invalid"
        )
    for field in (
        "ready_authority_response_digest",
        "ready_authority_resource_digest",
        "readiness_attestation_id",
        "snapshot_id",
        "ready_manifest_digest",
        "immutable_snapshot_digest",
        "signed_projection_document_digest",
        "exact_four_binding_digest",
        "controlled_pilot_policy_digest",
        "manifest_digest",
    ):
        if not _is_sha256_digest(document.get(field)):
            raise ControlledReadyCustodyV2Error(
                f"Controlled custody {field} is not a SHA-256 digest"
            )
    if _canonical_bytes(document) != raw:
        raise ControlledReadyCustodyV2Error(
            "Controlled custody manifest bytes are not canonical"
        )
    body = dict(document)
    declared_digest = body.pop("manifest_digest")
    if declared_digest != canonical_authority_digest(body):
        raise ControlledReadyCustodyV2Error(
            "Controlled custody manifest digest does not verify"
        )
    try:
        ready_response = base64.b64decode(
            document["ready_authority_response_base64"], validate=True
        )
        ready_response = _require_ready_response_bytes(ready_response)
        if (
            base64.b64encode(ready_response).decode("ascii")
            != document["ready_authority_response_base64"]
        ):
            raise ValueError("non-canonical READY response base64")
        evidence = verify_ready_authority_response_v2(
            ready_response,
            expected_environment=expected_environment,
        )
    except Exception as exc:
        raise ControlledReadyCustodyV2Error(
            "Controlled custody READY evidence does not verify"
        ) from exc
    subject = evidence.subject
    if (
        evidence.response_digest != document["ready_authority_response_digest"]
        or subject.ready_authority_instance_id
        != document["ready_authority_instance_id"]
        or subject.ready_authority_resource_digest
        != document["ready_authority_resource_digest"]
        or subject.readiness_attestation_id
        != document["readiness_attestation_id"]
        or subject.snapshot_id != document["snapshot_id"]
        or subject.ready_manifest_digest != document["ready_manifest_digest"]
        or subject.immutable_snapshot_digest
        != document["immutable_snapshot_digest"]
        or subject.exact_four_binding_digest
        != document["exact_four_binding_digest"]
        or subject.controlled_pilot_policy_digest
        != document["controlled_pilot_policy_digest"]
        or _attested_projection_digest(ready_response)
        != document["signed_projection_document_digest"]
    ):
        raise ControlledReadyCustodyV2Error(
            "Controlled custody fields differ from signed READY evidence"
        )
    reader_gid = int(document["controlled_reader_gid"])
    snapshot_name = document["immutable_snapshot_file"]
    projection_name = document["signed_projection_file"]
    for name, label in (
        (snapshot_name, "snapshot"),
        (projection_name, "projection"),
    ):
        if (
            type(name) is not str
            or not name
            or Path(name).name != name
            or name in {".", ".."}
        ):
            raise ControlledReadyCustodyV2Error(
                f"Controlled custody {label} filename is unsafe"
            )
    if (
        path.name != f"custody-{declared_digest[7:]}.json"
        or snapshot_name
        != f"snapshot-{document['immutable_snapshot_digest'][7:]}.sqlite3"
        or projection_name
        != f"projection-{document['signed_projection_document_digest'][7:]}.json"
    ):
        raise ControlledReadyCustodyV2Error(
            "Controlled custody filenames are not content-addressed"
        )
    root = path.parent
    root_flags = (
        os.O_RDONLY
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    try:
        root_fd = os.open(root, root_flags)
    except OSError as exc:
        raise ControlledReadyCustodyV2Error(
            "Controlled custody root cannot be pinned"
        ) from exc
    try:
        root_metadata = os.fstat(root_fd)
        lexical_root = root.lstat()
        if (
            root_metadata.st_uid != expected_owner_uid
            or root_metadata.st_gid != reader_gid
            or stat.S_IMODE(root_metadata.st_mode) != 0o750
            or _identity(root_metadata) != _identity(lexical_root)
        ):
            raise ControlledReadyCustodyV2Error(
                "Controlled custody root identity drifted"
            )
        _verify_installed_file(
            root_fd=root_fd,
            name=path.name,
            expected_digest=_sha256_bytes(raw),
            expected_size=len(raw),
            owner_uid=expected_owner_uid,
            reader_gid=reader_gid,
            deadline_monotonic=deadline,
        )
        snapshot_fd, snapshot_metadata = _require_pinned_source(
            root / snapshot_name,
            expected_uid=expected_owner_uid,
            maximum_bytes=_MAX_READY_BYTES,
            label="Controlled custody snapshot",
            parent_fd=root_fd,
        )
        try:
            _verify_installed_file(
                root_fd=root_fd,
                name=snapshot_name,
                expected_digest=document["immutable_snapshot_digest"],
                expected_size=snapshot_metadata.st_size,
                owner_uid=expected_owner_uid,
                reader_gid=reader_gid,
                deadline_monotonic=deadline,
            )
            _verify_embedded_ready_manifest(
                snapshot_fd,
                snapshot_id=document["snapshot_id"],
                expected_ready_manifest_digest=document["ready_manifest_digest"],
                deadline_monotonic=deadline,
            )
            if _identity(os.fstat(snapshot_fd)) != _identity(snapshot_metadata):
                raise ControlledReadyCustodyV2Error(
                    "Controlled custody snapshot changed during READY replay"
                )
        finally:
            os.close(snapshot_fd)

        projection_fd, projection_metadata = _require_pinned_source(
            root / projection_name,
            expected_uid=expected_owner_uid,
            maximum_bytes=_MAX_PROJECTION_BYTES,
            label="Controlled custody signed projection",
            parent_fd=root_fd,
        )
        try:
            _verify_installed_file(
                root_fd=root_fd,
                name=projection_name,
                expected_digest=document["signed_projection_document_digest"],
                expected_size=projection_metadata.st_size,
                owner_uid=expected_owner_uid,
                reader_gid=reader_gid,
                deadline_monotonic=deadline,
            )
            projection_raw = _read_fd(
                projection_fd,
                expected_size=projection_metadata.st_size,
                label="Controlled custody signed projection",
                deadline_monotonic=deadline,
            )
            from research.ready_manifest import (
                _verified_projection_evidence,
                load_exact_four_pilot_ready_binding,
            )

            binding = load_exact_four_pilot_ready_binding()
            verified_projection = _verified_projection_evidence(
                projection_raw,
                list(binding.required_datasets),
                expected_environment=expected_environment,
            )
            _require_io_budget(deadline)
            if (
                verified_projection.signed_document_digest
                != document["signed_projection_document_digest"]
                or _identity(os.fstat(projection_fd))
                != _identity(projection_metadata)
            ):
                raise ControlledReadyCustodyV2Error(
                    "Controlled custody projection failed current verification"
                )
        except ControlledReadyCustodyV2Error:
            raise
        except Exception as exc:
            raise ControlledReadyCustodyV2Error(
                "Controlled custody projection failed current verification"
            ) from exc
        finally:
            os.close(projection_fd)
    finally:
        os.close(root_fd)
    return InstalledControlledReadyCustodyV2(
        manifest_path=path,
        manifest_digest=declared_digest,
        snapshot_path=root / snapshot_name,
        projection_path=root / projection_name,
        snapshot_digest=document["immutable_snapshot_digest"],
        projection_digest=document["signed_projection_document_digest"],
        snapshot_id=document["snapshot_id"],
        ready_authority_resource_digest=document[
            "ready_authority_resource_digest"
        ],
        controlled_reader_gid=reader_gid,
    )


__all__ = [
    "CONTROLLED_READY_CUSTODY_FORMAT",
    "ControlledReadyCustodyV2Error",
    "InstalledControlledReadyCustodyV2",
    "install_controlled_ready_custody_v2",
    "read_root_owned_controlled_ready_input_v2",
]
