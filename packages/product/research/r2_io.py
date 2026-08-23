"""R2 object put and get via wrangler. Local FS is not SoT.

Python default_r2_put(create_only=True) is head-then-put TOCTOU, not
immutable create-if-absent. Worker onlyIf children-then-manifest is the
immutable authority. Python CLI put is not artifact authority.
Remote put is fail-closed unless QP_ALLOW_PYTHON_R2_PUT=1.
put_children_then_manifest_via_worker is the Worker-client entry; it
POSTs /v1/children-then-manifest with X-Mass-Eval-Token. It does not
fall back to CLI put. Unbound Worker URL/token fail closed. Non-JSON
bodies fail closed. Digests are Worker-computed, never forged here.
"""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from qp_paths import repo_root

REPO_ROOT = repo_root()
DEFAULT_WRANGLER = (
    REPO_ROOT
    / "platform"
    / "workers"
    / "ingestion-premium"
    / "node_modules"
    / ".bin"
    / "wrangler"
)
DEFAULT_WRANGLER_CONFIG = (
    REPO_ROOT / "platform" / "workers" / "ingestion-premium" / "wrangler.toml"
)

# Private aliases used by history/feature loaders.
_REPO_ROOT = REPO_ROOT
_DEFAULT_WRANGLER = DEFAULT_WRANGLER
_DEFAULT_WRANGLER_CONFIG = DEFAULT_WRANGLER_CONFIG

PYTHON_R2_PUT_ENV = "QP_ALLOW_PYTHON_R2_PUT"
WORKER_PUT_URL_ENV = "MASS_EVAL_WORKER_URL"
WORKER_PUT_TOKEN_ENV = "MASS_EVAL_TOKEN"
WORKER_CHILDREN_THEN_MANIFEST_PATH = "/v1/children-then-manifest"
WORKER_CHILDREN_THEN_MANIFEST_ERROR = (
    "python must use Worker children-then-manifest; CLI put is not authority"
)

# Comment-level invariant: CLI put is head-then-put TOCTOU, not create-if-absent.
# Python CLI put is not artifact authority.
python_cli_put_is_not_immutable_authority: bool = True


class R2IOError(ValueError):
    """Invalid R2 wrangler I/O input or put/get failure."""


def python_r2_put_allowed() -> bool:
    """True only when QP_ALLOW_PYTHON_R2_PUT=1. Not artifact authority."""
    return os.environ.get(PYTHON_R2_PUT_ENV, "").strip() == "1"


def _bound_worker_url(explicit: str | None) -> str:
    if explicit is not None and str(explicit).strip():
        return str(explicit).strip()
    return (os.environ.get(WORKER_PUT_URL_ENV) or "").strip()


def _bound_worker_token(explicit: str | None) -> str:
    if explicit is not None and str(explicit).strip():
        return str(explicit).strip()
    return (os.environ.get(WORKER_PUT_TOKEN_ENV) or "").strip()


def _item_key(item: Mapping[str, Any], label: str) -> str:
    key = str(item.get("key") or "").strip()
    if not key:
        raise R2IOError(f"{label} missing key")
    return key


def _item_body(item: Mapping[str, Any], label: str) -> bytes:
    if "body" in item and item["body"] is not None:
        raw = item["body"]
        if isinstance(raw, bytes):
            return raw
        if isinstance(raw, str):
            return raw.encode("utf-8")
        raise R2IOError(f"{label} body must be bytes or str")
    if "data" not in item:
        raise R2IOError(f"{label} requires data or body")
    data = item["data"]
    if isinstance(data, bytes):
        return data
    return json.dumps(data, indent=2, default=str).encode("utf-8")


