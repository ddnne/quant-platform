#!/usr/bin/env python3
"""Fail-closed staging-first owner for quant-ingest D1 migrations.

Database identity and Wrangler configuration come from the frozen canonical
manifest, never caller input.  The command independently observes the live D1
identity, Time Travel bookmark, export, migration history, pending inventory,
foreign keys, and JSDA preservation evidence.  The encrypted export is only a
rollback artifact; it never authorizes production.

Remote mutation remains structurally disabled until a trusted control plane
can provide both a cross-host exclusive lock and an attestation binding the
executing source SHA.  Until then this command records a canonical UNKNOWN
reservation and exits HOLD.  Recovery re-observes the canonical live D1 and is
the only way to classify that reservation as exactly applied or not applied.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import stat
import subprocess
import tempfile
from typing import Any, Callable, Mapping, Sequence

from scripts.d1_ingestion_migration_validation import (
    MIGRATION_NAMES,
    IngestionMigrationError,
    _canonical_target,
    canonical_binding,
    validate_export,
)
from scripts.encrypt_d1_backup import encrypt_backup, verify_encrypted


ROOT = Path(__file__).resolve().parents[1]
WORKER = ROOT / "platform" / "workers" / "ingestion-premium"
CANONICAL_RESERVATION_ROOT = (
    ROOT / "data" / "ops" / "d1_migration_reservations" / "v1"
)
WRANGLER_VERSION = "4.125.0"
_SHA = re.compile(r"^[0-9a-f]{40}$")
_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
_BOOKMARK = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{8}-[0-9a-f]{8}-[0-9a-f]{32}$")
Runner = Callable[[Sequence[str], Path], subprocess.CompletedProcess[str]]


class GuardedMigrationError(ValueError):
    """The governed remote migration sequence must stop without applying."""


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace(
        "+00:00", "Z"
    )


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def _digest(value: object) -> str:
    return "sha256:" + hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _default_runner(
    argv: Sequence[str], cwd: Path
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(argv),
        cwd=cwd,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        env=os.environ.copy(),
    )


def _run(
    runner: Runner,
    argv: Sequence[str],
    *,
    capture_json: bool = False,
) -> Any:
    result = runner(argv, WORKER)
    if result.returncode != 0:
        # Provider output may contain request metadata; do not relay it into
        # durable evidence or exception text.
        raise GuardedMigrationError(f"Wrangler command failed: {argv[1:4]}")
    if not capture_json:
        return None
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise GuardedMigrationError("Wrangler JSON output is malformed") from exc


def _wrangler_prefix(environment: str) -> tuple[list[str], dict[str, str]]:
    binding = canonical_binding(environment)
    executable = WORKER / "node_modules" / ".bin" / "wrangler"
    if not executable.is_file() or executable.is_symlink():
        raise GuardedMigrationError(
            "pinned local Wrangler is missing; run npm ci in ingestion-premium"
        )
    prefix = [str(executable)]
    return prefix, binding


def _environment_args(binding: Mapping[str, str]) -> list[str]:
    args = ["--config", str(ROOT / binding["config"])]
    if binding["environment"] == "production":
        args.extend(("--env", "production"))
    return args


def _unique_mapping_with_identity(value: Any, *, name: str, database_id: str) -> Mapping[str, Any]:
    candidates: list[Mapping[str, Any]] = []

    def visit(item: Any) -> None:
        if isinstance(item, Mapping):
            observed_name = item.get("name") or item.get("database_name")
            observed_id = item.get("uuid") or item.get("id") or item.get("database_id")
            if observed_name == name and observed_id == database_id:
                candidates.append(item)
            for child in item.values():
                visit(child)
        elif isinstance(item, list):
            for child in item:
                visit(child)

    visit(value)
    if len(candidates) != 1:
        raise GuardedMigrationError("Wrangler D1 identity is absent or ambiguous")
    return candidates[0]


def _bookmark(value: Any) -> str:
    candidates: set[str] = set()

    def visit(item: Any, key: str = "") -> None:
        if isinstance(item, Mapping):
            for child_key, child in item.items():
                visit(child, str(child_key))
        elif isinstance(item, list):
            for child in item:
                visit(child, key)
        elif "bookmark" in key.lower() and isinstance(item, str) and _BOOKMARK.fullmatch(item):
            candidates.add(item)

    visit(value)
    if len(candidates) != 1:
        raise GuardedMigrationError("Wrangler Time Travel bookmark is absent or ambiguous")
    return next(iter(candidates))


def _observe_remote_database(
    *,
    environment: str,
    phase: str,
    runner: Runner,
) -> dict[str, Any]:
    if phase not in {"preflight", "postflight"}:
        raise GuardedMigrationError("remote observation phase is invalid")
    prefix, binding = _wrangler_prefix(environment)
    version = runner((*prefix, "--version"), WORKER)
    if version.returncode != 0 or version.stdout.strip() != WRANGLER_VERSION:
        raise GuardedMigrationError("pinned Wrangler version is not active")
    common = _environment_args(binding)
    info = _run(
        runner,
        (*prefix, "d1", "info", binding["database_name"], "--json", *common),
        capture_json=True,
    )
    identity = _unique_mapping_with_identity(
        info,
        name=binding["database_name"],
        database_id=binding["database_id"],
    )
    time_travel = _run(
        runner,
        (
            *prefix,
            "d1",
            "time-travel",
            "info",
            binding["database_name"],
            "--json",
            *common,
        ),
        capture_json=True,
    )
    bookmark = _bookmark(time_travel)
    with tempfile.TemporaryDirectory(
        prefix=f"quant-ingest-{environment}-live-observation-"
    ) as raw:
        export_path = Path(raw) / "export.sql"
        _run(
            runner,
            (
                *prefix,
                "d1",
                "export",
                binding["database_name"],
                "--remote",
                "--yes",
                "--output",
                str(export_path),
                *common,
            ),
        )
        validation = validate_export(
            export_path,
            environment=environment,
            phase=phase,
        )
    pending_result = runner(
        (
            *prefix,
            "d1",
            "migrations",
            "list",
            binding["database_name"],
            "--remote",
            *common,
        ),
        WORKER,
    )
    if pending_result.returncode != 0:
        raise GuardedMigrationError("Wrangler pending-migration query failed")
    expected_pending = (
        validation.get("pending_migrations", []) if phase == "preflight" else []
    )
    if not isinstance(expected_pending, list):
        raise GuardedMigrationError("validated pending inventory is malformed")
    pending_digest = _validate_pending_inventory(
        pending_result.stdout,
        tuple(str(name) for name in expected_pending),
    )
    confirm_time_travel = _run(
        runner,
        (
            *prefix,
            "d1",
            "time-travel",
            "info",
            binding["database_name"],
            "--json",
            *common,
        ),
        capture_json=True,
    )
    if _bookmark(confirm_time_travel) != bookmark:
        raise GuardedMigrationError(
            "D1 changed while the canonical live observation was collected"
        )
    return {
        "schema_version": "quant-ingest-live-d1-observation/v1",
        "environment": environment,
        "database": binding,
        "phase": phase,
        "live_identity_digest": _digest(identity),
        "time_travel_response_digest": _digest(time_travel),
        "time_travel_confirm_response_digest": _digest(confirm_time_travel),
        "bookmark": bookmark,
        "validation": validation,
        "pending_migrations": expected_pending,
        "pending_response_digest": pending_digest,
        "observed_at": _utc_now(),
    }


def _source_sha(runner: Runner) -> str:
    head = runner(("git", "rev-parse", "HEAD"), ROOT)
    status = runner(("git", "status", "--porcelain"), ROOT)
    sha = head.stdout.strip()
    if head.returncode != 0 or not _SHA.fullmatch(sha):
        raise GuardedMigrationError("release source SHA is unavailable")
    if status.returncode != 0 or status.stdout.strip():
        raise GuardedMigrationError("migration owner requires a clean worktree")
    return sha


def _validate_pending_output(value: str) -> str:
    lines = tuple(line.strip() for line in value.splitlines() if line.strip())
    if (
        "✅ No migrations to apply!" not in lines
        or any("Migrations to be applied:" in line for line in lines)
    ):
        raise GuardedMigrationError("Wrangler does not prove an empty pending set")
    return "sha256:" + hashlib.sha256(value.encode("utf-8")).hexdigest()


def _validate_pending_inventory(value: str, expected: Sequence[str]) -> str:
    expected_names = tuple(expected)
    observed = tuple(re.findall(r"\b\d{4}_[a-z0-9_]+\.sql\b", value))
    if not expected_names:
        return _validate_pending_output(value)
    if observed != expected_names or "✅ No migrations to apply!" in value:
        raise GuardedMigrationError(
            "Wrangler pending inventory does not match canonical history"
        )
    return "sha256:" + hashlib.sha256(value.encode("utf-8")).hexdigest()


def _requires_exact_cutover(preflight: Mapping[str, Any]) -> bool:
    pending = preflight.get("pending_migrations")
    if not isinstance(pending, list) or any(
        not isinstance(name, str) for name in pending
    ):
        raise GuardedMigrationError("preflight pending migration evidence is malformed")
    return "0012_jsda_observation_identity.sql" in pending


def _secure_create_target(path: Path, *, label: str) -> Path:
    absolute = path.expanduser().absolute()
    parent = absolute.parent
    if (
        not parent.is_dir()
        or parent.is_symlink()
        or parent.resolve() != parent
    ):
        raise GuardedMigrationError(f"{label} parent must be a real directory")
    metadata = parent.stat()
    if metadata.st_uid != os.getuid() or metadata.st_mode & (stat.S_IWGRP | stat.S_IWOTH):
        raise GuardedMigrationError(f"{label} parent permissions are unsafe")
    if absolute.exists() or absolute.is_symlink():
        raise GuardedMigrationError(f"{label} target already exists")
    return absolute


def _secure_input(path: Path, *, label: str) -> Path:
    absolute = path.expanduser().absolute()
    if (
        not absolute.is_file()
        or absolute.is_symlink()
        or absolute.resolve() != absolute
        or absolute.stat().st_mode & (stat.S_IWGRP | stat.S_IWOTH)
    ):
        raise GuardedMigrationError(f"{label} must be a protected regular file")
    return absolute


def _preflight_local_paths(
    *,
    backup_target: Path,
    backup_key: Path,
    prepare_evidence_target: Path,
    evidence_target: Path,
) -> dict[str, Path]:
    paths = {
        "backup_target": _secure_create_target(
            backup_target, label="backup"
        ),
        "backup_key": _secure_input(backup_key, label="backup key"),
        "prepare_evidence_target": _secure_create_target(
            prepare_evidence_target, label="prepared evidence"
        ),
        "evidence_target": _secure_create_target(
            evidence_target, label="final evidence"
        ),
    }
    present = list(paths.values())
    if len(present) != len(set(present)):
        raise GuardedMigrationError(
            "backup, evidence, and key paths must be resolve-distinct"
        )
    return paths


def _read_exact_evidence(path: Path) -> Mapping[str, Any]:
    absolute = path.absolute()
    if (
        not absolute.is_file()
        or absolute.is_symlink()
        or absolute.resolve() != absolute
        or absolute.stat().st_mode & (stat.S_IWGRP | stat.S_IWOTH)
    ):
        raise GuardedMigrationError(
            "reserved final evidence must be a protected regular file"
        )
    try:
        raw = json.loads(absolute.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise GuardedMigrationError("reserved final evidence is unreadable") from exc
    if not isinstance(raw, Mapping):
        raise GuardedMigrationError("reserved final evidence is malformed")
    return raw


def _finalize_reserved_evidence(
    path: Path,
    *,
    reservation: Mapping[str, Any],
    payload: Mapping[str, Any],
) -> None:
    if _read_exact_evidence(path) != reservation:
        raise GuardedMigrationError("final evidence reservation was replaced or modified")
    descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent,
        prefix=f".{path.name}.{reservation['reservation_nonce']}.",
        suffix=".finalizing",
    )
    temporary = Path(temporary_name)
    os.chmod(temporary, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(_canonical_bytes(payload) + b"\n")
            handle.flush()
            os.fsync(handle.fileno())
        if _read_exact_evidence(path) != reservation:
            raise GuardedMigrationError(
                "final evidence reservation changed during finalization"
            )
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def _canonical_reservation_identity(
    *,
    environment: str,
    source_sha: str,
    manifest_digest: str,
) -> dict[str, Any]:
    if not _SHA.fullmatch(source_sha) or not _DIGEST.fullmatch(manifest_digest):
        raise GuardedMigrationError("canonical reservation identity is malformed")
    return {
        "schema_version": "quant-ingest-migration-reservation-identity/v1",
        "environment": environment,
        "database": canonical_binding(environment),
        "source_sha": source_sha,
        "canonical_manifest_digest": manifest_digest,
    }


def _canonical_reservation_path(identity: Mapping[str, Any]) -> Path:
    expected = _canonical_reservation_identity(
        environment=str(identity.get("environment") or ""),
        source_sha=str(identity.get("source_sha") or ""),
        manifest_digest=str(identity.get("canonical_manifest_digest") or ""),
    )
    if dict(identity) != expected:
        raise GuardedMigrationError("canonical reservation identity drift")
    identity_digest = _digest(expected)
    return (
        CANONICAL_RESERVATION_ROOT
        / str(expected["environment"])
        / str(expected["database"]["database_id"])
        / str(expected["source_sha"])
        / f"{identity_digest.removeprefix('sha256:')}.json"
    )


def _secure_canonical_reservation_parent(path: Path) -> None:
    root = CANONICAL_RESERVATION_ROOT.absolute()
    target_parent = path.parent.absolute()
    try:
        relative_parent = target_parent.relative_to(root)
    except ValueError as exc:
        raise GuardedMigrationError(
            "canonical reservation escaped its governed store"
        ) from exc
    target_parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    current = root
    candidates = [current]
    for part in relative_parent.parts:
        current = current / part
        candidates.append(current)
    for candidate in candidates:
        metadata = candidate.lstat()
        if (
            not candidate.is_dir()
            or candidate.is_symlink()
            or candidate.resolve() != candidate.absolute()
            or metadata.st_uid != os.getuid()
            or metadata.st_mode & (stat.S_IWGRP | stat.S_IWOTH)
        ):
            raise GuardedMigrationError(
                "canonical reservation store permissions are unsafe"
            )


def _require_reservation_path_distinct(
    canonical_path: Path,
    local_paths: Mapping[str, Path],
) -> None:
    reserved = canonical_path.absolute()
    if any(path.absolute() == reserved for path in local_paths.values()):
        raise GuardedMigrationError(
            "caller artifact path collides with canonical reservation"
        )


def _load_canonical_reservation(
    identity: Mapping[str, Any],
) -> tuple[Path, Mapping[str, Any]]:
    path = _canonical_reservation_path(identity)
    raw = _read_exact_evidence(path)
    expected_keys = {
        "schema_version",
        "status",
        "reason",
        "identity",
        "identity_digest",
        "reservation_nonce",
        "reservation_id",
        "baseline",
        "staging_observation",
        "rollback_backup_digest",
        "recovery",
        "created_at",
        "updated_at",
        "reservation_digest",
    }
    if set(raw) != expected_keys:
        raise GuardedMigrationError("canonical reservation schema is invalid")
    unsigned = {key: raw[key] for key in raw if key != "reservation_digest"}
    if (
        raw.get("schema_version")
        != "quant-ingest-canonical-migration-reservation/v1"
        or raw.get("identity") != identity
        or raw.get("identity_digest") != _digest(identity)
        or raw.get("reservation_digest") != _digest(unsigned)
        or not re.fullmatch(r"[0-9a-f]{64}", str(raw.get("reservation_nonce") or ""))
        or raw.get("reservation_id")
        != _digest(
            {
                "identity": identity,
                "nonce": raw.get("reservation_nonce"),
            }
        )
    ):
        raise GuardedMigrationError("canonical reservation binding is invalid")
    return path, raw


def _create_canonical_unknown_reservation(
    *,
    identity: Mapping[str, Any],
    reason: str,
    baseline: Mapping[str, Any] | None,
    staging_observation: Mapping[str, Any] | None,
    rollback_backup_digest: str | None,
) -> tuple[Path, dict[str, Any]]:
    path = _canonical_reservation_path(identity)
    if path.exists() or path.is_symlink():
        _load_canonical_reservation(identity)
        raise GuardedMigrationError(
            "canonical migration reservation already exists; recover it first"
        )
    _secure_canonical_reservation_parent(path)
    now = _utc_now()
    nonce = secrets.token_hex(32)
    unsigned = {
        "schema_version": "quant-ingest-canonical-migration-reservation/v1",
        "status": "UNKNOWN",
        "reason": reason,
        "identity": dict(identity),
        "identity_digest": _digest(identity),
        "reservation_nonce": nonce,
        "reservation_id": _digest({"identity": identity, "nonce": nonce}),
        "baseline": dict(baseline) if baseline is not None else None,
        "staging_observation": (
            dict(staging_observation) if staging_observation is not None else None
        ),
        "rollback_backup_digest": rollback_backup_digest,
        "recovery": None,
        "created_at": now,
        "updated_at": now,
    }
    reservation = {**unsigned, "reservation_digest": _digest(unsigned)}
    _publish_evidence(path, reservation)
    return path, reservation


def _finalize_canonical_reservation(
    *,
    identity: Mapping[str, Any],
    status: str,
    reason: str,
    recovery: Mapping[str, Any],
) -> dict[str, Any]:
    if status not in {"RECOVERED_APPLIED_EXACT", "RECOVERED_NOT_APPLIED"}:
        raise GuardedMigrationError("canonical recovery terminal state is invalid")
    path, reservation = _load_canonical_reservation(identity)
    if reservation.get("status") != "UNKNOWN":
        raise GuardedMigrationError("canonical reservation is already terminal")
    unsigned = {
        **{key: reservation[key] for key in reservation if key != "reservation_digest"},
        "status": status,
        "reason": reason,
        "recovery": dict(recovery),
        "updated_at": _utc_now(),
    }
    payload = {**unsigned, "reservation_digest": _digest(unsigned)}
    _finalize_reserved_evidence(path, reservation=reservation, payload=payload)
    return payload


def _publish_evidence(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(_canonical_bytes(payload) + b"\n")
            handle.flush()
            os.fsync(handle.fileno())
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    except BaseException:
        path.unlink(missing_ok=True)
        raise


def _unchanged_observation_contract(value: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": value.get("schema_version"),
        "environment": value.get("environment"),
        "database": value.get("database"),
        "phase": value.get("phase"),
        "live_identity_digest": value.get("live_identity_digest"),
        "bookmark": value.get("bookmark"),
        "validation": value.get("validation"),
        "pending_migrations": value.get("pending_migrations"),
    }


def recover_guarded(
    *,
    environment: str,
    runner: Runner = _default_runner,
) -> dict[str, Any]:
    source_sha = _source_sha(runner)
    _target, manifest_digest = _canonical_target()
    identity = _canonical_reservation_identity(
        environment=environment,
        source_sha=source_sha,
        manifest_digest=manifest_digest,
    )
    _path, reservation = _load_canonical_reservation(identity)
    if reservation.get("status") != "UNKNOWN":
        raise GuardedMigrationError("canonical reservation does not require recovery")

    try:
        postflight = _observe_remote_database(
            environment=environment,
            phase="postflight",
            runner=runner,
        )
    except (GuardedMigrationError, IngestionMigrationError):
        postflight = None
    if postflight is not None:
        return _finalize_canonical_reservation(
            identity=identity,
            status="RECOVERED_APPLIED_EXACT",
            reason="LIVE_CANONICAL_POSTFLIGHT_AND_PENDING_ZERO",
            recovery={
                "source_sha_execution": "UNPROVEN",
                "observation": postflight,
            },
        )

    current = _observe_remote_database(
        environment=environment,
        phase="preflight",
        runner=runner,
    )
    baseline = reservation.get("baseline")
    if isinstance(baseline, Mapping) and _unchanged_observation_contract(
        current
    ) == _unchanged_observation_contract(baseline):
        return _finalize_canonical_reservation(
            identity=identity,
            status="RECOVERED_NOT_APPLIED",
            reason="LIVE_PREFLIGHT_BOOKMARK_AND_PENDING_UNCHANGED",
            recovery={
                "source_sha_execution": "NOT_APPLICABLE",
                "observation": current,
            },
        )
    raise GuardedMigrationError(
        "canonical migration state remains UNKNOWN; live state changed or is ambiguous"
    )


def apply_guarded(
    *,
    environment: str,
    backup_target: Path,
    backup_key: Path,
    prepare_evidence_target: Path,
    evidence_target: Path,
    runner: Runner = _default_runner,
) -> dict[str, Any]:
    local_paths = _preflight_local_paths(
        backup_target=backup_target,
        backup_key=backup_key,
        prepare_evidence_target=prepare_evidence_target,
        evidence_target=evidence_target,
    )
    backup_target = local_paths["backup_target"]  # type: ignore[assignment]
    backup_key = local_paths["backup_key"]  # type: ignore[assignment]
    prepare_evidence_target = local_paths["prepare_evidence_target"]  # type: ignore[assignment]
    evidence_target = local_paths["evidence_target"]  # type: ignore[assignment]
    assert isinstance(backup_target, Path)
    assert isinstance(backup_key, Path)
    assert isinstance(prepare_evidence_target, Path)
    assert isinstance(evidence_target, Path)
    prefix, binding = _wrangler_prefix(environment)
    source_sha = _source_sha(runner)
    _target, manifest_digest = _canonical_target()
    canonical_identity = _canonical_reservation_identity(
        environment=environment,
        source_sha=source_sha,
        manifest_digest=manifest_digest,
    )
    canonical_path = _canonical_reservation_path(canonical_identity)
    _require_reservation_path_distinct(canonical_path, local_paths)
    if canonical_path.exists() or canonical_path.is_symlink():
        _load_canonical_reservation(canonical_identity)
        raise GuardedMigrationError(
            "canonical migration reservation exists; recovery is required before retry"
        )
    if environment == "production":
        target_baseline = _observe_remote_database(
            environment="production",
            phase="preflight",
            runner=runner,
        )
        staging_observation = _observe_remote_database(
            environment="staging",
            phase="postflight",
            runner=runner,
        )
        _reservation_path, hold = _create_canonical_unknown_reservation(
            identity=canonical_identity,
            reason="STAGING_SOURCE_SHA_EXECUTION_UNPROVEN",
            baseline=target_baseline,
            staging_observation=staging_observation,
            rollback_backup_digest=None,
        )
        report_unsigned = {
            "schema_version": "quant-ingest-migration-hold/v1",
            "status": "HOLD",
            "reason": "STAGING_SOURCE_SHA_EXECUTION_UNPROVEN",
            "environment": environment,
            "source_sha": source_sha,
            "canonical_manifest_digest": manifest_digest,
            "target_baseline": target_baseline,
            "staging_observation": staging_observation,
            "authoritative_reservation_digest": hold["reservation_digest"],
            "observed_at": _utc_now(),
        }
        report = {**report_unsigned, "evidence_digest": _digest(report_unsigned)}
        _publish_evidence(evidence_target, report)
        raise GuardedMigrationError(
            "production HOLD: canonical staging is exact, but trusted control-plane "
            "proof of the executing source SHA is unavailable"
        )
    version = runner((*prefix, "--version"), WORKER)
    if version.returncode != 0 or version.stdout.strip() != WRANGLER_VERSION:
        raise GuardedMigrationError("pinned Wrangler version is not active")
    common = _environment_args(binding)
    info = _run(
        runner,
        (*prefix, "d1", "info", binding["database_name"], "--json", *common),
        capture_json=True,
    )
    identity = _unique_mapping_with_identity(
        info, name=binding["database_name"], database_id=binding["database_id"]
    )
    bookmark_json = _run(
        runner,
        (
            *prefix,
            "d1",
            "time-travel",
            "info",
            binding["database_name"],
            "--json",
            *common,
        ),
        capture_json=True,
    )
    pre_apply_bookmark = _bookmark(bookmark_json)

    with tempfile.TemporaryDirectory(prefix="quant-ingest-guarded-migration-") as raw:
        directory = Path(raw)
        pre_export = directory / "preflight.sql"
        _run(
            runner,
            (
                *prefix,
                "d1",
                "export",
                binding["database_name"],
                "--remote",
                "--yes",
                "--output",
                str(pre_export),
                *common,
            ),
        )
        preflight = validate_export(
            pre_export, environment=environment, phase="preflight"
        )
        expected_pending = preflight.get("pending_migrations")
        if not isinstance(expected_pending, list):
            raise GuardedMigrationError("preflight pending migration evidence is malformed")
        pending_result = runner(
            (
                *prefix,
                "d1",
                "migrations",
                "list",
                binding["database_name"],
                "--remote",
                *common,
            ),
            WORKER,
        )
        if pending_result.returncode != 0:
            raise GuardedMigrationError("Wrangler pending-migration query failed")
        pending_digest = _validate_pending_inventory(
            pending_result.stdout,
            tuple(str(name) for name in expected_pending),
        )
        confirm_bookmark_json = _run(
            runner,
            (
                *prefix,
                "d1",
                "time-travel",
                "info",
                binding["database_name"],
                "--json",
                *common,
            ),
            capture_json=True,
        )
        if _bookmark(confirm_bookmark_json) != pre_apply_bookmark:
            raise GuardedMigrationError(
                "D1 changed while the rollback baseline was collected"
            )
        backup = encrypt_backup(
            pre_export,
            backup_target,
            backup_key,
            environment=environment,
            database_name=binding["database_name"],
            database_id=binding["database_id"],
            exported_at=_utc_now(),
            release_source_sha=source_sha,
        )
        verified_backup = verify_encrypted(backup_target, backup_key)
        if verified_backup != backup or backup["database"] != {
            "environment": environment,
            "name": binding["database_name"],
            "id": binding["database_id"],
            "schema_profile": f"quant-ingest-{environment}/v1",
        }:
            raise GuardedMigrationError("encrypted preflight backup is misbound")

        prepared_unsigned = {
            "schema_version": "quant-ingest-guarded-migration-prepared/v1",
            "status": "PREPARED_NO_APPLY",
            "environment": environment,
            "source_sha": source_sha,
            "canonical_manifest_digest": manifest_digest,
            "database": binding,
            "preflight": preflight,
            "backup": backup,
            "pre_apply_bookmark": pre_apply_bookmark,
            "live_identity_digest": _digest(identity),
            "time_travel_response_digest": _digest(bookmark_json),
            "time_travel_confirm_response_digest": _digest(
                confirm_bookmark_json
            ),
            "observed_at": _utc_now(),
        }
        prepared = {
            **prepared_unsigned,
            "evidence_digest": _digest(prepared_unsigned),
        }
        _publish_evidence(prepare_evidence_target, prepared)
        baseline = {
            "schema_version": "quant-ingest-live-d1-observation/v1",
            "environment": environment,
            "database": binding,
            "phase": "preflight",
            "live_identity_digest": _digest(identity),
            "time_travel_response_digest": _digest(bookmark_json),
            "time_travel_confirm_response_digest": _digest(
                confirm_bookmark_json
            ),
            "bookmark": pre_apply_bookmark,
            "validation": preflight,
            "pending_migrations": expected_pending,
            "pending_response_digest": pending_digest,
            "observed_at": _utc_now(),
        }
        _reservation_path, reservation = _create_canonical_unknown_reservation(
            identity=canonical_identity,
            reason="CROSS_HOST_EXCLUSION_UNPROVEN",
            baseline=baseline,
            staging_observation=None,
            rollback_backup_digest=str(backup["ciphertext_digest"]),
        )
        hold_unsigned = {
            "schema_version": "quant-ingest-migration-hold/v1",
            "status": "HOLD",
            "reason": "CROSS_HOST_EXCLUSION_UNPROVEN",
            "environment": environment,
            "source_sha": source_sha,
            "canonical_manifest_digest": manifest_digest,
            "database": binding,
            "preflight": preflight,
            "backup": backup,
            "pre_apply_bookmark": pre_apply_bookmark,
            "authoritative_reservation_digest": reservation[
                "reservation_digest"
            ],
            "observed_at": _utc_now(),
        }
        hold = {**hold_unsigned, "evidence_digest": _digest(hold_unsigned)}
        _publish_evidence(evidence_target, hold)
        raise GuardedMigrationError(
            "staging HOLD: no durable cross-host exclusive migration lock authority"
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--environment", choices=("staging", "production"), required=True)
    parser.add_argument("--recover", action="store_true")
    parser.add_argument("--backup-target", type=Path)
    parser.add_argument("--backup-key", type=Path)
    parser.add_argument("--prepare-evidence-target", type=Path)
    parser.add_argument("--evidence-target", type=Path)
    args = parser.parse_args(argv)
    if args.recover:
        if any(
            value is not None
            for value in (
                args.backup_target,
                args.backup_key,
                args.prepare_evidence_target,
                args.evidence_target,
            )
        ):
            parser.error("--recover does not accept caller evidence or backup paths")
        result = recover_guarded(environment=args.environment)
        print(
            json.dumps(
                {
                    "status": result["status"],
                    "reservation_digest": result["reservation_digest"],
                }
            )
        )
        return 0
    if any(
        value is None
        for value in (
            args.backup_target,
            args.backup_key,
            args.prepare_evidence_target,
            args.evidence_target,
        )
    ):
        parser.error(
            "apply preparation requires --backup-target, --backup-key, "
            "--prepare-evidence-target, and --evidence-target"
        )
    result = apply_guarded(
        environment=args.environment,
        backup_target=args.backup_target,
        backup_key=args.backup_key,
        prepare_evidence_target=args.prepare_evidence_target,
        evidence_target=args.evidence_target,
    )
    print(json.dumps({"status": result["status"], "evidence_digest": result["evidence_digest"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
