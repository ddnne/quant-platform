"""HttpClient abstraction — the seam between shared logic and the runtime.

* ``LocalHttpClient`` (httpx) is **required** for the local runtime.
* ``CloudflareHttpClient`` is an intentional **stub**. Under Pattern B the
  Cloudflare side only *reads* storage; fetching happens on local. Phase 1
  does not require Cloudflare fetch to work.
* ``CloudflareJquantsProxyHttpClient`` routes J-Quants requests through the
  Cloudflare secret-proxy Worker so local runners never hold the J-Quants key
  (see :mod:`ingestion.common.secrets`).

Switching is via ``make_http_client(runtime)`` / env ``INGESTION_RUNTIME`` /
CLI ``--runtime``. Pass ``jquants_via_cf_proxy=`` to opt into (or out of) the
J-Quants proxy for the returned client.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Optional, Protocol, Union, runtime_checkable

_DEFAULT_UA = "quant-platform-ingest/0.1 (+personal-research; JST)"


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


class CloudflareJquantsProxyHttpClient:
    """Route J-Quants requests through the Cloudflare secret-proxy Worker.

    The J-Quants API key lives only on the Worker; the local runner holds just
    a shared ``X-Ingestion-Token``. This client satisfies the ``HttpClient``
    protocol via :meth:`get` — callers (e.g. ``JQuantsClient``) build the same
    ``https://api.jquants.com/v2/...`` URL they would for a direct call; here
    we translate that into a ``POST {proxy}/v1/proxy/jquants`` with body
    ``{"path", "query"}``. The Worker injects ``x-api-key`` upstream, so this
    client **never** sends the J-Quants key (or any caller-supplied
    ``x-api-key`` header) from local — defence in depth against leaking it.

    Underlying POSTs use ``httpx`` (lazy import); a ``transport`` kwarg lets
    tests inject ``httpx.MockTransport`` for fully offline requests, matching
    :class:`LocalHttpClient`.
    """

    name = "cf-jquants-proxy"

    def __init__(
        self,
        *,
        proxy_url: str,
        proxy_token: str,
        user_agent: str = _DEFAULT_UA,
        timeout: float = 30.0,
        transport: Any = None,
    ) -> None:
        import httpx  # lazy: only proxy fetch needs it

        if not proxy_url or not proxy_token:
            raise ValueError("CloudflareJquantsProxyHttpClient needs proxy_url + token")
        self._proxy_url = proxy_url.rstrip("/")
        self._token = proxy_token
        self._timeout = float(timeout)
        kwargs: dict[str, Any] = dict(
            timeout=self._timeout,
            follow_redirects=True,
            headers={"User-Agent": user_agent},
        )
        if transport is not None:
            kwargs["transport"] = transport
        self._client = httpx.Client(**kwargs)

    @staticmethod
    def _path_of(url: str) -> str:
        """Extract the ``/v2/...`` path from a J-Quants URL.

        The Worker rejects anything not under ``/v2/``; we surface that as a
        clear local error rather than a 400 round-trip.
        """
        idx = url.find("/v2/")
        if idx < 0:
            raise ValueError(
                f"jquants proxy: target URL has no /v2/ path to forward: {url!r}"
            )
        return url[idx:]

    def get(
        self,
        url: str,
        *,
        headers: Optional[Mapping[str, str]] = None,
        params: Optional[Mapping[str, Any]] = None,
        timeout: Optional[float] = None,
    ) -> HttpResponse:
        path = self._path_of(url)
        # query: stringified, None/empty dropped — the Worker forwards as-is.
        query: dict[str, str] = {}
        for k, v in (params or {}).items():
            if v is None or v == "":
                continue
            query[str(k)] = str(v)
        # NOTE: caller-supplied `headers` are intentionally NOT forwarded —
        # only X-Ingestion-Token leaves local. The J-Quants key is never sent.
        resp = self._client.post(
            f"{self._proxy_url}/v1/proxy/jquants",
            headers={
                "X-Ingestion-Token": self._token,
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            json={"path": path, "method": "GET", "query": query},
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

    def __enter__(self) -> "CloudflareJquantsProxyHttpClient":
        return self

    def __exit__(self, *exc) -> None:
        self.close()


def make_http_client(
    runtime: Union[str, None] = "local",
    *,
    jquants_via_cf_proxy: bool = False,
    **kwargs: Any,
) -> HttpClient:
    """Factory keyed by runtime name.

    ``jquants_via_cf_proxy`` is a plain opt-in flag (default ``False``):

    * ``False`` (default) -> direct fetch via :class:`LocalHttpClient` /
      :class:`CloudflareHttpClient`. The factory stays source-agnostic, so the
      same client can serve EDINET DB / JSDA too. Bare ``make_http_client("local")``
      therefore always returns a :class:`LocalHttpClient`.
    * ``True`` -> build a :class:`CloudflareJquantsProxyHttpClient` from the
      resolved proxy config (raises if none configured). The returned client
      only forwards ``/v2/`` J-Quants URLs — use it **for J-Quants only**.

    The "use the proxy when configured, for local J-Quants" convenience lives
    in :func:`make_jquants_http` (auto) rather than here, so this general
    factory never silently reroutes non-J-Quants sources.
    """
    if jquants_via_cf_proxy:
        from .secrets import resolve_proxy_config  # local import avoids cycle

        cfg = resolve_proxy_config()
        if cfg is None:
            raise ValueError(
                "jquants_via_cf_proxy requested but no proxy config "
                "(INGESTION_PROXY_URL/INGESTION_PROXY_TOKEN or "
                "~/.config/quant-platform/ingestion_proxy_{url,token}) found"
            )
        # Only forward proxy-relevant kwargs (transport/timeout/ua) to the
        # proxy client; drop any Local-only options the caller mixed in.
        proxy_kwargs: dict[str, Any] = {}
        for k in ("transport", "timeout", "user_agent", "verify"):
            if k in kwargs:
                proxy_kwargs[k] = kwargs[k]
        return CloudflareJquantsProxyHttpClient(
            proxy_url=cfg.url, proxy_token=cfg.token, **proxy_kwargs
        )

    rt = (runtime or "local").strip().lower()
    if rt == "local":
        return LocalHttpClient(**kwargs)
    if rt == "cloudflare":
        return CloudflareHttpClient(**kwargs)
    raise ValueError(f"unknown runtime: {runtime!r}")


def make_jquants_http(
    runtime: Union[str, None] = "local",
    *,
    via_cf_proxy: Optional[bool] = None,
    **kwargs: Any,
) -> HttpClient:
    """Build the J-Quants-specific HTTP client with proxy auto-detection.

    * ``via_cf_proxy=True``  -> force the Cloudflare proxy (raise if no config).
    * ``via_cf_proxy=False`` -> force direct (key-required) fetch.
    * ``via_cf_proxy=None`` (default) -> on the **local** runtime, use the
      proxy when proxy config is available; otherwise direct. This is the
      "local runner with the Worker configured needs no local key" default.
    """
    rt = (runtime or "local").strip().lower()
    use_proxy = via_cf_proxy
    if use_proxy is None:
        from .secrets import resolve_proxy_config

        use_proxy = rt == "local" and resolve_proxy_config() is not None
    return make_http_client(runtime, jquants_via_cf_proxy=use_proxy, **kwargs)
