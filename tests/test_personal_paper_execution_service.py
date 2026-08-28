"""Focused invariants for the single-user, paper-only execution boundary."""

from __future__ import annotations

from dataclasses import replace
from datetime import date, timedelta

import pytest

from agents import ComposedMemo
from agents.strategist import StrategistAgent
from execution.personal_paper_service import (
    PersonalPaperExecutionRejected,
    PersonalPaperExecutionService,
)
from paper_runtime import data_snapshot_id
from research.universe_contract import ResolvedUniverseMembership
from strategies.paper import Lifecycle, PaperRunConfig
from strategies.spec import FeatureRef, iter_feature_refs

from _coreseed import CODES, seed_db


def _weekdays(count: int) -> list[str]:
    days: list[str] = []
    cursor = date(2025, 4, 1)
    while len(days) < count:
        if cursor.weekday() < 5:
            days.append(cursor.isoformat())
        cursor += timedelta(days=1)
    return days


def _case(tmp_path):
    days = _weekdays(12)
    prices = {
        code: {
            day: 100.0 + code_index * 20.0 + day_index * (code_index + 1)
            for day_index, day in enumerate(days)
        }
        for code_index, code in enumerate(CODES)
    }
    db_path = seed_db(tmp_path, codes=CODES, days=days, prices=prices)
    spec = StrategistAgent(momentum_n=3, top_k=1).propose(
        ComposedMemo(
            as_of=days[-1],
            thesis="personal momentum paper",
            source_roles=("quant",),
        )
    )
    universe = ResolvedUniverseMembership(
        period_start=days[0],
        period_end=days[-1],
        decision_memberships=tuple((day, tuple(CODES)) for day in days),
    )
    config = PaperRunConfig(
        start=days[0],
        end=days[-1],
        db_path=db_path,
        universe=universe,
        lookback_days=30,
        lifecycle=Lifecycle.DRAFT,
    )
    return spec, config, data_snapshot_id(db_path), iter_feature_refs(spec)


def _execute(service, spec, config, snapshot_id, refs):
    return service.execute(
        spec,
        config,
        expected_snapshot_id=snapshot_id,
        approved_feature_refs=refs,
    )


def test_personal_service_executes_exact_draft_against_pinned_snapshot(tmp_path):
    spec, config, snapshot_id, refs = _case(tmp_path)

    result = _execute(
        PersonalPaperExecutionService(), spec, config, snapshot_id, refs
    )

    assert result.lifecycle is Lifecycle.DRAFT
    assert result.reproducibility["data_snapshot_id"] == snapshot_id
    assert result.reproducibility["feature_versions"] == {
        ref.id: ref.version for ref in refs
    }


def test_personal_service_rejects_non_draft(tmp_path):
    spec, config, snapshot_id, refs = _case(tmp_path)
    config = replace(config, lifecycle=Lifecycle.PAPER)

    with pytest.raises(PersonalPaperExecutionRejected, match="DRAFT-only"):
        _execute(PersonalPaperExecutionService(), spec, config, snapshot_id, refs)


def test_personal_service_rejects_initial_snapshot_mismatch(tmp_path):
    spec, config, _snapshot_id, refs = _case(tmp_path)

    with pytest.raises(
        PersonalPaperExecutionRejected,
        match="does not match expected_snapshot_id",
    ):
        _execute(
            PersonalPaperExecutionService(),
            spec,
            config,
            "sha256:" + "0" * 64,
            refs,
        )


def test_personal_service_rejects_snapshot_tamper_after_run(tmp_path, monkeypatch):
    spec, config, snapshot_id, refs = _case(tmp_path)
    observed = iter((snapshot_id, "sha256:" + "f" * 64))
    monkeypatch.setattr(
        "execution.personal_paper_service.data_snapshot_id",
        lambda _path: next(observed),
    )

    with pytest.raises(PersonalPaperExecutionRejected, match="changed during"):
        _execute(PersonalPaperExecutionService(), spec, config, snapshot_id, refs)


def test_personal_service_rejects_approved_feature_ref_mismatch(tmp_path):
    spec, config, snapshot_id, refs = _case(tmp_path)
    mismatched = FeatureRef(
        id=refs[0].id,
        version="9.9.9",
        params=refs[0].params,
    )

    with pytest.raises(
        PersonalPaperExecutionRejected,
        match="do not exactly match",
    ):
        _execute(
            PersonalPaperExecutionService(),
            spec,
            config,
            snapshot_id,
            (mismatched,),
        )


def test_personal_service_rejects_consumed_feature_mismatch(tmp_path, monkeypatch):
    spec, config, snapshot_id, refs = _case(tmp_path)
    from execution import personal_paper_service as module

    real_run_paper = module.run_paper

    def mismatched_run(*args, **kwargs):
        result = real_run_paper(*args, **kwargs)
        reproduction = dict(result.reproducibility)
        reproduction["feature_versions"] = {refs[0].id: "9.9.9"}
        return replace(result, reproducibility=reproduction)

    monkeypatch.setattr(module, "run_paper", mismatched_run)

    with pytest.raises(
        PersonalPaperExecutionRejected,
        match="FeatureRefs do not match",
    ):
        _execute(PersonalPaperExecutionService(), spec, config, snapshot_id, refs)


@pytest.mark.parametrize("tamper", ["identity", "body"])
def test_personal_service_rejects_strategy_result_tamper(
    tmp_path, monkeypatch, tamper
):
    spec, config, snapshot_id, refs = _case(tmp_path)
    from execution import personal_paper_service as module

    real_run_paper = module.run_paper

    def mismatched_run(*args, **kwargs):
        result = real_run_paper(*args, **kwargs)
        reproduction = dict(result.reproducibility)
        if tamper == "identity":
            reproduction["strategy_id"] = "different_strategy"
        else:
            strategy_params = dict(reproduction["strategy_params"])
            strategy_params["strategy_spec"] = {
                **spec.to_dict(),
                "strategy_id": "different_strategy",
            }
            reproduction["strategy_params"] = strategy_params
        return replace(result, reproducibility=reproduction)

    monkeypatch.setattr(module, "run_paper", mismatched_run)

    with pytest.raises(
        PersonalPaperExecutionRejected,
        match="exact StrategySpec",
    ):
        _execute(PersonalPaperExecutionService(), spec, config, snapshot_id, refs)


@pytest.mark.parametrize(
    "field",
    ["universe_rule_digest", "resolved_universe_digest"],
)
def test_personal_service_rejects_universe_result_tamper(
    tmp_path, monkeypatch, field
):
    spec, config, snapshot_id, refs = _case(tmp_path)
    from execution import personal_paper_service as module

    real_run_paper = module.run_paper

    def mismatched_run(*args, **kwargs):
        result = real_run_paper(*args, **kwargs)
        reproduction = dict(result.reproducibility)
        reproduction[field] = "sha256:" + "0" * 64
        return replace(result, reproducibility=reproduction)

    monkeypatch.setattr(module, "run_paper", mismatched_run)

    with pytest.raises(
        PersonalPaperExecutionRejected,
        match="resolved daily universe",
    ):
        _execute(PersonalPaperExecutionService(), spec, config, snapshot_id, refs)


@pytest.mark.parametrize("universe", [None, ("1332", "8697")])
def test_personal_service_requires_resolved_daily_universe(tmp_path, universe):
    spec, config, snapshot_id, refs = _case(tmp_path)
    config = replace(config, universe=universe)

    with pytest.raises(
        PersonalPaperExecutionRejected,
        match="resolved daily universe",
    ):
        _execute(PersonalPaperExecutionService(), spec, config, snapshot_id, refs)
