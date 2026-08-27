#!/usr/bin/env python3
"""Canonical, staging-first Wrangler owner for quant-ingest migrations.

This is the only documented remote apply entrypoint for migrations 0011+.
Database identity and Wrangler configuration come from the frozen canonical
manifest, never caller input.  The command captures an encrypted, checksummed
pre-apply export and Time Travel bookmark, proves an exact/resumable preflight
on that export, applies through the canonical owner, exports independently for
exact postflight, and publishes create-only evidence.  Production additionally
requires accepted staging evidence for the same source and manifest.
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
from scripts.encrypt_d1_backup import (
    _governed_database,
    encrypt_backup,
    verify_encrypted,
)


ROOT = Path(__file__).resolve().parents[1]
WORKER = ROOT / "platform" / "workers" / "ingestion-premium"
WRANGLER_VERSION = "4.125.0"
_SHA = re.compile(r"^[0-9a-f]{40}$")
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


def _source_sha(runner: Runner) -> str:
    head = runner(("git", "rev-parse", "HEAD"), ROOT)
    status = runner(("git", "status", "--porcelain"), ROOT)
    sha = head.stdout.strip()
    if head.returncode != 0 or not _SHA.fullmatch(sha):
        raise GuardedMigrationError("release source SHA is unavailable")
    if status.returncode != 0 or status.stdout.strip():
        raise GuardedMigrationError("migration owner requires a clean worktree")
    return sha


def validate_staging_acceptance(
    path: Path,
    *,
    source_sha: str,
    manifest_digest: str,
) -> Mapping[str, Any]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise GuardedMigrationError("staging migration evidence is unreadable") from exc
    required = {
        "schema_version",
        "status",
        "environment",
        "source_sha",
        "canonical_manifest_digest",
        "database",
        "preflight",
        "postflight",
        "backup",
        "pre_apply_bookmark",
        "prepared_evidence_digest",
        "reservation_digest",
        "live_identity_digest",
        "time_travel_response_digest",
        "wrangler_pending_digest",
        "observed_at",
        "evidence_digest",
    }
    if not isinstance(raw, Mapping) or set(raw) != required:
        raise GuardedMigrationError("staging migration evidence schema is invalid")
    unsigned = {key: raw[key] for key in raw if key != "evidence_digest"}
    if raw.get("evidence_digest") != _digest(unsigned):
        raise GuardedMigrationError("staging migration evidence digest is invalid")
    binding = canonical_binding("staging")
    backup_identity = _governed_database("staging")
    backup = raw.get("backup")
    restore = backup.get("restore") if isinstance(backup, Mapping) else None
    preflight = raw.get("preflight")
    simulated = (
        preflight.get("simulated_postflight")
        if isinstance(preflight, Mapping)
        else None
    )
    postflight = raw.get("postflight")
    if (
        raw.get("status") != "APPLIED_EXACT"
        or raw.get("environment") != "staging"
        or raw.get("source_sha") != source_sha
        or raw.get("canonical_manifest_digest") != manifest_digest
        or raw.get("database") != binding
        or not isinstance(backup, Mapping)
        or backup.get("database") != backup_identity
        or not isinstance(restore, Mapping)
        or restore.get("source_sha") != source_sha
        or not isinstance(preflight, Mapping)
        or preflight.get("status")
        not in {"RESUMABLE_EXACT_PREFIX", "ALREADY_EXACT"}
        or preflight.get("environment") != "staging"
        or preflight.get("database") != binding
        or preflight.get("canonical_manifest_digest") != manifest_digest
        or not isinstance(simulated, Mapping)
        or simulated.get("environment") != "staging"
        or simulated.get("database") != binding
        or simulated.get("canonical_manifest_digest") != manifest_digest
        or not isinstance(postflight, Mapping)
        or postflight.get("status") != "EXACT_POSTFLIGHT"
        or postflight.get("environment") != "staging"
        or postflight.get("database") != binding
        or postflight.get("canonical_manifest_digest") != manifest_digest
        or postflight.get("applied_migrations") != list(MIGRATION_NAMES)
    ):
        raise GuardedMigrationError(
            "production requires exact same-source staging migration acceptance"
        )
    return raw


def validate_staging_artifact(
    evidence: Mapping[str, Any],
    *,
    encrypted: Path,
    key: Path,
    source_sha: str,
    manifest_digest: str,
) -> Mapping[str, Any]:
    observed = verify_encrypted(encrypted, key)
    if observed != evidence.get("backup"):
        raise GuardedMigrationError(
            "staging evidence does not match the authenticated backup artifact"
        )
    database = observed.get("database")
    restore = observed.get("restore")
    if (
        database != _governed_database("staging")
        or not isinstance(restore, Mapping)
        or restore.get("source_sha") != source_sha
        or evidence.get("source_sha") != source_sha
        or evidence.get("canonical_manifest_digest") != manifest_digest
        or evidence.get("database") != canonical_binding("staging")
    ):
        raise GuardedMigrationError("staging backup artifact cross-binding is invalid")
    return observed


def _validate_pending_output(value: str) -> str:
    lines = tuple(line.strip() for line in value.splitlines() if line.strip())
    if (
        "✅ No migrations to apply!" not in lines
        or any("Migrations to be applied:" in line for line in lines)
    ):
        raise GuardedMigrationError("Wrangler does not prove an empty pending set")
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
    environment: str,
    backup_target: Path,
    backup_key: Path,
    prepare_evidence_target: Path,
    evidence_target: Path,
    staging_evidence: Path | None,
    staging_backup: Path | None,
    staging_backup_key: Path | None,
) -> dict[str, Path | None]:
    paths: dict[str, Path | None] = {
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
        "staging_evidence": None,
        "staging_backup": None,
        "staging_backup_key": None,
    }
    staging_values = (staging_evidence, staging_backup, staging_backup_key)
    if environment == "production":
        if any(value is None for value in staging_values):
            raise GuardedMigrationError(
                "production requires staging evidence, backup, and key"
            )
        assert staging_evidence is not None
        assert staging_backup is not None
        assert staging_backup_key is not None
        paths["staging_evidence"] = _secure_input(
            staging_evidence, label="staging evidence"
        )
        paths["staging_backup"] = _secure_input(
            staging_backup, label="staging backup"
        )
        paths["staging_backup_key"] = _secure_input(
            staging_backup_key, label="staging backup key"
        )
    elif any(value is not None for value in staging_values):
        raise GuardedMigrationError("staging does not accept production evidence")

    present = [path for path in paths.values() if path is not None]
    if len(present) != len(set(present)):
        raise GuardedMigrationError(
            "backup, evidence, key, and staging paths must be resolve-distinct"
        )
    return paths


def _read_exact_evidence(path: Path) -> Mapping[str, Any]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise GuardedMigrationError("reserved final evidence is unreadable") from exc
    if not isinstance(raw, Mapping):
        raise GuardedMigrationError("reserved final evidence is malformed")
    return raw


def _reserve_final_evidence(
    path: Path,
    *,
    environment: str,
    source_sha: str,
    manifest_digest: str,
    prepared_evidence_digest: str,
    backup_digest: str,
    pre_apply_bookmark: str,
) -> dict[str, Any]:
    unsigned = {
        "schema_version": "quant-ingest-guarded-migration-reservation/v1",
        "status": "REMOTE_APPLY_AUTHORIZED_STATE_UNKNOWN_UNTIL_FINALIZED",
        "environment": environment,
        "source_sha": source_sha,
        "canonical_manifest_digest": manifest_digest,
        "prepared_evidence_digest": prepared_evidence_digest,
        "backup_digest": backup_digest,
        "pre_apply_bookmark": pre_apply_bookmark,
        "reservation_nonce": secrets.token_hex(32),
        "reserved_at": _utc_now(),
    }
    reservation = {**unsigned, "reservation_digest": _digest(unsigned)}
    _publish_evidence(path, reservation)
    return reservation


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


def apply_guarded(
    *,
    environment: str,
    backup_target: Path,
    backup_key: Path,
    prepare_evidence_target: Path,
    evidence_target: Path,
    staging_evidence: Path | None = None,
    staging_backup: Path | None = None,
    staging_backup_key: Path | None = None,
    runner: Runner = _default_runner,
) -> dict[str, Any]:
    local_paths = _preflight_local_paths(
        environment=environment,
        backup_target=backup_target,
        backup_key=backup_key,
        prepare_evidence_target=prepare_evidence_target,
        evidence_target=evidence_target,
        staging_evidence=staging_evidence,
        staging_backup=staging_backup,
        staging_backup_key=staging_backup_key,
    )
    backup_target = local_paths["backup_target"]  # type: ignore[assignment]
    backup_key = local_paths["backup_key"]  # type: ignore[assignment]
    prepare_evidence_target = local_paths["prepare_evidence_target"]  # type: ignore[assignment]
    evidence_target = local_paths["evidence_target"]  # type: ignore[assignment]
    staging_evidence = local_paths["staging_evidence"]
    staging_backup = local_paths["staging_backup"]
    staging_backup_key = local_paths["staging_backup_key"]
    assert isinstance(backup_target, Path)
    assert isinstance(backup_key, Path)
    assert isinstance(prepare_evidence_target, Path)
    assert isinstance(evidence_target, Path)
    prefix, binding = _wrangler_prefix(environment)
    source_sha = _source_sha(runner)
    _target, manifest_digest = _canonical_target()
    if environment == "production":
        if staging_evidence is None:
            raise GuardedMigrationError(
                "production migration requires staging acceptance evidence"
            )
        accepted_staging = validate_staging_acceptance(
            staging_evidence,
            source_sha=source_sha,
            manifest_digest=manifest_digest,
        )
        if staging_backup is None or staging_backup_key is None:
            raise GuardedMigrationError(
                "production requires the authenticated staging backup and key"
            )
        validate_staging_artifact(
            accepted_staging,
            encrypted=staging_backup,
            key=staging_backup_key,
            source_sha=source_sha,
            manifest_digest=manifest_digest,
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
        require_exact_cutover = _requires_exact_cutover(preflight)
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
            "observed_at": _utc_now(),
        }
        prepared = {
            **prepared_unsigned,
            "evidence_digest": _digest(prepared_unsigned),
        }
        _publish_evidence(prepare_evidence_target, prepared)
        reservation = _reserve_final_evidence(
            evidence_target,
            environment=environment,
            source_sha=source_sha,
            manifest_digest=manifest_digest,
            prepared_evidence_digest=str(prepared["evidence_digest"]),
            backup_digest=str(backup["ciphertext_digest"]),
            pre_apply_bookmark=pre_apply_bookmark,
        )

        _run(
            runner,
            (
                *prefix,
                "d1",
                "migrations",
                "apply",
                binding["database_name"],
                "--remote",
                *common,
            ),
        )
        post_export = directory / "postflight.sql"
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
                str(post_export),
                *common,
            ),
        )
        postflight = validate_export(
            post_export,
            environment=environment,
            phase="postflight",
            require_exact_cutover=require_exact_cutover,
        )
        post_export.unlink(missing_ok=True)
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
        pending_digest = _validate_pending_output(pending_result.stdout)

    unsigned = {
        "schema_version": "quant-ingest-guarded-migration-evidence/v1",
        "status": "APPLIED_EXACT",
        "environment": environment,
        "source_sha": source_sha,
        "canonical_manifest_digest": manifest_digest,
        "database": binding,
        "preflight": preflight,
        "postflight": postflight,
        "backup": backup,
        "pre_apply_bookmark": pre_apply_bookmark,
        "prepared_evidence_digest": prepared["evidence_digest"],
        "reservation_digest": reservation["reservation_digest"],
        "live_identity_digest": _digest(identity),
        "time_travel_response_digest": _digest(bookmark_json),
        "wrangler_pending_digest": pending_digest,
        "observed_at": _utc_now(),
    }
    payload = {**unsigned, "evidence_digest": _digest(unsigned)}
    _finalize_reserved_evidence(
        evidence_target,
        reservation=reservation,
        payload=payload,
    )
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--environment", choices=("staging", "production"), required=True)
    parser.add_argument("--backup-target", type=Path, required=True)
    parser.add_argument("--backup-key", type=Path, required=True)
    parser.add_argument("--prepare-evidence-target", type=Path, required=True)
    parser.add_argument("--evidence-target", type=Path, required=True)
    parser.add_argument("--staging-evidence", type=Path)
    parser.add_argument("--staging-backup", type=Path)
    parser.add_argument("--staging-backup-key", type=Path)
    args = parser.parse_args(argv)
    result = apply_guarded(
        environment=args.environment,
        backup_target=args.backup_target,
        backup_key=args.backup_key,
        prepare_evidence_target=args.prepare_evidence_target,
        evidence_target=args.evidence_target,
        staging_evidence=args.staging_evidence,
        staging_backup=args.staging_backup,
        staging_backup_key=args.staging_backup_key,
    )
    print(json.dumps({"status": result["status"], "evidence_digest": result["evidence_digest"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
