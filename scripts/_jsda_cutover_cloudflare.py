"""Small Cloudflare API/Wrangler adapter for the JSDA cutover CLI."""

from __future__ import annotations

import json
import hashlib
import os
from pathlib import Path
import re
import subprocess
from typing import Any, Mapping, Sequence
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from scripts.d1_ingestion_migration_validation import canonical_binding


ROOT = Path(__file__).resolve().parents[1]
WORKER = ROOT / "platform" / "workers" / "ingestion-jsda"
API = "https://api.cloudflare.com/client/v4"
_SHA = re.compile(r"^[0-9a-f]{40}$")
SURFACE = {
    "production": {
        "script": "quant-platform-ingestion-jsda",
        "config": "wrangler.toml",
        "env": "production",
        "queue": "quant-jsda-ingestion",
        "d1": "quant-ingest",
    },
    "staging": {
        "script": "quant-platform-ingestion-jsda-staging",
        "config": "wrangler.staging.toml",
        "env": None,
        "queue": "quant-jsda-ingestion-staging",
        "d1": "quant-ingest-staging",
    },
}


class JsdaCutoverError(RuntimeError):
    """The cutover cannot safely continue."""


def compiled_cutover_config_digest() -> str:
    migrations = ROOT / "platform/workers/ingestion-premium/migrations"
    checksums = {
        f"quant-ingest:{name.removesuffix('.sql')}": "sha256:" + hashlib.sha256(
            (migrations / name).read_bytes()
        ).hexdigest()
        for name in ("0011_jsda_queue_v2.sql", "0012_jsda_observation_identity.sql")
    }
    body = {"kind": "jsda-v3-cutover-pin/v1", "migrations": checksums,
            "queue_contract": "jsda-acquisition-job/v2"}
    return "sha256:" + hashlib.sha256(_bytes(body)).hexdigest()


def _bytes(value: object) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")


def _wrangler() -> Path:
    executable = WORKER / "node_modules" / ".bin" / "wrangler"
    expected = WORKER / "node_modules" / "wrangler" / "bin" / "wrangler.js"
    try:
        if executable.resolve(strict=True) != expected.resolve(strict=True):
            raise JsdaCutoverError("pinned JSDA Wrangler is invalid")
    except OSError as exc:
        raise JsdaCutoverError("pinned JSDA Wrangler is missing") from exc
    return executable


def _config(environment: str) -> list[str]:
    surface = SURFACE[environment]
    args = ["--config", str(WORKER / str(surface["config"]))]
    if surface["env"]:
        args += ["--env", str(surface["env"])]
    return args


