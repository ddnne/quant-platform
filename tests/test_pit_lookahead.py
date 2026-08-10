"""PIT API lookahead guard: ``available_at <= as_of`` is enforced.

The defining property of a point-in-time read: a row whose ``available_at`` is
*after* ``as_of`` is invisible — that data did not exist yet and using it
would leak the future. Rows with ``available_at == as_of`` ARE visible
(publication at exactly that instant is fair game). This module pins the
boundary on the canonical table and across the parsing offset round-trip.
"""

from __future__ import annotations

import pytest

from pit import get_equity_bars_daily, get_jquants_records
from storage.sqlite_store import SqliteStore


def _seed_bars(tmp_path, rows):
    path = tmp_path / "ing.sqlite"
    store = SqliteStore(path)
    store.upsert("jquants_daily_bars", rows)
    store.close()
    return path


def _bar(code: str, d: str, avail: str, close: float) -> dict:
    return {
        "source": "jquants",
        "code": code,
        "date": d,
        "event_time": f"{d}T15:00:00+09:00",
        "available_at": avail,
        "ingested_at": avail,
        "close": close,
    }


# Three bars for the same code on consecutive dates, each "published" the day
# after its session close (available_at one day later at 17:00 JST).
BARS = [
    _bar("8697", "2025-03-30", "2025-03-31T17:00:00+09:00", 100.0),
    _bar("8697", "2025-03-31", "2025-04-01T17:00:00+09:00", 110.0),
    _bar("8697", "2025-04-01", "2025-04-02T17:00:00+09:00", 120.0),  # future
]


def test_future_available_at_excluded_equal_included(tmp_path):
    """as_of == the middle row's available_at: that row + earlier visible, later not."""
    path = _seed_bars(tmp_path, BARS)
    res = get_equity_bars_daily(as_of="2025-04-01T17:00:00+09:00", code="8697", db_path=path)
    dates = {r["date"] for r in res}
    assert dates == {"2025-03-30", "2025-03-31"}  # 04-01 (avail 04-02) is future
    assert res.count == 2


def test_boundary_strictly_before_publication_excludes_equal(tmp_path):
    """One second before publication -> the == row is NOT yet visible."""
    path = _seed_bars(tmp_path, BARS)
    res = get_equity_bars_daily(as_of="2025-04-01T16:59:59+09:00", code="8697", db_path=path)
    assert {r["date"] for r in res} == {"2025-03-30"}


def test_offset_round_trip_compares_correctly(tmp_path):
    """available_at stored from a UTC instant == as_of given as that same UTC instant.

    The store canonicalizes offsets to +09:00 on write; as_of is normalized the
    same way. So an equivalent instant in a different offset compares equal —
    the lexicographic string ``<=`` is valid because both sides share the
    canonical fixed-width form.
    """
    rows = [
        _bar("8697", "2025-03-31", "2025-04-01T08:00:00+00:00", 110.0),  # == 17:00 JST
    ]
    path = _seed_bars(tmp_path, rows)
    # Same instant, given as UTC -> normalized to 17:00 JST == stored value.
    res_eq = get_equity_bars_daily(
        as_of="2025-04-01T08:00:00+00:00", code="8697", db_path=path
    )
    assert res_eq.count == 1
    # One second earlier (UTC) -> strictly before -> excluded.
    res_before = get_equity_bars_daily(
        as_of="2025-04-01T07:59:59+00:00", code="8697", db_path=path
    )
    assert res_before.count == 0


def test_lookahead_guard_applies_to_generic_table_too(tmp_path):
    """The available_at gate is not bars-specific — it gates every table."""
    avail_early = "2025-04-01T17:00:00+09:00"
    avail_late = "2025-04-02T17:00:00+09:00"
    rows = [
        {
            "source": "jquants",
            "dataset": "fins_dividend",
            "natural_key": '{"AnnouncementDate": "2025-03-10", "Code": "8697"}',
            "event_time": "2025-03-10T09:00:00+09:00",
            "available_at": avail_early,
            "ingested_at": avail_early,
            "payload": '{"Code": "8697", "AnnouncementDate": "2025-03-10", "D": 10.0}',
        },
        {
            "source": "jquants",
            "dataset": "fins_dividend",
            "natural_key": '{"AnnouncementDate": "2025-03-11", "Code": "8697"}',
            "event_time": "2025-03-11T09:00:00+09:00",
            "available_at": avail_late,  # future relative to as_of below
            "ingested_at": avail_late,
            "payload": '{"Code": "8697", "AnnouncementDate": "2025-03-11", "D": 11.0}',
        },
    ]
    path = tmp_path / "ing.sqlite"
    store = SqliteStore(path)
    store.upsert("jquants_records", rows)
    store.close()

    res = get_jquants_records(
        as_of="2025-04-01T17:00:00+09:00", dataset="fins_dividend", db_path=path
    )
    # Only the early-available row; the late one is look-ahead and excluded.
    assert res.count == 1
    assert res.rows[0]["payload"]["AnnouncementDate"] == "2025-03-10"


@pytest.mark.parametrize(
    "as_of, expected",
    [
        ("2025-03-31T16:59:59+09:00", set()),                      # before any
        ("2025-03-31T17:00:00+09:00", {"2025-03-30"}),             # == earliest pub
        ("2025-04-01T17:00:00+09:00", {"2025-03-30", "2025-03-31"}),
        ("2025-04-02T17:00:00+09:00", {"2025-03-30", "2025-03-31", "2025-04-01"}),
        ("2025-12-31T00:00:00+09:00", {"2025-03-30", "2025-03-31", "2025-04-01"}),
    ],
)
def test_lookahead_boundary_matrix(tmp_path, as_of, expected):
    """Boundary sweep: as_of monotonically reveals rows as they become available."""
    path = _seed_bars(tmp_path, BARS)
    res = get_equity_bars_daily(as_of=as_of, code="8697", db_path=path)
    assert {r["date"] for r in res} == expected


if __name__ == "__main__":
    pytest.main([__file__, "-q"])
