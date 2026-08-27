"""Presentation / read helpers for verified paper data snapshots.

READY stays fail-closed. Empty DB and PARTIAL coverage cannot publish READY.
This module describes and opens verified READY artifacts; it does not decide READY.
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import stat
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Iterator
from urllib.parse import quote

if TYPE_CHECKING:
    from paper_runtime.snapshot import ReadySnapshot


_READY_ARTIFACT_MAX_BYTES = 64 * 1024 * 1024 * 1024
_READY_CONTROL_MAX_BYTES = 4 * 1024 * 1024
_READY_IO_BUDGET_SECONDS = 15 * 60
_READ_CHUNK_BYTES = 1024 * 1024


@dataclass(frozen=True, slots=True)
class _ImmutableFileIdentity:
    device: int
    inode: int
    size: int
    mtime_ns: int
    ctime_ns: int
    owner_uid: int
    mode: int
    links: int

    @classmethod
    def from_stat(cls, metadata: os.stat_result) -> _ImmutableFileIdentity:
        return cls(
            device=metadata.st_dev,
            inode=metadata.st_ino,
            size=metadata.st_size,
            mtime_ns=metadata.st_mtime_ns,
            ctime_ns=metadata.st_ctime_ns,
            owner_uid=metadata.st_uid,
            mode=stat.S_IMODE(metadata.st_mode),
            links=metadata.st_nlink,
        )

    def as_tuple(self) -> tuple[int, ...]:
        return (
            self.device,
            self.inode,
            self.size,
            self.mtime_ns,
            self.ctime_ns,
            self.owner_uid,
            self.mode,
            self.links,
        )


@dataclass(frozen=True, slots=True)
class _PinnedRegularFile:
    fd: int
    path: Path
    identity: _ImmutableFileIdentity
    deadline_monotonic: float


def _require_safe_parent(path: Path, *, label: str) -> os.stat_result:
    try:
        parent = os.stat(path.parent, follow_symlinks=False)
    except FileNotFoundError as exc:
        raise FileNotFoundError(f"{label} does not exist: {path}") from exc
    except OSError as exc:
        raise RuntimeError(f"{label} parent cannot be inspected") from exc
    if (
        not stat.S_ISDIR(parent.st_mode)
        or stat.S_IMODE(parent.st_mode) & (stat.S_IWGRP | stat.S_IWOTH)
    ):
        raise RuntimeError(f"{label} parent is not a protected directory")
    return parent


@contextmanager
def _open_immutable_regular_file(
    path: Path,
    *,
    label: str,
    max_bytes: int,
    expected_identity: tuple[int, ...] | None = None,
    deadline_monotonic: float | None = None,
) -> Iterator[_PinnedRegularFile]:
    """Pin one protected file and reject identity drift before releasing it."""

    parent = _require_safe_parent(path, label=label)
    nofollow = getattr(os, "O_NOFOLLOW", None)
    if nofollow is None:
        raise RuntimeError(f"{label} no-follow support is unavailable")
    flags = os.O_RDONLY | nofollow | getattr(os, "O_CLOEXEC", 0)
    try:
        fd = os.open(path, flags)
    except FileNotFoundError as exc:
        raise FileNotFoundError(f"{label} does not exist: {path}") from exc
    except OSError as exc:
        raise RuntimeError(f"{label} cannot be opened without following links") from exc
    try:
        before = os.fstat(fd)
        identity = _ImmutableFileIdentity.from_stat(before)
        if (
            not stat.S_ISREG(before.st_mode)
            or identity.links != 1
            or identity.size <= 0
            or identity.size > max_bytes
            or identity.mode not in {0o400, 0o440, 0o444}
            or identity.owner_uid != parent.st_uid
        ):
            raise RuntimeError(f"{label} is not an immutable regular file")
        if expected_identity is not None and identity.as_tuple() != expected_identity:
            raise RuntimeError(f"{label} identity drifted after validation")
        deadline = (
            time.monotonic() + _READY_IO_BUDGET_SECONDS
            if deadline_monotonic is None
            else deadline_monotonic
        )
        if time.monotonic() >= deadline:
            raise RuntimeError(f"{label} verification deadline exceeded")
        yield _PinnedRegularFile(fd, path, identity, deadline)
        if _ImmutableFileIdentity.from_stat(os.fstat(fd)) != identity:
            raise RuntimeError(f"{label} changed while it was pinned")
    finally:
        os.close(fd)


def _hash_pinned_file(pinned: _PinnedRegularFile) -> str:
    digest = hashlib.sha256()
    offset = 0
    while offset < pinned.identity.size:
        if time.monotonic() >= pinned.deadline_monotonic:
            raise RuntimeError("READY artifact verification deadline exceeded")
        chunk = os.pread(
            pinned.fd,
            min(_READ_CHUNK_BYTES, pinned.identity.size - offset),
            offset,
        )
        if not chunk:
            raise RuntimeError("READY artifact changed while hashing")
        digest.update(chunk)
        offset += len(chunk)
    return "sha256:" + digest.hexdigest()


def _read_pinned_file(pinned: _PinnedRegularFile) -> bytes:
    chunks: list[bytes] = []
    offset = 0
    while offset < pinned.identity.size:
        if time.monotonic() >= pinned.deadline_monotonic:
            raise RuntimeError("READY control-file verification deadline exceeded")
        chunk = os.pread(
            pinned.fd,
            min(_READ_CHUNK_BYTES, pinned.identity.size - offset),
            offset,
        )
        if not chunk:
            raise RuntimeError("READY control file changed while it was read")
        chunks.append(chunk)
        offset += len(chunk)
    return b"".join(chunks)


def _read_immutable_regular_file_with_identity(
    path: Path,
    *,
    label: str,
    expected_identity: tuple[int, ...] | None = None,
) -> tuple[bytes, tuple[int, ...]]:
    with _open_immutable_regular_file(
        path,
        label=label,
        max_bytes=_READY_CONTROL_MAX_BYTES,
        expected_identity=expected_identity,
    ) as pinned:
        return _read_pinned_file(pinned), pinned.identity.as_tuple()


def _read_immutable_regular_file(path: Path, *, label: str) -> bytes:
    """Read one exact non-symlink, non-writable file identity."""
    raw, _identity = _read_immutable_regular_file_with_identity(
        path,
        label=label,
    )
    return raw


def _open_pinned_sqlite(pinned: _PinnedRegularFile) -> sqlite3.Connection:
    """Open SQLite through the already-pinned inode, never through its name."""

    descriptor_paths = (
        Path(f"/dev/fd/{pinned.fd}"),
        Path(f"/proc/self/fd/{pinned.fd}"),
    )
    descriptor_path = next(
        (candidate for candidate in descriptor_paths if candidate.exists()),
        None,
    )
    if descriptor_path is None:
        raise RuntimeError("READY descriptor-backed SQLite access is unavailable")
    uri = "file:" + quote(str(descriptor_path)) + "?mode=ro&immutable=1"
    try:
        conn = sqlite3.connect(uri, uri=True)
    except sqlite3.Error as exc:
        raise RuntimeError("READY descriptor-backed SQLite open failed") from exc
    conn.row_factory = sqlite3.Row
    return conn


def _embedded_research_manifest(
    conn: sqlite3.Connection,
    snapshot_id: str,
    *,
    expected_format: str,
) -> dict[str, object]:
    """Load the publisher-retained manifest from the immutable artifact.

    The external manifest and publication marker are replace-last discovery
    documents, not independent signing authorities.  Production readiness
    signs the artifact digest, so the exact embedded copy is the authority
    boundary for every outer field, including volatile ordering fields such as
    ``committed_at``.
    """
    try:
        rows = conn.execute(
            "SELECT format, manifest_json FROM local_snapshot_manifests "
            "WHERE snapshot_id=?",
            (snapshot_id,),
        ).fetchall()
    except sqlite3.Error as exc:
        raise RuntimeError(
            "READY snapshot has no readable embedded research manifest"
        ) from exc
    if len(rows) != 1 or rows[0][0] != expected_format:
        raise RuntimeError(
            "READY snapshot embedded research manifest identity is invalid"
        )
    try:
        embedded = json.loads(rows[0][1])
    except (TypeError, json.JSONDecodeError) as exc:
        raise RuntimeError(
            "READY snapshot embedded research manifest is invalid JSON"
        ) from exc
    if not isinstance(embedded, dict):
        raise RuntimeError(
            "READY snapshot embedded research manifest is not an object"
        )
    return embedded


def _describe_snapshot_for_scope(
    snapshot_dir: str | Path,
    snapshot_id: str,
    *,
    publication_scope: str,
) -> ReadySnapshot:
    """Verify one publication for an exact, non-downgradable scope."""
    from paper_runtime.snapshot import (
        RESEARCH_SNAPSHOT_MANIFEST_FORMAT,
        ReadySnapshot,
        _artifact_stem,
        _canonical_digest,
        _data_snapshot_id_from_open_connection,
        _research_manifest_digest,
        _research_manifest_id,
        RESEARCH_SNAPSHOT_PUBLICATION_FORMAT,
    )

    directory = Path(snapshot_dir).resolve()
    stem = _artifact_stem(snapshot_id)
    manifest_path = directory / f"{stem}.manifest.json"
    publication_path = directory / f"{stem}.publication.json"
    try:
        publication_bytes, publication_identity = (
            _read_immutable_regular_file_with_identity(
                publication_path,
                label="snapshot publication marker",
            )
        )
        publication = json.loads(publication_bytes)
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            f"invalid snapshot publication marker: {publication_path}"
        ) from exc
    publication_fields = {
        "format",
        "snapshot_id",
        "manifest_digest",
        "committed_at",
        "change_seq",
        "artifact_digest",
        "publication_scope",
        "readiness_attestation",
        "readiness_attestation_digest",
        "readiness_attestation_id",
        "publication_digest",
    }
    if not isinstance(publication, dict) or set(publication) != publication_fields:
        raise RuntimeError("snapshot publication marker shape is invalid")
    publication_body = {
        key: value
        for key, value in publication.items()
        if key != "publication_digest"
    }
    if (
        publication.get("format") != RESEARCH_SNAPSHOT_PUBLICATION_FORMAT
        or publication.get("snapshot_id") != snapshot_id
        or publication.get("publication_scope") != publication_scope
        or not isinstance(publication.get("change_seq"), int)
        or int(publication.get("change_seq", 0)) <= 0
        or not isinstance(publication.get("artifact_digest"), str)
        or not str(publication.get("artifact_digest")).startswith("sha256:")
        or len(str(publication.get("artifact_digest"))) != 71
        or publication.get("publication_digest")
        != _canonical_digest(publication_body)
    ):
        raise RuntimeError("snapshot publication marker is invalid")
    try:
        manifest_bytes, manifest_identity = (
            _read_immutable_regular_file_with_identity(
                manifest_path,
                label="snapshot manifest",
            )
        )
        manifest = json.loads(manifest_bytes)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"invalid snapshot manifest: {manifest_path}") from exc
    if not isinstance(manifest, dict):
        raise RuntimeError("snapshot manifest is not an object")
    if manifest.get("format") != RESEARCH_SNAPSHOT_MANIFEST_FORMAT:
        raise RuntimeError("unsupported research snapshot manifest format")
    if manifest.get("state") != "READY" or manifest.get("snapshot_id") != snapshot_id:
        raise RuntimeError("snapshot manifest is not the requested READY snapshot")
    if _research_manifest_id(manifest) != snapshot_id:
        raise RuntimeError("research snapshot manifest checksum mismatch")
    if manifest.get("manifest_digest") != _research_manifest_digest(manifest):
        raise RuntimeError("research snapshot full-manifest checksum mismatch")
    if (
        publication.get("manifest_digest") != manifest.get("manifest_digest")
        or publication.get("committed_at") != manifest.get("committed_at")
        or publication.get("change_seq") != manifest.get("change_seq")
    ):
        raise RuntimeError("snapshot publication marker does not bind the manifest")
    artifact_name = manifest.get("artifact")
    if artifact_name != f"{stem}.sqlite":
        raise RuntimeError("research snapshot artifact name mismatch")
    artifact_path = directory / artifact_name
    with _open_immutable_regular_file(
        artifact_path,
        label="READY snapshot artifact",
        max_bytes=_READY_ARTIFACT_MAX_BYTES,
    ) as artifact:
        artifact_digest = _hash_pinned_file(artifact)
        if artifact_digest != publication.get("artifact_digest"):
            raise RuntimeError("READY snapshot artifact digest mismatch")
        artifact_conn = _open_pinned_sqlite(artifact)
        try:
            embedded_manifest = _embedded_research_manifest(
                artifact_conn,
                snapshot_id,
                expected_format=RESEARCH_SNAPSHOT_MANIFEST_FORMAT,
            )
            if embedded_manifest != manifest:
                raise RuntimeError(
                    "external READY snapshot manifest does not match embedded manifest"
                )
            if (
                publication_scope == "PRODUCTION"
                and _data_snapshot_id_from_open_connection(artifact_conn)
                != snapshot_id
            ):
                raise RuntimeError(
                    "embedded snapshot manifest does not match sidecar"
                )
        finally:
            artifact_conn.close()

        attestation_name = publication.get("readiness_attestation")
        attestation_digest = publication.get("readiness_attestation_digest")
        attestation_id = publication.get("readiness_attestation_id")
        attestation_path: Path | None = None
        attestation_bytes: bytes | None = None
        attestation_identity: tuple[int, ...] | None = None
        if publication_scope == "PRODUCTION":
            if not isinstance(attestation_name, str) or not attestation_name:
                raise RuntimeError("production READY publication has no attestation")
            if (
                not isinstance(attestation_digest, str)
                or not attestation_digest.startswith("sha256:")
                or len(attestation_digest) != 71
            ):
                raise RuntimeError("production READY attestation digest is invalid")
            if (
                type(attestation_id) is not str
                or not attestation_id
                or Path(attestation_id).name != attestation_id
                or attestation_name
                != f"{stem}.{attestation_id}.readiness.json"
            ):
                raise RuntimeError(
                    "production READY marker does not bind the exact attestation id"
                )
        if attestation_name is not None:
            if (
                not isinstance(attestation_name, str)
                or Path(attestation_name).name != attestation_name
            ):
                raise RuntimeError("READY attestation path is invalid")
            attestation_path = directory / attestation_name
            attestation_bytes, attestation_identity = (
                _read_immutable_regular_file_with_identity(
                    attestation_path,
                    label="READY attestation",
                )
            )
            digest = hashlib.sha256(attestation_bytes).hexdigest()
            if attestation_digest != "sha256:" + digest:
                raise RuntimeError("READY attestation digest mismatch")
            if publication_scope == "PRODUCTION":
                try:
                    from paper_runtime.readiness_attestation import (
                        verify_pinned_pilot_snapshot_attestation,
                    )

                    nested_manifest = manifest.get("ready_manifest")
                    if not isinstance(nested_manifest, dict):
                        raise RuntimeError(
                            "production READY snapshot has no embedded ReadyManifest"
                        )
                    verified_attestation = verify_pinned_pilot_snapshot_attestation(
                        attestation_bytes,
                        snapshot_id=snapshot_id,
                        ready_manifest=nested_manifest,
                        immutable_db_digest=artifact_digest,
                        expected_environment="production",
                    )
                    if verified_attestation.get("attestation_id") != attestation_id:
                        raise RuntimeError(
                            "production READY attestation id does not match marker"
                        )
                except Exception as exc:
                    raise RuntimeError(
                        "production READY attestation is not trusted"
                    ) from exc
        elif attestation_digest is not None or attestation_id is not None:
            raise RuntimeError("READY attestation identity has no artifact")
        if publication_scope == "FIXTURE" and (
            attestation_name is not None
            or attestation_digest is not None
            or attestation_id is not None
        ):
            raise RuntimeError("fixture publication cannot carry READY authority")
        return ReadySnapshot(
            snapshot_id,
            artifact_path,
            manifest_path,
            manifest,
            publication_path=publication_path,
            readiness_path=attestation_path,
            readiness_digest=(
                str(attestation_digest) if attestation_digest is not None else None
            ),
            readiness_attestation_id=(
                str(attestation_id) if attestation_id is not None else None
            ),
            readiness_bytes=attestation_bytes,
            artifact_digest=artifact_digest,
            artifact_identity=artifact.identity.as_tuple(),
            manifest_identity=manifest_identity,
            publication_identity=publication_identity,
            readiness_identity=attestation_identity,
            publication_digest=str(publication["publication_digest"]),
        )


def describe_snapshot(
    snapshot_dir: str | Path, snapshot_id: str
) -> ReadySnapshot:
    """Verify a production READY artifact; fixture markers are rejected."""
    return _describe_snapshot_for_scope(
        snapshot_dir,
        snapshot_id,
        publication_scope="PRODUCTION",
    )


def _describe_fixture_snapshot(
    snapshot_dir: str | Path, snapshot_id: str
) -> ReadySnapshot:
    """Tests-only reader for non-authoritative fixture publications."""
    return _describe_snapshot_for_scope(
        snapshot_dir,
        snapshot_id,
        publication_scope="FIXTURE",
    )


def _list_ready_snapshots_for_scope(
    snapshot_dir: str | Path,
    *,
    publication_scope: str,
    strict: bool = False,
) -> list[ReadySnapshot]:
    directory = Path(snapshot_dir).resolve()
    if not directory.is_dir():
        return []
    snapshots: list[ReadySnapshot] = []
    for path in directory.glob("sha256_*.publication.json"):
        token = path.name.removesuffix(".publication.json").replace("_", ":", 1)
        try:
            snapshots.append(
                _describe_snapshot_for_scope(
                    directory,
                    token,
                    publication_scope=publication_scope,
                )
            )
        except (FileNotFoundError, RuntimeError, ValueError) as exc:
            if strict:
                raise RuntimeError(
                    "READY namespace contains an invalid or scope-mismatched "
                    f"publication marker: {path}"
                ) from exc
            continue
    return sorted(
        snapshots,
        key=lambda item: (
            int(item.manifest["change_seq"]),
            item.committed_at,
            item.snapshot_id,
        ),
        reverse=True,
    )


def list_ready_snapshots(snapshot_dir: str | Path) -> list[ReadySnapshot]:
    """List only production, signed READY publications."""
    return _list_ready_snapshots_for_scope(
        snapshot_dir,
        publication_scope="PRODUCTION",
    )


def _list_fixture_snapshots(snapshot_dir: str | Path) -> list[ReadySnapshot]:
    return _list_ready_snapshots_for_scope(
        snapshot_dir,
        publication_scope="FIXTURE",
    )


def _latest_ready_snapshot_for_scope(
    snapshot_dir: str | Path,
    *,
    publication_scope: str,
) -> ReadySnapshot:
    """Resolve the newest monotonic publication for one exact scope."""
    directory = Path(snapshot_dir).resolve()
    pointer_path = directory / "latest-ready.json"
    try:
        pointer_bytes, _pointer_identity = (
            _read_immutable_regular_file_with_identity(
                pointer_path,
                label="latest READY pointer",
            )
        )
        pointer = json.loads(pointer_bytes)
    except FileNotFoundError as exc:
        raise FileNotFoundError(
            f"no READY research snapshot: committed pointer missing under {directory}"
        ) from exc
    except json.JSONDecodeError as exc:
        raise RuntimeError("latest READY pointer is invalid") from exc
    if (
        not isinstance(pointer, dict)
        or set(pointer)
        != {
            "format",
            "snapshot_id",
            "manifest",
            "committed_at",
            "change_seq",
            "publication_digest",
        }
        or pointer.get("format") != "research-snapshot-pointer/v1"
        or not isinstance(pointer.get("snapshot_id"), str)
        or not isinstance(pointer.get("change_seq"), int)
        or int(pointer.get("change_seq", 0)) <= 0
        or not isinstance(pointer.get("publication_digest"), str)
    ):
        raise RuntimeError("latest READY pointer is malformed")
    ready = _describe_snapshot_for_scope(
        directory,
        pointer["snapshot_id"],
        publication_scope=publication_scope,
    )
    if (
        pointer.get("manifest") != ready.manifest_path.name
        or pointer.get("committed_at") != ready.committed_at
        or pointer.get("change_seq") != ready.manifest.get("change_seq")
        or pointer.get("publication_digest") != ready.publication_digest
    ):
        raise RuntimeError("latest READY pointer does not bind its snapshot")
    candidates = _list_ready_snapshots_for_scope(
        directory,
        publication_scope=publication_scope,
        strict=True,
    )
    if not candidates or candidates[0].snapshot_id != ready.snapshot_id:
        raise RuntimeError(
            "latest READY pointer is not the newest committed generation"
        )
    return ready


def latest_ready_snapshot(snapshot_dir: str | Path) -> ReadySnapshot:
    """Latest signed production READY; never accept fixture downgrade."""
    return _latest_ready_snapshot_for_scope(
        snapshot_dir,
        publication_scope="PRODUCTION",
    )


def _latest_fixture_snapshot(snapshot_dir: str | Path) -> ReadySnapshot:
    return _latest_ready_snapshot_for_scope(
        snapshot_dir,
        publication_scope="FIXTURE",
    )


def open_ready_snapshot(
    snapshot_dir: str | Path, snapshot_id: str | None = None
) -> sqlite3.Connection:
    """Open the exact inode verified by the production READY reader."""
    ready = (
        latest_ready_snapshot(snapshot_dir)
        if snapshot_id is None
        else describe_snapshot(snapshot_dir, snapshot_id)
    )
    if (
        type(ready.artifact_digest) is not str
        or ready.artifact_identity is None
    ):
        raise RuntimeError("READY snapshot has no pinned artifact identity")
    return _open_verified_snapshot_connection(
        ready,
        label="READY snapshot artifact",
    )


def _open_verified_snapshot_connection(
    ready: ReadySnapshot,
    *,
    label: str,
) -> sqlite3.Connection:
    """Reopen, remeasure, and transfer one pinned inode to SQLite."""

    conn: sqlite3.Connection | None = None
    try:
        with _open_immutable_regular_file(
            ready.db_path,
            label=label,
            max_bytes=_READY_ARTIFACT_MAX_BYTES,
            expected_identity=ready.artifact_identity,
        ) as artifact:
            if _hash_pinned_file(artifact) != ready.artifact_digest:
                raise RuntimeError(
                    f"{label} digest drifted after validation"
                )
            # SQLite opens /dev/fd or /proc/self/fd while ``artifact`` is
            # alive. Its own descriptor remains on the pinned inode after the
            # context closes. A final hash and fstat reject mutation or rename
            # during descriptor transfer.
            conn = _open_pinned_sqlite(artifact)
            if _hash_pinned_file(artifact) != ready.artifact_digest:
                raise RuntimeError(f"{label} changed during SQLite open")
        return conn
    except Exception:
        if conn is not None:
            conn.close()
        raise


def _open_fixture_snapshot(
    snapshot_dir: str | Path, snapshot_id: str | None = None
) -> sqlite3.Connection:
    ready = (
        _latest_fixture_snapshot(snapshot_dir)
        if snapshot_id is None
        else _describe_fixture_snapshot(snapshot_dir, snapshot_id)
    )
    if (
        type(ready.artifact_digest) is not str
        or ready.artifact_identity is None
    ):
        raise RuntimeError("fixture snapshot has no pinned artifact identity")
    return _open_verified_snapshot_connection(
        ready,
        label="fixture snapshot artifact",
    )
