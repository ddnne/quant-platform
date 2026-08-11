"""Offline role-agent vertical slice through paper and independent risk."""

from __future__ import annotations

from dataclasses import replace
from datetime import date, timedelta

import pytest

from agents import AgentPaperPipeline
from agents.strategist import StrategistAgent
from risk import JsonRiskStore
from strategies.paper import JsonPaperStore, PaperRunConfig

from _coreseed import CODES, seed_db


def _weekdays(count: int) -> list[str]:
    days: list[str] = []
    cursor = date(2025, 4, 1)
    while len(days) < count:
        if cursor.weekday() < 5:
            days.append(cursor.isoformat())
        cursor += timedelta(days=1)
    return days


def test_agents_spec_paper_risk_pipeline_runs_offline(tmp_path):
    days = _weekdays(10)
    prices = {
        code: {
            day: 100.0 + code_index * 20.0 + day_index * (code_index + 1)
            for day_index, day in enumerate(days)
        }
        for code_index, code in enumerate(CODES)
    }
    db = seed_db(tmp_path, codes=CODES, days=days, prices=prices)
    paper_root = tmp_path / "paper-results"
    risk_root = tmp_path / "risk-audits"
    pipeline = AgentPaperPipeline(
        paper_store=JsonPaperStore(paper_root),
        risk_store=JsonRiskStore(risk_root),
        strategist=StrategistAgent(momentum_n=3, top_k=1),
    )

    output = pipeline.run(
        PaperRunConfig(
            start=days[0],
            end=days[-1],
            db_path=db,
            universe=tuple(CODES),
            lookback_days=30,
        )
    )

    assert output.paper_result.trades
    assert output.paper_result.experiment_id
    assert output.paper_result_path.is_file()
    assert output.paper_result_path.is_relative_to(paper_root)
    assert output.risk_audit.experiment_id == output.paper_result.experiment_id
    assert output.risk_audit_path.is_file()
    assert output.risk_audit_path.is_relative_to(risk_root)
    assert not output.risk_audit_path.is_relative_to(paper_root)
    assert JsonRiskStore(risk_root).load(output.risk_audit.audit_id)["run_id"] == (
        output.paper_result.run_id
    )
    assert [artifact.type for artifact in output.artifacts] == [
        "strategy_spec",
        "portfolio_decision",
        "authorized_paper_execution_request",
        "paper_result",
        "risk_audit",
    ]
    assert all(
        artifact.data_snapshot_id
        == output.paper_result.reproducibility["data_snapshot_id"]
        for artifact in output.artifacts
    )
    assert output.artifacts[-1].parent_ids == (output.artifacts[-2].artifact_id,)
    with pytest.raises(ValueError, match="canonical audit content"):
        pipeline.risk_store.save(replace(output.risk_audit, status="tampered"))


def test_pipeline_refuses_overlapping_paper_and_risk_write_targets(tmp_path):
    with pytest.raises(ValueError, match="disjoint roots"):
        AgentPaperPipeline(
            paper_store=JsonPaperStore(tmp_path / "outputs"),
            risk_store=JsonRiskStore(tmp_path / "outputs" / "risk"),
        )


def test_pipeline_never_passes_database_path_to_roles(tmp_path, monkeypatch):
    pipeline = AgentPaperPipeline(
        paper_store=JsonPaperStore(tmp_path / "paper"),
        risk_store=JsonRiskStore(tmp_path / "risk"),
    )
    seen: list[object] = []

    for agent in pipeline.researchers:
        real = agent.research

        def spy(request, _real=real):
            seen.append(request)
            assert not hasattr(request, "db_path")
            return _real(request)

        monkeypatch.setattr(agent, "research", spy)

    # Stop immediately after roles, before a real paper DB is needed.
    monkeypatch.setattr(pipeline.composer, "compose", lambda _memos: (_ for _ in ()).throw(RuntimeError("stop")))
    with pytest.raises(RuntimeError, match="stop"):
        pipeline.run(
            PaperRunConfig(
                start="2025-04-01",
                end="2025-04-02",
                db_path=tmp_path / "secret-location.sqlite",
                universe=("1332",),
            )
        )
    assert len(seen) == 3
