"""``available_at`` validation and conservative-placeholder logic.

PIT rule: a structured row MUST record when its data became usable
(``available_at``). Rows missing it are rejected. Where the true publication
time is unknown, use a documented conservative placeholder marked **仮**.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from .timeutil import date_at, ensure_jst, to_iso


def is_available_at_known(value: Any) -> bool:
    return not (value is None or (isinstance(value, str) and not value.strip()))


def validate_available_at(value: Any) -> str:
    """Return a canonical ISO ``available_at`` string or raise ``ValueError``.

    This is the PIT hard gate: structured persistence requires it.
    """
    if not is_available_at_known(value):
        raise ValueError(
            "available_at is missing — PIT requires a non-empty available_at"
        )
    if isinstance(value, str):
        # Trust caller-provided ISO; round-trip normalizes the offset.
        return to_iso(ensure_jst(_coerce_str(value)))
    if isinstance(value, datetime):
        return to_iso(ensure_jst(value))
    raise ValueError(f"available_at unsupported type: {type(value)!r}")


def _coerce_str(value: str) -> datetime:
    from .timeutil import parse_dt  # local import to keep module import cheap
    try:
        return parse_dt(value)
    except ValueError:
        # Already an ISO string with offset that parse_dt may reject rarely.
        return datetime.fromisoformat(value)


def conservative_available_at(event_time) -> datetime:
    """Conservative placeholder for an unknown ``available_at`` (**仮**).

    Rule of thumb: data is deemed available the **next calendar day at 08:00
    JST** after the event. This is deliberately later than ``event_time``
    (avoids look-ahead) and must be refined per source once the real
    publication timing is confirmed. See ``docs/data_sources.md``.
    """
    return date_at(event_time) + timedelta(days=1, hours=8)
