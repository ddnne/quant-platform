"""Challenge/assertion orchestration for the exact-four Trader authority."""

from __future__ import annotations

import hashlib
import os
import secrets
import socket
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec

from execution.exact_four_codec import (
    ExactFourAuthorityPending,
    _canonical_bytes,
    _parsed_timestamp,
    _strict_json_loads,
    canonical_authority_digest,
)
from execution.exact_four_trader_v2 import (
    _decode_canonical_base64url,
    _require_content_digest,
    _validate_webauthn_bytes,
    derive_exact_four_trader_one_use_key_v2,
)
from execution.trader_webauthn_ledger_v2 import (
    SQLiteExactFourTraderLedgerV2,
    _AUTHORITY_CONSTRUCTION_TOKEN,
)
from execution.trader_webauthn_registry_v2 import (
    TRADER_ASSERTION_FORMAT,
    ExactFourTraderAuthorityV2Error,
    ExactFourTraderCredentialRegistryV2,
    ExactFourTraderRelyingPartyRegistryV2,
    IssuedExactFourTraderChallengeV2,
    CommittedExactFourTraderHandoffV2,
    VerifiedReadyAuthorityEvidenceV2,
    _ASSERTION_FIELDS,
    _COMMITTED_HANDOFF_TOKEN,
    _b64url,
    _iso_utc,
    _require_ready_authority_evidence_v2,
    _sha256_bytes,
)
from execution.trader_authority_ipc_v2 import (
    open_immutable_handoff_descriptor,
    send_descriptor_frame,
    unix_peer_uid,
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
_CHALLENGE_BYTES = 32
_MAX_CLOCK_SKEW = timedelta(seconds=5)
class ExactFourTraderWebAuthnAuthorityV2:
    """Authority-side verifier; constructed only by an activation boundary."""

    __slots__ = (
        "environment",
        "_rps",
        "_credentials",
        "_ledger",
        "_clock",
        "_controlled_execution_uid",
        "_server_bound",
        "_positive_gate",
    )

    def __init__(
        self,
        *,
        environment: str,
        relying_parties: ExactFourTraderRelyingPartyRegistryV2,
        credentials: ExactFourTraderCredentialRegistryV2,
        ledger: SQLiteExactFourTraderLedgerV2,
        clock: Callable[[], datetime],
        controlled_execution_uid: int,
        server_bound: bool,
        positive_gate: Callable[[], object],
        _token: object,
    ) -> None:
        if _token is not _AUTHORITY_CONSTRUCTION_TOKEN:
            raise ExactFourAuthorityPending(TRADER_AUTHORITY_LIVE_STATE)
        rp = relying_parties.require(environment)
        for credential in credentials.credentials:
            if credential.environment == environment and (
                credential.rp_policy_digest != rp.policy_digest
            ):
                raise ExactFourTraderAuthorityV2Error(
                    "credential registry is not bound to the active RP policy"
                )
        self.environment = environment
        self._rps = relying_parties
        self._credentials = credentials
        self._ledger = ledger
        self._clock = clock
        if type(controlled_execution_uid) is not int or controlled_execution_uid < 0:
            raise ExactFourTraderAuthorityV2Error(
                "controlled execution peer UID is invalid"
            )
        self._controlled_execution_uid = controlled_execution_uid
        if type(server_bound) is not bool or not callable(positive_gate):
            raise ExactFourTraderAuthorityV2Error(
                "Trader positive operation gate configuration is invalid"
            )
        self._server_bound = server_bound
        self._positive_gate = positive_gate

    def _require_positive_operation(self) -> None:
        if self._server_bound is not True:
            raise ExactFourAuthorityPending(
                "positive Trader operations require the local AuthorityServer entrypoint"
            )
        self._positive_gate()

    @property
    def ledger(self) -> SQLiteExactFourTraderLedgerV2:
        return self._ledger

    def issue_challenge(
        self,
        readiness: VerifiedReadyAuthorityEvidenceV2,
    ) -> IssuedExactFourTraderChallengeV2:
        self._require_positive_operation()
        verified_ready = _require_ready_authority_evidence_v2(readiness)
        subject = verified_ready.subject
        now = self._clock()
        issued_at = _iso_utc(now, "Trader challenge clock")
        ready_expires = _parsed_timestamp(
            subject.ready_expires_at, "subject ready_expires_at"
        ).astimezone(timezone.utc)
        expires = min(
            now.astimezone(timezone.utc)
            + timedelta(seconds=subject.lease_ttl_seconds),
            ready_expires,
        )
        if expires <= now.astimezone(timezone.utc):
            raise ExactFourTraderAuthorityV2Error(
                "READY window expired before Trader challenge issuance"
            )
        rp = self._rps.require(self.environment)
        challenge_body: dict[str, Any] = {
            "format": TRADER_CHALLENGE_FORMAT,
            "environment": self.environment,
            "status": "ISSUED",
            "challenge_id": str(uuid.uuid4()),
            "challenge_base64url": _b64url(secrets.token_bytes(_CHALLENGE_BYTES)),
            "approval_subject_id": subject.approval_subject_id,
            "rp_policy_generation": rp.policy_generation,
            "rp_policy_digest": rp.policy_digest,
            "rp_id": rp.rp_id,
            "origin": rp.origin,
            "user_presence_required": True,
            "user_verification_required": True,
            "issued_at": issued_at,
            "expires_at": _iso_utc(expires, "Trader challenge expiry"),
        }
        challenge_body["one_use_key"] = (
            derive_exact_four_trader_one_use_key_v2(dict(challenge_body))
        )
        document = {
            **challenge_body,
            "challenge_digest": canonical_authority_digest(challenge_body),
        }
        self._ledger.register_challenge(document)
        return IssuedExactFourTraderChallengeV2.from_document(document)

    def authorize(
        self,
        *,
        readiness: VerifiedReadyAuthorityEvidenceV2,
        challenge: IssuedExactFourTraderChallengeV2,
        assertion_raw: bytes | str,
    ) -> CommittedExactFourTraderHandoffV2:
        self._require_positive_operation()
        verified_ready = _require_ready_authority_evidence_v2(readiness)
        subject = verified_ready.subject
        if type(challenge) is not IssuedExactFourTraderChallengeV2:
            raise ExactFourTraderAuthorityV2Error(
                "exact issued Trader challenge is required"
            )
        challenge_document = challenge.to_dict()
        if (
            challenge_document["approval_subject_id"]
            != subject.approval_subject_id
            or challenge_document["environment"] != self.environment
        ):
            raise ExactFourTraderAuthorityV2Error(
                "Trader challenge is not bound to READY subject/environment"
            )
        assertion = _strict_json_loads(
            assertion_raw,
            label="exact-four Trader WebAuthn assertion",
        )
        if set(assertion) != set(_ASSERTION_FIELDS):
            raise ExactFourTraderAuthorityV2Error(
                "WebAuthn assertion fields are not closed"
            )
        if (
            assertion["format"] != TRADER_ASSERTION_FORMAT
            or assertion["status"] != "VERIFIED"
        ):
            raise ExactFourTraderAuthorityV2Error(
                "WebAuthn assertion identity is invalid"
            )
        _require_content_digest(
            assertion,
            digest_field="assertion_digest",
            label="WebAuthn assertion",
        )
        for field in (
            "environment",
            "challenge_id",
            "approval_subject_id",
            "rp_policy_generation",
            "rp_policy_digest",
            "rp_id",
            "origin",
            "one_use_key",
        ):
            if assertion[field] != challenge_document[field]:
                raise ExactFourTraderAuthorityV2Error(
                    f"WebAuthn assertion {field} does not bind the issued challenge"
                )
        if assertion["challenge_digest"] != challenge_document["challenge_digest"]:
            raise ExactFourTraderAuthorityV2Error(
                "WebAuthn assertion challenge digest mismatch"
            )
        _validate_webauthn_bytes(challenge_document, assertion)
        credential = self._credentials.require(
            self.environment,
            assertion["credential_id_base64url"],
        )
        rp = self._rps.require(self.environment)
        if credential.rp_policy_digest != rp.policy_digest:
            raise ExactFourTraderAuthorityV2Error(
                "WebAuthn credential is not bound to the current RP generation"
            )
        authenticator_data = _decode_canonical_base64url(
            assertion["authenticator_data_base64url"],
            label="authenticatorData",
            minimum_bytes=37,
            maximum_bytes=4096,
        )
        client_data = _decode_canonical_base64url(
            assertion["client_data_json_base64url"],
            label="clientDataJSON",
            minimum_bytes=32,
            maximum_bytes=8192,
        )
        signature = _decode_canonical_base64url(
            assertion["signature_base64url"],
            label="WebAuthn signature",
            minimum_bytes=8,
            maximum_bytes=1024,
        )
        signed_bytes = authenticator_data + hashlib.sha256(client_data).digest()
        try:
            credential.public_key.verify(
                signature,
                signed_bytes,
                ec.ECDSA(hashes.SHA256()),
            )
        except (InvalidSignature, ValueError) as exc:
            raise ExactFourTraderAuthorityV2Error(
                "WebAuthn ES256 assertion signature is invalid"
            ) from exc
        current = self._clock()
        committed_at = _iso_utc(current, "Trader authority clock")
        asserted_at = _parsed_timestamp(
            assertion["asserted_at"], "assertion asserted_at"
        )
        challenge_issued = _parsed_timestamp(
            challenge_document["issued_at"], "challenge issued_at"
        )
        challenge_expires = _parsed_timestamp(
            challenge_document["expires_at"], "challenge expires_at"
        )
        credential_effective = _parsed_timestamp(
            credential.effective_at, "credential effective_at"
        )
        rp_effective = _parsed_timestamp(rp.effective_at, "RP effective_at")
        current_utc = current.astimezone(timezone.utc)
        if not (
            credential_effective <= asserted_at
            and rp_effective <= asserted_at
            and challenge_issued <= asserted_at <= current_utc + _MAX_CLOCK_SKEW
            and asserted_at <= challenge_expires
            and current_utc < challenge_expires
        ):
            raise ExactFourTraderAuthorityV2Error(
                "WebAuthn assertion or authority observation is outside challenge window"
            )
        handoff = self._ledger.commit_verified_assertion(
            ready_response_digest=verified_ready.response_digest,
            approval_subject=subject.to_dict(),
            challenge=challenge_document,
            assertion=assertion,
            credential=credential,
            credential_registry=self._credentials,
            committed_at=committed_at,
        )
        return CommittedExactFourTraderHandoffV2(
            handoff,
            _token=_COMMITTED_HANDOFF_TOKEN,
        )

    def open_handoff_descriptor(
        self,
        handoff: CommittedExactFourTraderHandoffV2,
    ) -> int:
        """Return an unlinked, read-only, CLOEXEC descriptor for SCM_RIGHTS."""

        if type(handoff) is not CommittedExactFourTraderHandoffV2:
            raise ExactFourTraderAuthorityV2Error(
                "exact committed Trader handoff is required"
            )
        document = handoff.to_dict()
        body = dict(document)
        declared = body.pop("handoff_id", None)
        if declared != canonical_authority_digest(body):
            raise ExactFourTraderAuthorityV2Error(
                "committed Trader handoff content id is invalid"
            )
        return open_immutable_handoff_descriptor(
            self._ledger._path.parent,
            handoff.canonical_bytes,
        )

    def send_handoff(
        self,
        channel: socket.socket,
        handoff: CommittedExactFourTraderHandoffV2,
    ) -> None:
        """Authenticate controlled_execution and send exactly one read-only FD."""

        self._require_positive_operation()
        peer_uid = unix_peer_uid(channel)
        if peer_uid != self._controlled_execution_uid:
            raise ExactFourTraderAuthorityV2Error(
                "controlled execution AF_UNIX peer UID mismatch"
            )
        descriptor = self.open_handoff_descriptor(handoff)
        try:
            request = {
                "format": "local-authority-request/v1",
                "request_id": handoff.handoff_id,
                "operation": "controlled_execution:consume_trader_handoff",
                "purpose": "exact_four_one_shot_execution",
                "payload": {
                    "handoff_id": handoff.handoff_id,
                    "handoff_digest": _sha256_bytes(handoff.canonical_bytes),
                },
            }
            payload = _canonical_bytes(request)
            send_descriptor_frame(
                channel,
                descriptor=descriptor,
                canonical_request=payload,
            )
        finally:
            os.close(descriptor)


def _create_test_exact_four_trader_authority_v2(
    *,
    ledger_path: Path,
    relying_parties: ExactFourTraderRelyingPartyRegistryV2,
    credentials: ExactFourTraderCredentialRegistryV2,
    clock: Callable[[], datetime],
    positive_gate: Callable[[], object] = lambda: object(),
    server_bound: bool = True,
) -> ExactFourTraderWebAuthnAuthorityV2:
    """Construct an intentionally non-activatable authority for behavior tests."""

    environment = "test"
    rp = relying_parties.require(environment)
    if not rp.rp_id.endswith(".invalid"):
        raise ExactFourTraderAuthorityV2Error(
            "test Trader authority RP must use the reserved .invalid suffix"
        )
    ledger = SQLiteExactFourTraderLedgerV2(
        ledger_path,
        environment=environment,
        credentials=credentials,
        _token=_AUTHORITY_CONSTRUCTION_TOKEN,
    )
    return ExactFourTraderWebAuthnAuthorityV2(
        environment=environment,
        relying_parties=relying_parties,
        credentials=credentials,
        ledger=ledger,
        clock=clock,
        controlled_execution_uid=os.geteuid(),
        server_bound=server_bound,
        positive_gate=positive_gate,
        _token=_AUTHORITY_CONSTRUCTION_TOKEN,
    )


__all__ = ["ExactFourTraderWebAuthnAuthorityV2"]
