#!/usr/bin/env python3
"""Freeze every active Cloudflare Worker deployment surface.

The manifest is intentionally generated from Wrangler TOML plus an explicit
secret-name policy. It contains names only; secret values are never read.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import tempfile
import tomllib
from pathlib import Path
import subprocess
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
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
PROJECT_ACCOUNT_ID = "11233bca08d134a9b738eaa46b9751d9"

# Names are policy. Values remain exclusively in Cloudflare Secrets.
PRODUCTION_SECRET_NAMES: dict[str, tuple[str, ...]] = {
    "ingestion-jsda": ("INGESTION_RUN_TOKEN",),
    "ingestion-premium": (
        "DATA_EXPORT_TOKEN",
        "INGESTION_RUN_TOKEN",
        "JQUANTS_API_KEY",
        "OPS_PROJECTION_SIGNING_PKCS8_B64",
        "READY_ED25519_PRIVATE_KEY",
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
    "receipt-activation-observer": (),
    "receipt-evidence-authority": ("RECEIPT_KEY_WRAP_KEY",),
    "research-ai-gateway": ("GATEWAY_TOKEN",),
    "research-mass-eval": ("MASS_EVAL_TOKEN",),
}

STAGING_SECRET_NAMES: dict[str, tuple[str, ...]] = {
    "receipt-activation-observer": (),
    "ingestion-premium": (
        "INGESTION_RUN_TOKEN",
        "OPS_PROJECTION_SIGNING_PKCS8_B64",
        "READY_ED25519_PRIVATE_KEY",
    ),
    "ingestion-secrets": (
        "JQUANTS_API_KEY",
        "JQUANTS_RPC_CURSOR_HMAC_KEY",
    ),
    "receipt-evidence-authority": ("RECEIPT_KEY_WRAP_KEY",),
    "research-mass-eval": ("MASS_EVAL_TOKEN",),
}


def _load_toml(path: Path) -> dict[str, Any]:
    with path.open("rb") as fh:
        return tomllib.load(fh)


def _python_from_worker_package(script: str) -> str:
    """Invoke a repository script from `platform/workers/<worker>` cwd."""
    relative = Path(
        os.path.relpath(ROOT / "scripts" / script, WORKER_ROOT / "_worker")
    ).as_posix()
    return f"python3 {relative}"


def _generic_tagged_deploy_command(worker: str) -> str:
    return (
        f"{_python_from_worker_package('cloudflare_binding_manifest.py')} "
        f"--deploy-tagged --worker {worker} --env production"
    )


_WRANGLER_PACKAGE_SCRIPT_POLICY = {
    "build": (
        'wrangler deploy --dry-run --config=wrangler.toml --env="" '
        "--outdir .wrangler-dry-run"
    ),
    "cf-typegen": 'wrangler types --config=wrangler.toml --env=""',
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
        "deploy": (
            f"{_python_from_worker_package('activate_jsda_v3_cutover.py')} "
            "--environment production --activate --yes"
        ),
        "deploy:staging": (
            f"{_python_from_worker_package('activate_jsda_v3_cutover.py')} "
            "--environment staging --activate --yes"
        ),
        "deploy:unsafe-dev": "wrangler deploy --config=wrangler.toml --env=\"\"",
        "tail": _WRANGLER_PACKAGE_SCRIPT_POLICY["tail"],
        "test": (
            "vitest run --config vitest.config.ts && "
            "vitest run --config vitest.runtime.config.ts"
        ),
    },
    "ingestion-premium": {
        **_COMMON_PACKAGE_SCRIPTS,
        "cf-typegen": _WRANGLER_PACKAGE_SCRIPT_POLICY["cf-typegen"],
        "deploy": _generic_tagged_deploy_command("ingestion-premium"),
        "test": (
            "vitest run --config vitest.config.ts && "
            "vitest run --config vitest.runtime.config.ts"
        ),
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
        "deploy": (
            f"{_python_from_worker_package('predeploy_ops_projection_gate.py')} "
            "--environment production && "
            + _generic_tagged_deploy_command("quant-ops-mcp")
        ),
        "test": (
            "node --experimental-test-module-mocks --test test/*.test.mjs && "
            "vitest run --config vitest.runtime.config.ts && "
            "vitest run --config vitest.harness.config.ts"
        ),
    },
    "receipt-activation-observer": {
        **_COMMON_PACKAGE_SCRIPTS,
        "cf-typegen": _WRANGLER_PACKAGE_SCRIPT_POLICY["cf-typegen"],
        "test": "vitest run --config vitest.runtime.config.ts",
    },
    "receipt-evidence-authority": {
        **_COMMON_PACKAGE_SCRIPTS,
        "cf-typegen": _WRANGLER_PACKAGE_SCRIPT_POLICY["cf-typegen"],
        "test": "vitest run --config vitest.runtime.config.ts",
    },
    "research-ai-gateway": {
        **_COMMON_PACKAGE_SCRIPTS,
        "deploy": _generic_tagged_deploy_command("research-ai-gateway"),
        "test": (
            "vitest run --config vitest.config.ts && "
            "vitest run --config vitest.harness.config.ts"
        ),
    },
    "research-mass-eval": {
        **_COMMON_PACKAGE_SCRIPTS,
        "deploy": _generic_tagged_deploy_command("research-mass-eval"),
        "dev": _WRANGLER_PACKAGE_SCRIPT_POLICY["dev"],
        "tail": _WRANGLER_PACKAGE_SCRIPT_POLICY["tail"],
        "test": (
            "vitest run && vitest run --config vitest.runtime.config.mts"
        ),
        "test:runtime": "vitest run --config vitest.runtime.config.mts",
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

# Named WorkerEntrypoints are RPC capability surfaces even without a route.
# `fetch` is a reserved special handler, not an ordinary RPC method, so freeze
# it independently. Keep Durable Object RPC inventories separate as well.
WORKER_ENTRYPOINT_RPC_POLICY: dict[
    str, dict[str, tuple[bool, tuple[str, ...]]]
] = {
    "ingestion-secrets": {
        "IngestionSecretsService": (True, ("fetch_governed_page",)),
    },
    "receipt-evidence-authority": {
        "ReceiptAuthorityService": (
            True,
            (
                "begin_audit_recovery_canary",
                "issue_for_segment",
                "public_key_registration",
                "recover_audit_recovery_canary",
                "recover_issue",
            ),
        ),
    },
    "ingestion-premium": {
        "PremiumReceiptOperatorService": (
            False,
            ("pending_public_key_registration",),
        ),
        "PremiumReceiptAuditEvidenceService": (
            False,
            ("staging_recovery_audit_evidence",),
        ),
        "PremiumReceiptProductInputService": (
            False,
            ("read_receipt_product_bytes",),
        ),
        "PilotReadyPublicationService": (True, ("publishPilotReady",)),
    },
    "ingestion-jsda": {
        "JsdaReadinessService": (True, ()),
    },
    "research-ai-gateway": {
        "GatewayService": (
            False,
            (
                "cancelControlledPaper",
                "complete",
                "finalizeControlledPaper",
                "heartbeatControlledPaper",
                "queryControlledPaper",
                "reserveControlledPaper",
            ),
        ),
    },
    "research-mass-eval": {},
}

DEFAULT_FETCH_RESERVED_SPECIAL_POLICY = frozenset(
    {
        "ingestion-jsda",
        "ingestion-premium",
        "ingestion-secrets",
        "quant-ops-mcp",
        "receipt-activation-observer",
        "receipt-evidence-authority",
        "research-ai-gateway",
        "research-mass-eval",
    }
)

DURABLE_OBJECT_RPC_POLICY: dict[str, dict[str, tuple[str, ...]]] = {
    "receipt-evidence-authority": {
        "ReceiptEvidenceAuthority": (
            "begin_audit_recovery_canary",
            "issue_for_segment",
            "public_key_registration",
            "recover_audit_recovery_canary",
            "recover_issue",
        ),
    },
    "research-ai-gateway": {
        "BudgetLedger": (
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
        ),
    },
    "research-mass-eval": {
        "PersonalResearchContainer": (),
    },
}

# Durable Object lifecycle handlers are reserved runtime specials, not
# ordinary RPC methods. Model only explicitly governed classes here so older
# class inventories retain their existing schema until separately reviewed.
DURABLE_OBJECT_RESERVED_SPECIAL_POLICY: dict[
    str, dict[str, tuple[bool, bool]]
] = {
    "receipt-evidence-authority": {
        "ReceiptEvidenceAuthority": (False, True),
    },
    "research-ai-gateway": {
        "BudgetLedger": (True, True),
    },
    "research-mass-eval": {
        "PersonalResearchContainer": (True, True),
    },
}

QUANT_OPS_AGENTS_DEPENDENCY_POLICY = {
    "package": "agents",
    "requested": "0.17.4",
    "resolved_version": "0.17.4",
    "resolved": "https://registry.npmjs.org/agents/-/agents-0.17.4.tgz",
    "integrity": (
        "sha512-K6YRbpD3VcwdTOPBlDgI4dILAwkhXo5cdxTlVF0IvUwQEKfMPawmH8E/"
        "QMXTN8CPGHqVYgYFACxTyk6nKlK+vg=="
    ),
    "package_lock": "platform/workers/quant-ops-mcp/package-lock.json",
    "package_lock_digest": (
        "sha256:fd583b8f3c1a75f5511c4abe0422274529c987e0512c0b724e63733a588af52f"
    ),
}

# McpAgent is a framework-owned legacy Durable Object. Its dependency copies
# inherited prototype methods onto the application class during construction,
# so a short explicit method list would hide the real RPC surface. Freeze the
# exact post-construction workerd descriptor inventory instead. The descriptor
# digest is over canonical rows ordered by prototype owner, property name and
# accessor kind; each row includes owner/order/name/kind plus the enumerable,
# configurable and writable flags.
FRAMEWORK_DURABLE_OBJECT_POLICY: dict[str, dict[str, dict[str, Any]]] = {
    "quant-ops-mcp": {
        "QuantOpsMcpAgent": {
            "policy_kind": "framework-prototype-inventory/v1",
            "framework_class": "McpAgent",
            "own_custom_pre_init_rpc_methods": ["init"],
            "constructor_prototype_copy": {
                "observed": True,
                "copied_method_count": 17,
                "post_construction_own_method_count": 18,
            },
            "post_construction_prototype": {
                "canonicalization": "prototype-descriptors/v1",
                "owner_order": ["QuantOpsMcpAgent", "McpAgent", "Agent", "Server"],
                "owner_inventories": [
                    {
                        "owner": "QuantOpsMcpAgent",
                        "descriptor_row_count": 18,
                        "descriptor_digest": (
                            "sha256:311e5b28b8a5edafc1cf4d26fba62616b5f7f0c2331e8b25b8c20225c30af126"
                        ),
                    },
                    {
                        "owner": "McpAgent",
                        "descriptor_row_count": 21,
                        "descriptor_digest": (
                            "sha256:f82cfc1fc012c399a9f4356e27352f8dbaa88ea541e8f405c9eff95e1fad17a3"
                        ),
                    },
                    {
                        "owner": "Agent",
                        "descriptor_row_count": 284,
                        "descriptor_digest": (
                            "sha256:916d6fd9f21ed584b8e862432831ddbdabe92055201211f2593337f4a86917f0"
                        ),
                    },
                    {
                        "owner": "Server",
                        "descriptor_row_count": 22,
                        "descriptor_digest": (
                            "sha256:2d7f8feda2717b89fad0bd6ef6df7b4071dd5e526a60ccee9d2302657f3c5d5a"
                        ),
                    },
                ],
                "descriptor_row_count": 345,
                "descriptor_digest": (
                    "sha256:077694dde17e90c2ac702c71652a53f9f69b3c8143197de0c8ccaff3afc34d1f"
                ),
                "unique_method_count": 310,
                "unique_ordinary_method_count": 305,
                "unique_getter_count": 6,
                "unique_setter_count": 0,
                "unique_reserved_special_count": 5,
            },
            "reserved_specials": {
                "fetch": True,
                "alarm": True,
                "webSocketMessage": True,
                "webSocketClose": True,
                "webSocketError": True,
            },
            "dependency": QUANT_OPS_AGENTS_DEPENDENCY_POLICY,
        },
    },
}


BINDING_MANIFEST_SCHEMA_VERSION = "cloudflare-active-worker-bindings/v11"

_OPS_D1_IDENTITY: dict[str, tuple[tuple[str, str, str, str, str], ...]] = {
    "base": (
        (
            "OPS_PROJECTION_DB",
            "quant-ops-projection",
            "1b497e8a-5c69-4e19-ae2e-89a8f3185272",
            "migrations/projection",
            "d1_migrations_ops_projection",
        ),
        (
            "QUOTA_DB",
            "quant-ops-quota",
            "d2c4bddd-7970-495c-aa05-ff28cbc1f6b6",
            "migrations/quota",
            "d1_migrations_ops_quota",
        ),
    ),
    "production": (
        (
            "OPS_PROJECTION_DB",
            "quant-ops-projection",
            "1b497e8a-5c69-4e19-ae2e-89a8f3185272",
            "migrations/projection",
            "d1_migrations_ops_projection",
        ),
        (
            "QUOTA_DB",
            "quant-ops-quota",
            "d2c4bddd-7970-495c-aa05-ff28cbc1f6b6",
            "migrations/quota",
            "d1_migrations_ops_quota",
        ),
    ),
    "staging": (
        (
            "OPS_PROJECTION_DB",
            "quant-ops-projection-staging",
            "68ee96d5-766c-4832-836b-54c079bd6265",
            "migrations/projection",
            "d1_migrations_ops_projection",
        ),
        (
            "QUOTA_DB",
            "quant-ops-quota-staging",
            "a27f8ce9-82cb-4eec-abac-9c3385ce40e1",
            "migrations/quota",
            "d1_migrations_ops_quota",
        ),
    ),
}


def _canonical_digest(value: Any) -> str:
    rendered = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(rendered).hexdigest()


def _resource_identity_rows(
    surface: dict[str, Any],
    table: str,
    fields: tuple[str, ...],
    type_name: str,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for raw in surface.get(table) or []:
        row = {"type": type_name}
        for field in fields:
            if field in raw:
                row[field] = raw[field]
        rows.append(row)
    return rows


def binding_identity(surface: dict[str, Any]) -> dict[str, Any]:
    """Names, resource IDs, types, and migration identity for one Worker env."""
    return {
        "d1_databases": _resource_identity_rows(
            surface,
            "d1_databases",
            (
                "binding",
                "database_id",
                "database_name",
                "migrations_dir",
                "migrations_table",
            ),
            "D1Database",
        ),
        "durable_objects": _resource_identity_rows(
            surface,
            "durable_objects",
            ("class_name", "name", "script_name"),
            "DurableObject",
        ),
        "kv_namespaces": _resource_identity_rows(
            surface, "kv_namespaces", ("binding", "id"), "KVNamespace"
        ),
        "name": surface.get("name"),
        "queue_consumers": _resource_identity_rows(
            surface,
            "queue_consumers",
            ("dead_letter_queue", "queue"),
            "QueueConsumer",
        ),
        "queue_producers": _resource_identity_rows(
            surface, "queue_producers", ("binding", "queue"), "QueueProducer"
        ),
        "r2_buckets": _resource_identity_rows(
            surface, "r2_buckets", ("binding", "bucket_name"), "R2Bucket"
        ),
        "ratelimits": _resource_identity_rows(
            surface, "ratelimits", ("name", "namespace_id"), "RateLimit"
        ),
        "secret_names": list(surface.get("secret_names") or []),
        "services": _resource_identity_rows(
            surface,
            "services",
            ("binding", "entrypoint", "service"),
            "Service",
        ),
    }


def binding_identity_digest(surface: dict[str, Any]) -> str:
    return _canonical_digest(binding_identity(surface))


def quant_ops_binding_identity(workers: dict[str, Any]) -> dict[str, Any]:
    ops = workers["quant-ops-mcp"]
    return {
        "environments": {
            environment: binding_identity(ops[environment])
            for environment in ("base", "production", "staging")
        },
        "schema_version": "quant-ops-mcp-binding-identity/v1",
        "worker": "quant-ops-mcp",
    }


def quant_ops_binding_identity_digest(workers: dict[str, Any]) -> str:
    return _canonical_digest(quant_ops_binding_identity(workers))


def _ops_d1_row(row: dict[str, Any]) -> tuple[str, str, str, str, str]:
    return (
        str(row.get("binding")),
        str(row.get("database_name")),
        str(row.get("database_id")),
        str(row.get("migrations_dir")),
        str(row.get("migrations_table")),
    )


def _quant_ops_agents_dependency() -> dict[str, str]:
    policy = QUANT_OPS_AGENTS_DEPENDENCY_POLICY
    package_path = WORKER_ROOT / "quant-ops-mcp" / "package.json"
    lock_path = ROOT / policy["package_lock"]
    try:
        package = json.loads(package_path.read_text(encoding="utf-8"))
        lock_raw = lock_path.read_bytes()
        lock = json.loads(lock_raw)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("quant-ops-mcp agents dependency metadata is unreadable") from exc
    if (
        not isinstance(package, dict)
        or not isinstance(package.get("dependencies"), dict)
        or package["dependencies"].get("agents") != policy["requested"]
    ):
        raise ValueError("quant-ops-mcp agents dependency must be an exact pin")
    if (
        not isinstance(lock, dict)
        or lock.get("lockfileVersion") != 3
        or not isinstance(lock.get("packages"), dict)
    ):
        raise ValueError("quant-ops-mcp package-lock is not exact npm lockfile v3")
    root = lock["packages"].get("")
    resolved = lock["packages"].get("node_modules/agents")
    if (
        not isinstance(root, dict)
        or not isinstance(root.get("dependencies"), dict)
        or root["dependencies"].get("agents") != policy["requested"]
        or not isinstance(resolved, dict)
        or resolved.get("version") != policy["resolved_version"]
        or resolved.get("resolved") != policy["resolved"]
        or resolved.get("integrity") != policy["integrity"]
    ):
        raise ValueError("quant-ops-mcp resolved agents dependency drifted")
    digest = "sha256:" + hashlib.sha256(lock_raw).hexdigest()
    if digest != policy["package_lock_digest"]:
        raise ValueError("quant-ops-mcp package-lock byte digest drifted")
    return dict(policy)

_MODELED_CONFIG_KEYS = (
    "account_id",
    "ai",
    "compatibility_date",
    "compatibility_flags",
    "containers",
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

    entrypoint_policy = WORKER_ENTRYPOINT_RPC_POLICY.get(worker, {})
    if environment == "test" and worker == "ingestion-premium":
        entrypoint_policy = {
            name: entrypoint_policy[name]
            for name in (
                "PremiumReceiptOperatorService",
                "PremiumReceiptAuditEvidenceService",
                "PremiumReceiptProductInputService",
            )
        }

    return {
        "config": str(config_path.relative_to(ROOT)),
        "account_id": account_id,
        "name": effective_name,
        "main": scalar("main"),
        "compatibility_date": scalar("compatibility_date"),
        "compatibility_flags": sorted(scalar("compatibility_flags", default=[]) or []),
        "containers": _json_rows(section.get("containers")),
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
        "default_handler": {
            "fetch_reserved_special": worker
            in DEFAULT_FETCH_RESERVED_SPECIAL_POLICY,
        },
        "worker_entrypoints": [
            {
                "name": name,
                "handlers": ["class"],
                "fetch_reserved_special": fetch_reserved_special,
                "rpc_methods": list(methods),
            }
            for name, (fetch_reserved_special, methods) in (
                entrypoint_policy.items()
            )
        ],
        "durable_object_class_handlers": [
            _durable_object_inventory(worker, row["class_name"])
            for row in _json_rows(durable_objects.get("bindings"))
        ],
    }


def _durable_object_inventory(worker: str, class_name: str) -> dict[str, Any]:
    rpc_methods = DURABLE_OBJECT_RPC_POLICY.get(worker, {}).get(class_name)
    framework = FRAMEWORK_DURABLE_OBJECT_POLICY.get(worker, {}).get(class_name)
    if (rpc_methods is None) == (framework is None):
        raise ValueError(
            f"{worker}/{class_name}: Durable Object needs exactly one explicit "
            "RPC or framework inventory policy"
        )
    row: dict[str, Any] = {"name": class_name, "handlers": ["class"]}
    if rpc_methods is not None:
        reserved_specials = DURABLE_OBJECT_RESERVED_SPECIAL_POLICY.get(
            worker, {}
        ).get(class_name)
        if reserved_specials is not None:
            row.update({
                "fetch_reserved_special": reserved_specials[0],
                "alarm_reserved_special": reserved_specials[1],
            })
        row["rpc_methods"] = list(rpc_methods)
        return row
    assert framework is not None
    rendered = json.loads(json.dumps(framework, sort_keys=True))
    rendered["dependency"] = _quant_ops_agents_dependency()
    row["framework_rpc_inventory"] = rendered
    return row


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
    body = {
        "schema_version": BINDING_MANIFEST_SCHEMA_VERSION,
        "active_workers": list(ACTIVE_WORKERS),
        "project_account_id": PROJECT_ACCOUNT_ID,
        "config_key_policy": CONFIG_KEY_POLICY,
        "ops_binding_identity_digest": quant_ops_binding_identity_digest(workers),
        "test_harness_surfaces": test_harness_surfaces,
        "toolchain_policy": TOOLCHAIN,
        "worker_package_scripts": {
            worker: _package_scripts(worker) for worker in ACTIVE_WORKERS
        },
        "workers": workers,
    }
    manifest = {**body, "manifest_digest": _canonical_digest(body)}
    validate_manifest(manifest)
    return manifest


def validate_manifest(manifest: dict[str, Any]) -> None:
    if set(manifest) != {
        "active_workers",
        "config_key_policy",
        "manifest_digest",
        "ops_binding_identity_digest",
        "project_account_id",
        "schema_version",
        "test_harness_surfaces",
        "toolchain_policy",
        "worker_package_scripts",
        "workers",
    }:
        raise ValueError("binding manifest fields are not closed")
    if manifest["schema_version"] != BINDING_MANIFEST_SCHEMA_VERSION:
        raise ValueError("binding manifest schema_version drift")
    if manifest["project_account_id"] != PROJECT_ACCOUNT_ID:
        raise ValueError("binding manifest project account id drift")
    if DEFAULT_FETCH_RESERVED_SPECIAL_POLICY != frozenset(ACTIVE_WORKERS):
        raise ValueError("default fetch reserved-special policy drift")
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
            if surface.get("default_handler") != {
                "fetch_reserved_special": True,
            }:
                raise ValueError(
                    f"{worker}/{environment}: default fetch reserved-special drift"
                )
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
        expected_entrypoints = [
            {
                "name": name,
                "handlers": ["class"],
                "fetch_reserved_special": fetch_reserved_special,
                "rpc_methods": list(methods),
            }
            for name, (fetch_reserved_special, methods) in (
                WORKER_ENTRYPOINT_RPC_POLICY.get(worker, {}).items()
            )
        ]
        expected_do_handlers = [
            _durable_object_inventory(worker, row["class_name"])
            for row in staging["durable_objects"]
        ]
        for target in ("base", "production", "staging"):
            if environments[target]["worker_entrypoints"] != expected_entrypoints:
                raise ValueError(
                    f"{worker}/{target}: WorkerEntrypoint RPC surface drifted"
                )
            if (
                environments[target]["durable_object_class_handlers"]
                != expected_do_handlers
            ):
                raise ValueError(
                    f"{worker}/{target}: Durable Object class handlers drifted"
                )
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

    mass_eval_services = {
        "base": [
            {
                "binding": "AI_GATEWAY",
                "entrypoint": "GatewayService",
                "service": "quant-platform-research-ai-gateway",
            },
            {
                "binding": "INGESTION_PREMIUM",
                "entrypoint": "PremiumReceiptProductInputService",
                "service": "quant-platform-ingestion-premium",
            },
            {
                "binding": "JQUANTS_ACQUISITION",
                "entrypoint": "IngestionSecretsService",
                "service": "quant-platform-ingestion-secrets",
            },
        ],
        "production": [
            {
                "binding": "AI_GATEWAY",
                "entrypoint": "GatewayService",
                "service": "quant-platform-research-ai-gateway",
            },
            {
                "binding": "INGESTION_PREMIUM",
                "entrypoint": "PremiumReceiptProductInputService",
                "service": "quant-platform-ingestion-premium",
            },
            {
                "binding": "JQUANTS_ACQUISITION",
                "entrypoint": "IngestionSecretsService",
                "service": "quant-platform-ingestion-secrets",
            },
        ],
        "staging": [
            {
                "binding": "AI_GATEWAY",
                "entrypoint": "GatewayService",
                "service": "quant-platform-research-ai-gateway-staging",
            },
            {
                "binding": "INGESTION_PREMIUM",
                "entrypoint": "PremiumReceiptProductInputService",
                "service": "quant-platform-ingestion-premium-staging",
            },
            {
                "binding": "JQUANTS_ACQUISITION",
                "entrypoint": "IngestionSecretsService",
                "service": "quant-platform-ingestion-secrets-staging",
            },
        ],
    }
    for environment, expected_services in mass_eval_services.items():
        if workers["research-mass-eval"][environment]["services"] != expected_services:
            raise ValueError(
                f"research-mass-eval/{environment}: GatewayService and "
                "IngestionSecretsService and PremiumReceiptProductInputService "
                "bindings are required"
            )

    personal_container = [
        {
            "class_name": "PersonalResearchContainer",
            "image": "./Dockerfile",
            "image_build_context": "../../..",
            "instance_type": "standard-4",
            "max_instances": 8,
            "rollout_active_grace_period": 11400,
        }
    ]
    personal_binding = [
        {
            "class_name": "PersonalResearchContainer",
            "name": "PERSONAL_RESEARCH_CONTAINER",
        }
    ]
    personal_migration = [
        {
            "new_sqlite_classes": ["PersonalResearchContainer"],
            "tag": "personal-research-container-v1",
        }
    ]
    for environment in ("base", "production", "staging"):
        mass = workers["research-mass-eval"][environment]
        if mass["containers"] != personal_container:
            raise ValueError(
                f"research-mass-eval/{environment}: personal Container drift"
            )
        if mass["durable_objects"] != personal_binding:
            raise ValueError(
                f"research-mass-eval/{environment}: personal Container binding drift"
            )
        if mass["migrations"] != personal_migration:
            raise ValueError(
                f"research-mass-eval/{environment}: personal Container migration drift"
            )
    for environment in ("base", "production", "staging"):
        if workers["research-mass-eval"][environment]["workers_dev"] is not True:
            raise ValueError(
                f"research-mass-eval/{environment}: token-gated personal route missing"
            )
        if workers["research-mass-eval"][environment]["preview_urls"] is not False:
            raise ValueError(
                f"research-mass-eval/{environment}: preview_urls must remain false"
            )
    mass_test = manifest["test_harness_surfaces"].get("research-mass-eval")
    if not isinstance(mass_test, dict) or any(
        mass_test[field] != [] for field in ("containers", "durable_objects")
    ):
        raise ValueError("research-mass-eval/test: Container must stay unbound")

    observer_names = {
        "base": "quant-platform-receipt-activation-observer",
        "production": "quant-platform-receipt-activation-observer",
        "staging": "quant-platform-receipt-activation-observer-staging",
    }
    no_observer_bindings = (
        "d1_databases",
        "r2_buckets",
        "kv_namespaces",
        "queue_producers",
        "queue_consumers",
        "durable_objects",
        "tail_consumers",
        "ratelimits",
    )
    for environment in ("base", "production", "staging"):
        observer = workers["receipt-activation-observer"][environment]
        if (
            observer["name"] != observer_names[environment]
            or observer["preview_urls"] is not False
            or observer["route"] is not None
            or observer["routes"] != []
            or observer["worker_entrypoints"] != []
            or observer["durable_object_class_handlers"] != []
            or observer["secret_names"] != []
            or any(observer[field] != [] for field in no_observer_bindings)
            or observer["ai"] != {}
        ):
            raise ValueError(
                f"receipt-activation-observer/{environment}: capability surface drift"
            )
        if observer["vars"] != {
            "ENVIRONMENT": "staging" if environment == "staging" else "disabled"
        }:
            raise ValueError(
                f"receipt-activation-observer/{environment}: environment policy drift"
            )
    observer_base = workers["receipt-activation-observer"]["base"]
    if observer_base["workers_dev"] is not False or observer_base["services"] != []:
        raise ValueError("receipt-activation-observer/base: public surface drift")
    observer_production = workers["receipt-activation-observer"]["production"]
    if observer_production["workers_dev"] is not False or observer_production["services"] != [
        {
            "binding": "JSDA_INGESTION",
            "entrypoint": "JsdaReadinessService",
            "service": "quant-platform-ingestion-jsda",
        },
    ]:
        raise ValueError(
            "receipt-activation-observer/production: HOLD JSDA collector binding drift"
        )
    observer_staging = workers["receipt-activation-observer"]["staging"]
    if observer_staging["workers_dev"] is not True or observer_staging["services"] != [
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
    ]:
        raise ValueError(
            "receipt-activation-observer/staging: operator binding drift"
        )

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
    raw_buckets = {
        "base": "quant-raw",
        "production": "quant-raw",
        "staging": "quant-raw-staging",
    }
    structured_buckets = {
        "base": "quant-structured",
        "production": "quant-structured",
        "staging": "quant-structured-staging",
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
            {
                "binding": "RAW_BUCKET",
                "bucket_name": raw_buckets[environment],
            },
            {
                "binding": "STRUCTURED_BUCKET",
                "bucket_name": structured_buckets[environment],
            },
        ]
        if receipt["r2_buckets"] != expected_buckets:
            raise ValueError(
                f"receipt-evidence-authority/{environment}: dedicated "
                "authority store identity drift"
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
            "OPS_PROJECTION_ENVIRONMENT": (
                "staging" if environment == "staging" else "production"
            ),
            "OPS_PROJECTION_SIGNING_KEY_ID": (
                "ops-projection-cloud-staging-v1"
                if environment == "staging"
                else "ops-projection-20260826-v2"
            ),
            "RECEIPT_AUTHORITY_ENVIRONMENT": (
                "staging" if environment == "staging" else "production"
            ),
            "RECEIPT_AUTHORITY_OPERATION_MODE": "PENDING",
            "READY_DECLARED": "false",
        }:
            raise ValueError(
                f"ingestion-premium/{environment}: Receipt environment policy drift"
            )

    for environment, expected in _OPS_D1_IDENTITY.items():
        ops_surface = workers["quant-ops-mcp"][environment]
        databases = ops_surface["d1_databases"]
        actual = tuple(_ops_d1_row(row) for row in databases)
        if actual != expected:
            raise ValueError(
                f"quant-ops-mcp/{environment}: dedicated projection/quota "
                f"bindings drifted: {list(actual)}"
            )
        if ops_surface["durable_objects"] != [{
            "class_name": "QuantOpsMcpAgent",
            "name": "MCP_OBJECT",
        }]:
            raise ValueError(
                f"quant-ops-mcp/{environment}: MCP_OBJECT must be a self-only "
                "QuantOpsMcpAgent namespace"
            )
        if ops_surface["services"] != []:
            raise ValueError(
                f"quant-ops-mcp/{environment}: MCP_OBJECT Worker must not "
                "receive Service Binding capabilities"
            )

    ops_test = manifest["test_harness_surfaces"].get("quant-ops-mcp")
    if not isinstance(ops_test, dict):
        raise ValueError("quant-ops-mcp: governed test-harness surface is required")
    if ops_test["durable_objects"] != [{
        "class_name": "QuantOpsMcpAgent",
        "name": "MCP_OBJECT",
    }] or ops_test["services"] != []:
        raise ValueError(
            "quant-ops-mcp/test: MCP_OBJECT must be self-only without Service Bindings"
        )

    ops_worker_names = {
        workers["quant-ops-mcp"][environment]["name"]
        for environment in ("base", "production", "staging")
    }
    for worker, environments in workers.items():
        if worker == "quant-ops-mcp":
            continue
        for environment, surface in environments.items():
            if any(
                row.get("name") == "MCP_OBJECT"
                or row.get("class_name") == "QuantOpsMcpAgent"
                or row.get("script_name") in ops_worker_names
                for row in surface["durable_objects"]
            ) or any(
                row.get("service") in ops_worker_names
                for row in surface["services"]
            ):
                raise ValueError(
                    f"{worker}/{environment}: QuantOps MCP_OBJECT capability "
                    "must not be distributed to another Worker"
                )

    for environment in ("base", "production"):
        ratelimits = workers["ingestion-secrets"][environment]["ratelimits"]
        if {row.get("name") for row in ratelimits} != {"PROXY_RATE_LIMITER"}:
            raise ValueError(
                f"ingestion-secrets/{environment}: PROXY_RATE_LIMITER binding required"
            )

    jsda_main = "quant-jsda-ingestion"
    jsda_dlq = "quant-jsda-ingestion-dlq"
    for environment in ("base", "production"):
        consumers = workers["ingestion-jsda"][environment]["queue_consumers"]
        if any(row.get("queue") == jsda_dlq for row in consumers):
            raise ValueError(
                f"ingestion-jsda/{environment}: production DLQ must not have a consumer"
            )
        mains = [row for row in consumers if row.get("queue") == jsda_main]
        if (
            len(mains) != 1
            or mains[0].get("dead_letter_queue") != jsda_dlq
        ):
            raise ValueError(
                f"ingestion-jsda/{environment}: main Queue must keep the "
                "quant-jsda-ingestion-dlq dead-letter route"
            )
    staging_consumers = workers["ingestion-jsda"]["staging"]["queue_consumers"]
    if not any(
        row.get("queue") == "quant-jsda-ingestion-dlq-staging"
        for row in staging_consumers
    ):
        raise ValueError(
            "ingestion-jsda/staging: staging DLQ consumer fixture is required"
        )

    body = {key: value for key, value in manifest.items() if key != "manifest_digest"}
    if manifest["ops_binding_identity_digest"] != quant_ops_binding_identity_digest(
        workers
    ):
        raise ValueError("ops binding identity digest drift")
    if manifest["manifest_digest"] != _canonical_digest(body):
        raise ValueError("binding manifest digest drift")


def _render(manifest: dict[str, Any]) -> str:
    return json.dumps(manifest, indent=2, sort_keys=True) + "\n"


def _clean_merged_sha(*, runner: Any | None = None) -> str:
    # Look up subprocess.run at call time; a bound default would ignore test injection.
    run = subprocess.run if runner is None else runner
    from scripts.receipt_authority_pending_gate import (
        PendingReceiptAuthorityError,
        _require_exact_clean_source,
    )
    from scripts.receipt_authority_pending_live_acceptance import (
        ReceiptPendingLiveAcceptanceError,
        _require_official_origin_main,
    )

    completed = run(
        ["git", "rev-parse", "HEAD"],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        check=False,
    )
    sha = (completed.stdout or "").strip()
    try:
        _require_exact_clean_source(sha)
        _require_official_origin_main(sha, runner=run)
    except (PendingReceiptAuthorityError, ReceiptPendingLiveAcceptanceError) as exc:
        raise ValueError(
            "merged SHA is not current clean official origin/main"
        ) from exc
    return sha


_SHA40 = re.compile(r"^[0-9a-f]{40}$")


def _load_json_object(payload: object, *, label: str) -> dict[str, Any]:
    document = payload
    if isinstance(payload, str):
        try:
            document = json.loads(payload)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{label} is not JSON") from exc
    if not isinstance(document, dict):
        raise ValueError(f"{label} is malformed")
    return document


_SUPPORTED_DEPLOY_ENVIRONMENTS = frozenset({"production", "staging"})
_ACCOUNT_ID = re.compile(r"^[0-9a-f]{32}$")
_UUID = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
)


def _generic_wrapper_workers() -> frozenset[str]:
    marker = _python_from_worker_package("cloudflare_binding_manifest.py")
    return frozenset(
        worker
        for worker, scripts in _PINNED_PACKAGE_SCRIPTS.items()
        if marker in scripts.get("deploy", "")
        and "--deploy-tagged" in scripts.get("deploy", "")
    )


def _status_argv(
    executable: str, config: str, environment_args: tuple[str, ...]
) -> list[str]:
    return [
        executable,
        "deployments",
        "status",
        "--config",
        config,
        "--json",
        *environment_args,
    ]


def _version_view_argv(
    executable: str,
    version_id: str,
    config: str,
    environment_args: tuple[str, ...],
) -> list[str]:
    return [
        executable,
        "versions",
        "view",
        version_id,
        "--config",
        config,
        "--json",
        *environment_args,
    ]


def _wrangler_selector_args(environment: str) -> tuple[str, ...]:
    if environment == "staging":
        return ("--config", "wrangler.staging.toml")
    return ("--config", "wrangler.toml", "--env", "production")


def parse_selected_deployment(payload: object) -> dict[str, str]:
    document = _load_json_object(payload, label="deployment observation")
    versions = document.get("versions")
    if not isinstance(versions, list) or len(versions) != 1 or not isinstance(versions[0], dict):
        raise ValueError("deployment must select exactly one version")
    row = versions[0]
    if row.get("percentage") != 100:
        raise ValueError("deployment must route 100 percent to one version")
    version_id = row.get("version_id")
    if not isinstance(version_id, str) or not version_id:
        raise ValueError("selected version id is missing")
    deployment_id = document.get("id")
    if not isinstance(deployment_id, str) or not deployment_id:
        raise ValueError("selected deployment id is missing")
    return {
        "deployment_id": deployment_id,
        "version_id": version_id,
        "traffic_percent": "100",
    }


def parse_selected_version(
    payload: object,
    *,
    version_id: str,
    expected_sha: str,
) -> None:
    if not _SHA40.fullmatch(expected_sha):
        raise ValueError("expected SHA is not a clean merged Git SHA")
    document = _load_json_object(payload, label="version observation")
    if document.get("id") != version_id:
        raise ValueError("version document id does not match selected version")
    annotations = document.get("annotations")
    if not isinstance(annotations, dict):
        raise ValueError("selected version tag/message is not the exact merged SHA")
    if (
        annotations.get("workers/tag") != expected_sha
        or annotations.get("workers/message") != expected_sha
    ):
        raise ValueError("selected version tag/message is not the exact merged SHA")


def _observe_selected_version(
    *,
    executable: str,
    version_id: str,
    config: str,
    environment_args: tuple[str, ...],
    directory: Path,
    run: Any,
    command_env: Mapping[str, str] | None,
    expected_sha: str,
) -> dict[str, Any]:
    viewed = _run_pinned(
        run,
        _version_view_argv(executable, version_id, config, environment_args),
        cwd=directory,
        command_env=command_env,
        timeout=120,
    )
    if viewed.returncode != 0:
        raise ValueError("tagged deploy could not observe selected version")
    parse_selected_version(
        viewed.stdout or "",
        version_id=version_id,
        expected_sha=expected_sha,
    )
    return _load_json_object(viewed.stdout or "", label="version observation")


def _observe_selected_deployment(
    *,
    executable: str,
    config: str,
    environment_args: tuple[str, ...],
    directory: Path,
    run: Any,
    command_env: Mapping[str, str] | None = None,
) -> dict[str, str]:
    observed = run(
        _status_argv(executable, config, environment_args),
        cwd=str(directory),
        capture_output=True,
        text=True,
        check=False,
        **({"env": dict(command_env)} if command_env is not None else {}),
    )
    if observed.returncode != 0:
        raise ValueError("tagged deploy could not observe selected version")
    return parse_selected_deployment(observed.stdout or "")


def _canonical_deploy_target(
    *,
    worker: str,
    environment: str,
    environ: Mapping[str, str],
) -> dict[str, Any]:
    if worker not in ACTIVE_WORKERS:
        raise ValueError("canonical deploy target is unknown or inactive")
    if environment not in _SUPPORTED_DEPLOY_ENVIRONMENTS:
        raise ValueError("canonical deploy environment is unsupported")
    if worker not in _generic_wrapper_workers():
        raise ValueError(
            f"{worker}: generic tagged deploy is not the specialized or PENDING entrypoint"
        )
    directory = WORKER_ROOT / worker
    if directory.is_symlink() or not directory.is_dir():
        raise ValueError(f"{worker}: worker directory is absent or indirect")
    config_name = (
        "wrangler.staging.toml" if environment == "staging" else "wrangler.toml"
    )
    config_path = directory / config_name
    if (
        config_path.is_symlink()
        or not config_path.is_file()
        or config_path.resolve().parent != directory.resolve()
    ):
        raise ValueError(f"{worker}: tracked Wrangler config is absent or indirect")
    data = _load_toml(config_path)
    if environment == "staging":
        section = data
        worker_name = data.get("name")
        environment_args: tuple[str, ...] = ()
        if data.get("env") is not None:
            raise ValueError(
                f"{worker}: dedicated staging config must not contain named envs"
            )
    else:
        try:
            section = data["env"]["production"]
        except (KeyError, TypeError) as exc:
            raise ValueError(f"{worker}: missing [env.production]") from exc
        if not isinstance(section, dict):
            raise ValueError(f"{worker}: env.production must be a table")
        inherited = data.get("name")
        worker_name = section.get("name", inherited)
        if "name" not in section and isinstance(inherited, str) and inherited:
            worker_name = f"{inherited}-production"
        environment_args = ("--env", "production")
    containers = section.get("containers")
    if containers is None and environment != "staging":
        containers = data.get("containers")
    if containers:
        raise ValueError(
            f"{worker}: local generic deploy is prohibited while a Container image is declared"
        )
    if not isinstance(worker_name, str) or not worker_name:
        raise ValueError(f"{worker}: Worker name is missing")
    if (
        "WRANGLER_CI_OVERRIDE_NAME" in environ
        and environ.get("WRANGLER_CI_OVERRIDE_NAME") != worker_name
    ):
        raise ValueError(
            "WRANGLER_CI_OVERRIDE_NAME conflicts with the canonical Worker name"
        )
    if "account_id" in section:
        config_account = section.get("account_id")
    elif "account_id" in data:
        config_account = data.get("account_id")
    else:
        config_account = None
    if config_account is not None and config_account != PROJECT_ACCOUNT_ID:
        raise ValueError(
            "tracked Wrangler account_id does not match the approved project account"
        )
    for override_name in ("CLOUDFLARE_ACCOUNT_ID", "CF_ACCOUNT_ID"):
        if override_name in environ and environ.get(override_name) != PROJECT_ACCOUNT_ID:
            raise ValueError(
                "authenticated account does not match the approved project account"
            )
    package_path = directory / "package.json"
    if package_path.is_symlink() or not package_path.is_file():
        raise ValueError(f"{worker}: package.json is absent or indirect")
    try:
        package = json.loads(package_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"{worker}: package.json is unreadable") from exc
    pin = (package.get("devDependencies") or {}).get("wrangler") if isinstance(
        package, dict
    ) else None
    if pin != TOOLCHAIN["wrangler"]:
        raise ValueError(f"{worker}: Wrangler pin is not the exact toolchain version")
    deploy_command = _PINNED_PACKAGE_SCRIPTS.get(worker, {}).get("deploy", "")
    return {
        "worker": worker,
        "environment": environment,
        "directory": directory,
        "config_name": config_name,
        "config_path": config_path,
        "environment_args": environment_args,
        "worker_name": worker_name,
        "executable": directory / "node_modules" / ".bin" / "wrangler",
        "requires_ops_gate": "predeploy_ops_projection_gate.py" in deploy_command,
        "account_id": PROJECT_ACCOUNT_ID,
    }


def _run_pinned(
    run: Any,
    argv: list[str],
    *,
    cwd: Path,
    command_env: Mapping[str, str] | None = None,
    timeout: int | None = None,
) -> subprocess.CompletedProcess[str]:
    kwargs: dict[str, Any] = {
        "cwd": str(cwd),
        "capture_output": True,
        "text": True,
        "check": False,
    }
    if command_env is not None:
        kwargs["env"] = dict(command_env)
    if timeout is not None:
        kwargs["timeout"] = timeout
    return run(argv, **kwargs)


def _parse_bearer_token(payload: str) -> str:
    try:
        document = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise ValueError("pinned Wrangler auth token output is malformed") from exc
    if not isinstance(document, dict):
        raise ValueError("pinned Wrangler auth token output is malformed")
    kind = document.get("type")
    if kind == "api_key":
        raise ValueError("Cloudflare API keys are not a supported bearer credential")
    if kind not in {"api_token", "oauth"}:
        raise ValueError("pinned Wrangler auth token type is unsupported")
    token = document.get("token")
    if not isinstance(token, str) or not token:
        raise ValueError("pinned Wrangler auth token is missing")
    return token


def _require_authenticated_account(
    *,
    target: dict[str, Any],
    executable: str,
    run: Any,
    environ: Mapping[str, str],
    isolated_env: Mapping[str, str],
) -> str:
    account_id = target["account_id"]
    if _ACCOUNT_ID.fullmatch(account_id) is None:
        raise ValueError("approved project account id is malformed")
    configured = (environ.get("CLOUDFLARE_ACCOUNT_ID") or "").strip()
    if configured and configured != account_id:
        raise ValueError("authenticated account does not match the approved project account")
    if (environ.get("CLOUDFLARE_API_KEY") or "").strip():
        raise ValueError("Cloudflare API keys are not a supported bearer credential")
    token = (environ.get("CLOUDFLARE_API_TOKEN") or "").strip()
    if not token:
        completed = _run_pinned(
            run,
            [executable, "auth", "token", "--json"],
            cwd=target["directory"],
            command_env=dict(environ),
            timeout=30,
        )
        if completed.returncode != 0:
            raise ValueError("canonical deploy could not establish a bearer credential")
        token = _parse_bearer_token(completed.stdout or "")
    whoami = _run_pinned(
        run,
        [executable, "whoami", "--json"],
        cwd=target["directory"],
        command_env={**dict(isolated_env), "CLOUDFLARE_API_TOKEN": token, "CLOUDFLARE_ACCOUNT_ID": account_id},
        timeout=30,
    )
    if whoami.returncode != 0:
        raise ValueError("canonical deploy could not verify the authenticated account")
    try:
        document = json.loads(whoami.stdout or "")
    except json.JSONDecodeError as exc:
        raise ValueError("pinned Wrangler whoami output is malformed") from exc
    if not isinstance(document, dict) or document.get("loggedIn") is not True:
        raise ValueError("canonical deploy could not verify the authenticated account")
    accounts = document.get("accounts")
    if not isinstance(accounts, list) or not accounts:
        raise ValueError("authenticated account list is empty or ambiguous")
    ids = [
        row.get("id")
        for row in accounts
        if isinstance(row, dict)
    ]
    if account_id not in ids:
        raise ValueError("authenticated account does not match the approved project account")
    return token


def _require_pinned_local_wrangler(directory: Path) -> str:
    """Require the worker-local package entrypoint, not an unrelated binary."""

    worker = directory.name
    executable = directory / "node_modules" / ".bin" / "wrangler"
    package_entrypoint = directory / "node_modules" / "wrangler" / "bin" / "wrangler.js"
    package_json = directory / "node_modules" / "wrangler" / "package.json"
    try:
        resolved = executable.resolve(strict=True)
        expected = package_entrypoint.resolve(strict=True)
    except OSError as exc:
        raise ValueError(f"{worker}: pinned Wrangler is not installed") from exc
    if not executable.is_file() or resolved != expected:
        raise ValueError(f"{worker}: pinned Wrangler is not the package entrypoint")
    try:
        installed = json.loads(package_json.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ValueError(f"{worker}: pinned Wrangler package is unreadable") from exc
    version = installed.get("version") if isinstance(installed, dict) else None
    if version != TOOLCHAIN["wrangler"]:
        raise ValueError(f"{worker}: installed Wrangler pin is not exact")
    return str(executable)


def _require_pinned_executable(target: dict[str, Any], *, run: Any | None = None) -> str:
    del run
    return _require_pinned_local_wrangler(target["directory"])


def deploy_tagged(
    *,
    worker: str,
    environment: str,
    runner: Any | None = None,
    opener: Any | None = None,
    environ: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    from scripts.predeploy_ops_projection_gate import (
        PredeployGateError,
        require_sealed_active_generation,
    )
    from scripts.receipt_authority_pending_live_acceptance import (
        ReceiptPendingLiveAcceptanceError,
        _compare_module_inventories,
        _isolated_command_environment,
        _live_version_module_inventory,
        _require_verified_module_inventory,
        parse_worker_upload_bundle,
    )
    from urllib.request import urlopen

    run = subprocess.run if runner is None else runner
    transport = urlopen if opener is None else opener
    process_env = os.environ if environ is None else environ
    target = _canonical_deploy_target(
        worker=worker, environment=environment, environ=process_env
    )
    sha = _clean_merged_sha(runner=run)
    if not _SHA40.fullmatch(sha):
        raise ValueError("merged SHA is not 40 hex")
    executable = _require_pinned_executable(target)
    with tempfile.TemporaryDirectory(prefix="quant-canonical-deploy-") as temporary:
        isolated_root = Path(temporary)
        token: str | None = None
        try:
            build_env = _isolated_command_environment(isolated_root / "build-environment")
            credential_env = _isolated_command_environment(
                isolated_root / "credential-environment"
            )
            token = _require_authenticated_account(
                target=target,
                executable=executable,
                run=run,
                environ=process_env,
                isolated_env=credential_env,
            )
            mutate_env = _isolated_command_environment(
                isolated_root / "mutate-environment",
                account_id=target["account_id"],
                api_token=token,
            )
            if target["requires_ops_gate"]:
                previous_token = os.environ.get("CLOUDFLARE_API_TOKEN")
                previous_account = os.environ.get("CLOUDFLARE_ACCOUNT_ID")
                os.environ["CLOUDFLARE_API_TOKEN"] = token
                os.environ["CLOUDFLARE_ACCOUNT_ID"] = target["account_id"]
                try:
                    require_sealed_active_generation(
                        environment, intended_source_sha=sha
                    )
                except PredeployGateError as exc:
                    raise ValueError(
                        f"{worker}: ops projection predeploy gate failed"
                    ) from exc
                finally:
                    if previous_token is None:
                        os.environ.pop("CLOUDFLARE_API_TOKEN", None)
                    else:
                        os.environ["CLOUDFLARE_API_TOKEN"] = previous_token
                    if previous_account is None:
                        os.environ.pop("CLOUDFLARE_ACCOUNT_ID", None)
                    else:
                        os.environ["CLOUDFLARE_ACCOUNT_ID"] = previous_account
            outfile = isolated_root / "worker.bundle"
            dry_run = _run_pinned(
                run,
                [
                    executable,
                    "deploy",
                    "--dry-run",
                    * _wrangler_selector_args(environment),
                    "--outfile",
                    str(outfile),
                ],
                cwd=target["directory"],
                command_env=build_env,
                timeout=120,
            )
            if dry_run.returncode != 0 or outfile.is_symlink() or not outfile.is_file():
                raise ValueError("tagged deploy local upload inventory failed")
            try:
                local_inventory = parse_worker_upload_bundle(outfile.read_bytes())
            finally:
                try:
                    outfile.unlink()
                except OSError:
                    pass
            deploy = _run_pinned(
                run,
                [
                    executable,
                    "deploy",
                    "--config",
                    target["config_name"],
                    "--tag",
                    sha,
                    "--message",
                    sha,
                    *target["environment_args"],
                ],
                cwd=target["directory"],
                command_env=mutate_env,
                timeout=120,
            )
            if deploy.returncode != 0:
                raise ValueError("tagged wrangler deploy failed")
            selected = _observe_selected_deployment(
                executable=executable,
                config=target["config_name"],
                environment_args=target["environment_args"],
                directory=target["directory"],
                run=run,
                command_env=mutate_env,
            )
            if _UUID.fullmatch(selected["version_id"]) is None:
                raise ValueError("selected version id must be a full UUID")
            version_document = _observe_selected_version(
                executable=executable,
                version_id=selected["version_id"],
                config=target["config_name"],
                environment_args=target["environment_args"],
                directory=target["directory"],
                run=run,
                command_env=mutate_env,
                expected_sha=sha,
            )
            live_inventory = _live_version_module_inventory(
                account_id=target["account_id"],
                worker_name=target["worker_name"],
                version_id=selected["version_id"],
                api_token=token,
                opener=transport,
            )
            inventory = _compare_module_inventories(
                local_inventory, live_inventory, label=worker
            )
            reread = _observe_selected_deployment(
                executable=executable,
                config=target["config_name"],
                environment_args=target["environment_args"],
                directory=target["directory"],
                run=run,
                command_env=mutate_env,
            )
            if reread != selected:
                raise ValueError("selected deployment changed during version read")
            version_reread = _observe_selected_version(
                executable=executable,
                version_id=selected["version_id"],
                config=target["config_name"],
                environment_args=target["environment_args"],
                directory=target["directory"],
                run=run,
                command_env=mutate_env,
                expected_sha=sha,
            )
            modules_reread = _live_version_module_inventory(
                account_id=target["account_id"],
                worker_name=target["worker_name"],
                version_id=selected["version_id"],
                api_token=token,
                opener=transport,
            )
            reread_inventory = _require_verified_module_inventory(
                {
                    "main_module": modules_reread["main_module"],
                    "modules": modules_reread["modules"],
                },
                label=f"{worker} version reread",
            )
            if (
                modules_reread.get("id") != selected["version_id"]
                or reread_inventory != inventory
                or _canonical_digest(version_document) != _canonical_digest(version_reread)
            ):
                raise ValueError("selected version changed during module read")
        except ReceiptPendingLiveAcceptanceError as exc:
            raise ValueError(str(exc)) from exc
        finally:
            token = None
    if _clean_merged_sha(runner=run) != sha:
        raise ValueError("merged SHA changed during tagged deploy")
    facts = {
        "result": "VERIFIED_EXACT_MODULE_BYTES",
        "worker": worker,
        "environment": environment,
        "account_id": target["account_id"],
        "source_sha": sha,
        "deployment_id": selected["deployment_id"],
        "version_id": selected["version_id"],
        "main_module": inventory["main_module"],
        "modules": inventory["modules"],
    }
    print(json.dumps(facts, sort_keys=True, separators=(",", ":")))
    return facts


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--write", action="store_true", help="replace the frozen manifest")
    parser.add_argument(
        "--print-worker-paths",
        action="store_true",
        help="print canonical active Worker paths, one per line",
    )
    parser.add_argument("--deploy-tagged", action="store_true")
    parser.add_argument("--worker")
    parser.add_argument("--config")
    parser.add_argument("--env", dest="environment", default="production")
    args = parser.parse_args(argv)
    if args.deploy_tagged:
        if args.config is not None:
            parser.error("canonical deploy does not accept a caller config")
        if not args.worker:
            parser.error("--worker is required for --deploy-tagged")
        deploy_tagged(worker=args.worker, environment=args.environment)
        return 0
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
