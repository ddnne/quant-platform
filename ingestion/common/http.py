"""HttpClient abstraction — the seam between shared logic and the runtime.

* ``LocalHttpClient`` (httpx) is **required** for the local runtime.
* ``CloudflareHttpClient`` is an intentional **stub**. Under Pattern B the
  Cloudflare side only *reads* storage; fetching happens on local. Phase 1
  does not require Cloudflare fetch to work.

Switching is via ``make_http_client(runtime)`` / env ``INGESTION_RUNTIME`` /
CLI ``--runtime``.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Mapping, Optional, Protocol, Union, runtime_checkable
from urllib.parse import parse_qsl, urlsplit

from .secrets import ProxyConfig, proxy_endpoint

_DEFAULT_UA = "quant-platform-ingest/0.1 (+personal-research; JST)"

#: Host that may be routed through the Cloudflare J-Quants proxy.
_JQ_HOST = "api.jquants.com"


def transport_exception_types() -> tuple:
    """Exception types the HTTP client raises on connection / timeout faults.

    Used by clients to wrap transport errors as retriable. ``httpx`` is
    imported lazily (it is a local-runtime dependency only); when absent the
    tuple falls back to ``OSError`` so the module still loads.
    """
    try:  # pragma: no cover - depends on optional dep presence
        import httpx
    except ImportError:  # pragma: no cover
        return (OSError,)
    return (httpx.TransportError, httpx.TimeoutException, OSError)


@dataclass(frozen=True)
class HttpResponse:
    """Runtime-agnostic HTTP response."""

    status: int
    headers: Mapping[str, str]
    body: bytes
    url: str

    @property
    def ok(self) -> bool:
        return 200 <= self.status < 300

    def text(self, encoding: str = "utf-8") -> str:
        return bytes(self.body).decode(encoding, errors="replace")

    def json(self) -> Any:
        import json

        return json.loads(self.text())


@runtime_checkable
class HttpClient(Protocol):
    name: str

    def get(
        self,
        url: str,
        *,
        headers: Optional[Mapping[str, str]] = None,
        params: Optional[Mapping[str, Any]] = None,
        timeout: float = 30.0,
    ) -> HttpResponse: ...


class LocalHttpClient:
    """HTTP client backed by ``httpx``. Local runtime only.

    ``httpx`` is imported lazily so the module loads even in environments
    without it (the Cloudflare stub needs no httpx). A ``transport`` kwarg
    lets tests inject ``httpx.MockTransport`` for fully offline requests.
    """

    name = "local"

    def __init__(
        self,
        *,
        user_agent: str = _DEFAULT_UA,
        timeout: float = 30.0,
        verify: bool = True,
        transport: Any = None,
    ) -> None:
        import httpx  # lazy: only the local runtime needs it

        self._timeout = float(timeout)
        kwargs: dict[str, Any] = dict(
            timeout=self._timeout,
            verify=verify,
            follow_redirects=True,
            headers={"User-Agent": user_agent},
        )
        if transport is not None:
            kwargs["transport"] = transport
        self._client = httpx.Client(**kwargs)

    def get(
        self,
        url: str,
        *,
        headers: Optional[Mapping[str, str]] = None,
        params: Optional[Mapping[str, Any]] = None,
        timeout: Optional[float] = None,
    ) -> HttpResponse:
        resp = self._client.get(
            url,
            headers=dict(headers or {}),
            params=dict(params or {}),
            timeout=timeout if timeout is not None else self._timeout,
        )
        return HttpResponse(
            status=resp.status_code,
            headers=dict(resp.headers),
            body=resp.content,
            url=str(resp.url),
        )

    def close(self) -> None:
        try:
            self._client.close()
        except Exception:  # pragma: no cover - best effort
            pass

    def __enter__(self) -> "LocalHttpClient":
        return self

    def __exit__(self, *exc) -> None:
        self.close()


class CloudflareHttpClient:
    """Cloudflare-runtime stub.

    Pattern B: fetch on local -> store raw/structured -> Cloudflare reads
    storage only. So this client deliberately does **not** issue real HTTP.
    Asking it to fetch raises ``NotImplementedError`` rather than failing
    silently. (A later phase may implement fetch via Cloudflare's ``fetch()``
    binding if/when direct fetch from the edge is required.)
    """

    name = "cloudflare"

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        pass

    def get(self, *args: Any, **kwargs: Any) -> HttpResponse:
        raise NotImplementedError(
            "CloudflareHttpClient.fetch is intentionally unimplemented in "
            "Phase 1. Pattern B: fetch on local runtime; CF reads storage only."
        )


class ProxyHttpClient:
    """Routes J-Quants calls through the Cloudflare ``ingestion-secrets`` proxy.

    The Worker (``platform/workers/ingestion-secrets``) holds
    ``JQUANTS_API_KEY`` and injects the upstream ``x-api-key`` itself, so the
    local runner never sees the key. This client translates a direct call —

        GET https://api.jquants.com/v2/<path>?<params>

    — into a proxy call::

        POST <proxy_endpoint>
        X-Ingestion-Token: <proxy_token>
        {"path": "/v2/<path>", "method": "GET", "query": {...}}

    and wraps the Worker's passthrough response (upstream status + body) in an
    :class:`HttpResponse`. Any client-supplied ``x-api-key`` header is dropped
    here — the Worker ignores it anyway and uses its own secret.

    Only ``api.jquants.com`` URLs are proxied; anything else raises so a
    misconfigured JSDA/other fetch cannot accidentally leak through the proxy.
    """

    name = "local-proxy"

    def __init__(
        self,
        proxy: ProxyConfig,
        *,
        user_agent: str = _DEFAULT_UA,
        timeout: float = 30.0,
        transport: Any = None,
    ) -> None:
        import httpx  # lazy: local runtime dependency

        self._endpoint = proxy_endpoint(proxy)
        self._token = proxy.proxy_token
        self._timeout = float(timeout)
        kwargs: dict[str, Any] = dict(
            timeout=self._timeout,
            follow_redirects=True,
            headers={"User-Agent": user_agent},
        )
        if transport is not None:
            kwargs["transport"] = transport
        self._client = httpx.Client(**kwargs)

    def get(
        self,
        url: str,
        *,
        headers: Optional[Mapping[str, str]] = None,
        params: Optional[Mapping[str, Any]] = None,
        timeout: Optional[float] = None,
    ) -> HttpResponse:
        u = urlsplit(url)
        if u.netloc != _JQ_HOST:
            raise RuntimeError(
                f"ProxyHttpClient only proxies {_JQ_HOST}; refusing to route {url}"
            )
        query: dict[str, str] = {}
        for k, v in parse_qsl(u.query, keep_blank_values=True):
            query[k] = v
        if params:
            for k, v in params.items():
                if v is None:
                    continue
                query[k] = str(v)
        body = json.dumps(
            {"path": u.path or "/", "method": "GET", "query": query}
        ).encode("utf-8")
        # Drop any caller-supplied x-api-key: the Worker injects its own.
        out_headers: dict[str, str] = {"content-type": "application/json"}
        if self._token:
            out_headers["X-Ingestion-Token"] = self._token
        resp = self._client.post(
            self._endpoint,
            content=body,
            headers=out_headers,
            timeout=timeout if timeout is not None else self._timeout,
        )
        return HttpResponse(
            status=resp.status_code,
            headers=dict(resp.headers),
            body=resp.content,
            url=str(resp.url),
        )

    def close(self) -> None:
        try:
            self._client.close()
        except Exception:  # pragma: no cover - best effort
            pass

    def __enter__(self) -> "ProxyHttpClient":
        return self

    def __exit__(self, *exc) -> None:
        self.close()


def make_http_client(runtime: Union[str, None] = "local", **kwargs: Any) -> HttpClient:
    """Factory keyed by runtime name."""
    rt = (runtime or "local").strip().lower()
    if rt == "local":
        return LocalHttpClient(**kwargs)
    if rt == "cloudflare":
        return CloudflareHttpClient(**kwargs)
    raise ValueError(f"unknown runtime: {runtime!r}")
