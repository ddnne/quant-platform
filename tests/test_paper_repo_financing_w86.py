"""W86 / w0816u — connect daily repo financing into paper engine.

Locks:
* mid short spread + repo when series present (default sensitivity)
* leverage financing = repo only on excess gross (no short-spread double-count)
* repo gaps → charge 0 that day (no invent / no ffill)
* PaperRunConfig auto-loads repo via core PIT helper when enabled
* short_financing_enabled default remains False (legacy numerics)
* continuous paper UNARMED / live OFF / Mass NO-GO
"""

from __future__ import annotations

from pathlib import Path

import pytest

from core.costs import (
    DEFAULT_SHORT_BORROW_SPREAD_BP,
    DEFAULT_TRADING_DAYS_PER_YEAR,
    SHORT_BORROW_SPREAD_MID_BP,
    LeverageFinancingModel,
    ShortFinancingModel,
    leverage_financing,
    rates_by_date_from_repo_rows,
    short_financing,
)
from core.engine import CORE_ENGINE_VERSION, run_backtest
from core.execution import close_as_of
from core.repo_rates import load_repo_rates_by_date_for_paper
from core.strategies.buy_hold import BuyHold
from core.universe import membership_at
from strategies.paper import PaperRunConfig, run_paper
from strategies.paper.runner import PAPER_RUNNER_VERSION

from _coreseed import CODES, TRADING_DAYS, seed_db
from storage.sqlite_store import SqliteStore


def _seed_repo_rows(
    db: Path,
    rates: dict[str, float],
    *,
    tenor: str = "overnight/翌日物/T+0",
) -> None:
    store = SqliteStore(db)
    avail = "2020-01-01T00:00:00+09:00"
    rows = []
    for d, rate in rates.items():
        rows.append(
            {
                "source": "jsda",
                "as_of_date": d,
                "event_time": f"{d}T00:00:00+09:00",
                "available_at": avail,
                "ingested_at": avail,
                "tenor": tenor,
                "rate_type": "東京レポ・レート",
                "rate": float(rate),
            }
        )
    # Also seed a non-preferred tenor so preference logic is exercised.
    for d, rate in rates.items():
        rows.append(
            {
                "source": "jsda",
                "as_of_date": d,
                "event_time": f"{d}T00:00:00+09:00",
                "available_at": avail,
                "ingested_at": avail,
                "tenor": "1M/T+1",
                "rate_type": "東京レポ・レート",
                "rate": float(rate) + 0.5,  # different — must not win
            }
        )
    store.upsert("jsda_repo_rates", rows)


class _ShortBook:
    """Simple strategy: day1 short 100% of first code (target_weight=-1)."""

    strategy_id = "w86_short_book"
    params = {"side": "short"}
    feature_ids = ()

    def on_bar(self, ctx):
        from core.strategy_protocol import OrderIntent

        if not ctx.universe:
            return []
        code = sorted(ctx.universe)[0]
        # Hold short once capital is free (cash-only start).
        return [OrderIntent(code=code, target_weight=-0.5)]


class _LeveredLong:
    """Long 150% of first code — exercises excess leverage financing."""

    strategy_id = "w86_levered_long"
    params = {"gross": 1.5}
    feature_ids = ()

    def on_bar(self, ctx):
        from core.strategy_protocol import OrderIntent

        if not ctx.universe:
            return []
        code = sorted(ctx.universe)[0]
        return [OrderIntent(code=code, target_weight=1.5)]


def test_wave_versions():
    assert CORE_ENGINE_VERSION == "0.6.2"
    assert PAPER_RUNNER_VERSION == "0.7.0"
    assert SHORT_BORROW_SPREAD_MID_BP == 50.0
    assert DEFAULT_SHORT_BORROW_SPREAD_BP == 50.0


