"""Bounded personal DRAFT research over a compact-v7 snapshot.

The normal path is cloud: R2 is the snapshot authority, D1 is small job
state, and Container SQLite is ephemeral. Persistent local market, price, or
fundamental history is not a normal path; it remains exact opt-in
developer/recovery only (``QP_ALLOW_LOCAL_MARKET_DATA=1``).

This module is not Prime-limited. Default universe is PIT ``topix_all``;
Core30, Large70, Mid400, Small, TOPIX100, and TOPIX500 selectors are
PIT-resolved and intersected with financials at the execution decision cutoff.
Default AM cohorts use 11:30 information and same-day PM close.

Snapshot build is compact v7, one continuous object, at most 7000 inclusive
calendar days. Compressed R2/HTTP is <= 4 GiB; expanded SQLite/builder is
<= 5 GiB. One standard-4 Container shares one snapshot/quality prep and runs
up to four strategy child processes; a batch runs up to eight cohort/universe
jobs.

This module intentionally does not participate in the controlled-pilot or
mass-research authority chains. It evaluates a bounded set of closed
``StrategySpec`` values and emits DRAFT paper evidence for human review. It
cannot promote a strategy or place an order.
"""

from __future__ import annotations

import calendar
import hashlib
import itertools
import json
import math
import multiprocessing
import os
import sqlite3
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any
from urllib.parse import quote

import features
from agents.risk_agent import RiskAgent
from core.execution import close_as_of
from execution.personal_paper_service import PersonalPaperExecutionService
from paper_runtime.personal_snapshot import (
    PersonalSnapshot,
    materialize_personal_snapshot,
    verify_personal_snapshot,
)
from paper_runtime.personal_prepared_frame import _personal_prepared_frame_scope
from price_basis import PERSONAL_RETROSPECTIVE_ADJUSTED
from strategies.paper import Lifecycle, PaperRunConfig, PaperRunResult
from strategies.spec import StrategySpec, iter_feature_refs, strategy_spec_digest

from data_contracts.personal_history_compact import (
    PERSONAL_HISTORY_COMPACT_BARS_TABLE,
    compact_history_state,
)

from research.dependency_closure import (
    ContractDependency,
    PlanDependencyClosure,
    build_strategy_dependency_closure,
)
from research.factor_cohorts import (
    AM_SIGNAL_PM_CLOSE_EXECUTION_CONTRACT,
    AM_SIGNAL_PM_CLOSE_EXECUTION_MODE,
    COHORT_REGISTRY_VERSION,
    LEGACY_NEXT_CLOSE_EXECUTION_MODE,
    LEGACY_NEXT_CLOSE_LABEL,
    PERSONAL_EXECUTABLE_COHORT_IDS,
    PERSONAL_SHORT_FINANCING_AM_PM_COHORT_ID,
    PERSONAL_SHORT_FINANCING_COHORT_ID,
    ResearchCohort,
    execution_contract_for_cohort,
    get_research_cohort,
    is_personal_short_financing_cohort,
    personal_specs_for_cohort,
)
from research.personal_metrics import (
    performance_delta,
    summarize_performance,
    summarize_validation_performance,
)
from research.personal_universe import (
    DEFAULT_PERSONAL_UNIVERSE_ID,
    PERSONAL_UNIVERSE_IDS,
    PersonalResolvedUniverseMembership,
    PersonalUniverseError,
    PersonalUniverseSelector,
    personal_research_universe_decision_cutoff,
    personal_universe_selector,
    resolve_personal_universe_with_evidence,
)
from research.paper_candidate_specs import (
    build_cross_section_hold_strategy_spec,
    build_fundamentals_hold_strategy_spec,
    build_multi_day_hold_strategy_spec,
)
from research.personal_base_sleeve import (
    AM_PM_BASE_COHORT_ID as INDEX_VOL_AM_PM_BASE_COHORT_ID,
    AM_PM_BASE_SLEEVE_ID as INDEX_VOL_AM_PM_BASE_SLEEVE_ID,
    BASE_COHORT_ID as INDEX_VOL_BASE_COHORT_ID,
    BASE_SLEEVE_ID as INDEX_VOL_BASE_SLEEVE_ID,
    BASE_UNIVERSE_ID as INDEX_VOL_BASE_UNIVERSE_ID,
    PERSONAL_BASE_SLEEVE_COST_BPS,
    PERSONAL_BASE_SLEEVE_RANKING_ROLE,
    PERSONAL_BASE_SLEEVE_REFERENCE_SCHEMA,
    PERSONAL_BASE_SLEEVE_ROLE,
    PERSONAL_BASE_SLEEVE_SHORT_FINANCING_RATE,
    build_personal_base_sleeve_am_pm_artifact,
    build_personal_base_sleeve_artifact,
)
from research.stats_metrics import sharpe_ratio

PERSONAL_RESEARCH_REPORT_VERSION = "personal-research-report/v11"
PERSONAL_DECISION_POLICY = "personal_drawdown_cost_stress/v3"
PERSONAL_DATA_PROFILE = "personal-japan-equities-paper/v3"
PERSONAL_BAR_COVERAGE_EVIDENCE = "observed-pit-market-breadth/v1"
PERSONAL_SHORT_FINANCING_SCHEMA = "personal-short-financing-sensitivity/v1"
PERSONAL_SHORT_FINANCING_FORMULA_VERSION = "fixed-baseline-position-short-financing/v1"
PERSONAL_SHORT_FINANCING_TRACE_SCHEMA = "personal-short-notional-trace/v1"
PERSONAL_SHORT_FINANCING_ANNUAL_RATES = (0.0, 0.03, 0.10)
PERSONAL_SHORT_FINANCING_BASELINE_ANNUAL_RATE = 0.03
PERSONAL_SHORT_FINANCING_SESSIONS_PER_YEAR = 245
PERSONAL_EXACT_FOUR_MAX_BACKTESTS = 25
_CANDIDATE_PROCESS_RESULT_SCHEMA = "personal-candidate-process-result/v1"
_CANDIDATE_PROCESS_STOP_GRACE_SECONDS = 5.0
_TYPED_BAR_TABLES = ("jquants_daily_bars", "jquants_daily_bars_revisions")
_GENERIC_BAR_TABLES = ("jquants_records", "jquants_records_revisions")


class PersonalResearchInputError(ValueError):
    """Raised for an invalid local database, period, spec, or output request."""


@dataclass(frozen=True, slots=True)
class PersonalResearchPolicy:
    """The deliberately small default gate used by the local CLI."""

    validation_folds: int = 4
    min_fold_sessions: int = 180
    holdout_months: int = 12
    min_holdout_sessions: int = 180
    base_cost_bps: float = 10.0
    stress_cost_bps: float = 20.0
    min_positive_folds: int = 3
    min_validation_sharpe: float = 0.5
    max_drawdown: float = 0.25
    min_fills: int = 100
    max_candidates: int = 12
    max_parallel: int = 4
    min_observed_bar_coverage: float = 0.995
    min_universe_fins_breadth: float = 0.95

    def __post_init__(self) -> None:
        if self.validation_folds < 1:
            raise ValueError("validation_folds must be positive")
        if self.min_fold_sessions < 2 or self.min_holdout_sessions < 2:
            raise ValueError("research periods must contain at least two sessions")
        if self.holdout_months < 1:
            raise ValueError("holdout_months must be positive")
        if not 1 <= self.min_positive_folds <= self.validation_folds:
            raise ValueError("min_positive_folds must fit validation_folds")
        if not 0.0 < self.max_drawdown <= 1.0:
            raise ValueError("max_drawdown must be in (0, 1]")
        if self.min_fills < 0 or self.max_candidates < 1:
            raise ValueError("fill and candidate limits cannot be negative")
        if not 1 <= self.max_parallel <= 4:
            raise ValueError("personal research parallelism must be in [1, 4]")
        if not 0.0 < self.min_observed_bar_coverage <= 1.0:
            raise ValueError("min_observed_bar_coverage must be in (0, 1]")
        if not 0.0 < self.min_universe_fins_breadth <= 1.0:
            raise ValueError("min_universe_fins_breadth must be in (0, 1]")
        if self.base_cost_bps < 0 or self.stress_cost_bps < self.base_cost_bps:
            raise ValueError("stress cost must be no lower than base cost")

    def to_dict(self) -> dict[str, Any]:
        return {
            "policy": PERSONAL_DECISION_POLICY,
            "validation_folds": self.validation_folds,
            "min_fold_sessions": self.min_fold_sessions,
            "holdout_months": self.holdout_months,
            "min_holdout_sessions": self.min_holdout_sessions,
            "base_cost_bps": self.base_cost_bps,
            "stress_cost_bps": self.stress_cost_bps,
            "min_positive_folds": self.min_positive_folds,
            "min_validation_sharpe": self.min_validation_sharpe,
            "max_drawdown": self.max_drawdown,
            "min_fills": self.min_fills,
            "max_candidates": self.max_candidates,
            "max_parallel": self.max_parallel,
            "min_observed_bar_coverage": self.min_observed_bar_coverage,
            "min_universe_fins_breadth": self.min_universe_fins_breadth,
            "automatic_promotion": False,
        }


@dataclass(frozen=True, slots=True)
class PersonalResearchRequest:
    source_db: Path
    period_end: str
    output_root: Path
    period_start: str | None = None
    specs: tuple[StrategySpec, ...] | None = None
    cohort_id: str | None = None
    universe_id: str = DEFAULT_PERSONAL_UNIVERSE_ID


@dataclass(frozen=True, slots=True)
class PersonalResearchRun:
    report_id: str
    report_json_path: Path
    report_markdown_path: Path
    snapshot: PersonalSnapshot
    candidate_count: int
    evaluated_count: int
    hold_count: int
    unexpected_errors: int
    cohort_id: str | None = None
    cohort_digest: str | None = None
    universe_id: str = DEFAULT_PERSONAL_UNIVERSE_ID
    universe_rule_digest: str | None = None
    execution_mode: str = LEGACY_NEXT_CLOSE_EXECUTION_MODE
    execution_contract_digest: str | None = None
    base_sleeve_artifact_path: Path | None = None
    base_sleeve_artifact_digest: str | None = None
    base_sleeve_archive_member: str | None = None
    base_sleeve_artifact: dict[str, Any] | None = None
    non_candidate_source_backtest_count: int = 0

    @property
    def exit_code(self) -> int:
        if self.unexpected_errors:
            return 1
        return 0 if self.evaluated_count else 2


def default_personal_specs() -> tuple[StrategySpec, ...]:
    """Four modest, closed candidates; default does not imply an invariant."""
    return (
        build_multi_day_hold_strategy_spec(
            hold_days=10,
            momentum_feature_id="retrospective_split_adjusted_momentum_n",
            strategy_id="personal_momentum_topk_hold10",
        ),
        build_multi_day_hold_strategy_spec(
            hold_days=5,
            momentum_n=5,
            momentum_feature_id="retrospective_split_adjusted_momentum_n",
            strategy_id="personal_momentum_topk_hold5",
        ),
        build_cross_section_hold_strategy_spec(
            hold_days=10,
            allow_short=False,
            momentum_feature_id="retrospective_split_adjusted_momentum_n",
            strategy_id="personal_cross_section_momentum_hold10_long_only",
        ),
        build_fundamentals_hold_strategy_spec(
            hold_days=10,
            allow_short=False,
            momentum_feature_id="retrospective_split_adjusted_momentum_n",
            value_feature_id=(
                "retrospective_split_safe_fundamental_value_score"
            ),
            strategy_id="personal_value_momentum_hold10_long_only",
        ),
    )


_EVALUATION = ContractDependency(
    kind="evaluation",
    dependency_id="personal_walk_forward",
    version="personal-walk-forward/v1",
    dataset_dependencies=("equities_bars_daily", "markets_calendar"),
)
_RISK = ContractDependency(
    kind="risk",
    dependency_id="personal_drawdown",
    version="personal-drawdown/v1",
)
_COST = ContractDependency(
    kind="cost",
    dependency_id="personal_one_way_cost_stress",
    version="personal-one-way-cost-stress/v1",
)
_SHORT_COST = ContractDependency(
    kind="cost",
    dependency_id="personal_one_way_plus_modelled_short_financing",
    version="personal-one-way-plus-modelled-short-financing/v1",
)


def _short_financing_execution_timing(
    execution_contract: Mapping[str, Any] | None,
) -> str:
    if (
        isinstance(execution_contract, Mapping)
        and execution_contract.get("execution_mode")
        == AM_SIGNAL_PM_CLOSE_EXECUTION_MODE
    ):
        return "am_signal_pm_close_same_trading_date_fill"
    return "next_close_one_session_lag_no_lookahead"


def _short_financing_policy_document(
    *,
    execution_timing: str = "next_close_one_session_lag_no_lookahead",
) -> dict[str, Any]:
    return {
        "schema_version": PERSONAL_SHORT_FINANCING_SCHEMA,
        "formula_version": PERSONAL_SHORT_FINANCING_FORMULA_VERSION,
        "annual_rates": list(PERSONAL_SHORT_FINANCING_ANNUAL_RATES),
        "baseline_annual_rate": PERSONAL_SHORT_FINANCING_BASELINE_ANNUAL_RATE,
        "sessions_per_year": PERSONAL_SHORT_FINANCING_SESSIONS_PER_YEAR,
        "rate_source": "fixed_modelled_assumption",
        "borrow_evidence": False,
        "caller_tunable": False,
        "formula": "daily_cost = actual_short_notional * annual_rate / 245",
        "notional_basis": "actual_post_fill_end_of_session_short_market_value",
        "execution_timing": execution_timing,
        "sensitivity_method": (
            "fixed_3pct_baseline_position_trace_cash_counterfactual"
        ),
        "sensitivity_execution": "derived_non_executable",
        "accrual_convention": "post_fill_close_to_next_evaluation_session",
        "terminal_accrual_residual_risk": (
            "current_engine_includes_one_period_end_accrual_without_a_next_valuation"
        ),
        "transaction_cost": "one_way_fill_cost_charged_separately",
        "leverage_financing_enabled": False,
        "lifecycle": "DRAFT",
        "ready_snapshot_declared": False,
        "go": False,
        "automatic_promotion": False,
        "live_orders_enabled": False,
    }


def _canonical_bytes(value: Any) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")


def _digest(value: Any) -> str:
    return "sha256:" + hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _parse_day(value: str, label: str) -> date:
    try:
        parsed = date.fromisoformat(str(value))
    except (TypeError, ValueError) as exc:
        raise PersonalResearchInputError(f"{label} must be an ISO date") from exc
    if parsed.isoformat() != str(value):
        raise PersonalResearchInputError(f"{label} must be an ISO date")
    return parsed


def _subtract_months(day: date, months: int) -> date:
    month_index = day.year * 12 + day.month - 1 - months
    year, zero_month = divmod(month_index, 12)
    month = zero_month + 1
    return date(year, month, min(day.day, calendar.monthrange(year, month)[1]))


