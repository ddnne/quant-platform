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

from scripts.cloudflare_binding_manifest import build_manifest  # noqa: E402
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
_API_BASE = "https://api.cloudflare.com/client/v4"
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


def _load_json(raw: str | bytes, *, label: str) -> Any:
    if isinstance(raw, str):
        encoded = raw.encode("utf-8")
    else:
        encoded = raw
    if len(encoded) > _MAX_JSON_BYTES:
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


def deployment_message(role: str, environment: str, source_sha: str) -> str:
    if role not in {item[0] for item in CHAIN}:
        raise ReceiptPendingLiveAcceptanceError("Receipt chain role is not closed")
    return (
        f"quant-platform receipt-chain PENDING {environment} "
        f"{role} source {source_sha}"
    )


def version_tag(role: str, environment: str, source_sha: str) -> str:
    if role not in {item[0] for item in CHAIN}:
        raise ReceiptPendingLiveAcceptanceError("Receipt chain role is not closed")
    return f"receipt-pending-{environment}-{role}-{source_sha[:12]}"


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
    for row in surface["durable_objects"]:
        add({
            "class_name": row["class_name"],
            "name": row["name"],
            "type": "durable_object_namespace",
            "namespace_id": "<LIVE_NAMESPACE_ID>",
        })
    for row in surface["services"]:
        add({
            "entrypoint": row["entrypoint"],
            "environment": "production",
            "name": row["binding"],
            "service": row["service"],
            "type": "service",
        })
    for row in surface["ratelimits"]:
        add({
            "name": row["name"],
            "namespace_id": row["namespace_id"],
            "simple": row["simple"],
            "type": "ratelimit",
        })
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


def _validate_deployment(
    value: Any,
    *,
    role: str,
    environment: str,
    source_sha: str,
) -> tuple[str, str, str]:
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
    annotations = _mapping(
        deployment.get("annotations"), label=f"{role} deployment annotations"
    )
    expected_message = deployment_message(role, environment, source_sha)
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
    return deployment_id, version_id, expected_message


