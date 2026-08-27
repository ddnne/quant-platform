"""Root-orchestrated, research-ineligible local-authority startup canaries.

This module is deliberately not a second release gate.  It can execute exactly
one code-pinned inactive preflight for one of the six local OS principals and
write the result only to a canonical root-owned journal.  It cannot activate a
registry, write the normal activation state, call a product handler, publish
READY, issue a COMPLETE receipt, or authorize Controlled execution.

The public CLI exposes only ``plan``, ``audit`` and the atomic ``run`` workflow.
There is no public permit/mint/claim/complete API and no path, owner, action,
source-SHA, resource-digest, or evidence-digest argument.
"""

from __future__ import annotations

import base64
import grp
import hashlib
import json
import os
import pwd
import re
import stat
import sys
import time
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import MappingProxyType
from typing import Any, NoReturn

from cryptography.hazmat.primitives import serialization

from scripts.authority_principal_manifest import (
    LOCAL_OS_PRINCIPALS,
    PINNED_MANIFEST_DIGEST,
    load_and_validate_manifest,
)
from scripts.finding_ledger_gate import load_pinned_finding_ledger
from scripts.local_authority_activation import (
    canonical_json_bytes,
    observe_runtime_resource_bindings,
    regular_file_digest,
    stat_observation,
)
from scripts.local_authority_bootstrap_common import (
    RUNTIME_BUNDLE_MANIFEST_PATH,
    SERVICE_GROUP,
    BootstrapError,
    _deployments,
)
from scripts.local_authority_files import (
    ProtectedAuthorityFileError,
    read_protected_authority_file,
)
from scripts.local_authority_provisioning import (
    _load_public_metadata,
    _runtime_config_template,
)
from scripts.local_authority_runtime_bundle import _load_runtime_bundle_manifest
from scripts.local_authority_service import (
    FileEd25519KeyCustody,
    LocalAuthorityError,
    SQLiteAuthorityEventLedger,
)

ROOT = Path(__file__).resolve().parents[1]
POLICY_PATH = (
    ROOT / "specs" / "authorities" / "local-authority-staged-canary-policy.json"
)
POLICY_DIGEST = (
    "sha256:8d275d22d6aa7dc77441c37ec30c7e21b0c15b2944ac7559cb0d42d1b1c4fcfa"
)
POLICY_FORMAT = "local-authority-staged-canary-policy/v1"
CHALLENGE_FORMAT = "local-authority-staged-canary-challenge/v1"
CANARY_FORMAT = "local-authority-staged-canary-evidence/v1"
JOURNAL_FORMAT = "local-authority-staged-canary-journal/v1"
CLASSIFICATION = "CANARY_NOT_RESEARCH_ELIGIBLE"
CANONICAL_STATE_ROOT = Path(
    "/Library/Application Support/quant-platform/authorities/staged-canary"
)
CANONICAL_JOURNAL_PATH = CANONICAL_STATE_ROOT / "journal.sqlite3"
LEASE_SECONDS = 120
MAXIMUM_ATTEMPTS = 3
MAX_CANARY_BYTES = 1024 * 1024
STRICT_BOUNDARIES = MappingProxyType(
    {
        "release": False,
        "ready_publication": False,
        "receipt_complete": False,
        "controlled_pilot": False,
        "mass_research": False,
    }
)

