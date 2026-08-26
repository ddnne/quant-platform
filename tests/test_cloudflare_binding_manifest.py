"""Behavioral checks for the frozen active-Worker deployment surface."""

from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path

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
    with pytest.raises(ValueError, match="must pin --config=wrangler.toml"):
        manifest_module._package_scripts(worker)  # noqa: SLF001


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
    logical_lines = ci.replace("\\\n", " ").splitlines()
    wrangler_invocations = [
        line.strip()
        for line in logical_lines
        if "npx --no-install wrangler " in line and not line.lstrip().startswith("#")
    ]
    assert wrangler_invocations
    for command in wrangler_invocations:
        assert "--config=" in command, command
        assert "--env=" in command, command


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


def test_staging_surfaces_are_private_and_have_no_production_secret_policy() -> None:
    manifest = manifest_module.build_manifest()
    for environments in manifest["workers"].values():
        staging = environments["staging"]
        assert staging["workers_dev"] is False
        assert staging["preview_urls"] is False
        assert staging["secret_names"] == []
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
