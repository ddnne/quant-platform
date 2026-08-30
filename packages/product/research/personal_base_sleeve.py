"""Canonical DRAFT source artifact for the frozen index-volatility base sleeve.

The index-volatility overlay consumes one continuous stock-sleeve NAV rather
than stitched validation folds.  This module turns the one extra, predeclared
paper run into a small content-addressable document.  It does not evaluate an
overlay, rank a candidate, promote a strategy, or place an order.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from datetime import date
from pathlib import PurePosixPath
from typing import Any, Final

from strategies.paper import Lifecycle, PaperRunResult
from strategies.spec import StrategySpec, strategy_spec_digest

from research.personal_index_vol_overlay import (
    BASE_COHORT_ID,
    BASE_NAV_SEMANTICS,
    BASE_RETURN_SEMANTICS,
    BASE_SLEEVE_ID,
    BASE_UNIVERSE_ID,
    EXPECTED_BASE_COHORT_DIGEST,
    EXPECTED_BASE_STRATEGY_SPEC_DIGEST,
    SOURCE_SLICE_WRAPPER_COST_SEMANTICS,
    canonical_trading_calendar_digest,
)

PERSONAL_BASE_SLEEVE_ARTIFACT_SCHEMA: Final = "personal-base-sleeve-source/v1"
PERSONAL_BASE_SLEEVE_REFERENCE_SCHEMA: Final = "personal-base-sleeve-reference/v1"
PERSONAL_BASE_SLEEVE_ROLE: Final = "INDEX_VOL_OVERLAY_BASE_SOURCE"
PERSONAL_BASE_SLEEVE_RANKING_ROLE: Final = "NON_CANDIDATE_NOT_RANKED"
PERSONAL_BASE_SLEEVE_COST_BPS: Final = 10.0
PERSONAL_BASE_SLEEVE_SHORT_FINANCING_RATE: Final = 0.03
PERSONAL_BASE_SLEEVE_STARTING_CAPITAL: Final = 1_000_000.0


def _sha256_digest(value: Any) -> bool:
    if not isinstance(value, str) or not value.startswith("sha256:"):
        return False
    payload = value[7:]
    return len(payload) == 64 and all(
        character in "0123456789abcdef" for character in payload
    )


def _safe_archive_member(value: Any) -> bool:
    if not isinstance(value, str) or not value:
        return False
    path = PurePosixPath(value)
    return not path.is_absolute() and ".." not in path.parts


def _finite_number(value: Any) -> float:
    if isinstance(value, bool):
        raise TypeError("base sleeve numeric values cannot be booleans")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("base sleeve numeric value is invalid") from exc
    if not math.isfinite(number):
        raise ValueError("base sleeve numeric value must be finite")
    return number


def _canonical_day(value: Any) -> str:
    if not isinstance(value, str):
        raise TypeError("base sleeve date must be canonical ISO")
    try:
        canonical = date.fromisoformat(value).isoformat()
    except ValueError as exc:
        raise ValueError("base sleeve date must be canonical ISO") from exc
    if canonical != value:
        raise ValueError("base sleeve date must be canonical ISO")
    return canonical


def _daily_path(
    result: PaperRunResult,
    *,
    starting_capital: float,
) -> list[dict[str, Any]]:
    previous_equity = _finite_number(starting_capital)
    if previous_equity <= 0.0:
        raise ValueError("base sleeve starting capital must be positive")
    previous_day: str | None = None
    rows: list[dict[str, Any]] = []
    for source in result.equity_curve:
        day = _canonical_day(source.get("date"))
        if previous_day is not None and day <= previous_day:
            raise ValueError("base sleeve dates must be strictly increasing")
        equity = _finite_number(source.get("equity"))
        if equity <= 0.0:
            raise ValueError("base sleeve equity must remain positive")
        rows.append(
            {
                "date": day,
                "equity": equity,
                "base_sleeve_return": equity / previous_equity - 1.0,
            }
        )
        previous_day = day
        previous_equity = equity
    if not rows:
        raise ValueError("base sleeve source run produced no daily NAV")
    return rows


def _require_exact_execution(
    result: PaperRunResult,
    evidence: Mapping[str, Any],
    *,
    source_period: tuple[str, str],
) -> None:
    if result.lifecycle is not Lifecycle.DRAFT:
        raise ValueError("base sleeve source must remain DRAFT")
    if result.strategy_id != BASE_SLEEVE_ID:
        raise ValueError("base sleeve source strategy is not the frozen strategy")
    reproduction = result.reproducibility
    if reproduction.get("execution_mode") != "next_close":
        raise ValueError("base sleeve source must use next_close")
    if reproduction.get("period") != {
        "start": source_period[0],
        "end": source_period[1],
    }:
        raise ValueError("base sleeve source period does not match its paper run")
    if not math.isclose(
        _finite_number(reproduction.get("starting_capital")),
        PERSONAL_BASE_SLEEVE_STARTING_CAPITAL,
    ):
        raise ValueError("base sleeve source starting capital drifted")
    if not math.isclose(
        _finite_number(evidence.get("cost_bps")),
        PERSONAL_BASE_SLEEVE_COST_BPS,
    ):
        raise ValueError("base sleeve source must use 10bp stock costs")
    financing = evidence.get("short_financing")
    if not isinstance(financing, Mapping):
        raise TypeError("base sleeve source is missing short-financing evidence")
    if (
        not math.isclose(
            _finite_number(financing.get("annual_rate")),
            PERSONAL_BASE_SLEEVE_SHORT_FINANCING_RATE,
        )
        or financing.get("baseline") is not True
        or financing.get("modelled_assumption") is not True
        or financing.get("borrow_evidence") is not False
        or not _sha256_digest(financing.get("trace_digest"))
    ):
        raise ValueError("base sleeve source must use fixed 3% financing")
    forbidden = [
        str(trade.get("side") or "")
        for trade in result.trades
        if "terminal" in str(trade.get("side") or "").lower()
        or "liquidat" in str(trade.get("side") or "").lower()
        or "wrapper" in str(trade.get("side") or "").lower()
    ]
    if forbidden:
        raise ValueError("base sleeve source contains wrapper or terminal trades")


def build_personal_base_sleeve_artifact(
    *,
    result: PaperRunResult,
    evidence: Mapping[str, Any],
    spec: StrategySpec,
    dependency_closure_digest: str,
    cohort_digest: str,
    universe_id: str,
    universe_rule_digest: str,
    resolved_membership_digest: str,
    snapshot_id: str,
    logical_data_snapshot_id: str,
    source_period: tuple[str, str],
    source_session_dates: tuple[str, ...],
) -> dict[str, Any]:
    """Build and validate the single continuous, non-candidate NAV source."""

    if spec.strategy_id != BASE_SLEEVE_ID:
        raise ValueError("base sleeve artifact requires the frozen strategy")
    if strategy_spec_digest(spec) != EXPECTED_BASE_STRATEGY_SPEC_DIGEST:
        raise ValueError("base sleeve strategy definition drifted")
    if cohort_digest != EXPECTED_BASE_COHORT_DIGEST:
        raise ValueError("base sleeve cohort definition drifted")
    if universe_id != BASE_UNIVERSE_ID:
        raise ValueError("base sleeve artifact is frozen to topix_all")
    start, end = map(_canonical_day, source_period)
    if end < start:
        raise ValueError("base sleeve source period is reversed")
    _require_exact_execution(result, evidence, source_period=(start, end))
    if resolved_membership_digest != result.reproducibility.get(
        "resolved_universe_digest"
    ):
        raise ValueError(
            "base sleeve membership digest does not match its paper run"
        )
    daily_path = _daily_path(
        result,
        starting_capital=PERSONAL_BASE_SLEEVE_STARTING_CAPITAL,
    )
    ordered_session_dates = tuple(row["date"] for row in daily_path)
    if ordered_session_dates != tuple(source_session_dates):
        raise ValueError("base sleeve daily NAV must cover every source session")
    if ordered_session_dates[0] != start or ordered_session_dates[-1] != end:
        raise ValueError("base sleeve daily NAV must span the source period")
    source_session_dates_digest = canonical_trading_calendar_digest(
        ordered_session_dates
    )
    for digest in (
        dependency_closure_digest,
        universe_rule_digest,
        resolved_membership_digest,
        snapshot_id,
        logical_data_snapshot_id,
    ):
        if not _sha256_digest(digest):
            raise ValueError("base sleeve provenance requires canonical digests")
    for artifact_field in ("paper_artifact", "risk_artifact"):
        if not _safe_archive_member(evidence.get(artifact_field)):
            raise ValueError(f"base sleeve {artifact_field} is not archive-safe")
    performance = evidence.get("performance")
    if not isinstance(performance, Mapping):
        raise TypeError("base sleeve performance evidence is missing")
    financing = evidence["short_financing"]
    document: dict[str, Any] = {
        "schema_version": PERSONAL_BASE_SLEEVE_ARTIFACT_SCHEMA,
        "role": PERSONAL_BASE_SLEEVE_ROLE,
        "ranking_role": PERSONAL_BASE_SLEEVE_RANKING_ROLE,
        "candidate_count_contribution": 0,
        "strategy": {
            "strategy_id": BASE_SLEEVE_ID,
            "strategy_spec_version": spec.version,
            "strategy_spec_digest": EXPECTED_BASE_STRATEGY_SPEC_DIGEST,
            "dependency_closure_digest": dependency_closure_digest,
        },
        "cohort": {
            "cohort_id": BASE_COHORT_ID,
            "cohort_digest": cohort_digest,
        },
        "universe": {
            "universe_id": universe_id,
            "universe_rule_digest": universe_rule_digest,
            "resolved_membership_digest": resolved_membership_digest,
        },
        "snapshot": {
            "snapshot_id": snapshot_id,
            "logical_data_snapshot_id": logical_data_snapshot_id,
        },
        "source_run": {
            "experiment_id": result.experiment_id,
            "run_id": result.run_id,
            "period": {"start": start, "end": end},
            "execution_mode": "next_close",
            "starting_capital": PERSONAL_BASE_SLEEVE_STARTING_CAPITAL,
            "stock_one_way_cost_bps": PERSONAL_BASE_SLEEVE_COST_BPS,
            "short_financing_annual_rate": (PERSONAL_BASE_SLEEVE_SHORT_FINANCING_RATE),
            "short_financing_trace_digest": financing["trace_digest"],
            "source_session_count": len(ordered_session_dates),
            "source_session_dates_digest": source_session_dates_digest,
            "paper_artifact": evidence["paper_artifact"],
            "risk_artifact": evidence["risk_artifact"],
            "terminal_positions": "NOT_FORCE_LIQUIDATED_BY_SOURCE_RUN",
        },
        "return_semantics": BASE_RETURN_SEMANTICS,
        "base_nav_semantics": BASE_NAV_SEMANTICS,
        "source_slice_wrapper_cost_semantics": (SOURCE_SLICE_WRAPPER_COST_SEMANTICS),
        "wrapper_entry_cost_applied_to_source": False,
        "wrapper_liquidation_cost_applied_to_source": False,
        "daily_path": daily_path,
        "performance": dict(performance),
        "lifecycle": "DRAFT",
        "ready_snapshot_declared": False,
        "go": False,
        "automatic_promotion": False,
        "live_orders_enabled": False,
    }
    validate_personal_base_sleeve_artifact(document)
    return document


def validate_personal_base_sleeve_artifact(document: Any) -> None:
    """Reject a referenced artifact whose frozen role or execution drifted."""

    if not isinstance(document, Mapping):
        raise TypeError("base sleeve artifact must be an object")
    if document.get("schema_version") != PERSONAL_BASE_SLEEVE_ARTIFACT_SCHEMA:
        raise ValueError("base sleeve artifact schema mismatch")
    if (
        document.get("role") != PERSONAL_BASE_SLEEVE_ROLE
        or document.get("ranking_role") != PERSONAL_BASE_SLEEVE_RANKING_ROLE
        or document.get("candidate_count_contribution") != 0
    ):
        raise ValueError("base sleeve artifact candidate role drifted")
    strategy = document.get("strategy")
    cohort = document.get("cohort")
    universe = document.get("universe")
    source = document.get("source_run")
    if not all(
        isinstance(value, Mapping) for value in (strategy, cohort, universe, source)
    ):
        raise ValueError("base sleeve artifact provenance is incomplete")
    assert isinstance(strategy, Mapping)
    assert isinstance(cohort, Mapping)
    assert isinstance(universe, Mapping)
    assert isinstance(source, Mapping)
    if (
        strategy.get("strategy_id") != BASE_SLEEVE_ID
        or strategy.get("strategy_spec_digest") != EXPECTED_BASE_STRATEGY_SPEC_DIGEST
        or cohort.get("cohort_id") != BASE_COHORT_ID
        or cohort.get("cohort_digest") != EXPECTED_BASE_COHORT_DIGEST
        or universe.get("universe_id") != BASE_UNIVERSE_ID
    ):
        raise ValueError("base sleeve artifact frozen identity drifted")
    for value in (
        strategy.get("dependency_closure_digest"),
        universe.get("universe_rule_digest"),
        universe.get("resolved_membership_digest"),
        document.get("snapshot", {}).get("snapshot_id")
        if isinstance(document.get("snapshot"), Mapping)
        else None,
        document.get("snapshot", {}).get("logical_data_snapshot_id")
        if isinstance(document.get("snapshot"), Mapping)
        else None,
        source.get("short_financing_trace_digest"),
        source.get("source_session_dates_digest"),
    ):
        if not _sha256_digest(value):
            raise ValueError("base sleeve artifact contains an invalid digest")
    if (
        source.get("execution_mode") != "next_close"
        or not math.isclose(
            _finite_number(source.get("starting_capital")),
            PERSONAL_BASE_SLEEVE_STARTING_CAPITAL,
        )
        or not math.isclose(
            _finite_number(source.get("stock_one_way_cost_bps")),
            PERSONAL_BASE_SLEEVE_COST_BPS,
        )
        or not math.isclose(
            _finite_number(source.get("short_financing_annual_rate")),
            PERSONAL_BASE_SLEEVE_SHORT_FINANCING_RATE,
        )
        or source.get("terminal_positions") != "NOT_FORCE_LIQUIDATED_BY_SOURCE_RUN"
    ):
        raise ValueError("base sleeve artifact execution contract drifted")
    if (
        document.get("return_semantics") != BASE_RETURN_SEMANTICS
        or document.get("base_nav_semantics") != BASE_NAV_SEMANTICS
        or document.get("source_slice_wrapper_cost_semantics")
        != SOURCE_SLICE_WRAPPER_COST_SEMANTICS
        or document.get("wrapper_entry_cost_applied_to_source") is not False
        or document.get("wrapper_liquidation_cost_applied_to_source") is not False
    ):
        raise ValueError("base sleeve artifact NAV semantics drifted")
    if (
        document.get("lifecycle") != "DRAFT"
        or document.get("ready_snapshot_declared") is not False
        or document.get("go") is not False
        or document.get("automatic_promotion") is not False
        or document.get("live_orders_enabled") is not False
    ):
        raise ValueError("base sleeve artifact escaped DRAFT policy")
    if not _safe_archive_member(
        source.get("paper_artifact")
    ) or not _safe_archive_member(source.get("risk_artifact")):
        raise ValueError("base sleeve source evidence reference is unsafe")
    rows = document.get("daily_path")
    if not isinstance(rows, list) or not rows:
        raise ValueError("base sleeve artifact daily_path is empty")
    period = source.get("period")
    if not isinstance(period, Mapping):
        raise TypeError("base sleeve artifact source period is invalid")
    period_start = _canonical_day(period.get("start"))
    period_end = _canonical_day(period.get("end"))
    if period_end < period_start:
        raise ValueError("base sleeve artifact source period is reversed")
    source_session_count = source.get("source_session_count")
    if type(source_session_count) is not int or source_session_count != len(rows):
        raise ValueError("base sleeve artifact source session count is invalid")
    prior_day: str | None = None
    prior_equity = PERSONAL_BASE_SLEEVE_STARTING_CAPITAL
    for row in rows:
        if not isinstance(row, Mapping) or set(row) != {
            "date",
            "equity",
            "base_sleeve_return",
        }:
            raise ValueError("base sleeve artifact daily row is invalid")
        day = _canonical_day(row.get("date"))
        if day < period_start or day > period_end:
            raise ValueError("base sleeve artifact daily row is outside its period")
        if prior_day is not None and day <= prior_day:
            raise ValueError("base sleeve artifact dates are not increasing")
        equity = _finite_number(row.get("equity"))
        if equity <= 0.0:
            raise ValueError("base sleeve artifact equity is not positive")
        observed_return = _finite_number(row.get("base_sleeve_return"))
        expected_return = equity / prior_equity - 1.0
        if not math.isclose(
            observed_return,
            expected_return,
            rel_tol=1.0e-12,
            abs_tol=1.0e-12,
        ):
            raise ValueError("base sleeve artifact NAV and return are inconsistent")
        prior_day = day
        prior_equity = equity
    ordered_session_dates = tuple(str(row["date"]) for row in rows)
    if (
        ordered_session_dates[0] != period_start
        or ordered_session_dates[-1] != period_end
    ):
        raise ValueError("base sleeve artifact does not span its source period")
    if source.get("source_session_dates_digest") != canonical_trading_calendar_digest(
        ordered_session_dates
    ):
        raise ValueError("base sleeve artifact source session digest is invalid")


__all__ = [
    "BASE_COHORT_ID",
    "BASE_NAV_SEMANTICS",
    "BASE_RETURN_SEMANTICS",
    "BASE_SLEEVE_ID",
    "BASE_UNIVERSE_ID",
    "EXPECTED_BASE_COHORT_DIGEST",
    "EXPECTED_BASE_STRATEGY_SPEC_DIGEST",
    "PERSONAL_BASE_SLEEVE_ARTIFACT_SCHEMA",
    "PERSONAL_BASE_SLEEVE_COST_BPS",
    "PERSONAL_BASE_SLEEVE_RANKING_ROLE",
    "PERSONAL_BASE_SLEEVE_REFERENCE_SCHEMA",
    "PERSONAL_BASE_SLEEVE_ROLE",
    "PERSONAL_BASE_SLEEVE_SHORT_FINANCING_RATE",
    "SOURCE_SLICE_WRAPPER_COST_SEMANTICS",
    "build_personal_base_sleeve_artifact",
    "validate_personal_base_sleeve_artifact",
]
