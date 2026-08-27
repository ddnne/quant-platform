"""Shared declarations and fail-closed primitives for local authority bootstrap."""

from __future__ import annotations

import grp
import os
import platform
import pwd
import stat
import subprocess
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from scripts.authority_principal_manifest import (
    LOCAL_OS_PRINCIPALS,
    LOCAL_PEER_IDENTITIES,
    load_and_validate_manifest,
)
from scripts.finding_ledger_gate import (
    FindingLedgerError,
    require_pinned_finding_ledger_gate,
)

_ROOT = Path(__file__).resolve().parents[1]
SERVICE_GROUP = "quant_platform_authorities"
PROTECTED_ROOT = Path("/Library/Application Support/quant-platform/authorities")
RUN_ROOT = Path("/var/run/quant-platform")
LAUNCHD_TEMPLATE = _ROOT / "specs" / "authorities" / "launchd" / "local-authority.plist.template"
LAUNCHD_RENDER_ROOT = PROTECTED_ROOT / "launchd"
LAUNCHD_INSTALL_ROOT = Path("/Library/LaunchDaemons")
RUNTIME_BUNDLES_ROOT = PROTECTED_ROOT / "runtime-bundles"
RUNTIME_BUNDLE_MANIFEST_PATH = PROTECTED_ROOT / "runtime-bundle.json"
PUBLIC_METADATA_NAME = "ed25519-public-metadata.json"
REGISTRY_PROPOSAL_PATH = PROTECTED_ROOT / "public-registry-proposals.json"
BOOTSTRAP_ONLY_ACTIONS = frozenset({
    "prepare-users", "generate-keys", "install-runtime-configs",
    "install-runtime-bundle", "render-plists", "install-plists", "registry-proposals",
})
POSITIVE_ACTIVATION_ACTIONS = frozenset({"load-plists", "activate"})
_ACTIONS = ("plan", "audit", *sorted(BOOTSTRAP_ONLY_ACTIONS), *sorted(POSITIVE_ACTIVATION_ACTIONS))
_RUNNABLE_AUTHORITIES = frozenset(LOCAL_OS_PRINCIPALS)
_FILE_BACKED_ACTIVATION_AUTHORITIES = frozenset(
    authority_id
    for authority_id in LOCAL_OS_PRINCIPALS
    if authority_id != "trader"
)
EXECUTION_ACTIVATION_DOCUMENTS = {
    "trader": Path("/etc/quant-platform/authorities/trader/activation.json"),
    "controlled_execution": Path(
        "/etc/quant-platform/authorities/controlled_execution/activation.json"
    ),
}


class BootstrapError(RuntimeError):
    """The bootstrap plan cannot be applied or audited safely."""

def _environments(selected: str) -> tuple[str, ...]:
    return ("staging", "production") if selected == "all" else (selected,)


def controlled_custody_reader_group(environment: str) -> str:
    """Return the one supplementary group allowed to read Controlled custody."""

    if environment not in {"staging", "production"}:
        raise BootstrapError("Controlled custody environment is not declared")
    return f"qp_{environment}_controlled_execution_readers"


