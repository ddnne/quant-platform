#!/usr/bin/env python3
"""Run one launchd socket-activated, separately permissioned local authority."""

from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import pwd
import socket
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any, NoReturn

_ROOT = Path(__file__).resolve().parents[1]
_IMPORT_ROOTS = (
    _ROOT,
    _ROOT / "packages" / "edge",
    _ROOT / "packages" / "data_plane",
    _ROOT / "packages" / "research_runtime",
    _ROOT / "packages" / "product",
)
for import_root in reversed(_IMPORT_ROOTS):
    if str(import_root) not in sys.path:
        sys.path.insert(0, str(import_root))

from scripts.authority_principal_manifest import load_and_validate_manifest
from scripts.finding_ledger_gate import FindingLedgerError
from scripts.local_authority_files import (
    ProtectedAuthorityFileError,
    read_protected_authority_file,
)
from scripts.local_authority_entrypoints import (
    CoverageTransitionAuthorize,
    D1FreezeAndRenderOpsProjection,
    D1FreezeAuthorizeApplyCoverage,
    D1SyncNow,
    OpsProjectionRenderAndSign,
    ReadyPublishProfilePlanBound,
)
from scripts.local_authority_service import (
    FileEd25519KeyCustody,
    LocalAuthorityError,
    PeerPrincipalRegistry,
    SQLiteAuthorityEventLedger,
    UnixAuthorityConnectionServer,
    UnixAuthorityService,
    require_declared_service_identity,
)

RUNTIME_CONFIG_FORMAT = "local-authority-runtime-config/v1"
_TOP_LEVEL_FIELDS = {
    "format",
    "authority_id",
    "environment",
    "peer_callers",
    "resources",
}
_REQUIRED_CALLERS = {
    "d1_sync": {"ops_scheduler", "coverage_scheduler"},
    "ops_projection": {"d1_sync"},
    "coverage_transition": {"d1_sync"},
    "ready": {"ready_publisher"},
}
_RESOURCE_FIELDS = {
    "d1_sync": {
        "governed_db_path",
        "cloudflare_token_path",
        "node_executable_path",
        "wrangler_cli_path",
        "wrangler_cli_tree_path",
        "wrangler_config_path",
        "wrangler_lock_path",
    },
    "ops_projection": {"artifact_store"},
    "coverage_transition": set(),
    "ready": {"snapshot_root"},
}


class AuthorityRunnerError(RuntimeError):
    """A local authority daemon cannot safely start."""


def _reject_float(value: str) -> NoReturn:
    raise AuthorityRunnerError(f"runtime config contains forbidden number {value!r}")


def _reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise AuthorityRunnerError(f"runtime config duplicates key {key!r}")
        result[key] = value
    return result


def validate_runtime_config(
    document: object, *, authority_id: str, environment: str
) -> dict[str, Any]:
    if type(document) is not dict or set(document) != _TOP_LEVEL_FIELDS:
        raise AuthorityRunnerError("runtime config top-level fields are not closed")
    if (
        document["format"] != RUNTIME_CONFIG_FORMAT
        or document["authority_id"] != authority_id
        or document["environment"] != environment
        or authority_id not in _REQUIRED_CALLERS
    ):
        raise AuthorityRunnerError("runtime config identity is invalid or unsupported")
    peers = document["peer_callers"]
    if (
        type(peers) is not dict
        or len(peers) != len(_REQUIRED_CALLERS[authority_id])
        or set(peers.values()) != _REQUIRED_CALLERS[authority_id]
        or any(type(name) is not str or not name for name in peers)
        or any(type(caller) is not str or not caller for caller in peers.values())
    ):
        raise AuthorityRunnerError(
            "runtime peer caller map is not the exact method ACL"
        )
    resources = document["resources"]
    if type(resources) is not dict or set(resources) != _RESOURCE_FIELDS[authority_id]:
        raise AuthorityRunnerError("runtime resource capability fields are not closed")
    for name, value in resources.items():
        if type(value) is not str or not value or not Path(value).is_absolute():
            raise AuthorityRunnerError(f"runtime resource path is invalid: {name}")
    return document


