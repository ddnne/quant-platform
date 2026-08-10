"""JSDA fetcher — local runtime only.

Scrapes the index page for data-file links, then GETs the chosen file. A
per-source User-Agent and a conservative rate limit are applied; JSDA pages
are sensitive to aggressive scraping.
"""

from __future__ import annotations

from typing import List, Optional

from ..common.http import HttpClient
from ..common.rate_limit import RateLimiter
from .urls import index_url, pick_latest, resolve_download_links

JSDA_USER_AGENT = "quant-platform-ingest/0.1 (+personal-research; JSDA bond stats)"


class JsdaFetcher:
    source = "jsda"

    def __init__(
        self,
        http: HttpClient,
        *,
        rate_limiter: Optional[RateLimiter] = None,
    ) -> None:
        self._http = http
        self._rl = rate_limiter or RateLimiter(1.0)  # be polite

    def list_files(self) -> List[str]:
        """GET the index page and return resolved data-file URLs."""
        self._rl.acquire()
        resp = self._http.get(
            index_url(), headers={"User-Agent": JSDA_USER_AGENT}
        )
        if not resp.ok:
            raise RuntimeError(
                f"JSDA index -> HTTP {resp.status}: {resp.text()[:200]}"
            )
        return resolve_download_links(resp.text())

    def pick(self, links: Optional[List[str]] = None) -> Optional[str]:
        return pick_latest(links if links is not None else self.list_files())

    def fetch_file(self, url: str) -> bytes:
        self._rl.acquire()
        resp = self._http.get(url, headers={"User-Agent": JSDA_USER_AGENT})
        if not resp.ok:
            raise RuntimeError(
                f"JSDA file {url} -> HTTP {resp.status}: {resp.text()[:200]}"
            )
        return resp.body
