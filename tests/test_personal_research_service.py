"""Behavior tests for the small personal DRAFT research loop."""

from __future__ import annotations

import json
import sqlite3
from datetime import date, timedelta
from pathlib import Path

import pytest

from data_contracts.identity import natural_key
from research.paper_candidate_specs import build_multi_day_hold_strategy_spec
from research.personal_service import (
    PERSONAL_DECISION_POLICY,
    PERSONAL_RESEARCH_REPORT_VERSION,
    PersonalResearchInputError,
    PersonalResearchPolicy,
    PersonalResearchRequest,
    PersonalResearchService,
    _calendar_lookback_days,
    _periods,
    _validated_specs,
    default_personal_specs,
)
from research.personal_universe import PersonalResolvedUniverseMembership
from storage.sqlite_store import SqliteStore
from strategies.spec import iter_feature_refs


def _dates(start: date, end: date) -> list[str]:
    values: list[str] = []
    cursor = start
    while cursor <= end:
        values.append(cursor.isoformat())
        cursor += timedelta(days=1)
    return values


def _generic(dataset: str, payload: dict, *, event: str, available: str) -> dict:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return {
        "source": "jquants",
        "dataset": dataset,
        "natural_key": natural_key(payload, dataset),
        "event_time": event,
        "available_at": available,
        "ingested_at": available,
        "payload": encoded,
        "raw_payload": encoded,
    }


@pytest.fixture
def personal_db(tmp_path: Path) -> tuple[Path, str, str]:
    start = date(2024, 1, 1)
    end = date(2024, 5, 31)
    all_days = _dates(start, end)
    sessions = [day for day in all_days if date.fromisoformat(day).weekday() < 5]
    codes = ("1301", "1302", "1303", "1304")
    source = tmp_path / "personal.sqlite"
    store = SqliteStore(source)
    store.upsert(
        "jquants_market_calendar",
        [
            {
                "source": "jquants",
                "date": day,
                "event_time": f"{day}T09:00:00+09:00",
                "available_at": "2023-01-01T00:00:00+09:00",
                "ingested_at": "2023-01-01T00:00:00+09:00",
                "holiday_division": (
                    "1" if date.fromisoformat(day).weekday() < 5 else "0"
                ),
            }
            for day in all_days
        ],
    )
    store.upsert(
        "jquants_listed_info",
        [
            {
                "source": "jquants",
                "code": code,
                "snapshot_date": "2023-12-29",
                "event_time": "2023-12-29T09:00:00+09:00",
                "available_at": "2023-12-29T09:00:00+09:00",
                "ingested_at": "2023-12-29T09:00:00+09:00",
                "company_name": f"Fixture {code}",
                "sector_17_code": "1",
                "market_code": "0112" if code == "1304" else "0111",
                "scale_category": (
                    "TOPIX Core30" if code == "1301" else "TOPIX Large70"
                ),
            }
            for code in codes
        ],
    )
    bars: list[dict] = []
    generic: list[dict] = []
    for day in all_days:
        holiday = "1" if date.fromisoformat(day).weekday() < 5 else "0"
        generic.append(
            _generic(
                "markets_calendar",
                {"Date": day, "HolidayDivision": holiday},
                event=f"{day}T09:00:00+09:00",
                available="2023-01-01T00:00:00+09:00",
            )
        )
    for code_index, code in enumerate(codes):
        master = {
            "Code": code,
            "Date": "2023-12-29",
            "CompanyName": f"Fixture {code}",
            "MarketCode": "0112" if code == "1304" else "0111",
            "ScaleCategory": (
                "TOPIX Core30" if code == "1301" else "TOPIX Large70"
            ),
        }
        generic.append(
            _generic(
                "equities_master",
                master,
                event="2023-12-29T09:00:00+09:00",
                available="2023-12-29T09:00:00+09:00",
            )
        )
        fins = {
            "Code": code,
            "DiscDate": "2023-12-29",
            "DiscNo": str(code_index + 1),
            "EPS": 8.0 + code_index,
            "BPS": 80.0 + 10.0 * code_index,
        }
        generic.append(
            _generic(
                "fins_summary",
                fins,
                event="2023-12-29T15:00:00+09:00",
                available="2023-12-29T15:00:00+09:00",
            )
        )
        for session_index, day in enumerate(sessions):
            close = 100.0 + code_index * 5.0 + session_index * (0.2 + code_index * 0.05)
            available = f"{day}T15:00:00+09:00"
            bars.append(
                {
                    "source": "jquants",
                    "code": code,
                    "date": day,
                    "event_time": available,
                    "available_at": available,
                    "ingested_at": available,
                    "open": close,
                    "high": close,
                    "low": close,
                    "close": close,
                    "adjustment_close": close,
                    "volume": 1000.0,
                }
            )
    store.upsert("jquants_daily_bars", bars)
    store.upsert("jquants_records", generic)
    store.close()
    return source, start.isoformat(), end.isoformat()


