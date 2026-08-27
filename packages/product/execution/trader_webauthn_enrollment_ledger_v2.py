"""Durable one-use ledger for WebAuthn registration ceremonies.

The browser response is verified by ``trader_webauthn_enrollment_v2``.  This
module owns only request issuance and the atomic expiry/one-use transition so
that replaying an otherwise valid registration transcript cannot produce a
second root activation proposal.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from execution.exact_four_codec import _canonical_bytes


ENROLLMENT_LEDGER_BACKEND = "SQLiteTraderWebAuthnEnrollmentLedger/v2"


class TraderWebAuthnEnrollmentLedgerV2Error(ValueError):
    """The enrollment request ledger could not preserve one-use semantics."""


class SQLiteTraderWebAuthnEnrollmentLedgerV2:
    """Append-only issued requests plus one atomic terminal consumption."""

    __slots__ = ("_path",)

    def __init__(self, path: Path) -> None:
        if not isinstance(path, Path) or not path.is_absolute():
            raise TraderWebAuthnEnrollmentLedgerV2Error(
                "enrollment ledger path must be absolute"
            )
        self._path = path
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    @property
    def path(self) -> Path:
        return self._path

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(
            str(self._path), timeout=10.0, isolation_level=None
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout = 10000")
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                PRAGMA journal_mode = WAL;
                PRAGMA synchronous = FULL;
                CREATE TABLE IF NOT EXISTS enrollment_requests (
                    request_id TEXT PRIMARY KEY,
                    request_digest TEXT NOT NULL UNIQUE,
                    environment TEXT NOT NULL,
                    challenge_base64url TEXT NOT NULL UNIQUE,
                    expires_at TEXT NOT NULL,
                    canonical_request BLOB NOT NULL,
                    status TEXT NOT NULL CHECK(status IN ('ISSUED','CONSUMED')),
                    consumed_at TEXT,
                    transcript_digest TEXT UNIQUE,
                    proposal_digest TEXT UNIQUE
                );
                CREATE TRIGGER IF NOT EXISTS enrollment_requests_no_delete
                    BEFORE DELETE ON enrollment_requests BEGIN
                    SELECT RAISE(ABORT, 'enrollment requests are immutable');
                    END;
                CREATE TRIGGER IF NOT EXISTS enrollment_requests_identity_no_update
                    BEFORE UPDATE OF request_id, request_digest, environment,
                        challenge_base64url, expires_at, canonical_request
                    ON enrollment_requests BEGIN
                    SELECT RAISE(ABORT, 'enrollment request identity is immutable');
                    END;
                """
            )

    def issue(self, request: dict[str, Any]) -> None:
        try:
            with self._connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                connection.execute(
                    "INSERT INTO enrollment_requests VALUES "
                    "(?, ?, ?, ?, ?, ?, 'ISSUED', NULL, NULL, NULL)",
                    (
                        request["request_id"],
                        request["request_digest"],
                        request["environment"],
                        request["challenge_base64url"],
                        request["expires_at"],
                        _canonical_bytes(request),
                    ),
                )
                connection.execute("COMMIT")
        except (KeyError, sqlite3.Error) as exc:
            raise TraderWebAuthnEnrollmentLedgerV2Error(
                "enrollment request identity is duplicate or cannot be recorded"
            ) from exc

    def consume(
        self,
        request: dict[str, Any],
        *,
        consumed_at: str,
        transcript_digest: str,
        proposal_digest: str,
    ) -> None:
        """Atomically compare exact request bytes, expiry, and one-use state."""

        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM enrollment_requests WHERE request_id = ?",
                (request["request_id"],),
            ).fetchone()
            if row is None:
                raise TraderWebAuthnEnrollmentLedgerV2Error(
                    "enrollment request is not present in the governed ledger"
                )
            if (
                row["status"] != "ISSUED"
                or bytes(row["canonical_request"]) != _canonical_bytes(request)
                or row["request_digest"] != request["request_digest"]
                or row["environment"] != request["environment"]
                or row["challenge_base64url"]
                != request["challenge_base64url"]
                or row["expires_at"] != request["expires_at"]
            ):
                raise TraderWebAuthnEnrollmentLedgerV2Error(
                    "enrollment request is consumed or differs from issued bytes"
                )
            if consumed_at > row["expires_at"]:
                raise TraderWebAuthnEnrollmentLedgerV2Error(
                    "enrollment request expired before registration verification"
                )
            cursor = connection.execute(
                "UPDATE enrollment_requests SET status='CONSUMED', "
                "consumed_at=?, transcript_digest=?, proposal_digest=? "
                "WHERE request_id=? AND status='ISSUED'",
                (
                    consumed_at,
                    transcript_digest,
                    proposal_digest,
                    request["request_id"],
                ),
            )
            if cursor.rowcount != 1:
                raise TraderWebAuthnEnrollmentLedgerV2Error(
                    "enrollment request lost its one-use reservation"
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


__all__ = [
    "ENROLLMENT_LEDGER_BACKEND",
    "SQLiteTraderWebAuthnEnrollmentLedgerV2",
    "TraderWebAuthnEnrollmentLedgerV2Error",
]
