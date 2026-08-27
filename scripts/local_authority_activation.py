#!/usr/bin/env python3
"""Root-owned observed-state gate for local authority activation.

The checked-in principal manifest is a declaration and intentionally remains
``PENDING_NO_KEY``.  A daemon may become operational only when a root-owned,
read-only observed-state document binds that exact manifest to live OS users,
private-key/public-registry identity, event ledger, and launchd socket facts.
This module never creates those resources.
"""

from __future__ import annotations

import base64
import grp
import hashlib
import json
import os
import pwd
import sqlite3
import stat
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
from types import MappingProxyType
from typing import Any, NoReturn

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from scripts.authority_principal_manifest import (
    PINNED_MANIFEST_DIGEST,
    load_and_validate_manifest,
)
from scripts.finding_ledger_gate import require_pinned_finding_ledger_gate

ACTIVATION_STATE_FORMAT = "local-authority-activation-state/v2"
ACTIVATION_STATE_PATH = Path(
    "/Library/Application Support/quant-platform/authorities/activation-state.json"
)
_TOP_LEVEL_FIELDS = {
    "format",
    "manifest_digest",
    "finding_ledger_digest",
    "generated_at",
    "deployments",
    "state_digest",
}
_ROW_FIELDS = {
    "authority_id",
    "environment",
    "state",
    "service_user",
    "service_uid",
    "service_gid",
    "service_home",
    "service_shell",
    "hidden_identity",
    "caller_group",
    "caller_group_gid",
    "key_backend",
    "key_id",
    "public_key_base64",
    "public_key_sha256",
    "registry_path",
    "registry_file_digest",
    "runtime_config_path",
    "runtime_config_file_digest",
    "runtime_config_observation",
    "runtime_bundle_path",
    "runtime_bundle_digest",
    "runtime_bundle_observation",
    "runtime_entrypoint_path",
    "runtime_entrypoint_digest",
    "runtime_entrypoint_observation",
    "runtime_python_path",
    "runtime_python_digest",
    "runtime_python_observation",
    "runtime_resource_bindings",
    "key_path",
    "key_observation",
    "ledger_path",
    "ledger_observation",
    "socket_path",
    "socket_observation",
}
_OBSERVATION_FIELDS = {
    "device",
    "inode",
    "owner_uid",
    "owner_gid",
    "mode",
    "nlink",
}
_RUNTIME_RESOURCE_BINDING_FIELDS = {
    "name",
    "kind",
    "path",
    "digest",
    "observation",
}
_D1_SYNC_PINNED_RUNTIME_RESOURCES = {
    "node_executable_path": "file",
    "wrangler_cli_path": "file",
    "wrangler_cli_tree_path": "tree",
    "wrangler_config_path": "file",
    "wrangler_lock_path": "file",
}


class ActivationStateError(RuntimeError):
    """The root-owned activation evidence is absent, malformed, or stale."""


def _reject_float(value: str) -> NoReturn:
    raise ActivationStateError(f"activation state contains forbidden number {value!r}")


def _reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ActivationStateError(f"activation state duplicates key {key!r}")
        result[key] = value
    return result


def _copy_exact(value: Any, *, field: str) -> Any:
    if type(value) is dict:
        if any(type(key) is not str for key in value):
            raise ActivationStateError(f"{field} contains a non-string key")
        return {
            key: _copy_exact(item, field=f"{field}.{key}")
            for key, item in value.items()
        }
    if type(value) is list:
        return [
            _copy_exact(item, field=f"{field}[{index}]")
            for index, item in enumerate(value)
        ]
    if type(value) in {str, int, bool, type(None)}:
        return value
    raise ActivationStateError(f"{field} contains a non-JSON value")