_SOURCE_SHA_RE = re.compile(r"[0-9a-f]{40}\Z")
_DIGEST_RE = re.compile(r"sha256:[0-9a-f]{64}\Z")
_NONCE_RE = re.compile(r"[0-9a-f]{64}\Z")
_POLICY_TOP_FIELDS = {
    "schema_version",
    "classification",
    "scope",
    "principal_manifest_digest",
    "state_root",
    "journal_path",
    "source_sha_binding",
    "lease_seconds",
    "maximum_attempts",
    "strict_boundaries",
    "authorities",
    "excluded_authorities",
}
_SOURCE_BINDING_FIELDS = {
    "manifest_path",
    "manifest_format",
    "field",
    "required_owner_uid",
}
_ACTION_FIELDS = {
    "authority_id",
    "action",
    "environments",
    "proof_kind",
    "resource_roles",
}
_EXCLUDED_FIELDS = {"authority_id", "reason"}
_CHALLENGE_FIELDS = {
    "format",
    "classification",
    "authority_id",
    "environment",
    "action",
    "proof_kind",
    "source_sha",
    "runtime_bundle_digest",
    "policy_digest",
    "principal_manifest_digest",
    "finding_ledger_digest",
    "open_p0_ids",
    "resource_digest",
    "nonce",
    "issued_at",
    "expires_at",
    "deadline_monotonic_ns",
    "strict_boundaries",
}
_CANARY_BODY_FIELDS = {
    "format",
    "classification",
    "research_eligible",
    "authority_id",
    "environment",
    "action",
    "proof_kind",
    "source_sha",
    "runtime_bundle_digest",
    "policy_digest",
    "principal_manifest_digest",
    "finding_ledger_digest",
    "open_p0_ids",
    "resource_digest",
    "challenge_digest",
    "nonce",
    "observed_at",
    "strict_boundaries",
    "issuer_key_id",
    "issuer_public_key_base64",
}
_CANARY_FIELDS = _CANARY_BODY_FIELDS | {"signature", "canary_digest"}

_EXPECTED_ACTIONS = MappingProxyType(
    {
        "d1_sync": (
            "d1_sync:inactive_signing_preflight",
            "ED25519_PROTECTED_KEY_PREFLIGHT",
            (
                "service_identity",
                "runtime_bundle_source_sha",
                "runtime_config",
                "protected_signing_key_public_identity",
                "authority_event_ledger",
                "governed_db",
                "cloudflare_token_metadata_only",
                "node_executable",
                "wrangler_cli",
                "wrangler_cli_tree",
                "wrangler_config",
                "wrangler_lock",
            ),
        ),
        "ops_projection": (
            "ops_projection:inactive_signing_preflight",
            "ED25519_PROTECTED_KEY_PREFLIGHT",
            (
                "service_identity",
                "runtime_bundle_source_sha",
                "runtime_config",
                "protected_signing_key_public_identity",
                "authority_event_ledger",
                "artifact_store",
            ),
        ),
        "coverage_transition": (
            "coverage_transition:inactive_signing_preflight",
            "ED25519_PROTECTED_KEY_PREFLIGHT",
            (
                "service_identity",
                "runtime_bundle_source_sha",
                "runtime_config",
                "protected_signing_key_public_identity",
                "authority_event_ledger",
            ),
        ),
        "ready": (
            "ready:inactive_signing_preflight",
            "ED25519_PROTECTED_KEY_PREFLIGHT",
            (
                "service_identity",
                "runtime_bundle_source_sha",
                "runtime_config",
                "protected_signing_key_public_identity",
                "authority_event_ledger",
                "snapshot_root",
            ),
        ),
        "trader": (
            "trader:inactive_webauthn_registry_preflight",
            "ROOT_EXEC_EXACT_UID_WEBAUTHN_REGISTRY_PREFLIGHT",
            (
                "service_identity",
                "runtime_bundle_source_sha",
                "runtime_config",
                "authority_event_ledger",
                "root_owned_webauthn_activation",
                "trader_store",
                "controlled_execution_socket_identity",
            ),
        ),
        "controlled_execution": (
            "controlled_execution:inactive_signing_preflight",
            "ED25519_PROTECTED_KEY_PREFLIGHT",
            (
                "service_identity",
                "runtime_bundle_source_sha",
                "runtime_config",
                "protected_signing_key_public_identity",
                "authority_event_ledger",
                "root_owned_controlled_activation",
            ),
        ),
    }
)


class StagedCanaryError(RuntimeError):
    """The staged local-authority canary contract failed closed."""


def _reject_constant(value: str) -> NoReturn:
    raise StagedCanaryError(f"staged canary JSON contains {value!r}")


def _reject_duplicates(pairs: Iterable[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise StagedCanaryError(
                f"staged canary JSON contains duplicate key {key!r}"
            )
        result[key] = value
    return result


def _strict_json(raw: bytes, *, label: str) -> dict[str, Any]:
    try:
        value = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_reject_duplicates,
            parse_float=_reject_constant,
            parse_constant=_reject_constant,
        )
    except StagedCanaryError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError) as exc:
        raise StagedCanaryError(f"{label} is not strict UTF-8 JSON") from exc
    if type(value) is not dict:
        raise StagedCanaryError(f"{label} must be one exact object")
    return value


