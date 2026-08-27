#!/usr/bin/env python3
"""Run one launchd socket-activated, separately permissioned local authority."""

from __future__ import annotations

import argparse
import base64
import ctypes
import grp
import hashlib
import json
import os
import pwd
import socket
import stat
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any, NoReturn

from cryptography.hazmat.primitives import serialization

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

from execution.exact_four_codec import ExactFourAuthorityPending

from scripts.authority_principal_manifest import load_and_validate_manifest
from scripts.execution_authority_entrypoints import (
    CONTROLLED_TRADER_HANDOFF_OPERATION,
    TRADER_AUTHORIZE_OPERATION,
    open_live_controlled_execution_handler_v2,
    open_live_trader_authority_handler_v2,
)
from scripts.finding_ledger_gate import FindingLedgerError
from scripts.local_authority_bootstrap_common import (
    EXECUTION_ACTIVATION_DOCUMENTS,
    PROTECTED_ROOT,
)
from scripts.local_authority_entrypoints import (
    CoverageTransitionAuthorize,
    D1FreezeAndRenderOpsProjection,
    D1FreezeAuthorizeApplyCoverage,
    D1SyncNow,
    OpsProjectionRenderAndSign,
    ReadyPublishProfilePlanBound,
    _d1_sync_tool_bindings_digest,
)
from scripts.local_authority_files import (
    ProtectedAuthorityFileError,
    read_protected_authority_file,
)
from scripts.local_authority_service import (
    DEFAULT_PROCESSING_TIMEOUT_SECONDS,
    FileEd25519KeyCustody,
    LocalAuthorityError,
    LocalAuthorityPending,
    PeerPrincipalRegistry,
    SQLiteAuthorityEventLedger,
    UnixAuthorityConnectionServer,
    UnixAuthorityService,
    require_declared_service_identity,
)

D1_SYNC_PROCESSING_TIMEOUT_SECONDS = 900.0
READY_PROCESSING_TIMEOUT_SECONDS = 900.0
EXECUTION_PROCESSING_TIMEOUT_SECONDS = 1800.0


def _processing_timeout_seconds(authority_id: str) -> float:
    """Return the code-pinned processing lease for one authority."""

    if authority_id == "d1_sync":
        return D1_SYNC_PROCESSING_TIMEOUT_SECONDS
    if authority_id == "ready":
        return READY_PROCESSING_TIMEOUT_SECONDS
    if authority_id in {"trader", "controlled_execution"}:
        return EXECUTION_PROCESSING_TIMEOUT_SECONDS
    return DEFAULT_PROCESSING_TIMEOUT_SECONDS


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
    "trader": {"controlled_pilot_orchestrator"},
    "controlled_execution": {"trader"},
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
    "trader": {"activation_document_path"},
    "controlled_execution": {"activation_document_path"},
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
    if (
        authority_id in EXECUTION_ACTIVATION_DOCUMENTS
        and Path(resources["activation_document_path"])
        != EXECUTION_ACTIVATION_DOCUMENTS[authority_id]
    ):
        raise AuthorityRunnerError(
            "execution activation document path differs from the pinned authority"
        )
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


def _load_root_runtime_config(
    path: Path, *, authority_id: str, environment: str
) -> dict[str, Any]:
    """Read one exact root-owned config when no generic key overlay exists."""

    try:
        raw = read_protected_authority_file(
            path,
            expected_owner_uids={0},
            allowed_modes={0o440, 0o444},
            max_bytes=1024 * 1024,
        ).raw
    except ProtectedAuthorityFileError as exc:
        raise AuthorityRunnerError("root-owned runtime config is unavailable") from exc
    return decode_runtime_config(
        raw,
        authority_id=authority_id,
        environment=environment,
    )


def _require_execution_activation_path(
    *, authority_id: str, resources: Mapping[str, Any]
) -> Path:
    try:
        expected = EXECUTION_ACTIVATION_DOCUMENTS[authority_id]
    except KeyError as exc:  # pragma: no cover - closed caller set
        raise AuthorityRunnerError("execution authority identity is unsupported") from exc
    observed = Path(resources["activation_document_path"])
    if observed != expected:
        raise AuthorityRunnerError(
            "execution activation document path differs from the pinned authority"
        )
    return observed


