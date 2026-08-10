"""Secret / proxy-config resolution for ingestion.

The J-Quants API key lives **only** on the Cloudflare Worker
(``quant-platform-ingestion-secrets``); local runners must never hold it. To
fetch J-Quants from local, the runner instead calls the Worker's proxy endpoint
(``POST {proxy}/v1/proxy/jquants``) authenticated with a shared
``INGESTION_PROXY_TOKEN``. The Worker injects the real ``x-api-key``
upstream — the local process never sees it.

This module resolves the *proxy* configuration (URL + bearer token) — **not**
any data-source API key. A URL and its token must come from the **same**
source — never a proxy URL from one place paired with a token from another
(that would risk pointing an authenticated token at the wrong proxy). We try
each source in order and use the first that yields a *complete* pair:

1. environment variables ``INGESTION_PROXY_URL`` **and**
   ``INGESTION_PROXY_TOKEN`` (both required);
2. else a single JSON file ``~/.config/quant-platform/ingestion_proxy.json``
   with keys ``{"url", "token"}`` (both required);
3. else the split files ``~/.config/quant-platform/ingestion_proxy_url`` and
   ``ingestion_proxy_token`` (first line, stripped; both required).

A *missing* or *partial* config is not an error — :func:`resolve_proxy_config`
simply returns ``None`` and callers fall back to direct (key-required) fetch.

Nothing here ever logs or returns a raw data-source key.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

CONFIG_DIR = Path.home() / ".config" / "quant-platform"
URL_FILE = CONFIG_DIR / "ingestion_proxy_url"
TOKEN_FILE = CONFIG_DIR / "ingestion_proxy_token"
JSON_FILE = CONFIG_DIR / "ingestion_proxy.json"

ENV_URL = "INGESTION_PROXY_URL"
ENV_TOKEN = "INGESTION_PROXY_TOKEN"


@dataclass(frozen=True)
class ProxyConfig:
    """Resolved Cloudflare ingestion-proxy coordinates.

    ``token`` is the shared bearer compared by the Worker against its
    ``INGESTION_PROXY_TOKEN`` secret; treat it as a credential (do not log).
    """

    url: str
    token: str


def _read_first_line(path: Path) -> Optional[str]:
    try:
        with path.open("r", encoding="utf-8") as fh:
            for line in fh:
                s = line.strip()
                if s:
                    return s
    except FileNotFoundError:
        return None
    except OSError:  # pragma: no cover - best effort
        return None
    return None


def _read_json_pair(path: Path) -> Optional[ProxyConfig]:
    """Read a single-file JSON proxy pair ``{"url": ..., "token": ...}``.

    Returns a :class:`ProxyConfig` only if BOTH keys are present and
    non-empty — a partial JSON file is treated as *no* config rather than
    mixed with another source. A missing, unreadable, or malformed file is
    likewise ignored (best effort), mirroring :func:`_read_first_line`.
    """
    try:
        with path.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
    except FileNotFoundError:
        return None
    except (OSError, ValueError):  # unreadable / malformed JSON
        return None
    if not isinstance(data, dict):
        return None
    url = str(data.get("url") or "").strip()
    token = str(data.get("token") or "").strip()
    if not url or not token:
        return None
    return ProxyConfig(url=url.rstrip("/"), token=token)


def resolve_proxy_config(
    *,
    env: Optional[dict[str, str]] = None,
    config_dir: Optional[Path] = None,
) -> Optional[ProxyConfig]:
    """Resolve proxy URL + token, or ``None`` if no *complete* pair exists.

    A URL and its token must come from the **same** source. We try each
    source in order and return the first that yields both fields; a URL from
    one source is never paired with a token from another:

    1. environment variables ``INGESTION_PROXY_URL`` **and**
       ``INGESTION_PROXY_TOKEN`` (both required);
    2. a single JSON pair file ``ingestion_proxy.json`` (both keys required);
    3. the split files ``ingestion_proxy_url`` and ``ingestion_proxy_token``
       (both required).

    If no source is complete we return ``None`` (an unauthenticated or
    cross-source proxy is not safe to use), so callers cleanly fall back to
    direct fetch rather than half-working.
    """
    env = os.environ if env is None else env
    base = config_dir or CONFIG_DIR
    json_file = base / "ingestion_proxy.json" if config_dir else JSON_FILE
    url_file = base / "ingestion_proxy_url" if config_dir else URL_FILE
    token_file = base / "ingestion_proxy_token" if config_dir else TOKEN_FILE

    # 1) env pair — both must be set together.
    env_url = (env.get(ENV_URL) or "").strip()
    env_token = (env.get(ENV_TOKEN) or "").strip()
    if env_url and env_token:
        return ProxyConfig(url=env_url.rstrip("/"), token=env_token)

    # 2) single JSON pair file — both keys must be present together.
    json_cfg = _read_json_pair(json_file)
    if json_cfg is not None:
        return json_cfg

    # 3) split-file pair — both files must be present together.
    file_url = _read_first_line(url_file)
    file_token = _read_first_line(token_file)
    if file_url and file_token:
        return ProxyConfig(url=file_url.rstrip("/"), token=file_token)

    return None
