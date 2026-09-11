#!/usr/bin/env python3
"""Read-only acceptance of the complete Receipt authority PENDING chain.

The source-only PENDING gate proves what *would* be deployed.  This verifier
proves that the three live Workers which form the closed Receipt path are the
reviewed versions at 100% traffic and expose the exact binding/public surface:

    ingestion-secrets -> receipt-evidence-authority -> ingestion-premium

It never reads a secret value and never calls a Worker operation.  Wrangler's
version APIs return secret binding names only.  The Cloudflare API calls are
GET-only and inspect routes, custom domains, workers.dev, previews, Cron,
Logpush and tail-consumer status.  The result remains PENDING, non-positive and
research-ineligible.
"""

from __future__ import annotations

import argparse
import base64
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from typing import Any, Callable, Iterable, Mapping, NoReturn, Sequence
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.cloudflare_binding_manifest import (  # noqa: E402
    _require_pinned_local_wrangler,
    build_manifest,
)
from scripts.receipt_authority_pending_gate import (  # noqa: E402
    _require_exact_clean_source,
    validate_pending_receipt_authority,
)


CHAIN: tuple[tuple[str, str], ...] = (
    ("acquisition", "ingestion-secrets"),
    ("authority", "receipt-evidence-authority"),
    ("caller", "ingestion-premium"),
)
_ENVIRONMENTS = frozenset({"production", "staging"})
_SHA = re.compile(r"[0-9a-f]{40}\Z")
_ACCOUNT_ID = re.compile(r"[0-9a-f]{32}\Z")
_UUID = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\Z"
)
_ETAG = re.compile(r"[0-9a-f]{64}\Z")
_SHA256 = re.compile(r"sha256:[0-9a-f]{64}\Z")
_NAMESPACE_ID = re.compile(r"[0-9a-f]{32}\Z")
_MAX_JSON_BYTES = 1_048_576
_MAX_UPLOAD_BUNDLE_BYTES = 32 * 1024 * 1024
_MAX_VERSION_JSON_BYTES = 16 * 1024 * 1024
_API_BASE = "https://api.cloudflare.com/client/v4"
_ALLOWED_MODULE_CONTENT_TYPES = frozenset({
    "application/javascript+module",
    "application/javascript",
    "application/wasm",
    "application/octet-stream",
    "text/plain",
    "text/x-python",
    "text/x-python-requirement",
    "application/source-map",
})
_DISPOSITION_NAME = re.compile(
    r'(?:^|;)\s*name=(?:\"([^\"]*)\"|([^;\s]+))',
    re.IGNORECASE,
)
_DISPOSITION_FILENAME = re.compile(
    r'(?:^|;)\s*filename=(?:\"([^\"]*)\"|([^;\s]+))',
    re.IGNORECASE,
)
_MODULE_INVENTORY_FIELDS = frozenset({"name", "content_type", "bytes", "digest"})
_SOURCE_PROVENANCE_FIELDS = frozenset({"main_module", "modules"})
_OFFICIAL_ORIGIN_URLS = frozenset({
    "https://github.com/ddnne/quant-platform",
    "https://github.com/ddnne/quant-platform.git",
})
_SCRIPT_SETTING_KEYS = frozenset({
    "logpush",
    "observability",
    "tags",
    "tail_consumers",
})


class ReceiptPendingLiveAcceptanceError(RuntimeError):
    """The live Receipt PENDING chain differs from the reviewed source."""


def _reject_constant(value: str) -> NoReturn:
    raise ReceiptPendingLiveAcceptanceError(
        f"live Receipt evidence contains non-finite JSON {value!r}"
    )


