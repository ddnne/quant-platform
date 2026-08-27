"""macOS accounts, keys, runtime config, socket groups, plists and proposals."""

from __future__ import annotations

import grp
import hashlib
import json
import os
import platform
import plistlib
import pwd
import stat
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from scripts.authority_principal_manifest import (
    PINNED_MANIFEST_DIGEST,
    load_and_validate_manifest,
)
from scripts.local_authority_activation import (
    canonical_json_bytes,
    public_key_fingerprint,
    public_key_from_seed,
)
from scripts.local_authority_bootstrap_common import (
    _ROOT,
    _RUNNABLE_AUTHORITIES,
    LAUNCHD_RENDER_ROOT,
    LAUNCHD_TEMPLATE,
    PROTECTED_ROOT,
    REGISTRY_PROPOSAL_PATH,
    RUN_ROOT,
    SERVICE_GROUP,
    BootstrapError,
    _caller_service_user,
    _deployments,
    _ensure_directory,
    _local_peer_rows,
    _require_human_root,
    _require_positive_activation,
    _run,
    _safe_file_state,
    _write_exclusive,
    _write_root_owned_file,
)
from scripts.local_authority_runtime_bundle import _load_runtime_bundle_manifest
from scripts.local_authority_service import SQLiteAuthorityEventLedger


def _record_exists(kind: str, name: str) -> bool:
    result = _run(["/usr/bin/dscl", ".", "-read", f"/{kind}/{name}"])
    return result.returncode == 0


def _used_ids(kind: str, attribute: str) -> set[int]:
    result = _run(["/usr/bin/dscl", ".", "-list", f"/{kind}", attribute])
    if result.returncode != 0:
        raise BootstrapError(f"cannot enumerate macOS {kind} ids")
    used: set[int] = set()
    for line in result.stdout.splitlines():
        fields = line.rsplit(None, 1)
        if len(fields) == 2 and fields[1].isdigit():
            used.add(int(fields[1]))
    return used


def _next_id(used: set[int]) -> int:
    candidate = max(600, max(used, default=599) + 1)
    while candidate in used:
        candidate += 1
    used.add(candidate)
    return candidate


def _dscl_create(path: str, attribute: str, value: str) -> None:
    result = _run(["/usr/bin/dscl", ".", "-create", path, attribute, value])
    if result.returncode != 0:
        raise BootstrapError(f"dscl failed while setting {path} {attribute}")


def _dscl_values(kind: str, name: str, attribute: str) -> tuple[str, ...]:
    result = _run(["/usr/bin/dscl", ".", "-read", f"/{kind}/{name}", attribute])
    if result.returncode != 0:
        raise BootstrapError(f"cannot read macOS identity {kind}/{name} {attribute}")
    prefix = f"{attribute}:"
    line = next(
        (item for item in result.stdout.splitlines() if item.startswith(prefix)),
        None,
    )
    if line is None:
        raise BootstrapError(
            f"macOS identity {kind}/{name} has no {attribute} attribute"
        )
    return tuple(line.removeprefix(prefix).strip().split())


def _ensure_group() -> int:
    if not _record_exists("Groups", SERVICE_GROUP):
        group_id = _next_id(_used_ids("Groups", "PrimaryGroupID"))
        path = f"/Groups/{SERVICE_GROUP}"
        _dscl_create(path, "PrimaryGroupID", str(group_id))
        _dscl_create(path, "RealName", "quant-platform signing authorities")
        _dscl_create(path, "Password", "*")
    try:
        entry = grp.getgrnam(SERVICE_GROUP)
    except KeyError as exc:
        raise BootstrapError("service group was not visible after creation") from exc
    if _dscl_values("Groups", SERVICE_GROUP, "PrimaryGroupID") != (
        str(entry.gr_gid),
    ) or _dscl_values("Groups", SERVICE_GROUP, "Password") != ("*",):
        raise BootstrapError("existing service group has unsafe identity")
    return entry.gr_gid


