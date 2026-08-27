#!/usr/bin/env python3
"""Freeze every active Cloudflare Worker deployment surface.

The manifest is intentionally generated from Wrangler TOML plus an explicit
secret-name policy. It contains names only; secret values are never read.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tomllib
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "specs" / "cloudflare" / "active_worker_bindings.json"
INVENTORY = ROOT / "specs" / "cloudflare" / "active_workers.json"
WORKER_ROOT = ROOT / "platform" / "workers"
_WORKER_DIRECTORY_RE = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*\Z")
_ALLOWED_WRANGLER_CONFIGS = frozenset(
    {"wrangler.toml", "wrangler.staging.toml", "wrangler.test.toml"}
)
_ALLOWED_WORKER_CONTROL_FILES = _ALLOWED_WRANGLER_CONFIGS | frozenset(
    {"package.json", "package-lock.json", "tsconfig.json"}
)
_DEPLOYMENT_CONTROL_SUFFIXES = frozenset({".toml", ".json", ".jsonc"})
_EXPERIMENTAL_WRANGLER_CONFIGS = frozenset(
    {"cloudflare.config.ts", "wrangler.config.ts"}
)
_REPOSITORY_SCAN_PRUNED_DIRS = frozenset(
    {
        ".git",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".venv",
        ".wrangler",
        ".wrangler-dry-run",
        "node_modules",
    }
)


def _load_active_workers(path: Path = INVENTORY) -> tuple[str, ...]:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"active Worker inventory is unreadable: {path}") from exc
    if not isinstance(document, dict) or set(document) != {"schema_version", "workers"}:
        raise ValueError("active Worker inventory fields are not closed")
    if document["schema_version"] != "cloudflare-active-worker-inventory/v1":
        raise ValueError("active Worker inventory schema_version drift")
    workers = document["workers"]
    if (
        not isinstance(workers, list)
        or not workers
        or not all(
            isinstance(worker, str)
            and _WORKER_DIRECTORY_RE.fullmatch(worker) is not None
            for worker in workers
        )
        or len(workers) != len(set(workers))
        or workers != sorted(workers)
    ):
        raise ValueError("active Worker inventory must be a sorted unique non-empty list")
    return tuple(workers)


ACTIVE_WORKERS = _load_active_workers()


def _wrangler_config_paths(worker_root: Path = WORKER_ROOT) -> tuple[Path, ...]:
    discovered: list[Path] = []
    for current, directories, filenames in os.walk(worker_root):
        directories[:] = [
            name for name in directories if name not in {".wrangler", "node_modules"}
        ]
        parent = Path(current)
        for name in filenames:
            if _is_wrangler_config_filename(name):
                discovered.append(parent / name)
    return tuple(sorted(discovered))


def _is_wrangler_config_filename(name: str) -> bool:
    return (
        name.startswith("wrangler")
        and Path(name).suffix in _DEPLOYMENT_CONTROL_SUFFIXES
    ) or name in _EXPERIMENTAL_WRANGLER_CONFIGS


def _is_deployment_control_filename(name: str) -> bool:
    return (
        Path(name).suffix in _DEPLOYMENT_CONTROL_SUFFIXES
        or name in _EXPERIMENTAL_WRANGLER_CONFIGS
    )


def _deployment_control_paths(worker_root: Path = WORKER_ROOT) -> tuple[Path, ...]:
    """Find every file type that Wrangler or a package script can use as config."""
    discovered: list[Path] = []
    for current, directories, filenames in os.walk(worker_root):
        directories[:] = [
            name for name in directories if name not in {".wrangler", "node_modules"}
        ]
        parent = Path(current)
        for name in filenames:
            if _is_deployment_control_filename(name):
                discovered.append(parent / name)
    return tuple(sorted(discovered))


def _package_is_wrangler_marker(path: Path) -> bool:
    try:
        package = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ValueError(f"repository package marker is unreadable: {path}") from exc
    if not isinstance(package, dict):
        raise ValueError(f"repository package marker must be an object: {path}")
    runtime_dependencies = package.get("dependencies") or {}
    development_dependencies = package.get("devDependencies") or {}
    scripts = package.get("scripts") or {}
    if not all(
        isinstance(value, dict)
        for value in (runtime_dependencies, development_dependencies, scripts)
    ):
        raise ValueError(f"repository package marker fields are invalid: {path}")
    dependencies = {**runtime_dependencies, **development_dependencies}
    deployment_roles = {"cf-typegen", "deploy", "dev", "tail"}
    return (
        "wrangler" in dependencies
        or bool(deployment_roles & set(scripts))
        or any(
            isinstance(command, str) and re.search(r"\bwrangler\b", command)
            for command in scripts.values()
        )
    )


def _repository_worker_marker_paths(repo_root: Path = ROOT) -> tuple[Path, ...]:
    markers: list[Path] = []
    for current, directories, filenames in os.walk(repo_root):
        directories[:] = [
            name for name in directories if name not in _REPOSITORY_SCAN_PRUNED_DIRS
        ]
        parent = Path(current)
        for name in filenames:
            path = parent / name
            if _is_wrangler_config_filename(name):
                markers.append(path)
            elif name == "package.json" and _package_is_wrangler_marker(path):
                markers.append(path)
    return tuple(sorted(markers))


def validate_repository_worker_boundary(
    *,
    repo_root: Path = ROOT,
    worker_root: Path = WORKER_ROOT,
    workers: tuple[str, ...] = ACTIVE_WORKERS,
) -> None:
    expected = {
        worker_root / worker / "package.json"
        for worker in workers
    }
    expected.update(
        worker_root / worker / config
        for worker in workers
        for config in _ALLOWED_WRANGLER_CONFIGS
        if (worker_root / worker / config).is_file()
    )
    observed = set(_repository_worker_marker_paths(repo_root))
    if observed != expected:
        missing = sorted(str(path.relative_to(repo_root)) for path in expected - observed)
        ungoverned = sorted(
            str(path.relative_to(repo_root)) for path in observed - expected
        )
        raise ValueError(
            "repository Worker deployment boundary drift: "
            f"missing={missing!r}, ungoverned={ungoverned!r}"
        )


def _deployable_worker_directories(worker_root: Path = WORKER_ROOT) -> tuple[str, ...]:
    """Discover every directory that has any Worker deployment marker."""
    discovered = {
        path.parent.relative_to(worker_root).as_posix()
        for path in _deployment_control_paths(worker_root)
        if path.name == "package.json"
    }
    for path in _wrangler_config_paths(worker_root):
        discovered.add(path.parent.relative_to(worker_root).as_posix())
    return tuple(sorted(discovered))


def validate_active_worker_inventory(
    workers: tuple[str, ...] = ACTIVE_WORKERS,
    *,
    worker_root: Path = WORKER_ROOT,
) -> None:
    if worker_root == WORKER_ROOT:
        validate_repository_worker_boundary(workers=workers)
    discovered = _deployable_worker_directories(worker_root)
    if discovered != workers:
        missing = sorted(set(workers) - set(discovered))
        ungoverned = sorted(set(discovered) - set(workers))
        raise ValueError(
            "active Worker inventory/filesystem drift: "
            f"missing={missing!r}, ungoverned={ungoverned!r}"
        )
    unexpected_controls = sorted(
        str(path.relative_to(worker_root))
        for path in _deployment_control_paths(worker_root)
        if (
            len(path.relative_to(worker_root).parts) != 2
            or path.relative_to(worker_root).parts[0] not in workers
            or path.name not in _ALLOWED_WORKER_CONTROL_FILES
        )
    )
    if unexpected_controls:
        raise ValueError(
            "active Worker has an ungoverned deployment control file: "
            f"{unexpected_controls!r}"
        )
    required = (
        "package.json",
        "package-lock.json",
        "wrangler.toml",
        "wrangler.staging.toml",
    )
    for worker in workers:
        absent = [name for name in required if not (worker_root / worker / name).is_file()]
        if absent:
            raise ValueError(f"{worker}: active Worker files missing: {absent!r}")

TOOLCHAIN = {
    "wrangler": "4.125.0",
    "@cloudflare/workers-types": "5.20260825.1",
    "typescript": "5.9.2",
    "vitest": "4.1.11",
    "@cloudflare/vitest-plugin": "1.0.0",
}

# Names are policy. Values remain exclusively in Cloudflare Secrets.
PRODUCTION_SECRET_NAMES: dict[str, tuple[str, ...]] = {
    "ingestion-jsda": ("INGESTION_RUN_TOKEN",),
    "ingestion-premium": (
        "DATA_EXPORT_TOKEN",
        "INGESTION_RUN_TOKEN",
        "JQUANTS_API_KEY",
    ),
    "ingestion-secrets": (
        "JQUANTS_API_KEY",
        "JQUANTS_PROXY_TOKEN",
        "JQUANTS_RPC_CURSOR_HMAC_KEY",
    ),
    "quant-ops-mcp": (
        "GITHUB_CLIENT_ID",
        "GITHUB_CLIENT_SECRET",
        "STATE_SECRET",
    ),
    "receipt-evidence-authority": ("RECEIPT_KEY_WRAP_KEY",),
    "research-ai-gateway": ("GATEWAY_TOKEN",),
    "research-mass-eval": ("MASS_EVAL_TOKEN",),
}

STAGING_SECRET_NAMES: dict[str, tuple[str, ...]] = {
    "receipt-evidence-authority": ("RECEIPT_KEY_WRAP_KEY",),
}


def _load_toml(path: Path) -> dict[str, Any]:
    with path.open("rb") as fh:
        return tomllib.load(fh)


_WRANGLER_PACKAGE_SCRIPT_POLICY = {
    "build": (
        'wrangler deploy --dry-run --config=wrangler.toml --env="" '
        "--outdir .wrangler-dry-run"
    ),
    "cf-typegen": 'wrangler types --config=wrangler.toml --env=""',
    "deploy": "wrangler deploy --config=wrangler.toml --env=production",
    "dev": 'wrangler dev --config=wrangler.toml --env=""',
    "tail": "wrangler tail --config=wrangler.toml --env=production",
    "types": (
        'wrangler types --config=wrangler.toml --env="" --include-runtime false'
    ),
}
_COMMON_PACKAGE_SCRIPTS = {
    "build": _WRANGLER_PACKAGE_SCRIPT_POLICY["build"],
    "typecheck": "tsc --noEmit",
    "types": _WRANGLER_PACKAGE_SCRIPT_POLICY["types"],
}
_PINNED_PACKAGE_SCRIPTS = {
    "ingestion-jsda": {
        **_COMMON_PACKAGE_SCRIPTS,
        "deploy": _WRANGLER_PACKAGE_SCRIPT_POLICY["deploy"],
        "tail": _WRANGLER_PACKAGE_SCRIPT_POLICY["tail"],
        "test": (
            "vitest run --config vitest.config.ts && "
            "vitest run --config vitest.runtime.config.ts"
        ),
    },
    "ingestion-premium": {
        **_COMMON_PACKAGE_SCRIPTS,
        "cf-typegen": _WRANGLER_PACKAGE_SCRIPT_POLICY["cf-typegen"],
        "test": "vitest run",
    },
    "ingestion-secrets": {
        **_COMMON_PACKAGE_SCRIPTS,
        "cf-typegen": _WRANGLER_PACKAGE_SCRIPT_POLICY["cf-typegen"],
        "test": (
            "vitest run --config vitest.config.ts && "
            "vitest run --config vitest.runtime.config.ts && "
            "node --test harness/*.test.mjs"
        ),
    },
    "quant-ops-mcp": {
        **_COMMON_PACKAGE_SCRIPTS,
        "deploy": _WRANGLER_PACKAGE_SCRIPT_POLICY["deploy"],
        "test": (
            "node --experimental-test-module-mocks --test test/*.test.mjs && "
            "vitest run --config vitest.runtime.config.ts && "
            "vitest run --config vitest.harness.config.ts"
        ),
    },
    "receipt-evidence-authority": {
        **_COMMON_PACKAGE_SCRIPTS,
        "cf-typegen": _WRANGLER_PACKAGE_SCRIPT_POLICY["cf-typegen"],
        "test": "vitest run --config vitest.runtime.config.ts",
    },
    "research-ai-gateway": {
        **_COMMON_PACKAGE_SCRIPTS,
        "deploy": _WRANGLER_PACKAGE_SCRIPT_POLICY["deploy"],
        "test": (
            "vitest run --config vitest.config.ts && "
            "vitest run --config vitest.harness.config.ts"
        ),
    },
    "research-mass-eval": {
        **_COMMON_PACKAGE_SCRIPTS,
        "deploy": _WRANGLER_PACKAGE_SCRIPT_POLICY["deploy"],
        "dev": _WRANGLER_PACKAGE_SCRIPT_POLICY["dev"],
        "tail": _WRANGLER_PACKAGE_SCRIPT_POLICY["tail"],
        "test": "vitest run",
    },
}


def _package_scripts(worker: str) -> dict[str, str]:
    path = WORKER_ROOT / worker / "package.json"
    try:
        package = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"{worker}: package.json is unreadable") from exc
    if not isinstance(package, dict):
        raise ValueError(f"{worker}: package.json must contain an object")
    scripts = package.get("scripts") or {}
    if not isinstance(scripts, dict) or not all(
        isinstance(name, str) and isinstance(command, str)
        for name, command in scripts.items()
    ):
        raise ValueError(f"{worker}: package scripts must be a string map")
    frozen = dict(sorted(scripts.items()))
    expected = dict(sorted(_PINNED_PACKAGE_SCRIPTS.get(worker, {}).items()))
    if frozen != expected:
        raise ValueError(f"{worker}: package scripts violate the closed command policy")
    return frozen


REQUIRED_OBSERVABILITY = {"enabled": True, "head_sampling_rate": 1.0}
VERSION_METADATA_BINDING = "CF_VERSION_METADATA"

_MODELED_CONFIG_KEYS = (
    "account_id",
    "ai",
    "compatibility_date",
    "compatibility_flags",
    "d1_databases",
    "durable_objects",
    "kv_namespaces",
    "main",
    "migrations",
    "name",
    "observability",
    "placement",
    "preview_urls",
    "queues",
    "r2_buckets",
    "ratelimits",
    "route",
    "routes",
    "secrets",
    "services",
    "tail_consumers",
    "triggers",
    "vars",
    "version_metadata",
    "workers_dev",
)
_NESTED_CONFIG_KEYS = {
    "durable_objects": ("bindings",),
    "queues": ("consumers", "producers"),
    "secrets": ("required",),
    "triggers": ("crons",),
}
CONFIG_KEY_POLICY = {
    "schema_version": "wrangler-config-key-policy/v1",
    "modeled": list(_MODELED_CONFIG_KEYS),
    "selection_only": ["env"],
    "ignored": [],
    "nested_modeled": {
        key: list(value) for key, value in sorted(_NESTED_CONFIG_KEYS.items())
    },
    "unclassified": "REJECT",
}


def _validate_config_key_policy(
    data: dict[str, Any],
    *,
    config_path: Path,
    environment: str,
) -> None:
    allowed = set(_MODELED_CONFIG_KEYS)
    unknown_root = sorted(set(data) - allowed - {"env"})
    if unknown_root:
        raise ValueError(
            f"{config_path}: unclassified top-level Wrangler keys: {unknown_root!r}"
        )

    envs = data.get("env")
    if environment in {"staging", "test"} and envs is not None:
        raise ValueError(
            f"{config_path}: standalone {environment} config must not contain named envs"
        )
    sections: list[tuple[str, dict[str, Any]]] = [("root", data)]
    if envs is not None:
        if not isinstance(envs, dict) or set(envs) != {"production"}:
            raise ValueError(
                f"{config_path}: named environments must be exactly ['production']"
            )
        production = envs["production"]
        if not isinstance(production, dict):
            raise ValueError(f"{config_path}: env.production must be a table")
        sections.append(("env.production", production))

    for label, section in sections:
        keys = set(section) - ({"env"} if label == "root" else set())
        unknown = sorted(keys - allowed)
        if unknown:
            raise ValueError(
                f"{config_path}: {label} has unclassified Wrangler keys: {unknown!r}"
            )
        for table, nested_allowed in _NESTED_CONFIG_KEYS.items():
            value = section.get(table)
            if value is None:
                continue
            if not isinstance(value, dict):
                raise ValueError(f"{config_path}: {label}.{table} must be a table")
            nested_unknown = sorted(set(value) - set(nested_allowed))
            if nested_unknown:
                raise ValueError(
                    f"{config_path}: {label}.{table} has unclassified keys: "
                    f"{nested_unknown!r}"
                )


def _canonical_json_value(value: Any, *, field: str) -> Any:
    try:
        encoded = json.dumps(
            value,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        return json.loads(encoded)
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ValueError(f"{field} must be canonical JSON data") from exc


def _json_rows(value: Any) -> list[dict[str, Any]]:
    if not value:
        return []
    if not isinstance(value, list) or not all(isinstance(row, dict) for row in value):
        raise ValueError(f"expected a list of tables, got {type(value).__name__}")
    rows = [dict(sorted(row.items())) for row in value]
    return sorted(rows, key=lambda row: json.dumps(row, sort_keys=True))


def _ordered_json_rows(value: Any, *, field: str) -> list[dict[str, Any]]:
    """Validate rows while preserving declaration order when order is semantic."""
    if not value:
        return []
    if not isinstance(value, list) or not all(isinstance(row, dict) for row in value):
        raise ValueError(f"{field} must be a list of tables")
    return [dict(sorted(row.items())) for row in value]


def _external_binding_targets(surface: dict[str, Any]) -> set[tuple[str, str]]:
    """Return resource identities that must not cross environment boundaries."""
    targets: set[tuple[str, str]] = set()
    worker_name = surface.get("name")
    if worker_name is not None and str(worker_name):
        targets.add(("worker", str(worker_name)))
    tables = {
        "d1_databases": ("d1", ("database_id", "preview_database_id")),
        "kv_namespaces": ("kv", ("id", "preview_id")),
        "r2_buckets": ("r2", ("bucket_name", "preview_bucket_name")),
        "queue_producers": ("queue", ("queue",)),
        "queue_consumers": ("queue", ("queue", "dead_letter_queue")),
        "services": ("worker", ("service",)),
        "tail_consumers": ("worker", ("service",)),
        "durable_objects": ("worker", ("script_name",)),
        "ratelimits": ("ratelimit", ("namespace_id",)),
    }
    for table, (kind, fields) in tables.items():
        for row in surface.get(table) or []:
            for field in fields:
                value = row.get(field)
                if value is not None and str(value):
                    targets.add((kind, str(value)))
    return targets


def _secret_names(value: Any) -> list[str]:
    if not value:
        return []
    if not isinstance(value, dict):
        raise ValueError("secrets must be a table")
    required = value.get("required") or []
    if (
        not isinstance(required, list)
        or not all(isinstance(name, str) and name for name in required)
        or len(required) != len(set(required))
    ):
        raise ValueError("secrets.required must contain unique non-empty names")
    return sorted(required)


def _effective_surface(
    *,
    worker: str,
    config_path: Path,
    environment: str,
    named_environment: str | None,
) -> dict[str, Any]:
    data = _load_toml(config_path)
    _validate_config_key_policy(
        data,
        config_path=config_path,
        environment=environment,
    )
    section: dict[str, Any]
    if named_environment is None:
        section = data
    else:
        try:
            section = data["env"][named_environment]
        except (KeyError, TypeError) as exc:
            raise ValueError(f"{config_path}: missing [env.{named_environment}]") from exc

    def scalar(name: str, *, inherited: bool = True, default: Any = None) -> Any:
        if name in section:
            return section[name]
        if inherited:
            return data.get(name, default)
        return default

    queues = section.get("queues") or {}
    durable_objects = section.get("durable_objects") or {}
    migrations = section.get("migrations")
    if migrations is None and named_environment is not None:
        # Wrangler migration declarations are shared by named environments.
        migrations = data.get("migrations")

    package = json.loads((WORKER_ROOT / worker / "package.json").read_text(encoding="utf-8"))
    dev_dependencies = package.get("devDependencies") or {}
    pinned_toolchain = {name: dev_dependencies.get(name) for name in TOOLCHAIN}
    observability = scalar("observability")
    version_metadata = section.get("version_metadata")
    account_id = scalar("account_id")
    if account_id is not None and (
        not isinstance(account_id, str) or not account_id.strip()
    ):
        raise ValueError(f"{config_path}: account_id must be a non-empty string")
    route = scalar("route")
    routes = scalar("routes", default=[]) or []
    if route is not None and routes:
        raise ValueError(f"{config_path}: route and routes are mutually exclusive")
    effective_name = scalar("name")
    if named_environment is not None and "name" not in section:
        base_name = data.get("name")
        if not isinstance(base_name, str) or not base_name:
            raise ValueError(f"{config_path}: inherited Worker name is invalid")
        # Wrangler appends the named environment when an explicit name override
        # is absent; raw TOML inheritance would otherwise freeze the wrong target.
        effective_name = f"{base_name}-{named_environment}"

    return {
        "config": str(config_path.relative_to(ROOT)),
        "account_id": account_id,
        "name": effective_name,
        "main": scalar("main"),
        "compatibility_date": scalar("compatibility_date"),
        "compatibility_flags": sorted(scalar("compatibility_flags", default=[]) or []),
        "workers_dev": bool(scalar("workers_dev", default=True)),
        "preview_urls": bool(scalar("preview_urls", default=True)),
        "routes": _json_rows(routes),
        "route": _canonical_json_value(route, field="route"),
        "d1_databases": _json_rows(section.get("d1_databases")),
        "r2_buckets": _json_rows(section.get("r2_buckets")),
        "kv_namespaces": _json_rows(section.get("kv_namespaces")),
        "queue_producers": _json_rows(queues.get("producers")),
        "queue_consumers": _json_rows(queues.get("consumers")),
        "durable_objects": _json_rows(durable_objects.get("bindings")),
        "services": _json_rows(section.get("services")),
        "tail_consumers": _json_rows(section.get("tail_consumers")),
        "ratelimits": _json_rows(section.get("ratelimits")),
        "ai": dict(sorted((section.get("ai") or {}).items())),
        "placement": _canonical_json_value(
            scalar("placement", default={}) or {}, field="placement"
        ),
        "migrations": _ordered_json_rows(migrations, field="migrations"),
        "crons": sorted(
            ((scalar("triggers", default={}) or {}).get("crons") or [])
        ),
        "vars": dict(sorted((section.get("vars") or {}).items())),
        "secret_names": _secret_names(section.get("secrets")),
        "toolchain": pinned_toolchain,
        "observability": dict(sorted((observability or {}).items())),
        "version_metadata": dict(sorted((version_metadata or {}).items())),
    }


def build_manifest() -> dict[str, Any]:
    validate_active_worker_inventory()
    workers: dict[str, Any] = {}
    for worker in ACTIVE_WORKERS:
        directory = WORKER_ROOT / worker
        production_config = directory / "wrangler.toml"
        staging_config = directory / "wrangler.staging.toml"
        workers[worker] = {
            "base": _effective_surface(
                worker=worker,
                config_path=production_config,
                environment="base",
                named_environment=None,
            ),
            "production": _effective_surface(
                worker=worker,
                config_path=production_config,
                environment="production",
                named_environment="production",
            ),
            "staging": _effective_surface(
                worker=worker,
                config_path=staging_config,
                environment="staging",
                named_environment=None,
            ),
        }
    test_harness_surfaces = {
        worker: _effective_surface(
            worker=worker,
            config_path=WORKER_ROOT / worker / "wrangler.test.toml",
            environment="test",
            named_environment=None,
        )
        for worker in ACTIVE_WORKERS
        if (WORKER_ROOT / worker / "wrangler.test.toml").is_file()
    }
    manifest = {
        "schema_version": "cloudflare-active-worker-bindings/v4",
        "active_workers": list(ACTIVE_WORKERS),
        "config_key_policy": CONFIG_KEY_POLICY,
        "test_harness_surfaces": test_harness_surfaces,
        "toolchain_policy": TOOLCHAIN,
        "worker_package_scripts": {
            worker: _package_scripts(worker) for worker in ACTIVE_WORKERS
        },
        "workers": workers,
    }
    validate_manifest(manifest)
    return manifest


def validate_manifest(manifest: dict[str, Any]) -> None:
    if set(manifest) != {
        "active_workers",
        "config_key_policy",
        "schema_version",
        "test_harness_surfaces",
        "toolchain_policy",
        "worker_package_scripts",
        "workers",
    }:
        raise ValueError("binding manifest fields are not closed")
    if manifest["schema_version"] != "cloudflare-active-worker-bindings/v4":
        raise ValueError("binding manifest schema_version drift")
    if manifest["config_key_policy"] != CONFIG_KEY_POLICY:
        raise ValueError("Wrangler config-key policy drift")
    if manifest["active_workers"] != list(ACTIVE_WORKERS):
        raise ValueError("active Worker inventory digest surface drift")
    if manifest["toolchain_policy"] != TOOLCHAIN:
        raise ValueError("binding manifest toolchain policy drift")
    expected_scripts = {
        worker: _package_scripts(worker) for worker in ACTIVE_WORKERS
    }
    if manifest["worker_package_scripts"] != expected_scripts:
        raise ValueError("active Worker package-script deployment surface drift")
    workers = manifest["workers"]
    if tuple(workers) != ACTIVE_WORKERS:
        raise ValueError("active Worker order or membership drift")
    production_targets = set().union(
        *(
            _external_binding_targets(environments[environment])
            for environments in workers.values()
            for environment in ("base", "production")
        )
    )
    staging_targets = set().union(
        *(
            _external_binding_targets(environments["staging"])
            for environments in workers.values()
        )
    )
    overlap = production_targets & staging_targets
    if overlap:
        raise ValueError(
            f"staging external binding targets overlap production: {sorted(overlap)!r}"
        )
    expected_test_workers = tuple(
        worker
        for worker in ACTIVE_WORKERS
        if (WORKER_ROOT / worker / "wrangler.test.toml").is_file()
    )
    test_surfaces = manifest["test_harness_surfaces"]
    if tuple(test_surfaces) != expected_test_workers:
        raise ValueError("test-harness Wrangler config membership drift")
    for worker, surface in test_surfaces.items():
        expected_config = str(
            (WORKER_ROOT / worker / "wrangler.test.toml").relative_to(ROOT)
        )
        if surface.get("config") != expected_config:
            raise ValueError(f"{worker}: test-harness config path drift")
        if not str(surface.get("name") or "").endswith("-test"):
            raise ValueError(f"{worker}: test-harness Worker name must end in -test")
        if surface.get("workers_dev") is not False:
            raise ValueError(f"{worker}: test-harness workers_dev must be false")
        if surface.get("preview_urls") is not False:
            raise ValueError(f"{worker}: test-harness preview_urls must be false")
        if surface.get("route") is not None or surface.get("routes") != []:
            raise ValueError(f"{worker}: test-harness routes must be empty")
        for table, fields in {
            "d1_databases": ("database_name",),
            "r2_buckets": ("bucket_name", "preview_bucket_name"),
            "queue_producers": ("queue",),
            "queue_consumers": ("queue", "dead_letter_queue"),
            "services": ("service",),
            "tail_consumers": ("service",),
            "durable_objects": ("script_name",),
        }.items():
            for row in surface.get(table) or []:
                for field in fields:
                    value = row.get(field)
                    if value is not None and not str(value).endswith("-test"):
                        raise ValueError(
                            f"{worker}/test: {table}.{field} is not test-isolated: "
                            f"{value}"
                        )
                target_environment = row.get("environment")
                if target_environment is not None and target_environment != "test":
                    raise ValueError(
                        f"{worker}/test: {table}.environment must be test"
                    )
        forbidden_test_targets = production_targets | staging_targets
        test_overlap = _external_binding_targets(surface) & forbidden_test_targets
        if test_overlap:
            raise ValueError(
                f"{worker}: test-harness external binding target overlap: "
                f"{sorted(test_overlap)!r}"
            )

    for worker, environments in workers.items():
        for environment, surface in environments.items():
            expected_secrets = sorted(
                STAGING_SECRET_NAMES.get(worker, ())
                if environment == "staging"
                else PRODUCTION_SECRET_NAMES[worker]
            )
            if surface["secret_names"] != expected_secrets:
                raise ValueError(
                    f"{worker}/{environment}: secrets.required drifted: "
                    f"{surface['secret_names']!r}"
                )
            if surface["preview_urls"]:
                raise ValueError(f"{worker}/{environment}: preview_urls must be false")
            observability = surface.get("observability") or {}
            if observability.get("enabled") is not True:
                raise ValueError(
                    f"{worker}/{environment}: observability.enabled must be true"
                )
            rate = observability.get("head_sampling_rate")
            try:
                sampled = float(rate)
            except (TypeError, ValueError) as exc:
                raise ValueError(
                    f"{worker}/{environment}: observability.head_sampling_rate drifted: {rate!r}"
                ) from exc
            if sampled != REQUIRED_OBSERVABILITY["head_sampling_rate"]:
                raise ValueError(
                    f"{worker}/{environment}: observability.head_sampling_rate drifted: {rate!r}"
                )
            version_binding = (surface.get("version_metadata") or {}).get("binding")
            if version_binding != VERSION_METADATA_BINDING:
                raise ValueError(
                    f"{worker}/{environment}: version_metadata binding "
                    f"{VERSION_METADATA_BINDING} is required"
                )
            for package_name, expected in TOOLCHAIN.items():
                actual = surface["toolchain"].get(package_name)
                if actual != expected:
                    raise ValueError(
                        f"{worker}: {package_name} must be exactly {expected}, got {actual!r}"
                    )

        staging = environments["staging"]
        if not str(staging["name"]).endswith("-staging"):
            raise ValueError(f"{worker}: staging Worker name must end in -staging")
        if staging.get("route") is not None or staging.get("routes") != []:
            raise ValueError(f"{worker}: staging routes must be empty")
        if staging["secret_names"] != sorted(STAGING_SECRET_NAMES.get(worker, ())):
            raise ValueError(f"{worker}: staging secret-name policy drifted")
        for table, fields in {
            "d1_databases": ("database_name",),
            "r2_buckets": ("bucket_name", "preview_bucket_name"),
            "queue_producers": ("queue",),
            "queue_consumers": ("queue", "dead_letter_queue"),
            "services": ("service",),
            "tail_consumers": ("service",),
            "durable_objects": ("script_name",),
        }.items():
            for row in staging[table]:
                for field in fields:
                    value = row.get(field)
                    if value is not None and not str(value).endswith("-staging"):
                        raise ValueError(
                            f"{worker}/staging: {table}.{field} is not staging-isolated: {value}"
                        )
                target_environment = row.get("environment")
                if target_environment is not None and target_environment != "staging":
                    raise ValueError(
                        f"{worker}/staging: {table}.environment must be staging"
                    )

    service = workers["research-mass-eval"]["production"]["services"]
    if service != [
        {
            "binding": "AI_GATEWAY",
            "entrypoint": "GatewayService",
            "service": "quant-platform-research-ai-gateway",
        }
    ]:
        raise ValueError("mass-eval must use the typed GatewayService binding")

    receipt_names = {
        "base": "quant-platform-receipt-evidence-authority",
        "production": "quant-platform-receipt-evidence-authority",
        "staging": "quant-platform-receipt-evidence-authority-staging",
    }
    acquisition_targets = {
        "base": "quant-platform-ingestion-secrets",
        "production": "quant-platform-ingestion-secrets",
        "staging": "quant-platform-ingestion-secrets-staging",
    }
    caller_targets = {
        "base": "quant-platform-receipt-evidence-authority",
        "production": "quant-platform-receipt-evidence-authority",
        "staging": "quant-platform-receipt-evidence-authority-staging",
    }
    receipt_evidence_buckets = {
        "base": "quant-receipt-evidence",
        "production": "quant-receipt-evidence",
        "staging": "quant-receipt-evidence-staging",
    }
    for environment in ("base", "production", "staging"):
        receipt = workers["receipt-evidence-authority"][environment]
        if (
            receipt["name"] != receipt_names[environment]
            or receipt["workers_dev"] is not False
            or receipt["preview_urls"] is not False
            or receipt["route"] is not None
            or receipt["routes"] != []
        ):
            raise ValueError(
                f"receipt-evidence-authority/{environment}: public surface drift"
            )
        if receipt["vars"] != {
            "AUTHORITY_MODE": "PENDING",
            "ENVIRONMENT": "staging" if environment == "staging" else "production",
            "RECEIPT_KEY_GENERATION": "1",
        }:
            raise ValueError(
                f"receipt-evidence-authority/{environment}: PENDING key policy drift"
            )
        if receipt["durable_objects"] != [{
            "class_name": "ReceiptEvidenceAuthority",
            "name": "RECEIPT_EVIDENCE_AUTHORITY_DO",
        }]:
            raise ValueError(
                f"receipt-evidence-authority/{environment}: authority DO drift"
            )
        if receipt["services"] != [{
            "binding": "JQUANTS_ACQUISITION",
            "entrypoint": "IngestionSecretsService",
            "service": acquisition_targets[environment],
        }]:
            raise ValueError(
                f"receipt-evidence-authority/{environment}: acquisition binding drift"
            )
        expected_buckets = [
            {
                "binding": "AUTHORITY_EVIDENCE_BUCKET",
                "bucket_name": receipt_evidence_buckets[environment],
            },
        ]
        if receipt["r2_buckets"] != expected_buckets:
            raise ValueError(
                f"receipt-evidence-authority/{environment}: dedicated "
                "authority bucket drift"
            )
        receipt_databases = receipt["d1_databases"]
        if len(receipt_databases) != 1 or set(receipt_databases[0]) != {
            "binding", "database_id", "database_name"
        }:
            raise ValueError(
                f"receipt-evidence-authority/{environment}: receipt Worker "
                "must consume Premium-owned D1 without migration metadata"
            )
        caller = workers["ingestion-premium"][environment]["services"]
        if caller != [{
            "binding": "RECEIPT_EVIDENCE_AUTHORITY",
            "entrypoint": "ReceiptAuthorityService",
            "service": caller_targets[environment],
        }]:
            raise ValueError(
                f"ingestion-premium/{environment}: typed Receipt binding drift"
            )
        premium_vars = workers["ingestion-premium"][environment]["vars"]
        if premium_vars != {
            "INGEST_CONCURRENCY": "2" if environment == "staging" else "6",
            "RECEIPT_AUTHORITY_ENVIRONMENT": (
                "staging" if environment == "staging" else "production"
            ),
        }:
            raise ValueError(
                f"ingestion-premium/{environment}: Receipt environment policy drift"
            )

    expected_ops_databases = {
        "base": {
            ("OPS_PROJECTION_DB", "quant-ops-projection", "migrations/projection"),
            ("QUOTA_DB", "quant-ops-quota", "migrations/quota"),
        },
        "production": {
            ("OPS_PROJECTION_DB", "quant-ops-projection", "migrations/projection"),
            ("QUOTA_DB", "quant-ops-quota", "migrations/quota"),
        },
        "staging": {
            (
                "OPS_PROJECTION_DB",
                "quant-ops-projection-staging",
                "migrations/projection",
            ),
            ("QUOTA_DB", "quant-ops-quota-staging", "migrations/quota"),
        },
    }
    for environment, expected in expected_ops_databases.items():
        databases = workers["quant-ops-mcp"][environment]["d1_databases"]
        actual = {
            (
                str(row.get("binding")),
                str(row.get("database_name")),
                str(row.get("migrations_dir")),
            )
            for row in databases
        }
        if actual != expected:
            raise ValueError(
                f"quant-ops-mcp/{environment}: dedicated projection/quota "
                f"bindings drifted: {sorted(actual)}"
            )

    for environment in ("base", "production"):
        ratelimits = workers["ingestion-secrets"][environment]["ratelimits"]
        if {row.get("name") for row in ratelimits} != {"PROXY_RATE_LIMITER"}:
            raise ValueError(
                f"ingestion-secrets/{environment}: PROXY_RATE_LIMITER binding required"
            )


def _render(manifest: dict[str, Any]) -> str:
    return json.dumps(manifest, indent=2, sort_keys=True) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--write", action="store_true", help="replace the frozen manifest")
    parser.add_argument(
        "--print-worker-paths",
        action="store_true",
        help="print canonical active Worker paths, one per line",
    )
    args = parser.parse_args(argv)
    if args.write and args.print_worker_paths:
        parser.error("--write and --print-worker-paths are mutually exclusive")
    if args.print_worker_paths:
        validate_active_worker_inventory()
        for worker in ACTIVE_WORKERS:
            print((WORKER_ROOT / worker).relative_to(ROOT))
        return 0
    rendered = _render(build_manifest())
    if args.write:
        MANIFEST.parent.mkdir(parents=True, exist_ok=True)
        MANIFEST.write_text(rendered, encoding="utf-8")
        print(MANIFEST.relative_to(ROOT))
        return 0
    if not MANIFEST.is_file():
        print(f"missing binding manifest: {MANIFEST}", file=sys.stderr)
        return 1
    frozen = MANIFEST.read_text(encoding="utf-8")
    if frozen != rendered:
        print(
            "Cloudflare binding drift; review and run "
            "scripts/cloudflare_binding_manifest.py --write",
            file=sys.stderr,
        )
        return 1
    print("Cloudflare binding manifest: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
