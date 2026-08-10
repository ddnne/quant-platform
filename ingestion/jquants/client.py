"""J-Quants API V2 client — full Premium + add-on catalog.

Base: ``https://api.jquants.com`` — header ``x-api-key`` (or, when fetching
via the Cloudflare secret-proxy, none — the Worker injects the key upstream;
see :class:`ingestion.common.http.CloudflareJquantsProxyHttpClient`).

Every dataset in :mod:`ingestion.jquants.catalog` is reachable through the
generic :meth:`JQuantsClient.fetch_dataset`; the four Phase-1 methods
(:meth:`listed_info`, :meth:`daily_bars`, :meth:`market_calendar`,
:meth:`fins_summary`) remain as thin wrappers for back-compat.

V2 envelope: records nest under a top-level **``data``** key. Some legacy
fixtures use per-endpoint keys (``info`` / ``daily_bars`` / ``calendar`` /
``summary``); those are accepted as secondary fallbacks via :func:`_records`.

V2 pagination: the **request** param is ``pagination_key`` (not
``pagination_token``). The response key may appear as either
``pagination_key`` (standard) or ``pagination_token`` (legacy).

Transient HTTP errors (429, 5xx) and transport faults (connection / timeout)
are retried with exponential backoff. Rate limit defaults to a Premium-safe
~8 rps (480/min, under the 500/min cap). ToS: personal research use only; do
not redistribute raw data.
"""

from __future__ import annotations

from typing import Any, Callable, Optional

from ..common.http import HttpClient, transport_exception_types
from ..common.rate_limit import RateLimiter
from ..common.retry import with_retry
from . import catalog

BASE = catalog.BASE

# Request-param aliases -> canonical V2 names. Lets callers pass the readable
# ``from_date``/``to_date`` while the wire uses ``from``/``to``.
_PARAM_ALIASES = {"from_date": "from", "to_date": "to"}


class _Transient(Exception):
    """Retriable transport / rate-limit error."""


def _records(payload: Any, *fallbacks: str) -> list:
    """Extract the records list from a V2 response envelope.

    V2 nests records under ``data``. ``fallbacks`` are older per-endpoint
    keys (``info`` / ``daily_bars`` / ...) checked only when ``data`` is
    absent — kept so legacy fixtures and tests keep working.
    """
    if not isinstance(payload, dict):
        return []
    rows = payload.get("data")
    if rows is None:
        for k in fallbacks:
            if k in payload:
                rows = payload.get(k)
                break
    if rows is None:
        return []
    return rows if isinstance(rows, list) else []