def _policy(**changes) -> PersonalResearchPolicy:
    values = {
        "validation_folds": 2,
        "min_fold_sessions": 20,
        "holdout_months": 1,
        "min_holdout_sessions": 20,
        "base_cost_bps": 0.0,
        "stress_cost_bps": 0.0,
        "min_positive_folds": 2,
        "min_validation_sharpe": -100.0,
        "max_drawdown": 1.0,
        "min_fills": 0,
        "max_candidates": 12,
        "max_parallel": 1,
    }
    values.update(changes)
    return PersonalResearchPolicy(**values)


def _request(
    source: Path, start: str, end: str, output: Path
) -> PersonalResearchRequest:
    return PersonalResearchRequest(
        source_db=source,
        period_start=start,
        period_end=end,
        output_root=output,
        specs=(
            build_multi_day_hold_strategy_spec(
                hold_days=3,
                momentum_n=3,
                top_k=2,
                momentum_feature_id=(
                    "retrospective_split_adjusted_momentum_n"
                ),
                strategy_id="personal_test_momentum",
            ),
        ),
    )


def _install_managed_sync_evidence(source: Path, *, failing: str | None = None) -> None:
    datasets = (
        "equities_bars_daily",
        "equities_master",
        "fins_summary",
        "markets_calendar",
    )
    connection = sqlite3.connect(source)
    try:
        connection.execute(
            "INSERT INTO local_snapshot_policy "
            "(singleton,require_manifest,snapshot_ready,publication_state,last_error) "
            "VALUES (1,1,0,'REJECTED','READY not published') "
            "ON CONFLICT(singleton) DO UPDATE SET require_manifest=1,"
            "snapshot_ready=0,publication_state='REJECTED',"
            "last_error='READY not published'"
        )
        connection.execute(
            "CREATE TABLE IF NOT EXISTS ingestion_validation ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT,dataset TEXT,status TEXT,"
            "rows_seen INTEGER)"
        )
        connection.execute(
            "CREATE TABLE IF NOT EXISTS ingestion_watermarks ("
            "dataset TEXT PRIMARY KEY,last_ingested_at TEXT NOT NULL)"
        )
        for dataset in datasets:
            connection.execute(
                "INSERT INTO ingestion_validation(dataset,status,rows_seen) "
                "VALUES (?,?,1)",
                (dataset, "fail" if dataset == failing else "pass"),
            )
            connection.execute(
                "INSERT INTO ingestion_watermarks(dataset,last_ingested_at) "
                "VALUES (?,?)",
                (dataset, "2024-06-01T00:00:00+09:00"),
            )
        connection.commit()
    finally:
        connection.close()


