"""Persistent pre-call budget reservations for Controlled execution.

Reservations are capabilities only inside the Controlled authority process.
The ledger reserves governed worst-case capacity and an experiment lease before
any provider call, then settles every terminal path exactly once.  An unknown
post-call outcome is retained as ``RECOVERY_REQUIRED`` and blocks new work.
"""

from __future__ import annotations

import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Mapping

from execution.exact_four_codec import (
    _canonical_bytes,
    _require_digest,
    _strict_json_loads,
    canonical_authority_digest,
)
from selection.budget_ledger import ResearchBudgetCapability
from selection.controlled_pilot_policy import load_controlled_pilot_policy


CONTROLLED_BUDGET_LEDGER_BACKEND = "ControlledPersistentBudgetLedger/v2"
_RESERVATION_TOKEN = object()
_TERMINAL_OUTCOMES = frozenset(
    {"success", "provider_error", "timeout", "schema_reject", "commit_error"}
)
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
_PROVIDER_USAGE_FORMAT = "controlled-provider-usage/v2"
_PROVIDER_USAGE_BINDING_FIELDS = frozenset(
    {
        "format",
        "environment",
        "budget_id",
        "reservation_id",
        "idempotency_key",
        "snapshot_digest",
        "projection_digest",
        "manifest_digest",
        "contents_digest",
    }
)


class ControlledBudgetLedgerV2Error(RuntimeError):
    """A reservation, state transition, or durable settlement failed."""


@dataclass(frozen=True, slots=True, init=False)
class _ControlledBudgetReservationV2:
    reservation_id: str
    lease_id: str
    budget_id: str
    idempotency_key: str

    def __init__(
        self,
        *,
        reservation_id: str,
        lease_id: str,
        budget_id: str,
        idempotency_key: str,
        _token: object,
    ) -> None:
        if _token is not _RESERVATION_TOKEN:
            raise ControlledBudgetLedgerV2Error(
                "Controlled budget reservation requires a committed ledger row"
            )
        object.__setattr__(self, "reservation_id", reservation_id)
        object.__setattr__(self, "lease_id", lease_id)
        object.__setattr__(self, "budget_id", budget_id)
        object.__setattr__(self, "idempotency_key", idempotency_key)


def _aware_utc(clock: Callable[[], datetime]) -> datetime:
    value = clock()
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise ControlledBudgetLedgerV2Error(
            "Controlled budget clock must return an exact aware datetime"
        )
    return value.astimezone(timezone.utc)


