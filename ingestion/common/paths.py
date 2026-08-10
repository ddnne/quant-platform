"""Raw-save path conventions.

Layout: ``data/raw/{source}/{yyyy}/{mm}/{dd}/{filename}`` — partitioned by
the fetch date so re-runs and historical backfills do not clobber each other.
"""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

from .timeutil import ensure_jst


def _ymd(when) -> tuple[str, str, str]:
    if isinstance(when, datetime):
        d = ensure_jst(when)
    elif isinstance(when, date):
        y, m, dd = when.year, when.month, when.day
        return f"{y:04d}", f"{m:02d}", f"{dd:02d}"
    else:  # str -> parse
        d = ensure_jst(_parse(when))
    return f"{d.year:04d}", f"{d.month:02d}", f"{d.day:02d}"


def _parse(when: str) -> datetime:
    from .timeutil import parse_dt
    return parse_dt(when)


def raw_dir(base, source: str, when) -> Path:
    y, m, d = _ymd(when)
    return Path(base) / "raw" / source / y / m / d


def raw_path(base, source: str, when, filename: str) -> Path:
    return raw_dir(base, source, when) / filename
