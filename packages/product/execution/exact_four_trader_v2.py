"""Fail-closed exact-four Trader v2 wire and positive-boundary contracts.

The audit compiler derives a deterministic, unverified pre-approval subject
from unsigned READY claims.  It is intentionally separate from the future
positive entrypoint, whose exact input is ``VerifiedPilotReadinessV2`` and
which remains unavailable.

The envelope parser validates canonical WebAuthn bytes, governed RP and
credential evidence, one atomic one-use-plus-counter transaction, and the
existing append-only ``authority-event/v2`` convention.  It still returns an
explicitly unverified document.  Governed CSPRNG challenge generation,
credential signature verification, pinned RP and credential registries,
transactional ledgers, and positive capability construction remain PENDING.
Final issuance/expiry are derived exactly from authority observation/challenge
expiry, while a sequence-independent decision key freezes the future store's
atomic retry and ledger-reuse boundary.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, Mapping, Protocol
from urllib.parse import urlsplit

from execution.exact_four_claims import (
    PilotReadinessAttestationClaimsV2,
    validate_exact_four_authority_claims_v2,
)
from execution.exact_four_codec import (
    PILOT_EXECUTION_MODE,
    TRADER_AUTHORIZATION_SCOPE,
    ExactFourAuthorityContractError,
    ExactFourAuthorityPending,
    _canonical_bytes,
    _parsed_timestamp,
    _require_bounded_window,
    _require_digest,
    _require_exact_json,
    _require_text,
    _strict_json_loads,
    canonical_authority_digest,
)
from execution.exact_four_protocol import (
    AuthorizedExactFourExecutionV2,
    VerifiedExactFourTraderAuthorizationV2,
    VerifiedPilotReadinessV2,
)
from qp_paths import repo_root
from selection.controlled_pilot_policy import CONTROLLED_PILOT_POLICY_DIGEST


TRADER_APPROVAL_SUBJECT_FORMAT = "exact-four-trader-approval-subject/v2"
TRADER_APPROVAL_SUBJECT_SCOPE = "EXACT_FOUR_TRADER_PRE_APPROVAL"
TRADER_AUTHORIZATION_ENVELOPE_FORMAT = (
    "exact-four-trader-authorization-envelope/v2"
)
TRADER_AUTHORIZATION_ISSUER_V2 = "ExactFourTraderAuthorizationAuthority/v2"
TRADER_AUTHORIZATION_V2_STATE = (
    "PENDING_VERIFIED_READY_RP_REGISTRY_CSPRNG_CHALLENGE_CREDENTIAL_SIGNATURE_"
    "ATOMIC_LEDGER_AUTHORITY_EVENT_AND_CONTROLLED_EXECUTION"
)
TRADER_V2_ACTIVE_RP_REGISTRY_COUNT = 0
TRADER_V2_ACTIVE_CREDENTIAL_REGISTRY_COUNT = 0

EXACT_FOUR_TRADER_AUTHORIZATION_SCHEMA_REL = (
    Path("specs") / "ready" / "exact_four_trader_authorization_v2.schema.json"
)
PINNED_EXACT_FOUR_TRADER_AUTHORIZATION_SCHEMA_DIGEST = (
    "sha256:aa194409d8408a506db249e743fc36d9e74afa16c52b944ccad4160f7c04ff0f"
)
PINNED_EXACT_FOUR_TRADER_AUTHORIZATION_SCHEMA_RAW_DIGEST = (
    "sha256:fd7b6e4ccbd8da9a7d9bb966fa2c6b61d352f11cd23464536e8628da08476532"
)

_UUID4_RE = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}\Z"
)
_CHALLENGE_BODY_FIELDS = frozenset(
    {
        "format",
        "environment",
        "status",
        "challenge_id",
        "challenge_base64url",
        "approval_subject_id",
        "rp_policy_generation",
        "rp_policy_digest",
        "rp_id",
        "origin",
        "user_presence_required",
        "user_verification_required",
        "issued_at",
        "expires_at",
    }
)
_AUTHORITY_PAYLOAD_FIELDS = frozenset(
    {
        "format",
        "environment",
        "authority_backend_id",
        "authority_backend_generation",
        "prior_sequence",
        "prior_event_digest",
        "authority_transaction_id",
        "authority_event_id",
        "authority_request_id",
        "authorization_decision_id",
        "authority_transaction_idempotency_key",
        "authority_sequence",
        "authority_transaction_status",
        "approval_subject_id",
        "challenge_digest",
        "assertion_digest",
        "credential_registry_evidence_digest",
        "one_use_ledger_generation",
        "one_use_ledger_transaction_id",
        "one_use_ledger_transaction_digest",
        "one_use_ledger_event_id",
        "one_use_ledger_event_digest",
        "one_use_ledger_commit_status",
        "recorded_at",
        "authority_transaction_digest",
    }
)


class ExactFourTraderAuthorityDecisionStoreV2(Protocol):
    """Required atomic exactly-once store; no implementation is active.

    One transaction must enforce uniqueness of the environment-scoped Trader
    ``authorization_decision_id``, transaction idempotency key, request id,
    and exact one-use ledger transaction/event identities. A retry may return
    only the already committed byte-identical authority event; every conflict
    must fail closed before a verified Trader capability can be minted.
    """

    def append_decision_once(
        self,
        *,
        environment: str,
        authority_id: Literal["trader"],
        authorization_decision_id: str,
        authority_transaction_idempotency_key: str,
        authority_request_id: str,
        one_use_ledger_transaction_digest: str,
        one_use_ledger_event_digest: str,
        canonical_authority_event: bytes,
    ) -> str: ...


def exact_four_trader_authorization_schema_path() -> Path:
    return repo_root() / EXACT_FOUR_TRADER_AUTHORIZATION_SCHEMA_REL


def load_exact_four_trader_authorization_schema() -> dict[str, Any]:
    """Load the closed subject/envelope schema under dual digest pins."""

    path = exact_four_trader_authorization_schema_path()
    try:
        raw = path.read_bytes()
        value = _strict_json_loads(
            raw,
            label="exact-four Trader authorization v2 schema",
        )
    except (OSError, ExactFourAuthorityContractError) as exc:
        raise ExactFourAuthorityContractError(
            "cannot load exact-four Trader authorization v2 schema"
        ) from exc
    raw_digest = "sha256:" + hashlib.sha256(raw).hexdigest()
    if raw_digest != PINNED_EXACT_FOUR_TRADER_AUTHORIZATION_SCHEMA_RAW_DIGEST:
        raise ExactFourAuthorityContractError(
            "pinned exact-four Trader authorization schema raw digest mismatch"
        )
    if (
        set(value) != {"$schema", "$id", "title", "oneOf", "$defs"}
        or value.get("$schema")
        != "https://json-schema.org/draft/2020-12/schema"
        or value.get("$id")
        != "https://quant-platform.local/specs/ready/"
        "exact_four_trader_authorization_v2.schema.json"
        or value.get("title")
        != "Exact-four Trader pre-approval and authorization envelope v2"
        or canonical_authority_digest(value)
        != PINNED_EXACT_FOUR_TRADER_AUTHORIZATION_SCHEMA_DIGEST
    ):
        raise ExactFourAuthorityContractError(
            "pinned exact-four Trader authorization schema identity or digest "
            "mismatch"
        )
    try:
        from jsonschema import Draft202012Validator

        Draft202012Validator.check_schema(value)
    except Exception as exc:
        raise ExactFourAuthorityContractError(
            "exact-four Trader authorization v2 schema is invalid"
        ) from exc
    return value


@dataclass(frozen=True, slots=True)
class UnverifiedExactFourTraderApprovalSubjectV2:
    """Audit-only subject compiled from unsigned READY claims."""

    pilot_run_id: str
    environment: str
    ready_authority_instance_id: str
    ready_authority_resource_digest: str
    readiness_attestation_id: str
    snapshot_id: str
    ready_manifest_digest: str
    immutable_snapshot_digest: str
    exact_four_binding_digest: str
    controlled_pilot_policy_digest: str
    budget_scope_digest: str
    execution_limit_set_digest: str
    lease_ttl_seconds: int
    ready_issued_at: str
    ready_expires_at: str
    format: str = TRADER_APPROVAL_SUBJECT_FORMAT
    authority_scope: str = TRADER_APPROVAL_SUBJECT_SCOPE
    execution_mode: str = PILOT_EXECUTION_MODE
    automatic_promotion: bool = False
    mass_research_enabled: bool = False
    live_trading_enabled: bool = False

    def __post_init__(self) -> None:
        if (
            type(self.format) is not str
            or self.format != TRADER_APPROVAL_SUBJECT_FORMAT
            or type(self.authority_scope) is not str
            or self.authority_scope != TRADER_APPROVAL_SUBJECT_SCOPE
            or type(self.execution_mode) is not str
            or self.execution_mode != PILOT_EXECUTION_MODE
        ):
            raise ExactFourAuthorityContractError(
                "Trader pre-approval subject identity is not canonical"
            )
        _require_text(self.pilot_run_id, "pilot_run_id")
        if (
            type(self.environment) is not str
            or self.environment not in {"staging", "production"}
            or self.ready_authority_instance_id
            != f"ready-authority/{self.environment}/v1"
        ):
            raise ExactFourAuthorityContractError(
                "Trader pre-approval READY authority scope is invalid"
            )
        for name in (
            "ready_authority_resource_digest",
            "readiness_attestation_id",
            "snapshot_id",
            "ready_manifest_digest",
            "immutable_snapshot_digest",
            "exact_four_binding_digest",
            "controlled_pilot_policy_digest",
            "budget_scope_digest",
            "execution_limit_set_digest",
        ):
            _require_digest(getattr(self, name), name)
        _require_bounded_window(
            self.ready_issued_at,
            self.ready_expires_at,
            ttl_seconds=self.lease_ttl_seconds,
            label="subject READY",
        )
        from execution.exact_four_binding import load_exact_four_execution_binding

        canonical = load_exact_four_execution_binding()
        if (
            self.controlled_pilot_policy_digest
            != CONTROLLED_PILOT_POLICY_DIGEST
            or self.exact_four_binding_digest != canonical.binding_digest
            or self.budget_scope_digest != canonical.budget_scope_digest
            or self.execution_limit_set_digest
            != canonical.execution_limit_set_digest
            or type(self.lease_ttl_seconds) is not int
            or self.lease_ttl_seconds != canonical.lease_ttl_seconds
        ):
            raise ExactFourAuthorityContractError(
                "Trader pre-approval subject limits are not canonical exact-four"
            )
        if (
            self.automatic_promotion is not False
            or self.mass_research_enabled is not False
            or self.live_trading_enabled is not False
        ):
            raise ExactFourAuthorityContractError(
                "Trader pre-approval cannot enable Mass, live, or promotion"
            )

    def to_canonical_dict(self) -> dict[str, Any]:
        return {
            "format": self.format,
            "authority_scope": self.authority_scope,
            "execution_mode": self.execution_mode,
            "pilot_run_id": self.pilot_run_id,
            "environment": self.environment,
            "ready_authority_instance_id": self.ready_authority_instance_id,
            "ready_authority_resource_digest": (
                self.ready_authority_resource_digest
            ),
            "readiness_attestation_id": self.readiness_attestation_id,
            "snapshot_id": self.snapshot_id,
            "ready_manifest_digest": self.ready_manifest_digest,
            "immutable_snapshot_digest": self.immutable_snapshot_digest,
            "exact_four_binding_digest": self.exact_four_binding_digest,
            "controlled_pilot_policy_digest": (
                self.controlled_pilot_policy_digest
            ),
            "budget_scope_digest": self.budget_scope_digest,
            "execution_limit_set_digest": self.execution_limit_set_digest,
            "lease_ttl_seconds": self.lease_ttl_seconds,
            "ready_issued_at": self.ready_issued_at,
            "ready_expires_at": self.ready_expires_at,
            "automatic_promotion": self.automatic_promotion,
            "mass_research_enabled": self.mass_research_enabled,
            "live_trading_enabled": self.live_trading_enabled,
        }

    @property
    def approval_subject_id(self) -> str:
        return canonical_authority_digest(self.to_canonical_dict())

    def to_dict(self) -> dict[str, Any]:
        return {
            **self.to_canonical_dict(),
            "approval_subject_id": self.approval_subject_id,
        }


def compile_unverified_exact_four_trader_approval_subject_v2(
    readiness: PilotReadinessAttestationClaimsV2,
) -> UnverifiedExactFourTraderApprovalSubjectV2:
    """Audit compiler; unsigned READY claims never become a positive capability."""

    if type(readiness) is not PilotReadinessAttestationClaimsV2:
        raise ExactFourAuthorityContractError("exact unsigned READY claims required")
    validate_exact_four_authority_claims_v2(readiness)
    exact_four = readiness.exact_four
    snapshot = readiness.snapshot
    return UnverifiedExactFourTraderApprovalSubjectV2(
        pilot_run_id=readiness.pilot_run_id,
        environment=readiness.environment,
        ready_authority_instance_id=readiness.ready_authority_instance_id,
        ready_authority_resource_digest=(
            readiness.ready_authority_resource_digest
        ),
        readiness_attestation_id=readiness.attestation_id,
        snapshot_id=snapshot.snapshot_id,
        ready_manifest_digest=snapshot.ready_manifest_digest,
        immutable_snapshot_digest=snapshot.immutable_snapshot_digest,
        exact_four_binding_digest=exact_four.binding_digest,
        controlled_pilot_policy_digest=exact_four.policy.policy_digest,
        budget_scope_digest=exact_four.budget_scope_digest,
        execution_limit_set_digest=exact_four.execution_limit_set_digest,
        lease_ttl_seconds=exact_four.lease_ttl_seconds,
        ready_issued_at=readiness.issued_at,
        ready_expires_at=readiness.expires_at,
    )


def prepare_exact_four_trader_approval_subject_v2(
    readiness: VerifiedPilotReadinessV2,
) -> UnverifiedExactFourTraderApprovalSubjectV2:
    """Future positive READY entrypoint; no verified READY authority is active."""

    if type(readiness) is not VerifiedPilotReadinessV2:
        raise ExactFourAuthorityContractError(
            "exact VerifiedPilotReadinessV2 capability required"
        )
    raise ExactFourAuthorityPending(
        "verified READY to Trader subject preparation is unavailable: "
        f"{TRADER_AUTHORIZATION_V2_STATE}"
    )


def authorize_controlled_exact_four_execution_v2(
    readiness: VerifiedPilotReadinessV2,
    trader: VerifiedExactFourTraderAuthorizationV2,
) -> AuthorizedExactFourExecutionV2:
    """Future controlled consumer; accepts only the two positive v2 types."""

    if type(readiness) is not VerifiedPilotReadinessV2:
        raise ExactFourAuthorityContractError(
            "exact VerifiedPilotReadinessV2 capability required"
        )
    if type(trader) is not VerifiedExactFourTraderAuthorizationV2:
        raise ExactFourAuthorityContractError(
            "exact VerifiedExactFourTraderAuthorizationV2 capability required"
        )
    raise ExactFourAuthorityPending(
        "verified READY and Trader controlled execution is unavailable: "
        f"{TRADER_AUTHORIZATION_V2_STATE}"
    )


def _validate_schema(document: dict[str, Any]) -> None:
    try:
        from jsonschema import Draft202012Validator, FormatChecker

        validator = Draft202012Validator(
            load_exact_four_trader_authorization_schema(),
            format_checker=FormatChecker(),
        )
        errors = sorted(
            validator.iter_errors(document),
            key=lambda item: tuple(str(part) for part in item.path),
        )
    except ExactFourAuthorityContractError:
        raise
    except Exception as exc:
        raise ExactFourAuthorityContractError(
            "cannot validate exact-four Trader authorization v2 document"
        ) from exc
    if errors:
        location = "$" + "".join(
            f"[{part}]" if type(part) is int else f".{part}"
            for part in errors[0].path
        )
        raise ExactFourAuthorityContractError(
            f"exact-four Trader authorization schema violation at {location}: "
            f"{errors[0].message}"
        )


def parse_and_validate_unverified_exact_four_trader_approval_subject_v2(
    raw: bytes | str,
) -> UnverifiedExactFourTraderApprovalSubjectV2:
    """Parse canonical audit-only subject; legacy human-event claims fail."""

    document = _strict_json_loads(raw, label="unverified Trader approval subject")
    _validate_schema(document)
    if document.get("format") != TRADER_APPROVAL_SUBJECT_FORMAT:
        raise ExactFourAuthorityContractError(
            "unverified exact-four Trader pre-approval subject v2 required"
        )
    body = dict(document)
    body.pop("approval_subject_id", None)
    try:
        subject = UnverifiedExactFourTraderApprovalSubjectV2(**body)
    except TypeError as exc:
        raise ExactFourAuthorityContractError(
            "Trader pre-approval subject fields are not closed"
        ) from exc
    if subject.to_dict() != document:
        raise ExactFourAuthorityContractError(
            "Trader pre-approval subject content id is invalid"
        )
    return subject


def _require_content_digest(
    document: Mapping[str, Any],
    *,
    digest_field: str,
    label: str,
) -> str:
    claimed = _require_digest(document.get(digest_field), f"{label} {digest_field}")
    body = dict(document)
    body.pop(digest_field, None)
    measured = canonical_authority_digest(body)
    if claimed != measured:
        raise ExactFourAuthorityContractError(f"{label} content digest mismatch")
    return claimed


def _require_uuid4(value: Any, label: str) -> str:
    text = _require_text(value, label)
    if _UUID4_RE.fullmatch(text) is None:
        raise ExactFourAuthorityContractError(f"{label} must be canonical UUID4")
    return text


def _decode_canonical_base64url(
    value: Any,
    *,
    label: str,
    minimum_bytes: int,
    maximum_bytes: int,
) -> bytes:
    if type(value) is not str or not value or "=" in value or len(value) % 4 == 1:
        raise ExactFourAuthorityContractError(
            f"{label} must be unpadded canonical base64url"
        )
    try:
        decoded = base64.b64decode(
            value + "=" * (-len(value) % 4),
            altchars=b"-_",
            validate=True,
        )
    except (binascii.Error, TypeError, ValueError) as exc:
        raise ExactFourAuthorityContractError(
            f"{label} must be unpadded canonical base64url"
        ) from exc
    recoded = base64.urlsafe_b64encode(decoded).decode("ascii").rstrip("=")
    if recoded != value:
        raise ExactFourAuthorityContractError(
            f"{label} has non-canonical base64url pad bits"
        )
    if not minimum_bytes <= len(decoded) <= maximum_bytes:
        raise ExactFourAuthorityContractError(
            f"{label} decoded size is outside the closed contract"
        )
    return decoded


def _validate_rp_origin(rp_id: Any, origin: Any) -> None:
    rp = _require_text(rp_id, "rp_id")
    origin_text = _require_text(origin, "origin")
    try:
        parsed = urlsplit(origin_text)
        port = parsed.port
    except ValueError as exc:
        raise ExactFourAuthorityContractError("origin is not canonical HTTPS") from exc
    host = parsed.hostname
    if (
        parsed.scheme != "https"
        or host is None
        or host != host.casefold()
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path
        or parsed.query
        or parsed.fragment
        or (port is not None and not 1 <= port <= 65535)
        or (host != rp and not host.endswith("." + rp))
    ):
        raise ExactFourAuthorityContractError(
            "origin must be an exact governed HTTPS origin under rp_id"
        )


def derive_exact_four_trader_one_use_key_v2(
    challenge_body: Mapping[str, Any],
) -> str:
    """Digest every challenge identity/RP/time/UP/UV field before issuance."""

    if type(challenge_body) is not dict or set(challenge_body) != set(
        _CHALLENGE_BODY_FIELDS
    ):
        raise ExactFourAuthorityContractError(
            "one-use key requires the exact canonical challenge body"
        )
    _require_exact_json(challenge_body)
    return canonical_authority_digest(challenge_body)


def _challenge_one_use_key(challenge: Mapping[str, Any]) -> str:
    return derive_exact_four_trader_one_use_key_v2(
        {
            key: challenge[key]
            for key in _CHALLENGE_BODY_FIELDS
        }
    )


def _authority_request_id(
    *,
    environment: str,
    subject_id: str,
    challenge_digest: str,
    assertion_digest: str,
    registry_evidence_digest: str,
    ledger_transaction_digest: str,
    ledger_event_digest: str,
) -> str:
    return canonical_authority_digest(
        {
            "format": "exact-four-trader-authority-request/v2",
            "environment": environment,
            "approval_subject_id": subject_id,
            "challenge_digest": challenge_digest,
            "assertion_digest": assertion_digest,
            "credential_registry_evidence_digest": registry_evidence_digest,
            "one_use_ledger_transaction_digest": ledger_transaction_digest,
            "one_use_ledger_event_digest": ledger_event_digest,
        }
    )


def _authorization_decision_id(
    *,
    environment: str,
    subject_id: str,
    request_id: str,
    challenge_digest: str,
    assertion_digest: str,
    registry_evidence_digest: str,
    ledger_transaction_digest: str,
    ledger_event_digest: str,
) -> str:
    """Derive the stable authority-owned decision identity from exact evidence."""

    return canonical_authority_digest(
        {
            "format": "exact-four-trader-authorization-decision/v2",
            "environment": environment,
            "authority_id": "trader",
            "approval_subject_id": subject_id,
            "authority_request_id": request_id,
            "challenge_digest": challenge_digest,
            "assertion_digest": assertion_digest,
            "credential_registry_evidence_digest": registry_evidence_digest,
            "one_use_ledger_transaction_digest": ledger_transaction_digest,
            "one_use_ledger_event_digest": ledger_event_digest,
            "authorization_status": "AUTHORIZED",
        }
    )


def _authority_transaction_idempotency_key(
    *,
    environment: str,
    subject_id: str,
    request_id: str,
    authorization_decision_id: str,
    ledger_transaction_digest: str,
    ledger_event_digest: str,
) -> str:
    """Derive the stable store key; append sequence/event fields are excluded."""

    return canonical_authority_digest(
        {
            "format": "exact-four-trader-authority-transaction-idempotency/v2",
            "environment": environment,
            "authority_id": "trader",
            "approval_subject_id": subject_id,
            "authority_request_id": request_id,
            "authorization_decision_id": authorization_decision_id,
            "one_use_ledger_transaction_digest": ledger_transaction_digest,
            "one_use_ledger_event_digest": ledger_event_digest,
        }
    )


def _authority_idempotency_key(
    *,
    environment: str,
    request_id: str,
    subject_id: str,
    payload_schema: str,
    payload_digest: str,
) -> str:
    """Apply the shared ``authority-event/v2`` idempotency convention."""

    return canonical_authority_digest(
        {
            "environment": environment,
            "authority_id": "trader",
            "request_id": request_id,
            "event_type": "COMMITTED",
            "subject_id": subject_id,
            "payload_schema": payload_schema,
            "payload_digest": payload_digest,
        }
    )


def _parse_authority_payload(authority: Mapping[str, Any]) -> dict[str, Any]:
    payload = _strict_json_loads(
        authority["payload_json"],
        label="exact-four Trader authority event payload",
    )
    if set(payload) != set(_AUTHORITY_PAYLOAD_FIELDS):
        raise ExactFourAuthorityContractError(
            "Trader authority event payload fields are not closed"
        )
    if _canonical_bytes(payload).decode("utf-8") != authority["payload_json"]:
        raise ExactFourAuthorityContractError(
            "Trader authority event payload_json is not canonical"
        )
    if canonical_authority_digest(payload) != authority["payload_digest"]:
        raise ExactFourAuthorityContractError(
            "Trader authority event payload digest mismatch"
        )
    transaction_body = dict(payload)
    transaction_digest = transaction_body.pop("authority_transaction_digest")
    if canonical_authority_digest(transaction_body) != transaction_digest:
        raise ExactFourAuthorityContractError(
            "Trader authority transaction digest mismatch"
        )
    if (
        payload["format"]
        != "exact-four-trader-authority-event-payload/v2"
        or payload["authority_transaction_status"] != "COMMITTED"
    ):
        raise ExactFourAuthorityContractError(
            "Trader authority transaction status or format is not canonical"
        )
    _require_uuid4(payload["authority_transaction_id"], "authority transaction id")
    return payload


def _validate_webauthn_bytes(
    challenge: Mapping[str, Any], assertion: Mapping[str, Any]
) -> None:
    _decode_canonical_base64url(
        challenge["challenge_base64url"],
        label="challenge",
        minimum_bytes=32,
        maximum_bytes=64,
    )
    _decode_canonical_base64url(
        assertion["credential_id_base64url"],
        label="credential id",
        minimum_bytes=16,
        maximum_bytes=1024,
    )
    authenticator = _decode_canonical_base64url(
        assertion["authenticator_data_base64url"],
        label="authenticatorData",
        minimum_bytes=37,
        maximum_bytes=4096,
    )
    client_raw = _decode_canonical_base64url(
        assertion["client_data_json_base64url"],
        label="clientDataJSON",
        minimum_bytes=32,
        maximum_bytes=8192,
    )
    _decode_canonical_base64url(
        assertion["signature_base64url"],
        label="WebAuthn signature",
        minimum_bytes=32,
        maximum_bytes=1024,
    )
    client = _strict_json_loads(client_raw, label="WebAuthn clientDataJSON")
    if set(client) != {"type", "challenge", "origin", "crossOrigin"} or (
        client["type"] != "webauthn.get"
        or client["challenge"] != challenge["challenge_base64url"]
        or client["origin"] != challenge["origin"]
        or client["crossOrigin"] is not False
    ):
        raise ExactFourAuthorityContractError(
            "WebAuthn clientDataJSON does not bind the exact challenge"
        )
    expected_rp_hash = hashlib.sha256(challenge["rp_id"].encode("utf-8")).digest()
    flags = authenticator[32]
    sign_count = int.from_bytes(authenticator[33:37], "big")
    if authenticator[:32] != expected_rp_hash or flags & 0x01 == 0 or flags & 0x04 == 0:
        raise ExactFourAuthorityContractError(
            "WebAuthn authenticatorData RP/UP/UV evidence is invalid"
        )
    if (
        assertion["user_present"] is not True
        or assertion["user_verified"] is not True
        or assertion["sign_count"] != sign_count
    ):
        raise ExactFourAuthorityContractError(
            "WebAuthn authenticatorData counter or flags mismatch"
        )


def _validate_envelope_links_and_time(
    document: dict[str, Any],
    *,
    subject: UnverifiedExactFourTraderApprovalSubjectV2,
) -> None:
    challenge = document["challenge_evidence"]
    assertion = document["assertion_evidence"]
    registry = document["credential_registry_evidence"]
    ledger = document["one_use_ledger_event"]
    authority = document["authority_event"]
    for item in (challenge, assertion, registry, ledger, authority):
        if type(item) is not dict:
            raise ExactFourAuthorityContractError(
                "Trader authorization evidence must use exact JSON objects"
            )

    challenge_digest = _require_content_digest(
        challenge,
        digest_field="challenge_digest",
        label="WebAuthn challenge evidence",
    )
    assertion_digest = _require_content_digest(
        assertion,
        digest_field="assertion_digest",
        label="WebAuthn assertion evidence",
    )
    registry_evidence_digest = _require_content_digest(
        registry,
        digest_field="evidence_digest",
        label="credential registry evidence",
    )
    ledger_event_digest = _require_content_digest(
        ledger,
        digest_field="event_digest",
        label="one-use and counter ledger event",
    )
    ledger_transaction_body = dict(ledger)
    ledger_transaction_body.pop("event_digest")
    claimed_ledger_transaction_digest = ledger_transaction_body.pop(
        "ledger_transaction_digest"
    )
    ledger_transaction_digest = canonical_authority_digest(ledger_transaction_body)
    if claimed_ledger_transaction_digest != ledger_transaction_digest:
        raise ExactFourAuthorityContractError(
            "atomic one-use and counter transaction digest mismatch"
        )
    _require_content_digest(
        authority,
        digest_field="event_digest",
        label="authority-event/v2 Trader event",
    )
    payload = _parse_authority_payload(authority)

    subject_id = subject.approval_subject_id
    environments = {
        challenge["environment"],
        assertion["environment"],
        registry["environment"],
        ledger["environment"],
        authority["environment"],
        payload["environment"],
    }
    if len(environments) != 1:
        raise ExactFourAuthorityContractError(
            "Trader evidence environment splice is forbidden"
        )
    environment = challenge["environment"]
    if any(
        value != subject_id
        for value in (
            document["approval_subject_id"],
            challenge["approval_subject_id"],
            assertion["approval_subject_id"],
            ledger["approval_subject_id"],
            authority["subject_id"],
            payload["approval_subject_id"],
        )
    ):
        raise ExactFourAuthorityContractError(
            "Trader envelope does not bind the supplied pre-approval subject"
        )
    if challenge["one_use_key"] != _challenge_one_use_key(challenge):
        raise ExactFourAuthorityContractError(
            "WebAuthn challenge one-use key does not bind its full body"
        )
    challenge_fields = (
        "environment",
        "challenge_id",
        "approval_subject_id",
        "rp_policy_generation",
        "rp_policy_digest",
        "rp_id",
        "origin",
        "one_use_key",
    )
    if any(assertion[field] != challenge[field] for field in challenge_fields) or (
        assertion["challenge_digest"] != challenge_digest
    ):
        raise ExactFourAuthorityContractError(
            "WebAuthn assertion does not bind the exact challenge"
        )
    _validate_rp_origin(challenge["rp_id"], challenge["origin"])
    _validate_webauthn_bytes(challenge, assertion)

    registry_fields = (
        "environment",
        "rp_policy_generation",
        "rp_policy_digest",
        "rp_id",
        "origin",
        "credential_id_base64url",
    )
    if any(registry[field] != assertion[field] for field in registry_fields) or (
        document["issuer_key_id"] != registry["credential_id_base64url"]
        or document["issuer_key_algorithm"] != registry["credential_algorithm"]
        or document["issuer_key_backend"] != registry["key_backend"]
        or document["issuer_key_registry_generation"]
        != registry["registry_generation"]
        or document["issuer_key_registry_digest"]
        != registry["registry_digest"]
    ):
        raise ExactFourAuthorityContractError(
            "Trader envelope does not bind governed RP and credential evidence"
        )
    ledger_links = {
        "environment": environment,
        "approval_subject_id": subject_id,
        "challenge_id": challenge["challenge_id"],
        "challenge_digest": challenge_digest,
        "assertion_digest": assertion_digest,
        "one_use_key": challenge["one_use_key"],
        "credential_id_base64url": assertion["credential_id_base64url"],
        "credential_registry_generation": registry["registry_generation"],
        "credential_registry_digest": registry["registry_digest"],
        "counter_mode": registry["counter_mode"],
        "prior_sign_count": registry["stored_sign_count"],
        "asserted_sign_count": assertion["sign_count"],
    }
    if any(ledger[key] != value for key, value in ledger_links.items()):
        raise ExactFourAuthorityContractError(
            "one-use and counter transaction does not bind exact assertion state"
        )
    if ledger["counter_mode"] == "COUNTING":
        if not (
            ledger["prior_sign_count"] < ledger["asserted_sign_count"]
            == ledger["result_sign_count"]
            and ledger["counter_cas_status"] == "APPLIED"
        ):
            raise ExactFourAuthorityContractError(
                "counting credential CAS must advance prior to asserted result"
            )
    elif not (
        ledger["prior_sign_count"]
        == ledger["asserted_sign_count"]
        == ledger["result_sign_count"]
        == 0
        and ledger["counter_cas_status"] == "NOT_APPLICABLE"
    ):
        raise ExactFourAuthorityContractError(
            "counterless credential must keep every counter at zero"
        )

    request_id = _authority_request_id(
        environment=environment,
        subject_id=subject_id,
        challenge_digest=challenge_digest,
        assertion_digest=assertion_digest,
        registry_evidence_digest=registry_evidence_digest,
        ledger_transaction_digest=ledger_transaction_digest,
        ledger_event_digest=ledger_event_digest,
    )
    authorization_decision_id = _authorization_decision_id(
        environment=environment,
        subject_id=subject_id,
        request_id=request_id,
        challenge_digest=challenge_digest,
        assertion_digest=assertion_digest,
        registry_evidence_digest=registry_evidence_digest,
        ledger_transaction_digest=ledger_transaction_digest,
        ledger_event_digest=ledger_event_digest,
    )
    authority_transaction_idempotency_key = (
        _authority_transaction_idempotency_key(
            environment=environment,
            subject_id=subject_id,
            request_id=request_id,
            authorization_decision_id=authorization_decision_id,
            ledger_transaction_digest=ledger_transaction_digest,
            ledger_event_digest=ledger_event_digest,
        )
    )
    if document["authorization_decision_id"] != authorization_decision_id:
        raise ExactFourAuthorityContractError(
            "Trader envelope authorization decision id is not evidence-bound"
        )
    if authority["request_id"] != request_id or authority[
        "idempotency_key"
    ] != _authority_idempotency_key(
        environment=environment,
        request_id=request_id,
        subject_id=subject_id,
        payload_schema=authority["payload_schema"],
        payload_digest=authority["payload_digest"],
    ):
        raise ExactFourAuthorityContractError(
            "Trader authority request or idempotency key mismatch"
        )
    sequence = authority["sequence"]
    prior_sequence = payload["prior_sequence"]
    if type(prior_sequence) is not int or prior_sequence < 0 or sequence != (
        prior_sequence + 1
    ):
        raise ExactFourAuthorityContractError(
            "Trader authority sequence is not prior sequence plus one"
        )
    if (prior_sequence == 0) != (authority["prior_event_digest"] is None):
        raise ExactFourAuthorityContractError(
            "Trader authority prior sequence and digest disagree"
        )
    expected_payload = {
        "environment": environment,
        "authority_backend_id": document["issuer_backend_id"],
        "authority_backend_generation": document["issuer_backend_generation"],
        "prior_event_digest": authority["prior_event_digest"],
        "authority_event_id": authority["event_id"],
        "authority_request_id": authority["request_id"],
        "authorization_decision_id": authorization_decision_id,
        "authority_transaction_idempotency_key": (
            authority_transaction_idempotency_key
        ),
        "authority_sequence": authority["sequence"],
        "approval_subject_id": subject_id,
        "challenge_digest": challenge_digest,
        "assertion_digest": assertion_digest,
        "credential_registry_evidence_digest": registry_evidence_digest,
        "one_use_ledger_generation": ledger["ledger_generation"],
        "one_use_ledger_transaction_id": ledger["ledger_transaction_id"],
        "one_use_ledger_transaction_digest": ledger_transaction_digest,
        "one_use_ledger_event_id": ledger["event_id"],
        "one_use_ledger_event_digest": ledger_event_digest,
        "one_use_ledger_commit_status": ledger["transaction_status"],
    }
    if any(payload[key] != value for key, value in expected_payload.items()):
        raise ExactFourAuthorityContractError(
            "Trader authority event does not bind the full evidence transaction"
        )
    if (
        document["issued_at"] != authority["observed_at"]
        or document["expires_at"] != challenge["expires_at"]
    ):
        raise ExactFourAuthorityContractError(
            "Trader authorization lifetime is not deterministically derived"
        )

    challenge_issued, challenge_expires = _require_bounded_window(
        challenge["issued_at"],
        challenge["expires_at"],
        ttl_seconds=subject.lease_ttl_seconds,
        label="Trader WebAuthn challenge",
    )
    ready_issued = _parsed_timestamp(subject.ready_issued_at, "ready_issued_at")
    ready_expires = _parsed_timestamp(subject.ready_expires_at, "ready_expires_at")
    asserted_at = _parsed_timestamp(assertion["asserted_at"], "asserted_at")
    credential_effective = _parsed_timestamp(
        registry["effective_at"], "credential effective_at"
    )
    credential_observed = _parsed_timestamp(
        registry["observed_at"], "credential observed_at"
    )
    consumed_at = _parsed_timestamp(ledger["consumed_at"], "consumed_at")
    ledger_committed = _parsed_timestamp(
        ledger["transaction_committed_at"], "ledger transaction_committed_at"
    )
    recorded_at = _parsed_timestamp(payload["recorded_at"], "recorded_at")
    authority_observed = _parsed_timestamp(
        authority["observed_at"], "authority observed_at"
    )
    envelope_issued, envelope_expires = _require_bounded_window(
        document["issued_at"],
        document["expires_at"],
        ttl_seconds=subject.lease_ttl_seconds,
        label="Trader authorization envelope",
    )
    if not (
        ready_issued
        <= challenge_issued
        <= asserted_at
        <= credential_observed
        <= consumed_at
        <= ledger_committed
        <= recorded_at
        <= authority_observed
        <= envelope_issued
        < envelope_expires
        <= challenge_expires
        <= ready_expires
    ) or not credential_effective <= asserted_at:
        raise ExactFourAuthorityContractError(
            "Trader authorization evidence lifetime or event order is invalid"
        )


@dataclass(frozen=True, slots=True, init=False)
class UnverifiedExactFourTraderAuthorizationEnvelopeV2:
    """Structurally valid envelope; deliberately not an authorization token."""

    _canonical_document: bytes
    _authorization_id: str
    _authorization_decision_id: str
    _approval_subject_id: str

    def __init__(self, document: Mapping[str, Any]) -> None:
        copied = dict(document)
        _require_exact_json(copied)
        object.__setattr__(self, "_canonical_document", _canonical_bytes(copied))
        object.__setattr__(
            self,
            "_authorization_id",
            _require_digest(copied.get("authorization_id"), "authorization_id"),
        )
        object.__setattr__(
            self,
            "_authorization_decision_id",
            _require_digest(
                copied.get("authorization_decision_id"),
                "authorization_decision_id",
            ),
        )
        object.__setattr__(
            self,
            "_approval_subject_id",
            _require_digest(copied.get("approval_subject_id"), "approval_subject_id"),
        )

    @property
    def authorization_id(self) -> str:
        return self._authorization_id

    @property
    def authorization_decision_id(self) -> str:
        return self._authorization_decision_id

    @property
    def approval_subject_id(self) -> str:
        return self._approval_subject_id

    def to_dict(self) -> dict[str, Any]:
        return _strict_json_loads(
            self._canonical_document,
            label="stored exact-four Trader envelope v2",
        )


def parse_and_validate_unverified_exact_four_trader_authorization_envelope_v2(
    raw: bytes | str,
    *,
    subject: UnverifiedExactFourTraderApprovalSubjectV2,
) -> UnverifiedExactFourTraderAuthorizationEnvelopeV2:
    """Validate wire shape and lineage only; positive authority stays PENDING."""

    if type(subject) is not UnverifiedExactFourTraderApprovalSubjectV2:
        raise ExactFourAuthorityContractError(
            "exact unverified Trader pre-approval subject v2 required"
        )
    document = _strict_json_loads(raw, label="unverified Trader envelope v2")
    _validate_schema(document)
    if document.get("format") != TRADER_AUTHORIZATION_ENVELOPE_FORMAT:
        raise ExactFourAuthorityContractError(
            "unverified exact-four Trader authorization envelope v2 required"
        )
    _validate_envelope_links_and_time(document, subject=subject)
    _require_content_digest(
        document,
        digest_field="authorization_id",
        label="Trader authorization envelope",
    )
    return UnverifiedExactFourTraderAuthorizationEnvelopeV2(document)


def require_current_exact_four_trader_authorization_v2(
    value: Any,
) -> VerifiedExactFourTraderAuthorizationV2:
    """Positive gate: structurally valid evidence still cannot authorize."""

    del value
    raise ExactFourAuthorityPending(
        "exact-four Trader v2 positive verification is unavailable: "
        f"{TRADER_AUTHORIZATION_V2_STATE}"
    )


__all__ = [
    "EXACT_FOUR_TRADER_AUTHORIZATION_SCHEMA_REL",
    "PINNED_EXACT_FOUR_TRADER_AUTHORIZATION_SCHEMA_DIGEST",
    "PINNED_EXACT_FOUR_TRADER_AUTHORIZATION_SCHEMA_RAW_DIGEST",
    "TRADER_APPROVAL_SUBJECT_FORMAT",
    "TRADER_APPROVAL_SUBJECT_SCOPE",
    "TRADER_AUTHORIZATION_ENVELOPE_FORMAT",
    "TRADER_AUTHORIZATION_ISSUER_V2",
    "TRADER_AUTHORIZATION_V2_STATE",
    "TRADER_V2_ACTIVE_CREDENTIAL_REGISTRY_COUNT",
    "TRADER_V2_ACTIVE_RP_REGISTRY_COUNT",
    "ExactFourTraderAuthorityDecisionStoreV2",
    "UnverifiedExactFourTraderApprovalSubjectV2",
    "UnverifiedExactFourTraderAuthorizationEnvelopeV2",
    "authorize_controlled_exact_four_execution_v2",
    "compile_unverified_exact_four_trader_approval_subject_v2",
    "derive_exact_four_trader_one_use_key_v2",
    "exact_four_trader_authorization_schema_path",
    "load_exact_four_trader_authorization_schema",
    "parse_and_validate_unverified_exact_four_trader_approval_subject_v2",
    "parse_and_validate_unverified_exact_four_trader_authorization_envelope_v2",
    "prepare_exact_four_trader_approval_subject_v2",
    "require_current_exact_four_trader_authorization_v2",
]
