"""Minimal content-addressed knowledge artifact store."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _digest(payload: Mapping[str, Any]) -> str:
    blob = json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(blob.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class KnowledgeArtifact:
    artifact_id: str
    artifact_type: str
    schema_version: str
    producer_role: str
    parent_artifact_ids: tuple[str, ...]
    data_snapshot_id: str | None
    created_at: str
    payload: Mapping[str, Any]


class KnowledgeStore:
    """Filesystem store under ``root``; create-if-absent only."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def put(
        self,
        *,
        artifact_type: str,
        schema_version: str,
        producer_role: str,
        payload: Mapping[str, Any],
        parent_artifact_ids: tuple[str, ...] = (),
        data_snapshot_id: str | None = None,
    ) -> KnowledgeArtifact:
        created_at = _now()
        body = {
            "artifact_type": artifact_type,
            "schema_version": schema_version,
            "producer_role": producer_role,
            "parent_artifact_ids": list(parent_artifact_ids),
            "data_snapshot_id": data_snapshot_id,
            "created_at": created_at,
            "payload": dict(payload),
        }
        artifact_id = _digest(body)
        body["artifact_id"] = artifact_id
        path = self.root / f"{artifact_id.replace(':', '_')}.json"
        if not path.exists():
            path.write_text(json.dumps(body, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")
        return KnowledgeArtifact(
            artifact_id=artifact_id,
            artifact_type=artifact_type,
            schema_version=schema_version,
            producer_role=producer_role,
            parent_artifact_ids=parent_artifact_ids,
            data_snapshot_id=data_snapshot_id,
            created_at=created_at,
            payload=dict(payload),
        )

    def get(self, artifact_id: str) -> KnowledgeArtifact | None:
        path = self.root / f"{artifact_id.replace(':', '_')}.json"
        if not path.exists():
            return None
        body = json.loads(path.read_text(encoding="utf-8"))
        return KnowledgeArtifact(
            artifact_id=body["artifact_id"],
            artifact_type=body["artifact_type"],
            schema_version=body["schema_version"],
            producer_role=body["producer_role"],
            parent_artifact_ids=tuple(body.get("parent_artifact_ids") or ()),
            data_snapshot_id=body.get("data_snapshot_id"),
            created_at=body["created_at"],
            payload=body.get("payload") or {},
        )
