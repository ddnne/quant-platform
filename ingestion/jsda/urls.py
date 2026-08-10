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

# 東京レポ・レート (Tokyo Repo Rate, "TRR") index. The JSDA took over
# publication from the Bank of Japan on 2012-10-29. The index publishes the
# latest day's rates plus a historical time-series listing. Files are legacy
# ``.xls`` (see :func:`pick_repo_file`); ingestion parses ``.csv``/``.xlsx``
# the same way bond trades do (legacy ``.xls`` is a documented skip — convert
# the source file, matching the bond-trade policy).
REPO_INDEX = "https://www.jsda.or.jp/shiryoshitsu/toukei/trr/"

_DATA_EXT = (".csv", ".xlsx", ".xls")
_LINK_RE = re.compile(r'<a\s+[^>]*href=["\']([^"\']+)["\']', re.IGNORECASE)
_YEAR_RE = re.compile(r"(20\d{2})")

# Filenames that are *not* rate data (reference-institution appointment
# attachments ``別紙`` / procedure docs live alongside the rate files).
_REPO_NON_DATA = ("reference", "bessi", "kijun", "koubo", "youkou")


def index_url() -> str:
    return INDEX


def repo_index_url() -> str:
    return REPO_INDEX


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


def resolve_repo_links(html: str, *, base: str = REPO_INDEX) -> List[str]:
    """Extract absolute data-file URLs from the TRR index HTML.

    Same link extraction as :func:`resolve_download_links`, but rooted at the
    repo-rate index so relative links absolutize correctly.
    """
    return resolve_download_links(html, base=base)


def _is_repo_rate_file(url: str) -> bool:
    """True if the filename looks like a rate-data file (not a ``別紙`` doc)."""
    name = url.rsplit("/", 1)[-1].lower()
    return not any(tok in name for tok in _REPO_NON_DATA)


def pick_repo_file(links: List[str]) -> Optional[str]:
    """Choose the best TRR rate file from resolved links.

    Preference order:

    1. The historical time-series listing (filename contains ``trr`` *and*
       ``ts`` / ``list`` / ``ichiran``) — the richest single fetch.
    2. Any other ``trr`` rate file (e.g. the latest-day file).
    3. Fall back to the largest-year data link (bond-style heuristic) among
       non-doc files.

    Reference-institution attachments (``別紙`` / ``reference``) are excluded —
    they list panel institutions, not rates. Returns ``None`` if nothing fits.
    """
    rate_links = [u for u in (links or []) if _is_repo_rate_file(u)]
    if not rate_links:
        return None

    def _name(url: str) -> str:
        return url.rsplit("/", 1)[-1].lower()

    ts = [
        u for u in rate_links
        if "trr" in _name(u) and ("ts" in _name(u) or "list" in _name(u)
                                  or "ichiran" in _name(u))
    ]
    if ts:
        return ts[0]
    trr = [u for u in rate_links if "trr" in _name(u)]
    if trr:
        return trr[0]
    return pick_latest(rate_links)
