"""CloudflareJquantsProxyHttpClient: routes POST to the proxy, never sends the key.

Offline via ``httpx.MockTransport`` — captures the outgoing request and
asserts the J-Quants key never leaves local (only ``X-Ingestion-Token``).
Also covers ``make_http_client``/``make_jquants_http`` dispatch.
"""

from __future__ import annotations

import json

import pytest

httpx = pytest.importorskip("httpx")

from ingestion.common import http as httpmod  # noqa: E402
from ingestion.common import secrets as secretsmod  # noqa: E402
from ingestion.common.http import (  # noqa: E402
    CloudflareJquantsProxyHttpClient,
    LocalHttpClient,
    make_http_client,
    make_jquants_http,
)
from ingestion.common.secrets import ProxyConfig, resolve_proxy_config  # noqa: E402

_PROXY = "https://proxy.example.workers.dev"
_TOKEN = "shared-proxy-secret"


def _capturing_transport(captured: dict, *, status: int = 200, body: dict | None = None):
    body = {"data": [{"Code": "1"}]} if body is None else body

    def handler(request: httpx.Request) -> httpx.Response:
        captured["method"] = request.method
        captured["url"] = str(request.url)
        captured["headers"] = dict(request.headers)
        captured["json"] = json.loads(request.content.decode("utf-8"))
        return httpx.Response(status, json=body)

    return httpx.MockTransport(handler)


# --------------------------------------------------------------------------- proxy POST

def test_proxy_posts_to_proxy_url_with_token_and_no_api_key():
    cap: dict = {}
    transport = _capturing_transport(cap)
    with CloudflareJquantsProxyHttpClient(
        proxy_url=_PROXY, proxy_token=_TOKEN, transport=transport
    ) as client:
        resp = client.get(
            "https://api.jquants.com/v2/equities/bars/daily",
            params={"code": "8697", "from": "2025-04-01", "empty": None},
            # a caller-supplied x-api-key must be DROPPED, not forwarded
            headers={"x-api-key": "SHOULD-NOT-LEAK"},
        )

    # method + endpoint
    assert cap["method"] == "POST"
    assert cap["url"] == f"{_PROXY}/v1/proxy/jquants"
    # auth: only the shared token reaches the wire; no J-Quants key
    assert cap["headers"].get("x-ingestion-token") == _TOKEN
    assert "x-api-key" not in {k.lower() for k in cap["headers"]}
    # body shape: only the /v2/ path + non-empty query
    assert cap["json"]["path"] == "/v2/equities/bars/daily"
    assert cap["json"]["query"] == {"code": "8697", "from": "2025-04-01"}
    # response passes through
    assert resp.status == 200
    assert resp.json() == {"data": [{"Code": "1"}]}


def test_proxy_strips_trailing_slash_and_passes_status():
    cap: dict = {}
    transport = _capturing_transport(cap, status=503, body={"err": "boom"})
    with CloudflareJquantsProxyHttpClient(
        proxy_url=_PROXY + "/", proxy_token=_TOKEN, transport=transport
    ) as client:
        resp = client.get("https://api.jquants.com/v2/markets/calendar")
    assert cap["url"] == f"{_PROXY}/v1/proxy/jquants"  # no double slash
    assert resp.status == 503


def test_proxy_rejects_non_v2_url():
    with CloudflareJquantsProxyHttpClient(
        proxy_url=_PROXY, proxy_token=_TOKEN,
        transport=httpx.MockTransport(lambda r: httpx.Response(200)),
    ) as client:
        with pytest.raises(ValueError):
            client.get("https://api.jquants.com/v1/legacy")


def test_proxy_requires_url_and_token():
    with pytest.raises(ValueError):
        CloudflareJquantsProxyHttpClient(proxy_url="", proxy_token=_TOKEN)
    with pytest.raises(ValueError):
        CloudflareJquantsProxyHttpClient(proxy_url=_PROXY, proxy_token="")


# --------------------------------------------------------------------------- factories

def test_make_http_client_default_is_direct_and_source_agnostic():
    # No jquants_via_cf_proxy -> plain LocalHttpClient, even with proxy on disk.
    assert isinstance(make_http_client("local"), LocalHttpClient)
    with pytest.raises(ValueError):
        make_http_client("magic")


def test_make_jquants_http_auto_uses_proxy_when_configured(monkeypatch, tmp_path):
    monkeypatch.setattr(
        secretsmod, "resolve_proxy_config",
        lambda: ProxyConfig(url=_PROXY, token=_TOKEN),
    )
    client = make_jquants_http("local")  # via_cf_proxy=None -> auto
    assert isinstance(client, CloudflareJquantsProxyHttpClient)


def test_make_jquants_http_auto_falls_back_to_direct(monkeypatch):
    monkeypatch.setattr(secretsmod, "resolve_proxy_config", lambda: None)
    assert isinstance(make_jquants_http("local"), LocalHttpClient)


def test_make_http_client_explicit_proxy_requires_config(monkeypatch):
    monkeypatch.setattr(secretsmod, "resolve_proxy_config", lambda: None)
    with pytest.raises(ValueError):
        make_http_client("local", jquants_via_cf_proxy=True)


# --------------------------------------------------------------------------- secrets

def test_resolve_proxy_config_from_env(monkeypatch):
    monkeypatch.delenv("INGESTION_PROXY_URL", raising=False)
    monkeypatch.delenv("INGESTION_PROXY_TOKEN", raising=False)
    monkeypatch.setenv("INGESTION_PROXY_URL", "https://env.proxy/")
    monkeypatch.setenv("INGESTION_PROXY_TOKEN", "envtok")
    cfg = resolve_proxy_config()
    assert cfg is not None
    assert cfg.url == "https://env.proxy"  # trailing slash stripped
    assert cfg.token == "envtok"


def test_resolve_proxy_config_half_configured_is_none(monkeypatch, tmp_path):
    monkeypatch.delenv("INGESTION_PROXY_URL", raising=False)
    monkeypatch.delenv("INGESTION_PROXY_TOKEN", raising=False)
    monkeypatch.setenv("INGESTION_PROXY_URL", "https://env.proxy")
    # token missing -> None (don't use an unauthenticated proxy)
    assert resolve_proxy_config(config_dir=tmp_path) is None


def test_resolve_proxy_config_from_files(monkeypatch, tmp_path):
    monkeypatch.delenv("INGESTION_PROXY_URL", raising=False)
    monkeypatch.delenv("INGESTION_PROXY_TOKEN", raising=False)
    (tmp_path / "ingestion_proxy_url").write_text("https://file.proxy\n", encoding="utf-8")
    (tmp_path / "ingestion_proxy_token").write_text("filetok\n\n", encoding="utf-8")
    cfg = resolve_proxy_config(config_dir=tmp_path)
    assert cfg == ProxyConfig(url="https://file.proxy", token="filetok")


def test_resolve_proxy_config_nothing_configured(monkeypatch, tmp_path):
    monkeypatch.delenv("INGESTION_PROXY_URL", raising=False)
    monkeypatch.delenv("INGESTION_PROXY_TOKEN", raising=False)
    assert resolve_proxy_config(config_dir=tmp_path) is None
