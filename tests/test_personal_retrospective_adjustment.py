"""Behavioral invariants for the personal retrospective split-adjusted DRAFT path."""

from __future__ import annotations

import json

import features
import pytest
from _coreseed import TRADING_DAYS, seed_db
from core import PERSONAL_RETROSPECTIVE_ADJUSTED, run_backtest, standard_cost
from core.execution import close_as_of
from core.strategies.buy_hold import BuyHold
from core.universe import membership_at
from data_contracts.identity import natural_key
from features.complete21_min_parsers import (
    _latest_fins_per_share_observation,
    _retrospective_split_safety,
)
from price_basis import PIT_ADJUSTED
from storage.sqlite_store import SqliteStore
from strategies.paper import Lifecycle, PaperRunConfig, run_paper


def _split_prices():
    raw = {
        "1332": {
            TRADING_DAYS[0]: 100.0,
            TRADING_DAYS[1]: 100.0,
            TRADING_DAYS[2]: 50.0,
            TRADING_DAYS[3]: 50.0,
        }
    }
    adjusted = {"1332": {day: 50.0 for day in TRADING_DAYS}}
    return raw, adjusted


def test_adjusted_buy_and_hold_crosses_split_without_synthetic_loss(tmp_path) -> None:
    raw, adjusted = _split_prices()
    db = seed_db(
        tmp_path, codes=["1332"], prices=raw, adjustment_prices=adjusted
    )

    result = run_backtest(
        BuyHold(),
        TRADING_DAYS[0],
        TRADING_DAYS[-1],
        db_path=db,
        universe=membership_at(
            close_as_of(TRADING_DAYS[0]), db_path=db, codes=("1332",)
        ),
        price_basis=PERSONAL_RETROSPECTIVE_ADJUSTED,
        cost_model=standard_cost(bps=0.0),
    )

    assert result.trades[0]["price"] == 50.0
    assert [row["equity"] for row in result.equity_curve] == pytest.approx(
        [1_000_000.0] * len(TRADING_DAYS)
    )
    assert result.metadata["valuation_mark_policy"] == (
        "last_retrospective_adjusted_exact_session_bar"
    )
    provenance = result.metadata["price_basis_provenance"]
    assert provenance["time_semantics"] == "retrospective_not_point_in_time"
    assert provenance["live_trading_eligible"] is False


def test_adjusted_momentum_crosses_split_in_one_price_unit(tmp_path) -> None:
    raw, adjusted = _split_prices()
    db = seed_db(
        tmp_path, codes=["1332"], prices=raw, adjustment_prices=adjusted
    )

    output = features.compute(
        features.get(
            "retrospective_split_adjusted_momentum_n", version="1.0.0"
        ),
        as_of=close_as_of(TRADING_DAYS[-1]),
        code="1332",
        n=3,
        db_path=db,
    )

    assert output.value == pytest.approx(0.0)
    assert output.metadata["price_basis"] == PERSONAL_RETROSPECTIVE_ADJUSTED
    assert output.metadata["time_semantics"] == "retrospective_not_point_in_time"


def test_adjusted_close_missing_fails_without_raw_fallback(tmp_path) -> None:
    raw, adjusted = _split_prices()
    del adjusted["1332"][TRADING_DAYS[1]]
    db = seed_db(
        tmp_path, codes=["1332"], prices=raw, adjustment_prices=adjusted
    )

    with pytest.raises(ValueError, match="requires adjustment_close"):
        run_backtest(
            BuyHold(),
            TRADING_DAYS[0],
            TRADING_DAYS[-1],
            db_path=db,
            universe=membership_at(
                close_as_of(TRADING_DAYS[0]), db_path=db, codes=("1332",)
            ),
            price_basis=PERSONAL_RETROSPECTIVE_ADJUSTED,
        )


def test_retrospective_basis_allows_controlled_paper_and_pit_adjusted_stays_closed() -> None:
    with pytest.raises(ValueError, match="DRAFT"):
        PaperRunConfig(
            start="2025-01-01",
            end="2025-01-02",
            lifecycle=Lifecycle.PAPER,
            price_basis=PERSONAL_RETROSPECTIVE_ADJUSTED,
            execution_mode="am_signal_pm_close",
        )
    with pytest.raises(ValueError, match="not enabled"):
        PaperRunConfig(
            start="2025-01-01",
            end="2025-01-02",
            price_basis=PIT_ADJUSTED,
        )


