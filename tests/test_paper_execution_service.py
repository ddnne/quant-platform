"""Phase 7 PaperExecutionService authority gate coverage.

The service is the sole positive capability reaching ``run_paper``. These tests
exercise the happy path and each authority rejection: mode, StrategySpec hash,
authorization id, constraints, FeatureRef versions, and exact snapshot pin.
"""

from __future__ import annotations

import ast
import types
from datetime import date, timedelta
from pathlib import Path

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
from strategies.paper import Lifecycle

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
        lifecycle=Lifecycle.DRAFT,
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
        lifecycle=Lifecycle.DRAFT,
    )
    with pytest.raises(PaperExecutionRejected, match="does not exist"):
        PaperExecutionService().execute(plan, spec, config)


def test_service_rejects_mismatched_profile_digest(tmp_path):
    plan, spec, config, _db = _build(tmp_path)
    object.__setattr__(plan, "profile_digest", "sha256:" + "0" * 64)
    with pytest.raises(PaperExecutionRejected, match="offline fixture"):
        PaperExecutionService().execute(plan, spec, config)


def test_runtime_dto_delegates_to_strong_service(tmp_path):
    from paper_runtime.execution import (
        AuthorizedPaperExecutionRequest as RuntimeRequest,
        PaperExecutionService as RuntimeService,
    )

    plan, spec, config, _db = _build(tmp_path)
    dto = RuntimeRequest(
        authorization_id=plan.authorization_id,
        mode=plan.mode,
        strategy=spec,
        strategy_spec_hash=plan.strategy_spec_hash,
        config=config,
        max_gross=plan.max_gross_weight,
        ready_snapshot_id=plan.ready_snapshot_id,
    )
    result = RuntimeService().execute(dto)
    assert result.experiment_id
    assert result.reproducibility["data_snapshot_id"]


def test_runtime_dto_rejects_raw_strategy(tmp_path):
    from paper_runtime.execution import (
        AuthorizedPaperExecutionRequest as RuntimeRequest,
        PaperExecutionService as RuntimeService,
    )

    plan, spec, config, _db = _build(tmp_path)
    dto = RuntimeRequest(
        authorization_id=plan.authorization_id,
        mode=plan.mode,
        strategy=object(),
        strategy_spec_hash=plan.strategy_spec_hash,
        config=config,
        max_gross=plan.max_gross_weight,
    )
    with pytest.raises(PaperExecutionRejected, match="StrategySpec"):
        RuntimeService().execute(dto)


def test_production_packages_import_run_paper_only_via_paper_execution_service():
    """packages/ may import run_paper only from strategies.paper or paper_service."""
    repo = Path(__file__).resolve().parents[1]
    packages = repo / "packages"
    allowed_rel = {
        Path("packages/research_runtime/strategies/paper/runner.py"),
        Path("packages/research_runtime/strategies/paper/__init__.py"),
        Path("packages/product/execution/paper_service.py"),
    }
    offenders: list[str] = []
    for path in sorted(packages.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        rel = path.relative_to(repo)
        if rel in allowed_rel:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                if any(alias.name == "run_paper" for alias in node.names):
                    offenders.append(f"{rel}:{node.lineno}: import run_paper from {node.module}")
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name == "run_paper" or alias.name.endswith(".run_paper"):
                        offenders.append(f"{rel}:{node.lineno}: import {alias.name}")
            elif isinstance(node, ast.Call):
                func = node.func
                if isinstance(func, ast.Name) and func.id == "run_paper":
                    offenders.append(f"{rel}:{node.lineno}: call run_paper")
                elif isinstance(func, ast.Attribute) and func.attr == "run_paper":
                    offenders.append(f"{rel}:{node.lineno}: call {func.attr}")
    assert not offenders, "run_paper must enter via PaperExecutionService:\n" + "\n".join(
        offenders
    )
