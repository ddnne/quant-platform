"""W85 / w0816t — short cost = f(repo[t]) + fixed spread (L/M/H) wiring.

Locks:
* short_annual = repo_annual_bp + spread_bp (25/50/150)
* hold cost = daily * hold_days (multi-day L-S approved approx)
* remeasure_period_rows_with_short_cost applies mid primary by default
* repo gaps → no invent / no ffill
* paper ShortFinancingModel daily charge on short notional
* Mass/READY stay closed
"""

from __future__ import annotations

import pytest

from core.costs import (
    SHORT_BORROW_SPREAD_HIGH_BP,
    SHORT_BORROW_SPREAD_LOW_BP,
    SHORT_BORROW_SPREAD_MID_BP,
    ShortFinancingModel,
    short_financing,
)
from research.cost_models import (
    COST_MODELS_PROOF,
    COST_MODELS_VERSION,
    COST_MODELS_WAVE,
    DEFAULT_TRADING_DAYS_PER_YEAR,
    RATE_SOURCE_REPO_PLUS_SPREAD,
    SHORT_BORROW_SPREAD_SENSITIVITY,
    load_repo_rate_series_from_mapping,
    remeasure_period_rows_with_short_cost,
    research_net_with_short_hold_cost,
    resolve_short_borrow_spread_bp,
    short_borrow_daily_cost_from_repo,
    short_borrow_hold_cost_from_repo,
    short_cost_sensitivity_bands,
)


SYNTH = {
    "2024-01-02": 0.10,  # 10bp
    "2024-01-03": 0.12,
    "2024-01-05": 0.08,
    # gap on 2024-01-04
}


def _series(**kwargs):
    return load_repo_rate_series_from_mapping(SYNTH, **kwargs)


def test_wave_and_proof_pin():
    from research.cost_models import COST_MODELS_PROOF_SHORT_COST_W85

    assert COST_MODELS_VERSION == "research-cost-models/v2"
    # Wave tip advanced to W86 paper-repo connect; W85 short-cost proof pinned.
    assert "W86" in COST_MODELS_WAVE or "W85" in COST_MODELS_WAVE
    assert "w0816t_w85_short_cost" in COST_MODELS_PROOF_SHORT_COST_W85
    assert SHORT_BORROW_SPREAD_SENSITIVITY == {
        "low": 25.0,
        "mid": 50.0,
        "high": 150.0,
    }


def test_resolve_spread_sensitivity_bands():
    bp, lab = resolve_short_borrow_spread_bp(sensitivity="low")
    assert bp == 25.0 and lab == "low"
    bp, lab = resolve_short_borrow_spread_bp(sensitivity="mid")
    assert bp == 50.0 and lab == "mid"
    bp, lab = resolve_short_borrow_spread_bp(sensitivity="high")
    assert bp == 150.0 and lab == "high"
    bp, lab = resolve_short_borrow_spread_bp(spread_bp=50.0)
    assert lab == "mid"
    with pytest.raises(ValueError):
        resolve_short_borrow_spread_bp(sensitivity="extreme")


def test_short_hold_cost_scales_with_hold_and_sensitivity():
    # repo 10bp + mid 50 = 60bp annual; frac 0.5; hold 10
    daily = short_borrow_daily_cost_from_repo(
        0.10, short_fraction=0.5, sensitivity="mid"
    )
    hold = short_borrow_hold_cost_from_repo(
        0.10, hold_days=10, short_fraction=0.5, sensitivity="mid"
    )
    assert abs(hold - daily * 10) < 1e-15
    low = short_borrow_hold_cost_from_repo(
        0.10, hold_days=10, short_fraction=0.5, sensitivity="low"
    )
    high = short_borrow_hold_cost_from_repo(
        0.10, hold_days=10, short_fraction=0.5, sensitivity="high"
    )
    assert low < hold < high
    # Explicit magnitudes (bp over hold)
    expected_mid_bp = (60.0 / 10_000.0) / float(DEFAULT_TRADING_DAYS_PER_YEAR) * 0.5 * 10
    assert abs(hold - expected_mid_bp) < 1e-15


def test_sensitivity_bands_gap_no_invent():
    gap = short_cost_sensitivity_bands(None, hold_days=10, short_fraction=0.5)
    for lab in ("low", "mid", "high"):
        assert gap["bands"][lab]["is_gap"] is True
        assert gap["bands"][lab]["short_borrow_hold"] is None
    ok = short_cost_sensitivity_bands(0.10, hold_days=10, short_fraction=0.5)
    assert ok["bands"]["mid"]["is_gap"] is False
    assert ok["bands"]["mid"]["short_borrow_hold"] > 0
    assert ok["bands"]["low"]["spread_base_bp"] == 25.0
    assert ok["bands"]["high"]["spread_base_bp"] == 150.0