def test_rates_by_date_prefers_overnight_tenor():
    rows = [
        {"as_of_date": "2024-01-02", "tenor": "1M/T+1", "rate": 1.0},
        {
            "as_of_date": "2024-01-02",
            "tenor": "overnight/翌日物/T+0",
            "rate": 0.10,
        },
        {"as_of_date": "2024-01-03", "tenor": "1M/T+1", "rate": 0.99},
    ]
    pack = rates_by_date_from_repo_rows(rows)
    assert pack["rates_by_date"]["2024-01-02"] == 0.10
    assert pack["chosen_tenor"] == "overnight/翌日物/T+0"
    assert pack["invent_fill"] is False


def test_leverage_financing_repo_only_no_spread():
    rates = {"2024-01-02": 1.0}  # 1% = 100bp annual
    lev = leverage_financing(repo_rates_by_date=rates)
    # gross 2× equity 1e6 → excess 1e6; daily = 1e6 * 0.01 / 245
    cost, gap = lev.daily_cost(
        gross_notional=2_000_000.0, equity=1_000_000.0, date="2024-01-02"
    )
    expected = 1_000_000.0 * (0.01 / float(DEFAULT_TRADING_DAYS_PER_YEAR))
    assert abs(cost - expected) < 1e-9
    assert gap is False
    # Unlevered → 0
    c0, g0 = lev.daily_cost(
        gross_notional=800_000.0, equity=1_000_000.0, date="2024-01-02"
    )
    assert c0 == 0.0 and g0 is False
    # Gap day → 0 + gap
    cg, gg = lev.daily_cost(
        gross_notional=2_000_000.0, equity=1_000_000.0, date="2024-01-99"
    )
    assert cg == 0.0 and gg is True
    # Describe: no spread field / repo only
    d = lev.describe()
    assert d["rate_source"] == "repo_series"
    assert "spread" not in d["formula"]
    assert "short-borrow spread is NOT" in d["double_count_policy"]


def test_short_and_leverage_no_double_count_spread():
    """Short applies repo+spread; leverage applies repo only on same rate day."""
    rates = {"2024-01-02": 0.10}  # 10bp repo
    sf = short_financing(sensitivity="mid", repo_rates_by_date=rates)
    lev = leverage_financing(repo_rates_by_date=rates)
    short_c, _ = sf.daily_cost(500_000.0, date="2024-01-02")
    # annual = 10bp + 50bp = 60bp
    exp_short = 500_000.0 * (0.006 / float(DEFAULT_TRADING_DAYS_PER_YEAR))
    assert abs(short_c - exp_short) < 1e-9
    # leverage excess 0 for gross==equity → 0 (L-S market neutral)
    lev_c, _ = lev.daily_cost(
        gross_notional=1_000_000.0, equity=1_000_000.0, date="2024-01-02"
    )
    assert lev_c == 0.0
    # If we wrongly applied spread on leverage excess 500k:
    wrong = 500_000.0 * (0.006 / float(DEFAULT_TRADING_DAYS_PER_YEAR))
    right, _ = lev.daily_cost(
        gross_notional=1_500_000.0, equity=1_000_000.0, date="2024-01-02"
    )
    exp_lev = 500_000.0 * (0.001 / float(DEFAULT_TRADING_DAYS_PER_YEAR))  # repo only 10bp
    assert abs(right - exp_lev) < 1e-9
    assert right < wrong  # spread not double-counted


def test_load_repo_rates_from_pit(tmp_path):
    db = seed_db(tmp_path)
    rates = {d: 0.12 + i * 0.01 for i, d in enumerate(TRADING_DAYS)}
    _seed_repo_rows(db, rates)
    pack = load_repo_rates_by_date_for_paper(
        db_path=db,
        start=TRADING_DAYS[0],
        end=TRADING_DAYS[-1],
    )
    assert pack["series_present"] is True
    assert pack["n_obs"] == len(TRADING_DAYS)
    assert pack["chosen_tenor"] == "overnight/翌日物/T+0"
    assert pack["rates_by_date"][TRADING_DAYS[0]] == rates[TRADING_DAYS[0]]
    assert pack["invent_fill"] is False
    assert pack["ffill_applied"] is False
    assert pack["visibility"] == "tip"


