"""JST time helpers.

All ingestion timestamps default to **Asia/Tokyo**. ISO-8601 with an explicit
offset is the canonical string form (e.g. ``2025-04-01T15:00:00+09:00``).
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Optional, Union
from zoneinfo import ZoneInfo

JST = ZoneInfo("Asia/Tokyo")
UTC = timezone.utc

DateLike = Union[str, date, datetime]


def now_jst() -> datetime:
    """Current wall-clock time in JST."""
    return datetime.now(JST)


def now_iso() -> str:
    return to_iso(now_jst())


def ensure_jst(dt: datetime) -> datetime:
    """Attach JST to naive datetimes; convert aware ones to JST."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=JST)
    return dt.astimezone(JST)


def to_iso(dt: datetime) -> str:
    """Canonical ISO string (seconds precision, JST offset)."""
    return ensure_jst(dt).isoformat(timespec="seconds")


def parse_dt(value: str) -> datetime:
    """Parse a date or datetime string into a JST-aware datetime.

    Accepts ``YYYY-MM-DD`` (treated as JST midnight), ``YYYY-MM-DDTHH:MM:SS``
    (naive -> JST) and full ISO strings with an offset.
    """
    if value is None:
        raise ValueError("parse_dt: value is None")
    s = str(value).strip()
    if not s:
        raise ValueError("parse_dt: empty value")
    if len(s) == 10 and s[4] == "-":
        d = datetime.strptime(s, "%Y-%m-%d")
        return d.replace(tzinfo=JST)
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=JST)
    return ensure_jst(dt)


def parse_date_str(value: str) -> str:
    """Return ``YYYY-MM-DD`` from a flexible date-ish input.

    Tolerates ``YYYY/MM/DD``, ``YYYY-MM-DD`` and ``YYYY年MM月DD日``.
    """
    if not value:
        raise ValueError("parse_date_str: empty")
    s = str(value).strip()
    for fmt in ("%Y/%m/%d", "%Y-%m-%d", "%Y年%m月%d日"):
        try:
            return datetime.strptime(s, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    # Fall back to first 10 chars if ISO-ish.
    return s[:10]


def date_at(value: DateLike, hour: int = 0, minute: int = 0) -> datetime:
    """A JST datetime on the given date at ``hour:minute``."""
    if isinstance(value, datetime):
        d = ensure_jst(value).date()
    elif isinstance(value, date):
        d = value
    else:
        d = datetime.strptime(str(value).strip()[:10], "%Y-%m-%d").date()
    return datetime(d.year, d.month, d.day, hour, minute, tzinfo=JST)


def today_str(now: Optional[datetime] = None) -> str:
    return (now or now_jst()).strftime("%Y-%m-%d")
