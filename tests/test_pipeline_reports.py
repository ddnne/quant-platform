"""RunReport semantics, exit-code decision, JSDA xlsx dispatch.

Unit-level — no network.
"""

from __future__ import annotations

import pytest

from ingestion.common.http import HttpResponse
from ingestion.common.rate_limit import RateLimiter
from ingestion.jsda.parse import parse_csv, parse_xlsx
from ingestion.pipeline import RunReport, _choose_jsda_parser, decide_exit


# --------------------------------------------------------------------------- report semantics

def test_error_report_not_ok_and_tagged():
    r = RunReport("jquants", "daily_bars", error="boom")
    assert not r.ok
    assert "ERROR" in r.summary() and "boom" in r.summary()


def test_skipped_report_not_ok_and_tagged():
    r = RunReport("jquants", "*", skipped="JQUANTS_API_KEY not set")
    assert not r.ok
    assert "SKIPPED" in r.summary()


def test_zero_registered_without_skip_is_not_ok():
    # the schema-miss guard: fetched>0 but registered==0 must not look successful
    r = RunReport("jquants", "daily_bars", fetched=5, registered=0)
    assert not r.ok


def test_expected_empty_is_ok():
    r = RunReport("jquants", "fins_summary", registered=0, expected_empty=True)
    assert r.ok


def test_registered_gt_zero_is_ok():
    r = RunReport("jsda", "bond_trades", fetched=3, registered=3)
    assert r.ok


# --------------------------------------------------------------------------- schema miss (zero rows after fetch)

def test_schema_miss_flagged_when_fetched_but_registered_zero():
    # the silent schema-miss guard: fetched>0 but registered==0 with no
    # skip/error/expected_empty is a failure, not success.
    r = RunReport("jquants", "daily_bars", fetched=5, registered=0)
    assert r.schema_miss
    assert r.effective_error
    assert not r.ok


def test_schema_miss_summary_shows_error_not_ok():
    r = RunReport("jquants", "daily_bars", fetched=5, registered=0)
    s = r.summary()
    assert "ERROR" in s
    assert "OK" not in s
    assert "schema miss" in s


def test_schema_miss_exit_code_is_1():
    # a silent schema miss fails the run (exit 1), not all-skipped (exit 2)
    assert decide_exit([RunReport("jquants", "daily_bars", fetched=5, registered=0)]) == 1


def test_schema_miss_dominates_ok_in_mixed_run():
    # even with an OK source elsewhere, a schema miss still fails the run
    mixed = [
        RunReport("jsda", "bond_trades", fetched=3, registered=3),  # ok
        RunReport("jquants", "daily_bars", fetched=5, registered=0),  # schema miss
    ]
    assert decide_exit(mixed) == 1


def test_zero_fetched_zero_registered_is_not_schema_miss():
    # fetched==0 (nothing to do) is NOT a schema miss; stays on exit-2 path
    r = RunReport("jquants", "calendar", fetched=0, registered=0)
    assert not r.schema_miss
    assert r.effective_error == ""
    assert decide_exit([r]) == 2


def test_expected_empty_shields_zero_registered_from_schema_miss():
    # raw-only endpoints register 0 rows intentionally — not a schema miss
    r = RunReport("jquants", "fins_summary", fetched=2, registered=0, expected_empty=True)
    assert not r.schema_miss
    assert r.ok
    assert "OK" in r.summary()


# --------------------------------------------------------------------------- exit codes

def test_decide_exit_error_dominates():
    assert decide_exit([RunReport("a", "b", error="e")]) == 1
    assert decide_exit([RunReport("a", "b", registered=1)]) == 0
    assert decide_exit([RunReport("a", "b", skipped="k")]) == 2
    # error beats ok in a mixed run
    mixed = [
        RunReport("a", "b", registered=1),
        RunReport("c", "d", error="e"),
    ]
    assert decide_exit(mixed) == 1
    # all skipped/zero -> 2
    assert decide_exit(
        [RunReport("a", "b", skipped="k"), RunReport("c", "d", fetched=0, registered=0)]
    ) == 2


# --------------------------------------------------------------------------- JSDA dispatch

def test_choose_xlsx_parser():
    p, kind = _choose_jsda_parser("saiken.xlsx", b"PK\x03\x04zipdata")
    assert kind == "xlsx" and p is parse_xlsx


def test_choose_csv_parser():
    p, kind = _choose_jsda_parser("saiken.csv", b"col\nrow\n")
    assert kind == "csv" and p is parse_csv


def test_zip_magic_overrides_csv_extension():
    p, kind = _choose_jsda_parser("file.csv", b"PK\x03\x04zipdata")
    assert kind == "xlsx" and p is parse_xlsx


def test_legacy_xls_rejected_not_silent():
    with pytest.raises(ValueError):
        _choose_jsda_parser("old.xls", b"\xd0\xcf\x11\xe0legacy")


# --------------------------------------------------------------------------- JSDA fetch retry

def test_jsda_fetch_retries_5xx_then_succeeds():
    from ingestion.jsda.fetch import JsdaFetcher

    file_url = "https://www.jsda.or.jp/x/saiken.csv"

    class _Seq:
        name = "local"

        def __init__(self):
            self._r = [
                HttpResponse(503, {}, b"err", file_url),
                HttpResponse(200, {}, b"ok-bytes", file_url),
            ]
            self.n = 0

        def get(self, url, *, headers=None, params=None, timeout=30.0):
            self.n += 1
            return self._r.pop(0)

    http = _Seq()
    f = JsdaFetcher(http, retries=2, sleep=lambda d: None,
                    rate_limiter=RateLimiter(0.0))
    assert f.fetch_file(file_url) == b"ok-bytes"
    assert http.n == 2


def test_jsda_fetch_retries_transport_then_raises():
    from ingestion.jsda.fetch import JsdaFetcher

    class _Dead:
        name = "local"

        def get(self, url, *, headers=None, params=None, timeout=30.0):
            raise OSError("down")

    f = JsdaFetcher(_Dead(), retries=1, sleep=lambda d: None,
                    rate_limiter=RateLimiter(0.0))
    with pytest.raises(RuntimeError):
        f.fetch_file("https://x/y")