def canonical_json_bytes(value: Mapping[str, Any]) -> bytes:
    if type(value) is not dict:
        raise ActivationStateError("activation state input must be one exact object")
    copied = _copy_exact(value, field="activation state")
    return json.dumps(
        copied,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8")


def _digest_bytes(raw: bytes) -> str:
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def state_body_digest(document: Mapping[str, Any]) -> str:
    if type(document) is not dict:
        raise ActivationStateError("activation state must be one exact object")
    return _digest_bytes(
        canonical_json_bytes(
            {key: value for key, value in document.items() if key != "state_digest"}
        )
    )


def stat_observation(info: os.stat_result) -> dict[str, int]:
    return {
        "device": int(info.st_dev),
        "inode": int(info.st_ino),
        "owner_uid": int(info.st_uid),
        "owner_gid": int(info.st_gid),
        "mode": stat.S_IMODE(info.st_mode),
        "nlink": int(info.st_nlink),
    }


def regular_file_digest(path: Path) -> str:
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(path, flags)
    except OSError as exc:
        raise ActivationStateError(f"protected file is unavailable: {path}") from exc
    digest = hashlib.sha256()
    try:
        before = os.fstat(fd)
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
            raise ActivationStateError(f"protected file metadata is unsafe: {path}")
        while True:
            chunk = os.read(fd, 1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
        after = os.fstat(fd)
        if (
            before.st_dev,
            before.st_ino,
            before.st_size,
            before.st_mtime_ns,
        ) != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns):
            raise ActivationStateError(f"protected file changed while read: {path}")
    finally:
        os.close(fd)
    return "sha256:" + digest.hexdigest()


def runtime_bundle_tree_digest(path: Path, *, expected_owner_uid: int) -> str:
    """Hash every immutable bundle path, mode, and file content without links."""

    try:
        root_info = path.lstat()
    except OSError as exc:
        raise ActivationStateError("runtime bundle is unavailable") from exc
    if (
        not stat.S_ISDIR(root_info.st_mode)
        or root_info.st_uid != expected_owner_uid
        or stat.S_IMODE(root_info.st_mode) not in {0o555, 0o755}
    ):
        raise ActivationStateError("runtime bundle root metadata is unsafe")
    inventory: list[dict[str, Any]] = []
    for current, directory_names, file_names in os.walk(path, followlinks=False):
        current_path = Path(current)
        directory_names.sort()
        file_names.sort()
        for name in [*directory_names, *file_names]:
            target = current_path / name
            info = target.lstat()
            relative = target.relative_to(path).as_posix()
            mode = stat.S_IMODE(info.st_mode)
            if info.st_uid != expected_owner_uid or (
                stat.S_ISREG(info.st_mode) and info.st_nlink != 1
            ):
                raise ActivationStateError(
                    "runtime bundle owner/link metadata is unsafe"
                )
            if stat.S_ISDIR(info.st_mode):
                if mode not in {0o555, 0o755}:
                    raise ActivationStateError("runtime bundle directory is writable")
                kind = "directory"
                digest = None
            elif stat.S_ISREG(info.st_mode):
                if mode not in {0o444, 0o555}:
                    raise ActivationStateError("runtime bundle file is writable")
                kind = "file"
                digest = regular_file_digest(target)
            else:
                raise ActivationStateError(
                    "runtime bundle contains a special file or link"
                )
            inventory.append(
                {"path": relative, "kind": kind, "mode": mode, "digest": digest}
            )
    if not inventory:
        raise ActivationStateError("runtime bundle inventory is empty")
    return _digest_bytes(canonical_json_bytes({"entries": inventory}))


def observe_runtime_resource_bindings(
    *,
    authority_id: str,
    resources: Mapping[str, Any],
    expected_owner_uid: int,
) -> list[dict[str, Any]]:
    """Capture exact executable/config/lock identities used by an authority."""

    expected = (
        _D1_SYNC_PINNED_RUNTIME_RESOURCES if authority_id == "d1_sync" else {}
    )
    if any(
        type(resources.get(name)) is not str
        or not Path(resources[name]).is_absolute()
        for name in expected
    ):
        raise ActivationStateError("runtime resource binding path is invalid")
    if authority_id == "d1_sync":
        cli = Path(resources["wrangler_cli_path"])
        tree = Path(resources["wrangler_cli_tree_path"])
        try:
            cli.relative_to(tree)
        except ValueError as exc:
            raise ActivationStateError(
                "Wrangler CLI entrypoint escapes its pinned tree"
            ) from exc

    observed: list[dict[str, Any]] = []
    for name, kind in sorted(expected.items()):
        path = Path(resources[name])
        try:
            info = path.lstat()
        except OSError as exc:
            raise ActivationStateError(
                f"runtime resource is unavailable: {name}"
            ) from exc
        mode = stat.S_IMODE(info.st_mode)
        if (
            info.st_uid != expected_owner_uid
            or mode & 0o022
            or kind == "tree"
            and not stat.S_ISDIR(info.st_mode)
            or kind == "file"
            and (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1)
        ):
            raise ActivationStateError(f"runtime resource metadata is unsafe: {name}")
        digest = (
            runtime_bundle_tree_digest(path, expected_owner_uid=expected_owner_uid)
            if kind == "tree"
            else regular_file_digest(path)
        )
        observed.append(
            {
                "name": name,
                "kind": kind,
                "path": str(path),
                "digest": digest,
                "observation": stat_observation(info),
            }
        )
    return observed


def _validate_runtime_resource_bindings(
    *, authority_id: str, value: object
) -> list[dict[str, Any]]:
    if type(value) is not list:
        raise ActivationStateError("runtime resource bindings must be a list")
    expected = (
        _D1_SYNC_PINNED_RUNTIME_RESOURCES if authority_id == "d1_sync" else {}
    )
    bindings: list[dict[str, Any]] = []
    names: set[str] = set()
    for index, row in enumerate(value):
        if type(row) is not dict or set(row) != _RUNTIME_RESOURCE_BINDING_FIELDS:
            raise ActivationStateError(
                f"runtime resource bindings[{index}] schema is not exact"
            )
        name = row["name"]
        if (
            name not in expected
            or name in names
            or row["kind"] != expected[name]
            or type(row["path"]) is not str
            or not Path(row["path"]).is_absolute()
            or type(row["digest"]) is not str
            or not row["digest"].startswith("sha256:")
        ):
            raise ActivationStateError("runtime resource binding identity is invalid")
        _validate_observation(
            row["observation"], field=f"runtime resource {name}"
        )
        names.add(name)
        bindings.append(row)
    if names != set(expected):
        raise ActivationStateError("runtime resource binding set is incomplete")
    return bindings


def public_key_fingerprint(public_key_base64: str) -> str:
    if type(public_key_base64) is not str or not public_key_base64:
        raise ActivationStateError("activation public key must be base64 text")
    try:
        raw = base64.b64decode(public_key_base64, validate=True)
    except (TypeError, ValueError) as exc:
        raise ActivationStateError("activation public key is invalid base64") from exc
    if len(raw) != 32 or base64.b64encode(raw).decode("ascii") != public_key_base64:
        raise ActivationStateError("activation public key is not canonical Ed25519")
    return _digest_bytes(raw)


def public_key_from_seed(path: Path, *, expected_uid: int) -> str:
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(path, flags)
    except OSError as exc:
        raise ActivationStateError("activation private key is unavailable") from exc
    try:
        before = os.fstat(fd)
        raw = os.read(fd, 33)
        after = os.fstat(fd)
    finally:
        os.close(fd)
    if (
        not stat.S_ISREG(before.st_mode)
        or before.st_uid != expected_uid
        or stat.S_IMODE(before.st_mode) not in {0o400, 0o600}
        or before.st_nlink != 1
        or len(raw) != 32
        or (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
        != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
    ):
        raise ActivationStateError("activation private key metadata is unsafe")
    public = (
        Ed25519PrivateKey.from_private_bytes(raw)
        .public_key()
        .public_bytes(
            serialization.Encoding.Raw,
            serialization.PublicFormat.Raw,
        )
    )
    return base64.b64encode(public).decode("ascii")


def _protected_document_bytes(path: Path, *, expected_owner_uid: int) -> bytes:
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(path, flags)
    except OSError as exc:
        raise ActivationStateError(
            "root-owned activation state is unavailable"
        ) from exc
    try:
        before = os.fstat(fd)
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_uid != expected_owner_uid
            or stat.S_IMODE(before.st_mode) not in {0o440, 0o444}
            or before.st_nlink != 1
            or before.st_size <= 0
            or before.st_size > 1024 * 1024
        ):
            raise ActivationStateError("root-owned activation state metadata is unsafe")
        raw = b""
        while len(raw) < before.st_size:
            chunk = os.read(fd, before.st_size - len(raw))
            if not chunk:
                break
            raw += chunk
        after = os.fstat(fd)
        if len(raw) != before.st_size or (
            before.st_dev,
            before.st_ino,
            before.st_size,
            before.st_mtime_ns,
        ) != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns):
            raise ActivationStateError("root-owned activation state changed while read")
        return raw
    finally:
        os.close(fd)


