"""J-Quants API V2 client.

Base: ``https://api.jquants.com`` — header ``x-api-key``.

Phase 1 endpoints:
  * ``GET /v2/equities/master``     — listed issues
  * ``GET /v2/equities/bars/daily`` — daily OHLCV
  * ``GET /v2/markets/calendar``    — trading calendar / holidays
  * ``GET /v2/fins/summary``        — OPTIONAL (may 403 on some plans; skip)

V2 pagination uses a ``pagination_token`` request param; the response key may
appear as ``pagination_key`` depending on endpoint version, so both are
checked. Transient HTTP errors (429, 5xx) are retried with backoff.

ToS: personal research use only; do not redistribute raw data.
"""

from __future__ import annotations

from typing import Any, Optional

from ..common.http import HttpClient
from ..common.rate_limit import RateLimiter
from ..common.retry import with_retry

BASE = "https://api.jquants.com"


class _Transient(Exception):
    """Retriable transport / rate-limit error."""


class JQuantsClient:
    source = "jquants"

    def __init__(
        self,
        http: HttpClient,
        api_key: str,
        *,
        rate_limiter: Optional[RateLimiter] = None,
        retries: int = 3,
    ) -> None:
        if not api_key:
            raise ValueError("JQuantsClient requires a non-empty api_key")
        self._http = http
        self._api_key = api_key
        self._rl = rate_limiter or RateLimiter(0.5)
        self._retries = retries

    def _headers(self) -> dict[str, str]:
        return {"x-api-key": self._api_key}

    def _get(self, path: str, params: Optional[dict[str, Any]] = None) -> Any:
        url = f"{BASE}{path}"

        def call() -> Any:
            self._rl.acquire()
            resp = self._http.get(url, headers=self._headers(), params=params)
            if resp.status == 429 or 500 <= resp.status < 600:
                raise _Transient(f"{path} -> HTTP {resp.status}")
            if not resp.ok:
                raise RuntimeError(
                    f"J-Quants {path} -> HTTP {resp.status}: {resp.text()[:200]}"
                )
            return resp.json()

        return with_retry(call, retries=self._retries, exceptions=(_Transient,))

    # --- endpoints --------------------------------------------------------

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
            if pagination:
                params["pagination_token"] = pagination
            data = self._get("/v2/equities/master", params=params)
            rows.extend(data.get("info", []) or [])
            pagination = data.get("pagination_key") or data.get("pagination_token")
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
            if pagination:
                params["pagination_token"] = pagination
            data = self._get("/v2/equities/bars/daily", params=params)
            rows.extend(data.get("daily_bars", []) or [])
            pagination = data.get("pagination_key") or data.get("pagination_token")
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
        return data.get("calendar", []) or []

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
        return data.get("summary", []) or []
