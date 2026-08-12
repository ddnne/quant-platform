"""Trusted SQLite control plane for the paper experiment index."""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator


class ExperimentIndex:
    """Parallel-safe WAL index; immutable result JSON stays authoritative."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.path, timeout=30.0)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("PRAGMA busy_timeout = 30000")
            conn.execute("PRAGMA journal_mode = WAL")
            conn.execute("PRAGMA synchronous = NORMAL")
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS paper_experiments (
                    experiment_id    TEXT NOT NULL,
                    run_id           TEXT NOT NULL,
                    strategy_id      TEXT NOT NULL,
                    lifecycle        TEXT NOT NULL,
                    data_snapshot_id TEXT,
                    start_date       TEXT,
                    end_date         TEXT,
                    total_return     REAL,
                    max_dd           REAL,
                    sharpe           REAL,
                    feature_ids_json TEXT NOT NULL,
                    created_at       TEXT NOT NULL,
                    result_path      TEXT NOT NULL UNIQUE,
                    PRIMARY KEY (experiment_id, run_id)
                );
                CREATE INDEX IF NOT EXISTS ix_paper_experiments_strategy_created
                    ON paper_experiments (strategy_id, created_at DESC);
                """
            )
            yield conn
        finally:
            conn.close()

    def entries(self) -> list[dict[str, Any]]:
        if not self.path.is_file():
            return []
        with self._connection() as conn:
            rows = conn.execute(
                "SELECT experiment_id, run_id, strategy_id, lifecycle, "
                "data_snapshot_id, start_date, end_date, total_return, max_dd, "
                "sharpe, feature_ids_json, created_at, result_path "
                "FROM paper_experiments ORDER BY experiment_id, run_id"
            ).fetchall()
        return [
            {
                "experiment_id": row["experiment_id"],
                "run_id": row["run_id"],
                "strategy_id": row["strategy_id"],
                "lifecycle": row["lifecycle"],
                "data_snapshot_id": row["data_snapshot_id"],
                "start": row["start_date"],
                "end": row["end_date"],
                "total_return": row["total_return"],
                "max_dd": row["max_dd"],
                "sharpe": row["sharpe"],
                "feature_ids": json.loads(row["feature_ids_json"]),
                "created_at": row["created_at"],
                "result_path": row["result_path"],
            }
            for row in rows
        ]

    def initialize(self) -> None:
        """Create an empty index schema when there are no result records."""
        with self._connection():
            pass

    def upsert(self, entry: dict[str, Any]) -> None:
        """Index one immutable result under a writer-serializing transaction."""
        with self._connection() as conn:
            try:
                conn.execute("BEGIN IMMEDIATE")
                existing = conn.execute(
                    "SELECT created_at, result_path FROM paper_experiments "
                    "WHERE experiment_id = ? AND run_id = ?",
                    (entry["experiment_id"], entry["run_id"]),
                ).fetchone()
                if (
                    existing is not None
                    and existing["result_path"] != entry["result_path"]
                ):
                    raise ValueError(
                        "paper experiment index points at a different "
                        "immutable result"
                    )
                created_at = (
                    str(existing["created_at"])
                    if existing is not None
                    else str(entry["created_at"])
                )
                conn.execute(
                    """
                    INSERT INTO paper_experiments
                        (experiment_id, run_id, strategy_id, lifecycle,
                         data_snapshot_id, start_date, end_date, total_return,
                         max_dd, sharpe, feature_ids_json, created_at, result_path)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(experiment_id, run_id) DO UPDATE SET
                        strategy_id = excluded.strategy_id,
                        lifecycle = excluded.lifecycle,
                        data_snapshot_id = excluded.data_snapshot_id,
                        start_date = excluded.start_date,
                        end_date = excluded.end_date,
                        total_return = excluded.total_return,
                        max_dd = excluded.max_dd,
                        sharpe = excluded.sharpe,
                        feature_ids_json = excluded.feature_ids_json,
                        result_path = excluded.result_path
                    """,
                    (
                        entry["experiment_id"], entry["run_id"],
                        entry["strategy_id"], entry["lifecycle"],
                        entry["data_snapshot_id"], entry["start"], entry["end"],
                        entry["total_return"], entry["max_dd"], entry["sharpe"],
                        json.dumps(entry["feature_ids"], separators=(",", ":")),
                        created_at, entry["result_path"],
                    ),
                )
                conn.commit()
            except Exception:
                conn.rollback()
                raise

    def checkpoint(self) -> None:
        """Materialize WAL contents before atomic index publication."""
        if not self.path.is_file():
            return
        with self._connection() as conn:
            conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")


__all__ = ["ExperimentIndex"]
