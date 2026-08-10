"""Phase 3.5 — natural_key / event_time extraction.

Cross-language consistency: the Worker (TypeScript) and the Python sync
script must derive the same `natural_key` and `event_time` for any given
J-Quants row. The Python source of truth is
`cf_platform.ingest_premium.natural_key`.
"""

from __future__ import annotations

import pytest

from cf_platform.ingest_premium.natural_key import (
    EVENT_TIME_FIELDS,
    KEY_FIELDS,
    natural_key,
    pick_event_time,
)


def test_natural_key_picks_known_fields():
    row = {"Code": "8697", "Date": "2025-04-01", "Close": 100.0}
    nk = natural_key(row)
    assert "Code" in nk and "8697" in nk
    assert "Date" in nk and "2025-04-01" in nk
    # Non-key fields do not leak into the natural key.
    assert "Close" not in nk


def test_natural_key_ignores_empties():
    row = {"Code": "8697", "Date": "", "Close": 1.0}
    nk = natural_key(row)
    assert "Date" not in nk
    assert "Code" in nk


def test_natural_key_falls_back_to_hash_when_no_id_present():
    row = {"Close": 100.0, "Volume": 1000}
    nk = natural_key(row)
    assert nk.startswith("hash:")
    # Stable: same input → same key
    assert nk == natural_key(dict(row))


def test_natural_key_distinct_no_id_rows_distinct():
    a = {"Close": 100.0}
    b = {"Close": 200.0}
    assert natural_key(a) != natural_key(b)


def test_natural_key_order_independent():
    row1 = {"Code": "8697", "Date": "2025-04-01"}
    row2 = {"Date": "2025-04-01", "Code": "8697"}
    assert natural_key(row1) == natural_key(row2)


def test_key_fields_match_ts_constant():
    """KEY_FIELDS must match the TypeScript catalog.ts mirror exactly."""
    assert KEY_FIELDS == (
        "Code", "Date", "DateTime", "Time", "DisclosedDate",
        "AnnouncementDate", "DiscDate", "DiscNo",
    )


def test_event_time_fields_match_ts_constant():
    assert EVENT_TIME_FIELDS == (
        "DateTime", "Date", "DisclosedDate", "AnnouncementDate", "DiscDate",
    )


@pytest.mark.parametrize(
    "row,expected",
    [
        ({"Date": "2025-04-01"}, "2025-04-01T09:00:00+09:00"),
        ({"DateTime": "2025-04-01T10:30:00+09:00"}, "2025-04-01T10:30:00+09:00"),
        ({"DisclosedDate": "2025-04-01"}, "2025-04-01T09:00:00+09:00"),
        ({"DisclosedDate": "2025-04-01T15:00:00+09:00"}, "2025-04-01T15:00:00+09:00"),
        ({"Close": 100.0}, None),
    ],
)
def test_pick_event_time(row, expected):
    assert pick_event_time(row) == expected


def test_pick_event_time_priority_datetime_over_date():
    """DateTime beats Date when both are present."""
    row = {
        "DateTime": "2025-04-01T10:00:00+09:00",
        "Date": "2025-04-01",
    }
    assert pick_event_time(row) == "2025-04-01T10:00:00+09:00"
