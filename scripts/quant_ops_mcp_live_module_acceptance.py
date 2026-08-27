#!/usr/bin/env python3
"""Read-only exact-module acceptance for the live Quant Ops MCP Worker.

The collector brackets the dashboard download with the active deployment
document.  It compares the downloaded main module with a clean local Wrangler
dry-run byte-for-byte.  The reviewed local module embeds the binding-manifest
schema and digest, so exact byte equality also binds the live bundle to the
framework RPC/dependency inventory without pretending that Cloudflare exposes
the npm lockfile itself.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
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
    deployment_before: Any,
    deployment_after: Any,
    source_provenance: Any,
) -> dict[str, Any]:
    """Validate collected GET-only deployment and exact-module evidence."""

    if environment not in {"production", "staging"}:
        raise QuantOpsMcpLiveAcceptanceError("environment is invalid")
    if _SHA.fullmatch(source_sha) is None:
        raise QuantOpsMcpLiveAcceptanceError("source SHA is invalid")
    if _ACCOUNT_ID.fullmatch(account_id) is None:
        raise QuantOpsMcpLiveAcceptanceError("Cloudflare account id is invalid")
    if _canonical_digest(deployment_before) != _canonical_digest(deployment_after):
        raise QuantOpsMcpLiveAcceptanceError(
            "deployment changed during exact-module collection"
        )
    version_id = _selected_version(deployment_before)
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
    manifest = build_manifest()
    framework = manifest["workers"]["quant-ops-mcp"][environment][
        "durable_object_class_handlers"
    ]
    if (
        len(framework) != 1
        or framework[0].get("name") != "QuantOpsMcpAgent"
        or type(framework[0].get("framework_rpc_inventory")) is not dict
    ):
        raise QuantOpsMcpLiveAcceptanceError(
            "binding manifest lacks the Quant Ops framework inventory"
        )
    return {
        "format": "quant-ops-mcp-live-module-acceptance/v1",
        "observed_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "environment": environment,
        "account_id": account_id,
        "source_sha": source_sha,
        "worker_name": manifest["workers"]["quant-ops-mcp"][environment]["name"],
        "deployment_version_id": version_id,
        "module_digest": live_digest,
        "module_bytes": live_bytes,
        "binding_manifest_schema_version": manifest["schema_version"],
        "binding_manifest_digest": manifest["manifest_digest"],
        "agents_dependency": framework[0]["framework_rpc_inventory"]["dependency"],
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
    worker = "quant-ops-mcp"
    worker_name = manifest["workers"][worker][environment]["name"]
    try:
        before = _wrangler_json(
            worker=worker,
            environment=environment,
            arguments=("deployments", "status", "--json"),
            account_id=account_id,
            api_token=api_token,
            runner=runner,
        )
        provenance = _source_provenance(
            worker=worker,
            worker_name=worker_name,
            environment=environment,
            account_id=account_id,
            api_token=api_token,
            runner=runner,
        )
        after = _wrangler_json(
            worker=worker,
            environment=environment,
            arguments=("deployments", "status", "--json"),
            account_id=account_id,
            api_token=api_token,
            runner=runner,
        )
    except ReceiptPendingLiveAcceptanceError as exc:
        raise QuantOpsMcpLiveAcceptanceError(
            "read-only Quant Ops exact-module collection failed"
        ) from exc
    return validate_live_quant_ops_module(
        environment=environment,
        source_sha=source_sha,
        account_id=account_id,
        deployment_before=before,
        deployment_after=after,
        source_provenance=provenance,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--environment", choices=("production", "staging"), required=True
    )
    parser.add_argument("--expected-source-sha", required=True)
    parser.add_argument("--expected-account-id", required=True)
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
    except (QuantOpsMcpLiveAcceptanceError, ValueError) as exc:
        print(f"Quant Ops live module acceptance: FAIL: {exc}", file=sys.stderr)
        return 1
    print(
        "Quant Ops live module acceptance: ok "
        f"({result['environment']}, {result['deployment_version_id']}, "
        f"{result['module_digest']})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