def _ensure_caller_group(name: str, *, used_ids: set[int]) -> int:
    if not _record_exists("Groups", name):
        group_id = _next_id(used_ids)
        path = f"/Groups/{name}"
        _dscl_create(path, "PrimaryGroupID", str(group_id))
        _dscl_create(path, "RealName", f"quant-platform socket callers {name}")
        _dscl_create(path, "Password", "*")
    try:
        entry = grp.getgrnam(name)
    except KeyError as exc:
        raise BootstrapError(f"caller group was not visible: {name}") from exc
    if _dscl_values("Groups", name, "PrimaryGroupID") != (
        str(entry.gr_gid),
    ) or _dscl_values("Groups", name, "Password") != ("*",):
        raise BootstrapError(f"existing caller group is unsafe: {name}")
    return entry.gr_gid


def _set_exact_caller_group_members(
    group_name: str, *, usernames: tuple[str, ...]
) -> None:
    if not usernames or len(set(usernames)) != len(usernames):
        raise BootstrapError("caller group membership is invalid")
    result = _run(
        [
            "/usr/bin/dscl",
            ".",
            "-create",
            f"/Groups/{group_name}",
            "GroupMembership",
            *usernames,
        ]
    )
    if result.returncode != 0:
        raise BootstrapError(f"cannot set exact caller group membership: {group_name}")
    if set(_dscl_values("Groups", group_name, "GroupMembership")) != set(usernames):
        raise BootstrapError(f"caller group membership did not converge: {group_name}")


def _ensure_user(username: str, *, group_id: int, used_ids: set[int]) -> int:
    if not _record_exists("Users", username):
        uid = _next_id(used_ids)
        path = f"/Users/{username}"
        _dscl_create(path, "UniqueID", str(uid))
        _dscl_create(path, "PrimaryGroupID", str(group_id))
        _dscl_create(path, "RealName", f"quant-platform authority {username}")
        _dscl_create(path, "NFSHomeDirectory", "/var/empty")
        _dscl_create(path, "UserShell", "/usr/bin/false")
        _dscl_create(path, "Password", "*")
        _dscl_create(path, "IsHidden", "1")
    try:
        entry = pwd.getpwnam(username)
    except KeyError as exc:
        raise BootstrapError(f"service user was not visible: {username}") from exc
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
            _dscl_values("Users", username, attribute) != expected
            for attribute, expected in expected_attributes.items()
        )
    ):
        raise BootstrapError(f"existing service user has unsafe identity: {username}")
    return entry.pw_uid


def apply_plan(selected: str) -> dict[str, Any]:
    _require_human_root()
    rows = _deployments(selected)
    group_id = _ensure_group()
    used_ids = _used_ids("Users", "UniqueID")
    used_group_ids = _used_ids("Groups", "PrimaryGroupID")
    _ensure_directory(PROTECTED_ROOT, uid=0, gid=group_id, mode=0o711)
    _ensure_directory(RUN_ROOT, uid=0, gid=group_id, mode=0o711)
    applied: list[dict[str, Any]] = []
    peer_identities: list[dict[str, Any]] = []
    for peer in _local_peer_rows(selected):
        uid = _ensure_user(peer["service_user"], group_id=group_id, used_ids=used_ids)
        peer_identities.append({**peer, "uid": uid, "signing_capability": False})
    for row in rows:
        uid = _ensure_user(row["service_user"], group_id=group_id, used_ids=used_ids)
        caller_group_id = _ensure_caller_group(
            row["caller_group"], used_ids=used_group_ids
        )
        _ensure_directory(
            PROTECTED_ROOT / row["environment"],
            uid=0,
            gid=group_id,
            mode=0o711,
        )
        _ensure_directory(Path(row["service_dir"]), uid=uid, gid=group_id, mode=0o700)
        # launchd owns socket creation; service users do not receive write
        # access to a shared directory containing other authorities' sockets.
        _ensure_directory(
            RUN_ROOT / row["environment"], uid=0, gid=group_id, mode=0o711
        )
        applied.append(
            {
                "authority_id": row["authority_id"],
                "environment": row["environment"],
                "service_user": row["service_user"],
                "uid": uid,
                "caller_group": row["caller_group"],
                "caller_group_gid": caller_group_id,
                "service_directory_prepared": True,
                "key_created": False,
                "launchd_loaded": False,
                "declared_mode": row["declared_mode"],
            }
        )
    return {
        "format": "local-authority-bootstrap-apply/v1",
        "phase": "BOOTSTRAP_INACTIVE",
        "status": "PREPARED_NOT_ACTIVATED",
        "positive_activation_performed": False,
        "local_peer_identities": peer_identities,
        "deployments": applied,
    }