def _reject_duplicates(pairs: Iterable[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ReceiptPendingLiveAcceptanceError(
                f"live Receipt evidence duplicates key {key!r}"
            )
        result[key] = value
    return result


def _load_json(
    raw: str | bytes,
    *,
    label: str,
    max_bytes: int = _MAX_JSON_BYTES,
) -> Any:
    if isinstance(raw, str):
        encoded = raw.encode("utf-8")
    else:
        encoded = raw
    if len(encoded) > max_bytes:
        raise ReceiptPendingLiveAcceptanceError(f"{label} exceeded the JSON bound")
    try:
        return json.loads(
            encoded,
            object_pairs_hook=_reject_duplicates,
            parse_constant=_reject_constant,
        )
    except ReceiptPendingLiveAcceptanceError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ReceiptPendingLiveAcceptanceError(
            f"{label} was not strict JSON"
        ) from exc


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
        raise ReceiptPendingLiveAcceptanceError(
            "live Receipt evidence is not canonical JSON"
        ) from exc
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def _environment(value: str) -> str:
    if value not in _ENVIRONMENTS:
        raise ReceiptPendingLiveAcceptanceError(
            "Receipt live environment must be production or staging"
        )
    return value


def _source_sha(value: str) -> str:
    if _SHA.fullmatch(value) is None:
        raise ReceiptPendingLiveAcceptanceError(
            "Receipt live source SHA must be a full lowercase Git SHA"
        )
    return value


def deployment_message(
    role: str,
    environment: str,
    source_sha: str,
    authority_mode: str = "PENDING",
) -> str:
    if role not in {item[0] for item in CHAIN}:
        raise ReceiptPendingLiveAcceptanceError("Receipt chain role is not closed")
    if authority_mode not in {"PENDING", "ACTIVE"}:
        raise ReceiptPendingLiveAcceptanceError("Receipt chain mode is not closed")
    return (
        f"quant-platform receipt-chain {authority_mode} {environment} "
        f"{role} source {source_sha}"
    )


def version_tag(
    role: str,
    environment: str,
    source_sha: str,
    authority_mode: str = "PENDING",
) -> str:
    if role not in {item[0] for item in CHAIN}:
        raise ReceiptPendingLiveAcceptanceError("Receipt chain role is not closed")
    environment_code = {"staging": "s", "production": "p"}[environment]
    role_code = {"acquisition": "a", "authority": "r", "caller": "c"}[role]
    # Keep the tag under Cloudflare's limit while preserving the complete
    # reviewed source identity for runtime provenance revalidation.
    mode_code = {"PENDING": "rp", "ACTIVE": "ra"}.get(authority_mode)
    if mode_code is None:
        raise ReceiptPendingLiveAcceptanceError("Receipt chain mode is not closed")
    return f"{mode_code}-{environment_code}-{role_code}-{source_sha}"


def _timestamp(value: Any, *, label: str) -> str:
    if type(value) is not str or not value.endswith("Z"):
        raise ReceiptPendingLiveAcceptanceError(f"{label} is not UTC RFC3339")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ReceiptPendingLiveAcceptanceError(
            f"{label} is not UTC RFC3339"
        ) from exc
    if parsed.tzinfo is None or parsed.utcoffset() != timezone.utc.utcoffset(parsed):
        raise ReceiptPendingLiveAcceptanceError(f"{label} is not UTC RFC3339")
    return value


def _mapping(value: Any, *, label: str) -> Mapping[str, Any]:
    if type(value) is not dict:
        raise ReceiptPendingLiveAcceptanceError(f"{label} must be an object")
    return value


def _sequence(value: Any, *, label: str) -> Sequence[Any]:
    if type(value) is not list:
        raise ReceiptPendingLiveAcceptanceError(f"{label} must be a list")
    return value


def _expected_bindings(surface: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    expected: dict[str, dict[str, Any]] = {}

    def add(row: dict[str, Any]) -> None:
        name = row["name"]
        if name in expected:
            raise ReceiptPendingLiveAcceptanceError(
                f"reviewed binding surface duplicates {name!r}"
            )
        expected[name] = row

    for name, value in sorted(surface["vars"].items()):
        add({"name": name, "text": value, "type": "plain_text"})
    for name in surface["secret_names"]:
        add({"name": name, "type": "secret_text"})
    for row in surface["d1_databases"]:
        add({
            "database_id": row["database_id"],
            "id": row["database_id"],
            "name": row["binding"],
            "type": "d1",
        })
    for row in surface["r2_buckets"]:
        add({
            "bucket_name": row["bucket_name"],
            "name": row["binding"],
            "type": "r2_bucket",
        })
    for row in surface["kv_namespaces"]:
        add({
            "name": row["binding"],
            "namespace_id": row["id"],
            "type": "kv_namespace",
        })
    for row in surface["queue_producers"]:
        add({
            "name": row["binding"],
            "queue_name": row["queue"],
            "type": "queue",
        })
    for row in surface["durable_objects"]:
        add({
            "class_name": row["class_name"],
            "name": row["name"],
            "type": "durable_object_namespace",
            "namespace_id": "<LIVE_NAMESPACE_ID>",
        })
    for row in surface["services"]:
        binding = {
            "environment": "production",
            "name": row["binding"],
            "service": row["service"],
            "type": "service",
        }
        entrypoint = row.get("entrypoint")
        if type(entrypoint) is str and entrypoint:
            binding["entrypoint"] = entrypoint
        add(binding)
    for row in surface["ratelimits"]:
        add({
            "name": row["name"],
            "namespace_id": row["namespace_id"],
            "simple": row["simple"],
            "type": "ratelimit",
        })
    ai = surface["ai"]
    if ai:
        add({"name": ai["binding"], "type": "ai"})
    version_metadata = surface["version_metadata"]
    if version_metadata:
        add({"name": version_metadata["binding"], "type": "version_metadata"})
    return expected


def _validate_bindings(
    observed_value: Any,
    *,
    surface: Mapping[str, Any],
    role: str,
) -> tuple[list[dict[str, Any]], str | None]:
    observed_rows = _sequence(observed_value, label=f"{role} live bindings")
    observed: dict[str, dict[str, Any]] = {}
    for value in observed_rows:
        row = _mapping(value, label=f"{role} live binding")
        name = row.get("name")
        if type(name) is not str or not name or name in observed:
            raise ReceiptPendingLiveAcceptanceError(
                f"{role} live binding names are invalid or duplicated"
            )
        observed[name] = dict(row)
    expected = _expected_bindings(surface)
    if set(observed) != set(expected):
        raise ReceiptPendingLiveAcceptanceError(
            f"{role} live binding-name inventory drifted"
        )
    namespace_id: str | None = None
    normalized: list[dict[str, Any]] = []
    for name in sorted(expected):
        wanted = expected[name]
        actual = observed[name]
        if wanted.get("namespace_id") == "<LIVE_NAMESPACE_ID>":
            namespace_id = actual.get("namespace_id")
            if type(namespace_id) is not str or _NAMESPACE_ID.fullmatch(namespace_id) is None:
                raise ReceiptPendingLiveAcceptanceError(
                    f"{role} Durable Object namespace identity is invalid"
                )
            wanted = {**wanted, "namespace_id": namespace_id}
        if actual != wanted:
            raise ReceiptPendingLiveAcceptanceError(
                f"{role} live binding {name!r} drifted"
            )
        normalized.append(actual)
    return normalized, namespace_id


def _expected_named_handlers(surface: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Return the complete frozen named class capability surface."""

    return [
        {"name": row["name"], "handlers": list(row["handlers"])}
        for row in (
            *surface["worker_entrypoints"],
            *surface["durable_object_class_handlers"],
        )
    ]


def _expected_migration_tag(surface: Mapping[str, Any]) -> str | None:
    """Return the final frozen Durable Object migration tag, when present."""

    migrations = surface["migrations"]
    return migrations[-1]["tag"] if migrations else None


def _validate_deployment(
    value: Any,
    *,
    role: str,
    environment: str,
    source_sha: str,
    authority_mode: str = "PENDING",
) -> tuple[str, str, str, str]:
    deployment = _mapping(value, label=f"{role} deployment")
    deployment_id = deployment.get("id")
    if type(deployment_id) is not str or _UUID.fullmatch(deployment_id) is None:
        raise ReceiptPendingLiveAcceptanceError(
            f"{role} deployment id is invalid"
        )
    if deployment.get("source") != "wrangler" or deployment.get("strategy") != "percentage":
        raise ReceiptPendingLiveAcceptanceError(
            f"{role} deployment source or strategy drifted"
        )
    created_on = _timestamp(
        deployment.get("created_on"), label=f"{role} deployment created_on"
    )
    annotations = _mapping(
        deployment.get("annotations"), label=f"{role} deployment annotations"
    )
    expected_message = deployment_message(
        role, environment, source_sha, authority_mode
    )
    if annotations.get("workers/message") != expected_message:
        raise ReceiptPendingLiveAcceptanceError(
            f"{role} deployment is not bound to the reviewed source SHA"
        )
    versions = _sequence(deployment.get("versions"), label=f"{role} deployment versions")
    if len(versions) != 1:
        raise ReceiptPendingLiveAcceptanceError(
            f"{role} deployment must route one version at 100 percent"
        )
    traffic = _mapping(versions[0], label=f"{role} deployment traffic")
    if (
        set(traffic) != {"percentage", "version_id"}
        or type(traffic["percentage"]) is not int
        or traffic["percentage"] != 100
    ):
        raise ReceiptPendingLiveAcceptanceError(
            f"{role} deployment must route one version at 100 percent"
        )
    version_id = traffic["version_id"]
    if type(version_id) is not str or _UUID.fullmatch(version_id) is None:
        raise ReceiptPendingLiveAcceptanceError(f"{role} version id is invalid")
    return deployment_id, version_id, expected_message, created_on


def _validate_version_runtime_surface(
    value: Any,
    *,
    role: str,
    version_id: str,
    surface: Mapping[str, Any],
) -> dict[str, Any]:
    """Validate immutable Worker version resources against one manifest surface."""

    version = _mapping(value, label=f"{role} version")
    if version.get("id") != version_id:
        raise ReceiptPendingLiveAcceptanceError(
            f"{role} deployment selected a different version"
        )
    metadata = _mapping(version.get("metadata"), label=f"{role} version metadata")
    if metadata.get("source") != "wrangler" or metadata.get("has_preview") is not False:
        raise ReceiptPendingLiveAcceptanceError(
            f"{role} version source or preview state drifted"
        )
    created_on = _timestamp(
        metadata.get("created_on"), label=f"{role} version created_on"
    )
    resources = _mapping(version.get("resources"), label=f"{role} resources")
    if set(resources) != {"bindings", "script", "script_runtime"}:
        raise ReceiptPendingLiveAcceptanceError(
            f"{role} live version contains an undeclared resource surface"
        )
    script = _mapping(resources.get("script"), label=f"{role} script resource")
    handlers = script.get("handlers")
    expected_handlers = ["fetch"]
    if surface["crons"]:
        expected_handlers.append("scheduled")
    if surface["queue_consumers"]:
        expected_handlers.append("queue")
    expected_named_handlers = _expected_named_handlers(surface)
    expected_script_keys = {"etag", "handlers", "last_deployed_from"}
    if expected_named_handlers:
        expected_script_keys.add("named_handlers")
    if (
        set(script) != expected_script_keys
        or handlers != expected_handlers
        or (
            expected_named_handlers
            and script.get("named_handlers") != expected_named_handlers
        )
        or script.get("last_deployed_from") != "wrangler"
        or type(script.get("etag")) is not str
        or _ETAG.fullmatch(script["etag"]) is None
    ):
        raise ReceiptPendingLiveAcceptanceError(
            f"{role} script handler, source, or etag drifted"
        )
    runtime = _mapping(
        resources.get("script_runtime"), label=f"{role} script runtime"
    )
    expected_runtime_keys = {"compatibility_date", "usage_model"}
    if surface["compatibility_flags"]:
        expected_runtime_keys.add("compatibility_flags")
    expected_migration_tag = _expected_migration_tag(surface)
    if expected_migration_tag is not None:
        expected_runtime_keys.add("migration_tag")
    if (
        set(runtime) != expected_runtime_keys
        or runtime.get("compatibility_date") != surface["compatibility_date"]
        or list(runtime.get("compatibility_flags") or [])
        != surface["compatibility_flags"]
        or runtime.get("usage_model") != "standard"
        or (
            expected_migration_tag is not None
            and runtime.get("migration_tag") != expected_migration_tag
        )
    ):
        raise ReceiptPendingLiveAcceptanceError(
            f"{role} compatibility runtime drifted"
        )
    bindings, namespace_id = _validate_bindings(
        resources.get("bindings"), surface=surface, role=role
    )
    return {
        "worker_name": surface["name"],
        "deployment_version_id": version_id,
        "version_created_on": created_on,
        # Cloudflare documents this as an opaque etag, not a local bundle hash.
        "cloudflare_script_etag": script["etag"],
        "binding_digest": _canonical_digest(bindings),
        "binding_names": [row["name"] for row in bindings],
        "secret_binding_names": sorted(surface["secret_names"]),
        "durable_object_namespace_id": namespace_id,
    }


def _validate_version(
    value: Any,
    *,
    role: str,
    environment: str,
    source_sha: str,
    version_id: str,
    surface: Mapping[str, Any],
    authority_mode: str = "PENDING",
) -> dict[str, Any]:
    version = _mapping(value, label=f"{role} version")
    annotations = _mapping(
        version.get("annotations"), label=f"{role} version annotations"
    )
    if (
        annotations.get("workers/message")
        != deployment_message(role, environment, source_sha, authority_mode)
        or annotations.get("workers/tag")
        != version_tag(role, environment, source_sha, authority_mode)
    ):
        raise ReceiptPendingLiveAcceptanceError(
            f"{role} version annotations are not source-bound"
        )
    accepted = _validate_version_runtime_surface(
        version,
        role=role,
        version_id=version_id,
        surface=surface,
    )
    accepted["version_tag"] = version_tag(
        role, environment, source_sha, authority_mode
    )
    return accepted


def _validate_public_surface(
    value: Any,
    *,
    role: str,
    surface: Mapping[str, Any],
) -> dict[str, Any]:
    public = _mapping(value, label=f"{role} public surface")
    if set(public) != {
        "custom_domain_total",
        "custom_domains",
        "routes",
        "schedules",
        "script_settings",
        "subdomain",
    }:
        raise ReceiptPendingLiveAcceptanceError(
            f"{role} public-surface evidence fields are not closed"
        )
    subdomain = _mapping(
        public.get("subdomain"), label=f"{role} workers.dev surface"
    )
    if (
        set(subdomain) != {"enabled", "previews_enabled"}
        or subdomain.get("enabled") is not surface["workers_dev"]
        or subdomain.get("previews_enabled") is not surface["preview_urls"]
    ):
        raise ReceiptPendingLiveAcceptanceError(
            f"{role} live workers.dev or preview surface drifted"
        )
    routes = _sequence(public.get("routes"), label=f"{role} routes")
    domains = _sequence(public.get("custom_domains"), label=f"{role} custom domains")
    total = public.get("custom_domain_total")
    if routes or domains or type(total) is not int or total != 0:
        raise ReceiptPendingLiveAcceptanceError(
            f"{role} has an undeclared route or custom domain"
        )
    schedule_document = _mapping(
        public.get("schedules"), label=f"{role} Cron schedule document"
    )
    if set(schedule_document) != {"schedules"}:
        raise ReceiptPendingLiveAcceptanceError(
            f"{role} Cron schedule document is not closed"
        )
    schedule_rows = _sequence(
        schedule_document.get("schedules"), label=f"{role} Cron schedules"
    )
    observed_crons: list[str] = []
    for value in schedule_rows:
        row = _mapping(value, label=f"{role} Cron schedule")
        cron = row.get("cron")
        if type(cron) is not str or not cron or cron in observed_crons:
            raise ReceiptPendingLiveAcceptanceError(
                f"{role} Cron schedule identity is invalid or duplicated"
            )
        observed_crons.append(cron)
    if sorted(observed_crons) != sorted(surface["crons"]):
        raise ReceiptPendingLiveAcceptanceError(
            f"{role} live Cron trigger surface drifted"
        )
    settings = _mapping(
        public.get("script_settings"), label=f"{role} script settings"
    )
    if not set(settings).issubset(_SCRIPT_SETTING_KEYS):
        raise ReceiptPendingLiveAcceptanceError(
            f"{role} live script settings contain an undeclared capability"
        )
    tail_consumers = settings.get("tail_consumers") or []
    tags = settings.get("tags") or []
    if (
        type(tail_consumers) is not list
        or tail_consumers != surface["tail_consumers"]
        or type(tags) is not list
        or tags
        or settings.get("logpush") not in (None, False)
    ):
        raise ReceiptPendingLiveAcceptanceError(
            f"{role} live log export or tail-consumer capability drifted"
        )
    observability = _mapping(
        settings.get("observability"), label=f"{role} observability settings"
    )
    expected_observability = surface["observability"]
    if (
        set(observability) != set(expected_observability)
        or observability.get("enabled") is not expected_observability["enabled"]
        or observability.get("head_sampling_rate")
        != expected_observability["head_sampling_rate"]
    ):
        raise ReceiptPendingLiveAcceptanceError(
            f"{role} live observability settings drifted"
        )
    return {
        "workers_dev": subdomain["enabled"],
        "preview_urls": subdomain["previews_enabled"],
        "route_count": 0,
        "custom_domain_count": 0,
        "cron_triggers": sorted(observed_crons),
        "logpush": False,
        "tail_consumer_count": 0,
        "observability_enabled": observability["enabled"],
        "observability_head_sampling_rate": observability["head_sampling_rate"],
    }


def validate_live_pending_receipt_chain(
    *,
    environment: str,
    source_sha: str,
    account_id: str,
    deployments: Mapping[str, Any],
    versions: Mapping[str, Any],
    public_surfaces: Mapping[str, Any],
    source_provenance: Mapping[str, Any],
) -> dict[str, Any]:
    """Validate already-collected GET-only live documents."""

    selected = _environment(environment)
    reviewed_sha = _source_sha(source_sha)
    if _ACCOUNT_ID.fullmatch(account_id) is None:
        raise ReceiptPendingLiveAcceptanceError(
            "Receipt live account id must be exact lowercase hexadecimal"
        )
    pending = validate_pending_receipt_authority(selected)
    manifest = build_manifest()
    roles = {role for role, _worker in CHAIN}
    if (
        set(deployments) != roles
        or set(versions) != roles
        or set(public_surfaces) != roles
        or set(source_provenance) != roles
    ):
        raise ReceiptPendingLiveAcceptanceError(
            "Receipt live chain evidence must contain exactly three roles"
        )
    accepted_workers: dict[str, Any] = {}
    for role, worker in CHAIN:
        surface = manifest["workers"][worker][selected]
        deployment_id, version_id, message, deployment_created_on = (
            _validate_deployment(
                deployments[role],
                role=role,
                environment=selected,
                source_sha=reviewed_sha,
            )
        )
        accepted = _validate_version(
            versions[role],
            role=role,
            environment=selected,
            source_sha=reviewed_sha,
            version_id=version_id,
            surface=surface,
        )
        accepted["deployment_id"] = deployment_id
        accepted["deployment_created_on"] = deployment_created_on
        accepted["deployment_message"] = message
        accepted["traffic_percent"] = 100
        provenance = _require_verified_module_inventory(
            source_provenance[role], label=f"{role} source provenance"
        )
        accepted["source_provenance"] = {
            **provenance,
            "status": "VERIFIED_EXACT_MODULE_BYTES",
        }
        accepted["public_surface"] = _validate_public_surface(
            public_surfaces[role], role=role, surface=surface
        )
        accepted_workers[role] = accepted
    return {
        "format": "receipt-authority-pending-live-acceptance/v2",
        "observed_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "environment": selected,
        "account_id": account_id,
        "source_sha": reviewed_sha,
        "source_provenance": "VERIFIED_EXACT_MODULE_BYTES",
        "authority_instance_digest": pending["authority_instance_digest"],
        "binding_manifest_raw_digest": pending["binding_manifest_raw_digest"],
        "scoped_registry_raw_digest": pending["scoped_registry_raw_digest"],
        "scoped_registry_digest": pending["scoped_registry_digest"],
        "finding_ledger_digest": pending["finding_ledger_digest"],
        "open_p0_ids": pending["open_p0_ids"],
        "workers": accepted_workers,
        "active_key_count": 0,
        "authority_mode": "PENDING",
        "positive_operation_allowed": False,
        "research_eligible": False,
        "authorization_scope": "PENDING_LIVE_ACCEPTANCE_ONLY",
    }


Runner = Callable[..., subprocess.CompletedProcess[str]]


def _isolated_command_environment(
    root: Path,
    *,
    account_id: str | None = None,
    api_token: str | None = None,
) -> dict[str, str]:
    """Return a minimum environment with a fresh credential/config home."""

    if (account_id is None) != (api_token is None):
        raise ReceiptPendingLiveAcceptanceError(
            "Cloudflare account id and API token must be supplied together"
        )
    directories = {
        "HOME": root / "isolated-home",
        "WRANGLER_HOME": root / "isolated-wrangler",
        "XDG_CACHE_HOME": root / "isolated-cache",
        "XDG_CONFIG_HOME": root / "isolated-config",
        "XDG_DATA_HOME": root / "isolated-data",
    }
    for path in directories.values():
        path.mkdir(mode=0o700, parents=True, exist_ok=False)
    environment = {
        name: os.environ[name]
        for name in ("LANG", "LC_ALL", "PATH")
        if os.environ.get(name)
    }
    environment.update({
        "CI": "true",
        "NO_COLOR": "1",
        "TMPDIR": str(root),
        "WRANGLER_SEND_METRICS": "false",
        **{name: str(path) for name, path in directories.items()},
    })
    if account_id is not None and api_token is not None:
        environment.update({
            "CLOUDFLARE_ACCOUNT_ID": account_id,
            "CLOUDFLARE_API_TOKEN": api_token,
        })
    return environment


def _require_official_origin_main(
    expected_source_sha: str,
    *,
    runner: Runner = subprocess.run,
) -> None:
    """Bind the caller-selected SHA to the official remote main branch."""

    reviewed_sha = _source_sha(expected_source_sha)
    commands = (
        ("git", "remote", "get-url", "origin"),
        ("git", "rev-parse", "--verify", "refs/remotes/origin/main^{commit}"),
    )
    results: list[subprocess.CompletedProcess[str]] = []
    for command in commands:
        try:
            completed = runner(
                command,
                cwd=ROOT,
                capture_output=True,
                text=True,
                check=False,
                timeout=30,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise ReceiptPendingLiveAcceptanceError(
                "official origin/main provenance could not be verified"
            ) from exc
        if completed.returncode != 0:
            raise ReceiptPendingLiveAcceptanceError(
                "official origin/main provenance could not be verified"
            )
        results.append(completed)
    origin_url = results[0].stdout.strip()
    local_origin_main = results[1].stdout.strip()
    if origin_url not in _OFFICIAL_ORIGIN_URLS or local_origin_main != reviewed_sha:
        raise ReceiptPendingLiveAcceptanceError(
            "reviewed source SHA is not the pinned official origin/main"
        )
    with tempfile.TemporaryDirectory(prefix="receipt-origin-main-") as temporary:
        git_environment = _isolated_command_environment(Path(temporary))
        git_environment.update({
            "GIT_ASKPASS": "/usr/bin/false",
            "GIT_CONFIG_GLOBAL": "/dev/null",
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_TERMINAL_PROMPT": "0",
        })
        try:
            remote = runner(
                (
                    "git",
                    "ls-remote",
                    "--exit-code",
                    "--refs",
                    origin_url,
                    "refs/heads/main",
                ),
                cwd=Path(temporary),
                capture_output=True,
                text=True,
                check=False,
                timeout=30,
                env=git_environment,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise ReceiptPendingLiveAcceptanceError(
                "official remote main could not be verified"
            ) from exc
    expected_row = f"{reviewed_sha}\trefs/heads/main"
    if remote.returncode != 0 or remote.stdout.strip() != expected_row:
        raise ReceiptPendingLiveAcceptanceError(
            "reviewed source SHA is not current on official remote main"
        )


def _wrangler_target(environment: str) -> tuple[str, ...]:
    return (
        ("--config", "wrangler.staging.toml")
        if environment == "staging"
        else ("--config", "wrangler.toml", "--env", "production")
    )


def _pinned_wrangler(worker: str) -> str:
    directory = ROOT / "platform" / "workers" / worker
    try:
        return _require_pinned_local_wrangler(directory)
    except ValueError as exc:
        raise ReceiptPendingLiveAcceptanceError(str(exc)) from exc


def _wrangler_json(
    *,
    worker: str,
    environment: str,
    arguments: Sequence[str],
    account_id: str,
    api_token: str,
    runner: Runner,
) -> Any:
    directory = ROOT / "platform" / "workers" / worker
    executable = _pinned_wrangler(worker)
    command = (executable, *arguments, *_wrangler_target(environment))
    with tempfile.TemporaryDirectory(prefix="receipt-wrangler-read-") as temporary:
        environment_vars = _isolated_command_environment(
            Path(temporary), account_id=account_id, api_token=api_token
        )
        try:
            completed = runner(
                command,
                cwd=directory,
                capture_output=True,
                text=True,
                check=False,
                timeout=120,
                env=environment_vars,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise ReceiptPendingLiveAcceptanceError(
                f"{worker}: read-only Wrangler inventory failed"
            ) from exc
    if completed.returncode != 0:
        # Do not relay arbitrary stderr from an authenticated command.
        raise ReceiptPendingLiveAcceptanceError(
            f"{worker}: read-only Wrangler inventory failed"
        )
    return _load_json(completed.stdout, label=f"{worker} Wrangler inventory")


def _run_wrangler_read_only(
    command: Sequence[str],
    *,
    cwd: Path,
    runner: Runner,
    environment: Mapping[str, str] | None = None,
) -> None:
    try:
        completed = runner(
            tuple(command),
            cwd=cwd,
            capture_output=True,
            text=True,
            check=False,
            timeout=120,
            **({"env": dict(environment)} if environment is not None else {}),
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise ReceiptPendingLiveAcceptanceError(
            "read-only Worker source-provenance collection failed"
        ) from exc
    if completed.returncode != 0:
        # Auth and build diagnostics can contain environment-specific details.
        raise ReceiptPendingLiveAcceptanceError(
            "read-only Worker source-provenance collection failed"
        )


def _bytes_identity(raw: bytes, *, label: str) -> tuple[str, int]:
    if type(raw) is not bytes or not raw:
        raise ReceiptPendingLiveAcceptanceError(f"{label} module is empty")
    return "sha256:" + hashlib.sha256(raw).hexdigest(), len(raw)


def _safe_module_name(name: str, *, label: str) -> str:
    if (
        type(name) is not str
        or not name
        or name in {".", "..", "metadata"}
        or Path(name).is_absolute()
        or ".." in Path(name).parts
        or "\\" in name
        or "\x00" in name
        or name.startswith("/")
        or name.startswith("./")
    ):
        raise ReceiptPendingLiveAcceptanceError(f"{label} module name is unsafe")
    return name


def _normalize_content_type(value: str, *, label: str) -> str:
    if type(value) is not str or not value.strip():
        raise ReceiptPendingLiveAcceptanceError(
            f"{label} module content type is missing"
        )
    normalized = value.split(";", 1)[0].strip().lower()
    if normalized not in _ALLOWED_MODULE_CONTENT_TYPES:
        raise ReceiptPendingLiveAcceptanceError(
            f"{label} module content type is unsupported"
        )
    return normalized


def _disposition_param(
    header: str, pattern: re.Pattern[str], *, label: str
) -> str | None:
    matches = list(pattern.finditer(header))
    if len(matches) > 1:
        raise ReceiptPendingLiveAcceptanceError(
            f"{label} disposition parameter is duplicated"
        )
    if not matches:
        return None
    match = matches[0]
    return match.group(1) if match.group(1) is not None else match.group(2)


def _parse_multipart_headers(block: bytes) -> dict[str, str]:
    if b"\0" in block:
        raise ReceiptPendingLiveAcceptanceError(
            "Worker upload bundle headers are malformed"
        )
    try:
        text = block.decode("ascii")
    except UnicodeDecodeError as exc:
        raise ReceiptPendingLiveAcceptanceError(
            "Worker upload bundle headers are malformed"
        ) from exc
    headers: dict[str, str] = {}
    for line in text.split("\r\n"):
        if not line:
            continue
        if ":" not in line:
            raise ReceiptPendingLiveAcceptanceError(
                "Worker upload bundle headers are malformed"
            )
        key, value = line.split(":", 1)
        name = key.strip().lower()
        if not name or name in headers:
            raise ReceiptPendingLiveAcceptanceError(
                "Worker upload bundle headers are malformed"
            )
        headers[name] = value.strip()
    return headers


def parse_worker_upload_bundle(raw: bytes) -> dict[str, Any]:
    """Return non-secret module facts from a pinned Wrangler --outfile body."""

    if type(raw) is not bytes or not raw:
        raise ReceiptPendingLiveAcceptanceError("Worker upload bundle is missing")
    if len(raw) > _MAX_UPLOAD_BUNDLE_BYTES:
        raise ReceiptPendingLiveAcceptanceError(
            "Worker upload bundle exceeded the finite bound"
        )
    newline = raw.find(b"\n")
    if newline < 4:
        raise ReceiptPendingLiveAcceptanceError(
            "Worker upload bundle boundary is malformed"
        )
    first_line = raw[:newline].rstrip(b"\r")
    if not first_line.startswith(b"--") or len(first_line) <= 2:
        raise ReceiptPendingLiveAcceptanceError(
            "Worker upload bundle boundary is malformed"
        )
    boundary = first_line[2:]
    if not boundary or not all(33 <= byte < 127 and byte != 34 for byte in boundary):
        raise ReceiptPendingLiveAcceptanceError(
            "Worker upload bundle boundary is malformed"
        )
    delimiter = b"--" + boundary
    chunks = raw.split(delimiter)
    if len(chunks) < 3 or chunks[0].strip(b"\r\n"):
        raise ReceiptPendingLiveAcceptanceError(
            "Worker upload bundle is not a closed multipart body"
        )
    terminator = chunks[-1]
    if not terminator.startswith(b"--") or terminator.strip(b"\r\n") != b"--":
        raise ReceiptPendingLiveAcceptanceError(
            "Worker upload bundle is not a closed multipart body"
        )
    metadata_json: bytes | None = None
    modules: dict[str, dict[str, Any]] = {}
    for chunk in chunks[1:-1]:
        payload = chunk
        if payload.startswith(b"\r\n"):
            payload = payload[2:]
        elif payload.startswith(b"\n"):
            payload = payload[1:]
        else:
            raise ReceiptPendingLiveAcceptanceError(
                "Worker upload bundle part is malformed"
            )
        if payload.endswith(b"\r\n"):
            payload = payload[:-2]
        elif payload.endswith(b"\n"):
            payload = payload[:-1]
        header_end = payload.find(b"\r\n\r\n")
        separator = 4
        if header_end < 0:
            header_end = payload.find(b"\n\n")
            separator = 2
        if header_end < 0:
            raise ReceiptPendingLiveAcceptanceError(
                "Worker upload bundle part is malformed"
            )
        headers = _parse_multipart_headers(payload[:header_end])
        body = payload[header_end + separator:]
        disposition = headers.get("content-disposition", "")
        if not disposition.lower().startswith("form-data"):
            raise ReceiptPendingLiveAcceptanceError(
                "Worker upload bundle part is not form-data"
            )
        name = _disposition_param(disposition, _DISPOSITION_NAME, label="upload")
        filename = _disposition_param(
            disposition, _DISPOSITION_FILENAME, label="upload"
        )
        if name is None:
            raise ReceiptPendingLiveAcceptanceError(
                "Worker upload bundle part is unnamed"
            )
        if name == "metadata":
            if metadata_json is not None or filename is not None:
                raise ReceiptPendingLiveAcceptanceError(
                    "Worker upload metadata part is duplicated or unsafe"
                )
            metadata_json = body
            continue
        module_name = _safe_module_name(name, label="upload")
        if filename is not None and _safe_module_name(
            filename, label="upload"
        ) != module_name:
            raise ReceiptPendingLiveAcceptanceError(
                "Worker upload module filename does not match its part name"
            )
        if module_name in modules:
            raise ReceiptPendingLiveAcceptanceError(
                "Worker upload module name is duplicated"
            )
        content_type = _normalize_content_type(
            headers.get("content-type", ""), label="upload"
        )
        digest, size = _bytes_identity(body, label="upload")
        modules[module_name] = {
            "name": module_name,
            "content_type": content_type,
            "bytes": size,
            "digest": digest,
        }
    if metadata_json is None:
        raise ReceiptPendingLiveAcceptanceError(
            "Worker upload metadata part is missing"
        )
    metadata = _mapping(
        _load_json(
            metadata_json,
            label="Worker upload metadata",
            max_bytes=_MAX_UPLOAD_BUNDLE_BYTES,
        ),
        label="Worker upload metadata",
    )
    has_main = "main_module" in metadata
    has_body = "body_part" in metadata
    if has_main == has_body:
        raise ReceiptPendingLiveAcceptanceError(
            "Worker upload must declare exactly one of main_module or body_part"
        )
    declared_raw = metadata.get("main_module") if has_main else metadata.get("body_part")
    if type(declared_raw) is not str or not declared_raw:
        raise ReceiptPendingLiveAcceptanceError(
            "Worker upload must declare exactly one of main_module or body_part"
        )
    declared = _safe_module_name(declared_raw, label="upload")
    if declared not in modules:
        raise ReceiptPendingLiveAcceptanceError(
            "Worker upload entry module is missing from the multipart inventory"
        )
    if not modules:
        raise ReceiptPendingLiveAcceptanceError("Worker upload module inventory is empty")
    return {
        "main_module": declared,
        "modules": [modules[name] for name in sorted(modules)],
    }


def _require_verified_module_inventory(value: Any, *, label: str) -> dict[str, Any]:
    document = _mapping(value, label=label)
    if set(document) != _SOURCE_PROVENANCE_FIELDS:
        raise ReceiptPendingLiveAcceptanceError(f"{label} fields are not closed")
    main_module = document.get("main_module")
    rows = document.get("modules")
    if type(main_module) is not str:
        raise ReceiptPendingLiveAcceptanceError(f"{label} main_module is missing")
    declared = _safe_module_name(main_module, label=label)
    if type(rows) is not list or not rows:
        raise ReceiptPendingLiveAcceptanceError(f"{label} module inventory is empty")
    names: list[str] = []
    normalized: list[dict[str, Any]] = []
    for row in rows:
        if type(row) is not dict or set(row) != _MODULE_INVENTORY_FIELDS:
            raise ReceiptPendingLiveAcceptanceError(
                f"{label} module row fields are not closed"
            )
        name = _safe_module_name(row["name"], label=label)
        content_type = _normalize_content_type(
            row["content_type"], label=label
        )
        digest = row["digest"]
        size = row["bytes"]
        if (
            type(digest) is not str
            or _SHA256.fullmatch(digest) is None
            or type(size) is not int
            or size <= 0
        ):
            raise ReceiptPendingLiveAcceptanceError(
                f"{label} module digest or size is malformed"
            )
        names.append(name)
        normalized.append(
            {
                "name": name,
                "content_type": content_type,
                "bytes": size,
                "digest": digest,
            }
        )
    if names != sorted(names) or len(names) != len(set(names)):
        raise ReceiptPendingLiveAcceptanceError(
            f"{label} module names are unsorted or duplicated"
        )
    if declared not in names:
        raise ReceiptPendingLiveAcceptanceError(
            f"{label} main_module is missing from the module inventory"
        )
    return {"main_module": declared, "modules": normalized}


def _live_version_module_inventory(
    *,
    account_id: str,
    worker_name: str,
    version_id: str,
    api_token: str,
    opener: Callable[..., Any] = urlopen,
) -> dict[str, Any]:
    if _ACCOUNT_ID.fullmatch(account_id) is None:
        raise ReceiptPendingLiveAcceptanceError(
            "Receipt live account id must be exact lowercase hexadecimal"
        )
    if type(worker_name) is not str or not worker_name:
        raise ReceiptPendingLiveAcceptanceError("Worker name is missing")
    if type(version_id) is not str or _UUID.fullmatch(version_id) is None:
        raise ReceiptPendingLiveAcceptanceError(
            "selected version id must be a full UUID"
        )
    if version_id in {"latest", "current"} or len(version_id) != 36:
        raise ReceiptPendingLiveAcceptanceError(
            "selected version id must be a full UUID"
        )
    account = quote(account_id, safe="")
    worker = quote(worker_name, safe="")
    version = quote(version_id, safe="")
    request = Request(
        (
            f"{_API_BASE}/accounts/{account}/workers/workers/{worker}"
            f"/versions/{version}?include=modules"
        ),
        method="GET",
        headers={
            "accept": "application/json",
            "authorization": f"Bearer {api_token}",
        },
    )
    try:
        with opener(request, timeout=30) as response:
            raw = response.read(_MAX_VERSION_JSON_BYTES + 1)
    except (HTTPError, URLError, TimeoutError, OSError) as exc:
        raise ReceiptPendingLiveAcceptanceError(
            "selected Worker version modules are unavailable"
        ) from exc
    envelope = _mapping(
        _load_json(
            raw,
            label="Worker version modules",
            max_bytes=_MAX_VERSION_JSON_BYTES,
        ),
        label="Worker version modules envelope",
    )
    if envelope.get("success") is not True or envelope.get("errors") not in ([], None):
        raise ReceiptPendingLiveAcceptanceError(
            "selected Worker version modules were unsuccessful"
        )
    result = _mapping(envelope.get("result"), label="Worker version modules result")
    if result.get("id") != version_id:
        raise ReceiptPendingLiveAcceptanceError(
            "version document id does not match selected version"
        )
    main_module = result.get("main_module")
    if type(main_module) is not str or not main_module:
        if type(result.get("body_part")) is str and result.get("body_part"):
            main_module = result["body_part"]
        else:
            raise ReceiptPendingLiveAcceptanceError(
                "selected version does not declare main_module"
            )
    declared = _safe_module_name(main_module, label="selected version")
    rows = result.get("modules")
    if type(rows) is not list or not rows:
        raise ReceiptPendingLiveAcceptanceError(
            "selected version module inventory is missing"
        )
    modules: dict[str, dict[str, Any]] = {}
    for row in rows:
        if type(row) is not dict:
            raise ReceiptPendingLiveAcceptanceError(
                "selected version module row is malformed"
            )
        name = _safe_module_name(row.get("name"), label="selected version")
        if name in modules:
            raise ReceiptPendingLiveAcceptanceError(
                "selected version module name is duplicated"
            )
        content_type = _normalize_content_type(
            row.get("content_type") if type(row.get("content_type")) is str else "",
            label="selected version",
        )
        encoded = row.get("content_base64")
        if type(encoded) is not str or not encoded:
            raise ReceiptPendingLiveAcceptanceError(
                "selected version module content is missing"
            )
        try:
            body = base64.b64decode(encoded, validate=True)
        except (ValueError, TypeError) as exc:
            raise ReceiptPendingLiveAcceptanceError(
                "selected version module content is not strict base64"
            ) from exc
        digest, size = _bytes_identity(body, label="selected version")
        modules[name] = {
            "name": name,
            "content_type": content_type,
            "bytes": size,
            "digest": digest,
        }
    if declared not in modules:
        raise ReceiptPendingLiveAcceptanceError(
            "selected version main_module is missing from the module inventory"
        )
    return {
        "id": version_id,
        "main_module": declared,
        "modules": [modules[name] for name in sorted(modules)],
    }


def _compare_module_inventories(
    local: Mapping[str, Any],
    live: Mapping[str, Any],
    *,
    label: str,
) -> dict[str, Any]:
    local_inventory = _require_verified_module_inventory(local, label=f"{label} local")
    live_inventory = _require_verified_module_inventory(
        {"main_module": live["main_module"], "modules": live["modules"]},
        label=f"{label} live",
    )
    if (
        local_inventory["main_module"] != live_inventory["main_module"]
        or local_inventory["modules"] != live_inventory["modules"]
    ):
        raise ReceiptPendingLiveAcceptanceError(
            f"{label} live module differs from the clean reviewed source build"
        )
    return live_inventory


def _source_provenance(
    *,
    worker: str,
    worker_name: str,
    environment: str,
    account_id: str,
    api_token: str,
    version_id: str,
    runner: Runner,
    opener: Callable[..., Any] = urlopen,
) -> dict[str, Any]:
    directory = ROOT / "platform" / "workers" / worker
    executable = _pinned_wrangler(worker)
    if _UUID.fullmatch(version_id) is None:
        raise ReceiptPendingLiveAcceptanceError(
            f"{worker}: selected version id must be a full UUID"
        )
    with tempfile.TemporaryDirectory(prefix="receipt-live-source-") as temporary:
        temporary_root = Path(temporary)
        outfile = temporary_root / "worker.bundle"
        # This local build must not see ambient provider credentials or a stored
        # Wrangler OAuth session.  The absolute Wrangler path only needs node
        # discoverable through PATH; all other inherited variables are omitted.
        build_environment = _isolated_command_environment(
            temporary_root / "build-environment"
        )
        _run_wrangler_read_only(
            (
                executable,
                "deploy",
                "--dry-run",
                *_wrangler_target(environment),
                "--outfile",
                str(outfile),
            ),
            cwd=directory,
            runner=runner,
            environment=build_environment,
        )
        if outfile.is_symlink() or not outfile.is_file():
            raise ReceiptPendingLiveAcceptanceError(
                f"{worker}: pinned dry-run upload bundle is absent or indirect"
            )
        try:
            local_inventory = parse_worker_upload_bundle(outfile.read_bytes())
        finally:
            try:
                outfile.unlink()
            except OSError:
                pass
        live_inventory = _live_version_module_inventory(
            account_id=account_id,
            worker_name=worker_name,
            version_id=version_id,
            api_token=api_token,
            opener=opener,
        )
        return _compare_module_inventories(
            local_inventory, live_inventory, label=worker
        )


def _api_result(
    path: str,
    *,
    api_token: str,
    opener: Callable[..., Any] = urlopen,
) -> tuple[Any, Mapping[str, Any] | None]:
    request = Request(
        _API_BASE + path,
        method="GET",
        headers={
            "accept": "application/json",
            "authorization": f"Bearer {api_token}",
        },
    )
    try:
        with opener(request, timeout=30) as response:
            raw = response.read(_MAX_JSON_BYTES + 1)
    except (HTTPError, URLError, TimeoutError, OSError) as exc:
        raise ReceiptPendingLiveAcceptanceError(
            "Cloudflare read-only public-surface inventory failed"
        ) from exc
    envelope = _mapping(
        _load_json(raw, label="Cloudflare public-surface inventory"),
        label="Cloudflare API envelope",
    )
    if envelope.get("success") is not True or envelope.get("errors") not in ([], None):
        raise ReceiptPendingLiveAcceptanceError(
            "Cloudflare read-only public-surface inventory was unsuccessful"
        )
    info = envelope.get("result_info")
    if info is not None and type(info) is not dict:
        raise ReceiptPendingLiveAcceptanceError(
            "Cloudflare public-surface pagination metadata is malformed"
        )
    return envelope.get("result"), info


def _live_public_surface(
    *,
    worker_name: str,
    account_id: str,
    api_token: str,
    opener: Callable[..., Any] = urlopen,
) -> dict[str, Any]:
    account = quote(account_id, safe="")
    worker = quote(worker_name, safe="")
    subdomain, _ = _api_result(
        f"/accounts/{account}/workers/scripts/{worker}/subdomain",
        api_token=api_token,
        opener=opener,
    )
    routes, _ = _api_result(
        f"/accounts/{account}/workers/services/{worker}/environments/production/"
        "routes?show_zonename=true",
        api_token=api_token,
        opener=opener,
    )
    query = urlencode({
        "page": 1,
        "per_page": 100,
        "service": worker_name,
        "environment": "production",
    })
    domains, info = _api_result(
        f"/accounts/{account}/workers/domains/records?{query}",
        api_token=api_token,
        opener=opener,
    )
    if info is None or type(info.get("total_count")) is not int:
        raise ReceiptPendingLiveAcceptanceError(
            "Cloudflare custom-domain total is unavailable"
        )
    schedules, _ = _api_result(
        f"/accounts/{account}/workers/scripts/{worker}/schedules",
        api_token=api_token,
        opener=opener,
    )
    script_settings, _ = _api_result(
        f"/accounts/{account}/workers/scripts/{worker}/script-settings",
        api_token=api_token,
        opener=opener,
    )
    return {
        "subdomain": subdomain,
        "routes": routes,
        "custom_domains": domains,
        "custom_domain_total": info["total_count"],
        "schedules": schedules,
        "script_settings": script_settings,
    }


def collect_live_pending_receipt_chain(
    *,
    environment: str,
    source_sha: str,
    account_id: str,
    api_token: str,
    runner: Runner = subprocess.run,
    opener: Callable[..., Any] = urlopen,
) -> dict[str, Any]:
    selected = _environment(environment)
    reviewed_sha = _source_sha(source_sha)
    if _ACCOUNT_ID.fullmatch(account_id) is None or not api_token:
        raise ReceiptPendingLiveAcceptanceError(
            "exact Cloudflare account id and API token are required"
        )
    manifest = build_manifest()
    if selected == "production" and manifest["workers"]["ingestion-secrets"][
        "production"
    ]["workers_dev"]:
        raise ReceiptPendingLiveAcceptanceError(
            "production ingestion-secrets workers.dev remains C7 HOLD until "
            "Cloudflare Access is independently provisioned and verified"
        )
    deployments: dict[str, Any] = {}
    versions: dict[str, Any] = {}
    public: dict[str, Any] = {}
    source_provenance: dict[str, Any] = {}

    # Snapshot the complete chain before downloading any Worker. Per-Worker
    # bracketing alone lets an earlier role change after its local check while a
    # later role is being inspected.
    for role, worker in CHAIN:
        deployments[role] = _wrangler_json(
            worker=worker,
            environment=selected,
            arguments=("deployments", "status", "--json"),
            account_id=account_id,
            api_token=api_token,
            runner=runner,
        )
        worker_name = manifest["workers"][worker][selected]["name"]
        public[role] = _live_public_surface(
            worker_name=worker_name,
            account_id=account_id,
            api_token=api_token,
            opener=opener,
        )

    for role, worker in CHAIN:
        traffic = _sequence(
            _mapping(deployments[role], label=f"{role} deployment").get("versions"),
            label=f"{role} deployment versions",
        )
        if len(traffic) != 1 or type(traffic[0]) is not dict:
            raise ReceiptPendingLiveAcceptanceError(
                f"{role} deployment must select one version"
            )
        version_id = traffic[0].get("version_id")
        if type(version_id) is not str or _UUID.fullmatch(version_id) is None:
            raise ReceiptPendingLiveAcceptanceError(f"{role} version id is invalid")
        versions[role] = _wrangler_json(
            worker=worker,
            environment=selected,
            arguments=("versions", "view", version_id, "--json"),
            account_id=account_id,
            api_token=api_token,
            runner=runner,
        )
        worker_name = manifest["workers"][worker][selected]["name"]
        source_provenance[role] = _source_provenance(
            worker=worker,
            worker_name=worker_name,
            environment=selected,
            account_id=account_id,
            api_token=api_token,
            version_id=version_id,
            runner=runner,
            opener=opener,
        )
        public_during = _live_public_surface(
            worker_name=worker_name,
            account_id=account_id,
            api_token=api_token,
            opener=opener,
        )
        version_after = _wrangler_json(
            worker=worker,
            environment=selected,
            arguments=("versions", "view", version_id, "--json"),
            account_id=account_id,
            api_token=api_token,
            runner=runner,
        )
        deployment_after = _wrangler_json(
            worker=worker,
            environment=selected,
            arguments=("deployments", "status", "--json"),
            account_id=account_id,
            api_token=api_token,
            runner=runner,
        )
        if _canonical_digest(deployments[role]) != _canonical_digest(deployment_after):
            raise ReceiptPendingLiveAcceptanceError(
                f"{role} deployment changed during source-provenance collection"
            )
        if _canonical_digest(versions[role]) != _canonical_digest(version_after):
            raise ReceiptPendingLiveAcceptanceError(
                f"{role} selected version changed during source-provenance collection"
            )
        if _canonical_digest(public[role]) != _canonical_digest(public_during):
            raise ReceiptPendingLiveAcceptanceError(
                f"{role} public surface changed during source-provenance collection"
            )

    # Close the whole-chain observation window. This detects an acquisition or
    # authority change that occurs after that role's local check while a later
    # Worker is still being downloaded and rebuilt.
    for role, worker in CHAIN:
        final_deployment = _wrangler_json(
            worker=worker,
            environment=selected,
            arguments=("deployments", "status", "--json"),
            account_id=account_id,
            api_token=api_token,
            runner=runner,
        )
        worker_name = manifest["workers"][worker][selected]["name"]
        version_id = _mapping(
            versions[role], label=f"{role} version"
        ).get("id")
        if type(version_id) is not str or _UUID.fullmatch(version_id) is None:
            raise ReceiptPendingLiveAcceptanceError(f"{role} version id is invalid")
        final_version = _wrangler_json(
            worker=worker,
            environment=selected,
            arguments=("versions", "view", version_id, "--json"),
            account_id=account_id,
            api_token=api_token,
            runner=runner,
        )
        final_public = _live_public_surface(
            worker_name=worker_name,
            account_id=account_id,
            api_token=api_token,
            opener=opener,
        )
        if _canonical_digest(deployments[role]) != _canonical_digest(final_deployment):
            raise ReceiptPendingLiveAcceptanceError(
                f"{role} deployment changed during whole-chain acceptance"
            )
        if _canonical_digest(versions[role]) != _canonical_digest(final_version):
            raise ReceiptPendingLiveAcceptanceError(
                f"{role} selected version changed during whole-chain acceptance"
            )
        if _canonical_digest(public[role]) != _canonical_digest(final_public):
            raise ReceiptPendingLiveAcceptanceError(
                f"{role} public surface changed during whole-chain acceptance"
            )
    return validate_live_pending_receipt_chain(
        environment=selected,
        source_sha=reviewed_sha,
        account_id=account_id,
        deployments=deployments,
        versions=versions,
        public_surfaces=public,
        source_provenance=source_provenance,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--environment", choices=("staging", "production"), required=True
    )
    parser.add_argument("--expected-source-sha", required=True)
    parser.add_argument("--expected-account-id", required=True)
    args = parser.parse_args(argv)
    api_token = os.environ.get("CLOUDFLARE_API_TOKEN", "")
    account_id = os.environ.get("CLOUDFLARE_ACCOUNT_ID", "")
    if account_id != args.expected_account_id:
        print(
            "Receipt PENDING live acceptance: FAIL: Cloudflare account id differs "
            "from the reviewed target",
            file=sys.stderr,
        )
        return 1
    try:
        _require_exact_clean_source(args.expected_source_sha)
        _require_official_origin_main(args.expected_source_sha)
        result = collect_live_pending_receipt_chain(
            environment=args.environment,
            source_sha=args.expected_source_sha,
            account_id=args.expected_account_id,
            api_token=api_token,
        )
        # Detect a clean-commit/worktree/remote-main swap during the three builds.
        _require_exact_clean_source(args.expected_source_sha)
        _require_official_origin_main(args.expected_source_sha)
    except (ReceiptPendingLiveAcceptanceError, RuntimeError, ValueError) as exc:
        print(f"Receipt PENDING live acceptance: FAIL: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
