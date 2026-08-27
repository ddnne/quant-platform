"""Root-owned activation loader for the Controlled AuthorityServer."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import pwd
import sqlite3
import stat
import urllib.parse
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from selection.budget_ledger import ResearchBudgetCapability
from selection.screen import OfflineExperimentBudget

from execution.controlled_execution_budget_v2 import (
    ControlledPersistentBudgetLedgerV2,
)
from execution.controlled_execution_quiescence_v2 import (
    ControlledWriterLifecycleLeaseV2,
    require_held_controlled_writer_lifecycle_v2,
)
from execution.controlled_execution_runtime_v2 import (
    ControlledExecutionRuntimeV2,
    UnixControlledExecutionProviderV2,
    _build_server_controlled_execution_runtime_v2,
    open_pinned_controlled_snapshot_v2,
)
from execution.controlled_ready_custody_v2 import (
    ControlledReadyCustodyV2Error,
    load_controlled_ready_custody_v2,
)
from execution.controlled_execution_store_v2 import (
    _WRITER_CONSTRUCTION_TOKEN,
    SQLiteControlledExecutionWriterV2,
)
from execution.controlled_execution_types_v2 import _ControlledWriterSignerV2
from execution.exact_four_codec import (
    ExactFourAuthorityPending,
    _strict_json_loads,
)
from execution.exact_four_trader_v2 import (
    _decode_canonical_base64url,
)
from execution.secure_authority_files_v2 import read_pinned_authority_file_v2
from execution.trader_webauthn_authority_v2 import (
    ExactFourTraderCredentialRegistryV2,
    ExactFourTraderCredentialV2,
    ExactFourTraderRelyingPartyRegistryV2,
    ExactFourTraderRelyingPartyV2,
)

CONTROLLED_WRITER_MANIFEST_FORMAT = "controlled-exact-four-artifact-manifest/v2"
CONTROLLED_WRITER_ARTIFACT_FORMAT = "controlled-exact-four-artifact/v2"
CONTROLLED_WRITER_EVENT_FORMAT = "controlled-execution-authority-event/v2"
CONTROLLED_WRITER_ISSUER = "ControlledExactFourExecutionWriter/v2"
CONTROLLED_TRADER_HANDOFF_OPERATION = "controlled_execution:consume_trader_handoff"
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
_CONTROLLED_STORE_TABLES = frozenset(
    {
        "controlled_authority_metadata",
        "controlled_credential_counters",
        "controlled_handoffs",
        "controlled_execution_attempts",
        "controlled_artifacts",
        "controlled_writer_events",
        "controlled_manifests",
    }
)
_CONTROLLED_STORE_SCHEMA_DIGEST = (
    "sha256:c39c435e89cba63db7ea1b5ca81805c5e12d985d3025c674cf517c53ccc2ab68"
)
_CONTROLLED_STORE_TRIGGERS = frozenset(
    {
        "controlled_metadata_no_update",
        "controlled_metadata_no_delete",
        "controlled_counters_no_delete",
        "controlled_handoffs_no_update",
        "controlled_handoffs_no_delete",
        "controlled_attempts_no_update",
        "controlled_attempts_no_delete",
        "controlled_artifacts_no_update",
        "controlled_artifacts_no_delete",
        "controlled_writer_events_no_update",
        "controlled_writer_events_no_delete",
        "controlled_manifests_no_update",
        "controlled_manifests_no_delete",
    }
)


def _require_controlled_reader_group_v2(
    *,
    environment: str,
    service_uid: int,
    claimed_gid: int,
) -> None:
    """Bind custody reads to a Controlled-only supplementary group."""

    try:
        from scripts.local_authority_bootstrap_common import (
            BootstrapError,
            _deployments,
            require_controlled_custody_reader_group,
        )
    except ImportError as exc:
        raise ExactFourAuthorityPending(
            "Controlled dedicated reader group is not provisioned"
        ) from exc
    try:
        rows = [
            row
            for row in _deployments(environment)
            if row["authority_id"] == "controlled_execution"
        ]
        if len(rows) != 1:
            raise ValueError("Controlled deployment is not unique")
        row = rows[0]
        account = pwd.getpwuid(service_uid)
        service_group, caller_group, reader_group = (
            require_controlled_custody_reader_group(
                row=row,
                service_account=account,
            )
        )
        supplementary_gids = set(os.getgroups())
    except (BootstrapError, KeyError, OSError, TypeError, ValueError) as exc:
        raise ExactFourAuthorityPending(
            "Controlled dedicated reader group is not provisioned"
        ) from exc
    if (
        row.get("environment") != environment
        or row.get("service_user") != account.pw_name
        or account.pw_uid != service_uid
        or account.pw_gid != service_group.gr_gid
        or reader_group.gr_gid != claimed_gid
        or claimed_gid not in supplementary_gids
        or os.getegid() != caller_group.gr_gid
    ):
        raise ExactFourAuthorityPending(
            "Controlled reader group drifts from its isolated supplementary capability"
        )


def _require_live_controlled_store_identity_v2(
    path: Path,
    *,
    expected_uid: int,
    allow_missing: bool,
) -> tuple[int, int] | None:
    """Return one exact live-store identity without following a final symlink."""

    try:
        observed = path.lstat()
    except FileNotFoundError:
        if allow_missing:
            return None
        raise ExactFourAuthorityPending(
            "Controlled protected store is not provisioned"
        ) from None
    except OSError as exc:
        raise ExactFourAuthorityPending(
            "Controlled protected store identity cannot be observed"
        ) from exc
    if (
        not stat.S_ISREG(observed.st_mode)
        or observed.st_uid != expected_uid
        or stat.S_IMODE(observed.st_mode) != 0o600
        or observed.st_nlink != 1
    ):
        raise ExactFourAuthorityPending(
            "Controlled store is not a private single-link service store"
        )
    return observed.st_dev, observed.st_ino


def _open_or_provision_pinned_live_controlled_store_v2(
    path: Path,
    *,
    expected_uid: int,
) -> tuple[int, tuple[int, int]]:
    """Pin the exact live store, creating it without closing the new inode."""

    existing_flags = (
        os.O_RDWR
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_NONBLOCK", 0)
    )
    create_flags = (
        os.O_RDWR
        | os.O_CREAT
        | os.O_EXCL
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    created = False
    try:
        descriptor = os.open(path, existing_flags)
    except FileNotFoundError:
        try:
            descriptor = os.open(path, create_flags, 0o600)
            created = True
        except FileExistsError:
            try:
                descriptor = os.open(path, existing_flags)
            except OSError as exc:
                raise ExactFourAuthorityPending(
                    "Controlled protected store creation race cannot be pinned"
                ) from exc
        except OSError as exc:
            raise ExactFourAuthorityPending(
                "Controlled protected store cannot be provisioned"
            ) from exc
    except OSError as exc:
        raise ExactFourAuthorityPending(
            "Controlled store is not a private single-link service store"
        ) from exc
    try:
        if created:
            os.fchmod(descriptor, 0o600)
        observed = os.fstat(descriptor)
        lexical = path.lstat()
        if (
            not stat.S_ISREG(observed.st_mode)
            or observed.st_uid != expected_uid
            or stat.S_IMODE(observed.st_mode) != 0o600
            or observed.st_nlink != 1
            or not stat.S_ISREG(lexical.st_mode)
            or lexical.st_uid != expected_uid
            or stat.S_IMODE(lexical.st_mode) != 0o600
            or lexical.st_nlink != 1
            or (lexical.st_dev, lexical.st_ino)
            != (observed.st_dev, observed.st_ino)
        ):
            raise ExactFourAuthorityPending(
                "Controlled store is not a private single-link service store"
            )
        identity = (observed.st_dev, observed.st_ino)
        os.fsync(descriptor)
        parent_flags = (
            os.O_RDONLY
            | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_DIRECTORY", 0)
            | getattr(os, "O_NOFOLLOW", 0)
        )
        try:
            parent_descriptor = os.open(path.parent, parent_flags)
        except OSError as exc:
            raise ExactFourAuthorityPending(
                "Controlled store directory cannot be synchronized"
            ) from exc
        try:
            os.fsync(parent_descriptor)
        finally:
            os.close(parent_descriptor)
    except OSError as exc:
        os.close(descriptor)
        raise ExactFourAuthorityPending(
            "Controlled protected store cannot be validated while pinned"
        ) from exc
    except BaseException:
        os.close(descriptor)
        raise
    return descriptor, identity


def _audit_live_controlled_store_read_only_v2(
    path: Path,
    *,
    environment: str,
    trader_uid: int,
    signer_key_id: str,
    relying_parties: ExactFourTraderRelyingPartyRegistryV2,
    credentials: ExactFourTraderCredentialRegistryV2,
    expected_uid: int,
) -> dict[str, Any]:
    """Audit the already-provisioned Controlled store without writable open."""

    sidecars = (
        Path(f"{path}-wal"),
        Path(f"{path}-shm"),
        Path(f"{path}-journal"),
    )

    def sidecar_present() -> bool:
        return any(os.path.lexists(item) for item in sidecars)

    try:
        before = path.lstat()
    except OSError as exc:
        raise ExactFourAuthorityPending(
            "Controlled protected store is not provisioned"
        ) from exc
    if (
        not stat.S_ISREG(before.st_mode)
        or before.st_uid != expected_uid
        or stat.S_IMODE(before.st_mode) != 0o600
        or before.st_nlink != 1
        or sidecar_present()
    ):
        raise ExactFourAuthorityPending(
            "Controlled protected store is not an inactive private SQLite store"
        )
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise ExactFourAuthorityPending(
            "Controlled protected store cannot be pinned"
        ) from exc
    pinned_before = os.fstat(descriptor)
    if (pinned_before.st_dev, pinned_before.st_ino) != (
        before.st_dev,
        before.st_ino,
    ):
        os.close(descriptor)
        raise ExactFourAuthorityPending("Controlled store changed before audit")
    try:
        header = os.pread(descriptor, 100, 0)
    except OSError as exc:
        os.close(descriptor)
        raise ExactFourAuthorityPending(
            "Controlled store header cannot be read"
        ) from exc
    if (
        len(header) < 20
        or header[:16] != b"SQLite format 3\x00"
        or header[18:20] != b"\x01\x01"
    ):
        os.close(descriptor)
        raise ExactFourAuthorityPending(
            "Controlled store is not a pinned DELETE-mode SQLite database"
        )
    target = (
        "file:"
        + urllib.parse.quote(f"/dev/fd/{descriptor}", safe="/")
        + "?mode=ro&immutable=1"
    )
    connection: sqlite3.Connection | None = None
    try:
        connection = sqlite3.connect(
            target,
            isolation_level=None,
            timeout=10.0,
            uri=True,
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA query_only=ON")
        connection.execute("PRAGMA trusted_schema=OFF")
        connection.execute("PRAGMA temp_store=MEMORY")
        if str(connection.execute("PRAGMA journal_mode").fetchone()[0]).lower() != (
            "delete"
        ):
            raise ExactFourAuthorityPending(
                "Controlled store journal mode is not DELETE"
            )
        if connection.execute("PRAGMA quick_check").fetchone()[0] != "ok":
            raise ExactFourAuthorityPending("Controlled store integrity check failed")
        if connection.execute("PRAGMA foreign_key_check").fetchone() is not None:
            raise ExactFourAuthorityPending("Controlled store foreign keys are invalid")
        objects = connection.execute(
            "SELECT type,name,tbl_name,sql FROM sqlite_master "
            "WHERE name NOT LIKE 'sqlite_%' ORDER BY type,name"
        ).fetchall()
        schema_inventory = [
            [
                row["type"],
                row["name"],
                row["tbl_name"],
                " ".join(str(row["sql"]).split()),
            ]
            for row in objects
        ]
        schema_digest = (
            "sha256:"
            + hashlib.sha256(
                json.dumps(
                    schema_inventory,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            ).hexdigest()
        )
        tables = {row["name"] for row in objects if row["type"] == "table"}
        triggers = {
            row["name"]: row["sql"] for row in objects if row["type"] == "trigger"
        }
        if (
            schema_digest != _CONTROLLED_STORE_SCHEMA_DIGEST
            or tables != _CONTROLLED_STORE_TABLES
            or set(triggers) != _CONTROLLED_STORE_TRIGGERS
            or any(row["type"] not in {"table", "trigger"} for row in objects)
        ):
            raise ExactFourAuthorityPending("Controlled store schema inventory drifted")
        for name, sql in triggers.items():
            operation = "UPDATE" if name.endswith("_update") else "DELETE"
            normalized = " ".join(str(sql).upper().split())
            if (
                f"BEFORE {operation} ON" not in normalized
                or "RAISE(ABORT" not in normalized
            ):
                raise ExactFourAuthorityPending(
                    "Controlled immutability trigger drifted"
                )
        rp = relying_parties.require(environment)
        expected_metadata = (
            environment,
            trader_uid,
            relying_parties.registry_digest,
            credentials.registry_digest,
            signer_key_id,
        )
        metadata = connection.execute(
            "SELECT environment,trader_uid,rp_registry_digest,"
            "credential_registry_digest,writer_key_id "
            "FROM controlled_authority_metadata ORDER BY environment"
        ).fetchall()
        if [tuple(row) for row in metadata] != [expected_metadata]:
            raise ExactFourAuthorityPending(
                "Controlled store authority identity drifted"
            )
        expected_credentials = {
            credential.credential_id_base64url: credential
            for credential in credentials.credentials
            if credential.environment == environment
            and credential.rp_policy_digest == rp.policy_digest
        }
        counters = connection.execute(
            "SELECT credential_id,public_key_digest,registry_digest,counter_mode,"
            "sign_count FROM controlled_credential_counters WHERE environment=? "
            "ORDER BY credential_id",
            (environment,),
        ).fetchall()
        if {row["credential_id"] for row in counters} != set(expected_credentials):
            raise ExactFourAuthorityPending("Controlled credential inventory drifted")
        for row in counters:
            credential = expected_credentials[row["credential_id"]]
            if (
                row["public_key_digest"] != credential.public_key_digest
                or row["registry_digest"] != credentials.registry_digest
                or row["counter_mode"] != credential.counter_mode
                or type(row["sign_count"]) is not int
                or row["sign_count"] < credential.initial_sign_count
            ):
                raise ExactFourAuthorityPending(
                    "Controlled credential identity drifted"
                )
        counts = {
            name: int(
                connection.execute(f'SELECT COUNT(*) FROM "{name}"').fetchone()[0]
            )
            for name in (
                "controlled_handoffs",
                "controlled_execution_attempts",
                "controlled_artifacts",
                "controlled_writer_events",
                "controlled_manifests",
            )
        }
    except sqlite3.Error as exc:
        raise ExactFourAuthorityPending(
            "Controlled store read-only audit failed"
        ) from exc
    finally:
        if connection is not None:
            connection.close()
        pinned_after = os.fstat(descriptor)
        os.close(descriptor)
    try:
        after = path.lstat()
    except OSError as exc:
        raise ExactFourAuthorityPending(
            "Controlled store changed during audit"
        ) from exc
    stable_fields = (
        "st_dev",
        "st_ino",
        "st_size",
        "st_mtime_ns",
        "st_ctime_ns",
        "st_nlink",
    )
    if (
        any(
            getattr(pinned_before, field) != getattr(pinned_after, field)
            for field in stable_fields
        )
        or any(
            getattr(before, field) != getattr(after, field) for field in stable_fields
        )
        or (after.st_dev, after.st_ino)
        != (
            pinned_after.st_dev,
            pinned_after.st_ino,
        )
        or sidecar_present()
    ):
        raise ExactFourAuthorityPending(
            "Controlled store changed during read-only audit"
        )
    return {
        "schema": "exact-four-controlled-writer-store/v2",
        "environment": environment,
        "trader_uid": trader_uid,
        "rp_registry_digest": relying_parties.registry_digest,
        "credential_registry_digest": credentials.registry_digest,
        "writer_key_id": signer_key_id,
        "credential_count": len(expected_credentials),
        **counts,
    }


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


def _decode_protected_writer_key_v2(key_bytes: bytes) -> Ed25519PrivateKey:
    """Accept only the bootstrap's exact raw Ed25519 seed representation."""

    try:
        if type(key_bytes) is not bytes or len(key_bytes) != 32:
            raise ValueError("Controlled Ed25519 seed must be exactly 32 bytes")
        return Ed25519PrivateKey.from_private_bytes(key_bytes)
    except ValueError as exc:
        raise ExactFourAuthorityPending(
            "Controlled protected signing key cannot be decoded"
        ) from exc