def _exact(value: object, fields: set[str], *, label: str) -> dict[str, Any]:
    if type(value) is not dict or set(value) != fields:
        observed = set(value) if type(value) is dict else set()
        raise StagedCanaryError(
            f"{label} schema drift: missing={sorted(fields - observed)}, "
            f"extra={sorted(observed - fields)}"
        )
    return value


def _digest(raw: bytes | Mapping[str, Any]) -> str:
    encoded = raw if type(raw) is bytes else canonical_json_bytes(dict(raw))
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _require_digest(value: object, *, label: str) -> str:
    if type(value) is not str or _DIGEST_RE.fullmatch(value) is None:
        raise StagedCanaryError(f"{label} is not one canonical sha256 digest")
    return value


def _parse_time(value: object, *, label: str) -> datetime:
    if type(value) is not str:
        raise StagedCanaryError(f"{label} must be an RFC3339 timestamp")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise StagedCanaryError(f"{label} must be an RFC3339 timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise StagedCanaryError(f"{label} must include an explicit timezone")
    return parsed.astimezone(UTC)


@dataclass(frozen=True, slots=True)
class CanaryAction:
    authority_id: str
    action: str
    proof_kind: str
    resource_roles: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class CanaryPolicy:
    digest: str
    actions: Mapping[str, CanaryAction]


def _evaluate_policy_bytes(raw: bytes) -> CanaryPolicy:
    if _digest(raw) != POLICY_DIGEST:
        raise StagedCanaryError("staged canary policy digest is not code-pinned")
    document = _exact(
        _strict_json(raw, label="staged canary policy"),
        _POLICY_TOP_FIELDS,
        label="staged canary policy",
    )
    if (
        document["schema_version"] != POLICY_FORMAT
        or document["classification"] != CLASSIFICATION
        or document["scope"] != "LOCAL_OS_AUTHORITIES_ONLY"
        or document["principal_manifest_digest"] != PINNED_MANIFEST_DIGEST
        or document["state_root"] != str(CANONICAL_STATE_ROOT)
        or document["journal_path"] != str(CANONICAL_JOURNAL_PATH)
        or document["lease_seconds"] != LEASE_SECONDS
        or document["maximum_attempts"] != MAXIMUM_ATTEMPTS
        or document["strict_boundaries"] != dict(STRICT_BOUNDARIES)
    ):
        raise StagedCanaryError("staged canary policy constants drifted")
    source = _exact(
        document["source_sha_binding"],
        _SOURCE_BINDING_FIELDS,
        label="staged canary source binding",
    )
    if source != {
        "manifest_path": str(RUNTIME_BUNDLE_MANIFEST_PATH),
        "manifest_format": "local-authority-runtime-bundle/v1",
        "field": "source_sha",
        "required_owner_uid": 0,
    }:
        raise StagedCanaryError("staged canary source binding drifted")
    rows = document["authorities"]
    if type(rows) is not list:
        raise StagedCanaryError("staged canary authorities must be an array")
    actions: dict[str, CanaryAction] = {}
    for index, raw_row in enumerate(rows):
        row = _exact(
            raw_row,
            _ACTION_FIELDS,
            label=f"staged canary authorities[{index}]",
        )
        authority_id = row["authority_id"]
        expected = _EXPECTED_ACTIONS.get(authority_id)
        if (
            expected is None
            or authority_id in actions
            or row["action"] != expected[0]
            or row["environments"] != ["staging", "production"]
            or row["proof_kind"] != expected[1]
            or row["resource_roles"] != list(expected[2])
        ):
            raise StagedCanaryError("staged canary authority action drifted")
        actions[authority_id] = CanaryAction(
            authority_id=authority_id,
            action=expected[0],
            proof_kind=expected[1],
            resource_roles=expected[2],
        )
    if set(actions) != set(LOCAL_OS_PRINCIPALS) or set(actions) != set(
        _EXPECTED_ACTIONS
    ):
        raise StagedCanaryError("staged canary local authority inventory drifted")
    excluded = document["excluded_authorities"]
    if type(excluded) is not list or len(excluded) != 1:
        raise StagedCanaryError("staged canary exclusion inventory drifted")
    receipt = _exact(
        excluded[0], _EXCLUDED_FIELDS, label="staged canary excluded receipt"
    )
    if (
        receipt["authority_id"] != "receipt"
        or "Service Binding" not in receipt["reason"]
        or "caller-supplied evidence is forbidden" not in receipt["reason"]
    ):
        raise StagedCanaryError("Receipt exclusion rationale drifted")
    return CanaryPolicy(digest=POLICY_DIGEST, actions=MappingProxyType(actions))


def load_policy() -> CanaryPolicy:
    """Load only the repository-pinned policy; callers cannot select a path."""

    try:
        raw = POLICY_PATH.read_bytes()
    except OSError as exc:
        raise StagedCanaryError("staged canary policy is unavailable") from exc
    return _evaluate_policy_bytes(raw)


def _runtime_binding() -> dict[str, Any]:
    try:
        binding = _load_runtime_bundle_manifest()
    except BootstrapError as exc:
        raise StagedCanaryError(
            "root-owned exact-source runtime bundle is unavailable"
        ) from exc
    source_sha = binding.get("source_sha")
    entrypoint = Path(binding.get("entrypoint_path", ""))
    if (
        type(source_sha) is not str
        or _SOURCE_SHA_RE.fullmatch(source_sha) is None
        or entrypoint
        != Path(binding["bundle_path"]) / "scripts" / "run_local_authority.py"
        or regular_file_digest(entrypoint) != binding["entrypoint_digest"]
    ):
        raise StagedCanaryError(
            "runtime bundle source or entrypoint binding is invalid"
        )
    return binding


def _safe_observation(
    path: Path,
    *,
    label: str,
    owner_uids: set[int],
    kinds: set[str],
    allowed_modes: set[int] | None = None,
    include_digest: bool,
) -> dict[str, Any]:
    try:
        info = path.lstat()
    except OSError as exc:
        raise StagedCanaryError(f"{label} is unavailable") from exc
    kind = (
        "file"
        if stat.S_ISREG(info.st_mode)
        else "directory"
        if stat.S_ISDIR(info.st_mode)
        else "socket"
        if stat.S_ISSOCK(info.st_mode)
        else "other"
    )
    mode = stat.S_IMODE(info.st_mode)
    if (
        kind not in kinds
        or info.st_uid not in owner_uids
        or mode & 0o002
        or kind == "file"
        and info.st_nlink != 1
        or allowed_modes is not None
        and mode not in allowed_modes
    ):
        raise StagedCanaryError(f"{label} metadata is unsafe")
    digest = regular_file_digest(path) if include_digest and kind == "file" else None
    return {
        "path": str(path),
        "kind": kind,
        "digest": digest,
        "observation": stat_observation(info),
    }


def _deployment(authority_id: str, environment: str) -> dict[str, Any]:
    if authority_id not in LOCAL_OS_PRINCIPALS or environment not in {
        "staging",
        "production",
    }:
        raise StagedCanaryError("staged canary identity is not declared")
    matches = [
        row for row in _deployments(environment) if row["authority_id"] == authority_id
    ]
    if len(matches) != 1:
        raise StagedCanaryError("staged canary deployment is not unique")
    manifest = load_and_validate_manifest()
    principal = manifest["principals"].get(authority_id)
    declared = principal.get("deployments", {}).get(environment) if principal else None
    if (
        type(principal) is not dict
        or principal.get("runtime") != "local_os_service"
        or type(declared) is not dict
        or declared.get("mode") != "PENDING_NO_KEY"
    ):
        raise StagedCanaryError("staged canary principal is not PENDING local OS")
    return matches[0]


def _observe_runtime_resources(
    *,
    authority_id: str,
    resources: Mapping[str, Any],
    service_uid: int,
) -> list[dict[str, Any]]:
    observed: list[dict[str, Any]] = []
    if authority_id == "d1_sync":
        pinned = observe_runtime_resource_bindings(
            authority_id=authority_id,
            resources=resources,
            expected_owner_uid=0,
        )
        pinned_by_name = {row["name"]: row for row in pinned}
        observed.extend(pinned)
        observed.append(
            {
                "name": "governed_db_path",
                "sensitivity": "MUTABLE_GOVERNED_DATA_METADATA_ONLY",
                **_safe_observation(
                    Path(resources["governed_db_path"]),
                    label="governed D1 mirror",
                    owner_uids={service_uid},
                    kinds={"file"},
                    allowed_modes={0o600},
                    include_digest=False,
                ),
            }
        )
        observed.append(
            {
                "name": "cloudflare_token_path",
                "sensitivity": "SECRET_METADATA_ONLY",
                **_safe_observation(
                    Path(resources["cloudflare_token_path"]),
                    label="Cloudflare token",
                    owner_uids={service_uid},
                    kinds={"file"},
                    allowed_modes={0o400},
                    include_digest=False,
                ),
            }
        )
        if set(pinned_by_name) != {
            "node_executable_path",
            "wrangler_cli_path",
            "wrangler_cli_tree_path",
            "wrangler_config_path",
            "wrangler_lock_path",
        }:
            raise StagedCanaryError("D1 runtime resource inventory drifted")
    elif authority_id == "ops_projection":
        observed.append(
            {
                "name": "artifact_store",
                "sensitivity": "MUTABLE_AUTHORITY_STORE_METADATA_ONLY",
                **_safe_observation(
                    Path(resources["artifact_store"]),
                    label="Ops projection artifact store",
                    owner_uids={service_uid},
                    kinds={"directory"},
                    allowed_modes={0o700},
                    include_digest=False,
                ),
            }
        )
    elif authority_id == "ready":
        observed.append(
            {
                "name": "snapshot_root",
                "sensitivity": "IMMUTABLE_INPUT_ROOT_METADATA_ONLY",
                **_safe_observation(
                    Path(resources["snapshot_root"]),
                    label="READY snapshot root",
                    owner_uids={0, service_uid},
                    kinds={"directory"},
                    allowed_modes={0o500, 0o550, 0o555, 0o700, 0o750, 0o755},
                    include_digest=False,
                ),
            }
        )
    elif authority_id in {"trader", "controlled_execution"}:
        observed.append(
            {
                "name": "activation_document_path",
                "sensitivity": "ROOT_OWNED_ACTIVATION_DOCUMENT",
                **_safe_observation(
                    Path(resources["activation_document_path"]),
                    label=f"{authority_id} activation document",
                    owner_uids={0},
                    kinds={"file"},
                    allowed_modes={0o400, 0o440, 0o444, 0o600, 0o640, 0o644},
                    include_digest=True,
                ),
            }
        )
    elif authority_id != "coverage_transition":
        raise StagedCanaryError("authority has no reviewed resource observer")
    return sorted(observed, key=lambda row: row["name"])


def observe_preflight_resources(
    *, authority_id: str, environment: str
) -> Mapping[str, Any]:
    """Remeasure all governed resources from fixed manifests and canonical paths."""

    policy = load_policy()
    action = policy.actions.get(authority_id)
    if action is None:
        raise StagedCanaryError("authority has no staged canary action")
    row = _deployment(authority_id, environment)
    binding = _runtime_binding()
    try:
        account = pwd.getpwnam(row["service_user"])
        service_group = grp.getgrnam(SERVICE_GROUP)
        caller_group = grp.getgrnam(row["caller_group"])
    except KeyError as exc:
        raise StagedCanaryError(
            "authority service UID/groups are not provisioned"
        ) from exc
    if (
        account.pw_uid <= 0
        or account.pw_gid != service_group.gr_gid
        or caller_group.gr_gid in {0, service_group.gr_gid}
        or account.pw_dir != "/var/empty"
        or account.pw_shell != "/usr/bin/false"
        or os.geteuid() not in {0, account.pw_uid}
        or os.geteuid() == account.pw_uid
        and os.getegid() != caller_group.gr_gid
    ):
        raise StagedCanaryError("authority process/service identity is unsafe")
    service_dir = _safe_observation(
        Path(row["service_dir"]),
        label="authority service directory",
        owner_uids={account.pw_uid},
        kinds={"directory"},
        allowed_modes={0o700},
        include_digest=False,
    )
    config_path = Path(row["runtime_config_path"])
    try:
        config_raw = read_protected_authority_file(
            config_path,
            expected_owner_uids={0},
            allowed_modes={0o440, 0o444},
            max_bytes=1024 * 1024,
        ).raw
    except ProtectedAuthorityFileError as exc:
        raise StagedCanaryError("root-owned runtime config is unavailable") from exc
    from scripts.run_local_authority import decode_runtime_config

    try:
        config = decode_runtime_config(
            config_raw,
            authority_id=authority_id,
            environment=environment,
        )
    except Exception as exc:  # closed runner exception surface
        raise StagedCanaryError("runtime config failed closed validation") from exc
    expected_peers = _runtime_config_template(row)["peer_callers"]
    if config["peer_callers"] != expected_peers:
        raise StagedCanaryError("runtime config peer identities are not exact")
    peer_uids: set[int] = set()
    for peer_user in sorted(expected_peers):
        try:
            peer = pwd.getpwnam(peer_user)
        except KeyError as exc:
            raise StagedCanaryError("runtime peer UID is not provisioned") from exc
        if (
            peer.pw_uid in {0, account.pw_uid}
            or peer.pw_uid in peer_uids
            or peer.pw_dir != "/var/empty"
            or peer.pw_shell != "/usr/bin/false"
        ):
            raise StagedCanaryError("runtime peer identity is not isolated")
        peer_uids.add(peer.pw_uid)
    ledger = SQLiteAuthorityEventLedger(
        row["ledger_path"],
        authority_id=authority_id,
        environment=environment,
        expected_uid=account.pw_uid,
    )
    try:
        ledger_audit = dict(ledger.audit_read_only())
    except LocalAuthorityError as exc:
        raise StagedCanaryError("authority event ledger preflight failed") from exc
    key: dict[str, Any] | None = None
    if row["key_backend"] == "protected_local_key":
        try:
            metadata = _load_public_metadata(row, expected_uid=account.pw_uid)
        except BootstrapError as exc:
            raise StagedCanaryError("authority public metadata is unavailable") from exc
        key_path = Path(row["key_path"])
        key = {
            "key_id": metadata["key_id"],
            "public_key_base64": metadata["public_key_base64"],
            "public_key_sha256": metadata["public_key_sha256"],
            "public_metadata_digest": regular_file_digest(
                Path(row["public_metadata_path"])
            ),
            "key_observation": _safe_observation(
                key_path,
                label="protected authority key",
                owner_uids={account.pw_uid},
                kinds={"file"},
                allowed_modes={0o400, 0o600},
                include_digest=False,
            )["observation"],
        }
        if os.geteuid() == account.pw_uid:
            custody = FileEd25519KeyCustody(
                key_path,
                key_id=metadata["key_id"],
                expected_uid=account.pw_uid,
            )
            if custody.public_key_base64() != metadata["public_key_base64"]:
                raise StagedCanaryError(
                    "protected authority key differs from public metadata"
                )
    elif authority_id != "trader":
        raise StagedCanaryError("unexpected non-file local signing backend")
    resources = _observe_runtime_resources(
        authority_id=authority_id,
        resources=config["resources"],
        service_uid=account.pw_uid,
    )
    snapshot = {
        "format": "local-authority-staged-canary-resources/v1",
        "authority_id": authority_id,
        "environment": environment,
        "action": action.action,
        "resource_roles": list(action.resource_roles),
        "principal_manifest_digest": PINNED_MANIFEST_DIGEST,
        "source_sha": binding["source_sha"],
        "runtime_bundle_digest": binding["bundle_digest"],
        "runtime_entrypoint_digest": binding["entrypoint_digest"],
        "runtime_python_digest": binding["python_digest"],
        "service_identity": {
            "service_user": row["service_user"],
            "uid": account.pw_uid,
            "gid": account.pw_gid,
            "service_group": SERVICE_GROUP,
            "service_group_gid": service_group.gr_gid,
            "caller_group": row["caller_group"],
            "caller_group_gid": caller_group.gr_gid,
            "peer_uids": sorted(peer_uids),
            "home": account.pw_dir,
            "shell": account.pw_shell,
            "service_directory": service_dir,
        },
        "runtime_config": {
            "path": str(config_path),
            "digest": _digest(config_raw),
            "observation": stat_observation(config_path.lstat()),
        },
        "key": key,
        "event_ledger": {
            "path": row["ledger_path"],
            **ledger_audit,
            "observation": stat_observation(Path(row["ledger_path"]).lstat()),
        },
        "runtime_resources": resources,
    }
    return MappingProxyType(
        {
            **snapshot,
            "resource_digest": _digest(snapshot),
        }
    )


def _validate_challenge(
    challenge: Mapping[str, Any],
    *,
    policy: CanaryPolicy,
    action: CanaryAction,
    binding: Mapping[str, Any],
    resource_digest: str,
) -> dict[str, Any]:
    value = _exact(dict(challenge), _CHALLENGE_FIELDS, label="canary challenge")
    if (
        value["format"] != CHALLENGE_FORMAT
        or value["classification"] != CLASSIFICATION
        or value["authority_id"] != action.authority_id
        or value["environment"] not in {"staging", "production"}
        or value["action"] != action.action
        or value["proof_kind"] != action.proof_kind
        or value["source_sha"] != binding["source_sha"]
        or value["runtime_bundle_digest"] != binding["bundle_digest"]
        or value["policy_digest"] != policy.digest
        or value["principal_manifest_digest"] != PINNED_MANIFEST_DIGEST
        or value["resource_digest"] != resource_digest
        or value["strict_boundaries"] != dict(STRICT_BOUNDARIES)
        or type(value["deadline_monotonic_ns"]) is not int
        or value["deadline_monotonic_ns"] <= 0
        or type(value["open_p0_ids"]) is not list
        or not value["open_p0_ids"]
        or "A2" not in value["open_p0_ids"]
        or type(value["nonce"]) is not str
        or _NONCE_RE.fullmatch(value["nonce"]) is None
    ):
        raise StagedCanaryError("canary challenge is not exactly governed")
    _require_digest(value["finding_ledger_digest"], label="finding ledger digest")
    issued = _parse_time(value["issued_at"], label="challenge issued_at")
    expires = _parse_time(value["expires_at"], label="challenge expires_at")
    if expires <= issued or expires - issued > timedelta(seconds=LEASE_SECONDS + 1):
        raise StagedCanaryError("canary challenge wall-clock lease is invalid")
    ledger = load_pinned_finding_ledger()
    if (
        ledger.digest != value["finding_ledger_digest"]
        or list(ledger.open_p0_ids) != value["open_p0_ids"]
        or ledger.release_allowed
        or "A2" not in ledger.open_p0_ids
    ):
        raise StagedCanaryError("canary challenge finding ledger is stale")
    if time.monotonic_ns() >= value["deadline_monotonic_ns"]:
        raise StagedCanaryError("canary challenge monotonic deadline expired")
    return value


def run_exact_inactive_preflight(
    challenge_raw: bytes,
    *,
    expected_authority_id: str,
    expected_environment: str,
) -> Mapping[str, Any]:
    """Authority-UID runner; invoked only from the protected runtime bundle.

    The function accepts only a server-generated challenge.  It derives its
    authority/environment/action/resource identity from that closed challenge
    and independently remeasures the same fixed manifests and paths.  It has no
    facility for a caller to supply counts, digests, stores, owners, or paths.
    """

    if (
        type(challenge_raw) is not bytes
        or not challenge_raw
        or len(challenge_raw) > MAX_CANARY_BYTES
    ):
        raise StagedCanaryError("canary challenge byte length is invalid")
    challenge = _strict_json(challenge_raw, label="canary challenge")
    authority_id = challenge.get("authority_id")
    environment = challenge.get("environment")
    if (
        type(authority_id) is not str
        or type(environment) is not str
        or authority_id != expected_authority_id
        or environment != expected_environment
    ):
        raise StagedCanaryError("canary challenge identity is absent")
    policy = load_policy()
    action = policy.actions.get(authority_id)
    if action is None:
        raise StagedCanaryError("canary authority has no exact action")
    binding = _runtime_binding()
    if Path(__file__).resolve() != Path(binding["bundle_path"]) / "scripts" / (
        "local_authority_staged_canary.py"
    ):
        raise StagedCanaryError(
            "canary runner is not executing from the protected runtime bundle"
        )
    resources = observe_preflight_resources(
        authority_id=authority_id,
        environment=environment,
    )
    validated = _validate_challenge(
        challenge,
        policy=policy,
        action=action,
        binding=binding,
        resource_digest=resources["resource_digest"],
    )
    observed_at = datetime.now(UTC).isoformat(timespec="microseconds")
    issuer_key_id: str | None = None
    issuer_public_key_base64: str | None = None
    signature: str | None = None
    if action.proof_kind == "ED25519_PROTECTED_KEY_PREFLIGHT":
        key = resources["key"]
        if type(key) is not dict:
            raise StagedCanaryError("file-backed canary has no observed key")
        issuer_key_id = key["key_id"]
        issuer_public_key_base64 = key["public_key_base64"]
        if authority_id == "controlled_execution":
            from execution.controlled_execution_activation_v2 import (
                open_live_controlled_execution_writer_v2,
            )

            try:
                writer = open_live_controlled_execution_writer_v2()
                writer_public = base64.b64encode(
                    writer.public_key.public_bytes(
                        serialization.Encoding.Raw,
                        serialization.PublicFormat.Raw,
                    )
                ).decode("ascii")
            except Exception as exc:  # never expose activation/store details
                raise StagedCanaryError(
                    "Controlled inactive writer preflight failed"
                ) from exc
            if (
                writer.environment != environment
                or writer_public != issuer_public_key_base64
                or writer._signer.key_id != issuer_key_id
            ):
                raise StagedCanaryError(
                    "Controlled activation differs from bootstrap key identity"
                )
    elif action.proof_kind == "ROOT_EXEC_EXACT_UID_WEBAUTHN_REGISTRY_PREFLIGHT":
        from execution.trader_webauthn_activation_v2 import (
            open_live_exact_four_trader_authority_v2,
        )

        try:
            trader = open_live_exact_four_trader_authority_v2()
        except Exception as exc:  # never expose credential/activation details
            raise StagedCanaryError(
                "Trader inactive registry preflight failed"
            ) from exc
        if trader.environment != environment:
            raise StagedCanaryError("Trader preflight environment drifted")
    else:  # code-pinned closed set
        raise StagedCanaryError("canary proof kind is unsupported")
    body = {
        "format": CANARY_FORMAT,
        "classification": CLASSIFICATION,
        "research_eligible": False,
        "authority_id": authority_id,
        "environment": environment,
        "action": action.action,
        "proof_kind": action.proof_kind,
        "source_sha": binding["source_sha"],
        "runtime_bundle_digest": binding["bundle_digest"],
        "policy_digest": policy.digest,
        "principal_manifest_digest": PINNED_MANIFEST_DIGEST,
        "finding_ledger_digest": validated["finding_ledger_digest"],
        "open_p0_ids": list(validated["open_p0_ids"]),
        "resource_digest": resources["resource_digest"],
        "challenge_digest": _digest(canonical_json_bytes(validated)),
        "nonce": validated["nonce"],
        "observed_at": observed_at,
        "strict_boundaries": dict(STRICT_BOUNDARIES),
        "issuer_key_id": issuer_key_id,
        "issuer_public_key_base64": issuer_public_key_base64,
    }
    if action.proof_kind == "ED25519_PROTECTED_KEY_PREFLIGHT":
        row = _deployment(authority_id, environment)
        custody = FileEd25519KeyCustody(
            row["key_path"],
            key_id=issuer_key_id or "",
            expected_uid=os.geteuid(),
        )
        signature = custody.sign(canonical_json_bytes(body))
    if time.monotonic_ns() >= validated["deadline_monotonic_ns"]:
        raise StagedCanaryError("canary preflight crossed its monotonic deadline")
    evidence = {**body, "signature": signature}
    return MappingProxyType(
        {
            **evidence,
            "canary_digest": _digest(evidence),
        }
    )


def runner_main(*, authority_id: str, environment: str) -> int:
    """Read one challenge from stdin and emit one canonical canary or fail."""

    try:
        if sys.flags.isolated != 1:
            raise StagedCanaryError("inactive canary runner requires Python -I")
        raw = sys.stdin.buffer.read(MAX_CANARY_BYTES + 1)
        result = run_exact_inactive_preflight(
            raw,
            expected_authority_id=authority_id,
            expected_environment=environment,
        )
    except (StagedCanaryError, LocalAuthorityError, BootstrapError):
        print("inactive authority canary preflight rejected", file=sys.stderr)
        return 1
    sys.stdout.buffer.write(canonical_json_bytes(dict(result)) + b"\n")
    return 0
