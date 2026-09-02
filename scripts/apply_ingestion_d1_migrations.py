#!/usr/bin/env python3
"""Small single-operator owner for quant-ingest D1 migrations.

The JSDA cutover CLI owns orchestration.  This module only supplies the shared
D1 lease, current migration/schema observation, Time Travel bookmark lookup,
and a bounded Wrangler migration process.  It never exports D1 or stores a
local database copy.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import subprocess
import sys
import time
from typing import Any, Callable, Mapping, Sequence

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.d1_ingestion_migration_validation import (
    MIGRATION_NAMES,
    _canonical_target,
    canonical_binding,
)


ROOT = Path(__file__).resolve().parents[1]
WORKER = ROOT / "platform" / "workers" / "ingestion-premium"
BOOTSTRAP = WORKER / "migrations" / "0023_mutation_lease.sql"
WRANGLER_VERSION = "4.125.0"
LEASE_SECONDS = 900
APPLY_TIMEOUT_SECONDS = 600
HEARTBEAT_SECONDS = 20
_SHA = re.compile(r"^[0-9a-f]{40}$")
_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
_OWNER = re.compile(r"^apply:[0-9a-f]{32}$")
_NONCE = re.compile(r"^[0-9a-f]{64}$")
_BOOKMARK = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{8}-[0-9a-f]{8}-[0-9a-f]{32}$"
)
Runner = Callable[[Sequence[str], Path], subprocess.CompletedProcess[str]]


class GuardedMigrationError(RuntimeError):
    """The canonical D1 mutation must stop."""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _utc(value: datetime | None = None) -> str:
    return (value or _now()).astimezone(timezone.utc).isoformat(
        timespec="seconds"
    ).replace("+00:00", "Z")


def _parse_utc_instant(value: object, *, label: str) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise GuardedMigrationError(f"{label} is invalid")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise GuardedMigrationError(f"{label} is invalid") from exc
    return parsed.astimezone(timezone.utc)


def _lease_now() -> datetime:
    return _now()


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")


def _digest(value: object) -> str:
    return "sha256:" + hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _sql(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _default_runner(
    argv: Sequence[str], cwd: Path
) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            list(argv),
            cwd=cwd,
            text=True,
            capture_output=True,
            check=False,
            timeout=120,
            env=os.environ.copy(),
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise GuardedMigrationError("Wrangler command failed") from exc


def _wrangler_prefix(environment: str) -> tuple[list[str], dict[str, str]]:
    binding = canonical_binding(environment)
    executable = WORKER / "node_modules" / ".bin" / "wrangler"
    package_entrypoint = WORKER / "node_modules" / "wrangler" / "bin" / "wrangler.js"
    try:
        resolved = executable.resolve(strict=True)
        expected = package_entrypoint.resolve(strict=True)
    except OSError as exc:
        raise GuardedMigrationError("pinned local Wrangler is missing") from exc
    if not executable.is_file() or resolved != expected:
        raise GuardedMigrationError("pinned local Wrangler is missing")
    return [str(executable)], binding


def _environment_args(binding: Mapping[str, str]) -> list[str]:
    args = ["--config", str(ROOT / binding["config"])]
    if binding["environment"] == "production":
        args += ["--env", "production"]
    return args


def _json_output(result: subprocess.CompletedProcess[str], label: str) -> Any:
    if result.returncode != 0:
        raise GuardedMigrationError(f"{label} failed")
    text = result.stdout or ""
    starts = [index for index in (text.find("["), text.find("{")) if index >= 0]
    if not starts:
        raise GuardedMigrationError(f"{label} returned malformed JSON")
    try:
        return json.loads(text[min(starts) :])
    except json.JSONDecodeError as exc:
        raise GuardedMigrationError(f"{label} returned malformed JSON") from exc


def _d1_payloads(
    sql: str, *, environment: str, runner: Runner = _default_runner
) -> list[Mapping[str, Any]]:
    prefix, binding = _wrangler_prefix(environment)
    result = runner(
        (
            *prefix,
            "d1",
            "execute",
            binding["database_name"],
            "--remote",
            "--json",
            "--command",
            sql,
            *_environment_args(binding),
        ),
        WORKER,
    )
    payload = _json_output(result, "D1 execute")
    rows = payload if isinstance(payload, list) else [payload]
    if not rows or any(
        not isinstance(row, Mapping) or row.get("success") is False for row in rows
    ):
        raise GuardedMigrationError("D1 execute result is invalid")
    return list(rows)


def _d1_execute(
    sql: str, *, environment: str, runner: Runner = _default_runner
) -> Mapping[str, Any]:
    rows = _d1_payloads(sql, environment=environment, runner=runner)
    if len(rows) != 1:
        raise GuardedMigrationError("D1 execute result is ambiguous")
    return rows[0]


def _results(payload: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    value = payload.get("results")
    if not isinstance(value, list) or any(not isinstance(row, Mapping) for row in value):
        raise GuardedMigrationError("D1 result rows are invalid")
    return list(value)


def _changes(payload: Mapping[str, Any]) -> int:
    meta = payload.get("meta")
    value = meta.get("changes") if isinstance(meta, Mapping) else None
    if not isinstance(value, int):
        raise GuardedMigrationError("D1 CAS result is invalid")
    return value


def _find_bookmark(value: Any) -> str:
    found: set[str] = set()

    def visit(item: Any, key: str = "") -> None:
        if isinstance(item, Mapping):
            for child_key, child in item.items():
                visit(child, str(child_key))
        elif isinstance(item, list):
            for child in item:
                visit(child, key)
        elif "bookmark" in key.lower() and isinstance(item, str) and _BOOKMARK.fullmatch(item):
            found.add(item)

    visit(value)
    if len(found) != 1:
        raise GuardedMigrationError("D1 Time Travel bookmark is ambiguous")
    return next(iter(found))


def time_travel_bookmark(
    environment: str, *, runner: Runner = _default_runner
) -> dict[str, str]:
    prefix, binding = _wrangler_prefix(environment)
    common = _environment_args(binding)
    version = runner((*prefix, "--version"), WORKER)
    if version.returncode != 0 or version.stdout.strip() != WRANGLER_VERSION:
        raise GuardedMigrationError("pinned Wrangler version is not active")
    info = _json_output(
        runner(
            (*prefix, "d1", "info", binding["database_name"], "--json", *common),
            WORKER,
        ),
        "D1 info",
    )
    candidates: list[Mapping[str, Any]] = []

    def visit(item: Any) -> None:
        if isinstance(item, Mapping):
            if (item.get("uuid") or item.get("id")) == binding["database_id"]:
                candidates.append(item)
            for child in item.values():
                visit(child)
        elif isinstance(item, list):
            for child in item:
                visit(child)

    visit(info)
    if len(candidates) != 1 or candidates[0].get("name") != binding["database_name"]:
        raise GuardedMigrationError("canonical D1 identity is not exact")
    if candidates[0].get("version") != "production":
        raise GuardedMigrationError("D1 Time Travel requires production backend")
    travel = _json_output(
        runner(
            (
                *prefix,
                "d1",
                "time-travel",
                "info",
                binding["database_name"],
                "--json",
                *common,
            ),
            WORKER,
        ),
        "D1 Time Travel info",
    )
    return {
        "bookmark": _find_bookmark(travel),
        "database_id": binding["database_id"],
        "database_name": binding["database_name"],
        "version": "production",
        "response_digest": _digest(travel),
    }


def observe_migration_state(
    environment: str, *, runner: Runner = _default_runner
) -> dict[str, Any]:
    binding = canonical_binding(environment)
    table = binding["migrations_table"]
    if not table.isidentifier():
        raise GuardedMigrationError("migration table name is invalid")
    applied = [
        str(row.get("name"))
        for row in _results(
            _d1_execute(
                f"SELECT name FROM {table} ORDER BY name",
                environment=environment,
                runner=runner,
            )
        )
    ]
    expected = list(MIGRATION_NAMES)
    if applied != expected[: len(applied)]:
        raise GuardedMigrationError("live migration history is not a canonical prefix")
    required_tables = {
        "jsda_acquisition_jobs_v2",
        "jsda_acquisition_jobs_v3",
        "jsda_v3_cutover_control",
    }
    present = {
        str(row.get("name"))
        for row in _results(
            _d1_execute(
                "SELECT name FROM sqlite_master WHERE type='table'",
                environment=environment,
                runner=runner,
            )
        )
    }
    return {
        "applied_migrations": applied,
        "pending_migrations": expected[len(applied) :],
        "schema_observations": sorted(required_tables - present),
    }


def _identity(environment: str, source_sha: str) -> dict[str, Any]:
    if not _SHA.fullmatch(source_sha):
        raise GuardedMigrationError("source SHA is invalid")
    _manifest, manifest_digest = _canonical_target()
    return {
        "environment": environment,
        "database": canonical_binding(environment),
        "source_sha": source_sha,
        "canonical_manifest_digest": manifest_digest,
    }


def _identity_values(identity: Mapping[str, Any]) -> tuple[str, str, str, str]:
    database = identity.get("database")
    if not isinstance(database, Mapping):
        raise GuardedMigrationError("lease identity is invalid")
    values = (
        str(identity.get("environment") or ""),
        str(database.get("database_id") or ""),
        str(identity.get("canonical_manifest_digest") or ""),
        str(identity.get("source_sha") or ""),
    )
    if (
        values[0] not in {"staging", "production"}
        or not values[1]
        or not _DIGEST.fullmatch(values[2])
        or not _SHA.fullmatch(values[3])
    ):
        raise GuardedMigrationError("lease identity is invalid")
    return values


def bootstrap_mutation_lease_authority(
    *,
    environment: str,
    runner: Runner = _default_runner,
    pre_bootstrap_bookmark: str,
    resume_owner_token: str | None = None,
    resume_nonce_token: str | None = None,
) -> dict[str, Any]:
    if not _BOOKMARK.fullmatch(pre_bootstrap_bookmark):
        raise GuardedMigrationError("pre-bootstrap bookmark is invalid")
    current = observe_mutation_lease_authority(environment=environment, runner=runner)
    if current is None:
        prefix, binding = _wrangler_prefix(environment)
        result = runner(
            (
                *prefix,
                "d1",
                "execute",
                binding["database_name"],
                "--remote",
                "--file",
                str(BOOTSTRAP),
                *_environment_args(binding),
            ),
            WORKER,
        )
        if result.returncode != 0:
            raise GuardedMigrationError("mutation lease bootstrap failed")
        current = observe_mutation_lease_authority(environment=environment, runner=runner)
    if current is None:
        raise GuardedMigrationError("mutation lease bootstrap is not observable")
    if current["phase"] != "vacant" and not (
        current["phase"] == "acquired"
        and current["remote_spawned"] == 0
        and current["owner"] == resume_owner_token
        and current["nonce"] == resume_nonce_token
    ):
        raise GuardedMigrationError("mutation lease is already held")
    return {
        "pre_bootstrap_bookmark": pre_bootstrap_bookmark,
        "post_bootstrap_observation": current,
    }


def observe_mutation_lease_authority(
    *, environment: str, runner: Runner = _default_runner
) -> dict[str, Any] | None:
    try:
        rows = _results(
            _d1_execute(
                "SELECT environment,database_id,manifest_digest,source_sha,owner,nonce,"
                "phase,expires_at,remote_spawned,updated_at "
                "FROM quant_ingest_mutation_lease WHERE singleton=1",
                environment=environment,
                runner=runner,
            )
        )
    except GuardedMigrationError as exc:
        if "failed" in str(exc) or "invalid" in str(exc):
            return None
        raise
    if len(rows) != 1:
        raise GuardedMigrationError("mutation lease singleton is missing")
    row = dict(rows[0])
    row["remote_spawned"] = int(row.get("remote_spawned") or 0)
    return row


def acquire_authorized_mutation_lease(
    *,
    environment: str,
    source_sha: str,
    baseline: Mapping[str, Any] | None = None,
    runner: Runner = _default_runner,
    lease_owner_token: str | None = None,
    lease_nonce_token: str | None = None,
) -> dict[str, Any]:
    del baseline
    identity = _identity(environment, source_sha)
    env, database_id, manifest_digest, sha = _identity_values(identity)
    owner = lease_owner_token or f"apply:{secrets.token_hex(16)}"
    nonce = lease_nonce_token or secrets.token_hex(32)
    if not _OWNER.fullmatch(owner) or not _NONCE.fullmatch(nonce):
        raise GuardedMigrationError("lease owner or nonce is invalid")
    current = observe_mutation_lease_authority(environment=environment, runner=runner)
    if current and current.get("owner") == owner and current.get("nonce") == nonce:
        if (
            current.get("phase") == "acquired"
            and int(current.get("remote_spawned") or 0) == 0
            and _parse_utc_instant(current.get("expires_at"), label="lease expiry")
            <= _now()
        ):
            return _transition_mutation_lease(
                identity=identity, environment=environment, owner=owner,
                nonce=nonce, to_phase="acquired", from_phases=("acquired",),
                runner=runner, remote_spawned=0, require_unexpired=False,
            )
        return revalidate_mutation_lease(
            identity=identity, environment=environment, owner=owner,
            nonce=nonce, runner=runner,
        )
    expires = _utc(_now() + timedelta(seconds=LEASE_SECONDS))
    updated = _utc()
    command = (
        "UPDATE quant_ingest_mutation_lease SET "
        f"environment={_sql(env)},database_id={_sql(database_id)},"
        f"manifest_digest={_sql(manifest_digest)},source_sha={_sql(sha)},"
        f"owner={_sql(owner)},nonce={_sql(nonce)},phase='acquired',"
        f"expires_at={_sql(expires)},remote_spawned=0,updated_at={_sql(updated)} "
        "WHERE singleton=1 AND (phase='vacant' OR "
        "(phase='acquired' AND remote_spawned=0 AND expires_at<=strftime('%Y-%m-%dT%H:%M:%SZ','now')))"
    )
    try:
        changed = _changes(
            _d1_execute(command, environment=environment, runner=runner)
        )
    except GuardedMigrationError as uncertain:
        observed = observe_mutation_lease_authority(
            environment=environment, runner=runner
        )
        if (
            observed is not None
            and observed.get("phase") == "acquired"
            and int(observed.get("remote_spawned") or 0) == 0
        ):
            try:
                return revalidate_mutation_lease(
                    identity=identity, environment=environment, owner=owner,
                    nonce=nonce, runner=runner,
                    allow_phases=frozenset({"acquired"}),
                )
            except GuardedMigrationError:
                pass
        raise uncertain
    if changed != 1:
        raise GuardedMigrationError("mutation lease is already held")
    return revalidate_mutation_lease(
        identity=identity,
        environment=environment,
        owner=owner,
        nonce=nonce,
        runner=runner,
    )


def revalidate_mutation_lease(
    *,
    identity: Mapping[str, Any],
    environment: str,
    owner: str,
    nonce: str,
    runner: Runner = _default_runner,
    require_unexpired: bool = True,
    allow_phases: frozenset[str] | None = None,
) -> dict[str, Any]:
    env, database_id, manifest_digest, sha = _identity_values(identity)
    row = observe_mutation_lease_authority(environment=environment, runner=runner)
    allowed = allow_phases or frozenset(
        {"acquired", "migrating", "verifying", "recovery_required"}
    )
    if (
        row is None
        or env != environment
        or row.get("environment") != env
        or row.get("database_id") != database_id
        or row.get("manifest_digest") != manifest_digest
        or row.get("source_sha") != sha
        or row.get("owner") != owner
        or row.get("nonce") != nonce
        or row.get("phase") not in allowed
    ):
        raise GuardedMigrationError("mutation lease identity is not active")
    if require_unexpired and _parse_utc_instant(
        row.get("expires_at"), label="lease expiry"
    ) <= _now():
        raise GuardedMigrationError("mutation lease is expired")
    return row


def _transition_mutation_lease(
    *,
    identity: Mapping[str, Any],
    environment: str,
    owner: str,
    nonce: str,
    to_phase: str,
    runner: Runner,
    from_phases: Sequence[str],
    remote_spawned: int | None = None,
    journal_status: str | None = None,
    require_unexpired: bool = True,
) -> dict[str, Any]:
    del journal_status
    _identity_values(identity)
    if to_phase not in {"acquired", "migrating", "verifying", "recovery_required"}:
        raise GuardedMigrationError("mutation lease phase is invalid")
    phases = ",".join(_sql(value) for value in from_phases)
    assignments = [f"phase={_sql(to_phase)}", f"updated_at={_sql(_utc())}"]
    assignments.append(
        f"expires_at={_sql(_utc(_now() + timedelta(seconds=LEASE_SECONDS)))}"
    )
    if remote_spawned is not None:
        assignments.append(f"remote_spawned={int(remote_spawned)}")
    where = (
        f"singleton=1 AND owner={_sql(owner)} AND nonce={_sql(nonce)} "
        f"AND phase IN ({phases})"
    )
    if require_unexpired:
        where += " AND expires_at>strftime('%Y-%m-%dT%H:%M:%SZ','now')"
    try:
        payload = _d1_execute(
            "UPDATE quant_ingest_mutation_lease SET "
            + ",".join(assignments)
            + " WHERE "
            + where,
            environment=environment,
            runner=runner,
        )
    except GuardedMigrationError as uncertain:
        observed = observe_mutation_lease_authority(
            environment=environment, runner=runner
        )
        expected_spawned = remote_spawned
        if (
            observed is not None
            and observed.get("owner") == owner
            and observed.get("nonce") == nonce
            and observed.get("phase") == to_phase
            and (
                expected_spawned is None
                or int(observed.get("remote_spawned") or 0) == expected_spawned
            )
        ):
            return revalidate_mutation_lease(
                identity=identity, environment=environment, owner=owner,
                nonce=nonce, runner=runner, require_unexpired=False,
                allow_phases=frozenset({to_phase}),
            )
        raise uncertain
    if _changes(payload) != 1:
        raise GuardedMigrationError("mutation lease CAS failed")
    return revalidate_mutation_lease(
        identity=identity,
        environment=environment,
        owner=owner,
        nonce=nonce,
        runner=runner,
        require_unexpired=False,
    )


def renew_mutation_lease(
    *, identity: Mapping[str, Any], environment: str, owner: str, nonce: str,
    runner: Runner = _default_runner,
) -> dict[str, Any]:
    row = revalidate_mutation_lease(
        identity=identity, environment=environment, owner=owner, nonce=nonce,
        runner=runner,
    )
    return _transition_mutation_lease(
        identity=identity, environment=environment, owner=owner, nonce=nonce,
        to_phase=str(row["phase"]), from_phases=(str(row["phase"]),), runner=runner,
        remote_spawned=int(row["remote_spawned"]),
    )


def resume_owned_mutation_lease(
    *, identity: Mapping[str, Any], environment: str, owner: str, nonce: str,
    runner: Runner = _default_runner,
) -> dict[str, Any]:
    row = revalidate_mutation_lease(
        identity=identity, environment=environment, owner=owner, nonce=nonce,
        runner=runner, require_unexpired=False,
        allow_phases=frozenset({"acquired", "verifying"}),
    )
    if int(row["remote_spawned"]) != 0:
        raise GuardedMigrationError("remote process evidence requires manual recovery")
    return _transition_mutation_lease(
        identity=identity, environment=environment, owner=owner, nonce=nonce,
        to_phase=str(row["phase"]), from_phases=(str(row["phase"]),), runner=runner,
        remote_spawned=0, require_unexpired=False,
    )


def release_mutation_lease(
    *, environment: str, owner: str, nonce: str,
    runner: Runner = _default_runner, allow_recovery: bool = False,
) -> None:
    phases = ["acquired", "verifying"]
    if allow_recovery:
        phases.append("recovery_required")
    phase_sql = ",".join(_sql(value) for value in phases)
    payload = _d1_execute(
        "UPDATE quant_ingest_mutation_lease SET environment='',database_id='',"
        "manifest_digest='',source_sha='',owner='',nonce='',phase='vacant',"
        "expires_at='1970-01-01T00:00:00Z',remote_spawned=0,"
        f"updated_at={_sql(_utc())} WHERE singleton=1 AND owner={_sql(owner)} "
        f"AND nonce={_sql(nonce)} AND phase IN ({phase_sql}) AND remote_spawned=0",
        environment=environment,
        runner=runner,
    )
    if _changes(payload) != 1:
        raise GuardedMigrationError("mutation lease release failed")


def _run_apply_process(
    argv: Sequence[str], *, environment: str, identity: Mapping[str, Any],
    owner: str, nonce: str, runner: Runner,
) -> int:
    if runner is not _default_runner:
        return runner(argv, WORKER).returncode
    try:
        process = subprocess.Popen(
            list(argv), cwd=WORKER, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL, env=os.environ.copy(),
        )
    except OSError as exc:
        raise GuardedMigrationError("Wrangler migration process could not start") from exc
    deadline = time.monotonic() + APPLY_TIMEOUT_SECONDS
    heartbeat = time.monotonic() + HEARTBEAT_SECONDS
    while process.poll() is None:
        if time.monotonic() >= deadline:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
            raise GuardedMigrationError("Wrangler migration process timed out")
        if time.monotonic() >= heartbeat:
            renew_mutation_lease(
                identity=identity, environment=environment, owner=owner,
                nonce=nonce, runner=runner,
            )
            heartbeat = time.monotonic() + HEARTBEAT_SECONDS
        time.sleep(1)
    return int(process.returncode or 0)


def _apply_remote_migrations(
    *, environment: str, binding: Mapping[str, str], runner: Runner,
    prefix: Sequence[str], identity: Mapping[str, Any], owner: str, nonce: str,
    on_spawned: Callable[[], None] | None = None,
) -> None:
    _transition_mutation_lease(
        identity=identity, environment=environment, owner=owner, nonce=nonce,
        to_phase="migrating", from_phases=("acquired",), runner=runner,
        remote_spawned=0,
    )
    _transition_mutation_lease(
        identity=identity, environment=environment, owner=owner, nonce=nonce,
        to_phase="migrating", from_phases=("migrating",), runner=runner,
        remote_spawned=1,
    )
    if on_spawned:
        on_spawned()
    argv = (
        *prefix, "d1", "migrations", "apply", binding["database_name"],
        "--remote", "--yes", *_environment_args(binding),
    )
    try:
        if _run_apply_process(
            argv, environment=environment, identity=identity, owner=owner,
            nonce=nonce, runner=runner,
        ) != 0:
            raise GuardedMigrationError("Wrangler migration apply failed")
        _transition_mutation_lease(
            identity=identity, environment=environment, owner=owner, nonce=nonce,
            to_phase="verifying", from_phases=("migrating",), runner=runner,
            remote_spawned=0, require_unexpired=False,
        )
    except BaseException:
        try:
            _transition_mutation_lease(
                identity=identity, environment=environment, owner=owner,
                nonce=nonce, to_phase="recovery_required",
                from_phases=("migrating",), runner=runner,
                remote_spawned=1, require_unexpired=False,
            )
        except GuardedMigrationError:
            pass
        raise


def _source_sha() -> str:
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True,
        capture_output=True, check=False,
    )
    origin = subprocess.run(
        ["git", "rev-parse", "origin/main"], cwd=ROOT, text=True,
        capture_output=True, check=False,
    )
    status = subprocess.run(
        ["git", "status", "--porcelain"], cwd=ROOT, text=True,
        capture_output=True, check=False,
    )
    sha = head.stdout.strip()
    if (
        head.returncode or origin.returncode or status.returncode
        or status.stdout.strip() or sha != origin.stdout.strip()
        or not _SHA.fullmatch(sha)
    ):
        raise GuardedMigrationError("migration requires clean merged origin/main")
    return sha


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--environment", choices=("staging", "production"), required=True)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    if not args.check:
        raise GuardedMigrationError(
            "mutating migrations run only through activate_jsda_v3_cutover.py"
        )
    result = observe_migration_state(args.environment)
    result["time_travel"] = time_travel_bookmark(args.environment)
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except GuardedMigrationError as exc:
        raise SystemExit(str(exc)) from exc