class ControlledPersistentBudgetLedgerV2:
    """Reserve and settle governed capacity in one authority-owned SQLite DB."""

    __slots__ = ("_budget", "_environment", "_clock", "_amounts")

    def __init__(
        self,
        *,
        budget: ResearchBudgetCapability,
        environment: str,
        clock: Callable[[], datetime],
    ) -> None:
        if type(budget) is not ResearchBudgetCapability:
            raise ControlledBudgetLedgerV2Error(
                "exact ResearchBudgetCapability required"
            )
        if not isinstance(budget.ledger_path, Path) or not budget.ledger_path.is_absolute():
            raise ControlledBudgetLedgerV2Error(
                "Controlled budget ledger path must be absolute"
            )
        if environment not in {"staging", "production"}:
            raise ControlledBudgetLedgerV2Error(
                "Controlled budget environment is invalid"
            )
        policy = load_controlled_pilot_policy()
        expected = {
            "max_parallel_experiments": policy.max_parallel_experiments,
            "max_generations": policy.max_generations,
            "max_model_calls": policy.max_model_calls,
            "max_input_tokens": policy.max_input_tokens,
            "max_output_tokens": policy.max_output_tokens,
            "max_cached_tokens": policy.max_cached_tokens,
            "max_paper_runs": policy.max_paper_runs,
            "max_estimated_cost_micros": policy.max_cost_usd * 1_000_000,
            "lease_ttl_seconds": policy.lease_ttl_seconds,
            "automatic_promotion": False,
        }
        if any(getattr(budget.limits, key) != value for key, value in expected.items()):
            raise ControlledBudgetLedgerV2Error(
                "Controlled budget capability does not match pinned policy"
            )
        self._budget = budget
        self._environment = environment
        self._clock = clock
        self._amounts = {
            "generations": policy.max_generations,
            "model_calls": policy.max_model_calls,
            "input_tokens": policy.max_input_tokens,
            "output_tokens": policy.max_output_tokens,
            "cached_tokens": policy.max_cached_tokens,
            "paper_runs": 4,
            "compute_time_ms": budget.limits.max_compute_time_ms,
            "estimated_cost_micros": policy.max_cost_usd * 1_000_000,
        }
        self._initialize()

    @property
    def budget_id(self) -> str:
        return self._budget.budget_id

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(
            str(self._budget.ledger_path), timeout=10.0, isolation_level=None
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout = 10000")
        return connection

    def _initialize(self) -> None:
        self._budget.ledger_path.parent.mkdir(parents=True, exist_ok=True)
        # Initialize the shared BudgetLedger tables through its public API.
        self._budget.snapshot()
        columns = ",\n".join(
            f"reserved_{counter} INTEGER NOT NULL CHECK(reserved_{counter} >= 0)"
            for counter in _COUNTERS
        )
        charged_columns = ",\n".join(
            f"charged_{counter} INTEGER CHECK(charged_{counter} >= 0)"
            for counter in _COUNTERS
        )
        with self._connect() as connection:
            connection.executescript(
                f"""
                PRAGMA journal_mode = WAL;
                PRAGMA synchronous = FULL;
                CREATE TABLE IF NOT EXISTS controlled_budget_reservations (
                    environment TEXT NOT NULL,
                    reservation_id TEXT NOT NULL UNIQUE,
                    budget_id TEXT NOT NULL,
                    idempotency_key TEXT NOT NULL UNIQUE,
                    handoff_id TEXT NOT NULL UNIQUE,
                    lease_id TEXT NOT NULL UNIQUE,
                    snapshot_digest TEXT NOT NULL,
                    projection_digest TEXT NOT NULL,
                    state TEXT NOT NULL CHECK(state IN (
                        'RESERVED','EXECUTING','SUCCEEDED','FAILED',
                        'RECOVERY_REQUIRED'
                    )),
                    provider_started INTEGER NOT NULL CHECK(provider_started IN (0,1)),
                    {columns},
                    {charged_columns},
                    usage_source TEXT CHECK(usage_source IN (
                        'not_started','verified_provider_evidence',
                        'reserved_estimate'
                    )),
                    usage_evidence_digest TEXT,
                    usage_evidence BLOB,
                    reserved_at TEXT NOT NULL,
                    executing_at TEXT,
                    settled_at TEXT,
                    terminal_outcome TEXT,
                    error_class TEXT,
                    PRIMARY KEY(environment, reservation_id)
                );
                CREATE TRIGGER IF NOT EXISTS controlled_budget_identity_no_update
                    BEFORE UPDATE OF environment, reservation_id, budget_id,
                        idempotency_key, handoff_id, lease_id, snapshot_digest,
                        projection_digest, reserved_at
                    ON controlled_budget_reservations BEGIN
                    SELECT RAISE(ABORT, 'Controlled budget identity is immutable');
                    END;
                CREATE TRIGGER IF NOT EXISTS controlled_budget_no_delete
                    BEFORE DELETE ON controlled_budget_reservations BEGIN
                    SELECT RAISE(ABORT, 'Controlled budget reservations are immutable');
                    END;
                CREATE TRIGGER IF NOT EXISTS controlled_budget_terminal_no_update
                    BEFORE UPDATE ON controlled_budget_reservations
                    WHEN OLD.state IN ('SUCCEEDED','FAILED') BEGIN
                    SELECT RAISE(ABORT, 'Controlled budget terminal state is immutable');
                    END;
                """
            )

    def _limit(self, counter: str) -> int:
        mapping = {
            "generations": self._budget.limits.max_generations,
            "model_calls": self._budget.limits.max_model_calls,
            "input_tokens": self._budget.limits.max_input_tokens,
            "output_tokens": self._budget.limits.max_output_tokens,
            "cached_tokens": self._budget.limits.max_cached_tokens,
            "paper_runs": self._budget.limits.max_paper_runs,
            "compute_time_ms": self._budget.limits.max_compute_time_ms,
            "estimated_cost_micros": self._budget.limits.max_estimated_cost_micros,
        }
        value = mapping[counter]
        if value is None:
            raise ControlledBudgetLedgerV2Error(
                f"Controlled budget {counter} must have a hard limit"
            )
        return int(value)

    @property
    def reserved_maximums(self) -> Mapping[str, int]:
        return dict(self._amounts)

    def _validated_usage(
        self,
        usage: Mapping[str, Any] | None,
        *,
        provider_started: bool,
    ) -> tuple[dict[str, int], str]:
        if not provider_started:
            if usage is not None:
                raise ControlledBudgetLedgerV2Error(
                    "Controlled provider usage cannot exist before execution"
                )
            return {counter: 0 for counter in _COUNTERS}, "not_started"
        if usage is None:
            return dict(self._amounts), "reserved_estimate"
        if type(usage) is not dict or set(usage) != set(_COUNTERS):
            raise ControlledBudgetLedgerV2Error(
                "Controlled provider usage counters are not closed"
            )
        measured: dict[str, int] = {}
        for counter in _COUNTERS:
            value = usage[counter]
            if (
                type(value) is not int
                or value < 0
                or value > self._amounts[counter]
            ):
                raise ControlledBudgetLedgerV2Error(
                    f"Controlled provider {counter} usage exceeds its reservation"
                )
            measured[counter] = value
        return measured, "verified_provider_evidence"

    def _validated_usage_evidence(
        self,
        row: sqlite3.Row,
        usage_evidence: bytes | None,
        *,
        outcome: str,
    ) -> tuple[dict[str, int], str, str | None, bytes | None]:
        provider_started = bool(row["provider_started"])
        if not provider_started:
            if usage_evidence is not None:
                raise ControlledBudgetLedgerV2Error(
                    "Controlled usage evidence cannot precede the provider call"
                )
            return (
                {counter: 0 for counter in _COUNTERS},
                "not_started",
                None,
                None,
            )
        if usage_evidence is None:
            if outcome == "success":
                raise ControlledBudgetLedgerV2Error(
                    "successful Controlled execution requires verified provider usage"
                )
            return dict(self._amounts), "reserved_estimate", None, None
        if type(usage_evidence) is not bytes:
            raise ControlledBudgetLedgerV2Error(
                "Controlled provider usage evidence must be canonical bytes"
            )
        try:
            evidence = _strict_json_loads(
                usage_evidence, label="Controlled provider usage evidence"
            )
        except Exception as exc:
            raise ControlledBudgetLedgerV2Error(
                "Controlled provider usage evidence is not strict JSON"
            ) from exc
        expected_fields = _PROVIDER_USAGE_BINDING_FIELDS | set(_COUNTERS) | {
            "usage_digest"
        }
        if (
            set(evidence) != expected_fields
            or _canonical_bytes(evidence) != usage_evidence
            or evidence.get("format") != _PROVIDER_USAGE_FORMAT
            or evidence.get("environment") != self._environment
            or evidence.get("budget_id") != row["budget_id"]
            or evidence.get("reservation_id") != row["reservation_id"]
            or evidence.get("idempotency_key") != row["idempotency_key"]
            or evidence.get("snapshot_digest") != row["snapshot_digest"]
            or evidence.get("projection_digest") != row["projection_digest"]
        ):
            raise ControlledBudgetLedgerV2Error(
                "Controlled provider usage evidence binding is invalid"
            )
        try:
            for field in ("manifest_digest", "contents_digest", "usage_digest"):
                _require_digest(evidence[field], f"Controlled usage {field}")
        except Exception as exc:
            raise ControlledBudgetLedgerV2Error(
                "Controlled provider usage evidence digest is invalid"
            ) from exc
        body = {key: value for key, value in evidence.items() if key != "usage_digest"}
        if evidence["usage_digest"] != canonical_authority_digest(body):
            raise ControlledBudgetLedgerV2Error(
                "Controlled provider usage evidence digest does not verify"
            )
        counters = {counter: evidence[counter] for counter in _COUNTERS}
        charged, source = self._validated_usage(counters, provider_started=True)
        return charged, source, evidence["usage_digest"], usage_evidence

    def reserve(
        self,
        context: Mapping[str, Any],
        *,
        snapshot_digest: str,
        projection_digest: str,
    ) -> _ControlledBudgetReservationV2:
        """Atomically reserve hard capacity and a persistent experiment lease."""

        if type(context) is not dict:
            raise ControlledBudgetLedgerV2Error(
                "Controlled reservation requires an exact execution context"
            )
        handoff_id = context.get("trader_authorization_id")
        idempotency_key = context.get("idempotency_key")
        if any(
            type(value) is not str or not value.startswith("sha256:")
            for value in (
                handoff_id,
                idempotency_key,
                snapshot_digest,
                projection_digest,
            )
        ):
            raise ControlledBudgetLedgerV2Error(
                "Controlled reservation identities require canonical digests"
            )
        reservation_id = canonical_authority_digest(
            {
                "format": "controlled-budget-reservation/v2",
                "environment": self._environment,
                "budget_id": self._budget.budget_id,
                "handoff_id": handoff_id,
                "idempotency_key": idempotency_key,
                "snapshot_digest": snapshot_digest,
                "projection_digest": projection_digest,
            }
        )
        lease_id = str(uuid.uuid4())
        now = _aware_utc(self._clock)
        expires = now + timedelta(seconds=self._budget.limits.lease_ttl_seconds)
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            recovery = connection.execute(
                "SELECT 1 FROM controlled_budget_reservations WHERE "
                "environment=? AND state='RECOVERY_REQUIRED' LIMIT 1",
                (self._environment,),
            ).fetchone()
            if recovery is not None:
                raise ControlledBudgetLedgerV2Error(
                    "Controlled budget recovery is required before new execution"
                )
            existing = connection.execute(
                "SELECT * FROM controlled_budget_reservations WHERE "
                "environment=? AND reservation_id=?",
                (self._environment, reservation_id),
            ).fetchone()
            if existing is not None:
                raise ControlledBudgetLedgerV2Error(
                    "Controlled budget reservation is already consumed"
                )
            connection.execute(
                "UPDATE research_experiment_leases SET released_at=? WHERE "
                "budget_id=? AND released_at IS NULL AND expires_at < ?",
                (now.isoformat(), self._budget.budget_id, now.isoformat()),
            )
            active = connection.execute(
                "SELECT COUNT(*) FROM research_experiment_leases WHERE "
                "budget_id=? AND released_at IS NULL",
                (self._budget.budget_id,),
            ).fetchone()[0]
            if int(active) >= self._budget.limits.max_parallel_experiments:
                raise ControlledBudgetLedgerV2Error(
                    "Controlled concurrent experiment budget is exhausted"
                )
            for counter in _COUNTERS:
                used_row = connection.execute(
                    "SELECT used FROM research_budget_ledger WHERE "
                    "budget_id=? AND counter=?",
                    (self._budget.budget_id, counter),
                ).fetchone()
                used = 0 if used_row is None else int(used_row[0])
                reserved = connection.execute(
                    f"SELECT COALESCE(SUM(reserved_{counter}), 0) FROM "
                    "controlled_budget_reservations WHERE environment=? AND "
                    "state IN ('RESERVED','EXECUTING','RECOVERY_REQUIRED')",
                    (self._environment,),
                ).fetchone()[0]
                if used + int(reserved) + self._amounts[counter] > self._limit(counter):
                    raise ControlledBudgetLedgerV2Error(
                        f"Controlled {counter} budget is exhausted before provider call"
                    )
            connection.execute(
                "INSERT INTO research_experiment_leases VALUES (?, ?, ?, ?, ?, NULL)",
                (
                    lease_id,
                    self._budget.budget_id,
                    now.isoformat(),
                    expires.isoformat(),
                    now.isoformat(),
                ),
            )
            amount_columns = ", ".join(f"reserved_{item}" for item in _COUNTERS)
            placeholders = ", ".join("?" for _ in _COUNTERS)
            connection.execute(
                "INSERT INTO controlled_budget_reservations "
                "(environment,reservation_id,budget_id,idempotency_key,handoff_id,"
                "lease_id,snapshot_digest,projection_digest,state,provider_started,"
                f"{amount_columns},reserved_at,executing_at,settled_at,"
                "terminal_outcome,error_class) VALUES "
                f"(?,?,?,?,?,?,?,?,'RESERVED',0,{placeholders},?,NULL,NULL,NULL,NULL)",
                (
                    self._environment,
                    reservation_id,
                    self._budget.budget_id,
                    idempotency_key,
                    handoff_id,
                    lease_id,
                    snapshot_digest,
                    projection_digest,
                    *(self._amounts[item] for item in _COUNTERS),
                    now.isoformat(),
                ),
            )
            connection.execute("COMMIT")
        except Exception:
            try:
                connection.execute("ROLLBACK")
            except sqlite3.Error:
                pass
            raise
        finally:
            connection.close()
        return _ControlledBudgetReservationV2(
            reservation_id=reservation_id,
            lease_id=lease_id,
            budget_id=self._budget.budget_id,
            idempotency_key=idempotency_key,
            _token=_RESERVATION_TOKEN,
        )

    def mark_executing(self, reservation: _ControlledBudgetReservationV2) -> None:
        if type(reservation) is not _ControlledBudgetReservationV2:
            raise ControlledBudgetLedgerV2Error(
                "exact committed Controlled budget reservation required"
            )
        now = _aware_utc(self._clock).isoformat()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            changed = connection.execute(
                "UPDATE controlled_budget_reservations SET state='EXECUTING', "
                "provider_started=1, executing_at=? WHERE environment=? AND "
                "reservation_id=? AND state='RESERVED' AND provider_started=0",
                (now, self._environment, reservation.reservation_id),
            ).rowcount
            if changed != 1:
                connection.execute("ROLLBACK")
                raise ControlledBudgetLedgerV2Error(
                    "Controlled budget reservation is not executable"
                )
            connection.execute("COMMIT")

    def settle(
        self,
        reservation: _ControlledBudgetReservationV2,
        *,
        outcome: str,
        error_class: str | None = None,
        usage_evidence: bytes | None = None,
    ) -> None:
        if (
            type(reservation) is not _ControlledBudgetReservationV2
            or outcome not in _TERMINAL_OUTCOMES
            or (error_class is not None and type(error_class) is not str)
        ):
            raise ControlledBudgetLedgerV2Error(
                "Controlled budget settlement arguments are invalid"
            )
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM controlled_budget_reservations WHERE "
                "environment=? AND reservation_id=?",
                (self._environment, reservation.reservation_id),
            ).fetchone()
            target = "SUCCEEDED" if outcome == "success" else "FAILED"
            if (
                row is not None
                and row["state"] == target
                and row["terminal_outcome"] == outcome
            ):
                connection.execute("COMMIT")
                return
            if row is None or row["state"] not in {"RESERVED", "EXECUTING"}:
                raise ControlledBudgetLedgerV2Error(
                    "Controlled budget reservation cannot be settled"
                )
            provider_started = bool(row["provider_started"])
            (
                charged,
                usage_source,
                usage_evidence_digest,
                canonical_usage_evidence,
            ) = self._validated_usage_evidence(
                row,
                usage_evidence,
                outcome=outcome,
            )
            if provider_started:
                for counter in _COUNTERS:
                    amount = charged[counter]
                    connection.execute(
                        "INSERT INTO research_budget_ledger "
                        "(budget_id,counter,used,updated_at) VALUES (?,?,?,?) "
                        "ON CONFLICT(budget_id,counter) DO UPDATE SET "
                        "used=used+excluded.used,updated_at=excluded.updated_at",
                        (
                            self._budget.budget_id,
                            counter,
                            amount,
                            _aware_utc(self._clock).isoformat(),
                        ),
                    )
            settled_at = _aware_utc(self._clock).isoformat()
            connection.execute(
                "UPDATE research_experiment_leases SET released_at=? WHERE "
                "lease_id=? AND budget_id=? AND released_at IS NULL",
                (settled_at, reservation.lease_id, self._budget.budget_id),
            )
            connection.execute(
                "UPDATE controlled_budget_reservations SET state=?,settled_at=?,"
                "terminal_outcome=?,error_class=?,usage_source=?,"
                "usage_evidence_digest=?,usage_evidence=?,"
                + ",".join(f"charged_{counter}=?" for counter in _COUNTERS)
                + " WHERE environment=? AND reservation_id=?",
                (
                    target,
                    settled_at,
                    outcome,
                    error_class,
                    usage_source,
                    usage_evidence_digest,
                    canonical_usage_evidence,
                    *(charged[counter] for counter in _COUNTERS),
                    self._environment,
                    reservation.reservation_id,
                ),
            )
            connection.execute("COMMIT")
        except Exception as exc:
            try:
                connection.execute("ROLLBACK")
            except sqlite3.Error:
                pass
            self._mark_recovery_required(reservation.reservation_id, exc)
            raise
        finally:
            connection.close()

    def _mark_recovery_required(
        self, reservation_id: str, error: BaseException
    ) -> None:
        try:
            with self._connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                connection.execute(
                    "UPDATE controlled_budget_reservations SET "
                    "state='RECOVERY_REQUIRED',error_class=? WHERE environment=? "
                    "AND reservation_id=? AND state IN ('RESERVED','EXECUTING')",
                    (type(error).__name__, self._environment, reservation_id),
                )
                connection.execute("COMMIT")
        except sqlite3.Error:
            pass

    def recover_unfinished(self) -> int:
        """Fail reserved work and quarantine unknown post-provider outcomes."""

        now = _aware_utc(self._clock).isoformat()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            reserved = connection.execute(
                "SELECT lease_id FROM controlled_budget_reservations WHERE "
                "environment=? AND state='RESERVED'",
                (self._environment,),
            ).fetchall()
            for row in reserved:
                connection.execute(
                    "UPDATE research_experiment_leases SET released_at=? WHERE "
                    "lease_id=? AND released_at IS NULL",
                    (now, row["lease_id"]),
                )
            failed = connection.execute(
                "UPDATE controlled_budget_reservations SET state='FAILED',"
                "settled_at=?,terminal_outcome='commit_error',"
                "error_class='RecoveredBeforeProviderCall',"
                "usage_source='not_started',"
                + ",".join(f"charged_{counter}=0" for counter in _COUNTERS)
                + " WHERE environment=? "
                "AND state='RESERVED'",
                (now, self._environment),
            ).rowcount
            unknown = connection.execute(
                "UPDATE controlled_budget_reservations SET "
                "state='RECOVERY_REQUIRED',error_class='UnknownProviderOutcome' "
                "WHERE environment=? AND state='EXECUTING'",
                (self._environment,),
            ).rowcount
            connection.execute("COMMIT")
            return int(failed) + int(unknown)

    def settle_recovery_required(self, reservation_id: str) -> None:
        """Conservatively charge and release one unknown provider outcome."""

        now = _aware_utc(self._clock).isoformat()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM controlled_budget_reservations WHERE "
                "environment=? AND reservation_id=? AND state='RECOVERY_REQUIRED'",
                (self._environment, reservation_id),
            ).fetchone()
            if row is None:
                connection.execute("ROLLBACK")
                raise ControlledBudgetLedgerV2Error(
                    "Controlled recovery reservation is absent"
                )
            if bool(row["provider_started"]):
                for counter in _COUNTERS:
                    connection.execute(
                        "INSERT INTO research_budget_ledger "
                        "(budget_id,counter,used,updated_at) VALUES (?,?,?,?) "
                        "ON CONFLICT(budget_id,counter) DO UPDATE SET "
                        "used=used+excluded.used,updated_at=excluded.updated_at",
                        (
                            self._budget.budget_id,
                            counter,
                            int(row[f"reserved_{counter}"]),
                            now,
                        ),
                    )
            connection.execute(
                "UPDATE research_experiment_leases SET released_at=? WHERE "
                "lease_id=? AND released_at IS NULL",
                (now, row["lease_id"]),
            )
            connection.execute(
                "UPDATE controlled_budget_reservations SET state='FAILED',"
                "settled_at=?,terminal_outcome='provider_error',"
                "error_class='RecoveredUnknownProviderOutcome',"
                "usage_source='reserved_estimate',"
                + ",".join(
                    f"charged_{counter}=reserved_{counter}" for counter in _COUNTERS
                )
                + " WHERE "
                "environment=? AND reservation_id=?",
                (now, self._environment, reservation_id),
            )
            connection.execute("COMMIT")

    def settlement(self, reservation_id: str) -> Mapping[str, Any] | None:
        """Return durable accounting evidence for audit and recovery tooling."""

        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM controlled_budget_reservations WHERE "
                "environment=? AND reservation_id=?",
                (self._environment, reservation_id),
            ).fetchone()
            if row is None:
                return None
            return {
                "state": str(row["state"]),
                "terminal_outcome": row["terminal_outcome"],
                "usage_source": row["usage_source"],
                "usage_evidence_digest": row["usage_evidence_digest"],
                "charged": {
                    counter: row[f"charged_{counter}"] for counter in _COUNTERS
                },
            }

    def state(self, reservation_id: str) -> str | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT state FROM controlled_budget_reservations WHERE "
                "environment=? AND reservation_id=?",
                (self._environment, reservation_id),
            ).fetchone()
            return None if row is None else str(row["state"])


__all__ = [
    "CONTROLLED_BUDGET_LEDGER_BACKEND",
    "ControlledBudgetLedgerV2Error",
    "ControlledPersistentBudgetLedgerV2",
]
