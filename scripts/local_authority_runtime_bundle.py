"""Root-owned content-addressed runtime bundle preparation and validation."""

from __future__ import annotations

import grp
import io
import json
import os
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from scripts.local_authority_activation import (
    canonical_json_bytes,
    regular_file_digest,
    runtime_bundle_tree_digest,
)
from scripts.local_authority_bootstrap_common import (
    _ROOT,
    RUNTIME_BUNDLE_MANIFEST_PATH,
    RUNTIME_BUNDLES_ROOT,
    SERVICE_GROUP,
    BootstrapError,
    _ensure_directory,
    _require_human_root,
    _run,
    _safe_file_state,
    _write_root_owned_file,
)


def _require_root_owned_executable(path: Path) -> Path:
    try:
        resolved = path.resolve(strict=True)
    except OSError as exc:
        raise BootstrapError("root-owned runtime Python is unavailable") from exc
    info = resolved.lstat()
    if (
        not stat.S_ISREG(info.st_mode)
        or info.st_uid != 0
        or info.st_nlink != 1
        or stat.S_IMODE(info.st_mode) & 0o022
        or not stat.S_IMODE(info.st_mode) & 0o111
    ):
        raise BootstrapError("runtime Python is not a protected root-owned executable")
    for parent in (resolved.parent, *resolved.parents):
        parent_info = parent.lstat()
        if (
            not stat.S_ISDIR(parent_info.st_mode)
            or parent_info.st_uid != 0
            or stat.S_IMODE(parent_info.st_mode) & 0o022
        ):
            raise BootstrapError("runtime Python has a user-writable path ancestor")
    return resolved


def _validate_root_python_dependencies(python_path: Path) -> None:
    probe = (
        "import json,sys,cryptography,jsonschema;"
        "print(json.dumps({'version':list(sys.version_info[:3]),"
        "'modules':[cryptography.__file__,jsonschema.__file__]}))"
    )
    result = _run([str(python_path), "-I", "-c", probe])
    if result.returncode != 0:
        raise BootstrapError("root-owned runtime Python lacks required dependencies")
    try:
        evidence = json.loads(result.stdout)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise BootstrapError(
            "runtime Python dependency probe returned invalid evidence"
        ) from exc
    if (
        type(evidence) is not dict
        or type(evidence.get("version")) is not list
        or tuple(evidence["version"][:2]) < (3, 11)
        or type(evidence.get("modules")) is not list
        or len(evidence["modules"]) != 2
    ):
        raise BootstrapError("runtime Python dependency evidence is invalid")
    for raw_path in evidence["modules"]:
        if type(raw_path) is not str:
            raise BootstrapError("runtime Python dependency path is invalid")
        module_path = Path(raw_path).resolve(strict=True)
        module_info = module_path.lstat()
        if (
            not stat.S_ISREG(module_info.st_mode)
            or module_info.st_uid != 0
            or stat.S_IMODE(module_info.st_mode) & 0o022
        ):
            raise BootstrapError("runtime Python dependency is not root-owned")
        for parent in (module_path.parent, *module_path.parents):
            parent_info = parent.lstat()
            if parent_info.st_uid != 0 or stat.S_IMODE(parent_info.st_mode) & 0o022:
                raise BootstrapError("runtime dependency has a user-writable ancestor")


