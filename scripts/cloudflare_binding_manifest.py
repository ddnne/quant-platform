#!/usr/bin/env python3
"""Freeze every active Cloudflare Worker deployment surface.

The manifest is intentionally generated from Wrangler TOML plus an explicit
secret-name policy. It contains names only; secret values are never read.
"""

from __future__ import annotations

import argparse
import json
import sys
import tomllib
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "specs" / "cloudflare" / "active_worker_bindings.json"
WORKER_ROOT = ROOT / "platform" / "workers"

ACTIVE_WORKERS = (
    "ingestion-jsda",
    "ingestion-premium",
    "ingestion-secrets",
    "quant-ops-mcp",
    "research-ai-gateway",
    "research-mass-eval",
)

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
    "ingestion-secrets": ("JQUANTS_API_KEY", "JQUANTS_PROXY_TOKEN"),
    "quant-ops-mcp": (
        "GITHUB_CLIENT_ID",
        "GITHUB_CLIENT_SECRET",
        "STATE_SECRET",
    ),
    "research-ai-gateway": ("GATEWAY_TOKEN",),
    "research-mass-eval": ("MASS_EVAL_TOKEN",),
}


def _load_toml(path: Path) -> dict[str, Any]:
    with path.open("rb") as fh:
        return tomllib.load(fh)


def _json_rows(value: Any) -> list[dict[str, Any]]:
    if not value:
        return []
    if not isinstance(value, list) or not all(isinstance(row, dict) for row in value):
        raise ValueError(f"expected a list of tables, got {type(value).__name__}")
    rows = [dict(sorted(row.items())) for row in value]
    return sorted(rows, key=lambda row: json.dumps(row, sort_keys=True))


def _effective_surface(
    *,
    worker: str,
    config_path: Path,
    environment: str,
    named_environment: str | None,
) -> dict[str, Any]:
    data = _load_toml(config_path)
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

    secrets = () if environment == "staging" else PRODUCTION_SECRET_NAMES[worker]
    package = json.loads((WORKER_ROOT / worker / "package.json").read_text(encoding="utf-8"))
    dev_dependencies = package.get("devDependencies") or {}
    pinned_toolchain = {name: dev_dependencies.get(name) for name in TOOLCHAIN}

    return {
        "config": str(config_path.relative_to(ROOT)),
        "name": scalar("name"),
        "main": scalar("main"),
        "compatibility_date": scalar("compatibility_date"),
        "compatibility_flags": sorted(scalar("compatibility_flags", default=[]) or []),
        "workers_dev": bool(scalar("workers_dev", default=True)),
        "preview_urls": bool(scalar("preview_urls", default=True)),
        "routes": _json_rows(section.get("routes")),
        "d1_databases": _json_rows(section.get("d1_databases")),
        "r2_buckets": _json_rows(section.get("r2_buckets")),
        "kv_namespaces": _json_rows(section.get("kv_namespaces")),
        "queue_producers": _json_rows(queues.get("producers")),
        "queue_consumers": _json_rows(queues.get("consumers")),
        "durable_objects": _json_rows(durable_objects.get("bindings")),
        "services": _json_rows(section.get("services")),
        "ratelimits": _json_rows(section.get("ratelimits")),
        "ai": dict(sorted((section.get("ai") or {}).items())),
        "migrations": _json_rows(migrations),
        "crons": sorted(((section.get("triggers") or {}).get("crons") or [])),
        "vars": dict(sorted((section.get("vars") or {}).items())),
        "secret_names": sorted(secrets),
        "toolchain": pinned_toolchain,
    }


def build_manifest() -> dict[str, Any]:
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
    manifest = {
        "schema_version": "cloudflare-active-worker-bindings/v1",
        "active_workers": list(ACTIVE_WORKERS),
        "toolchain_policy": TOOLCHAIN,
        "workers": workers,
    }
    validate_manifest(manifest)
    return manifest


def validate_manifest(manifest: dict[str, Any]) -> None:
    workers = manifest["workers"]
    if tuple(workers) != ACTIVE_WORKERS:
        raise ValueError("active Worker order or membership drift")

    for worker, environments in workers.items():
        for environment, surface in environments.items():
            if surface["preview_urls"]:
                raise ValueError(f"{worker}/{environment}: preview_urls must be false")
            for package_name, expected in TOOLCHAIN.items():
                actual = surface["toolchain"].get(package_name)
                if actual != expected:
                    raise ValueError(
                        f"{worker}: {package_name} must be exactly {expected}, got {actual!r}"
                    )

        staging = environments["staging"]
        if not str(staging["name"]).endswith("-staging"):
            raise ValueError(f"{worker}: staging Worker name must end in -staging")
        if staging["secret_names"]:
            raise ValueError(f"{worker}: production secret names leaked into staging policy")
        for table, fields in {
            "d1_databases": ("database_name",),
            "r2_buckets": ("bucket_name",),
            "queue_producers": ("queue",),
            "queue_consumers": ("queue", "dead_letter_queue"),
            "services": ("service",),
        }.items():
            for row in staging[table]:
                for field in fields:
                    value = row.get(field)
                    if value is not None and not str(value).endswith("-staging"):
                        raise ValueError(
                            f"{worker}/staging: {table}.{field} is not staging-isolated: {value}"
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
    args = parser.parse_args(argv)
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
