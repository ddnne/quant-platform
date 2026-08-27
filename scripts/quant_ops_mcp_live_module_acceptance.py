#!/usr/bin/env python3
"""Read-only capability-surface acceptance for the live Quant Ops MCP Worker.

The collector brackets the dashboard download with every active Worker's
deployment and immutable selected-version document.  It compares every live
runtime/binding surface with the reviewed manifest and the downloaded Quant Ops
main module with a clean local Wrangler dry-run byte-for-byte.  The reviewed
local module embeds the binding-manifest schema and digest, so exact byte
equality also binds the live bundle to the framework RPC/dependency inventory
without pretending that Cloudflare exposes the npm lockfile itself.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.cloudflare_binding_manifest import build_manifest  # noqa: E402
from scripts.receipt_authority_pending_gate import (  # noqa: E402
    _require_exact_clean_source,
)
from scripts.receipt_authority_pending_live_acceptance import (  # noqa: E402
    ReceiptPendingLiveAcceptanceError,
    _canonical_digest,
    _require_official_origin_main,
    _source_provenance,
    _validate_version_runtime_surface,
    _wrangler_json,
)


_SHA = re.compile(r"[0-9a-f]{40}\Z")
_ACCOUNT_ID = re.compile(r"[0-9a-f]{32}\Z")
_UUID = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\Z"
)
_DIGEST = re.compile(r"sha256:[0-9a-f]{64}\Z")
_PROVENANCE_FIELDS = {
    "live_main_module",
    "live_main_module_bytes",
    "live_main_module_digest",
    "local_main_module",
    "local_main_module_bytes",
    "local_main_module_digest",
}


class QuantOpsMcpLiveAcceptanceError(RuntimeError):
    """The live Quant Ops module is not the reviewed exact bundle."""


def _selected_version(document: Any) -> str:
    if type(document) is not dict:
        raise QuantOpsMcpLiveAcceptanceError("deployment document must be an object")
    versions = document.get("versions")
    if type(versions) is not list or len(versions) != 1:
        raise QuantOpsMcpLiveAcceptanceError(
            "deployment must select exactly one version"
        )
    row = versions[0]
    if (
        type(row) is not dict
        or set(row) != {"percentage", "version_id"}
        or type(row["percentage"]) is not int
        or row["percentage"] != 100
        or type(row["version_id"]) is not str
        or _UUID.fullmatch(row["version_id"]) is None
    ):
        raise QuantOpsMcpLiveAcceptanceError(
            "deployment must route one UUID version at 100 percent"
        )
    return row["version_id"]


def validate_live_quant_ops_module(
    *,
    environment: str,
    source_sha: str,
    account_id: str,
    deployments_before: Any,
    deployments_after: Any,
    versions_before: Any,
    versions_after: Any,
    source_provenance: Any,
) -> dict[str, Any]:
    """Validate GET-only deployment, selected version, and module evidence."""

    if environment not in {"production", "staging"}:
        raise QuantOpsMcpLiveAcceptanceError("environment is invalid")
    if _SHA.fullmatch(source_sha) is None:
        raise QuantOpsMcpLiveAcceptanceError("source SHA is invalid")
    if _ACCOUNT_ID.fullmatch(account_id) is None:
        raise QuantOpsMcpLiveAcceptanceError("Cloudflare account id is invalid")
    manifest = build_manifest()
    active_workers = tuple(manifest["active_workers"])
    for label, value in {
        "deployment before": deployments_before,
        "deployment after": deployments_after,
        "version before": versions_before,
        "version after": versions_after,
    }.items():
        if type(value) is not dict or set(value) != set(active_workers):
            raise QuantOpsMcpLiveAcceptanceError(
                f"{label} inventory must contain every active Worker exactly"
            )

    version_ids: dict[str, str] = {}
    for worker in active_workers:
        if _canonical_digest(deployments_before[worker]) != _canonical_digest(
            deployments_after[worker]
        ):
            raise QuantOpsMcpLiveAcceptanceError(
                f"{worker}: deployment changed during exact-module collection"
            )
        try:
            version_ids[worker] = _selected_version(deployments_before[worker])
        except QuantOpsMcpLiveAcceptanceError as exc:
            raise QuantOpsMcpLiveAcceptanceError(f"{worker}: {exc}") from exc
        if _canonical_digest(versions_before[worker]) != _canonical_digest(
            versions_after[worker]
        ):
            raise QuantOpsMcpLiveAcceptanceError(
                f"{worker}: selected version changed during exact-module collection"
            )

    quant_worker_name = manifest["workers"]["quant-ops-mcp"][environment]["name"]
    for worker in active_workers:
        if worker == "quant-ops-mcp":
            continue
        version = versions_before[worker]
        resources = version.get("resources") if type(version) is dict else None
        bindings = resources.get("bindings") if type(resources) is dict else None
        if type(bindings) is not list:
            continue
        for binding in bindings:
            if type(binding) is not dict:
                continue
            if (
                binding.get("type") == "service"
                and binding.get("service") == quant_worker_name
            ) or (
                binding.get("type") == "durable_object_namespace"
                and (
                    binding.get("script_name") == quant_worker_name
                    or binding.get("class_name") == "QuantOpsMcpAgent"
                    or binding.get("name") == "MCP_OBJECT"
                )
            ):
                raise QuantOpsMcpLiveAcceptanceError(
                    f"{worker}: live binding distributes a Quant Ops capability"
                )
    if type(source_provenance) is not dict or set(source_provenance) != _PROVENANCE_FIELDS:
        raise QuantOpsMcpLiveAcceptanceError("module provenance fields are not closed")
    local_digest = source_provenance["local_main_module_digest"]
    live_digest = source_provenance["live_main_module_digest"]
    local_bytes = source_provenance["local_main_module_bytes"]
    live_bytes = source_provenance["live_main_module_bytes"]
    live_module = source_provenance["live_main_module"]
    if (
        source_provenance["local_main_module"] != "index.js"
        or type(live_module) is not str
        or (live_module != "index.js" and not live_module.endswith("/index.js"))
        or type(local_digest) is not str
        or _DIGEST.fullmatch(local_digest) is None
        or live_digest != local_digest
        or type(local_bytes) is not int
        or local_bytes <= 0
        or type(live_bytes) is not int
        or live_bytes != local_bytes
    ):
        raise QuantOpsMcpLiveAcceptanceError(
            "live module differs from the clean reviewed source build"
        )
    surface = manifest["workers"]["quant-ops-mcp"][environment]
    framework = surface["durable_object_class_handlers"]
    if (
        len(framework) != 1
        or framework[0].get("name") != "QuantOpsMcpAgent"
        or type(framework[0].get("framework_rpc_inventory")) is not dict
    ):
        raise QuantOpsMcpLiveAcceptanceError(
            "binding manifest lacks the Quant Ops framework inventory"
        )
    accepted_versions: dict[str, dict[str, Any]] = {}
    for worker in active_workers:
        try:
            accepted_versions[worker] = _validate_version_runtime_surface(
                versions_before[worker],
                role=worker,
                version_id=version_ids[worker],
                surface=manifest["workers"][worker][environment],
            )
        except ReceiptPendingLiveAcceptanceError as exc:
            raise QuantOpsMcpLiveAcceptanceError(
                f"{worker}: selected version surface drifted: {exc}"
            ) from exc
    accepted_version = accepted_versions["quant-ops-mcp"]
    return {
        "format": "quant-ops-mcp-live-module-acceptance/v1",
        "observed_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "environment": environment,
        "account_id": account_id,
        "source_sha": source_sha,
        "worker_name": surface["name"],
        "deployment_version_id": version_ids["quant-ops-mcp"],
        "version_created_on": accepted_version["version_created_on"],
        "cloudflare_script_etag": accepted_version["cloudflare_script_etag"],
        "binding_digest": accepted_version["binding_digest"],
        "binding_names": accepted_version["binding_names"],
        "durable_object_namespace_id": accepted_version[
            "durable_object_namespace_id"
        ],
        "module_digest": live_digest,
        "module_bytes": live_bytes,
        "binding_manifest_schema_version": manifest["schema_version"],
        "binding_manifest_digest": manifest["manifest_digest"],
        "agents_dependency": framework[0]["framework_rpc_inventory"]["dependency"],
        "active_version_surfaces": {
            worker: {
                "worker_name": accepted_versions[worker]["worker_name"],
                "deployment_version_id": accepted_versions[worker][
                    "deployment_version_id"
                ],
                "version_created_on": accepted_versions[worker][
                    "version_created_on"
                ],
                "cloudflare_script_etag": accepted_versions[worker][
                    "cloudflare_script_etag"
                ],
                "binding_digest": accepted_versions[worker]["binding_digest"],
                "binding_names": accepted_versions[worker]["binding_names"],
                "durable_object_namespace_id": accepted_versions[worker][
                    "durable_object_namespace_id"
                ],
                "deployment_bracket_before_digest": _canonical_digest(
                    deployments_before[worker]
                ),
                "deployment_bracket_after_digest": _canonical_digest(
                    deployments_after[worker]
                ),
                "version_bracket_before_digest": _canonical_digest(
                    versions_before[worker]
                ),
                "version_bracket_after_digest": _canonical_digest(
                    versions_after[worker]
                ),
            }
            for worker in active_workers
        },
        "status": "VERIFIED_EXACT_MODULE_BYTES",
    }


def collect_live_quant_ops_module(
    *,
    environment: str,
    source_sha: str,
    account_id: str,
    api_token: str,
    runner: Any = subprocess.run,
) -> dict[str, Any]:
    if environment not in {"production", "staging"}:
        raise QuantOpsMcpLiveAcceptanceError("environment is invalid")
    if _ACCOUNT_ID.fullmatch(account_id) is None or not api_token:
        raise QuantOpsMcpLiveAcceptanceError(
            "exact Cloudflare account id and API token are required"
        )
    manifest = build_manifest()
    active_workers = tuple(manifest["active_workers"])
    quant_worker = "quant-ops-mcp"
    worker_name = manifest["workers"][quant_worker][environment]["name"]
    deployments_before: dict[str, Any] = {}
    deployments_after: dict[str, Any] = {}
    versions_before: dict[str, Any] = {}
    versions_after: dict[str, Any] = {}
    try:
        for worker in active_workers:
            deployments_before[worker] = _wrangler_json(
                worker=worker,
                environment=environment,
                arguments=("deployments", "status", "--json"),
                account_id=account_id,
                api_token=api_token,
                runner=runner,
            )
        for worker in active_workers:
            version_id = _selected_version(deployments_before[worker])
            versions_before[worker] = _wrangler_json(
                worker=worker,
                environment=environment,
                arguments=("versions", "view", version_id, "--json"),
                account_id=account_id,
                api_token=api_token,
                runner=runner,
            )
        provenance = _source_provenance(
            worker=quant_worker,
            worker_name=worker_name,
            environment=environment,
            account_id=account_id,
            api_token=api_token,
            runner=runner,
        )
        for worker in active_workers:
            version_id = _selected_version(deployments_before[worker])
            versions_after[worker] = _wrangler_json(
                worker=worker,
                environment=environment,
                arguments=("versions", "view", version_id, "--json"),
                account_id=account_id,
                api_token=api_token,
                runner=runner,
            )
        for worker in active_workers:
            deployments_after[worker] = _wrangler_json(
                worker=worker,
                environment=environment,
                arguments=("deployments", "status", "--json"),
                account_id=account_id,
                api_token=api_token,
                runner=runner,
            )
    except (ReceiptPendingLiveAcceptanceError, QuantOpsMcpLiveAcceptanceError) as exc:
        raise QuantOpsMcpLiveAcceptanceError(
            "read-only Quant Ops exact-module collection failed"
        ) from exc
    return validate_live_quant_ops_module(
        environment=environment,
        source_sha=source_sha,
        account_id=account_id,
        deployments_before=deployments_before,
        deployments_after=deployments_after,
        versions_before=versions_before,
        versions_after=versions_after,
        source_provenance=provenance,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--environment", choices=("production", "staging"), required=True
    )
    parser.add_argument("--expected-source-sha", required=True)
    parser.add_argument("--expected-account-id", required=True)
    parser.add_argument(
        "--json",
        action="store_true",
        help="emit canonical JSON suitable for immutable release evidence intake",
    )
    args = parser.parse_args(argv)
    if os.environ.get("CLOUDFLARE_ACCOUNT_ID", "") != args.expected_account_id:
        print("Quant Ops live module acceptance: FAIL: account id drift", file=sys.stderr)
        return 1
    try:
        _require_exact_clean_source(args.expected_source_sha)
        _require_official_origin_main(args.expected_source_sha)
        result = collect_live_quant_ops_module(
            environment=args.environment,
            source_sha=args.expected_source_sha,
            account_id=args.expected_account_id,
            api_token=os.environ.get("CLOUDFLARE_API_TOKEN", ""),
        )
        # The local dry-run and the live downloads above can take long enough
        # for HEAD, the worktree, or origin/main to change. Revalidate after the
        # complete observation window before reporting acceptance.
        _require_exact_clean_source(args.expected_source_sha)
        _require_official_origin_main(args.expected_source_sha)
    except (RuntimeError, ValueError, OSError, subprocess.SubprocessError) as exc:
        print(f"Quant Ops live module acceptance: FAIL: {exc}", file=sys.stderr)
        return 1
    if args.json:
        print(
            json.dumps(
                result,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=True,
                allow_nan=False,
            )
        )
    else:
        print(
            "Quant Ops live module acceptance: ok "
            f"({result['environment']}, {result['deployment_version_id']}, "
            f"{result['module_digest']})"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
