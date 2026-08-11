"""Immutable paper-result JSON with a parallel-safe SQLite experiment index.

This module persists research outputs only.  It does not read market facts;
all facts in a :class:`PaperRunResult` have already passed through PIT,
features, and the core engine.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from paper_runtime import ExperimentIndex

from .types import PaperRunResult


DEFAULT_PAPER_ROOT = Path("data/paper")
_SAFE_COMPONENT = re.compile(r"[^A-Za-z0-9._-]+")


def _safe_component(value: str) -> str:
    component = _SAFE_COMPONENT.sub("-", value.strip()).strip(".-")
    if not component:
        raise ValueError(f"unsafe empty paper path component from {value!r}")
    return component


class JsonPaperStore:
    """Immutable result store with a SQLite WAL control-plane index.

    V2 results live below
    ``<root>/<strategy_id>/<experiment_id>/<run_id>.json``.  The JSON is the
    immutable source of truth; ``index.sqlite3`` is only a query accelerator.
    Independent processes may add experiments concurrently without rewriting
    a shared text file.
    """

    def __init__(self, root: str | Path = DEFAULT_PAPER_ROOT) -> None:
        self.root = Path(root)

    @property
    def index_path(self) -> Path:
        return self.root / "index.sqlite3"

    def result_path(self, result: PaperRunResult) -> Path:
        strategy_id = str(result.reproducibility["strategy_id"])
        return (
            self.root
            / _safe_component(strategy_id)
            / _safe_component(result.experiment_id)
            / f"{_safe_component(result.run_id)}.json"
        )

    def save(self, result: PaperRunResult) -> Path:
        """Persist ``result`` once and index it transactionally.

        An identical retry is idempotent. Reusing a run path for different
        JSON is rejected: experiment metadata must never silently rewrite its
        immutable evidence record.
        """
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
        try:
            # Hard-link publication is atomic and refuses to replace an
            # existing result, including a result written by another process.
            os.link(temporary, path)
        except FileExistsError:
            if path.read_text(encoding="utf-8") != serialized:
                raise FileExistsError(
                    f"immutable paper result already exists with different "
                    f"content: {path}"
                )
        finally:
            temporary.unlink(missing_ok=True)
        self._upsert_index(result, path)
        return path

    def _read_index(self) -> list[dict[str, Any]]:
        return ExperimentIndex(self.index_path).entries()

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
        entry = self._index_entry(
            result,
            path,
            created_at=datetime.now(timezone.utc).isoformat(),
        )
        ExperimentIndex(self.index_path).upsert(entry)

    def rebuild_index(self) -> int:
        """Atomically rebuild the disposable index from immutable JSON.

        All result files are parsed and validated before the current index is
        replaced. A corrupt artifact therefore cannot destroy a usable index.
        """
        paths = sorted(self.root.glob("*/*/*.json"))
        paths.extend(sorted(self.root.glob("*/*.json")))
        records: list[tuple[PaperRunResult, Path, str]] = []
        for path in paths:
            result = self.load(path)
            created_at = datetime.fromtimestamp(
                path.stat().st_mtime, tz=timezone.utc
            ).isoformat()
            records.append((result, path, created_at))

        self.root.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            dir=self.root,
            prefix=".index-rebuild.",
            suffix=".sqlite3",
            delete=False,
        ) as handle:
            temporary = Path(handle.name)
        temporary.unlink()
        try:
            rebuilt = ExperimentIndex(temporary)
            rebuilt.initialize()
            for result, path, created_at in records:
                rebuilt.upsert(
                    self._index_entry(result, path, created_at=created_at)
                )
            rebuilt.checkpoint()
            os.replace(temporary, self.index_path)
            # A replaced SQLite main file must not inherit sidecars belonging
            # to the previous index generation.
            for suffix in ("-wal", "-shm"):
                self.index_path.with_name(self.index_path.name + suffix).unlink(
                    missing_ok=True
                )
        finally:
            temporary.unlink(missing_ok=True)
            for suffix in ("-wal", "-shm"):
                temporary.with_name(temporary.name + suffix).unlink(missing_ok=True)
        return len(records)

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
