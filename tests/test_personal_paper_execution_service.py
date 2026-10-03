"""Focused invariants for the single-user, paper-only execution boundary."""

from __future__ import annotations

from dataclasses import replace
from datetime import date, timedelta
import sqlite3

import pit.query as query_module
import pytest
from _coreseed import CODES, seed_db
from agents import ComposedMemo
from agents.strategist import StrategistAgent
from execution.personal_paper_service import (
    PersonalPaperExecutionRejected,
    PersonalPaperExecutionService,
)
from paper_runtime import data_snapshot_id
from paper_runtime.personal_draft_bind import (
    run_bound_personal_paper,
)
from paper_runtime.personal_prepared_frame import _personal_prepared_frame_scope
from pit._draft_storage import draft_sqlite_path
from pit.personal_research_view import OfflineFixtureDataView, SnapshotIdentity
from research.personal_service import _closures, PersonalResearchPolicy
from research.personal_universe import personal_universe_selector
from research.universe_contract import ResolvedUniverseMembership
from strategies.paper import Lifecycle, PaperRunConfig, run_paper
from strategies.spec import interpret_strategy_spec


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
        universe=universe,
        lookback_days=30,
        lifecycle=Lifecycle.DRAFT,
    )
    snapshot_id = data_snapshot_id(db_path)
    closure = _closures(
        (spec,), start=days[0], end=days[-1],
        policy=PersonalResearchPolicy(),
        universe_selector=personal_universe_selector("topix_all"),
    )[0]
    view = OfflineFixtureDataView.bind(
        db_path,
        artifact_root=tmp_path / "personal-paper-artifacts",
        decision_cutoff="session_close",
    )
    view.bind_snapshot_identity(
        SnapshotIdentity(
            snapshot_id=snapshot_id,
            logical_data_snapshot_id=snapshot_id,
            database_sha256=snapshot_id,
            required_datasets=closure.required_datasets,
            period_start=days[0],
            period_end=days[-1],
            closure_digests=(closure.closure_digest,),
            manifest={},
        )
    )
    return spec, config, snapshot_id, closure, view, db_path


def _execute(service, spec, config, snapshot_id, closure, view):
    return service.execute(
        spec,
        config,
        expected_snapshot_id=snapshot_id,
        dependency_closure=closure,
        view=view,
    )


def test_personal_service_executes_exact_draft_against_pinned_snapshot(tmp_path):
    spec, config, snapshot_id, closure, view, _db_path = _case(tmp_path)

    result = _execute(
        PersonalPaperExecutionService(), spec, config, snapshot_id, closure, view
    )

    assert result.lifecycle is Lifecycle.DRAFT
    assert result.reproducibility["data_snapshot_id"] == snapshot_id
    assert "db_path" not in result.reproducibility
    assert "db_path" not in result.backtest.metadata
    assert result.reproducibility.get("db_locator") == "logical_data_snapshot_id"
    assert result.reproducibility["feature_versions"] == {
        ref.feature_id: ref.feature_version for ref in closure.feature_dependencies
    }


def test_personal_service_reuses_one_pit_connection_without_changing_result(
    tmp_path,
    monkeypatch,
):
    spec, config, snapshot_id, closure, view, db_path = _case(tmp_path)
    bound_path = draft_sqlite_path(view)
    baseline = query_module._scoped_read_connection(bound_path)
    assert baseline is None
    expected = run_paper(
        interpret_strategy_spec(spec),
        replace(config, db_path=db_path),
        store=None,
    )

    real_connect = query_module.connect_readonly
    from pit import sqlite_identity

    real_identity_connect = sqlite_identity._connect_readonly
    connection_count = 0
    identity_reads = 0

    def counting_connect(db_path):
        nonlocal connection_count
        connection_count += 1
        return real_connect(db_path)

    def counting_identity_connect(*args, **kwargs):
        nonlocal identity_reads
        identity_reads += 1
        return real_identity_connect(*args, **kwargs)

    monkeypatch.setattr(query_module, "connect_readonly", counting_connect)
    monkeypatch.setattr(sqlite_identity, "_connect_readonly", counting_identity_connect)
    actual = _execute(
        PersonalPaperExecutionService(), spec, config, snapshot_id, closure, view
    )

    assert connection_count == 1
    assert identity_reads == 2
    expected_pathless = replace(
        expected,
        reproducibility={
            **{
                key: value
                for key, value in expected.reproducibility.items()
                if key != "db_path"
            },
            "db_locator": "logical_data_snapshot_id",
        },
        backtest=replace(
            expected.backtest,
            metadata={
                **{
                    key: value
                    for key, value in expected.backtest.metadata.items()
                    if key != "db_path"
                },
                "db_locator": "logical_data_snapshot_id",
            },
        ),
    )
    assert actual == expected_pathless
    assert query_module._scoped_read_connection(bound_path) is None