def decode_runtime_config(
    raw: bytes, *, authority_id: str, environment: str
) -> dict[str, Any]:
    try:
        document = json.loads(
            raw,
            object_pairs_hook=_reject_duplicates,
            parse_float=_reject_float,
            parse_constant=_reject_float,
        )
    except AuthorityRunnerError:
        raise
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise AuthorityRunnerError("runtime config is invalid JSON") from exc
    return validate_runtime_config(
        document,
        authority_id=authority_id,
        environment=environment,
    )


def load_runtime_config(
    row: Mapping[str, Any], *, authority_id: str, environment: str
) -> dict[str, Any]:
    path = Path(row["runtime_config_path"])
    try:
        raw = read_protected_authority_file(
            path,
            expected_owner_uids={0},
            allowed_modes={0o440, 0o444},
            max_bytes=1024 * 1024,
            expected_observation=row["runtime_config_observation"],
        ).raw
    except ProtectedAuthorityFileError as exc:
        raise AuthorityRunnerError("root-owned runtime config is unavailable") from exc
    digest = "sha256:" + hashlib.sha256(raw).hexdigest()
    if digest != row["runtime_config_file_digest"]:
        raise AuthorityRunnerError(
            "runtime config digest differs from activation state"
        )
    document = decode_runtime_config(
        raw,
        authority_id=authority_id,
        environment=environment,
    )
    if row["service_user"] in document["peer_callers"]:
        raise AuthorityRunnerError("authority service user cannot call itself")
    return document


def _load_public_metadata(
    row: Mapping[str, Any], *, expected_uid: int
) -> dict[str, Any]:
    metadata_path = Path(row["key_path"]).with_name("ed25519-public-metadata.json")
    try:
        raw = read_protected_authority_file(
            metadata_path,
            expected_owner_uids={expected_uid},
            allowed_modes={0o400, 0o440, 0o444},
            max_bytes=64 * 1024,
        ).raw
        document = json.loads(raw)
    except (
        ProtectedAuthorityFileError,
        UnicodeError,
        json.JSONDecodeError,
    ) as exc:
        raise AuthorityRunnerError(
            "authority public-key metadata is unavailable"
        ) from exc
    if (
        type(document) is not dict
        or document.get("format") != "local-authority-public-key/v1"
        or document.get("authority_id") != row["authority_id"]
        or document.get("environment") != row["environment"]
        or document.get("key_id") != row["key_id"]
        or document.get("public_key_base64") != row["public_key_base64"]
        or document.get("public_key_sha256") != row["public_key_sha256"]
    ):
        raise AuthorityRunnerError("authority public-key metadata identity is invalid")
    return document