def test_research_net_with_short_hold():
    # gross 100bp, am_tx 1bp, short hold 1.22bp → ~97.78bp
    g = 0.01
    am = 0.0001
    sh = short_borrow_hold_cost_from_repo(
        0.10, hold_days=10, short_fraction=0.5, sensitivity="mid"
    )
    net = research_net_with_short_hold_cost(
        g, amortized_one_way_cost=am, short_borrow_hold=sh
    )
    assert abs(net - (g - am - sh)) < 1e-15
    assert research_net_with_short_hold_cost(
        g, amortized_one_way_cost=am, short_borrow_hold=None
    ) is None  # gap → no invent


def test_remeasure_period_rows_primary_mid_and_gap():
    s = _series()
    rows = [
        {
            "period_id": "p1",
            "status": "ok",
            "period_end": "2024-01-02",
            "hold_days": 10,
            "gross_signed_mean_active": 0.01,
            "amortized_one_way_cost": 0.0001,
            "net_one_way_mean_active": 0.0099,  # tx-only
        },
        {
            "period_id": "p_gap",
            "status": "ok",
            "period_end": "2024-01-04",  # gap
            "hold_days": 10,
            "gross_signed_mean_active": 0.01,
            "amortized_one_way_cost": 0.0001,
            "net_one_way_mean_active": 0.0099,
        },
    ]
    pack = remeasure_period_rows_with_short_cost(
        rows,
        repo_rate_series=s,
        short_fraction=0.5,
        hold_days=10,
        default_sensitivity="mid",
        apply_primary_net=True,
    )
    assert pack["default_sensitivity"] == "mid"
    assert pack["n_short_cost_obs"] == 1
    assert pack["n_repo_gaps"] == 1
    r0 = pack["period_rows"][0]
    assert r0["short_cost_applied"] is True
    assert r0["short_rate_source"] == RATE_SOURCE_REPO_PLUS_SPREAD
    # primary net = gross - am - short_hold < tx-only
    assert r0["net_one_way_mean_active"] < 0.0099
    assert "low" in r0["short_cost_sensitivity"]
    assert "high" in r0["short_cost_sensitivity"]
    assert (
        r0["short_cost_sensitivity"]["low"]["net_with_short"]
        > r0["short_cost_sensitivity"]["high"]["net_with_short"]
    )
    r_gap = pack["period_rows"][1]
    assert r_gap["repo_rate_gap"] is True
    assert r_gap["short_cost_applied"] is False
    # gap: tx-only retained, no invent short
    assert abs(r_gap["net_one_way_mean_active"] - 0.0099) < 1e-15
    # summary bands
    assert pack["summary_by_sensitivity"]["mid"]["n_periods"] == 1
    assert pack["ready_declared"] is False
    assert pack["mass_research"] == "NO-GO"


def test_paper_short_financing_model_formula_and_gap():
    rates = {"2024-01-02": 0.10, "2024-01-03": 0.12}
    m = short_financing(
        sensitivity="mid",
        repo_rates_by_date=rates,
    )
    assert m.spread_bp == SHORT_BORROW_SPREAD_MID_BP
    cost, gap = m.daily_cost(1_000_000.0, date="2024-01-02")
    # annual = 10bp repo + 50bp spread = 60bp; daily frac = 0.006 / 245
    expected = 1_000_000.0 * (0.006 / float(DEFAULT_TRADING_DAYS_PER_YEAR))
    assert abs(cost - expected) < 1e-9
    assert gap is False
    cost_gap, is_gap = m.daily_cost(1_000_000.0, date="2024-01-04")
    assert cost_gap == 0.0
    assert is_gap is True  # no invent

    fixed = ShortFinancingModel(
        sensitivity="high",
        repo_rates_by_date=None,
        fallback_repo_annual_bp=0.0,
    )
    assert fixed.spread_bp == SHORT_BORROW_SPREAD_HIGH_BP
    c_fix, g_fix = fixed.daily_cost(500_000.0, date="2024-01-02")
    assert g_fix is False
    assert c_fix > 0
    # high > mid for same notional with fixed fallback
    mid_fixed = short_financing(sensitivity="mid")
    c_mid, _ = mid_fixed.daily_cost(500_000.0, date="2024-01-02")
    assert c_fix > c_mid
    assert SHORT_BORROW_SPREAD_LOW_BP == 25.0


def test_paper_short_financing_disabled_charges_zero():
    m = short_financing(sensitivity="mid", enabled=False)
    c, g = m.daily_cost(1_000_000.0, date="2024-01-02")
    assert c == 0.0 and g is False
    assert m.describe()["enabled"] is False
