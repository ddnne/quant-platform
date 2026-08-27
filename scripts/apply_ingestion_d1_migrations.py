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
    if (
        raw.get("status") != "APPLIED_EXACT"
        or raw.get("environment") != "staging"
        or raw.get("source_sha") != source_sha
        or raw.get("canonical_manifest_digest") != manifest_digest
        or not isinstance(raw.get("postflight"), Mapping)
        or raw["postflight"].get("status") != "EXACT_POSTFLIGHT"
        or raw["postflight"].get("applied_migrations") != list(MIGRATION_NAMES)
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
) -> Mapping[str, Any]:
    observed = verify_encrypted(encrypted, key)
    if observed != evidence.get("backup"):
        raise GuardedMigrationError(
            "staging evidence does not match the authenticated backup artifact"
        )
    database = observed.get("database")
    if not isinstance(database, Mapping) or database.get("environment") != "staging":
        raise GuardedMigrationError("staging backup artifact is environment-misbound")
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


def _publish_evidence(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(_canonical_bytes(payload) + b"\n")
            handle.flush()
            os.fsync(handle.fileno())
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
        )
    elif any(
        value is not None
        for value in (staging_evidence, staging_backup, staging_backup_key)
    ):
        raise GuardedMigrationError("staging does not accept production evidence")

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
        "live_identity_digest": _digest(identity),
        "time_travel_response_digest": _digest(bookmark_json),
        "wrangler_pending_digest": pending_digest,
        "observed_at": _utc_now(),
    }
    payload = {**unsigned, "evidence_digest": _digest(unsigned)}
    _publish_evidence(evidence_target, payload)
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
