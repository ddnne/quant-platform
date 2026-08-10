"""Natural-key + event_time extraction shared between Worker and Python.

The Worker (TypeScript) upserts rows into D1's `jquants_records` table.
The Python local sync pulls them back and writes them into SQLite. For the
two layouts to agree, both sides must derive the SAME `natural_key` and
`event_time` from the same upstream row.

This module is the Python half. The TypeScript mirror lives in
`platform/workers/ingestion-premium/src/index.ts` (functions `naturalKey`
and `pickEventTime`). The cross-language test
`tests/test_phase35_natural_key.py` asserts agreement on a canonical set of
fixture rows.
"""

from __future__ import annotations

import json
from typing import Any

# Identity fields in priority order. Must match KEY_FIELDS in catalog.ts.
KEY_FIELDS: tuple[str, ...] = (
    "Code", "Date", "DateTime", "Time", "DisclosedDate",
    "AnnouncementDate", "DiscDate", "DiscNo",
)

# Event-time candidate fields in priority order. Must match the TypeScript
# `pickEventTime` candidate list.
EVENT_TIME_FIELDS: tuple[str, ...] = (
    "DateTime", "Date", "DisclosedDate", "AnnouncementDate", "DiscDate",
)


def natural_key(row: dict[str, Any]) -> str:
    """Canonical identity of a J-Quants row.

    Picks the known identity fields present in the row and serializes them
    to a stable JSON string. If none are present, falls back to a hash of
    the row's sorted-key serialization (so the same row always maps to the
    same key, but two distinct no-key rows don't collide on a single sentinel).
    """
    picked: dict[str, Any] = {}
    for k in KEY_FIELDS:
        v = row.get(k)
        if v is not None and v != "":
            picked[k] = v
    if picked:
        return json.dumps(picked, sort_keys=True, ensure_ascii=False)
    stable = json.dumps(row, sort_keys=True, ensure_ascii=False)
    return f"hash:{stable[:60]}"


def pick_event_time(row: dict[str, Any]) -> str | None:
    """Pick the event_time for a row, or None if no candidate is present.

    Bare dates (``YYYY-MM-DD``) are normalized to ``YYYY-MM-DDT09:00:00+09:00``
    so they sort against full ISO timestamps and remain PIT-correct.
    """
    for k in EVENT_TIME_FIELDS:
        v = row.get(k)
        if isinstance(v, str) and v:
            if len(v) == 10 and v[4] == "-" and v[7] == "-":
                return f"{v}T09:00:00+09:00"
            return v
    return None
