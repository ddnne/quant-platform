"""Live observed-state audit and strict-gated activation evidence publication."""

from __future__ import annotations

import grp
import hashlib
import json
import pwd
import stat
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from scripts.authority_principal_manifest import PINNED_MANIFEST_DIGEST
from scripts.finding_ledger_gate import load_pinned_finding_ledger
from scripts.local_authority_activation import (
    ACTIVATION_STATE_FORMAT,
    ACTIVATION_STATE_PATH,
    ActivationStateError,
    canonical_json_bytes,
    load_activation_state,
    stat_observation,
    state_body_digest,
    validate_activation_state,
)
from scripts.local_authority_bootstrap_common import (
    _ROOT,
    _RUNNABLE_AUTHORITIES,
    SERVICE_GROUP,
    BootstrapError,
    _deployments,
    _require_positive_activation,
    _safe_file_state,
    _write_root_owned_file,
)
from scripts.local_authority_provisioning import (
    _dscl_values,
    _launchd_loaded,
    _load_public_metadata,
    _record_exists,
)
from scripts.local_authority_runtime_bundle import _load_runtime_bundle_manifest


def _require_existing_safe_user(row: dict[str, Any], *, group_id: int) -> Any:
    if not _record_exists("Users", row["service_user"]):
        raise BootstrapError(f"service user is absent: {row['service_user']}")
    try:
        entry = pwd.getpwnam(row["service_user"])
    except KeyError as exc:
        raise BootstrapError(
            f"service user is not visible: {row['service_user']}"
        ) from exc
    expected_attributes = {
        "UniqueID": (str(entry.pw_uid),),
        "PrimaryGroupID": (str(group_id),),
        "NFSHomeDirectory": ("/var/empty",),
        "UserShell": ("/usr/bin/false",),
        "IsHidden": ("1",),
        "Password": ("*",),
    }
    if (
        entry.pw_gid != group_id
        or entry.pw_dir != "/var/empty"
        or entry.pw_shell != "/usr/bin/false"
        or any(
            _dscl_values("Users", row["service_user"], attribute) != expected
            for attribute, expected in expected_attributes.items()
        )
    ):
        raise BootstrapError(f"service user is unsafe: {row['service_user']}")
    return entry


def _require_active_registry(
    row: dict[str, Any], metadata: dict[str, Any]
) -> tuple[str, bytes]:
    registry_path = _ROOT / row["registry_path"]
    try:
        raw = registry_path.read_bytes()
        document = json.loads(raw)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise BootstrapError("public registry is unavailable") from exc
    rows = document.get("keys") if type(document) is dict else None
    matches = [
        item
        for item in rows or []
        if type(item) is dict
        and item.get("key_id") == metadata["key_id"]
        and item.get("status") == "active"
        and (item.get("public_key_base64") or item.get("public_key_b64"))
        == metadata["public_key_base64"]
    ]
    if len(matches) != 1:
        raise BootstrapError(
            f"independently reviewed registry has not activated {row['authority_id']} key"
        )
    return "sha256:" + hashlib.sha256(raw).hexdigest(), raw