def _runtime_python_acquisition_plan() -> dict[str, Any]:
    candidates: list[dict[str, Any]] = []
    for candidate in dict.fromkeys((Path("/usr/bin/python3"), Path(sys.executable))):
        try:
            resolved = candidate.resolve(strict=True)
            info = resolved.lstat()
            version = _run([str(resolved), "--version"])
            version_text = (version.stdout or version.stderr).strip()
            try:
                version_tuple = tuple(
                    int(item) for item in version_text.split()[1].split(".")[:2]
                )
            except (IndexError, ValueError):
                version_tuple = (0, 0)
            dependency_probe = _run(
                [
                    str(resolved),
                    "-I",
                    "-c",
                    "import cryptography,jsonschema",
                ]
            )
            protected = True
            for parent in (resolved.parent, *resolved.parents):
                parent_info = parent.lstat()
                if parent_info.st_uid != 0 or stat.S_IMODE(parent_info.st_mode) & 0o022:
                    protected = False
                    break
            candidates.append(
                {
                    "path": str(resolved),
                    "owner_uid": info.st_uid,
                    "mode": stat.S_IMODE(info.st_mode),
                    "version": version_text,
                    "required_modules_importable": dependency_probe.returncode == 0,
                    "root_owned_protected_path": protected,
                    "launchd_eligible": (
                        protected
                        and dependency_probe.returncode == 0
                        and version_tuple >= (3, 11)
                    ),
                }
            )
        except OSError:
            candidates.append(
                {"path": str(candidate), "status": "ABSENT", "launchd_eligible": False}
            )
    return {
        "status": "HUMAN_REVIEWED_ROOT_RUNTIME_ARTIFACT_REQUIRED",
        "minimum_python": "3.11",
        "required_modules": ["cryptography", "jsonschema"],
        "dependency_lock": str(_ROOT / "uv.lock"),
        "dependency_lock_digest": regular_file_digest(_ROOT / "uv.lock"),
        "required_human_inputs": [
            "approved_distribution_source_url",
            "vendor_signature_verification_evidence",
            "approved_distribution_sha256",
            "root_owned_installed_interpreter_path",
        ],
        "reviewed_sequence": [
            "acquire a reviewed CPython 3.11+ distribution without sudo",
            "verify vendor signature and record the exact archive SHA-256",
            "install only that verified artifact below a root-owned non-writable prefix",
            "build an isolated root-owned runtime from the pinned dependency lock",
            "pass its interpreter as --root-python; user-owned Python/uv remain forbidden",
        ],
        "host_candidates": candidates,
    }


def _d1_remote_sync_prerequisite_plan() -> dict[str, Any]:
    worker_root = _ROOT / "platform" / "workers" / "ingestion-premium"
    node_candidate = shutil.which("node")
    node_observation: dict[str, Any] = {"status": "ABSENT"}
    if node_candidate is not None:
        candidate = Path(node_candidate)
        try:
            resolved = candidate.resolve(strict=True)
            info = resolved.lstat()
            protected = info.st_uid == 0 and not stat.S_IMODE(info.st_mode) & 0o022
            for parent in (resolved.parent, *resolved.parents):
                parent_info = parent.lstat()
                protected = protected and parent_info.st_uid == 0 and not (
                    stat.S_IMODE(parent_info.st_mode) & 0o022
                )
            node_observation = {
                "status": "OBSERVED",
                "path": str(resolved),
                "owner_uid": info.st_uid,
                "mode": stat.S_IMODE(info.st_mode),
                "root_owned_protected_path": protected,
                "authority_eligible": protected,
            }
        except OSError:
            node_observation = {
                "status": "UNAVAILABLE",
                "path": str(candidate),
                "authority_eligible": False,
            }
    return {
        "format": "d1-authority-remote-sync-prerequisites/v1",
        "governed_environment": "production",
        "governed_database_name": "quant-ingest",
        "governed_database_id": "be6fdcf8-40be-41fc-9535-7facd1fc2ffc",
        "pinned_wrangler_version": "4.125.0",
        "package_lock": str(worker_root / "package-lock.json"),
        "package_lock_digest": regular_file_digest(worker_root / "package-lock.json"),
        "wrangler_config": str(worker_root / "wrangler.toml"),
        "wrangler_config_digest": regular_file_digest(worker_root / "wrangler.toml"),
        "observed_node_candidate": node_observation,
        "required_protected_resources": [
            "root_owned_non_writable_node_executable",
            "root_owned_non_writable_wrangler_4_125_0_cli_from_pinned_lock",
            "root_owned_non_writable_governed_wrangler_config",
            "d1_authority_uid_owned_mode_0400_scoped_cloudflare_api_token_file",
        ],
        "credential_requirements": {
            "delivery": "protected file referenced by root-owned runtime config",
            "argv": "FORBIDDEN",
            "logs_or_artifacts": "FORBIDDEN",
            "minimum_scope": "read/export governed quant-ingest D1 only",
        },
        "activation_status": "HUMAN_PROVISIONING_REQUIRED",
    }


