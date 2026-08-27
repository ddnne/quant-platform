"""Behavioral gates around the canonical staging-first migration owner."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess

import pytest

from scripts import apply_ingestion_d1_migrations as owner
from scripts.d1_ingestion_migration_validation import MIGRATION_NAMES, canonical_binding


SHA = "a" * 40


def _staging_evidence(manifest_digest: str) -> dict[str, object]:
    binding = canonical_binding("staging")
    postflight = {
        "status": "EXACT_POSTFLIGHT",
        "environment": "staging",
        "database": binding,
        "canonical_manifest_digest": manifest_digest,
        "applied_migrations": list(MIGRATION_NAMES),
    }
    unsigned: dict[str, object] = {
        "schema_version": "quant-ingest-guarded-migration-evidence/v1",
        "status": "APPLIED_EXACT",
        "environment": "staging",
        "source_sha": SHA,
        "canonical_manifest_digest": manifest_digest,
        "database": binding,
        "preflight": {
            "status": "RESUMABLE_EXACT_PREFIX",
            "environment": "staging",
            "database": binding,
            "canonical_manifest_digest": manifest_digest,
            "simulated_postflight": postflight,
        },
        "postflight": postflight,
        "backup": {
            "ciphertext_digest": "sha256:" + "b" * 64,
            "database": owner._governed_database("staging"),
            "restore": {"source_sha": SHA},
        },
        "pre_apply_bookmark": "00000001-00000002-00000003-" + "c" * 32,
        "prepared_evidence_digest": "sha256:" + "1" * 64,
        "reservation_digest": "sha256:" + "2" * 64,
        "live_identity_digest": "sha256:" + "d" * 64,
        "time_travel_response_digest": "sha256:" + "e" * 64,
        "wrangler_pending_digest": "sha256:" + "f" * 64,
        "observed_at": "2026-08-27T00:00:00Z",
    }
    return {**unsigned, "evidence_digest": owner._digest(unsigned)}


def test_production_accepts_only_same_source_content_addressed_staging(
    tmp_path: Path,
) -> None:
    _target, manifest_digest = owner._canonical_target()
    evidence = _staging_evidence(manifest_digest)
    path = tmp_path / "staging.json"
    path.write_text(json.dumps(evidence), encoding="utf-8")
    accepted = owner.validate_staging_acceptance(
        path, source_sha=SHA, manifest_digest=manifest_digest
    )
    assert accepted["environment"] == "staging"

    for field, value, message in (
        ("source_sha", "f" * 40, "same-source"),
        ("canonical_manifest_digest", "sha256:" + "f" * 64, "same-source"),
        ("environment", "production", "same-source"),
    ):
        tampered = dict(evidence)
        tampered[field] = value
        # Even when an attacker recomputes the unkeyed content address, the
        # canonical source/environment comparison still rejects substitution.
        unsigned = {key: tampered[key] for key in tampered if key != "evidence_digest"}
        tampered["evidence_digest"] = owner._digest(unsigned)
        path.write_text(json.dumps(tampered), encoding="utf-8")
        with pytest.raises(owner.GuardedMigrationError, match=message):
            owner.validate_staging_acceptance(
                path, source_sha=SHA, manifest_digest=manifest_digest
            )


def test_staging_digest_and_exact_postflight_cannot_be_fabricated(
    tmp_path: Path,
) -> None:
    _target, manifest_digest = owner._canonical_target()
    evidence = _staging_evidence(manifest_digest)
    path = tmp_path / "staging.json"
    evidence["evidence_digest"] = "sha256:" + "0" * 64
    path.write_text(json.dumps(evidence), encoding="utf-8")
    with pytest.raises(owner.GuardedMigrationError, match="digest"):
        owner.validate_staging_acceptance(
            path, source_sha=SHA, manifest_digest=manifest_digest
        )

    evidence = _staging_evidence(manifest_digest)
    postflight = dict(evidence["postflight"])  # type: ignore[arg-type]
    postflight["applied_migrations"] = list(MIGRATION_NAMES[:-1])
    evidence["postflight"] = postflight
    unsigned = {key: evidence[key] for key in evidence if key != "evidence_digest"}
    evidence["evidence_digest"] = owner._digest(unsigned)
    path.write_text(json.dumps(evidence), encoding="utf-8")
    with pytest.raises(owner.GuardedMigrationError, match="same-source"):
        owner.validate_staging_acceptance(
            path, source_sha=SHA, manifest_digest=manifest_digest
        )


def test_live_identity_and_bookmark_must_be_unique_and_exact() -> None:
    binding = canonical_binding("staging")
    observed = {
        "result": {
            "name": binding["database_name"],
            "uuid": binding["database_id"],
            "version": "production",
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
    bookmark = "00000001-00000002-00000003-" + "c" * 32
    assert owner._bookmark({"current_bookmark": bookmark}) == bookmark
    with pytest.raises(owner.GuardedMigrationError, match="ambiguous"):
        owner._bookmark(
            {
                "current_bookmark": bookmark,
                "other_bookmark": "00000004-00000005-00000006-" + "d" * 32,
            }
        )


def test_production_staging_artifact_must_authenticate_exact_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _target, manifest_digest = owner._canonical_target()
    evidence = _staging_evidence(manifest_digest)
    encrypted = tmp_path / "staging.enc"
    key = tmp_path / "staging.key"
    monkeypatch.setattr(
        owner,
        "verify_encrypted",
        lambda observed_encrypted, observed_key: (
            evidence["backup"]
            if (observed_encrypted, observed_key) == (encrypted, key)
            else {}
        ),
    )
    assert owner.validate_staging_artifact(
        evidence,
        encrypted=encrypted,
        key=key,
        source_sha=SHA,
        manifest_digest=manifest_digest,
    ) == evidence["backup"]
    with pytest.raises(owner.GuardedMigrationError, match="does not match"):
        owner.validate_staging_artifact(
            {"backup": {"verified": False}},
            encrypted=encrypted,
            key=key,
            source_sha=SHA,
            manifest_digest=manifest_digest,
        )


def test_old_authenticated_backup_cannot_be_relabelled_with_current_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _target, manifest_digest = owner._canonical_target()
    forged = _staging_evidence(manifest_digest)
    old_backup = dict(forged["backup"])  # type: ignore[arg-type]
    old_backup["restore"] = {"source_sha": "f" * 40}
    forged["backup"] = old_backup
    unsigned = {key: forged[key] for key in forged if key != "evidence_digest"}
    forged["evidence_digest"] = owner._digest(unsigned)
    path = tmp_path / "forged.json"
    path.write_text(json.dumps(forged), encoding="utf-8")
    with pytest.raises(owner.GuardedMigrationError, match="same-source"):
        owner.validate_staging_acceptance(
            path,
            source_sha=SHA,
            manifest_digest=manifest_digest,
        )

    encrypted = tmp_path / "old.enc"
    key = tmp_path / "old.key"
    monkeypatch.setattr(owner, "verify_encrypted", lambda *_args: old_backup)
    with pytest.raises(owner.GuardedMigrationError, match="cross-binding"):
        owner.validate_staging_artifact(
            forged,
            encrypted=encrypted,
            key=key,
            source_sha=SHA,
            manifest_digest=manifest_digest,
        )


def test_wrangler_pending_inventory_must_be_empty() -> None:
    assert owner._validate_pending_output(
        "checking remote D1\n✅ No migrations to apply!\n"
    ).startswith("sha256:")
    with pytest.raises(owner.GuardedMigrationError, match="empty pending"):
        owner._validate_pending_output(
            "Migrations to be applied:\n0018_receipt_product_materialization.sql\n"
        )


def test_postflight_exact_copy_is_required_only_when_0012_was_pending() -> None:
    assert owner._requires_exact_cutover(
        {"pending_migrations": list(MIGRATION_NAMES[11:])}
    )
    assert not owner._requires_exact_cutover({"pending_migrations": []})
    with pytest.raises(owner.GuardedMigrationError, match="malformed"):
        owner._requires_exact_cutover({"pending_migrations": "0012"})


def test_evidence_publication_is_create_only(tmp_path: Path) -> None:
    target = tmp_path / "evidence.json"
    owner._publish_evidence(target, {"status": "APPLIED_EXACT"})
    original = target.read_bytes()
    with pytest.raises(FileExistsError):
        owner._publish_evidence(target, {"status": "forged"})
    assert target.read_bytes() == original


def test_local_path_preflight_is_distinct_create_only_and_private(
    tmp_path: Path,
) -> None:
    key = tmp_path / "backup.key"
    key.write_bytes(b"k" * 32)
    key.chmod(0o600)
    paths = owner._preflight_local_paths(
        environment="staging",
        backup_target=tmp_path / "backup.enc",
        backup_key=key,
        prepare_evidence_target=tmp_path / "prepared.json",
        evidence_target=tmp_path / "final.json",
        staging_evidence=None,
        staging_backup=None,
        staging_backup_key=None,
    )
    assert len({path for path in paths.values() if path is not None}) == 4

    collision = tmp_path / "collision.json"
    with pytest.raises(owner.GuardedMigrationError, match="resolve-distinct"):
        owner._preflight_local_paths(
            environment="staging",
            backup_target=tmp_path / "second.enc",
            backup_key=key,
            prepare_evidence_target=collision,
            evidence_target=collision,
            staging_evidence=None,
            staging_backup=None,
            staging_backup_key=None,
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


def test_final_evidence_reservation_is_create_only_and_auditable(
    tmp_path: Path,
) -> None:
    target = tmp_path / "final.json"
    reservation = owner._reserve_final_evidence(
        target,
        environment="staging",
        source_sha=SHA,
        manifest_digest="sha256:" + "1" * 64,
        prepared_evidence_digest="sha256:" + "2" * 64,
        backup_digest="sha256:" + "3" * 64,
        pre_apply_bookmark="00000001-00000002-00000003-" + "4" * 32,
    )
    assert owner._read_exact_evidence(target) == reservation
    assert reservation["status"] == (
        "REMOTE_APPLY_AUTHORIZED_STATE_UNKNOWN_UNTIL_FINALIZED"
    )
    with pytest.raises(FileExistsError):
        owner._reserve_final_evidence(
            target,
            environment="staging",
            source_sha=SHA,
            manifest_digest="sha256:" + "1" * 64,
            prepared_evidence_digest="sha256:" + "2" * 64,
            backup_digest="sha256:" + "3" * 64,
            pre_apply_bookmark="00000001-00000002-00000003-" + "4" * 32,
        )

    target.write_text('{"tampered":true}\n', encoding="utf-8")
    with pytest.raises(owner.GuardedMigrationError, match="replaced or modified"):
        owner._finalize_reserved_evidence(
            target,
            reservation=reservation,
            payload={"status": "APPLIED_EXACT"},
        )
    assert owner._read_exact_evidence(target) == {"tampered": True}


@pytest.mark.parametrize("apply_returncode", [0, 1])
def test_remote_apply_observes_reserved_final_path_before_mutation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    apply_returncode: int,
) -> None:
    binding = canonical_binding("staging")
    _target, manifest_digest = owner._canonical_target()
    key = tmp_path / "backup.key"
    key.write_bytes(b"k" * 32)
    key.chmod(0o600)
    final = tmp_path / "final.json"
    backup = {
        "ciphertext_digest": "sha256:" + "9" * 64,
        "database": owner._governed_database("staging"),
        "restore": {"source_sha": SHA},
    }
    postflight = {
        "status": "EXACT_POSTFLIGHT",
        "environment": "staging",
        "database": binding,
        "canonical_manifest_digest": manifest_digest,
        "applied_migrations": list(MIGRATION_NAMES),
    }
    preflight = {
        "status": "ALREADY_EXACT",
        "environment": "staging",
        "database": binding,
        "canonical_manifest_digest": manifest_digest,
        "pending_migrations": [],
        "simulated_postflight": postflight,
    }
    monkeypatch.setattr(owner, "_wrangler_prefix", lambda _environment: (["wrangler"], binding))
    monkeypatch.setattr(owner, "_source_sha", lambda _runner: SHA)
    monkeypatch.setattr(
        owner,
        "validate_export",
        lambda _path, *, environment, phase, require_exact_cutover=False: (
            preflight if phase == "preflight" else postflight
        ),
    )

    def fake_encrypt(_source: Path, target: Path, _key: Path, **_kwargs: object):
        target.write_bytes(b"encrypted")
        return backup

    monkeypatch.setattr(owner, "encrypt_backup", fake_encrypt)
    monkeypatch.setattr(owner, "verify_encrypted", lambda *_args: backup)

    def runner(argv: object, _cwd: Path) -> subprocess.CompletedProcess[str]:
        args = tuple(argv)  # type: ignore[arg-type]
        if args == ("wrangler", "--version"):
            return subprocess.CompletedProcess(args, 0, owner.WRANGLER_VERSION, "")
        if args[1:3] == ("d1", "info"):
            value = {"name": binding["database_name"], "uuid": binding["database_id"]}
            return subprocess.CompletedProcess(args, 0, json.dumps(value), "")
        if args[1:4] == ("d1", "time-travel", "info"):
            value = {"current_bookmark": "00000001-00000002-00000003-" + "c" * 32}
            return subprocess.CompletedProcess(args, 0, json.dumps(value), "")
        if args[1:4] == ("d1", "migrations", "apply"):
            observed = owner._read_exact_evidence(final)
            assert observed["status"] == (
                "REMOTE_APPLY_AUTHORIZED_STATE_UNKNOWN_UNTIL_FINALIZED"
            )
            return subprocess.CompletedProcess(
                args, apply_returncode, "applied", "failed"
            )
        if args[1:4] == ("d1", "migrations", "list"):
            return subprocess.CompletedProcess(
                args, 0, "✅ No migrations to apply!\n", ""
            )
        if args[1:3] == ("d1", "export"):
            return subprocess.CompletedProcess(args, 0, "exported", "")
        raise AssertionError(args)

    arguments = {
        "environment": "staging",
        "backup_target": tmp_path / "backup.enc",
        "backup_key": key,
        "prepare_evidence_target": tmp_path / "prepared.json",
        "evidence_target": final,
        "runner": runner,
    }
    if apply_returncode:
        with pytest.raises(owner.GuardedMigrationError, match="Wrangler command failed"):
            owner.apply_guarded(**arguments)  # type: ignore[arg-type]
        assert owner._read_exact_evidence(final)["status"] == (
            "REMOTE_APPLY_AUTHORIZED_STATE_UNKNOWN_UNTIL_FINALIZED"
        )
        return
    result = owner.apply_guarded(**arguments)  # type: ignore[arg-type]
    assert result["status"] == "APPLIED_EXACT"
    assert owner._read_exact_evidence(final) == result
