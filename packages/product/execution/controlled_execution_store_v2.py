"""Atomic reservation, execution-attempt, and immutable artifact store."""

from __future__ import annotations

import hashlib
import os
import socket
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from types import MappingProxyType
from typing import Any, Callable, Mapping, Sequence

from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

from execution.exact_four_codec import (
    ExactFourAuthorityPending,
    _canonical_bytes,
    _strict_json_loads,
    canonical_authority_digest,
)
from execution.trader_webauthn_authority_v2 import (
    ExactFourTraderCredentialRegistryV2,
    ExactFourTraderRelyingPartyRegistryV2,
)
from scripts.local_authority_service import AuthorityRequestContext
from execution.controlled_execution_ipc_v2 import (
    _read_unlinked_readonly_descriptor,
    _recv_framed_request_with_one_fd,
    _unix_peer_uid,
)
from execution.controlled_execution_types_v2 import (
    ControlledExecutionWriterV2Error,
    WrittenExactFourControlledArtifactsV2,
    _ControlledWriterSignerV2,
    _VerifiedBoundedExecutionOutputV2,
    _WRITTEN_BUNDLE_TOKEN,
)
from execution.controlled_execution_runtime_v2 import (
    ControlledExecutionRuntimeV2,
    ControlledProviderTimeoutV2,
)
from execution.controlled_execution_validation_v2 import (
    ControlledExecutionEvidenceValidatorV2,
)


CONTROLLED_WRITER_MANIFEST_FORMAT = "controlled-exact-four-artifact-manifest/v2"
CONTROLLED_WRITER_ARTIFACT_FORMAT = "controlled-exact-four-artifact/v2"
CONTROLLED_WRITER_EVENT_FORMAT = "controlled-execution-authority-event/v2"
CONTROLLED_WRITER_ISSUER = "ControlledExactFourExecutionWriter/v2"
CONTROLLED_TRADER_HANDOFF_OPERATION = (
    "controlled_execution:consume_trader_handoff"
)
CONTROLLED_TRADER_HANDOFF_PURPOSE = "exact_four_one_shot_execution"
CONTROLLED_WRITER_LIVE_STATE = (
    "PENDING_PROTECTED_CONTROLLED_EXECUTION_PRINCIPAL_KEY_STORE_AND_TRADER_PEER"
)
CONTROLLED_WRITER_ARTIFACT_TYPES = (
    "Paper",
    "Risk",
    "Selection",
    "Knowledge",
)
CONTROLLED_EXECUTION_ACTIVATION_PATH = Path(
    "/etc/quant-platform/authorities/controlled_execution/activation.json"
)

_WRITER_CONSTRUCTION_TOKEN = object()

_REQUEST_FIELDS = frozenset(
    {"format", "request_id", "operation", "purpose", "payload"}
)