def _load_runtime_bundle_manifest() -> dict[str, Any]:
    if not _safe_file_state(RUNTIME_BUNDLE_MANIFEST_PATH, uid=0, modes=(0o440, 0o444)):
        raise BootstrapError("root-owned runtime bundle manifest is absent or unsafe")
    try:
        document = json.loads(RUNTIME_BUNDLE_MANIFEST_PATH.read_bytes())
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise BootstrapError("runtime bundle manifest is invalid JSON") from exc
    expected_fields = {
        "format",
        "source_sha",
        "bundle_path",
        "bundle_digest",
        "entrypoint_path",
        "entrypoint_digest",
        "python_path",
        "python_digest",
        "installed_at",
    }
    if type(document) is not dict or set(document) != expected_fields:
        raise BootstrapError("runtime bundle manifest fields are not closed")
    bundle_path = Path(document["bundle_path"])
    entrypoint = Path(document["entrypoint_path"])
    python_path = Path(document["python_path"])
    if (
        not str(bundle_path).startswith(str(RUNTIME_BUNDLES_ROOT) + os.sep)
        or entrypoint != bundle_path / "scripts" / "run_local_authority.py"
        or runtime_bundle_tree_digest(bundle_path, expected_owner_uid=0)
        != document["bundle_digest"]
        or regular_file_digest(entrypoint) != document["entrypoint_digest"]
        or regular_file_digest(python_path) != document["python_digest"]
    ):
        raise BootstrapError("runtime bundle manifest does not match immutable files")
    _require_root_owned_executable(python_path)
    return document


def _protect_runtime_tree(path: Path, *, gid: int) -> None:
    for current, directories, files in os.walk(path, topdown=False, followlinks=False):
        current_path = Path(current)
        for name in files:
            target = current_path / name
            if target.is_symlink() or not target.is_file():
                raise BootstrapError("runtime bundle contains a link or special file")
            os.chown(target, 0, gid)
            os.chmod(target, 0o444)
        for name in directories:
            target = current_path / name
            if target.is_symlink() or not target.is_dir():
                raise BootstrapError("runtime bundle contains a linked directory")
            os.chown(target, 0, gid)
            os.chmod(target, 0o555)
        os.chown(current_path, 0, gid)
        os.chmod(current_path, 0o555)


