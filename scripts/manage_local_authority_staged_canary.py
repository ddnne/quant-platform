#!/usr/bin/env python3
"""Operate the fixed local-authority staged canary workflow.

``run`` is one indivisible root-orchestrated workflow: the program derives the
action, source SHA, resources, challenge, lease and evidence from protected
state; launches the exact root-owned runtime as the declared authority UID;
verifies the returned preflight; remeasures resources; and commits the result.
No subcommand exposes an intermediate permit or a generic completion surface.
"""

from __future__ import annotations

import argparse
import base64
import grp
import hashlib
import json
import os
import platform
import pwd
import secrets
import sqlite3
import stat
import subprocess
import sys
import time
import urllib.parse
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

_MANAGER_ROOT = Path(__file__).resolve().parents[1]
if str(_MANAGER_ROOT) not in sys.path:
    sys.path.insert(0, str(_MANAGER_ROOT))

from scripts.authority_principal_manifest import (
    LOCAL_OS_PRINCIPALS,
    PINNED_MANIFEST_DIGEST,
)
from scripts.finding_ledger_gate import load_pinned_finding_ledger
from scripts.local_authority_activation import canonical_json_bytes
from scripts.local_authority_bootstrap_common import PROTECTED_ROOT, _deployments
from scripts.local_authority_staged_canary import (
    _CANARY_BODY_FIELDS,
    _CANARY_FIELDS,
    _CHALLENGE_FIELDS,
    _DIGEST_RE,
    _NONCE_RE,
    _SOURCE_SHA_RE,
    CANARY_FORMAT,
    CANONICAL_JOURNAL_PATH,
    CANONICAL_STATE_ROOT,
    CHALLENGE_FORMAT,
    CLASSIFICATION,
    JOURNAL_FORMAT,
    LEASE_SECONDS,
    MAX_CANARY_BYTES,
    MAXIMUM_ATTEMPTS,
    STRICT_BOUNDARIES,
    StagedCanaryError,
    _digest,
    _exact,
    _expected_protocol_descriptor,
    _parse_time,
    _runtime_binding,
    _strict_json,
    load_policy,
    observe_preflight_resources,
)

_RUN_STATES = {"RUNNING", "FAILED_RETRYABLE", "FAILED_FINAL", "COMMITTED"}
_EVENT_TYPES = {
    "LEASE_ACQUIRED",
    "EXPIRED_LEASE_RECOVERED",
    "ACTION_STARTED",
    "ACTION_FAILED_RETRYABLE",
    "ACTION_FAILED_FINAL",
    "CANARY_COMMITTED",
}
_SCHEMA = """
PRAGMA journal_mode=DELETE;
PRAGMA synchronous=FULL;
PRAGMA foreign_keys=ON;
CREATE TABLE IF NOT EXISTS staged_canary_meta (
  singleton INTEGER PRIMARY KEY CHECK(singleton=1),
  schema_version INTEGER NOT NULL CHECK(schema_version=1),
  journal_format TEXT NOT NULL,
  policy_digest TEXT NOT NULL,
  principal_manifest_digest TEXT NOT NULL,
  canonical_path TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS staged_canary_runs (
  canary_id TEXT PRIMARY KEY,
  authority_id TEXT NOT NULL,
  environment TEXT NOT NULL,
  action TEXT NOT NULL,
  source_sha TEXT NOT NULL,
  runtime_bundle_digest TEXT NOT NULL,
  resource_digest TEXT NOT NULL,
  resource_json TEXT NOT NULL,
  state TEXT NOT NULL CHECK(state IN
    ('RUNNING','FAILED_RETRYABLE','FAILED_FINAL','COMMITTED')),
  attempt_count INTEGER NOT NULL CHECK(attempt_count BETWEEN 1 AND 3),
  lease_token TEXT,
  lease_boot_id TEXT,
  deadline_monotonic_ns INTEGER,
  lease_expires_at TEXT,
  challenge_json TEXT,
  result_json TEXT,
  result_digest TEXT,
  failure_class TEXT,
  updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS staged_canary_events (
  sequence INTEGER PRIMARY KEY,
  canary_id TEXT NOT NULL,
  event_type TEXT NOT NULL,
  attempt INTEGER NOT NULL,
  observed_at TEXT NOT NULL,
  lease_token_digest TEXT,
  detail_digest TEXT,
  prior_event_digest TEXT,
  event_digest TEXT NOT NULL UNIQUE,
  FOREIGN KEY(canary_id) REFERENCES staged_canary_runs(canary_id)
);
CREATE TRIGGER IF NOT EXISTS staged_canary_events_no_update
BEFORE UPDATE ON staged_canary_events
BEGIN SELECT RAISE(ABORT, 'immutable staged canary event'); END;
CREATE TRIGGER IF NOT EXISTS staged_canary_events_no_delete
BEFORE DELETE ON staged_canary_events
BEGIN SELECT RAISE(ABORT, 'immutable staged canary event'); END;
"""
_JOURNAL_SCHEMA_DIGEST = (
    "sha256:91b8ef440a2167d0c097d8d64e9cd420a2eff29ce6e40de491de41b60b17ec97"
)
_RESOURCE_TOP_FIELDS = {
    "format",
    "authority_id",
    "environment",
    "action",
    "resource_roles",
    "principal_manifest_digest",
    "source_sha",
    "runtime_bundle_digest",
    "runtime_entrypoint_digest",
    "runtime_python_digest",
    "service_identity",
    "runtime_config",
    "key",
    "event_ledger",
    "runtime_resources",
    "resource_digest",
}
_SERVICE_IDENTITY_FIELDS = {
    "service_user",
    "uid",
    "gid",
    "service_group",
    "service_group_gid",
    "caller_group",
    "caller_group_gid",
    "peer_uids",
    "home",
    "shell",
    "service_directory",
}
_OBSERVATION_FIELDS = {"device", "inode", "owner_uid", "owner_gid", "mode", "nlink"}
_KEY_FIELDS = {
    "key_id",
    "public_key_base64",
    "public_key_sha256",
    "public_metadata_digest",
    "key_observation",
}
_EVENT_LEDGER_FIELDS = {
    "path",
    "schema_version",
    "authority_id",
    "environment",
    "event_count",
    "tail_event_digest",
    "chain_digest",
    "observation",
}
_RUNTIME_RESOURCE_CONTRACTS = {
    "d1_sync": {
        "cloudflare_token_path": ("file", False),
        "governed_db_path": ("file", False),
        "node_executable_path": ("file", True),
        "wrangler_cli_path": ("file", True),
        "wrangler_cli_tree_path": ("tree", True),
        "wrangler_config_path": ("file", True),
        "wrangler_lock_path": ("file", True),
    },
    "ops_projection": {"artifact_store": ("directory", False)},
    "coverage_transition": {},
    "ready": {"snapshot_root": ("directory", False)},
    "controlled_execution": {
        "activation_document_path": ("file", True),
        "controlled_store": ("file", True),
    },
}


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _time_text(value: datetime) -> str:
    return value.astimezone(UTC).isoformat(timespec="microseconds")


