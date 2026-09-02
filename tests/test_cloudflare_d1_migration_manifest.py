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
        "rollback_authority": "CLOUDFLARE_D1_TIME_TRAVEL",
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
            "bookmark-and-undo-persisted-before-migration",
            "same-d1-cas-mutation-lease",
            "exact-remote-schema-and-migration-inventory",
            "staging-activation-before-production",
        ],
    }


def test_jsda_v2_v3_and_ops_projection_migrations_are_canonical_for_both_envs() -> None:
    targets = build_manifest()["targets"]
    ingest = [
        row["migration_id"] for row in targets["quant-ingest"]["migrations"]
    ]
    assert ingest.index("quant-ingest:0010_raw_acquisition_status") < ingest.index(
        "quant-ingest:0011_jsda_queue_v2"
    )
    assert ingest.index("quant-ingest:0011_jsda_queue_v2") < ingest.index(
        "quant-ingest:0012_jsda_observation_identity"
    )
    assert ingest.index("quant-ingest:0012_jsda_observation_identity") < ingest.index(
        "quant-ingest:0013_restore_specialized_jquants_schema"
    )
    policy = targets["quant-ingest"]["application_policy"]
    assert policy["pending_from_live_applied_through"] == (
        "quant-ingest:0010_raw_acquisition_status"
    )
    assert ingest[ingest.index("quant-ingest:0011_jsda_queue_v2") :] == [
        f"quant-ingest:{index:04d}_{name}"
        for index, name in (
            (11, "jsda_queue_v2"),
            (12, "jsda_observation_identity"),
            (13, "restore_specialized_jquants_schema"),
            (14, "receipt_authority_reconciliation"),
            (15, "receipt_authority_requests"),
            (16, "receipt_authority_immutability"),
            (17, "receipt_authority_run_evidence"),
            (18, "receipt_product_materialization"),
            (19, "receipt_authority_recovery_smoke"),
            (20, "receipt_authority_governed_sources"),
            (21, "snapshot_quality_evidence"),
            (22, "receipt_authority_jsda_locator"),
            (23, "mutation_lease"),
        )
    ]
    projection = [
        row["migration_id"]
        for row in targets["quant-ops-projection"]["migrations"]
    ]
    assert projection == [
        "quant-ops-projection:0001_ops_projection",
        "quant-ops-projection:0002_receipt_product_materializations",
    ]
    for environment in ("staging", "production"):
        ingest_env = targets["quant-ingest"]["environments"][environment]
        projection_env = targets["quant-ops-projection"]["environments"][
            environment
        ]
        quota_env = targets["quant-ops-quota"]["environments"][environment]
        assert ingest_env["applied_state"] == "UNVERIFIED"
        assert ingest_env["binding"] == "DB"
        assert projection_env["binding"] == "OPS_PROJECTION_DB"
        assert quota_env["binding"] == "QUOTA_DB"
        assert projection_env["applied_state"] == "UNVERIFIED"
        assert quota_env["applied_state"] == "UNVERIFIED"