def _default_start(end: date) -> date:
    try:
        return end.replace(year=end.year - 5)
    except ValueError:
        return end.replace(year=end.year - 5, day=28)


def _calendar_lookback_days(required_trading_days: int) -> int:
    """Conservatively translate a session lookback for the calendar API."""
    sessions = int(required_trading_days)
    if sessions < 0:
        raise ValueError("required trading-day lookback cannot be negative")
    # Core currently accepts a calendar-day window.  Two calendar days per
    # required session plus a month covers weekends, exchange holidays, and
    # year-end closures without pretending the two units are interchangeable.
    return max(30, sessions * 2 + 30)


def _validated_specs(
    raw: Sequence[StrategySpec] | None,
    policy: PersonalResearchPolicy,
    cohort_id: str | None = None,
    universe_id: str | None = None,
) -> tuple[tuple[StrategySpec, ...], ResearchCohort | None]:
    if raw is not None and cohort_id is not None:
        raise PersonalResearchInputError(
            "cohort_id and explicit StrategySpec candidates are mutually exclusive"
        )
    cohort: ResearchCohort | None = None
    if cohort_id is not None:
        if type(cohort_id) is not str or cohort_id not in PERSONAL_EXECUTABLE_COHORT_IDS:
            raise PersonalResearchInputError(
                "cohort_id must be one of "
                f"{list(PERSONAL_EXECUTABLE_COHORT_IDS)}"
            )
        cohort = get_research_cohort(cohort_id)
        try:
            specs = tuple(
                personal_specs_for_cohort(cohort_id, universe_id=universe_id)
            )
        except ValueError as exc:  # defensive if registry eligibility drifts
            raise PersonalResearchInputError(str(exc)) from exc
    else:
        specs = tuple(default_personal_specs() if raw is None else raw)
    if not specs:
        raise PersonalResearchInputError("at least one StrategySpec is required")
    if len(specs) > policy.max_candidates:
        raise PersonalResearchInputError(
            f"candidate count exceeds {policy.max_candidates}"
        )
    if any(not isinstance(spec, StrategySpec) for spec in specs):
        raise PersonalResearchInputError("every candidate must be a StrategySpec")
    if cohort is None and any(
        bool(getattr(spec.rule, "allow_short", False)) for spec in specs
    ):
        raise PersonalResearchInputError(
            "personal short strategies require the closed "
            f"{PERSONAL_SHORT_FINANCING_COHORT_ID!r} or "
            f"{PERSONAL_SHORT_FINANCING_AM_PM_COHORT_ID!r} cohort"
        )
    identities = tuple((spec.strategy_id, spec.version) for spec in specs)
    if len(identities) != len(set(identities)):
        raise PersonalResearchInputError("candidate identities must be unique")
    for spec in specs:
        for ref in iter_feature_refs(spec):
            try:
                definition = features.get(ref.id, version=ref.version)
            except KeyError as exc:
                raise PersonalResearchInputError(
                    f"unknown exact feature {ref.id!r}@{ref.version!r}"
                ) from exc
            if definition.price_basis not in {
                None,
                PERSONAL_RETROSPECTIVE_ADJUSTED,
            }:
                raise PersonalResearchInputError(
                    "personal retrospective runs cannot mix a RAW or "
                    f"PIT-adjusted price feature: {ref.id!r}@{ref.version!r} "
                    f"declares {definition.price_basis!r}"
                )
    return specs, cohort


def _resolved_execution_contract(
    cohort: ResearchCohort | None,
    *,
    using_default_specs: bool,
) -> dict[str, Any]:
    if cohort is not None:
        return execution_contract_for_cohort(cohort)
    if using_default_specs:
        return dict(AM_SIGNAL_PM_CLOSE_EXECUTION_CONTRACT)
    return execution_contract_for_cohort(None)


def _requires_index_vol_base_sleeve(
    cohort: ResearchCohort | None,
    *,
    universe_id: str,
) -> bool:
    """Only the frozen TOPIX-all long/short run feeds the later overlay."""

    return bool(
        cohort is not None
        and universe_id == INDEX_VOL_BASE_UNIVERSE_ID
        and cohort.cohort_id
        in {INDEX_VOL_BASE_COHORT_ID, INDEX_VOL_AM_PM_BASE_COHORT_ID}
    )


def _closures(
    specs: Sequence[StrategySpec],
    *,
    start: str,
    end: str,
    policy: PersonalResearchPolicy,
    universe_selector: PersonalUniverseSelector,
    cohort_ref: dict[str, str] | None = None,
    execution_contract: Mapping[str, Any] | None = None,
) -> tuple[PlanDependencyClosure, ...]:
    universe_dependency = ContractDependency(
        kind="universe",
        dependency_id=universe_selector.rule_id,
        version=universe_selector.rule_version,
        dataset_dependencies=("equities_master", "fins_summary"),
    )
    closures: list[PlanDependencyClosure] = []
    for spec in specs:
        spec_hash = strategy_spec_digest(spec)
        uses_short = bool(getattr(spec.rule, "allow_short", False))
        plan_body = {
            "profile": PERSONAL_DATA_PROFILE,
            "strategy_spec": spec.to_dict(),
            "period_start": start,
            "period_end": end,
            "policy": policy.to_dict(),
            "universe": universe_selector.to_dict(),
        }
        if uses_short:
            plan_body["short_financing"] = _short_financing_policy_document(
                execution_timing=_short_financing_execution_timing(
                    execution_contract
                )
            )
        if cohort_ref is not None:
            plan_body["strategy_cohort"] = cohort_ref
        if (
            isinstance(execution_contract, Mapping)
            and execution_contract.get("execution_mode")
            == AM_SIGNAL_PM_CLOSE_EXECUTION_MODE
        ):
            plan_body["execution_contract"] = dict(execution_contract)
        closures.append(
            build_strategy_dependency_closure(
                plan_id=f"personal:{spec.strategy_id}:{spec_hash[7:19]}",
                plan_digest=_digest(plan_body),
                spec=spec,
                universe_dependencies=(universe_dependency,),
                evaluation_dependency=_EVALUATION,
                risk_dependency=_RISK,
                cost_dependency=_SHORT_COST if uses_short else _COST,
                research_data_profile_id=PERSONAL_DATA_PROFILE,
                period_start=start,
                period_end=end,
            )
        )
    return tuple(closures)


def _periods(
    universe: PersonalResolvedUniverseMembership,
    *,
    end: date,
    policy: PersonalResearchPolicy,
    warmup_sessions: int = 0,
) -> tuple[tuple[tuple[str, str], ...], tuple[str, str]] | None:
    if type(warmup_sessions) is not int or warmup_sessions < 0:
        raise ValueError("warmup_sessions must be a non-negative integer")
    sessions = tuple(
        day for day, _codes in universe.decision_memberships[warmup_sessions:]
    )
    boundary = _subtract_months(end, policy.holdout_months).isoformat()
    validation = tuple(day for day in sessions if day < boundary)
    holdout = tuple(day for day in sessions if day >= boundary)
    required_validation = policy.validation_folds * policy.min_fold_sessions
    if (
        len(validation) < required_validation
        or len(holdout) < policy.min_holdout_sessions
    ):
        return None
    quotient, remainder = divmod(len(validation), policy.validation_folds)
    folds: list[tuple[str, str]] = []
    cursor = 0
    for ordinal in range(policy.validation_folds):
        size = quotient + (1 if ordinal < remainder else 0)
        selected = validation[cursor : cursor + size]
        cursor += size
        if len(selected) < policy.min_fold_sessions:
            return None
        folds.append((selected[0], selected[-1]))
    return tuple(folds), (holdout[0], holdout[-1])


def _table_names(connection: sqlite3.Connection) -> set[str]:
    return {
        str(row[0])
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        )
    }


def _table_columns(connection: sqlite3.Connection, table: str) -> set[str]:
    if table not in _table_names(connection):
        return set()
    return {str(row[1]) for row in connection.execute(f"PRAGMA table_info({table})")}


def _compact_v7_bar_read_state(
    connection: sqlite3.Connection,
) -> tuple[str, str | None]:
    state = compact_history_state(connection)
    if state == "invalid":
        return "invalid", "compact_v7_marker_or_schema_invalid"
    if state == "mixed":
        return "mixed", "mixed_compact_and_typed_or_generic_bars"
    if state == "compact":
        return "compact", None
    return "legacy", None


def _observed_market_bar_coverage(
    db_path: Path,
    universe: PersonalResolvedUniverseMembership,
    *,
    minimum_ratio: float,
) -> dict[str, Any]:
    """Measure exact PIT-visible bar breadth without claiming source completeness.

    This is deliberately an observed-data guard, not a signed coverage system.
    It prevents a materially incomplete local file from silently turning
    missing issuers into apparent losers/winners while remaining practical for
    one person's SQLite workflow.
    """

    uri = "file:" + quote(str(Path(db_path).resolve()), safe="/") + "?mode=ro"
    connection = sqlite3.connect(uri, uri=True)
    try:
        tables = _table_names(connection)
        read_state, compact_reason = _compact_v7_bar_read_state(connection)
        if read_state in {"invalid", "mixed"}:
            return {
                "version": PERSONAL_BAR_COVERAGE_EVIDENCE,
                "evidence_kind": "OBSERVED",
                "status": "FAIL",
                "reason": compact_reason,
                "minimum_ratio": minimum_ratio,
                "source_complete_claim": False,
            }
        selects: list[str] = []
        if read_state == "compact":
            selects.append(
                "SELECT date AS day, code AS code "
                f"FROM {PERSONAL_HISTORY_COMPACT_BARS_TABLE} "
                "WHERE date BETWEEN ? AND ? "
                "AND available_at IS NOT NULL "
                "AND event_time IS NOT NULL "
                "AND available_at <= event_time"
            )
        else:
            for table in _TYPED_BAR_TABLES:
                if table in tables:
                    selects.append(
                        "SELECT date AS day, code AS code "
                        f"FROM {table} "
                        "WHERE source='jquants' AND date BETWEEN ? AND ? "
                        "AND available_at IS NOT NULL "
                        "AND event_time IS NOT NULL "
                        "AND available_at <= event_time"
                    )
            code_sql = (
                "COALESCE("
                "CASE WHEN json_valid(payload) "
                "THEN CAST(json_extract(payload, '$.Code') AS TEXT) END,"
                "CASE WHEN json_valid(raw_payload) "
                "THEN CAST(json_extract(raw_payload, '$.Code') AS TEXT) END)"
            )
            for table in _GENERIC_BAR_TABLES:
                if table in tables:
                    selects.append(
                        "SELECT substr(event_time, 1, 10) AS day, "
                        f"{code_sql} AS code FROM {table} "
                        "WHERE source='jquants' "
                        "AND dataset = 'equities_bars_daily' "
                        "AND substr(event_time, 1, 10) BETWEEN ? AND ? "
                        "AND available_at IS NOT NULL "
                        "AND event_time IS NOT NULL "
                        "AND available_at <= event_time"
                    )
        expected_by_day = dict(universe.decision_memberships)
        expected_total = sum(len(codes) for codes in expected_by_day.values())
        if not selects or expected_total == 0:
            return {
                "version": PERSONAL_BAR_COVERAGE_EVIDENCE,
                "evidence_kind": "OBSERVED",
                "status": "UNKNOWN",
                "reason": "bar_tables_or_expected_membership_missing",
                "minimum_ratio": minimum_ratio,
                "source_complete_claim": False,
            }
        params: list[str] = []
        for _ in selects:
            params.extend((universe.period_start, universe.period_end))
        union_sql = " UNION ALL ".join(selects)
        cursor = connection.execute(
            "SELECT day, code FROM (" + union_sql + ") "
            "WHERE day IS NOT NULL AND code IS NOT NULL "
            "GROUP BY day, code ORDER BY day, code",
            params,
        )
        observed_total = 0
        seen_days: set[str] = set()
        daily: list[dict[str, Any]] = []
        missing_sample: list[dict[str, str]] = []
        for day, rows in itertools.groupby(cursor, key=lambda row: str(row[0])):
            expected_codes = set(expected_by_day.get(day, ()))
            if not expected_codes:
                continue
            observed_codes = {
                str(row[1]) for row in rows if str(row[1]) in expected_codes
            }
            seen_days.add(day)
            observed = len(observed_codes)
            expected = len(expected_codes)
            observed_total += observed
            daily.append(
                {
                    "date": day,
                    "expected": expected,
                    "observed": observed,
                    "ratio": observed / expected,
                }
            )
            if len(missing_sample) < 20:
                missing_sample.extend(
                    {"date": day, "code": code}
                    for code in sorted(expected_codes - observed_codes)[
                        : 20 - len(missing_sample)
                    ]
                )
        for day, codes in universe.decision_memberships:
            if day in seen_days:
                continue
            daily.append(
                {"date": day, "expected": len(codes), "observed": 0, "ratio": 0.0}
            )
            if len(missing_sample) < 20:
                missing_sample.extend(
                    {"date": day, "code": code}
                    for code in codes[: 20 - len(missing_sample)]
                )
        overall_ratio = observed_total / expected_total
        minimum_daily_ratio = min(float(row["ratio"]) for row in daily)
        passed = (
            overall_ratio >= minimum_ratio
            and minimum_daily_ratio >= minimum_ratio
        )
        return {
            "version": PERSONAL_BAR_COVERAGE_EVIDENCE,
            "evidence_kind": "OBSERVED",
            "status": "PASS" if passed else "FAIL",
            "minimum_ratio": minimum_ratio,
            "overall_ratio": overall_ratio,
            "minimum_daily_ratio": minimum_daily_ratio,
            "expected_rows": expected_total,
            "observed_rows": observed_total,
            "missing_rows": expected_total - observed_total,
            "worst_days": sorted(
                daily, key=lambda row: (float(row["ratio"]), str(row["date"]))
            )[:10],
            "missing_sample": missing_sample,
            "source_complete_claim": False,
        }
    finally:
        connection.close()


