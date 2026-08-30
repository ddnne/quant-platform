"""Offline end-to-end coverage for the Phase 5 Paper pipeline."""

from __future__ import annotations

from dataclasses import replace
from datetime import date, timedelta

import features
import pit
import pytest
from core import (
    CORE_ENGINE_VERSION,
    PERSONAL_RETROSPECTIVE_ADJUSTED,
    PIT_ADJUSTED,
    UnsupportedPriceBasis,
)
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


def _config(db, days, *, lifecycle: Lifecycle = Lifecycle.DRAFT) -> PaperRunConfig:
    return PaperRunConfig(
        start=days[0],
        end=days[-1],
        db_path=db,
        universe=None,
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
    strategy = Return1dFeatureStrategy(threshold=0.0)

    result = run_paper(strategy, _config(db, days))

    assert isinstance(result, PaperRunResult)
    assert result.experiment_id
    assert result.run_id
    assert result.run_id == result.experiment_id
    assert result.lifecycle is Lifecycle.DRAFT
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
        "data_snapshot_id",
        "git_commit",
        "strategy_definition_hash",
        "feature_definition_hashes",
        "price_basis",
    }
    assert required <= metadata.keys()
    assert metadata["core_engine_version"] == CORE_ENGINE_VERSION
    assert metadata["pit_api_version"] == pit.PIT_API_VERSION
    assert metadata["features_runtime_version"] == FEATURES_RUNTIME_VERSION
    assert metadata["feature_versions"]["return_1d"]
    assert metadata["period"] == {"start": days[0], "end": days[-1]}
    assert metadata["cost_model"]["bps_one_way"] == 5.0
    assert metadata["price_basis"] == "RAW"
    assert metadata["strategy_id"] == "return_1d_feature"
    assert metadata["strategy_params"] == {"threshold": 0.0}
    assert metadata["data_snapshot_id"].startswith("sha256:")
    assert metadata["strategy_definition_hash"].startswith("sha256:")
    assert metadata["feature_definition_hashes"]["return_1d"].startswith(
        "sha256:"
    )
    assert "db_fingerprint" not in metadata


def test_identical_inputs_have_a_deterministic_run_id(paper_fixture):
    db, days = paper_fixture
    config = _config(db, days)

    first = run_paper(Return1dFeatureStrategy(), config)
    second = run_paper(Return1dFeatureStrategy(), config)

    assert first.run_id == second.run_id
    assert first.experiment_id == second.experiment_id
    assert first.metadata == second.metadata
    assert first.metrics == second.metrics
    assert first.trades == second.trades
    assert first.equity_curve == second.equity_curve


def test_momentum_example_runs_and_pins_its_feature_version(paper_fixture):
    db, days = paper_fixture
    strategy = MomentumFeatureStrategy(n=5, top_k=1, min_momentum=0.0)

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


def test_local_runtime_rejects_paper_lifecycle(paper_fixture):
    db, days = paper_fixture
    paper = _config(db, days, lifecycle=Lifecycle.PAPER)

    with pytest.raises(
        PermissionError,
        match="DRAFT-only.*CONTROLLED_AUTHORITY_UNPROVISIONED",
    ):
        run_paper(Return1dFeatureStrategy(), paper)


def test_engine_config_change_creates_a_distinct_experiment(paper_fixture):
    db, days = paper_fixture
    baseline = _config(db, days)

    first = run_paper(Return1dFeatureStrategy(), baseline)
    second = run_paper(
        Return1dFeatureStrategy(), replace(baseline, cost_bps=25.0)
    )

    assert first.experiment_id != second.experiment_id


def test_paper_config_rejects_unproven_adjusted_basis(paper_fixture):
    db, days = paper_fixture
    with pytest.raises(UnsupportedPriceBasis, match="not enabled"):
        replace(_config(db, days), price_basis=PIT_ADJUSTED)


def test_paper_run_fails_closed_when_snapshot_changes(
    paper_fixture, monkeypatch
):
    from strategies.paper import runner

    db, days = paper_fixture
    snapshots = iter(("sha256:before", "sha256:after"))
    monkeypatch.setattr(runner, "data_snapshot_id", lambda _path: next(snapshots))

    with pytest.raises(RuntimeError, match="database changed during the run"):
        run_paper(Return1dFeatureStrategy(), _config(db, days))


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

    run_paper(Return1dFeatureStrategy(), _config(db, days))

    assert calls
    assert {feature_id for feature_id, _ in calls} == {"return_1d"}
    allowed = {close_iso(day) for day in days}
    assert all(as_of in allowed for _, as_of in calls)
    assert all(as_of is not None for _, as_of in calls)


def test_lifecycle_labels_are_stable_public_values():
    assert Lifecycle.DRAFT.value == "Draft"
    assert Lifecycle.PAPER.value == "Paper"


def test_paper_config_admits_am_signal_pm_close_for_personal_draft():
    config = PaperRunConfig(
        start="2025-04-01",
        end="2025-04-04",
        execution_mode="am_signal_pm_close",
        price_basis=PERSONAL_RETROSPECTIVE_ADJUSTED,
        lifecycle=Lifecycle.DRAFT,
    )
    assert config.execution_mode == "am_signal_pm_close"
    assert config.price_basis == PERSONAL_RETROSPECTIVE_ADJUSTED


def test_paper_config_rejects_am_signal_pm_close_on_raw_basis():
    with pytest.raises(ValueError, match="PERSONAL_RETROSPECTIVE_ADJUSTED"):
        PaperRunConfig(
            start="2025-04-01",
            end="2025-04-04",
            execution_mode="am_signal_pm_close",
        )


def test_paper_config_still_rejects_unknown_execution_mode():
    with pytest.raises(ValueError, match="execution_mode"):
        PaperRunConfig(
            start="2025-04-01",
            end="2025-04-04",
            execution_mode="next_open",
        )
