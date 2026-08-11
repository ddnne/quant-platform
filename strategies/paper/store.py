"""Local JSON persistence and a thin JSONL index for paper results.

This module persists research outputs only.  It does not read market facts;
all facts in a :class:`PaperRunResult` have already passed through PIT,
features, and the core engine.
"""

from __future__ import annotations

import json
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .types import PaperRunResult


DEFAULT_PAPER_ROOT = Path("data/paper")
_SAFE_COMPONENT = re.compile(r"[^A-Za-z0-9._-]+")


def _safe_component(value: str) -> str:
    component = _SAFE_COMPONENT.sub("-", value.strip()).strip(".-")
    if not component:
        raise ValueError(f"unsafe empty paper path component from {value!r}")
    return component


class JsonPaperStore:
    """Atomic result store with a small control-plane experiment index.

    V2 results live below
    ``<root>/<strategy_id>/<experiment_id>/<run_id>.json``.  ``index.jsonl``
    is rewritten atomically on each save, making repeated saves an idempotent
    upsert instead of accumulating duplicate index records.
    """

    def __init__(self, root: str | Path = DEFAULT_PAPER_ROOT) -> None:
        self.root = Path(root)

    @property
    def index_path(self) -> Path:
        return self.root / "index.jsonl"

    def result_path(self, result: PaperRunResult) -> Path:
        strategy_id = str(result.reproducibility["strategy_id"])
        return (
            self.root
            / _safe_component(strategy_id)
            / _safe_component(result.experiment_id)
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
        self._upsert_index(result, path)
        return path

    def _read_index(self) -> list[dict[str, Any]]:
        if not self.index_path.is_file():
            return []
        entries: list[dict[str, Any]] = []
        for line_number, line in enumerate(
            self.index_path.read_text(encoding="utf-8").splitlines(), start=1
        ):
            if not line.strip():
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(
                    f"invalid paper index JSON at {self.index_path}:{line_number}"
                ) from exc
            if not isinstance(entry, dict):
                raise ValueError(
                    f"paper index entry at {self.index_path}:{line_number} "
                    "is not a JSON object"
                )
            entries.append(entry)
        return entries

    @staticmethod
    def _metric(metrics: dict[str, Any], *keys: str) -> Any:
        for key in keys:
            if key in metrics:
                return metrics[key]
        return None

    def _index_entry(
        self,
        result: PaperRunResult,
        path: Path,
        *,
        created_at: str,
    ) -> dict[str, Any]:
        reproduction = result.reproducibility
        period = reproduction.get("period", {})
        if not isinstance(period, dict):
            period = {}
        versions = reproduction.get("feature_versions", {})
        feature_ids = sorted(versions) if isinstance(versions, dict) else []
        metrics = result.metrics
        return {
            "experiment_id": result.experiment_id,
            "run_id": result.run_id,
            "strategy_id": result.strategy_id,
            "lifecycle": result.lifecycle.value,
            "data_snapshot_id": reproduction.get("data_snapshot_id"),
            "start": period.get("start"),
            "end": period.get("end"),
            "total_return": self._metric(
                metrics, "total_return_post_cost", "total_return"
            ),
            "max_dd": self._metric(metrics, "max_drawdown", "max_dd"),
            "sharpe": self._metric(metrics, "sharpe", "sharpe_ratio"),
            "feature_ids": feature_ids,
            "created_at": created_at,
            "result_path": path.relative_to(self.root).as_posix(),
        }

    def _upsert_index(self, result: PaperRunResult, path: Path) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        entries = self._read_index()
        key = (result.experiment_id, result.run_id)
        existing = next(
            (
                entry
                for entry in entries
                if (entry.get("experiment_id"), entry.get("run_id")) == key
            ),
            None,
        )
        created_at = (
            str(existing["created_at"])
            if existing is not None and existing.get("created_at")
            else datetime.now(timezone.utc).isoformat()
        )
        replacement = self._index_entry(result, path, created_at=created_at)
        entries_by_key = {
            (str(entry.get("experiment_id", "")), str(entry.get("run_id", ""))): entry
            for entry in entries
        }
        entries_by_key[key] = replacement
        ordered = sorted(entries_by_key.values(), key=lambda row: (
            str(row.get("experiment_id", "")),
            str(row.get("run_id", "")),
        ))
        serialized = "".join(
            json.dumps(
                entry,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            )
            + "\n"
            for entry in ordered
        )
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=self.root,
            prefix=f".{self.index_path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            handle.write(serialized)
            temporary = Path(handle.name)
        temporary.replace(self.index_path)

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
            legacy_path = (
                self.root
                / _safe_component(strategy_id)
                / f"{_safe_component(str(path_or_run_id))}.json"
            )
            matches = sorted(
                self.root.glob(
                    f"{_safe_component(strategy_id)}/*/"
                    f"{_safe_component(str(path_or_run_id))}.json"
                )
            )
            if legacy_path.is_file():
                matches.append(legacy_path)
            if len(matches) != 1:
                raise FileNotFoundError(
                    f"expected one result for run_id={path_or_run_id!s}, "
                    f"strategy_id={strategy_id!r}; found {len(matches)} "
                    f"under {self.root}"
                )
            path = matches[0]
        else:
            safe_run_id = _safe_component(str(path_or_run_id))
            matches = sorted(self.root.glob(f"*/*/{safe_run_id}.json"))
            matches.extend(sorted(self.root.glob(f"*/{safe_run_id}.json")))
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

    def load_by_experiment_id(
        self,
        experiment_id: str,
        *,
        strategy_id: str | None = None,
    ) -> PaperRunResult:
        """Load the newest indexed execution for ``experiment_id``.

        Pure backtests normally have one run per experiment.  If a caller has
        saved multiple executions, ``created_at`` (and then ``run_id``) makes
        selection deterministic.
        """
        safe_experiment_id = _safe_component(experiment_id)
        entries = [
            entry
            for entry in self._read_index()
            if entry.get("experiment_id") == experiment_id
            and (
                strategy_id is None
                or entry.get("strategy_id") == strategy_id
            )
        ]
        if entries:
            entry = max(
                entries,
                key=lambda row: (
                    str(row.get("created_at", "")), str(row.get("run_id", ""))
                ),
            )
            relative = Path(str(entry["result_path"]))
            if relative.is_absolute() or ".." in relative.parts:
                raise ValueError(
                    f"unsafe result_path in paper index: {entry['result_path']!r}"
                )
            return self.load(self.root / relative)

        strategy_glob = (
            _safe_component(strategy_id) if strategy_id is not None else "*"
        )
        matches = sorted(
            self.root.glob(f"{strategy_glob}/{safe_experiment_id}/*.json")
        )
        if len(matches) != 1:
            raise FileNotFoundError(
                f"expected one result for experiment_id={experiment_id!r}; "
                f"found {len(matches)} under {self.root}"
            )
        return self.load(matches[0])
