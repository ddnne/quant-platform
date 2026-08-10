"""Tests for the HttpClient abstraction.

* FakeHttpClient (offline) proves the protocol shape.
* LocalHttpClient is exercised with httpx.MockTransport — no real network.
* CloudflareHttpClient is a stub that refuses to fetch (Pattern B).
"""

from __future__ import annotations

import json

import pytest

httpx = pytest.importorskip("httpx")

from ingestion.common.http import (  # noqa: E402
    CloudflareHttpClient,
    HttpResponse,
    LocalHttpClient,
    HttpClient,
    make_http_client,
)


def test_httpresponse_helpers():
    r = HttpResponse(
        status=200,
        headers={"content-type": "application/json"},
        body=json.dumps({"a": 1}).encode("utf-8"),
        url="https://x/y",
    )
    assert r.ok
    assert r.json() == {"a": 1}
    assert r.text().startswith("{")


def test_local_http_client_uses_transport_and_params():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["headers"] = dict(request.headers)
        return httpx.Response(
            200, json={"ok": True}, headers={"x-test": "1"}
        )

    transport = httpx.MockTransport(handler)
    with LocalHttpClient(user_agent="ua-test", transport=transport) as client:
        resp = client.get(
            "https://api.example.com/v2/things",
            params={"code": "8697", "from": "2025-04-01"},
            headers={"x-api-key": "secret"},
        )

    assert resp.status == 200
    assert resp.ok
    assert resp.json() == {"ok": True}
    # params merged into URL
    assert "code=8697" in seen["url"]
    assert "from=2025-04-01" in seen["url"]
    # headers passed through, UA set
    assert seen["headers"]["x-api-key"] == "secret"
    assert seen["headers"]["user-agent"] == "ua-test"


def test_local_http_client_records_status_and_body():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, content=b"boom")

    with LocalHttpClient(transport=httpx.MockTransport(handler)) as client:
        resp = client.get("https://api.example.com/x")
    assert resp.status == 500
    assert not resp.ok
    assert resp.body == b"boom"
    assert resp.text() == "boom"


def test_cloudflare_client_refuses_to_fetch():
    client = CloudflareHttpClient()
    with pytest.raises(NotImplementedError):
        client.get("https://anything")


def test_make_http_client_dispatch():
    assert isinstance(make_http_client("local"), LocalHttpClient)
    assert isinstance(make_http_client("cloudflare"), CloudflareHttpClient)
    assert isinstance(make_http_client(None), LocalHttpClient)
    with pytest.raises(ValueError):
        make_http_client("magic")


def test_fake_http_matches_protocol(fake_http):
    # The FakeHttpClient from conftest must satisfy the structural protocol.
    fake_http.route("https://x/y", json_data={"ok": 1})
    resp = fake_http.get("https://x/y", params={"a": "b"})
    assert isinstance(fake_http, HttpClient)
    assert resp.ok
    assert resp.json() == {"ok": 1}
    assert fake_http.calls[0]["params"] == {"a": "b"}
