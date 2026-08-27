"""Behavioral gates around the canonical staging-first migration owner."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts import apply_ingestion_d1_migrations as owner
from scripts.d1_ingestion_migration_validation import MIGRATION_NAMES, canonical_binding


SHA = "a" * 40


def _staging_evidence(manifest_digest: str) -> dict[str, object]:
    unsigned: dict[str, object] = {
        "schema_version": "quant-ingest-guarded-migration-evidence/v1",
        "status": "APPLIED_EXACT",
        "environment": "staging",
        "source_sha": SHA,
        "canonical_manifest_digest": manifest_digest,
        "database": canonical_binding("staging"),
        "preflight": {"status": "RESUMABLE_EXACT_PREFIX"},
        "postflight": {
            "status": "EXACT_POSTFLIGHT",
            "applied_migrations": list(MIGRATION_NAMES),
        },
        "backup": {"ciphertext_digest": "sha256:" + "b" * 64},
        "pre_apply_bookmark": "00000001-00000002-00000003-" + "c" * 32,
        "prepared_evidence_digest": "sha256:" + "1" * 64,
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
    evidence = {"backup": {"database": {"environment": "staging"}, "verified": True}}
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
        evidence, encrypted=encrypted, key=key
    ) == evidence["backup"]
    with pytest.raises(owner.GuardedMigrationError, match="does not match"):
        owner.validate_staging_artifact(
            {"backup": {"verified": False}}, encrypted=encrypted, key=key
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