def _key_id(row: dict[str, Any]) -> str:
    return f"{row['authority_id'].replace('_', '-')}-{row['environment']}-local-v1"


def _public_metadata_document(
    row: dict[str, Any], *, public_key_base64: str
) -> dict[str, Any]:
    return {
        "format": "local-authority-public-key/v1",
        "manifest_digest": PINNED_MANIFEST_DIGEST,
        "authority_id": row["authority_id"],
        "environment": row["environment"],
        "key_id": _key_id(row),
        "algorithm": "Ed25519",
        "public_key_base64": public_key_base64,
        "public_key_sha256": public_key_fingerprint(public_key_base64),
    }


def _load_public_metadata(row: dict[str, Any], *, expected_uid: int) -> dict[str, Any]:
    metadata_path = Path(row["public_metadata_path"])
    if not _safe_file_state(
        metadata_path, uid=expected_uid, modes=(0o400, 0o440, 0o444)
    ):
        raise BootstrapError(
            f"public key metadata is missing or unsafe: {row['authority_id']}"
        )
    try:
        document = json.loads(metadata_path.read_bytes())
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise BootstrapError("public key metadata is invalid JSON") from exc
    expected = _public_metadata_document(
        row,
        public_key_base64=public_key_from_seed(
            Path(row["key_path"]), expected_uid=expected_uid
        ),
    )
    if type(document) is not dict or document != expected:
        raise BootstrapError("public key metadata does not match protected key")
    return document


def _generate_or_validate_key_material(
    row: dict[str, Any], *, expected_uid: int
) -> dict[str, Any]:
    """Run as the service UID; never return or print the private seed."""

    if row["key_backend"] != "protected_local_key" or row["key_path"] is None:
        raise BootstrapError("file key generation is forbidden for this authority")
    if os.geteuid() != expected_uid:
        raise BootstrapError("private key generation did not enter the service UID")
    service_dir = Path(row["service_dir"])
    try:
        service_info = service_dir.lstat()
    except OSError as exc:
        raise BootstrapError("protected service directory is unavailable") from exc
    if (
        not stat.S_ISDIR(service_info.st_mode)
        or service_info.st_uid != expected_uid
        or stat.S_IMODE(service_info.st_mode) != 0o700
    ):
        raise BootstrapError("protected service directory ownership is unsafe")
    key_path = Path(row["key_path"])
    created = False
    if not key_path.exists():
        private = Ed25519PrivateKey.generate()
        seed = private.private_bytes(
            serialization.Encoding.Raw,
            serialization.PrivateFormat.Raw,
            serialization.NoEncryption(),
        )
        try:
            _write_exclusive(key_path, seed, mode=0o400)
        finally:
            # Drop the only explicit immutable copy promptly.  Python cannot
            # guarantee zeroization, so the seed is never rendered or returned.
            seed = b""
        created = True
    public_key_base64 = public_key_from_seed(key_path, expected_uid=expected_uid)
    expected_metadata = _public_metadata_document(
        row, public_key_base64=public_key_base64
    )
    metadata_path = Path(row["public_metadata_path"])
    if not metadata_path.exists():
        _write_exclusive(
            metadata_path,
            canonical_json_bytes(expected_metadata) + b"\n",
            mode=0o400,
        )
    metadata = _load_public_metadata(row, expected_uid=expected_uid)
    ledger = SQLiteAuthorityEventLedger(
        row["ledger_path"],
        authority_id=row["authority_id"],
        environment=row["environment"],
        expected_uid=expected_uid,
    )
    ledger.initialize()
    return {
        "authority_id": row["authority_id"],
        "environment": row["environment"],
        "status": "CREATED" if created else "ALREADY_PRESENT_VERIFIED",
        "key_id": metadata["key_id"],
        "public_key_sha256": metadata["public_key_sha256"],
        "private_key_exposed": False,
        "event_ledger_initialized": True,
    }