def _require_trader_service_identity(
    *, environment: str, manifest: Mapping[str, Any]
) -> tuple[int, dict[str, Any], Path, Path]:
    """Authenticate the WebAuthn-only Trader process and its root config.

    Trader deliberately has no file-key activation row.  Its independently
    root-owned WebAuthn activation document is reopened by the handler factory;
    this layer pins the surrounding OS principal, caller group, config, store
    directory and outer event ledger before that factory can run.
    """

    try:
        deployment = manifest["principals"]["trader"]["deployments"][environment]
        account = pwd.getpwnam(deployment["service_user"])
        caller_group_name = f"qp_{environment}_trader_callers"
        caller_group = grp.getgrnam(caller_group_name)
    except (KeyError, TypeError) as exc:
        raise AuthorityRunnerError("declared Trader service identity is absent") from exc
    if (
        deployment.get("key_backend") != "webauthn_platform_or_hardware"
        or deployment.get("mode") != "PENDING_NO_KEY"
        or account.pw_uid <= 0
        or account.pw_dir != "/var/empty"
        or account.pw_shell != "/usr/bin/false"
        or account.pw_uid != os.geteuid()
        or caller_group.gr_gid != os.getegid()
    ):
        raise AuthorityRunnerError("Trader process does not match its isolated UID")
    service_dir = PROTECTED_ROOT / environment / "trader"
    try:
        directory = service_dir.lstat()
    except OSError as exc:
        raise AuthorityRunnerError("Trader protected service directory is absent") from exc
    if (
        not stat.S_ISDIR(directory.st_mode)
        or directory.st_uid != account.pw_uid
        or stat.S_IMODE(directory.st_mode) != 0o700
    ):
        raise AuthorityRunnerError("Trader protected service directory is unsafe")
    config = _load_root_runtime_config(
        PROTECTED_ROOT / "runtime-config" / environment / "trader.json",
        authority_id="trader",
        environment=environment,
    )
    _require_execution_activation_path(
        authority_id="trader", resources=config["resources"]
    )
    return (
        account.pw_uid,
        config,
        service_dir,
        service_dir / "authority-events.sqlite3",
    )


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
    manifest = load_and_validate_manifest()
    if authority_id == "trader":
        uid, config, service_dir, ledger_path = _require_trader_service_identity(
            environment=environment,
            manifest=manifest,
        )
        activation = None
        metadata = None
        custody = None
    else:
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
        service_dir = Path(activation["key_path"]).parent
        ledger_path = Path(activation["ledger_path"])
    resources = config["resources"]
    ledger = SQLiteAuthorityEventLedger(
        ledger_path,
        authority_id=authority_id,
        environment=environment,
        expected_uid=uid,
    )
    ledger.initialize()

    def service_uid(principal_id: str) -> int:
        deployment = manifest["principals"][principal_id]["deployments"][environment]
        try:
            return pwd.getpwnam(deployment["service_user"]).pw_uid
        except KeyError as exc:
            raise AuthorityRunnerError(
                f"declared {principal_id} service user is absent"
            ) from exc

    if authority_id == "d1_sync":
        assert activation is not None and custody is not None
        handlers = {
            D1SyncNow.operation: D1SyncNow(
                environment=environment,
                governed_db_path=resources["governed_db_path"],
                cloudflare_token_path=resources["cloudflare_token_path"],
                node_executable_path=resources["node_executable_path"],
                wrangler_cli_path=resources["wrangler_cli_path"],
                wrangler_cli_tree_path=resources["wrangler_cli_tree_path"],
                wrangler_config_path=resources["wrangler_config_path"],
                wrangler_lock_path=resources["wrangler_lock_path"],
                custody=custody,
                expected_uid=uid,
                source_sha=activation["runtime_bundle_digest"],
                tool_digest=_d1_sync_tool_bindings_digest(
                    activation["runtime_resource_bindings"]
                ),
                event_ledger=ledger,
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
        assert custody is not None
        handlers = {
            OpsProjectionRenderAndSign.operation: OpsProjectionRenderAndSign(
                environment=environment,
                custody=custody,
                artifact_store=resources["artifact_store"],
                expected_d1_uid=service_uid("d1_sync"),
            )
        }
    elif authority_id == "coverage_transition":
        assert custody is not None
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
        assert custody is not None
        handlers = {
            ReadyPublishProfilePlanBound.operation: ReadyPublishProfilePlanBound(
                environment=environment,
                snapshot_root=resources["snapshot_root"],
                custody=custody,
            )
        }
    elif authority_id == "trader":
        _require_execution_activation_path(
            authority_id=authority_id,
            resources=resources,
        )
        try:
            handler = open_live_trader_authority_handler_v2()
        except ExactFourAuthorityPending as exc:
            raise LocalAuthorityPending(
                "Trader WebAuthn activation is PENDING"
            ) from exc
        except Exception as exc:  # noqa: BLE001 - startup exposes only this class
            raise AuthorityRunnerError(
                "Trader WebAuthn activation validation failed"
            ) from exc
        controlled_uid = service_uid("controlled_execution")
        expected_socket = Path(
            manifest["principals"]["controlled_execution"]["deployments"]
            [environment]["socket_path"]
        )
        if (
            handler.authority.environment != environment
            or handler.controlled_execution_uid != controlled_uid
            or handler.controlled_socket_path != expected_socket
            or handler.authority.ledger._path.parent.resolve()
            != service_dir.resolve()
        ):
            raise AuthorityRunnerError(
                "Trader activation is not bound to the declared peer and store"
            )
        handlers = {TRADER_AUTHORIZE_OPERATION: handler}
    elif authority_id == "controlled_execution":
        assert activation is not None and metadata is not None and custody is not None
        _require_execution_activation_path(
            authority_id=authority_id,
            resources=resources,
        )
        try:
            handler = open_live_controlled_execution_handler_v2()
        except ExactFourAuthorityPending as exc:
            raise LocalAuthorityPending(
                "Controlled execution activation is PENDING"
            ) from exc
        except Exception as exc:  # noqa: BLE001 - startup exposes only this class
            raise AuthorityRunnerError(
                "Controlled execution activation validation failed"
            ) from exc
        writer = handler.writer
        writer_public = base64.b64encode(
            writer.public_key.public_bytes(
                encoding=serialization.Encoding.Raw,
                format=serialization.PublicFormat.Raw,
            )
        ).decode("ascii")
        if (
            writer.environment != environment
            or writer._trader_uid != service_uid("trader")
            or writer._signer.key_id != metadata["key_id"]
            or writer_public != metadata["public_key_base64"]
            or writer._path.parent.resolve() != service_dir.resolve()
        ):
            raise AuthorityRunnerError(
                "Controlled activation is not bound to its UID, peer, store, and key"
            )
        handlers = {CONTROLLED_TRADER_HANDOFF_OPERATION: handler}
    else:  # validated by load_runtime_config; defensive for future manifest rows
        raise AuthorityRunnerError("authority has no reviewed local handler set")
    return UnixAuthorityService(
        authority_id=authority_id,
        environment=environment,
        peers=PeerPrincipalRegistry.from_usernames(config["peer_callers"]),
        ledger=ledger,
        handlers=handlers,
        processing_timeout_seconds=_processing_timeout_seconds(authority_id),
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
    parser.add_argument(
        "--staged-canary-preflight",
        action="store_true",
        help=(
            "run only the root-orchestrated research-ineligible inactive "
            "preflight; never serve a product operation"
        ),
    )
    args = parser.parse_args(argv)
    if args.staged_canary_preflight:
        from scripts.local_authority_staged_canary import runner_main

        return runner_main(
            authority_id=args.authority,
            environment=args.environment,
        )
    try:
        serve_forever(authority_id=args.authority, environment=args.environment)
    except (AuthorityRunnerError, LocalAuthorityError, FindingLedgerError) as exc:
        print(
            f"local authority startup rejected: {type(exc).__name__}", file=sys.stderr
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
