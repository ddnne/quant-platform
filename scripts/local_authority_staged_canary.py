"""Root-orchestrated, research-ineligible local-authority startup canaries.

This module is deliberately not a second release gate. It can execute exactly
one code-pinned inactive preflight for one of five signed local OS principals
and return evidence only to the root manager, which may commit the canonical
journal. It cannot activate a registry, write the normal activation state, call
a product handler, publish READY, issue a COMPLETE receipt, or authorize
Controlled execution.

The public CLI exposes only ``plan``, ``audit`` and the atomic ``run`` workflow.
There is no public permit/mint/claim/complete API and no path, owner, action,
source-SHA, resource-digest, or evidence-digest argument.
"""

from __future__ import annotations

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
    "sha256:f904f24657bcd06ae37e5606e6a5395a06fda52a6e9ed0c7a2ebdc93c3120f65"
)
POLICY_FORMAT = "local-authority-staged-canary-policy/v1"
CHALLENGE_FORMAT = "local-authority-staged-canary-challenge/v1"
CANARY_FORMAT = "local-authority-staged-canary-evidence/v1"
JOURNAL_FORMAT = "local-authority-staged-canary-journal/v3"
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
    "attempt_family",
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
_CONTROLLED_ACTIVATION_FIELDS = {
    "format",
    "environment",
    "service_uid",
    "trader_uid",
    "store_path",
    "signer_key_id",
    "private_key_path",
    "budget_id",
    "budget_ledger_path",
    "immutable_snapshot_path",
    "signed_projection_path",
    "provider_socket_path",
    "provider_uid",
    "provider_timeout_seconds",
    "protected_store_observed",
    "protected_signing_key_observed",
    "rp_registry",
    "credential_registry",
}
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
    "protocol_digest",
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
                "controlled_store",
            ),
        ),
    }
)
_EXPECTED_PROTOCOL_OPERATIONS = MappingProxyType(
    {
        "d1_sync": (
            "d1_sync:sync_now",
            "d1_sync:freeze_and_render_ops_projection",
            "d1_sync:freeze_authorize_apply_coverage",
        ),
        "ops_projection": ("ops_projection:render_and_sign",),
        "coverage_transition": ("coverage_transition:authorize",),
        "ready": ("ready:publish_profile_plan_bound",),
        "controlled_execution": ("controlled_execution:consume_trader_handoff",),
    }
)