def _command(
    args: Sequence[str], *, environment: str, token: str, account: str,
    timeout: int = 120,
) -> subprocess.CompletedProcess[str]:
    env = {
        key: value for key, value in os.environ.items()
        if key not in {"HOME", "WRANGLER_HOME", "CLOUDFLARE_API_TOKEN"}
    }
    env.update({
        "CLOUDFLARE_API_TOKEN": token,
        "CLOUDFLARE_ACCOUNT_ID": account,
        "CI": "true",
        "NO_COLOR": "1",
        "WRANGLER_SEND_METRICS": "false",
    })
    try:
        return subprocess.run(
            list(args), cwd=WORKER, text=True, capture_output=True,
            check=False, timeout=timeout, env=env,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise JsdaCutoverError("Wrangler command failed") from exc


def _json_result(result: subprocess.CompletedProcess[str], label: str) -> Any:
    if result.returncode != 0:
        raise JsdaCutoverError(f"{label} failed")
    text = result.stdout or ""
    starts = [value for value in (text.find("["), text.find("{")) if value >= 0]
    try:
        return json.loads(text[min(starts) :])
    except (ValueError, json.JSONDecodeError) as exc:
        raise JsdaCutoverError(f"{label} returned malformed JSON") from exc


def _wrangler_json(
    args: Sequence[str], *, environment: str, token: str, account: str,
) -> Any:
    return _json_result(
        _command(
            [str(_wrangler()), *args, *_config(environment)],
            environment=environment, token=token, account=account,
        ),
        "Wrangler inventory",
    )


def _api(
    method: str, path: str, *, token: str, body: object | None = None,
) -> Any:
    request = Request(
        API + path, data=None if body is None else _bytes(body), method=method,
        headers={
            "authorization": f"Bearer {token}", "accept": "application/json",
            **({"content-type": "application/json"} if body is not None else {}),
        },
    )
    try:
        with urlopen(request, timeout=30) as response:
            raw = response.read(1_048_577)
    except (HTTPError, URLError, OSError, TimeoutError) as exc:
        raise JsdaCutoverError("Cloudflare API request failed") from exc
    if len(raw) > 1_048_576:
        raise JsdaCutoverError("Cloudflare API response is too large")
    try:
        envelope = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise JsdaCutoverError("Cloudflare API response is malformed") from exc
    if not isinstance(envelope, Mapping) or envelope.get("success") is not True:
        raise JsdaCutoverError("Cloudflare API request was unsuccessful")
    return envelope.get("result")


def _queue(name: str, *, token: str, account: str) -> dict[str, Any]:
    listed = _api("GET", f"/accounts/{account}/queues", token=token)
    rows = listed if isinstance(listed, list) else []
    matches = [
        row for row in rows if isinstance(row, Mapping)
        and (row.get("name") or row.get("queue_name")) == name
    ]
    if len(matches) != 1:
        raise JsdaCutoverError("queue identity is ambiguous")
    queue_id = str(matches[0].get("id") or matches[0].get("queue_id") or "")
    detail = _api("GET", f"/accounts/{account}/queues/{queue_id}", token=token)
    metrics = _api(
        "GET", f"/accounts/{account}/queues/{queue_id}/metrics", token=token
    )
    if not isinstance(detail, Mapping) or not isinstance(metrics, Mapping):
        raise JsdaCutoverError("queue observation is malformed")
    settings = detail.get("settings")
    paused = isinstance(settings, Mapping) and settings.get("delivery_paused") is True
    count, size = metrics.get("backlog_count"), metrics.get("backlog_bytes")
    if type(count) is not int or type(size) is not int:
        raise JsdaCutoverError("queue backlog is unobserved")
    return {"id": queue_id, "paused": paused, "backlog": count, "bytes": size}


def _schedules(environment: str, *, token: str, account: str) -> list[dict[str, str]]:
    rows = _api(
        "GET",
        f"/accounts/{account}/workers/scripts/{SURFACE[environment]['script']}/schedules",
        token=token,
    )
    if not isinstance(rows, list):
        raise JsdaCutoverError("Cron schedules are unobserved")
    return sorted(
        [{"cron": str(row["cron"])} for row in rows
         if isinstance(row, Mapping) and row.get("cron")],
        key=lambda row: row["cron"],
    )


def _set_schedules(
    environment: str, schedules: list[dict[str, str]], *, token: str, account: str,
) -> None:
    _api(
        "PUT",
        f"/accounts/{account}/workers/scripts/{SURFACE[environment]['script']}/schedules",
        token=token, body=schedules,
    )


def _queue_action(
    environment: str, action: str, *, token: str, account: str,
) -> None:
    if action not in {"pause-delivery", "resume-delivery"}:
        raise JsdaCutoverError("queue action is invalid")
    result = _command(
        [str(_wrangler()), "queues", action, str(SURFACE[environment]["queue"]),
         *_config(environment)],
        environment=environment, token=token, account=account,
    )
    if result.returncode:
        raise JsdaCutoverError("queue action failed")


def _d1_batch(
    environment: str, statements: Sequence[Mapping[str, Any]], *, token: str,
    account: str,
) -> list[dict[str, Any]]:
    binding = canonical_binding(environment)
    result = _api(
        "POST", f"/accounts/{account}/d1/database/{binding['database_id']}/query",
        token=token, body={"batch": [dict(row) for row in statements]},
    )
    if not isinstance(result, list) or len(result) != len(statements):
        raise JsdaCutoverError("D1 batch result is malformed")
    rows = [dict(row) for row in result if isinstance(row, Mapping)]
    if len(rows) != len(result) or any(row.get("success") is False for row in rows):
        raise JsdaCutoverError("D1 batch failed")
    return rows


def _d1_rows(
    environment: str, sql: str, *, token: str, account: str,
    params: Sequence[object] = (),
) -> list[dict[str, Any]]:
    result = _d1_batch(
        environment, [{"sql": sql, "params": list(params)}],
        token=token, account=account,
    )[0].get("results")
    if not isinstance(result, list) or any(not isinstance(row, Mapping) for row in result):
        raise JsdaCutoverError("D1 rows are malformed")
    return [dict(row) for row in result]


def _selected(environment: str, *, token: str, account: str) -> dict[str, str]:
    deployment = _wrangler_json(
        ["deployments", "status", "--json"], environment=environment,
        token=token, account=account,
    )
    if not isinstance(deployment, Mapping) or not isinstance(deployment.get("versions"), list):
        raise JsdaCutoverError("selected deployment is malformed")
    versions = deployment["versions"]
    if len(versions) != 1 or not isinstance(versions[0], Mapping):
        raise JsdaCutoverError("deployment must select one version")
    version_id = str(versions[0].get("version_id") or "")
    version = _wrangler_json(
        ["versions", "view", version_id, "--json"], environment=environment,
        token=token, account=account,
    )
    if not isinstance(version, Mapping):
        raise JsdaCutoverError("selected version is malformed")
    annotations = version.get("annotations")
    annotations = annotations if isinstance(annotations, Mapping) else {}
    tag = str(annotations.get("workers/tag") or annotations.get("workers/message") or "")
    if not _SHA.fullmatch(tag):
        raise JsdaCutoverError("selected version has no source tag")
    return {
        "deployment_id": str(deployment.get("id") or ""),
        "version_id": version_id,
        "version_tag": tag,
    }
