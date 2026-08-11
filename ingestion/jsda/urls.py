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
from dataclasses import dataclass
from datetime import date
import html as html_lib
from pathlib import Path
from typing import Any, List, Mapping, Optional
from urllib.parse import urljoin, urlsplit

INDEX = "https://www.jsda.or.jp/shiryoshitsu/toukei/saiken_torihiki/"
BASE = "https://www.jsda.or.jp"

# 公社債店頭売買参考統計値.  This is a different official product from
# ``INDEX`` (社債の取引情報).  Its root links one page per publication year,
# including a CSV-only archive beginning in 2002.
OTC_REFERENCE_INDEX = (
    "https://market.jsda.or.jp/shijyo/saiken/baibai/baisanchi/index.html"
)
OTC_REFERENCE_CORRECTIONS_INDEX = (
    "https://market.jsda.or.jp/shijyo/saiken/baibai/baisanchi/reki/index.html"
)
OTC_REFERENCE_DATASET = "jsda_otc_bond_reference_prices"

# 東京レポ・レート (Tokyo Repo Rate, "TRR") index. The JSDA took over
# publication from the Bank of Japan on 2012-10-29. The index publishes the
# latest day's rates plus a historical time-series listing. Files are legacy
# ``.xls`` (see :func:`pick_repo_file`); the authoritative history is parsed
# directly with xlrd and is never silently skipped.
REPO_INDEX = "https://www.jsda.or.jp/shiryoshitsu/toukei/trr/"
TOKYO_REPO_DATASET = "jsda_tokyo_repo_rates"
TOKYO_REPO_JSDA_START = "2012-10-29"

_DATA_EXT = (".csv", ".xlsx", ".xls")
_LINK_RE = re.compile(r'<a\s+[^>]*href=["\']([^"\']+)["\']', re.IGNORECASE)
_YEAR_RE = re.compile(r"(20\d{2})")
_ANCHOR_RE = re.compile(
    r'<a\s+[^>]*href=["\']([^"\']+)["\'][^>]*>(.*?)</a\s*>',
    re.IGNORECASE | re.DOTALL,
)
_ROW_RE = re.compile(r"<tr\b[^>]*>(.*?)</tr\s*>", re.IGNORECASE | re.DOTALL)
_TAG_RE = re.compile(r"<[^>]+>")
_PUBLICATION_DATE_RE = re.compile(
    r"(?<!\d)(20\d{2})[./年]\s*(\d{1,2})[./月]\s*(\d{1,2})(?:日)?(?!\d)"
)
_ARCHIVE_YEAR_RE = re.compile(r"archive(20\d{2})\.html", re.IGNORECASE)
_REPO_LATEST_RE = re.compile(
    r"東京レポ[・･]?レート\s*[（(]\s*"
    r"(20\d{2})[./年]\s*(\d{1,2})[./月]\s*(\d{1,2})(?:日)?\s*[）)]"
)


@dataclass(frozen=True)
class JsdaArchiveIndex:
    """One official JSDA annual archive page discovered from its root."""

    year: int
    url: str


@dataclass(frozen=True)
class JsdaArchiveSegment:
    """One resumable source segment and its official collection scope.

    ``publication_label_date`` is deliberately not called an event date.  For
    OTC reference values JSDA labels the file for the following business day,
    while the quote itself is based on the preceding 15:00 session.  The
    calendar-backed effective date is supplied later by normalization.
    """

    dataset_id: str
    segment_id: str
    period_id: str
    segment_start: str
    segment_end: str
    publication_label_date: str
    expected_scope: Mapping[str, Any]
    index_url: str
    source_url: Optional[str]
    source_format: Optional[str]
    discovery_status: str


@dataclass(frozen=True)
class JsdaRepoTimeseries:
    """The authoritative JSDA-era Tokyo Repo Rate source segment."""

    dataset_id: str
    segment_id: str
    segment_start: str
    segment_end: Optional[str]
    index_url: str
    source_url: Optional[str]
    source_format: Optional[str]
    latest_publication_date: Optional[str]
    discovery_status: str


@dataclass(frozen=True)
class JsdaCorrectionArtifact:
    """One replacement correction from section 1 of JSDA's history page."""

    dataset_id: str
    correction_id: str
    affected_start: str
    affected_end: str
    correction_publication_label: str
    correction_published_at: Optional[str]
    source_url: str
    source_format: str
    label: str

# Filenames that are *not* rate data (reference-institution appointment
# attachments ``別紙`` / procedure docs live alongside the rate files).
_REPO_NON_DATA = ("reference", "bessi", "kijun", "koubo", "youkou")


