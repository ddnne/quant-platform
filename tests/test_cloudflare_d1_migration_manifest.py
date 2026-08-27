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


def test_ingestion_apply_policy_is_staging_first_and_fail_closed() -> None:
    policy = build_manifest()["targets"]["quant-ingest"]["application_policy"]
    assert policy == {
        "mode": "guarded-staging-first/v1",
        "owner_command": "scripts/apply_ingestion_d1_migrations.py",
        "environment_order": ["staging", "production"],
        "requires": [
            "canonical-live-database-identity",
            "time-travel-bookmark",
            "encrypted-export-checksum",
            "exact-export-preflight",
            "exact-export-postflight",
            "same-source-staging-acceptance-before-production",
            "authenticated-staging-backup-before-production",
            "signed-jsda-v3-cutover-authority-before-readiness",
            "jsda-v3-readiness-smoke-before-product-acceptance",
        ],
    }
