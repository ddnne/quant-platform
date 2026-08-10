"""HttpClient abstraction — the seam between shared logic and the runtime.

* ``LocalHttpClient`` (httpx) is **required** for the local runtime.
* ``CloudflareHttpClient`` is an intentional **stub**. Under Pattern B the
  Cloudflare side only *reads* storage; fetching happens on local. Phase 1
  does not require Cloudflare fetch to work.

Switching is via ``make_http_client(runtime)`` / env ``INGESTION_RUNTIME`` /
CLI ``--runtime``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Optional, Protocol, Union, runtime_checkable

_DEFAULT_UA = "quant-platform-ingest/0.1 (+personal-research; JST)"


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


def make_http_client(runtime: Union[str, None] = "local", **kwargs: Any) -> HttpClient:
    """Factory keyed by runtime name."""
    rt = (runtime or "local").strip().lower()
    if rt == "local":
        return LocalHttpClient(**kwargs)
    if rt == "cloudflare":
        return CloudflareHttpClient(**kwargs)
    raise ValueError(f"unknown runtime: {runtime!r}")
