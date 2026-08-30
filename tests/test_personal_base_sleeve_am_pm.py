"""Separately versioned AM base-sleeve producer stays off the next-close artifact."""

from __future__ import annotations

import copy
from typing import Any

import pytest
from core.result import BacktestResult
from pit.personal_retrospective_session import am_session_view_digest
from research.factor_cohorts import (
    AM_PM_EXECUTION_MODE,
    AM_SIGNAL_PM_CLOSE_EXECUTION_CONTRACT,
    PERSONAL_SHORT_FINANCING_AM_PM_COHORT_ID,
    canonical_trading_calendar_digest,
    get_research_cohort,
    personal_specs_for_cohort,
    verified_am_pm_base_digests,
)
from research.personal_base_sleeve import (
    AM_PM_BASE_COHORT_ID,
    AM_PM_BASE_SLEEVE_ID,
    EXPECTED_BASE_COHORT_DIGEST,
    EXPECTED_BASE_STRATEGY_SPEC_DIGEST,
    PERSONAL_BASE_SLEEVE_AM_PM_ARTIFACT_SCHEMA,
    PERSONAL_BASE_SLEEVE_ARTIFACT_SCHEMA,
    PERSONAL_BASE_SLEEVE_COST_BPS,
    PERSONAL_BASE_SLEEVE_SHORT_FINANCING_RATE,
    build_personal_base_sleeve_am_pm_artifact,
    validate_personal_base_sleeve_am_pm_artifact,
    validate_personal_base_sleeve_artifact,
)
from strategies.paper import Lifecycle, PaperRunResult
from strategies.spec import strategy_spec_digest


DATES = ("2023-01-04", "2023-01-05", "2023-01-06")
DIGEST = "sha256:" + "a" * 64


def _quality(
    *,
    skipped: tuple[str, ...] = (),
    incomplete: tuple[str, ...] = (),
    missing_fill: tuple[str, ...] = (),
) -> dict[str, Any]:
    comparable = not skipped and not incomplete and not missing_fill
    return {
        "comparable": comparable,
        "selection_eligible": comparable,
        "comparison_eligible": comparable,
        "incomplete_valuation": bool(incomplete),
        "skipped_decision_count": len(skipped),
        "incomplete_valuation_count": len(incomplete),
        "unfilled_order_count": len(missing_fill),
        "skipped_decision_dates": list(skipped),
        "incomplete_valuation_dates": list(incomplete),
        "incomplete_valuation_codes": ["1332"] if incomplete else [],
        "missing_fill_dates": list(missing_fill),
        "missing_fill_codes": ["1332"] if missing_fill else [],
        "non_comparable_session_dates": sorted(set(skipped) | set(incomplete) | set(missing_fill)),
        "held_missing_morning_adjustment_close": [
            {"date": day, "reason": "held_missing_morning_adjustment_close", "codes": ["1332"]}
            for day in skipped
        ],
        "held_missing_afternoon_adjustment_close": [
            {
                "date": day,
                "reason": "held_missing_afternoon_adjustment_close",
                "codes": ["1332"],
            }
            for day in incomplete
        ],
        "missing_afternoon_adjustment_close_unfilled": [
            {
                "date": day,
                "reason": "missing_afternoon_adjustment_close",
                "codes": ["1332"],
            }
            for day in missing_fill
        ],
    }


def _am_spec():
    return next(
        spec
        for spec in personal_specs_for_cohort(
            PERSONAL_SHORT_FINANCING_AM_PM_COHORT_ID, universe_id="topix_all"
        )
        if spec.strategy_id == AM_PM_BASE_SLEEVE_ID
    )


def _paper_result(
    rows: list[dict[str, Any]],
    *,
    quality: dict[str, Any] | None = None,
) -> PaperRunResult:
    quality = quality or _quality()
    return PaperRunResult(
        experiment_id="am-base-experiment",
        run_id="am-base-run",
        lifecycle=Lifecycle.DRAFT,
        backtest=BacktestResult(
            equity_curve=rows,
            trades=[],
            metrics={"comparable": quality["comparable"]},
            metadata={
                "execution_mode": "am_signal_pm_close",
                "session_view_digest": am_session_view_digest(
                    include_morning_turnover_history=True
                ),
                "data_quality": quality,
            },
        ),
        reproducibility={
            "execution_mode": "am_signal_pm_close",
            "period": {"start": rows[0]["date"], "end": rows[-1]["date"]},
            "starting_capital": 1_000_000.0,
            "strategy_id": AM_PM_BASE_SLEEVE_ID,
            "resolved_universe_digest": DIGEST,
        },
    )


