#!/usr/bin/env python3
"""Build/check the canonical Cloudflare D1 migration ownership manifest.

The source-controlled manifest records ownership, physical target bindings,
ordering, dependencies, and content checksums. Remote applied state is never
inferred from files or Wrangler config; release evidence must record the actual
post-apply state separately.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
import tomllib
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[1]
WORKERS = ROOT / "platform" / "workers"
MANIFEST = ROOT / "specs" / "cloudflare" / "d1_migration_manifest.json"

TARGETS: Mapping[str, Mapping[str, str]] = {
    "quant-ingest": {
        "target_role": "ingestion_source_of_truth",
        "owner": "platform/workers/ingestion-premium",
        "worker": "ingestion-premium",
        "binding": "DB",
        "migration_dir": "migrations",
    },
    "quant-ops-projection": {
        "target_role": "ops_projection_read_model",
        "owner": "platform/workers/quant-ops-mcp",
        "worker": "quant-ops-mcp",
        "binding": "OPS_PROJECTION_DB",
        "migration_dir": "migrations/projection",
    },
    "quant-ops-quota": {
        "target_role": "ops_mcp_quota",
        "owner": "platform/workers/quant-ops-mcp",
        "worker": "quant-ops-mcp",
        "binding": "QUOTA_DB",
        "migration_dir": "migrations/quota",
    },
}

APPLICATION_POLICIES: Mapping[str, Mapping[str, Any]] = {
    "quant-ingest": {
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
            "jsda-v3-readiness-smoke-before-product-acceptance",
        ],
    },
    "quant-ops-projection": {
        "mode": "wrangler-canonical-owner/v1",
        "owner_command": None,
        "environment_order": ["staging", "production"],
        "requires": [],
    },
    "quant-ops-quota": {
        "mode": "wrangler-canonical-owner/v1",
        "owner_command": None,
        "environment_order": ["staging", "production"],
        "requires": [],
    },
}


def _load_toml(path: Path) -> dict[str, Any]:
    with path.open("rb") as handle:
        return tomllib.load(handle)


def _environment_section(
    worker: str, environment: str
) -> tuple[Path, dict[str, Any]]:
    directory = WORKERS / worker
    if environment == "staging":
        path = directory / "wrangler.staging.toml"
        return path, _load_toml(path)
    path = directory / "wrangler.toml"
    document = _load_toml(path)
    if environment == "base":
        return path, document
    try:
        section = document["env"]["production"]
    except (KeyError, TypeError) as exc:
        raise ValueError(f"{path}: missing [env.production]") from exc
    return path, section


def _database(
    worker: str, environment: str, binding: str
) -> tuple[Path, dict[str, Any]]:
    config, section = _environment_section(worker, environment)
    matches = [
        dict(row)
        for row in section.get("d1_databases") or []
        if row.get("binding") == binding
    ]
    if len(matches) != 1:
        raise ValueError(
            f"{config}: expected exactly one {binding} D1 binding in {environment}"
        )
    return config, matches[0]


def _checksum(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _migrations(target_name: str, owner: str, migration_dir: str) -> list[dict[str, Any]]:
    directory = ROOT / owner / migration_dir
    paths = sorted(directory.glob("*.sql"))
    if not paths:
        raise ValueError(f"{directory}: no SQL migrations")
    rows: list[dict[str, Any]] = []
    previous: str | None = None
    for order, path in enumerate(paths, start=1):
        migration_id = f"{target_name}:{path.stem}"
        rows.append(
            {
                "migration_id": migration_id,
                "path": str(path.relative_to(ROOT)),
                "checksum": _checksum(path),
                "order": order,
                "depends_on": previous,
            }
        )
        previous = migration_id
    return rows


def build_manifest() -> dict[str, Any]:
    targets: dict[str, Any] = {}
    for target_name, policy in TARGETS.items():
        owner = policy["owner"]
        migration_dir = policy["migration_dir"]
        environments: dict[str, Any] = {}
        for environment in ("base", "production", "staging"):
            config, database = _database(
                policy["worker"], environment, policy["binding"]
            )
            configured_dir = str(database.get("migrations_dir") or "migrations")
            if configured_dir != migration_dir:
                raise ValueError(
                    f"{config}: {policy['binding']} migrations_dir {configured_dir!r} "
                    f"does not match canonical {migration_dir!r}"
                )
            environments[environment] = {
                "config": str(config.relative_to(ROOT)),
                "binding": policy["binding"],
                "database_name": str(database["database_name"]),
                "database_id": str(database["database_id"]),
                "migrations_table": str(
                    database.get("migrations_table") or "d1_migrations"
                ),
                "applied_state": "UNVERIFIED",
            }
        targets[target_name] = {
            "target_role": policy["target_role"],
            "owner": owner,
            "migration_dir": str((ROOT / owner / migration_dir).relative_to(ROOT)),
            "application_policy": dict(APPLICATION_POLICIES[target_name]),
            "environments": environments,
            "migrations": _migrations(target_name, owner, migration_dir),
        }
    manifest = {
        "schema_version": "cloudflare-d1-migration-manifest/v1",
        "applied_state_policy": (
            "UNVERIFIED is fail-closed source state; remote post-apply state belongs "
            "in immutable release evidence"
        ),
        "targets": targets,
    }
    validate_manifest(manifest)
    return manifest


def validate_manifest(manifest: Mapping[str, Any]) -> None:
    targets = manifest.get("targets")
    if not isinstance(targets, Mapping) or tuple(targets) != tuple(TARGETS):
        raise ValueError("canonical D1 target order or membership drift")
    included: set[str] = set()
    for target_name, target in targets.items():
        policy = TARGETS[str(target_name)]
        if target.get("owner") != policy["owner"]:
            raise ValueError(f"{target_name}: migration owner drift")
        if target.get("application_policy") != APPLICATION_POLICIES[target_name]:
            raise ValueError(f"{target_name}: migration application policy drift")
        migrations = target.get("migrations") or []
        for order, migration in enumerate(migrations, start=1):
            if migration.get("order") != order:
                raise ValueError(f"{target_name}: non-canonical migration order")
            expected_dependency = None if order == 1 else migrations[order - 2]["migration_id"]
            if migration.get("depends_on") != expected_dependency:
                raise ValueError(f"{target_name}: dependency chain drift")
            path = str(migration["path"])
            if path in included:
                raise ValueError(f"migration appears under multiple owners: {path}")
            included.add(path)
        environments = target.get("environments") or {}
        if tuple(environments) != ("base", "production", "staging"):
            raise ValueError(f"{target_name}: environment set drift")
        for environment, binding in environments.items():
            if binding.get("applied_state") != "UNVERIFIED":
                raise ValueError(
                    f"{target_name}/{environment}: source manifest may not claim remote apply"
                )

    discovered = {
        str(path.relative_to(ROOT))
        for path in (WORKERS).glob("*/migrations/**/*.sql")
    }
    if included != discovered:
        missing = sorted(discovered - included)
        extra = sorted(included - discovered)
        raise ValueError(f"D1 migration inventory drift: missing={missing} extra={extra}")


def _render(manifest: Mapping[str, Any]) -> str:
    return json.dumps(manifest, indent=2, sort_keys=False) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--write", action="store_true", help="replace frozen manifest")
    args = parser.parse_args(argv)
    rendered = _render(build_manifest())
    if args.write:
        MANIFEST.parent.mkdir(parents=True, exist_ok=True)
        MANIFEST.write_text(rendered, encoding="utf-8")
        print(MANIFEST.relative_to(ROOT))
        return 0
    if not MANIFEST.is_file() or MANIFEST.read_text(encoding="utf-8") != rendered:
        print(
            "D1 migration manifest drift; review and run "
            "scripts/cloudflare_d1_migration_manifest.py --write",
            file=sys.stderr,
        )
        return 1
    print("Cloudflare D1 migration manifest: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
