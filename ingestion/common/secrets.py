"""Secret / credential resolution for ingestion.

J-Quants is authenticated one of two ways, in priority order:

1. **Cloudflare proxy (default when configured)** — a proxy config under the
   quant-platform config dir points local runners at the ``ingestion-secrets``
   Worker (``platform/workers/ingestion-secrets``), which holds
   ``JQUANTS_API_KEY`` on Cloudflare. The local machine never sees the key:
   the Worker injects the upstream ``x-api-key``. Activate by creating
   ``~/.config/quant-platform/ingestion-proxy.json`` (schema below).
2. **Env var fallback** — ``JQUANTS_API_KEY`` for a direct call with no proxy.

Config dir overrides via ``QUANT_PLATFORM_CONFIG_DIR``.

This module **never logs or returns secret values** to general callers.
:func:`resolve_jquants` returns a small descriptor of *which* path is in use
plus the non-secret bits needed to build a client (a proxy endpoint / token,
or a key handed only to the client that will send it upstream). ``via`` is a
short label safe to print.

Proxy config schema (``ingestion-proxy.json``)::

    {
      "proxy_url": "https://quant-platform-ingestion-secrets.<sub>.workers.dev",
      "proxy_token": "..."            // optional; matches Worker INGESTION_PROXY_TOKEN
    }

``proxy_url`` may be either the Worker origin or the full
``<origin>/v1/proxy/jquants`` route — :func:`proxy_endpoint` normalizes both.
``proxy_token`` corresponds to the Worker secret ``INGESTION_PROXY_TOKEN``
and is *not* the J-Quants key.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

#: Override the config directory (default ``~/.config/quant-platform``).
CONFIG_DIR_ENV = "QUANT_PLATFORM_CONFIG_DIR"
DEFAULT_CONFIG_DIR = "~/.config/quant-platform"

#: File name holding the proxy config inside the config dir.
PROXY_CONFIG_FILENAME = "ingestion-proxy.json"

#: Route the Worker exposes for proxied J-Quants calls.
PROXY_ROUTE = "/v1/proxy/jquants"

#: Sentinel api_key used when J-Quants is routed via the proxy. The Worker
#: ignores client-supplied ``x-api-key`` and injects its own, so this value
#: never reaches the real upstream. ``JQuantsClient`` only requires it be
#: non-empty (its "no key" guard) — it must not be mistaken for a real key.
PROXY_API_KEY_SENTINEL = "via-proxy"


@dataclass(frozen=True)
class ProxyConfig:
    """Non-secret descriptor of the Cloudflare J-Quants proxy.

    ``proxy_token`` authorizes the proxy call (Worker secret
    ``INGESTION_PROXY_TOKEN``); it is **not** the J-Quants key and is safe to
    hand to the HTTP client, but should still not be logged.
    """

    proxy_url: str
    proxy_token: str = ""


@dataclass
class JquantsAuth:
    """Resolved J-Quants authentication. Exactly one path is populated.

    * ``via == "proxy"`` — use :attr:`proxy`; the real key lives on Cloudflare.
    * ``via == "env"``  — direct call with :attr:`api_key` from the environment.
    * ``via == "none"`` — no key and no proxy; J-Quants must be skipped.
    """

    via: str
    proxy: Optional[ProxyConfig] = None
    api_key: str = ""

    @property
    def effective_api_key(self) -> str:
        """Key to hand ``JQuantsClient``.

        The proxy sentinel when proxying (the Worker injects the real key),
        the env key for a direct call, or ``""`` when unauthenticated.
        """
        if self.via == "proxy":
            return PROXY_API_KEY_SENTINEL
        return self.api_key


def config_dir() -> Path:
    """Resolved config directory (expands ``~``)."""
    return Path(os.environ.get(CONFIG_DIR_ENV, DEFAULT_CONFIG_DIR)).expanduser()


def proxy_endpoint(cfg: ProxyConfig) -> str:
    """Full proxy POST URL.

    Accepts ``proxy_url`` as either the Worker origin or the full route, and
    tolerates a trailing slash. Returns ``<origin>/v1/proxy/jquants``.
    """
    base = (cfg.proxy_url or "").strip().rstrip("/")
    if not base:
        raise ValueError("ProxyConfig.proxy_url is empty")
    if base.endswith(PROXY_ROUTE):
        return base
    return base + PROXY_ROUTE


def load_proxy_config() -> Optional[ProxyConfig]:
    """Load the proxy config if present and well-formed, else ``None``.

    Missing file, unreadable file, or a payload without ``proxy_url`` all
    resolve to ``None`` (fall through to the env var). Never raises — a broken
    proxy config should not crash ingestion, just disable the proxy path.
    """
    path = config_dir() / PROXY_CONFIG_FILENAME
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    url = str(data.get("proxy_url") or "").strip()
    if not url:
        return None
    token = str(data.get("proxy_token") or data.get("token") or "").strip()
    return ProxyConfig(proxy_url=url, proxy_token=token)


def resolve_jquants(*, env: Optional[dict] = None) -> JquantsAuth:
    """Pick the CF proxy when configured, else the env key, else none.

    ``env`` defaults to ``os.environ``; tests inject a mapping. The proxy
    wins over the env key so that, once a proxy is configured, the local
    machine does not need (and should not use) a local copy of the key.
    """
    proxy = load_proxy_config()
    if proxy is not None:
        return JquantsAuth(via="proxy", proxy=proxy)
    environ = env if env is not None else os.environ
    key = environ.get("JQUANTS_API_KEY", "")
    if key:
        return JquantsAuth(via="env", api_key=key)
    return JquantsAuth(via="none")
