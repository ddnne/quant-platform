"""Persistent atomic research budget ledger + experiment slot leases (6.2.2).

Mass/autonomous research runners must hold a ResearchBudgetCapability.
``concurrent_experiments`` is modeled as active leases, not a cumulative consume.
Hard token caps are required (no None into mass research).
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Mapping
from urllib.parse import quote
from uuid import uuid4

from selection.screen import ExperimentBudget

_COUNTERS = (
    "generations",
    "model_calls",
    "input_tokens",
    "output_tokens",
    "cached_tokens",
    "paper_runs",
    "compute_time_ms",
    "estimated_cost_micros",
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _now_iso() -> str:
    return _now().isoformat()


class BudgetExhaustedError(RuntimeError):
    """Raised when a consume would exceed the hard limit."""


class MassResearchDisabledError(RuntimeError):
    """Mass research scheduler is fail-closed until READY GO conditions."""


@dataclass(frozen=True)
class ExperimentSlotLease:
    lease_id: str
    budget_id: str
    acquired_at: str
    expires_at: str
    last_heartbeat_at: str

    def is_expired(self, *, now: datetime | None = None) -> bool:
        clock = now or _now()
        expires = datetime.fromisoformat(self.expires_at.replace("Z", "+00:00"))
        return clock > expires


@dataclass(frozen=True)
class ResearchBudgetCapability:
    """Positive capability required to start mass research."""

    budget_id: str
    ledger_path: Path
    limits: ExperimentBudget

    def __post_init__(self) -> None:
        # Hard token/cost budgets — never None for mass research.
        if self.limits.max_input_tokens is None or self.limits.max_output_tokens is None:
            raise MassResearchDisabledError(
                "token budgets must be hard-capped (max_input_tokens/max_output_tokens)"
            )
        if self.limits.max_input_tokens < 1 or self.limits.max_output_tokens < 1:
            raise MassResearchDisabledError("token budgets must be >= 1")

    def _connect(self) -> sqlite3.Connection:
        uri = "file:" + quote(str(self.ledger_path)) + "?mode=rwc"
        conn = sqlite3.connect(uri, uri=True, timeout=30.0)
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
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS research_experiment_leases (
                lease_id TEXT PRIMARY KEY,
                budget_id TEXT NOT NULL,
                acquired_at TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                last_heartbeat_at TEXT NOT NULL,
                released_at TEXT
            )
            """
        )
        return conn

    def _recover_expired(self, conn: sqlite3.Connection) -> int:
        now = _now_iso()
        cur = conn.execute(
            """
            UPDATE research_experiment_leases
            SET released_at=?
            WHERE budget_id=? AND released_at IS NULL AND expires_at < ?
            """,
            (now, self.budget_id, now),
        )
        return int(cur.rowcount or 0)

    def active_lease_count(self) -> int:
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            self._recover_expired(conn)
            row = conn.execute(
                """
                SELECT COUNT(*) FROM research_experiment_leases
                WHERE budget_id=? AND released_at IS NULL
                """,
                (self.budget_id,),
            ).fetchone()
            conn.execute("COMMIT")
            return int(row[0]) if row else 0
        finally:
            conn.close()

    def acquire_slot(self, *, ttl_seconds: int | None = None) -> ExperimentSlotLease:
        """Transactional experiment slot lease (max_parallel_experiments bound)."""
        if ttl_seconds is None:
            ttl_seconds = int(self.limits.lease_ttl_seconds)
        if ttl_seconds < 30 or ttl_seconds > 86_400:
            raise ValueError("ttl_seconds must be in [30, 86400]")
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            self._recover_expired(conn)
            row = conn.execute(
                """
                SELECT COUNT(*) FROM research_experiment_leases
                WHERE budget_id=? AND released_at IS NULL
                """,
                (self.budget_id,),
            ).fetchone()
            active = int(row[0]) if row else 0
            limit = int(self.limits.max_parallel_experiments)
            if active >= limit:
                conn.execute("ROLLBACK")
                raise BudgetExhaustedError(
                    f"concurrent_experiments: active={active} limit={limit}"
                )
            lease_id = str(uuid4())
            acquired = _now()
            expires = acquired + timedelta(seconds=ttl_seconds)
            conn.execute(
                """
                INSERT INTO research_experiment_leases
                (lease_id, budget_id, acquired_at, expires_at, last_heartbeat_at, released_at)
                VALUES (?, ?, ?, ?, ?, NULL)
                """,
                (
                    lease_id,
                    self.budget_id,
                    acquired.isoformat(),
                    expires.isoformat(),
                    acquired.isoformat(),
                ),
            )
            conn.execute("COMMIT")
            return ExperimentSlotLease(
                lease_id=lease_id,
                budget_id=self.budget_id,
                acquired_at=acquired.isoformat(),
                expires_at=expires.isoformat(),
                last_heartbeat_at=acquired.isoformat(),
            )
        finally:
            conn.close()

    def heartbeat(
        self,
        lease: ExperimentSlotLease,
        *,
        extend_seconds: int | None = None,
    ) -> ExperimentSlotLease:
        if extend_seconds is None:
            extend_seconds = int(self.limits.lease_ttl_seconds)
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                """
                SELECT lease_id FROM research_experiment_leases
                WHERE lease_id=? AND budget_id=? AND released_at IS NULL
                """,
                (lease.lease_id, self.budget_id),
            ).fetchone()
            if row is None:
                conn.execute("ROLLBACK")
                raise BudgetExhaustedError(f"lease {lease.lease_id} not active")
            now = _now()
            expires = now + timedelta(seconds=extend_seconds)
            conn.execute(
                """
                UPDATE research_experiment_leases
                SET last_heartbeat_at=?, expires_at=?
                WHERE lease_id=?
                """,
                (now.isoformat(), expires.isoformat(), lease.lease_id),
            )
            conn.execute("COMMIT")
            return ExperimentSlotLease(
                lease_id=lease.lease_id,
                budget_id=self.budget_id,
                acquired_at=lease.acquired_at,
                expires_at=expires.isoformat(),
                last_heartbeat_at=now.isoformat(),
            )
        finally:
            conn.close()

    def release(self, lease: ExperimentSlotLease) -> None:
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                """
                UPDATE research_experiment_leases
                SET released_at=?
                WHERE lease_id=? AND budget_id=? AND released_at IS NULL
                """,
                (_now_iso(), lease.lease_id, self.budget_id),
            )
            conn.execute("COMMIT")
        finally:
            conn.close()

    def consume(self, **amounts: int) -> None:
        """Atomically consume cumulative counters (not concurrent slots)."""
        if not amounts:
            return
        if "concurrent_experiments" in amounts:
            raise ValueError(
                "concurrent_experiments is lease-based; use acquire_slot/release"
            )
        for key, val in amounts.items():
            if key not in _COUNTERS:
                raise KeyError(f"unknown budget counter: {key}")
            if int(val) < 0:
                raise ValueError("consume amounts must be non-negative")
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
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
                    (self.budget_id, counter, delta, _now_iso()),
                )
            conn.execute("COMMIT")
        finally:
            conn.close()

    def charge_provider_usage(
        self,
        *,
        input_tokens: int = 0,
        output_tokens: int = 0,
        cached_tokens: int = 0,
        model_calls: int = 1,
        estimated_cost_micros: int = 0,
    ) -> None:
        """Charge real provider usage into the ledger."""
        self.consume(
            input_tokens=int(input_tokens),
            output_tokens=int(output_tokens),
            cached_tokens=int(cached_tokens),
            model_calls=int(model_calls),
            estimated_cost_micros=int(estimated_cost_micros),
        )

    def snapshot(self) -> Mapping[str, int]:
        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT counter, used FROM research_budget_ledger WHERE budget_id=?",
                (self.budget_id,),
            ).fetchall()
            out = {str(c): int(u) for c, u in rows}
            out["active_leases"] = self.active_lease_count()
            return out
        finally:
            conn.close()


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
        "generations": limits.max_generations,
        "model_calls": limits.max_model_calls,
        "paper_runs": limits.max_paper_runs,
        "input_tokens": limits.max_input_tokens,
        "output_tokens": limits.max_output_tokens,
        "cached_tokens": limits.max_cached_tokens,
        "compute_time_ms": limits.max_compute_time_ms,
        "estimated_cost_micros": limits.max_estimated_cost_micros,
    }
    return mapping.get(counter)


__all__ = [
    "BudgetExhaustedError",
    "ExperimentSlotLease",
    "MassResearchDisabledError",
    "ResearchBudgetCapability",
    "require_budget_capability",
]