def _source_sync_evidence(
    db_path: Path,
    snapshot_manifest: dict[str, Any],
    *,
    required_datasets: Sequence[str],
) -> dict[str, Any]:
    """Use lightweight sync controls when present; keep plain fixtures usable."""

    provenance = snapshot_manifest.get("source_policy_provenance")
    source_policy = dict(provenance) if isinstance(provenance, dict) else {}
    managed = bool(
        source_policy.get("table_present") and source_policy.get("row_present")
    )
    uri = "file:" + quote(str(Path(db_path).resolve()), safe="/") + "?mode=ro"
    connection = sqlite3.connect(uri, uri=True)
    connection.row_factory = sqlite3.Row
    try:
        tables = _table_names(connection)
        has_validation = "ingestion_validation" in tables
        has_watermarks = "ingestion_watermarks" in tables
        if not managed and not has_validation and not has_watermarks:
            return {
                "status": "PASS",
                "basis": "legacy_unmanaged_local_database",
                "source_publication_state": None,
                "required_datasets": list(required_datasets),
                "source_complete_claim": False,
            }
        if not has_validation or not has_watermarks:
            return {
                "status": "UNKNOWN",
                "basis": "managed_sync_controls_missing",
                "source_publication_state": source_policy.get("publication_state"),
                "required_datasets": list(required_datasets),
                "source_complete_claim": False,
            }
        validation_columns = _table_columns(connection, "ingestion_validation")
        watermark_columns = _table_columns(connection, "ingestion_watermarks")
        if not {"dataset", "status"} <= validation_columns or not {
            "dataset",
            "last_ingested_at",
        } <= watermark_columns:
            return {
                "status": "UNKNOWN",
                "basis": "managed_sync_controls_incompatible",
                "source_publication_state": source_policy.get("publication_state"),
                "required_datasets": list(required_datasets),
                "source_complete_claim": False,
            }
        order_column = "id" if "id" in validation_columns else "rowid"
        latest_rows = connection.execute(
            "SELECT v.dataset,v.status"
            + " FROM ingestion_validation v JOIN ("
            + f"SELECT dataset,MAX({order_column}) AS latest_id "
            + "FROM ingestion_validation GROUP BY dataset) latest "
            + f"ON latest.dataset=v.dataset AND latest.latest_id=v.{order_column}",
        ).fetchall()
        validation: dict[str, dict[str, Any]] = {}
        for row in latest_rows:
            dataset = str(row["dataset"] or "")
            validation[dataset] = {
                "status": str(row["status"] or "").lower(),
            }
        watermark_rows = connection.execute(
            "SELECT dataset,last_ingested_at FROM ingestion_watermarks"
        ).fetchall()
        watermarks = {
            str(row["dataset"]): str(row["last_ingested_at"] or "")
            for row in watermark_rows
        }
        failures: list[dict[str, Any]] = []
        for dataset in required_datasets:
            latest = validation.get(dataset)
            watermark = watermarks.get(dataset, "")
            if latest is None or latest["status"] != "pass":
                failures.append(
                    {
                        "dataset": dataset,
                        "reason": "latest_validation_not_pass",
                        "observed_status": None if latest is None else latest["status"],
                    }
                )
            if not watermark:
                failures.append(
                    {"dataset": dataset, "reason": "watermark_missing"}
                )
        return {
            "status": "FAIL" if failures else "PASS",
            "basis": "latest_local_validation_and_watermark",
            "source_publication_state": source_policy.get("publication_state"),
            "required_datasets": list(required_datasets),
            "failures": failures,
            "source_complete_claim": False,
        }
    finally:
        connection.close()


def _daily_returns_from_equity_curve(
    equity_curve: Sequence[Mapping[str, Any]], starting_capital: float
) -> list[float]:
    previous = float(starting_capital)
    values: list[float] = []
    for row in equity_curve:
        current = float(row["equity"])
        if previous <= 0.0 or current <= 0.0:
            raise RuntimeError("paper equity became non-positive")
        values.append(current / previous - 1.0)
        previous = current
    return values


def _daily_returns(result: PaperRunResult, starting_capital: float) -> list[float]:
    return _daily_returns_from_equity_curve(result.equity_curve, starting_capital)


def _short_financing_trace(
    result: PaperRunResult,
) -> tuple[list[dict[str, Any]], str]:
    """Canonical post-fill notional trace from the observed 3% run."""

    rows = sorted(
        (
            {
                "date": str(trade.get("fill_date") or ""),
                "short_notional": float(trade.get("short_notional") or 0.0),
            }
            for trade in result.trades
            if trade.get("side") == "short_financing"
        ),
        key=lambda row: row["date"],
    )
    if len(rows) != len({row["date"] for row in rows}) or any(
        not row["date"] or row["short_notional"] <= 0.0 for row in rows
    ):
        raise RuntimeError("invalid observed short-financing trace")
    expected_costs = {
        row["date"]: row["short_notional"]
        * PERSONAL_SHORT_FINANCING_BASELINE_ANNUAL_RATE
        / PERSONAL_SHORT_FINANCING_SESSIONS_PER_YEAR
        for row in rows
    }
    if any(
        not math.isclose(
            float(trade.get("cost") or 0.0),
            expected_costs[str(trade.get("fill_date") or "")],
            rel_tol=1e-10,
            abs_tol=1e-8,
        )
        for trade in result.trades
        if trade.get("side") == "short_financing"
    ):
        raise RuntimeError("observed 3% financing does not use the fixed divisor")
    trace = {
        "schema_version": PERSONAL_SHORT_FINANCING_TRACE_SCHEMA,
        "formula_version": PERSONAL_SHORT_FINANCING_FORMULA_VERSION,
        "baseline_run_id": result.run_id,
        "sessions_per_year": PERSONAL_SHORT_FINANCING_SESSIONS_PER_YEAR,
        "rows": rows,
    }
    return rows, _digest(trace)


def _fixed_position_short_financing_evidence(
    result: PaperRunResult,
    *,
    period: tuple[str, str],
    starting_capital: float,
    annual_rate: float,
) -> tuple[dict[str, Any], list[float], list[str]]:
    """Reprice financing on one observed 3% position path without re-execution."""

    rate = float(annual_rate)
    if rate not in PERSONAL_SHORT_FINANCING_ANNUAL_RATES:
        raise ValueError("short financing rate is outside the fixed sensitivity")
    trace_rows, trace_digest = _short_financing_trace(result)
    short_by_date = {row["date"]: row["short_notional"] for row in trace_rows}
    cumulative_delta = 0.0
    adjusted_curve: list[dict[str, Any]] = []
    for source_row in result.equity_curve:
        row = dict(source_row)
        day = str(row.get("date") or "")
        if day in short_by_date:
            cumulative_delta += (
                short_by_date[day]
                * (rate - PERSONAL_SHORT_FINANCING_BASELINE_ANNUAL_RATE)
                / PERSONAL_SHORT_FINANCING_SESSIONS_PER_YEAR
            )
        row["equity"] = float(row["equity"]) - cumulative_delta
        adjusted_curve.append(row)
    if set(short_by_date) - {str(row.get("date") or "") for row in adjusted_curve}:
        raise RuntimeError(
            "short financing trace contains a date outside the equity path"
        )

    adjusted_trades = [dict(trade) for trade in result.trades]
    for trade in adjusted_trades:
        if trade.get("side") == "short_financing":
            trade["cost"] = (
                float(trade["short_notional"])
                * rate
                / PERSONAL_SHORT_FINANCING_SESSIONS_PER_YEAR
            )
    returns = _daily_returns_from_equity_curve(adjusted_curve, starting_capital)
    performance = summarize_performance(
        equity_curve=adjusted_curve,
        trades=adjusted_trades,
        starting_capital=starting_capital,
    )
    dates = [str(row.get("date") or "") for row in adjusted_curve]
    body: dict[str, Any] = {
        "schema_version": PERSONAL_SHORT_FINANCING_SCHEMA,
        "formula_version": PERSONAL_SHORT_FINANCING_FORMULA_VERSION,
        "baseline_run_id": result.run_id,
        "trace_digest": trace_digest,
        "annual_rate": rate,
        "sessions_per_year": PERSONAL_SHORT_FINANCING_SESSIONS_PER_YEAR,
        "position_trace": "fixed_to_observed_3pct_baseline",
        "execution": "derived_non_executable",
        "lifecycle": "DRAFT",
        "derived_artifacts_emitted": False,
        "period": {"start": period[0], "end": period[1]},
        "fills": performance["fill_count"],
        "short_financing_cost_amount": sum(
            row["short_notional"] * rate
            / PERSONAL_SHORT_FINANCING_SESSIONS_PER_YEAR
            for row in trace_rows
        ),
        "charged_sessions": len(trace_rows),
        "performance": performance,
    }
    return (
        {**body, "evidence_digest": _digest(body)},
        returns,
        dates,
    )


def _risk_document(result: PaperRunResult, limit: float) -> dict[str, Any]:
    audit = RiskAgent(max_drawdown_limit=limit).audit(result)
    return {
        "audit_id": audit.audit_id,
        "experiment_id": audit.experiment_id,
        "run_id": audit.run_id,
        "status": audit.status,
        "checks": dict(audit.checks),
        "findings": list(audit.findings),
        "metrics": dict(audit.metrics),
    }