def _run_key_generation_as_service_user(
    row: dict[str, Any], *, uid: int, gid: int
) -> dict[str, Any]:
    if os.geteuid() == uid:
        return _generate_or_validate_key_material(row, expected_uid=uid)
    if os.geteuid() != 0:
        raise BootstrapError("service UID transition requires root")
    read_fd, write_fd = os.pipe()
    child = os.fork()
    if child == 0:  # pragma: no cover - exercised only by root macOS activation
        os.close(read_fd)
        try:
            os.setgroups([gid])
            os.setgid(gid)
            os.setuid(uid)
            result = _generate_or_validate_key_material(row, expected_uid=uid)
            payload = {"ok": True, "result": result}
        except Exception as exc:  # noqa: BLE001 - child reports only the error class
            payload = {"ok": False, "error": type(exc).__name__}
        try:
            os.write(write_fd, canonical_json_bytes(payload))
        finally:
            os.close(write_fd)
        os._exit(0 if payload["ok"] else 1)
    os.close(write_fd)
    raw = b""
    while True:
        chunk = os.read(read_fd, 65536)
        if not chunk:
            break
        raw += chunk
    os.close(read_fd)
    _, status = os.waitpid(child, 0)
    try:
        payload = json.loads(raw)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise BootstrapError(
            "service UID key generator returned invalid evidence"
        ) from exc
    if status != 0 or type(payload) is not dict or payload.get("ok") is not True:
        error = payload.get("error") if type(payload) is dict else "unknown"
        raise BootstrapError(f"service UID key generation failed: {error}")
    return payload["result"]


def generate_keys(selected: str, *, apply: bool) -> dict[str, Any]:
    rows = _deployments(selected)
    if not apply:
        return {
            "format": "local-authority-key-generation-plan/v1",
            "mode": "DRY_RUN",
            "phase": "BOOTSTRAP_INACTIVE",
            "requires_human_sudo": True,
            "strict_gate_required": False,
            "positive_activation_forbidden": True,
            "deployments": [
                {
                    "authority_id": row["authority_id"],
                    "environment": row["environment"],
                    "action": (
                        "GENERATE_PROTECTED_ED25519_AS_SERVICE_UID"
                        if row["key_backend"] == "protected_local_key"
                        else "SKIP_WEBAUTHN_HUMAN_PRESENCE_REQUIRED"
                    ),
                }
                for row in rows
            ],
        }
    _require_human_root()
    try:
        group_id = grp.getgrnam(SERVICE_GROUP).gr_gid
    except KeyError as exc:
        raise BootstrapError("prepare-users must run before generate-keys") from exc
    results: list[dict[str, Any]] = []
    used_ids: set[int] = set()
    for row in rows:
        if row["key_backend"] != "protected_local_key":
            results.append(
                {
                    "authority_id": row["authority_id"],
                    "environment": row["environment"],
                    "status": "SKIPPED_WEBAUTHN_HUMAN_PRESENCE_REQUIRED",
                    "private_key_created": False,
                }
            )
            continue
        uid = _ensure_user(row["service_user"], group_id=group_id, used_ids=used_ids)
        results.append(_run_key_generation_as_service_user(row, uid=uid, gid=group_id))
    return {
        "format": "local-authority-key-generation-result/v1",
        "phase": "BOOTSTRAP_INACTIVE",
        "status": "KEYS_PREPARED_NOT_ACTIVATED",
        "positive_activation_performed": False,
        "private_keys_exposed": False,
        "deployments": results,
    }


