"""Persistent atomic research budget ledger (Phase 7 hard capability).

Mass/autonomous research runners must hold a ResearchBudgetCapability that
consumes counters via SQLite transactions. Process-memory-only budgets are
not sufficient for production mass research.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping
from urllib.parse import quote

from selection.screen import ExperimentBudget

_COUNTERS = (
    "concurrent_experiments",
    "generations",
    "model_calls",
    "input_tokens",
    "output_tokens",
    "paper_runs",
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class ResearchBudgetCapability:
    """Positive capability required to start mass research."""

    budget_id: str
    ledger_path: Path
    limits: ExperimentBudget

    def consume(self, **amounts: int) -> None:
        """Atomically consume counters; raise BudgetExhaustedError if over limit."""
        if not amounts:
            return
        for key, val in amounts.items():
            if key not in _COUNTERS:
                raise KeyError(f"unknown budget counter: {key}")
            if int(val) < 0:
                raise ValueError("consume amounts must be non-negative")
        uri = "file:" + quote(str(self.ledger_path)) + "?mode=rwc"
        conn = sqlite3.connect(uri, uri=True, timeout=30.0)
        try:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS research_budget_ledger (
                    budget_id TEXT NOT NULL,
                    counter TEXT NOT NULL,
                    used INTEGER NOT NULL DEFAULT 0,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (budget_id, counter)
                )
                """
            )
            for counter, delta in amounts.items():
                delta = int(delta)
                if delta == 0:
                    continue
                row = conn.execute(
                    "SELECT used FROM research_budget_ledger "
                    "WHERE budget_id=? AND counter=?",
                    (self.budget_id, counter),
                ).fetchone()
                used = int(row[0]) if row else 0
                limit = _limit_for(self.limits, counter)
                if limit is not None and used + delta > limit:
                    conn.execute("ROLLBACK")
                    raise BudgetExhaustedError(
                        f"{counter}: used={used} delta={delta} limit={limit}"
                    )
                conn.execute(
                    """
                    INSERT INTO research_budget_ledger (budget_id, counter, used, updated_at)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(budget_id, counter) DO UPDATE SET
                        used = used + excluded.used,
                        updated_at = excluded.updated_at
                    """,
                    (self.budget_id, counter, delta, _now()),
                )
            conn.execute("COMMIT")
        finally:
            conn.close()

    def snapshot(self) -> Mapping[str, int]:
        uri = "file:" + quote(str(self.ledger_path)) + "?mode=rwc"
        conn = sqlite3.connect(uri, uri=True, timeout=30.0)
        try:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS research_budget_ledger (
                    budget_id TEXT NOT NULL,
                    counter TEXT NOT NULL,
                    used INTEGER NOT NULL DEFAULT 0,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (budget_id, counter)
                )
                """
            )
            rows = conn.execute(
                "SELECT counter, used FROM research_budget_ledger WHERE budget_id=?",
                (self.budget_id,),
            ).fetchall()
            return {str(c): int(u) for c, u in rows}
        finally:
            conn.close()


class BudgetExhaustedError(RuntimeError):
    """Raised when a consume would exceed the hard limit."""


class MassResearchDisabledError(RuntimeError):
    """Mass research scheduler is fail-closed until READY GO conditions."""


def require_budget_capability(
    cap: ResearchBudgetCapability | None,
) -> ResearchBudgetCapability:
    if cap is None:
        raise MassResearchDisabledError(
            "ResearchBudgetCapability is required; mass research is fail-closed"
        )
    return cap


def _limit_for(limits: ExperimentBudget, counter: str) -> int | None:
    mapping = {
        "concurrent_experiments": limits.max_parallel_experiments,
        "generations": limits.max_generations,
        "model_calls": limits.max_model_calls,
        "paper_runs": limits.max_paper_runs,
        "input_tokens": None,  # optional monetary/token caps set later
        "output_tokens": None,
    }
    return mapping.get(counter)


__all__ = [
    "BudgetExhaustedError",
    "MassResearchDisabledError",
    "ResearchBudgetCapability",
    "require_budget_capability",
]
