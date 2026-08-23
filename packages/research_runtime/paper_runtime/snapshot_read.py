"""Presentation / read helpers for verified paper data snapshots.

READY stays fail-closed. Empty DB and PARTIAL coverage cannot publish READY.
This module describes and opens verified READY artifacts; it does not decide READY.
"""

from __future__ import annotations

import json
import sqlite3
import stat
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import quote

if TYPE_CHECKING:
    from paper_runtime.snapshot import ReadySnapshot


def describe_snapshot(
    snapshot_dir: str | Path, snapshot_id: str
) -> ReadySnapshot:
    """Verify sidecar, immutable artifact, and embedded manifest."""
    from paper_runtime.snapshot import (
        RESEARCH_SNAPSHOT_MANIFEST_FORMAT,
        ReadySnapshot,
        _artifact_stem,
        _research_manifest_digest,
        _research_manifest_id,
        data_snapshot_id,
    )

    directory = Path(snapshot_dir).resolve()
    stem = _artifact_stem(snapshot_id)
    manifest_path = directory / f"{stem}.manifest.json"
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
    if data_snapshot_id(artifact_path) != snapshot_id:
        raise RuntimeError("embedded snapshot manifest does not match sidecar")
    return ReadySnapshot(snapshot_id, artifact_path, manifest_path, manifest)


def list_ready_snapshots(snapshot_dir: str | Path) -> list[ReadySnapshot]:
    directory = Path(snapshot_dir).resolve()
    if not directory.is_dir():
        return []
    snapshots: list[ReadySnapshot] = []
    for path in directory.glob("sha256_*.manifest.json"):
        token = path.name.removesuffix(".manifest.json").replace("_", ":", 1)
        try:
            snapshots.append(describe_snapshot(directory, token))
        except (FileNotFoundError, RuntimeError, ValueError):
            continue
    return sorted(
        snapshots, key=lambda item: (item.committed_at, item.snapshot_id),
        reverse=True,
    )


def latest_ready_snapshot(snapshot_dir: str | Path) -> ReadySnapshot:
    """Latest verified READY snapshot; never return a BUILDING artifact."""
    directory = Path(snapshot_dir).resolve()
    ready = list_ready_snapshots(directory)
    if not ready:
        raise FileNotFoundError(f"no READY research snapshot under {directory}")
    return ready[0]


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
