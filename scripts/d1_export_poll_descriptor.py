#!/usr/bin/env python3
"""Poll Cloudflare D1 export to a private descriptor. Never downloads SQL.

Wrangler `d1 export --remote --output` writes SQL to a local file (`--output -`
is the filename "-"). This helper only POSTs/polls
`/accounts/{account_id}/d1/database/{database_id}/export` and writes a 0600
descriptor. Do not invoke against live D1 until combined approval: export
interrupts the database.

Auth: CLOUDFLARE_API_TOKEN and CLOUDFLARE_ACCOUNT_ID from the environment.
Never pass tokens on argv. Signed URLs are written only to --output.
"""

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from scripts.encrypt_d1_backup import _governed_database

BUNDLE_SCHEMA = "d1-export-bundle/v1"
API_ROOT = "https://api.cloudflare.com/client/v4"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _redact(error: BaseException) -> str:
    text = str(error)
    lowered = text.lower()
    for token in ("http://", "https://", "signed_url", "bearer", "api_token"):
        if token in lowered:
            return type(error).__name__
    return text[:240]


def download_host_from_url(signed_url: str) -> str:
    try:
        parsed = urlparse(signed_url)
    except ValueError as exc:
        raise ValueError("export signed_url missing") from exc
    if parsed.scheme != "https" or parsed.username or parsed.password:
        raise ValueError("export signed_url missing")
    host = (parsed.hostname or "").lower()
    if not host or host == "localhost" or host.endswith(".local") or ":" in host:
        raise ValueError("export signed_url missing")
    if all(part.isdigit() for part in host.split(".")):
        raise ValueError("export signed_url missing")
    return host


def parse_export_complete_envelope(envelope: Mapping[str, Any]) -> dict[str, str]:
    """Extract bookmark + signed_url from the Cloudflare API envelope.

    Raw HTTP JSON is {success, result:{status, at_bookmark, result:{signed_url}}}.
    The download URL is outer.result.result.signed_url, not outer.result.signed_url.
    """
    if not isinstance(envelope, Mapping):
        raise ValueError("export envelope is invalid")
    outer: Any = envelope
    if "success" in envelope:
        if envelope.get("success") is not True:
            raise ValueError("export request failed")
        outer = envelope.get("result")
    if not isinstance(outer, Mapping):
        raise ValueError("export envelope is invalid")
    if outer.get("status") != "complete":
        raise ValueError("export is not complete")
    inner = outer.get("result")
    if not isinstance(inner, Mapping):
        raise ValueError("export signed_url missing")
    signed = inner.get("signed_url")
    if not isinstance(signed, str) or not signed.startswith("https://"):
        raise ValueError("export signed_url missing")
    bookmark = outer.get("at_bookmark")
    if not isinstance(bookmark, str) or not bookmark.strip():
        raise ValueError("export at_bookmark missing")
    host = download_host_from_url(signed)
    filename = inner.get("filename")
    return {
        "at_bookmark": bookmark.strip(),
        "signed_url": signed,
        "download_host": host,
        "filename": filename if isinstance(filename, str) else "",
    }


def build_descriptor(
    *,
    environment: str,
    governed: Mapping[str, str],
    complete: Mapping[str, str],
    export_completed_at: str,
) -> dict[str, str]:
    if governed.get("environment") != environment:
        raise ValueError("export environment mismatch")
    return {
        "schema_version": BUNDLE_SCHEMA,
        "environment": environment,
        "database_name": str(governed["name"]),
        "database_id": str(governed["id"]),
        "at_bookmark": complete["at_bookmark"],
        "export_completed_at": export_completed_at,
        "download_host": complete["download_host"],
        "signed_url": complete["signed_url"],
    }


def _api(token: str, method: str, path: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = None if body is None else json.dumps(body, separators=(",", ":")).encode("utf-8")
    request = Request(
        API_ROOT + path,
        data=payload,
        method=method,
        headers={
            "authorization": "Bearer " + token,
            "content-type": "application/json",
        },
    )
    try:
        with urlopen(request, timeout=60) as response:
            raw = response.read(1024 * 1024)
    except HTTPError as error:
        raise RuntimeError(_redact(error)) from None
    except URLError as error:
        raise RuntimeError(_redact(error)) from None
    try:
        parsed = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError("export envelope is invalid") from exc
    if not isinstance(parsed, dict):
        raise RuntimeError("export envelope is invalid")
    return parsed


def poll_export(*, token: str, account_id: str, database_id: str) -> dict[str, str]:
    path = f"/accounts/{account_id}/d1/database/{database_id}/export"
    bookmark: str | None = None
    for _ in range(120):
        body: dict[str, Any] = {"output_format": "polling"}
        if bookmark:
            body["current_bookmark"] = bookmark
        envelope = _api(token, "POST", path, body)
        outer = envelope.get("result") if envelope.get("success") is True else envelope
        if not isinstance(outer, Mapping):
            raise RuntimeError("export envelope is invalid")
        status = outer.get("status")
        if status == "complete":
            return parse_export_complete_envelope(envelope)
        if status == "error":
            raise RuntimeError("export failed")
        next_bookmark = outer.get("at_bookmark")
        if isinstance(next_bookmark, str) and next_bookmark:
            bookmark = next_bookmark
    raise RuntimeError("export poll exhausted")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--environment", choices=("staging", "production"), required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--initiate",
        action="store_true",
        help="POST/poll live export (interrupts D1; required to run)",
    )
    args = parser.parse_args(argv)
    if not args.initiate:
        raise SystemExit("refusing to run without --initiate; export interrupts D1")
    governed = _governed_database(args.environment)
    token = os.environ.get("CLOUDFLARE_API_TOKEN") or ""
    account = os.environ.get("CLOUDFLARE_ACCOUNT_ID") or ""
    if not token or not account:
        raise SystemExit("CLOUDFLARE_API_TOKEN and CLOUDFLARE_ACCOUNT_ID are required")
    complete = poll_export(token=token, account_id=account, database_id=governed["id"])
    bundle = build_descriptor(
        environment=args.environment,
        governed=governed,
        complete=complete,
        export_completed_at=_utc_now(),
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(bundle, indent=2, sort_keys=True) + "\n")
    os.chmod(args.output, 0o600)
    public = {k: v for k, v in bundle.items() if k != "signed_url"}
    print(json.dumps(public, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
