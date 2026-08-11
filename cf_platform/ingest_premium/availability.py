"""Phase 3.5 (P0-1) — Dataset-level ``available_at`` policy (Python mirror).

The Cloudflare Worker picks ``available_at`` per row using a dataset-level
policy:

    policy         | rule
    ---------------+---------------------------------------------------------
    session_close  | equities_bars_daily / am / indices / derivatives bars:
                   | available_at = event-date session close JST
                   | (15:30 from 2024-11-05; 15:00 before that).
    event_field    | If the row has DisclosedDate / AnnouncementDate /
                   | DateTime use that as the event; available_at = that
                   | instant (or next business open at 09:00 JST when only
                   | a date is present).
    ingest_time    | Fallback only when no better signal exists.

This module is the Python half. The TypeScript mirror lives in
``platform/workers/ingestion-premium/src/availability.ts``. Cross-language
consistency is asserted in ``tests/test_phase35_availability.py``.

Nothing here performs I/O — it is pure transformation so unit tests stay
fast and deterministic.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Iterable, Mapping, Optional

JST = timezone(timedelta(hours=9))

# Datasets whose row Date IS the session — session-close JST is the correct
# PIT-available time for these. MUST match the TS SESSION_CLOSE_DATASETS.
SESSION_CLOSE_DATASETS: tuple[str, ...] = (
    "derivatives_bars_daily_futures",
    "derivatives_bars_daily_options",
    "derivatives_bars_daily_options_225",
    "equities_bars_daily",
    "equities_bars_daily_am",
    "indices_bars_daily",
    "indices_bars_daily_topix",
)

# 2024-11-05: TSE afternoon close moved from 15:00 to 15:30 JST.
SESSION_CLOSE_CUTOFF_DATE = "2024-11-05"
SESSION_CLOSE_TIME_NEW = "15:30"
SESSION_CLOSE_TIME_OLD = "15:00"

# Event-time candidate fields in priority order. Bare dates are normalized
# to next-business-open 09:00 JST. MUST match the TS EVENT_FIELD_CANDIDATES.
EVENT_FIELD_CANDIDATES: tuple[str, ...] = (
    "DateTime",
    "DisclosedDate",
    "AnnouncementDate",
    "DiscDate",
    "Date",
)

POLICIES = ("session_close", "event_field", "ingest_time")
AvailabilityPolicy = str  # literal type would require Python 3.8+ in cf_platform

DATASET_POLICY: dict[str, str] = {ds: "session_close" for ds in SESSION_CLOSE_DATASETS}
DEFAULT_POLICY = "event_field"


def policy_for_dataset(dataset_id: str) -> str:
    """Return the policy name for ``dataset_id`` (falls back to default)."""
    return DATASET_POLICY.get(dataset_id, DEFAULT_POLICY)


def session_close_jst(date_yyyy_mm_dd: str) -> str:
    """JST session-close instant for a session date.

    15:30 JST from 2024-11-05 onward, 15:00 JST before. Raises ``ValueError``
    on malformed input.
    """
    _check_date(date_yyyy_mm_dd)
    time = (
        SESSION_CLOSE_TIME_OLD
        if date_yyyy_mm_dd < SESSION_CLOSE_CUTOFF_DATE
        else SESSION_CLOSE_TIME_NEW
    )
    return f"{date_yyyy_mm_dd}T{time}:00+09:00"


def next_business_open_jst(date_yyyy_mm_dd: str) -> str:
    """Advance ``date_yyyy_mm_dd`` past weekends; return 09:00 JST that day."""
    _check_date(date_yyyy_mm_dd)
    # Use UTC constructors so the day-walk does not drift across TZs.
    y, m, d = (int(x) for x in date_yyyy_mm_dd.split("-"))
    dt = datetime(y, m, d, tzinfo=timezone.utc)
    while dt.weekday() >= 5:  # Sat=5, Sun=6
        dt += timedelta(days=1)
    return f"{dt.strftime('%Y-%m-%d')}T09:00:00+09:00"


def pick_event_field_instant(row: Mapping[str, Any]) -> Optional[str]:
    """Pick the event-field instant from ``row``, or ``None`` if no candidate.

    Bare dates (``YYYY-MM-DD``) advance to next business open at 09:00 JST.
    Full timestamps are returned verbatim (caller is expected to have
    offset-aware formatting).
    """
    for key in EVENT_FIELD_CANDIDATES:
        v = row.get(key)
        if not isinstance(v, str) or not v:
            continue
        if _is_bare_date(v):
            return next_business_open_jst(v)
        if _has_time_component(v):
            return v
        # Unexpected shape — keep scanning candidates rather than guessing.
    return None


def pick_available_at(
    row: Mapping[str, Any],
    dataset_id: str,
    ingested_at: str,
) -> str:
    """Compute ``available_at`` per dataset policy.

    Resolution order:
      1. Policy rule for the dataset (session_close → session close JST;
         event_field → event-field instant).
      2. Cross-policy fallback: if a session_close row lacks ``Date``, try
         event_field; if event_field finds nothing, fall through to ingest.
      3. ``ingested_at`` — the fetch instant. Last resort, PIT-safe.
    """
    policy = policy_for_dataset(dataset_id)
    if policy == "session_close":
        d = row.get("Date")
        if isinstance(d, str) and _is_bare_date(d):
            return session_close_jst(d)
        ev = pick_event_field_instant(row)
        if ev is not None:
            return ev
        return ingested_at
    if policy == "event_field":
        ev = pick_event_field_instant(row)
        if ev is not None:
            return ev
        return ingested_at
    # ingest_time
    return ingested_at


def _check_date(value: str) -> None:
    if len(value) != 10 or value[4] != "-" or value[7] != "-":
        raise ValueError(f"expected YYYY-MM-DD, got {value!r}")
    try:
        datetime.strptime(value, "%Y-%m-%d")
    except ValueError as exc:
        raise ValueError(f"expected YYYY-MM-DD, got {value!r}") from exc


def _is_bare_date(value: str) -> bool:
    return (
        len(value) == 10
        and value[4] == "-"
        and value[7] == "-"
        and value[:4].isdigit()
        and value[5:7].isdigit()
        and value[8:10].isdigit()
    )


def _has_time_component(value: str) -> bool:
    return "T" in value or " " in value


__all__ = [
    "AvailabilityPolicy",
    "DATASET_POLICY",
    "DEFAULT_POLICY",
    "EVENT_FIELD_CANDIDATES",
    "JST",
    "POLICIES",
    "SESSION_CLOSE_DATASETS",
    "next_business_open_jst",
    "pick_available_at",
    "pick_event_field_instant",
    "policy_for_dataset",
    "session_close_jst",
]