def _validate_observation(value: object, *, field: str) -> dict[str, int]:
    if type(value) is not dict or set(value) != _OBSERVATION_FIELDS:
        raise ActivationStateError(f"{field} observation schema is not exact")
    if any(
        type(value[name]) is not int or value[name] < 0 for name in _OBSERVATION_FIELDS
    ):
        raise ActivationStateError(f"{field} observation values are invalid")
    return dict(value)


def _validate_timestamp(value: object) -> None:
    if type(value) is not str or not value:
        raise ActivationStateError("activation generated_at is required")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ActivationStateError("activation generated_at is invalid") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ActivationStateError("activation generated_at must include a timezone")


def validate_activation_state(document: Mapping[str, Any]) -> Mapping[str, Any]:
    value = _copy_exact(document, field="activation state")
    if type(value) is not dict or set(value) != _TOP_LEVEL_FIELDS:
        raise ActivationStateError("activation state top-level schema is not exact")
    if value["format"] != ACTIVATION_STATE_FORMAT:
        raise ActivationStateError("activation state format is invalid")
    if value["manifest_digest"] != PINNED_MANIFEST_DIGEST:
        raise ActivationStateError("activation state manifest digest is not pinned")
    if type(value["finding_ledger_digest"]) is not str:
        raise ActivationStateError("activation finding-ledger digest is invalid")
    _validate_timestamp(value["generated_at"])
    if type(value["deployments"]) is not list or not value["deployments"]:
        raise ActivationStateError("activation deployments must be non-empty")
    identities: set[tuple[str, str]] = set()
    for index, row in enumerate(value["deployments"]):
        if type(row) is not dict or set(row) != _ROW_FIELDS:
            raise ActivationStateError(
                f"activation deployments[{index}] schema is not exact"
            )
        identity = (row["authority_id"], row["environment"])
        if (
            any(type(item) is not str or not item for item in identity)
            or row["environment"] not in {"staging", "production"}
            or identity in identities
            or row["state"] != "ACTIVE"
        ):
            raise ActivationStateError(
                f"activation deployments[{index}] identity is invalid"
            )
        identities.add(identity)
        for name in ("service_uid", "service_gid", "caller_group_gid"):
            if type(row[name]) is not int or row[name] < 0:
                raise ActivationStateError(
                    f"activation deployments[{index}].{name} is invalid"
                )
        for name in (
            "service_user",
            "service_home",
            "service_shell",
            "caller_group",
            "key_backend",
            "key_id",
            "public_key_base64",
            "public_key_sha256",
            "registry_path",
            "registry_file_digest",
            "runtime_config_path",
            "runtime_config_file_digest",
            "runtime_bundle_path",
            "runtime_bundle_digest",
            "runtime_entrypoint_path",
            "runtime_entrypoint_digest",
            "runtime_python_path",
            "runtime_python_digest",
            "key_path",
            "ledger_path",
            "socket_path",
        ):
            if type(row[name]) is not str or not row[name]:
                raise ActivationStateError(
                    f"activation deployments[{index}].{name} is invalid"
                )
        if row["hidden_identity"] is not True:
            raise ActivationStateError("activation service identity is not hidden")
        if row["key_backend"] != "protected_local_key":
            raise ActivationStateError(
                "file authority activation requires protected_local_key"
            )
        if public_key_fingerprint(row["public_key_base64"]) != row["public_key_sha256"]:
            raise ActivationStateError(
                "activation public-key fingerprint is inconsistent"
            )
        _validate_observation(row["key_observation"], field="key")
        _validate_observation(row["runtime_config_observation"], field="runtime config")
        _validate_observation(row["runtime_bundle_observation"], field="runtime bundle")
        _validate_observation(
            row["runtime_entrypoint_observation"], field="runtime entrypoint"
        )
        _validate_observation(row["runtime_python_observation"], field="runtime python")
        _validate_runtime_resource_bindings(
            authority_id=row["authority_id"],
            value=row["runtime_resource_bindings"],
        )
        _validate_observation(row["ledger_observation"], field="ledger")
        _validate_observation(row["socket_observation"], field="socket")
    if value["state_digest"] != state_body_digest(value):
        raise ActivationStateError("activation state body digest is invalid")
    return MappingProxyType(value)