def _load_root_owned_activation() -> dict[str, Any]:
    path = CONTROLLED_EXECUTION_ACTIVATION_PATH
    try:
        raw = read_pinned_authority_file_v2(
            path,
            chain_root=Path("/"),
            directory_owner_uids={0},
            expected_file_uid=0,
            allowed_file_modes=frozenset({0o400, 0o440, 0o444, 0o600, 0o640, 0o644}),
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
        "ready_custody_manifest_path",
        "ready_custody_manifest_digest",
        "controlled_reader_gid",
        "provider_socket_path",
        "provider_uid",
        "provider_timeout_seconds",
        "protected_store_observed",
        "protected_signing_key_observed",
        "rp_registry",
        "credential_registry",
    }
    if set(document) != required or document.get("format") != (
        "exact-four-controlled-execution-activation/v3"
    ):
        raise ExactFourAuthorityPending(
            "Controlled activation state fields or format are invalid"
        )
    if (
        document.get("environment") not in {"staging", "production"}
        or type(document.get("service_uid")) is not int
        or document["service_uid"] <= 0
        or type(document.get("controlled_reader_gid")) is not int
        or document["controlled_reader_gid"] <= 0
    ):
        raise ExactFourAuthorityPending(
            "Controlled activation reader-group binding is invalid"
        )
    _require_controlled_reader_group_v2(
        environment=document["environment"],
        service_uid=document["service_uid"],
        claimed_gid=document["controlled_reader_gid"],
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
            raise ExactFourAuthorityPending(
                "Controlled RP activation row is not closed"
            )
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


def _load_live_controlled_execution_writer_material_v2() -> tuple[
    str,
    Path,
    _ControlledWriterSignerV2,
    int,
    ExactFourTraderRelyingPartyRegistryV2,
    ExactFourTraderCredentialRegistryV2,
]:
    """Validate fixed activation material without opening its product store."""

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
    _require_live_controlled_store_identity_v2(
        store_path,
        expected_uid=service_uid,
        allow_missing=True,
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
    private_key = _decode_protected_writer_key_v2(key_bytes)
    key_id = document["signer_key_id"]
    if type(key_id) is not str or not key_id or key_id != key_id.strip():
        raise ExactFourAuthorityPending("Controlled signer key id is invalid")
    rps, credentials = _activation_registries(document)
    return (
        environment,
        store_path,
        _ControlledWriterSignerV2(key_id=key_id, private_key=private_key),
        trader_uid,
        rps,
        credentials,
    )


def _preflight_live_controlled_execution_writer_v2() -> tuple[
    str,
    Path,
    str,
    str,
    int,
]:
    """Return only non-secret identity after a read-only activation preflight."""

    environment, store_path, signer, trader_uid, _rps, _credentials = (
        _load_live_controlled_execution_writer_material_v2()
    )
    public = base64.b64encode(
        signer.private_key.public_key().public_bytes(
            serialization.Encoding.Raw,
            serialization.PublicFormat.Raw,
        )
    ).decode("ascii")
    return environment, store_path, signer.key_id, public, trader_uid


def _preflight_inactive_canary_controlled_execution_writer_v2() -> tuple[
    str,
    Path,
    str,
    str,
    int,
]:
    """Canary-only audit; normal WAL restart semantics remain unchanged."""

    environment, store_path, signer, trader_uid, rps, credentials = (
        _load_live_controlled_execution_writer_material_v2()
    )
    _audit_live_controlled_store_read_only_v2(
        store_path,
        environment=environment,
        trader_uid=trader_uid,
        signer_key_id=signer.key_id,
        relying_parties=rps,
        credentials=credentials,
        expected_uid=os.geteuid(),
    )
    public = base64.b64encode(
        signer.private_key.public_key().public_bytes(
            serialization.Encoding.Raw,
            serialization.PublicFormat.Raw,
        )
    ).decode("ascii")
    return environment, store_path, signer.key_id, public, trader_uid


def _load_live_controlled_execution_writer_v2(
    *,
    server_bound: bool,
    lifecycle: ControlledWriterLifecycleLeaseV2 | None = None,
) -> SQLiteControlledExecutionWriterV2:
    """Load the fixed writer only under the daemon's held lifecycle lease."""

    if server_bound is not True:
        raise ExactFourAuthorityPending(
            "live Controlled writer loading requires AuthorityServer binding"
        )
    require_held_controlled_writer_lifecycle_v2(
        lifecycle,
        expected_environment=None,
    )

    environment, store_path, signer, trader_uid, rps, credentials = (
        _load_live_controlled_execution_writer_material_v2()
    )
    require_held_controlled_writer_lifecycle_v2(
        lifecycle,
        expected_environment=environment,
        expected_store_path=store_path,
    )
    service_uid = os.geteuid()
    pinned_descriptor, identity = _open_or_provision_pinned_live_controlled_store_v2(
        store_path,
        expected_uid=service_uid,
    )
    try:
        require_held_controlled_writer_lifecycle_v2(
            lifecycle,
            expected_environment=environment,
            expected_store_path=store_path,
        )
        pinned = os.fstat(pinned_descriptor)
        if (
            (pinned.st_dev, pinned.st_ino) != identity
            or not stat.S_ISREG(pinned.st_mode)
            or pinned.st_uid != service_uid
            or stat.S_IMODE(pinned.st_mode) != 0o600
            or pinned.st_nlink != 1
        ):
            raise ExactFourAuthorityPending(
                "Controlled store changed before live writer initialization"
            )
        writer = SQLiteControlledExecutionWriterV2(
            store_path,
            environment=environment,
            signer=signer,
            clock=lambda: datetime.now(UTC),
            trader_uid=trader_uid,
            relying_parties=rps,
            credentials=credentials,
            server_bound=server_bound,
            test_mode=False,
            lifecycle=lifecycle,
            _token=_WRITER_CONSTRUCTION_TOKEN,
        )
        require_held_controlled_writer_lifecycle_v2(
            lifecycle,
            expected_environment=environment,
            expected_store_path=store_path,
        )
        initialized_identity = _require_live_controlled_store_identity_v2(
            store_path,
            expected_uid=service_uid,
            allow_missing=False,
        )
        pinned_after = os.fstat(pinned_descriptor)
        if (
            initialized_identity != identity
            or (pinned_after.st_dev, pinned_after.st_ino) != identity
            or pinned_after.st_nlink != 1
        ):
            raise ExactFourAuthorityPending(
                "Controlled store identity changed during live writer initialization"
            )
    finally:
        os.close(pinned_descriptor)
    return writer


def _load_live_controlled_execution_runtime_v2(
    *, lifecycle: ControlledWriterLifecycleLeaseV2 | None = None
) -> ControlledExecutionRuntimeV2:
    """Build the fixed provider/budget/snapshot runtime from root activation."""

    require_held_controlled_writer_lifecycle_v2(
        lifecycle,
        expected_environment=None,
    )
    document = _load_root_owned_activation()
    environment = document["environment"]
    service_uid = document["service_uid"]
    store_path = _activation_absolute_path(document, "store_path")
    provider_uid = document["provider_uid"]
    budget_id = document["budget_id"]
    budget_path = _activation_absolute_path(document, "budget_ledger_path")
    custody_manifest_path = _activation_absolute_path(
        document, "ready_custody_manifest_path"
    )
    custody_manifest_digest = document.get("ready_custody_manifest_digest")
    controlled_reader_gid = document.get("controlled_reader_gid")
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
        or type(timeout_seconds) is not int
        or not 0 < timeout_seconds <= 300
        or type(custody_manifest_digest) is not str
        or not custody_manifest_digest.startswith("sha256:")
        or len(custody_manifest_digest) != 71
        or type(controlled_reader_gid) is not int
        or controlled_reader_gid <= 0
        or document["protected_store_observed"] is not True
    ):
        raise ExactFourAuthorityPending(
            "Controlled runtime principal, budget, snapshot, or provider is absent"
        )
    require_held_controlled_writer_lifecycle_v2(
        lifecycle,
        expected_environment=environment,
        expected_store_path=store_path,
    )
    _require_controlled_reader_group_v2(
        environment=environment,
        service_uid=service_uid,
        claimed_gid=controlled_reader_gid,
    )
    try:
        require_held_controlled_writer_lifecycle_v2(
            lifecycle,
            expected_environment=environment,
            expected_store_path=store_path,
        )
        custody = load_controlled_ready_custody_v2(
            custody_manifest_path,
            expected_environment=environment,
            expected_owner_uid=0,
            expected_reader_gid=controlled_reader_gid,
        )
    except ControlledReadyCustodyV2Error as exc:
        raise ExactFourAuthorityPending(
            "Controlled READY custody transition is absent or invalid"
        ) from exc
    if custody.manifest_digest != custody_manifest_digest:
        raise ExactFourAuthorityPending(
            "Controlled READY custody manifest digest differs from activation"
        )
    require_held_controlled_writer_lifecycle_v2(
        lifecycle,
        expected_environment=environment,
        expected_store_path=store_path,
    )
    snapshot_path = custody.snapshot_path
    projection_path = custody.projection_path
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
        raise ExactFourAuthorityPending("Controlled provider socket is absent") from exc
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
    clock = lambda: datetime.now(UTC)
    require_held_controlled_writer_lifecycle_v2(
        lifecycle,
        expected_environment=environment,
        expected_store_path=store_path,
    )
    budget_ledger = ControlledPersistentBudgetLedgerV2(
        budget=budget,
        environment=environment,
        clock=clock,
    )
    require_held_controlled_writer_lifecycle_v2(
        lifecycle,
        expected_environment=environment,
        expected_store_path=store_path,
    )
    # Startup never retries work with an unknown provider outcome.
    budget_ledger.recover_unfinished()
    require_held_controlled_writer_lifecycle_v2(
        lifecycle,
        expected_environment=environment,
        expected_store_path=store_path,
    )
    snapshot = open_pinned_controlled_snapshot_v2(
        snapshot_path=str(snapshot_path),
        projection_path=str(projection_path),
        expected_uid=0,
        chain_root="/",
    )
    require_held_controlled_writer_lifecycle_v2(
        lifecycle,
        expected_environment=environment,
        expected_store_path=store_path,
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
    """Reject the legacy public opener before activation or SQLite access."""

    raise ExactFourAuthorityPending(CONTROLLED_WRITER_LIVE_STATE)


def _open_server_bound_controlled_execution_writer_v2(
    *, lifecycle: ControlledWriterLifecycleLeaseV2 | None = None
) -> (
    SQLiteControlledExecutionWriterV2
):
    """Execution adapter hook used only inside UnixAuthorityService."""

    return _load_live_controlled_execution_writer_v2(
        server_bound=True,
        lifecycle=lifecycle,
    )


def _open_server_bound_controlled_execution_runtime_v2(
    *, lifecycle: ControlledWriterLifecycleLeaseV2 | None = None
) -> (
    ControlledExecutionRuntimeV2
):
    """Provider runtime hook used only by the local AuthorityServer adapter."""

    return _load_live_controlled_execution_runtime_v2(lifecycle=lifecycle)


__all__ = [
    "CONTROLLED_EXECUTION_ACTIVATION_PATH",
    "CONTROLLED_WRITER_LIVE_STATE",
    "open_live_controlled_execution_writer_v2",
]
