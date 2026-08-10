"""J-Quants V2 client: ``data`` envelope, ``pagination_key`` paging, retry.

All offline — driven by a tiny in-memory HTTP double.
"""

from __future__ import annotations

import json

import pytest

from ingestion.common.http import HttpResponse
from ingestion.jquants.client import JQuantsClient, _records

MASTER = "https://api.jquants.com/v2/equities/master"
BARS = "https://api.jquants.com/v2/equities/bars/daily"


def _resp(payload, status=200, url="https://api.jquants.com"):
    return HttpResponse(
        status,
        {"content-type": "application/json"},
        json.dumps(payload).encode("utf-8"),
        url,
    )


class _SeqHttp:
    """Pops prepared responses in order; records each call's params."""

    name = "local"

    def __init__(self, payloads):
        self._payloads = list(payloads)
        self.calls: list[dict] = []

    def get(self, url, *, headers=None, params=None, timeout=30.0):
        self.calls.append({"url": url, "params": dict(params or {})})
        if not self._payloads:
            return _resp({"data": []})
        return _resp(self._payloads.pop(0))


# --------------------------------------------------------------------------- envelope

def test_records_reads_data_envelope():
    assert _records({"data": [{"a": 1}]}) == [{"a": 1}]
    # legacy per-endpoint key fallback
    assert _records({"info": [{"a": 1}]}, "info") == [{"a": 1}]
    assert _records({"daily_bars": [{"a": 1}]}, "daily_bars") == [{"a": 1}]
    # missing / non-list
    assert _records({}) == []
    assert _records({"data": None}, "info") == []
    assert _records([], "info") == []


def test_daily_bars_reads_data_envelope():
    http = _SeqHttp([
        {"data": [{"Code": "8697", "Date": "2025-04-01", "Close": 100}]}
    ])
    c = JQuantsClient(http, "key", retries=0)
    bars = c.daily_bars(code="8697")
    assert [b["Code"] for b in bars] == ["8697"]


# --------------------------------------------------------------------------- paging

def test_pagination_uses_pagination_key_request_param():
    http = _SeqHttp([
        {"data": [{"Code": "1"}], "pagination_key": "tok"},
        {"data": [{"Code": "2"}]},
    ])
    c = JQuantsClient(http, "k", retries=0)
    rows = c.listed_info()
    assert [r["Code"] for r in rows] == ["1", "2"]
    assert len(http.calls) == 2
    # first call: no pagination param at all
    assert "pagination_key" not in http.calls[0]["params"]
    assert "pagination_token" not in http.calls[0]["params"]
    # second call: sent pagination_key (NOT pagination_token)
    assert http.calls[1]["params"].get("pagination_key") == "tok"
    assert "pagination_token" not in http.calls[1]["params"]


def test_pagination_accepts_legacy_response_token():
    http = _SeqHttp([
        {"data": [{"Code": "1"}], "pagination_token": "tok"},  # legacy resp key
        {"data": [{"Code": "2"}]},
    ])
    c = JQuantsClient(http, "k", retries=0)
    rows = c.listed_info()
    assert [r["Code"] for r in rows] == ["1", "2"]
    # still re-sent as pagination_key on the request side
    assert http.calls[1]["params"].get("pagination_key") == "tok"


# --------------------------------------------------------------------------- retry

def test_transport_error_retried_then_succeeds():
    class _Flaky:
        name = "local"

        def __init__(self):
            self.n = 0

        def get(self, url, *, headers=None, params=None, timeout=30.0):
            self.n += 1
            if self.n == 1:
                raise OSError("connection reset")
            return _resp({"data": [{"Code": "1", "Date": "2025-04-01"}]})

    http = _Flaky()
    c = JQuantsClient(http, "k", retries=2, sleep=lambda d: None)
    bars = c.daily_bars(code="1")
    assert len(bars) == 1 and http.n == 2


def test_transport_error_exhausts_and_raises():
    from ingestion.jquants.client import _Transient

    class _Dead:
        name = "local"

        def __init__(self):
            self.n = 0

        def get(self, url, *, headers=None, params=None, timeout=30.0):
            self.n += 1
            raise OSError("down")

    http = _Dead()
    sleeps = []
    c = JQuantsClient(http, "k", retries=2, sleep=sleeps.append)
    with pytest.raises(_Transient):
        c.listed_info()
    assert http.n == 3  # 1 initial + 2 retries
    assert len(sleeps) == 2


def test_5xx_is_retriable():
    class _Five:
        name = "local"

        def __init__(self):
            self.n = 0

        def get(self, url, *, headers=None, params=None, timeout=30.0):
            self.n += 1
            if self.n == 1:
                return _resp({"err": "boom"}, status=503)
            return _resp({"data": [{"Code": "1"}]})

    http = _Five()
    c = JQuantsClient(http, "k", retries=2, sleep=lambda d: None)
    rows = c.listed_info()
    assert [r["Code"] for r in rows] == ["1"] and http.n == 2