def _runtime_config_template(row: dict[str, Any]) -> dict[str, Any]:
    manifest = load_and_validate_manifest()
    callers = {
        _caller_service_user(
            environment=row["environment"], caller=grant["authenticated_caller"]
        ): grant["authenticated_caller"]
        for grant in manifest["principals"][row["authority_id"]]["method_acl"]
    }
    resource_names = {
        "d1_sync": (
            "governed_db_path",
            "cloudflare_token_path",
            "node_executable_path",
            "wrangler_cli_path",
            "wrangler_config_path",
        ),
        "ops_projection": ("artifact_store",),
        "coverage_transition": (),
        "ready": ("snapshot_root",),
    }[row["authority_id"]]
    return {
        "format": "local-authority-runtime-config/v1",
        "authority_id": row["authority_id"],
        "environment": row["environment"],
        "peer_callers": callers,
        "resources": {
            resource_name: f"/REPLACE/WITH/{resource_name.upper()}"
            for resource_name in resource_names
        },
    }


def install_runtime_configs(
    selected: str, *, apply: bool, source_root: Path | None
) -> dict[str, Any]:
    declared_rows = _deployments(selected)
    rows = [
        row for row in declared_rows if row["authority_id"] in _RUNNABLE_AUTHORITIES
    ]
    result = {
        "format": "local-authority-runtime-config-install/v1",
        "mode": "DRY_RUN" if not apply else "APPLY",
        "phase": "BOOTSTRAP_INACTIVE",
        "requires_human_sudo": True,
        "strict_gate_required": False,
        "positive_activation_forbidden": True,
        "templates": [
            {
                "destination": row["runtime_config_path"],
                "reviewed_source_relative": (
                    f"{row['environment']}/{row['authority_id']}.json"
                ),
                "template": _runtime_config_template(row),
            }
            for row in rows
        ],
        "deferred_authorities": sorted(
            {
                row["authority_id"]
                for row in declared_rows
                if row["authority_id"] not in _RUNNABLE_AUTHORITIES
            }
        ),
    }
    if not apply:
        return result
    _require_human_root()
    if source_root is None:
        raise BootstrapError(
            "install-runtime-configs --apply requires --config-source-root"
        )
    source_root = source_root.resolve(strict=True)
    from scripts.run_local_authority import (
        AuthorityRunnerError,
        decode_runtime_config,
    )

    try:
        group_id = grp.getgrnam(SERVICE_GROUP).gr_gid
    except KeyError as exc:
        raise BootstrapError("service group is absent") from exc
    _ensure_directory(
        PROTECTED_ROOT / "runtime-config", uid=0, gid=group_id, mode=0o755
    )
    written: list[dict[str, Any]] = []
    for row in rows:
        _ensure_directory(
            PROTECTED_ROOT / "runtime-config" / row["environment"],
            uid=0,
            gid=group_id,
            mode=0o755,
        )
        relative = Path(row["environment"]) / f"{row['authority_id']}.json"
        source = source_root / relative
        try:
            raw = source.read_bytes()
            config = decode_runtime_config(
                raw,
                authority_id=row["authority_id"],
                environment=row["environment"],
            )
        except (OSError, AuthorityRunnerError) as exc:
            raise BootstrapError(
                f"reviewed runtime config is invalid: {relative}"
            ) from exc
        if config["peer_callers"] != _runtime_config_template(row)["peer_callers"]:
            raise BootstrapError(
                f"runtime config peer identities differ from pinned manifest: {relative}"
            )
        if any(
            "REPLACE" in value
            for value in (
                *config["peer_callers"].keys(),
                *config["resources"].values(),
            )
        ):
            raise BootstrapError(f"runtime config retains a placeholder: {relative}")
        authority_entry = pwd.getpwnam(row["service_user"])
        peer_usernames: list[str] = []
        for peer_username in config["peer_callers"]:
            try:
                peer_entry = pwd.getpwnam(peer_username)
            except KeyError as exc:
                raise BootstrapError(
                    f"runtime peer service user is absent: {peer_username}"
                ) from exc
            if peer_entry.pw_uid in {0, authority_entry.pw_uid}:
                raise BootstrapError("runtime peer is not an isolated non-root UID")
            peer_usernames.append(peer_username)
        for resource_path in config["resources"].values():
            try:
                Path(resource_path).resolve(strict=True)
            except OSError as exc:
                raise BootstrapError(
                    f"runtime governed resource is absent: {resource_path}"
                ) from exc
        _ensure_caller_group(
            row["caller_group"], used_ids=_used_ids("Groups", "PrimaryGroupID")
        )
        _set_exact_caller_group_members(
            row["caller_group"],
            usernames=tuple(sorted({row["service_user"], *peer_usernames})),
        )
        content = canonical_json_bytes(config) + b"\n"
        changed = _write_root_owned_file(
            Path(row["runtime_config_path"]),
            content,
            mode=0o444,
            gid=group_id,
        )
        written.append(
            {
                "authority_id": row["authority_id"],
                "environment": row["environment"],
                "path": row["runtime_config_path"],
                "digest": "sha256:" + hashlib.sha256(content).hexdigest(),
                "changed": changed,
            }
        )
    result["status"] = "INSTALLED_NOT_ACTIVATED"
    result["installed"] = written
    return result


