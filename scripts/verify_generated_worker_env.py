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
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "specs" / "cloudflare" / "active_worker_bindings.json"
WORKER_ROOT = ROOT / "platform" / "workers"


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


def expected_types(worker: str, environment: str) -> dict[str, str]:
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
        add(row.get("name"), "DurableObjectNamespace<any>")
    for row in surface["services"]:
        add(row.get("binding"), "Fetcher")
    for row in surface["ratelimits"]:
        add(row.get("name"), "RateLimit")
    ai = surface.get("ai") or {}
    if ai:
        add(ai.get("binding"), "Ai")
    for name, value in (surface.get("vars") or {}).items():
        add(name, _literal_type(value))
    return dict(sorted(expected.items()))


def render_assertion(worker: str, environment: str) -> str:
    properties = "\n".join(
        f"  readonly {_property_name(name)}: {type_name};"
        for name, type_name in expected_types(worker, environment).items()
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

    assertion.write_text(render_assertion(worker, environment), encoding="utf-8")
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
    parser.add_argument("--worker", required=True)
    parser.add_argument("--environment", choices=("production", "staging"), required=True)
    parser.add_argument("--generated-types", type=Path, required=True)
    parser.add_argument("--assertion", type=Path, required=True)
    parser.add_argument("--tsconfig", type=Path, required=True)
    args = parser.parse_args()
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