def test_personal_research_runs_real_paper_and_is_idempotent(
    personal_db: tuple[Path, str, str], tmp_path: Path
) -> None:
    source, start, end = personal_db
    service = PersonalResearchService(policy=_policy())
    request = _request(source, start, end, tmp_path / "artifacts")

    first = service.run(request)
    second = service.run(request)

    assert first.exit_code == 0
    assert first.report_id == second.report_id
    assert first.report_json_path == second.report_json_path
    assert first.snapshot == second.snapshot
    report = json.loads(first.report_json_path.read_text(encoding="utf-8"))
    assert report["version"] == PERSONAL_RESEARCH_REPORT_VERSION
    assert report["decision_policy"] == PERSONAL_DECISION_POLICY
    assert report["summary"] == {
        "analysis_status": "COMPLETED",
        "candidate_count": 1,
        "evaluated_count": 1,
        "hold_count": 1,
        "unexpected_errors": 0,
    }
    assert report["candidates"][0]["decision"] == "HOLD"
    assert report["candidates"][0]["stress"] is not None
    assert report["candidates"][0]["holdout"] is not None
    assert report["candidates"][0]["holdout"]["selection_use"] is False
    candidate = report["candidates"][0]
    assert candidate["strategy"]["thesis"]
    assert candidate["strategy"]["mechanics_summary"]
    assert candidate["strategy"]["return_source"]
    assert candidate["strategy"]["works_when"]
    assert candidate["strategy"]["fails_when"]
    assert candidate["validation"]["performance"]["schema_version"] == (
        "personal-fold-stability/v1"
    )
    assert candidate["validation"]["performance"]["stitched_performance"][
        "schema_version"
    ] == "personal-performance/v1"
    assert report["comparison"]["schema_version"] == (
        "personal-performance-comparison/v2"
    )
    comparison_row = report["comparison"]["rows"][0]
    assert comparison_row["return_source"]
    assert comparison_row["works_when"]
    assert comparison_row["fails_when"]
    assert comparison_row["evidence_assessment"]
    assert report["comparison"]["rows"][0]["strategy_id"] == (
        candidate["strategy_id"]
    )
    assert first.universe_id == "topix_all"
    assert report["universe"]["rule_id"] == "topix_all_with_fins"
    assert report["universe"]["controlled_live_eligibility"] == "FORBIDDEN"
    assert report["dependency_closures"][0]["universe_dependencies"][0][
        "id"
    ] == "topix_all_with_fins"
    markdown = first.report_markdown_path.read_text(encoding="utf-8")
    assert "## Comparable performance" in markdown
    assert "Return source" in markdown
    assert "Works when" in markdown
    assert "Fails when" in markdown
    assert "Evidence" in markdown
    assert report["data_quality"]["market_bar_coverage"]["status"] == "PASS"
    assert report["price_basis"] == {
        "id": "PERSONAL_RETROSPECTIVE_ADJUSTED",
        "source": "vendor_adjusted_ohlcv",
        "time_semantics": "retrospective_not_point_in_time",
        "position_units": "synthetic_split_adjusted_units",
        "supported_actions": "vendor_splits_and_reverse_splits",
        "unexplained_action_policy": (
            "extreme_adjusted_moves_advisory; missing_adjusted_"
            "evidence_fail_closed"
        ),
        "lifecycle": "DRAFT_only",
        "live_trading_eligible": False,
    }
    assert report["live_orders_enabled"] is False
    assert report["automatic_promotion"] is False
    assert report["model_calls"] == 0
    assert report["estimated_ai_cost_usd"] == 0.0


def test_zero_passes_is_completed_not_an_error(
    personal_db: tuple[Path, str, str], tmp_path: Path
) -> None:
    source, start, end = personal_db
    result = PersonalResearchService(policy=_policy(min_fills=1_000_000)).run(
        _request(source, start, end, tmp_path / "rejected")
    )

    assert result.exit_code == 0
    assert result.hold_count == 0
    report = json.loads(result.report_json_path.read_text(encoding="utf-8"))
    assert report["candidates"][0]["decision"] == "REJECT"
    assert "fills" in report["candidates"][0]["reasons"]
    assert report["candidates"][0]["stress"] is None
    assert report["candidates"][0]["holdout"] is None


def test_default_candidates_are_long_only_where_applicable() -> None:
    specs = default_personal_specs()
    assert len(specs) == 4
    assert all(
        "retrospective_split_adjusted_momentum_n"
        in {ref.id for ref in iter_feature_refs(spec)}
        for spec in specs
    )
    assert specs[2].rule.allow_short is False
    assert specs[3].rule.allow_short is False


def test_closed_cohort_selection_and_explicit_specs_are_mutually_exclusive() -> None:
    specs, cohort = _validated_specs(
        None,
        _policy(),
        "diverse-core-v1",
    )
    assert cohort is not None
    assert cohort.cohort_id == "diverse-core-v1"
    assert len(specs) == 4

    with pytest.raises(PersonalResearchInputError, match="mutually exclusive"):
        _validated_specs((specs[0],), _policy(), "diverse-core-v1")
    with pytest.raises(PersonalResearchInputError, match="must be one of"):
        _validated_specs(None, _policy(), "sector-relative-ls-v1")


