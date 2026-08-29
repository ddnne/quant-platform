"""Small, deterministic research loop for one person's local paper database.

This module intentionally does not participate in the controlled-pilot or
mass-research authority chains.  It snapshots one local SQLite database,
evaluates a bounded set of closed ``StrategySpec`` values, and emits DRAFT
paper evidence for human review.  It cannot promote a strategy or place an
order.
"""

from __future__ import annotations

import calendar
import hashlib
import itertools
import json
import os
import sqlite3
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
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
from price_basis import PERSONAL_RETROSPECTIVE_ADJUSTED
from strategies.paper import Lifecycle, PaperRunConfig, PaperRunResult
from strategies.spec import StrategySpec, iter_feature_refs, strategy_spec_digest

from research.dependency_closure import (
    ContractDependency,
    PlanDependencyClosure,
    build_strategy_dependency_closure,
)
from research.factor_cohorts import (
    COHORT_REGISTRY_VERSION,
    PERSONAL_EXECUTABLE_COHORT_IDS,
    ResearchCohort,
    get_research_cohort,
    personal_specs_for_cohort,
)
from research.paper_candidate_specs import (
    build_cross_section_hold_strategy_spec,
    build_fundamentals_hold_strategy_spec,
    build_multi_day_hold_strategy_spec,
)
from research.stats_metrics import sharpe_ratio
from research.universe_contract import (
    ResolvedUniverseMembership,
    resolve_tse_prime_with_fins_evidence,
)


PERSONAL_RESEARCH_REPORT_VERSION = "personal-research-report/v4"
PERSONAL_DECISION_POLICY = "personal_drawdown_cost_stress/v3"
PERSONAL_DATA_PROFILE = "personal-japan-equities-paper/v2"
PERSONAL_BAR_COVERAGE_EVIDENCE = "observed-pit-market-breadth/v1"


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
    min_observed_bar_coverage: float = 0.995
    min_prime_fins_breadth: float = 0.95

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
            raise ValueError("personal research is intentionally serial")
        if not 0.0 < self.min_observed_bar_coverage <= 1.0:
            raise ValueError("min_observed_bar_coverage must be in (0, 1]")
        if not 0.0 < self.min_prime_fins_breadth <= 1.0:
            raise ValueError("min_prime_fins_breadth must be in (0, 1]")
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
            "min_prime_fins_breadth": self.min_prime_fins_breadth,
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


