"""Shared immutable content-addressed artifact store.

Used by Knowledge / Paper / Risk style writers:
create-if-absent, temp write + fsync + atomic rename, hash verify.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

_ID_OK = re.compile(r"^sha256:[0-9a-f]{64}$")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def content_digest(payload: Mapping[str, Any]) -> str:
    blob = json.dumps(
        payload, ensure_ascii=True, sort_keys=True, separators=(",", ":"),
        allow_nan=False,
    )
    return "sha256:" + hashlib.sha256(blob.encode("utf-8")).hexdigest()


def validate_artifact_id(artifact_id: str) -> str:
    if not _ID_OK.match(artifact_id):
        raise ValueError(f"invalid artifact_id: {artifact_id!r}")
    return artifact_id


@dataclass(frozen=True)
class ImmutableArtifactRef:
    artifact_id: str
    path: Path
    created: bool


class ImmutableArtifactStore:
    """Filesystem store: content-addressed JSON, immutable after create."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def path_for(self, artifact_id: str) -> Path:
        validate_artifact_id(artifact_id)
        return self.root / f"{artifact_id.replace(':', '_')}.json"

    def create_if_absent(self, identity: Mapping[str, Any]) -> ImmutableArtifactRef:
        """Write artifact if missing. Returns existing path when already present."""
        artifact_id = content_digest(dict(identity))
        path = self.path_for(artifact_id)
        if path.exists():
            self.verify(path, artifact_id)
            return ImmutableArtifactRef(artifact_id=artifact_id, path=path, created=False)

        body = {
            **dict(identity),
            "artifact_id": artifact_id,
            "created_at": _now(),
        }
        data = json.dumps(body, ensure_ascii=True, indent=2, sort_keys=True) + "\n"
        fd, tmp = tempfile.mkstemp(
            prefix=".art.", suffix=".tmp", dir=self.root
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(data)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp, path)
            # best-effort dir fsync
            try:
                dir_fd = os.open(str(self.root), os.O_RDONLY)
                try:
                    os.fsync(dir_fd)
                finally:
                    os.close(dir_fd)
            except OSError:
                pass
        except Exception:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
        # chmod read-only
        try:
            os.chmod(path, 0o444)
        except OSError:
            pass
        return ImmutableArtifactRef(artifact_id=artifact_id, path=path, created=True)

    def verify(self, path: Path, expected_id: str | None = None) -> dict[str, Any]:
        body = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(body, dict):
            raise ValueError("artifact body must be object")
        aid = str(body.get("artifact_id", ""))
        validate_artifact_id(aid)
        if expected_id is not None and aid != expected_id:
            raise ValueError("artifact_id mismatch on disk")
        # re-hash identity without created_at / artifact_id
        identity = {
            k: v
            for k, v in body.items()
            if k not in {"artifact_id", "created_at"}
        }
        recomputed = content_digest(identity)
        if recomputed != aid:
            raise ValueError("artifact content hash mismatch")
        return body


__all__ = [
    "ImmutableArtifactRef",
    "ImmutableArtifactStore",
    "content_digest",
    "validate_artifact_id",
]