def index_url() -> str:
    return INDEX


def repo_index_url() -> str:
    return REPO_INDEX


def otc_reference_index_url() -> str:
    return OTC_REFERENCE_INDEX


def otc_reference_corrections_index_url() -> str:
    return OTC_REFERENCE_CORRECTIONS_INDEX


def _visible_text(fragment: str) -> str:
    return html_lib.unescape(_TAG_RE.sub(" ", fragment or "")).strip()


def _source_format(url: str) -> str:
    path = urlsplit(url).path.lower()
    return path.rsplit(".", 1)[-1] if "." in path else ""


def _publication_date(fragment: str) -> Optional[str]:
    match = _PUBLICATION_DATE_RE.search(_visible_text(fragment))
    if not match:
        return None
    try:
        return date(*(int(part) for part in match.groups())).isoformat()
    except ValueError:
        return None


def discover_otc_reference_year_indexes(
    html: str, *, base: str = OTC_REFERENCE_INDEX
) -> List[JsdaArchiveIndex]:
    """Discover the official yearly OTC-reference archive pages.

    No year is synthesized: only explicit ``archiveYYYY.html`` links on the
    official root become expected collection scope.
    """
    discovered: dict[int, JsdaArchiveIndex] = {}
    for href, _label in _ANCHOR_RE.findall(html or ""):
        absolute = urljoin(base, html_lib.unescape(href).strip())
        match = _ARCHIVE_YEAR_RE.search(urlsplit(absolute).path)
        if match:
            year = int(match.group(1))
            discovered[year] = JsdaArchiveIndex(year=year, url=absolute)
    return [discovered[year] for year in sorted(discovered)]


def discover_otc_reference_segments(
    html: str,
    *,
    year: int,
    index_url: Optional[str] = None,
) -> List[JsdaArchiveSegment]:
    """Discover publication-day files from one official annual archive.

    CSV is canonical and preferred whenever the row offers it, which covers
    the source's pre-2008 CSV-only history. XLSX/XLS are accepted only when a
    CSV is absent. Decorative download-icon URLs are ignored because their
    extension is not a data format.
    """
    archive_url = index_url or urljoin(
        OTC_REFERENCE_INDEX, f"archive{int(year):04d}.html"
    )
    out: list[JsdaArchiveSegment] = []
    seen: set[str] = set()
    for row in _ROW_RE.findall(html or ""):
        label_date = _publication_date(row)
        if label_date is None or int(label_date[:4]) != int(year):
            continue
        choices: list[tuple[int, str, str]] = []
        for href, label in _ANCHOR_RE.findall(row):
            absolute = urljoin(archive_url, html_lib.unescape(href).strip())
            fmt = _source_format(absolute)
            if fmt not in {"csv", "xlsx", "xls"}:
                continue
            visible = _visible_text(label).lower()
            # A row may include both the reference values and the separate
            # rating-matrix product. Exclude links whose label names the latter.
            if "格付" in visible or "matrix" in visible:
                continue
            priority = {"csv": 0, "xlsx": 1, "xls": 2}[fmt]
            choices.append((priority, absolute, fmt))
        if label_date in seen:
            continue
        seen.add(label_date)
        if choices:
            _priority, source_url, fmt = min(choices, key=lambda item: item[0])
            discovery_status = "DISCOVERED"
        else:
            source_url, fmt = None, None
            discovery_status = "MISSING_SOURCE_LINK"
        out.append(JsdaArchiveSegment(
            dataset_id=OTC_REFERENCE_DATASET,
            segment_id=label_date,
            period_id=label_date[:7],
            segment_start=label_date,
            segment_end=label_date,
            publication_label_date=label_date,
            expected_scope={
                "coverage_mode": "official_archive_index_reconciled",
                "expected_item_unit": "official_archive_file",
                "expected_frequency": "trading_day",
                "index_url": archive_url,
                "publication_label_date": label_date,
                "source_format": fmt,
                "source_url": source_url,
                "universe_rule": "all_bonds_in_official_publication_file",
            },
            index_url=archive_url,
            source_url=source_url,
            source_format=fmt,
            discovery_status=discovery_status,
        ))
    return sorted(out, key=lambda item: item.publication_label_date)


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


