#!/usr/bin/env python3
"""Authenticated staging JSDA AUDIT_ONLY intake; local stage is not A6 close.

Caller-supplied JSON is untrusted. The pinned all-P0 finding-ledger gate runs
first. Staging intake GETs the existing observer JSDA health-ready path after
Access host/AUD and observer plus JSDA version/binding/module-byte checks.
The digest-named file is STAGED_LOCAL_NOT_PUBLISHED / AUDIT_ONLY /
release_allowed=false. Eventual remote publication is a GitHub Release asset
plus independent exact-byte readback; this CLI does not publish or mark A6
FIXED.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable, Mapping, NoReturn
from urllib.error import HTTPError, URLError
from urllib.request import Request

try:
    from scripts.finding_ledger_gate import (
        FindingLedgerError,
        require_pinned_finding_ledger_gate,
    )
except ModuleNotFoundError:  # Direct ``python scripts/...`` execution.
    from finding_ledger_gate import (  # type: ignore[no-redef]
        FindingLedgerError,
        require_pinned_finding_ledger_gate,
    )

_JSDA_PATH = "/v1/private/jsda-health-ready"
_JSDA_OBSERVATION_KEYS = frozenset(
    {
        "access_aud",
        "binding_name",
        "collector",
        "eligibility",
        "endpoint",
        "exact_response_b64",
        "exact_response_bytes",
        "exact_response_utf8",
        "http_status",
        "observer_source_sha",
        "observer_worker_version_id",
        "observer_worker_version_tag",
        "response_digest",
        "schema_version",
        "transport",
    }
)
_MAX_JSDA_HEALTH_BYTES = 8 * 1024
_OBSERVED_WORKERS = (
    ("observer", "receipt-activation-observer"),
    ("jsda", "ingestion-jsda"),
)


class ReleaseObservationAuthorityUnavailable(RuntimeError):
    """Trusted remote observations cannot yet be minted or published."""


def _refuse_publication() -> NoReturn:
    raise ReleaseObservationAuthorityUnavailable(
        "release evidence publication is PENDING: authenticated "
        "collection/publication implementation is missing; caller-supplied "
        "JSON is untrusted"
    )


def build_envelope(payload: Mapping[str, Any]) -> dict[str, Any]:
    del payload
    _refuse_publication()


def write_envelope(payload: Mapping[str, Any], output_dir: Path) -> NoReturn:
    del payload, output_dir
    _refuse_publication()


def _intake():
    try:
        from scripts import cloudflare_binding_manifest as bindings
        from scripts import receipt_authority_pending_gate as pending_gate
        from scripts import receipt_authority_pending_live_acceptance as live
        from scripts import receipt_authority_staging_active_gate as staging
    except ModuleNotFoundError:
        import cloudflare_binding_manifest as bindings
        import receipt_authority_pending_gate as pending_gate
        import receipt_authority_pending_live_acceptance as live
        import receipt_authority_staging_active_gate as staging
    return bindings, pending_gate, live, staging


def _wrap(exc: BaseException) -> NoReturn:
    raise ReleaseObservationAuthorityUnavailable(str(exc)) from exc


def _selected_version_id(deployment: Any, *, label: str, live: Any) -> str:
    document = live._mapping(deployment, label=f"{label} deployment")
    versions = live._sequence(
        document.get("versions"), label=f"{label} deployment versions"
    )
    if len(versions) != 1 or type(versions[0]) is not dict:
        raise ReleaseObservationAuthorityUnavailable(
            f"{label} deployment must select one version"
        )
    version_id = versions[0].get("version_id")
    percentage = versions[0].get("percentage")
    if (
        type(version_id) is not str
        or live._UUID.fullmatch(version_id) is None
        or percentage != 100
    ):
        raise ReleaseObservationAuthorityUnavailable(
            f"{label} deployment must route one version at 100 percent"
        )
    return version_id


def _get_jsda_observation(
    *,
    endpoint_url: str,
    client_id: str,
    client_secret: str,
    opener: Callable[..., Any],
    max_bytes: int,
) -> bytes:
    url = endpoint_url.rstrip("/") + _JSDA_PATH
    probe = Request(url, method="GET", headers={"accept": "application/json"})
    try:
        with opener(probe, timeout=30) as response:
            response.read(max_bytes + 1)
            raise ReleaseObservationAuthorityUnavailable(
                "JSDA observer accepted an unauthenticated request"
            )
    except HTTPError as exc:
        exc.read(max_bytes + 1)
        if type(exc.code) is not int or exc.code not in {401, 403}:
            raise ReleaseObservationAuthorityUnavailable(
                "JSDA observer unauthenticated rejection drifted"
            ) from exc
        if exc.headers.get("location") is not None:
            raise ReleaseObservationAuthorityUnavailable(
                "JSDA observer unauthenticated rejection drifted"
            ) from exc
    except ReleaseObservationAuthorityUnavailable:
        raise
    except (URLError, TimeoutError, OSError) as exc:
        raise ReleaseObservationAuthorityUnavailable(
            "JSDA observer unauthenticated probe failed"
        ) from exc
    authenticated = Request(
        url,
        method="GET",
        headers={
            "accept": "application/json",
            "CF-Access-Client-Id": client_id,
            "CF-Access-Client-Secret": client_secret,
        },
    )
    try:
        with opener(authenticated, timeout=30) as response:
            raw = response.read(max_bytes + 1)
            headers = response.headers
            code = response.getcode()
            if (
                type(code) is not int
                or code != 200
                or response.geturl() != url
                or headers.get("location") is not None
                or not str(headers.get("content-type") or "").lower().startswith(
                    "application/json"
                )
                or headers.get("cache-control") != "no-store"
            ):
                raise ReleaseObservationAuthorityUnavailable(
                    "JSDA observer authenticated response metadata drifted"
                )
    except ReleaseObservationAuthorityUnavailable:
        raise
    except (HTTPError, URLError, TimeoutError, OSError) as exc:
        raise ReleaseObservationAuthorityUnavailable(
            "JSDA observer authenticated request failed"
        ) from exc
    if type(raw) is not bytes or len(raw) > max_bytes:
        raise ReleaseObservationAuthorityUnavailable(
            "JSDA observer response is oversized"
        )
    return raw


def _require_observation(
    raw: bytes,
    *,
    source_sha: str,
    version_id: str,
    access_aud: str,
    live: Any,
    observer_tag: str,
    max_bytes: int,
) -> dict[str, Any]:
    observation = live._load_json(raw, label="JSDA observation", max_bytes=max_bytes)
    if type(observation) is not dict or set(observation) != _JSDA_OBSERVATION_KEYS:
        raise ReleaseObservationAuthorityUnavailable(
            "JSDA observation schema drifted"
        )
    status = observation.get("http_status")
    if (
        observation.get("schema_version") != "quant-platform-release-observation/v2"
        or observation.get("collector") != "private-jsda-health-ready/v1"
        or observation.get("transport") != "private-service-binding"
        or observation.get("binding_name") != "JSDA_INGESTION"
        or observation.get("endpoint") != "/health/ready"
        or observation.get("eligibility") != "AUDIT_ONLY"
        or observation.get("observer_source_sha") != source_sha
        or observation.get("observer_worker_version_id") != version_id
        or observation.get("observer_worker_version_tag") != observer_tag
        or observation.get("access_aud") != access_aud
        or type(status) is not int
        or status < 100
        or status > 599
        or type(observation.get("exact_response_b64")) is not str
        or type(observation.get("exact_response_utf8")) is not str
        or type(observation.get("exact_response_bytes")) is not int
        or type(observation.get("response_digest")) is not str
    ):
        raise ReleaseObservationAuthorityUnavailable(
            "JSDA observation provenance drifted"
        )
    try:
        inner = base64.b64decode(observation["exact_response_b64"], validate=True)
        text = inner.decode("utf-8")
    except (ValueError, TypeError, UnicodeDecodeError) as exc:
        raise ReleaseObservationAuthorityUnavailable(
            "JSDA observation exact bytes are invalid"
        ) from exc
    digest = "sha256:" + hashlib.sha256(inner).hexdigest()
    if (
        not inner
        or len(inner) > _MAX_JSDA_HEALTH_BYTES
        or len(inner) != observation["exact_response_bytes"]
        or text != observation["exact_response_utf8"]
        or digest != observation["response_digest"]
    ):
        raise ReleaseObservationAuthorityUnavailable(
            "JSDA observation exact bytes drifted"
        )
    return observation


def _measure_selected(
    *,
    sha: str,
    account: str,
    token: str,
    runner: Callable[..., Any],
    live: Any,
    staging: Any,
    bindings: Any,
) -> dict[str, Any]:
    workers = bindings.build_manifest()["workers"]
    measured: dict[str, Any] = {}
    for role, worker in _OBSERVED_WORKERS:
        surface = workers[worker]["staging"]
        deployment = live._wrangler_json(
            worker=worker,
            environment="staging",
            arguments=("deployments", "status", "--json"),
            account_id=account,
            api_token=token,
            runner=runner,
        )
        if role == "observer":
            _deployment_id, version_id, _message, _created = (
                staging._validate_observer_deployment(deployment, source_sha=sha)
            )
        else:
            version_id = _selected_version_id(deployment, label=role, live=live)
        version = live._wrangler_json(
            worker=worker,
            environment="staging",
            arguments=("versions", "view", version_id, "--json"),
            account_id=account,
            api_token=token,
            runner=runner,
        )
        if role == "observer":
            accepted = staging._validate_observer_version(
                version,
                source_sha=sha,
                version_id=version_id,
                surface=surface,
            )
        else:
            accepted = live._validate_version_runtime_surface(
                version,
                role=role,
                version_id=version_id,
                surface=surface,
            )
        measured[role] = {
            "accepted": accepted,
            "deployment": deployment,
            "surface": surface,
            "version": version,
            "version_id": version_id,
            "worker": worker,
        }
    return measured


def _match_modules(
    measured: Mapping[str, Any],
    *,
    account: str,
    token: str,
    runner: Callable[..., Any],
    opener: Callable[..., Any],
    live: Any,
) -> None:
    for role, _worker in _OBSERVED_WORKERS:
        row = measured[role]
        row["provenance"] = live._source_provenance(
            worker=row["worker"],
            worker_name=row["surface"]["name"],
            environment="staging",
            account_id=account,
            api_token=token,
            version_id=row["version_id"],
            runner=runner,
            opener=opener,
        )


def _worker_evidence(row: Mapping[str, Any]) -> dict[str, Any]:
    accepted = row["accepted"]
    evidence = {
        "binding_digest": accepted["binding_digest"],
        "binding_names": list(accepted["binding_names"]),
        "source_provenance": row["provenance"],
        "version_id": row["version_id"],
    }
    if "version_tag" in accepted:
        evidence["version_tag"] = accepted["version_tag"]
    return evidence


def collect_and_stage_jsda_observation(
    *,
    output_dir: Path,
    source_sha: str,
    runner: Callable[..., Any] = subprocess.run,
    opener: Callable[..., Any] | None = None,
    clock: Callable[[], datetime] | None = None,
) -> dict[str, Any]:
    ledger = require_pinned_finding_ledger_gate()
    bindings, pending_gate, live, staging = _intake()
    try:
        sha = live._source_sha(source_sha)
        pending_gate._require_exact_clean_source(sha)
        live._require_official_origin_main(sha, runner=runner)
        https_open = opener or staging._pinned_https_opener().open
        pending_gate._require_native_required_check(sha, opener=https_open)
        account = os.environ.get("CLOUDFLARE_ACCOUNT_ID") or bindings.PROJECT_ACCOUNT_ID
        token = os.environ.get("CLOUDFLARE_API_TOKEN") or ""
        client_id = os.environ.get(staging.ACCESS_CLIENT_ID_ENV) or ""
        client_secret = os.environ.get(staging.ACCESS_CLIENT_SECRET_ENV) or ""
        if not token or not client_id or not client_secret:
            raise ReleaseObservationAuthorityUnavailable(
                "Cloudflare API token and observer Access credentials are required"
            )
        access_manifest = staging._load_access_manifest(
            staging.ACCESS_MANIFEST_PATH, account_id=account
        )
        measured = _measure_selected(
            sha=sha,
            account=account,
            token=token,
            runner=runner,
            live=live,
            staging=staging,
            bindings=bindings,
        )
        if "JSDA_INGESTION" not in measured["observer"]["accepted"]["binding_names"]:
            raise ReleaseObservationAuthorityUnavailable(
                "observer JSDA_INGESTION binding is absent"
            )
        access_before = staging._collect_access_snapshot(
            account_id=account,
            api_token=token,
            access_manifest=access_manifest,
            opener=https_open,
        )
        raw = _get_jsda_observation(
            endpoint_url=str(access_manifest["endpoint"]["url"]),
            client_id=client_id,
            client_secret=client_secret,
            opener=https_open,
            max_bytes=staging.MAX_OBSERVER_RESPONSE_BYTES,
        )
        observed_at_text = (clock or (lambda: datetime.now(UTC)))().astimezone(
            UTC
        ).strftime("%Y-%m-%dT%H:%M:%SZ")
        pending_gate._require_exact_clean_source(sha)
        measured_after = _measure_selected(
            sha=sha,
            account=account,
            token=token,
            runner=runner,
            live=live,
            staging=staging,
            bindings=bindings,
        )
        access_after = staging._collect_access_snapshot(
            account_id=account,
            api_token=token,
            access_manifest=access_manifest,
            opener=https_open,
        )
        for role, _worker in _OBSERVED_WORKERS:
            if live._canonical_digest(measured[role]["deployment"]) != live._canonical_digest(
                measured_after[role]["deployment"]
            ) or live._canonical_digest(measured[role]["version"]) != live._canonical_digest(
                measured_after[role]["version"]
            ):
                raise ReleaseObservationAuthorityUnavailable(
                    f"{role} identity changed during JSDA collection"
                )
        if live._canonical_digest(access_before) != live._canonical_digest(access_after):
            raise ReleaseObservationAuthorityUnavailable(
                "Access identity changed during JSDA collection"
            )
        _match_modules(
            measured,
            account=account,
            token=token,
            runner=runner,
            opener=https_open,
            live=live,
        )
        observation = _require_observation(
            raw,
            source_sha=sha,
            version_id=measured["observer"]["version_id"],
            access_aud=str(access_manifest["application"]["aud"]),
            live=live,
            observer_tag=staging._observer_tag(sha),
            max_bytes=staging.MAX_OBSERVER_RESPONSE_BYTES,
        )
    except (
        staging.ReceiptStagingActiveGateError,
        live.ReceiptPendingLiveAcceptanceError,
        pending_gate.PendingReceiptAuthorityError,
        ValueError,
    ) as exc:
        _wrap(exc)
    document = {
        "access": {
            "application_id": access_manifest["application"]["id"],
            "aud": access_manifest["application"]["aud"],
            "endpoint_url": access_manifest["endpoint"]["url"],
            "snapshot_digest": live._canonical_digest(access_before),
            "worker_id": access_manifest["worker"]["id"],
        },
        "eligibility": "AUDIT_ONLY",
        "jsda": _worker_evidence(measured["jsda"]),
        "jsda_http_status": observation["http_status"],
        "ledger_digest": ledger.digest,
        "observation": observation,
        "observed_at": observed_at_text,
        "observer": _worker_evidence(measured["observer"]),
        "publication_state": "STAGED_LOCAL_NOT_PUBLISHED",
        "release_allowed": False,
        "schema_version": "quant-platform-release-evidence/v1",
        "source_sha": sha,
    }
    payload = json.dumps(
        document, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")
    digest = "sha256:" + hashlib.sha256(payload).hexdigest()
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / f"{digest.replace(':', '=')}.json"
    try:
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
    except FileExistsError as exc:
        raise ReleaseObservationAuthorityUnavailable(
            "release observation artifact already exists"
        ) from exc
    with os.fdopen(fd, "wb") as handle:
        handle.write(payload)
    return {
        "digest": digest,
        "path": str(path),
        "publication_state": "STAGED_LOCAL_NOT_PUBLISHED",
        "release_allowed": False,
        "result": "STAGED_LOCAL_NOT_PUBLISHED",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "input",
        nargs="?",
        type=Path,
        help="rejected caller JSON; omit to collect from the observer",
    )
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--source-sha")
    args = parser.parse_args(argv)
    try:
        if args.input is not None:
            require_pinned_finding_ledger_gate()
            _refuse_publication()
        if not args.source_sha:
            raise ReleaseObservationAuthorityUnavailable("source SHA is required")
        facts = collect_and_stage_jsda_observation(
            output_dir=args.output_dir,
            source_sha=args.source_sha,
        )
    except FindingLedgerError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except ReleaseObservationAuthorityUnavailable as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(json.dumps(facts, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
