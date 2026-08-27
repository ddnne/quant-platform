"""Atomic one-use challenge, credential counter, and Trader event ledger."""

from __future__ import annotations

import sqlite3
import uuid
from datetime import timedelta
from pathlib import Path
from typing import Any

from execution.exact_four_codec import (
    ExactFourAuthorityPending,
    _canonical_bytes,
    _strict_json_loads,
    canonical_authority_digest,
)
from execution.trader_webauthn_registry_v2 import (
    TRADER_COMMITTED_HANDOFF_FORMAT,
    TRADER_LEDGER_BACKEND,
    TRADER_LEDGER_EVENT_FORMAT,
    ExactFourTraderAuthorityV2Error,
    ExactFourTraderCredentialRegistryV2,
    ExactFourTraderCredentialV2,
)


TRADER_RP_REGISTRY_FORMAT = "exact-four-trader-rp-registry/v2"
TRADER_CREDENTIAL_REGISTRY_FORMAT = "exact-four-trader-credential-registry/v2"
TRADER_CHALLENGE_FORMAT = "exact-four-trader-webauthn-challenge/v2"
TRADER_ASSERTION_FORMAT = "exact-four-trader-webauthn-assertion/v2"
TRADER_LEDGER_EVENT_FORMAT = "exact-four-trader-ledger-event/v2"
TRADER_COMMITTED_HANDOFF_FORMAT = "exact-four-trader-committed-handoff/v2"
TRADER_VERIFIER_BACKEND = "ExactFourTraderWebAuthnVerifier/v2"
TRADER_LEDGER_BACKEND = "ExactFourTraderOneUseCounterEventLedger/v2"
TRADER_AUTHORITY_LIVE_STATE = (
    "PENDING_HUMAN_ENROLLMENT_AND_PROTECTED_PRINCIPAL_STORE"
)
_AUTHORITY_CONSTRUCTION_TOKEN = object()
_CHALLENGE_BYTES = 32
_MAX_CLOCK_SKEW = timedelta(seconds=5)
class SQLiteExactFourTraderLedgerV2:
    """Authority-owned atomic challenge/counter/append-only decision store."""

    __slots__ = ("_path", "_environment", "_registry_digest")

    def __init__(
        self,
        path: Path,
        *,
        environment: str,
        credentials: ExactFourTraderCredentialRegistryV2,
        _token: object,
    ) -> None:
        if _token is not _AUTHORITY_CONSTRUCTION_TOKEN:
            raise ExactFourAuthorityPending(TRADER_AUTHORITY_LIVE_STATE)
        if not isinstance(path, Path) or not path.is_absolute():
            raise ExactFourTraderAuthorityV2Error(
                "Trader authority ledger requires an absolute authority-owned path"
            )
        self._path = path
        self._environment = environment
        self._registry_digest = credentials.registry_digest
        self._initialize(credentials)

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(
            str(self._path),
            timeout=10.0,
            isolation_level=None,
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 10000")
        return connection

    def _initialize(
        self, credentials: ExactFourTraderCredentialRegistryV2
    ) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.executescript(
                """
                PRAGMA journal_mode = WAL;
                PRAGMA synchronous = FULL;
                CREATE TABLE IF NOT EXISTS authority_metadata (
                    environment TEXT PRIMARY KEY,
                    credential_registry_digest TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS credential_counters (
                    environment TEXT NOT NULL,
                    credential_id TEXT NOT NULL,
                    public_key_digest TEXT NOT NULL,
                    registry_digest TEXT NOT NULL,
                    counter_mode TEXT NOT NULL,
                    sign_count INTEGER NOT NULL CHECK(sign_count >= 0),
                    PRIMARY KEY(environment, credential_id)
                );
                CREATE TABLE IF NOT EXISTS challenges (
                    environment TEXT NOT NULL,
                    challenge_id TEXT NOT NULL,
                    challenge_digest TEXT NOT NULL UNIQUE,
                    approval_subject_id TEXT NOT NULL,
                    one_use_key TEXT NOT NULL UNIQUE,
                    expires_at TEXT NOT NULL,
                    canonical_challenge BLOB NOT NULL,
                    status TEXT NOT NULL CHECK(status IN ('AVAILABLE','CONSUMED')),
                    consumed_at TEXT,
                    PRIMARY KEY(environment, challenge_id)
                );
                CREATE TABLE IF NOT EXISTS trader_events (
                    environment TEXT NOT NULL,
                    sequence INTEGER NOT NULL,
                    event_id TEXT NOT NULL UNIQUE,
                    event_digest TEXT NOT NULL UNIQUE,
                    prior_event_digest TEXT,
                    request_digest TEXT NOT NULL UNIQUE,
                    approval_subject_id TEXT NOT NULL,
                    one_use_key TEXT NOT NULL UNIQUE,
                    credential_id TEXT NOT NULL,
                    prior_sign_count INTEGER NOT NULL,
                    result_sign_count INTEGER NOT NULL,
                    canonical_event BLOB NOT NULL,
                    PRIMARY KEY(environment, sequence)
                );
                CREATE TABLE IF NOT EXISTS trader_decisions (
                    environment TEXT NOT NULL,
                    authorization_id TEXT NOT NULL UNIQUE,
                    request_digest TEXT NOT NULL UNIQUE,
                    approval_subject_id TEXT NOT NULL UNIQUE,
                    assertion_digest TEXT NOT NULL UNIQUE,
                    event_digest TEXT NOT NULL UNIQUE,
                    canonical_authorization BLOB NOT NULL,
                    PRIMARY KEY(environment, authorization_id),
                    FOREIGN KEY(event_digest) REFERENCES trader_events(event_digest)
                );
                CREATE TRIGGER IF NOT EXISTS trader_events_no_update
                    BEFORE UPDATE ON trader_events BEGIN
                    SELECT RAISE(ABORT, 'trader events are immutable');
                    END;
                CREATE TRIGGER IF NOT EXISTS trader_events_no_delete
                    BEFORE DELETE ON trader_events BEGIN
                    SELECT RAISE(ABORT, 'trader events are immutable');
                    END;
                CREATE TRIGGER IF NOT EXISTS trader_decisions_no_update
                    BEFORE UPDATE ON trader_decisions BEGIN
                    SELECT RAISE(ABORT, 'trader decisions are immutable');
                    END;
                CREATE TRIGGER IF NOT EXISTS trader_decisions_no_delete
                    BEFORE DELETE ON trader_decisions BEGIN
                    SELECT RAISE(ABORT, 'trader decisions are immutable');
                    END;
                """
            )
            connection.execute("BEGIN IMMEDIATE")
            try:
                row = connection.execute(
                    "SELECT credential_registry_digest FROM authority_metadata "
                    "WHERE environment = ?",
                    (self._environment,),
                ).fetchone()
                if row is None:
                    connection.execute(
                        "INSERT INTO authority_metadata VALUES (?, ?)",
                        (self._environment, credentials.registry_digest),
                    )
                elif row["credential_registry_digest"] != credentials.registry_digest:
                    raise ExactFourTraderAuthorityV2Error(
                        "credential registry generation changed without migration"
                    )
                for credential in credentials.credentials:
                    if credential.environment != self._environment:
                        continue
                    existing = connection.execute(
                        "SELECT * FROM credential_counters WHERE environment = ? "
                        "AND credential_id = ?",
                        (self._environment, credential.credential_id_base64url),
                    ).fetchone()
                    expected = (
                        credential.public_key_digest,
                        credentials.registry_digest,
                        credential.counter_mode,
                    )
                    if existing is None:
                        connection.execute(
                            "INSERT INTO credential_counters VALUES (?, ?, ?, ?, ?, ?)",
                            (
                                self._environment,
                                credential.credential_id_base64url,
                                *expected,
                                credential.initial_sign_count,
                            ),
                        )
                    elif (
                        existing["public_key_digest"],
                        existing["registry_digest"],
                        existing["counter_mode"],
                    ) != expected:
                        raise ExactFourTraderAuthorityV2Error(
                            "stored credential identity differs from governed registry"
                        )
                connection.execute("COMMIT")
            except Exception:
                connection.execute("ROLLBACK")
                raise

    def register_challenge(self, document: dict[str, Any]) -> None:
        canonical = _canonical_bytes(document)
        try:
            with self._connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                connection.execute(
                    "INSERT INTO challenges VALUES (?, ?, ?, ?, ?, ?, ?, 'AVAILABLE', NULL)",
                    (
                        document["environment"],
                        document["challenge_id"],
                        document["challenge_digest"],
                        document["approval_subject_id"],
                        document["one_use_key"],
                        document["expires_at"],
                        canonical,
                    ),
                )
                connection.execute("COMMIT")
        except sqlite3.Error as exc:
            raise ExactFourTraderAuthorityV2Error(
                "challenge identity is already issued or ledger registration failed"
            ) from exc

    def _decision_for_request(
        self, connection: sqlite3.Connection, request_digest: str
    ) -> dict[str, Any] | None:
        row = connection.execute(
            "SELECT canonical_authorization FROM trader_decisions "
            "WHERE environment = ? AND request_digest = ?",
            (self._environment, request_digest),
        ).fetchone()
        if row is None:
            return None
        return _strict_json_loads(
            bytes(row["canonical_authorization"]),
            label="stored Trader authorization decision",
        )

    def commit_verified_assertion(
        self,
        *,
        ready_response_digest: str,
        approval_subject: dict[str, Any],
        challenge: dict[str, Any],
        assertion: dict[str, Any],
        credential: ExactFourTraderCredentialV2,
        credential_registry: ExactFourTraderCredentialRegistryV2,
        committed_at: str,
    ) -> dict[str, Any]:
        """Consume challenge, CAS counter, append event, and store decision once."""

        request_body = {
            "format": "exact-four-trader-authority-request/v2",
            "environment": self._environment,
            "approval_subject_id": challenge["approval_subject_id"],
            "ready_authority_response_digest": ready_response_digest,
            "challenge_digest": challenge["challenge_digest"],
            "assertion_digest": assertion["assertion_digest"],
            "credential_registry_digest": credential_registry.registry_digest,
            "credential_public_key_digest": credential.public_key_digest,
        }
        request_digest = canonical_authority_digest(request_body)
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            prior = self._decision_for_request(connection, request_digest)
            if prior is not None:
                connection.execute("COMMIT")
                return prior
            challenge_row = connection.execute(
                "SELECT * FROM challenges WHERE environment = ? AND challenge_id = ?",
                (self._environment, challenge["challenge_id"]),
            ).fetchone()
            if (
                challenge_row is None
                or challenge_row["status"] != "AVAILABLE"
                or bytes(challenge_row["canonical_challenge"])
                != _canonical_bytes(challenge)
            ):
                raise ExactFourTraderAuthorityV2Error(
                    "WebAuthn challenge is unavailable, consumed, or not ledger-identical"
                )
            counter = connection.execute(
                "SELECT * FROM credential_counters WHERE environment = ? "
                "AND credential_id = ?",
                (self._environment, credential.credential_id_base64url),
            ).fetchone()
            if (
                counter is None
                or counter["public_key_digest"] != credential.public_key_digest
                or counter["registry_digest"] != credential_registry.registry_digest
                or counter["counter_mode"] != credential.counter_mode
            ):
                raise ExactFourTraderAuthorityV2Error(
                    "credential counter state is not registry-bound"
                )
            prior_count = int(counter["sign_count"])
            asserted_count = assertion["sign_count"]
            if credential.counter_mode == "COUNTING":
                if type(asserted_count) is not int or asserted_count <= prior_count:
                    raise ExactFourTraderAuthorityV2Error(
                        "WebAuthn signature counter did not advance"
                    )
                updated = connection.execute(
                    "UPDATE credential_counters SET sign_count = ? WHERE "
                    "environment = ? AND credential_id = ? AND sign_count = ?",
                    (
                        asserted_count,
                        self._environment,
                        credential.credential_id_base64url,
                        prior_count,
                    ),
                ).rowcount
                if updated != 1:
                    raise ExactFourTraderAuthorityV2Error(
                        "WebAuthn signature counter CAS failed"
                    )
            elif prior_count != 0 or asserted_count != 0:
                raise ExactFourTraderAuthorityV2Error(
                    "counterless WebAuthn credential must remain at zero"
                )
            consumed = connection.execute(
                "UPDATE challenges SET status = 'CONSUMED', consumed_at = ? "
                "WHERE environment = ? AND challenge_id = ? AND status = 'AVAILABLE'",
                (committed_at, self._environment, challenge["challenge_id"]),
            ).rowcount
            if consumed != 1:
                raise ExactFourTraderAuthorityV2Error(
                    "WebAuthn challenge one-use CAS failed"
                )
            tail = connection.execute(
                "SELECT sequence, event_digest FROM trader_events WHERE "
                "environment = ? ORDER BY sequence DESC LIMIT 1",
                (self._environment,),
            ).fetchone()
            sequence = 1 if tail is None else int(tail["sequence"]) + 1
            prior_event_digest = None if tail is None else tail["event_digest"]
            event_body = {
                "format": TRADER_LEDGER_EVENT_FORMAT,
                "environment": self._environment,
                "ledger_backend_id": TRADER_LEDGER_BACKEND,
                "sequence": sequence,
                "event_id": str(uuid.uuid4()),
                "prior_event_digest": prior_event_digest,
                "request_digest": request_digest,
                "approval_subject_id": challenge["approval_subject_id"],
                "challenge_id": challenge["challenge_id"],
                "challenge_digest": challenge["challenge_digest"],
                "assertion_digest": assertion["assertion_digest"],
                "one_use_key": challenge["one_use_key"],
                "one_use_prior_status": "AVAILABLE",
                "one_use_result_status": "CONSUMED",
                "one_use_cas_status": "APPLIED",
                "credential_id_base64url": credential.credential_id_base64url,
                "credential_registry_generation": credential_registry.generation,
                "credential_registry_digest": credential_registry.registry_digest,
                "counter_mode": credential.counter_mode,
                "prior_sign_count": prior_count,
                "asserted_sign_count": asserted_count,
                "result_sign_count": asserted_count,
                "counter_cas_status": (
                    "APPLIED"
                    if credential.counter_mode == "COUNTING"
                    else "NOT_APPLICABLE"
                ),
                "transaction_status": "COMMITTED",
                "committed_at": committed_at,
                "automatic_promotion": False,
                "mass_research_enabled": False,
                "live_trading_enabled": False,
            }
            event = {
                **event_body,
                "event_digest": canonical_authority_digest(event_body),
            }
            credential_evidence = {
                "format": "exact-four-trader-credential-evidence/v2",
                "environment": self._environment,
                "credential_id_base64url": credential.credential_id_base64url,
                "credential_public_key_digest": credential.public_key_digest,
                "credential_algorithm": credential.algorithm,
                "key_backend": credential.key_backend,
                "credential_registry_generation": credential_registry.generation,
                "credential_registry_digest": credential_registry.registry_digest,
                "rp_policy_digest": credential.rp_policy_digest,
                "counter_mode": credential.counter_mode,
            }
            handoff_body = {
                "format": TRADER_COMMITTED_HANDOFF_FORMAT,
                "environment": self._environment,
                "handoff_status": "COMMITTED",
                "ready_authority_response_digest": ready_response_digest,
                "approval_subject_id": challenge["approval_subject_id"],
                "approval_subject": approval_subject,
                "challenge_evidence": challenge,
                "assertion_evidence": assertion,
                "credential_registry_evidence": credential_evidence,
                "one_use_counter_event": event,
                "issued_at": committed_at,
                "expires_at": challenge["expires_at"],
                "automatic_promotion": False,
                "mass_research_enabled": False,
                "live_trading_enabled": False,
            }
            handoff = {
                **handoff_body,
                "handoff_id": canonical_authority_digest(handoff_body),
            }
            connection.execute(
                "INSERT INTO trader_events VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    self._environment,
                    sequence,
                    event["event_id"],
                    event["event_digest"],
                    prior_event_digest,
                    request_digest,
                    challenge["approval_subject_id"],
                    challenge["one_use_key"],
                    credential.credential_id_base64url,
                    prior_count,
                    asserted_count,
                    _canonical_bytes(event),
                ),
            )
            connection.execute(
                "INSERT INTO trader_decisions VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    self._environment,
                    handoff["handoff_id"],
                    request_digest,
                    challenge["approval_subject_id"],
                    assertion["assertion_digest"],
                    event["event_digest"],
                    _canonical_bytes(handoff),
                ),
            )
            connection.execute("COMMIT")
            return handoff
        except ExactFourTraderAuthorityV2Error:
            connection.execute("ROLLBACK")
            raise
        except sqlite3.Error as exc:
            connection.execute("ROLLBACK")
            raise ExactFourTraderAuthorityV2Error(
                "atomic Trader one-use/counter/event transaction failed"
            ) from exc
        finally:
            connection.close()

    def challenge_status(self, challenge_id: str) -> str | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT status FROM challenges WHERE environment = ? AND challenge_id = ?",
                (self._environment, challenge_id),
            ).fetchone()
            return None if row is None else str(row["status"])

    def credential_sign_count(self, credential_id_base64url: str) -> int | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT sign_count FROM credential_counters WHERE environment = ? "
                "AND credential_id = ?",
                (self._environment, credential_id_base64url),
            ).fetchone()
            return None if row is None else int(row["sign_count"])

    def event_count(self) -> int:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT COUNT(*) AS count FROM trader_events WHERE environment = ?",
                (self._environment,),
            ).fetchone()
            assert row is not None
            return int(row["count"])


__all__ = ["SQLiteExactFourTraderLedgerV2"]
