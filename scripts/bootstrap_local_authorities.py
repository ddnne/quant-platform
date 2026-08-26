#!/usr/bin/env python3
"""Prepare or audit macOS service principals for local signing authorities.

The default is a machine-readable dry run.  ``--apply`` must be run as root and
creates only disabled service users and protected directories.  It never
creates private keys, activates public registries, loads launchd jobs, starts a
socket, or changes the checked-in PENDING authority contract.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import platform
import pwd
import grp
import socket
import stat
import subprocess
import sys
from typing import Any, Iterable

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from scripts.authority_principal_manifest import (
    LOCAL_OS_PRINCIPALS,
    load_and_validate_manifest,
)
from scripts.finding_ledger_gate import load_pinned_finding_ledger


SERVICE_GROUP = "quant_platform_authorities"
PROTECTED_ROOT = Path("/Library/Application Support/quant-platform/authorities")
RUN_ROOT = Path("/var/run/quant-platform")
LAUNCHD_TEMPLATE = (
    Path(__file__).resolve().parents[1]
    / "specs"
    / "authorities"
    / "launchd"
    / "local-authority.plist.template"
)


class BootstrapError(RuntimeError):
    """The bootstrap plan cannot be applied or audited safely."""


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--environment",
        choices=("staging", "production", "all"),
        default="all",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="create disabled service users/directories; requires human sudo",
    )
    parser.add_argument(
        "--audit",
        action="store_true",
        help="report live users/files/sockets/registries without mutation",
    )
    return parser


def _environments(selected: str) -> tuple[str, ...]:
    return ("staging", "production") if selected == "all" else (selected,)


def _deployments(selected: str) -> list[dict[str, Any]]:
    manifest = load_and_validate_manifest()
    rows: list[dict[str, Any]] = []
    for environment in _environments(selected):
        for authority_id in sorted(LOCAL_OS_PRINCIPALS):
            deployment = manifest["principals"][authority_id]["deployments"][
                environment
            ]
            rows.append(
                {
                    "environment": environment,
                    "authority_id": authority_id,
                    "service_user": deployment["service_user"],
                    "service_identity": deployment["service_identity"],
                    "declared_mode": deployment["mode"],
                    "socket_path": deployment["socket_path"],
                    "service_dir": str(PROTECTED_ROOT / environment / authority_id),
                    "key_path": str(
                        PROTECTED_ROOT
                        / environment
                        / authority_id
                        / "ed25519-private-key"
                    ),
                    "ledger_path": str(
                        PROTECTED_ROOT
                        / environment
                        / authority_id
                        / "authority-events.sqlite3"
                    ),
                    "registry_path": manifest["principals"][authority_id].get(
                        "registry_path"
                    ),
                }
            )
    return rows


def build_plan(selected: str) -> dict[str, Any]:
    rows = _deployments(selected)
    return {
        "format": "local-authority-bootstrap-plan/v1",
        "mode": "DRY_RUN",
        "requires_human_sudo": True,
        "creates_private_keys": False,
        "loads_launchd_jobs": False,
        "activates_registries": False,
        "changes_declared_pending_mode": False,
        "service_group": SERVICE_GROUP,
        "launchd_template": str(LAUNCHD_TEMPLATE),
        "deployments": [
            {
                **row,
                "actions": [
                    "ensure_disabled_service_user",
                    "ensure_service_owned_mode_0700_directory",
                    "reserve_launchd_socket_parent_only",
                ],
            }
            for row in rows
        ],
        "remaining_activation": [
            "generate each Ed25519 key while running as its dedicated service user",
            "independently review and activate the matching public registry",
            "install reviewed launchd plist and load its socket-activated job",
            "verify peer UID, key owner, ledger owner, socket owner, and event append",
            "close the pinned P0 finding ledger through independent review",
        ],
    }


def _run(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, check=False, capture_output=True, text=True)


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


def _ensure_group() -> int:
    if not _record_exists("Groups", SERVICE_GROUP):
        group_id = _next_id(_used_ids("Groups", "PrimaryGroupID"))
        path = f"/Groups/{SERVICE_GROUP}"
        _dscl_create(path, "PrimaryGroupID", str(group_id))
        _dscl_create(path, "RealName", "quant-platform signing authorities")
        _dscl_create(path, "Password", "*")
    try:
        return grp.getgrnam(SERVICE_GROUP).gr_gid
    except KeyError as exc:
        raise BootstrapError("service group was not visible after creation") from exc


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
    if entry.pw_gid != group_id or entry.pw_shell != "/usr/bin/false":
        raise BootstrapError(f"existing service user has unsafe identity: {username}")
    return entry.pw_uid


def _ensure_directory(path: Path, *, uid: int, gid: int, mode: int) -> None:
    path.mkdir(parents=True, exist_ok=True)
    if path.is_symlink() or not path.is_dir():
        raise BootstrapError(f"protected directory is not a directory: {path}")
    os.chown(path, uid, gid)
    os.chmod(path, mode)


def apply_plan(selected: str) -> dict[str, Any]:
    if platform.system() != "Darwin":
        raise BootstrapError("local authority OS bootstrap supports macOS only")
    if os.geteuid() != 0:
        raise BootstrapError(
            "--apply requires an interactive human to run this command with sudo"
        )
    rows = _deployments(selected)
    group_id = _ensure_group()
    used_ids = _used_ids("Users", "UniqueID")
    _ensure_directory(PROTECTED_ROOT, uid=0, gid=group_id, mode=0o711)
    _ensure_directory(RUN_ROOT, uid=0, gid=group_id, mode=0o755)
    applied: list[dict[str, Any]] = []
    for row in rows:
        uid = _ensure_user(
            row["service_user"], group_id=group_id, used_ids=used_ids
        )
        _ensure_directory(
            PROTECTED_ROOT / row["environment"],
            uid=0,
            gid=group_id,
            mode=0o711,
        )
        _ensure_directory(
            Path(row["service_dir"]), uid=uid, gid=group_id, mode=0o700
        )
        # launchd owns socket creation; service users do not receive write
        # access to a shared directory containing other authorities' sockets.
        _ensure_directory(
            RUN_ROOT / row["environment"], uid=0, gid=group_id, mode=0o755
        )
        applied.append(
            {
                "authority_id": row["authority_id"],
                "environment": row["environment"],
                "service_user": row["service_user"],
                "uid": uid,
                "service_directory_prepared": True,
                "key_created": False,
                "launchd_loaded": False,
                "declared_mode": row["declared_mode"],
            }
        )
    return {
        "format": "local-authority-bootstrap-apply/v1",
        "status": "PREPARED_NOT_ACTIVATED",
        "deployments": applied,
    }


def _safe_file_state(path: Path, *, uid: int, modes: Iterable[int]) -> bool:
    try:
        info = path.lstat()
    except OSError:
        return False
    return (
        stat.S_ISREG(info.st_mode)
        and info.st_uid == uid
        and stat.S_IMODE(info.st_mode) in set(modes)
        and info.st_nlink == 1
    )


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
    audited: list[dict[str, Any]] = []
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
            socket_info = socket_path.lstat()
            socket_ready = (
                uid is not None
                and stat.S_ISSOCK(socket_info.st_mode)
                and socket_info.st_uid in {0, uid}
                and not stat.S_IMODE(socket_info.st_mode) & 0o007
            )
        except OSError:
            socket_ready = False
        key_ready = uid is not None and _safe_file_state(
            Path(row["key_path"]), uid=uid, modes=(0o400, 0o600)
        )
        ledger_ready = uid is not None and _safe_file_state(
            Path(row["ledger_path"]), uid=uid, modes=(0o600,)
        )
        active_keys = _active_registry_keys(row["registry_path"])
        checks = {
            "service_user_exists": entry is not None,
            "service_directory_protected": directory_protected,
            "private_key_protected": key_ready,
            "event_ledger_protected": ledger_ready,
            "socket_kernel_object_ready": socket_ready,
            "public_registry_active_key_count": active_keys,
            "strict_release_gate_allowed": ledger.release_allowed,
        }
        activation_checks = (
            checks["service_user_exists"],
            checks["service_directory_protected"],
            checks["private_key_protected"],
            checks["event_ledger_protected"],
            checks["socket_kernel_object_ready"],
            active_keys == 1,
            checks["strict_release_gate_allowed"],
        )
        audited.append(
            {
                "authority_id": row["authority_id"],
                "environment": row["environment"],
                "declared_mode": row["declared_mode"],
                "checks": checks,
                "observed_state": (
                    "ACTIVATION_ELIGIBLE"
                    if row["declared_mode"] == "ACTIVE"
                    and all(activation_checks)
                    else "NOT_ACTIVATED"
                ),
            }
        )
    return {
        "format": "local-authority-observed-state/v1",
        "mutation_performed": False,
        "finding_ledger_digest": ledger.digest,
        "open_p0_ids": list(ledger.open_p0_ids),
        "deployments": audited,
    }


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.apply and args.audit:
        print("--apply and --audit are mutually exclusive", file=sys.stderr)
        return 2
    try:
        if args.apply:
            result = apply_plan(args.environment)
        elif args.audit:
            result = audit_state(args.environment)
        else:
            result = build_plan(args.environment)
    except BootstrapError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
