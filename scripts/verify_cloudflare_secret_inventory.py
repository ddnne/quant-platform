#!/usr/bin/env python3
"""Compare live production Worker secret names with the frozen manifest.

Only ``wrangler secret list --format json`` is used. That API returns secret
names and binding kinds; this verifier never requests, reads, or prints values.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable, Sequence


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "specs" / "cloudflare" / "active_worker_bindings.json"
WORKER_ROOT = ROOT / "platform" / "workers"


class SecretInventoryError(RuntimeError):
    """A live secret-name inventory could not be proven exact."""


def expected_secret_names(
    environment: str,
    manifest_path: Path = MANIFEST,
) -> dict[str, tuple[str, ...]]:
    if environment not in {"production", "staging"}:
        raise SecretInventoryError("secret inventory environment is invalid")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    active = manifest.get("active_workers")
    workers = manifest.get("workers")
    if not isinstance(active, list) or not active or not isinstance(workers, dict):
        raise SecretInventoryError("active Worker manifest is incomplete")
    expected: dict[str, tuple[str, ...]] = {}
    for worker in active:
        if not isinstance(worker, str) or not worker:
            raise SecretInventoryError("active Worker name is invalid")
        try:
            names = workers[worker][environment]["secret_names"]
        except (KeyError, TypeError) as exc:
            raise SecretInventoryError(
                f"{worker}: {environment} secret-name policy is missing"
            ) from exc
        if (
            not isinstance(names, list)
            or not all(isinstance(name, str) and name for name in names)
            or names != sorted(set(names))
        ):
            raise SecretInventoryError(
                f"{worker}: {environment} secret-name policy is not exact"
            )
        expected[worker] = tuple(names)
    return expected


def expected_production_secret_names(
    manifest_path: Path = MANIFEST,
) -> dict[str, tuple[str, ...]]:
    """Compatibility wrapper for the ordinary production acceptance path."""

    return expected_secret_names("production", manifest_path)


def parse_wrangler_secret_list(raw: str) -> tuple[str, ...]:
    try:
        payload: Any = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise SecretInventoryError("wrangler secret list returned invalid JSON") from exc
    if not isinstance(payload, list):
        raise SecretInventoryError("wrangler secret list did not return a list")
    names: list[str] = []
    for row in payload:
        if not isinstance(row, dict) or set(row) != {"name", "type"}:
            raise SecretInventoryError("wrangler secret list row shape drifted")
        name = row.get("name")
        kind = row.get("type")
        if not isinstance(name, str) or not name:
            raise SecretInventoryError("wrangler secret list returned an invalid name")
        if kind != "secret_text":
            raise SecretInventoryError(
                f"{name}: live binding is not a Worker secret_text"
            )
        names.append(name)
    if len(names) != len(set(names)):
        raise SecretInventoryError("wrangler secret list returned duplicate names")
    return tuple(sorted(names))


def wrangler_command(
    worker: str, *, environment: str = "production"
) -> tuple[str, ...]:
    if environment not in {"production", "staging"}:
        raise SecretInventoryError("secret inventory environment is invalid")
    executable = WORKER_ROOT / worker / "node_modules" / ".bin" / "wrangler"
    if not executable.is_file():
        raise SecretInventoryError(f"{worker}: pinned Wrangler is not installed")
    target = (
        ("--config", "wrangler.staging.toml")
        if environment == "staging"
        else ("--env", "production")
    )
    return (
        str(executable),
        "secret",
        "list",
        *target,
        "--format",
        "json",
    )


Runner = Callable[..., subprocess.CompletedProcess[str]]


def live_secret_names(
    worker: str,
    *,
    environment: str = "production",
    runner: Runner = subprocess.run,
) -> tuple[str, ...]:
    completed = runner(
        wrangler_command(worker, environment=environment),
        cwd=WORKER_ROOT / worker,
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        # Wrangler stderr can contain authentication diagnostics. Do not relay
        # arbitrary command output from a secret-management operation.
        raise SecretInventoryError(f"{worker}: wrangler secret list failed")
    return parse_wrangler_secret_list(completed.stdout)


def verify_live_secret_inventory(
    workers: Sequence[str] | None = None,
    *,
    environment: str = "production",
    manifest_path: Path = MANIFEST,
    runner: Runner = subprocess.run,
) -> list[str]:
    expected = expected_secret_names(environment, manifest_path)
    selected = list(workers) if workers is not None else list(expected)
    if not selected or any(worker not in expected for worker in selected):
        raise SecretInventoryError("requested Worker inventory is not active")
    verified: list[str] = []
    for worker in selected:
        live = live_secret_names(worker, environment=environment, runner=runner)
        policy = expected[worker]
        if live != policy:
            missing = sorted(set(policy) - set(live))
            unexpected = sorted(set(live) - set(policy))
            raise SecretInventoryError(
                f"{worker}: {environment} secret-name drift; "
                f"missing={missing!r} unexpected={unexpected!r}"
            )
        verified.append(worker)
    return verified


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--worker", action="append", dest="workers")
    parser.add_argument(
        "--environment",
        choices=("production", "staging"),
        default="production",
    )
    parser.add_argument(
        "--require-api-token",
        action="store_true",
        help="fail before any request unless CLOUDFLARE_API_TOKEN is present",
    )
    args = parser.parse_args(argv)
    if args.require_api_token and not os.environ.get("CLOUDFLARE_API_TOKEN"):
        print(
            f"CLOUDFLARE_API_TOKEN is required for {args.environment} secret acceptance",
            file=sys.stderr,
        )
        return 1
    try:
        verified = verify_live_secret_inventory(
            args.workers, environment=args.environment
        )
    except SecretInventoryError as exc:
        print(f"{args.environment} secret inventory: {exc}", file=sys.stderr)
        return 1
    print(
        f"{args.environment} secret inventory: ok "
        f"({len(verified)} active Workers; names only)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
