#!/usr/bin/env python3
"""Compile a named-environment Wrangler declaration against frozen bindings.

Wrangler is the authority that renders ``Cloudflare.Env``.  The binding
manifest is the reviewed authority for which capabilities an environment may
contain.  This helper joins the two by generating a TypeScript exact-key and
assignability assertion plus an environment-specific tsconfig.
"""

from __future__ import annotations

import argparse
import json
import os
import re
from pathlib import Path
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "specs" / "cloudflare" / "active_worker_bindings.json"
WORKER_ROOT = ROOT / "platform" / "workers"
ENVIRONMENTS = ("base", "production", "staging")
_TS_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_GENERIC_ERASURE = (
    "any",
    "unknown",
    "object",
    "Fetcher",
    "Record<string, unknown>",
    "DurableObjectNamespace<any>",
    "DurableObjectNamespace",
)


def _property_name(value: Any) -> str:
    name = str(value or "")
    if not name:
        raise ValueError("binding name must be non-empty")
    return json.dumps(name)


def _literal_type(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return json.dumps(value)
    if isinstance(value, str):
        return json.dumps(value)
    raise ValueError(f"unsupported Wrangler var type: {type(value).__name__}")


def active_worker_environments() -> list[tuple[str, str]]:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    workers = manifest.get("workers") or {}
    rows: list[tuple[str, str]] = []
    for worker, environments in workers.items():
        if tuple(environments) != ENVIRONMENTS:
            raise ValueError(f"{worker}: environment set drift")
        for environment in ENVIRONMENTS:
            rows.append((str(worker), environment))
    if not rows:
        raise ValueError("active Worker Env inventory is empty")
    return rows


def _reject_generic_erasure(worker: str, environment: str, name: str, type_name: str) -> None:
    collapsed = type_name.replace(" ", "")
    if (
        type_name in _GENERIC_ERASURE
        or collapsed in {"DurableObjectNamespace<any>", "DurableObjectNamespace"}
        or type_name.endswith("<any>")
    ):
        raise ValueError(
            f"{worker}/{environment}:{name}: generic Env erasure {type_name}"
        )


def _durable_object_type(
    worker: str,
    environment: str,
    row: Mapping[str, Any],
    source_import: str,
) -> str:
    class_name = str(row.get("class_name") or "")
    if not _TS_IDENT.fullmatch(class_name):
        raise ValueError(
            f"{worker}/{environment}: Durable Object class_name is not a typed identifier"
        )
    return f'DurableObjectNamespace<import("{source_import}").{class_name}>'


def expected_types(
    worker: str,
    environment: str,
    *,
    source_import: str = "./src/index",
) -> dict[str, str]:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    try:
        surface = manifest["workers"][worker][environment]
    except (KeyError, TypeError) as exc:
        raise ValueError(f"unknown Worker environment: {worker}/{environment}") from exc

    expected: dict[str, str] = {}

    def add(name: Any, type_name: str) -> None:
        key = str(name or "")
        if not key:
            raise ValueError(f"{worker}/{environment}: empty binding name")
        if key in expected:
            raise ValueError(f"{worker}/{environment}: duplicate Env binding {key}")
        _reject_generic_erasure(worker, environment, key, type_name)
        expected[key] = type_name

    for row in surface["d1_databases"]:
        add(row.get("binding"), "D1Database")
    for row in surface["r2_buckets"]:
        add(row.get("binding"), "R2Bucket")
    for row in surface["kv_namespaces"]:
        add(row.get("binding"), "KVNamespace")
    for row in surface["queue_producers"]:
        add(row.get("binding"), "Queue")
    for row in surface["durable_objects"]:
        add(
            row.get("name"),
            _durable_object_type(worker, environment, row, source_import),
        )
    for row in surface["services"]:
        entrypoint = row.get("entrypoint")
        if entrypoint:
            if not _TS_IDENT.fullmatch(str(entrypoint)):
                raise ValueError(
                    f"{worker}/{environment}: service entrypoint is not a typed identifier"
                )
            add(row.get("binding"), "Service")
        else:
            add(row.get("binding"), "Fetcher")
    for row in surface["ratelimits"]:
        add(row.get("name"), "RateLimit")
    ai = surface.get("ai") or {}
    if ai:
        add(ai.get("binding"), "Ai")
    version_binding = (surface.get("version_metadata") or {}).get("binding")
    if version_binding:
        add(version_binding, "WorkerVersionMetadata")
    for name in surface.get("secret_names") or []:
        add(name, "string")
    for name, value in (surface.get("vars") or {}).items():
        add(name, _literal_type(value))
    return dict(sorted(expected.items()))


def render_assertion(
    worker: str,
    environment: str,
    *,
    source_import: str = "./src/index",
) -> str:
    properties = "\n".join(
        f"  readonly {_property_name(name)}: {type_name};"
        for name, type_name in expected_types(
            worker, environment, source_import=source_import
        ).items()
    )
    return f"""// Generated CI assertion; never deployed.
type ExpectedWorkerEnv = {{
{properties}
}};
type Assert<T extends true> = T;
type NoMissingBindings = Assert<
  Exclude<keyof ExpectedWorkerEnv, keyof Cloudflare.Env> extends never ? true : false
>;
type NoUnexpectedBindings = Assert<
  Exclude<keyof Cloudflare.Env, keyof ExpectedWorkerEnv> extends never ? true : false
>;
type CompatibleBindingTypes = Assert<
  Cloudflare.Env extends ExpectedWorkerEnv ? true : false
>;
"""


def write_check(
    *,
    worker: str,
    environment: str,
    generated_types: Path,
    assertion: Path,
    tsconfig: Path,
) -> None:
    worker_dir = WORKER_ROOT / worker
    base_tsconfig = worker_dir / "tsconfig.json"
    if not generated_types.is_file() or not base_tsconfig.is_file():
        raise ValueError("generated declaration and Worker tsconfig must exist")
    raw = generated_types.read_text(encoding="utf-8")
    if "interface __BaseEnv_Env {" not in raw or "interface Env extends __BaseEnv_Env" not in raw:
        raise ValueError("Wrangler declaration does not contain a generated Env surface")
    if "DurableObjectNamespace<any>" in raw.replace(" ", ""):
        raise ValueError("generated Env erased a Durable Object class parameter")
    relative_source = os.path.relpath(
        worker_dir / "src" / "index", assertion.parent
    ).replace(os.sep, "/")
    source_import = (
        relative_source if relative_source.startswith(".") else f"./{relative_source}"
    )
    expected = expected_types(
        worker, environment, source_import=source_import
    )
    if any(type_name == "Service" for type_name in expected.values()) and re.search(
        r":\s*Fetcher\b", raw
    ):
        raise ValueError("generated Env erased a typed Service binding to Fetcher")

    assertion.write_text(
        render_assertion(worker, environment, source_import=source_import),
        encoding="utf-8",
    )
    config = {
        "extends": str(base_tsconfig),
        "compilerOptions": {
            "noEmit": True,
            "skipLibCheck": False,
            # The generated tsconfig lives in a CI temp directory, so make the
            # Worker's pinned packages (including @cloudflare/workers-types)
            # the explicit type-resolution root.
            "typeRoots": [str(worker_dir / "node_modules")],
        },
        "files": [str(generated_types), str(assertion)],
        "include": [
            str(worker_dir / "src" / "**" / "*.ts"),
            str(worker_dir / "src" / "**" / "*.js"),
            str(worker_dir / "src" / "**" / "*.d.ts"),
        ],
        "exclude": [
            str(worker_dir / "src" / "**" / "*.test.ts"),
            str(worker_dir / "src" / "**" / "*.test.js"),
            str(worker_dir / "src" / "test-setup.ts"),
            str(worker_dir / "node_modules"),
        ],
    }
    tsconfig.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--list-environments", action="store_true")
    parser.add_argument("--worker")
    parser.add_argument("--environment", choices=ENVIRONMENTS)
    parser.add_argument("--generated-types", type=Path)
    parser.add_argument("--assertion", type=Path)
    parser.add_argument("--tsconfig", type=Path)
    args = parser.parse_args()
    if args.list_environments:
        print("\n".join(ENVIRONMENTS))
        return 0
    required = {
        "worker": args.worker,
        "environment": args.environment,
        "generated_types": args.generated_types,
        "assertion": args.assertion,
        "tsconfig": args.tsconfig,
    }
    missing = [name for name, value in required.items() if value is None]
    if missing:
        parser.error("missing required arguments: " + ", ".join(missing))
    write_check(
        worker=args.worker,
        environment=args.environment,
        generated_types=args.generated_types,
        assertion=args.assertion,
        tsconfig=args.tsconfig,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
