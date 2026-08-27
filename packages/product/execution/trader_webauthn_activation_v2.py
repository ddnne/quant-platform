"""Root-owned live activation loader for the Trader AuthorityServer."""

from __future__ import annotations

import base64
import os
import re
import stat
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives import serialization

from execution.exact_four_codec import (
    ExactFourAuthorityPending,
    _strict_json_loads,
)
from execution.exact_four_trader_v2 import (
    _decode_canonical_base64url,
)
from scripts.finding_ledger_gate import require_pinned_finding_ledger_gate
from execution.trader_webauthn_authority_core_v2 import (
    ExactFourTraderWebAuthnAuthorityV2,
)
from execution.trader_webauthn_ledger_v2 import (
    SQLiteExactFourTraderLedgerV2,
    _AUTHORITY_CONSTRUCTION_TOKEN,
)
from execution.trader_webauthn_registry_v2 import (
    ExactFourTraderCredentialRegistryV2,
    ExactFourTraderCredentialV2,
    ExactFourTraderRelyingPartyRegistryV2,
    ExactFourTraderRelyingPartyV2,
)
from execution.secure_authority_files_v2 import read_pinned_authority_file_v2


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
TRADER_AUTHORITY_ACTIVATION_PATH = Path(
    "/etc/quant-platform/authorities/trader/activation.json"
)
_SHA256_RE = re.compile(r"sha256:[0-9a-f]{64}\Z")

def _load_live_activation_document() -> dict[str, Any]:
    path = TRADER_AUTHORITY_ACTIVATION_PATH
    try:
        raw = read_pinned_authority_file_v2(
            path,
            chain_root=Path("/"),
            directory_owner_uids={0},
            expected_file_uid=0,
            allowed_file_modes=frozenset(
                {0o400, 0o440, 0o444, 0o600, 0o640, 0o644}
            ),
            max_bytes=1024 * 1024,
        )
    except OSError as exc:
        raise ExactFourAuthorityPending(TRADER_AUTHORITY_LIVE_STATE) from exc
    document = _strict_json_loads(raw, label="Trader authority activation state")
    required = {
        "format",
        "environment",
        "service_uid",
        "controlled_execution_uid",
        "controlled_execution_socket_path",
        "store_path",
        "registration_payload_validated",
        "attestation_state",
        "human_enrollment_witness_digest",
        "trusted_attestation_evidence_digest",
        "protected_store_observed",
        "enrollment_transcript_digest",
        "rp_registry",
        "credential_registry",
    }
    if set(document) != required or document.get("format") != (
        "exact-four-trader-authority-activation/v2"
    ):
        raise ExactFourAuthorityPending(
            "Trader activation state fields or format are invalid"
        )
    return document