class JQuantsClient:
    source = "jquants"

    def __init__(
        self,
        http: HttpClient,
        api_key: str = "",
        *,
        rate_limiter: Optional[RateLimiter] = None,
        retries: int = 3,
        sleep: Callable[[float], None] = None,
    ) -> None:
        # ``api_key`` is optional: direct fetch needs it, but the Cloudflare
        # proxy client injects the key upstream so local proxy callers pass "".
        self._http = http
        self._api_key = api_key or ""
        self._rl = rate_limiter or RateLimiter(catalog.PREMIUM_MIN_INTERVAL)
        self._retries = retries
        self._sleep = sleep  # None -> with_retry default (time.sleep)
        self._transport_exc = transport_exception_types()

    @property
    def via_proxy(self) -> bool:
        """True when the underlying http client is the Cloudflare proxy."""
        return getattr(self._http, "name", "") == "cf-jquants-proxy"

    def _headers(self) -> dict[str, str]:
        # Never required in proxy mode (the proxy drops caller headers anyway,
        # so this is defence in depth rather than a correctness path).
        return {"x-api-key": self._api_key} if self._api_key else {}

    def _get(self, path: str, params: Optional[dict[str, Any]] = None) -> Any:
        url = f"{BASE}{path}"

        def call() -> Any:
            self._rl.acquire()
            try:
                resp = self._http.get(url, headers=self._headers(), params=params)
            except self._transport_exc as exc:
                # Connection / timeout faults are transient -> retriable.
                raise _Transient(f"{path} -> transport error: {exc}") from exc
            if resp.status == 429 or 500 <= resp.status < 600:
                raise _Transient(f"{path} -> HTTP {resp.status}")
            if not resp.ok:
                raise RuntimeError(
                    f"J-Quants {path} -> HTTP {resp.status}: {resp.text()[:200]}"
                )
            return resp.json()

        kwargs: dict[str, Any] = {"retries": self._retries, "exceptions": (_Transient,)}
        if self._sleep is not None:
            kwargs["sleep"] = self._sleep
        return with_retry(call, **kwargs)

    # --- generic catalog access -----------------------------------------

    @staticmethod
    def _normalize_params(params: Optional[dict[str, Any]]) -> dict[str, Any]:
        """Drop empties + apply ``from_date``/``to_date`` aliases."""
        out: dict[str, Any] = {}
        for k, v in (params or {}).items():
            if v is None or v == "":
                continue
            out[_PARAM_ALIASES.get(k, k)] = v
        return out

    def fetch_paginated(
        self, path: str, params: Optional[dict[str, Any]] = None
    ) -> list[dict]:
        """Page through ``GET path`` until no ``pagination_key`` is returned.

        ``params`` is the caller's request params (already canonical); the
        loop adds ``pagination_key`` on follow-up calls without mutating the
        caller's dict.
        """
        base = self._normalize_params(params)
        rows: list[dict] = []
        pagination: Optional[str] = None
        while True:
            req = dict(base)
            if pagination:
                req["pagination_key"] = pagination
            data = self._get(path, params=req)
            rows.extend(_records(data))
            pagination = data.get("pagination_key") if isinstance(data, dict) else None
            if not pagination:
                # legacy response key fallback
                pagination = (
                    data.get("pagination_token") if isinstance(data, dict) else None
                )
            if not pagination:
                break
        return rows

    def fetch_dataset(self, dataset_id: str, **params: Any) -> list[dict]:
        """Fetch any catalog dataset by id, paginating as needed.

        Example: ``client.fetch_dataset("equities_bars_daily", code="8697",
        from_date="2025-04-01", to_date="2025-04-05")``.
        """
        return self.fetch_paginated(catalog.path_of(dataset_id), params=params)

    # --- Phase-1 convenience wrappers (back-compat) ---------------------

    def listed_info(
        self, *, date: Optional[str] = None, code: Optional[str] = None
    ) -> list[dict]:
        params: dict[str, Any] = {}
        if date:
            params["date"] = date
        if code:
            params["code"] = code
        rows: list[dict] = []
        pagination = None
        while True:
            req = dict(params)
            if pagination:
                req["pagination_key"] = pagination
            data = self._get("/v2/equities/master", params=req)
            rows.extend(_records(data, "info"))
            pagination = data.get("pagination_key") if isinstance(data, dict) else None
            if not pagination:
                # legacy response key fallback
                pagination = (
                    data.get("pagination_token") if isinstance(data, dict) else None
                )
            if not pagination:
                break
        return rows

    def daily_bars(
        self,
        *,
        code: Optional[str] = None,
        date: Optional[str] = None,
        from_date: Optional[str] = None,
        to_date: Optional[str] = None,
    ) -> list[dict]:
        params: dict[str, Any] = {}
        if code:
            params["code"] = code
        if date:
            params["date"] = date
        if from_date:
            params["from"] = from_date
        if to_date:
            params["to"] = to_date
        rows: list[dict] = []
        pagination = None
        while True:
            req = dict(params)
            if pagination:
                req["pagination_key"] = pagination
            data = self._get("/v2/equities/bars/daily", params=req)
            rows.extend(_records(data, "daily_bars"))
            pagination = data.get("pagination_key") if isinstance(data, dict) else None
            if not pagination:
                pagination = (
                    data.get("pagination_token") if isinstance(data, dict) else None
                )
            if not pagination:
                break
        return rows

    def market_calendar(
        self,
        *,
        from_date: Optional[str] = None,
        to_date: Optional[str] = None,
        holiday_division: Optional[str] = None,
    ) -> list[dict]:
        params: dict[str, Any] = {}
        if from_date:
            params["from"] = from_date
        if to_date:
            params["to"] = to_date
        if holiday_division:
            params["holidaydivision"] = holiday_division
        data = self._get("/v2/markets/calendar", params=params)
        return _records(data, "calendar")

    def fins_summary(
        self, *, code: Optional[str] = None, date: Optional[str] = None
    ) -> list[dict]:  # exercised via mock in tests
        """OPTIONAL endpoint. May 403/404 on some plans — callers must skip."""
        params: dict[str, Any] = {}
        if code:
            params["code"] = code
        if date:
            params["date"] = date
        data = self._get("/v2/fins/summary", params=params)
        return _records(data, "summary")
