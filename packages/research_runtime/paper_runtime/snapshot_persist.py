"""Persistence I/O for paper data snapshot artifacts.

READY stays fail-closed. Empty DB and PARTIAL coverage cannot publish READY.
This module copies SQLite, writes JSON sidecars, and persists BUILDING/SYNCED
rows; it does not decide READY.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any


def _atomic_json(path: Path, payload: dict[str, Any], *, mode: int) -> None:
    fd, raw_path = tempfile.mkstemp(prefix="." + path.name + ".", dir=path.parent)
    temp_path = Path(raw_path)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(
                payload, handle, ensure_ascii=True, sort_keys=True,
                separators=(",", ":"), allow_nan=False,
            )
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temp_path, mode)
        os.replace(temp_path, path)
    except Exception:
        temp_path.unlink(missing_ok=True)
        raise


def _atomic_bytes(path: Path, payload: bytes, *, mode: int) -> None:
    """Replace one immutable sidecar with its already-verified exact bytes."""

    if type(payload) is not bytes or not payload:
        raise TypeError("atomic byte payload must be exact non-empty bytes")
    fd, raw_path = tempfile.mkstemp(prefix="." + path.name + ".", dir=path.parent)
    temp_path = Path(raw_path)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temp_path, mode)
        os.replace(temp_path, path)
    except Exception:
        temp_path.unlink(missing_ok=True)
        raise
