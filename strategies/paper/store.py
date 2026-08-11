"""Local JSON persistence for paper results.

This module persists research outputs only.  It does not read market facts;
all facts in a :class:`PaperRunResult` have already passed through PIT,
features, and the core engine.
"""

from __future__ import annotations

import json
import re
import tempfile
from pathlib import Path

from .types import PaperRunResult


DEFAULT_PAPER_ROOT = Path("data/paper")
_SAFE_COMPONENT = re.compile(r"[^A-Za-z0-9._-]+")


def _safe_component(value: str) -> str:
    component = _SAFE_COMPONENT.sub("-", value.strip()).strip(".-")
    if not component:
        raise ValueError(f"unsafe empty paper path component from {value!r}")
    return component


class JsonPaperStore:
    """Atomic JSON store under ``<root>/<strategy_id>/<run_id>.json``."""

    def __init__(self, root: str | Path = DEFAULT_PAPER_ROOT) -> None:
        self.root = Path(root)

    def result_path(self, result: PaperRunResult) -> Path:
        strategy_id = str(result.reproducibility["strategy_id"])
        return (
            self.root
            / _safe_component(strategy_id)
            / f"{_safe_component(result.run_id)}.json"
        )

    def save(self, result: PaperRunResult) -> Path:
        """Persist ``result`` atomically and return its path."""
        path = self.result_path(result)
        path.parent.mkdir(parents=True, exist_ok=True)
        serialized = json.dumps(
            result.to_dict(),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
            allow_nan=False,
        ) + "\n"
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
        temporary.replace(path)
        return path

    def load(
        self,
        path_or_run_id: str | Path,
        *,
        strategy_id: str | None = None,
    ) -> PaperRunResult:
        """Load by exact path, or by run id (optionally scoped by strategy)."""
        candidate = Path(path_or_run_id)
        if candidate.exists():
            path = candidate
        elif strategy_id is not None:
            path = (
                self.root
                / _safe_component(strategy_id)
                / f"{_safe_component(str(path_or_run_id))}.json"
            )
        else:
            matches = sorted(
                self.root.glob(f"*/{_safe_component(str(path_or_run_id))}.json")
            )
            if len(matches) != 1:
                raise FileNotFoundError(
                    f"expected one result for run_id={path_or_run_id!s}; "
                    f"found {len(matches)} under {self.root}"
                )
            path = matches[0]
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError(f"paper result at {path} is not a JSON object")
        return PaperRunResult.from_dict(payload)