def require_controlled_custody_reader_group(
    *,
    row: dict[str, Any],
    service_account: pwd.struct_passwd,
) -> tuple[grp.struct_group, grp.struct_group, grp.struct_group]:
    """Resolve the exact service, socket, and custody groups fail closed.

    Custody is a supplementary capability held only by the Controlled service
    user.  It must never reuse either the authorities' shared primary group or
    the Controlled socket caller group, whose membership also includes Trader.
    """

    environment = row.get("environment")
    expected_reader_name = (
        controlled_custody_reader_group(environment)
        if type(environment) is str
        else None
    )
    if (
        row.get("authority_id") != "controlled_execution"
        or row.get("service_user") != service_account.pw_name
        or type(row.get("caller_group")) is not str
        or row.get("custody_reader_group") != expected_reader_name
    ):
        raise BootstrapError("Controlled custody reader declaration drifted")
    try:
        service_group = grp.getgrnam(SERVICE_GROUP)
        caller_group = grp.getgrnam(row["caller_group"])
        reader_group = grp.getgrnam(row["custody_reader_group"])
    except KeyError as exc:
        raise BootstrapError(
            "Controlled custody reader group is not provisioned"
        ) from exc
    if (
        type(service_group.gr_gid) is not int
        or type(caller_group.gr_gid) is not int
        or type(reader_group.gr_gid) is not int
        or min(service_group.gr_gid, caller_group.gr_gid, reader_group.gr_gid) <= 0
        or len(
            {service_group.gr_gid, caller_group.gr_gid, reader_group.gr_gid}
        ) != 3
        or service_account.pw_uid <= 0
        or service_account.pw_gid != service_group.gr_gid
        or reader_group.gr_name != expected_reader_name
        or set(reader_group.gr_mem) != {service_account.pw_name}
    ):
        raise BootstrapError(
            "Controlled custody reader group is not an isolated exact membership"
        )
    try:
        reader_by_gid = grp.getgrgid(reader_group.gr_gid)
    except KeyError as exc:
        raise BootstrapError("Controlled custody reader GID is not resolvable") from exc
    if reader_by_gid.gr_name != expected_reader_name:
        raise BootstrapError("Controlled custody reader GID reverse mapping drifted")
    return service_group, caller_group, reader_group


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
                    "key_backend": deployment["key_backend"],
                    "socket_path": deployment["socket_path"],
                    "service_dir": str(PROTECTED_ROOT / environment / authority_id),
                    "key_path": (
                        str(
                            PROTECTED_ROOT
                            / environment
                            / authority_id
                            / "ed25519-private-key"
                        )
                        if deployment["key_backend"] == "protected_local_key"
                        else None
                    ),
                    "public_metadata_path": (
                        str(
                            PROTECTED_ROOT
                            / environment
                            / authority_id
                            / PUBLIC_METADATA_NAME
                        )
                        if deployment["key_backend"] == "protected_local_key"
                        else None
                    ),
                    "ledger_path": str(
                        PROTECTED_ROOT
                        / environment
                        / authority_id
                        / "authority-events.sqlite3"
                    ),
                    "registry_path": deployment["public_registry_path"],
                    "runtime_config_path": str(
                        PROTECTED_ROOT
                        / "runtime-config"
                        / environment
                        / f"{authority_id}.json"
                    ),
                    "caller_group": (f"qp_{environment}_{authority_id}_callers"),
                    "custody_reader_group": (
                        controlled_custody_reader_group(environment)
                        if authority_id == "controlled_execution"
                        else None
                    ),
                    "launchd_label": (
                        f"com.quant-platform.{environment}.{authority_id}"
                    ),
                    "rendered_plist_path": str(
                        LAUNCHD_RENDER_ROOT
                        / f"com.quant-platform.{environment}.{authority_id}.plist"
                    ),
                    "installed_plist_path": str(
                        LAUNCHD_INSTALL_ROOT
                        / f"com.quant-platform.{environment}.{authority_id}.plist"
                    ),
                }
            )
    return rows


def _local_peer_rows(selected: str) -> list[dict[str, str]]:
    return [
        {
            "environment": environment,
            "caller": caller,
            "service_user": identity["deployments"][environment]["service_user"],
            "runtime": identity["runtime"],
        }
        for environment in _environments(selected)
        for caller, identity in sorted(LOCAL_PEER_IDENTITIES.items())
    ]


def _caller_service_user(*, environment: str, caller: str) -> str:
    manifest = load_and_validate_manifest()
    if caller in LOCAL_OS_PRINCIPALS:
        return manifest["principals"][caller]["deployments"][environment][
            "service_user"
        ]
    identity = manifest["local_peer_identities"].get(caller)
    if type(identity) is not dict:
        raise BootstrapError(f"caller has no declared local service identity: {caller}")
    return identity["deployments"][environment]["service_user"]


