"""Bounded personal DRAFT research over a compact-v8 snapshot.

The normal path is cloud: R2 is the snapshot authority, D1 is small job
state, and Container SQLite is ephemeral. Persistent local market, price, or
fundamental history is not a normal path; it remains exact opt-in
developer/recovery only (``QP_ALLOW_LOCAL_MARKET_DATA=1``).

This module is not Prime-limited. Default universe is PIT ``topix_all``;
Core30, Large70, Mid400, Small, TOPIX100, and TOPIX500 selectors are
PIT-resolved and intersected with financials at the execution decision cutoff.
Default AM cohorts use 11:30 information and same-day PM close.

Snapshot build is compact v8, one continuous object, at most 7000 inclusive
calendar days. Compressed R2/HTTP is <= 4 GiB; expanded SQLite/builder is
<= 5 GiB. One standard-4 Container shares one snapshot/quality prep and runs
the typed personal service in-process; a batch runs up to eight cohort/universe
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
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from types import SimpleNamespace
from typing import Any

import features
from agents.risk_agent import RiskAgent
from execution.personal_paper_service import PersonalPaperExecutionService
from paper_runtime.personal_draft_bind import (
    execute_personal_draft,
    prepare_draft_snapshot,
    prepared_frame_scope,
    verify_draft_snapshot,
)
from price_basis import PERSONAL_RETROSPECTIVE_ADJUSTED
from strategies.paper import Lifecycle, PaperRunConfig, PaperRunResult
from strategies.spec import StrategySpec, iter_feature_refs, strategy_spec_digest

from data_contracts.personal_history_compact import DEFAULT_MIN_OBSERVED_BAR_RATIO
from pit.cooperative_deadline import CooperativeDeadline, install_deadline
from pit.personal_research_view import (
    CONTAINER_EPHEMERAL_KIND,
    DEFAULT_DECISION_CUTOFF,
    LEGACY_SESSION_CLOSE_CUTOFF,
    OFFLINE_FIXTURE_KIND,
    ArtifactRef,
    PersonalResearchDataView,
    SnapshotIdentity,
)
from pit import PERSONAL_BAR_COVERAGE_EVIDENCE

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
PERSONAL_SHORT_FINANCING_SCHEMA = "personal-short-financing-sensitivity/v1"
PERSONAL_SHORT_FINANCING_FORMULA_VERSION = "fixed-baseline-position-short-financing/v1"
PERSONAL_SHORT_FINANCING_TRACE_SCHEMA = "personal-short-notional-trace/v1"
PERSONAL_SHORT_FINANCING_ANNUAL_RATES = (0.0, 0.03, 0.10)
PERSONAL_SHORT_FINANCING_BASELINE_ANNUAL_RATE = 0.03
PERSONAL_SHORT_FINANCING_SESSIONS_PER_YEAR = 245
PERSONAL_EXACT_FOUR_MAX_BACKTESTS = 25


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
    max_parallel: int = 1
    min_observed_bar_coverage: float = DEFAULT_MIN_OBSERVED_BAR_RATIO
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
        if self.max_parallel != 1:
            raise ValueError(
                "personal research calculation is serial; max_parallel must be 1"
            )
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
    data_view: PersonalResearchDataView
    period_end: str
    period_start: str | None = None
    specs: tuple[StrategySpec, ...] | None = None
    cohort_id: str | None = None
    universe_id: str = DEFAULT_PERSONAL_UNIVERSE_ID
    deadline: CooperativeDeadline | None = None


class _ReadableArtifact:
    """Bytes capability for one written artifact. Not a filesystem Path."""

    __slots__ = ("_view", "_ref")

    def __init__(self, view: PersonalResearchDataView, ref: ArtifactRef) -> None:
        self._view = view
        self._ref = ref

    def read_text(self, encoding: str = "utf-8") -> str:
        return self._view.read_artifact(self._ref.archive_member).decode(encoding)

    def read_bytes(self) -> bytes:
        return self._view.read_artifact(self._ref.archive_member)

    @property
    def archive_member(self) -> str:
        return self._ref.archive_member

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, _ReadableArtifact):
            return NotImplemented
        return self._ref == other._ref

    def __str__(self) -> str:
        return self._ref.archive_member


@dataclass(frozen=True, slots=True)
class PersonalResearchRun:
    report_id: str
    report_json: ArtifactRef
    report_markdown: ArtifactRef
    data_view: PersonalResearchDataView
    snapshot: SnapshotIdentity
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
    base_sleeve_artifact_digest: str | None = None
    base_sleeve_archive_member: str | None = None
    base_sleeve_artifact: dict[str, Any] | None = None
    non_candidate_source_backtest_count: int = 0
    go: bool = False
    ready_snapshot_declared: bool = False
    live_orders_enabled: bool = False
    automatic_promotion: bool = False
    model_calls: int = 0
    estimated_ai_cost_usd: float = 0.0

    @property
    def report_json_path(self) -> _ReadableArtifact:
        return _ReadableArtifact(self.data_view, self.report_json)

    @property
    def report_markdown_path(self) -> _ReadableArtifact:
        return _ReadableArtifact(self.data_view, self.report_markdown)

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
_EVALUATION_AM = ContractDependency(
    kind="evaluation",
    dependency_id="personal_walk_forward",
    version="personal-walk-forward/v1",
    dataset_dependencies=(
        "equities_bars_daily",
        "equities_bars_daily_am",
        "markets_calendar",
    ),
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
                evaluation_dependency=(
                    _EVALUATION_AM
                    if (
                        isinstance(execution_contract, Mapping)
                        and execution_contract.get("execution_mode")
                        == AM_SIGNAL_PM_CLOSE_EXECUTION_MODE
                    )
                    else _EVALUATION
                ),
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


def _write_artifact(
    view: PersonalResearchDataView, category: str, suffix: str, content: bytes
) -> str:
    return view.write_artifact(
        category=category, suffix=suffix, payload=content
    ).archive_member


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


_DATA_QUALITY_FLAG_NAMES = (
    "comparable",
    "selection_eligible",
    "comparison_eligible",
)
_DATA_QUALITY_DETAIL_KEYS = (
    "incomplete_valuation",
    "skipped_decision_count",
    "incomplete_valuation_count",
    "unfilled_order_count",
    "skipped_decision_dates",
    "incomplete_valuation_dates",
    "incomplete_valuation_codes",
    "missing_fill_dates",
    "missing_fill_codes",
    "non_comparable_session_dates",
    "held_missing_morning_adjustment_close",
    "held_missing_afternoon_adjustment_close",
    "missing_afternoon_adjustment_close_unfilled",
    "data_quality_gate",
)


def _explicit_quality_flag(source: Mapping[str, Any], name: str) -> bool:
    if name not in source:
        return True
    return source[name] is not False


def _paper_run_data_quality(metrics: Mapping[str, Any]) -> dict[str, Any]:
    """Always emit AM/PM eligibility flags; absent metrics stay eligible."""

    quality = {
        name: _explicit_quality_flag(metrics, name)
        for name in _DATA_QUALITY_FLAG_NAMES
    }
    for key in _DATA_QUALITY_DETAIL_KEYS:
        if key in metrics:
            quality[key] = metrics[key]
    return quality


def _run_is_selection_eligible(run: Mapping[str, Any]) -> bool:
    """True unless a run explicitly marks itself selection-ineligible."""

    if not isinstance(run, Mapping):
        return True
    if "selection_eligible" in run:
        return run["selection_eligible"] is not False
    quality = run.get("data_quality")
    if isinstance(quality, Mapping) and "selection_eligible" in quality:
        return quality["selection_eligible"] is not False
    return True


def _paper_evidence(
    result: PaperRunResult,
    *,
    config: PaperRunConfig,
    view: PersonalResearchDataView,
    max_drawdown: float,
    short_financing_annual_rate: float | None = None,
    execution_contract: Mapping[str, Any] | None = None,
) -> tuple[dict[str, Any], list[float], list[str]]:
    paper_path = _write_artifact(
        view, "paper", "json", _canonical_bytes(_portable_paper_document(result))
    )
    risk = _risk_document(result, max_drawdown)
    risk_path = _write_artifact(
        view, "risk", "json", _canonical_bytes(risk)
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
    data_quality = _paper_run_data_quality(metrics)
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
            "comparable": data_quality["comparable"],
            "selection_eligible": data_quality["selection_eligible"],
            "comparison_eligible": data_quality["comparison_eligible"],
            "data_quality": data_quality,
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
    view: PersonalResearchDataView,
    universe: PersonalResolvedUniverseMembership,
    period: tuple[str, str],
    cost_bps: float,
    lookback_days: int,
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
    result = execute_personal_draft(
        executor,
        spec,
        view=view,
        universe=period_universe,
        period=period,
        cost_bps=cost_bps,
        lookback_days=_calendar_lookback_days(lookback_days),
        execution_mode=execution_mode,
        short_financing_annual_rate=short_financing_annual_rate,
        short_financing_enabled=short_financing_annual_rate is not None,
        short_financing_spread_bp=(
            None
            if short_financing_annual_rate is None
            else short_financing_annual_rate * 10_000.0
        ),
        short_financing_fallback_repo_annual_bp=0.0,
        short_financing_auto_load_repo=False,
        leverage_financing_enabled=False,
        lifecycle=Lifecycle.DRAFT,
        price_basis=PERSONAL_RETROSPECTIVE_ADJUSTED,
    )
    config = SimpleNamespace(
        start=period[0],
        end=period[1],
        cost_bps=cost_bps,
        execution_mode=execution_mode,
        starting_capital=1_000_000.0,
    )
    evidence, returns, dates = _paper_evidence(
        result,
        config=config,
        view=view,
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
    view: PersonalResearchDataView,
    universe: PersonalResolvedUniverseMembership,
    source_period: tuple[str, str],
    cohort_digest: str,
    execution_mode: str = LEGACY_NEXT_CLOSE_EXECUTION_MODE,
    execution_contract: Mapping[str, Any] | None = None,
) -> tuple[dict[str, Any], ArtifactRef, str]:
    """Execute one full-period base sleeve outside candidate selection."""

    snapshot = view.snapshot_identity()
    am_sleeve = (
        execution_mode == AM_SIGNAL_PM_CLOSE_EXECUTION_MODE
        or spec.strategy_id == INDEX_VOL_AM_PM_BASE_SLEEVE_ID
    )
    evidence, _returns, _dates, paper_result = _run_one(
        executor,
        spec,
        view=view,
        universe=universe,
        period=source_period,
        cost_bps=PERSONAL_BASE_SLEEVE_COST_BPS,
        lookback_days=closure.required_lookback_trading_days,
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
    written = view.write_artifact(
        category="base-sleeve",
        suffix="json",
        payload=_canonical_bytes(document),
    )
    reference = {
        "schema_version": PERSONAL_BASE_SLEEVE_REFERENCE_SCHEMA,
        "artifact_schema_version": document["schema_version"],
        "archive_member": written.archive_member,
        "sha256": written.sha256,
        "strategy_id": document["strategy"]["strategy_id"],
        "cohort_id": document["cohort"]["cohort_id"],
        "universe_id": document["universe"]["universe_id"],
        "role": PERSONAL_BASE_SLEEVE_ROLE,
        "ranking_role": PERSONAL_BASE_SLEEVE_RANKING_ROLE,
        "candidate_count_contribution": 0,
    }
    return reference, written, written.sha256


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
    view: PersonalResearchDataView,
    universe: PersonalResolvedUniverseMembership,
    fold_periods: tuple[tuple[str, str], ...],
    holdout_period: tuple[str, str],
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
            view=view,
            universe=universe,
            period=period,
            cost_bps=policy.base_cost_bps,
            lookback_days=closure.required_lookback_trading_days,
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
        "data_quality_selection": all(
            _run_is_selection_eligible(run) for run in validation_runs
        ),
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
        view=view,
        universe=universe,
        period=(fold_periods[0][0], fold_periods[-1][1]),
        cost_bps=policy.stress_cost_bps,
        lookback_days=closure.required_lookback_trading_days,
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
        "data_quality_selection": _run_is_selection_eligible(stress),
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
        view=view,
        universe=universe,
        period=holdout_period,
        cost_bps=policy.base_cost_bps,
        lookback_days=closure.required_lookback_trading_days,
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




def _unexpected_candidate(
    spec: StrategySpec,
    closure: PlanDependencyClosure,
    error: BaseException,
    *,
    execution_contract: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
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
        with install_deadline(request.deadline):
            return self._run(request)

    def _run(self, request: PersonalResearchRequest) -> PersonalResearchRun:
        view = request.data_view
        if not isinstance(view, PersonalResearchDataView):
            raise TypeError("PersonalResearchDataView required")
        if view.kind not in {OFFLINE_FIXTURE_KIND, CONTAINER_EPHEMERAL_KIND}:
            raise PersonalResearchInputError(
                "personal DRAFT requires an OfflineFixture or container view"
            )
        if view.controlled_eligible:
            raise PersonalResearchInputError(
                "Controlled views cannot feed personal DRAFT"
            )
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
        if execution_mode == AM_SIGNAL_PM_CLOSE_EXECUTION_MODE:
            if view.decision_cutoff != DEFAULT_DECISION_CUTOFF:
                raise PersonalResearchInputError(
                    "active AM→PM uses morning_close only"
                )
        elif (
            view.kind != OFFLINE_FIXTURE_KIND
            or not view.allows_legacy_session_close
            or view.decision_cutoff != LEGACY_SESSION_CLOSE_CUTOFF
        ):
            raise PersonalResearchInputError(
                "session_close is legacy OfflineFixture DRAFT and is not "
                "selectable by cloud or container composition"
            )
        try:
            universe_selector = universe_selector.with_decision_cutoff(
                view.decision_cutoff
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
        required = tuple(
            sorted(
                {
                    dataset
                    for closure in closures
                    for dataset in closure.required_datasets
                }
            )
        )
        try:
            snapshot = prepare_draft_snapshot(
                view,
                required_datasets=required,
                period_start=start_day.isoformat(),
                period_end=end_day.isoformat(),
                closure_digests=tuple(c.closure_digest for c in closures),
            )
        except Exception as exc:
            message = str(exc)
            if "does not exist" in message or "database does not exist" in message:
                raise PersonalResearchInputError(message) from exc
            raise
        snapshot_manifest = dict(snapshot.manifest)
        source_sync = view.source_sync_evidence(
            snapshot_manifest,
            required_datasets=required,
        )
        try:
            universe, universe_breadth = resolve_personal_universe_with_evidence(
                view,
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
        bar_coverage = view.observed_bar_coverage(
            universe,
            minimum_ratio=self.policy.min_observed_bar_coverage,
        )
        corporate_actions = view.corporate_action_check(
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
            or not source_sync.get("execution_allowed")
            or universe_breadth["status"] != "PASS"
            or periods is None
        ):
            reason = (
                "observed_bar_coverage_below_threshold"
                if bar_coverage["status"] != "PASS"
                else (
                    "source_sync_evidence_unusable"
                    if not source_sync.get("execution_allowed")
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
                with prepared_frame_scope(view):
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
                        _base_sleeve_ref,
                        base_sleeve_artifact_digest,
                    ) = _write_continuous_base_sleeve_artifact(
                        executor,
                        base_spec,
                        base_closure,
                        view=view,
                        universe=universe,
                        source_period=(fold_periods[0][0], holdout_period[1]),
                        cohort_digest=cohort_ref["cohort_digest"],
                        execution_mode=execution_mode,
                        execution_contract=execution_contract,
                    )
            candidate_execution = {
                **candidate_execution,
                "model": "serial",
                "worker_processes": 1,
                "max_parallel_bound": 1,
            }
            with prepared_frame_scope(view):
                for spec, closure in zip(specs, closures, strict=True):
                    if request.deadline is not None:
                        request.deadline.check()
                    try:
                        candidates.append(
                            _candidate_evaluation(
                                executor,
                                spec,
                                closure,
                                view=view,
                                universe=universe,
                                fold_periods=fold_periods,
                                holdout_period=holdout_period,
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
        verify_draft_snapshot(view)
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
                "manifest_artifact": snapshot.snapshot_id,
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
        report_json = view.write_artifact(
            category="reports", suffix="json", payload=_canonical_bytes(report)
        )
        report_markdown = view.write_artifact(
            category="reports",
            suffix="md",
            payload=_markdown(report).encode("utf-8"),
        )
        return PersonalResearchRun(
            report_id=report_id,
            report_json=report_json,
            report_markdown=report_markdown,
            data_view=view,
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
    "PERSONAL_BAR_COVERAGE_EVIDENCE",
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
