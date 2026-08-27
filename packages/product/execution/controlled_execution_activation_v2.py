"""Root-owned activation loader for the Controlled AuthorityServer."""

from __future__ import annotations

import base64
import os
import stat
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from execution.exact_four_codec import (
    ExactFourAuthorityPending,
    _strict_json_loads,
)
from execution.exact_four_trader_v2 import (
    _decode_canonical_base64url,
)
from execution.trader_webauthn_authority_v2 import (
    ExactFourTraderCredentialRegistryV2,
    ExactFourTraderCredentialV2,
    ExactFourTraderRelyingPartyRegistryV2,
    ExactFourTraderRelyingPartyV2,
)
from execution.controlled_execution_store_v2 import (
    SQLiteControlledExecutionWriterV2,
    _WRITER_CONSTRUCTION_TOKEN,
)
from execution.controlled_execution_types_v2 import _ControlledWriterSignerV2
from execution.controlled_execution_budget_v2 import (
    ControlledPersistentBudgetLedgerV2,
)
from execution.controlled_execution_runtime_v2 import (
    ControlledExecutionRuntimeV2,
    UnixControlledExecutionProviderV2,
    _build_server_controlled_execution_runtime_v2,
    open_pinned_controlled_snapshot_v2,
)
from selection.budget_ledger import ResearchBudgetCapability
from selection.screen import OfflineExperimentBudget
from execution.secure_authority_files_v2 import read_pinned_authority_file_v2


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

_MAX_FRAME_BYTES = 1024 * 1024
_MAX_HANDOFF_BYTES = 1024 * 1024


def _activation_absolute_path(document: dict[str, Any], field: str) -> Path:
    value = document.get(field)
    if (
        type(value) is not str
        or not value
        or value != value.strip()
        or not os.path.isabs(value)
        or os.path.abspath(value) != value
    ):
        raise ExactFourAuthorityPending(
            f"Controlled activation {field} is not one canonical absolute path"
        )
    return Path(value)


def _load_root_owned_activation() -> dict[str, Any]:
    path = CONTROLLED_EXECUTION_ACTIVATION_PATH
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
        raise ExactFourAuthorityPending(CONTROLLED_WRITER_LIVE_STATE) from exc
    document = _strict_json_loads(raw, label="Controlled authority activation state")
    required = {
        "format",
        "environment",
        "service_uid",
        "trader_uid",
        "store_path",
        "signer_key_id",
        "private_key_path",
        "budget_id",
        "budget_ledger_path",
        "immutable_snapshot_path",
        "signed_projection_path",
        "provider_socket_path",
        "provider_uid",
        "provider_timeout_seconds",
        "protected_store_observed",
        "protected_signing_key_observed",
        "rp_registry",
        "credential_registry",
    }
    if set(document) != required or document.get("format") != (
        "exact-four-controlled-execution-activation/v2"
    ):
        raise ExactFourAuthorityPending(
            "Controlled activation state fields or format are invalid"
        )
    return document


