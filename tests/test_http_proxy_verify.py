"""Regression tests: ``verify=`` must round-trip to the J-Quants proxy client.

``CloudflareJquantsProxyHttpClient`` previously had no ``verify`` kwarg, but
``make_http_client`` already collected ``verify`` into the proxy kwargs and
forwarded it. That made ``make_jquants_http(..., verify=False)`` raise
``TypeError`` when routed through the proxy. The fix: accept ``verify`` on the
proxy client and forward it to ``httpx.Client`` (matching ``LocalHttpClient``).

These tests pin both paths — the factory entrypoint and the client ctor — so
the bug cannot silently return.
"""

from __future__ import annotations

import json

import pytest

httpx = pytest.importorskip("httpx")

from ingestion.common import secrets as secretsmod  # noqa: E402
from ingestion.common.http import (  # noqa: E402
    CloudflareJquantsProxyHttpClient,
    make_http_client,
    make_jquants_http,
)
from ingestion.common.secrets import ProxyConfig  # noqa: E402

_PROXY = "https://proxy.example.workers.dev"
_TOKEN = "shared-proxy-secret"


def _capturing_transport(captured: dict, *, status: int = 200, body: dict | None = None):
    body = {"data": [{"Code": "1"}]} if body is None else body

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["json"] = json.loads(request.content.decode("utf-8"))
        return httpx.Response(status, json=body)

    return httpx.MockTransport(handler)


def test_make_jquants_http_accepts_verify_when_routed_via_proxy(monkeypatch):
    """make_jquants_http(..., verify=False) must not TypeError via the proxy."""
    monkeypatch.setattr(
        secretsmod,
        "resolve_proxy_config",
        lambda: ProxyConfig(url=_PROXY, token=_TOKEN),
    )
    client = make_jquants_http("local", verify=False)
    assert isinstance(client, CloudflareJquantsProxyHttpClient)


def test_make_http_client_forwards_verify_to_proxy_client(monkeypatch):
    """Explicit proxy path forwards verify= without TypeError."""
    monkeypatch.setattr(
        secretsmod,
        "resolve_proxy_config",
        lambda: ProxyConfig(url=_PROXY, token=_TOKEN),
    )
    client = make_http_client("local", jquants_via_cf_proxy=True, verify=False)
    assert isinstance(client, CloudflareJquantsProxyHttpClient)


def test_proxy_client_ctor_accepts_verify_and_still_fetches():
    """Direct ctor with verify= builds a usable client (offline MockTransport)."""
    cap: dict = {}
    with CloudflareJquantsProxyHttpClient(
        proxy_url=_PROXY,
        proxy_token=_TOKEN,
        verify=False,
        transport=_capturing_transport(cap),
    ) as client:
        resp = client.get("https://api.jquants.com/v2/equities/bars/daily")
    assert cap["url"] == f"{_PROXY}/v1/proxy/jquants"
    assert cap["json"]["path"] == "/v2/equities/bars/daily"
    assert resp.status == 200
