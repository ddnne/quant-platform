"""W79 / w0816n — liquidity-linked research cost model.

Locks:
* Liquidity proxy from equities_bars yen turnover (ADV)
* high/mid/low buckets scale one_way_tx and/or short spread
* Short low/mid/high sensitivity retained and combined with liquidity mult
* Missing liquidity → gap disclose; mult=1.0; never invent
* Repo-linked cost_models v2 kept
* checklist v2 / run_standard_research_eval wiring
* Mass/READY stay closed
"""

from __future__ import annotations

from research.cost_models import (
    COST_MODELS_VERSION,
    COST_MODELS_WAVE,
    DEFAULT_ONE_WAY_COST,
    DEFAULT_ONE_WAY_COST_BP,
    DEFAULT_SHORT_BORROW_ANNUAL_BP,
    LIQUIDITY_ADV_HIGH_JPY,
    LIQUIDITY_ADV_MID_JPY,
    LIQUIDITY_BUCKET_HIGH,
    LIQUIDITY_BUCKET_LOW,
    LIQUIDITY_BUCKET_MID,
    LIQUIDITY_BUCKET_MISSING,
    LIQUIDITY_TX_MULT,
    POSITION_STYLE_LONG_ONLY_UNLEVERED,
    POSITION_STYLE_LONG_SHORT,
    RATE_SOURCE_REPO_PLUS_SPREAD,
    SHORT_BORROW_SPREAD_HIGH_BP,
    SHORT_BORROW_SPREAD_LOW_BP,
    SHORT_BORROW_SPREAD_MID_BP,
    apply_liquidity_to_one_way_cost,
    apply_liquidity_to_short_spread_bp,
    build_leverage_short_cost_assumption,
    compute_liquidity_proxy_from_adv,
    compute_liquidity_proxy_from_bars,
    liquidity_bucket_from_proxy,
    liquidity_cost_multipliers,
    load_repo_rate_series_from_mapping,
    resolve_liquidity_modulation,
    yen_turnover_from_bar,
)


# ---------------------------------------------------------------------------
# Synthetic bars
# ---------------------------------------------------------------------------

# High ADV (~¥2bn/day via turnover_value)
HIGH_BARS = [
    {"date": "2024-01-02", "code": "7203", "turnover_value": 2_000_000_000},
    {"date": "2024-01-03", "code": "7203", "turnover_value": 2_200_000_000},
    {"date": "2024-01-05", "code": "7203", "turnover_value": 1_800_000_000},
]

# Mid ADV (~¥300m/day via close*volume)
MID_BARS = [
    {"date": "2024-01-02", "code": "9999", "close": 1000.0, "volume": 300_000},
    {"date": "2024-01-03", "code": "9999", "close": 1000.0, "volume": 300_000},
]

# Low ADV (~¥10m/day)
LOW_BARS = [
    {"date": "2024-01-02", "code": "1111", "close": 100.0, "volume": 100_000},
    {"date": "2024-01-03", "code": "1111", "close": 100.0, "volume": 100_000},
]

SYNTH_REPO = {
    "2024-01-02": 0.10,  # 10bp
    "2024-01-03": 0.12,
    "2024-01-05": 0.08,
}


# ---------------------------------------------------------------------------
# Yen turnover + proxy
# ---------------------------------------------------------------------------


def test_yen_turnover_prefers_turnover_value():
    hit = yen_turnover_from_bar(
        {"date": "2024-01-02", "turnover_value": 1e9, "close": 100, "volume": 1}
    )
    assert hit["is_gap"] is False
    assert hit["yen_turnover"] == 1e9
    assert hit["source_field"] == "turnover_value"


def test_yen_turnover_fallback_close_x_volume():
    hit = yen_turnover_from_bar(
        {"date": "2024-01-02", "close": 500.0, "volume": 2000.0}
    )
    assert hit["is_gap"] is False
    assert hit["yen_turnover"] == 1_000_000.0
    assert hit["source_field"] == "close_x_volume"


def test_yen_turnover_gap_no_invent():
    hit = yen_turnover_from_bar({"date": "2024-01-02", "code": "X"})
    assert hit["is_gap"] is True
    assert hit["yen_turnover"] is None