def _render_plist(row: dict[str, Any], bundle: dict[str, Any]) -> bytes:
    replacements = {
        b"__ENVIRONMENT__": row["environment"].encode(),
        b"__AUTHORITY__": row["authority_id"].encode(),
        b"__SERVICE_USER__": row["service_user"].encode(),
        b"__CALLER_GROUP__": row["caller_group"].encode(),
        b"__PYTHON_PATH__": bundle["python_path"].encode(),
        b"__BUNDLE_ENTRYPOINT__": bundle["entrypoint_path"].encode(),
        b"__BUNDLE_ROOT__": bundle["bundle_path"].encode(),
        b"__SOCKET_PATH__": row["socket_path"].encode(),
    }
    raw = LAUNCHD_TEMPLATE.read_bytes()
    for marker, value in replacements.items():
        raw = raw.replace(marker, value)
    if b"__" in raw:
        raise BootstrapError("launchd template still contains an unresolved marker")
    try:
        document = plistlib.loads(raw)
    except plistlib.InvalidFileException as exc:
        raise BootstrapError("rendered launchd plist is invalid") from exc
    if (
        document.get("Label") != row["launchd_label"]
        or document.get("UserName") != row["service_user"]
        or document.get("GroupName") != row["caller_group"]
        or document.get("Sockets", {}).get("Listener", {}).get("SockPathName")
        != row["socket_path"]
        or document.get("Sockets", {}).get("Listener", {}).get("SockPathMode") != 0o660
        or document.get("ProgramArguments", [])[:3]
        != [bundle["python_path"], "-I", bundle["entrypoint_path"]]
        or document.get("WorkingDirectory") != bundle["bundle_path"]
        or str(_ROOT) in raw.decode("utf-8")
        or "uv" in document.get("ProgramArguments", [])
        or "EnvironmentVariables" in document
    ):
        raise BootstrapError("rendered launchd plist does not preserve isolation")
    return raw