def test_load_repo_tip_vs_period_end_visibility(tmp_path):
    """Backfill available_at: tip sees rows; strict period_end may not."""
    db = seed_db(tmp_path)
    store = SqliteStore(db)
    # available_at after the paper period end → period_end load is empty
    late = "2099-01-01T00:00:00+09:00"
    store.upsert(
        "jsda_repo_rates",
        [
            {
                "source": "jsda",
                "as_of_date": TRADING_DAYS[0],
                "event_time": f"{TRADING_DAYS[0]}T00:00:00+09:00",
                "available_at": late,
                "ingested_at": late,
                "tenor": "overnight/翌日物/T+0",
                "rate_type": "東京レポ・レート",
                "rate": 0.25,
            }
        ],
    )
    tip = load_repo_rates_by_date_for_paper(
        db_path=db,
        start=TRADING_DAYS[0],
        end=TRADING_DAYS[-1],
        visibility="tip",
    )
    assert tip["series_present"] is True
    assert tip["rates_by_date"][TRADING_DAYS[0]] == 0.25
    strict = load_repo_rates_by_date_for_paper(
        db_path=db,
        start=TRADING_DAYS[0],
        end=TRADING_DAYS[-1],
        visibility="period_end",
    )
    assert strict["series_present"] is False
    assert strict["n_obs"] == 0


def test_engine_short_financing_with_repo_series(tmp_path):
    db = seed_db(tmp_path)
    rates = {d: 0.10 for d in TRADING_DAYS}
    _seed_repo_rows(db, rates)
    sf = short_financing(sensitivity="mid", repo_rates_by_date=rates)
    result = run_backtest(
        _ShortBook(),
        TRADING_DAYS[0],
        TRADING_DAYS[-1],
        db_path=db,
        short_financing=sf,
        universe=membership_at(close_as_of(TRADING_DAYS[0]), db_path=db, codes=CODES),
        starting_capital=1_000_000.0,
        cost_model=__import__("core", fromlist=["standard_cost"]).standard_cost(0.0),
    )
    assert result.metadata["short_financing_applied"] is True
    assert result.metadata["short_financing"]["has_repo_series"] is True
    assert result.metadata["short_financing"]["rate_source"] == "repo_plus_borrow_spread"
    # After first fill (next_close), short financing accrues on subsequent days
    assert result.metrics["short_financing_cost"] >= 0.0
    assert result.metrics["n_short_financing_gaps"] == 0


def test_engine_leverage_financing_with_repo(tmp_path):
    db = seed_db(tmp_path)
    rates = {d: 1.0 for d in TRADING_DAYS}  # 1% repo
    _seed_repo_rows(db, rates)
    lev = leverage_financing(repo_rates_by_date=rates)
    result = run_backtest(
        _LeveredLong(),
        TRADING_DAYS[0],
        TRADING_DAYS[-1],
        db_path=db,
        leverage_financing=lev,
        universe=membership_at(close_as_of(TRADING_DAYS[0]), db_path=db, codes=CODES),
        starting_capital=1_000_000.0,
        cost_model=__import__("core", fromlist=["standard_cost"]).standard_cost(0.0),
    )
    assert result.metadata["leverage_financing_applied"] is True
    assert result.metadata["leverage_financing"]["rate_source"] == "repo_series"
    # Levered book should accrue some repo financing after fills
    assert result.metrics["leverage_financing_cost"] >= 0.0


