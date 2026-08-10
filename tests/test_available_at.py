"""Tests for available_at validation and the conservative placeholder."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from ingestion.common.available_at import (
    conservative_available_at,
    is_available_at_known,
    validate_available_at,
)
from ingestion.common.timeutil import JST


@pytest.mark.parametrize("bad", [None, "", "   "])
def test_validate_rejects_missing(bad):
    assert not is_available_at_known(bad)
    with pytest.raises(ValueError):
        validate_available_at(bad)


def test_validate_accepts_datetime():
    dt = datetime(2025, 4, 2, 8, 0, 0, tzinfo=JST)
    s = validate_available_at(dt)
    assert s == "2025-04-02T08:00:00+09:00"


def test_validate_accepts_iso_string():
    s = validate_available_at("2025-04-02T08:00:00+09:00")
    assert s.startswith("2025-04-02T08:00:00")


def test_validate_rejects_unknown_type():
    with pytest.raises(ValueError):
        validate_available_at(12345)


def test_conervative_placeholder_is_after_event_and_next_morning():
    et = datetime(2025, 4, 1, 15, 0, 0, tzinfo=JST)
    av = conservative_available_at(et)
    assert av > et
    # Rule: next calendar day at 08:00 JST.
    assert av == datetime(2025, 4, 2, 8, 0, 0, tzinfo=JST)


def test_conervative_placeholder_with_utc_event():
    et = datetime(2025, 4, 1, 6, 0, 0, tzinfo=ZoneInfo("UTC"))  # 15:00 JST same day
    av = conservative_available_at(et)
    assert av.tzinfo == JST
    assert av.day == 2  # still next JST day