def render_plists(selected: str, *, apply: bool) -> dict[str, Any]:
    declared_rows = _deployments(selected)
    rows = [
        row for row in declared_rows if row["authority_id"] in _RUNNABLE_AUTHORITIES
    ]
    try:
        bundle = _load_runtime_bundle_manifest()
    except BootstrapError:
        bundle = None
    rendered = []
    for row in rows:
        content = None if bundle is None else _render_plist(row, bundle)
        rendered.append(
            {
                "authority_id": row["authority_id"],
                "environment": row["environment"],
                "path": row["rendered_plist_path"],
                "sha256": (
                    None
                    if content is None
                    else "sha256:" + hashlib.sha256(content).hexdigest()
                ),
                "prerequisite": (
                    "install-runtime-bundle"
                    if bundle is None
                    else "SATISFIED_ROOT_OWNED_BUNDLE"
                ),
            }
        )
    if not apply:
        return {
            "format": "local-authority-launchd-render-plan/v1",
            "mode": "DRY_RUN",
            "phase": "BOOTSTRAP_INACTIVE",
            "requires_human_sudo": True,
            "strict_gate_required": False,
            "positive_activation_forbidden": True,
            "plists": rendered,
            "deferred_authorities": sorted(
                {
                    row["authority_id"]
                    for row in declared_rows
                    if row["authority_id"] not in _RUNNABLE_AUTHORITIES
                }
            ),
        }
    _require_human_root()
    bundle = _load_runtime_bundle_manifest()
    group_id = grp.getgrnam(SERVICE_GROUP).gr_gid
    _ensure_directory(LAUNCHD_RENDER_ROOT, uid=0, gid=group_id, mode=0o755)
    for row, result in zip(rows, rendered, strict=True):
        result["changed"] = _write_root_owned_file(
            Path(row["rendered_plist_path"]),
            _render_plist(row, bundle),
            mode=0o444,
            gid=group_id,
        )
    return {
        "format": "local-authority-launchd-render-result/v1",
        "phase": "BOOTSTRAP_INACTIVE",
        "status": "RENDERED_NOT_INSTALLED",
        "positive_activation_performed": False,
        "plists": rendered,
        "deferred_authorities": sorted(
            {
                row["authority_id"]
                for row in declared_rows
                if row["authority_id"] not in _RUNNABLE_AUTHORITIES
            }
        ),
    }


def install_plists(selected: str, *, apply: bool) -> dict[str, Any]:
    declared_rows = _deployments(selected)
    rows = [
        row for row in declared_rows if row["authority_id"] in _RUNNABLE_AUTHORITIES
    ]
    plan = {
        "format": "local-authority-launchd-install-plan/v1",
        "mode": "DRY_RUN" if not apply else "APPLY",
        "phase": "BOOTSTRAP_INACTIVE",
        "requires_human_sudo": True,
        "strict_gate_required": False,
        "positive_activation_forbidden": True,
        "plists": [
            {
                "authority_id": row["authority_id"],
                "environment": row["environment"],
                "source": row["rendered_plist_path"],
                "destination": row["installed_plist_path"],
            }
            for row in rows
        ],
        "deferred_authorities": sorted(
            {
                row["authority_id"]
                for row in declared_rows
                if row["authority_id"] not in _RUNNABLE_AUTHORITIES
            }
        ),
    }
    if not apply:
        return plan
    _require_human_root()
    bundle = _load_runtime_bundle_manifest()
    for row, result in zip(rows, plan["plists"], strict=True):
        rendered_path = Path(row["rendered_plist_path"])
        expected = _render_plist(row, bundle)
        if rendered_path.read_bytes() != expected:
            raise BootstrapError("render-plists --apply must precede install-plists")
        result["changed"] = _write_root_owned_file(
            Path(row["installed_plist_path"]),
            expected,
            mode=0o644,
            gid=0,
        )
    plan["status"] = "INSTALLED_NOT_LOADED"
    return plan


def _launchd_loaded(label: str) -> bool:
    if platform.system() != "Darwin":
        return False
    return _run(["/bin/launchctl", "print", f"system/{label}"]).returncode == 0


def load_plists(selected: str, *, apply: bool) -> dict[str, Any]:
    declared_rows = _deployments(selected)
    rows = [
        row for row in declared_rows if row["authority_id"] in _RUNNABLE_AUTHORITIES
    ]
    result = {
        "format": "local-authority-launchd-load-plan/v1",
        "mode": "DRY_RUN" if not apply else "APPLY",
        "phase": "POSITIVE_ACTIVATION",
        "requires_human_sudo": True,
        "strict_gate_required": True,
        "jobs": [
            {
                "authority_id": row["authority_id"],
                "environment": row["environment"],
                "label": row["launchd_label"],
                "plist": row["installed_plist_path"],
            }
            for row in rows
        ],
        "deferred_authorities": sorted(
            {
                row["authority_id"]
                for row in declared_rows
                if row["authority_id"] not in _RUNNABLE_AUTHORITIES
            }
        ),
    }
    if not apply:
        return result
    _require_positive_activation()
    bundle = _load_runtime_bundle_manifest()
    for row, job in zip(rows, result["jobs"], strict=True):
        installed = Path(row["installed_plist_path"])
        if installed.read_bytes() != _render_plist(row, bundle):
            raise BootstrapError("installed launchd plist differs from reviewed render")
        runtime_config = Path(row["runtime_config_path"])
        if not _safe_file_state(runtime_config, uid=0, modes=(0o440, 0o444)):
            raise BootstrapError(
                f"root-owned runtime config must be installed before load: {runtime_config}"
            )
        if _launchd_loaded(row["launchd_label"]):
            job["status"] = "ALREADY_LOADED"
            continue
        loaded = _run(
            ["/bin/launchctl", "bootstrap", "system", row["installed_plist_path"]]
        )
        if loaded.returncode != 0:
            raise BootstrapError(f"launchctl bootstrap failed: {row['launchd_label']}")
        if not _launchd_loaded(row["launchd_label"]):
            raise BootstrapError(
                f"launchd job did not become visible: {row['launchd_label']}"
            )
        job["status"] = "LOADED_SOCKET_ACTIVATED"
    result["status"] = "LOADED_NOT_ACTIVATED"
    return result