def build_plan(selected: str) -> dict[str, Any]:
    rows = _deployments(selected)
    return {
        "format": "local-authority-bootstrap-plan/v1",
        "mode": "DRY_RUN",
        "phase": "BOOTSTRAP_INACTIVE",
        "requires_human_sudo": True,
        "strict_gate_required": False,
        "positive_activation_forbidden": True,
        "creates_private_keys": False,
        "loads_launchd_jobs": False,
        "activates_registries": False,
        "changes_declared_pending_mode": False,
        "service_group": SERVICE_GROUP,
        "local_peer_identities": _local_peer_rows(selected),
        "launchd_template": str(LAUNCHD_TEMPLATE),
        "deployments": [
            {
                **row,
                "actions": [
                    "ensure_disabled_service_user",
                    "ensure_service_owned_mode_0700_directory",
                    "reserve_launchd_socket_parent_only",
                    *(
                        ["ensure_controlled_only_custody_reader_group"]
                        if row["custody_reader_group"] is not None
                        else []
                    ),
                ],
            }
            for row in rows
        ],
        "remaining_activation": [
            "generate file-backed Ed25519 keys under each dedicated signing service UID",
            (
                "for Trader only, enroll an independently governed WebAuthn "
                "credential with human presence; never create a file private key"
            ),
            "independently review and activate the matching public registry",
            "install an exact root-owned runtime config for peer callers/resources",
            (
                "install root-owned Node and pinned Wrangler 4.125.0 artifacts, "
                "then place a D1-export-scoped Cloudflare token in a d1_sync-UID-owned "
                "mode-0400 file; no credential is accepted in argv or the manifest"
            ),
            "install reviewed launchd plist and load its socket-activated job",
            "verify peer UID, key owner, ledger owner, socket owner, and event append",
            "close the pinned P0 finding ledger through independent review",
        ],
    }


def _run(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, check=False, capture_output=True, text=True)


def _require_human_root() -> None:
    if platform.system() != "Darwin":
        raise BootstrapError("local authority OS bootstrap supports macOS only")
    if os.geteuid() != 0:
        raise BootstrapError(
            "--apply requires an interactive human to run this command with sudo"
        )
    # Revalidate the independently code-pinned declaration on every mutating
    # bootstrap action.  These actions may prepare resources but cannot load a
    # job, write ACTIVE state, edit a public registry, or serve a positive call.
    load_and_validate_manifest()


def _require_positive_activation() -> Any:
    _require_human_root()
    try:
        return require_pinned_finding_ledger_gate()
    except FindingLedgerError as exc:
        raise BootstrapError(
            f"strict finding-ledger release gate rejected apply: {exc}"
        ) from exc


def _ensure_directory(path: Path, *, uid: int, gid: int, mode: int) -> None:
    path.mkdir(parents=True, exist_ok=True)
    if path.is_symlink() or not path.is_dir():
        raise BootstrapError(f"protected directory is not a directory: {path}")
    os.chown(path, uid, gid)
    os.chmod(path, mode)


def _write_exclusive(path: Path, content: bytes, *, mode: int) -> None:
    flags = (
        os.O_WRONLY
        | os.O_CREAT
        | os.O_EXCL
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    fd = os.open(path, flags, mode)
    try:
        offset = 0
        while offset < len(content):
            offset += os.write(fd, content[offset:])
        os.fsync(fd)
        os.fchmod(fd, mode)
    finally:
        os.close(fd)


def _write_root_owned_file(path: Path, content: bytes, *, mode: int, gid: int) -> bool:
    if path.exists():
        info = path.lstat()
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_uid != 0
            or stat.S_IMODE(info.st_mode) != mode
            or info.st_nlink != 1
        ):
            raise BootstrapError(f"existing root-owned file is unsafe: {path}")
        if path.read_bytes() == content:
            return False
    elif path.is_symlink():
        raise BootstrapError(f"root-owned file path is a symlink: {path}")
    temporary = path.with_name(f".{path.name}.new-{os.getpid()}")
    try:
        _write_exclusive(temporary, content, mode=mode)
        temporary_fd = os.open(temporary, os.O_RDONLY)
        try:
            os.fchown(temporary_fd, 0, gid)
        finally:
            os.close(temporary_fd)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise
    os.replace(temporary, path)
    directory_fd = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)
    return True


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