def _write_artifact(root: Path, category: str, suffix: str, content: bytes) -> str:
    digest = hashlib.sha256(content).hexdigest()
    directory = root / category
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{digest}.{suffix}"
    try:
        with path.open("xb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        path.chmod(0o444)
    except FileExistsError:
        if path.read_bytes() != content:
            raise RuntimeError(f"content-address collision for {path.name}")
    return path.relative_to(root).as_posix()


def _portable_paper_document(result: PaperRunResult) -> dict[str, Any]:
    """Remove the physical checkout path from content-addressed evidence."""

    document = result.to_dict()
    reproduction = document.get("reproducibility")
    if isinstance(reproduction, dict):
        reproduction.pop("db_path", None)
        reproduction["db_locator"] = "logical_data_snapshot_id"
    backtest = document.get("backtest")
    if isinstance(backtest, dict) and isinstance(backtest.get("metadata"), dict):
        backtest["metadata"].pop("db_path", None)
        backtest["metadata"]["db_locator"] = "logical_data_snapshot_id"
    return document


_FACTOR_ECONOMICS: dict[str, tuple[str, str, str]] = {
    "return_ratio": (
        "sector-relative medium-term price continuation",
        "leadership diffuses gradually and sector-internal trends persist",
        "crowded momentum unwinds or leadership reverses abruptly",
    ),
    "short_long_momentum": (
        "acceleration of recent returns relative to the medium horizon",
        "new information creates a persistent acceleration in leadership",
        "prices oscillate and the short horizon repeatedly whipsaws",
    ),
    "realized_vol_ratio": (
        "the defensive premium associated with contracting relative volatility",
        "stable low-risk names retain leadership as volatility normalizes",
        "crisis rebounds reward the highest-risk names or volatility jumps suddenly",
    ),
    "turnover_ratio": (
        "price continuation confirmed by expanding trading participation",
        "turnover broadens behind a durable price move",
        "one-off events or mechanical flows create volume without continuation",
    ),
    "market_cap": (
        "the within-sector small-company size premium",
        "market breadth is healthy and smaller firms can re-rate without a liquidity shock",
        "returns concentrate in mega-caps or illiquidity and trading costs dominate",
    ),
    "book_to_price": (
        "sector-relative value re-rating from a low price-to-book valuation",
        "valuation dispersion mean-reverts and balance-sheet assets remain informative",
        "cheap firms are value traps or intangible-heavy sectors make book value misleading",
    ),
    "earnings_to_price": (
        "sector-relative earnings-yield re-rating",
        "reported earnings are sustainable and valuation dispersion narrows",
        "cyclical peak earnings or accounting transients make the yield look artificially cheap",
    ),
    "roe": (
        "persistent profitability and capital-allocation quality",
        "high returns on equity persist without excessive leverage",
        "ROE is leverage-driven or profitability mean-reverts sharply",
    ),
    "asset_turnover": (
        "operating efficiency relative to sector peers",
        "efficient asset use translates into durable margins and cash generation",
        "asset-light accounting differences or a capex transition break comparability",
    ),
    "sales_growth": (
        "persistent sector-relative revenue growth",
        "revenue growth carries through to future earnings rather than being fully priced",
        "growth mean-reverts, is acquisition-driven, or valuation compression dominates",
    ),
    "net_margin": (
        "durable operating profitability",
        "pricing power and cost discipline persist",
        "margins are at a cyclical peak or competition forces normalization",
    ),
    "equity_ratio": (
        "balance-sheet resilience and lower financial distress risk",
        "funding conditions tighten or resilient firms compound steadily",
        "leverage is rewarded in a rapid risk-on rebound",
    ),
    "assets_growth": (
        "the conservative-investment premium from avoiding aggressive asset expansion",
        "disciplined investment outperforms empire building",
        "a productive capex cycle rewards rapid asset growth",
    ),
}


def _joined_unique(values: Sequence[str]) -> str:
    return "; ".join(dict.fromkeys(value for value in values if value))


def _strategy_context(
    spec: StrategySpec,
    *,
    execution_contract: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Portable mechanics plus the declared return thesis for comparison."""

    rule = spec.rule.to_dict()
    rule_type = str(rule.get("type") or "unknown")
    rebalance = (
        "daily"
        if spec.rebalance == "daily"
        else f"every {spec.hold_days} sessions"
    )
    return_sources: list[str] = []
    works_when: list[str] = []
    fails_when: list[str] = []
    if rule_type == "factor_rank":
        leg_labels: list[str] = []
        for leg in rule.get("legs", []):
            feature = leg.get("feature", {})
            params = feature.get("params", {})
            label = str(params.get("mode") or feature.get("id") or "feature")
            weight = float(leg.get("weight", 0.0))
            direction = str(leg.get("direction") or "")
            leg_labels.append(f"{label} {weight:.0%} {direction}")
            economics = _FACTOR_ECONOMICS.get(label)
            if economics is not None:
                return_sources.append(economics[0])
                works_when.append(economics[1])
                fails_when.append(economics[2])
        exposure = (
            f"long top {float(rule['long_frac']):.0%} / "
            f"short bottom {float(rule['short_frac']):.0%}"
            if rule.get("allow_short")
            else f"long top {float(rule['long_frac']):.0%}"
        )
        summary = (
            f"{rebalance}; percentile rank within {rule['group']}; "
            f"{exposure}; " + ", ".join(leg_labels)
        )
        short_financing = (
            _short_financing_policy_document(
                execution_timing=_short_financing_execution_timing(
                    execution_contract
                )
            )
            if rule.get("allow_short")
            else None
        )
        if short_financing is not None:
            summary += (
                "; fixed modelled short-financing sensitivity at 0%, "
                "3% baseline, and 10% annual on actual short notional"
            )
    else:
        exposure = "long/short" if rule.get("allow_short") else "long-only"
        summary = f"{rebalance}; {rule_type}; {exposure}"
        short_financing = None
        return_sources.append(spec.rationale)
        works_when.append("the declared signal remains predictive after execution costs")
        fails_when.append("the signal decays, reverses, or is overwhelmed by trading costs")
    return {
        "thesis": spec.rationale,
        "return_source": _joined_unique(return_sources) or spec.rationale,
        "works_when": _joined_unique(works_when),
        "fails_when": _joined_unique(fails_when),
        "mechanics_summary": summary,
        "mechanics": {
            "rule": rule,
            "rebalance": spec.rebalance,
            "hold_days": spec.hold_days,
        },
        "short_financing": short_financing,
    }


def _candidate_evidence_assessment(candidate: Mapping[str, Any]) -> str:
    decision = str(candidate.get("decision") or "UNKNOWN")
    reasons = [str(value) for value in candidate.get("reasons", [])]
    validation = candidate.get("validation")
    if not isinstance(validation, Mapping):
        detail = ", ".join(reasons) or "evaluation evidence unavailable"
        return f"NOT EVALUATED: {detail}. No promotion or trading authority."
    if decision == "HOLD":
        return (
            "HOLD: validation and fixed cost-stress gates passed; the recent "
            "holdout is descriptive only. Human review remains required and this "
            "does not authorize promotion or trading."
        )
    failed = ", ".join(reasons) or "one or more fixed gates failed"
    return f"REJECT: {failed}. The observed evidence does not support promotion."


def _universe_corporate_action_check(
    db_path: Path,
    *,
    universe: PersonalResolvedUniverseMembership,
    lookback_days: int,
) -> dict[str, Any]:
    """Classify handled split boundaries and advisory adjusted-price moves.

    Vendor factor boundaries are expected under the explicitly retrospective
    DRAFT basis and therefore are evidence, not automatic rejection. A large
    move that remains in adjusted prices is not proof of a corporate action:
    it can be a genuine market move. Preserve it as a review warning without
    rejecting a candidate. Missing adjusted evidence remains fail-closed in
    the adjusted-price execution path.
    """

    expected_codes = {
        code
        for _day, codes in universe.decision_memberships
        for code in codes
    }
    if not expected_codes:
        return {
            "status": "UNKNOWN",
            "price_basis": PERSONAL_RETROSPECTIVE_ADJUSTED,
            "reason": "resolved_universe_empty",
            "checked_codes": 0,
            "affected_codes": [],
            "suspicious_jump_codes": [],
            "supported_factor_events": [],
            "extreme_price_move_events": [],
        }
    start = (
        date.fromisoformat(universe.period_start) - timedelta(days=lookback_days)
    ).isoformat()
    end = universe.period_end
    end_as_of = close_as_of(end)
    uri = "file:" + quote(str(Path(db_path).resolve()), safe="/") + "?mode=ro"
    connection = sqlite3.connect(uri, uri=True)
    try:
        tables = _table_names(connection)
        read_state, compact_reason = _compact_v7_bar_read_state(connection)
        if read_state in {"invalid", "mixed"}:
            return {
                "status": "FAIL",
                "price_basis": PERSONAL_RETROSPECTIVE_ADJUSTED,
                "reason": compact_reason,
                "checked_codes": 0,
                "affected_codes": [],
                "suspicious_jump_codes": [],
                "supported_factor_events": [],
                "extreme_price_move_events": [],
            }
        selects: list[str] = []
        if read_state == "compact":
            selects.append(
                "SELECT code,date AS day,close AS raw_close,"
                "adjustment_close AS adjusted_close,volume AS raw_volume,"
                "adjustment_volume AS adjusted_volume,available_at,ingested_at "
                f"FROM {PERSONAL_HISTORY_COMPACT_BARS_TABLE} "
                "WHERE date BETWEEN ? AND ? "
                "AND available_at <= ?"
            )
        else:
            for table in _TYPED_BAR_TABLES:
                if table in tables:
                    selects.append(
                        "SELECT code,date AS day,close AS raw_close,"
                        "adjustment_close AS adjusted_close,volume AS raw_volume,"
                        "adjustment_volume AS adjusted_volume,available_at,ingested_at "
                        f"FROM {table} "
                        "WHERE source='jquants' AND date BETWEEN ? AND ? "
                        "AND available_at <= ?"
                    )
            code_sql = (
                "COALESCE("
                "CASE WHEN json_valid(payload) "
                "THEN CAST(json_extract(payload, '$.Code') AS TEXT) END,"
                "CASE WHEN json_valid(raw_payload) "
                "THEN CAST(json_extract(raw_payload, '$.Code') AS TEXT) END)"
            )
            raw_close_sql = (
                "COALESCE("
                "CASE WHEN json_valid(payload) "
                "THEN json_extract(payload, '$.Close') END,"
                "CASE WHEN json_valid(raw_payload) "
                "THEN json_extract(raw_payload, '$.Close') END)"
            )
            adjusted_close_sql = (
                "COALESCE("
                "CASE WHEN json_valid(payload) THEN COALESCE("
                "json_extract(payload, '$.AdjustmentClose'),"
                "json_extract(payload, '$.AdjClose'),"
                "json_extract(payload, '$.AdjC')) END,"
                "CASE WHEN json_valid(raw_payload) THEN COALESCE("
                "json_extract(raw_payload, '$.AdjustmentClose'),"
                "json_extract(raw_payload, '$.AdjClose'),"
                "json_extract(raw_payload, '$.AdjC')) END)"
            )
            raw_volume_sql = (
                "COALESCE("
                "CASE WHEN json_valid(payload) "
                "THEN json_extract(payload, '$.Volume') END,"
                "CASE WHEN json_valid(raw_payload) "
                "THEN json_extract(raw_payload, '$.Volume') END)"
            )
            adjusted_volume_sql = (
                "COALESCE("
                "CASE WHEN json_valid(payload) THEN COALESCE("
                "json_extract(payload, '$.AdjustmentVolume'),"
                "json_extract(payload, '$.AdjVolume'),"
                "json_extract(payload, '$.AdjVo')) END,"
                "CASE WHEN json_valid(raw_payload) THEN COALESCE("
                "json_extract(raw_payload, '$.AdjustmentVolume'),"
                "json_extract(raw_payload, '$.AdjVolume'),"
                "json_extract(raw_payload, '$.AdjVo')) END)"
            )
            for table in _GENERIC_BAR_TABLES:
                if table in tables:
                    selects.append(
                        f"SELECT {code_sql} AS code,substr(event_time,1,10) AS day,"
                        f"{raw_close_sql} AS raw_close,"
                        f"{adjusted_close_sql} AS adjusted_close,"
                        f"{raw_volume_sql} AS raw_volume,"
                        f"{adjusted_volume_sql} AS adjusted_volume,"
                        "available_at,ingested_at "
                        f"FROM {table} "
                        "WHERE source='jquants' AND dataset='equities_bars_daily' "
                        "AND substr(event_time,1,10) BETWEEN ? AND ? "
                        "AND available_at <= ?"
                    )
        if not selects:
            return {
                "status": "UNKNOWN",
                "price_basis": PERSONAL_RETROSPECTIVE_ADJUSTED,
                "reason": "bar_tables_missing",
                "checked_codes": 0,
                "affected_codes": [],
                "suspicious_jump_codes": [],
                "supported_factor_events": [],
                "extreme_price_move_events": [],
            }
        params: list[str] = []
        for _ in selects:
            params.extend((start, end, end_as_of))
        cursor = connection.execute(
            "SELECT code,day,raw_close,adjusted_close,raw_volume,adjusted_volume,"
            "available_at,ingested_at FROM ("
            + " UNION ALL ".join(selects)
            + ") WHERE code IS NOT NULL AND day IS NOT NULL "
            "ORDER BY code,day,available_at,ingested_at",
            params,
        )
        supported_events: list[dict[str, Any]] = []
        extreme_price_move_events: list[dict[str, Any]] = []
        observed_codes: set[str] = set()
        missing_adjusted_codes: set[str] = set()
        adjusted_observations = 0
        observations = 0
        previous: dict[str, tuple[str, float, float, float | None]] = {}
        for (code, _day), rows in itertools.groupby(
            cursor, key=lambda row: (str(row[0]), str(row[1]))
        ):
            if code not in expected_codes:
                continue
            versions = list(rows)
            latest_marker = max(
                (str(row[6] or ""), str(row[7] or "")) for row in versions
            )
            pairs = [
                (row[2], row[3], row[4], row[5])
                for row in versions
                if row[2] is not None
                and (str(row[6] or ""), str(row[7] or "")) == latest_marker
            ]
            if not pairs:
                continue
            observed_codes.add(code)
            observations += 1
            raw_value = float(pairs[-1][0])
            adjusted_value = pairs[-1][1]
            if adjusted_value is None or raw_value <= 0.0:
                missing_adjusted_codes.add(code)
                continue
            adjusted = float(adjusted_value)
            if adjusted <= 0.0:
                missing_adjusted_codes.add(code)
                continue
            adjusted_observations += 1
            price_ratio = adjusted / raw_value
            raw_volume = pairs[-1][2]
            adjusted_volume = pairs[-1][3]
            volume_ratio: float | None = None
            if (
                raw_volume is not None
                and float(raw_volume) != 0.0
                and adjusted_volume is not None
            ):
                volume_ratio = float(adjusted_volume) / float(raw_volume)
            prior = previous.get(code)
            if prior is not None:
                prior_day, prior_adjusted, prior_price_ratio, prior_volume_ratio = prior
                price_factor_changed = (
                    prior_price_ratio != 0.0
                    and abs(price_ratio / prior_price_ratio - 1.0) > 0.01
                )
                volume_factor_changed = (
                    volume_ratio is not None
                    and prior_volume_ratio is not None
                    and prior_volume_ratio != 0.0
                    and abs(volume_ratio / prior_volume_ratio - 1.0) > 0.01
                )
                if price_factor_changed or volume_factor_changed:
                    supported_events.append(
                        {
                            "code": code,
                            "date": _day,
                            "previous_date": prior_day,
                            "price_ratio_changed": price_factor_changed,
                            "volume_ratio_changed": volume_factor_changed,
                        }
                    )
                adjusted_return = adjusted / prior_adjusted - 1.0
                if abs(adjusted_return) > 0.35:
                    extreme_price_move_events.append(
                        {
                            "code": code,
                            "date": _day,
                            "previous_date": prior_day,
                            "adjusted_close_return": adjusted_return,
                            "classification": "advisory_market_or_data_move",
                        }
                    )
            previous[code] = (_day, adjusted, price_ratio, volume_ratio)
    finally:
        connection.close()
    missing_codes = sorted(expected_codes - observed_codes)
    supported_codes = sorted({event["code"] for event in supported_events})
    extreme_move_codes = sorted(
        {event["code"] for event in extreme_price_move_events}
    )
    warned = bool(
        extreme_price_move_events or missing_codes or missing_adjusted_codes
    )
    adjustment_ratio = (
        adjusted_observations / observations if observations else 0.0
    )
    return {
        "status": "WARN" if warned else "PASS",
        "price_basis": PERSONAL_RETROSPECTIVE_ADJUSTED,
        "reason": (
            "extreme_adjusted_price_move_or_missing_evidence"
            if warned
            else "supported_factor_events_handled_by_retrospective_basis"
        ),
        "checked_codes": len(expected_codes),
        "lookback_start": start,
        "period_end": end,
        "adjustment_observation_ratio": adjustment_ratio,
        "affected_codes": supported_codes,
        "suspicious_jump_codes": extreme_move_codes,
        "risk_codes": [],
        "supported_factor_events": supported_events,
        "extreme_price_move_events": extreme_price_move_events,
        "missing_codes": missing_codes,
        "missing_adjusted_codes": sorted(missing_adjusted_codes),
        "adjusted_jump_threshold": 0.35,
        "adjustment_factor_change_threshold": 0.01,
        "handling": (
            "supported_factor_events_are_handled; extreme_adjusted_price_"
            "moves_are_review_advisories_not_corporate_action_proof"
        ),
        "future_event_policy": "never_reject_an_earlier_fold",
        "unfilled_rank_bias_possible": True,
        "source_complete_claim": False,
    }


def _paper_evidence(
    result: PaperRunResult,
    *,
    config: PaperRunConfig,
    output_root: Path,
    max_drawdown: float,
    short_financing_annual_rate: float | None = None,
    execution_contract: Mapping[str, Any] | None = None,
) -> tuple[dict[str, Any], list[float], list[str]]:
    paper_path = _write_artifact(
        output_root, "paper", "json", _canonical_bytes(_portable_paper_document(result))
    )
    risk = _risk_document(result, max_drawdown)
    risk_path = _write_artifact(
        output_root, "risk", "json", _canonical_bytes(risk)
    )
    returns = _daily_returns(result, config.starting_capital)
    sharpe = sharpe_ratio(returns, periods_per_year=252.0).get("sharpe")
    metrics = result.metrics
    short_trace_digest = (
        None
        if short_financing_annual_rate is None
        else _short_financing_trace(result)[1]
    )
    performance = summarize_performance(
        equity_curve=result.equity_curve,
        trades=result.trades,
        starting_capital=config.starting_capital,
    )
    return (
        {
            "run_id": result.run_id,
            "experiment_id": result.experiment_id,
            "period": {"start": config.start, "end": config.end},
            "cost_bps": config.cost_bps,
            "execution_mode": config.execution_mode,
            "execution_contract": (
                None if execution_contract is None else dict(execution_contract)
            ),
            "total_return_post_cost": float(
                metrics.get("total_return_post_cost", 0.0)
            ),
            "annualized_sharpe": None if sharpe is None else float(sharpe),
            "sharpe_periods_per_year": 252,
            "max_drawdown": abs(float(metrics.get("max_drawdown", 0.0))),
            "fills": int(metrics.get("num_trades", len(result.trades))),
            "risk_status": risk["status"],
            "performance": performance,
            "short_financing": (
                None
                if short_financing_annual_rate is None
                else {
                    "schema_version": PERSONAL_SHORT_FINANCING_SCHEMA,
                    "formula_version": PERSONAL_SHORT_FINANCING_FORMULA_VERSION,
                    "annual_rate": short_financing_annual_rate,
                    "sessions_per_year": (
                        PERSONAL_SHORT_FINANCING_SESSIONS_PER_YEAR
                    ),
                    "baseline": short_financing_annual_rate
                    == PERSONAL_SHORT_FINANCING_BASELINE_ANNUAL_RATE,
                    "modelled_assumption": True,
                    "borrow_evidence": False,
                    "cost_amount": float(
                        metrics.get("short_financing_cost", 0.0)
                    ),
                    "charged_sessions": int(
                        metrics.get("n_short_financing_days", 0)
                    ),
                    "gap_sessions": int(
                        metrics.get("n_short_financing_gaps", 0)
                    ),
                    "trace_digest": short_trace_digest,
                    "notional_basis": (
                        "actual_post_fill_end_of_session_short_market_value"
                    ),
                }
            ),
            "paper_artifact": paper_path,
            "risk_artifact": risk_path,
        },
        returns,
        [str(row.get("date") or "") for row in result.equity_curve],
    )


def _run_one(
    executor: PersonalPaperExecutionService,
    spec: StrategySpec,
    *,
    db_path: Path,
    snapshot_id: str,
    universe: PersonalResolvedUniverseMembership,
    period: tuple[str, str],
    cost_bps: float,
    lookback_days: int,
    output_root: Path,
    max_drawdown: float,
    short_financing_annual_rate: float | None = None,
    execution_mode: str = LEGACY_NEXT_CLOSE_EXECUTION_MODE,
    execution_contract: Mapping[str, Any] | None = None,
) -> tuple[dict[str, Any], list[float], list[str], PaperRunResult]:
    if (
        short_financing_annual_rate is not None
        and short_financing_annual_rate
        != PERSONAL_SHORT_FINANCING_BASELINE_ANNUAL_RATE
    ):
        raise ValueError("only the fixed 3% baseline may execute a paper run")
    period_universe = PersonalResolvedUniverseMembership(
        period_start=period[0],
        period_end=period[1],
        decision_memberships=tuple(
            (day, codes)
            for day, codes in universe.decision_memberships
            if period[0] <= day <= period[1]
        ),
        rule_id=universe.rule_id,
        rule_version=universe.rule_version,
        rule_digest=universe.rule_digest,
    )
    config = PaperRunConfig(
        start=period[0],
        end=period[1],
        db_path=db_path,
        universe=period_universe,
        execution_mode=execution_mode,
        cost_bps=cost_bps,
        starting_capital=1_000_000.0,
        lookback_days=_calendar_lookback_days(lookback_days),
        lifecycle=Lifecycle.DRAFT,
        price_basis=PERSONAL_RETROSPECTIVE_ADJUSTED,
        short_financing_enabled=short_financing_annual_rate is not None,
        short_financing_spread_bp=(
            None
            if short_financing_annual_rate is None
            else short_financing_annual_rate * 10_000.0
        ),
        short_financing_fallback_repo_annual_bp=0.0,
        short_financing_auto_load_repo=False,
        leverage_financing_enabled=False,
    )
    result = executor.execute(
        spec,
        config,
        expected_snapshot_id=snapshot_id,
        approved_feature_refs=iter_feature_refs(spec),
    )
    evidence, returns, dates = _paper_evidence(
        result,
        config=config,
        output_root=output_root,
        max_drawdown=max_drawdown,
        short_financing_annual_rate=short_financing_annual_rate,
        execution_contract=execution_contract,
    )
    return evidence, returns, dates, result


def _write_continuous_base_sleeve_artifact(
    executor: PersonalPaperExecutionService,
    spec: StrategySpec,
    closure: PlanDependencyClosure,
    *,
    snapshot: PersonalSnapshot,
    universe: PersonalResolvedUniverseMembership,
    source_period: tuple[str, str],
    output_root: Path,
    cohort_digest: str,
    execution_mode: str = LEGACY_NEXT_CLOSE_EXECUTION_MODE,
    execution_contract: Mapping[str, Any] | None = None,
) -> tuple[dict[str, Any], Path, str]:
    """Execute one full-period base sleeve outside candidate selection."""

    am_sleeve = (
        execution_mode == AM_SIGNAL_PM_CLOSE_EXECUTION_MODE
        or spec.strategy_id == INDEX_VOL_AM_PM_BASE_SLEEVE_ID
    )
    evidence, _returns, _dates, paper_result = _run_one(
        executor,
        spec,
        db_path=snapshot.db_path,
        snapshot_id=snapshot.logical_data_snapshot_id,
        universe=universe,
        period=source_period,
        cost_bps=PERSONAL_BASE_SLEEVE_COST_BPS,
        lookback_days=closure.required_lookback_trading_days,
        output_root=output_root,
        max_drawdown=1.0,
        short_financing_annual_rate=(
            PERSONAL_BASE_SLEEVE_SHORT_FINANCING_RATE
        ),
        execution_mode=(
            AM_SIGNAL_PM_CLOSE_EXECUTION_MODE
            if am_sleeve
            else LEGACY_NEXT_CLOSE_EXECUTION_MODE
        ),
        execution_contract=execution_contract,
    )
    paper_membership_digest = paper_result.reproducibility.get(
        "resolved_universe_digest"
    )
    if not isinstance(paper_membership_digest, str):
        raise RuntimeError("base sleeve paper membership digest is absent")
    builder = (
        build_personal_base_sleeve_am_pm_artifact
        if am_sleeve
        else build_personal_base_sleeve_artifact
    )
    document = builder(
        result=paper_result,
        evidence=evidence,
        spec=spec,
        dependency_closure_digest=closure.closure_digest,
        cohort_digest=cohort_digest,
        universe_id=INDEX_VOL_BASE_UNIVERSE_ID,
        universe_rule_digest=universe.rule_digest,
        resolved_membership_digest=paper_membership_digest,
        snapshot_id=snapshot.snapshot_id,
        logical_data_snapshot_id=snapshot.logical_data_snapshot_id,
        source_period=source_period,
        source_session_dates=tuple(
            day
            for day, _codes in universe.decision_memberships
            if source_period[0] <= day <= source_period[1]
        ),
    )
    archive_member = _write_artifact(
        output_root,
        "base-sleeve",
        "json",
        _canonical_bytes(document),
    )
    artifact_path = output_root / archive_member
    artifact_digest = "sha256:" + artifact_path.stem
    reference = {
        "schema_version": PERSONAL_BASE_SLEEVE_REFERENCE_SCHEMA,
        "artifact_schema_version": document["schema_version"],
        "archive_member": archive_member,
        "sha256": artifact_digest,
        "strategy_id": document["strategy"]["strategy_id"],
        "cohort_id": document["cohort"]["cohort_id"],
        "universe_id": document["universe"]["universe_id"],
        "role": PERSONAL_BASE_SLEEVE_ROLE,
        "ranking_role": PERSONAL_BASE_SLEEVE_RANKING_ROLE,
        "candidate_count_contribution": 0,
    }
    return reference, artifact_path, artifact_digest


def _short_financing_sensitivity_document(
    runs_by_rate: Mapping[float, Sequence[dict[str, Any]]],
    returns_by_rate: Mapping[float, Sequence[float]],
    dates_by_rate: Mapping[float, Sequence[str]],
    *,
    execution_timing: str = "next_close_one_session_lag_no_lookahead",
) -> dict[str, Any]:
    results: list[dict[str, Any]] = []
    for rate in PERSONAL_SHORT_FINANCING_ANNUAL_RATES:
        runs = list(runs_by_rate[rate])
        performance = summarize_validation_performance(
            runs,
            list(returns_by_rate[rate]),
            stitched_dates=list(dates_by_rate[rate]),
        )
        results.append(
            {
                "annual_rate": rate,
                "baseline": rate
                == PERSONAL_SHORT_FINANCING_BASELINE_ANNUAL_RATE,
                "short_financing_cost_amount": sum(
                    float(run.get("short_financing_cost_amount") or 0.0)
                    for run in runs
                ),
                "fold_evidence": [
                    {
                        key: value
                        for key, value in run.items()
                        if key != "performance"
                    }
                    for run in runs
                ],
                "performance": performance,
            }
        )
    net_returns = [
        float(result["performance"]["stitched_performance"]["total_return_net"])
        for result in results
    ]
    document = {
        **_short_financing_policy_document(execution_timing=execution_timing),
        "results": results,
        "higher_rate_net_return_nonincreasing": all(
            left >= right for left, right in itertools.pairwise(net_returns)
        ),
    }
    return {**document, "evidence_digest": _digest(document)}


def _candidate_evaluation(
    executor: PersonalPaperExecutionService,
    spec: StrategySpec,
    closure: PlanDependencyClosure,
    *,
    snapshot: PersonalSnapshot,
    universe: PersonalResolvedUniverseMembership,
    fold_periods: tuple[tuple[str, str], ...],
    holdout_period: tuple[str, str],
    output_root: Path,
    policy: PersonalResearchPolicy,
    short_financing_required: bool = False,
    execution_mode: str = LEGACY_NEXT_CLOSE_EXECUTION_MODE,
    execution_contract: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    validation_runs: list[dict[str, Any]] = []
    pooled_returns: list[float] = []
    pooled_dates: list[str] = []
    sensitivity_runs: dict[float, list[dict[str, Any]]] = {
        rate: [] for rate in PERSONAL_SHORT_FINANCING_ANNUAL_RATES
    }
    sensitivity_returns: dict[float, list[float]] = {
        rate: [] for rate in PERSONAL_SHORT_FINANCING_ANNUAL_RATES
    }
    sensitivity_dates: dict[float, list[str]] = {
        rate: [] for rate in PERSONAL_SHORT_FINANCING_ANNUAL_RATES
    }
    for period in fold_periods:
        baseline_rate = (
            PERSONAL_SHORT_FINANCING_BASELINE_ANNUAL_RATE
            if short_financing_required
            else None
        )
        evidence, returns, dates, paper_result = _run_one(
            executor,
            spec,
            db_path=snapshot.db_path,
            snapshot_id=snapshot.logical_data_snapshot_id,
            universe=universe,
            period=period,
            cost_bps=policy.base_cost_bps,
            lookback_days=closure.required_lookback_trading_days,
            output_root=output_root,
            max_drawdown=policy.max_drawdown,
            short_financing_annual_rate=baseline_rate,
            execution_mode=execution_mode,
            execution_contract=execution_contract,
        )
        if short_financing_required:
            for rate in PERSONAL_SHORT_FINANCING_ANNUAL_RATES:
                derived, derived_returns, derived_dates = (
                    _fixed_position_short_financing_evidence(
                        paper_result,
                        period=period,
                        starting_capital=1_000_000.0,
                        annual_rate=rate,
                    )
                )
                sensitivity_runs[rate].append(derived)
                sensitivity_returns[rate].extend(derived_returns)
                sensitivity_dates[rate].extend(derived_dates)
        validation_runs.append(evidence)
        pooled_returns.extend(returns)
        pooled_dates.extend(dates)

    pooled = sharpe_ratio(pooled_returns, periods_per_year=252.0).get("sharpe")
    positive = sum(
        run["total_return_post_cost"] > 0.0 for run in validation_runs
    )
    fills = sum(int(run["fills"]) for run in validation_runs)
    validation_performance = summarize_validation_performance(
        validation_runs,
        pooled_returns,
        stitched_dates=pooled_dates,
    )
    short_financing_sensitivity = (
        _short_financing_sensitivity_document(
            sensitivity_runs,
            sensitivity_returns,
            sensitivity_dates,
            execution_timing=_short_financing_execution_timing(
                execution_contract
            ),
        )
        if short_financing_required
        else None
    )
    validation_checks = {
        "positive_folds": positive >= policy.min_positive_folds,
        "pooled_annualized_sharpe": pooled is not None
        and float(pooled) >= policy.min_validation_sharpe,
        "drawdown": all(
            run["max_drawdown"] <= policy.max_drawdown
            for run in validation_runs
        ),
        "fills": fills >= policy.min_fills,
        "risk_agent": all(run["risk_status"] == "pass" for run in validation_runs),
    }
    if short_financing_sensitivity is not None:
        validation_checks["short_financing_rate_monotonicity"] = bool(
            short_financing_sensitivity[
                "higher_rate_net_return_nonincreasing"
            ]
        )
    candidate: dict[str, Any] = {
        "strategy_id": spec.strategy_id,
        "strategy_spec_version": spec.version,
        "strategy_spec_digest": strategy_spec_digest(spec),
        "dependency_closure_digest": closure.closure_digest,
        "strategy": _strategy_context(
            spec, execution_contract=execution_contract
        ),
        "execution_contract": (
            None if execution_contract is None else dict(execution_contract)
        ),
        "decision": "REJECT",
        "reasons": [
            (
                f"analysis_failure:{name}"
                if name == "short_financing_rate_monotonicity"
                else name
            )
            for name, passed in validation_checks.items()
            if not passed
        ],
        "validation": {
            "runs": validation_runs,
            "positive_folds": positive,
            "total_fills": fills,
            "pooled_annualized_sharpe": None if pooled is None else float(pooled),
            "sharpe_periods_per_year": 252,
            "performance": validation_performance,
            "checks": validation_checks,
        },
        "stress": None,
        "holdout": None,
        "decision_basis": "validation_and_cost_stress",
        "performance_comparison": {
            "stress_vs_validation": None,
            "holdout_vs_validation": None,
        },
    }
    if short_financing_sensitivity is not None:
        candidate["short_financing_sensitivity"] = short_financing_sensitivity
    if not all(validation_checks.values()):
        return candidate

    stress, _, _, _ = _run_one(
        executor,
        spec,
        db_path=snapshot.db_path,
        snapshot_id=snapshot.logical_data_snapshot_id,
        universe=universe,
        period=(fold_periods[0][0], fold_periods[-1][1]),
        cost_bps=policy.stress_cost_bps,
        lookback_days=closure.required_lookback_trading_days,
        output_root=output_root,
        max_drawdown=policy.max_drawdown,
        short_financing_annual_rate=(
            PERSONAL_SHORT_FINANCING_BASELINE_ANNUAL_RATE
            if short_financing_required
            else None
        ),
        execution_mode=execution_mode,
        execution_contract=execution_contract,
    )
    stress_checks = {
        "positive_return": stress["total_return_post_cost"] > 0.0,
        "nonnegative_sharpe": stress["annualized_sharpe"] is not None
        and stress["annualized_sharpe"] >= 0.0,
        "drawdown": stress["max_drawdown"] <= policy.max_drawdown,
        "risk_agent": stress["risk_status"] == "pass",
    }
    candidate["stress"] = {**stress, "checks": stress_checks}
    candidate["performance_comparison"]["stress_vs_validation"] = performance_delta(
        validation_performance["stitched_performance"],
        stress.get("performance"),
    )
    if not all(stress_checks.values()):
        candidate["reasons"] = [
            f"stress:{name}" for name, passed in stress_checks.items() if not passed
        ]
        return candidate

    holdout, _, _, _ = _run_one(
        executor,
        spec,
        db_path=snapshot.db_path,
        snapshot_id=snapshot.logical_data_snapshot_id,
        universe=universe,
        period=holdout_period,
        cost_bps=policy.base_cost_bps,
        lookback_days=closure.required_lookback_trading_days,
        output_root=output_root,
        max_drawdown=policy.max_drawdown,
        short_financing_annual_rate=(
            PERSONAL_SHORT_FINANCING_BASELINE_ANNUAL_RATE
            if short_financing_required
            else None
        ),
        execution_mode=execution_mode,
        execution_contract=execution_contract,
    )
    holdout_checks = {
        "positive_return": holdout["total_return_post_cost"] > 0.0,
        "nonnegative_sharpe": holdout["annualized_sharpe"] is not None
        and holdout["annualized_sharpe"] >= 0.0,
        "drawdown": holdout["max_drawdown"] <= policy.max_drawdown,
        "risk_agent": holdout["risk_status"] == "pass",
    }
    candidate["holdout"] = {
        **holdout,
        "checks": holdout_checks,
        "selection_use": False,
        "purpose": "exploratory_recent_period",
    }
    candidate["performance_comparison"]["holdout_vs_validation"] = performance_delta(
        validation_performance["stitched_performance"],
        holdout.get("performance"),
    )
    candidate["decision"] = "HOLD"
    candidate["reasons"] = ["human_review_required"]
    return candidate


@dataclass(frozen=True, slots=True)
class _CandidateProcessTask:
    ordinal: int
    strategy_spec_document: bytes
    dependency_closure_document: bytes
    snapshot: PersonalSnapshot
    universe: PersonalResolvedUniverseMembership
    fold_periods: tuple[tuple[str, str], ...]
    holdout_period: tuple[str, str]
    output_root: Path
    policy: PersonalResearchPolicy
    short_financing_required: bool
    execution_mode: str = LEGACY_NEXT_CLOSE_EXECUTION_MODE
    execution_contract: Mapping[str, Any] | None = None


def _process_contract_dependency(
    document: Any,
    *,
    expected_kind: str,
) -> ContractDependency:
    if not isinstance(document, Mapping):
        raise RuntimeError("candidate process contract document is invalid")
    try:
        dependency = ContractDependency(
            kind=document["kind"],
            dependency_id=document["id"],
            version=document["version"],
            dataset_dependencies=tuple(document["dataset_dependencies"]),
        )
    except (KeyError, TypeError, ValueError) as error:
        raise RuntimeError(
            "candidate process contract document cannot be reconstructed"
        ) from error
    if dependency.kind != expected_kind or dependency.to_dict() != dict(document):
        raise RuntimeError("candidate process contract identity mismatch")
    return dependency


def _candidate_process_domain(
    task: _CandidateProcessTask,
) -> tuple[StrategySpec, PlanDependencyClosure]:
    """Rebuild immutable domain values from canonical, pickle-safe bytes."""

    try:
        spec_document = json.loads(task.strategy_spec_document)
        closure_document = json.loads(task.dependency_closure_document)
    except (TypeError, json.JSONDecodeError) as error:
        raise RuntimeError("candidate process document is invalid") from error
    if not isinstance(spec_document, dict) or not isinstance(closure_document, dict):
        raise RuntimeError("candidate process document must be an object")
    spec = StrategySpec.from_dict(spec_document)
    if spec.to_dict() != spec_document:
        raise RuntimeError("candidate process strategy identity mismatch")
    universe_documents = closure_document.get("universe_dependencies")
    if not isinstance(universe_documents, list):
        raise RuntimeError("candidate process universe dependencies are invalid")
    closure = build_strategy_dependency_closure(
        plan_id=closure_document["plan_id"],
        plan_digest=closure_document["plan_digest"],
        spec=spec,
        universe_dependencies=tuple(
            _process_contract_dependency(document, expected_kind="universe")
            for document in universe_documents
        ),
        evaluation_dependency=_process_contract_dependency(
            closure_document.get("evaluation_dependency"),
            expected_kind="evaluation",
        ),
        risk_dependency=_process_contract_dependency(
            closure_document.get("risk_dependency"),
            expected_kind="risk",
        ),
        cost_dependency=_process_contract_dependency(
            closure_document.get("cost_dependency"),
            expected_kind="cost",
        ),
        research_data_profile_id=closure_document["research_data_profile_id"],
        period_start=closure_document["period_start"],
        period_end=closure_document["period_end"],
    )
    if closure.to_dict() != closure_document:
        raise RuntimeError("candidate process dependency closure identity mismatch")
    return spec, closure


def _candidate_process(task: _CandidateProcessTask) -> tuple[int, dict[str, Any]]:
    """Evaluate one candidate in an isolated process-local prepared frame."""

    spec, closure = _candidate_process_domain(task)
    executor = PersonalPaperExecutionService()
    with _personal_prepared_frame_scope(
        db_path=task.snapshot.db_path,
        snapshot_id=task.snapshot.logical_data_snapshot_id,
    ):
        candidate = _candidate_evaluation(
            executor,
            spec,
            closure,
            snapshot=task.snapshot,
            universe=task.universe,
            fold_periods=task.fold_periods,
            holdout_period=task.holdout_period,
            output_root=task.output_root,
            policy=task.policy,
            short_financing_required=task.short_financing_required,
            execution_mode=task.execution_mode,
            execution_contract=task.execution_contract,
        )
    return task.ordinal, candidate


def _unexpected_candidate(
    spec: StrategySpec,
    closure: PlanDependencyClosure,
    error: BaseException,
    *,
    execution_contract: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    if isinstance(error, _CandidateProcessReportedError):
        error_type = error.error_type
        detail = error.detail
    else:
        error_type = type(error).__name__
        detail = " ".join(str(error).split())[:400]
    return {
        "strategy_id": spec.strategy_id,
        "strategy_spec_version": spec.version,
        "strategy_spec_digest": strategy_spec_digest(spec),
        "dependency_closure_digest": closure.closure_digest,
        "strategy": _strategy_context(
            spec, execution_contract=execution_contract
        ),
        "execution_contract": (
            None if execution_contract is None else dict(execution_contract)
        ),
        "decision": "SKIPPED",
        "reasons": [f"unexpected:{error_type}"],
        "validation": None,
        "stress": None,
        "holdout": None,
        "decision_basis": "validation_and_cost_stress",
        "performance_comparison": {
            "stress_vs_validation": None,
            "holdout_vs_validation": None,
        },
        "error": {
            "type": error_type,
            "detail": detail or "no detail",
        },
    }


class _CandidateProcessReportedError(RuntimeError):
    """A bounded child error transported without a semaphore-backed channel."""

    def __init__(self, error_type: str, detail: str) -> None:
        super().__init__(f"{error_type}: {detail}")
        self.error_type = error_type
        self.detail = detail


def _candidate_process_identity(task: _CandidateProcessTask) -> dict[str, Any]:
    spec, closure = _candidate_process_domain(task)
    return {
        "ordinal": task.ordinal,
        "strategy_id": spec.strategy_id,
        "strategy_spec_version": spec.version,
        "strategy_spec_digest": strategy_spec_digest(spec),
        "dependency_closure_digest": closure.closure_digest,
    }


def _validate_candidate_process_candidate(
    candidate: Any,
    identity: Mapping[str, Any],
) -> dict[str, Any]:
    if not isinstance(candidate, dict):
        raise RuntimeError("candidate process result must be an object")
    expected = {
        "strategy_id": identity["strategy_id"],
        "strategy_spec_version": identity["strategy_spec_version"],
        "strategy_spec_digest": identity["strategy_spec_digest"],
        "dependency_closure_digest": identity["dependency_closure_digest"],
    }
    if any(candidate.get(key) != value for key, value in expected.items()):
        raise RuntimeError("candidate process result identity mismatch")
    return candidate


def _candidate_process_error_document(error: BaseException) -> dict[str, str]:
    return {
        "type": type(error).__name__,
        "detail": " ".join(str(error).split())[:400] or "no detail",
    }


def _write_candidate_process_envelope(
    result_path: Path,
    envelope: Mapping[str, Any],
) -> None:
    """Publish one result atomically on the result directory's filesystem."""

    temporary_path = result_path.with_name(
        f".{result_path.name}.{os.getpid()}.tmp"
    )
    try:
        with temporary_path.open("xb") as handle:
            handle.write(_canonical_bytes(envelope))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, result_path)
    finally:
        temporary_path.unlink(missing_ok=True)


def _candidate_process_to_file(
    task: _CandidateProcessTask,
    result_path: Path,
    candidate_worker: Any,
) -> None:
    """Child entrypoint: evaluate and publish one closed atomic JSON envelope."""

    identity = _candidate_process_identity(task)
    try:
        ordinal, candidate = candidate_worker(task)
        if ordinal != task.ordinal:
            raise RuntimeError("candidate process ordinal mismatch")
        candidate = _validate_candidate_process_candidate(candidate, identity)
    except Exception as error:
        envelope: dict[str, Any] = {
            "schema_version": _CANDIDATE_PROCESS_RESULT_SCHEMA,
            "status": "ERROR",
            **identity,
            "error": _candidate_process_error_document(error),
        }
    else:
        envelope = {
            "schema_version": _CANDIDATE_PROCESS_RESULT_SCHEMA,
            "status": "SUCCESS",
            **identity,
            "candidate": candidate,
        }
    _write_candidate_process_envelope(result_path, envelope)


def _read_candidate_process_envelope(
    task: _CandidateProcessTask,
    result_path: Path,
) -> dict[str, Any]:
    try:
        raw = result_path.read_bytes()
    except FileNotFoundError as error:
        raise RuntimeError("candidate process result file is missing") from error
    try:
        envelope = json.loads(raw)
    except (TypeError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise RuntimeError("candidate process result file is malformed") from error
    if not isinstance(envelope, dict):
        raise RuntimeError("candidate process result envelope must be an object")
    try:
        canonical = _canonical_bytes(envelope)
    except (TypeError, ValueError) as error:
        raise RuntimeError(
            "candidate process result envelope is not canonical"
        ) from error
    if raw != canonical:
        raise RuntimeError("candidate process result envelope is not canonical")

    identity = _candidate_process_identity(task)
    common_fields = {
        "schema_version",
        "status",
        "ordinal",
        "strategy_id",
        "strategy_spec_version",
        "strategy_spec_digest",
        "dependency_closure_digest",
    }
    if envelope.get("schema_version") != _CANDIDATE_PROCESS_RESULT_SCHEMA:
        raise RuntimeError("candidate process result schema mismatch")
    if any(envelope.get(key) != value for key, value in identity.items()):
        raise RuntimeError("candidate process result envelope identity mismatch")

    status = envelope.get("status")
    if status == "SUCCESS":
        if set(envelope) != common_fields | {"candidate"}:
            raise RuntimeError("candidate process success fields are not closed")
        return _validate_candidate_process_candidate(
            envelope.get("candidate"), identity
        )
    if status == "ERROR":
        if set(envelope) != common_fields | {"error"}:
            raise RuntimeError("candidate process error fields are not closed")
        child_error = envelope.get("error")
        if (
            not isinstance(child_error, dict)
            or set(child_error) != {"type", "detail"}
            or not isinstance(child_error.get("type"), str)
            or not child_error["type"]
            or len(child_error["type"]) > 120
            or not isinstance(child_error.get("detail"), str)
            or not child_error["detail"]
            or len(child_error["detail"]) > 400
        ):
            raise RuntimeError("candidate process error document is invalid")
        raise _CandidateProcessReportedError(
            child_error["type"], child_error["detail"]
        )
    raise RuntimeError("candidate process result status is invalid")


def _process_is_alive(process: Any) -> bool:
    try:
        return bool(process.is_alive())
    except (AssertionError, ValueError):
        return False


def _shutdown_candidate_processes(
    processes: Sequence[Any],
    *,
    attempted_processes: Sequence[Any],
    terminate_live: bool,
) -> None:
    """Reap and close every process; force survivors only on abnormal unwind."""

    if terminate_live:
        for process in attempted_processes:
            if _process_is_alive(process):
                process.terminate()
        for process in attempted_processes:
            try:
                process.join(_CANDIDATE_PROCESS_STOP_GRACE_SECONDS)
            except (AssertionError, ValueError):
                # A truly unstarted Process has no child to join. An attempted
                # start can still leave a live child, which is checked below.
                continue
        for process in attempted_processes:
            if _process_is_alive(process):
                process.kill()
        for process in attempted_processes:
            try:
                process.join()
            except (AssertionError, ValueError):
                continue
    unreaped = any(_process_is_alive(process) for process in attempted_processes)
    for process in processes:
        try:
            process.close()
        except ValueError:
            # A Process constructed but never started has no resources to close.
            continue
    if unreaped:
        raise RuntimeError("candidate process could not be reaped")


def _evaluate_candidates_concurrently(
    tasks: Sequence[_CandidateProcessTask],
    *,
    max_workers: int,
    process_context: Any | None = None,
    candidate_worker: Any | None = None,
) -> tuple[list[dict[str, Any]], int]:
    """Directly spawn bounded children and fan-in through atomic result files."""

    if not tasks or not 1 <= max_workers <= 4 or max_workers > len(tasks):
        raise ValueError("candidate process fan-out is outside its closed bound")
    if [task.ordinal for task in tasks] != list(range(len(tasks))):
        raise ValueError("candidate process tasks must be globally contiguous")
    output_roots = {task.output_root.resolve() for task in tasks}
    if len(output_roots) != 1:
        raise ValueError("candidate process tasks must share one output root")
    output_root = output_roots.pop()
    output_root.mkdir(parents=True, exist_ok=True)
    context = (
        multiprocessing.get_context("spawn")
        if process_context is None
        else process_context
    )
    worker = _candidate_process if candidate_worker is None else candidate_worker
    ordered: list[dict[str, Any] | None] = [None] * len(tasks)
    unexpected_errors = 0
    with TemporaryDirectory(
        prefix=".candidate-process-results-",
        dir=output_root,
    ) as temporary_directory:
        result_root = Path(temporary_directory)
        completed_rows: list[tuple[_CandidateProcessTask, Path, int | None]] = []
        for wave_start in range(0, len(tasks), max_workers):
            wave = tasks[wave_start : wave_start + max_workers]
            rows: list[tuple[_CandidateProcessTask, Path, Any]] = []
            attempted_processes: list[Any] = []
            try:
                for task in wave:
                    result_path = result_root / f"candidate-{task.ordinal}.json"
                    process = context.Process(
                        target=_candidate_process_to_file,
                        args=(task, result_path, worker),
                        name=f"qp-candidate-{task.ordinal}",
                        daemon=False,
                    )
                    rows.append((task, result_path, process))
                # Every child in this bounded wave starts before its first
                # join. A Process is tracked before start(), because a failed
                # start may already have made its child live.
                for _task, _result_path, process in rows:
                    attempted_processes.append(process)
                    process.start()
                for _task, _result_path, process in rows:
                    process.join()
                exitcodes = [process.exitcode for _task, _path, process in rows]
            except BaseException:
                _shutdown_candidate_processes(
                    [process for _task, _path, process in rows],
                    attempted_processes=attempted_processes,
                    terminate_live=True,
                )
                raise
            else:
                _shutdown_candidate_processes(
                    [process for _task, _path, process in rows],
                    attempted_processes=attempted_processes,
                    terminate_live=False,
                )
            completed_rows.extend(
                (task, result_path, exitcode)
                for (task, result_path, _process), exitcode in zip(
                    rows, exitcodes, strict=True
                )
            )

        for task, result_path, exitcode in completed_rows:
            try:
                if exitcode != 0:
                    raise RuntimeError(
                        f"candidate process exited nonzero ({exitcode})"
                    )
                candidate = _read_candidate_process_envelope(task, result_path)
            except Exception as error:
                unexpected_errors += 1
                spec, closure = _candidate_process_domain(task)
                ordered[task.ordinal] = _unexpected_candidate(
                    spec,
                    closure,
                    error,
                    execution_contract=task.execution_contract,
                )
            else:
                ordered[task.ordinal] = candidate
    if any(candidate is None for candidate in ordered):
        raise RuntimeError("candidate process fan-in was incomplete")
    return [candidate for candidate in ordered if candidate is not None], unexpected_errors


def _comparison_document(candidates: Sequence[dict[str, Any]]) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for candidate in candidates:
        validation = candidate.get("validation")
        stability = (
            validation.get("performance")
            if isinstance(validation, dict)
            and isinstance(validation.get("performance"), dict)
            else None
        )
        stitched = (
            stability.get("stitched_performance")
            if isinstance(stability, dict)
            else None
        )
        stress = candidate.get("stress")
        holdout = candidate.get("holdout")
        contract = candidate.get("execution_contract")
        rows.append(
            {
                "strategy_id": candidate["strategy_id"],
                "decision": candidate["decision"],
                "thesis": candidate.get("strategy", {}).get("thesis", ""),
                "return_source": candidate.get("strategy", {}).get(
                    "return_source", ""
                ),
                "works_when": candidate.get("strategy", {}).get(
                    "works_when", ""
                ),
                "fails_when": candidate.get("strategy", {}).get(
                    "fails_when", ""
                ),
                "evidence_assessment": _candidate_evidence_assessment(candidate),
                "mechanics_summary": candidate.get("strategy", {}).get(
                    "mechanics_summary", ""
                ),
                "validation": stitched,
                "fold_stability": stability,
                "stress": (
                    stress.get("performance")
                    if isinstance(stress, dict)
                    else None
                ),
                "holdout": (
                    holdout.get("performance")
                    if isinstance(holdout, dict)
                    else None
                ),
                "deltas": candidate.get("performance_comparison"),
                "short_financing_sensitivity": candidate.get(
                    "short_financing_sensitivity"
                ),
                "execution_contract": contract,
                "execution_contract_id": (
                    contract.get("id") if isinstance(contract, Mapping) else None
                ),
                "execution_contract_digest": (
                    contract.get("contract_digest")
                    if isinstance(contract, Mapping)
                    else None
                ),
                "execution_contract_label": (
                    contract.get("label")
                    if isinstance(contract, Mapping)
                    else None
                ),
            }
        )
    digests: list[str | None] = []
    for row in rows:
        contract = row.get("execution_contract")
        digest = (
            contract.get("contract_digest")
            if isinstance(contract, Mapping)
            else None
        )
        digests.append(digest if isinstance(digest, str) else None)
    unique_digests = {digest for digest in digests if digest is not None}
    mixed = len(set(digests)) > 1
    am_only = (
        not mixed
        and rows
        and isinstance(rows[0].get("execution_contract"), Mapping)
        and rows[0]["execution_contract"].get("execution_mode")
        == AM_SIGNAL_PM_CLOSE_EXECUTION_MODE
    )
    metric_basis = {
        "return_frequency": (
            "d_pm_to_next_pm_including_first_new_position"
            if am_only
            else "daily_close_to_close_including_first_session"
        ),
        "annualization_sessions": 252,
        "return_basis": "post_cost_equity",
        "drawdown_basis": "post_cost_equity_including_starting_capital",
        "drawdown_duration": "peak_to_trough_sessions",
        "drawdown_recovery": "trough_to_first_prior_peak_recovery_sessions",
        "turnover_basis": "one_way_absolute_fill_notional_over_starting_capital",
        "var_cvar_basis": "positive_loss_magnitude_from_daily_returns",
        "stress_holdout_delta": "observed_minus_validation_stitched",
    }
    document: dict[str, Any] = {
        "schema_version": "personal-performance-comparison/v2",
        "metric_basis": metric_basis,
        "rows": rows,
        "execution_contract_column": True,
    }
    if mixed:
        document.update(
            {
                "comparable": False,
                "cross_contract_aggregation": "forbidden",
                "cross_contract_ranking": "forbidden",
                "reason": "mixed_execution_contracts",
            }
        )
    else:
        document["comparable"] = True
        if unique_digests:
            document["execution_contract_digest"] = next(iter(unique_digests))
    return document


def pool_or_rank_personal_comparison(
    document: Mapping[str, Any],
) -> list[dict[str, Any]]:
    """Refuse silent pooling or ranking across execution contracts."""

    if not isinstance(document, Mapping):
        raise PersonalResearchInputError("comparison document is required")
    rows = document.get("rows")
    if not isinstance(rows, list):
        raise PersonalResearchInputError("comparison rows are required")
    identities: list[str | None] = []
    for row in rows:
        contract = row.get("execution_contract") if isinstance(row, Mapping) else None
        if isinstance(contract, Mapping):
            digest = contract.get("contract_digest")
            identities.append(digest if isinstance(digest, str) else None)
        else:
            identities.append(None)
    if len(set(identities)) > 1 or document.get("comparable") is False:
        raise PersonalResearchInputError(
            "cannot rank or pool comparison rows across execution contracts"
        )
    return [row for row in rows if isinstance(row, Mapping)]


def _md_text(value: Any) -> str:
    return " ".join(str(value or "not declared").split()).replace("|", "\\|")


def _md_ratio(value: Any) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "—"
    return f"{number * 100:.2f}%" if number == number else "—"


def _md_number(value: Any) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "—"
    return f"{number:.3f}" if number == number else "—"


def _md_short_financing(value: Any) -> str:
    if not isinstance(value, Mapping):
        return "not applicable"
    monotonicity = (
        "PASS"
        if value.get("higher_rate_net_return_nonincreasing") is True
        else "FAIL (validation REJECT)"
    )
    parts: list[str] = []
    for result in value.get("results", []):
        if not isinstance(result, Mapping):
            continue
        performance = result.get("performance")
        stitched = (
            performance.get("stitched_performance")
            if isinstance(performance, Mapping)
            else None
        )
        if not isinstance(stitched, Mapping):
            continue
        rate = _md_ratio(result.get("annual_rate"))
        suffix = " baseline" if result.get("baseline") is True else ""
        parts.append(
            f"{rate}{suffix}: net {_md_ratio(stitched.get('total_return_net'))}, "
            f"Sharpe {_md_number(stitched.get('annualized_sharpe'))}"
        )
    results = "; ".join(parts) or "not evaluated"
    return f"fixed 3% trace, monotonicity {monotonicity}; {results}"


def _markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Personal Paper Research",
        "",
        f"- Report: `{report['report_id']}`",
        f"- Snapshot: `{report['snapshot']['snapshot_id']}`",
        f"- Universe: `{report['universe']['rule_id']}`",
        f"- Data period: {report['period']['data_start']} to {report['period']['end']}",
        f"- Evaluation start: {report['period']['evaluation_start'] or 'none'}",
        f"- Warmup sessions: {report['period']['warmup_sessions']}",
        f"- Analysis: {report['summary']['analysis_status']}",
        f"- Candidates: {report['summary']['candidate_count']}",
        f"- Evaluated: {report['summary']['evaluated_count']}",
        f"- HOLD: {report['summary']['hold_count']}",
        f"- Price basis: {report['price_basis']['id']} (retrospective DRAFT only)",
        "- GO: false",
        "- READY snapshot: not declared",
        "- Live orders: disabled",
        "- Automatic promotion: disabled",
        "- Model calls / estimated AI cost: 0 / USD 0",
        "",
        "## Decisions",
        "",
    ]
    cohort = report.get("strategy_cohort")
    if isinstance(cohort, dict):
        lines.insert(6, f"- Cohort: `{cohort['cohort_id']}`")
    execution_contract = report.get("execution_contract")
    comparison = report.get("comparison")
    mixed_contracts = (
        isinstance(comparison, Mapping) and comparison.get("comparable") is False
    )
    am_execution = (
        isinstance(execution_contract, Mapping)
        and execution_contract.get("execution_mode")
        == AM_SIGNAL_PM_CLOSE_EXECUTION_MODE
    )
    if am_execution:
        insert_at = 7 if isinstance(cohort, dict) else 6
        lines[insert_at:insert_at] = [
            (
                "- Execution: `am_signal_pm_close` "
                f"(`{execution_contract.get('contract_digest')}`)"
            ),
            (
                "- Timing: AM MAdjC signal / same-day PM AAdjC fill; "
                "non-price cutoff 11:30:00+09:00; AM acquisition deadline "
                "12:30:00+09:00 is not the cutoff; first PnL D_PM_to_next_PM; "
                "D-1 market cap; no fallback/ffill; DRAFT retrospective only"
            ),
        ]
    for candidate in report["candidates"]:
        reasons = ", ".join(candidate["reasons"]) or "none"
        lines.append(
            f"- **{candidate['strategy_id']}**: {candidate['decision']} ({reasons})"
        )
    lines.extend(
        [
            "",
            "HOLD means only that the DRAFT evidence is worth human review. ",
            "It is selected by validation plus cost stress; the recent holdout is ",
            "exploratory and reusable. HOLD does not authorize promotion or trading.",
            "",
            "## Comparable performance",
            "",
            (
                "Validation is the chronologically stitched fold path. Stress and "
                "holdout deltas are observed minus validation."
            ),
            "",
        ]
    )
    show_execution_column = bool(am_execution or mixed_contracts)
    if mixed_contracts:
        lines.extend(
            [
                "Rows include an explicit execution-contract column and are not "
                "pooled or ranked across contracts.",
                "",
            ]
        )
    if show_execution_column:
        lines.extend(
            [
                (
                    "| Strategy | Execution contract | Thesis | Return source | "
                    "Works when | Fails when | Evidence | Mechanics | Decision | "
                    "Short financing sensitivity | "
                    "Net return | CAGR | Volatility | Sharpe | Sortino | Max DD | "
                    "Calmar | Positive days | Positive months | Daily CVaR 95 | "
                    "Turnover / year | Cost drag | Stress Sharpe delta | "
                    "Holdout Sharpe delta |"
                ),
                (
                    "|---|---|---|---|---|---|---|---|---:|---|---:|---:|---:|"
                    "---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|"
                ),
            ]
        )
    else:
        lines.extend(
            [
                (
                    "| Strategy | Thesis | Return source | Works when | Fails when | "
                    "Evidence | Mechanics | Decision | "
                    "Short financing sensitivity | "
                    "Net return | CAGR | Volatility | Sharpe | Sortino | Max DD | "
                    "Calmar | Positive days | Positive months | Daily CVaR 95 | "
                    "Turnover / year | Cost drag | Stress Sharpe delta | "
                    "Holdout Sharpe delta |"
                ),
                (
                    "|---|---|---|---|---|---|---|---:|---|---:|---:|---:|---:|"
                    "---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|"
                ),
            ]
        )
    for row in report["comparison"]["rows"]:
        validation = row.get("validation") or {}
        deltas = row.get("deltas") or {}
        stress_delta = deltas.get("stress_vs_validation") or {}
        holdout_delta = deltas.get("holdout_vs_validation") or {}
        contract = row.get("execution_contract")
        contract_label = LEGACY_NEXT_CLOSE_LABEL
        if isinstance(contract, Mapping):
            contract_label = str(
                contract.get("label")
                or contract.get("execution_mode")
                or LEGACY_NEXT_CLOSE_LABEL
            )
        cells = [
            f"`{row['strategy_id']}`",
        ]
        if show_execution_column:
            cells.append(_md_text(contract_label))
        cells.extend(
            (
                _md_text(row.get("thesis")),
                _md_text(row.get("return_source")),
                _md_text(row.get("works_when")),
                _md_text(row.get("fails_when")),
                _md_text(row.get("evidence_assessment")),
                _md_text(row.get("mechanics_summary")),
                str(row["decision"]),
                _md_short_financing(row.get("short_financing_sensitivity")),
                _md_ratio(validation.get("total_return_net")),
                _md_ratio(validation.get("cagr")),
                _md_ratio(validation.get("annualized_volatility")),
                _md_number(validation.get("annualized_sharpe")),
                _md_number(validation.get("annualized_sortino")),
                _md_ratio(validation.get("max_drawdown")),
                _md_number(validation.get("calmar_ratio")),
                _md_ratio(validation.get("positive_day_rate")),
                _md_ratio(validation.get("positive_month_rate")),
                _md_ratio(
                    validation.get("daily_conditional_value_at_risk_95")
                ),
                _md_number(
                    validation.get("turnover_one_way_annualized_ratio")
                ),
                _md_ratio(validation.get("cost_return")),
                _md_number(stress_delta.get("annualized_sharpe")),
                _md_number(holdout_delta.get("annualized_sharpe")),
            )
        )
        lines.append("| " + " | ".join(cells) + " |")
    lines.extend(
        [
            "",
            "All ratios are based on post-cost daily equity. VaR/CVaR are shown ",
            "as positive loss magnitudes. Unrecovered drawdowns use `null` for ",
            "recovery sessions in the JSON report.",
            "",
        ]
    )
    short_policy = report.get("short_financing_policy")
    if isinstance(short_policy, Mapping):
        lines.extend(
            [
                "",
                (
                    "Financing note: only 3% executes Paper/Risk; 0% and 10% "
                    "are non-executable DRAFT repricings of its fixed trace. "
                    "The 245-session close-to-next-session convention includes "
                    "one terminal accrual without a next valuation (residual risk)."
                ),
                "",
            ]
        )
    return "\n".join(lines)


class PersonalResearchService:
    """Bounded DRAFT service; shared preparation and at most four candidates."""

    def __init__(self, *, policy: PersonalResearchPolicy | None = None) -> None:
        self.policy = policy or PersonalResearchPolicy()

    def run(self, request: PersonalResearchRequest) -> PersonalResearchRun:
        if not isinstance(request, PersonalResearchRequest):
            raise TypeError("PersonalResearchRequest required")
        source = Path(request.source_db).expanduser().resolve()
        if not source.is_file():
            raise PersonalResearchInputError(f"database does not exist: {source}")
        end_day = _parse_day(request.period_end, "period_end")
        start_day = (
            _parse_day(request.period_start, "period_start")
            if request.period_start is not None
            else _default_start(end_day)
        )
        if start_day >= end_day:
            raise PersonalResearchInputError("period_start must precede period_end")
        try:
            universe_selector = personal_universe_selector(request.universe_id)
        except PersonalUniverseError as exc:
            raise PersonalResearchInputError(str(exc)) from exc
        specs, cohort = _validated_specs(
            request.specs,
            self.policy,
            request.cohort_id,
            universe_selector.selector_id,
        )
        execution_contract = _resolved_execution_contract(
            cohort,
            using_default_specs=request.specs is None
            and request.cohort_id is None,
        )
        execution_mode = str(execution_contract["execution_mode"])
        try:
            universe_selector = universe_selector.with_decision_cutoff(
                personal_research_universe_decision_cutoff(
                    am_pm=execution_mode == AM_SIGNAL_PM_CLOSE_EXECUTION_MODE
                )
            )
        except PersonalUniverseError as exc:
            raise PersonalResearchInputError(str(exc)) from exc
        short_financing_required = bool(
            cohort is not None and cohort.short_financing_required
        )
        base_sleeve_required = _requires_index_vol_base_sleeve(
            cohort,
            universe_id=universe_selector.selector_id,
        )
        if short_financing_required and (
            cohort is None
            or not is_personal_short_financing_cohort(cohort.cohort_id)
        ):
            raise PersonalResearchInputError(
                "personal modelled short financing is closed to the "
                f"{PERSONAL_SHORT_FINANCING_COHORT_ID!r} or "
                f"{PERSONAL_SHORT_FINANCING_AM_PM_COHORT_ID!r} cohort"
            )
        if cohort is not None:
            planned_maximum = len(specs) * (self.policy.validation_folds + 2) + int(
                base_sleeve_required
            )
            if planned_maximum > PERSONAL_EXACT_FOUR_MAX_BACKTESTS:
                raise PersonalResearchInputError(
                    "closed exact-four cohort exceeds the fixed "
                    f"{PERSONAL_EXACT_FOUR_MAX_BACKTESTS}-backtest budget"
                )
        cohort_ref: dict[str, str] | None = None
        if cohort is not None:
            history_start = _parse_day(
                cohort.history_data_start,
                "cohort history_data_start",
            )
            if start_day < history_start:
                raise PersonalResearchInputError(
                    f"period_start precedes {cohort.cohort_id} history floor "
                    f"{history_start.isoformat()}"
                )
            cohort_document = cohort.to_dict()
            cohort_ref = {
                "registry_version": COHORT_REGISTRY_VERSION,
                "cohort_id": cohort.cohort_id,
                "cohort_digest": str(cohort_document["cohort_digest"]),
            }
        closures = _closures(
            specs,
            start=start_day.isoformat(),
            end=end_day.isoformat(),
            policy=self.policy,
            universe_selector=universe_selector,
            cohort_ref=cohort_ref,
            execution_contract=execution_contract,
        )
        output_root = Path(request.output_root).expanduser().resolve()
        output_root.mkdir(parents=True, exist_ok=True)
        required = tuple(
            sorted(
                {
                    dataset
                    for closure in closures
                    for dataset in closure.required_datasets
                }
            )
        )
        snapshot = materialize_personal_snapshot(
            source,
            output_root / "snapshots",
            required_datasets=required,
            period_start=start_day.isoformat(),
            period_end=end_day.isoformat(),
            closure_digests=tuple(c.closure_digest for c in closures),
        )
        verify_personal_snapshot(snapshot)
        snapshot_manifest = json.loads(
            snapshot.manifest_path.read_text(encoding="utf-8")
        )
        source_sync = _source_sync_evidence(
            snapshot.db_path,
            snapshot_manifest,
            required_datasets=required,
        )
        try:
            universe, universe_breadth = resolve_personal_universe_with_evidence(
                snapshot.db_path,
                period_start=start_day.isoformat(),
                period_end=end_day.isoformat(),
                universe_id=universe_selector.selector_id,
                decision_cutoff=universe_selector.decision_cutoff,
            )
        except PersonalUniverseError as exc:
            raise PersonalResearchInputError(str(exc)) from exc
        universe_breadth = {
            **universe_breadth,
            "minimum_ratio": self.policy.min_universe_fins_breadth,
            "status": (
                "PASS"
                if universe_breadth["minimum_daily_ratio"]
                >= self.policy.min_universe_fins_breadth
                else "FAIL"
            ),
        }
        bar_coverage = _observed_market_bar_coverage(
            snapshot.db_path,
            universe,
            minimum_ratio=self.policy.min_observed_bar_coverage,
        )
        corporate_actions = _universe_corporate_action_check(
            snapshot.db_path,
            universe=universe,
            lookback_days=_calendar_lookback_days(
                max(
                    (
                        closure.required_lookback_trading_days
                        for closure in closures
                    ),
                    default=0,
                )
            ),
        )
        warmup_sessions = 0 if cohort is None else cohort.warmup_sessions
        evaluation_memberships = universe.decision_memberships[warmup_sessions:]
        evaluation_start = (
            evaluation_memberships[0][0] if evaluation_memberships else None
        )
        periods = _periods(
            universe,
            end=end_day,
            policy=self.policy,
            warmup_sessions=warmup_sessions,
        )
        candidates: list[dict[str, Any]] = []
        unexpected_errors = 0
        base_sleeve_reference: dict[str, Any] | None = None
        base_sleeve_artifact_path: Path | None = None
        base_sleeve_artifact_digest: str | None = None
        candidate_execution = {
            "model": "not_started",
            "worker_processes": 0,
            "max_parallel": self.policy.max_parallel,
            "shared_snapshot_and_quality_preparation": True,
            "base_sleeve_before_fanout": base_sleeve_required,
        }
        if (
            bar_coverage["status"] != "PASS"
            or source_sync["status"] != "PASS"
            or universe_breadth["status"] != "PASS"
            or periods is None
        ):
            reason = (
                "observed_bar_coverage_below_threshold"
                if bar_coverage["status"] != "PASS"
                else (
                    "source_sync_evidence_unusable"
                    if source_sync["status"] != "PASS"
                    else (
                        "universe_fins_breadth_below_threshold"
                        if universe_breadth["status"] != "PASS"
                        else (
                            "insufficient_post_warmup_sessions"
                            if evaluation_start is None
                            else "insufficient_validation_or_holdout_sessions"
                        )
                    )
                )
            )
            for spec, closure in zip(specs, closures, strict=True):
                candidates.append(
                    {
                        "strategy_id": spec.strategy_id,
                        "strategy_spec_version": spec.version,
                        "strategy_spec_digest": strategy_spec_digest(spec),
                        "dependency_closure_digest": closure.closure_digest,
                        "strategy": _strategy_context(
                            spec, execution_contract=execution_contract
                        ),
                        "execution_contract": dict(execution_contract),
                        "decision": "SKIPPED",
                        "reasons": [reason],
                        "validation": None,
                        "stress": None,
                        "holdout": None,
                        "decision_basis": "validation_and_cost_stress",
                        "performance_comparison": {
                            "stress_vs_validation": None,
                            "holdout_vs_validation": None,
                        },
                    }
                )
        else:
            fold_periods, holdout_period = periods
            executor = PersonalPaperExecutionService()
            if base_sleeve_required:
                with _personal_prepared_frame_scope(
                    db_path=snapshot.db_path,
                    snapshot_id=snapshot.logical_data_snapshot_id,
                ):
                    if cohort_ref is None:
                        raise RuntimeError("base sleeve cohort provenance is absent")
                    matching = [
                        (spec, closure)
                        for spec, closure in zip(specs, closures, strict=True)
                        if spec.strategy_id
                        in {INDEX_VOL_BASE_SLEEVE_ID, INDEX_VOL_AM_PM_BASE_SLEEVE_ID}
                    ]
                    if len(matching) != 1:
                        raise RuntimeError(
                            "frozen base sleeve is not unique in its exact cohort"
                        )
                    base_spec, base_closure = matching[0]
                    (
                        base_sleeve_reference,
                        base_sleeve_artifact_path,
                        base_sleeve_artifact_digest,
                    ) = _write_continuous_base_sleeve_artifact(
                        executor,
                        base_spec,
                        base_closure,
                        snapshot=snapshot,
                        universe=universe,
                        source_period=(fold_periods[0][0], holdout_period[1]),
                        output_root=output_root,
                        cohort_digest=cohort_ref["cohort_digest"],
                        execution_mode=execution_mode,
                        execution_contract=execution_contract,
                    )
            worker_count = min(len(specs), self.policy.max_parallel)
            if worker_count > 1:
                tasks = tuple(
                    _CandidateProcessTask(
                        ordinal=ordinal,
                        strategy_spec_document=_canonical_bytes(spec.to_dict()),
                        dependency_closure_document=_canonical_bytes(
                            closure.to_dict()
                        ),
                        snapshot=snapshot,
                        universe=universe,
                        fold_periods=fold_periods,
                        holdout_period=holdout_period,
                        output_root=output_root,
                        policy=self.policy,
                        short_financing_required=short_financing_required,
                        execution_mode=execution_mode,
                        execution_contract=execution_contract,
                    )
                    for ordinal, (spec, closure) in enumerate(
                        zip(specs, closures, strict=True)
                    )
                )
                candidates, unexpected_errors = _evaluate_candidates_concurrently(
                    tasks,
                    max_workers=worker_count,
                )
                candidate_execution = {
                    **candidate_execution,
                    "model": "direct_spawn_atomic_files",
                    "worker_processes": worker_count,
                }
            else:
                candidate_execution = {
                    **candidate_execution,
                    "model": "serial",
                    "worker_processes": 1,
                }
                with _personal_prepared_frame_scope(
                    db_path=snapshot.db_path,
                    snapshot_id=snapshot.logical_data_snapshot_id,
                ):
                    for spec, closure in zip(specs, closures, strict=True):
                        try:
                            candidates.append(
                                _candidate_evaluation(
                                    executor,
                                    spec,
                                    closure,
                                    snapshot=snapshot,
                                    universe=universe,
                                    fold_periods=fold_periods,
                                    holdout_period=holdout_period,
                                    output_root=output_root,
                                    policy=self.policy,
                                    short_financing_required=short_financing_required,
                                    execution_mode=execution_mode,
                                    execution_contract=execution_contract,
                                )
                            )
                        except Exception as error:  # report; CLI still exits 1
                            unexpected_errors += 1
                            candidates.append(
                                _unexpected_candidate(
                                    spec,
                                    closure,
                                    error,
                                    execution_contract=execution_contract,
                                )
                            )
        verify_personal_snapshot(snapshot)
        evaluated_count = sum(
            candidate["decision"] in {"HOLD", "REJECT"}
            for candidate in candidates
        )
        hold_count = sum(candidate["decision"] == "HOLD" for candidate in candidates)
        analysis_status = (
            "NO_ANALYSIS"
            if not evaluated_count
            else ("PARTIAL" if unexpected_errors else "COMPLETED")
        )
        body: dict[str, Any] = {
            "version": PERSONAL_RESEARCH_REPORT_VERSION,
            "decision_policy": PERSONAL_DECISION_POLICY,
            "profile_id": PERSONAL_DATA_PROFILE,
            "period": {
                "start": start_day.isoformat(),
                "data_start": start_day.isoformat(),
                "evaluation_start": evaluation_start,
                "end": end_day.isoformat(),
                "warmup_sessions": warmup_sessions,
            },
            "policy": self.policy.to_dict(),
            "candidate_execution": candidate_execution,
            "universe": {
                **universe_selector.to_dict(),
                "resolved_membership_digest": (
                    universe.resolved_membership_digest
                ),
            },
            "snapshot": {
                "snapshot_id": snapshot.snapshot_id,
                "logical_data_snapshot_id": snapshot.logical_data_snapshot_id,
                "manifest": snapshot_manifest,
                "manifest_artifact": snapshot.manifest_path.relative_to(
                    output_root
                ).as_posix(),
            },
            "dependency_closures": [closure.to_dict() for closure in closures],
            "data_quality": {
                "market_bar_coverage": bar_coverage,
                "corporate_actions": corporate_actions,
                "source_sync": source_sync,
                "universe_breadth": universe_breadth,
            },
            "price_basis": {
                "id": PERSONAL_RETROSPECTIVE_ADJUSTED,
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
            },
            "execution_contract": dict(execution_contract),
            "candidates": candidates,
            "comparison": _comparison_document(candidates),
            "base_sleeve_artifact": base_sleeve_reference,
            "summary": {
                "analysis_status": analysis_status,
                "candidate_count": len(candidates),
                "evaluated_count": evaluated_count,
                "hold_count": hold_count,
                "unexpected_errors": unexpected_errors,
                "non_candidate_source_backtest_count": int(
                    base_sleeve_reference is not None
                ),
            },
            "live_orders_enabled": False,
            "automatic_promotion": False,
            "model_calls": 0,
            "estimated_ai_cost_usd": 0.0,
            "go": False,
            "ready_snapshot_declared": False,
        }
        if cohort_ref is not None:
            body["strategy_cohort"] = cohort_ref
        if short_financing_required:
            body["short_financing_policy"] = (
                _short_financing_policy_document(
                    execution_timing=_short_financing_execution_timing(
                        execution_contract
                    )
                )
            )
        report_id = _digest(body)
        report = {**body, "report_id": report_id}
        json_path = _write_artifact(
            output_root, "reports", "json", _canonical_bytes(report)
        )
        markdown_path = _write_artifact(
            output_root,
            "reports",
            "md",
            _markdown(report).encode("utf-8"),
        )
        return PersonalResearchRun(
            report_id=report_id,
            report_json_path=output_root / json_path,
            report_markdown_path=output_root / markdown_path,
            snapshot=snapshot,
            candidate_count=len(candidates),
            evaluated_count=evaluated_count,
            hold_count=hold_count,
            unexpected_errors=unexpected_errors,
            cohort_id=(None if cohort_ref is None else cohort_ref["cohort_id"]),
            cohort_digest=(
                None if cohort_ref is None else cohort_ref["cohort_digest"]
            ),
            universe_id=universe_selector.selector_id,
            universe_rule_digest=universe_selector.rule_digest,
            execution_mode=execution_mode,
            execution_contract_digest=str(
                execution_contract.get("contract_digest")
            ),
            base_sleeve_artifact_path=base_sleeve_artifact_path,
            base_sleeve_artifact_digest=base_sleeve_artifact_digest,
            base_sleeve_archive_member=(
                None
                if base_sleeve_reference is None
                else str(base_sleeve_reference["archive_member"])
            ),
            base_sleeve_artifact=base_sleeve_reference,
            non_candidate_source_backtest_count=int(
                base_sleeve_reference is not None
            ),
        )


__all__ = [
    "DEFAULT_PERSONAL_UNIVERSE_ID",
    "PERSONAL_DECISION_POLICY",
    "PERSONAL_EXACT_FOUR_MAX_BACKTESTS",
    "PERSONAL_EXECUTABLE_COHORT_IDS",
    "PERSONAL_RESEARCH_REPORT_VERSION",
    "PERSONAL_SHORT_FINANCING_ANNUAL_RATES",
    "PERSONAL_SHORT_FINANCING_BASELINE_ANNUAL_RATE",
    "PERSONAL_SHORT_FINANCING_FORMULA_VERSION",
    "PERSONAL_SHORT_FINANCING_SCHEMA",
    "PERSONAL_SHORT_FINANCING_SESSIONS_PER_YEAR",
    "PERSONAL_SHORT_FINANCING_TRACE_SCHEMA",
    "PERSONAL_UNIVERSE_IDS",
    "PersonalResearchInputError",
    "PersonalResearchPolicy",
    "PersonalResearchRequest",
    "PersonalResearchRun",
    "PersonalResearchService",
    "default_personal_specs",
    "pool_or_rank_personal_comparison",
]
