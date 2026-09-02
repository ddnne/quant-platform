"""AM/PM data-quality flags must reach candidate selection gates."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from core.result import BacktestResult
from research.paper_candidate_specs import build_multi_day_hold_strategy_spec
from pit.personal_research_view import ArtifactRef
from research.personal_service import (
    PersonalResearchPolicy,
    _candidate_evaluation,
    _paper_evidence,
)
from strategies.paper import Lifecycle, PaperRunConfig, PaperRunResult


class _Sink:
    def write_artifact(self, *, category: str, suffix: str, payload: bytes) -> ArtifactRef:
        return ArtifactRef(
            archive_member=f"{category}/x.{suffix}",
            sha256="sha256:" + "0" * 64,
        )

_FLAGS = ("comparable", "selection_eligible", "comparison_eligible")
_FOLD = ("2024-01-04", "2024-06-30")
_HOLDOUT = ("2024-07-01", "2024-07-31")
_POLICY = PersonalResearchPolicy(
    validation_folds=1, min_fold_sessions=2, holdout_months=1,
    min_holdout_sessions=2, base_cost_bps=0.0, stress_cost_bps=20.0,
    min_positive_folds=1, min_validation_sharpe=-100.0, max_drawdown=1.0,
    min_fills=0, max_parallel=1,
)


def _flags(eligible: bool) -> dict[str, bool]:
    return dict.fromkeys(_FLAGS, eligible)


def _paper_result(metrics: dict | None = None) -> PaperRunResult:
    body = {"total_return_post_cost": 0.01, "max_drawdown": 0.0, "num_trades": 0}
    if metrics:
        body.update(metrics)
    return PaperRunResult(
        experiment_id="exp",
        run_id="exp",
        lifecycle=Lifecycle.DRAFT,
        backtest=BacktestResult(
            equity_curve=[
                {"date": "2024-01-04", "equity": 1_000_000.0},
                {"date": "2024-01-05", "equity": 1_010_000.0},
            ],
            metrics=body,
        ),
        reproducibility={"data_snapshot_id": "snap", "strategy_id": "s"},
    )


@pytest.mark.parametrize(
    ("metrics", "eligible"),
    [(None, True), (_flags(False), False)],
    ids=("absent_defaults_eligible", "explicit_false_propagates"),
)
def test_paper_evidence_quality_flags(
    tmp_path: Path, metrics: dict | None, eligible: bool
) -> None:
    evidence, _, _ = _paper_evidence(
        _paper_result(metrics),
        config=PaperRunConfig(start="2024-01-04", end="2024-01-05"),
        view=_Sink(),
        max_drawdown=1.0,
    )
    for name in _FLAGS:
        assert evidence[name] is eligible
        assert evidence["data_quality"][name] is eligible


def _run_evidence(eligible: bool) -> dict:
    quality = _flags(eligible)
    return {
        "run_id": "run",
        "experiment_id": "run",
        "period": {"start": _FOLD[0], "end": _FOLD[1]},
        "cost_bps": 0.0,
        "execution_mode": "am_signal_pm_close",
        **quality,
        "data_quality": quality,
        "total_return_post_cost": 0.1,
        "annualized_sharpe": 1.0,
        "max_drawdown": 0.01,
        "fills": 10,
        "risk_status": "pass",
        "performance": {"schema_version": "personal-performance/v1", "cost_amount": 0.0},
        "paper_artifact": "paper/x.json",
        "risk_artifact": "risk/x.json",
    }


@pytest.fixture
def evaluate(monkeypatch):
    spec = build_multi_day_hold_strategy_spec(
        hold_days=3, momentum_n=3, top_k=2, strategy_id="personal_test_momentum"
    )

    def run(*, validation: bool = True, stress: bool = True, holdout: bool = True):
        roles: list[str] = []

        def fake_run_one(*_args, **kwargs):
            if float(kwargs["cost_bps"]) == 20.0:
                role, eligible = "stress", stress
            elif kwargs["period"] == _HOLDOUT:
                role, eligible = "holdout", holdout
            else:
                role, eligible = "validation", validation
            roles.append(role)
            return _run_evidence(eligible), [0.01, 0.02], [
                "2024-01-04",
                "2024-01-05",
            ], SimpleNamespace()

        monkeypatch.setattr("research.personal_service._run_one", fake_run_one)
        candidate = _candidate_evaluation(
            executor=SimpleNamespace(),
            spec=spec,
            closure=SimpleNamespace(
                required_lookback_trading_days=1,
                closure_digest="sha256:" + "a" * 64,
            ),
            view=_Sink(),
            universe=SimpleNamespace(),
            fold_periods=(_FOLD,),
            holdout_period=_HOLDOUT,
            policy=_POLICY,
        )
        candidate["_roles"] = roles
        return candidate

    return run


@pytest.mark.parametrize(
    ("ineligible", "decision", "reason", "roles"),
    [
        ("validation", "REJECT", "data_quality_selection", ["validation"]),
        ("stress", "REJECT", "stress:data_quality_selection", ["validation", "stress"]),
        ("holdout", "HOLD", "human_review_required", ["validation", "stress", "holdout"]),
    ],
)
def test_selection_driving_ineligibility(
    evaluate, ineligible: str, decision: str, reason: str, roles: list[str]
) -> None:
    candidate = evaluate(**{ineligible: False})
    assert candidate["decision"] == decision
    assert candidate["reasons"] == [reason]
    assert candidate["_roles"] == roles
    if ineligible == "validation":
        assert candidate["stress"] is None
    if ineligible == "holdout":
        holdout = candidate["holdout"]
        assert holdout["selection_use"] is False
        assert holdout["purpose"] == "exploratory_recent_period"
        assert holdout["selection_eligible"] is False
    else:
        assert candidate["holdout"] is None
