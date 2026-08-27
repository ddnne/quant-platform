"""Behavioral checks for canonical Cloudflare D1 migration ownership."""

from __future__ import annotations

from pathlib import Path

from scripts.cloudflare_d1_migration_manifest import ROOT, build_manifest


def test_every_d1_migration_has_one_canonical_owner_and_checksum() -> None:
    manifest = build_manifest()
    rows = [
        migration
        for target in manifest["targets"].values()
        for migration in target["migrations"]
    ]
    discovered = {
        str(path.relative_to(ROOT))
        for path in (ROOT / "platform" / "workers").glob("*/migrations/**/*.sql")
    }
    assert {row["path"] for row in rows} == discovered
    assert len(rows) == len({row["migration_id"] for row in rows})
    assert all(str(row["checksum"]).startswith("sha256:") for row in rows)


def test_ingestion_and_ops_have_distinct_migration_authorities() -> None:
    targets = build_manifest()["targets"]
    assert targets["quant-ingest"]["owner"] == "platform/workers/ingestion-premium"
    assert targets["quant-ops-projection"]["owner"] == "platform/workers/quant-ops-mcp"
    assert targets["quant-ops-quota"]["owner"] == "platform/workers/quant-ops-mcp"
    assert targets["quant-ops-projection"]["migration_dir"].endswith(
        "migrations/projection"
    )
    assert targets["quant-ops-quota"]["migration_dir"].endswith("migrations/quota")


def test_remote_applied_state_is_never_fabricated() -> None:
    targets = build_manifest()["targets"]
    for target in targets.values():
        production = target["environments"]["production"]
        staging = target["environments"]["staging"]
        assert production["database_id"] != staging["database_id"]
        assert production["applied_state"] == "UNVERIFIED"
        assert staging["applied_state"] == "UNVERIFIED"
        assert production["database_name"] != staging["database_name"]


def test_ingestion_apply_policy_is_source_only_and_fail_closed() -> None:
    manifest = build_manifest()
    assert manifest["schema_version"] == "cloudflare-d1-migration-manifest/v2"
    policy = manifest["targets"]["quant-ingest"]["application_policy"]
    assert policy == {
        "mode": "source-only-hold/v2",
        "owner_command": None,
        "observation_recovery_command": (
            "scripts/apply_ingestion_d1_migrations.py"
        ),
        "remote_mutation_authorized": False,
        "environment_order": ["staging", "production"],
        "authorization_state": {
            "staging": "HOLD",
            "production": "HOLD",
        },
        "canonical_reservation_identity": [
            "environment",
            "database_id",
            "source_sha",
            "canonical_manifest_digest",
        ],
        "hold_until": [
            "trusted-remote-cross-host-exclusive-lock",
            "trusted-control-plane-source-sha-attestation",
        ],
        "local_o_excl_role": "SINGLE_HOST_CRASH_AUDIT_MARKER_ONLY",
        "production_staging_evidence": (
            "independent-canonical-staging-d1-reobservation"
        ),
        "caller_staging_artifacts": "FORBIDDEN",
        "encrypted_backup_role": "ROLLBACK_ONLY",
        "encrypted_backup_grants_authority": False,
        "recovery_states": {
            "APPLIED": "fresh-exact-canonical-postflight-and-zero-pending",
            "NOT_APPLIED": (
                "fresh-observation-exactly-matches-recorded-preflight-baseline"
            ),
            "UNKNOWN": "all-other-or-unobservable-states",
        },
        "recovery_grants_mutation_authority": False,
        "jsda_acceptance": {
            "endpoint": "/health/ready",
            "http_status": 200,
            "product_ready": True,
            "cutover": "V3_ACTIVE",
            "response_digest_bound_to_provenance": True,
            "deployment_version_and_source_sha_bound": True,
        },
        "requires": [
            "canonical-live-database-identity",
            "time-travel-bookmark",
            "rollback-only-encrypted-export-checksum",
            "exact-export-preflight",
            "exact-export-postflight",
            "signed-jsda-v3-cutover-authority-before-readiness",
            "jsda-v3-readiness-smoke-before-product-acceptance",
        ],
    }
