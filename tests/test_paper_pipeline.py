"""Offline end-to-end coverage for the Phase 5 Paper pipeline."""

from __future__ import annotations

from datetime import date, timedelta

import features
import pit
import pytest
from core import CORE_ENGINE_VERSION
from features.runtime import FEATURES_RUNTIME_VERSION
from strategies.examples import MomentumFeatureStrategy, Return1dFeatureStrategy
from strategies.paper import Lifecycle, PaperRunConfig, PaperRunResult, run_paper

from _coreseed import CODES, close_iso, seed_db


def _weekdays(count: int) -> list[str]:
    days: list[str] = []
    cursor = date(2025, 4, 1)
    while len(days) < count:
        if cursor.weekday() < 5:
            days.append(cursor.isoformat())
        cursor += timedelta(days=1)
    return days


@pytest.fixture
def paper_fixture(tmp_path):
    """A long-enough rising market for return and momentum strategies."""
    days = _weekdays(30)
    prices = {
        code: {
            day: 100.0 + code_index * 10.0 + day_index * (code_index + 1)
            for day_index, day in enumerate(days)
        }
        for code_index, code in enumerate(CODES)
    }
    db = seed_db(tmp_path, codes=CODES, days=days, prices=prices)
    return db, days


def _config(db, days, *, lifecycle: Lifecycle = Lifecycle.PAPER) -> PaperRunConfig:
    return PaperRunConfig(
        start=days[0],
        end=days[-1],
        db_path=db,
        universe=tuple(CODES),
        execution_mode="next_close",
        cost_bps=5.0,
        starting_capital=1_000_000.0,
        lookback_days=45,
        lifecycle=lifecycle,
    )


def test_paper_run_completes_with_metrics_trades_and_reproducibility(
    paper_fixture,
):
    db, days = paper_fixture
    strategy = Return1dFeatureStrategy(db, threshold=0.0)

    result = run_paper(strategy, _config(db, days))

    assert isinstance(result, PaperRunResult)
    assert result.run_id
    assert result.lifecycle is Lifecycle.PAPER
    assert result.equity_curve
    assert result.trades
    assert result.metrics["num_trading_days"] == len(days)
    assert "total_return_pre_cost" in result.metrics
    assert "total_return_post_cost" in result.metrics

    metadata = result.metadata
    required = {
        "core_engine_version",
        "pit_api_version",
        "features_runtime_version",
        "feature_versions",
        "period",
        "cost_model",
        "strategy_id",
        "strategy_params",
        "db_fingerprint",
    }
    assert required <= metadata.keys()
    assert metadata["core_engine_version"] == CORE_ENGINE_VERSION
    assert metadata["pit_api_version"] == pit.PIT_API_VERSION
    assert metadata["features_runtime_version"] == FEATURES_RUNTIME_VERSION
    assert metadata["feature_versions"]["return_1d"]
    assert metadata["period"] == {"start": days[0], "end": days[-1]}
    assert metadata["cost_model"]["bps_one_way"] == 5.0
    assert metadata["strategy_id"] == "return_1d_feature"
    assert metadata["strategy_params"] == {"threshold": 0.0}
    assert metadata["db_fingerprint"]


def test_identical_inputs_have_a_deterministic_run_id(paper_fixture):
    db, days = paper_fixture
    config = _config(db, days)

    first = run_paper(Return1dFeatureStrategy(db), config)
    second = run_paper(Return1dFeatureStrategy(db), config)

    assert first.run_id == second.run_id
    assert first.metadata == second.metadata
    assert first.metrics == second.metrics
    assert first.trades == second.trades
    assert first.equity_curve == second.equity_curve


def test_momentum_example_runs_and_pins_its_feature_version(paper_fixture):
    db, days = paper_fixture
    strategy = MomentumFeatureStrategy(db, n=5, top_k=1, min_momentum=0.0)

    result = run_paper(strategy, _config(db, days, lifecycle=Lifecycle.DRAFT))

    assert result.lifecycle is Lifecycle.DRAFT
    assert result.trades
    assert result.metadata["strategy_id"] == "momentum_feature"
    assert result.metadata["strategy_params"] == {
        "n": 5,
        "top_k": 1,
        "min_momentum": 0.0,
    }
    assert result.metadata["feature_versions"]["momentum_n"]


def test_feature_strategy_passes_every_decision_as_of_explicitly(
    paper_fixture, monkeypatch
):
    """Sample strategy feature calls inherit the engine decision instant."""
    db, days = paper_fixture
    real_compute = features.compute
    calls: list[tuple[str, str]] = []

    def spy_compute(feature, *, as_of, **kwargs):
        calls.append((str(feature), as_of))
        return real_compute(feature, as_of=as_of, **kwargs)

    monkeypatch.setattr(features, "compute", spy_compute)

    run_paper(Return1dFeatureStrategy(db), _config(db, days))

    assert calls
    assert {feature_id for feature_id, _ in calls} == {"return_1d"}
    allowed = {close_iso(day) for day in days}
    assert all(as_of in allowed for _, as_of in calls)
    assert all(as_of is not None for _, as_of in calls)


def test_lifecycle_labels_are_stable_public_values():
    assert Lifecycle.DRAFT.value == "Draft"
    assert Lifecycle.PAPER.value == "Paper"

