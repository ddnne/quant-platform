"""Minimal content-addressed knowledge artifact store (via ImmutableArtifactStore)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from storage.immutable_artifact import ImmutableArtifactStore


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
        self._store = ImmutableArtifactStore(self.root)

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
        identity = {
            "artifact_type": artifact_type,
            "schema_version": schema_version,
            "producer_role": producer_role,
            "parent_artifact_ids": list(parent_artifact_ids),
            "data_snapshot_id": data_snapshot_id,
            "payload": dict(payload),
        }
        ref = self._store.create_if_absent(identity)
        body = self._store.verify(ref.path, ref.artifact_id)
        return KnowledgeArtifact(
            artifact_id=ref.artifact_id,
            artifact_type=artifact_type,
            schema_version=schema_version,
            producer_role=producer_role,
            parent_artifact_ids=parent_artifact_ids,
            data_snapshot_id=data_snapshot_id,
            created_at=str(body.get("created_at") or ""),
            payload=dict(payload),
        )

    def get(self, artifact_id: str) -> KnowledgeArtifact | None:
        try:
            path = self._store.path_for(artifact_id)
        except ValueError:
            return None
        if not path.exists():
            return None
        body = self._store.verify(path, artifact_id)
        return KnowledgeArtifact(
            artifact_id=artifact_id,
            artifact_type=str(body["artifact_type"]),
            schema_version=str(body["schema_version"]),
            producer_role=str(body["producer_role"]),
            parent_artifact_ids=tuple(body.get("parent_artifact_ids") or ()),
            data_snapshot_id=body.get("data_snapshot_id"),
            created_at=str(body.get("created_at") or ""),
            payload=dict(body.get("payload") or {}),
        )


__all__ = ["KnowledgeArtifact", "KnowledgeStore"]