def _validate_version(
    value: Any,
    *,
    role: str,
    environment: str,
    source_sha: str,
    version_id: str,
    surface: Mapping[str, Any],
) -> dict[str, Any]:
    version = _mapping(value, label=f"{role} version")
    if version.get("id") != version_id:
        raise ReceiptPendingLiveAcceptanceError(
            f"{role} deployment selected a different version"
        )
    annotations = _mapping(
        version.get("annotations"), label=f"{role} version annotations"
    )
    if (
        annotations.get("workers/message")
        != deployment_message(role, environment, source_sha)
        or annotations.get("workers/tag")
        != version_tag(role, environment, source_sha)
    ):
        raise ReceiptPendingLiveAcceptanceError(
            f"{role} version annotations are not source-bound"
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
    expected_handlers = ["fetch"] + (["scheduled"] if surface["crons"] else [])
    if (
        set(script) != {"etag", "handlers", "last_deployed_from"}
        or handlers != expected_handlers
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
    if (
        set(runtime) != expected_runtime_keys
        or runtime.get("compatibility_date") != surface["compatibility_date"]
        or list(runtime.get("compatibility_flags") or [])
        != surface["compatibility_flags"]
        or runtime.get("usage_model") != "standard"
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
        "version_tag": version_tag(role, environment, source_sha),
        # Cloudflare documents this as an opaque etag, not a local bundle hash.
        "cloudflare_script_etag": script["etag"],
        "binding_digest": _canonical_digest(bindings),
        "binding_names": [row["name"] for row in bindings],
        "secret_binding_names": sorted(surface["secret_names"]),
        "durable_object_namespace_id": namespace_id,
    }


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
        deployment_id, version_id, message = _validate_deployment(
            deployments[role],
            role=role,
            environment=selected,
            source_sha=reviewed_sha,
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
        accepted["deployment_message"] = message
        accepted["traffic_percent"] = 100
        provenance = _mapping(
            source_provenance[role], label=f"{role} source provenance"
        )
        if set(provenance) != {
            "live_main_module",
            "live_main_module_bytes",
            "live_main_module_digest",
            "local_main_module",
            "local_main_module_bytes",
            "local_main_module_digest",
        }:
            raise ReceiptPendingLiveAcceptanceError(
                f"{role} source provenance fields are not closed"
            )
        local_digest = provenance.get("local_main_module_digest")
        live_digest = provenance.get("live_main_module_digest")
        local_size = provenance.get("local_main_module_bytes")
        live_size = provenance.get("live_main_module_bytes")
        if (
            type(local_digest) is not str
            or _SHA256.fullmatch(local_digest) is None
            or type(live_digest) is not str
            or _SHA256.fullmatch(live_digest) is None
            or local_digest != live_digest
            or type(local_size) is not int
            or local_size <= 0
            or type(live_size) is not int
            or live_size != local_size
            or type(provenance.get("local_main_module")) is not str
            or provenance.get("local_main_module") != "index.js"
            or type(provenance.get("live_main_module")) is not str
            or (
                provenance["live_main_module"] != "index.js"
                and not provenance["live_main_module"].endswith("/index.js")
            )
        ):
            raise ReceiptPendingLiveAcceptanceError(
                f"{role} live module differs from the clean reviewed source build"
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
        "format": "receipt-authority-pending-live-acceptance/v1",
        "observed_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "environment": selected,
        "account_id": account_id,
        "source_sha": reviewed_sha,
        "source_provenance": "VERIFIED_EXACT_MODULE_BYTES",
        "authority_instance_digest": pending["authority_instance_digest"],
        "authority_principal_manifest_digest": pending[
            "authority_principal_manifest_digest"
        ],
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
    executable = directory / "node_modules" / ".bin" / "wrangler"
    if not executable.is_file():
        raise ReceiptPendingLiveAcceptanceError(
            f"{worker}: pinned Wrangler is not installed"
        )
    command = (str(executable), *arguments, *_wrangler_target(environment))
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


def _safe_main_module(root: Path, relative: str, *, label: str) -> Path:
    if (
        type(relative) is not str
        or not relative
        or Path(relative).is_absolute()
        or ".." in Path(relative).parts
    ):
        raise ReceiptPendingLiveAcceptanceError(
            f"{label} main module path is unsafe"
        )
    candidate = root / relative
    if candidate.is_symlink() or not candidate.is_file():
        raise ReceiptPendingLiveAcceptanceError(
            f"{label} main module is absent or indirect"
        )
    resolved_root = root.resolve()
    resolved = candidate.resolve()
    if resolved.parent != resolved_root and resolved_root not in resolved.parents:
        raise ReceiptPendingLiveAcceptanceError(
            f"{label} main module escaped its temporary root"
        )
    return candidate


def _module_identity(path: Path) -> tuple[str, int]:
    raw = path.read_bytes()
    if not raw:
        raise ReceiptPendingLiveAcceptanceError("Worker main module is empty")
    return "sha256:" + hashlib.sha256(raw).hexdigest(), len(raw)


def _source_provenance(
    *,
    worker: str,
    worker_name: str,
    environment: str,
    account_id: str,
    api_token: str,
    runner: Runner,
) -> dict[str, Any]:
    directory = ROOT / "platform" / "workers" / worker
    executable = directory / "node_modules" / ".bin" / "wrangler"
    if not executable.is_file():
        raise ReceiptPendingLiveAcceptanceError(
            f"{worker}: pinned Wrangler is not installed"
        )
    with tempfile.TemporaryDirectory(prefix="receipt-live-source-") as temporary:
        temporary_root = Path(temporary)
        local_root = temporary_root / "local"
        live_root = temporary_root / "live"
        local_root.mkdir(mode=0o700)
        live_root.mkdir(mode=0o700)
        # This local build must not see ambient provider credentials or a stored
        # Wrangler OAuth session.  The absolute Wrangler path only needs node
        # discoverable through PATH; all other inherited variables are omitted.
        build_environment = _isolated_command_environment(
            temporary_root / "build-environment"
        )
        _run_wrangler_read_only(
            (
                str(executable),
                "deploy",
                "--dry-run",
                *_wrangler_target(environment),
                "--outdir",
                str(local_root),
            ),
            cwd=directory,
            runner=runner,
            environment=build_environment,
        )
        local_files = sorted(
            path.relative_to(local_root).as_posix()
            for path in local_root.rglob("*")
            if path.is_file()
            and path.name != "README.md"
            and not path.name.endswith(".map")
        )
        if local_files != ["index.js"]:
            raise ReceiptPendingLiveAcceptanceError(
                f"{worker}: local dry-run module inventory is not closed"
            )
        local_main = _safe_main_module(local_root, "index.js", label=worker)

        # The dashboard download receives only the Cloudflare account/token and
        # a fresh config home. It cannot discover the operator's Wrangler OAuth
        # session or unrelated provider/application secrets from the ambient
        # process environment.
        live_environment = _isolated_command_environment(
            temporary_root / "live-environment",
            account_id=account_id,
            api_token=api_token,
        )
        _run_wrangler_read_only(
            (
                str(executable),
                "init",
                "--from-dash",
                worker_name,
                "--yes",
                "--no-delegate-c3",
            ),
            cwd=live_root,
            runner=runner,
            environment=live_environment,
        )
        downloaded = live_root / worker_name
        config_path = downloaded / "wrangler.jsonc"
        if config_path.is_symlink() or not config_path.is_file():
            raise ReceiptPendingLiveAcceptanceError(
                f"{worker}: live downloaded config is absent or indirect"
            )
        config = _mapping(
            _load_json(config_path.read_bytes(), label=f"{worker} live config"),
            label=f"{worker} live config",
        )
        live_relative = config.get("main")
        if type(live_relative) is not str:
            raise ReceiptPendingLiveAcceptanceError(
                f"{worker}: live downloaded main module is not declared"
            )
        live_main = _safe_main_module(downloaded, live_relative, label=worker)
        downloaded_files = sorted(
            path.relative_to(downloaded).as_posix()
            for path in downloaded.rglob("*")
            if path.is_file() and path.name != "wrangler.jsonc"
        )
        if downloaded_files != [live_relative]:
            raise ReceiptPendingLiveAcceptanceError(
                f"{worker}: live module inventory contains undeclared modules"
            )
        local_digest, local_size = _module_identity(local_main)
        live_digest, live_size = _module_identity(live_main)
        if local_digest != live_digest or local_size != live_size:
            raise ReceiptPendingLiveAcceptanceError(
                f"{worker}: live module differs from the clean reviewed source build"
            )
        return {
            "local_main_module": "index.js",
            "local_main_module_digest": local_digest,
            "local_main_module_bytes": local_size,
            "live_main_module": live_relative,
            "live_main_module_digest": live_digest,
            "live_main_module_bytes": live_size,
        }


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
            runner=runner,
        )
        public_during = _live_public_surface(
            worker_name=worker_name,
            account_id=account_id,
            api_token=api_token,
            opener=opener,
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
