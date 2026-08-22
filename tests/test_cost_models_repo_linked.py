"""W78 / w0816m — repo-linked research cost model (jsda_tokyo_repo_rates).

Locks:
* Prefer date-matched repo rates over fixed bp
* Missing dates → gap flags; never ffill / invent
* Leverage financing = f(repo[t], excess leverage)
* Short cost = f(repo[t] + spread, short_frac) with low/mid/high bands
* Long-only unlevered: tx + N/A short/financing
* checklist v2 / run_standard_research_eval prefers (not hard-requires) model
* Mass/READY stay closed
"""

from __future__ import annotations

import pytest

from research.cost_models import (
    COST_MODELS_VERSION,
    DEFAULT_LEVERAGE_FINANCING_ANNUAL_BP,
    DEFAULT_SHORT_BORROW_ANNUAL_BP,
    DEFAULT_SHORT_BORROW_SPREAD_BP,
    DEFAULT_TRADING_DAYS_PER_YEAR,
    POSITION_STYLE_LEVERED_LONG,
    POSITION_STYLE_LONG_ONLY_UNLEVERED,
    POSITION_STYLE_LONG_SHORT,
    RATE_SOURCE_FIXED_BP,
    RATE_SOURCE_NOT_APPLICABLE,
    RATE_SOURCE_REPO_PLUS_SPREAD,
    RATE_SOURCE_REPO_SERIES,
    SHORT_BORROW_SPREAD_HIGH_BP,
    SHORT_BORROW_SPREAD_LOW_BP,
    SHORT_BORROW_SPREAD_MID_BP,
    annotate_period_rows_with_extended_costs,
    build_leverage_short_cost_assumption,
    date_matched_leverage_financing_costs,
    date_matched_short_borrow_costs,
    default_long_only_unlevered_cost_assumption,
    leverage_financing_daily_cost_from_repo,
    load_repo_rate_series,
    load_repo_rate_series_from_mapping,
    load_repo_rate_series_from_pit,
    load_repo_rate_series_from_rows,
    lookup_repo_rate,
    mean_repo_rate_pct,
    repo_rate_pct_to_annual_bp,
    repo_rate_pct_to_annual_fraction,
    short_borrow_daily_cost_from_repo,
)
from research.eval_harness import (
    MASS_RESEARCH,
    PHASE7,
    run_standard_research_eval,
)
from research.eval_harness_checklist import (
    COST_MODEL_PREFER_REPO_LINKED,
    COST_MODEL_REQUIRE_REPO_LINKED,
    standard_research_eval_checklist_document,
)


# ---------------------------------------------------------------------------
# Synthetic series
# ---------------------------------------------------------------------------

# rate_pct units match JSDA schema (percent). 0.10 → 10bp annual.
SYNTH_RATES = {
    "2024-01-02": 0.10,   # 10bp
    "2024-01-03": 0.12,   # 12bp
    "2024-01-05": 0.08,   # 8bp  (gap on 2024-01-04)
}


def _series(**kwargs):
    return load_repo_rate_series_from_mapping(SYNTH_RATES, **kwargs)


# ---------------------------------------------------------------------------
# Unit conversions
# ---------------------------------------------------------------------------


def test_repo_rate_unit_conversion():
    assert abs(repo_rate_pct_to_annual_fraction(0.10) - 0.001) < 1e-15
    assert abs(repo_rate_pct_to_annual_bp(0.10) - 10.0) < 1e-12
    assert abs(repo_rate_pct_to_annual_bp(1.0) - 100.0) < 1e-12


# ---------------------------------------------------------------------------
# Load API + gap policy
# ---------------------------------------------------------------------------


def test_load_from_mapping_with_gaps_no_ffill():
    dates = ["2024-01-02", "2024-01-03", "2024-01-04", "2024-01-05"]
    s = _series(required_dates=dates)
    assert s["n_obs"] == 3
    assert s["gap_dates"] == ["2024-01-04"]
    assert s["n_gaps"] == 1
    assert s["coverage_complete"] is False
    assert s["ffill_applied"] is False
    assert s["invent_fill"] is False
    assert "2024-01-04" not in s["rates_by_date"]
    # Present dates keep original values — no invent
    assert s["rates_by_date"]["2024-01-02"] == 0.10


def test_load_from_rows_prefers_tenor():
    rows = [
        {"as_of_date": "2024-01-02", "tenor": "1週間物", "rate": 0.20, "rate_type": "東京レポ・レート"},
        {"as_of_date": "2024-01-02", "tenor": "隔日物", "rate": 0.10, "rate_type": "東京レポ・レート"},
        {"as_of_date": "2024-01-03", "tenor": "隔日物", "rate": 0.12, "rate_type": "東京レポ・レート"},
    ]
    s = load_repo_rate_series_from_rows(rows, required_dates=["2024-01-02", "2024-01-03", "2024-01-04"])
    assert s["rates_by_date"]["2024-01-02"] == 0.10  # prefer 隔日物
    assert s["gap_dates"] == ["2024-01-04"]
    assert s["ffill_applied"] is False