def discover_repo_timeseries(
    html: str, *, base: str = REPO_INDEX
) -> JsdaRepoTimeseries:
    """Discover JSDA's authoritative ``東京レポ・レート（一覧）`` file.

    The index also links the latest one-day workbook and many unrelated XLS
    attachments.  An anchor labelled ``一覧`` is authoritative; the existing
    filename heuristic is only a fallback for older equivalent markup.
    """
    candidates: list[str] = []
    labelled: list[str] = []
    for href, label in _ANCHOR_RE.findall(html or ""):
        absolute = urljoin(base, html_lib.unescape(href).strip())
        if _source_format(absolute) not in {"xls", "xlsx", "csv"}:
            continue
        candidates.append(absolute)
        if "一覧" in _visible_text(label):
            labelled.append(absolute)
    source_url = labelled[0] if labelled else pick_repo_file(candidates)

    latest: Optional[str] = None
    match = _REPO_LATEST_RE.search(_visible_text(html or ""))
    if match:
        try:
            latest = date(*(int(part) for part in match.groups())).isoformat()
        except ValueError:
            latest = None
    status_parts: list[str] = []
    if source_url is None:
        status_parts.append("MISSING_TIMESERIES_LINK")
    if latest is None:
        status_parts.append("MISSING_LATEST_PUBLICATION_LABEL")
    return JsdaRepoTimeseries(
        dataset_id=TOKYO_REPO_DATASET,
        segment_id="jsda-era-timeseries",
        segment_start=TOKYO_REPO_JSDA_START,
        segment_end=latest,
        index_url=base,
        source_url=source_url,
        source_format=None if source_url is None else _source_format(source_url),
        latest_publication_date=latest,
        discovery_status="DISCOVERED" if not status_parts else "+".join(status_parts),
    )


def _correction_dates(fragment: str) -> list[str]:
    """Parse full and abbreviated Japanese dates in one correction clause."""
    out: list[str] = []
    current_year: Optional[int] = None
    pattern = re.compile(
        r"(?:(20\d{2})[./年])?\s*(\d{1,2})[./月]\s*(\d{1,2})(?:日)?"
    )
    for match in pattern.finditer(fragment):
        if match.group(1):
            current_year = int(match.group(1))
        if current_year is None:
            continue
        try:
            out.append(date(
                current_year, int(match.group(2)), int(match.group(3))
            ).isoformat())
        except ValueError:
            continue
    return out


def discover_otc_reference_corrections(
    html: str, *, base: str = OTC_REFERENCE_CORRECTIONS_INDEX
) -> List[JsdaCorrectionArtifact]:
    """Discover replacement corrections, excluding comparison-only notices.

    JSDA section 1 says the historical values were corrected. Section 2 says
    the opposite (comparison tables only), so its artifacts must never mutate
    the governed fact table.
    """
    document = html_lib.unescape(html or "")
    start = document.find("（1）システム障害")
    end = document.find("（2）発表後", start + 1)
    if start < 0 or end < 0:
        return []
    section = document[start:end]
    out: list[JsdaCorrectionArtifact] = []
    seen: set[str] = set()
    for href, raw_label in _ANCHOR_RE.findall(section):
        label = _visible_text(raw_label)
        absolute = urljoin(base, html_lib.unescape(href).strip())
        source_format = _source_format(absolute)
        if source_format not in {"xls", "xlsx", "csv", "pdf"}:
            continue
        open_paren = max(label.rfind("（"), label.rfind("("))
        close_paren = max(label.rfind("）"), label.rfind(")"))
        if open_paren < 0 or close_paren <= open_paren:
            continue
        affected_dates = _correction_dates(label[:open_paren])
        correction_clause = label[open_paren + 1:close_paren]
        correction_dates = _correction_dates(correction_clause)
        if not affected_dates or not correction_dates:
            continue
        correction_label = correction_dates[-1]
        time_match = re.search(
            r"(\d{1,2})\s*時\s*(\d{1,2})\s*分", correction_clause
        )
        correction_at = None
        if time_match:
            correction_at = (
                f"{correction_label}T{int(time_match.group(1)):02d}:"
                f"{int(time_match.group(2)):02d}:00+09:00"
            )
        filename = Path(urlsplit(absolute).path).name
        correction_id = f"{correction_label}:{filename}"
        if correction_id in seen:
            continue
        seen.add(correction_id)
        out.append(JsdaCorrectionArtifact(
            dataset_id=OTC_REFERENCE_DATASET,
            correction_id=correction_id,
            affected_start=min(affected_dates),
            affected_end=max(affected_dates),
            correction_publication_label=correction_label,
            correction_published_at=correction_at,
            source_url=absolute,
            source_format=source_format,
            label=label,
        ))
    return sorted(
        out,
        key=lambda item: (
            item.correction_publication_label, item.correction_id
        ),
    )