def test_compute_proxy_from_bars_adv_and_gaps():
    proxy = compute_liquidity_proxy_from_bars(
        HIGH_BARS,
        required_dates=["2024-01-02", "2024-01-03", "2024-01-04", "2024-01-05"],
    )
    assert proxy["is_gap"] is False
    assert proxy["n_obs"] == 3
    assert proxy["gap_dates"] == ["2024-01-04"]
    assert proxy["ffill_applied"] is False
    assert proxy["invent_fill"] is False
    # mean of 2.0, 2.2, 1.8 bn
    assert abs(proxy["adv_jpy"] - 2_000_000_000.0) < 1.0


def test_compute_proxy_empty_is_gap():
    proxy = compute_liquidity_proxy_from_bars([])
    assert proxy["is_gap"] is True
    assert proxy["adv_jpy"] is None
    assert proxy["n_obs"] == 0
    assert proxy["invent_fill"] is False


def test_compute_proxy_from_adv_scalar():
    proxy = compute_liquidity_proxy_from_adv(5e8)
    assert proxy["adv_jpy"] == 5e8
    assert proxy["is_gap"] is False
    gap = compute_liquidity_proxy_from_adv(None)
    assert gap["is_gap"] is True


# ---------------------------------------------------------------------------
# Buckets + multipliers
# ---------------------------------------------------------------------------


def test_bucket_thresholds():
    assert liquidity_bucket_from_proxy(LIQUIDITY_ADV_HIGH_JPY)["bucket"] == LIQUIDITY_BUCKET_HIGH
    assert liquidity_bucket_from_proxy(LIQUIDITY_ADV_MID_JPY)["bucket"] == LIQUIDITY_BUCKET_MID
    assert liquidity_bucket_from_proxy(LIQUIDITY_ADV_MID_JPY - 1)["bucket"] == LIQUIDITY_BUCKET_LOW
    missing = liquidity_bucket_from_proxy(None)
    assert missing["bucket"] == LIQUIDITY_BUCKET_MISSING
    assert missing["is_gap"] is True
    assert missing["invent_fill"] is False


def test_topix_soft_upgrade_only_when_adv_observed():
    # mid ADV + topix → high
    p = compute_liquidity_proxy_from_adv(LIQUIDITY_ADV_MID_JPY, is_topix=True)
    b = liquidity_bucket_from_proxy(p)
    assert b["bucket"] == LIQUIDITY_BUCKET_HIGH
    assert b["soft_upgrade_applied"] is True
    # missing ADV + topix → still missing (no invent)
    p2 = compute_liquidity_proxy_from_adv(None, is_topix=True)
    b2 = liquidity_bucket_from_proxy(p2)
    assert b2["bucket"] == LIQUIDITY_BUCKET_MISSING
    assert b2["is_gap"] is True


def test_multipliers_ordering():
    h = liquidity_cost_multipliers(LIQUIDITY_BUCKET_HIGH)
    m = liquidity_cost_multipliers(LIQUIDITY_BUCKET_MID)
    lo = liquidity_cost_multipliers(LIQUIDITY_BUCKET_LOW)
    gap = liquidity_cost_multipliers(LIQUIDITY_BUCKET_MISSING)
    assert h["tx_mult"] < m["tx_mult"] < lo["tx_mult"]
    assert h["short_spread_mult"] < m["short_spread_mult"] < lo["short_spread_mult"]
    assert gap["tx_mult"] == 1.0
    assert gap["short_spread_mult"] == 1.0
    assert gap["modulated"] is False
    assert gap["is_gap"] is True


def test_apply_helpers():
    assert abs(
        apply_liquidity_to_one_way_cost(0.001, tx_mult=2.5) - 0.0025
    ) < 1e-15
    assert abs(
        apply_liquidity_to_short_spread_bp(50.0, short_spread_mult=2.0) - 100.0
    ) < 1e-12


# ---------------------------------------------------------------------------
# Combined short sensitivity × liquidity
# ---------------------------------------------------------------------------