def test_load_repo_rate_series_unified():
    s1 = load_repo_rate_series(SYNTH_RATES, required_dates=["2024-01-04"])
    assert s1["n_gaps"] == 1
    s2 = load_repo_rate_series(
        [{"as_of_date": "2024-01-02", "tenor": "隔日物", "rate": 0.1}],
        required_dates=["2024-01-02", "2024-01-03"],
    )
    assert s2["gap_dates"] == ["2024-01-03"]
    empty = load_repo_rate_series(None, required_dates=["2024-01-02"])
    assert empty["n_obs"] == 0
    assert empty["gap_dates"] == ["2024-01-02"]


def test_lookup_repo_rate_gap_no_ffill():
    s = _series()
    hit = lookup_repo_rate(s, "2024-01-02")
    assert hit["is_gap"] is False
    assert hit["rate_pct"] == 0.10
    assert hit["ffill_applied"] is False

    gap = lookup_repo_rate(s, "2024-01-04")
    assert gap["is_gap"] is True
    assert gap["rate_pct"] is None
    assert gap["ffill_applied"] is False
    assert gap["reason"] == "missing_repo_rate"


def test_mean_excludes_gaps():
    s = _series(required_dates=["2024-01-02", "2024-01-03", "2024-01-04"])
    m = mean_repo_rate_pct(s, dates=["2024-01-02", "2024-01-03", "2024-01-04"])
    assert m["n_obs"] == 2
    assert m["n_gaps"] == 1
    assert abs(m["mean_rate_pct"] - 0.11) < 1e-12  # (0.10+0.12)/2
    assert abs(m["mean_annual_bp"] - 11.0) < 1e-12


def test_load_from_pit_injected():
    class _R:
        rows = [
            {"as_of_date": "2024-01-02", "tenor": "隔日物", "rate": 0.15},
            {"as_of_date": "2024-01-03", "tenor": "隔日物", "rate": 0.16},
        ]

    def fake_get(as_of, **kwargs):
        assert as_of == "2024-01-10T15:00:00+09:00"
        return _R()

    s = load_repo_rate_series_from_pit(
        as_of="2024-01-10T15:00:00+09:00",
        required_dates=["2024-01-02", "2024-01-03", "2024-01-04"],
        get_jsda_repo_rates_fn=fake_get,
    )
    assert s["n_obs"] == 2
    assert s["gap_dates"] == ["2024-01-04"]
    assert s["load_path"] == "pit.get_jsda_repo_rates"
    assert s["ffill_applied"] is False


# ---------------------------------------------------------------------------
# Financing / short pure formulas
# ---------------------------------------------------------------------------


def test_leverage_financing_from_repo():
    # repo 0.10% → 10bp annual; lev 2.0 → excess 1.0
    # daily = 0.001 * 1.0 / 245
    daily = leverage_financing_daily_cost_from_repo(0.10, gross_leverage=2.0)
    expected = 0.001 / float(DEFAULT_TRADING_DAYS_PER_YEAR)
    assert abs(daily - expected) < 1e-15
    assert leverage_financing_daily_cost_from_repo(0.10, gross_leverage=1.0) == 0.0


def test_short_borrow_from_repo_with_sensitivity():
    # repo 10bp + mid 50bp = 60bp annual; short_frac 0.5
    mid = short_borrow_daily_cost_from_repo(
        0.10, short_fraction=0.5, sensitivity="mid"
    )
    expected_mid = (60.0 / 10_000.0) / float(DEFAULT_TRADING_DAYS_PER_YEAR) * 0.5
    assert abs(mid - expected_mid) < 1e-15

    low = short_borrow_daily_cost_from_repo(
        0.10, short_fraction=0.5, sensitivity="low"
    )
    high = short_borrow_daily_cost_from_repo(
        0.10, short_fraction=0.5, sensitivity="high"
    )
    assert low < mid < high
    assert abs(SHORT_BORROW_SPREAD_LOW_BP - 25.0) < 1e-12
    assert abs(SHORT_BORROW_SPREAD_MID_BP - 50.0) < 1e-12
    assert abs(SHORT_BORROW_SPREAD_HIGH_BP - 150.0) < 1e-12


