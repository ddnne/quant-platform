"""J-Quants API V2 client.

Base: ``https://api.jquants.com`` — header ``x-api-key``.

Phase 1 endpoints:
  * ``GET /v2/equities/master``     — listed issues
  * ``GET /v2/equities/bars/daily`` — daily OHLCV
  * ``GET /v2/markets/calendar``    — trading calendar / holidays
  * ``GET /v2/fins/summary``        — OPTIONAL (may 403 on some plans; skip)

V2 places records under a top-level **``data``** envelope. Some shims / tests
still use the older per-endpoint keys (``info`` / ``daily_bars`` /
``calendar`` / ``summary``); those are accepted as secondary fallbacks via
:func:`_records`.

V2 pagination: the **request** param is ``pagination_key`` (not
``pagination_token``). The response key may still appear as
``pagination_key`` (checked first) or ``pagination_token`` (legacy).

Transient HTTP errors (429, 5xx) and transport faults (connection / timeout)
are retried with exponential backoff. ToS: personal research use only; do not
redistribute raw data.
"""

from __future__ import annotations

from typing import Any, Callable, Optional

from ..common.http import HttpClient, transport_exception_types
from ..common.rate_limit import RateLimiter
from ..common.retry import with_retry

BASE = "https://api.jquants.com"


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
        api_key: str,
        *,
        rate_limiter: Optional[RateLimiter] = None,
        retries: int = 3,
        sleep: Callable[[float], None] = None,
    ) -> None:
        if not api_key:
            raise ValueError("JQuantsClient requires a non-empty api_key")
        self._http = http
        self._api_key = api_key
        self._rl = rate_limiter or RateLimiter(0.5)
        self._retries = retries
        self._sleep = sleep  # None -> with_retry default (time.sleep)
        self._transport_exc = transport_exception_types()

    def _headers(self) -> dict[str, str]:
        return {"x-api-key": self._api_key}

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
                params["pagination_key"] = pagination
            data = self._get("/v2/equities/master", params=params)
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
            if pagination:
                params["pagination_key"] = pagination
            data = self._get("/v2/equities/bars/daily", params=params)
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
