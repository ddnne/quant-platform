"""EDINET DB normalizer: zero-safe numeric mapping.

Also covers ``run_edinetdb`` financials error-vs-skip semantics
(auto-sampled codes fail -> skipped; explicit codes fail -> error).
"""

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


# ---------------------------------------------------------------------------
# run_edinetdb: auto-sampled vs explicit financial codes
# ---------------------------------------------------------------------------

class _FakeEdinetClient:
    """Stand-in for EdinetDbClient: companies succeed, financials always fail.

    Lets us exercise run_edinetdb's error/skip wiring offline (no network,
    no retry/rate-limiter machinery).
    """

    def __init__(self, http, api_key, **kwargs):
        self.http = http
        self.api_key = api_key

    def list_companies(self, **kwargs):
        return [{"code": "8697"}, {"code": "8698"}, {"code": "8699"}]

    def financials(self, code):
        raise RuntimeError(f"financials failed for {code}")


class _FakeStore:
    def upsert(self, table, rows):
        return len(list(rows))

    def log_run(self, **kwargs):
        return None


def _run_edinetdb(tmp_path, monkeypatch, *, financial_codes):
    from ingestion.pipeline import run_edinetdb
    monkeypatch.setattr("ingestion.edinetdb.client.EdinetDbClient", _FakeEdinetClient)
    return run_edinetdb(
        http=object(),
        store=_FakeStore(),
        api_key="key",
        data_base=tmp_path,
        today="2025-04-02T09:00:00+09:00",
        runtime="local",
        financial_codes=financial_codes,
    )


def test_auto_sampled_financials_failure_is_skipped(tmp_path, monkeypatch):
    # no explicit codes -> best-effort sample from companies; per-code failure
    # is a clean skip, never an error.
    reports = _run_edinetdb(tmp_path, monkeypatch, financial_codes=None)
    fin = [r for r in reports if r.kind.startswith("financials/")]
    assert len(fin) == 3  # one per auto-picked company code
    assert all(r.skipped for r in fin)
    assert not any(r.error for r in fin)
    assert not any(r.effective_error for r in fin)
    # companies fetch still succeeds
    assert any(r.kind == "companies" and r.ok for r in reports)


def test_explicit_code_financials_failure_is_error(tmp_path, monkeypatch):
    # caller-supplied code is expected, so a failure is a real error.
    reports = _run_edinetdb(tmp_path, monkeypatch, financial_codes=["8697"])
    fin = [r for r in reports if r.kind.startswith("financials/")]
    assert len(fin) == 1
    assert fin[0].kind == "financials/8697"
    assert fin[0].error
    assert not fin[0].skipped
    assert fin[0].effective_error  # surfaces via decide_exit path