def _activation_registries(
    document: dict[str, Any],
) -> tuple[
    ExactFourTraderRelyingPartyRegistryV2,
    ExactFourTraderCredentialRegistryV2,
]:
    rp_document = document["rp_registry"]
    if (
        type(rp_document) is not dict
        or set(rp_document) != {"generation", "entries"}
        or type(rp_document["entries"]) is not list
    ):
        raise ExactFourAuthorityPending("Controlled RP activation registry is invalid")
    rp_rows: list[ExactFourTraderRelyingPartyV2] = []
    rp_fields = {
        "environment",
        "policy_id",
        "policy_generation",
        "rp_id",
        "origin",
        "effective_at",
        "status",
        "user_presence_required",
        "user_verification_required",
    }
    for row in rp_document["entries"]:
        if type(row) is not dict or set(row) != rp_fields:
            raise ExactFourAuthorityPending("Controlled RP activation row is not closed")
        rp_rows.append(ExactFourTraderRelyingPartyV2(**row))
    rps = ExactFourTraderRelyingPartyRegistryV2(
        tuple(rp_rows), generation=rp_document["generation"]
    )

    credential_document = document["credential_registry"]
    if (
        type(credential_document) is not dict
        or set(credential_document) != {"registry_id", "generation", "credentials"}
        or type(credential_document["credentials"]) is not list
    ):
        raise ExactFourAuthorityPending(
            "Controlled credential activation registry is invalid"
        )
    credential_fields = {
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
    credentials: list[ExactFourTraderCredentialV2] = []
    for row in credential_document["credentials"]:
        if type(row) is not dict or set(row) != credential_fields:
            raise ExactFourAuthorityPending(
                "Controlled credential activation row is not closed"
            )
        try:
            credential_id = _decode_canonical_base64url(
                row["credential_id_base64url"],
                label="Controlled activation credential id",
                minimum_bytes=16,
                maximum_bytes=1024,
            )
            key_text = row["public_key_spki_der_base64"]
            key_bytes = base64.b64decode(key_text, validate=True)
            if base64.b64encode(key_bytes).decode("ascii") != key_text:
                raise ValueError("non-canonical public key base64")
            public_key = serialization.load_der_public_key(key_bytes)
        except (TypeError, ValueError) as exc:
            raise ExactFourAuthorityPending(
                "Controlled activation credential public material is invalid"
            ) from exc
        credentials.append(
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
    registry = ExactFourTraderCredentialRegistryV2(
        tuple(credentials),
        generation=credential_document["generation"],
        registry_id=credential_document["registry_id"],
    )
    return rps, registry


def _load_live_controlled_execution_writer_v2(
    *, server_bound: bool
) -> SQLiteControlledExecutionWriterV2:
    """Load fixed activation for observation or the AuthorityServer entrypoint."""

    document = _load_root_owned_activation()
    environment = document["environment"]
    service_uid = document["service_uid"]
    trader_uid = document["trader_uid"]
    if (
        environment not in {"staging", "production"}
        or type(service_uid) is not int
        or service_uid <= 0
        or type(trader_uid) is not int
        or trader_uid <= 0
        or trader_uid == service_uid
        or os.geteuid() != service_uid
        or document["protected_store_observed"] is not True
        or document["protected_signing_key_observed"] is not True
    ):
        raise ExactFourAuthorityPending(
            "Controlled principal, protected store, key, or Trader peer is absent"
        )
    store_path = _activation_absolute_path(document, "store_path")
    key_path = _activation_absolute_path(document, "private_key_path")
    if (
        not store_path.is_absolute()
        or not key_path.is_absolute()
        or not store_path.parent.exists()
    ):
        raise ExactFourAuthorityPending(
            "Controlled protected paths are absent or not absolute"
        )
    parent = store_path.parent.lstat()
    if (
        not stat.S_ISDIR(parent.st_mode)
        or parent.st_uid != service_uid
        or parent.st_mode & 0o077
    ):
        raise ExactFourAuthorityPending(
            "Controlled store directory is not service-owned mode 0700"
        )
    if store_path.exists():
        stored = store_path.lstat()
        if (
            not stat.S_ISREG(stored.st_mode)
            or stored.st_uid != service_uid
            or stored.st_mode & 0o077
        ):
            raise ExactFourAuthorityPending(
                "Controlled store is not service-owned and private"
            )
    try:
        key_bytes = read_pinned_authority_file_v2(
            key_path,
            chain_root=Path("/"),
            directory_owner_uids={0, service_uid},
            expected_file_uid=service_uid,
            allowed_file_modes=frozenset({0o400, 0o600}),
            max_bytes=64 * 1024,
        )
    except OSError as exc:
        raise ExactFourAuthorityPending(
            "Controlled protected signing key is absent"
        ) from exc
    try:
        private_key = serialization.load_pem_private_key(key_bytes, password=None)
    except (TypeError, ValueError) as exc:
        raise ExactFourAuthorityPending(
            "Controlled protected signing key cannot be decoded"
        ) from exc
    if not isinstance(private_key, Ed25519PrivateKey):
        raise ExactFourAuthorityPending(
            "Controlled protected signing key is not Ed25519"
        )
    key_id = document["signer_key_id"]
    if type(key_id) is not str or not key_id or key_id != key_id.strip():
        raise ExactFourAuthorityPending("Controlled signer key id is invalid")
    rps, credentials = _activation_registries(document)
    return SQLiteControlledExecutionWriterV2(
        store_path,
        environment=environment,
        signer=_ControlledWriterSignerV2(key_id=key_id, private_key=private_key),
        clock=lambda: datetime.now(timezone.utc),
        trader_uid=trader_uid,
        relying_parties=rps,
        credentials=credentials,
        server_bound=server_bound,
        test_mode=False,
        _token=_WRITER_CONSTRUCTION_TOKEN,
    )


def _load_live_controlled_execution_runtime_v2() -> ControlledExecutionRuntimeV2:
    """Build the fixed provider/budget/snapshot runtime from root activation."""

    document = _load_root_owned_activation()
    environment = document["environment"]
    service_uid = document["service_uid"]
    provider_uid = document["provider_uid"]
    budget_id = document["budget_id"]
    budget_path = _activation_absolute_path(document, "budget_ledger_path")
    snapshot_path = _activation_absolute_path(document, "immutable_snapshot_path")
    projection_path = _activation_absolute_path(document, "signed_projection_path")
    provider_socket = _activation_absolute_path(document, "provider_socket_path")
    timeout_seconds = document.get("provider_timeout_seconds")
    if (
        environment not in {"staging", "production"}
        or type(service_uid) is not int
        or service_uid <= 0
        or os.geteuid() != service_uid
        or type(provider_uid) is not int
        or provider_uid <= 0
        or provider_uid == service_uid
        or type(budget_id) is not str
        or not budget_id
        or budget_id != budget_id.strip()
        or type(timeout_seconds) not in {int, float}
        or not 0 < float(timeout_seconds) <= 300
        or document["protected_store_observed"] is not True
    ):
        raise ExactFourAuthorityPending(
            "Controlled runtime principal, budget, snapshot, or provider is absent"
        )
    for path, label in (
        (budget_path, "budget ledger"),
        (snapshot_path, "immutable snapshot"),
        (projection_path, "signed projection"),
    ):
        if not path.is_absolute() or not path.parent.exists():
            raise ExactFourAuthorityPending(
                f"Controlled {label} protected path is absent"
            )
    try:
        provider_metadata = provider_socket.lstat()
    except OSError as exc:
        raise ExactFourAuthorityPending(
            "Controlled provider socket is absent"
        ) from exc
    if (
        not stat.S_ISSOCK(provider_metadata.st_mode)
        or provider_metadata.st_uid != provider_uid
        or provider_metadata.st_mode & 0o002
    ):
        raise ExactFourAuthorityPending(
            "Controlled provider socket identity or permissions are invalid"
        )
    try:
        budget_parent = budget_path.parent.lstat()
        budget_metadata = budget_path.lstat()
    except OSError as exc:
        raise ExactFourAuthorityPending(
            "Controlled budget ledger must be pre-provisioned"
        ) from exc
    if (
        not stat.S_ISDIR(budget_parent.st_mode)
        or budget_parent.st_uid != service_uid
        or stat.S_IMODE(budget_parent.st_mode) != 0o700
        or not stat.S_ISREG(budget_metadata.st_mode)
        or budget_metadata.st_uid != service_uid
        or budget_metadata.st_nlink != 1
        or stat.S_IMODE(budget_metadata.st_mode) != 0o600
    ):
        raise ExactFourAuthorityPending(
            "Controlled budget ledger is not a private single-link service store"
        )
    budget = ResearchBudgetCapability(
        budget_id=budget_id,
        ledger_path=budget_path,
        limits=OfflineExperimentBudget(),
    )
    clock = lambda: datetime.now(timezone.utc)
    budget_ledger = ControlledPersistentBudgetLedgerV2(
        budget=budget,
        environment=environment,
        clock=clock,
    )
    # Startup never retries work with an unknown provider outcome.
    budget_ledger.recover_unfinished()
    snapshot = open_pinned_controlled_snapshot_v2(
        snapshot_path=str(snapshot_path),
        projection_path=str(projection_path),
        expected_uid=0,
        chain_root="/",
    )
    provider = UnixControlledExecutionProviderV2(
        socket_path=str(provider_socket),
        provider_uid=provider_uid,
        timeout_seconds=timeout_seconds,
    )
    return _build_server_controlled_execution_runtime_v2(
        environment=environment,
        provider=provider,
        budget=budget_ledger,
        snapshot=snapshot,
    )


def open_live_controlled_execution_writer_v2() -> SQLiteControlledExecutionWriterV2:
    """Observe activated state; the returned object cannot launch positive ops."""

    return _load_live_controlled_execution_writer_v2(server_bound=False)


def _open_server_bound_controlled_execution_writer_v2(
) -> SQLiteControlledExecutionWriterV2:
    """Execution adapter hook used only inside UnixAuthorityService."""

    return _load_live_controlled_execution_writer_v2(server_bound=True)


def _open_server_bound_controlled_execution_runtime_v2(
) -> ControlledExecutionRuntimeV2:
    """Provider runtime hook used only by the local AuthorityServer adapter."""

    return _load_live_controlled_execution_runtime_v2()


__all__ = [
    "CONTROLLED_EXECUTION_ACTIVATION_PATH",
    "CONTROLLED_WRITER_LIVE_STATE",
    "open_live_controlled_execution_writer_v2",
]
