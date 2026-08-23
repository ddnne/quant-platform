"""Persistence I/O for paper data snapshot artifacts.

READY stays fail-closed. Empty DB and PARTIAL coverage cannot publish READY.
This module copies SQLite and writes JSON sidecars; it does not decide READY.
"""

from __future__ import annotations

import json
import os
import sqlite3
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


def _copy_sqlite(source: sqlite3.Connection, target_path: Path) -> None:
    target = sqlite3.connect(str(target_path))
    try:
        source.backup(target)
    finally:
        target.close()