def _load_live_exact_four_trader_authority_v2(
    *, server_bound: bool
) -> ExactFourTraderWebAuthnAuthorityV2:
    """Load fixed activation for either observation or the server entrypoint."""

    document = _load_live_activation_document()
    environment = document["environment"]
    service_uid = document["service_uid"]
    controlled_uid = document["controlled_execution_uid"]
    store_text = document["store_path"]
    controlled_socket_text = document["controlled_execution_socket_path"]
    attestation_state = document["attestation_state"]
    witness_digest = document["human_enrollment_witness_digest"]
    trusted_attestation_digest = document["trusted_attestation_evidence_digest"]
    witness_verified = (
        type(witness_digest) is str and _SHA256_RE.fullmatch(witness_digest) is not None
    )
    trusted_attestation_verified = (
        attestation_state == "TRUSTED"
        and type(trusted_attestation_digest) is str
        and _SHA256_RE.fullmatch(trusted_attestation_digest) is not None
    )
    if (
        environment not in {"staging", "production"}
        or type(service_uid) is not int
        or service_uid <= 0
        or type(controlled_uid) is not int
        or controlled_uid <= 0
        or controlled_uid == service_uid
        or os.geteuid() != service_uid
        or type(store_text) is not str
        or type(controlled_socket_text) is not str
        or document["registration_payload_validated"] is not True
        or attestation_state not in {"UNATTESTED", "TRUSTED"}
        or (
            witness_digest is not None
            and not witness_verified
        )
        or (
            trusted_attestation_digest is not None
            and type(trusted_attestation_digest) is not str
        )
        or (
            type(trusted_attestation_digest) is str
            and _SHA256_RE.fullmatch(trusted_attestation_digest) is None
        )
        or (attestation_state == "UNATTESTED" and trusted_attestation_digest is not None)
        or (attestation_state == "TRUSTED" and not trusted_attestation_verified)
        or not (witness_verified or trusted_attestation_verified)
        or document["protected_store_observed"] is not True
        or type(document["enrollment_transcript_digest"]) is not str
        or not _SHA256_RE.fullmatch(document["enrollment_transcript_digest"])
    ):
        raise ExactFourAuthorityPending(
            "Trader principal, enrollment, or controlled peer is not observed"
        )
    controlled_socket_path = Path(controlled_socket_text)
    if not controlled_socket_path.is_absolute():
        raise ExactFourAuthorityPending(
            "controlled execution socket path is not absolute"
        )
    try:
        controlled_socket_stat = controlled_socket_path.lstat()
    except OSError as exc:
        raise ExactFourAuthorityPending(
            "controlled execution socket is not observed"
        ) from exc
    if (
        not stat.S_ISSOCK(controlled_socket_stat.st_mode)
        or controlled_socket_stat.st_uid != controlled_uid
        or controlled_socket_stat.st_mode & 0o002
    ):
        raise ExactFourAuthorityPending(
            "controlled execution socket identity or permissions are invalid"
        )
    store_path = Path(store_text)
    if not store_path.is_absolute() or not store_path.parent.exists():
        raise ExactFourAuthorityPending(
            "Trader protected store path is absent or not absolute"
        )
    parent_stat = store_path.parent.lstat()
    if (
        not stat.S_ISDIR(parent_stat.st_mode)
        or parent_stat.st_uid != service_uid
        or parent_stat.st_mode & 0o077
    ):
        raise ExactFourAuthorityPending(
            "Trader store directory is not service-owned mode 0700"
        )
    if store_path.exists():
        store_stat = store_path.lstat()
        if (
            not stat.S_ISREG(store_stat.st_mode)
            or store_stat.st_uid != service_uid
            or store_stat.st_mode & 0o077
        ):
            raise ExactFourAuthorityPending(
                "Trader ledger is not service-owned and private"
            )
    rp_document = document["rp_registry"]
    if (
        type(rp_document) is not dict
        or set(rp_document) != {"generation", "entries"}
        or type(rp_document["entries"]) is not list
    ):
        raise ExactFourAuthorityPending("Trader RP activation registry is invalid")
    rp_entries: list[ExactFourTraderRelyingPartyV2] = []
    for row in rp_document["entries"]:
        if type(row) is not dict or set(row) != {
            "environment",
            "policy_id",
            "policy_generation",
            "rp_id",
            "origin",
            "effective_at",
            "status",
            "user_presence_required",
            "user_verification_required",
        }:
            raise ExactFourAuthorityPending(
                "Trader RP activation row is not closed"
            )
        rp_entries.append(ExactFourTraderRelyingPartyV2(**row))
    relying_parties = ExactFourTraderRelyingPartyRegistryV2(
        tuple(rp_entries), generation=rp_document["generation"]
    )
    credential_document = document["credential_registry"]
    if (
        type(credential_document) is not dict
        or set(credential_document) != {"registry_id", "generation", "credentials"}
        or type(credential_document["credentials"]) is not list
    ):
        raise ExactFourAuthorityPending(
            "Trader credential activation registry is invalid"
        )
    credential_entries: list[ExactFourTraderCredentialV2] = []
    for row in credential_document["credentials"]:
        required_fields = {
            "environment",
            "credential_id_base64url",
            "public_key_spki_der_base64",
            "rp_policy_digest",
            "effective_at",
            "initial_sign_count",
            "counter_mode",
            "status",
            "algorithm",
            "key_backend",
        }
        if type(row) is not dict or set(row) != required_fields:
            raise ExactFourAuthorityPending(
                "Trader credential activation row is not closed"
            )
        expected_backend = (
            "UNATTESTED"
            if attestation_state == "UNATTESTED"
            else "webauthn_platform_or_hardware"
        )
        if row.get("status") != "ACTIVE" or row.get("key_backend") != expected_backend:
            raise ExactFourAuthorityPending(
                "Trader credential is not active under the reviewed enrollment trust"
            )
        try:
            credential_id = _decode_canonical_base64url(
                row["credential_id_base64url"],
                label="activation credential id",
                minimum_bytes=16,
                maximum_bytes=1024,
            )
            encoded_key = row["public_key_spki_der_base64"]
            key_bytes = base64.b64decode(encoded_key, validate=True)
            if base64.b64encode(key_bytes).decode("ascii") != encoded_key:
                raise ValueError("non-canonical public key base64")
            public_key = serialization.load_der_public_key(key_bytes)
        except (TypeError, ValueError) as exc:
            raise ExactFourAuthorityPending(
                "Trader activation credential public material is invalid"
            ) from exc
        credential_entries.append(
            ExactFourTraderCredentialV2(
                environment=row["environment"],
                credential_id=credential_id,
                public_key=public_key,  # type: ignore[arg-type]
                rp_policy_digest=row["rp_policy_digest"],
                effective_at=row["effective_at"],
                initial_sign_count=row["initial_sign_count"],
                counter_mode=row["counter_mode"],
                status=row["status"],
                algorithm=row["algorithm"],
                key_backend=row["key_backend"],
            )
        )
    credentials = ExactFourTraderCredentialRegistryV2(
        tuple(credential_entries),
        generation=credential_document["generation"],
        registry_id=credential_document["registry_id"],
    )
    ledger = SQLiteExactFourTraderLedgerV2(
        store_path,
        environment=environment,
        credentials=credentials,
        _token=_AUTHORITY_CONSTRUCTION_TOKEN,
    )
    return ExactFourTraderWebAuthnAuthorityV2(
        environment=environment,
        relying_parties=relying_parties,
        credentials=credentials,
        ledger=ledger,
        clock=lambda: datetime.now(timezone.utc),
        controlled_execution_uid=controlled_uid,
        server_bound=server_bound,
        positive_gate=require_pinned_finding_ledger_gate,
        _token=_AUTHORITY_CONSTRUCTION_TOKEN,
    )


def open_live_exact_four_trader_authority_v2() -> ExactFourTraderWebAuthnAuthorityV2:
    """Observe activated state; the returned object cannot launch positive ops."""

    return _load_live_exact_four_trader_authority_v2(server_bound=False)


def _open_server_bound_exact_four_trader_authority_v2(
) -> ExactFourTraderWebAuthnAuthorityV2:
    """Execution-specific adapter hook used only inside UnixAuthorityService."""

    return _load_live_exact_four_trader_authority_v2(server_bound=True)


__all__ = [
    "TRADER_AUTHORITY_ACTIVATION_PATH",
    "TRADER_AUTHORITY_LIVE_STATE",
    "open_live_exact_four_trader_authority_v2",
]
