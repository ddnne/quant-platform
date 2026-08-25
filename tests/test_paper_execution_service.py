"""Phase 7 PaperExecutionService authority gate coverage.

The service is the sole positive capability reaching ``run_paper``. These tests
exercise the happy path and each authority rejection: mode, StrategySpec hash,
authorization id, constraints, FeatureRef versions, and exact snapshot pin.
"""

from __future__ import annotations

import types
from datetime import date, timedelta

import pytest

from agents.pm import PortfolioManagerAgent
from agents.strategist import StrategistAgent
from agents.trader import TraderAgent
from execution.paper_service import (
    PaperExecutionRejected,
    PaperExecutionService,
    _authorization_id,
)
from strategies.paper import PaperRunConfig

from _coreseed import CODES, seed_db


def _weekdays(count: int) -> list[str]:
    days: list[str] = []
    cursor = date(2025, 4, 1)
    while len(days) < count:
        if cursor.weekday() < 5:
            days.append(cursor.isoformat())
        cursor += timedelta(days=1)
    return days


def _build(tmp_path, *, momentum_version: str = "1.0.0"):
    """Produce a (plan, spec, config) triple plus the seeded db path."""
    days = _weekdays(12)
    prices = {
        code: {
            day: 100.0 + code_index * 20.0 + day_index * (code_index + 1)
            for day_index, day in enumerate(days)
        }
        for code_index, code in enumerate(CODES)
    }
    db = seed_db(tmp_path, codes=CODES, days=days, prices=prices)
    spec = StrategistAgent(momentum_n=3, top_k=1, momentum_version=momentum_version).propose(
        __import__("agents").ComposedMemo(
            as_of=days[-1],
            thesis="momentum",
            source_roles=("quant",),
        )
    )
    decision = PortfolioManagerAgent().review(spec)
    plan = TraderAgent().prepare(decision)
    config = PaperRunConfig(
        start=days[0],
        end=days[-1],
        db_path=db,
        universe=None,
        lookback_days=30,
    )
    return plan, spec, config, db


def test_service_executes_authorized_request_and_pins_snapshot(tmp_path):
    plan, spec, config, _db = _build(tmp_path)
    result = PaperExecutionService().execute(plan, spec, config)
    assert result.experiment_id
    assert result.run_id == result.experiment_id
    assert result.reproducibility["data_snapshot_id"]
    assert result.trades


def test_service_rejects_non_paper_mode(tmp_path):
    plan, spec, config, _db = _build(tmp_path)
    object.__setattr__(plan, "mode", "live")  # bypass the trader-side guard
    with pytest.raises(PaperExecutionRejected, match="paper mode"):
        PaperExecutionService().execute(plan, spec, config)


def test_service_rejects_tampered_strategy_spec_hash(tmp_path):
    plan, spec, config, _db = _build(tmp_path)
    object.__setattr__(plan, "strategy_spec_hash", "sha256:" + "0" * 64)
    with pytest.raises(PaperExecutionRejected, match="strategy_spec_hash"):
        PaperExecutionService().execute(plan, spec, config)


def test_service_rejects_tampered_authorization_id(tmp_path):
    plan, spec, config, _db = _build(tmp_path)
    object.__setattr__(plan, "authorization_id", "sha256:" + "f" * 64)
    with pytest.raises(PaperExecutionRejected, match="authorization_id"):
        PaperExecutionService().execute(plan, spec, config)


def test_service_rejects_out_of_range_constraint(tmp_path):
    plan, spec, config, _db = _build(tmp_path)
    # Re-mint a consistent authorization so earlier gates pass, then violate
    # only the (0, 1] gross-weight ceiling — proving the range gate itself.
    object.__setattr__(plan, "max_gross_weight", 1.5)
    object.__setattr__(
        plan,
        "authorization_id",
        _authorization_id(plan.mode, plan.strategy_spec_hash, 1.5),
    )
    with pytest.raises(PaperExecutionRejected, match="max_gross_weight"):
        PaperExecutionService().execute(plan, spec, config)


def test_service_rejects_unapproved_feature_version(tmp_path):
    plan, spec, config, _db = _build(tmp_path, momentum_version="9.9.9")
    with pytest.raises(PaperExecutionRejected, match="approved signal feature"):
        PaperExecutionService().execute(plan, spec, config)


def test_service_rejects_run_that_consumed_a_different_snapshot(
    tmp_path, monkeypatch
):
    plan, spec, config, _db = _build(tmp_path)
    # The run returns a result pinned to a foreign snapshot; the authority
    # refuses to surface it even though run_paper itself "succeeded".
    fake = types.SimpleNamespace(
        reproducibility={"data_snapshot_id": "sha256:" + "b" * 64}
    )
    monkeypatch.setattr(
        "execution.paper_service.run_paper", lambda *a, **k: fake
    )
    with pytest.raises(PaperExecutionRejected, match="different data snapshot"):
        PaperExecutionService().execute(plan, spec, config)


def test_service_rejects_missing_snapshot_database(tmp_path):
    plan, spec, _config, _db = _build(tmp_path)
    config = PaperRunConfig(
        start=_config.start,
        end=_config.end,
        db_path=tmp_path / "does-not-exist.sqlite",
        universe=_config.universe,
        lookback_days=30,
    )
    with pytest.raises(PaperExecutionRejected, match="does not exist"):
        PaperExecutionService().execute(plan, spec, config)
