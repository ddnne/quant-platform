"""JSDA fetcher — local runtime only.

Scrapes the index page for data-file links, then GETs the chosen file. A
per-source User-Agent and a conservative rate limit are applied; JSDA pages
are sensitive to aggressive scraping.

Transient failures (429, 5xx, connection / timeout faults) are retried with
exponential backoff via :func:`with_retry`.
"""

from __future__ import annotations

from typing import Any, Callable, List, Optional

from ..common.http import HttpClient, transport_exception_types
from ..common.rate_limit import RateLimiter
from ..common.retry import with_retry
from .urls import (
    index_url,
    pick_latest,
    pick_repo_file,
    repo_index_url,
    resolve_download_links,
    resolve_repo_links,
)

JSDA_USER_AGENT = "quant-platform-ingest/0.1 (+personal-research; JSDA bond stats)"


class _Transient(Exception):
    """Retriable JSDA transport / server error."""


class JsdaFetcher:
    source = "jsda"

    def __init__(
        self,
        http: HttpClient,
        *,
        rate_limiter: Optional[RateLimiter] = None,
        retries: int = 3,
        sleep: Callable[[float], None] = None,
    ) -> None:
        self._http = http
        self._rl = rate_limiter or RateLimiter(1.0)  # be polite
        self._retries = retries
        self._sleep = sleep  # None -> with_retry default (time.sleep)
        self._transport_exc = transport_exception_types()

    def _get(self, url: str):
        def call():
            self._rl.acquire()
            try:
                resp = self._http.get(url, headers={"User-Agent": JSDA_USER_AGENT})
            except self._transport_exc as exc:
                raise _Transient(f"JSDA {url} -> transport error: {exc}") from exc
            if resp.status == 429 or 500 <= resp.status < 600:
                raise _Transient(f"JSDA {url} -> HTTP {resp.status}")
            if not resp.ok:
                raise RuntimeError(
                    f"JSDA {url} -> HTTP {resp.status}: {resp.text()[:200]}"
                )
            return resp

        kwargs: dict[str, Any] = {"retries": self._retries, "exceptions": (_Transient,)}
        if self._sleep is not None:
            kwargs["sleep"] = self._sleep
        try:
            return with_retry(call, **kwargs)
        except _Transient as exc:
            # Surface as a plain runtime error at the public boundary.
            raise RuntimeError(str(exc)) from exc

    def list_files(self) -> List[str]:
        """GET the index page and return resolved data-file URLs."""
        return resolve_download_links(self._get(index_url()).text())

    def pick(self, links: Optional[List[str]] = None) -> Optional[str]:
        return pick_latest(links if links is not None else self.list_files())

    def fetch_file(self, url: str) -> bytes:
        return self._get(url).body

    # --- repo rate (東京レポ・レート) ----------------------------------------

    def list_repo_files(self) -> List[str]:
        """GET the TRR index page and return resolved data-file URLs."""
        return resolve_repo_links(self._get(repo_index_url()).text())

    def pick_repo(self, links: Optional[List[str]] = None) -> Optional[str]:
        return pick_repo_file(links if links is not None else self.list_repo_files())
