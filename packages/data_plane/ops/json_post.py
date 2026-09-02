"""Typed JSON POST for Worker clients. Not a signing or READY authority."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any, Mapping


class JsonPostError(ValueError):
    """Worker JSON POST failed closed."""


def post_json_object(
    *,
    url: str,
    body: bytes,
    headers: Mapping[str, str],
    timeout: int,
) -> dict[str, Any]:
    """POST ``body`` and return a JSON object, or raise :class:`JsonPostError`."""

    request = urllib.request.Request(
        url, data=body, method="POST", headers=dict(headers)
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8")
            status = int(response.status)
    except urllib.error.HTTPError as exc:
        detail = ""
        try:
            detail = exc.read().decode("utf-8")[:4000]
        except Exception:
            detail = str(exc)
        raise JsonPostError(f"HTTP {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise JsonPostError(f"network error: {exc}") from exc
    try:
        loaded = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise JsonPostError(f"non-json (HTTP {status}): {raw[:500]}") from exc
    if not isinstance(loaded, dict):
        raise JsonPostError("response is not a JSON object")
    loaded.setdefault("http_status", status)
    return loaded