def _item_json_data(item: Mapping[str, Any], label: str) -> Any:
    """JSON value for the Worker put. Non-JSON body fail-closes; no digest forge."""
    if "data" in item and item["data"] is not None:
        data = item["data"]
        if isinstance(data, bytes):
            try:
                return json.loads(data.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise R2IOError(f"{label} data is not JSON") from exc
        return data
    if "body" not in item or item["body"] is None:
        raise R2IOError(f"{label} requires data or body")
    raw = item["body"]
    if isinstance(raw, bytes):
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise R2IOError(f"{label} body is not JSON") from exc
    elif isinstance(raw, str):
        text = raw
    else:
        raise R2IOError(f"{label} body must be bytes or str")
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise R2IOError(f"{label} body is not JSON") from exc


def _worker_json_item(item: Mapping[str, Any], label: str) -> dict[str, Any]:
    return {"key": _item_key(item, label), "data": _item_json_data(item, label)}


def _post_worker_children_then_manifest(
    url: str,
    token: str,
    payload: bytes,
    *,
    timeout: int,
    http_post: Callable[..., Any] | None,
) -> dict[str, Any]:
    headers = {
        "Content-Type": "application/json",
        "X-Mass-Eval-Token": token,
    }
    if http_post is not None:
        raw_resp = http_post(url=url, body=payload, headers=headers)
        if isinstance(raw_resp, Mapping):
            parsed = dict(raw_resp)
        else:
            text = raw_resp if isinstance(raw_resp, str) else raw_resp.decode("utf-8")
            try:
                loaded = json.loads(text)
            except json.JSONDecodeError as exc:
                raise R2IOError(WORKER_CHILDREN_THEN_MANIFEST_ERROR) from exc
            if not isinstance(loaded, dict):
                raise R2IOError(WORKER_CHILDREN_THEN_MANIFEST_ERROR)
            parsed = loaded
        return parsed

    req = urllib.request.Request(url, data=payload, method="POST", headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
            status = int(resp.status)
    except urllib.error.HTTPError as exc:
        detail = ""
        try:
            detail = exc.read().decode("utf-8")[:2000]
        except Exception:
            detail = str(exc)
        raise R2IOError(
            f"{WORKER_CHILDREN_THEN_MANIFEST_ERROR}: HTTP {exc.code}: {detail}"
        ) from exc
    except urllib.error.URLError as exc:
        raise R2IOError(
            f"{WORKER_CHILDREN_THEN_MANIFEST_ERROR}: network error: {exc}"
        ) from exc
    try:
        loaded = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise R2IOError(
            f"{WORKER_CHILDREN_THEN_MANIFEST_ERROR}: non-json (HTTP {status})"
        ) from exc
    if not isinstance(loaded, dict):
        raise R2IOError(WORKER_CHILDREN_THEN_MANIFEST_ERROR)
    return loaded


def put_children_then_manifest_via_worker(
    children: Sequence[Mapping[str, Any]],
    manifest: Mapping[str, Any],
    *,
    worker_url: str | None = None,
    token: str | None = None,
    dry_run: bool = False,
    staging_dir: str | Path | None = None,
    timeout: int = 120,
    http_post: Callable[..., Any] | None = None,
) -> dict[str, Any]:
    """POST children-then-manifest via Worker. CLI put is not authority.

    dry_run stages locally only. Remote POSTs /v1/children-then-manifest with
    X-Mass-Eval-Token (Worker ``authorized``). Unbound URL/token fail closed.
    There is no CLI put fallback and no digest forge. Non-JSON body fail-closes.
    QP_ALLOW_PYTHON_R2_PUT=1 does not grant CLI put on this path.
    """
    child_items = [dict(c) for c in children]
    manifest_item = dict(manifest)
    child_keys = [_item_key(c, "child") for c in child_items]
    manifest_key = _item_key(manifest_item, "manifest")
    if dry_run:
        staged: list[str] = []
        if staging_dir is not None:
            root = Path(staging_dir)
            for item in (*child_items, manifest_item):
                label = "manifest" if item is manifest_item else "child"
                key = _item_key(item, label)
                out = root / key.replace("/", "__")
                out.parent.mkdir(parents=True, exist_ok=True)
                out.write_bytes(_item_body(item, label))
                staged.append(str(out))
        return {
            "status": "dry_run",
            "children": child_keys,
            "manifest_key": manifest_key,
            "staged_paths": staged or None,
        }

    url = _bound_worker_url(worker_url)
    tok = _bound_worker_token(token)
    if not url or not tok:
        raise R2IOError(WORKER_CHILDREN_THEN_MANIFEST_ERROR)

    child_payloads = [_worker_json_item(c, "child") for c in child_items]
    manifest_payload = _worker_json_item(manifest_item, "manifest")
    try:
        body = json.dumps(
            {"children": child_payloads, "manifest": manifest_payload}
        ).encode("utf-8")
    except TypeError as exc:
        raise R2IOError(
            f"{WORKER_CHILDREN_THEN_MANIFEST_ERROR}: payload is not JSON"
        ) from exc

    parsed = _post_worker_children_then_manifest(
        url.rstrip("/") + WORKER_CHILDREN_THEN_MANIFEST_PATH,
        tok,
        body,
        timeout=timeout,
        http_post=http_post,
    )
    if parsed.get("ok") is not True:
        err = str(parsed.get("error") or "worker rejected children-then-manifest")
        raise R2IOError(f"{WORKER_CHILDREN_THEN_MANIFEST_ERROR}: {err}")
    manifest_res = parsed.get("manifest")
    created = False
    if isinstance(manifest_res, Mapping):
        created = bool(manifest_res.get("created"))
    return {
        "status": "put_ok" if created else "exists",
        "ok": True,
        "conflict": bool(parsed.get("conflict")),
        "verified": bool(parsed.get("verified")),
        "created": created,
        "children": child_keys,
        "manifest_key": manifest_key,
    }


def default_r2_put(
    bucket: str,
    key: str,
    body: bytes,
    *,
    wrangler: str | Path | None = None,
    config: str | Path | None = None,
    content_type: str = "application/json",
    dry_run: bool = False,
    staging_dir: str | Path | None = None,
    create_only: bool = True,
    authoritative: bool = False,
) -> dict[str, Any]:
    """Put one object to R2 via wrangler (remote). dry_run stages only.

    create_only (default True): if the key already exists, do not overwrite.

    wrangler ``r2 object put`` has no create-if-absent / if-not-exists flag
    (Workers ``onlyIf.etagDoesNotMatch`` is not on the CLI). Existence is
    therefore head-then-put. That sequence is TOCTOU: a concurrent writer
    can create the key after a miss and this put will overwrite. If head
    succeeds, skip put and return status ``exists``.
    Python CLI put is not artifact authority and is not the immutable authority;
    Worker onlyIf children-then-manifest is.
    ``authoritative=True`` is refused.
    Remote (non dry_run) put is fail-closed unless QP_ALLOW_PYTHON_R2_PUT=1.
    """
    if authoritative:
        raise R2IOError("python CLI put is not artifact authority")
    meta = {
        "bucket": bucket,
        "key": key,
        "bytes": len(body),
        "content_type": content_type,
        "object_path": f"{bucket}/{key}",
    }
    # Local stage only — never wrangler/remote.
    if dry_run:
        staged: str | None = None
        if staging_dir is not None:
            out = Path(staging_dir) / key.replace("/", "__")
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(body)
            staged = str(out)
        return {**meta, "status": "dry_run", "staged_path": staged}

    if not python_r2_put_allowed():
        raise R2IOError(
            f"remote python R2 put without {PYTHON_R2_PUT_ENV}=1; "
            "Python CLI put is not artifact authority"
        )

    wr = Path(wrangler) if wrangler else DEFAULT_WRANGLER
    cfg = Path(config) if config else DEFAULT_WRANGLER_CONFIG
    if not wr.is_file():
        raise R2IOError(
            f"wrangler binary not found for R2 put: {wr}. "
            "Use dry_run=True to stage payloads without remote write."
        )

    if create_only:
        # TOCTOU: head hit refuses overwrite; a miss still races the put.
        head = subprocess.run(
            [
                str(wr),
                "r2",
                "object",
                "head",
                f"{bucket}/{key}",
                "--remote",
                f"--config={cfg}",
            ],
            capture_output=True,
            text=True,
            timeout=60,
            cwd=str(REPO_ROOT),
        )
        if head.returncode == 0:
            return {**meta, "status": "exists", "created": False, "wrangler_rc": 0}

    with tempfile.NamedTemporaryFile(
        prefix="r2put_", suffix=".json", delete=False
    ) as tmp:
        tmp.write(body)
        tmp_path = Path(tmp.name)
    try:
        proc = subprocess.run(
            [
                str(wr),
                "r2",
                "object",
                "put",
                f"{bucket}/{key}",
                f"--file={tmp_path}",
                "--remote",
                f"--config={cfg}",
                f"--content-type={content_type}",
            ],
            capture_output=True,
            text=True,
            timeout=180,
            cwd=str(REPO_ROOT),
        )
        if proc.returncode != 0:
            combined = (proc.stderr or "") + (proc.stdout or "")
            raise R2IOError(
                f"r2 put failed for {bucket}/{key} rc={proc.returncode}: "
                f"{combined[-1200:]}"
            )
        return {**meta, "status": "put_ok", "created": True, "wrangler_rc": 0}
    finally:
        try:
            tmp_path.unlink(missing_ok=True)
        except OSError:
            pass


def default_r2_get_object(
    bucket: str,
    key: str,
    *,
    wrangler: str | Path | None = None,
    config: str | Path | None = None,
    timeout: int = 300,
) -> bytes:
    """Fetch one R2 object body via ``wrangler r2 object get`` (remote)."""
    wr = Path(wrangler) if wrangler else DEFAULT_WRANGLER
    cfg = Path(config) if config else DEFAULT_WRANGLER_CONFIG
    if not wr.is_file():
        raise R2IOError(
            f"wrangler binary not found for R2 get: {wr}. "
            "Inject r2_get= or supply local_paths / pre-parsed rows."
        )
    with tempfile.NamedTemporaryFile(
        prefix="r2fc_get_", suffix=".bin", delete=False
    ) as tmp:
        tmp_path = Path(tmp.name)
    try:
        proc = subprocess.run(
            [
                str(wr),
                "r2",
                "object",
                "get",
                f"{bucket}/{key}",
                f"--file={tmp_path}",
                "--remote",
                f"--config={cfg}",
            ],
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=str(REPO_ROOT),
        )
        if proc.returncode != 0:
            combined = (proc.stderr or "") + (proc.stdout or "")
            raise R2IOError(
                f"r2 get failed for {bucket}/{key} rc={proc.returncode}: "
                f"{combined[-1200:]}"
            )
        return tmp_path.read_bytes()
    finally:
        try:
            tmp_path.unlink(missing_ok=True)
        except OSError:
            pass


__all__ = [
    "DEFAULT_WRANGLER",
    "DEFAULT_WRANGLER_CONFIG",
    "PYTHON_R2_PUT_ENV",
    "REPO_ROOT",
    "R2IOError",
    "WORKER_CHILDREN_THEN_MANIFEST_ERROR",
    "WORKER_CHILDREN_THEN_MANIFEST_PATH",
    "WORKER_PUT_TOKEN_ENV",
    "WORKER_PUT_URL_ENV",
    "default_r2_get_object",
    "default_r2_put",
    "put_children_then_manifest_via_worker",
    "python_cli_put_is_not_immutable_authority",
    "python_r2_put_allowed",
]
