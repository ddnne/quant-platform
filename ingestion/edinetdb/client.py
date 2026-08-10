"""EDINET DB client (best-effort V1 paths).

Endpoints (Phase 1, configurable rate):
  * ``GET /v1/companies``                     — search/list companies
  * ``GET /v1/companies/{code}``              — company detail
  * ``GET /v1/companies/{code}/financials``   — financials by code

Header: ``X-API-Key``. Response shapes are normalized defensively; see
``docs/data_sources.md`` for the 仮 field map.
"""

from __future__ import annotations

from typing import Any, Callable, Optional

from ..common.http import HttpClient, transport_exception_types
from ..common.rate_limit import RateLimiter
from ..common.retry import with_retry

BASE = "https://edinetdb.jp/v1"


class _Transient(Exception):
    pass


class EdinetDbClient:
    source = "edinetdb"

    def __init__(
        self,
        http: HttpClient,
        api_key: str,
        *,
        rate_limiter: Optional[RateLimiter] = None,
        retries: int = 3,
        sleep: Callable[[float], None] = None,
    ) -> None:
        if not api_key:
            raise ValueError("EdinetDbClient requires a non-empty api_key")
        self._http = http
        self._api_key = api_key
        self._rl = rate_limiter or RateLimiter(0.5)
        self._retries = retries
        self._sleep = sleep  # None -> with_retry default (time.sleep)
        self._transport_exc = transport_exception_types()

    def _headers(self) -> dict[str, str]:
        return {"X-API-Key": self._api_key}

    def _get(self, path: str, params: Optional[dict[str, Any]] = None) -> Any:
        url = f"{BASE}{path}"

        def call() -> Any:
            self._rl.acquire()
            try:
                resp = self._http.get(url, headers=self._headers(), params=params)
            except self._transport_exc as exc:
                raise _Transient(f"{path} -> transport error: {exc}") from exc
            if resp.status == 429 or 500 <= resp.status < 600:
                raise _Transient(f"{path} -> HTTP {resp.status}")
            if not resp.ok:
                raise RuntimeError(
                    f"EDINET DB {path} -> HTTP {resp.status}: {resp.text()[:200]}"
                )
            return resp.json()

        kwargs: dict[str, Any] = {"retries": self._retries, "exceptions": (_Transient,)}
        if self._sleep is not None:
            kwargs["sleep"] = self._sleep
        return with_retry(call, **kwargs)

    def list_companies(
        self, *, q: Optional[str] = None, limit: Optional[int] = None
    ) -> list[dict]:
        params: dict[str, Any] = {}
        if q:
            params["q"] = q
        if limit:
            params["limit"] = limit
        data = self._get("/companies", params=params)
        # Tolerate either a bare list or an envelope.
        if isinstance(data, list):
            return data
        return data.get("companies", []) or data.get("data", []) or []

    def company_detail(self, code: str) -> dict:
        return self._get(f"/companies/{code}")

    def financials(self, code: str) -> list[dict]:
        data = self._get(f"/companies/{code}/financials")
        if isinstance(data, list):
            return data
        return data.get("financials", []) or data.get("data", []) or []