_UNIVERSE = ContractDependency(
    kind="universe",
    dependency_id="tse_prime_with_fins",
    version="tse-prime-with-fins/v1",
    dataset_dependencies=("equities_master", "fins_summary"),
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
            specs = tuple(personal_specs_for_cohort(cohort_id))
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


def _closures(
    specs: Sequence[StrategySpec],
    *,
    start: str,
    end: str,
    policy: PersonalResearchPolicy,
    cohort_ref: dict[str, str] | None = None,
) -> tuple[PlanDependencyClosure, ...]:
    closures: list[PlanDependencyClosure] = []
    for spec in specs:
        spec_hash = strategy_spec_digest(spec)
        plan_body = {
            "profile": PERSONAL_DATA_PROFILE,
            "strategy_spec": spec.to_dict(),
            "period_start": start,
            "period_end": end,
            "policy": policy.to_dict(),
        }
        if cohort_ref is not None:
            plan_body["strategy_cohort"] = cohort_ref
        closures.append(
            build_strategy_dependency_closure(
                plan_id=f"personal:{spec.strategy_id}:{spec_hash[7:19]}",
                plan_digest=_digest(plan_body),
                spec=spec,
                universe_dependencies=(_UNIVERSE,),
                evaluation_dependency=_EVALUATION,
                risk_dependency=_RISK,
                cost_dependency=_COST,
                research_data_profile_id=PERSONAL_DATA_PROFILE,
                period_start=start,
                period_end=end,
            )
        )
    return tuple(closures)


def _periods(
    universe: ResolvedUniverseMembership,
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


def _observed_market_bar_coverage(
    db_path: Path,
    universe: ResolvedUniverseMembership,
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
        selects: list[str] = []
        for table in ("jquants_daily_bars", "jquants_daily_bars_revisions"):
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
        for table in ("jquants_records", "jquants_records_revisions"):
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


def _daily_returns(result: PaperRunResult, starting_capital: float) -> list[float]:
    previous = float(starting_capital)
    values: list[float] = []
    for row in result.equity_curve:
        current = float(row["equity"])
        if previous <= 0.0:
            raise RuntimeError("paper equity became non-positive")
        values.append(current / previous - 1.0)
        previous = current
    return values


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


def _universe_corporate_action_check(
    db_path: Path,
    *,
    universe: ResolvedUniverseMembership,
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
        selects: list[str] = []
        for table in ("jquants_daily_bars", "jquants_daily_bars_revisions"):
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
        for table in ("jquants_records", "jquants_records_revisions"):
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
) -> tuple[dict[str, Any], list[float]]:
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
    return (
        {
            "run_id": result.run_id,
            "experiment_id": result.experiment_id,
            "period": {"start": config.start, "end": config.end},
            "cost_bps": config.cost_bps,
            "total_return_post_cost": float(
                metrics.get("total_return_post_cost", 0.0)
            ),
            "annualized_sharpe": None if sharpe is None else float(sharpe),
            "sharpe_periods_per_year": 252,
            "max_drawdown": abs(float(metrics.get("max_drawdown", 0.0))),
            "fills": int(metrics.get("num_trades", len(result.trades))),
            "risk_status": risk["status"],
            "paper_artifact": paper_path,
            "risk_artifact": risk_path,
        },
        returns,
    )


def _run_one(
    executor: PersonalPaperExecutionService,
    spec: StrategySpec,
    *,
    db_path: Path,
    snapshot_id: str,
    universe: ResolvedUniverseMembership,
    period: tuple[str, str],
    cost_bps: float,
    lookback_days: int,
    output_root: Path,
    max_drawdown: float,
) -> tuple[dict[str, Any], list[float]]:
    period_universe = ResolvedUniverseMembership(
        period_start=period[0],
        period_end=period[1],
        decision_memberships=tuple(
            (day, codes)
            for day, codes in universe.decision_memberships
            if period[0] <= day <= period[1]
        ),
    )
    config = PaperRunConfig(
        start=period[0],
        end=period[1],
        db_path=db_path,
        universe=period_universe,
        execution_mode="next_close",
        cost_bps=cost_bps,
        starting_capital=1_000_000.0,
        lookback_days=_calendar_lookback_days(lookback_days),
        lifecycle=Lifecycle.DRAFT,
        price_basis=PERSONAL_RETROSPECTIVE_ADJUSTED,
        short_financing_enabled=False,
    )
    result = executor.execute(
        spec,
        config,
        expected_snapshot_id=snapshot_id,
        approved_feature_refs=iter_feature_refs(spec),
    )
    return _paper_evidence(
        result,
        config=config,
        output_root=output_root,
        max_drawdown=max_drawdown,
    )


def _candidate_evaluation(
    executor: PersonalPaperExecutionService,
    spec: StrategySpec,
    closure: PlanDependencyClosure,
    *,
    snapshot: PersonalSnapshot,
    universe: ResolvedUniverseMembership,
    fold_periods: tuple[tuple[str, str], ...],
    holdout_period: tuple[str, str],
    output_root: Path,
    policy: PersonalResearchPolicy,
) -> dict[str, Any]:
    validation_runs: list[dict[str, Any]] = []
    pooled_returns: list[float] = []
    for period in fold_periods:
        evidence, returns = _run_one(
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
        )
        validation_runs.append(evidence)
        pooled_returns.extend(returns)

    pooled = sharpe_ratio(pooled_returns, periods_per_year=252.0).get("sharpe")
    positive = sum(
        run["total_return_post_cost"] > 0.0 for run in validation_runs
    )
    fills = sum(int(run["fills"]) for run in validation_runs)
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
    candidate: dict[str, Any] = {
        "strategy_id": spec.strategy_id,
        "strategy_spec_version": spec.version,
        "strategy_spec_digest": strategy_spec_digest(spec),
        "dependency_closure_digest": closure.closure_digest,
        "decision": "REJECT",
        "reasons": [name for name, passed in validation_checks.items() if not passed],
        "validation": {
            "runs": validation_runs,
            "positive_folds": positive,
            "total_fills": fills,
            "pooled_annualized_sharpe": None if pooled is None else float(pooled),
            "sharpe_periods_per_year": 252,
            "checks": validation_checks,
        },
        "stress": None,
        "holdout": None,
        "decision_basis": "validation_and_cost_stress",
    }
    if not all(validation_checks.values()):
        return candidate

    stress, _ = _run_one(
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
    )
    stress_checks = {
        "positive_return": stress["total_return_post_cost"] > 0.0,
        "nonnegative_sharpe": stress["annualized_sharpe"] is not None
        and stress["annualized_sharpe"] >= 0.0,
        "drawdown": stress["max_drawdown"] <= policy.max_drawdown,
        "risk_agent": stress["risk_status"] == "pass",
    }
    candidate["stress"] = {**stress, "checks": stress_checks}
    if not all(stress_checks.values()):
        candidate["reasons"] = [
            f"stress:{name}" for name, passed in stress_checks.items() if not passed
        ]
        return candidate

    holdout, _ = _run_one(
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
    candidate["decision"] = "HOLD"
    candidate["reasons"] = ["human_review_required"]
    return candidate


def _markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Personal Paper Research",
        "",
        f"- Report: `{report['report_id']}`",
        f"- Snapshot: `{report['snapshot']['snapshot_id']}`",
        f"- Data period: {report['period']['data_start']} to {report['period']['end']}",
        f"- Evaluation start: {report['period']['evaluation_start'] or 'none'}",
        f"- Warmup sessions: {report['period']['warmup_sessions']}",
        f"- Analysis: {report['summary']['analysis_status']}",
        f"- Candidates: {report['summary']['candidate_count']}",
        f"- Evaluated: {report['summary']['evaluated_count']}",
        f"- HOLD: {report['summary']['hold_count']}",
        f"- Price basis: {report['price_basis']['id']} (retrospective DRAFT only)",
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
        ]
    )
    return "\n".join(lines)


class PersonalResearchService:
    """Serial local research service; no network, model, or promotion surface."""

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
        specs, cohort = _validated_specs(
            request.specs,
            self.policy,
            request.cohort_id,
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
            cohort_ref=cohort_ref,
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
        universe, universe_breadth = resolve_tse_prime_with_fins_evidence(
            snapshot.db_path,
            period_start=start_day.isoformat(),
            period_end=end_day.isoformat(),
        )
        universe_breadth = {
            **universe_breadth,
            "minimum_ratio": self.policy.min_prime_fins_breadth,
            "status": (
                "PASS"
                if universe_breadth["minimum_daily_ratio"]
                >= self.policy.min_prime_fins_breadth
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
                        "prime_fins_breadth_below_threshold"
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
                        "decision": "SKIPPED",
                        "reasons": [reason],
                        "validation": None,
                        "stress": None,
                        "holdout": None,
                        "decision_basis": "validation_and_cost_stress",
                    }
                )
        else:
            fold_periods, holdout_period = periods
            executor = PersonalPaperExecutionService()
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
                        )
                    )
                except Exception as exc:  # preserve a report; CLI still exits 1
                    unexpected_errors += 1
                    detail = " ".join(str(exc).split())[:400]
                    candidates.append(
                        {
                            "strategy_id": spec.strategy_id,
                            "strategy_spec_version": spec.version,
                            "strategy_spec_digest": strategy_spec_digest(spec),
                            "dependency_closure_digest": closure.closure_digest,
                            "decision": "SKIPPED",
                            "reasons": [f"unexpected:{type(exc).__name__}"],
                            "validation": None,
                            "stress": None,
                            "holdout": None,
                            "decision_basis": "validation_and_cost_stress",
                            "error": {
                                "type": type(exc).__name__,
                                "detail": detail or "no detail",
                            },
                        }
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
            "candidates": candidates,
            "summary": {
                "analysis_status": analysis_status,
                "candidate_count": len(candidates),
                "evaluated_count": evaluated_count,
                "hold_count": hold_count,
                "unexpected_errors": unexpected_errors,
            },
            "live_orders_enabled": False,
            "automatic_promotion": False,
            "model_calls": 0,
            "estimated_ai_cost_usd": 0.0,
        }
        if cohort_ref is not None:
            body["strategy_cohort"] = cohort_ref
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
        )


__all__ = [
    "PERSONAL_DECISION_POLICY",
    "PERSONAL_RESEARCH_REPORT_VERSION",
    "PersonalResearchInputError",
    "PersonalResearchPolicy",
    "PersonalResearchRequest",
    "PersonalResearchRun",
    "PersonalResearchService",
    "PERSONAL_EXECUTABLE_COHORT_IDS",
    "default_personal_specs",
]