def _evidence() -> dict[str, Any]:
    return {
        "cost_bps": PERSONAL_BASE_SLEEVE_COST_BPS,
        "execution_mode": "am_signal_pm_close",
        "execution_contract": dict(AM_SIGNAL_PM_CLOSE_EXECUTION_CONTRACT),
        "short_financing": {
            "annual_rate": PERSONAL_BASE_SLEEVE_SHORT_FINANCING_RATE,
            "baseline": True,
            "modelled_assumption": True,
            "borrow_evidence": False,
            "trace_digest": DIGEST,
        },
        "paper_artifact": "paper/base.json",
        "risk_artifact": "risk/base.json",
        "performance": {"schema_version": "personal-performance/v1"},
    }


def _build(
    rows: list[dict[str, Any]] | None = None,
    *,
    quality: dict[str, Any] | None = None,
    session_dates: tuple[str, ...] = DATES,
) -> dict[str, Any]:
    if rows is None:
        rows = [
            {
                "date": DATES[0],
                "equity": 1_000_000.0,
                "signal_equity": 1_000_000.0,
            },
            {
                "date": DATES[1],
                "equity": 1_010_000.0,
                "signal_equity": 1_005_000.0,
            },
            {
                "date": DATES[2],
                "equity": 1_020_000.0,
                "signal_equity": 1_012_000.0,
            },
        ]
    spec = _am_spec()
    cohort = get_research_cohort(PERSONAL_SHORT_FINANCING_AM_PM_COHORT_ID)
    return build_personal_base_sleeve_am_pm_artifact(
        result=_paper_result(rows, quality=quality),
        evidence=_evidence(),
        spec=spec,
        dependency_closure_digest=DIGEST,
        cohort_digest=str(cohort.to_dict()["cohort_digest"]),
        universe_id="topix_all",
        universe_rule_digest=DIGEST,
        resolved_membership_digest=DIGEST,
        snapshot_id=DIGEST,
        logical_data_snapshot_id=DIGEST,
        source_period=(session_dates[0], session_dates[-1]),
        source_session_dates=session_dates,
    )


def test_am_builder_binds_repo_identities_and_d_m_versus_d_a_nav() -> None:
    spec_digest, cohort_digest = verified_am_pm_base_digests()
    document = _build()
    assert document["schema_version"] == PERSONAL_BASE_SLEEVE_AM_PM_ARTIFACT_SCHEMA
    assert document["schema_version"] != PERSONAL_BASE_SLEEVE_ARTIFACT_SCHEMA
    assert document["strategy"]["strategy_id"] == AM_PM_BASE_SLEEVE_ID
    assert document["strategy"]["strategy_spec_digest"] == spec_digest
    assert document["cohort"]["cohort_id"] == AM_PM_BASE_COHORT_ID
    assert document["cohort"]["cohort_digest"] == cohort_digest
    assert document["source_run"]["execution_mode"] == "am_signal_pm_close"
    assert document["source_run"]["execution_mode"] != "am_pm"
    assert document["source_run"]["execution_contract_digest"] == (
        AM_SIGNAL_PM_CLOSE_EXECUTION_CONTRACT["contract_digest"]
    )
    assert document["source_run"]["session_view_digest"] == am_session_view_digest(
        include_morning_turnover_history=True
    )
    assert document["source_run"]["source_session_dates_digest"] == (
        canonical_trading_calendar_digest(DATES)
    )
    assert document["source_run"]["execution_contract_digest"] == (
        "sha256:5fc214947a8fdde7005561820a9bf4b3c301154535b4dc37cff09e9d801bddac"
    )
    assert document["source_run"]["session_view_digest"] == (
        "sha256:96ec026ad962605aaac6ce9de266be2da37852e9157b24ecfb5e04af97cc1027"
    )
    assert spec_digest == (
        "sha256:54a59cb980f38c37ac5879f979bd26a635bf23a95974413f2f24358ef936be4d"
    )
    assert cohort_digest == (
        "sha256:e12e65393985ab8b7cc2b0b922a362a055404777a49fda7250f735d47f0b073b"
    )
    assert AM_PM_EXECUTION_MODE == "am_signal_pm_close"
    first, second, third = document["daily_path"]
    assert first["am_nav"] == 1_000_000.0
    assert first["pm_nav"] == 1_000_000.0
    assert second["am_nav"] == 1_005_000.0
    assert second["pm_nav"] == 1_010_000.0
    assert second["am_nav"] != second["pm_nav"]
    assert third["base_sleeve_pm_return"] == pytest.approx(1_020_000.0 / 1_010_000.0 - 1.0)
    assert all(row["decision_valid"] is True for row in document["daily_path"])
    assert all(row["fill_valuation_valid"] is True for row in document["daily_path"])
    assert document["data_quality"]["comparable"] is True
    assert set(first) == {
        "date",
        "am_nav",
        "pm_nav",
        "base_sleeve_pm_return",
        "decision_valid",
        "fill_valuation_valid",
    }


