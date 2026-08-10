"""EDINET DB normalizer: zero-safe numeric mapping."""

from __future__ import annotations

from ingestion.edinetdb.normalize import normalize_financials

ING = "2025-04-02T09:00:00+09:00"


def test_zero_revenue_preserved():
    rows = [{
        "code": "8697", "period": "2024Q4",
        "revenue": 0, "operating_income": 0, "net_income": 0,
    }]
    out = normalize_financials(rows, code="8697", ingested_at=ING)
    r = out[0]
    assert r["revenue"] == 0.0
    assert r["operating_income"] == 0.0
    assert r["net_income"] == 0.0


def test_first_present_key_wins_and_zero_beats_later_candidate():
    # revenue=0 must win over a non-zero net_sales fallback (0 is valid)
    rows = [{"code": "8697", "period": "2024Q4", "revenue": 0, "net_sales": 999}]
    r = normalize_financials(rows, code="8697", ingested_at=ING)[0]
    assert r["revenue"] == 0.0


def test_falls_through_to_second_key_when_first_absent():
    rows = [{"code": "8697", "period": "2024Q4", "net_sales": 500}]
    r = normalize_financials(rows, code="8697", ingested_at=ING)[0]
    assert r["revenue"] == 500.0


def test_string_zero_also_preserved():
    rows = [{"code": "8697", "period": "2024Q4", "revenue": "0"}]
    r = normalize_financials(rows, code="8697", ingested_at=ING)[0]
    assert r["revenue"] == 0.0
