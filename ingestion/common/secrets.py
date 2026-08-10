"""Secret / proxy-config resolution for ingestion.

The J-Quants API key lives **only** on the Cloudflare Worker
(``quant-platform-ingestion-secrets``); local runners must never hold it. To
fetch J-Quants from local, the runner instead calls the Worker's proxy endpoint
(``POST {proxy}/v1/proxy/jquants``) authenticated with a shared
``INGESTION_PROXY_TOKEN``. The Worker injects the real ``x-api-key``
upstream — the local process never sees it.

This module resolves the *proxy* configuration (URL + bearer token) — **not**
any data-source API key. Resolution order:

1. environment variables ``INGESTION_PROXY_URL`` / ``INGESTION_PROXY_TOKEN``;
2. else the files ``~/.config/quant-platform/ingestion_proxy_url`` and
   ``ingestion_proxy_token`` (first line, stripped).

A *missing* config is not an error — :func:`resolve_proxy_config` simply
returns ``None`` and callers fall back to direct (key-required) fetch.

Nothing here ever logs or returns a raw data-source key.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

CONFIG_DIR = Path.home() / ".config" / "quant-platform"
URL_FILE = CONFIG_DIR / "ingestion_proxy_url"
TOKEN_FILE = CONFIG_DIR / "ingestion_proxy_token"

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


def resolve_proxy_config(
    *,
    env: Optional[dict[str, str]] = None,
    config_dir: Optional[Path] = None,
) -> Optional[ProxyConfig]:
    """Resolve proxy URL + token, or ``None`` if neither is configured.

    Both a URL and a token are required for a usable config. If only one is
    present we return ``None`` (an unauthenticated proxy is not safe to use),
    so callers cleanly fall back to direct fetch rather than half-working.
    """
    env = os.environ if env is None else env
    base = config_dir or CONFIG_DIR
    url_file = base / "ingestion_proxy_url" if config_dir else URL_FILE
    token_file = base / "ingestion_proxy_token" if config_dir else TOKEN_FILE

    url = (env.get(ENV_URL) or "").strip() or _read_first_line(url_file)
    token = (env.get(ENV_TOKEN) or "").strip() or _read_first_line(token_file)

    if not url or not token:
        return None
    return ProxyConfig(url=url.rstrip("/"), token=token)