def _observe_active_row(row: dict[str, Any], *, group_id: int) -> dict[str, Any]:
    if row["key_backend"] != "protected_local_key":
        raise BootstrapError(
            "Trader activation requires the separate WebAuthn human-presence adapter"
        )
    entry = _require_existing_safe_user(row, group_id=group_id)
    runtime_bundle = _load_runtime_bundle_manifest()
    service_dir = Path(row["service_dir"])
    service_info = service_dir.lstat()
    if (
        not stat.S_ISDIR(service_info.st_mode)
        or service_info.st_uid != entry.pw_uid
        or service_info.st_gid != group_id
        or stat.S_IMODE(service_info.st_mode) != 0o700
    ):
        raise BootstrapError("service directory is not isolated")
    metadata = _load_public_metadata(row, expected_uid=entry.pw_uid)
    registry_digest, _ = _require_active_registry(row, metadata)
    key_path = Path(row["key_path"])
    ledger_path = Path(row["ledger_path"])
    socket_path = Path(row["socket_path"])
    config_path = Path(row["runtime_config_path"])
    if not _safe_file_state(ledger_path, uid=entry.pw_uid, modes=(0o600,)):
        raise BootstrapError("event ledger is not protected")
    try:
        import sqlite3

        with sqlite3.connect(f"file:{ledger_path}?mode=ro", uri=True) as conn:
            ledger_meta = conn.execute(
                "SELECT schema_version,authority_id,environment FROM authority_ledger_meta "
                "WHERE singleton=1"
            ).fetchall()
    except sqlite3.Error as exc:
        raise BootstrapError("event ledger identity cannot be read") from exc
    if ledger_meta != [(1, row["authority_id"], row["environment"])]:
        raise BootstrapError("event ledger identity is incorrect")
    if not _safe_file_state(config_path, uid=0, modes=(0o440, 0o444)):
        raise BootstrapError("root-owned runtime config is absent or unsafe")
    config_raw = config_path.read_bytes()
    try:
        config = json.loads(config_raw)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise BootstrapError("runtime config is not JSON") from exc
    from scripts.run_local_authority import (
        AuthorityRunnerError,
        validate_runtime_config,
    )

    try:
        config = validate_runtime_config(
            config,
            authority_id=row["authority_id"],
            environment=row["environment"],
        )
    except AuthorityRunnerError as exc:
        raise BootstrapError("runtime config identity is invalid") from exc
    peer_usernames: list[str] = []
    for peer_username in config["peer_callers"]:
        try:
            peer = pwd.getpwnam(peer_username)
        except KeyError as exc:
            raise BootstrapError(
                f"runtime peer service user is absent: {peer_username}"
            ) from exc
        if peer.pw_uid in {0, entry.pw_uid}:
            raise BootstrapError("runtime peer UID is not independently permissioned")
        peer_usernames.append(peer_username)
    try:
        caller_group = grp.getgrnam(row["caller_group"])
    except KeyError as exc:
        raise BootstrapError("dedicated socket caller group is absent") from exc
    if set(_dscl_values("Groups", row["caller_group"], "GroupMembership")) != {
        row["service_user"],
        *peer_usernames,
    }:
        raise BootstrapError("dedicated socket caller group membership drifted")
    try:
        socket_info = socket_path.lstat()
    except OSError as exc:
        raise BootstrapError("launchd socket is absent") from exc
    if (
        not stat.S_ISSOCK(socket_info.st_mode)
        or socket_info.st_uid not in {0, entry.pw_uid}
        or socket_info.st_gid != caller_group.gr_gid
        or stat.S_IMODE(socket_info.st_mode) != 0o660
    ):
        raise BootstrapError("launchd socket is unsafe")
    if not _launchd_loaded(row["launchd_label"]):
        raise BootstrapError("launchd job is not loaded")
    return {
        "authority_id": row["authority_id"],
        "environment": row["environment"],
        "state": "ACTIVE",
        "service_user": row["service_user"],
        "service_uid": entry.pw_uid,
        "service_gid": entry.pw_gid,
        "service_home": entry.pw_dir,
        "service_shell": entry.pw_shell,
        "hidden_identity": True,
        "caller_group": row["caller_group"],
        "caller_group_gid": caller_group.gr_gid,
        "key_backend": row["key_backend"],
        "key_id": metadata["key_id"],
        "public_key_base64": metadata["public_key_base64"],
        "public_key_sha256": metadata["public_key_sha256"],
        "registry_path": row["registry_path"],
        "registry_file_digest": registry_digest,
        "runtime_config_path": str(config_path),
        "runtime_config_file_digest": (
            "sha256:" + hashlib.sha256(config_raw).hexdigest()
        ),
        "runtime_config_observation": stat_observation(config_path.lstat()),
        "runtime_bundle_path": runtime_bundle["bundle_path"],
        "runtime_bundle_digest": runtime_bundle["bundle_digest"],
        "runtime_bundle_observation": stat_observation(
            Path(runtime_bundle["bundle_path"]).lstat()
        ),
        "runtime_entrypoint_path": runtime_bundle["entrypoint_path"],
        "runtime_entrypoint_digest": runtime_bundle["entrypoint_digest"],
        "runtime_entrypoint_observation": stat_observation(
            Path(runtime_bundle["entrypoint_path"]).lstat()
        ),
        "runtime_python_path": runtime_bundle["python_path"],
        "runtime_python_digest": runtime_bundle["python_digest"],
        "runtime_python_observation": stat_observation(
            Path(runtime_bundle["python_path"]).lstat()
        ),
        "key_path": str(key_path),
        "key_observation": stat_observation(key_path.lstat()),
        "ledger_path": str(ledger_path),
        "ledger_observation": stat_observation(ledger_path.lstat()),
        "socket_path": str(socket_path),
        "socket_observation": stat_observation(socket_info),
    }