def load_activation_state(
    path: Path = ACTIVATION_STATE_PATH, *, expected_owner_uid: int = 0
) -> Mapping[str, Any]:
    raw = _protected_document_bytes(path, expected_owner_uid=expected_owner_uid)
    try:
        document = json.loads(
            raw,
            object_pairs_hook=_reject_duplicates,
            parse_float=_reject_float,
            parse_constant=_reject_float,
        )
    except ActivationStateError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ActivationStateError("activation state is invalid JSON") from exc
    return validate_activation_state(document)


def _require_registry_key(
    *, registry_path: Path, key_id: str, public_key_base64: str, expected_digest: str
) -> None:
    try:
        raw = registry_path.read_bytes()
        document = json.loads(raw)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ActivationStateError("activation public registry is unavailable") from exc
    if _digest_bytes(raw) != expected_digest:
        raise ActivationStateError("activation public registry changed after audit")
    rows = document.get("keys") if type(document) is dict else None
    if type(rows) is not list:
        raise ActivationStateError("activation public registry has no key list")
    matches = [
        row
        for row in rows
        if type(row) is dict
        and row.get("key_id") == key_id
        and row.get("status") == "active"
        and (row.get("public_key_base64") or row.get("public_key_b64"))
        == public_key_base64
    ]
    if len(matches) != 1:
        raise ActivationStateError("activation public registry has no exact active key")


