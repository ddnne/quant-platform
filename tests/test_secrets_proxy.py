"""J-Quants secret resolution and the Cloudflare proxy HTTP client.

Covers:

* :func:`ingestion.common.secrets.resolve_jquants` priority — proxy wins over
  env, env wins over none; config dir override; broken/missing config falls
  through cleanly.
* :func:`ingestion.common.secrets.proxy_endpoint` normalization (origin vs full
  route, trailing slash).
* :class:`ingestion.common.http.ProxyHttpClient` translates a direct J-Quants
  GET into the Worker proxy POST (path/method/query + ``X-Ingestion-Token``)
  and drops the caller's ``x-api-key`` — exercised offline via
  ``httpx.MockTransport``.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

httpx = pytest.importorskip("httpx")

from ingestion.common.http import ProxyHttpClient  # noqa: E402
from ingestion.common.secrets import (  # noqa: E402
    PROXY_API_KEY_SENTINEL,
    PROXY_CONFIG_FILENAME,
    ProxyConfig,
    config_dir,
    load_proxy_config,
    proxy_endpoint,
    resolve_jquants,
)


# --------------------------------------------------------------------------- resolve_jquants priority

def test_resolve_none_when_no_proxy_and_no_env(monkeypatch, tmp_path):
    monkeypatch.setenv("QUANT_PLATFORM_CONFIG_DIR", str(tmp_path))
    auth = resolve_jquants(env={})
    assert auth.via == "none"
    assert auth.api_key == ""
    assert auth.effective_api_key == ""
    assert auth.proxy is None


def test_resolve_env_when_no_proxy(monkeypatch, tmp_path):
    monkeypatch.setenv("QUANT_PLATFORM_CONFIG_DIR", str(tmp_path))
    auth = resolve_jquants(env={"JQUANTS_API_KEY": "abc123"})
    assert auth.via == "env"
    assert auth.api_key == "abc123"
    assert auth.effective_api_key == "abc123"
    assert auth.proxy is None


def test_resolve_proxy_wins_over_env(monkeypatch, tmp_path):
    _write_proxy(tmp_path, "https://jq-proxy.example.workers.dev", token="tok")
    monkeypatch.setenv("QUANT_PLATFORM_CONFIG_DIR", str(tmp_path))
    # env key present too — proxy still wins so the local box never uses a local key
    auth = resolve_jquants(env={"JQUANTS_API_KEY": "should-not-be-used"})
    assert auth.via == "proxy"
    assert auth.proxy is not None
    assert auth.proxy.proxy_url == "https://jq-proxy.example.workers.dev"
    assert auth.proxy.proxy_token == "tok"
    # effective key is the sentinel, never the real key (held on Cloudflare)
    assert auth.effective_api_key == PROXY_API_KEY_SENTINEL


def test_resolve_reads_real_environ_by_default(monkeypatch, tmp_path):
    monkeypatch.setenv("QUANT_PLATFORM_CONFIG_DIR", str(tmp_path))
    monkeypatch.setenv("JQUANTS_API_KEY", "from-environ")
    assert resolve_jquants().via == "env"
    assert resolve_jquants().api_key == "from-environ"


# --------------------------------------------------------------------------- config dir + load_proxy_config

def test_config_dir_override(monkeypatch, tmp_path):
    monkeypatch.setenv("QUANT_PLATFORM_CONFIG_DIR", str(tmp_path / "deep"))
    assert config_dir() == Path(tmp_path / "deep")


def test_load_proxy_config_missing_file_returns_none(monkeypatch, tmp_path):
    monkeypatch.setenv("QUANT_PLATFORM_CONFIG_DIR", str(tmp_path))
    assert load_proxy_config() is None


def test_load_proxy_config_broken_json_returns_none(monkeypatch, tmp_path):
    (tmp_path / PROXY_CONFIG_FILENAME).write_text("{not json", encoding="utf-8")
    monkeypatch.setenv("QUANT_PLATFORM_CONFIG_DIR", str(tmp_path))
    assert load_proxy_config() is None


def test_load_proxy_config_missing_url_returns_none(monkeypatch, tmp_path):
    _write_proxy(tmp_path, "", token="tok")
    monkeypatch.setenv("QUANT_PLATFORM_CONFIG_DIR", str(tmp_path))
    assert load_proxy_config() is None


def test_load_proxy_config_token_optional(monkeypatch, tmp_path):
    _write_proxy(tmp_path, "https://p.example.workers.dev")
    monkeypatch.setenv("QUANT_PLATFORM_CONFIG_DIR", str(tmp_path))
    cfg = load_proxy_config()
    assert cfg is not None
    assert cfg.proxy_url == "https://p.example.workers.dev"
    assert cfg.proxy_token == ""


# --------------------------------------------------------------------------- proxy_endpoint normalization

def test_proxy_endpoint_appends_route_to_origin():
    url = proxy_endpoint(ProxyConfig("https://p.example.workers.dev"))
    assert url == "https://p.example.workers.dev/v1/proxy/jquants"


def test_proxy_endpoint_accepts_full_route():
    full = "https://p.example.workers.dev/v1/proxy/jquants"
    assert proxy_endpoint(ProxyConfig(full)) == full


def test_proxy_endpoint_strips_trailing_slash():
    url = proxy_endpoint(ProxyConfig("https://p.example.workers.dev/"))
    assert url == "https://p.example.workers.dev/v1/proxy/jquants"


def test_proxy_endpoint_empty_url_raises():
    with pytest.raises(ValueError):
        proxy_endpoint(ProxyConfig(""))


# --------------------------------------------------------------------------- ProxyHttpClient translation

def test_proxy_client_translates_get_to_proxy_post():
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["method"] = request.method
        captured["url"] = str(request.url)
        captured["headers"] = dict(request.headers)
        captured["body"] = json.loads(request.content.decode("utf-8"))
        return httpx.Response(
            200,
            content=json.dumps({"data": [{"Code": "8697"}]}).encode("utf-8"),
            headers={"content-type": "application/json"},
        )

    proxy = ProxyConfig(
        "https://p.example.workers.dev", proxy_token="secret-token"
    )
    transport = httpx.MockTransport(handler)
    client = ProxyHttpClient(proxy, transport=transport)

    resp = client.get(
        "https://api.jquants.com/v2/equities/master",
        headers={"x-api-key": "local-leak-attempt"},
        params={"code": "8697", "pagination_key": "pg1"},
    )

    # The Worker receives a POST to the proxy route, not a GET to J-Quants.
    assert captured["method"] == "POST"
    assert captured["url"] == "https://p.example.workers.dev/v1/proxy/jquants"
    # The token authorizes the proxy call; the caller's x-api-key is dropped
    # (the Worker injects its own).
    assert captured["headers"]["x-ingestion-token"] == "secret-token"
    assert "x-api-key" not in captured["headers"]
    # path / method / query are forwarded for the Worker to reconstruct.
    assert captured["body"] == {
        "path": "/v2/equities/master",
        "method": "GET",
        "query": {"code": "8697", "pagination_key": "pg1"},
    }
    # The upstream body is surfaced verbatim through the runtime-agnostic shape.
    assert resp.status == 200
    assert resp.ok
    assert resp.json() == {"data": [{"Code": "8697"}]}


def test_proxy_client_preserves_upstream_error_status():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, content=b'{"error":"forbidden"}')

    client = ProxyHttpClient(
        ProxyConfig("https://p.example.workers.dev"),
        transport=httpx.MockTransport(handler),
    )
    resp = client.get("https://api.jquants.com/v2/fins/summary")
    assert resp.status == 403
    assert not resp.ok


def test_proxy_client_refuses_non_jquants_urls():
    client = ProxyHttpClient(
        ProxyConfig("https://p.example.workers.dev"),
        transport=httpx.MockTransport(lambda req: httpx.Response(200)),
    )
    # JSDA / arbitrary hosts must never be routed through the J-Quants proxy.
    with pytest.raises(RuntimeError):
        client.get("https://www.jsda.or.jp/x/saiken.csv")


def test_proxy_client_no_token_omits_header():
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["headers"] = dict(request.headers)
        return httpx.Response(200, content=b"{}")

    client = ProxyHttpClient(
        ProxyConfig("https://p.example.workers.dev"),  # no token
        transport=httpx.MockTransport(handler),
    )
    client.get("https://api.jquants.com/v2/markets/calendar")
    assert "x-ingestion-token" not in captured["headers"]


# --------------------------------------------------------------------------- helpers

def _write_proxy(base: Path, url: str, *, token: str = "") -> None:
    payload = {"proxy_url": url}
    if token:
        payload["proxy_token"] = token
    (base / PROXY_CONFIG_FILENAME).write_text(
        json.dumps(payload), encoding="utf-8"
    )