def activate_state(selected: str, *, apply: bool) -> dict[str, Any]:
    selected_rows = _deployments(selected)
    if not apply:
        return {
            "format": "local-authority-activation-plan/v1",
            "mode": "DRY_RUN",
            "phase": "POSITIVE_ACTIVATION",
            "requires_human_sudo": True,
            "strict_gate_required": True,
            "activation_state_path": str(ACTIVATION_STATE_PATH),
            "manifest_digest": PINNED_MANIFEST_DIGEST,
            "live_checks": [
                "hidden service UID/home/shell/password",
                "exact protected key fingerprint and active public registry",
                "root-owned runtime config",
                "protected SQLite event ledger identity",
                "loaded launchd job and exact Unix socket inode",
            ],
            "trader": "SEPARATE_WEBAUTHN_HUMAN_PRESENCE_ACTIVATION_REQUIRED",
        }
    gate = _require_positive_activation()
    try:
        group_id = grp.getgrnam(SERVICE_GROUP).gr_gid
    except KeyError as exc:
        raise BootstrapError("service group is absent") from exc
    identities = {
        (row["authority_id"], row["environment"])
        for row in selected_rows
        if row["authority_id"] in _RUNNABLE_AUTHORITIES
    }
    if ACTIVATION_STATE_PATH.exists():
        existing = load_activation_state(ACTIVATION_STATE_PATH)
        identities.update(
            (row["authority_id"], row["environment"]) for row in existing["deployments"]
        )
    all_rows = {
        (row["authority_id"], row["environment"]): row for row in _deployments("all")
    }
    observed = [
        _observe_active_row(all_rows[identity], group_id=group_id)
        for identity in sorted(identities)
    ]
    if not observed:
        raise BootstrapError("no file-backed authority was selected for activation")
    document = {
        "format": ACTIVATION_STATE_FORMAT,
        "manifest_digest": PINNED_MANIFEST_DIGEST,
        "finding_ledger_digest": gate.digest,
        "generated_at": datetime.now(UTC).isoformat(),
        "deployments": observed,
    }
    document["state_digest"] = state_body_digest(document)
    validate_activation_state(document)
    unchanged = False
    if ACTIVATION_STATE_PATH.exists():
        existing = load_activation_state(ACTIVATION_STATE_PATH)
        unchanged = (
            existing["manifest_digest"] == document["manifest_digest"]
            and existing["finding_ledger_digest"] == document["finding_ledger_digest"]
            and existing["deployments"] == document["deployments"]
        )
    if not unchanged:
        _write_root_owned_file(
            ACTIVATION_STATE_PATH,
            canonical_json_bytes(document) + b"\n",
            mode=0o444,
            gid=group_id,
        )
    return {
        "format": "local-authority-activation-result/v1",
        "status": "ALREADY_ACTIVE" if unchanged else "ACTIVE_OBSERVED_STATE_WRITTEN",
        "activation_state_path": str(ACTIVATION_STATE_PATH),
        "manifest_digest": PINNED_MANIFEST_DIGEST,
        "finding_ledger_digest": gate.digest,
        "state_digest": (
            existing["state_digest"] if unchanged else document["state_digest"]
        ),
        "activated": [
            {
                "authority_id": row["authority_id"],
                "environment": row["environment"],
                "service_uid": row["service_uid"],
                "key_id": row["key_id"],
                "public_key_sha256": row["public_key_sha256"],
                "socket_inode": row["socket_observation"]["inode"],
            }
            for row in observed
        ],
        "trader_activated": False,
        "deferred_authorities": sorted(
            {
                row["authority_id"]
                for row in selected_rows
                if row["authority_id"] not in _RUNNABLE_AUTHORITIES
            }
        ),
    }


def _active_registry_keys(path: object) -> int:
    if type(path) is not str or not path:
        return 0
    source = Path(__file__).resolve().parents[1] / path
    try:
        document = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return 0
    rows = document.get("keys") if type(document) is dict else None
    if type(rows) is not list:
        return 0
    return sum(type(row) is dict and row.get("status") == "active" for row in rows)