def test_personal_service_rejects_non_draft(tmp_path):
    spec, config, snapshot_id, closure, view, _db_path = _case(tmp_path)
    config = replace(config, lifecycle=Lifecycle.PAPER)

    with pytest.raises(PersonalPaperExecutionRejected, match="DRAFT-only"):
        _execute(
            PersonalPaperExecutionService(), spec, config, snapshot_id, closure, view
        )
    with pytest.raises(PermissionError, match="DRAFT-only"):
        run_bound_personal_paper(
            spec,
            config,
            view=view,
            expected_snapshot_id=snapshot_id,
        )


def test_personal_service_rejects_database_path(tmp_path):
    spec, config, snapshot_id, closure, view, db_path = _case(tmp_path)
    config = replace(config, db_path=db_path)

    with pytest.raises(
        PersonalPaperExecutionRejected, match="does not accept a database path"
    ):
        _execute(
            PersonalPaperExecutionService(), spec, config, snapshot_id, closure, view
        )


@pytest.mark.parametrize("missing", (False, True))
def test_personal_service_rejects_unavailable_or_mismatched_snapshot(
    tmp_path, monkeypatch, missing,
):
    spec, config, _snapshot_id, closure, view, db_path = _case(tmp_path)
    if missing:
        db_path.unlink()

    def unexpected_calculation(*args, **kwargs):
        pytest.fail("snapshot mismatch must reject before calculation")

    monkeypatch.setattr("strategies.paper.runner.run_backtest", unexpected_calculation)
    with pytest.raises(
        PersonalPaperExecutionRejected,
        match="not found" if missing else "does not match expected_snapshot_id",
    ):
        _execute(
            PersonalPaperExecutionService(),
            spec,
            config,
            _snapshot_id if missing else "sha256:" + "0" * 64,
            closure,
            view,
        )


def test_personal_service_rejects_miskeyed_prepared_frame(tmp_path):
    spec, config, snapshot_id, closure, view, _db_path = _case(tmp_path)
    with _personal_prepared_frame_scope(
        db_path=draft_sqlite_path(view),
        snapshot_id="sha256:" + "0" * 64,
    ):
        with pytest.raises(
            PersonalPaperExecutionRejected,
            match="prepared frame snapshot",
        ):
            _execute(
                PersonalPaperExecutionService(),
                spec,
                config,
                snapshot_id,
                closure,
                view,
            )


def test_personal_service_rejects_snapshot_tamper_after_run(tmp_path, monkeypatch):
    from strategies.paper import runner

    spec, config, snapshot_id, closure, view, db_path = _case(tmp_path)
    real_backtest = runner.run_backtest

    def mutate_after_calculation(*args, **kwargs):
        result = real_backtest(*args, **kwargs)
        with sqlite3.connect(db_path) as writer:
            writer.execute("PRAGMA user_version = 77")
        return result

    monkeypatch.setattr(runner, "run_backtest", mutate_after_calculation)

    with pytest.raises(PersonalPaperExecutionRejected, match="changed during"):
        _execute(
            PersonalPaperExecutionService(), spec, config, snapshot_id, closure, view
        )


