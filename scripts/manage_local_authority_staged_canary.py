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


def _require_journal_metadata() -> None:
    if CANONICAL_JOURNAL_PATH.parent != CANONICAL_STATE_ROOT:
        raise StagedCanaryError("canonical canary journal path drifted")
    try:
        info = CANONICAL_JOURNAL_PATH.lstat()
    except OSError as exc:
        raise StagedCanaryError("canonical canary journal is unavailable") from exc
    if (
        not stat.S_ISREG(info.st_mode)
        or info.st_uid != 0
        or stat.S_IMODE(info.st_mode) != 0o600
        or info.st_nlink != 1
    ):
        raise StagedCanaryError("canonical canary journal metadata is unsafe")


def _create_journal_file() -> None:
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
        return
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


def _connect_journal(*, create: bool, read_only: bool = False) -> sqlite3.Connection:
    policy = load_policy()
    if create and read_only:
        raise StagedCanaryError("read-only journal cannot be created")
    if create:
        _prepare_canonical_state_root()
        _create_journal_file()
    else:
        _require_exact_directory(CANONICAL_STATE_ROOT, mode=0o700)
    _require_journal_metadata()
    target = str(CANONICAL_JOURNAL_PATH)
    if read_only:
        target = "file:" + urllib.parse.quote(target, safe="/") + "?mode=ro"
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
    if create:
        connection.executescript(_SCHEMA)
        connection.execute("BEGIN IMMEDIATE")
        try:
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
        except BaseException:
            if connection.in_transaction:
                connection.rollback()
            connection.close()
            raise
    _validate_journal(connection, policy_digest=policy.digest)
    return connection


def _validate_journal(connection: sqlite3.Connection, *, policy_digest: str) -> None:
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
    sequence = 1
    for row in connection.execute(
        "SELECT * FROM staged_canary_events ORDER BY sequence"
    ):
        if (
            row["sequence"] != sequence
            or row["event_type"] not in _EVENT_TYPES
            or row["prior_event_digest"] != prior
            or row["canary_id"] not in runs
        ):
            raise StagedCanaryError("staged canary event chain is not contiguous")
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
        expected_canary_id = _digest(
            {
                "format": "local-authority-staged-canary-attempt-family/v1",
                "authority_id": row["authority_id"],
                "environment": row["environment"],
                "action": row["action"],
                "source_sha": row["source_sha"],
                "runtime_bundle_digest": row["runtime_bundle_digest"],
                "policy_digest": policy_digest,
            }
        )
        if (
            row["state"] not in _RUN_STATES
            or row["attempt_count"] < 1
            or row["attempt_count"] > MAXIMUM_ATTEMPTS
            or canary_id != expected_canary_id
            or challenge is None
            or resources is None
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
            or set(challenge) != _CHALLENGE_FIELDS
            or challenge["authority_id"] != row["authority_id"]
            or challenge["environment"] != row["environment"]
            or challenge["action"] != row["action"]
            or challenge["source_sha"] != row["source_sha"]
            or challenge["runtime_bundle_digest"] != row["runtime_bundle_digest"]
            or challenge["resource_digest"] != row["resource_digest"]
            or not events
            or max(event["attempt"] for event in events) != row["attempt_count"]
            or events[-1]["event_type"] not in expected_tail[row["state"]]
            or row["state"] == "COMMITTED"
            and (row["result_json"] is None or row["result_digest"] is None)
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
        by_attempt: dict[int, list[str]] = {}
        for event in events:
            by_attempt.setdefault(int(event["attempt"]), []).append(
                str(event["event_type"])
            )
        if set(by_attempt) != set(range(1, int(row["attempt_count"]) + 1)):
            raise StagedCanaryError("staged canary attempt history is not contiguous")
        for attempt in range(1, int(row["attempt_count"]) + 1):
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
    boot_id = _boot_id()
    now_ns = time.monotonic_ns()
    deadline_ns = now_ns + LEASE_SECONDS * 1_000_000_000
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
        if row is not None and _lease_is_live(
            row, boot_id=boot_id, monotonic_ns=now_ns
        ):
            raise StagedCanaryError("staged canary already has a live lease")
        prior_attempts = 0 if row is None else int(row["attempt_count"])
        if prior_attempts >= MAXIMUM_ATTEMPTS:
            raise StagedCanaryError("staged canary exhausted its bounded retries")
        attempt = prior_attempts + 1
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


def _mark_action_started(*, canary_id: str, token: str) -> None:
    connection = _connect_journal(create=False)
    try:
        connection.execute("BEGIN IMMEDIATE")
        _validate_journal(connection, policy_digest=load_policy().digest)
        row = _require_live_lease_under_lock(
            connection, canary_id=canary_id, token=token
        )
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
    *, authority_id: str, environment: str, challenge: Mapping[str, Any]
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
        result = subprocess.run(
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
    if action.proof_kind == "ED25519_PROTECTED_KEY_PREFLIGHT":
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
            public_raw = base64.b64decode(
                value["issuer_public_key_base64"], validate=True
            )
            signature = base64.b64decode(
                value["signature"].removeprefix("ed25519:"), validate=True
            )
            Ed25519PublicKey.from_public_bytes(public_raw).verify(
                signature, canonical_json_bytes(body)
            )
        except (TypeError, ValueError, InvalidSignature) as exc:
            raise StagedCanaryError("authority canary signature is invalid") from exc
    elif action.proof_kind == "ROOT_EXEC_EXACT_UID_WEBAUTHN_REGISTRY_PREFLIGHT" and (
        value["signature"] is not None
        or value["issuer_key_id"] is not None
        or value["issuer_public_key_base64"] is not None
    ):
        raise StagedCanaryError("Trader registry preflight cannot claim a signature")
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
) -> dict[str, Any]:
    connection = _connect_journal(create=False)
    try:
        connection.execute("BEGIN IMMEDIATE")
        _validate_journal(connection, policy_digest=load_policy().digest)
        row = _require_live_lease_under_lock(
            connection, canary_id=canary_id, token=token
        )
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


def run_canary(*, authority_id: str, environment: str) -> Mapping[str, Any]:
    """Execute the sole atomic workflow; no intermediate capability is returned."""

    _require_human_root()
    _require_protected_manager_binding()
    canary_id, token, challenge, resources = _acquire_lease(
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
        _mark_action_started(canary_id=canary_id, token=token)
        raw = _execute_exact_runner(
            authority_id=authority_id,
            environment=environment,
            challenge=challenge,
        )
        result = _commit_verified_runner_output(
            canary_id=canary_id,
            token=token,
            challenge=challenge,
            runner_output=raw,
        )
    except BaseException as exc:
        failure_class = type(exc).__name__
        try:
            _mark_failed(
                canary_id=canary_id,
                token=token,
                failure_class=failure_class,
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


def plan(*, authority_id: str, environment: str) -> Mapping[str, Any]:
    policy = load_policy()
    action = policy.actions[authority_id]
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