def install_runtime_bundle(
    *, apply: bool, expected_source_sha: str | None, root_python: Path | None
) -> dict[str, Any]:
    plan: dict[str, Any] = {
        "format": "local-authority-runtime-bundle-install/v1",
        "mode": "DRY_RUN" if not apply else "APPLY",
        "phase": "BOOTSTRAP_INACTIVE",
        "requires_human_sudo": True,
        "strict_gate_required": False,
        "positive_activation_forbidden": True,
        "source": "git archive of the reviewed exact commit only",
        "destination_root": str(RUNTIME_BUNDLES_ROOT),
        "runtime_manifest": str(RUNTIME_BUNDLE_MANIFEST_PATH),
        "launchd_uses_checkout_or_uv": False,
        "runtime_python_acquisition": _runtime_python_acquisition_plan(),
        "d1_remote_sync_prerequisites": _d1_remote_sync_prerequisite_plan(),
    }
    if not apply:
        return plan
    _require_human_root()
    if (
        type(expected_source_sha) is not str
        or len(expected_source_sha) != 40
        or any(character not in "0123456789abcdef" for character in expected_source_sha)
        or root_python is None
    ):
        raise BootstrapError(
            "install-runtime-bundle --apply requires lowercase --expected-source-sha "
            "and --root-python"
        )
    head = _run(["/usr/bin/git", "-C", str(_ROOT), "rev-parse", "HEAD"])
    status = _run(["/usr/bin/git", "-C", str(_ROOT), "status", "--porcelain"])
    if (
        head.returncode != 0
        or head.stdout.strip() != expected_source_sha
        or status.returncode != 0
        or status.stdout.strip()
    ):
        raise BootstrapError(
            "runtime bundle source is not the reviewed clean exact SHA"
        )
    python_path = _require_root_owned_executable(root_python)
    _validate_root_python_dependencies(python_path)
    archive = subprocess.run(
        [
            "/usr/bin/git",
            "-C",
            str(_ROOT),
            "archive",
            "--format=tar",
            expected_source_sha,
        ],
        check=False,
        capture_output=True,
    )
    if archive.returncode != 0:
        raise BootstrapError("git archive failed for the reviewed runtime SHA")
    try:
        group_id = grp.getgrnam(SERVICE_GROUP).gr_gid
    except KeyError as exc:
        raise BootstrapError("service group is absent") from exc
    _ensure_directory(RUNTIME_BUNDLES_ROOT, uid=0, gid=group_id, mode=0o755)
    temporary_root = Path(
        tempfile.mkdtemp(prefix=".runtime-new-", dir=RUNTIME_BUNDLES_ROOT)
    )
    source_root = temporary_root / "source"
    source_root.mkdir(mode=0o700)
    try:
        with tarfile.open(fileobj=io.BytesIO(archive.stdout), mode="r:") as tar:
            members = tar.getmembers()
            if any(
                member.name.startswith("/")
                or ".." in Path(member.name).parts
                or member.issym()
                or member.islnk()
                or member.isdev()
                for member in members
            ):
                raise BootstrapError("git archive contains an unsafe runtime path")
            tar.extractall(source_root, members=members)
        entrypoint = source_root / "scripts" / "run_local_authority.py"
        if not entrypoint.is_file():
            raise BootstrapError("reviewed runtime bundle has no authority entrypoint")
        _protect_runtime_tree(temporary_root, gid=group_id)
        bundle_digest = runtime_bundle_tree_digest(source_root, expected_owner_uid=0)
        destination = RUNTIME_BUNDLES_ROOT / bundle_digest.replace(":", "_")
        if destination.exists():
            existing_source = destination / "source"
            if (
                runtime_bundle_tree_digest(existing_source, expected_owner_uid=0)
                != bundle_digest
            ):
                raise BootstrapError("runtime bundle digest path collides")
            shutil.rmtree(temporary_root)
            source_root = existing_source
        else:
            os.rename(temporary_root, destination)
            source_root = destination / "source"
    except BaseException:
        if temporary_root.exists():
            shutil.rmtree(temporary_root)
        raise
    entrypoint = source_root / "scripts" / "run_local_authority.py"
    document = {
        "format": "local-authority-runtime-bundle/v1",
        "source_sha": expected_source_sha,
        "bundle_path": str(source_root),
        "bundle_digest": bundle_digest,
        "entrypoint_path": str(entrypoint),
        "entrypoint_digest": regular_file_digest(entrypoint),
        "python_path": str(python_path),
        "python_digest": regular_file_digest(python_path),
        "installed_at": datetime.now(UTC).isoformat(),
    }
    if RUNTIME_BUNDLE_MANIFEST_PATH.exists():
        existing = _load_runtime_bundle_manifest()
        if all(
            existing.get(key) == value
            for key, value in document.items()
            if key != "installed_at"
        ):
            document = existing
    _write_root_owned_file(
        RUNTIME_BUNDLE_MANIFEST_PATH,
        canonical_json_bytes(document) + b"\n",
        mode=0o444,
        gid=group_id,
    )
    plan.update(
        {
            "status": "INSTALLED_NOT_LOADED_NOT_ACTIVE",
            "source_sha": expected_source_sha,
            "bundle_path": document["bundle_path"],
            "bundle_digest": document["bundle_digest"],
            "entrypoint_digest": document["entrypoint_digest"],
            "python_digest": document["python_digest"],
        }
    )
    return plan