def test_personal_service_rejects_dependency_mismatch_before_calculation(tmp_path, monkeypatch):
    spec, config, snapshot_id, closure, view, _db_path = _case(tmp_path)
    dependency = closure.feature_dependencies[0]
    mismatches = (
        replace(closure, strategy_spec_hash="sha256:" + "0" * 64),
        replace(closure, feature_dependencies=(replace(dependency, params={"n": 3.0}),)),
        replace(closure, feature_dependencies=(replace(dependency, definition_digest="sha256:" + "0" * 64),)),
        replace(closure, plan_digest="sha256:" + "0" * 64),
    )
    monkeypatch.setattr(
        "execution.personal_paper_service.run_bound_personal_paper",
        lambda *args, **kwargs: pytest.fail("dependency mismatch reached calculation"),
    )
    for closure in mismatches:
        with pytest.raises(PersonalPaperExecutionRejected):
            _execute(PersonalPaperExecutionService(), spec, config, snapshot_id, closure, view)
    with pytest.raises(PersonalPaperExecutionRejected, match="run period"):
        _execute(
            PersonalPaperExecutionService(), spec,
            replace(config, start="2025-03-31", universe=replace(
                config.universe, period_start="2025-03-31", resolved_membership_digest="",
            )),
            snapshot_id, closure, view,
        )
    # A feature edit without a version bump must not reuse the snapshot's closure.
    from features.registry import FEATURES_REGISTRY

    key = (dependency.feature_id, dependency.feature_version)
    monkeypatch.setitem(
        FEATURES_REGISTRY, key,
        replace(FEATURES_REGISTRY[key], description="changed without version bump"),
    )
    with pytest.raises(PersonalPaperExecutionRejected, match="definition digest mismatch"):
        _execute(PersonalPaperExecutionService(), spec, config, snapshot_id, closure, view)


def test_personal_service_rejects_consumed_feature_mismatch(tmp_path, monkeypatch):
    spec, config, snapshot_id, closure, view, _db_path = _case(tmp_path)
    from paper_runtime import personal_draft_bind as module

    real_run_paper = module.run_paper

    def mismatched_run(*args, **kwargs):
        result = real_run_paper(*args, **kwargs)
        reproduction = dict(result.reproducibility)
        reproduction["feature_versions"] = {closure.feature_dependencies[0].feature_id: "9.9.9"}
        return replace(result, reproducibility=reproduction)

    monkeypatch.setattr(module, "run_paper", mismatched_run)

    with pytest.raises(
        PersonalPaperExecutionRejected,
        match="FeatureRefs do not match",
    ):
        _execute(
            PersonalPaperExecutionService(), spec, config, snapshot_id, closure, view
        )


@pytest.mark.parametrize("tamper", ["identity", "body"])
def test_personal_service_rejects_strategy_result_tamper(
    tmp_path, monkeypatch, tamper
):
    spec, config, snapshot_id, closure, view, _db_path = _case(tmp_path)
    from paper_runtime import personal_draft_bind as module

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
        _execute(
            PersonalPaperExecutionService(), spec, config, snapshot_id, closure, view
        )


@pytest.mark.parametrize(
    "field",
    ["universe_rule_digest", "resolved_universe_digest"],
)
def test_personal_service_rejects_universe_result_tamper(
    tmp_path, monkeypatch, field
):
    spec, config, snapshot_id, closure, view, _db_path = _case(tmp_path)
    from paper_runtime import personal_draft_bind as module

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
        _execute(
            PersonalPaperExecutionService(), spec, config, snapshot_id, closure, view
        )


@pytest.mark.parametrize("universe", [None, ("1332", "8697")])
def test_personal_service_requires_resolved_daily_universe(tmp_path, universe):
    spec, config, snapshot_id, closure, view, _db_path = _case(tmp_path)
    config = replace(config, universe=universe)

    with pytest.raises(
        PersonalPaperExecutionRejected,
        match="resolved daily universe",
    ):
        _execute(
            PersonalPaperExecutionService(), spec, config, snapshot_id, closure, view
        )
