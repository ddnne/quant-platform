"""Filesystem NDJSON adapters. Product receives decoded mappings only."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterator, Mapping


def _payload_map(raw: Any) -> Mapping[str, Any] | None:
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            return None
    return raw if isinstance(raw, Mapping) else None


def iter_ndjson_payloads(
    path: str | Path, *, payload_or_row: bool = False
) -> Iterator[Mapping[str, Any]]:
    with Path(path).open() as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            payload = _payload_map(
                row.get("payload") if isinstance(row, Mapping) else None
            )
            if payload is None and payload_or_row and isinstance(row, Mapping):
                payload = row
            if payload is not None:
                yield payload


__all__ = ["iter_ndjson_payloads"]