def test_short_sensitivity_times_liquidity_mult():
    # mid sensitivity 50bp * low liq mult 2.0 = 100bp effective spread
    liq = resolve_liquidity_modulation(
        liquidity_bucket=LIQUIDITY_BUCKET_LOW,
        prefer_liquidity_linked=True,
    )
    assert liq["applied"] is True
    assert liq["bucket"] == LIQUIDITY_BUCKET_LOW
    spread_eff = apply_liquidity_to_short_spread_bp(
        SHORT_BORROW_SPREAD_MID_BP,
        short_spread_mult=liq["short_spread_mult"],
    )
    assert abs(spread_eff - 100.0) < 1e-12

    # low sensitivity 25 * high liq 1.0 = 25
    liq_h = resolve_liquidity_modulation(liquidity_bucket=LIQUIDITY_BUCKET_HIGH)
    assert abs(
        apply_liquidity_to_short_spread_bp(
            SHORT_BORROW_SPREAD_LOW_BP,
            short_spread_mult=liq_h["short_spread_mult"],
        )
        - 25.0
    ) < 1e-12

    # high sensitivity 150 * mid liq 1.5 = 225
    liq_m = resolve_liquidity_modulation(liquidity_bucket=LIQUIDITY_BUCKET_MID)
    assert abs(
        apply_liquidity_to_short_spread_bp(
            SHORT_BORROW_SPREAD_HIGH_BP,
            short_spread_mult=liq_m["short_spread_mult"],
        )
        - 225.0
    ) < 1e-12


def test_missing_liquidity_unmodulated_gap_disclosed():
    liq = resolve_liquidity_modulation(prefer_liquidity_linked=True)
    assert liq["is_gap"] is True
    assert liq["applied"] is False
    assert liq["tx_mult"] == 1.0
    assert liq["short_spread_mult"] == 1.0
    assert liq["invent_fill"] is False


def test_prefer_liquidity_false_forces_unmodulated():
    liq = resolve_liquidity_modulation(
        liquidity_bucket=LIQUIDITY_BUCKET_LOW,
        prefer_liquidity_linked=False,
    )
    assert liq["bucket"] == LIQUIDITY_BUCKET_LOW  # still disclosed
    assert liq["tx_mult"] == 1.0
    assert liq["short_spread_mult"] == 1.0
    assert liq["applied"] is False


# ---------------------------------------------------------------------------
# Assumption builder
# ---------------------------------------------------------------------------


def test_long_only_tx_scaled_by_low_liquidity():
    ass = build_leverage_short_cost_assumption(
        position_style=POSITION_STYLE_LONG_ONLY_UNLEVERED,
        liquidity_bars=LOW_BARS,
        prefer_liquidity_linked=True,
    )
    assert ass["version"] == COST_MODELS_VERSION
    assert ass["wave"] == COST_MODELS_WAVE
    assert ass["liquidity_linked"] is True
    assert ass["liquidity"]["bucket"] == LIQUIDITY_BUCKET_LOW
    assert abs(
        ass["transaction"]["one_way_cost_bp"]
        - DEFAULT_ONE_WAY_COST_BP * LIQUIDITY_TX_MULT["low"]
    ) < 1e-9
    assert ass["transaction"]["one_way_cost_base_bp"] == DEFAULT_ONE_WAY_COST_BP
    assert ass["short_borrow"]["not_applicable"] is True
    assert ass["assumptions_complete"] is True
    assert ass["ready_declared"] is False
    assert ass["mass_research"] == "NO-GO"


