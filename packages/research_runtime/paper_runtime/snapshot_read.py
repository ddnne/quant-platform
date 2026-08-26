"""Presentation / read helpers for verified paper data snapshots.

READY stays fail-closed. Empty DB and PARTIAL coverage cannot publish READY.
This module describes and opens verified READY artifacts; it does not decide READY.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import stat
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import quote

if TYPE_CHECKING:
    from paper_runtime.snapshot import ReadySnapshot


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def _embedded_research_manifest(
    artifact_path: Path,
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
    uri = (
        "file:"
        + quote(str(artifact_path.resolve()))
        + "?mode=ro&immutable=1"
    )
    try:
        conn = sqlite3.connect(uri, uri=True)
        rows = conn.execute(
            "SELECT format, manifest_json FROM local_snapshot_manifests "
            "WHERE snapshot_id=?",
            (snapshot_id,),
        ).fetchall()
    except sqlite3.Error as exc:
        raise RuntimeError(
            "READY snapshot has no readable embedded research manifest"
        ) from exc
    finally:
        if "conn" in locals():
            conn.close()
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
        _immutable_data_snapshot_id,
        _research_manifest_digest,
        _research_manifest_id,
        RESEARCH_SNAPSHOT_PUBLICATION_FORMAT,
    )

    directory = Path(snapshot_dir).resolve()
    stem = _artifact_stem(snapshot_id)
    manifest_path = directory / f"{stem}.manifest.json"
    publication_path = directory / f"{stem}.publication.json"
    if not publication_path.is_file():
        raise FileNotFoundError(
            f"snapshot publication marker does not exist: {publication_path}"
        )
    try:
        publication = json.loads(publication_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
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
    if not manifest_path.is_file():
        raise FileNotFoundError(f"snapshot manifest does not exist: {manifest_path}")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"invalid snapshot manifest: {manifest_path}") from exc
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
    if not artifact_path.is_file():
        raise FileNotFoundError(f"snapshot artifact does not exist: {artifact_path}")
    mode = artifact_path.stat().st_mode
    if mode & (stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH):
        raise RuntimeError("READY snapshot artifact is writable")
    if manifest_path.stat().st_mode & (stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH):
        raise RuntimeError("READY snapshot manifest is writable")
    if publication_path.stat().st_mode & (
        stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH
    ):
        raise RuntimeError("READY snapshot publication marker is writable")
    artifact_digest = _file_sha256(artifact_path)
    if artifact_digest != publication.get("artifact_digest"):
        raise RuntimeError("READY snapshot artifact digest mismatch")
    embedded_manifest = _embedded_research_manifest(
        artifact_path,
        snapshot_id,
        expected_format=RESEARCH_SNAPSHOT_MANIFEST_FORMAT,
    )
    if embedded_manifest != manifest:
        raise RuntimeError(
            "external READY snapshot manifest does not match embedded manifest"
        )
    attestation_name = publication.get("readiness_attestation")
    attestation_digest = publication.get("readiness_attestation_digest")
    if publication_scope == "PRODUCTION":
        if not isinstance(attestation_name, str) or not attestation_name:
            raise RuntimeError("production READY publication has no attestation")
        if (
            not isinstance(attestation_digest, str)
            or not attestation_digest.startswith("sha256:")
            or len(attestation_digest) != 71
        ):
            raise RuntimeError("production READY attestation digest is invalid")
    if attestation_name is not None:
        if (
            not isinstance(attestation_name, str)
            or Path(attestation_name).name != attestation_name
        ):
            raise RuntimeError("READY attestation path is invalid")
        attestation_path = directory / attestation_name
        if not attestation_path.is_file():
            raise RuntimeError("READY attestation is missing")
        digest = hashlib.sha256(attestation_path.read_bytes()).hexdigest()
        if attestation_digest != "sha256:" + digest:
            raise RuntimeError("READY attestation digest mismatch")
        if attestation_path.stat().st_mode & (
            stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH
        ):
            raise RuntimeError("READY attestation is writable")
        if publication_scope == "PRODUCTION":
            try:
                from research.readiness import load_verified_pilot_readiness
                from research.ready_manifest import (
                    ready_manifest_from_snapshot_document,
                )

                nested_manifest = ready_manifest_from_snapshot_document(
                    manifest
                )

                readiness = load_verified_pilot_readiness(
                    attestation_path,
                    expected_snapshot_id=snapshot_id,
                    expected_ready_manifest_digest=str(
                        nested_manifest.to_dict().get("manifest_digest") or ""
                    ),
                )
                if readiness.immutable_db_digest != artifact_digest:
                    raise RuntimeError(
                        "production READY attestation does not bind the artifact"
                    )
            except Exception as exc:
                raise RuntimeError(
                    "production READY attestation is not trusted"
                ) from exc
    elif attestation_digest is not None:
        raise RuntimeError("READY attestation digest has no artifact")
    if publication_scope == "FIXTURE" and (
        attestation_name is not None or attestation_digest is not None
    ):
        raise RuntimeError("fixture publication cannot carry READY authority")
    if _immutable_data_snapshot_id(artifact_path) != snapshot_id:
        raise RuntimeError("embedded snapshot manifest does not match sidecar")
    return ReadySnapshot(snapshot_id, artifact_path, manifest_path, manifest)


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
    if not pointer_path.is_file():
        raise FileNotFoundError(
            f"no READY research snapshot: committed pointer missing under {directory}"
        )
    try:
        pointer = json.loads(pointer_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
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
    publication_path = directory / (
        pointer["snapshot_id"].replace(":", "_", 1) + ".publication.json"
    )
    publication = json.loads(publication_path.read_text(encoding="utf-8"))
    if (
        pointer.get("manifest") != ready.manifest_path.name
        or pointer.get("committed_at") != ready.committed_at
        or pointer.get("change_seq") != ready.manifest.get("change_seq")
        or pointer.get("publication_digest")
        != publication.get("publication_digest")
    ):
        raise RuntimeError("latest READY pointer does not bind its snapshot")
    if pointer_path.stat().st_mode & (
        stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH
    ):
        raise RuntimeError("latest READY pointer is writable")
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
    """Open a verified READY artifact with immutable SQLite URI flags."""
    ready = (
        latest_ready_snapshot(snapshot_dir)
        if snapshot_id is None
        else describe_snapshot(snapshot_dir, snapshot_id)
    )
    uri = "file:" + quote(str(ready.db_path)) + "?mode=ro&immutable=1"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def _open_fixture_snapshot(
    snapshot_dir: str | Path, snapshot_id: str | None = None
) -> sqlite3.Connection:
    ready = (
        _latest_fixture_snapshot(snapshot_dir)
        if snapshot_id is None
        else _describe_fixture_snapshot(snapshot_dir, snapshot_id)
    )
    uri = "file:" + quote(str(ready.db_path)) + "?mode=ro&immutable=1"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    return conn