def test_paper_boundary_rejects_adjusted_engine_with_raw_feature(tmp_path) -> None:
    _raw, adjusted = _split_prices()
    db = seed_db(tmp_path, codes=["1332"], adjustment_prices=adjusted)

    class RawFeatureStrategy:
        strategy_id = "raw_feature_with_adjusted_engine"
        feature_ids = ("momentum_n",)

        def __init__(self) -> None:
            self.params: dict = {}
            self.feature_versions = {"momentum_n": "1.0.0"}

        def on_bar(self, _ctx):
            return []

    config = PaperRunConfig(
        start=TRADING_DAYS[0],
        end=TRADING_DAYS[-1],
        db_path=db,
        price_basis=PERSONAL_RETROSPECTIVE_ADJUSTED,
    )
    with pytest.raises(ValueError, match="incompatible with paper run basis"):
        run_paper(RawFeatureStrategy(), config)


def test_split_safe_value_blacks_out_changed_per_share_units(tmp_path) -> None:
    db = tmp_path / "value.sqlite"
    store = SqliteStore(db)
    days = ("2025-03-31", "2025-04-01", "2025-04-02", "2025-04-03")
    raw = (100.0, 100.0, 50.0, 51.0)
    adjusted = (50.0, 50.0, 50.0, 51.0)
    store.upsert(
        "jquants_daily_bars",
        [
            {
                "source": "jquants",
                "code": "1332",
                "date": day,
                "event_time": f"{day}T15:30:00+09:00",
                "available_at": f"{day}T15:30:00+09:00",
                "ingested_at": f"{day}T15:30:00+09:00",
                "open": raw_close,
                "high": raw_close,
                "low": raw_close,
                "close": raw_close,
                "volume": 1_000.0,
                "adjustment_close": adjusted_close,
                "adjustment_volume": 2_000.0 if day < "2025-04-02" else 1_000.0,
            }
            for day, raw_close, adjusted_close in zip(
                days, raw, adjusted, strict=True
            )
        ],
    )
    payload = {
        "Code": "1332",
        "DiscDate": "2025-04-01",
        "CurPerEn": "2025-04-01",
        "BPS": 80.0,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    store.upsert(
        "jquants_records",
        [
            {
                "source": "jquants",
                "dataset": "fins_summary",
                "natural_key": natural_key(payload, "fins_summary"),
                "event_time": "2025-04-01T15:00:00+09:00",
                "available_at": "2025-04-01T15:00:00+09:00",
                "ingested_at": "2025-04-01T15:00:00+09:00",
                "payload": encoded,
                "raw_payload": encoded,
            }
        ],
    )
    store.close()

    output = features.compute(
        features.get(
            "retrospective_split_safe_fundamental_value_score",
            version="1.0.0",
        ),
        as_of=close_as_of(days[-1]),
        code="1332",
        db_path=db,
    )

    assert output.value is None
    assert output.metadata["reason"] == "per_share_split_blackout"
    assert output.metadata["split_safety_anchor_source"] == "statement_period_end"
    assert "2025-04-02" in output.metadata["factor_change_dates"]


def test_split_safety_uses_price_ratio_when_volume_ratio_is_constant() -> None:
    rows = [
        {
            "code": "71720",
            "date": "2025-03-31",
            "close": 100.0,
            "adjustment_close": 50.0,
            "volume": 1_000.0,
            "adjustment_volume": 2_000.0,
        },
        {
            "code": "71720",
            "date": "2025-04-01",
            "close": 100.0,
            "adjustment_close": 50.0,
            "volume": 1_000.0,
            "adjustment_volume": 2_000.0,
        },
        {
            "code": "71720",
            "date": "2025-04-02",
            "close": 50.0,
            "adjustment_close": 50.0,
            "volume": 1_000.0,
            "adjustment_volume": 2_000.0,
        },
    ]

    safe, evidence = _retrospective_split_safety(
        rows, anchor="2025-04-01"
    )

    assert safe is False
    assert evidence["price_factor_change_dates"] == ["2025-04-02"]
    assert evidence["volume_factor_change_dates"] == []
    no_baseline, missing = _retrospective_split_safety(
        rows[2:], anchor="2025-04-01"
    )
    assert no_baseline is False
    assert missing["reason"] == "missing_pre_anchor_factor_baseline"


def test_value_anchor_belongs_to_the_selected_bps_row() -> None:
    selected = _latest_fins_per_share_observation(
        [
            {
                "payload": {
                    "DiscDate": "2025-01-15",
                    "CurPerEn": "2024-12-31",
                    "BPS": 80.0,
                }
            },
            {
                "payload": {
                    "DiscDate": "2025-04-15",
                    "CurPerEn": "2025-03-31",
                    "EPS": 12.0,
                }
            },
        ]
    )

    assert selected is not None
    assert selected["mode"] == "bps_over_price"
    assert selected["bps"] == 80.0
    assert selected["split_safety_anchor"] == "2024-12-31"