def test_selected_cohort_id_and_digest_are_bound_to_report(
    personal_db: tuple[Path, str, str], tmp_path: Path
) -> None:
    source, start, end = personal_db
    result = PersonalResearchService(policy=_policy()).run(
        PersonalResearchRequest(
            source_db=source,
            period_start=start,
            period_end=end,
            output_root=tmp_path / "cohort-report",
            cohort_id="diverse-core-v1",
        )
    )
    report = json.loads(result.report_json_path.read_text(encoding="utf-8"))

    assert result.cohort_id == "diverse-core-v1"
    assert result.cohort_digest == report["strategy_cohort"]["cohort_digest"]
    assert report["strategy_cohort"]["registry_version"] == (
        "personal-factor-cohorts/v2"
    )
    assert report["summary"]["candidate_count"] == 4
    assert report["summary"]["analysis_status"] == "NO_ANALYSIS"
    assert report["period"] == {
        "start": start,
        "data_start": start,
        "evaluation_start": None,
        "end": end,
        "warmup_sessions": 253,
    }
    assert all(
        candidate["reasons"] == ["insufficient_post_warmup_sessions"]
        for candidate in report["candidates"]
    )
    assert all(
        closure["plan_digest"].startswith("sha256:")
        for closure in report["dependency_closures"]
    )
    assert "Cohort: `diverse-core-v1`" in result.report_markdown_path.read_text(
        encoding="utf-8"
    )


def test_cohort_history_floor_is_enforced_before_materialization(
    personal_db: tuple[Path, str, str], tmp_path: Path
) -> None:
    source, _start, end = personal_db

    with pytest.raises(PersonalResearchInputError, match="history floor 2008-07-07"):
        PersonalResearchService(policy=_policy()).run(
            PersonalResearchRequest(
                source_db=source,
                period_start="2008-07-06",
                period_end=end,
                output_root=tmp_path / "must-not-materialize",
                cohort_id="price-relative-v1",
            )
        )
    assert not (tmp_path / "must-not-materialize").exists()


def test_cohort_warmup_sessions_are_excluded_from_analysis_periods() -> None:
    days = _dates(date(2024, 1, 1), date(2024, 4, 30))
    universe = PersonalResolvedUniverseMembership(
        period_start=days[0],
        period_end=days[-1],
        decision_memberships=tuple((day, ("1301",)) for day in days),
        rule_id="topix_all_with_fins",
        rule_version="personal-topix-scale-with-fins/v1",
        rule_digest=(
            "sha256:1111111111111111111111111111111111111111111111111111111111111111"
        ),
    )
    policy = _policy(
        validation_folds=1,
        min_fold_sessions=10,
        holdout_months=1,
        min_holdout_sessions=10,
        min_positive_folds=1,
    )

    periods = _periods(
        universe,
        end=date.fromisoformat(days[-1]),
        policy=policy,
        warmup_sessions=5,
    )

    assert periods is not None
    validation, _holdout = periods
    assert validation[0][0] == days[5]
    assert (
        _periods(
            universe,
            end=date.fromisoformat(days[-1]),
            policy=policy,
            warmup_sessions=len(days),
        )
        is None
    )


def test_large_trading_lookback_is_expanded_to_calendar_days() -> None:
    assert _calendar_lookback_days(252) == 534


def test_report_identity_is_independent_of_output_directory(
    personal_db: tuple[Path, str, str], tmp_path: Path
) -> None:
    source, start, end = personal_db
    service = PersonalResearchService(policy=_policy())

    first = service.run(_request(source, start, end, tmp_path / "out-a"))
    second = service.run(_request(source, start, end, tmp_path / "out-b"))

    assert first.snapshot.snapshot_id == second.snapshot.snapshot_id
    assert first.report_id == second.report_id
    first_report = json.loads(first.report_json_path.read_text(encoding="utf-8"))
    paper_path = tmp_path / "out-a" / first_report["candidates"][0]["validation"][
        "runs"
    ][0]["paper_artifact"]
    paper = json.loads(paper_path.read_text(encoding="utf-8"))
    assert "db_path" not in paper["reproducibility"]
    assert "db_path" not in paper["backtest"]["metadata"]


def test_incomplete_observed_bar_breadth_is_no_analysis(
    personal_db: tuple[Path, str, str], tmp_path: Path
) -> None:
    source, start, end = personal_db
    connection = sqlite3.connect(source)
    try:
        connection.execute(
            "DELETE FROM jquants_daily_bars WHERE code='1304' AND date=?", (start,)
        )
        connection.execute(
            "DELETE FROM jquants_records WHERE dataset='equities_bars_daily' "
            "AND substr(event_time,1,10)=? AND json_extract(payload,'$.Code')='1304'",
            (start,),
        )
        connection.commit()
    finally:
        connection.close()

    result = PersonalResearchService(policy=_policy()).run(
        _request(source, start, end, tmp_path / "incomplete")
    )

    assert result.exit_code == 2
    assert result.evaluated_count == 0
    report = json.loads(result.report_json_path.read_text(encoding="utf-8"))
    assert report["summary"]["analysis_status"] == "NO_ANALYSIS"
    assert report["data_quality"]["market_bar_coverage"]["status"] == "FAIL"
    assert report["candidates"][0]["decision"] == "SKIPPED"


