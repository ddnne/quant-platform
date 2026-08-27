"""Behavioral gates around the fail-closed canonical D1 migration owner."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
from typing import Any, Mapping, Sequence

import pytest

from scripts import apply_ingestion_d1_migrations as owner
from scripts.d1_ingestion_migration_validation import (
    MIGRATION_NAMES,
    canonical_binding,
)
from scripts.encrypt_d1_backup import _governed_database


SHA = "a" * 40
OTHER_SHA = "b" * 40
MANIFEST_DIGEST = "sha256:" + "c" * 64
BOOKMARK = "00000001-00000002-00000003-" + "d" * 32


def _postflight(environment: str, manifest_digest: str) -> dict[str, Any]:
    return {
        "status": "EXACT_POSTFLIGHT",
        "environment": environment,
        "database": canonical_binding(environment),
        "canonical_manifest_digest": manifest_digest,
        "applied_migrations": list(MIGRATION_NAMES),
        "foreign_key_check": "PASS",
        "preservation": {
            "jobs": {"missing_rows": 0},
            "events": {"missing_rows": 0},
            "discoveries": {"missing_rows": 0},
        },
    }


def _preflight(
    environment: str,
    manifest_digest: str,
    *,
    pending: Sequence[str] | None = None,
) -> dict[str, Any]:
    pending_names = list(pending if pending is not None else MIGRATION_NAMES[11:])
    return {
        "status": "RESUMABLE_EXACT_PREFIX" if pending_names else "ALREADY_EXACT",
        "environment": environment,
        "database": canonical_binding(environment),
        "canonical_manifest_digest": manifest_digest,
        "applied_migrations": list(MIGRATION_NAMES[: -len(pending_names)])
        if pending_names
        else list(MIGRATION_NAMES),
        "pending_migrations": pending_names,
        "simulated_postflight": _postflight(environment, manifest_digest),
    }


def _observation(
    environment: str,
    phase: str,
    manifest_digest: str,
    *,
    bookmark: str = BOOKMARK,
    pending: Sequence[str] | None = None,
) -> dict[str, Any]:
    validation = (
        _postflight(environment, manifest_digest)
        if phase == "postflight"
        else _preflight(environment, manifest_digest, pending=pending)
    )
    pending_names = [] if phase == "postflight" else validation["pending_migrations"]
    return {
        "schema_version": "quant-ingest-live-d1-observation/v1",
        "environment": environment,
        "database": canonical_binding(environment),
        "phase": phase,
        "live_identity_digest": "sha256:" + "1" * 64,
        "time_travel_response_digest": "sha256:" + "2" * 64,
        "bookmark": bookmark,
        "validation": validation,
        "pending_migrations": list(pending_names),
        "pending_response_digest": "sha256:" + "3" * 64,
        "observed_at": "2026-08-27T00:00:00Z",
    }


def _private_key(tmp_path: Path) -> Path:
    key = tmp_path / "backup.key"
    key.write_bytes(b"k" * 32)
    key.chmod(0o600)
    return key


def _apply_paths(tmp_path: Path) -> dict[str, Path]:
    return {
        "backup_target": tmp_path / "backup.enc",
        "backup_key": _private_key(tmp_path),
        "prepare_evidence_target": tmp_path / "prepared.json",
        "evidence_target": tmp_path / "final.json",
    }


def _canonical_identity(environment: str, manifest_digest: str) -> dict[str, Any]:
    return owner._canonical_reservation_identity(
        environment=environment,
        source_sha=SHA,
        manifest_digest=manifest_digest,
    )


def test_live_identity_and_bookmark_must_be_unique_and_exact() -> None:
    binding = canonical_binding("staging")
    observed = {
        "result": {
            "name": binding["database_name"],
            "uuid": binding["database_id"],
        }
    }
    row = owner._unique_mapping_with_identity(
        observed,
        name=binding["database_name"],
        database_id=binding["database_id"],
    )
    assert row["uuid"] == binding["database_id"]
    with pytest.raises(owner.GuardedMigrationError, match="absent or ambiguous"):
        owner._unique_mapping_with_identity(
            {"result": [observed["result"], observed["result"]]},
            name=binding["database_name"],
            database_id=binding["database_id"],
        )
    with pytest.raises(owner.GuardedMigrationError, match="absent or ambiguous"):
        owner._unique_mapping_with_identity(
            {"name": "quant-ingest", "uuid": binding["database_id"]},
            name=binding["database_name"],
            database_id=binding["database_id"],
        )
    assert owner._bookmark({"current_bookmark": BOOKMARK}) == BOOKMARK
    with pytest.raises(owner.GuardedMigrationError, match="ambiguous"):
        owner._bookmark(
            {
                "current_bookmark": BOOKMARK,
                "other_bookmark": "00000004-00000005-00000006-" + "e" * 32,
            }
        )


def test_pending_inventory_must_be_exact_or_prove_empty() -> None:
    pending = tuple(MIGRATION_NAMES[11:])
    output = "Migrations to be applied:\n" + "\n".join(pending) + "\n"
    assert owner._validate_pending_inventory(output, pending).startswith("sha256:")
    assert owner._validate_pending_inventory(
        "checking remote D1\n✅ No migrations to apply!\n", ()
    ).startswith("sha256:")
    with pytest.raises(owner.GuardedMigrationError, match="canonical history"):
        owner._validate_pending_inventory(output, tuple(reversed(pending)))
    with pytest.raises(owner.GuardedMigrationError, match="empty pending"):
        owner._validate_pending_inventory(output, ())


def test_live_observation_queries_only_canonical_staging_and_validates_export(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    binding = canonical_binding("staging")
    _target, manifest_digest = owner._canonical_target()
    observed_validation = _postflight("staging", manifest_digest)
    calls: list[tuple[str, ...]] = []
    validated: list[tuple[Path, str, str]] = []
    monkeypatch.setattr(
        owner, "_wrangler_prefix", lambda environment: (["wrangler"], canonical_binding(environment))
    )

    def validate(path: Path, *, environment: str, phase: str) -> dict[str, Any]:
        validated.append((path, environment, phase))
        assert path.read_text(encoding="utf-8") == "-- canonical live export\n"
        return observed_validation

    monkeypatch.setattr(owner, "validate_export", validate)

    def runner(argv: Sequence[str], _cwd: Path) -> subprocess.CompletedProcess[str]:
        args = tuple(argv)
        calls.append(args)
        if args == ("wrangler", "--version"):
            return subprocess.CompletedProcess(args, 0, owner.WRANGLER_VERSION, "")
        if args[1:3] == ("d1", "info"):
            assert binding["database_name"] in args
            return subprocess.CompletedProcess(
                args,
                0,
                json.dumps(
                    {"name": binding["database_name"], "uuid": binding["database_id"]}
                ),
                "",
            )
        if args[1:4] == ("d1", "time-travel", "info"):
            return subprocess.CompletedProcess(
                args, 0, json.dumps({"current_bookmark": BOOKMARK}), ""
            )
        if args[1:3] == ("d1", "export"):
            output = Path(args[args.index("--output") + 1])
            output.write_text("-- canonical live export\n", encoding="utf-8")
            return subprocess.CompletedProcess(args, 0, "exported", "")
        if args[1:4] == ("d1", "migrations", "list"):
            return subprocess.CompletedProcess(
                args, 0, "✅ No migrations to apply!\n", ""
            )
        raise AssertionError(args)

    result = owner._observe_remote_database(
        environment="staging", phase="postflight", runner=runner
    )
    assert result["database"] == binding
    assert result["validation"] == observed_validation
    assert result["pending_migrations"] == []
    assert validated and validated[0][1:] == ("staging", "postflight")
    assert any(args[1:3] == ("d1", "info") for args in calls)
    assert any(args[1:4] == ("d1", "time-travel", "info") for args in calls)
    assert any(args[1:3] == ("d1", "export") for args in calls)
    assert any(args[1:4] == ("d1", "migrations", "list") for args in calls)


def test_live_observation_rejects_wrong_database_and_pending_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    binding = canonical_binding("staging")
    _target, manifest_digest = owner._canonical_target()
    monkeypatch.setattr(owner, "_wrangler_prefix", lambda _environment: (["wrangler"], binding))
    monkeypatch.setattr(
        owner,
        "validate_export",
        lambda _path, *, environment, phase: _postflight(environment, manifest_digest),
    )

    def wrong_identity(argv: Sequence[str], _cwd: Path) -> subprocess.CompletedProcess[str]:
        args = tuple(argv)
        if args == ("wrangler", "--version"):
            return subprocess.CompletedProcess(args, 0, owner.WRANGLER_VERSION, "")
        if args[1:3] == ("d1", "info"):
            return subprocess.CompletedProcess(
                args,
                0,
                json.dumps({"name": binding["database_name"], "uuid": "f" * 36}),
                "",
            )
        raise AssertionError(args)

    with pytest.raises(owner.GuardedMigrationError, match="identity"):
        owner._observe_remote_database(
            environment="staging", phase="postflight", runner=wrong_identity
        )

    def wrong_pending(argv: Sequence[str], _cwd: Path) -> subprocess.CompletedProcess[str]:
        args = tuple(argv)
        if args == ("wrangler", "--version"):
            return subprocess.CompletedProcess(args, 0, owner.WRANGLER_VERSION, "")
        if args[1:3] == ("d1", "info"):
            return subprocess.CompletedProcess(
                args,
                0,
                json.dumps({"name": binding["database_name"], "uuid": binding["database_id"]}),
                "",
            )
        if args[1:4] == ("d1", "time-travel", "info"):
            return subprocess.CompletedProcess(
                args, 0, json.dumps({"current_bookmark": BOOKMARK}), ""
            )
        if args[1:3] == ("d1", "export"):
            return subprocess.CompletedProcess(args, 0, "exported", "")
        if args[1:4] == ("d1", "migrations", "list"):
            return subprocess.CompletedProcess(
                args, 0, f"Migrations to be applied:\n{MIGRATION_NAMES[-1]}\n", ""
            )
        raise AssertionError(args)

    with pytest.raises(owner.GuardedMigrationError, match="empty pending"):
        owner._observe_remote_database(
            environment="staging", phase="postflight", runner=wrong_pending
        )


def test_live_observation_rejects_a_bookmark_change_during_collection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    binding = canonical_binding("staging")
    _target, manifest_digest = owner._canonical_target()
    monkeypatch.setattr(owner, "_wrangler_prefix", lambda _environment: (["wrangler"], binding))
    monkeypatch.setattr(
        owner,
        "validate_export",
        lambda _path, *, environment, phase: _postflight(environment, manifest_digest),
    )
    bookmark_queries = 0

    def runner(argv: Sequence[str], _cwd: Path) -> subprocess.CompletedProcess[str]:
        nonlocal bookmark_queries
        args = tuple(argv)
        if args == ("wrangler", "--version"):
            return subprocess.CompletedProcess(args, 0, owner.WRANGLER_VERSION, "")
        if args[1:3] == ("d1", "info"):
            return subprocess.CompletedProcess(
                args,
                0,
                json.dumps({"name": binding["database_name"], "uuid": binding["database_id"]}),
                "",
            )
        if args[1:4] == ("d1", "time-travel", "info"):
            bookmark_queries += 1
            bookmark = (
                BOOKMARK
                if bookmark_queries == 1
                else "00000004-00000005-00000006-" + "e" * 32
            )
            return subprocess.CompletedProcess(
                args, 0, json.dumps({"current_bookmark": bookmark}), ""
            )
        if args[1:3] == ("d1", "export"):
            return subprocess.CompletedProcess(args, 0, "exported", "")
        if args[1:4] == ("d1", "migrations", "list"):
            return subprocess.CompletedProcess(
                args, 0, "✅ No migrations to apply!\n", ""
            )
        raise AssertionError(args)

    with pytest.raises(owner.GuardedMigrationError, match="changed while"):
        owner._observe_remote_database(
            environment="staging", phase="postflight", runner=runner
        )


def test_canonical_reservation_is_exclusive_environment_bound_and_tamper_evident(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(owner, "CANONICAL_RESERVATION_ROOT", tmp_path / "state")
    identity = _canonical_identity("staging", MANIFEST_DIGEST)
    path, reservation = owner._create_canonical_unknown_reservation(
        identity=identity,
        reason="CROSS_HOST_EXCLUSION_UNPROVEN",
        baseline=_observation("staging", "preflight", MANIFEST_DIGEST),
        staging_observation=None,
        rollback_backup_digest="sha256:" + "4" * 64,
    )
    binding = canonical_binding("staging")
    assert path == (
        owner.CANONICAL_RESERVATION_ROOT
        / "staging"
        / binding["database_id"]
        / SHA
        / f"{owner._digest(identity).removeprefix('sha256:')}.json"
    )
    assert path.stat().st_mode & 0o077 == 0
    assert reservation["status"] == "UNKNOWN"
    assert reservation["reservation_id"] == owner._digest(
        {"identity": identity, "nonce": reservation["reservation_nonce"]}
    )
    assert owner._load_canonical_reservation(identity) == (path, reservation)
    with pytest.raises(owner.GuardedMigrationError, match="already exists"):
        owner._create_canonical_unknown_reservation(
            identity=identity,
            reason="forged-run",
            baseline=None,
            staging_observation=None,
            rollback_backup_digest=None,
        )

    forged = dict(reservation)
    forged["reservation_nonce"] = "f" * 64
    path.write_text(json.dumps(forged), encoding="utf-8")
    with pytest.raises(owner.GuardedMigrationError, match="binding"):
        owner._load_canonical_reservation(identity)

    for environment, source_sha, digest in (
        ("production", SHA, MANIFEST_DIGEST),
        ("staging", OTHER_SHA, MANIFEST_DIGEST),
        ("staging", SHA, "sha256:" + "e" * 64),
    ):
        other = owner._canonical_reservation_identity(
            environment=environment,
            source_sha=source_sha,
            manifest_digest=digest,
        )
        assert owner._canonical_reservation_path(other) != path


def test_canonical_reservation_rejects_symlink_store_and_caller_path_collision(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    real = tmp_path / "real"
    real.mkdir()
    alias = tmp_path / "alias"
    alias.symlink_to(real, target_is_directory=True)
    monkeypatch.setattr(owner, "CANONICAL_RESERVATION_ROOT", alias)
    identity = _canonical_identity("staging", MANIFEST_DIGEST)
    with pytest.raises(owner.GuardedMigrationError, match="permissions are unsafe"):
        owner._create_canonical_unknown_reservation(
            identity=identity,
            reason="CROSS_HOST_EXCLUSION_UNPROVEN",
            baseline=None,
            staging_observation=None,
            rollback_backup_digest=None,
        )

    canonical_root = tmp_path / "canonical"
    monkeypatch.setattr(owner, "CANONICAL_RESERVATION_ROOT", canonical_root)
    identity = _canonical_identity("staging", MANIFEST_DIGEST)
    canonical_path = owner._canonical_reservation_path(identity)
    canonical_path.parent.mkdir(parents=True, mode=0o700)
    paths = _apply_paths(tmp_path)
    paths["evidence_target"] = canonical_path
    monkeypatch.setattr(owner, "_source_sha", lambda _runner: SHA)
    monkeypatch.setattr(owner, "_canonical_target", lambda: ({}, MANIFEST_DIGEST))
    monkeypatch.setattr(
        owner, "_wrangler_prefix", lambda environment: (["wrangler"], canonical_binding(environment))
    )
    with pytest.raises(owner.GuardedMigrationError, match="collides"):
        owner.apply_guarded(environment="staging", **paths)


def test_local_artifact_paths_are_distinct_create_only_and_private(
    tmp_path: Path,
) -> None:
    key = _private_key(tmp_path)
    paths = owner._preflight_local_paths(
        backup_target=tmp_path / "backup.enc",
        backup_key=key,
        prepare_evidence_target=tmp_path / "prepared.json",
        evidence_target=tmp_path / "final.json",
    )
    assert len(set(paths.values())) == 4
    collision = tmp_path / "collision.json"
    with pytest.raises(owner.GuardedMigrationError, match="resolve-distinct"):
        owner._preflight_local_paths(
            backup_target=tmp_path / "second.enc",
            backup_key=key,
            prepare_evidence_target=collision,
            evidence_target=collision,
        )
    existing = tmp_path / "existing.json"
    existing.write_text("occupied", encoding="utf-8")
    with pytest.raises(owner.GuardedMigrationError, match="already exists"):
        owner._secure_create_target(existing, label="final evidence")
    unsafe = tmp_path / "unsafe"
    unsafe.mkdir(mode=0o777)
    unsafe.chmod(0o777)
    with pytest.raises(owner.GuardedMigrationError, match="permissions"):
        owner._secure_create_target(unsafe / "final.json", label="final evidence")


def test_production_reobserves_live_staging_and_refuses_aes_or_json_authority(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _target, manifest_digest = owner._canonical_target()
    monkeypatch.setattr(owner, "CANONICAL_RESERVATION_ROOT", tmp_path / "state")
    monkeypatch.setattr(owner, "_source_sha", lambda _runner: SHA)
    monkeypatch.setattr(
        owner, "_wrangler_prefix", lambda environment: (["wrangler"], canonical_binding(environment))
    )
    calls: list[tuple[str, str]] = []

    def observe(*, environment: str, phase: str, runner: owner.Runner) -> dict[str, Any]:
        del runner
        calls.append((environment, phase))
        return _observation(environment, phase, manifest_digest, pending=[])

    monkeypatch.setattr(owner, "_observe_remote_database", observe)
    monkeypatch.setattr(
        owner,
        "verify_encrypted",
        lambda *_args: (_ for _ in ()).throw(AssertionError("AES cannot authorize production")),
    )
    paths = _apply_paths(tmp_path)
    with pytest.raises(owner.GuardedMigrationError, match="trusted control-plane"):
        owner.apply_guarded(environment="production", **paths)
    assert calls == [("production", "preflight"), ("staging", "postflight")]
    identity = owner._canonical_reservation_identity(
        environment="production",
        source_sha=SHA,
        manifest_digest=manifest_digest,
    )
    _path, reservation = owner._load_canonical_reservation(identity)
    assert reservation["status"] == "UNKNOWN"
    assert reservation["reason"] == "STAGING_SOURCE_SHA_EXECUTION_UNPROVEN"
    assert reservation["baseline"]["database"] == canonical_binding("production")
    assert reservation["staging_observation"]["database"] == canonical_binding("staging")
    report = owner._read_exact_evidence(paths["evidence_target"])
    assert report["status"] == "HOLD"
    assert report["reason"] == "STAGING_SOURCE_SHA_EXECUTION_UNPROVEN"
    assert not hasattr(owner, "validate_staging_acceptance")
    assert not hasattr(owner, "validate_staging_artifact")


def test_staging_backup_is_rollback_only_and_cross_host_lock_keeps_apply_on_hold(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    binding = canonical_binding("staging")
    _target, manifest_digest = owner._canonical_target()
    pending = tuple(MIGRATION_NAMES[11:])
    preflight = _preflight("staging", manifest_digest, pending=pending)
    backup = {
        "ciphertext_digest": "sha256:" + "9" * 64,
        "database": _governed_database("staging"),
        "restore": {"source_sha": SHA},
    }
    monkeypatch.setattr(owner, "CANONICAL_RESERVATION_ROOT", tmp_path / "state")
    monkeypatch.setattr(owner, "_source_sha", lambda _runner: SHA)
    monkeypatch.setattr(owner, "_wrangler_prefix", lambda _environment: (["wrangler"], binding))
    monkeypatch.setattr(
        owner,
        "validate_export",
        lambda _path, *, environment, phase: preflight,
    )

    def encrypt(_source: Path, target: Path, _key: Path, **_kwargs: object) -> Mapping[str, Any]:
        target.write_bytes(b"encrypted rollback artifact")
        return backup

    monkeypatch.setattr(owner, "encrypt_backup", encrypt)
    monkeypatch.setattr(owner, "verify_encrypted", lambda *_args: backup)
    remote_apply_seen = False

    def runner(argv: Sequence[str], _cwd: Path) -> subprocess.CompletedProcess[str]:
        nonlocal remote_apply_seen
        args = tuple(argv)
        if args == ("wrangler", "--version"):
            return subprocess.CompletedProcess(args, 0, owner.WRANGLER_VERSION, "")
        if args[1:3] == ("d1", "info"):
            return subprocess.CompletedProcess(
                args,
                0,
                json.dumps({"name": binding["database_name"], "uuid": binding["database_id"]}),
                "",
            )
        if args[1:4] == ("d1", "time-travel", "info"):
            return subprocess.CompletedProcess(
                args, 0, json.dumps({"current_bookmark": BOOKMARK}), ""
            )
        if args[1:3] == ("d1", "export"):
            return subprocess.CompletedProcess(args, 0, "exported", "")
        if args[1:4] == ("d1", "migrations", "list"):
            output = "Migrations to be applied:\n" + "\n".join(pending) + "\n"
            return subprocess.CompletedProcess(args, 0, output, "")
        if args[1:4] == ("d1", "migrations", "apply"):
            remote_apply_seen = True
            raise AssertionError("remote apply must remain structurally unreachable")
        raise AssertionError(args)

    paths = _apply_paths(tmp_path)
    with pytest.raises(owner.GuardedMigrationError, match="cross-host"):
        owner.apply_guarded(environment="staging", runner=runner, **paths)
    assert not remote_apply_seen
    identity = owner._canonical_reservation_identity(
        environment="staging", source_sha=SHA, manifest_digest=manifest_digest
    )
    _path, reservation = owner._load_canonical_reservation(identity)
    assert reservation["status"] == "UNKNOWN"
    assert reservation["reason"] == "CROSS_HOST_EXCLUSION_UNPROVEN"
    assert reservation["rollback_backup_digest"] == backup["ciphertext_digest"]
    assert owner._read_exact_evidence(paths["evidence_target"])["status"] == "HOLD"


def _reserve_for_recovery(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    environment: str = "staging",
) -> tuple[dict[str, Any], dict[str, Any], str]:
    monkeypatch.setattr(owner, "CANONICAL_RESERVATION_ROOT", tmp_path / "state")
    _target, manifest_digest = owner._canonical_target()
    identity = owner._canonical_reservation_identity(
        environment=environment,
        source_sha=SHA,
        manifest_digest=manifest_digest,
    )
    baseline = _observation(environment, "preflight", manifest_digest)
    owner._create_canonical_unknown_reservation(
        identity=identity,
        reason="CROSS_HOST_EXCLUSION_UNPROVEN",
        baseline=baseline,
        staging_observation=None,
        rollback_backup_digest="sha256:" + "7" * 64,
    )
    monkeypatch.setattr(owner, "_source_sha", lambda _runner: SHA)
    return identity, baseline, manifest_digest


def test_recovery_finalizes_applied_only_from_live_exact_postflight(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    identity, _baseline, manifest_digest = _reserve_for_recovery(tmp_path, monkeypatch)
    postflight = _observation("staging", "postflight", manifest_digest)
    monkeypatch.setattr(owner, "_observe_remote_database", lambda **_kwargs: postflight)
    result = owner.recover_guarded(environment="staging")
    assert result["status"] == "RECOVERED_APPLIED_EXACT"
    assert result["recovery"] == {
        "source_sha_execution": "UNPROVEN",
        "observation": postflight,
    }
    assert owner._load_canonical_reservation(identity)[1] == result
    with pytest.raises(owner.GuardedMigrationError, match="does not require"):
        owner.recover_guarded(environment="staging")


def test_recovery_finalizes_not_applied_only_when_exact_baseline_is_unchanged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    identity, baseline, _manifest_digest = _reserve_for_recovery(tmp_path, monkeypatch)

    def observe(*, phase: str, **_kwargs: object) -> dict[str, Any]:
        if phase == "postflight":
            raise owner.IngestionMigrationError("not postflight")
        return baseline

    monkeypatch.setattr(owner, "_observe_remote_database", observe)
    result = owner.recover_guarded(environment="staging")
    assert result["status"] == "RECOVERED_NOT_APPLIED"
    assert result["recovery"]["observation"]["bookmark"] == BOOKMARK
    assert owner._load_canonical_reservation(identity)[1] == result


def test_recovery_retains_unknown_on_changed_bookmark_and_blocks_retry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    identity, baseline, _manifest_digest = _reserve_for_recovery(tmp_path, monkeypatch)
    changed = dict(baseline)
    changed["bookmark"] = "00000004-00000005-00000006-" + "8" * 32

    def observe(*, phase: str, **_kwargs: object) -> dict[str, Any]:
        if phase == "postflight":
            raise owner.IngestionMigrationError("not postflight")
        return changed

    monkeypatch.setattr(owner, "_observe_remote_database", observe)
    with pytest.raises(owner.GuardedMigrationError, match="remains UNKNOWN"):
        owner.recover_guarded(environment="staging")
    assert owner._load_canonical_reservation(identity)[1]["status"] == "UNKNOWN"

    paths = _apply_paths(tmp_path)
    monkeypatch.setattr(
        owner, "_wrangler_prefix", lambda environment: (["wrangler"], canonical_binding(environment))
    )
    with pytest.raises(owner.GuardedMigrationError, match="recovery is required"):
        owner.apply_guarded(environment="staging", **paths)


def test_recovery_cannot_select_cross_sha_manifest_database_or_caller_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    identity, _baseline, _manifest_digest = _reserve_for_recovery(tmp_path, monkeypatch)
    path, reservation = owner._load_canonical_reservation(identity)
    for field, value in (
        ("reservation_nonce", "e" * 64),
        ("reservation_id", "sha256:" + "f" * 64),
        ("identity_digest", "sha256:" + "0" * 64),
    ):
        forged = dict(reservation)
        forged[field] = value
        path.write_text(json.dumps(forged), encoding="utf-8")
        with pytest.raises(owner.GuardedMigrationError, match="binding"):
            owner._load_canonical_reservation(identity)
        path.write_text(json.dumps(reservation), encoding="utf-8")

    monkeypatch.setattr(owner, "_source_sha", lambda _runner: OTHER_SHA)
    with pytest.raises(owner.GuardedMigrationError, match="protected|unreadable"):
        owner.recover_guarded(environment="staging")
    assert owner._load_canonical_reservation(identity)[1]["status"] == "UNKNOWN"


def test_cli_recovery_rejects_caller_paths_and_legacy_staging_artifacts() -> None:
    with pytest.raises(SystemExit):
        owner.main(
            [
                "--environment",
                "staging",
                "--recover",
                "--evidence-target",
                "/tmp/caller.json",
            ]
        )
    with pytest.raises(SystemExit):
        owner.main(
            [
                "--environment",
                "production",
                "--staging-evidence",
                "/tmp/forged.json",
            ]
        )


def test_evidence_publication_is_create_only(tmp_path: Path) -> None:
    target = tmp_path / "evidence.json"
    owner._publish_evidence(target, {"status": "HOLD"})
    original = target.read_bytes()
    with pytest.raises(FileExistsError):
        owner._publish_evidence(target, {"status": "forged"})
    assert target.read_bytes() == original


def test_exact_cutover_mode_is_required_only_when_0012_was_pending() -> None:
    assert owner._requires_exact_cutover(
        {"pending_migrations": list(MIGRATION_NAMES[11:])}
    )
    assert not owner._requires_exact_cutover({"pending_migrations": []})
    with pytest.raises(owner.GuardedMigrationError, match="malformed"):
        owner._requires_exact_cutover({"pending_migrations": "0012"})
