"""Behavioral checks for the frozen active-Worker deployment surface."""

from __future__ import annotations

import base64
import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
from typing import Any
from urllib.request import Request

import pytest


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts" / "cloudflare_binding_manifest.py"
SPEC = importlib.util.spec_from_file_location("cloudflare_binding_manifest", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
manifest_module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(manifest_module)


def test_frozen_manifest_equals_effective_wrangler_surfaces() -> None:
    frozen = json.loads(manifest_module.MANIFEST.read_text(encoding="utf-8"))
    assert frozen == manifest_module.build_manifest()
    assert set(frozen["workers"]) == set(manifest_module.ACTIVE_WORKERS)
    assert "ci-aggregate" not in frozen["workers"]


def test_personal_research_runner_has_an_eight_instance_hard_cap() -> None:
    manifest = manifest_module.build_manifest()
    for environment in ("base", "production", "staging"):
        containers = manifest["workers"]["research-mass-eval"][environment][
            "containers"
        ]
        assert len(containers) == 1
        assert containers[0]["class_name"] == "PersonalResearchContainer"
        assert containers[0]["instance_type"] == "standard-4"
        assert containers[0]["max_instances"] == 8
        services = manifest["workers"]["research-mass-eval"][environment]["services"]
        assert any(
            row.get("binding") == "JQUANTS_ACQUISITION"
            and row.get("entrypoint") == "IngestionSecretsService"
            for row in services
        )

    drifted = copy.deepcopy(manifest)
    drifted["workers"]["research-mass-eval"]["production"]["containers"][0][
        "max_instances"
    ] = 9
    with pytest.raises(ValueError, match="personal Container drift"):
        manifest_module.validate_manifest(drifted)


def test_receipt_authority_uses_dedicated_evidence_and_premium_owned_migrations() -> None:
    receipt = manifest_module.build_manifest()["workers"][
        "receipt-evidence-authority"
    ]
    for environment, evidence_bucket in {
        "base": "quant-receipt-evidence",
        "production": "quant-receipt-evidence",
        "staging": "quant-receipt-evidence-staging",
    }.items():
        surface = receipt[environment]
        assert surface["r2_buckets"] == [
            {
                "binding": "AUTHORITY_EVIDENCE_BUCKET",
                "bucket_name": evidence_bucket,
            },
            {
                "binding": "RAW_BUCKET",
                "bucket_name": {
                    "base": "quant-raw",
                    "production": "quant-raw",
                    "staging": "quant-raw-staging",
                }[environment],
            },
            {
                "binding": "STRUCTURED_BUCKET",
                "bucket_name": {
                    "base": "quant-structured",
                    "production": "quant-structured",
                    "staging": "quant-structured-staging",
                }[environment],
            },
        ]
        assert len(surface["d1_databases"]) == 1
        assert "migrations_dir" not in surface["d1_databases"][0]
        assert "migrations_table" not in surface["d1_databases"][0]


def test_all_named_entrypoints_and_governed_dos_have_exact_rpc_inventories() -> None:
    manifest = manifest_module.build_manifest()
    expected = {
        "ingestion-secrets": [{
            "name": "IngestionSecretsService",
            "handlers": ["class"],
            "fetch_reserved_special": True,
            "rpc_methods": ["fetch_governed_page"],
        }],
        "receipt-evidence-authority": [{
            "name": "ReceiptAuthorityService",
            "handlers": ["class"],
            "fetch_reserved_special": True,
            "rpc_methods": [
                "begin_audit_recovery_canary",
                "issue_for_segment",
                "public_key_registration",
                "recover_audit_recovery_canary",
                "recover_issue",
            ],
        }],
        "ingestion-premium": [
            {
                "name": "PremiumReceiptOperatorService",
                "handlers": ["class"],
                "fetch_reserved_special": False,
                "rpc_methods": ["pending_public_key_registration"],
            },
            {
                "name": "PremiumReceiptAuditEvidenceService",
                "handlers": ["class"],
                "fetch_reserved_special": False,
                "rpc_methods": ["staging_recovery_audit_evidence"],
            },
        ],
        "ingestion-jsda": [{
            "name": "JsdaReadinessService",
            "handlers": ["class"],
            "fetch_reserved_special": True,
            "rpc_methods": [],
        }],
        "research-ai-gateway": [{
            "name": "GatewayService",
            "handlers": ["class"],
            "fetch_reserved_special": False,
            "rpc_methods": [
                "cancelControlledPaper",
                "complete",
                "finalizeControlledPaper",
                "heartbeatControlledPaper",
                "queryControlledPaper",
                "reserveControlledPaper",
            ],
        }],
    }
    for environment in ("base", "production", "staging"):
        for worker in manifest_module.ACTIVE_WORKERS:
            assert manifest["workers"][worker][environment]["default_handler"] == {
                "fetch_reserved_special": True,
            }
        for worker, inventory in expected.items():
            assert manifest["workers"][worker][environment][
                "worker_entrypoints"
            ] == inventory
        premium = manifest["workers"]["ingestion-premium"][environment]
        assert premium["durable_object_class_handlers"] == []
        assert premium["workers_dev"] is False
        assert premium["preview_urls"] is False
        assert premium["route"] is None
        assert premium["routes"] == []
    assert manifest["workers"]["receipt-evidence-authority"]["staging"][
        "durable_object_class_handlers"
    ] == [{
        "name": "ReceiptEvidenceAuthority",
        "handlers": ["class"],
        "fetch_reserved_special": False,
        "alarm_reserved_special": True,
        "rpc_methods": [
            "begin_audit_recovery_canary",
            "issue_for_segment",
            "public_key_registration",
            "recover_audit_recovery_canary",
            "recover_issue",
        ],
    }]
    budget_ledger = {
        "name": "BudgetLedger",
        "handlers": ["class"],
        "fetch_reserved_special": True,
        "alarm_reserved_special": True,
        "rpc_methods": [
            "cancelPreProvider",
            "finalizeExact",
            "finalizeOwnedPaper",
            "heartbeat",
            "markProviderStarted",
            "queryOwned",
            "release",
            "reserve",
            "reserveOwned",
            "settleUncertain",
            "snapshot",
        ],
    }
    for environment in ("base", "production", "staging"):
        assert manifest["workers"]["research-ai-gateway"][environment][
            "durable_object_class_handlers"
        ] == [budget_ledger]
    assert manifest["test_harness_surfaces"]["research-ai-gateway"][
        "durable_object_class_handlers"
    ] == [budget_ledger]


def test_quant_ops_framework_inventory_and_dependency_are_exact() -> None:
    manifest = manifest_module.build_manifest()
    expected = manifest_module.FRAMEWORK_DURABLE_OBJECT_POLICY["quant-ops-mcp"][
        "QuantOpsMcpAgent"
    ]
    for environment in ("base", "production", "staging"):
        handlers = manifest["workers"]["quant-ops-mcp"][environment][
            "durable_object_class_handlers"
        ]
        assert handlers == [{
            "name": "QuantOpsMcpAgent",
            "handlers": ["class"],
            "framework_rpc_inventory": expected,
        }]
    assert manifest["test_harness_surfaces"]["quant-ops-mcp"][
        "durable_object_class_handlers"
    ] == [{
        "name": "QuantOpsMcpAgent",
        "handlers": ["class"],
        "framework_rpc_inventory": expected,
    }]
    assert expected["own_custom_pre_init_rpc_methods"] == ["init"]
    assert expected["constructor_prototype_copy"] == {
        "observed": True,
        "copied_method_count": 17,
        "post_construction_own_method_count": 18,
    }
    assert expected["reserved_specials"] == {
        "fetch": True,
        "alarm": True,
        "webSocketMessage": True,
        "webSocketClose": True,
        "webSocketError": True,
    }
    assert expected["dependency"] == manifest_module.QUANT_OPS_AGENTS_DEPENDENCY_POLICY


def test_every_active_durable_object_needs_exactly_one_inventory_policy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest = manifest_module.build_manifest()
    observed = {
        (worker, row["class_name"])
        for worker, environments in manifest["workers"].items()
        for row in environments["production"]["durable_objects"]
    }
    governed = {
        (worker, class_name)
        for worker, classes in manifest_module.DURABLE_OBJECT_RPC_POLICY.items()
        for class_name in classes
    } | {
        (worker, class_name)
        for worker, classes in manifest_module.FRAMEWORK_DURABLE_OBJECT_POLICY.items()
        for class_name in classes
    }
    assert observed == governed

    without_quant_ops = copy.deepcopy(
        manifest_module.FRAMEWORK_DURABLE_OBJECT_POLICY
    )
    del without_quant_ops["quant-ops-mcp"]["QuantOpsMcpAgent"]
    monkeypatch.setattr(
        manifest_module,
        "FRAMEWORK_DURABLE_OBJECT_POLICY",
        without_quant_ops,
    )
    with pytest.raises(ValueError, match="needs exactly one explicit RPC or framework"):
        manifest_module.build_manifest()


def _recompute_binding_digests(manifest: dict) -> dict:
    body = {key: value for key, value in manifest.items() if key != "manifest_digest"}
    body["ops_binding_identity_digest"] = (
        manifest_module.quant_ops_binding_identity_digest(body["workers"])
    )
    manifest["ops_binding_identity_digest"] = body["ops_binding_identity_digest"]
    manifest["manifest_digest"] = manifest_module._canonical_digest(body)
    return manifest


def test_ops_mcp_bindings_never_use_ingestion_ops_db() -> None:
    manifest = manifest_module.build_manifest()
    for environment, expected in manifest_module._OPS_D1_IDENTITY.items():
        rows = manifest["workers"]["quant-ops-mcp"][environment]["d1_databases"]
        actual = tuple(manifest_module._ops_d1_row(row) for row in rows)
        assert actual == expected
        assert all(row["binding"] != "OPS_DB" for row in rows)
        assert all(
            row["database_name"]
            not in {"quant-ingest", "quant-ingest-staging"}
            for row in rows
        )

    drifted = copy.deepcopy(manifest)
    drifted["workers"]["quant-ops-mcp"]["production"]["d1_databases"] = [
        {
            "binding": "OPS_DB",
            "database_id": "be6fdcf8-40be-41fc-9535-7facd1fc2ffc",
            "database_name": "quant-ingest",
        }
    ]
    _recompute_binding_digests(drifted)
    with pytest.raises(ValueError, match="dedicated projection/quota"):
        manifest_module.validate_manifest(drifted)


def test_ops_projection_cannot_reuse_ingestion_database_id() -> None:
    manifest = manifest_module.build_manifest()
    ingest_id = manifest["workers"]["ingestion-premium"]["production"][
        "d1_databases"
    ][0]["database_id"]
    drifted = copy.deepcopy(manifest)
    for row in drifted["workers"]["quant-ops-mcp"]["production"]["d1_databases"]:
        if row["binding"] == "OPS_PROJECTION_DB":
            row["database_id"] = ingest_id
    _recompute_binding_digests(drifted)
    with pytest.raises(ValueError, match="dedicated projection/quota"):
        manifest_module.validate_manifest(drifted)


def test_ops_quota_migration_ledger_cannot_drift() -> None:
    manifest = manifest_module.build_manifest()
    drifted = copy.deepcopy(manifest)
    for row in drifted["workers"]["quant-ops-mcp"]["staging"]["d1_databases"]:
        if row["binding"] == "QUOTA_DB":
            row["migrations_table"] = "d1_migrations"
    _recompute_binding_digests(drifted)
    with pytest.raises(ValueError, match="dedicated projection/quota"):
        manifest_module.validate_manifest(drifted)


def test_premium_owns_jsda_v2_v3_migrations_in_production_and_staging() -> None:
    manifest = manifest_module.build_manifest()
    for environment in ("base", "production", "staging"):
        premium = manifest["workers"]["ingestion-premium"][environment][
            "d1_databases"
        ]
        assert [row["binding"] for row in premium] == ["DB", "OPS_PROJECTION_DB"]
        assert premium[0]["migrations_dir"] == "migrations"
        assert premium[1]["migrations_table"] == "d1_migrations_ops_projection"
        jsda = manifest["workers"]["ingestion-jsda"][environment]["d1_databases"]
        assert len(jsda) == 1
        assert jsda[0]["binding"] == "DB"
        assert "migrations_dir" not in jsda[0]


def test_jsda_production_keeps_dlq_route_without_consumer() -> None:
    manifest = manifest_module.build_manifest()
    for environment in ("base", "production"):
        consumers = manifest["workers"]["ingestion-jsda"][environment][
            "queue_consumers"
        ]
        assert [row["queue"] for row in consumers] == ["quant-jsda-ingestion"]
        assert consumers[0]["dead_letter_queue"] == "quant-jsda-ingestion-dlq"
    staging = manifest["workers"]["ingestion-jsda"]["staging"]["queue_consumers"]
    assert [row["queue"] for row in staging] == [
        "quant-jsda-ingestion-staging",
        "quant-jsda-ingestion-dlq-staging",
    ]
    drifted = copy.deepcopy(manifest)
    drifted["workers"]["ingestion-jsda"]["production"]["queue_consumers"].append({
        "dead_letter_queue": "quant-jsda-ingestion-rejects",
        "max_batch_size": 1,
        "max_batch_timeout": 5,
        "max_concurrency": 1,
        "max_retries": 8,
        "queue": "quant-jsda-ingestion-dlq",
        "retry_delay": 60,
    })
    _recompute_binding_digests(drifted)
    with pytest.raises(ValueError, match="production DLQ must not have a consumer"):
        manifest_module.validate_manifest(drifted)


def test_quant_ops_mcp_object_capability_is_self_only() -> None:
    manifest = manifest_module.build_manifest()
    for environment in ("base", "production", "staging"):
        surface = manifest["workers"]["quant-ops-mcp"][environment]
        assert surface["durable_objects"] == [{
            "class_name": "QuantOpsMcpAgent",
            "name": "MCP_OBJECT",
        }]
        assert surface["services"] == []

    drifted = copy.deepcopy(manifest)
    drifted["workers"]["ingestion-jsda"]["production"]["services"] = [{
        "binding": "OPS_AGENT",
        "service": "quant-platform-ops-read-mcp",
    }]
    with pytest.raises(ValueError, match="must not be distributed"):
        manifest_module.validate_manifest(drifted)

    stub_distributed = copy.deepcopy(manifest)
    stub_distributed["workers"]["ingestion-jsda"]["production"][
        "durable_objects"
    ] = [{
        "name": "OPS_AGENT",
        "class_name": "FrameworkAlias",
        "script_name": "quant-platform-ops-read-mcp",
    }]
    with pytest.raises(ValueError, match="must not be distributed"):
        manifest_module.validate_manifest(stub_distributed)


def test_manifest_digest_covers_the_complete_binding_policy() -> None:
    manifest = manifest_module.build_manifest()
    drifted = copy.deepcopy(manifest)
    drifted["workers"]["quant-ops-mcp"]["production"]["vars"][
        "DAILY_ROW_QUOTA"
    ] = "25001"
    with pytest.raises(ValueError, match="binding manifest digest drift"):
        manifest_module.validate_manifest(drifted)


def test_receipt_activation_observer_is_staging_only_and_capability_minimal() -> None:
    observer = manifest_module.build_manifest()["workers"][
        "receipt-activation-observer"
    ]
    base = observer["base"]
    assert base["workers_dev"] is False
    assert base["services"] == []
    production = observer["production"]
    assert production["workers_dev"] is False
    assert production["vars"]["ENVIRONMENT"] == "disabled"
    assert production["services"] == [
        {
            "binding": "JSDA_INGESTION",
            "entrypoint": "JsdaReadinessService",
            "service": "quant-platform-ingestion-jsda",
        },
    ]
    for surface in (base, production):
        assert surface["secret_names"] == []
        assert surface["route"] is None
        assert surface["routes"] == []
    staging = observer["staging"]
    assert staging["workers_dev"] is True
    assert staging["preview_urls"] is False
    assert staging["services"] == [
        {
            "binding": "JSDA_INGESTION",
            "entrypoint": "JsdaReadinessService",
            "service": "quant-platform-ingestion-jsda-staging",
        },
        {
            "binding": "PREMIUM_RECEIPT_OPERATOR",
            "entrypoint": "PremiumReceiptAuditEvidenceService",
            "service": "quant-platform-ingestion-premium-staging",
        },
    ]
    assert staging["worker_entrypoints"] == []
    assert staging["durable_object_class_handlers"] == []
    for field in (
        "d1_databases",
        "r2_buckets",
        "kv_namespaces",
        "queue_producers",
        "queue_consumers",
        "durable_objects",
    ):
        assert staging[field] == []


def test_default_fetch_reserved_special_drift_fails_closed() -> None:
    manifest = manifest_module.build_manifest()
    drifted = copy.deepcopy(manifest)
    drifted["workers"]["receipt-activation-observer"]["staging"][
        "default_handler"
    ]["fetch_reserved_special"] = False
    with pytest.raises(ValueError, match="default fetch reserved-special drift"):
        manifest_module.validate_manifest(drifted)


def test_rpc_inventory_rejects_method_or_reserved_special_drift() -> None:
    manifest = manifest_module.build_manifest()
    mutated = copy.deepcopy(manifest)
    mutated["workers"]["ingestion-premium"]["staging"][
        "worker_entrypoints"
    ][0]["rpc_methods"].append("unexpected_positive_rpc")
    with pytest.raises(ValueError, match="WorkerEntrypoint RPC surface drifted"):
        manifest_module.validate_manifest(mutated)

    mutated = copy.deepcopy(manifest)
    mutated["workers"]["ingestion-secrets"]["production"][
        "worker_entrypoints"
    ][0]["fetch_reserved_special"] = False
    with pytest.raises(ValueError, match="WorkerEntrypoint RPC surface drifted"):
        manifest_module.validate_manifest(mutated)

    mutated = copy.deepcopy(manifest)
    mutated["workers"]["receipt-evidence-authority"]["base"][
        "durable_object_class_handlers"
    ][0]["rpc_methods"].append("ensureKey")
    with pytest.raises(ValueError, match="Durable Object class handlers drifted"):
        manifest_module.validate_manifest(mutated)

    mutated = copy.deepcopy(manifest)
    mutated["workers"]["research-ai-gateway"]["production"][
        "durable_object_class_handlers"
    ][0]["alarm_reserved_special"] = False
    with pytest.raises(ValueError, match="Durable Object class handlers drifted"):
        manifest_module.validate_manifest(mutated)


def test_canonical_inventory_equals_every_deployable_worker_directory() -> None:
    assert manifest_module._deployable_worker_directories() == (  # noqa: SLF001
        manifest_module.ACTIVE_WORKERS
    )


def test_ungoverned_deployable_worker_fails_closed(tmp_path: Path) -> None:
    worker_root = tmp_path / "workers"
    worker_root.mkdir()
    for worker in manifest_module.ACTIVE_WORKERS:
        directory = worker_root / worker
        directory.mkdir()
        (directory / "wrangler.toml").write_text(
            f'name = "{worker}"\n', encoding="utf-8"
        )
    rogue = worker_root / "rogue-worker"
    rogue.mkdir()
    (rogue / "wrangler.jsonc").write_text(
        '{ "name": "rogue" }\n', encoding="utf-8"
    )
    with pytest.raises(ValueError, match="ungoverned=.*rogue-worker"):
        manifest_module.validate_active_worker_inventory(worker_root=worker_root)


def test_nested_worker_config_cannot_escape_inventory(tmp_path: Path) -> None:
    worker_root = tmp_path / "workers"
    worker_root.mkdir()
    for worker in manifest_module.ACTIVE_WORKERS:
        directory = worker_root / worker
        directory.mkdir()
        (directory / "wrangler.toml").write_text(
            f'name = "{worker}"\n', encoding="utf-8"
        )
    nested = worker_root / "experiments" / "rogue-worker"
    nested.mkdir(parents=True)
    (nested / "wrangler.toml").write_text('name = "rogue"\n', encoding="utf-8")
    with pytest.raises(ValueError, match="experiments/rogue-worker"):
        manifest_module.validate_active_worker_inventory(worker_root=worker_root)


@pytest.mark.parametrize("worker", ("../rogue", "rogue/worker", "rogue\nworker"))
def test_inventory_worker_names_are_safe_paths(tmp_path: Path, worker: str) -> None:
    inventory = tmp_path / "active_workers.json"
    inventory.write_text(
        json.dumps(
            {
                "schema_version": "cloudflare-active-worker-inventory/v1",
                "workers": [worker],
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="sorted unique non-empty list"):
        manifest_module._load_active_workers(inventory)  # noqa: SLF001


def test_known_worker_cannot_add_alternate_deployment_config(tmp_path: Path) -> None:
    worker_root = tmp_path / "workers"
    worker_root.mkdir()
    for worker in manifest_module.ACTIVE_WORKERS:
        directory = worker_root / worker
        directory.mkdir()
        (directory / "wrangler.toml").write_text(
            f'name = "{worker}"\n', encoding="utf-8"
        )
    (worker_root / manifest_module.ACTIVE_WORKERS[0] / "wrangler.prod.jsonc").write_text(
        '{ "name": "shadow-deployment" }\n', encoding="utf-8"
    )
    with pytest.raises(ValueError, match="ungoverned deployment control file"):
        manifest_module.validate_active_worker_inventory(worker_root=worker_root)


def test_arbitrary_toml_config_cannot_escape_known_worker(tmp_path: Path) -> None:
    worker_root = tmp_path / "workers"
    worker_root.mkdir()
    for worker in manifest_module.ACTIVE_WORKERS:
        directory = worker_root / worker
        directory.mkdir()
        (directory / "wrangler.toml").write_text(
            f'name = "{worker}"\n', encoding="utf-8"
        )
    (worker_root / manifest_module.ACTIVE_WORKERS[0] / "shadow.toml").write_text(
        'name = "shadow-deployment"\n', encoding="utf-8"
    )
    with pytest.raises(ValueError, match=r"shadow\.toml"):
        manifest_module.validate_active_worker_inventory(worker_root=worker_root)


def test_nested_package_json_cannot_escape_inventory(tmp_path: Path) -> None:
    worker_root = tmp_path / "workers"
    worker_root.mkdir()
    for worker in manifest_module.ACTIVE_WORKERS:
        directory = worker_root / worker
        directory.mkdir()
        (directory / "wrangler.toml").write_text(
            f'name = "{worker}"\n', encoding="utf-8"
        )
    rogue = worker_root / "experiments" / "rogue"
    rogue.mkdir(parents=True)
    (rogue / "package.json").write_text(
        json.dumps({"scripts": {"deploy": "wrangler deploy src/index.ts"}}),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="experiments/rogue"):
        manifest_module.validate_active_worker_inventory(worker_root=worker_root)


@pytest.mark.parametrize(
    "marker", ("wrangler.toml", "cloudflare.config.ts", "package.json")
)
def test_worker_outside_canonical_root_cannot_escape_repository_inventory(
    tmp_path: Path,
    marker: str,
) -> None:
    repo_root = tmp_path / "repo"
    worker_root = repo_root / "platform" / "workers"
    for worker in manifest_module.ACTIVE_WORKERS:
        directory = worker_root / worker
        directory.mkdir(parents=True)
        (directory / "package.json").write_text(
            json.dumps(
                {
                    "devDependencies": {"wrangler": "4.125.0"},
                    "scripts": {"deploy": "wrangler deploy"},
                }
            ),
            encoding="utf-8",
        )
        (directory / "wrangler.toml").write_text(
            f'name = "{worker}"\n', encoding="utf-8"
        )
    rogue = repo_root / "packages" / "rogue"
    rogue.mkdir(parents=True)
    if marker != "package.json":
        (rogue / marker).write_text('name = "rogue"\n', encoding="utf-8")
    else:
        (rogue / marker).write_text(
            json.dumps({"scripts": {"deploy": "node scripts/deploy-shadow.js"}}),
            encoding="utf-8",
        )
    with pytest.raises(ValueError, match=r"ungoverned=.*packages/rogue"):
        manifest_module.validate_repository_worker_boundary(
            repo_root=repo_root,
            worker_root=worker_root,
            workers=manifest_module.ACTIVE_WORKERS,
        )


def test_package_script_commands_are_frozen() -> None:
    manifest = manifest_module.build_manifest()
    drifted = copy.deepcopy(manifest)
    drifted["worker_package_scripts"]["ingestion-jsda"]["shadow"] = (
        "wrangler deploy --name shadow"
    )
    with pytest.raises(ValueError, match="package-script deployment surface drift"):
        manifest_module.validate_manifest(drifted)


def test_package_script_rejects_wrangler_config_redirect(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    worker = "ingestion-jsda"
    package = manifest_module.WORKER_ROOT / worker / "package.json"
    original_read_text = Path.read_text

    def read_text(path: Path, *args: object, **kwargs: object) -> str:
        body = original_read_text(path, *args, **kwargs)
        if path == package:
            data = json.loads(body)
            data["scripts"]["deploy"] = "wrangler deploy"
            return json.dumps(data)
        return body

    monkeypatch.setattr(Path, "read_text", read_text)
    with pytest.raises(ValueError, match="closed command policy"):
        manifest_module._package_scripts(worker)  # noqa: SLF001


@pytest.mark.parametrize(
    "script,command",
    (
        (
            "deploy",
            "wrangler deploy --config=wrangler.toml --env=production "
            "--name quant-platform-rogue",
        ),
        (
            "build",
            'wrangler deploy --dry-run=false --config=wrangler.toml --env="" '
            "--outdir .wrangler-dry-run",
        ),
        (
            "build",
            'wrangler deploy --dry-run --config=wrangler.toml --env="" '
            "--outdir .wrangler-dry-run && wrangler deploy "
            "--config=wrangler.toml --env=production",
        ),
        (
            "deploy",
            "wrangler deploy src/shadow.ts --config=wrangler.toml --env=production",
        ),
    ),
)
def test_package_script_rejects_wrangler_command_escape(
    monkeypatch: pytest.MonkeyPatch,
    script: str,
    command: str,
) -> None:
    worker = "ingestion-jsda"
    package = manifest_module.WORKER_ROOT / worker / "package.json"
    original_read_text = Path.read_text

    def read_text(path: Path, *args: object, **kwargs: object) -> str:
        body = original_read_text(path, *args, **kwargs)
        if path == package:
            data = json.loads(body)
            data["scripts"][script] = command
            return json.dumps(data)
        return body

    monkeypatch.setattr(Path, "read_text", read_text)
    with pytest.raises(ValueError, match="closed command policy"):
        manifest_module.build_manifest()


@pytest.mark.parametrize(
    "worker,script,command",
    (
        (
            "ingestion-jsda",
            "deploy",
            "wran''gler deploy --config=wran''gler.toml --env=production "
            "--name quant-platform-rogue",
        ),
        ("ingestion-jsda", "deploy", "node scripts/deploy-shadow.js"),
        ("ingestion-jsda", "test", "node scripts/deploy-shadow.js"),
        ("ingestion-jsda", "shadow", "node scripts/deploy-shadow.js"),
        ("research-mass-eval", "test", "vitest run"),
    ),
)
def test_all_package_script_roles_are_independently_pinned(
    monkeypatch: pytest.MonkeyPatch,
    worker: str,
    script: str,
    command: str,
) -> None:
    package = manifest_module.WORKER_ROOT / worker / "package.json"
    original_read_text = Path.read_text

    def read_text(path: Path, *args: object, **kwargs: object) -> str:
        body = original_read_text(path, *args, **kwargs)
        if path == package:
            data = json.loads(body)
            data["scripts"][script] = command
            return json.dumps(data)
        return body

    monkeypatch.setattr(Path, "read_text", read_text)
    with pytest.raises(ValueError, match="closed command policy"):
        manifest_module.build_manifest()


def test_test_harness_configs_are_frozen_as_nonpublic_surfaces() -> None:
    manifest = manifest_module.build_manifest()
    expected = {
        worker
        for worker in manifest_module.ACTIVE_WORKERS
        if (manifest_module.WORKER_ROOT / worker / "wrangler.test.toml").is_file()
    }
    assert set(manifest["test_harness_surfaces"]) == expected
    for worker, surface in manifest["test_harness_surfaces"].items():
        assert surface["config"].endswith(f"/{worker}/wrangler.test.toml")
        assert surface["name"].endswith("-test")
        assert surface["workers_dev"] is False
        assert surface["preview_urls"] is False
        assert surface["route"] is None
        assert surface["routes"] == []

    drifted = copy.deepcopy(manifest)
    worker = next(iter(drifted["test_harness_surfaces"]))
    drifted["test_harness_surfaces"][worker]["workers_dev"] = True
    with pytest.raises(ValueError, match="test-harness workers_dev must be false"):
        manifest_module.validate_manifest(drifted)

    routed = copy.deepcopy(manifest)
    routed["test_harness_surfaces"][worker]["routes"] = [
        {"pattern": "test.example/*", "zone_name": "test.example"}
    ]
    with pytest.raises(ValueError, match="test-harness routes must be empty"):
        manifest_module.validate_manifest(routed)

    production_bound = copy.deepcopy(manifest)
    production_bound["test_harness_surfaces"][worker]["d1_databases"] = [
        {
            "binding": "SHADOW_DB",
            "database_name": "shadow-test",
            "database_id": manifest["workers"]["ingestion-premium"]["production"][
                "d1_databases"
            ][0]["database_id"],
        }
    ]
    with pytest.raises(ValueError, match="external binding target overlap"):
        manifest_module.validate_manifest(production_bound)


def test_staging_binding_identity_cannot_alias_production() -> None:
    manifest = manifest_module.build_manifest()
    production_id = manifest["workers"]["ingestion-premium"]["production"][
        "d1_databases"
    ][0]["database_id"]
    drifted = copy.deepcopy(manifest)
    drifted["workers"]["ingestion-premium"]["staging"]["d1_databases"][0][
        "database_id"
    ] = production_id
    with pytest.raises(ValueError, match="staging external binding targets overlap"):
        manifest_module.validate_manifest(drifted)

    preview_aliases = (
        (
            "ingestion-premium",
            "d1_databases",
            "preview_database_id",
            production_id,
        ),
        (
            "quant-ops-mcp",
            "kv_namespaces",
            "preview_id",
            manifest["workers"]["quant-ops-mcp"]["production"]["kv_namespaces"][
                0
            ]["id"],
        ),
        (
            "ingestion-premium",
            "r2_buckets",
            "preview_bucket_name",
            manifest["workers"]["ingestion-premium"]["production"]["r2_buckets"][
                0
            ]["bucket_name"],
        ),
    )
    for worker, table, field, production_target in preview_aliases:
        drifted = copy.deepcopy(manifest)
        drifted["workers"][worker]["staging"][table][0][field] = production_target
        with pytest.raises(
            ValueError, match="staging external binding targets overlap"
        ):
            manifest_module.validate_manifest(drifted)

    for table, row in (
        ("tail_consumers", {"service": "quant-platform-ingestion-premium"}),
        (
            "durable_objects",
            {
                "name": "SHADOW_DO",
                "class_name": "Shadow",
                "script_name": "quant-platform-ingestion-premium",
            },
        ),
    ):
        drifted = copy.deepcopy(manifest)
        drifted["workers"]["ingestion-jsda"]["staging"][table] = [row]
        with pytest.raises(
            ValueError, match="staging external binding targets overlap"
        ):
            manifest_module.validate_manifest(drifted)


def test_staging_surfaces_reject_custom_routes() -> None:
    manifest = manifest_module.build_manifest()
    drifted = copy.deepcopy(manifest)
    drifted["workers"]["ingestion-jsda"]["staging"]["route"] = {
        "pattern": "staging.example/*",
        "zone_name": "staging.example",
    }
    with pytest.raises(ValueError, match="staging routes must be empty"):
        manifest_module.validate_manifest(drifted)

    production_kv = manifest["workers"]["quant-ops-mcp"]["production"][
        "kv_namespaces"
    ][0]["id"]
    drifted = copy.deepcopy(manifest)
    drifted["workers"]["quant-ops-mcp"]["staging"]["kv_namespaces"][0][
        "id"
    ] = production_kv
    with pytest.raises(ValueError, match="staging external binding targets overlap"):
        manifest_module.validate_manifest(drifted)


def test_test_harness_config_rejects_hidden_named_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    worker = next(
        worker
        for worker in manifest_module.ACTIVE_WORKERS
        if (manifest_module.WORKER_ROOT / worker / "wrangler.test.toml").is_file()
    )
    config = manifest_module.WORKER_ROOT / worker / "wrangler.test.toml"
    data = manifest_module._load_toml(config)  # noqa: SLF001
    data["env"] = {
        "production": {
            "name": "shadow-production",
            "main": "src/shadow.ts",
        }
    }
    monkeypatch.setattr(manifest_module, "_load_toml", lambda _path: data)
    with pytest.raises(ValueError, match="standalone test config"):
        manifest_module._effective_surface(  # noqa: SLF001
            worker=worker,
            config_path=config,
            environment="test",
            named_environment=None,
        )


def test_authoritative_ci_dry_runs_test_harness_configs() -> None:
    ci = (manifest_module.ROOT / "scripts" / "verify_ci.sh").read_text(
        encoding="utf-8"
    )
    assert "wrangler deploy --dry-run --config=wrangler.test.toml" in ci
    assert "--config=wrangler.toml --env=\"\"" in ci
    assert "--config=wrangler.toml --env=production" in ci
    assert "unset CLOUDFLARE_ENV" in ci
    logical_lines = ci.replace("\\\n", " ").splitlines()
    wrangler_invocations = [
        line.strip()
        for line in logical_lines
        if "npx --no-install wrangler " in line and not line.lstrip().startswith("#")
    ]
    assert wrangler_invocations
    parsed_invocations = []
    for command in wrangler_invocations:
        payload = command.split("npx --no-install wrangler ", 1)[1].rstrip(")")
        parsed_invocations.append(shlex.split(payload))
    assert parsed_invocations == [
        ["deploy", "--dry-run", "--config=wrangler.toml", "--env="],
        [
            "deploy",
            "--dry-run",
            "--config=wrangler.toml",
            "--env=production",
        ],
        ["deploy", "--dry-run", "--config=wrangler.staging.toml"],
        ["deploy", "--dry-run", "--config=wrangler.test.toml", "--env="],
        ["types", "--config=wrangler.toml", "--env="],
        [
            "types",
            "$base_types",
            "--config=wrangler.toml",
            "--env=",
            "--include-runtime=false",
        ],
        [
            "types",
            "$production_types",
            "--config=wrangler.toml",
            "--env=production",
            "--include-runtime=false",
        ],
        [
            "types",
            "$staging_types",
            "--config=wrangler.staging.toml",
            "--include-runtime=false",
        ],
    ]


def test_manifest_is_fail_closed_for_toolchain_drift() -> None:
    manifest = manifest_module.build_manifest()
    drifted = copy.deepcopy(manifest)
    drifted["workers"]["ingestion-jsda"]["production"]["toolchain"][
        "wrangler"
    ] = "4.124.0"
    with pytest.raises(ValueError, match="wrangler must be exactly"):
        manifest_module.validate_manifest(drifted)


def test_previously_ignored_wrangler_fields_are_modeled(monkeypatch: pytest.MonkeyPatch) -> None:
    config = manifest_module.WORKER_ROOT / "ingestion-premium" / "wrangler.toml"
    data = manifest_module._load_toml(config)  # noqa: SLF001
    data["account_id"] = "account-for-test"
    data["route"] = {"pattern": "example.test/*", "zone_name": "example.test"}
    data["tail_consumers"] = [{"service": "audit-tail"}]
    data["placement"] = {"mode": "smart"}
    monkeypatch.setattr(manifest_module, "_load_toml", lambda _path: data)

    surface = manifest_module._effective_surface(  # noqa: SLF001
        worker="ingestion-premium",
        config_path=config,
        environment="base",
        named_environment=None,
    )
    assert surface["account_id"] == "account-for-test"
    assert surface["route"] == {
        "pattern": "example.test/*",
        "zone_name": "example.test",
    }
    assert surface["tail_consumers"] == [{"service": "audit-tail"}]
    assert surface["placement"] == {"mode": "smart"}

    production = manifest_module._effective_surface(  # noqa: SLF001
        worker="ingestion-premium",
        config_path=config,
        environment="production",
        named_environment="production",
    )
    assert production["account_id"] == "account-for-test"
    assert production["route"] == surface["route"]
    assert production["placement"] == surface["placement"]
    assert production["tail_consumers"] == []


def test_missing_named_environment_name_tracks_wrangler_suffix(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = manifest_module.WORKER_ROOT / "ingestion-premium" / "wrangler.toml"
    data = manifest_module._load_toml(config)  # noqa: SLF001
    del data["env"]["production"]["name"]
    monkeypatch.setattr(manifest_module, "_load_toml", lambda _path: data)
    surface = manifest_module._effective_surface(  # noqa: SLF001
        worker="ingestion-premium",
        config_path=config,
        environment="production",
        named_environment="production",
    )
    assert surface["name"] == f'{data["name"]}-production'


def test_durable_object_migration_order_is_semantic(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = manifest_module.WORKER_ROOT / "research-ai-gateway" / "wrangler.toml"
    data = manifest_module._load_toml(config)  # noqa: SLF001
    first = {"tag": "v1", "new_sqlite_classes": ["BudgetLedger"]}
    second = {"tag": "v2", "renamed_classes": [{"from": "A", "to": "B"}]}
    data["migrations"] = [first, second]
    monkeypatch.setattr(manifest_module, "_load_toml", lambda _path: data)
    forward = manifest_module._effective_surface(  # noqa: SLF001
        worker="research-ai-gateway",
        config_path=config,
        environment="base",
        named_environment=None,
    )
    data["migrations"] = [second, first]
    reversed_surface = manifest_module._effective_surface(  # noqa: SLF001
        worker="research-ai-gateway",
        config_path=config,
        environment="base",
        named_environment=None,
    )
    assert forward["migrations"] == [first, second]
    assert reversed_surface["migrations"] == [second, first]
    assert forward != reversed_surface


def test_unclassified_wrangler_key_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    config = manifest_module.WORKER_ROOT / "ingestion-premium" / "wrangler.toml"
    data = manifest_module._load_toml(config)  # noqa: SLF001
    data["future_unmodeled_binding"] = {"binding": "ESCAPED"}
    monkeypatch.setattr(manifest_module, "_load_toml", lambda _path: data)
    with pytest.raises(ValueError, match="unclassified top-level Wrangler keys"):
        manifest_module._effective_surface(  # noqa: SLF001
            worker="ingestion-premium",
            config_path=config,
            environment="base",
            named_environment=None,
        )


def test_removed_observability_fails_closed() -> None:
    drifted = copy.deepcopy(manifest_module.build_manifest())
    drifted["workers"]["ingestion-jsda"]["production"]["observability"] = {
        "enabled": False,
        "head_sampling_rate": 1,
    }
    with pytest.raises(ValueError, match="observability.enabled must be true"):
        manifest_module.validate_manifest(drifted)


def test_sampling_drift_fails_closed() -> None:
    drifted = copy.deepcopy(manifest_module.build_manifest())
    drifted["workers"]["ingestion-premium"]["staging"]["observability"][
        "head_sampling_rate"
    ] = 0.1
    with pytest.raises(ValueError, match="head_sampling_rate drifted"):
        manifest_module.validate_manifest(drifted)


def test_missing_version_metadata_binding_fails_closed() -> None:
    drifted = copy.deepcopy(manifest_module.build_manifest())
    drifted["workers"]["research-ai-gateway"]["base"]["version_metadata"] = {}
    with pytest.raises(ValueError, match="version_metadata binding"):
        manifest_module.validate_manifest(drifted)


def test_staging_surfaces_have_exact_workers_dev_and_secret_policy() -> None:
    manifest = manifest_module.build_manifest()
    for worker, environments in manifest["workers"].items():
        staging = environments["staging"]
        assert staging["workers_dev"] is (
            worker in {"receipt-activation-observer", "research-mass-eval"}
        )
        assert staging["preview_urls"] is False
        assert staging["secret_names"] == sorted(
            manifest_module.STAGING_SECRET_NAMES.get(worker, ())
        )
        assert staging["name"].endswith("-staging")


def test_research_mass_eval_staging_workers_dev_secret_and_production_unchanged() -> None:
    manifest = manifest_module.build_manifest()
    production = manifest["workers"]["research-mass-eval"]["production"]
    staging = manifest["workers"]["research-mass-eval"]["staging"]
    frozen = json.loads(manifest_module.MANIFEST.read_text(encoding="utf-8"))

    assert production["name"] == "quant-platform-research-mass-eval"
    assert production["workers_dev"] is True
    assert production["preview_urls"] is False
    assert production["secret_names"] == [
        "MASS_EVAL_TOKEN",
        "READY_ED25519_PRIVATE_KEY",
    ]
    assert production["route"] is None
    assert production["routes"] == []
    assert production["r2_buckets"] == [
        {"binding": "STRUCTURED_BUCKET", "bucket_name": "quant-structured"}
    ]

    assert staging["name"] == "quant-platform-research-mass-eval-staging"
    assert staging["workers_dev"] is True
    assert staging["preview_urls"] is False
    assert staging["secret_names"] == [
        "MASS_EVAL_TOKEN",
        "READY_ED25519_PRIVATE_KEY",
    ]
    assert staging["route"] is None
    assert staging["routes"] == []
    assert staging["r2_buckets"] == [
        {"binding": "STRUCTURED_BUCKET", "bucket_name": "quant-structured-staging"}
    ]

    assert frozen == manifest
    assert frozen["workers"]["research-mass-eval"]["production"] == production

    drifted = copy.deepcopy(manifest)
    drifted["workers"]["research-mass-eval"]["staging"]["workers_dev"] = False
    with pytest.raises(ValueError, match="token-gated personal route missing"):
        manifest_module.validate_manifest(drifted)

    secret_drifted = copy.deepcopy(manifest)
    secret_drifted["workers"]["research-mass-eval"]["staging"]["secret_names"] = []
    with pytest.raises(ValueError, match="secrets.required drifted"):
        manifest_module.validate_manifest(secret_drifted)

    production_drifted = copy.deepcopy(manifest)
    production_drifted["workers"]["research-mass-eval"]["production"][
        "workers_dev"
    ] = False
    with pytest.raises(ValueError, match="token-gated personal route missing"):
        manifest_module.validate_manifest(production_drifted)


def test_declared_production_secret_names_are_exact_policy() -> None:
    manifest = manifest_module.build_manifest()
    for worker, expected in manifest_module.PRODUCTION_SECRET_NAMES.items():
        names = sorted(expected)
        assert manifest["workers"][worker]["base"]["secret_names"] == names
        assert manifest["workers"][worker]["production"]["secret_names"] == names

    drifted = copy.deepcopy(manifest)
    drifted["workers"]["ingestion-jsda"]["production"]["secret_names"] = []
    with pytest.raises(ValueError, match="secrets.required drifted"):
        manifest_module.validate_manifest(drifted)


def _raw_status_payload(
    *,
    deployment_id: str = "a27ab31f-6431-464c-94e5-16b513b0d424",
    version_id: str = "9d40fa96-e5c6-409e-b7bd-d66a3877afb2",
    percentage: int = 100,
    extra_versions: list[dict[str, Any]] | None = None,
) -> str:
    versions = [{"version_id": version_id, "percentage": percentage}]
    if extra_versions:
        versions.extend(extra_versions)
    return json.dumps(
        {
            "id": deployment_id,
            "source": "wrangler",
            "strategy": "percentage",
            "annotations": {"workers/triggered_by": "secret"},
            "versions": versions,
            "created_on": "2026-09-09T15:53:11.56021Z",
        }
    )


def _version_view_payload(
    *,
    version_id: str = "9d40fa96-e5c6-409e-b7bd-d66a3877afb2",
    sha: str = "a" * 40,
    annotations: dict[str, str] | None = None,
) -> str:
    if annotations is None:
        annotations = {"workers/tag": sha, "workers/message": sha}
    return json.dumps(
        {
            "id": version_id,
            "metadata": {"source": "wrangler"},
            "annotations": annotations,
        }
    )


def test_parse_selected_deployment_requires_one_100_percent_version() -> None:
    selected = manifest_module.parse_selected_deployment(_raw_status_payload())
    assert selected == {
        "deployment_id": "a27ab31f-6431-464c-94e5-16b513b0d424",
        "version_id": "9d40fa96-e5c6-409e-b7bd-d66a3877afb2",
        "traffic_percent": "100",
    }
    with pytest.raises(ValueError):
        manifest_module.parse_selected_deployment("not-json")
    with pytest.raises(ValueError, match="100 percent"):
        manifest_module.parse_selected_deployment(_raw_status_payload(percentage=90))
    with pytest.raises(ValueError, match="exactly one version"):
        manifest_module.parse_selected_deployment(
            _raw_status_payload(
                extra_versions=[{"version_id": "other", "percentage": 0}]
            )
        )


def test_parse_selected_version_requires_id_and_exact_sha_annotations() -> None:
    sha = "a" * 40
    version_id = "9d40fa96-e5c6-409e-b7bd-d66a3877afb2"
    manifest_module.parse_selected_version(
        _version_view_payload(version_id=version_id, sha=sha),
        version_id=version_id,
        expected_sha=sha,
    )
    with pytest.raises(ValueError, match="does not match selected version"):
        manifest_module.parse_selected_version(
            _version_view_payload(version_id="other", sha=sha),
            version_id=version_id,
            expected_sha=sha,
        )
    with pytest.raises(ValueError, match="exact merged SHA"):
        manifest_module.parse_selected_version(
            _version_view_payload(
                version_id=version_id,
                annotations={"workers/message": sha},
            ),
            version_id=version_id,
            expected_sha=sha,
        )
    with pytest.raises(ValueError, match="exact merged SHA"):
        manifest_module.parse_selected_version(
            _version_view_payload(version_id=version_id, sha="b" * 40),
            version_id=version_id,
            expected_sha=sha,
        )
    with pytest.raises(ValueError, match="exact merged SHA"):
        manifest_module.parse_selected_version(
            json.dumps(
                {
                    "id": version_id,
                    "tag": sha,
                    "message": sha,
                    "annotations": {},
                }
            ),
            version_id=version_id,
            expected_sha=sha,
        )


_PACKAGE_DEPLOY_PROBE = """#!/usr/bin/env python3
import json, os, sys
from pathlib import Path
log = Path(os.environ["QP_PACKAGE_DEPLOY_PROBE"])
records = json.loads(log.read_text(encoding="utf-8")) if log.is_file() else []
records.append({"script": str(Path(__file__).resolve()), "argv": sys.argv[1:]})
log.write_text(json.dumps(records), encoding="utf-8")
if os.environ.get("QP_FAIL_SCRIPT") == Path(__file__).name:
    raise SystemExit(3)
"""
_MUTATION_STUB = """#!/bin/sh
printf '%s\\n' "$0 $*" >> "${QP_PACKAGE_DEPLOY_MUTATIONS:?}"
echo "unexpected mutation: $(basename "$0")" >&2
exit 99
"""
_OFFICIAL_ORIGIN = "https://github.com/ddnne/quant-platform.git"
_DEPLOY_SHA = "a" * 40


def _python_package_deploy_commands() -> tuple[tuple[str, str, str], ...]:
    commands: list[tuple[str, str, str]] = []
    for worker in manifest_module.ACTIVE_WORKERS:
        package = json.loads(
            (manifest_module.WORKER_ROOT / worker / "package.json").read_text(
                encoding="utf-8"
            )
        )
        for name, command in (package.get("scripts") or {}).items():
            if isinstance(command, str) and "python3" in command:
                commands.append((worker, name, command))
    return tuple(commands)


def _write_executable(path: Path, source: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source, encoding="utf-8")
    path.chmod(0o755)


def _synthetic_package_deploy_repo(tmp_path: Path) -> tuple[Path, Path, Path]:
    repo = tmp_path / "repo"
    scripts = repo / "scripts"
    scripts.mkdir(parents=True)
    for name in (
        "activate_jsda_v3_cutover.py",
        "cloudflare_binding_manifest.py",
        "predeploy_ops_projection_gate.py",
    ):
        (scripts / name).write_text(_PACKAGE_DEPLOY_PROBE, encoding="utf-8")
    for tool in ("git", "npm", "npx", "wrangler"):
        _write_executable(tmp_path / "bin" / tool, _MUTATION_STUB)
    probe_log = tmp_path / "probe.json"
    mutation_log = tmp_path / "mutations.log"
    probe_log.write_text("[]", encoding="utf-8")
    mutation_log.write_text("", encoding="utf-8")
    return repo, probe_log, mutation_log


def _run_package_deploy_command(
    *,
    repo: Path,
    worker: str,
    command: str,
    env: dict[str, str],
) -> subprocess.CompletedProcess[str]:
    cwd = repo / "platform" / "workers" / worker
    cwd.mkdir(parents=True, exist_ok=True)
    return subprocess.run(
        ["sh", "-c", command],
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def test_package_deploy_commands_resolve_from_worker_cwd(tmp_path: Path) -> None:
    commands = _python_package_deploy_commands()
    repo, probe_log, mutation_log = _synthetic_package_deploy_repo(tmp_path)
    env = {
        "PATH": f"{tmp_path / 'bin'}{os.pathsep}{os.environ.get('PATH', '')}",
        "HOME": str(tmp_path / "empty-home"),
        "LANG": "C",
        "QP_PACKAGE_DEPLOY_PROBE": str(probe_log),
        "QP_PACKAGE_DEPLOY_MUTATIONS": str(mutation_log),
    }
    expected_scripts = (repo / "scripts").resolve()
    for worker, name, command in commands:
        probe_log.write_text("[]", encoding="utf-8")
        mutation_log.write_text("", encoding="utf-8")
        result = _run_package_deploy_command(
            repo=repo, worker=worker, command=command, env=env
        )
        assert result.returncode == 0, f"{worker}:{name}: {result.stderr}"
        assert mutation_log.read_text(encoding="utf-8") == ""
        records = json.loads(probe_log.read_text(encoding="utf-8"))
        assert records and all(
            Path(row["script"]).parent == expected_scripts for row in records
        )


def test_ops_predeploy_failure_skips_tagged_deploy_leg(tmp_path: Path) -> None:
    command = next(
        command
        for worker, name, command in _python_package_deploy_commands()
        if worker == "quant-ops-mcp" and name == "deploy"
    )
    repo, probe_log, mutation_log = _synthetic_package_deploy_repo(tmp_path)
    env = {
        "PATH": f"{tmp_path / 'bin'}{os.pathsep}{os.environ.get('PATH', '')}",
        "HOME": str(tmp_path / "empty-home"),
        "LANG": "C",
        "QP_PACKAGE_DEPLOY_PROBE": str(probe_log),
        "QP_PACKAGE_DEPLOY_MUTATIONS": str(mutation_log),
        "QP_FAIL_SCRIPT": "predeploy_ops_projection_gate.py",
    }
    result = _run_package_deploy_command(
        repo=repo, worker="quant-ops-mcp", command=command, env=env
    )
    assert result.returncode == 3
    assert mutation_log.read_text(encoding="utf-8") == ""
    records = json.loads(probe_log.read_text(encoding="utf-8"))
    assert [Path(row["script"]).name for row in records] == [
        "predeploy_ops_projection_gate.py"
    ]


def _git(repo: Path, env: dict[str, str], *args: str) -> None:
    completed = subprocess.run(
        ["git", *args],
        cwd=repo,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr


def _host_npm_cli() -> tuple[Path, Path]:
    """Resolve real node/npm in the parent toolchain before a sterile child env."""
    node = shutil.which("node")
    if shutil.which("npm") is None or node is None:
        raise RuntimeError(
            "npm is required to exercise package-cwd deploy; normal CI requires npm"
        )
    reported = subprocess.run(
        [node, "-p", "process.execPath"],
        capture_output=True,
        text=True,
        check=False,
    )
    real_node = Path((reported.stdout or "").strip()).resolve()
    real_npm = real_node.parent / "npm"
    if reported.returncode != 0 or not real_node.is_file() or not real_npm.is_file():
        raise RuntimeError(
            "parent node/npm could not be resolved to real executables"
        )
    return real_node, real_npm


def test_real_wrapper_from_package_cwd_rejects_unmerged_before_wrangler(
    tmp_path: Path,
) -> None:
    node, npm = _host_npm_cli()
    repo = tmp_path / "repo"
    scripts = repo / "scripts"
    inventory = repo / "specs" / "cloudflare"
    worker = repo / "platform" / "workers" / "ingestion-premium"
    scripts.mkdir(parents=True)
    inventory.mkdir(parents=True)
    worker.mkdir(parents=True)
    for name in (
        "cloudflare_binding_manifest.py",
        "finding_ledger_gate.py",
        "predeploy_ops_projection_gate.py",
        "receipt_authority_pending_gate.py",
        "receipt_authority_pending_live_acceptance.py",
    ):
        shutil.copy2(ROOT / "scripts" / name, scripts / name)
    shutil.copy2(
        ROOT / "specs" / "cloudflare" / "active_workers.json",
        inventory / "active_workers.json",
    )
    shutil.copy2(
        ROOT / "platform" / "workers" / "ingestion-premium" / "wrangler.toml",
        worker / "wrangler.toml",
    )
    source_package = json.loads(
        (
            ROOT / "platform" / "workers" / "ingestion-premium" / "package.json"
        ).read_text(encoding="utf-8")
    )
    (worker / "package.json").write_text(
        json.dumps(
            {
                "name": source_package["name"],
                "private": True,
                "devDependencies": {"wrangler": "4.125.0"},
                "scripts": {"deploy": source_package["scripts"]["deploy"]},
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    git_home = tmp_path / "git-home"
    git_home.mkdir()
    git_env = {
        "PATH": os.environ.get("PATH", ""),
        "HOME": str(git_home),
        "GIT_CONFIG_GLOBAL": "/dev/null",
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_TERMINAL_PROMPT": "0",
        "GIT_ASKPASS": "/usr/bin/false",
    }
    _git(repo, git_env, "init", "--initial-branch=unmerged")
    _git(repo, git_env, "config", "user.email", "review@example.invalid")
    _git(repo, git_env, "config", "user.name", "review")
    _git(repo, git_env, "add", "scripts", "specs", "platform")
    _git(repo, git_env, "commit", "-m", "unmerged wrapper fixture")
    _git(
        repo,
        git_env,
        "remote",
        "add",
        "origin",
        "https://example.invalid/ddnne/quant-platform.git",
    )
    sentinel = tmp_path / "wrangler.log"
    fake_bin = tmp_path / "bin"
    _write_executable(
        fake_bin / "python3",
        f"#!/bin/sh\nexec {shlex.quote(sys.executable)} \"$@\"\n",
    )
    _write_executable(
        fake_bin / "wrangler",
        """#!/bin/sh
printf '%s\\n' "$0 $*" >> "${QP_WRANGLER_SENTINEL:?}"
echo wrangler-sentinel >&2
exit 99
""",
    )
    result = subprocess.run(
        [str(npm), "run", "deploy", "--prefix", str(worker)],
        cwd=repo,
        env={
            "PATH": os.pathsep.join(
                (str(fake_bin), str(node.parent), os.environ.get("PATH", ""))
            ),
            "HOME": str(tmp_path / "empty-home"),
            "LANG": "C",
            "QP_WRANGLER_SENTINEL": str(sentinel),
        },
        capture_output=True,
        text=True,
        check=False,
    )
    output = result.stdout + result.stderr
    assert result.returncode != 0
    assert "ModuleNotFoundError" not in output
    assert "current clean official origin/main" in output
    assert not sentinel.exists()


_ACCOUNT = manifest_module.PROJECT_ACCOUNT_ID
_TOKEN = "synthetic-bearer-token"
_VERSION_ID = "9d40fa96-e5c6-409e-b7bd-d66a3877afb2"
_MODULE_BODY = b"export default {fetch(){return new Response('ok')}};\n"
_LATEST_BODY = _MODULE_BODY + b"// latest-upload\n"


def _module_digest(body: bytes) -> str:
    return "sha256:" + hashlib.sha256(body).hexdigest()


def _upload_bundle(*, body: bytes = _MODULE_BODY) -> bytes:
    metadata = {"main_module": "index.js"}
    boundary = "----formdata-test-boundary"
    return b"".join(
        (
            f"--{boundary}\r\n".encode("ascii"),
            b'Content-Disposition: form-data; name="metadata"\r\n\r\n',
            json.dumps(metadata).encode("utf-8"),
            b"\r\n",
            f"--{boundary}\r\n".encode("ascii"),
            (
                b'Content-Disposition: form-data; name="index.js"; '
                b'filename="index.js"\r\n'
                b"Content-Type: application/javascript+module\r\n\r\n"
            ),
            body,
            b"\r\n",
            f"--{boundary}--\r\n".encode("ascii"),
        )
    )


def _version_modules_envelope(*, version_id: str, body: bytes) -> bytes:
    return json.dumps(
        {
            "success": True,
            "errors": [],
            "result": {
                "id": version_id,
                "main_module": "index.js",
                "modules": [
                    {
                        "name": "index.js",
                        "content_type": "application/javascript+module",
                        "content_base64": base64.b64encode(body).decode("ascii"),
                    }
                ],
            },
        }
    ).encode("utf-8")


class _FakeHttp:
    def __init__(self, payload: bytes) -> None:
        self._payload = payload

    def read(self, _limit: int) -> bytes:
        return self._payload

    def __enter__(self) -> "_FakeHttp":
        return self

    def __exit__(self, *_args: object) -> None:
        return None


def _write_fake_pinned_wrangler(
    root: Path, *, version: str = "4.125.0", entrypoint: bool = True
) -> Path:
    package = root / "node_modules" / "wrangler"
    bin_dir = package / "bin"
    bin_dir.mkdir(parents=True)
    entry = bin_dir / "wrangler.js"
    entry.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    entry.chmod(0o755)
    (package / "package.json").write_text(
        json.dumps({"name": "wrangler", "version": version}) + "\n",
        encoding="utf-8",
    )
    shim = root / "node_modules" / ".bin" / "wrangler"
    shim.parent.mkdir(parents=True, exist_ok=True)
    if entrypoint:
        shim.symlink_to(entry)
    else:
        shim.write_text("#!/bin/sh\nprintf '4.125.0\\n'\n", encoding="utf-8")
        shim.chmod(0o755)
    return shim


def _git_ok(
    argv: tuple[str, ...], *, sha: str = _DEPLOY_SHA
) -> subprocess.CompletedProcess[str] | None:
    if argv == ("git", "rev-parse", "HEAD"):
        return subprocess.CompletedProcess(argv, 0, sha + "\n", "")
    if argv == ("git", "remote", "get-url", "origin"):
        return subprocess.CompletedProcess(argv, 0, _OFFICIAL_ORIGIN + "\n", "")
    if argv == (
        "git",
        "rev-parse",
        "--verify",
        "refs/remotes/origin/main^{commit}",
    ):
        return subprocess.CompletedProcess(argv, 0, sha + "\n", "")
    if argv[:4] == ("git", "ls-remote", "--exit-code", "--refs"):
        return subprocess.CompletedProcess(argv, 0, f"{sha}\trefs/heads/main\n", "")
    return None


def _canonical_runner(
    *,
    executable: str,
    body: bytes = _MODULE_BODY,
    live_body: bytes | None = None,
    latest_body: bytes = _LATEST_BODY,
    status_payloads: list[str] | None = None,
    version_payloads: list[str] | None = None,
    whoami_account: str | None = None,
    final_sha: str | None = None,
) -> Any:
    status_index = 0
    version_index = 0
    git_heads = 0
    live_body = body if live_body is None else live_body
    statuses = status_payloads or [_raw_status_payload()]
    versions = version_payloads or [_version_view_payload(sha=_DEPLOY_SHA)]
    account = whoami_account or _ACCOUNT
    urls: list[str] = []
    calls: list[dict[str, Any]] = []

    def runner(command, **kwargs):
        nonlocal status_index, version_index, git_heads
        argv = tuple(command)
        calls.append({"argv": argv, "kwargs": dict(kwargs)})
        if argv == ("git", "rev-parse", "HEAD"):
            git_heads += 1
        git = _git_ok(
            argv,
            sha=final_sha if final_sha is not None and git_heads >= 2 else _DEPLOY_SHA,
        )
        if git is not None:
            return git
        if argv and argv[0] != executable:
            raise AssertionError(argv)
        if argv[1:3] == ("auth", "token"):
            return subprocess.CompletedProcess(
                argv, 0, json.dumps({"type": "api_token", "token": _TOKEN}), ""
            )
        if argv[1] == "whoami":
            return subprocess.CompletedProcess(
                argv,
                0,
                json.dumps(
                    {"loggedIn": True, "accounts": [{"id": account, "name": "quant"}]}
                ),
                "",
            )
        if argv[1] == "deploy" and "--dry-run" in argv:
            Path(argv[argv.index("--outfile") + 1]).write_bytes(_upload_bundle(body=body))
            assert "--experimental-new-config" not in argv
            return subprocess.CompletedProcess(argv, 0, "", "")
        if argv[1] == "deploy":
            return subprocess.CompletedProcess(argv, 0, "", "")
        if argv[1:3] == ("deployments", "status"):
            payload = statuses[min(status_index, len(statuses) - 1)]
            status_index += 1
            return subprocess.CompletedProcess(argv, 0, payload, "")
        if argv[1:3] == ("versions", "view"):
            payload = versions[min(version_index, len(versions) - 1)]
            version_index += 1
            return subprocess.CompletedProcess(argv, 0, payload, "")
        raise AssertionError(argv)

    def opener(request: Request, timeout: int = 30) -> _FakeHttp:
        url = request.full_url
        urls.append(url)
        payload_body = latest_body if "latest" in url else live_body
        if _VERSION_ID in url:
            payload_body = live_body
        return _FakeHttp(
            _version_modules_envelope(version_id=_VERSION_ID, body=payload_body)
        )

    runner.opener = opener  # type: ignore[attr-defined]
    runner.calls = calls  # type: ignore[attr-defined]
    runner.urls = urls  # type: ignore[attr-defined]
    return runner


def _prepare_pin(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> str:
    layout = tmp_path / "pin-layout"
    shim = _write_fake_pinned_wrangler(layout)
    original = manifest_module._require_pinned_local_wrangler
    monkeypatch.setattr(
        manifest_module,
        "_require_pinned_local_wrangler",
        lambda _directory: original(layout),
    )
    return str(shim)


def _official_main(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "scripts.receipt_authority_pending_gate._require_exact_clean_source",
        lambda _sha: None,
    )


_SENTINEL_SECRET = "fake-sentinel-secret-must-not-leak"


def _wrangler_argvs(runner: Any, executable: str) -> list[tuple[str, ...]]:
    return [
        row["argv"]
        for row in runner.calls
        if row["argv"] and row["argv"][0] == executable
    ]


def _assert_canonical_child_isolation(
    runner: Any,
    *,
    worker: str,
    executable: str,
    config: str,
    environment_args: tuple[str, ...],
) -> None:
    worker_cwd = str(manifest_module.WORKER_ROOT / worker)
    wrangler = [
        row for row in runner.calls if row["argv"] and row["argv"][0] == executable
    ]
    dry_run = next(
        row
        for row in wrangler
        if row["argv"][1] == "deploy" and "--dry-run" in row["argv"]
    )
    mutate = next(
        row
        for row in wrangler
        if row["argv"][1] == "deploy" and "--dry-run" not in row["argv"]
    )
    authenticated = [
        row
        for row in wrangler
        if row["argv"][1] in {"whoami", "deploy"}
        or row["argv"][1:3] in {("deployments", "status"), ("versions", "view")}
    ]
    for row in wrangler:
        assert row["kwargs"].get("cwd") == worker_cwd
    assert dry_run["argv"][dry_run["argv"].index("--config") + 1] == config
    mutate_args = mutate["argv"]
    assert mutate_args[mutate_args.index("--config") + 1] == config
    if environment_args:
        assert mutate_args[-len(environment_args) :] == environment_args
    else:
        assert "--env" not in mutate_args
    build_env = dry_run["kwargs"]["env"]
    assert "CLOUDFLARE_API_TOKEN" not in build_env
    assert "CLOUDFLARE_ACCOUNT_ID" not in build_env
    assert _SENTINEL_SECRET not in build_env.values()
    assert "AWS_SECRET_ACCESS_KEY" not in build_env
    for row in authenticated:
        if row is dry_run:
            continue
        env = row["kwargs"]["env"]
        assert env["CLOUDFLARE_ACCOUNT_ID"] == _ACCOUNT
        assert env["CLOUDFLARE_API_TOKEN"] == _TOKEN
        assert _SENTINEL_SECRET not in env.values()
        assert "AWS_SECRET_ACCESS_KEY" not in env


def test_pinned_wrangler_requires_package_entrypoint_and_installed_version(
    tmp_path: Path,
) -> None:
    layout = tmp_path / "good"
    _write_fake_pinned_wrangler(layout)
    assert manifest_module._require_pinned_local_wrangler(layout).endswith("wrangler")
    wrong = tmp_path / "wrong"
    _write_fake_pinned_wrangler(wrong, entrypoint=False)
    with pytest.raises(ValueError, match="package entrypoint"):
        manifest_module._require_pinned_local_wrangler(wrong)
    drifted = tmp_path / "drifted"
    _write_fake_pinned_wrangler(drifted, version="4.0.0")
    with pytest.raises(ValueError, match="installed Wrangler pin is not exact"):
        manifest_module._require_pinned_local_wrangler(drifted)


@pytest.mark.parametrize(
    "origin_url,origin_main,remote_main",
    (
        ("https://example.invalid/ddnne/quant-platform.git", _DEPLOY_SHA, _DEPLOY_SHA),
        (_OFFICIAL_ORIGIN, "f" * 40, _DEPLOY_SHA),
        (_OFFICIAL_ORIGIN, _DEPLOY_SHA, "f" * 40),
    ),
)
def test_deploy_tagged_rejects_unofficial_or_stale_main_before_wrangler(
    monkeypatch: pytest.MonkeyPatch,
    origin_url: str,
    origin_main: str,
    remote_main: str,
) -> None:
    _official_main(monkeypatch)
    calls: list[tuple[str, ...]] = []

    def runner(command, **_kwargs):
        argv = tuple(command)
        calls.append(argv)
        if argv == ("git", "rev-parse", "HEAD"):
            return subprocess.CompletedProcess(argv, 0, _DEPLOY_SHA + "\n", "")
        if argv == ("git", "remote", "get-url", "origin"):
            return subprocess.CompletedProcess(argv, 0, origin_url + "\n", "")
        if argv == (
            "git",
            "rev-parse",
            "--verify",
            "refs/remotes/origin/main^{commit}",
        ):
            return subprocess.CompletedProcess(argv, 0, origin_main + "\n", "")
        if argv[:4] == ("git", "ls-remote", "--exit-code", "--refs"):
            return subprocess.CompletedProcess(
                argv, 0, f"{remote_main}\trefs/heads/main\n", ""
            )
        raise AssertionError(f"wrangler ran before provenance: {argv}")

    with pytest.raises(ValueError, match="current clean official origin/main"):
        manifest_module.deploy_tagged(
            worker="ingestion-premium",
            environment="production",
            runner=runner,
            environ={"CLOUDFLARE_API_TOKEN": _TOKEN},
        )
    assert all("deploy" not in call for call in calls)


def test_deploy_tagged_production_uses_pinned_executable_cwd_and_env(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _official_main(monkeypatch)
    executable = _prepare_pin(tmp_path, monkeypatch)
    runner = _canonical_runner(executable=executable)
    result = manifest_module.deploy_tagged(
        worker="ingestion-premium",
        environment="production",
        runner=runner,
        opener=runner.opener,
        environ={
            "CLOUDFLARE_API_TOKEN": _TOKEN,
            "PATH": os.environ.get("PATH", ""),
            "AWS_SECRET_ACCESS_KEY": _SENTINEL_SECRET,
        },
    )
    _assert_canonical_child_isolation(
        runner,
        worker="ingestion-premium",
        executable=executable,
        config="wrangler.toml",
        environment_args=("--env", "production"),
    )
    wrangler = _wrangler_argvs(runner, executable)
    view = [call for call in wrangler if call[1:3] == ("versions", "view")]
    assert len(view) == 2
    assert all(_VERSION_ID in url and "latest" not in url for url in runner.urls)
    assert result["modules"][0]["digest"] == _module_digest(_MODULE_BODY)
    assert '"result":"VERIFIED_EXACT_MODULE_BYTES"' in capsys.readouterr().out


def test_deploy_tagged_staging_omits_env_selector(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _official_main(monkeypatch)
    executable = _prepare_pin(tmp_path, monkeypatch)
    runner = _canonical_runner(executable=executable)
    manifest_module.deploy_tagged(
        worker="ingestion-premium",
        environment="staging",
        runner=runner,
        opener=runner.opener,
        environ={"CLOUDFLARE_API_TOKEN": _TOKEN, "PATH": os.environ.get("PATH", "")},
    )
    wrangler = _wrangler_argvs(runner, executable)
    deploy = next(
        call for call in wrangler if call[1] == "deploy" and "--dry-run" not in call
    )
    assert "wrangler.staging.toml" in deploy
    assert "--env" not in deploy
    assert all(
        "--env" not in call
        for call in wrangler
        if call[1:3] == ("deployments", "status")
    )


@pytest.mark.parametrize(
    "worker,match",
    (
        ("ingestion-jsda", "specialized or PENDING"),
        ("ingestion-secrets", "specialized or PENDING"),
        ("research-mass-eval", "Container image"),
    ),
)
def test_deploy_tagged_rejects_specialized_pending_and_mass_before_mutation(
    worker: str,
    match: str,
) -> None:
    calls: list[tuple[str, ...]] = []

    def runner(command, **_kwargs):
        calls.append(tuple(command))
        raise AssertionError(command)

    with pytest.raises(ValueError, match=match):
        manifest_module.deploy_tagged(
            worker=worker,
            environment="production",
            runner=runner,
            environ={"CLOUDFLARE_API_TOKEN": _TOKEN},
        )
    assert calls == []


def test_deploy_tagged_requires_quant_ops_gate_before_mutation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from scripts.predeploy_ops_projection_gate import PredeployGateError

    _official_main(monkeypatch)
    executable = _prepare_pin(tmp_path, monkeypatch)
    invoked = {"gate": 0}

    def gate(environment: str, **_kwargs: object) -> dict[str, object]:
        invoked["gate"] += 1
        raise PredeployGateError("projection is not SEALED")

    monkeypatch.setattr(
        "scripts.predeploy_ops_projection_gate.require_sealed_active_generation",
        gate,
    )
    runner = _canonical_runner(executable=executable)
    with pytest.raises(ValueError, match="ops projection predeploy gate failed"):
        manifest_module.deploy_tagged(
            worker="quant-ops-mcp",
            environment="production",
            runner=runner,
            opener=runner.opener,
            environ={"CLOUDFLARE_API_TOKEN": _TOKEN, "PATH": os.environ.get("PATH", "")},
        )
    assert invoked["gate"] == 1
    assert not any(
        call[1] == "deploy" and "--dry-run" not in call
        for call in _wrangler_argvs(runner, executable)
    )


@pytest.mark.parametrize(
    "environ,match",
    (
        (
            {"CLOUDFLARE_API_TOKEN": _TOKEN, "CLOUDFLARE_ACCOUNT_ID": "0" * 32},
            "approved project account",
        ),
        (
            {"CLOUDFLARE_API_TOKEN": _TOKEN, "CF_ACCOUNT_ID": "0" * 32},
            "approved project account",
        ),
        (
            {
                "CLOUDFLARE_API_TOKEN": _TOKEN,
                "WRANGLER_CI_OVERRIDE_NAME": "quant-platform-rogue",
            },
            "WRANGLER_CI_OVERRIDE_NAME",
        ),
    ),
)
def test_deploy_tagged_rejects_wrong_account_or_name_override(
    environ: dict[str, str],
    match: str,
) -> None:
    def runner(command, **_kwargs):
        raise AssertionError(command)

    with pytest.raises(ValueError, match=match):
        manifest_module.deploy_tagged(
            worker="ingestion-premium",
            environment="production",
            runner=runner,
            environ=environ,
        )


def test_deploy_tagged_rejects_conflicting_tracked_account_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = manifest_module._load_toml

    def load_toml(path: Path) -> dict[str, Any]:
        data = original(path)
        data["account_id"] = "0" * 32
        return data

    monkeypatch.setattr(manifest_module, "_load_toml", load_toml)

    def runner(command, **_kwargs):
        raise AssertionError(command)

    with pytest.raises(ValueError, match="approved project account"):
        manifest_module.deploy_tagged(
            worker="ingestion-premium",
            environment="production",
            runner=runner,
            environ={"CLOUDFLARE_API_TOKEN": _TOKEN},
        )


def test_deploy_tagged_rejects_module_mismatch_and_latest_confusion(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _official_main(monkeypatch)
    executable = _prepare_pin(tmp_path, monkeypatch)
    runner = _canonical_runner(executable=executable, live_body=_LATEST_BODY)
    with pytest.raises(ValueError, match="differs from the clean reviewed source build"):
        manifest_module.deploy_tagged(
            worker="ingestion-premium",
            environment="production",
            runner=runner,
            opener=runner.opener,
            environ={"CLOUDFLARE_API_TOKEN": _TOKEN, "PATH": os.environ.get("PATH", "")},
        )
    assert all("latest" not in url for url in runner.urls)


def test_deploy_tagged_rejects_selected_deployment_and_version_provenance_drift(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _official_main(monkeypatch)
    executable = _prepare_pin(tmp_path, monkeypatch)
    runner = _canonical_runner(
        executable=executable,
        status_payloads=[
            _raw_status_payload(),
            _raw_status_payload(deployment_id="switched"),
        ],
    )
    with pytest.raises(ValueError, match="changed during version read"):
        manifest_module.deploy_tagged(
            worker="ingestion-premium",
            environment="production",
            runner=runner,
            opener=runner.opener,
            environ={"CLOUDFLARE_API_TOKEN": _TOKEN, "PATH": os.environ.get("PATH", "")},
        )
    runner = _canonical_runner(
        executable=executable,
        version_payloads=[
            _version_view_payload(sha=_DEPLOY_SHA),
            _version_view_payload(
                sha=_DEPLOY_SHA,
                annotations={
                    "workers/tag": _DEPLOY_SHA,
                    "workers/message": _DEPLOY_SHA,
                    "workers/triggered_by": "other",
                },
            ),
        ],
    )
    with pytest.raises(ValueError, match="selected version changed during module read"):
        manifest_module.deploy_tagged(
            worker="ingestion-premium",
            environment="production",
            runner=runner,
            opener=runner.opener,
            environ={"CLOUDFLARE_API_TOKEN": _TOKEN, "PATH": os.environ.get("PATH", "")},
        )


def test_deploy_tagged_rechecks_source_and_redacts_credentials(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _official_main(monkeypatch)
    executable = _prepare_pin(tmp_path, monkeypatch)
    runner = _canonical_runner(executable=executable, final_sha="b" * 40)
    with pytest.raises(ValueError, match="merged SHA changed during tagged deploy"):
        manifest_module.deploy_tagged(
            worker="ingestion-premium",
            environment="production",
            runner=runner,
            opener=runner.opener,
            environ={"CLOUDFLARE_API_TOKEN": _TOKEN, "PATH": os.environ.get("PATH", "")},
        )

    def runner_fail(command, **_kwargs):
        argv = tuple(command)
        git = _git_ok(argv)
        if git is not None:
            return git
        if argv and argv[0] == executable and argv[1:3] == ("auth", "token"):
            return subprocess.CompletedProcess(
                argv,
                0,
                json.dumps({"type": "oauth", "token": "super-secret-oauth-token"}),
                "",
            )
        if argv and argv[0] == executable and argv[1] == "whoami":
            return subprocess.CompletedProcess(argv, 1, "", "auth failed")
        raise AssertionError(argv)

    with pytest.raises(ValueError) as excinfo:
        manifest_module.deploy_tagged(
            worker="ingestion-premium",
            environment="production",
            runner=runner_fail,
            environ={"PATH": os.environ.get("PATH", "")},
        )
    assert "super-secret-oauth-token" not in str(excinfo.value)