def test_partial_financials_cannot_silently_shrink_the_universe(
    personal_db: tuple[Path, str, str], tmp_path: Path
) -> None:
    source, start, end = personal_db
    connection = sqlite3.connect(source)
    try:
        connection.execute(
            "DELETE FROM jquants_records WHERE dataset='fins_summary' "
            "AND json_extract(payload,'$.Code')='1304'"
        )
        connection.commit()
    finally:
        connection.close()

    result = PersonalResearchService(policy=_policy()).run(
        _request(source, start, end, tmp_path / "partial-fins")
    )

    assert result.exit_code == 2
    report = json.loads(result.report_json_path.read_text(encoding="utf-8"))
    breadth = report["data_quality"]["universe_breadth"]
    assert breadth["status"] == "FAIL"
    assert breadth["minimum_daily_ratio"] == 0.75
    assert report["candidates"][0]["reasons"] == [
        "universe_fins_breadth_below_threshold"
    ]


def test_factor_change_is_handled_and_extreme_move_is_advisory(
    personal_db: tuple[Path, str, str], tmp_path: Path
) -> None:
    source, start, end = personal_db
    connection = sqlite3.connect(source)
    try:
        connection.execute(
            "UPDATE jquants_daily_bars SET adjustment_close=close/2 "
            "WHERE code='1304' AND date>='2024-03-01'"
        )
        connection.execute(
            "UPDATE jquants_records SET "
            "payload=json_set(payload,'$.AdjustmentClose',"
            "json_extract(payload,'$.Close')/2),"
            "raw_payload=json_set(raw_payload,'$.AdjustmentClose',"
            "json_extract(raw_payload,'$.Close')/2) "
            "WHERE dataset='equities_bars_daily' "
            "AND json_extract(payload,'$.Code')='1304' "
            "AND json_extract(payload,'$.Date')>='2024-03-01'"
        )
        connection.commit()
    finally:
        connection.close()

    result = PersonalResearchService(policy=_policy()).run(
        _request(source, start, end, tmp_path / "split")
    )

    assert result.exit_code == 0
    report = json.loads(result.report_json_path.read_text(encoding="utf-8"))
    candidate = report["candidates"][0]
    assert "corporate_action_trades" not in candidate["reasons"]
    assert report["data_quality"]["corporate_actions"]["status"] == "WARN"
    assert "1304" in report["data_quality"]["corporate_actions"][
        "affected_codes"
    ]
    corporate_actions = report["data_quality"]["corporate_actions"]
    assert "1304" in corporate_actions["suspicious_jump_codes"]
    assert corporate_actions["extreme_price_move_events"]


def test_large_adjusted_market_move_is_not_a_corporate_action_rejection(
    personal_db: tuple[Path, str, str], tmp_path: Path
) -> None:
    source, start, end = personal_db
    connection = sqlite3.connect(source)
    try:
        connection.execute(
            "UPDATE jquants_daily_bars SET open=open*1.4,high=high*1.4,"
            "low=low*1.4,close=close*1.4,adjustment_close=adjustment_close*1.4 "
            "WHERE code='1304' AND date='2024-03-11'"
        )
        connection.commit()
    finally:
        connection.close()

    result = PersonalResearchService(policy=_policy()).run(
        _request(source, start, end, tmp_path / "large-market-move")
    )

    assert result.exit_code == 0
    report = json.loads(result.report_json_path.read_text(encoding="utf-8"))
    corporate_actions = report["data_quality"]["corporate_actions"]
    candidate = report["candidates"][0]
    assert corporate_actions["status"] == "WARN"
    assert corporate_actions["affected_codes"] == []
    assert "1304" in corporate_actions["suspicious_jump_codes"]
    assert corporate_actions["extreme_price_move_events"]
    assert "corporate_action_trades" not in candidate["reasons"]


