"""Behavioral checks for canonical Cloudflare D1 migration ownership."""

from __future__ import annotations

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


def test_ingestion_apply_policy_is_single_operator_and_fail_closed() -> None:
    manifest = build_manifest()
    assert manifest["schema_version"] == "cloudflare-d1-migration-manifest/v2"
    policy = manifest["targets"]["quant-ingest"]["application_policy"]
    assert policy == {
        "mode": "single-operator-cloudflare/v1",
        "owner_command": "scripts/activate_jsda_v3_cutover.py",
        "check_command": "scripts/apply_ingestion_d1_migrations.py --check",
        "remote_mutation_authority": "OWNER_COMMAND_ONLY",
        "direct_wrangler_apply": "FORBIDDEN",
        "environment_order": ["staging", "production"],
        "rollback_authority": "FORWARD_REPAIR_REQUIRED",
        "local_whole_file_export_in_cutover": "FORBIDDEN",
        "recovery_cache": {
            "role": "SMALL_CREATE_ONLY_CONTROL_INTENT",
            "authority": False,
            "source_of_truth": "REMOTE_D1_CUTOVER_RUN_AND_LIVE_CLOUDFLARE",
        },
        "lease": {
            "store": "quant_ingest_mutation_lease",
            "acquire": "D1_CAS",
            "spawn_fence": "MIGRATING_REMOTE_SPAWNED",
            "sticky_after_spawn": True,
        },
        "pending_from_live_applied_through": "quant-ingest:0010_raw_acquisition_status",
        "production_admission": (
            "STAGING_ACTIVATED_SAME_SOURCE_SHA_AND_LIVE_CONFIG_QUEUE_CRON_SMOKE"
        ),
        "requires": [
            "canonical-live-database-identity",
            "production-backend-time-travel",
            "pre-migration-bookmark-after-writer-and-queue-quiescence",
            "bookmark-is-recovery-reference-not-restore-authority",
            "same-d1-cas-mutation-lease",
            "exact-remote-schema-and-migration-inventory",
            "staging-activation-before-production",
            "no-shared-d1-time-travel-restore",
        ],
    }