def _boot_id() -> str:
    linux = Path("/proc/sys/kernel/random/boot_id")
    try:
        value = linux.read_text(encoding="ascii").strip().lower()
    except OSError:
        value = ""
    if value:
        return "linux:" + hashlib.sha256(value.encode("ascii")).hexdigest()
    if platform.system() == "Darwin":
        result = subprocess.run(
            ["/usr/sbin/sysctl", "-n", "kern.boottime"],
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0 and result.stdout.strip():
            return (
                "darwin:"
                + hashlib.sha256(result.stdout.strip().encode("utf-8")).hexdigest()
            )
    raise StagedCanaryError("stable boot identity is unavailable")


def _require_human_root() -> None:
    if platform.system() != "Darwin":
        raise StagedCanaryError("staged authority canaries support macOS only")
    if os.geteuid() != 0:
        raise StagedCanaryError(
            "staged authority canary run requires interactive human sudo"
        )


def _require_protected_manager_binding() -> None:
    if sys.flags.isolated != 1:
        raise StagedCanaryError("protected canary manager requires Python -I")
    binding = _runtime_binding()
    expected = (
        Path(binding["bundle_path"])
        / "scripts"
        / ("manage_local_authority_staged_canary.py")
    )
    if Path(__file__).resolve() != expected:
        raise StagedCanaryError(
            "run must execute the manager from the protected exact-source bundle"
        )


def _require_exact_directory(path: Path, *, mode: int) -> None:
    try:
        info = path.lstat()
    except OSError as exc:
        raise StagedCanaryError(
            "canonical canary state directory is unavailable"
        ) from exc
    if (
        not stat.S_ISDIR(info.st_mode)
        or info.st_uid != 0
        or stat.S_IMODE(info.st_mode) != mode
    ):
        raise StagedCanaryError("canonical canary state directory is unsafe")


def _prepare_canonical_state_root() -> None:
    _require_human_root()
    try:
        protected = PROTECTED_ROOT.lstat()
    except OSError as exc:
        raise StagedCanaryError(
            "authority protected root must be bootstrapped first"
        ) from exc
    if (
        not stat.S_ISDIR(protected.st_mode)
        or protected.st_uid != 0
        or stat.S_IMODE(protected.st_mode) & 0o022
    ):
        raise StagedCanaryError("authority protected root is unsafe")
    if not CANONICAL_STATE_ROOT.exists():
        os.mkdir(CANONICAL_STATE_ROOT, 0o700)
        os.chown(CANONICAL_STATE_ROOT, 0, 0)
        directory = os.open(CANONICAL_STATE_ROOT.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    _require_exact_directory(CANONICAL_STATE_ROOT, mode=0o700)


def _journal_sidecars() -> tuple[Path, ...]:
    return tuple(
        Path(f"{CANONICAL_JOURNAL_PATH}{suffix}")
        for suffix in ("-wal", "-shm", "-journal")
    )


def _require_journal_metadata(
    *, allow_empty: bool = False, allow_recovery_journal: bool = False
) -> None:
    if CANONICAL_JOURNAL_PATH.parent != CANONICAL_STATE_ROOT:
        raise StagedCanaryError("canonical canary journal path drifted")
    try:
        info = CANONICAL_JOURNAL_PATH.lstat()
    except OSError as exc:
        raise StagedCanaryError("canonical canary journal is unavailable") from exc
    wal_path, shm_path, rollback_path = _journal_sidecars()
    if (
        not stat.S_ISREG(info.st_mode)
        or info.st_uid != 0
        or stat.S_IMODE(info.st_mode) != 0o600
        or info.st_nlink != 1
        or os.path.lexists(wal_path)
        or os.path.lexists(shm_path)
    ):
        raise StagedCanaryError("canonical canary journal metadata is unsafe")
    if os.path.lexists(rollback_path):
        if not allow_recovery_journal:
            raise StagedCanaryError("canonical canary rollback sidecar is present")
        try:
            rollback = rollback_path.lstat()
        except OSError as exc:
            raise StagedCanaryError(
                "canonical canary rollback sidecar is unavailable"
            ) from exc
        if (
            not stat.S_ISREG(rollback.st_mode)
            or rollback.st_uid != 0
            or stat.S_IMODE(rollback.st_mode) != 0o600
            or rollback.st_nlink != 1
        ):
            raise StagedCanaryError("canonical canary rollback sidecar is unsafe")
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(CANONICAL_JOURNAL_PATH, flags)
    except OSError as exc:
        raise StagedCanaryError("canonical canary journal cannot be pinned") from exc
    try:
        pinned_before = os.fstat(descriptor)
        header = os.read(descriptor, 20)
        pinned_after = os.fstat(descriptor)
    finally:
        os.close(descriptor)
    try:
        path_after = CANONICAL_JOURNAL_PATH.lstat()
    except OSError as exc:
        raise StagedCanaryError("canonical canary journal changed") from exc
    stable_fields = (
        "st_dev",
        "st_ino",
        "st_size",
        "st_mtime_ns",
        "st_ctime_ns",
        "st_nlink",
    )
    if any(
        getattr(info, field) != getattr(pinned_before, field)
        or getattr(pinned_before, field) != getattr(pinned_after, field)
        or getattr(pinned_after, field) != getattr(path_after, field)
        for field in stable_fields
    ):
        raise StagedCanaryError("canonical canary journal changed during pinning")
    if allow_empty and pinned_after.st_size == 0:
        return
    if (
        pinned_after.st_size < 20
        or header[:16] != b"SQLite format 3\x00"
        or header[18:20] != b"\x01\x01"
    ):
        raise StagedCanaryError(
            "canonical canary journal is not rollback-journal SQLite"
        )


def _create_journal_file() -> bool:
    flags = (
        os.O_RDWR
        | os.O_CREAT
        | os.O_EXCL
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    try:
        descriptor = os.open(CANONICAL_JOURNAL_PATH, flags, 0o600)
    except FileExistsError:
        return False
    except OSError as exc:
        raise StagedCanaryError("canonical canary journal cannot be created") from exc
    try:
        os.fchmod(descriptor, 0o600)
        os.fchown(descriptor, 0, 0)
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    directory = os.open(CANONICAL_STATE_ROOT, os.O_RDONLY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)
    return True


def _remove_cold_rollback_journal_under_exclusive_lock(
    connection: sqlite3.Connection,
) -> None:
    """Remove only SQLite's same-owner zero-header DELETE rollback remnant."""

    if not connection.in_transaction:
        raise StagedCanaryError("cold rollback cleanup has no exclusive transaction")
    rollback_path = _journal_sidecars()[2]
    main = CANONICAL_JOURNAL_PATH.lstat()
    try:
        before = rollback_path.lstat()
    except OSError as exc:
        raise StagedCanaryError("cold rollback sidecar disappeared") from exc
    if (
        not stat.S_ISREG(before.st_mode)
        or before.st_uid != main.st_uid
        or stat.S_IMODE(before.st_mode) != 0o600
        or before.st_nlink != 1
    ):
        raise StagedCanaryError("cold rollback sidecar is unsafe")
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(rollback_path, flags)
    except OSError as exc:
        raise StagedCanaryError("cold rollback sidecar cannot be pinned") from exc
    try:
        pinned_before = os.fstat(descriptor)
        header = os.read(descriptor, 28)
        pinned_after = os.fstat(descriptor)
    finally:
        os.close(descriptor)
    after = rollback_path.lstat()
    stable_fields = (
        "st_dev",
        "st_ino",
        "st_size",
        "st_mtime_ns",
        "st_ctime_ns",
        "st_nlink",
    )
    if (
        len(header) >= 8
        and header[:8] != b"\x00" * 8
        or any(
            getattr(before, field) != getattr(pinned_before, field)
            or getattr(pinned_before, field) != getattr(pinned_after, field)
            or getattr(pinned_after, field) != getattr(after, field)
            for field in stable_fields
        )
    ):
        raise StagedCanaryError("rollback sidecar is not an exact cold journal")
    os.unlink(rollback_path)
    directory = os.open(CANONICAL_STATE_ROOT, os.O_RDONLY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


def _connect_journal(*, create: bool, read_only: bool = False) -> sqlite3.Connection:
    policy = load_policy()
    if create and read_only:
        raise StagedCanaryError("read-only journal cannot be created")
    created = False
    if create:
        _prepare_canonical_state_root()
        created = _create_journal_file()
    else:
        _require_exact_directory(CANONICAL_STATE_ROOT, mode=0o700)
    _require_journal_metadata(
        allow_empty=created,
        allow_recovery_journal=not read_only,
    )
    target = str(CANONICAL_JOURNAL_PATH)
    if read_only:
        target = "file:" + urllib.parse.quote(target, safe="/") + "?mode=ro"
    connection: sqlite3.Connection | None = None
    try:
        connection = sqlite3.connect(
            target,
            isolation_level=None,
            timeout=10.0,
            uri=read_only,
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA trusted_schema=OFF")
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA busy_timeout=10000")
        if read_only:
            connection.execute("PRAGMA query_only=ON")
        else:
            connection.execute("PRAGMA synchronous=FULL")
            connection.execute("PRAGMA fullfsync=ON")
        if created:
            connection.executescript(_SCHEMA)
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM staged_canary_meta WHERE singleton=1"
            ).fetchone()
            expected = (
                1,
                JOURNAL_FORMAT,
                policy.digest,
                PINNED_MANIFEST_DIGEST,
                str(CANONICAL_JOURNAL_PATH),
            )
            if row is None:
                connection.execute(
                    "INSERT INTO staged_canary_meta VALUES(1,?,?,?,?,?)",
                    expected,
                )
            elif tuple(row)[1:] != expected:
                raise StagedCanaryError("canonical canary journal identity drifted")
            connection.commit()
        # The first schema read makes SQLite recover a legitimate hot DELETE
        # rollback journal before any gate-owned write is attempted.
        connection.execute("SELECT COUNT(*) FROM sqlite_master").fetchone()
        rollback_path = _journal_sidecars()[2]
        if not read_only and os.path.lexists(rollback_path):
            connection.execute("BEGIN EXCLUSIVE")
            try:
                _remove_cold_rollback_journal_under_exclusive_lock(connection)
                connection.commit()
            except BaseException:
                if connection.in_transaction:
                    connection.rollback()
                raise
        journal_mode = connection.execute("PRAGMA journal_mode").fetchone()
        synchronous = connection.execute("PRAGMA synchronous").fetchone()
        fullfsync = connection.execute("PRAGMA fullfsync").fetchone()
        if (
            journal_mode is None
            or str(journal_mode[0]).lower() != "delete"
            or not read_only
            and (synchronous is None or synchronous[0] != 2)
            or not read_only
            and (fullfsync is None or fullfsync[0] != 1)
        ):
            raise StagedCanaryError(
                "canonical canary journal durability mode is invalid"
            )
        _require_journal_metadata()
        _validate_journal(connection, policy_digest=policy.digest)
    except StagedCanaryError:
        if connection is not None:
            if connection.in_transaction:
                connection.rollback()
            connection.close()
        raise
    except BaseException as exc:
        if connection is not None:
            if connection.in_transaction:
                connection.rollback()
            connection.close()
        raise StagedCanaryError(
            "canonical canary journal failed closed validation"
        ) from exc
    assert connection is not None
    return connection


def _require_digest(value: Any, *, label: str) -> str:
    if type(value) is not str or _DIGEST_RE.fullmatch(value) is None:
        raise StagedCanaryError(f"{label} is not a canonical digest")
    return value


def _validate_observation(value: Any, *, label: str) -> None:
    if (
        type(value) is not dict
        or set(value) != _OBSERVATION_FIELDS
        or any(type(value[name]) is not int or value[name] < 0 for name in value)
        or value["nlink"] < 1
    ):
        raise StagedCanaryError(f"{label} file observation is invalid")


def _validate_archived_resources(
    resources: Mapping[str, Any],
    *,
    row: sqlite3.Row,
    action: Any,
) -> None:
    if (
        set(resources) != _RESOURCE_TOP_FIELDS
        or resources.get("format") != "local-authority-staged-canary-resources/v1"
        or resources.get("authority_id") != row["authority_id"]
        or resources.get("environment") != row["environment"]
        or resources.get("action") != action.action
        or resources.get("resource_roles") != list(action.resource_roles)
        or resources.get("principal_manifest_digest") != PINNED_MANIFEST_DIGEST
        or resources.get("source_sha") != row["source_sha"]
        or resources.get("runtime_bundle_digest") != row["runtime_bundle_digest"]
    ):
        raise StagedCanaryError("archived canary resource lineage is invalid")
    for name in (
        "runtime_bundle_digest",
        "runtime_entrypoint_digest",
        "runtime_python_digest",
        "resource_digest",
    ):
        _require_digest(resources.get(name), label=f"resource {name}")
    service = resources.get("service_identity")
    if (
        type(service) is not dict
        or set(service) != _SERVICE_IDENTITY_FIELDS
        or type(service.get("service_user")) is not str
        or not service["service_user"]
        or any(
            type(service.get(name)) is not int or service[name] <= 0
            for name in ("uid", "gid", "service_group_gid", "caller_group_gid")
        )
        or service["gid"] != service["service_group_gid"]
        or service["caller_group_gid"] == service["service_group_gid"]
        or type(service.get("peer_uids")) is not list
        or service["peer_uids"] != sorted(set(service["peer_uids"]))
        or any(type(uid) is not int or uid <= 0 for uid in service["peer_uids"])
        or service["uid"] in service["peer_uids"]
        or service.get("home") != "/var/empty"
        or service.get("shell") != "/usr/bin/false"
    ):
        raise StagedCanaryError("archived canary service identity is invalid")
    service_directory = service.get("service_directory")
    if (
        type(service_directory) is not dict
        or set(service_directory)
        != {"path", "resolved_path", "kind", "digest", "observation"}
        or service_directory.get("kind") != "directory"
        or service_directory.get("digest") is not None
        or type(service_directory.get("path")) is not str
        or not Path(service_directory["path"]).is_absolute()
        or type(service_directory.get("resolved_path")) is not str
        or not Path(service_directory["resolved_path"]).is_absolute()
    ):
        raise StagedCanaryError("archived canary service directory is invalid")
    _validate_observation(
        service_directory.get("observation"),
        label="service directory",
    )
    config = resources.get("runtime_config")
    if (
        type(config) is not dict
        or set(config) != {"path", "digest", "observation"}
        or type(config.get("path")) is not str
        or not Path(config["path"]).is_absolute()
    ):
        raise StagedCanaryError("archived canary runtime config is invalid")
    _require_digest(config.get("digest"), label="runtime config digest")
    _validate_observation(config.get("observation"), label="runtime config")
    key = resources.get("key")
    if action.proof_kind == "ED25519_PROTECTED_KEY_PREFLIGHT":
        if type(key) is not dict or set(key) != _KEY_FIELDS:
            raise StagedCanaryError("archived canary key identity is invalid")
        for name in ("public_key_sha256", "public_metadata_digest"):
            _require_digest(key.get(name), label=f"key {name}")
        if (
            type(key.get("key_id")) is not str
            or not key["key_id"]
            or type(key.get("public_key_base64")) is not str
        ):
            raise StagedCanaryError("archived canary public key is invalid")
        try:
            public_raw = base64.b64decode(key["public_key_base64"], validate=True)
            Ed25519PublicKey.from_public_bytes(public_raw)
        except (TypeError, ValueError) as exc:
            raise StagedCanaryError("archived canary public key is invalid") from exc
        if key["public_key_sha256"] != _digest(public_raw):
            raise StagedCanaryError("archived canary public key digest is invalid")
        _validate_observation(key.get("key_observation"), label="protected key")
    elif key is not None:
        raise StagedCanaryError("unsigned Trader canary cannot archive a key")
    ledger = resources.get("event_ledger")
    if (
        type(ledger) is not dict
        or set(ledger) != _EVENT_LEDGER_FIELDS
        or ledger.get("authority_id") != row["authority_id"]
        or ledger.get("environment") != row["environment"]
        or type(ledger.get("schema_version")) is not int
        or ledger["schema_version"] <= 0
        or type(ledger.get("event_count")) is not int
        or ledger["event_count"] < 0
        or ledger.get("tail_event_digest") is not None
        and (
            type(ledger["tail_event_digest"]) is not str
            or _DIGEST_RE.fullmatch(ledger["tail_event_digest"]) is None
        )
        or type(ledger.get("path")) is not str
        or not Path(ledger["path"]).is_absolute()
        or (ledger["event_count"] == 0) != (ledger["tail_event_digest"] is None)
    ):
        raise StagedCanaryError("archived authority event ledger is invalid")
    _require_digest(ledger.get("chain_digest"), label="authority ledger chain")
    ledger_evidence = {
        name: ledger[name]
        for name in (
            "schema_version",
            "authority_id",
            "environment",
            "event_count",
            "tail_event_digest",
        )
    }
    if ledger["chain_digest"] != _digest(ledger_evidence):
        raise StagedCanaryError("archived authority ledger chain digest is invalid")
    _validate_observation(ledger.get("observation"), label="authority event ledger")
    runtime_resources = resources.get("runtime_resources")
    if type(runtime_resources) is not list:
        raise StagedCanaryError("archived runtime resources are invalid")
    names: set[str] = set()
    for item in runtime_resources:
        if type(item) is not dict or type(item.get("name")) is not str:
            raise StagedCanaryError("archived runtime resource row is invalid")
        name = item["name"]
        if name in names:
            raise StagedCanaryError("archived runtime resource is duplicated")
        names.add(name)
        pinned_fields = {"name", "kind", "path", "digest", "observation"}
        observed_fields = {
            "name",
            "sensitivity",
            "path",
            "resolved_path",
            "kind",
            "digest",
            "observation",
        }
        if frozenset(item) not in {
            frozenset(pinned_fields),
            frozenset(observed_fields),
        }:
            raise StagedCanaryError("archived runtime resource schema is invalid")
        if set(item) == observed_fields and (
            type(item.get("sensitivity")) is not str
            or not item["sensitivity"]
            or type(item.get("resolved_path")) is not str
            or not Path(item["resolved_path"]).is_absolute()
        ):
            raise StagedCanaryError("archived runtime resource binding is invalid")
        contract = _RUNTIME_RESOURCE_CONTRACTS[row["authority_id"]].get(name)
        if (
            contract is None
            or item.get("kind") != contract[0]
            or type(item.get("path")) is not str
            or not Path(item["path"]).is_absolute()
            or contract[1]
            and (
                type(item["digest"]) is not str
                or _DIGEST_RE.fullmatch(item["digest"]) is None
            )
            or not contract[1]
            and item.get("digest") is not None
        ):
            raise StagedCanaryError("archived runtime resource identity is invalid")
        _validate_observation(item.get("observation"), label=f"resource {name}")
    if names != set(_RUNTIME_RESOURCE_CONTRACTS[row["authority_id"]]):
        raise StagedCanaryError("archived runtime resource inventory drifted")
    unsigned = {
        name: value for name, value in resources.items() if name != "resource_digest"
    }
    if _digest(unsigned) != resources["resource_digest"]:
        raise StagedCanaryError("archived runtime resource digest is invalid")


def _validate_archived_challenge(
    challenge: Mapping[str, Any],
    *,
    row: sqlite3.Row,
    action: Any,
    policy_digest: str,
) -> None:
    if set(challenge) != _CHALLENGE_FIELDS:
        raise StagedCanaryError("archived canary challenge schema is invalid")
    expected = {
        "format": CHALLENGE_FORMAT,
        "classification": CLASSIFICATION,
        "authority_id": row["authority_id"],
        "environment": row["environment"],
        "action": action.action,
        "proof_kind": action.proof_kind,
        "source_sha": row["source_sha"],
        "runtime_bundle_digest": row["runtime_bundle_digest"],
        "policy_digest": policy_digest,
        "principal_manifest_digest": PINNED_MANIFEST_DIGEST,
        "resource_digest": row["resource_digest"],
        "strict_boundaries": dict(STRICT_BOUNDARIES),
    }
    if any(challenge.get(name) != value for name, value in expected.items()):
        raise StagedCanaryError("archived canary challenge lineage is invalid")
    _require_digest(
        challenge.get("finding_ledger_digest"),
        label="archived finding ledger",
    )
    if (
        type(challenge.get("open_p0_ids")) is not list
        or challenge["open_p0_ids"] != sorted(set(challenge["open_p0_ids"]))
        or any(type(item) is not str or not item for item in challenge["open_p0_ids"])
        or "A2" not in challenge["open_p0_ids"]
        or type(challenge.get("nonce")) is not str
        or _NONCE_RE.fullmatch(challenge["nonce"]) is None
        or type(challenge.get("deadline_monotonic_ns")) is not int
        or challenge["deadline_monotonic_ns"] <= 0
    ):
        raise StagedCanaryError("archived canary challenge authority is invalid")
    issued = _parse_time(challenge.get("issued_at"), label="archived issued_at")
    expires = _parse_time(challenge.get("expires_at"), label="archived expires_at")
    if expires - issued != timedelta(seconds=LEASE_SECONDS):
        raise StagedCanaryError("archived canary wall-clock lease is invalid")


def _validate_journal(connection: sqlite3.Connection, *, policy_digest: str) -> None:
    schema_rows = connection.execute(
        "SELECT type,name,tbl_name,sql FROM sqlite_master "
        "WHERE name NOT LIKE 'sqlite_%' ORDER BY type,name"
    ).fetchall()
    schema_inventory = [
        [
            row["type"],
            row["name"],
            row["tbl_name"],
            " ".join(str(row["sql"]).split()),
        ]
        for row in schema_rows
    ]
    schema_digest = (
        "sha256:"
        + hashlib.sha256(
            json.dumps(
                schema_inventory,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
    )
    if schema_digest != _JOURNAL_SCHEMA_DIGEST:
        raise StagedCanaryError("canonical canary journal schema is invalid")
    policy = load_policy()
    if policy.digest != policy_digest:
        raise StagedCanaryError("canonical canary policy identity is invalid")
    meta = connection.execute(
        "SELECT schema_version,journal_format,policy_digest,"
        "principal_manifest_digest,canonical_path "
        "FROM staged_canary_meta WHERE singleton=1"
    ).fetchall()
    if [tuple(row) for row in meta] != [
        (
            1,
            JOURNAL_FORMAT,
            policy_digest,
            PINNED_MANIFEST_DIGEST,
            str(CANONICAL_JOURNAL_PATH),
        )
    ]:
        raise StagedCanaryError("canonical canary journal metadata is invalid")
    runs = {
        row["canary_id"]: row
        for row in connection.execute("SELECT * FROM staged_canary_runs")
    }
    events_by_canary: dict[str, list[sqlite3.Row]] = {
        canary_id: [] for canary_id in runs
    }
    prior: str | None = None
    prior_observed: datetime | None = None
    sequence = 1
    for row in connection.execute(
        "SELECT * FROM staged_canary_events ORDER BY sequence"
    ):
        if (
            row["sequence"] != sequence
            or row["event_type"] not in _EVENT_TYPES
            or row["prior_event_digest"] != prior
            or row["canary_id"] not in runs
            or type(row["attempt"]) is not int
            or row["attempt"] < 1
            or row["attempt"] > MAXIMUM_ATTEMPTS
            or type(row["lease_token_digest"]) is not str
            or _DIGEST_RE.fullmatch(row["lease_token_digest"]) is None
            or type(row["detail_digest"]) is not str
            or _DIGEST_RE.fullmatch(row["detail_digest"]) is None
        ):
            raise StagedCanaryError("staged canary event chain is not contiguous")
        observed = _parse_time(row["observed_at"], label="archived event observed_at")
        if prior_observed is not None and observed < prior_observed:
            raise StagedCanaryError("staged canary event time moved backwards")
        body = {
            "format": "local-authority-staged-canary-event/v1",
            "sequence": row["sequence"],
            "canary_id": row["canary_id"],
            "event_type": row["event_type"],
            "attempt": row["attempt"],
            "observed_at": row["observed_at"],
            "lease_token_digest": row["lease_token_digest"],
            "detail_digest": row["detail_digest"],
            "prior_event_digest": prior,
        }
        if _digest(body) != row["event_digest"]:
            raise StagedCanaryError("staged canary event digest is invalid")
        prior = row["event_digest"]
        prior_observed = observed
        events_by_canary[row["canary_id"]].append(row)
        sequence += 1
    expected_tail = {
        "RUNNING": {"LEASE_ACQUIRED", "ACTION_STARTED"},
        "FAILED_RETRYABLE": {"ACTION_FAILED_RETRYABLE"},
        "FAILED_FINAL": {"ACTION_FAILED_FINAL"},
        "COMMITTED": {"CANARY_COMMITTED"},
    }
    for canary_id, row in runs.items():
        events = events_by_canary[canary_id]
        challenge = (
            _strict_json(
                row["challenge_json"].encode("utf-8"),
                label="stored staged canary challenge",
            )
            if type(row["challenge_json"]) is str
            else None
        )
        resources = (
            _strict_json(
                row["resource_json"].encode("utf-8"),
                label="stored staged canary resources",
            )
            if type(row["resource_json"]) is str
            else None
        )
        action = policy.actions.get(row["authority_id"])
        if action is None:
            raise StagedCanaryError("staged canary authority is not policy governed")
        if challenge is None or resources is None:
            raise StagedCanaryError("staged canary archived evidence is absent")
        _validate_archived_challenge(
            challenge,
            row=row,
            action=action,
            policy_digest=policy_digest,
        )
        _validate_archived_resources(resources, row=row, action=action)
        expected_canary_id = _digest(
            {
                "format": "local-authority-staged-canary-attempt-family/v1",
                "authority_id": row["authority_id"],
                "environment": row["environment"],
                "action": action.action,
                "source_sha": row["source_sha"],
                "runtime_bundle_digest": row["runtime_bundle_digest"],
                "policy_digest": policy_digest,
            }
        )
        if (
            row["state"] not in _RUN_STATES
            or row["environment"] not in {"staging", "production"}
            or row["action"] != action.action
            or type(row["source_sha"]) is not str
            or _SOURCE_SHA_RE.fullmatch(row["source_sha"]) is None
            or type(row["runtime_bundle_digest"]) is not str
            or _DIGEST_RE.fullmatch(row["runtime_bundle_digest"]) is None
            or type(row["updated_at"]) is not str
            or row["attempt_count"] < 1
            or row["attempt_count"] > MAXIMUM_ATTEMPTS
            or canary_id != expected_canary_id
            or canonical_json_bytes(challenge).decode("utf-8") != row["challenge_json"]
            or canonical_json_bytes(resources).decode("utf-8") != row["resource_json"]
            or resources.get("resource_digest") != row["resource_digest"]
            or _digest(
                {
                    name: value
                    for name, value in resources.items()
                    if name != "resource_digest"
                }
            )
            != row["resource_digest"]
            or not events
            or max(event["attempt"] for event in events) != row["attempt_count"]
            or events[-1]["event_type"] not in expected_tail[row["state"]]
            or row["state"] == "COMMITTED"
            and (
                row["result_json"] is None
                or row["result_digest"] is None
                or row["failure_class"] is not None
            )
            or row["state"] in {"FAILED_RETRYABLE", "FAILED_FINAL"}
            and (
                row["result_json"] is not None
                or row["result_digest"] is not None
                or type(row["failure_class"]) is not str
                or not row["failure_class"]
            )
            or row["state"] == "RUNNING"
            and (
                row["result_json"] is not None
                or row["result_digest"] is not None
                or row["failure_class"] is not None
            )
            or row["state"] == "FAILED_FINAL"
            and row["attempt_count"] != MAXIMUM_ATTEMPTS
            or row["state"] == "FAILED_RETRYABLE"
            and row["attempt_count"] >= MAXIMUM_ATTEMPTS
            or row["state"] == "RUNNING"
            and any(
                row[name] is None
                for name in (
                    "lease_token",
                    "lease_boot_id",
                    "deadline_monotonic_ns",
                    "lease_expires_at",
                )
            )
            or row["state"] == "RUNNING"
            and (
                type(row["lease_token"]) is not str
                or _NONCE_RE.fullmatch(row["lease_token"]) is None
                or type(row["lease_boot_id"]) is not str
                or not row["lease_boot_id"]
                or row["deadline_monotonic_ns"] != challenge["deadline_monotonic_ns"]
                or row["lease_expires_at"] != challenge["expires_at"]
            )
            or row["state"] != "RUNNING"
            and any(
                row[name] is not None
                for name in (
                    "lease_token",
                    "lease_boot_id",
                    "deadline_monotonic_ns",
                    "lease_expires_at",
                )
            )
        ):
            raise StagedCanaryError("staged canary run state is invalid")
        _parse_time(row["updated_at"], label="archived run updated_at")
        by_attempt: dict[int, list[str]] = {}
        for event in events:
            by_attempt.setdefault(int(event["attempt"]), []).append(
                str(event["event_type"])
            )
        if set(by_attempt) != set(range(1, int(row["attempt_count"]) + 1)):
            raise StagedCanaryError("staged canary attempt history is not contiguous")
        for attempt in range(1, int(row["attempt_count"]) + 1):
            attempt_events = [event for event in events if event["attempt"] == attempt]
            if len({event["lease_token_digest"] for event in attempt_events}) != 1:
                raise StagedCanaryError("staged canary attempt changed lease identity")
            history = by_attempt[attempt]
            if attempt == 1:
                prefix = ["LEASE_ACQUIRED"]
            elif history and history[0] == "EXPIRED_LEASE_RECOVERED":
                prefix = ["EXPIRED_LEASE_RECOVERED", "LEASE_ACQUIRED"]
            else:
                prefix = ["LEASE_ACQUIRED"]
            if history[: len(prefix)] != prefix:
                raise StagedCanaryError(
                    "staged canary attempt did not acquire one lease"
                )
            suffix = history[len(prefix) :]
            if suffix and suffix[0] == "ACTION_STARTED":
                suffix = suffix[1:]
            if (
                len(suffix) > 1
                or suffix
                and suffix[0]
                not in {
                    "ACTION_FAILED_RETRYABLE",
                    "ACTION_FAILED_FINAL",
                    "CANARY_COMMITTED",
                }
            ):
                raise StagedCanaryError("staged canary attempt history is invalid")
            if attempt < row["attempt_count"]:
                next_history = by_attempt[attempt + 1]
                crashed = next_history[0] == "EXPIRED_LEASE_RECOVERED"
                if crashed and suffix:
                    raise StagedCanaryError("recovered canary attempt was not stranded")
                if not crashed and suffix != ["ACTION_FAILED_RETRYABLE"]:
                    raise StagedCanaryError(
                        "retried canary attempt did not fail retryably"
                    )
        challenge_digest = _digest(challenge)
        for event in events:
            if (
                event["attempt"] == row["attempt_count"]
                and event["event_type"]
                in {
                    "LEASE_ACQUIRED",
                    "EXPIRED_LEASE_RECOVERED",
                    "ACTION_STARTED",
                }
                and event["detail_digest"] != challenge_digest
            ):
                raise StagedCanaryError(
                    "staged canary event challenge lineage is invalid"
                )
        if row["state"] in {"FAILED_RETRYABLE", "FAILED_FINAL"} and events[-1][
            "detail_digest"
        ] != _digest(row["failure_class"].encode("ascii", "strict")):
            raise StagedCanaryError("staged canary failure lineage is invalid")
        if row["state"] == "COMMITTED":
            result = _strict_json(
                row["result_json"].encode("utf-8"),
                label="stored staged canary result",
            )
            if (
                canonical_json_bytes(result).decode("utf-8") != row["result_json"]
                or _digest(row["result_json"].encode("utf-8")) != row["result_digest"]
                or events[-1]["detail_digest"] != row["result_digest"]
                or by_attempt[int(row["attempt_count"])][-2:]
                != ["ACTION_STARTED", "CANARY_COMMITTED"]
            ):
                raise StagedCanaryError("committed staged canary result is invalid")
            _validate_canary(
                row["result_json"].encode("utf-8"),
                challenge=challenge,
                resources=resources,
            )


def _append_event(
    connection: sqlite3.Connection,
    *,
    canary_id: str,
    event_type: str,
    attempt: int,
    lease_token: str | None,
    detail_digest: str | None,
) -> None:
    if event_type not in _EVENT_TYPES:
        raise StagedCanaryError("staged canary event type is unsupported")
    tail = connection.execute(
        "SELECT sequence,event_digest,observed_at FROM staged_canary_events "
        "ORDER BY sequence DESC LIMIT 1"
    ).fetchone()
    sequence = 1 if tail is None else int(tail["sequence"]) + 1
    prior = None if tail is None else str(tail["event_digest"])
    observed_at = _time_text(_utc_now())
    if tail is not None and observed_at < str(tail["observed_at"]):
        # Event ordering is the durable sequence, not a fallible wall clock.
        # Preserve a nondecreasing audit timestamp so an NTP correction cannot
        # strand an otherwise recoverable expired lease.
        observed_at = str(tail["observed_at"])
    body = {
        "format": "local-authority-staged-canary-event/v1",
        "sequence": sequence,
        "canary_id": canary_id,
        "event_type": event_type,
        "attempt": attempt,
        "observed_at": observed_at,
        "lease_token_digest": (
            None if lease_token is None else _digest(lease_token.encode("ascii"))
        ),
        "detail_digest": detail_digest,
        "prior_event_digest": prior,
    }
    connection.execute(
        "INSERT INTO staged_canary_events VALUES(?,?,?,?,?,?,?,?,?)",
        (
            sequence,
            canary_id,
            event_type,
            attempt,
            observed_at,
            body["lease_token_digest"],
            detail_digest,
            prior,
            _digest(body),
        ),
    )


def _lease_is_live(row: sqlite3.Row, *, boot_id: str, monotonic_ns: int) -> bool:
    return (
        row["state"] == "RUNNING"
        and row["lease_boot_id"] == boot_id
        and type(row["deadline_monotonic_ns"]) is int
        and row["deadline_monotonic_ns"] > monotonic_ns
    )


def _build_challenge(
    *,
    authority_id: str,
    environment: str,
    source_sha: str,
    runtime_bundle_digest: str,
    resource_digest: str,
    nonce: str,
    deadline_monotonic_ns: int,
) -> dict[str, Any]:
    policy = load_policy()
    action = policy.actions[authority_id]
    ledger = load_pinned_finding_ledger()
    if ledger.release_allowed or "A2" not in ledger.open_p0_ids:
        raise StagedCanaryError(
            "staged A2 canary is permitted only while pinned A2 remains OPEN"
        )
    issued = _utc_now()
    return {
        "format": CHALLENGE_FORMAT,
        "classification": CLASSIFICATION,
        "authority_id": authority_id,
        "environment": environment,
        "action": action.action,
        "proof_kind": action.proof_kind,
        "source_sha": source_sha,
        "runtime_bundle_digest": runtime_bundle_digest,
        "policy_digest": policy.digest,
        "principal_manifest_digest": PINNED_MANIFEST_DIGEST,
        "finding_ledger_digest": ledger.digest,
        "open_p0_ids": list(ledger.open_p0_ids),
        "resource_digest": resource_digest,
        "nonce": nonce,
        "issued_at": _time_text(issued),
        "expires_at": _time_text(issued + timedelta(seconds=LEASE_SECONDS)),
        "deadline_monotonic_ns": deadline_monotonic_ns,
        "strict_boundaries": dict(STRICT_BOUNDARIES),
    }


def _canary_id(
    *,
    authority_id: str,
    environment: str,
    action: str,
    source_sha: str,
    runtime_bundle_digest: str,
) -> str:
    return _digest(
        {
            "format": "local-authority-staged-canary-attempt-family/v1",
            "authority_id": authority_id,
            "environment": environment,
            "action": action,
            "source_sha": source_sha,
            "runtime_bundle_digest": runtime_bundle_digest,
            "policy_digest": load_policy().digest,
        }
    )


def _acquire_lease(
    *, authority_id: str, environment: str
) -> tuple[str, str, dict[str, Any], Mapping[str, Any]]:
    policy = load_policy()
    action = policy.actions.get(authority_id)
    if action is None or environment not in {"staging", "production"}:
        raise StagedCanaryError("staged canary selector is not declared")

    # Terminalize every exhausted, expired lease for this exact selector before
    # consulting resources that may have disappeared because the service
    # crashed. This transition is negative evidence only; it cannot mint a
    # canary or reset an attempt family.
    recovery_connection = _connect_journal(create=True)
    try:
        recovery_connection.execute("BEGIN IMMEDIATE")
        _validate_journal(recovery_connection, policy_digest=policy.digest)
        recovery_boot_id = _boot_id()
        recovery_now_ns = time.monotonic_ns()
        for exhausted in recovery_connection.execute(
            "SELECT * FROM staged_canary_runs WHERE authority_id=? AND environment=? "
            "AND action=? AND state='RUNNING' AND attempt_count=?",
            (authority_id, environment, action.action, MAXIMUM_ATTEMPTS),
        ).fetchall():
            if _lease_is_live(
                exhausted,
                boot_id=recovery_boot_id,
                monotonic_ns=recovery_now_ns,
            ):
                continue
            failure_class = "EXPIRED_LEASE_EXHAUSTED"
            recovery_connection.execute(
                "UPDATE staged_canary_runs SET state='FAILED_FINAL',"
                "lease_token=NULL,lease_boot_id=NULL,deadline_monotonic_ns=NULL,"
                "lease_expires_at=NULL,failure_class=?,updated_at=? "
                "WHERE canary_id=? AND state='RUNNING'",
                (
                    failure_class,
                    _time_text(_utc_now()),
                    exhausted["canary_id"],
                ),
            )
            _append_event(
                recovery_connection,
                canary_id=exhausted["canary_id"],
                event_type="ACTION_FAILED_FINAL",
                attempt=MAXIMUM_ATTEMPTS,
                lease_token=exhausted["lease_token"],
                detail_digest=_digest(failure_class.encode("ascii")),
            )
        recovery_connection.commit()
    except BaseException:
        if recovery_connection.in_transaction:
            recovery_connection.rollback()
        raise
    finally:
        recovery_connection.close()

    binding = _runtime_binding()
    resources = observe_preflight_resources(
        authority_id=authority_id,
        environment=environment,
    )
    canary_id = _canary_id(
        authority_id=authority_id,
        environment=environment,
        action=action.action,
        source_sha=binding["source_sha"],
        runtime_bundle_digest=binding["bundle_digest"],
    )
    token = secrets.token_hex(32)
    resource_json = canonical_json_bytes(dict(resources)).decode("utf-8")
    connection = _connect_journal(create=True)
    try:
        connection.execute("BEGIN IMMEDIATE")
        _validate_journal(connection, policy_digest=policy.digest)
        row = connection.execute(
            "SELECT * FROM staged_canary_runs WHERE canary_id=?", (canary_id,)
        ).fetchone()
        if row is not None and row["state"] == "COMMITTED":
            if row["resource_digest"] != resources["resource_digest"]:
                raise StagedCanaryError("committed canary resource generation changed")
            result = _strict_json(
                row["result_json"].encode("utf-8"), label="stored staged canary"
            )
            connection.commit()
            return canary_id, "", {}, result
        recovered = row is not None and row["state"] == "RUNNING"
        boot_id = _boot_id()
        now_ns = time.monotonic_ns()
        if row is not None and _lease_is_live(
            row, boot_id=boot_id, monotonic_ns=now_ns
        ):
            raise StagedCanaryError("staged canary already has a live lease")
        prior_attempts = 0 if row is None else int(row["attempt_count"])
        if prior_attempts >= MAXIMUM_ATTEMPTS:
            if row is not None and row["state"] == "RUNNING":
                failure_class = "EXPIRED_LEASE_EXHAUSTED"
                connection.execute(
                    "UPDATE staged_canary_runs SET state='FAILED_FINAL',"
                    "lease_token=NULL,lease_boot_id=NULL,deadline_monotonic_ns=NULL,"
                    "lease_expires_at=NULL,failure_class=?,updated_at=? "
                    "WHERE canary_id=? AND state='RUNNING'",
                    (
                        failure_class,
                        _time_text(_utc_now()),
                        canary_id,
                    ),
                )
                _append_event(
                    connection,
                    canary_id=canary_id,
                    event_type="ACTION_FAILED_FINAL",
                    attempt=prior_attempts,
                    lease_token=row["lease_token"],
                    detail_digest=_digest(failure_class.encode("ascii")),
                )
                connection.commit()
            raise StagedCanaryError("staged canary exhausted its bounded retries")
        attempt = prior_attempts + 1
        deadline_ns = time.monotonic_ns() + LEASE_SECONDS * 1_000_000_000
        challenge = _build_challenge(
            authority_id=authority_id,
            environment=environment,
            source_sha=binding["source_sha"],
            runtime_bundle_digest=binding["bundle_digest"],
            resource_digest=resources["resource_digest"],
            nonce=secrets.token_hex(32),
            deadline_monotonic_ns=deadline_ns,
        )
        challenge_json = canonical_json_bytes(challenge).decode("utf-8")
        values = (
            authority_id,
            environment,
            action.action,
            binding["source_sha"],
            binding["bundle_digest"],
            resources["resource_digest"],
            resource_json,
            "RUNNING",
            attempt,
            token,
            boot_id,
            deadline_ns,
            challenge["expires_at"],
            challenge_json,
            None,
            None,
            None,
            _time_text(_utc_now()),
            canary_id,
        )
        if row is None:
            connection.execute(
                "INSERT INTO staged_canary_runs VALUES(?,?,?,?,?,?,?,?,?,?,?,?,"
                "?,?,?,?,?,?,?)",
                (canary_id, *values[:-1]),
            )
        else:
            connection.execute(
                "UPDATE staged_canary_runs SET authority_id=?,environment=?,action=?,"
                "source_sha=?,runtime_bundle_digest=?,resource_digest=?,resource_json=?,state=?,"
                "attempt_count=?,lease_token=?,lease_boot_id=?,deadline_monotonic_ns=?,"
                "lease_expires_at=?,challenge_json=?,result_json=?,result_digest=?,"
                "failure_class=?,updated_at=? WHERE canary_id=?",
                values,
            )
        if recovered:
            _append_event(
                connection,
                canary_id=canary_id,
                event_type="EXPIRED_LEASE_RECOVERED",
                attempt=attempt,
                lease_token=token,
                detail_digest=_digest(challenge),
            )
        _append_event(
            connection,
            canary_id=canary_id,
            event_type="LEASE_ACQUIRED",
            attempt=attempt,
            lease_token=token,
            detail_digest=_digest(challenge),
        )
        connection.commit()
    except BaseException:
        if connection.in_transaction:
            connection.rollback()
        raise
    finally:
        connection.close()
    return canary_id, token, challenge, resources


def _require_live_lease_under_lock(
    connection: sqlite3.Connection,
    *,
    canary_id: str,
    token: str,
) -> sqlite3.Row:
    row = connection.execute(
        "SELECT * FROM staged_canary_runs WHERE canary_id=?", (canary_id,)
    ).fetchone()
    now_ns = time.monotonic_ns()
    if (
        row is None
        or row["state"] != "RUNNING"
        or row["lease_token"] != token
        or row["lease_boot_id"] != _boot_id()
        or type(row["deadline_monotonic_ns"]) is not int
        or now_ns >= row["deadline_monotonic_ns"]
    ):
        raise StagedCanaryError("staged canary lease is stale or expired")
    return row


def _mark_action_started(
    *,
    canary_id: str,
    token: str,
    _require_live_lease: Any,
) -> None:
    connection = _connect_journal(create=False)
    try:
        connection.execute("BEGIN IMMEDIATE")
        _validate_journal(connection, policy_digest=load_policy().digest)
        row = _require_live_lease(connection, canary_id=canary_id, token=token)
        tail = connection.execute(
            "SELECT event_type,attempt,lease_token_digest FROM staged_canary_events "
            "WHERE canary_id=? ORDER BY sequence DESC LIMIT 1",
            (canary_id,),
        ).fetchone()
        if (
            tail is None
            or tail["event_type"] != "LEASE_ACQUIRED"
            or tail["attempt"] != row["attempt_count"]
            or tail["lease_token_digest"] != _digest(token.encode("ascii"))
        ):
            raise StagedCanaryError("staged canary action is not after one exact lease")
        _append_event(
            connection,
            canary_id=canary_id,
            event_type="ACTION_STARTED",
            attempt=row["attempt_count"],
            lease_token=token,
            detail_digest=_digest(row["challenge_json"].encode("utf-8")),
        )
        # This is the last operation under the write lock before the exact exec.
        if time.monotonic_ns() >= row["deadline_monotonic_ns"]:
            raise StagedCanaryError("staged canary expired before exact action")
        connection.commit()
    except BaseException:
        if connection.in_transaction:
            connection.rollback()
        raise
    finally:
        connection.close()


def _execute_exact_runner(
    *,
    authority_id: str,
    environment: str,
    challenge: Mapping[str, Any],
    _subprocess_run: Any,
) -> bytes:
    binding = _runtime_binding()
    rows = [
        row for row in _deployments(environment) if row["authority_id"] == authority_id
    ]
    if len(rows) != 1:
        raise StagedCanaryError("authority runner deployment is not unique")
    try:
        account = pwd.getpwnam(rows[0]["service_user"])
        caller_group = grp.getgrnam(rows[0]["caller_group"])
    except KeyError as exc:
        raise StagedCanaryError("authority runner UID/group is unavailable") from exc
    if (
        account.pw_uid <= 0
        or caller_group.gr_gid <= 0
        or caller_group.gr_gid == account.pw_gid
        or os.geteuid() != 0
    ):
        raise StagedCanaryError("authority runner requires root-to-service UID exec")

    def become_authority() -> None:
        os.setgroups([caller_group.gr_gid])
        os.setgid(caller_group.gr_gid)
        os.setuid(account.pw_uid)

    command = [
        binding["python_path"],
        "-I",
        binding["entrypoint_path"],
        "--authority",
        authority_id,
        "--environment",
        environment,
        "--staged-canary-preflight",
    ]
    remaining = max(
        1.0,
        (challenge["deadline_monotonic_ns"] - time.monotonic_ns()) / 1e9,
    )
    if time.monotonic_ns() >= challenge["deadline_monotonic_ns"]:
        raise StagedCanaryError("staged canary expired before exact runner exec")
    try:
        result = _subprocess_run(
            command,
            input=canonical_json_bytes(dict(challenge)),
            capture_output=True,
            cwd=binding["bundle_path"],
            env={"PATH": "/usr/bin:/bin", "PYTHONHASHSEED": "0"},
            preexec_fn=become_authority,
            timeout=remaining,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise StagedCanaryError("exact authority canary runner failed") from exc
    if (
        result.returncode != 0
        or not result.stdout
        or len(result.stdout) > MAX_CANARY_BYTES
    ):
        raise StagedCanaryError("exact authority canary preflight was rejected")
    return result.stdout


def _validate_canary(
    raw: bytes,
    *,
    challenge: Mapping[str, Any],
    resources: Mapping[str, Any],
) -> dict[str, Any]:
    value = _exact(
        _strict_json(raw, label="authority canary evidence"),
        _CANARY_FIELDS,
        label="authority canary evidence",
    )
    body = {name: value[name] for name in _CANARY_BODY_FIELDS}
    action = load_policy().actions[challenge["authority_id"]]
    expected_pairs = {
        "format": CANARY_FORMAT,
        "classification": CLASSIFICATION,
        "research_eligible": False,
        "authority_id": challenge["authority_id"],
        "environment": challenge["environment"],
        "action": challenge["action"],
        "proof_kind": challenge["proof_kind"],
        "source_sha": challenge["source_sha"],
        "runtime_bundle_digest": challenge["runtime_bundle_digest"],
        "policy_digest": challenge["policy_digest"],
        "principal_manifest_digest": challenge["principal_manifest_digest"],
        "finding_ledger_digest": challenge["finding_ledger_digest"],
        "open_p0_ids": challenge["open_p0_ids"],
        "resource_digest": resources["resource_digest"],
        "protocol_digest": _digest(
            _expected_protocol_descriptor(
                authority_id=challenge["authority_id"],
                environment=challenge["environment"],
            )
        ),
        "challenge_digest": _digest(canonical_json_bytes(dict(challenge))),
        "nonce": challenge["nonce"],
        "strict_boundaries": dict(STRICT_BOUNDARIES),
    }
    if any(body.get(name) != expected for name, expected in expected_pairs.items()):
        raise StagedCanaryError("authority canary lineage or eligibility drifted")
    observed_at = _parse_time(value["observed_at"], label="canary observed_at")
    if not (
        _parse_time(challenge["issued_at"], label="challenge issued_at")
        <= observed_at
        <= _parse_time(challenge["expires_at"], label="challenge expires_at")
    ):
        raise StagedCanaryError("authority canary observation is outside its lease")
    if value["canary_digest"] != _digest(
        {name: value[name] for name in _CANARY_FIELDS if name != "canary_digest"}
    ):
        raise StagedCanaryError("authority canary content digest is invalid")
    if action.proof_kind != "ED25519_PROTECTED_KEY_PREFLIGHT":
        raise StagedCanaryError("authority canary proof kind is not signed")
    key = resources["key"]
    if (
        type(key) is not dict
        or value["issuer_key_id"] != key["key_id"]
        or value["issuer_public_key_base64"] != key["public_key_base64"]
        or type(value["signature"]) is not str
        or not value["signature"].startswith("ed25519:")
    ):
        raise StagedCanaryError("authority canary signer identity is invalid")
    try:
        public_raw = base64.b64decode(value["issuer_public_key_base64"], validate=True)
        signature = base64.b64decode(
            value["signature"].removeprefix("ed25519:"), validate=True
        )
        Ed25519PublicKey.from_public_bytes(public_raw).verify(
            signature, canonical_json_bytes(body)
        )
    except (TypeError, ValueError, InvalidSignature) as exc:
        raise StagedCanaryError("authority canary signature is invalid") from exc
    return value


def _mark_failed(*, canary_id: str, token: str, failure_class: str) -> None:
    connection = _connect_journal(create=False)
    try:
        connection.execute("BEGIN IMMEDIATE")
        _validate_journal(connection, policy_digest=load_policy().digest)
        row = connection.execute(
            "SELECT * FROM staged_canary_runs WHERE canary_id=?", (canary_id,)
        ).fetchone()
        if row is None or row["state"] != "RUNNING" or row["lease_token"] != token:
            raise StagedCanaryError("failed canary no longer owns its exact lease")
        tail = connection.execute(
            "SELECT event_type,attempt,lease_token_digest FROM staged_canary_events "
            "WHERE canary_id=? ORDER BY sequence DESC LIMIT 1",
            (canary_id,),
        ).fetchone()
        if (
            tail is None
            or tail["event_type"] not in {"LEASE_ACQUIRED", "ACTION_STARTED"}
            or tail["attempt"] != row["attempt_count"]
            or tail["lease_token_digest"] != _digest(token.encode("ascii"))
        ):
            raise StagedCanaryError("failed canary has no current action lease")
        final = row["attempt_count"] >= MAXIMUM_ATTEMPTS
        state = "FAILED_FINAL" if final else "FAILED_RETRYABLE"
        event = "ACTION_FAILED_FINAL" if final else "ACTION_FAILED_RETRYABLE"
        connection.execute(
            "UPDATE staged_canary_runs SET state=?,lease_token=NULL,lease_boot_id=NULL,"
            "deadline_monotonic_ns=NULL,lease_expires_at=NULL,failure_class=?,updated_at=? "
            "WHERE canary_id=?",
            (state, failure_class, _time_text(_utc_now()), canary_id),
        )
        _append_event(
            connection,
            canary_id=canary_id,
            event_type=event,
            attempt=row["attempt_count"],
            lease_token=token,
            detail_digest=_digest(failure_class.encode("ascii", "strict")),
        )
        connection.commit()
    except BaseException:
        if connection.in_transaction:
            connection.rollback()
        raise
    finally:
        connection.close()


def _commit_verified_runner_output(
    *,
    canary_id: str,
    token: str,
    challenge: Mapping[str, Any],
    runner_output: bytes,
    _require_live_lease: Any,
) -> dict[str, Any]:
    connection = _connect_journal(create=False)
    try:
        connection.execute("BEGIN IMMEDIATE")
        _validate_journal(connection, policy_digest=load_policy().digest)
        row = _require_live_lease(connection, canary_id=canary_id, token=token)
        tail = connection.execute(
            "SELECT event_type,attempt,lease_token_digest FROM staged_canary_events "
            "WHERE canary_id=? ORDER BY sequence DESC LIMIT 1",
            (canary_id,),
        ).fetchone()
        if (
            tail is None
            or tail["event_type"] != "ACTION_STARTED"
            or tail["attempt"] != row["attempt_count"]
            or tail["lease_token_digest"] != _digest(token.encode("ascii"))
        ):
            raise StagedCanaryError(
                "verified runner output has no exact started action"
            )
        final_resources = observe_preflight_resources(
            authority_id=row["authority_id"],
            environment=row["environment"],
        )
        if final_resources["resource_digest"] != row["resource_digest"]:
            raise StagedCanaryError("authority resources changed before commit")
        binding = _runtime_binding()
        if (
            binding["source_sha"] != row["source_sha"]
            or binding["bundle_digest"] != row["runtime_bundle_digest"]
        ):
            raise StagedCanaryError("authority source SHA changed before commit")
        if (
            canonical_json_bytes(dict(challenge)).decode("utf-8")
            != row["challenge_json"]
        ):
            raise StagedCanaryError("authority canary challenge changed before commit")
        ledger = load_pinned_finding_ledger()
        if (
            ledger.digest != challenge["finding_ledger_digest"]
            or list(ledger.open_p0_ids) != challenge["open_p0_ids"]
            or ledger.release_allowed
            or "A2" not in ledger.open_p0_ids
        ):
            raise StagedCanaryError("finding ledger changed before canary commit")
        stored_resources = canonical_json_bytes(dict(final_resources)).decode("utf-8")
        if stored_resources != row["resource_json"]:
            raise StagedCanaryError("authority resource evidence changed before commit")
        result = _validate_canary(
            runner_output,
            challenge=challenge,
            resources=final_resources,
        )
        # Deadline is rechecked under the write lock immediately before the
        # durable state transition; no blocking work follows this check.
        result_json = canonical_json_bytes(result).decode("utf-8")
        result_digest = _digest(result_json.encode("utf-8"))
        if time.monotonic_ns() >= row["deadline_monotonic_ns"]:
            raise StagedCanaryError("authority canary expired before commit")
        connection.execute(
            "UPDATE staged_canary_runs SET state='COMMITTED',lease_token=NULL,"
            "lease_boot_id=NULL,deadline_monotonic_ns=NULL,lease_expires_at=NULL,"
            "result_json=?,result_digest=?,failure_class=NULL,updated_at=? "
            "WHERE canary_id=? AND state='RUNNING'",
            (result_json, result_digest, _time_text(_utc_now()), canary_id),
        )
        _append_event(
            connection,
            canary_id=canary_id,
            event_type="CANARY_COMMITTED",
            attempt=row["attempt_count"],
            lease_token=token,
            detail_digest=result_digest,
        )
        if time.monotonic_ns() >= row["deadline_monotonic_ns"]:
            raise StagedCanaryError("authority canary expired before durable commit")
        connection.commit()
    except BaseException:
        if connection.in_transaction:
            connection.rollback()
        raise
    finally:
        connection.close()
    return result


def _seal_atomic_run_workflow() -> Any:
    """Capture every minting primitive, then remove those module attributes."""

    acquire = _acquire_lease
    start_impl = _mark_action_started
    exact_uid_runner_impl = _execute_exact_runner
    commit_impl = _commit_verified_runner_output
    fail = _mark_failed
    require_live_lease = _require_live_lease_under_lock
    subprocess_run = subprocess.run
    root_check = _require_human_root
    protected_binding_check = _require_protected_manager_binding

    def start(*, canary_id: str, token: str) -> None:
        start_impl(
            canary_id=canary_id,
            token=token,
            _require_live_lease=require_live_lease,
        )

    def exact_uid_runner(
        *, authority_id: str, environment: str, challenge: Mapping[str, Any]
    ) -> bytes:
        return exact_uid_runner_impl(
            authority_id=authority_id,
            environment=environment,
            challenge=challenge,
            _subprocess_run=subprocess_run,
        )

    def commit(
        *,
        canary_id: str,
        token: str,
        challenge: Mapping[str, Any],
        runner_output: bytes,
    ) -> dict[str, Any]:
        return commit_impl(
            canary_id=canary_id,
            token=token,
            challenge=challenge,
            runner_output=runner_output,
            _require_live_lease=require_live_lease,
        )

    def atomic_run(*, authority_id: str, environment: str) -> Mapping[str, Any]:
        """Execute the sole workflow; no challenge, lease or raw bytes escape."""

        if load_policy().actions.get(authority_id) is None or environment not in {
            "staging",
            "production",
        }:
            raise StagedCanaryError(
                "staged canary selector is excluded and remains PENDING"
            )
        root_check()
        protected_binding_check()
        canary_id, token, challenge, resources = acquire(
            authority_id=authority_id,
            environment=environment,
        )
        if not token:
            return {
                "format": "local-authority-staged-canary-result/v1",
                "status": "ALREADY_COMMITTED_RESEARCH_INELIGIBLE_CANARY",
                "canary_id": canary_id,
                "canary_digest": resources["canary_digest"],
                "classification": CLASSIFICATION,
                "research_eligible": False,
                "strict_boundaries": dict(STRICT_BOUNDARIES),
            }
        try:
            start(canary_id=canary_id, token=token)
            # Raw bytes have one origin and one consumer inside this closure.
            raw = exact_uid_runner(
                authority_id=authority_id,
                environment=environment,
                challenge=challenge,
            )
            result = commit(
                canary_id=canary_id,
                token=token,
                challenge=challenge,
                runner_output=raw,
            )
        except BaseException as exc:
            try:
                fail(
                    canary_id=canary_id,
                    token=token,
                    failure_class=type(exc).__name__,
                )
            except StagedCanaryError:
                pass
            raise
        return {
            "format": "local-authority-staged-canary-result/v1",
            "status": "COMMITTED_RESEARCH_INELIGIBLE_CANARY",
            "canary_id": canary_id,
            "canary_digest": result["canary_digest"],
            "classification": CLASSIFICATION,
            "research_eligible": False,
            "strict_boundaries": dict(STRICT_BOUNDARIES),
        }

    return atomic_run


run_canary = _seal_atomic_run_workflow()
for _sealed_name in (
    "_seal_atomic_run_workflow",
    "_acquire_lease",
    "_mark_action_started",
    "_execute_exact_runner",
    "_commit_verified_runner_output",
    "_mark_failed",
    "_require_live_lease_under_lock",
):
    globals().pop(_sealed_name, None)
del _sealed_name


def plan(*, authority_id: str, environment: str) -> Mapping[str, Any]:
    policy = load_policy()
    action = policy.actions.get(authority_id)
    if action is None or environment not in {"staging", "production"}:
        raise StagedCanaryError(
            "staged canary selector is excluded and remains PENDING"
        )
    return {
        "format": "local-authority-staged-canary-plan/v1",
        "mode": "DRY_RUN",
        "mutation_performed": False,
        "authority_id": authority_id,
        "environment": environment,
        "action": action.action,
        "proof_kind": action.proof_kind,
        "policy_digest": policy.digest,
        "canonical_journal_path": str(CANONICAL_JOURNAL_PATH),
        "caller_selectable_path": False,
        "caller_selectable_owner": False,
        "caller_selectable_source_sha": False,
        "caller_selectable_resource_digest": False,
        "maximum_attempts": MAXIMUM_ATTEMPTS,
        "attempt_family": "AUTHORITY_ENVIRONMENT_ACTION_SOURCE_SHA",
        "lease_seconds": LEASE_SECONDS,
        "classification": CLASSIFICATION,
        "research_eligible": False,
        "trusted_root_required": True,
        "privileged_rollback_evident": False,
        "durability_scope": "POST_INITIALIZATION_CRASH_AND_POWER_LOSS_ONLY",
        "historical_attempt_evidence_complete": False,
        "operational_high_water_anchor_required": True,
        "strict_boundaries": dict(STRICT_BOUNDARIES),
    }


def audit() -> Mapping[str, Any]:
    connection = _connect_journal(create=False, read_only=True)
    try:
        _validate_journal(connection, policy_digest=load_policy().digest)
        rows = [
            {
                "canary_id": row["canary_id"],
                "authority_id": row["authority_id"],
                "environment": row["environment"],
                "action": row["action"],
                "source_sha": row["source_sha"],
                "resource_digest": row["resource_digest"],
                "state": row["state"],
                "attempt_count": row["attempt_count"],
                "result_digest": row["result_digest"],
                "failure_class": row["failure_class"],
                "updated_at": row["updated_at"],
            }
            for row in connection.execute(
                "SELECT * FROM staged_canary_runs ORDER BY authority_id,environment"
            )
        ]
        event_count = connection.execute(
            "SELECT COUNT(*) FROM staged_canary_events"
        ).fetchone()[0]
    finally:
        connection.close()
    return {
        "format": "local-authority-staged-canary-audit/v1",
        "mutation_performed": False,
        "classification": CLASSIFICATION,
        "research_eligible": False,
        "trusted_root_required": True,
        "privileged_rollback_evident": False,
        "durability_scope": "POST_INITIALIZATION_CRASH_AND_POWER_LOSS_ONLY",
        "historical_attempt_evidence_complete": False,
        "operational_high_water_anchor_required": True,
        "strict_boundaries": dict(STRICT_BOUNDARIES),
        "canonical_journal_path": str(CANONICAL_JOURNAL_PATH),
        "event_count": event_count,
        "runs": rows,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("plan", "audit", "run"))
    parser.add_argument("--authority", choices=sorted(LOCAL_OS_PRINCIPALS))
    parser.add_argument("--environment", choices=("staging", "production"))
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command in {"plan", "run"} and (
        args.authority is None or args.environment is None
    ):
        print("plan/run require --authority and --environment", file=sys.stderr)
        return 2
    if args.command == "audit" and (
        args.authority is not None or args.environment is not None
    ):
        print("audit does not accept selectors", file=sys.stderr)
        return 2
    try:
        if args.command == "plan":
            result = plan(
                authority_id=args.authority,
                environment=args.environment,
            )
        elif args.command == "audit":
            result = audit()
        else:
            result = run_canary(
                authority_id=args.authority,
                environment=args.environment,
            )
    except (StagedCanaryError, sqlite3.Error, OSError) as exc:
        print(
            f"staged authority canary rejected: {type(exc).__name__}", file=sys.stderr
        )
        return 1
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