def _sha256_bytes(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def _require_digest(value: Any, label: str) -> str:
    if (
        type(value) is not str
        or len(value) != 71
        or not value.startswith("sha256:")
        or any(character not in "0123456789abcdef" for character in value[7:])
    ):
        raise ControlledExecutionWriterV2Error(
            f"{label} must be a canonical sha256 digest"
        )
    return value


def _aware_utc(clock: Callable[[], datetime], label: str) -> datetime:
    value = clock()
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise ControlledExecutionWriterV2Error(
            f"{label} must return an exact aware datetime"
        )
    return value.astimezone(timezone.utc)


class SQLiteControlledExecutionWriterV2(ControlledExecutionEvidenceValidatorV2):
    """Peer-authenticated, verify-again, atomic one-shot Controlled service."""

    __slots__ = (
        "_path",
        "environment",
        "_signer",
        "_clock",
        "_trader_uid",
        "_rps",
        "_credentials",
        "_lifecycle",
        "_server_bound",
        "_test_mode",
    )

    def __init__(
        self,
        path: Path,
        *,
        environment: str,
        signer: _ControlledWriterSignerV2,
        clock: Callable[[], datetime],
        trader_uid: int,
        relying_parties: ExactFourTraderRelyingPartyRegistryV2,
        credentials: ExactFourTraderCredentialRegistryV2,
        server_bound: bool,
        test_mode: bool,
        lifecycle: object | None,
        _token: object,
    ) -> None:
        if _token is not _WRITER_CONSTRUCTION_TOKEN:
            raise ExactFourAuthorityPending(CONTROLLED_WRITER_LIVE_STATE)
        if not isinstance(path, Path) or not path.is_absolute():
            raise ControlledExecutionWriterV2Error(
                "Controlled writer requires an absolute authority-owned store path"
            )
        if type(environment) is not str or not environment:
            raise ControlledExecutionWriterV2Error(
                "Controlled writer environment is invalid"
            )
        if type(trader_uid) is not int or trader_uid < 0:
            raise ControlledExecutionWriterV2Error("Trader peer UID is invalid")
        if type(server_bound) is not bool or type(test_mode) is not bool:
            raise ControlledExecutionWriterV2Error(
                "Controlled AuthorityServer binding is invalid"
            )
        if test_mode:
            if lifecycle is not None:
                raise ControlledExecutionWriterV2Error(
                    "test Controlled writer cannot accept a live lifecycle lease"
                )
        elif server_bound is not True:
            raise ExactFourAuthorityPending(
                "live Controlled writer construction requires AuthorityServer binding"
            )
        rp = relying_parties.require(environment)
        for credential in credentials.credentials:
            if credential.environment == environment and (
                credential.rp_policy_digest != rp.policy_digest
            ):
                raise ControlledExecutionWriterV2Error(
                    "Controlled credential registry is not bound to its RP policy"
                )
        self._path = path
        self.environment = environment
        self._signer = signer
        self._clock = clock
        self._trader_uid = trader_uid
        self._rps = relying_parties
        self._credentials = credentials
        self._lifecycle = lifecycle
        self._server_bound = server_bound
        self._test_mode = test_mode
        self._require_live_lifecycle()
        self._initialize()

    def _require_live_lifecycle(self) -> None:
        if self._test_mode:
            return
        from execution.controlled_execution_quiescence_v2 import (
            require_held_controlled_writer_lifecycle_v2,
        )

        require_held_controlled_writer_lifecycle_v2(
            self._lifecycle,
            expected_environment=self.environment,
            expected_store_path=self._path,
        )

    def _require_positive_operation(self) -> None:
        self._require_live_lifecycle()
        if self._server_bound is not True:
            raise ExactFourAuthorityPending(
                "positive Controlled operations require the local AuthorityServer "
                "entrypoint"
            )
        # Preserve the stable facade as the test/launcher gate patch point.
        from execution import controlled_execution_writer_v2 as facade

        facade.require_pinned_finding_ledger_gate()

    @property
    def public_key(self) -> Ed25519PublicKey:
        return self._signer.private_key.public_key()

    def _connect(self) -> sqlite3.Connection:
        self._require_live_lifecycle()
        connection: sqlite3.Connection | None = None
        try:
            connection = sqlite3.connect(
                str(self._path),
                isolation_level=None,
                timeout=10.0,
            )
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA foreign_keys = ON")
            connection.execute("PRAGMA busy_timeout = 10000")
            self._require_live_lifecycle()
            return connection
        except BaseException:
            if connection is not None:
                connection.close()
            raise

    def _initialize(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.executescript(
                """
                PRAGMA journal_mode = WAL;
                PRAGMA synchronous = FULL;
                CREATE TABLE IF NOT EXISTS controlled_authority_metadata (
                    environment TEXT PRIMARY KEY,
                    trader_uid INTEGER NOT NULL,
                    rp_registry_digest TEXT NOT NULL,
                    credential_registry_digest TEXT NOT NULL,
                    writer_key_id TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS controlled_credential_counters (
                    environment TEXT NOT NULL,
                    credential_id TEXT NOT NULL,
                    public_key_digest TEXT NOT NULL,
                    registry_digest TEXT NOT NULL,
                    counter_mode TEXT NOT NULL,
                    sign_count INTEGER NOT NULL CHECK(sign_count >= 0),
                    PRIMARY KEY(environment, credential_id)
                );
                CREATE TABLE IF NOT EXISTS controlled_handoffs (
                    environment TEXT NOT NULL,
                    handoff_id TEXT NOT NULL,
                    handoff_digest TEXT NOT NULL UNIQUE,
                    trader_event_digest TEXT NOT NULL UNIQUE,
                    trader_event_sequence INTEGER NOT NULL,
                    assertion_digest TEXT NOT NULL UNIQUE,
                    one_use_key TEXT NOT NULL UNIQUE,
                    credential_id TEXT NOT NULL,
                    prior_sign_count INTEGER NOT NULL,
                    result_sign_count INTEGER NOT NULL,
                    consume_request_digest TEXT NOT NULL UNIQUE,
                    authority_request_digest TEXT NOT NULL UNIQUE,
                    authenticated_trader_uid INTEGER NOT NULL,
                    authenticated_trader_caller TEXT NOT NULL,
                    canonical_handoff BLOB NOT NULL,
                    status TEXT NOT NULL CHECK(status = 'CONSUMED'),
                    consumed_at TEXT NOT NULL,
                    PRIMARY KEY(environment, handoff_id)
                );
                CREATE TABLE IF NOT EXISTS controlled_execution_attempts (
                    environment TEXT NOT NULL,
                    handoff_id TEXT NOT NULL,
                    outcome TEXT NOT NULL CHECK(outcome IN ('SUCCEEDED','FAILED')),
                    retry_policy TEXT NOT NULL CHECK(retry_policy = 'DENY'),
                    artifact_set_digest TEXT,
                    error_class TEXT,
                    completed_at TEXT NOT NULL,
                    PRIMARY KEY(environment, handoff_id),
                    FOREIGN KEY(environment, handoff_id)
                        REFERENCES controlled_handoffs(environment, handoff_id)
                );
                CREATE TABLE IF NOT EXISTS controlled_artifacts (
                    environment TEXT NOT NULL,
                    handoff_id TEXT NOT NULL,
                    artifact_type TEXT NOT NULL,
                    ordinal INTEGER NOT NULL,
                    artifact_id TEXT NOT NULL UNIQUE,
                    content_digest TEXT NOT NULL,
                    canonical_metadata BLOB NOT NULL,
                    immutable_content BLOB NOT NULL,
                    PRIMARY KEY(environment, handoff_id, artifact_type, ordinal),
                    FOREIGN KEY(environment, handoff_id)
                        REFERENCES controlled_handoffs(environment, handoff_id)
                );
                CREATE TABLE IF NOT EXISTS controlled_writer_events (
                    environment TEXT NOT NULL,
                    sequence INTEGER NOT NULL,
                    event_id TEXT NOT NULL UNIQUE,
                    event_digest TEXT NOT NULL UNIQUE,
                    prior_event_digest TEXT,
                    handoff_id TEXT NOT NULL UNIQUE,
                    write_request_digest TEXT NOT NULL UNIQUE,
                    canonical_event BLOB NOT NULL,
                    PRIMARY KEY(environment, sequence),
                    FOREIGN KEY(environment, handoff_id)
                        REFERENCES controlled_handoffs(environment, handoff_id)
                );
                CREATE TABLE IF NOT EXISTS controlled_manifests (
                    environment TEXT NOT NULL,
                    handoff_id TEXT NOT NULL,
                    manifest_id TEXT NOT NULL UNIQUE,
                    write_request_digest TEXT NOT NULL UNIQUE,
                    controlled_event_digest TEXT NOT NULL UNIQUE,
                    canonical_manifest BLOB NOT NULL,
                    PRIMARY KEY(environment, handoff_id),
                    FOREIGN KEY(controlled_event_digest)
                        REFERENCES controlled_writer_events(event_digest)
                );
                CREATE TRIGGER IF NOT EXISTS controlled_metadata_no_update
                    BEFORE UPDATE ON controlled_authority_metadata BEGIN
                    SELECT RAISE(ABORT, 'Controlled metadata is immutable');
                    END;
                CREATE TRIGGER IF NOT EXISTS controlled_metadata_no_delete
                    BEFORE DELETE ON controlled_authority_metadata BEGIN
                    SELECT RAISE(ABORT, 'Controlled metadata is immutable');
                    END;
                CREATE TRIGGER IF NOT EXISTS controlled_counters_no_delete
                    BEFORE DELETE ON controlled_credential_counters BEGIN
                    SELECT RAISE(ABORT, 'Controlled credential counters cannot be deleted');
                    END;
                CREATE TRIGGER IF NOT EXISTS controlled_handoffs_no_update
                    BEFORE UPDATE ON controlled_handoffs BEGIN
                    SELECT RAISE(ABORT, 'Controlled handoffs are immutable');
                    END;
                CREATE TRIGGER IF NOT EXISTS controlled_handoffs_no_delete
                    BEFORE DELETE ON controlled_handoffs BEGIN
                    SELECT RAISE(ABORT, 'Controlled handoffs are immutable');
                    END;
                CREATE TRIGGER IF NOT EXISTS controlled_attempts_no_update
                    BEFORE UPDATE ON controlled_execution_attempts BEGIN
                    SELECT RAISE(ABORT, 'Controlled execution attempts are immutable');
                    END;
                CREATE TRIGGER IF NOT EXISTS controlled_attempts_no_delete
                    BEFORE DELETE ON controlled_execution_attempts BEGIN
                    SELECT RAISE(ABORT, 'Controlled execution attempts are immutable');
                    END;
                CREATE TRIGGER IF NOT EXISTS controlled_artifacts_no_update
                    BEFORE UPDATE ON controlled_artifacts BEGIN
                    SELECT RAISE(ABORT, 'Controlled artifacts are immutable');
                    END;
                CREATE TRIGGER IF NOT EXISTS controlled_artifacts_no_delete
                    BEFORE DELETE ON controlled_artifacts BEGIN
                    SELECT RAISE(ABORT, 'Controlled artifacts are immutable');
                    END;
                CREATE TRIGGER IF NOT EXISTS controlled_writer_events_no_update
                    BEFORE UPDATE ON controlled_writer_events BEGIN
                    SELECT RAISE(ABORT, 'Controlled writer events are immutable');
                    END;
                CREATE TRIGGER IF NOT EXISTS controlled_writer_events_no_delete
                    BEFORE DELETE ON controlled_writer_events BEGIN
                    SELECT RAISE(ABORT, 'Controlled writer events are immutable');
                    END;
                CREATE TRIGGER IF NOT EXISTS controlled_manifests_no_update
                    BEFORE UPDATE ON controlled_manifests BEGIN
                    SELECT RAISE(ABORT, 'Controlled manifests are immutable');
                    END;
                CREATE TRIGGER IF NOT EXISTS controlled_manifests_no_delete
                    BEFORE DELETE ON controlled_manifests BEGIN
                    SELECT RAISE(ABORT, 'Controlled manifests are immutable');
                    END;
                """
            )
            expected = (
                self._trader_uid,
                self._rps.registry_digest,
                self._credentials.registry_digest,
                self._signer.key_id,
            )
            row = connection.execute(
                "SELECT trader_uid, rp_registry_digest, "
                "credential_registry_digest, writer_key_id FROM "
                "controlled_authority_metadata WHERE environment = ?",
                (self.environment,),
            ).fetchone()
            if row is None:
                connection.execute(
                    "INSERT INTO controlled_authority_metadata VALUES (?, ?, ?, ?, ?)",
                    (self.environment, *expected),
                )
            elif tuple(row) != expected:
                raise ControlledExecutionWriterV2Error(
                    "Controlled authority identity changed without store migration"
                )
            for credential in self._credentials.credentials:
                if credential.environment != self.environment:
                    continue
                existing_counter = connection.execute(
                    "SELECT public_key_digest, registry_digest, counter_mode "
                    "FROM controlled_credential_counters WHERE environment = ? "
                    "AND credential_id = ?",
                    (self.environment, credential.credential_id_base64url),
                ).fetchone()
                counter_identity = (
                    credential.public_key_digest,
                    self._credentials.registry_digest,
                    credential.counter_mode,
                )
                if existing_counter is None:
                    connection.execute(
                        "INSERT INTO controlled_credential_counters VALUES "
                        "(?, ?, ?, ?, ?, ?)",
                        (
                            self.environment,
                            credential.credential_id_base64url,
                            *counter_identity,
                            credential.initial_sign_count,
                        ),
                    )
                elif tuple(existing_counter) != counter_identity:
                    raise ControlledExecutionWriterV2Error(
                        "Controlled credential counter identity changed without migration"
                    )

    def _materialize_artifacts(
        self,
        *,
        handoff: Mapping[str, Any],
        output: _VerifiedBoundedExecutionOutputV2,
    ) -> tuple[tuple[dict[str, Any], bytes], ...]:
        if type(output) is not _VerifiedBoundedExecutionOutputV2:
            raise ControlledExecutionWriterV2Error(
                "internally reverified bounded execution output is required"
            )
        artifacts: list[tuple[dict[str, Any], bytes]] = []
        paper_ids: list[str] = []
        risk_ids: list[str] = []
        common = {
            "environment": self.environment,
            "handoff_id": handoff["handoff_id"],
            "approval_subject_id": handoff["approval_subject_id"],
        }
        for evidence in output.manifest.paper_results:
            content = output.contents[f"Paper:{evidence.ordinal}"]
            body = {
                "format": CONTROLLED_WRITER_ARTIFACT_FORMAT,
                "artifact_type": "Paper",
                "ordinal": evidence.ordinal,
                "plan_id": evidence.plan_id,
                "plan_binding_digest": evidence.plan_binding_digest,
                **common,
                "parent_artifact_ids": [handoff["handoff_id"]],
                "content_digest": self._content_digest(content),
                "result_evidence": evidence.to_dict(),
            }
            metadata = {**body, "artifact_id": canonical_authority_digest(body)}
            paper_ids.append(metadata["artifact_id"])
            artifacts.append((metadata, content))
        for evidence, paper_id in zip(
            output.manifest.risk_results, paper_ids, strict=True
        ):
            content = output.contents[f"Risk:{evidence.ordinal}"]
            body = {
                "format": CONTROLLED_WRITER_ARTIFACT_FORMAT,
                "artifact_type": "Risk",
                "ordinal": evidence.ordinal,
                "plan_id": evidence.plan_id,
                "plan_binding_digest": evidence.plan_binding_digest,
                **common,
                "parent_artifact_ids": [paper_id],
                "content_digest": self._content_digest(content),
                "result_evidence": evidence.to_dict(),
            }
            metadata = {**body, "artifact_id": canonical_authority_digest(body)}
            risk_ids.append(metadata["artifact_id"])
            artifacts.append((metadata, content))
        selection_body = {
            "format": CONTROLLED_WRITER_ARTIFACT_FORMAT,
            "artifact_type": "Selection",
            "ordinal": 0,
            "plan_id": "aggregate-exact-four",
            "plan_binding_digest": output.manifest.exact_four_binding_digest,
            **common,
            "parent_artifact_ids": [*paper_ids, *risk_ids],
            "content_digest": self._content_digest(output.contents["Selection:0"]),
            "result_evidence": output.manifest.aggregate_selection.to_dict(),
        }
        selection = {
            **selection_body,
            "artifact_id": canonical_authority_digest(selection_body),
        }
        artifacts.append((selection, output.contents["Selection:0"]))
        knowledge_body = {
            "format": CONTROLLED_WRITER_ARTIFACT_FORMAT,
            "artifact_type": "Knowledge",
            "ordinal": 0,
            "plan_id": "aggregate-exact-four",
            "plan_binding_digest": selection["plan_binding_digest"],
            **common,
            "parent_artifact_ids": [selection["artifact_id"]],
            "content_digest": self._content_digest(output.contents["Knowledge:0"]),
            "result_evidence": output.manifest.knowledge_artifact.to_dict(),
        }
        knowledge = {
            **knowledge_body,
            "artifact_id": canonical_authority_digest(knowledge_body),
        }
        artifacts.append((knowledge, output.contents["Knowledge:0"]))
        return tuple(artifacts)

    @staticmethod
    def _content_map(
        artifacts: tuple[tuple[dict[str, Any], bytes], ...]
    ) -> dict[str, bytes]:
        return {
            f"{metadata['artifact_type']}:{metadata['ordinal']}": content
            for metadata, content in artifacts
        }

    def _load_committed_result(
        self,
        connection: sqlite3.Connection,
        *,
        handoff_id: str,
    ) -> WrittenExactFourControlledArtifactsV2 | None:
        manifest_row = connection.execute(
            "SELECT canonical_manifest FROM controlled_manifests WHERE "
            "environment = ? AND handoff_id = ?",
            (self.environment, handoff_id),
        ).fetchone()
        rows = connection.execute(
            "SELECT artifact_type, ordinal, immutable_content FROM "
            "controlled_artifacts WHERE environment = ? AND handoff_id = ? "
            "ORDER BY CASE artifact_type WHEN 'Paper' THEN 1 WHEN 'Risk' THEN 2 "
            "WHEN 'Selection' THEN 3 ELSE 4 END, ordinal",
            (self.environment, handoff_id),
        ).fetchall()
        if manifest_row is None:
            return None
        if len(rows) != 10:
            raise ControlledExecutionWriterV2Error(
                "stored exact-four Controlled transaction is incomplete"
            )
        contents = {
            f"{row['artifact_type']}:{row['ordinal']}": bytes(
                row["immutable_content"]
            )
            for row in rows
        }
        return WrittenExactFourControlledArtifactsV2(
            bytes(manifest_row["canonical_manifest"]),
            contents,
            _token=_WRITTEN_BUNDLE_TOKEN,
        )

    def _reserve_handoff(
        self,
        *,
        peer_uid: int,
        authenticated_caller: str,
        authority_request_digest: str,
        handoff: Mapping[str, Any],
        canonical_handoff: bytes,
    ) -> WrittenExactFourControlledArtifactsV2 | None:
        if (
            authenticated_caller != "trader"
            or type(authority_request_digest) is not str
            or not authority_request_digest.startswith("sha256:")
        ):
            raise ControlledExecutionWriterV2Error(
                "Controlled handoff requires the authenticated Trader request"
            )
        handoff_digest = _sha256_bytes(canonical_handoff)
        trader_event_digest = handoff["_controlled_event_digest"]
        consume_body = {
            "format": "controlled-exact-four-handoff-consume/v2",
            "environment": self.environment,
            "handoff_id": handoff["handoff_id"],
            "handoff_digest": handoff_digest,
            "trader_event_digest": trader_event_digest,
            "authority_request_digest": authority_request_digest,
            "authenticated_trader_uid": peer_uid,
            "authenticated_trader_caller": authenticated_caller,
        }
        consume_digest = canonical_authority_digest(consume_body)
        consumed_at = _aware_utc(
            self._clock, "Controlled handoff reservation clock"
        ).isoformat()
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                "SELECT handoff_digest, trader_event_digest, "
                "consume_request_digest, authority_request_digest, "
                "authenticated_trader_uid, authenticated_trader_caller, "
                "canonical_handoff "
                "FROM controlled_handoffs WHERE environment = ? AND handoff_id = ?",
                (self.environment, handoff["handoff_id"]),
            ).fetchone()
            if existing is not None:
                if (
                    existing["handoff_digest"] != handoff_digest
                    or existing["trader_event_digest"] != trader_event_digest
                    or existing["consume_request_digest"] != consume_digest
                    or existing["authority_request_digest"]
                    != authority_request_digest
                    or existing["authenticated_trader_uid"] != peer_uid
                    or existing["authenticated_trader_caller"]
                    != authenticated_caller
                    or bytes(existing["canonical_handoff"]) != canonical_handoff
                ):
                    raise ControlledExecutionWriterV2Error(
                        "one-shot Trader handoff was already consumed by different bytes"
                    )
                stored = self._load_committed_result(
                    connection,
                    handoff_id=handoff["handoff_id"],
                )
                if stored is not None:
                    connection.execute("COMMIT")
                    return stored
                raise ControlledExecutionWriterV2Error(
                    "one-shot Trader handoff is consumed and retry policy is DENY"
                )
            trader_event = handoff["one_use_counter_event"]
            assertion = handoff["assertion_evidence"]
            challenge = handoff["challenge_evidence"]
            credential_evidence = handoff["credential_registry_evidence"]
            counter = connection.execute(
                "SELECT public_key_digest, registry_digest, counter_mode, sign_count "
                "FROM controlled_credential_counters WHERE environment = ? "
                "AND credential_id = ?",
                (self.environment, assertion["credential_id_base64url"]),
            ).fetchone()
            if (
                counter is None
                or counter["public_key_digest"]
                != credential_evidence["credential_public_key_digest"]
                or counter["registry_digest"]
                != credential_evidence["credential_registry_digest"]
                or counter["counter_mode"] != credential_evidence["counter_mode"]
                or int(counter["sign_count"]) != trader_event["prior_sign_count"]
            ):
                raise ControlledExecutionWriterV2Error(
                    "Controlled-owned credential counter does not match Trader prior state"
                )
            if counter["counter_mode"] == "COUNTING":
                advanced = connection.execute(
                    "UPDATE controlled_credential_counters SET sign_count = ? "
                    "WHERE environment = ? AND credential_id = ? AND sign_count = ?",
                    (
                        trader_event["result_sign_count"],
                        self.environment,
                        assertion["credential_id_base64url"],
                        trader_event["prior_sign_count"],
                    ),
                ).rowcount
                if advanced != 1:
                    raise ControlledExecutionWriterV2Error(
                        "Controlled-owned WebAuthn counter CAS failed"
                    )
            connection.execute(
                "INSERT INTO controlled_handoffs VALUES "
                "(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, "
                "'CONSUMED', ?)",
                (
                    self.environment,
                    handoff["handoff_id"],
                    handoff_digest,
                    trader_event_digest,
                    trader_event["sequence"],
                    assertion["assertion_digest"],
                    challenge["one_use_key"],
                    assertion["credential_id_base64url"],
                    trader_event["prior_sign_count"],
                    trader_event["result_sign_count"],
                    consume_digest,
                    authority_request_digest,
                    peer_uid,
                    authenticated_caller,
                    canonical_handoff,
                    consumed_at,
                ),
            )
            connection.execute("COMMIT")
            return None
        except ControlledExecutionWriterV2Error:
            connection.execute("ROLLBACK")
            raise
        except sqlite3.Error as exc:
            connection.execute("ROLLBACK")
            raise ControlledExecutionWriterV2Error(
                "atomic Controlled handoff reservation failed"
            ) from exc
        finally:
            connection.close()

    def _record_failed_attempt(self, handoff_id: str, error: BaseException) -> None:
        completed_at = _aware_utc(
            self._clock, "Controlled failed attempt clock"
        ).isoformat()
        error_class = type(error).__name__
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                "SELECT outcome FROM controlled_execution_attempts WHERE "
                "environment = ? AND handoff_id = ?",
                (self.environment, handoff_id),
            ).fetchone()
            if existing is None:
                connection.execute(
                    "INSERT INTO controlled_execution_attempts VALUES "
                    "(?, ?, 'FAILED', 'DENY', NULL, ?, ?)",
                    (self.environment, handoff_id, error_class, completed_at),
                )
            connection.execute("COMMIT")
        except sqlite3.Error as exc:
            connection.execute("ROLLBACK")
            raise ControlledExecutionWriterV2Error(
                "failed Controlled attempt could not be recorded fail closed"
            ) from exc
        finally:
            connection.close()

    def _commit_verified_handoff(
        self,
        *,
        handoff: dict[str, Any],
        canonical_handoff: bytes,
        output: _VerifiedBoundedExecutionOutputV2,
    ) -> WrittenExactFourControlledArtifactsV2:
        controlled_event_digest = handoff["_controlled_event_digest"]
        handoff_digest = _sha256_bytes(canonical_handoff)
        artifacts = self._materialize_artifacts(handoff=handoff, output=output)
        artifact_metadata = [metadata for metadata, _content in artifacts]
        artifact_set_digest = canonical_authority_digest(artifact_metadata)
        request_body = {
            "format": "controlled-exact-four-write-request/v2",
            "environment": self.environment,
            "handoff_id": handoff["handoff_id"],
            "handoff_digest": handoff_digest,
            "trader_event_digest": controlled_event_digest,
            "artifact_set_digest": artifact_set_digest,
        }
        write_request_digest = canonical_authority_digest(request_body)
        written_at = _aware_utc(self._clock, "Controlled commit clock").isoformat()
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            reservation = connection.execute(
                "SELECT canonical_handoff FROM controlled_handoffs WHERE "
                "environment = ? AND handoff_id = ? AND handoff_digest = ? "
                "AND trader_event_digest = ? AND status = 'CONSUMED'",
                (
                    self.environment,
                    handoff["handoff_id"],
                    handoff_digest,
                    controlled_event_digest,
                ),
            ).fetchone()
            attempt = connection.execute(
                "SELECT outcome FROM controlled_execution_attempts WHERE "
                "environment = ? AND handoff_id = ?",
                (self.environment, handoff["handoff_id"]),
            ).fetchone()
            if (
                reservation is None
                or bytes(reservation["canonical_handoff"]) != canonical_handoff
                or attempt is not None
            ):
                raise ControlledExecutionWriterV2Error(
                    "Controlled execution requires one uncompleted reserved handoff"
                )
            for metadata, content in artifacts:
                connection.execute(
                    "INSERT INTO controlled_artifacts VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        self.environment,
                        handoff["handoff_id"],
                        metadata["artifact_type"],
                        metadata["ordinal"],
                        metadata["artifact_id"],
                        metadata["content_digest"],
                        _canonical_bytes(metadata),
                        content,
                    ),
                )
            tail = connection.execute(
                "SELECT sequence, event_digest FROM controlled_writer_events "
                "WHERE environment = ? ORDER BY sequence DESC LIMIT 1",
                (self.environment,),
            ).fetchone()
            sequence = 1 if tail is None else int(tail["sequence"]) + 1
            prior_event_digest = None if tail is None else tail["event_digest"]
            event_body = {
                "format": CONTROLLED_WRITER_EVENT_FORMAT,
                "environment": self.environment,
                "authority_id": "controlled_execution",
                "issuer": CONTROLLED_WRITER_ISSUER,
                "sequence": sequence,
                "event_id": str(uuid.uuid4()),
                "prior_event_digest": prior_event_digest,
                "handoff_id": handoff["handoff_id"],
                "trader_event_digest": controlled_event_digest,
                "write_request_digest": write_request_digest,
                "artifact_set_digest": artifact_set_digest,
                "artifact_count": 10,
                "transaction_status": "COMMITTED",
                "observed_at": written_at,
                "automatic_promotion": False,
                "mass_research_enabled": False,
                "live_trading_enabled": False,
            }
            event = {
                **event_body,
                "event_digest": canonical_authority_digest(event_body),
            }
            connection.execute(
                "INSERT INTO controlled_writer_events VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    self.environment,
                    sequence,
                    event["event_id"],
                    event["event_digest"],
                    prior_event_digest,
                    handoff["handoff_id"],
                    write_request_digest,
                    _canonical_bytes(event),
                ),
            )
            manifest_body = {
                "format": CONTROLLED_WRITER_MANIFEST_FORMAT,
                "environment": self.environment,
                "issuer": CONTROLLED_WRITER_ISSUER,
                "writer_key_id": self._signer.key_id,
                "handoff_id": handoff["handoff_id"],
                "handoff_digest": handoff_digest,
                "approval_subject_id": handoff["approval_subject_id"],
                "ready_authority_response_digest": handoff[
                    "ready_authority_response_digest"
                ],
                "trader_event_digest": controlled_event_digest,
                "write_request_digest": write_request_digest,
                "artifact_set_digest": artifact_set_digest,
                "controlled_event_digest": event["event_digest"],
                "result_manifest": output.manifest.to_dict(),
                "artifacts": artifact_metadata,
                "written_at": written_at,
                "generation": 1,
                "one_shot": True,
                "automatic_promotion": False,
                "mass_research_enabled": False,
                "live_trading_enabled": False,
            }
            signed_body = {
                **manifest_body,
                "manifest_id": canonical_authority_digest(manifest_body),
            }
            manifest = {
                **signed_body,
                "signature": self._signer.sign(signed_body),
            }
            connection.execute(
                "INSERT INTO controlled_manifests VALUES (?, ?, ?, ?, ?, ?)",
                (
                    self.environment,
                    handoff["handoff_id"],
                    signed_body["manifest_id"],
                    write_request_digest,
                    event["event_digest"],
                    _canonical_bytes(manifest),
                ),
            )
            connection.execute(
                "INSERT INTO controlled_execution_attempts VALUES "
                "(?, ?, 'SUCCEEDED', 'DENY', ?, NULL, ?)",
                (
                    self.environment,
                    handoff["handoff_id"],
                    artifact_set_digest,
                    written_at,
                ),
            )
            connection.execute("COMMIT")
            return WrittenExactFourControlledArtifactsV2(
                _canonical_bytes(manifest),
                self._content_map(artifacts),
                _token=_WRITTEN_BUNDLE_TOKEN,
            )
        except ControlledExecutionWriterV2Error:
            connection.execute("ROLLBACK")
            raise
        except sqlite3.Error as exc:
            connection.execute("ROLLBACK")
            raise ControlledExecutionWriterV2Error(
                "atomic Controlled handoff/artifact/event transaction failed"
            ) from exc
        finally:
            connection.close()

    def _execute_authenticated_handoff(
        self,
        *,
        peer_uid: int,
        authenticated_caller: str,
        authority_request_digest: str,
        request_id: str,
        payload: Mapping[str, Any],
        handoff_bytes: bytes,
        execution_runtime: ControlledExecutionRuntimeV2,
    ) -> WrittenExactFourControlledArtifactsV2:
        if (
            peer_uid != self._trader_uid
            or authenticated_caller != "trader"
            or type(payload) not in {dict, MappingProxyType}
            or set(payload) != {"handoff_id", "handoff_digest"}
            or request_id != payload.get("handoff_id")
            or payload.get("handoff_digest") != _sha256_bytes(handoff_bytes)
        ):
            raise ControlledExecutionWriterV2Error(
                "authenticated Trader request or handoff digest is invalid"
            )
        _require_digest(payload["handoff_id"], "Trader handoff_id")
        handoff = self._verify_handoff(
            handoff_bytes,
            expected_handoff_id=payload["handoff_id"],
        )
        stored = self._reserve_handoff(
            peer_uid=peer_uid,
            authenticated_caller=authenticated_caller,
            authority_request_digest=authority_request_digest,
            handoff=handoff,
            canonical_handoff=handoff_bytes,
        )
        if stored is not None:
            return stored
        context = self._execution_context(
            handoff,
            canonical_handoff=handoff_bytes,
        )
        if not (
            (
                self._test_mode is False
                and type(execution_runtime) is ControlledExecutionRuntimeV2
                and execution_runtime._production_bound is True
            )
            or (
                self._test_mode is True
                and isinstance(execution_runtime, ControlledExecutionRuntimeV2)
            )
        ):
            error = ControlledExecutionWriterV2Error(
                "server-constructed Controlled execution runtime is required"
            )
            self._record_failed_attempt(handoff["handoff_id"], error)
            raise error
        attempt = None
        stage = "reserve"
        try:
            attempt = execution_runtime.begin(context)
            stage = "provider"
            raw_output = attempt.invoke()
            stage = "snapshot"
            attempt.reverify_snapshot()
            stage = "schema"
            output = self._verify_executor_output(
                raw_output, context=attempt.context
            )
            stage = "commit"
            attempt.reverify_snapshot()
            written = self._commit_verified_handoff(
                handoff=handoff,
                canonical_handoff=handoff_bytes,
                output=output,
            )
            stage = "settlement"
            attempt.settle(outcome="success")
            return written
        except BaseException as exc:
            if attempt is not None and stage != "settlement":
                if isinstance(exc, ControlledProviderTimeoutV2):
                    outcome = "timeout"
                elif stage == "provider":
                    outcome = "provider_error"
                elif stage in {"snapshot", "schema"}:
                    outcome = "schema_reject"
                else:
                    outcome = "commit_error"
                try:
                    attempt.settle(outcome=outcome, error=exc)
                except BaseException as settlement_error:
                    self._record_failed_attempt(
                        handoff["handoff_id"], settlement_error
                    )
                    raise settlement_error from exc
            self._record_failed_attempt(handoff["handoff_id"], exc)
            raise

    def consume_authority_server_handoff(
        self,
        context: AuthorityRequestContext,
        payload: Mapping[str, Any],
        fds: Sequence[int],
        execution_runtime: ControlledExecutionRuntimeV2,
    ) -> WrittenExactFourControlledArtifactsV2:
        """Consume only a server-authenticated Trader request and one SCM FD."""

        self._require_positive_operation()
        if (
            type(context) is not AuthorityRequestContext
            or context.caller != "trader"
            or context.peer.uid != self._trader_uid
            or context.grant.caller != "trader"
            or context.grant.operation != CONTROLLED_TRADER_HANDOFF_OPERATION
            or context.grant.purpose != CONTROLLED_TRADER_HANDOFF_PURPOSE
            or context.grant.environment != self.environment
            or len(fds) != 1
        ):
            raise ControlledExecutionWriterV2Error(
                "Controlled handoff lacks the exact server-authenticated Trader context"
            )
        exact_payload = dict(payload)
        reconstructed_request = {
            "format": "local-authority-request/v1",
            "request_id": context.request_id,
            "operation": context.grant.operation,
            "purpose": context.grant.purpose,
            "payload": exact_payload,
        }
        if canonical_authority_digest(reconstructed_request) != context.request_digest:
            raise ControlledExecutionWriterV2Error(
                "Controlled server request context digest is inconsistent"
            )
        handoff_bytes = _read_unlinked_readonly_descriptor(
            fds[0],
            expected_uid=context.peer.uid,
        )
        return self._execute_authenticated_handoff(
            peer_uid=context.peer.uid,
            authenticated_caller=context.caller,
            authority_request_digest=context.request_digest,
            request_id=context.request_id,
            payload=exact_payload,
            handoff_bytes=handoff_bytes,
            execution_runtime=execution_runtime,
        )

    def receive_and_execute(
        self,
        channel: socket.socket,
        execution_runtime: ControlledExecutionRuntimeV2,
    ) -> WrittenExactFourControlledArtifactsV2:
        """Compatibility transport used by tests; live launch requires the server."""

        self._require_positive_operation()
        peer_uid = _unix_peer_uid(channel)
        if peer_uid != self._trader_uid:
            raise ControlledExecutionWriterV2Error(
                "Trader AF_UNIX peer UID mismatch"
            )
        request_raw, descriptor = _recv_framed_request_with_one_fd(channel)
        try:
            handoff_bytes = _read_unlinked_readonly_descriptor(
                descriptor,
                expected_uid=peer_uid,
            )
        finally:
            os.close(descriptor)
        request = _strict_json_loads(
            request_raw,
            label="Trader local-authority handoff request",
        )
        payload = request.get("payload") if type(request) is dict else None
        if (
            set(request) != set(_REQUEST_FIELDS)
            or request.get("format") != "local-authority-request/v1"
            or request.get("operation") != CONTROLLED_TRADER_HANDOFF_OPERATION
            or request.get("purpose") != CONTROLLED_TRADER_HANDOFF_PURPOSE
            or type(payload) is not dict
        ):
            raise ControlledExecutionWriterV2Error(
                "Trader local-authority request fields are invalid"
            )
        return self._execute_authenticated_handoff(
            peer_uid=peer_uid,
            authenticated_caller="trader",
            authority_request_digest=canonical_authority_digest(request),
            request_id=request["request_id"],
            payload=payload,
            handoff_bytes=handoff_bytes,
            execution_runtime=execution_runtime,
        )

    def artifact_count(self) -> int:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT COUNT(*) AS count FROM controlled_artifacts "
                "WHERE environment = ?",
                (self.environment,),
            ).fetchone()
            assert row is not None
            return int(row["count"])

    def event_count(self) -> int:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT COUNT(*) AS count FROM controlled_writer_events "
                "WHERE environment = ?",
                (self.environment,),
            ).fetchone()
            assert row is not None
            return int(row["count"])

    def handoff_count(self) -> int:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT COUNT(*) AS count FROM controlled_handoffs "
                "WHERE environment = ?",
                (self.environment,),
            ).fetchone()
            assert row is not None
            return int(row["count"])

    def attempt_outcome(self, handoff_id: str) -> str | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT outcome FROM controlled_execution_attempts WHERE "
                "environment = ? AND handoff_id = ?",
                (self.environment, handoff_id),
            ).fetchone()
            return None if row is None else str(row["outcome"])

    def credential_sign_count(self, credential_id: str) -> int | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT sign_count FROM controlled_credential_counters WHERE "
                "environment = ? AND credential_id = ?",
                (self.environment, credential_id),
            ).fetchone()
            return None if row is None else int(row["sign_count"])


