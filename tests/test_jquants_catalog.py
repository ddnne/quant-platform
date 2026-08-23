"""J-Quants catalog coverage + generic ``fetch_dataset`` routing.

Asserts *every* catalog dataset has a usable ``/v2/`` path and is reachable
through ``JQuantsClient.fetch_dataset`` with the right URL — fully offline
via a recording HTTP double. No endpoint may be a stub with no route.
"""

from __future__ import annotations

import json

import pytest

from ingestion.common.http import HttpResponse
from ingestion.common.rate_limit import RateLimiter
from ingestion.jquants import catalog
from ingestion.jquants.client import JQuantsClient, _records

_NO_RL = RateLimiter(0.0)


def _resp(payload, status=200):
    return HttpResponse(
        status,
        {"content-type": "application/json"},
        json.dumps(payload).encode("utf-8"),
        "https://api.jquants.com",
    )


class _RecordingHttp:
    """Returns ``{"data": [...]}`` and records the requested URL + params."""

    name = "local"

    def __init__(self):
        self.calls: list[dict] = []

    def get(self, url, *, headers=None, params=None, timeout=30.0):
        self.calls.append({"url": url, "params": dict(params or {})})
        return _resp({"data": [{"Code": "1", "Date": "2025-04-01"}]})


# --------------------------------------------------------------------------- coverage

def test_catalog_coverage_every_path_is_v2():
    """No stub-only entries: every dataset path starts with /v2/ and is non-trivial."""
    catalog.assert_catalog_coverage()  # raises on any bad entry
    assert len(catalog.list_datasets()) >= 20  # Premium core + addons present


def test_catalog_groups_partition_all_datasets():
    all_ids = set(catalog.list_datasets())
    grouped = set()
    for g in ("core", "addon", "edinet"):
        grouped |= set(catalog.list_datasets(g))
    assert grouped == all_ids  # every dataset belongs to exactly one group


def test_catalog_unknown_dataset_raises():
    with pytest.raises(KeyError):
        catalog.get("does_not_exist")
    with pytest.raises(KeyError):
        catalog.path_of("nope")


# --------------------------------------------------------------------------- routing

@pytest.mark.parametrize("did", catalog.list_datasets())
def test_fetch_dataset_routes_to_catalog_path(did):
    """Every catalog dataset is fetchable and hits its declared /v2/ path."""
    http = _RecordingHttp()
    c = JQuantsClient(http, "k", retries=0, rate_limiter=_NO_RL)
    rows = c.fetch_dataset(did, code="1", from_date="2025-04-01", to_date="2025-04-02")
    assert len(http.calls) == 1
    expected = "https://api.jquants.com" + catalog.path_of(did)
    assert http.calls[0]["url"] == expected
    # records came back through the data envelope
    assert isinstance(rows, list) and _records({"data": rows})


def test_fetch_dataset_aliases_from_date_to_from():
    http = _RecordingHttp()
    c = JQuantsClient(http, "k", retries=0, rate_limiter=_NO_RL)
    c.fetch_dataset("markets_calendar", from_date="2025-04-01", to_date="2025-04-05")
    p = http.calls[0]["params"]
    assert p.get("from") == "2025-04-01"
    assert p.get("to") == "2025-04-05"
    assert "from_date" not in p and "to_date" not in p


def test_fetch_dataset_drops_empty_params():
    http = _RecordingHttp()
    c = JQuantsClient(http, "k", retries=0, rate_limiter=_NO_RL)
    c.fetch_dataset("equities_master", code=None, date="")
    assert http.calls[0]["params"] == {}


def test_fetch_dataset_paginates_via_pagination_key():
    class _Pager:
        name = "local"

        def __init__(self):
            self.n = 0
            self.last_params = None

        def get(self, url, *, headers=None, params=None, timeout=30.0):
            self.n += 1
            self.last_params = dict(params or {})
            if self.n == 1:
                return _resp({"data": [{"Code": "1"}], "pagination_key": "tok"})
            return _resp({"data": [{"Code": "2"}]})

    http = _Pager()
    c = JQuantsClient(http, "k", retries=0, rate_limiter=_NO_RL)
    rows = c.fetch_dataset("fins_dividend", code="1")
    assert [r["Code"] for r in rows] == ["1", "2"]
    assert http.last_params.get("pagination_key") == "tok"


def test_am_and_earnings_params_match_vendor_snapshot_apis():
    """AM and earnings-calendar query params match J-Quants V3 vendor snapshot APIs."""
    am = catalog.get("equities_bars_daily_am")
    assert am["params"] == ["code", "pagination_key"]
    assert "date" not in am["params"]
    assert "from" not in am["params"] and "to" not in am["params"]
    earn = catalog.get("equities_earnings_calendar")
    assert earn["params"] == ["pagination_key"]
    assert earn["date_mode"] == "today"
    assert "from" not in earn["params"] and "to" not in earn["params"]
    assert "date" not in earn["params"]