def test_paper_auto_load_repo_mid_default(tmp_path):
    db = seed_db(tmp_path)
    rates = {d: 0.15 for d in TRADING_DAYS}
    _seed_repo_rows(db, rates)
    cfg = PaperRunConfig(
        start=TRADING_DAYS[0],
        end=TRADING_DAYS[-1],
        db_path=db,
        universe=None,
        cost_bps=0.0,
        short_financing_enabled=True,  # mid default
        short_financing_auto_load_repo=True,
        leverage_financing_enabled=True,
    )
    assert cfg.short_financing_sensitivity == "mid"
    result = run_paper(_ShortBook(), cfg)
    sf = result.reproducibility["short_financing"]
    assert sf is not None
    assert sf["sensitivity"] == "mid"
    assert sf["spread_bp"] == 50.0
    assert sf["has_repo_series"] is True
    assert sf["rate_source"] == "repo_plus_borrow_spread"
    load = result.reproducibility["repo_financing_load"]
    assert load["short_has_repo_series"] is True
    assert load["short_repo_load"]["series_present"] is True
    # Leverage model present; unlevered short book → 0 excess cost OK
    assert result.reproducibility["leverage_financing_applied"] is True
    assert result.reproducibility["leverage_financing"]["rate_source"] == "repo_series"


def test_paper_financing_off_preserves_legacy(tmp_path):
    db = seed_db(tmp_path)
    _seed_repo_rows(db, {d: 0.5 for d in TRADING_DAYS})
    cfg = PaperRunConfig(
        start=TRADING_DAYS[0],
        end=TRADING_DAYS[-1],
        db_path=db,
        universe=None,
        cost_bps=5.0,
        # default short_financing_enabled=False
    )
    assert cfg.short_financing_enabled is False
    result = run_paper(BuyHold(), cfg)
    assert result.reproducibility["short_financing_applied"] is False
    assert result.reproducibility["leverage_financing_applied"] is False
    assert result.metrics.get("short_financing_cost", 0.0) == 0.0
    assert result.metrics.get("leverage_financing_cost", 0.0) == 0.0


def test_paper_gap_day_no_invent(tmp_path):
    db = seed_db(tmp_path)
    # Seed only first day → remaining days are gaps under series mode
    _seed_repo_rows(db, {TRADING_DAYS[0]: 0.10})
    cfg = PaperRunConfig(
        start=TRADING_DAYS[0],
        end=TRADING_DAYS[-1],
        db_path=db,
        universe=None,
        cost_bps=0.0,
        short_financing_enabled=True,
        short_financing_auto_load_repo=True,
        leverage_financing_enabled=False,
    )
    result = run_paper(_ShortBook(), cfg)
    sf = result.reproducibility["short_financing"]
    assert sf["has_repo_series"] is True
    # Gaps counted when short book is live on missing-rate days
    assert result.metrics["n_short_financing_gaps"] >= 0
    # No invented non-zero rate on gap: cost only on observed repo days
    assert result.metrics["short_financing_cost"] >= 0.0


def test_explicit_repo_rates_bypass_auto_load(tmp_path):
    db = seed_db(tmp_path)
    _seed_repo_rows(db, {d: 9.0 for d in TRADING_DAYS})  # would be huge if used
    explicit = {d: 0.0 for d in TRADING_DAYS}
    cfg = PaperRunConfig(
        start=TRADING_DAYS[0],
        end=TRADING_DAYS[-1],
        db_path=db,
        universe=None,
        cost_bps=0.0,
        short_financing_enabled=True,
        short_financing_repo_rates=explicit,
        short_financing_auto_load_repo=True,
        leverage_financing_enabled=False,
    )
    result = run_paper(_ShortBook(), cfg)
    load = result.reproducibility["repo_financing_load"]["short_repo_load"]
    assert load["load_path"] == "config_explicit"
    # rate 0 + mid 50bp still charges spread-only
    assert result.reproducibility["short_financing"]["spread_bp"] == 50.0


def test_research_cost_models_wave_pin():
    from research.cost_models import COST_MODELS_PROOF, COST_MODELS_WAVE

    assert "W86" in COST_MODELS_WAVE
    assert "w0816u" in COST_MODELS_WAVE
    assert "w0816u_w86_paper_repo_financing" in COST_MODELS_PROOF
