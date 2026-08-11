"""Minimal immutable envelopes for handoffs between trusted role stages."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from types import MappingProxyType
from typing import Any, Mapping


ARTIFACT_SCHEMA_VERSION = "agent-artifact/v1"


def _canonical(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({str(key): _freeze(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item) for item in value)
    return value


def _thaw(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _thaw(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw(item) for item in value]
    return value


@dataclass(frozen=True, slots=True)
class ArtifactEnvelope:
    artifact_id: str
    type: str
    schema_version: str
    producer_role: str
    parent_ids: tuple[str, ...]
    data_snapshot_id: str
    created_at: str
    payload: Mapping[str, Any]

    def __post_init__(self) -> None:
        if self.schema_version != ARTIFACT_SCHEMA_VERSION:
            raise ValueError("unsupported agent artifact schema")
        if not self.type or not self.producer_role or not self.data_snapshot_id:
            raise ValueError("artifact envelope requires type, role, and snapshot")
        frozen_payload = _freeze(self.payload)
        object.__setattr__(self, "payload", frozen_payload)
        expected = self._content_id()
        if self.artifact_id != expected:
            raise ValueError("artifact_id does not match envelope content")

    def _content(self) -> dict[str, Any]:
        return {
            "type": self.type,
            "schema_version": self.schema_version,
            "producer_role": self.producer_role,
            "parent_ids": list(self.parent_ids),
            "data_snapshot_id": self.data_snapshot_id,
            "created_at": self.created_at,
            "payload": _thaw(self.payload),
        }

    def _content_id(self) -> str:
        return "sha256:" + hashlib.sha256(
            _canonical(self._content()).encode("utf-8")
        ).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        return {"artifact_id": self.artifact_id, **self._content()}

    @classmethod
    def create(
        cls,
        *,
        type: str,
        producer_role: str,
        data_snapshot_id: str,
        payload: Mapping[str, Any],
        parent_ids: tuple[str, ...] = (),
        created_at: str | None = None,
    ) -> "ArtifactEnvelope":
        timestamp = created_at or datetime.now(timezone.utc).isoformat()
        content = {
            "type": type,
            "schema_version": ARTIFACT_SCHEMA_VERSION,
            "producer_role": producer_role,
            "parent_ids": list(parent_ids),
            "data_snapshot_id": data_snapshot_id,
            "created_at": timestamp,
            "payload": dict(payload),
        }
        artifact_id = "sha256:" + hashlib.sha256(
            _canonical(content).encode("utf-8")
        ).hexdigest()
        return cls(
            artifact_id=artifact_id,
            type=type,
            schema_version=ARTIFACT_SCHEMA_VERSION,
            producer_role=producer_role,
            parent_ids=parent_ids,
            data_snapshot_id=data_snapshot_id,
            created_at=timestamp,
            payload=payload,
        )


__all__ = ["ARTIFACT_SCHEMA_VERSION", "ArtifactEnvelope"]
