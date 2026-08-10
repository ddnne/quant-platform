"""JSDA URL resolution (isolated so it can change in one place).

The index page lists downloadable CSV/XLSX files; the exact filenames change
each period. We scrape the index for ``<a href>`` links ending in a data
extension and absolutize them. ``pick_latest`` applies a simple heuristic
(largest year/date token in the filename).

Default runtime for JSDA is **local** — scraping from the edge is discouraged
(bot/DC risk).
"""

from __future__ import annotations

import re
from typing import List, Optional
from urllib.parse import urljoin

INDEX = "https://www.jsda.or.jp/shiryoshitsu/toukei/saiken_torihiki/"
BASE = "https://www.jsda.or.jp"

_DATA_EXT = (".csv", ".xlsx", ".xls")
_LINK_RE = re.compile(r'<a\s+[^>]*href=["\']([^"\']+)["\']', re.IGNORECASE)
_YEAR_RE = re.compile(r"(20\d{2})")


def index_url() -> str:
    return INDEX


def resolve_download_links(html: str, *, base: str = INDEX) -> List[str]:
    """Extract absolute data-file URLs from the JSDA index HTML."""
    out: List[str] = []
    seen = set()
    for href in _LINK_RE.findall(html or ""):
        href = href.strip()
        if not href:
            continue
        low = href.lower()
        if not low.endswith(_DATA_EXT):
            continue
        absolute = urljoin(base, href)
        if absolute not in seen:
            seen.add(absolute)
            out.append(absolute)
    return out


def pick_latest(links: List[str]) -> Optional[str]:
    """Heuristic: pick the link whose filename contains the largest year token."""
    if not links:
        return None
    best_year = -1
    best = links[0]
    for url in links:
        m = _YEAR_RE.search(url)
        y = int(m.group(1)) if m else -1
        if y > best_year:
            best_year = y
            best = url
    return best