def test_missing_m_and_a_stay_null_and_non_comparable() -> None:
    rows = [
        {"date": DATES[0], "equity": 1_000_000.0, "signal_equity": 1_000_000.0},
        {"date": DATES[1], "equity": 1_050_000.0, "signal_equity": None},
        {"date": DATES[2], "equity": 1_080_000.0, "signal_equity": 1_060_000.0},
    ]
    document = _build(
        rows,
        quality=_quality(skipped=(DATES[1],), incomplete=(DATES[2],)),
    )
    mid, last = document["daily_path"][1], document["daily_path"][2]
    assert mid["decision_valid"] is False
    assert mid["am_nav"] is None
    assert mid["fill_valuation_valid"] is True
    assert last["fill_valuation_valid"] is False
    assert last["pm_nav"] is None
    assert last["base_sleeve_pm_return"] is None
    assert document["data_quality"]["comparable"] is False
    assert document["data_quality"]["selection_eligible"] is False


def test_missing_a_rebases_pm_return_on_the_next_valid_afternoon() -> None:
    four = ("2023-01-04", "2023-01-05", "2023-01-06", "2023-01-07")
    rows = [
        {"date": four[0], "equity": 1_000_000.0, "signal_equity": 1_000_000.0},
        {"date": four[1], "equity": None, "signal_equity": 1_050_000.0},
        {"date": four[2], "equity": 1_200_000.0, "signal_equity": 1_150_000.0},
        {"date": four[3], "equity": 1_212_000.0, "signal_equity": 1_180_000.0},
    ]
    document = _build(
        rows,
        quality=_quality(incomplete=(four[1],)),
        session_dates=four,
    )
    first, gap, recovered, nxt = document["daily_path"]
    assert first["pm_nav"] == 1_000_000.0
    assert gap["fill_valuation_valid"] is False
    assert gap["pm_nav"] is None
    assert gap["base_sleeve_pm_return"] is None
    assert recovered["fill_valuation_valid"] is True
    assert recovered["pm_nav"] == 1_200_000.0
    assert recovered["base_sleeve_pm_return"] is None
    assert nxt["fill_valuation_valid"] is True
    assert nxt["base_sleeve_pm_return"] == pytest.approx(0.01)
    validate_personal_base_sleeve_am_pm_artifact(document)


def test_missing_fill_dates_are_not_valid_pm_valuations() -> None:
    rows = [
        {"date": DATES[0], "equity": 1_000_000.0, "signal_equity": 1_000_000.0},
        {"date": DATES[1], "equity": 1_050_000.0, "signal_equity": 1_020_000.0},
        {"date": DATES[2], "equity": 1_080_000.0, "signal_equity": 1_060_000.0},
    ]
    document = _build(rows, quality=_quality(missing_fill=(DATES[1],)))
    mid = document["daily_path"][1]
    assert mid["fill_valuation_valid"] is False
    assert mid["pm_nav"] is None
    assert mid["base_sleeve_pm_return"] is None
    assert document["data_quality"]["missing_fill_dates"] == [DATES[1]]
    validate_personal_base_sleeve_am_pm_artifact(document)


def test_am_validator_rejects_legacy_schema_invented_mode_and_arbitrary_digest() -> None:
    document = _build()
    legacy = copy.deepcopy(document)
    legacy["schema_version"] = PERSONAL_BASE_SLEEVE_ARTIFACT_SCHEMA
    with pytest.raises(ValueError, match="old next-close"):
        validate_personal_base_sleeve_am_pm_artifact(legacy)
    invented = copy.deepcopy(document)
    invented["source_run"]["execution_mode"] = "am_pm"
    with pytest.raises(ValueError, match="am_pm is not an execution mode"):
        validate_personal_base_sleeve_am_pm_artifact(invented)
    arbitrary = copy.deepcopy(document)
    arbitrary["strategy"]["strategy_spec_digest"] = "sha256:" + "c" * 64
    arbitrary["cohort"]["cohort_digest"] = "sha256:" + "d" * 64
    with pytest.raises(ValueError, match="frozen identity"):
        validate_personal_base_sleeve_am_pm_artifact(arbitrary)
    legacy_ids = copy.deepcopy(document)
    legacy_ids["strategy"]["strategy_spec_digest"] = EXPECTED_BASE_STRATEGY_SPEC_DIGEST
    legacy_ids["cohort"]["cohort_digest"] = EXPECTED_BASE_COHORT_DIGEST
    with pytest.raises(ValueError, match="frozen identity"):
        validate_personal_base_sleeve_am_pm_artifact(legacy_ids)
    with pytest.raises(ValueError, match="schema mismatch"):
        validate_personal_base_sleeve_artifact(document)


def test_am_strategy_digest_is_recomputed_from_repo_definitions() -> None:
    spec = _am_spec()
    live_spec, live_cohort = verified_am_pm_base_digests()
    assert strategy_spec_digest(spec) == live_spec
    assert get_research_cohort(AM_PM_BASE_COHORT_ID).to_dict()["cohort_digest"] == (
        live_cohort
    )