def build_service(*, authority_id: str, environment: str) -> UnixAuthorityService:
    uid, activation = require_declared_service_identity(
        authority_id=authority_id,
        environment=environment,
    )
    config = load_runtime_config(
        activation,
        authority_id=authority_id,
        environment=environment,
    )
    metadata = _load_public_metadata(activation, expected_uid=uid)
    custody = FileEd25519KeyCustody(
        activation["key_path"],
        key_id=metadata["key_id"],
        expected_uid=uid,
    )
    resources = config["resources"]
    manifest = load_and_validate_manifest()

    def service_uid(principal_id: str) -> int:
        deployment = manifest["principals"][principal_id]["deployments"][environment]
        try:
            return pwd.getpwnam(deployment["service_user"]).pw_uid
        except KeyError as exc:
            raise AuthorityRunnerError(
                f"declared {principal_id} service user is absent"
            ) from exc

    if authority_id == "d1_sync":
        handlers = {
            D1SyncNow.operation: D1SyncNow(
                environment=environment,
                governed_db_path=resources["governed_db_path"],
                cloudflare_token_path=resources["cloudflare_token_path"],
                node_executable_path=resources["node_executable_path"],
                wrangler_cli_path=resources["wrangler_cli_path"],
                wrangler_config_path=resources["wrangler_config_path"],
                custody=custody,
                expected_uid=uid,
            ),
            D1FreezeAndRenderOpsProjection.operation: (
                D1FreezeAndRenderOpsProjection(
                    environment=environment,
                    governed_db_path=resources["governed_db_path"],
                    ops_socket_path=manifest["principals"]["ops_projection"][
                        "deployments"
                    ][environment]["socket_path"],
                    ops_uid=service_uid("ops_projection"),
                )
            ),
            D1FreezeAuthorizeApplyCoverage.operation: (
                D1FreezeAuthorizeApplyCoverage(
                    environment=environment,
                    governed_db_path=resources["governed_db_path"],
                    coverage_socket_path=manifest["principals"]["coverage_transition"][
                        "deployments"
                    ][environment]["socket_path"],
                    coverage_uid=service_uid("coverage_transition"),
                )
            ),
        }
    elif authority_id == "ops_projection":
        handlers = {
            OpsProjectionRenderAndSign.operation: OpsProjectionRenderAndSign(
                environment=environment,
                custody=custody,
                artifact_store=resources["artifact_store"],
                expected_d1_uid=service_uid("d1_sync"),
            )
        }
    elif authority_id == "coverage_transition":
        handlers = {
            CoverageTransitionAuthorize.operation: (
                CoverageTransitionAuthorize(
                    environment=environment,
                    custody=custody,
                    expected_d1_uid=service_uid("d1_sync"),
                )
            )
        }
    elif authority_id == "ready":
        handlers = {
            ReadyPublishProfilePlanBound.operation: ReadyPublishProfilePlanBound(
                environment=environment,
                snapshot_root=resources["snapshot_root"],
                custody=custody,
            )
        }
    else:  # validated by load_runtime_config; defensive for future manifest rows
        raise AuthorityRunnerError("authority has no reviewed local handler set")
    ledger = SQLiteAuthorityEventLedger(
        activation["ledger_path"],
        authority_id=authority_id,
        environment=environment,
        expected_uid=uid,
    )
    ledger.initialize()
    return UnixAuthorityService(
        authority_id=authority_id,
        environment=environment,
        peers=PeerPrincipalRegistry.from_usernames(config["peer_callers"]),
        ledger=ledger,
        handlers=handlers,
    )


def launchd_listener(*, expected_socket_path: str) -> socket.socket:
    if sys.platform != "darwin":
        raise AuthorityRunnerError("launchd socket activation requires macOS")
    library = ctypes.CDLL("/usr/lib/libSystem.B.dylib", use_errno=True)
    activate = library.launch_activate_socket
    activate.argtypes = [
        ctypes.c_char_p,
        ctypes.POINTER(ctypes.POINTER(ctypes.c_int)),
        ctypes.POINTER(ctypes.c_size_t),
    ]
    activate.restype = ctypes.c_int
    descriptors = ctypes.POINTER(ctypes.c_int)()
    count = ctypes.c_size_t()
    error = activate(b"Listener", ctypes.byref(descriptors), ctypes.byref(count))
    if error != 0 or count.value != 1:
        raise AuthorityRunnerError(
            "launchd did not provide exactly one Listener socket"
        )
    try:
        descriptor = int(descriptors[0])
    finally:
        library.free(descriptors)
    listener = socket.socket(fileno=descriptor)
    if (
        listener.family != socket.AF_UNIX
        or listener.type & socket.SOCK_STREAM != socket.SOCK_STREAM
        or listener.getsockname() != expected_socket_path
    ):
        listener.close()
        raise AuthorityRunnerError(
            "launchd Listener identity differs from activation state"
        )
    return listener


def serve_forever(*, authority_id: str, environment: str) -> NoReturn:
    service = build_service(authority_id=authority_id, environment=environment)
    manifest = load_and_validate_manifest()
    socket_path = manifest["principals"][authority_id]["deployments"][environment][
        "socket_path"
    ]
    listener = launchd_listener(expected_socket_path=socket_path)
    UnixAuthorityConnectionServer(service).serve(listener)
    raise AssertionError("authority connection server returned unexpectedly")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--authority", required=True)
    parser.add_argument(
        "--environment", choices=("staging", "production"), required=True
    )
    args = parser.parse_args(argv)
    try:
        serve_forever(authority_id=args.authority, environment=args.environment)
    except (AuthorityRunnerError, LocalAuthorityError, FindingLedgerError) as exc:
        print(
            f"local authority startup rejected: {type(exc).__name__}", file=sys.stderr
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