def _create_test_controlled_execution_writer_v2(
    *,
    store_path: Path,
    private_key: Ed25519PrivateKey,
    clock: Callable[[], datetime],
    relying_parties: ExactFourTraderRelyingPartyRegistryV2,
    credentials: ExactFourTraderCredentialRegistryV2,
    trader_uid: int | None = None,
    key_id: str = "test-controlled-writer.invalid/v2",
    server_bound: bool = True,
) -> SQLiteControlledExecutionWriterV2:
    """Construct a test-environment writer with an ephemeral Controlled key."""

    if ".invalid" not in key_id:
        raise ControlledExecutionWriterV2Error(
            "test Controlled writer key id must use .invalid"
        )
    rp = relying_parties.require("staging")
    if not rp.rp_id.endswith(".invalid"):
        raise ControlledExecutionWriterV2Error(
            "test Controlled writer RP must use the reserved .invalid suffix"
        )
    signer = _ControlledWriterSignerV2(key_id=key_id, private_key=private_key)
    return SQLiteControlledExecutionWriterV2(
        store_path,
        environment="staging",
        signer=signer,
        clock=clock,
        trader_uid=os.geteuid() if trader_uid is None else trader_uid,
        relying_parties=relying_parties,
        credentials=credentials,
        server_bound=server_bound,
        test_mode=True,
        lifecycle=None,
        _token=_WRITER_CONSTRUCTION_TOKEN,
    )


__all__ = ["SQLiteControlledExecutionWriterV2"]
