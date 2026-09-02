#!/usr/bin/env python3
"""Authorize only the first fail-closed Receipt authority PENDING deployment.

This is deliberately not a release gate.  It validates the exact checked-in
authority identity and proves that no Receipt verification key is active.  The
ordinary all-P0 gate remains the only path to an ACTIVE authority or any
positive Receipt operation.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, NoReturn


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.cloudflare_binding_manifest import (  # noqa: E402
    MANIFEST as BINDING_MANIFEST_PATH,
    build_manifest,
)
from scripts.finding_ledger_gate import load_pinned_finding_ledger  # noqa: E402


AUTHORITY_INSTANCES_PATH = (
    ROOT
    / "packages"
    / "data_plane"
    / "data_contracts"
    / "receipt_authority_instances.json"
)
SCOPED_REGISTRY_PATHS = {
    environment: AUTHORITY_INSTANCES_PATH.with_name(
        f"receipt_verify_public_keys.{environment}.json"
    )
    for environment in ("production", "staging")
}
_ENVIRONMENTS = frozenset(SCOPED_REGISTRY_PATHS)
_SHA_RE = re.compile(r"[0-9a-f]{40}\Z")


class PendingReceiptAuthorityError(RuntimeError):
    """The requested deployment is not the exact fail-closed PENDING surface."""


def _reject_constant(value: str) -> NoReturn:
    raise PendingReceiptAuthorityError(
        f"PENDING authority evidence contains non-finite JSON {value!r}"
    )


def _reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise PendingReceiptAuthorityError(
                f"PENDING authority evidence duplicates key {key!r}"
            )
        result[key] = value
    return result


def _load_json(path: Path) -> tuple[bytes, dict[str, Any]]:
    try:
        raw = path.read_bytes()
        document = json.loads(
            raw,
            object_pairs_hook=_reject_duplicates,
            parse_constant=_reject_constant,
        )
    except PendingReceiptAuthorityError:
        raise
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PendingReceiptAuthorityError(
            f"PENDING authority contract is unreadable: {path.relative_to(ROOT)}"
        ) from exc
    if type(document) is not dict:
        raise PendingReceiptAuthorityError("PENDING authority contract must be an object")
    return raw, document


def _canonical_digest(value: Any) -> str:
    try:
        raw = json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise PendingReceiptAuthorityError(
            "PENDING authority contract is not canonical JSON"
        ) from exc
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def _require_environment(environment: str) -> str:
    if type(environment) is not str or environment not in _ENVIRONMENTS:
        raise PendingReceiptAuthorityError(
            "Receipt PENDING environment must be production or staging"
        )
    return environment


def _authority_instance(environment: str) -> tuple[dict[str, Any], str]:
    _raw, document = _load_json(AUTHORITY_INSTANCES_PATH)
    if (
        set(document) != {"schema_version", "instances"}
        or document.get("schema_version") != "receipt-authority-instances/v1"
        or type(document.get("instances")) is not dict
        or set(document["instances"]) != _ENVIRONMENTS
    ):
        raise PendingReceiptAuthorityError(
            "Receipt authority instance inventory is not closed"
        )
    instance = document["instances"].get(environment)
    if (
        type(instance) is not dict
        or set(instance) != {"environment", "authority_id", "worker_name", "resources"}
        or instance.get("environment") != environment
        or instance.get("authority_id") != "receipt-evidence-authority"
        or type(instance.get("resources")) is not dict
    ):
        raise PendingReceiptAuthorityError("Receipt authority instance identity drifted")
    return instance, _canonical_digest(instance)


def _require_zero_active_registry(
    environment: str, *, authority_instance_digest: str
) -> tuple[str, str]:
    path = SCOPED_REGISTRY_PATHS[environment]
    raw, registry = _load_json(path)
    required = {
        "schema_version",
        "purpose",
        "generation",
        "authority_status",
        "environment",
        "authority_instance_digest",
        "prior_registry_digest",
        "keys",
        "registry_digest",
    }
    keys = registry.get("keys")
    if (
        set(registry) != required
        or registry.get("schema_version") != 3
        or registry.get("purpose") != "receipt_verification"
        or registry.get("authority_status") != "PENDING"
        or registry.get("environment") != environment
        or registry.get("authority_instance_digest") != authority_instance_digest
        or type(keys) is not list
        or any(type(row) is not dict for row in keys)
        or any(row.get("status") == "active" for row in keys)
    ):
        raise PendingReceiptAuthorityError(
            "Receipt PENDING registry is active, unscoped, or malformed"
        )
    body = dict(registry)
    observed_digest = body.pop("registry_digest", None)
    if observed_digest != _canonical_digest(body):
        raise PendingReceiptAuthorityError("Receipt PENDING registry digest drifted")
    return "sha256:" + hashlib.sha256(raw).hexdigest(), str(observed_digest)


def _require_binding_surface(
    environment: str, *, instance: dict[str, Any]
) -> tuple[dict[str, Any], str]:
    raw, frozen = _load_json(BINDING_MANIFEST_PATH)
    generated = build_manifest()
    if frozen != generated:
        raise PendingReceiptAuthorityError(
            "Cloudflare binding manifest differs from the reviewed Wrangler surface"
        )
    surface = frozen["workers"]["receipt-evidence-authority"][environment]
    resources = instance["resources"]
    expected_config = (
        "platform/workers/receipt-evidence-authority/wrangler.staging.toml"
        if environment == "staging"
        else "platform/workers/receipt-evidence-authority/wrangler.toml"
    )
    expected_d1 = resources["d1"]
    expected_r2 = resources["authority_evidence_r2"]
    expected_do = resources["durable_object"]
    expected_service = resources["acquisition_service"]
    if (
        surface.get("config") != expected_config
        or surface.get("name") != instance["worker_name"]
        or surface.get("workers_dev") is not False
        or surface.get("preview_urls") is not False
        or surface.get("route") is not None
        or surface.get("routes") != []
        or surface.get("vars")
        != {
            "AUTHORITY_MODE": "PENDING",
            "ENVIRONMENT": environment,
            "RECEIPT_KEY_GENERATION": "1",
        }
        or surface.get("secret_names") != ["RECEIPT_KEY_WRAP_KEY"]
        or surface.get("d1_databases") != [expected_d1]
        or surface.get("r2_buckets")
        != [{"binding": expected_r2["binding"], "bucket_name": expected_r2["bucket_name"]}]
        or surface.get("durable_objects")
        != [{"name": expected_do["binding"], "class_name": expected_do["class_name"]}]
        or surface.get("services") != [expected_service]
    ):
        raise PendingReceiptAuthorityError(
            "Receipt PENDING Worker identity, resources, or private surface drifted"
        )
    premium = frozen["workers"]["ingestion-premium"][environment]
    if premium.get("services") != [{
        "binding": "RECEIPT_EVIDENCE_AUTHORITY",
        "entrypoint": "ReceiptAuthorityService",
        "service": instance["worker_name"],
    }]:
        raise PendingReceiptAuthorityError(
            "Receipt PENDING caller Service Binding identity drifted"
        )
    return surface, "sha256:" + hashlib.sha256(raw).hexdigest()


def validate_pending_receipt_authority(environment: str) -> dict[str, Any]:
    """Return non-secret provisioning evidence for one exact PENDING target."""

    selected = _require_environment(environment)
    instance, instance_digest = _authority_instance(selected)
    surface, binding_digest = _require_binding_surface(selected, instance=instance)
    registry_raw_digest, registry_digest = _require_zero_active_registry(
        selected, authority_instance_digest=instance_digest
    )
    ledger = load_pinned_finding_ledger()
    return {
        "format": "receipt-authority-pending-deployment-acceptance/v1",
        "environment": selected,
        "worker_name": surface["name"],
        "config": surface["config"],
        "authority_mode": "PENDING",
        "authority_instance_digest": instance_digest,
        "binding_manifest_raw_digest": binding_digest,
        "scoped_registry_raw_digest": registry_raw_digest,
        "scoped_registry_digest": registry_digest,
        "finding_ledger_digest": ledger.digest,
        "open_p0_ids": list(ledger.open_p0_ids),
        "public_surface": {
            "workers_dev": False,
            "preview_urls": False,
            "routes": [],
            "fetch_behavior": "NOT_FOUND_404",
        },
        "allowed_rpc": ["public_key_registration"],
        "forbidden_rpc": ["issue_for_segment", "recover_issue"],
        "active_key_count": 0,
        "positive_operation_allowed": False,
        "strict_release_gate_applied": False,
        "strict_release_gate_unchanged": True,
        "authorization_scope": "PENDING_PROVISIONING_ONLY",
        "pending_deployment_allowed": True,
    }


def _require_exact_clean_source(expected_source_sha: str) -> None:
    if _SHA_RE.fullmatch(expected_source_sha) is None:
        raise PendingReceiptAuthorityError("expected source SHA must be exact lowercase Git SHA")
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    status = subprocess.run(
        ["git", "status", "--porcelain=v1", "--untracked-files=all"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if (
        head.returncode != 0
        or status.returncode != 0
        or head.stdout.strip() != expected_source_sha
        or status.stdout
    ):
        raise PendingReceiptAuthorityError(
            "Receipt PENDING deployment requires the exact clean reviewed source SHA"
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--environment", choices=("staging", "production"), required=True
    )
    parser.add_argument("--expected-source-sha", required=True)
    args = parser.parse_args(argv)
    try:
        _require_exact_clean_source(args.expected_source_sha)
        result = validate_pending_receipt_authority(args.environment)
    except (PendingReceiptAuthorityError, RuntimeError, ValueError) as exc:
        print(f"Receipt PENDING deployment gate: FAIL: {exc}", file=sys.stderr)
        return 1
    result["source_sha"] = args.expected_source_sha
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