def audit_state(selected: str) -> dict[str, Any]:
    rows = _deployments(selected)
    ledger = load_pinned_finding_ledger()
    activation_document: Any = None
    activation_error: str | None = None
    if ACTIVATION_STATE_PATH.exists():
        try:
            activation_document = load_activation_state(ACTIVATION_STATE_PATH)
        except ActivationStateError as exc:
            activation_error = type(exc).__name__
    active_rows = {
        (row["authority_id"], row["environment"]): row
        for row in (
            activation_document["deployments"]
            if activation_document is not None
            else []
        )
    }
    audited: list[dict[str, Any]] = []
    try:
        runtime_bundle = _load_runtime_bundle_manifest()
    except BootstrapError:
        runtime_bundle = None
    for row in rows:
        try:
            entry = pwd.getpwnam(row["service_user"])
        except KeyError:
            entry = None
        uid = None if entry is None else entry.pw_uid
        service_dir = Path(row["service_dir"])
        try:
            directory_info = service_dir.lstat()
            directory_protected = (
                uid is not None
                and stat.S_ISDIR(directory_info.st_mode)
                and directory_info.st_uid == uid
                and stat.S_IMODE(directory_info.st_mode) == 0o700
            )
        except OSError:
            directory_protected = False
        socket_path = Path(row["socket_path"])
        try:
            caller_group = grp.getgrnam(row["caller_group"])
            socket_info = socket_path.lstat()
            socket_ready = (
                uid is not None
                and stat.S_ISSOCK(socket_info.st_mode)
                and socket_info.st_uid in {0, uid}
                and socket_info.st_gid == caller_group.gr_gid
                and stat.S_IMODE(socket_info.st_mode) == 0o660
            )
        except (KeyError, OSError):
            socket_ready = False
        key_ready = (
            row["key_backend"] == "protected_local_key"
            and uid is not None
            and _safe_file_state(Path(row["key_path"]), uid=uid, modes=(0o400, 0o600))
        )
        ledger_ready = uid is not None and _safe_file_state(
            Path(row["ledger_path"]), uid=uid, modes=(0o600,)
        )
        runtime_config_ready = _safe_file_state(
            Path(row["runtime_config_path"]), uid=0, modes=(0o440, 0o444)
        )
        active_keys = _active_registry_keys(row["registry_path"])
        recorded = active_rows.get((row["authority_id"], row["environment"]))
        checks = {
            "service_user_exists": entry is not None,
            "service_directory_protected": directory_protected,
            "private_key_protected": (
                key_ready
                if row["key_backend"] == "protected_local_key"
                else "NOT_APPLICABLE_WEBAUTHN"
            ),
            "event_ledger_protected": ledger_ready,
            "runtime_config_root_owned": runtime_config_ready,
            "runtime_bundle_root_owned": runtime_bundle is not None,
            "socket_kernel_object_ready": socket_ready,
            "launchd_job_loaded": _launchd_loaded(row["launchd_label"]),
            "public_registry_active_key_count": active_keys,
            "strict_release_gate_allowed": ledger.release_allowed,
            "root_activation_row_present": recorded is not None,
        }
        activation_checks = (
            checks["service_user_exists"],
            checks["service_directory_protected"],
            checks["private_key_protected"],
            checks["event_ledger_protected"],
            checks["runtime_config_root_owned"],
            checks["runtime_bundle_root_owned"],
            checks["socket_kernel_object_ready"],
            checks["launchd_job_loaded"],
            active_keys >= 1,
            checks["strict_release_gate_allowed"],
            checks["root_activation_row_present"],
        )
        audited.append(
            {
                "authority_id": row["authority_id"],
                "environment": row["environment"],
                "declared_mode": row["declared_mode"],
                "checks": checks,
                "observed_state": (
                    "ACTIVE_LIVE_AUDITED"
                    if all(value is True for value in activation_checks)
                    else "NOT_ACTIVATED"
                ),
            }
        )
    return {
        "format": "local-authority-observed-state/v1",
        "mutation_performed": False,
        "finding_ledger_digest": ledger.digest,
        "open_p0_ids": list(ledger.open_p0_ids),
        "activation_state_path": str(ACTIVATION_STATE_PATH),
        "activation_state_digest": (
            activation_document["state_digest"]
            if activation_document is not None
            else None
        ),
        "activation_state_error": activation_error,
        "deployments": audited,
    }

