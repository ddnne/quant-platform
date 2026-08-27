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

from selection.screen import OfflineExperimentBudget

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

_PROVIDER_CHARGE_TRIGGERS = frozenset(
    {"provider_response", "provider_error", "invalid_usage"}
)
_PROVIDER_TERMINAL_OUTCOMES = frozenset(
    {"success", "schema_reject", "provider_error", "invalid_usage", "actual_overage"}
)
_PROVIDER_USAGE_SOURCES = frozenset({"measured", "reserved_estimate"})


def _validate_settlement_id(settlement_id: str) -> None:
    if (
        type(settlement_id) is not str
        or not settlement_id
        or settlement_id != settlement_id.strip()
        or len(settlement_id) > 128
    ):
        raise ValueError("settlement_id must be a bounded non-empty string")


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


@dataclass(frozen=True, slots=True)
class ResearchBudgetCapability:
    """Positive capability required to start mass research."""

    budget_id: str
    ledger_path: Path
    limits: OfflineExperimentBudget

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
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS research_provider_settlements (
                budget_id TEXT NOT NULL,
                settlement_id TEXT NOT NULL,
                input_tokens INTEGER NOT NULL,
                output_tokens INTEGER NOT NULL,
                cached_tokens INTEGER NOT NULL,
                model_calls INTEGER NOT NULL,
                estimated_cost_micros INTEGER NOT NULL,
                usage_source TEXT NOT NULL,
                charge_trigger TEXT NOT NULL,
                over_limit INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                terminal_outcome TEXT,
                finalized_at TEXT,
                PRIMARY KEY (budget_id, settlement_id)
            )
            """
        )
        self._migrate_provider_settlements(conn)
        return conn

    @staticmethod
    def _migrate_provider_settlements(conn: sqlite3.Connection) -> None:
        """Upgrade the pre-two-phase settlement table without losing audit rows."""
        conn.execute("BEGIN IMMEDIATE")
        try:
            columns = {
                str(row[1])
                for row in conn.execute(
                    "PRAGMA table_info(research_provider_settlements)"
                ).fetchall()
            }
            legacy_outcome = "outcome" in columns
            if legacy_outcome:
                trigger_expr = """
                    CASE
                        WHEN outcome IN ('success', 'schema_reject', 'actual_overage')
                            THEN 'provider_response'
                        ELSE outcome
                    END
                """
                if "charge_trigger" in columns:
                    trigger_expr = f"COALESCE(charge_trigger, {trigger_expr})"
                terminal_expr = """
                    CASE
                        WHEN outcome IN (
                            'success', 'schema_reject', 'provider_error',
                            'invalid_usage', 'actual_overage'
                        ) THEN outcome
                        ELSE NULL
                    END
                """
                if "terminal_outcome" in columns:
                    terminal_expr = f"COALESCE(terminal_outcome, {terminal_expr})"
                finalized_expr = """
                    CASE
                        WHEN outcome IN (
                            'success', 'schema_reject', 'provider_error',
                            'invalid_usage', 'actual_overage'
                        ) THEN created_at
                        ELSE NULL
                    END
                """
                if "finalized_at" in columns:
                    finalized_expr = f"COALESCE(finalized_at, {finalized_expr})"
                conn.execute(
                    """
                    CREATE TABLE research_provider_settlements_v2_migration (
                        budget_id TEXT NOT NULL,
                        settlement_id TEXT NOT NULL,
                        input_tokens INTEGER NOT NULL,
                        output_tokens INTEGER NOT NULL,
                        cached_tokens INTEGER NOT NULL,
                        model_calls INTEGER NOT NULL,
                        estimated_cost_micros INTEGER NOT NULL,
                        usage_source TEXT NOT NULL,
                        charge_trigger TEXT NOT NULL,
                        over_limit INTEGER NOT NULL,
                        created_at TEXT NOT NULL,
                        terminal_outcome TEXT,
                        finalized_at TEXT,
                        PRIMARY KEY (budget_id, settlement_id)
                    )
                    """
                )
                conn.execute(
                    f"""
                    INSERT INTO research_provider_settlements_v2_migration (
                        budget_id, settlement_id, input_tokens, output_tokens,
                        cached_tokens, model_calls, estimated_cost_micros,
                        usage_source, charge_trigger, over_limit, created_at,
                        terminal_outcome, finalized_at
                    )
                    SELECT
                        budget_id, settlement_id, input_tokens, output_tokens,
                        cached_tokens, model_calls, estimated_cost_micros,
                        usage_source, {trigger_expr}, over_limit, created_at,
                        {terminal_expr}, {finalized_expr}
                    FROM research_provider_settlements
                    """
                )
                conn.execute("DROP TABLE research_provider_settlements")
                conn.execute(
                    "ALTER TABLE research_provider_settlements_v2_migration "
                    "RENAME TO research_provider_settlements"
                )
                columns = {
                    "budget_id",
                    "settlement_id",
                    "input_tokens",
                    "output_tokens",
                    "cached_tokens",
                    "model_calls",
                    "estimated_cost_micros",
                    "usage_source",
                    "charge_trigger",
                    "over_limit",
                    "created_at",
                    "terminal_outcome",
                    "finalized_at",
                }
            elif "charge_trigger" not in columns:
                raise RuntimeError("provider settlement charge trigger missing")

            if "terminal_outcome" not in columns:
                conn.execute(
                    "ALTER TABLE research_provider_settlements "
                    "ADD COLUMN terminal_outcome TEXT"
                )
            if "finalized_at" not in columns:
                conn.execute(
                    "ALTER TABLE research_provider_settlements "
                    "ADD COLUMN finalized_at TEXT"
                )

            invalid_trigger = conn.execute(
                """
                SELECT 1 FROM research_provider_settlements
                WHERE charge_trigger IS NULL
                   OR charge_trigger NOT IN (
                       'provider_response', 'provider_error', 'invalid_usage'
                   )
                LIMIT 1
                """
            ).fetchone()
            invalid_terminal = conn.execute(
                """
                SELECT 1 FROM research_provider_settlements
                WHERE (terminal_outcome IS NULL) != (finalized_at IS NULL)
                   OR (
                       terminal_outcome IS NOT NULL
                       AND terminal_outcome NOT IN (
                           'success', 'schema_reject', 'provider_error',
                           'invalid_usage', 'actual_overage'
                       )
                   )
                   OR (
                       terminal_outcome IN ('success', 'schema_reject')
                       AND charge_trigger != 'provider_response'
                   )
                   OR (
                       terminal_outcome = 'provider_error'
                       AND charge_trigger != 'provider_error'
                   )
                   OR (
                       terminal_outcome = 'invalid_usage'
                       AND charge_trigger != 'invalid_usage'
                   )
                LIMIT 1
                """
            ).fetchone()
            if invalid_trigger is not None or invalid_terminal is not None:
                raise RuntimeError("provider settlement audit state invalid")
            conn.execute("COMMIT")
        except BaseException:
            conn.execute("ROLLBACK")
            raise

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

    def settle_provider_usage_once(
        self,
        *,
        settlement_id: str,
        input_tokens: int = 0,
        output_tokens: int = 0,
        cached_tokens: int = 0,
        model_calls: int = 1,
        estimated_cost_micros: int = 0,
        usage_source: str,
        charge_trigger: str,
    ) -> bool:
        """Persist provider-started usage exactly once, including overage.

        This is an audit settlement path, not pre-call authorization. It records
        measured usage, or the reserved estimate when usage is unknown, even if
        the already-started side effect crossed a cap. Subsequent ordinary
        ``consume`` calls remain fail-closed because the persisted counters are
        then at or above their hard limits.

        This first phase records why usage became chargeable, but deliberately
        does not guess the terminal decode/result outcome. Call
        ``finalize_provider_settlement_once`` after the response is classified.
        Returns ``True`` when the settled cumulative usage exceeds a configured
        cap. Exact retries return the persisted result without charging again.
        """
        _validate_settlement_id(settlement_id)
        if type(usage_source) is not str or usage_source not in _PROVIDER_USAGE_SOURCES:
            raise ValueError("provider usage_source invalid")
        if (
            type(charge_trigger) is not str
            or charge_trigger not in _PROVIDER_CHARGE_TRIGGERS
        ):
            raise ValueError("provider settlement charge_trigger invalid")
        amounts = {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "cached_tokens": cached_tokens,
            "model_calls": model_calls,
            "estimated_cost_micros": estimated_cost_micros,
        }
        for counter, value in amounts.items():
            if type(value) is not int or value < 0:
                raise ValueError(f"{counter} must be an integer >= 0")
        canonical = (
            int(input_tokens),
            int(output_tokens),
            int(cached_tokens),
            int(model_calls),
            int(estimated_cost_micros),
            usage_source,
            charge_trigger,
        )

        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            existing = conn.execute(
                """
                SELECT input_tokens, output_tokens, cached_tokens, model_calls,
                       estimated_cost_micros, usage_source, charge_trigger, over_limit
                FROM research_provider_settlements
                WHERE budget_id=? AND settlement_id=?
                """,
                (self.budget_id, settlement_id),
            ).fetchone()
            if existing is not None:
                if tuple(existing[:7]) != canonical:
                    conn.execute("ROLLBACK")
                    raise ValueError("provider settlement idempotency conflict")
                conn.execute("COMMIT")
                return bool(existing[7])

            over_limit = False
            for counter, delta in amounts.items():
                row = conn.execute(
                    "SELECT used FROM research_budget_ledger "
                    "WHERE budget_id=? AND counter=?",
                    (self.budget_id, counter),
                ).fetchone()
                used = int(row[0]) if row else 0
                limit = _limit_for(self.limits, counter)
                if limit is not None and used + delta > limit:
                    over_limit = True

            conn.execute(
                """
                INSERT INTO research_provider_settlements (
                    budget_id, settlement_id, input_tokens, output_tokens,
                    cached_tokens, model_calls, estimated_cost_micros,
                    usage_source, charge_trigger, over_limit, created_at,
                    terminal_outcome, finalized_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL)
                """,
                (
                    self.budget_id,
                    settlement_id,
                    *canonical[:5],
                    usage_source,
                    charge_trigger,
                    1 if over_limit else 0,
                    _now_iso(),
                ),
            )
            for counter, delta in amounts.items():
                if delta == 0:
                    continue
                conn.execute(
                    """
                    INSERT INTO research_budget_ledger
                    (budget_id, counter, used, updated_at)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(budget_id, counter) DO UPDATE SET
                        used = used + excluded.used,
                        updated_at = excluded.updated_at
                    """,
                    (self.budget_id, counter, delta, _now_iso()),
                )
            conn.execute("COMMIT")
            return over_limit
        finally:
            conn.close()

    def finalize_provider_settlement_once(
        self,
        *,
        settlement_id: str,
        terminal_outcome: str,
    ) -> None:
        """Finalize one charged provider result without charging it again."""
        _validate_settlement_id(settlement_id)
        if (
            type(terminal_outcome) is not str
            or terminal_outcome not in _PROVIDER_TERMINAL_OUTCOMES
        ):
            raise ValueError("provider settlement terminal_outcome invalid")

        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                """
                SELECT charge_trigger, terminal_outcome
                FROM research_provider_settlements
                WHERE budget_id=? AND settlement_id=?
                """,
                (self.budget_id, settlement_id),
            ).fetchone()
            if row is None:
                conn.execute("ROLLBACK")
                raise ValueError("provider settlement must be charged before finalize")
            charge_trigger = str(row[0])
            expected_trigger = {
                "success": "provider_response",
                "schema_reject": "provider_response",
                "provider_error": "provider_error",
                "invalid_usage": "invalid_usage",
            }.get(terminal_outcome)
            if expected_trigger is not None and charge_trigger != expected_trigger:
                conn.execute("ROLLBACK")
                raise ValueError("provider settlement terminal outcome conflicts with trigger")
            existing = row[1]
            if existing is not None:
                if str(existing) != terminal_outcome:
                    conn.execute("ROLLBACK")
                    raise ValueError("provider settlement terminal outcome conflict")
                conn.execute("COMMIT")
                return
            conn.execute(
                """
                UPDATE research_provider_settlements
                SET terminal_outcome=?, finalized_at=?
                WHERE budget_id=? AND settlement_id=? AND terminal_outcome IS NULL
                """,
                (terminal_outcome, _now_iso(), self.budget_id, settlement_id),
            )
            conn.execute("COMMIT")
        finally:
            conn.close()

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


def _limit_for(limits: OfflineExperimentBudget, counter: str) -> int | None:
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