def _expected_protocol_descriptor(
    *, authority_id: str, environment: str
) -> Mapping[str, Any]:
    if authority_id not in _EXPECTED_PROTOCOL_OPERATIONS or environment not in {
        "staging",
        "production",
    }:
        raise StagedCanaryError("inactive protocol descriptor is not declared")
    return MappingProxyType(
        {
            "format": "local-authority-inactive-protocol-preflight/v1",
            "authority_id": authority_id,
            "environment": environment,
            "action": load_policy().actions[authority_id].action,
            "operations": list(_EXPECTED_PROTOCOL_OPERATIONS[authority_id]),
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
        or document["scope"] != "SIGNED_LOCAL_OS_AUTHORITIES_ONLY"
        or document["principal_manifest_digest"] != PINNED_MANIFEST_DIGEST
        or document["state_root"] != str(CANONICAL_STATE_ROOT)
        or document["journal_path"] != str(CANONICAL_JOURNAL_PATH)
        or document["lease_seconds"] != LEASE_SECONDS
        or document["maximum_attempts"] != MAXIMUM_ATTEMPTS
        or document["attempt_family"] != "AUTHORITY_ENVIRONMENT_ACTION_SOURCE_SHA"
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
    if set(actions) != set(_EXPECTED_ACTIONS):
        raise StagedCanaryError("staged canary local authority inventory drifted")
    excluded = document["excluded_authorities"]
    if type(excluded) is not list or len(excluded) != 2:
        raise StagedCanaryError("staged canary exclusion inventory drifted")
    excluded_by_authority: dict[str, dict[str, Any]] = {}
    for index, raw_exclusion in enumerate(excluded):
        exclusion = _exact(
            raw_exclusion,
            _EXCLUDED_FIELDS,
            label=f"staged canary exclusions[{index}]",
        )
        authority_id = exclusion.get("authority_id")
        if type(authority_id) is not str or authority_id in excluded_by_authority:
            raise StagedCanaryError("staged canary exclusion identity drifted")
        excluded_by_authority[authority_id] = exclusion
    receipt = excluded_by_authority.get("receipt")
    trader = excluded_by_authority.get("trader")
    if (
        receipt is None
        or receipt["authority_id"] != "receipt"
        or "Service Binding" not in receipt["reason"]
        or "caller-supplied evidence is forbidden" not in receipt["reason"]
        or trader is None
        or "Unsigned local WebAuthn preflight output" not in trader["reason"]
        or "authority-held attestation key" not in trader["reason"]
        or "caller-supplied evidence is forbidden" not in trader["reason"]
        or set(actions) | set(excluded_by_authority)
        != set(LOCAL_OS_PRINCIPALS) | {"receipt"}
    ):
        raise StagedCanaryError("staged canary exclusion rationale drifted")
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
    if not path.is_absolute() or ".." in path.parts:
        raise StagedCanaryError(f"{label} path is not canonical and absolute")
    permitted_owners = {0, *owner_uids}
    # Validate both the lexical chain (including root-owned compatibility
    # symlinks such as /etc on macOS) and the resolved chain.  No selected
    # resource may sit below an attacker-renamable directory.
    for lexical in reversed(path.parents):
        try:
            ancestor = lexical.lstat()
        except OSError as exc:
            raise StagedCanaryError(f"{label} ancestor is unavailable") from exc
        if stat.S_ISLNK(ancestor.st_mode):
            if ancestor.st_uid != 0:
                raise StagedCanaryError(f"{label} ancestor symlink is unsafe")
            continue
        if (
            not stat.S_ISDIR(ancestor.st_mode)
            or ancestor.st_uid not in permitted_owners
            or stat.S_IMODE(ancestor.st_mode) & 0o022
        ):
            raise StagedCanaryError(f"{label} ancestor is unsafe")
    try:
        lexical_target = path.lstat()
        if stat.S_ISLNK(lexical_target.st_mode) and lexical_target.st_uid != 0:
            raise StagedCanaryError(f"{label} target symlink is unsafe")
        resolved = path.resolve(strict=True)
    except OSError as exc:
        raise StagedCanaryError(f"{label} is unavailable") from exc
    for ancestor_path in reversed(resolved.parents):
        ancestor = ancestor_path.lstat()
        if (
            not stat.S_ISDIR(ancestor.st_mode)
            or ancestor.st_uid not in permitted_owners
            or stat.S_IMODE(ancestor.st_mode) & 0o022
        ):
            raise StagedCanaryError(f"{label} resolved ancestor is unsafe")
    info = resolved.lstat()
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
    digest: str | None = None
    if include_digest and kind == "file":
        flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
        try:
            descriptor = os.open(resolved, flags)
        except OSError as exc:
            raise StagedCanaryError(f"{label} cannot be opened safely") from exc
        try:
            before = os.fstat(descriptor)
            if (
                before.st_dev != info.st_dev
                or before.st_ino != info.st_ino
                or before.st_uid != info.st_uid
                or before.st_nlink != 1
            ):
                raise StagedCanaryError(f"{label} changed before observation")
            hasher = hashlib.sha256()
            while True:
                chunk = os.read(descriptor, 1024 * 1024)
                if not chunk:
                    break
                hasher.update(chunk)
            after = os.fstat(descriptor)
            stable = (
                before.st_dev,
                before.st_ino,
                before.st_size,
                before.st_mtime_ns,
                before.st_ctime_ns,
                before.st_nlink,
            ) == (
                after.st_dev,
                after.st_ino,
                after.st_size,
                after.st_mtime_ns,
                after.st_ctime_ns,
                after.st_nlink,
            )
            if not stable:
                raise StagedCanaryError(f"{label} changed during observation")
            digest = "sha256:" + hasher.hexdigest()
            info = after
        finally:
            os.close(descriptor)
    stable_fields = (
        "st_dev",
        "st_ino",
        "st_mode",
        "st_uid",
        "st_gid",
        "st_size",
        "st_mtime_ns",
        "st_ctime_ns",
        "st_nlink",
    )
    try:
        final_lexical_target = path.lstat()
        final_resolved = path.resolve(strict=True)
        final_info = final_resolved.lstat()
    except OSError as exc:
        raise StagedCanaryError(f"{label} changed after observation") from exc
    if (
        final_resolved != resolved
        or any(
            getattr(final_lexical_target, field) != getattr(lexical_target, field)
            for field in stable_fields
        )
        or any(
            getattr(final_info, field) != getattr(info, field)
            for field in stable_fields
        )
    ):
        raise StagedCanaryError(f"{label} path changed during observation")
    info = final_info
    return {
        "path": str(path),
        "resolved_path": str(resolved),
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
    environment: str,
    resources: Mapping[str, Any],
    service_uid: int,
    service_dir: Path,
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
    elif authority_id == "controlled_execution":
        activation_path = Path(resources["activation_document_path"])
        observed.append(
            {
                "name": "activation_document_path",
                "sensitivity": "ROOT_OWNED_ACTIVATION_DOCUMENT",
                **_safe_observation(
                    activation_path,
                    label=f"{authority_id} activation document",
                    owner_uids={0},
                    kinds={"file"},
                    allowed_modes={0o400, 0o440, 0o444, 0o600, 0o640, 0o644},
                    include_digest=True,
                ),
            }
        )
        try:
            activation_raw = read_protected_authority_file(
                activation_path,
                expected_owner_uids={0},
                allowed_modes={0o400, 0o440, 0o444, 0o600, 0o640, 0o644},
                max_bytes=1024 * 1024,
            ).raw
            activation = _strict_json(
                activation_raw,
                label=f"{authority_id} activation resource identity",
            )
        except ProtectedAuthorityFileError as exc:
            raise StagedCanaryError(
                f"{authority_id} activation resource identity is unavailable"
            ) from exc
        if (
            set(activation) != _CONTROLLED_ACTIVATION_FIELDS
            or activation.get("format")
            != "exact-four-controlled-execution-activation/v2"
            or activation.get("environment") != environment
            or activation.get("service_uid") != service_uid
            or activation.get("protected_store_observed") is not True
            or type(activation.get("store_path")) is not str
        ):
            raise StagedCanaryError(
                f"{authority_id} activation resource identity drifted"
            )
        store_path = Path(activation["store_path"])
        try:
            store_parent = store_path.parent.resolve(strict=True)
            expected_parent = service_dir.resolve(strict=True)
        except OSError as exc:
            raise StagedCanaryError(
                f"{authority_id} store parent is unavailable"
            ) from exc
        if (
            not store_path.is_absolute()
            or store_parent != expected_parent
            or os.path.lexists(Path(f"{store_path}-wal"))
            or os.path.lexists(Path(f"{store_path}-shm"))
            or os.path.lexists(Path(f"{store_path}-journal"))
        ):
            raise StagedCanaryError(f"{authority_id} inactive store identity is unsafe")
        observed.append(
            {
                "name": "controlled_store",
                "sensitivity": "INACTIVE_PRODUCT_SQLITE_STORE",
                **_safe_observation(
                    store_path,
                    label=f"{authority_id} product store",
                    owner_uids={service_uid},
                    kinds={"file"},
                    allowed_modes={0o600},
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
    else:
        raise StagedCanaryError("unexpected non-file local signing backend")
    resources = _observe_runtime_resources(
        authority_id=authority_id,
        environment=environment,
        resources=config["resources"],
        service_uid=account.pw_uid,
        service_dir=Path(row["service_dir"]),
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


def _service_uid_from_manifest(
    manifest: Mapping[str, Any], *, authority_id: str, environment: str
) -> int:
    try:
        user = manifest["principals"][authority_id]["deployments"][environment][
            "service_user"
        ]
        uid = pwd.getpwnam(user).pw_uid
    except (KeyError, TypeError) as exc:
        raise StagedCanaryError("authority peer UID is not declared") from exc
    if uid <= 0:
        raise StagedCanaryError("authority peer UID is unsafe")
    return uid


def _run_authority_specific_inactive_adapter(
    *, authority_id: str, environment: str
) -> Mapping[str, Any]:
    """Construct the exact handler wiring without initializing product stores."""

    row = _deployment(authority_id, environment)
    manifest = load_and_validate_manifest()
    try:
        account = pwd.getpwnam(row["service_user"])
        config_raw = read_protected_authority_file(
            Path(row["runtime_config_path"]),
            expected_owner_uids={0},
            allowed_modes={0o440, 0o444},
            max_bytes=1024 * 1024,
        ).raw
    except (KeyError, ProtectedAuthorityFileError) as exc:
        raise StagedCanaryError("inactive adapter identity is unavailable") from exc
    if os.geteuid() != account.pw_uid:
        raise StagedCanaryError("inactive adapter requires the exact authority UID")
    from scripts.run_local_authority import decode_runtime_config

    try:
        config = decode_runtime_config(
            config_raw,
            authority_id=authority_id,
            environment=environment,
        )
    except Exception as exc:
        raise StagedCanaryError("inactive adapter runtime config is invalid") from exc
    resources = config["resources"]
    ledger = SQLiteAuthorityEventLedger(
        row["ledger_path"],
        authority_id=authority_id,
        environment=environment,
        expected_uid=account.pw_uid,
    )
    handlers: list[object] = []
    expected_operations: tuple[str, ...]
    if authority_id in {
        "d1_sync",
        "ops_projection",
        "coverage_transition",
        "ready",
    }:
        from scripts.local_authority_entrypoints import (
            CoverageTransitionAuthorize,
            D1FreezeAndRenderOpsProjection,
            D1FreezeAuthorizeApplyCoverage,
            D1SyncNow,
            OpsProjectionRenderAndSign,
            ReadyPublishProfilePlanBound,
            _d1_sync_tool_bindings_digest,
        )

        try:
            metadata = _load_public_metadata(row, expected_uid=account.pw_uid)
            custody = FileEd25519KeyCustody(
                row["key_path"],
                key_id=metadata["key_id"],
                expected_uid=account.pw_uid,
            )
            if custody.public_key_base64() != metadata["public_key_base64"]:
                raise StagedCanaryError("inactive adapter key identity drifted")
            if authority_id == "d1_sync":
                ops_uid = _service_uid_from_manifest(
                    manifest,
                    authority_id="ops_projection",
                    environment=environment,
                )
                coverage_uid = _service_uid_from_manifest(
                    manifest,
                    authority_id="coverage_transition",
                    environment=environment,
                )
                handlers = [
                    D1SyncNow(
                        environment=environment,
                        governed_db_path=resources["governed_db_path"],
                        cloudflare_token_path=resources["cloudflare_token_path"],
                        node_executable_path=resources["node_executable_path"],
                        wrangler_cli_path=resources["wrangler_cli_path"],
                        wrangler_cli_tree_path=resources["wrangler_cli_tree_path"],
                        wrangler_config_path=resources["wrangler_config_path"],
                        wrangler_lock_path=resources["wrangler_lock_path"],
                        custody=custody,
                        expected_uid=account.pw_uid,
                        source_sha=_runtime_binding()["bundle_digest"],
                        tool_digest=_d1_sync_tool_bindings_digest(
                            observe_runtime_resource_bindings(
                                authority_id="d1_sync",
                                resources=resources,
                                expected_owner_uid=0,
                            )
                        ),
                        event_ledger=ledger,
                    ),
                    D1FreezeAndRenderOpsProjection(
                        environment=environment,
                        governed_db_path=resources["governed_db_path"],
                        ops_socket_path=manifest["principals"]["ops_projection"][
                            "deployments"
                        ][environment]["socket_path"],
                        ops_uid=ops_uid,
                    ),
                    D1FreezeAuthorizeApplyCoverage(
                        environment=environment,
                        governed_db_path=resources["governed_db_path"],
                        coverage_socket_path=manifest["principals"][
                            "coverage_transition"
                        ]["deployments"][environment]["socket_path"],
                        coverage_uid=coverage_uid,
                    ),
                ]
                expected_operations = (
                    D1SyncNow.operation,
                    D1FreezeAndRenderOpsProjection.operation,
                    D1FreezeAuthorizeApplyCoverage.operation,
                )
            elif authority_id == "ops_projection":
                handlers = [
                    OpsProjectionRenderAndSign(
                        environment=environment,
                        custody=custody,
                        artifact_store=resources["artifact_store"],
                        expected_d1_uid=_service_uid_from_manifest(
                            manifest,
                            authority_id="d1_sync",
                            environment=environment,
                        ),
                    )
                ]
                expected_operations = (OpsProjectionRenderAndSign.operation,)
            elif authority_id == "coverage_transition":
                handlers = [
                    CoverageTransitionAuthorize(
                        environment=environment,
                        custody=custody,
                        expected_d1_uid=_service_uid_from_manifest(
                            manifest,
                            authority_id="d1_sync",
                            environment=environment,
                        ),
                    )
                ]
                expected_operations = (CoverageTransitionAuthorize.operation,)
            else:
                handlers = [
                    ReadyPublishProfilePlanBound(
                        environment=environment,
                        snapshot_root=resources["snapshot_root"],
                        custody=custody,
                    )
                ]
                expected_operations = (ReadyPublishProfilePlanBound.operation,)
        except (BootstrapError, LocalAuthorityError, OSError) as exc:
            raise StagedCanaryError(
                "authority-specific inactive handler preflight failed"
            ) from exc
    elif authority_id == "controlled_execution":
        from execution.controlled_execution_activation_v2 import (
            _preflight_inactive_canary_controlled_execution_writer_v2,
        )

        from scripts.execution_authority_entrypoints import (
            CONTROLLED_TRADER_HANDOFF_OPERATION,
        )

        try:
            (
                observed_environment,
                store_path,
                signer_key_id,
                signer_public_key,
                trader_uid,
            ) = _preflight_inactive_canary_controlled_execution_writer_v2()
        except Exception as exc:
            raise StagedCanaryError("Controlled read-only preflight failed") from exc
        metadata = _load_public_metadata(row, expected_uid=account.pw_uid)
        if (
            observed_environment != environment
            or trader_uid
            != _service_uid_from_manifest(
                manifest,
                authority_id="trader",
                environment=environment,
            )
            or signer_key_id != metadata["key_id"]
            or signer_public_key != metadata["public_key_base64"]
            or store_path.parent.resolve()
            != Path(row["service_dir"]).resolve(strict=True)
        ):
            raise StagedCanaryError(
                "Controlled preflight is not bound to its peer, store, and key"
            )
        expected_operations = (CONTROLLED_TRADER_HANDOFF_OPERATION,)
    else:  # closed policy inventory
        raise StagedCanaryError("authority has no inactive protocol adapter")
    operations = tuple(getattr(handler, "operation", None) for handler in handlers)
    if handlers and operations != expected_operations:
        raise StagedCanaryError("inactive handler operation dispatch drifted")
    expected = _expected_protocol_descriptor(
        authority_id=authority_id,
        environment=environment,
    )
    if tuple(expected["operations"]) != expected_operations:
        raise StagedCanaryError("inactive protocol operation contract drifted")
    return expected


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


def _run_exact_inactive_preflight(
    challenge_raw: bytes,
    *,
    expected_authority_id: str,
    expected_environment: str,
) -> Mapping[str, Any]:
    """Authority-UID runner; invoked only from the protected runtime bundle.

    The function validates one closed challenge. It derives its authority,
    environment, action, and resource identity from that challenge and
    independently remeasures the same fixed manifests and paths. It has no
    facility for a caller to supply counts, digests, stores, owners, or paths.
    Only the root manager's journal commit can make the response canonical.
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
    protocol = _run_authority_specific_inactive_adapter(
        authority_id=authority_id,
        environment=environment,
    )
    if (
        protocol["authority_id"] != authority_id
        or protocol["environment"] != environment
        or protocol["action"] != action.action
    ):
        raise StagedCanaryError("inactive protocol adapter lineage drifted")
    observed_at = datetime.now(UTC).isoformat(timespec="microseconds")
    issuer_key_id: str | None = None
    issuer_public_key_base64: str | None = None
    signature: str | None = None
    if action.proof_kind != "ED25519_PROTECTED_KEY_PREFLIGHT":
        raise StagedCanaryError("canary proof kind is unsupported")
    key = resources["key"]
    if type(key) is not dict:
        raise StagedCanaryError("file-backed canary has no observed key")
    issuer_key_id = key["key_id"]
    issuer_public_key_base64 = key["public_key_base64"]
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
        "protocol_digest": _digest(protocol),
        "challenge_digest": _digest(canonical_json_bytes(validated)),
        "nonce": validated["nonce"],
        "observed_at": observed_at,
        "strict_boundaries": dict(STRICT_BOUNDARIES),
        "issuer_key_id": issuer_key_id,
        "issuer_public_key_base64": issuer_public_key_base64,
    }
    row = _deployment(authority_id, environment)
    custody = FileEd25519KeyCustody(
        row["key_path"],
        key_id=issuer_key_id,
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
    """Read one challenge and emit noncanonical signed evidence or fail."""

    try:
        if sys.flags.isolated != 1:
            raise StagedCanaryError("inactive canary runner requires Python -I")
        raw = sys.stdin.buffer.read(MAX_CANARY_BYTES + 1)
        result = _run_exact_inactive_preflight(
            raw,
            expected_authority_id=authority_id,
            expected_environment=environment,
        )
    except (StagedCanaryError, LocalAuthorityError, BootstrapError):
        print("inactive authority canary preflight rejected", file=sys.stderr)
        return 1
    sys.stdout.buffer.write(canonical_json_bytes(dict(result)) + b"\n")
    return 0
