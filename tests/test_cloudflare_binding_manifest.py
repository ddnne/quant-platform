"""Behavioral checks for the frozen active-Worker deployment surface."""

from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path
import shlex

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
        "ingestion-premium": [{
            "name": "PremiumReceiptOperatorService",
            "handlers": ["class"],
            "fetch_reserved_special": False,
            "rpc_methods": [
                "pending_public_key_registration",
                "staging_recovery_audit_evidence",
            ],
        }],
        "research-ai-gateway": [{
            "name": "GatewayService",
            "handlers": ["class"],
            "fetch_reserved_special": False,
            "rpc_methods": ["complete"],
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
            "heartbeat",
            "markProviderStarted",
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
    for environment in ("base", "production"):
        surface = observer[environment]
        assert surface["workers_dev"] is False
        assert surface["services"] == []
        assert surface["secret_names"] == []
        assert surface["route"] is None
        assert surface["routes"] == []
    staging = observer["staging"]
    assert staging["workers_dev"] is True
    assert staging["preview_urls"] is False
    assert staging["services"] == [{
        "binding": "PREMIUM_RECEIPT_OPERATOR",
        "entrypoint": "PremiumReceiptOperatorService",
        "service": "quant-platform-ingestion-premium-staging",
    }]
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
    "script,command",
    (
        (
            "deploy",
            "wran''gler deploy --config=wran''gler.toml --env=production "
            "--name quant-platform-rogue",
        ),
        ("deploy", "node scripts/deploy-shadow.js"),
        ("test", "node scripts/deploy-shadow.js"),
        ("shadow", "node scripts/deploy-shadow.js"),
    ),
)
def test_all_package_script_roles_are_independently_pinned(
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
            worker == "receipt-activation-observer"
        )
        assert staging["preview_urls"] is False
        assert staging["secret_names"] == sorted(
            manifest_module.STAGING_SECRET_NAMES.get(worker, ())
        )
        assert staging["name"].endswith("-staging")


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
