"""Immutable JSON store for risk audits, separate from paper results."""

from __future__ import annotations

import json
import re
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agents.types import RiskAudit


DEFAULT_RISK_ROOT = Path("data/risk/audits")
_SAFE_COMPONENT = re.compile(r"^[A-Za-z0-9._-]+$")


class JsonRiskStore:
    def __init__(self, root: str | Path = DEFAULT_RISK_ROOT) -> None:
        self.root = Path(root)

    def audit_path(self, audit: RiskAudit) -> Path:
        if not _SAFE_COMPONENT.fullmatch(audit.audit_id):
            raise ValueError("risk audit_id is not a safe path component")
        return self.root / f"{audit.audit_id}.json"

    def save(self, audit: RiskAudit) -> Path:
        """Create an immutable audit, or idempotently accept identical bytes."""
        path = self.audit_path(audit)
        serialized = json.dumps(
            audit.to_dict(),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
            allow_nan=False,
        ) + "\n"
        if path.is_file():
            if path.read_text(encoding="utf-8") != serialized:
                raise FileExistsError(f"risk audit is immutable: {path}")
            return path
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            handle.write(serialized)
            temporary = Path(handle.name)
        # There is a small concurrent first-writer race with replace().  The
        # audit id is content-derived, so identical writers produce identical
        # bytes; a later writer cannot mutate the in-memory audit object.
        temporary.replace(path)
        return path

    def load(self, audit_id: str) -> dict:
        if not _SAFE_COMPONENT.fullmatch(audit_id):
            raise ValueError("risk audit_id is not a safe path component")
        payload = json.loads((self.root / f"{audit_id}.json").read_text("utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("risk audit payload must be an object")
        return payload