def _require_live_observation(
    path: Path, recorded: Mapping[str, int], *, kind: str, owner_uids: set[int]
) -> None:
    try:
        info = path.lstat()
    except OSError as exc:
        raise ActivationStateError(f"activation {kind} is unavailable") from exc
    expected_kind = (
        stat.S_ISSOCK
        if kind == "socket"
        else stat.S_ISDIR
        if kind == "runtime bundle"
        else stat.S_ISREG
    )
    if not expected_kind(info.st_mode) or info.st_uid not in owner_uids:
        raise ActivationStateError(f"activation {kind} type or owner is invalid")
    if stat_observation(info) != dict(recorded):
        raise ActivationStateError(f"activation {kind} observation is stale")
    mode = stat.S_IMODE(info.st_mode)
    if (
        kind == "key"
        and mode not in {0o400, 0o600}
        or kind == "ledger"
        and mode != 0o600
        or kind == "runtime config"
        and mode not in {0o440, 0o444}
        or kind == "runtime bundle"
        and mode not in {0o555, 0o755}
        or kind == "runtime entrypoint"
        and mode not in {0o444, 0o555}
        or kind == "runtime python"
        and (mode & 0o022 or not mode & 0o111)
        or kind == "socket"
        and mode != 0o660
    ):
        raise ActivationStateError(f"activation {kind} permissions are unsafe")


