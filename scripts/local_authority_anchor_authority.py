"""Reference compare-and-swap authority for anchor protocol tests.

This in-memory model exercises the closed contract. It is not a provider
adapter, durable remote service, deployment, or operational authority.
"""

from __future__ import annotations

import secrets
import threading
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Any

from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

from scripts.local_authority_activation import canonical_json_bytes
from scripts.local_authority_anchor_contract import (
    AUTHORITY_ID,
    CHALLENGE_FORMAT,
    ENVIRONMENT_SET,
    RECEIPT_FORMAT,
    RESOLUTION_RESPONSE_FORMAT,
    AnchorProtocolError,
    _digest,
    _parse_time,
    _require_key_id,
    _sign,
    _strict_json,
    _validate_challenge_request,
    _validate_commit_request,
    _validate_resolution_request,
    _verify_lineage_proof,
)

class ReferenceExternalAnchorAuthority:
    """In-memory protocol reference, not a production provider adapter."""

    def __init__(
        self, *, remote_key_id: str, remote_private_key: Ed25519PrivateKey,
        client_keys: Mapping[str, Ed25519PublicKey], challenge_ttl_seconds: int = 60,
    ) -> None:
        self._remote_key_id = _require_key_id(remote_key_id, label="remote key id")
        self._remote_private_key = remote_private_key
        self._client_keys = dict(client_keys)
        if not self._client_keys or challenge_ttl_seconds != 60:
            raise AnchorProtocolError("reference anchor authority policy is invalid")
        self._generation = 0
        self._accepted_anchor_digest: str | None = None
        self._accepted_candidate: dict[str, Any] | None = None
        self._accepted_attempts: list[dict[str, Any]] = []
        self._accepted_runs: list[dict[str, Any]] = []
        self._accepted_events: list[dict[str, Any]] = []
        self._journal_instance_id: str | None = None
        self._challenges: dict[str, dict[str, Any]] = {}
        self._seen_challenge_requests: set[str] = set()
        self._accepted_receipts: dict[str, bytes] = {}
        self._rejected_commits: dict[str, dict[str, Any]] = {}
        self._lock = threading.Lock()

    @property
    def generation(self) -> int:
        with self._lock:
            return self._generation

    @property
    def accepted_anchor_digest(self) -> str | None:
        with self._lock:
            return self._accepted_anchor_digest

    def issue_challenge(self, raw: bytes, *, now: datetime) -> bytes:
        request = _validate_challenge_request(raw, client_keys=self._client_keys)
        request_digest = request["challenge_request_digest"]
        with self._lock:
            if request_digest in self._seen_challenge_requests:
                raise AnchorProtocolError("anchor challenge request replay rejected")
            if (
                self._journal_instance_id is not None
                and request["journal_instance_id"] != self._journal_instance_id
            ):
                raise AnchorProtocolError("anchor journal-instance substitution rejected")
            self._seen_challenge_requests.add(request_digest)
            issued = now.astimezone(UTC).replace(tzinfo=UTC)
            body = {
                "format": CHALLENGE_FORMAT,
                "authority_id": AUTHORITY_ID,
                "journal_instance_id": request["journal_instance_id"],
                "environment_set": list(ENVIRONMENT_SET),
                "anchor_candidate_digest": request["anchor_candidate_digest"],
                "challenge_request_digest": request_digest,
                "nonce": secrets.token_hex(32),
                "issued_at": issued.isoformat(timespec="microseconds"),
                "expires_at": (issued + timedelta(seconds=60)).isoformat(
                    timespec="microseconds"
                ),
                "generation": self._generation + 1,
                "prior_anchor_digest": self._accepted_anchor_digest,
                "remote_key_id": self._remote_key_id,
            }
            challenge = {
                **body,
                "challenge_digest": _digest(body),
                "signature": _sign(self._remote_private_key, body),
            }
            self._challenges[challenge["challenge_digest"]] = challenge
            return canonical_json_bytes(challenge)

    def commit(self, raw: bytes, *, now: datetime) -> bytes:
        request = _validate_commit_request(raw, client_keys=self._client_keys)
        request_digest = request["commit_request_digest"]
        with self._lock:
            recovered = self._accepted_receipts.get(request_digest)
            if recovered is not None:
                return recovered
            if request_digest in self._rejected_commits:
                raise AnchorProtocolError("anchor commit was atomically abandoned")
            challenge = self._challenges.get(request["challenge_digest"])
            if challenge is None:
                raise AnchorProtocolError("anchor challenge is absent or already consumed")
            if (
                request["challenge_nonce"] != challenge["nonce"]
                or request["journal_instance_id"] != challenge["journal_instance_id"]
                or request["environment_set"] != challenge["environment_set"]
                or request["anchor_candidate_digest"]
                != challenge["anchor_candidate_digest"]
                or request["generation"] != challenge["generation"]
                or request["prior_anchor_digest"] != challenge["prior_anchor_digest"]
            ):
                raise AnchorProtocolError("anchor commit does not match its challenge")
            current = now.astimezone(UTC).replace(tzinfo=UTC)
            if not (
                _parse_time(challenge["issued_at"], label="stored challenge issued_at")
                <= current
                < _parse_time(challenge["expires_at"], label="stored challenge expires_at")
            ):
                raise AnchorProtocolError("anchor challenge expired")
            if (
                request["generation"] != self._generation + 1
                or request["prior_anchor_digest"] != self._accepted_anchor_digest
            ):
                raise AnchorProtocolError("anchor generation compare-and-swap rejected")
            attempts, runs, events = _verify_lineage_proof(
                request["lineage_proof"],
                candidate=request["anchor_candidate"],
                previous_candidate=self._accepted_candidate,
                previous_attempts=self._accepted_attempts,
                previous_runs=self._accepted_runs,
                previous_events=self._accepted_events,
                prior_anchor_digest=self._accepted_anchor_digest,
            )
            accepted_at = current.isoformat(timespec="microseconds")
            accepted_record = {
                "format": RECEIPT_FORMAT,
                "authority_id": AUTHORITY_ID,
                "journal_instance_id": request["journal_instance_id"],
                "environment_set": list(ENVIRONMENT_SET),
                "generation": request["generation"],
                "prior_anchor_digest": request["prior_anchor_digest"],
                "challenge_digest": request["challenge_digest"],
                "commit_request_digest": request_digest,
                "anchor_candidate_digest": request["anchor_candidate_digest"],
                "lineage_proof_digest": request["lineage_proof_digest"],
                "accepted_at": accepted_at,
            }
            accepted_digest = _digest(accepted_record)
            body = {
                **accepted_record,
                "remote_key_id": self._remote_key_id,
                "accepted_anchor_digest": accepted_digest,
            }
            receipt = {**body, "signature": _sign(self._remote_private_key, body)}
            receipt["receipt_digest"] = _digest(receipt)
            receipt_raw = canonical_json_bytes(receipt)
            self._generation = request["generation"]
            self._accepted_anchor_digest = accepted_digest
            self._accepted_candidate = dict(request["anchor_candidate"])
            self._accepted_attempts = [dict(row) for row in attempts]
            self._accepted_runs = [dict(row) for row in runs]
            self._accepted_events = [dict(row) for row in events]
            self._journal_instance_id = request["journal_instance_id"]
            self._accepted_receipts[request_digest] = receipt_raw
            del self._challenges[request["challenge_digest"]]
            return receipt_raw

    def resolve(self, raw: bytes, *, now: datetime) -> bytes:
        """Atomically return an accepted receipt or abandon one exact commit."""

        request = _validate_resolution_request(raw, client_keys=self._client_keys)
        current = now.astimezone(UTC).replace(tzinfo=UTC)
        request_digest = request["commit_request_digest"]
        with self._lock:
            receipt_raw = self._accepted_receipts.get(request_digest)
            receipt = None if receipt_raw is None else _strict_json(
                receipt_raw, label="stored accepted anchor receipt"
            )
            if receipt is None:
                rejected = self._rejected_commits.get(request_digest)
                if rejected is None:
                    challenge = self._challenges.get(request["challenge_digest"])
                    if challenge is None:
                        raise AnchorProtocolError(
                            "anchor resolution challenge is absent or consumed"
                        )
                    if (
                        request["journal_instance_id"]
                        != challenge["journal_instance_id"]
                        or request["generation"] != challenge["generation"]
                        or request["prior_anchor_digest"]
                        != challenge["prior_anchor_digest"]
                        or request["generation"] != self._generation + 1
                        or request["prior_anchor_digest"]
                        != self._accepted_anchor_digest
                    ):
                        raise AnchorProtocolError(
                            "anchor resolution compare-and-swap rejected"
                        )
                    rejected = {
                        "journal_instance_id": request["journal_instance_id"],
                        "generation": request["generation"],
                        "prior_anchor_digest": request["prior_anchor_digest"],
                        "challenge_digest": request["challenge_digest"],
                    }
                    self._rejected_commits[request_digest] = rejected
                    del self._challenges[request["challenge_digest"]]
                elif any(
                    request[name] != rejected[name]
                    for name in (
                        "journal_instance_id",
                        "generation",
                        "prior_anchor_digest",
                        "challenge_digest",
                    )
                ):
                    raise AnchorProtocolError("anchor abandoned commit identity drifted")
                status = "NOT_ACCEPTED"
            else:
                if (
                    request["generation"] != receipt["generation"]
                    or request["prior_anchor_digest"] != receipt["prior_anchor_digest"]
                    or request["challenge_digest"] != receipt["challenge_digest"]
                ):
                    raise AnchorProtocolError("anchor accepted resolution identity drifted")
                status = "ACCEPTED"
            body = {
                "format": RESOLUTION_RESPONSE_FORMAT,
                "authority_id": AUTHORITY_ID,
                "journal_instance_id": request["journal_instance_id"],
                "environment_set": list(ENVIRONMENT_SET),
                "generation": request["generation"],
                "prior_anchor_digest": request["prior_anchor_digest"],
                "challenge_digest": request["challenge_digest"],
                "commit_request_digest": request_digest,
                "resolution_request_digest": request["resolution_request_digest"],
                "status": status,
                "receipt": receipt,
                "current_generation": self._generation,
                "current_anchor_digest": self._accepted_anchor_digest,
                "resolved_at": current.isoformat(timespec="microseconds"),
                "remote_key_id": self._remote_key_id,
            }
            response = {
                **body,
                "resolution_response_digest": _digest(body),
                "signature": _sign(self._remote_private_key, body),
            }
            return canonical_json_bytes(response)