def _registry_proposal_rows(selected: str) -> list[dict[str, Any]]:
    proposals: list[dict[str, Any]] = []
    for row in _deployments(selected):
        if row["key_backend"] != "protected_local_key":
            proposals.append(
                {
                    "authority_id": row["authority_id"],
                    "environment": row["environment"],
                    "status": "HUMAN_WEBAUTHN_ENROLLMENT_REQUIRED",
                    "registry_path": row["registry_path"],
                    "private_key_path": None,
                }
            )
            continue
        try:
            entry = pwd.getpwnam(row["service_user"])
            metadata = _load_public_metadata(row, expected_uid=entry.pw_uid)
        except (KeyError, BootstrapError):
            proposals.append(
                {
                    "authority_id": row["authority_id"],
                    "environment": row["environment"],
                    "status": "KEY_NOT_PREPARED",
                    "registry_path": row["registry_path"],
                }
            )
            continue
        registry_path = _ROOT / row["registry_path"]
        registry_raw = registry_path.read_bytes()
        public_field = (
            "public_key_base64"
            if row["authority_id"] in {"d1_sync", "ops_projection"}
            else "public_key_b64"
        )
        proposals.append(
            {
                "authority_id": row["authority_id"],
                "environment": row["environment"],
                "status": "INDEPENDENT_REVIEW_REQUIRED",
                "registry_path": row["registry_path"],
                "current_registry_file_digest": (
                    "sha256:" + hashlib.sha256(registry_raw).hexdigest()
                ),
                "json_patch": [
                    {
                        "op": "add",
                        "path": "/keys/-",
                        "value": {
                            "key_id": metadata["key_id"],
                            "algorithm": "Ed25519",
                            public_field: metadata["public_key_base64"],
                            "status": "active",
                        },
                    }
                ],
                "public_key_sha256": metadata["public_key_sha256"],
                "contains_private_key": False,
            }
        )
    return proposals


def registry_proposals(selected: str, *, apply: bool) -> dict[str, Any]:
    document = {
        "format": "local-authority-public-registry-proposals/v1",
        "manifest_digest": PINNED_MANIFEST_DIGEST,
        "mode": "DRY_RUN" if not apply else "WRITTEN_FOR_INDEPENDENT_REVIEW",
        "phase": "BOOTSTRAP_INACTIVE",
        "strict_gate_required": False,
        "positive_activation_forbidden": True,
        "changes_public_registries": False,
        "contains_private_keys": False,
        "proposals": _registry_proposal_rows(selected),
    }
    if not apply:
        return document
    _require_human_root()
    try:
        group_id = grp.getgrnam(SERVICE_GROUP).gr_gid
    except KeyError as exc:
        raise BootstrapError("service group is not provisioned") from exc
    _write_root_owned_file(
        REGISTRY_PROPOSAL_PATH,
        canonical_json_bytes(document) + b"\n",
        mode=0o444,
        gid=group_id,
    )
    document["path"] = str(REGISTRY_PROPOSAL_PATH)
    return document