def test_short_repo_plus_spread_with_liquidity_and_sensitivity():
    s = load_repo_rate_series_from_mapping(SYNTH_REPO)
    ass = build_leverage_short_cost_assumption(
        position_style=POSITION_STYLE_LONG_SHORT,
        short_fraction=0.5,
        uses_short=True,
        uses_leverage=False,
        repo_rate_series=s,
        short_borrow_sensitivity="mid",
        liquidity_bars=LOW_BARS,
        prefer_liquidity_linked=True,
    )
    assert ass["repo_linked"] is True
    assert ass["liquidity_linked"] is True
    assert ass["short_borrow"]["rate_source"] == RATE_SOURCE_REPO_PLUS_SPREAD
    assert ass["short_borrow"]["sensitivity"] == "mid"
    # mean repo (0.10+0.12+0.08)/3 = 0.10 → 10bp + (50*2.0)=100 spread = 110
    assert abs(ass["short_borrow"]["spread_base_bp"] - 50.0) < 1e-12
    assert abs(ass["short_borrow"]["spread_bp"] - 100.0) < 1e-12
    assert abs(ass["short_borrow"]["annual_bp"] - 110.0) < 1e-9
    assert ass["liquidity"]["ffill_applied"] is False
    assert ass["liquidity"]["invent_fill"] is False


def test_high_liquidity_keeps_base_tx():
    ass = build_leverage_short_cost_assumption(
        liquidity_bars=HIGH_BARS,
        prefer_liquidity_linked=True,
    )
    assert ass["liquidity"]["bucket"] == LIQUIDITY_BUCKET_HIGH
    assert abs(ass["transaction"]["one_way_cost"] - DEFAULT_ONE_WAY_COST) < 1e-15
    assert ass["liquidity_linked"] is True


def test_missing_liquidity_still_complete_unmodulated():
    ass = build_leverage_short_cost_assumption(
        position_style=POSITION_STYLE_LONG_SHORT,
        short_fraction=0.5,
        uses_short=True,
        prefer_liquidity_linked=True,
        # no liquidity inputs
    )
    assert ass["liquidity"]["is_gap"] is True
    assert ass["liquidity_linked"] is False
    assert ass["transaction"]["liquidity_tx_mult"] == 1.0
    assert abs(
        ass["short_borrow"]["annual_bp"] - DEFAULT_SHORT_BORROW_ANNUAL_BP
    ) < 1e-12
    assert ass["assumptions_complete"] is True
    assert ass["liquidity"]["invent_fill"] is False


def test_require_liquidity_linked_blocks_when_missing():
    ass = build_leverage_short_cost_assumption(
        require_liquidity_linked=True,
        prefer_liquidity_linked=True,
    )
    assert ass["assumptions_complete"] is False
    assert "liquidity_proxy" in ass["missing_disclosure"]
    assert ass["ready_declared"] is False


def test_explicit_bucket_override():
    ass = build_leverage_short_cost_assumption(
        liquidity_bucket="mid",
        prefer_liquidity_linked=True,
    )
    assert ass["liquidity"]["bucket"] == LIQUIDITY_BUCKET_MID
    assert abs(
        ass["transaction"]["one_way_cost_bp"]
        - DEFAULT_ONE_WAY_COST_BP * LIQUIDITY_TX_MULT["mid"]
    ) < 1e-9


def test_cost_models_liquidity_surface_constants():
    from research.cost_models import (
        LIQUIDITY_DATASET_ID,
        LIQUIDITY_SHORT_SPREAD_MULT,
        SHORT_BORROW_SPREAD_SENSITIVITY,
    )

    assert LIQUIDITY_DATASET_ID == "equities_bars_daily"
    assert LIQUIDITY_TX_MULT["low"] == 2.5
    assert LIQUIDITY_SHORT_SPREAD_MULT["low"] == 2.0
    assert SHORT_BORROW_SPREAD_SENSITIVITY["mid"] == 50.0
    ass = build_leverage_short_cost_assumption(prefer_liquidity_linked=True)
    assert ass["version"] == COST_MODELS_VERSION
    assert ass["prefer_liquidity_linked"] is True
    assert ass["require_liquidity_linked"] is False
    assert ass["ready_declared"] is False
    assert ass["mass_research"] == "NO-GO"


def test_mid_bars_proxy_bucket():
    proxy = compute_liquidity_proxy_from_bars(MID_BARS)
    # 1000 * 300_000 = 3e8 → mid
    assert abs(proxy["adv_jpy"] - 300_000_000.0) < 1.0
    b = liquidity_bucket_from_proxy(proxy)
    assert b["bucket"] == LIQUIDITY_BUCKET_MID