def test_date_matched_financing_gaps():
    s = _series()
    dates = ["2024-01-02", "2024-01-04", "2024-01-05"]
    out = date_matched_leverage_financing_costs(
        s, dates, gross_leverage=2.0
    )
    assert out["n_gaps"] == 1
    assert out["gap_dates"] == ["2024-01-04"]
    assert out["by_date"]["2024-01-04"]["is_gap"] is True
    assert out["by_date"]["2024-01-04"]["financing_daily"] is None
    assert out["by_date"]["2024-01-02"]["is_gap"] is False
    assert out["by_date"]["2024-01-02"]["financing_daily"] is not None
    assert out["ffill_applied"] is False
    assert out["invent_fill"] is False
    assert out["rate_source"] == RATE_SOURCE_REPO_SERIES


def test_date_matched_short_gaps():
    s = _series()
    out = date_matched_short_borrow_costs(
        s,
        ["2024-01-02", "2024-01-04"],
        short_fraction=0.5,
        sensitivity="mid",
    )
    assert out["n_gaps"] == 1
    assert out["by_date"]["2024-01-04"]["short_borrow_daily"] is None
    assert out["by_date"]["2024-01-02"]["short_borrow_daily"] > 0
    assert out["sensitivity"] == "mid"
    assert out["spread_bp"] == DEFAULT_SHORT_BORROW_SPREAD_BP
    assert out["ffill_applied"] is False


# ---------------------------------------------------------------------------
# Assumption builder
# ---------------------------------------------------------------------------


def test_long_only_unlevered_explicit_na():
    lo = default_long_only_unlevered_cost_assumption()
    assert lo["version"] == COST_MODELS_VERSION
    assert lo["assumptions_complete"] is True
    assert lo["short_borrow"]["not_applicable"] is True
    assert lo["leverage_financing"]["not_applicable"] is True
    assert lo["short_borrow"]["rate_source"] == RATE_SOURCE_NOT_APPLICABLE
    assert lo["leverage_financing"]["rate_source"] == RATE_SOURCE_NOT_APPLICABLE
    assert lo["transaction"]["one_way_cost_bp"] == 10.0
    assert lo["ready_declared"] is False
    assert lo["mass_research"] == "NO-GO"
    assert lo["connected_to_mass"] is False


def test_levered_prefers_repo_over_fixed():
    s = _series(required_dates=["2024-01-02", "2024-01-03", "2024-01-04"])
    ass = build_leverage_short_cost_assumption(
        position_style=POSITION_STYLE_LEVERED_LONG,
        gross_leverage=2.0,
        uses_leverage=True,
        repo_rate_series=s,
        prefer_repo_linked=True,
        required_dates=["2024-01-02", "2024-01-03", "2024-01-04"],
    )
    assert ass["repo_linked"] is True
    assert ass["leverage_financing"]["rate_source"] == RATE_SOURCE_REPO_SERIES
    # mean of 0.10, 0.12 only (gap excluded) → 11bp
    assert abs(ass["leverage_financing"]["annual_bp"] - 11.0) < 1e-9
    assert ass["repo_rate"]["n_gaps"] == 1
    assert ass["repo_rate"]["ffill_applied"] is False
    assert ass["repo_rate"]["invent_fill"] is False
    assert ass["assumptions_complete"] is True
    assert ass["ready_declared"] is False


def test_short_repo_plus_spread_and_fixed_fallback():
    s = _series()
    linked = build_leverage_short_cost_assumption(
        position_style=POSITION_STYLE_LONG_SHORT,
        short_fraction=0.5,
        uses_short=True,
        uses_leverage=False,
        repo_rate_series=s,
        short_borrow_sensitivity="mid",
    )
    assert linked["short_borrow"]["rate_source"] == RATE_SOURCE_REPO_PLUS_SPREAD
    # mean repo over all obs (0.10+0.12+0.08)/3 = 0.10 → 10bp + 50 spread = 60
    assert abs(linked["short_borrow"]["annual_bp"] - 60.0) < 1e-9
    assert linked["short_borrow"]["sensitivity"] == "mid"

    fixed = build_leverage_short_cost_assumption(
        position_style=POSITION_STYLE_LONG_SHORT,
        short_fraction=0.5,
        uses_short=True,
        uses_leverage=False,
        prefer_repo_linked=True,  # no series → fixed fallback
    )
    assert fixed["short_borrow"]["rate_source"] == RATE_SOURCE_FIXED_BP
    assert abs(fixed["short_borrow"]["annual_bp"] - DEFAULT_SHORT_BORROW_ANNUAL_BP) < 1e-12
    assert fixed["repo_linked"] is False