def test_constant_back_adjustment_factor_is_not_a_false_split_boundary(
    personal_db: tuple[Path, str, str], tmp_path: Path
) -> None:
    source, start, end = personal_db
    connection = sqlite3.connect(source)
    try:
        connection.execute(
            "UPDATE jquants_daily_bars SET adjustment_close=ROUND(close/3,1) "
            "WHERE code='1304'"
        )
        connection.execute(
            "UPDATE jquants_records SET "
            "payload=json_set(payload,'$.AdjustmentClose',"
            "ROUND(json_extract(payload,'$.Close')/3,1)),"
            "raw_payload=json_set(raw_payload,'$.AdjustmentClose',"
            "ROUND(json_extract(raw_payload,'$.Close')/3,1)) "
            "WHERE dataset='equities_bars_daily' "
            "AND json_extract(payload,'$.Code')='1304'"
        )
        connection.commit()
    finally:
        connection.close()

    result = PersonalResearchService(policy=_policy()).run(
        _request(source, start, end, tmp_path / "constant-adjustment")
    )

    assert result.exit_code == 0
    report = json.loads(result.report_json_path.read_text(encoding="utf-8"))
    assert report["data_quality"]["corporate_actions"]["status"] == "PASS"
    assert report["data_quality"]["corporate_actions"]["affected_codes"] == []


def test_recent_holdout_metrics_are_exploratory_not_a_selection_gate(
    personal_db: tuple[Path, str, str], tmp_path: Path, monkeypatch
) -> None:
    source, start, end = personal_db
    import research.personal_service as module

    calls = 0

    def fake_run_one(*args, **kwargs):
        nonlocal calls
        calls += 1
        recent = calls == 4
        evidence = {
            "total_return_post_cost": -0.1 if recent else 0.1,
            "annualized_sharpe": -1.0 if recent else 1.0,
            "max_drawdown": 0.1,
            "fills": 100,
            "risk_status": "pass",
        }
        returns = (
            [-0.015, -0.005] * 10
            if recent
            else [0.005, 0.015] * 10
        )
        dates = [f"2024-01-{index + 1:02d}" for index in range(len(returns))]
        return evidence, returns, dates

    monkeypatch.setattr(module, "_run_one", fake_run_one)
    result = PersonalResearchService(policy=_policy()).run(
        _request(source, start, end, tmp_path / "exploratory")
    )

    report = json.loads(result.report_json_path.read_text(encoding="utf-8"))
    candidate = report["candidates"][0]
    assert candidate["decision"] == "HOLD"
    assert candidate["holdout"]["checks"]["positive_return"] is False
    assert candidate["holdout"]["selection_use"] is False


def test_rejected_ready_state_does_not_block_valid_personal_sync_evidence(
    personal_db: tuple[Path, str, str], tmp_path: Path
) -> None:
    source, start, end = personal_db
    _install_managed_sync_evidence(source)

    result = PersonalResearchService(policy=_policy()).run(
        _request(source, start, end, tmp_path / "managed-valid")
    )

    assert result.exit_code == 0
    report = json.loads(result.report_json_path.read_text(encoding="utf-8"))
    assert report["data_quality"]["source_sync"]["status"] == "PASS"
    assert report["data_quality"]["source_sync"][
        "source_publication_state"
    ] == "REJECTED"


def test_failed_latest_dataset_validation_is_no_analysis(
    personal_db: tuple[Path, str, str], tmp_path: Path
) -> None:
    source, start, end = personal_db
    _install_managed_sync_evidence(source, failing="fins_summary")

    result = PersonalResearchService(policy=_policy()).run(
        _request(source, start, end, tmp_path / "managed-failed")
    )

    assert result.exit_code == 2
    report = json.loads(result.report_json_path.read_text(encoding="utf-8"))
    assert report["summary"]["analysis_status"] == "NO_ANALYSIS"
    assert report["data_quality"]["source_sync"]["status"] == "FAIL"
    assert report["candidates"][0]["reasons"] == [
        "source_sync_evidence_unusable"
    ]


def test_unexpected_candidate_error_keeps_bounded_diagnostic(
    personal_db: tuple[Path, str, str], tmp_path: Path, monkeypatch
) -> None:
    source, start, end = personal_db
    import research.personal_service as module

    def explode(*args, **kwargs):
        raise RuntimeError("useful bounded diagnostic")

    monkeypatch.setattr(module, "_candidate_evaluation", explode)
    result = PersonalResearchService(policy=_policy()).run(
        _request(source, start, end, tmp_path / "unexpected")
    )

    assert result.exit_code == 1
    report = json.loads(result.report_json_path.read_text(encoding="utf-8"))
    error = report["candidates"][0]["error"]
    assert error == {
        "type": "RuntimeError",
        "detail": "useful bounded diagnostic",
    }
