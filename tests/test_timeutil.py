"""Tests for JST time helpers."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from ingestion.common.timeutil import (
    JST,
    date_at,
    ensure_jst,
    now_iso,
    now_jst,
    parse_date_str,
    parse_dt,
    to_iso,
)


def test_now_jst_is_jst_aware():
    assert now_jst().tzinfo is not None
    assert now_jst().astimezone(JST).utcoffset() == datetime.now(JST).utcoffset()


def test_to_iso_roundtrip():
    dt = datetime(2025, 4, 1, 15, 0, 0, tzinfo=JST)
    s = to_iso(dt)
    assert s == "2025-04-01T15:00:00+09:00"
    assert parse_dt(s) == dt


def test_parse_dt_date_only_is_jst_midnight():
    dt = parse_dt("2025-04-01")
    assert dt == datetime(2025, 4, 1, 0, 0, 0, tzinfo=JST)


def test_parse_dt_naive_treated_as_jst():
    dt = parse_dt("2025-04-01T15:30:00")
    assert dt.tzinfo is not None
    assert dt == datetime(2025, 4, 1, 15, 30, 0, tzinfo=JST)


def test_parse_dt_utc_converted_to_jst():
    dt = parse_dt("2025-04-01T06:00:00+00:00")
    assert dt.tzinfo == JST
    assert dt.hour == 15  # 06:00Z -> 15:00 JST


def test_ensure_jst_naive_and_aware():
    naive = datetime(2025, 1, 2, 3, 4, 5)
    assert ensure_jst(naive).tzinfo == JST
    other = datetime(2025, 1, 2, 3, 4, 5, tzinfo=ZoneInfo("UTC"))
    assert ensure_jst(other).tzinfo == JST


def test_date_at():
    dt = date_at("2025-04-01", hour=15, minute=0)
    assert dt == datetime(2025, 4, 1, 15, 0, tzinfo=JST)


def test_parse_date_str_formats():
    assert parse_date_str("2025/04/01") == "2025-04-01"
    assert parse_date_str("2025-04-01") == "2025-04-01"
    assert parse_date_str("2025年4月1日") == "2025-04-01"


def test_now_iso_is_parseable():
    s = now_iso()
    assert "+09:00" in s
    parse_dt(s)  # must not raise
