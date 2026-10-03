"""Minimal paper-only execution boundary for a single-user research loop.

The service accepts only the inputs needed to reproduce one local backtest:
an exact ``StrategySpec``, a pathless DRAFT ``PaperRunConfig``, a bound
``PersonalResearchDataView``, the expected logical snapshot id, and its compiled
dependency closure. Storage path, connection, and read-session
lifetime stay in the paper-runtime bind.  It has no READY, Trader, promotion,
broker, or authority DTO surface.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date

from core.universe import RawFixedUniverseError, ResolvedDailyUniverse
from paper_runtime.personal_draft_bind import run_bound_personal_paper
from pit.personal_research_view import PersonalResearchDataView
from research.dependency_closure import (
    PlanDependencyClosure,
    PlanDependencyClosureError,
    validate_strategy_dependency_binding,
)
from strategies.paper import Lifecycle, PaperRunConfig, PaperRunResult
from strategies.spec import StrategySpec


class PersonalPaperExecutionRejected(ValueError):
    """Raised when a personal paper run is not reproducibly pinned."""


def _require_snapshot_id(value: str) -> str:
    snapshot_id = str(value or "").strip()
    if (
        len(snapshot_id) != 71
        or not snapshot_id.startswith("sha256:")
        or any(character not in "0123456789abcdef" for character in snapshot_id[7:])
    ):
        raise PersonalPaperExecutionRejected(
            "expected_snapshot_id must be a canonical sha256 digest"
        )
    return snapshot_id


def _require_explicit_period(config: PaperRunConfig) -> None:
    try:
        start = date.fromisoformat(str(config.start))
        end = date.fromisoformat(str(config.end))
    except ValueError as exc:
        raise PersonalPaperExecutionRejected(
            "personal paper execution requires an explicit ISO date period"
        ) from exc
    if (
        start.isoformat() != config.start
        or end.isoformat() != config.end
        or start > end
    ):
        raise PersonalPaperExecutionRejected(
            "personal paper execution requires an explicit ISO date period"
        )


def _require_resolved_daily_universe(
    config: PaperRunConfig,
) -> ResolvedDailyUniverse:
    universe = config.universe
    memberships = getattr(universe, "membership_by_date", None)
    if universe is None or not isinstance(memberships, Mapping) or not memberships:
        raise PersonalPaperExecutionRejected(
            "personal paper execution requires a resolved daily universe"
        )
    if (
        str(getattr(universe, "period_start", "")) != config.start
        or str(getattr(universe, "period_end", "")) != config.end
    ):
        raise PersonalPaperExecutionRejected(
            "resolved daily universe period does not match PaperRunConfig"
        )
    try:
        return ResolvedDailyUniverse(universe)
    except (RawFixedUniverseError, TypeError, ValueError) as exc:
        raise PersonalPaperExecutionRejected(
            "personal paper execution requires a valid resolved daily universe"
        ) from exc


class PersonalPaperExecutionService:
    """Execute one reproducible, local, DRAFT-only paper run."""

    __slots__ = ()

    def execute(
        self,
        spec: StrategySpec,
        config: PaperRunConfig,
        *,
        expected_snapshot_id: str,
        dependency_closure: PlanDependencyClosure,
        view: PersonalResearchDataView | None = None,
    ) -> PaperRunResult:
        if type(spec) is not StrategySpec:
            raise PersonalPaperExecutionRejected(
                "personal paper execution requires an exact StrategySpec"
            )
        if type(config) is not PaperRunConfig:
            raise PersonalPaperExecutionRejected(
                "personal paper execution requires an exact PaperRunConfig"
            )
        if config.lifecycle is not Lifecycle.DRAFT:
            raise PersonalPaperExecutionRejected(
                "personal paper execution is DRAFT-only"
            )
        if config.db_path is not None:
            raise PersonalPaperExecutionRejected(
                "personal paper execution does not accept a database path"
            )

        _require_explicit_period(config)
        resolved_universe = _require_resolved_daily_universe(config)
        expected_snapshot = _require_snapshot_id(expected_snapshot_id)
        if not isinstance(view, PersonalResearchDataView):
            raise PersonalPaperExecutionRejected(
                "personal paper execution requires a bound PersonalResearchDataView"
            )
        try:
            feature_refs = validate_strategy_dependency_binding(
                spec, dependency_closure
            )
            identity = view.snapshot_identity()
            if identity.logical_data_snapshot_id != expected_snapshot:
                raise PersonalPaperExecutionRejected(
                    "snapshot identity does not match expected_snapshot_id"
                )
            if (
                dependency_closure.closure_digest not in identity.closure_digests
                or not set(dependency_closure.required_datasets).issubset(
                    identity.required_datasets
                )
                or not (
                    identity.period_start
                    <= dependency_closure.period_start
                    <= config.start
                    <= config.end <= dependency_closure.period_end <= identity.period_end
                )
            ):
                raise PersonalPaperExecutionRejected(
                    "dependency closure is outside the bound snapshot or run period"
                )
            result = run_bound_personal_paper(
                spec,
                config,
                view=view,
                expected_snapshot_id=expected_snapshot,
            )
        except (FileNotFoundError, RuntimeError, PlanDependencyClosureError) as exc:
            raise PersonalPaperExecutionRejected(str(exc)) from exc
        if (
            type(result) is not PaperRunResult
            or result.lifecycle is not Lifecycle.DRAFT
        ):
            raise PersonalPaperExecutionRejected(
                "personal paper execution returned a noncanonical DRAFT result"
            )
        if result.reproducibility.get("data_snapshot_id") != expected_snapshot:
            raise PersonalPaperExecutionRejected(
                "paper result reports a different data snapshot"
            )

        strategy_params = result.reproducibility.get("strategy_params")
        if (
            result.reproducibility.get("strategy_id") != spec.strategy_id
            or not isinstance(strategy_params, Mapping)
            or strategy_params.get("strategy_spec") != spec.to_dict()
        ):
            raise PersonalPaperExecutionRejected(
                "paper result does not match the exact StrategySpec"
            )

        if (
            result.reproducibility.get("universe_rule_digest")
            != resolved_universe.rule_digest
            or result.reproducibility.get("resolved_universe_digest")
            != resolved_universe.resolved_membership_digest
        ):
            raise PersonalPaperExecutionRejected(
                "paper result universe does not match the resolved daily universe"
            )

        expected_versions = {ref.id: str(ref.version) for ref in feature_refs}
        consumed_versions = result.reproducibility.get("feature_versions")
        if consumed_versions != expected_versions:
            raise PersonalPaperExecutionRejected(
                "paper result FeatureRefs do not match the approved StrategySpec"
            )
        return result


__all__ = [
    "PersonalPaperExecutionRejected",
    "PersonalPaperExecutionService",
]