def test_fixed_financing_fallback_when_no_series():
    ass = build_leverage_short_cost_assumption(
        position_style=POSITION_STYLE_LEVERED_LONG,
        gross_leverage=2.0,
        uses_leverage=True,
    )
    assert ass["leverage_financing"]["rate_source"] == RATE_SOURCE_FIXED_BP
    assert abs(
        ass["leverage_financing"]["annual_bp"] - DEFAULT_LEVERAGE_FINANCING_ANNUAL_BP
    ) < 1e-12
    assert ass["assumptions_complete"] is True


def test_annotate_period_rows_date_matched_with_gap():
    s = _series()
    ass = build_leverage_short_cost_assumption(
        position_style=POSITION_STYLE_LEVERED_LONG,
        gross_leverage=2.0,
        uses_leverage=True,
        repo_rate_series=s,
    )
    rows = [
        {"period_id": "d1", "period_end": "2024-01-02", "gross_signed_mean_active": 0.01},
        {"period_id": "d2", "period_end": "2024-01-04", "gross_signed_mean_active": 0.01},
    ]
    ann = annotate_period_rows_with_extended_costs(
        rows, cost_assumption=ass, repo_rate_series=s
    )
    assert ann[0]["repo_rate_gap"] is False
    assert ann[0]["financing_daily"] is not None
    assert ann[0]["net_extended_mean_active"] is not None
    assert ann[1]["repo_rate_gap"] is True
    assert ann[1]["financing_daily"] is None
    assert ann[1]["net_extended_mean_active"] is None  # gap → no invent net


def test_cost_models_prefers_repo():
    ass = build_leverage_short_cost_assumption(prefer_repo_linked=True)
    assert ass["version"] == COST_MODELS_VERSION
    assert ass["prefer_repo_linked"] is True
    assert ass["liquidity"]["gap_policy"] == "disclose_only_no_ffill_no_invent"
    assert ass["ready_declared"] is False
    assert ass["mass_research"] == "NO-GO"


# ---------------------------------------------------------------------------
# Harness wiring
# ---------------------------------------------------------------------------


def test_checklist_document_cost_model_defaults():
    doc = standard_research_eval_checklist_document()
    assert doc["cost_model_defaults"]["prefer_repo_linked"] is True
    assert doc["cost_model_defaults"]["require_repo_linked"] is False
    assert "repo_linked_cost_model" in doc["recommended"]
    assert COST_MODEL_PREFER_REPO_LINKED is True
    assert COST_MODEL_REQUIRE_REPO_LINKED is False
    assert doc["cost_models_surface"]["version"] == COST_MODELS_VERSION
    assert doc["ready_declared"] is False
    assert doc["mass_research"] == "NO-GO"


def test_run_standard_research_eval_with_repo_series():
    s = _series(required_dates=["2024-01-02", "2024-01-03", "2024-01-04"])
    out = run_standard_research_eval(
        dry_run=True,
        position_style=POSITION_STYLE_LEVERED_LONG,
        gross_leverage=2.0,
        uses_leverage=True,
        repo_rate_series=s,
        prefer_repo_linked=True,
        repo_required_dates=["2024-01-02", "2024-01-03", "2024-01-04"],
    )
    lev = out["leverage_short_costs"]
    assert lev["repo_linked"] is True
    assert lev["leverage_financing"]["rate_source"] == RATE_SOURCE_REPO_SERIES
    assert lev["repo_rate"]["n_gaps"] == 1
    assert lev["repo_rate"]["ffill_applied"] is False
    assert out["prefer_repo_linked"] is True
    assert out["require_repo_linked"] is False
    assert out["repo_rate_series"] is not None
    assert out["ready_declared"] is False
    assert out["mass_research"] == MASS_RESEARCH == "NO-GO"
    assert out["phase7"] == PHASE7 == "OFF"
    assert out["connected_to_ready"] is False
    assert out["connected_to_mass"] is False
    assert out["research_candidate"] is False


def test_require_repo_linked_blocks_when_missing():
    out = run_standard_research_eval(
        dry_run=True,
        position_style=POSITION_STYLE_LEVERED_LONG,
        gross_leverage=2.0,
        uses_leverage=True,
        require_repo_linked=True,
        # no series
    )
    assert out["leverage_short_costs"]["assumptions_complete"] is False
    assert "repo_rate_series" in out["leverage_short_costs"]["missing_disclosure"]
    assert out["research_candidate"] is False
    assert out["ready_declared"] is False
    assert out["mass_research"] == "NO-GO"


def test_long_only_wiring_still_complete_without_repo():
    out = run_standard_research_eval(dry_run=True)
    assert out["leverage_short_costs"]["assumptions_complete"] is True
    assert out["leverage_short_costs"]["position_style"] == POSITION_STYLE_LONG_ONLY_UNLEVERED
    assert out["prefer_repo_linked"] is True
    assert out["ready_declared"] is False
    assert out["mass_research"] == "NO-GO"