def _require_live_runtime_resource_bindings(
    *,
    authority_id: str,
    resources: Mapping[str, Any],
    recorded: object,
    expected_owner_uid: int,
) -> None:
    live = observe_runtime_resource_bindings(
        authority_id=authority_id,
        resources=resources,
        expected_owner_uid=expected_owner_uid,
    )
    if live != recorded:
        raise ActivationStateError(
            "activation runtime executable/config/lock observation is stale"
        )


def require_active_service_identity(
    *,
    authority_id: str,
    environment: str,
    path: Path = ACTIVATION_STATE_PATH,
    expected_root_uid: int = 0,
    current_euid: int | None = None,
    current_egid: int | None = None,
    _protected_root: Path = Path(
        "/Library/Application Support/quant-platform/authorities"
    ),
    _repository_root: Path | None = None,
) -> tuple[int, Mapping[str, Any]]:
    """Return a live-audited deployment only after the strict release gate."""

    manifest = load_and_validate_manifest()
    gate = require_pinned_finding_ledger_gate()
    state = load_activation_state(path, expected_owner_uid=expected_root_uid)
    if state["finding_ledger_digest"] != gate.digest:
        raise ActivationStateError("activation state finding-ledger digest is stale")
    rows = [
        row
        for row in state["deployments"]
        if row["authority_id"] == authority_id and row["environment"] == environment
    ]
    if len(rows) != 1:
        raise ActivationStateError("authority has no exact ACTIVE observation")
    row = rows[0]
    try:
        principal = manifest["principals"][authority_id]
        declared = principal["deployments"][environment]
    except (KeyError, TypeError) as exc:
        raise ActivationStateError("activated authority is not declared") from exc
    repository_root = (
        Path(__file__).resolve().parents[1]
        if _repository_root is None
        else _repository_root
    )
    declared_ledger = (
        _protected_root / environment / authority_id / "authority-events.sqlite3"
    )
    declared_key = declared_ledger.with_name("ed25519-private-key")
    declared_runtime_config = (
        _protected_root / "runtime-config" / environment / f"{authority_id}.json"
    )
    expected = {
        "service_user": declared["service_user"],
        "key_backend": declared["key_backend"],
        "registry_path": principal["registry_path"],
        "runtime_config_path": str(declared_runtime_config),
        "key_path": str(declared_key),
        "ledger_path": str(declared_ledger),
        "socket_path": declared["socket_path"],
        "caller_group": f"qp_{environment}_{authority_id}_callers",
    }
    if any(row[name] != value for name, value in expected.items()):
        raise ActivationStateError("activation state drifts from declared deployment")
    try:
        account = pwd.getpwnam(row["service_user"])
    except KeyError as exc:
        raise ActivationStateError("activated service user is absent") from exc
    if (
        account.pw_uid != row["service_uid"]
        or account.pw_gid != row["service_gid"]
        or account.pw_dir != row["service_home"]
        or account.pw_shell != row["service_shell"]
        or row["service_home"] != "/var/empty"
        or row["service_shell"] != "/usr/bin/false"
        or (os.geteuid() if current_euid is None else current_euid) != account.pw_uid
    ):
        raise ActivationStateError("activated service identity no longer matches")
    try:
        caller_group = grp.getgrnam(row["caller_group"])
    except KeyError as exc:
        raise ActivationStateError("activated caller group is absent") from exc
    if (
        caller_group.gr_gid != row["caller_group_gid"]
        or (os.getegid() if current_egid is None else current_egid)
        != caller_group.gr_gid
        or row["socket_observation"]["owner_gid"] != caller_group.gr_gid
    ):
        raise ActivationStateError("activated caller group identity no longer matches")
    _require_live_observation(
        Path(row["key_path"]),
        row["key_observation"],
        kind="key",
        owner_uids={account.pw_uid},
    )
    public_key = public_key_from_seed(
        Path(row["key_path"]), expected_uid=account.pw_uid
    )
    if public_key != row["public_key_base64"]:
        raise ActivationStateError("activation private/public key identity changed")
    _require_live_observation(
        Path(row["runtime_config_path"]),
        row["runtime_config_observation"],
        kind="runtime config",
        owner_uids={expected_root_uid},
    )
    runtime_config_raw = Path(row["runtime_config_path"]).read_bytes()
    if _digest_bytes(runtime_config_raw) != row["runtime_config_file_digest"]:
        raise ActivationStateError("activation runtime config changed after audit")
    try:
        runtime_config = json.loads(
            runtime_config_raw,
            object_pairs_hook=_reject_duplicates,
            parse_float=_reject_float,
            parse_constant=_reject_float,
        )
        runtime_resources = runtime_config["resources"]
    except (
        ActivationStateError,
        KeyError,
        TypeError,
        UnicodeError,
        json.JSONDecodeError,
    ) as exc:
        raise ActivationStateError(
            "activation runtime config resource binding is invalid"
        ) from exc
    if type(runtime_resources) is not dict:
        raise ActivationStateError("activation runtime resources are invalid")
    _require_live_runtime_resource_bindings(
        authority_id=authority_id,
        resources=runtime_resources,
        recorded=row["runtime_resource_bindings"],
        expected_owner_uid=expected_root_uid,
    )
    _require_live_observation(
        Path(row["runtime_bundle_path"]),
        row["runtime_bundle_observation"],
        kind="runtime bundle",
        owner_uids={expected_root_uid},
    )
    if (
        runtime_bundle_tree_digest(
            Path(row["runtime_bundle_path"]),
            expected_owner_uid=expected_root_uid,
        )
        != row["runtime_bundle_digest"]
    ):
        raise ActivationStateError("activation runtime bundle changed after audit")
    entrypoint = Path(row["runtime_entrypoint_path"])
    try:
        entrypoint.relative_to(Path(row["runtime_bundle_path"]))
    except ValueError as exc:
        raise ActivationStateError("runtime entrypoint escapes its bundle") from exc
    _require_live_observation(
        entrypoint,
        row["runtime_entrypoint_observation"],
        kind="runtime entrypoint",
        owner_uids={expected_root_uid},
    )
    if regular_file_digest(entrypoint) != row["runtime_entrypoint_digest"]:
        raise ActivationStateError("activation runtime entrypoint changed after audit")
    runtime_python = Path(row["runtime_python_path"])
    _require_live_observation(
        runtime_python,
        row["runtime_python_observation"],
        kind="runtime python",
        owner_uids={expected_root_uid},
    )
    if regular_file_digest(runtime_python) != row["runtime_python_digest"]:
        raise ActivationStateError("activation runtime Python changed after audit")
    _require_live_observation(
        Path(row["ledger_path"]),
        row["ledger_observation"],
        kind="ledger",
        owner_uids={account.pw_uid},
    )
    try:
        with sqlite3.connect(f"file:{row['ledger_path']}?mode=ro", uri=True) as conn:
            ledger_meta = conn.execute(
                "SELECT schema_version,authority_id,environment FROM authority_ledger_meta "
                "WHERE singleton=1"
            ).fetchall()
    except sqlite3.Error as exc:
        raise ActivationStateError(
            "activation event ledger cannot be validated"
        ) from exc
    if ledger_meta != [(1, authority_id, environment)]:
        raise ActivationStateError("activation event ledger identity is invalid")
    _require_live_observation(
        Path(row["socket_path"]),
        row["socket_observation"],
        kind="socket",
        owner_uids={0, account.pw_uid},
    )
    _require_registry_key(
        registry_path=repository_root / row["registry_path"],
        key_id=row["key_id"],
        public_key_base64=row["public_key_base64"],
        expected_digest=row["registry_file_digest"],
    )
    return account.pw_uid, MappingProxyType(dict(row))


__all__ = [
    "ACTIVATION_STATE_FORMAT",
    "ACTIVATION_STATE_PATH",
    "ActivationStateError",
    "canonical_json_bytes",
    "load_activation_state",
    "observe_runtime_resource_bindings",
    "public_key_fingerprint",
    "public_key_from_seed",
    "regular_file_digest",
    "require_active_service_identity",
    "runtime_bundle_tree_digest",
    "stat_observation",
    "state_body_digest",
    "validate_activation_state",
]
