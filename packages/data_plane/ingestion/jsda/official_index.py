"""Official JSDA archive-index HTML → listed publication days."""

from __future__ import annotations

from .urls import (
    OTC_REFERENCE_DATASET,
    _PUBLICATION_DATE_RE,
    discover_otc_reference_segments,
)

OFFICIAL_ARCHIVE_INDEX_DATASETS = frozenset({OTC_REFERENCE_DATASET})


def parse_official_index_publication_days(
    index_text: str | None,
) -> tuple[str, ...]:
    """Listed publication days from official year-index HTML.

    Missing or blank HTML is fail-closed empty, never a calendar walk.
    """
    if index_text is None or not str(index_text).strip():
        return ()
    text = str(index_text)
    years = {
        int(match.group(1))
        for match in _PUBLICATION_DATE_RE.finditer(text)
    }
    if not years:
        return ()
    seen: set[str] = set()
    days: list[str] = []
    for year in sorted(years):
        for item in discover_otc_reference_segments(text, year=year):
            if item.segment_id in seen:
                continue
            seen.add(item.segment_id)
            days.append(item.segment_id)
    days.sort()
    return tuple(days)


def official_index_days(
    dataset: str,
    index_text: str | None,
) -> tuple[str, ...]:
    """Official year-index listed publication days for ``dataset``.

    Missing ``index_text`` is fail-closed: empty set, never a calendar walk.
    """
    if dataset not in OFFICIAL_ARCHIVE_INDEX_DATASETS:
        return ()
    return parse_official_index_publication_days(index_text)


__all__ = [
    "OFFICIAL_ARCHIVE_INDEX_DATASETS",
    "official_index_days",
    "parse_official_index_publication_days",
]
