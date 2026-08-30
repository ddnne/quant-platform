"""Minimal paper-only execution boundary for a single-user research loop.

The service accepts only the inputs needed to reproduce one local backtest:
an exact ``StrategySpec``, a DRAFT ``PaperRunConfig``, the expected logical
SQLite snapshot id, and the exact approved ``FeatureRef`` objects.  It has no
READY, Trader, promotion, broker, or authority DTO surface.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date
from pathlib import Path

from core.universe import RawFixedUniverseError, ResolvedDailyUniverse
from paper_runtime.personal_prepared_frame import _active_personal_prepared_frame
from paper_runtime.personal_read_session import _personal_paper_read_session
from paper_runtime.snapshot_identity import data_snapshot_id
from strategies.paper import Lifecycle, PaperRunConfig, PaperRunResult, run_paper
from strategies.spec import (
    FeatureRef,
    StrategySpec,
    interpret_strategy_spec,
    iter_feature_refs,
    resolve_feature_ref,
)


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


def _require_exact_approved_features(
    spec: StrategySpec,
    approved_feature_refs: Sequence[FeatureRef],
) -> tuple[FeatureRef, ...]:
    declared = iter_feature_refs(spec)
    approved = tuple(approved_feature_refs)
    if not approved or any(type(ref) is not FeatureRef for ref in approved):
        raise PersonalPaperExecutionRejected(
            "approved_feature_refs must contain exact FeatureRef objects"
        )
    if tuple(ref.to_dict() for ref in approved) != tuple(
        ref.to_dict() for ref in declared
    ):
        raise PersonalPaperExecutionRejected(
            "approved FeatureRefs do not exactly match the StrategySpec"
        )
    for ref in declared:
        try:
            resolve_feature_ref(ref)
        except (KeyError, ValueError) as exc:
            raise PersonalPaperExecutionRejected(
                f"FeatureRef {ref.id!r}@{ref.version!r} is not an approved signal"
            ) from exc
    return declared


class PersonalPaperExecutionService:
    """Execute one reproducible, local, DRAFT-only paper run."""

    __slots__ = ()

    def execute(
        self,
        spec: StrategySpec,
        config: PaperRunConfig,
        *,
        expected_snapshot_id: str,
        approved_feature_refs: Sequence[FeatureRef],
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
        if config.db_path is None:
            raise PersonalPaperExecutionRejected(
                "personal paper execution requires an explicit database path"
            )

        _require_explicit_period(config)
        resolved_universe = _require_resolved_daily_universe(config)
        expected_snapshot = _require_snapshot_id(expected_snapshot_id)
        feature_refs = _require_exact_approved_features(
            spec, approved_feature_refs
        )

        db_path = Path(config.db_path)
        try:
            before = data_snapshot_id(db_path)
        except (FileNotFoundError, RuntimeError) as exc:
            raise PersonalPaperExecutionRejected(str(exc)) from exc
        if before != expected_snapshot:
            raise PersonalPaperExecutionRejected(
                "database snapshot does not match expected_snapshot_id"
            )
        prepared_frame = _active_personal_prepared_frame(db_path)
        if (
            prepared_frame is not None
            and prepared_frame.snapshot_id != expected_snapshot
        ):
            raise PersonalPaperExecutionRejected(
                "personal prepared frame snapshot does not match "
                "expected_snapshot_id"
            )

        strategy = interpret_strategy_spec(spec)
        # Only the immutable paper computation opts into connection reuse.
        # The before/after snapshot verification remains outside this scope.
        with _personal_paper_read_session(db_path):
            result = run_paper(strategy, config, store=None)

        try:
            after = data_snapshot_id(db_path)
        except (FileNotFoundError, RuntimeError) as exc:
            raise PersonalPaperExecutionRejected(str(exc)) from exc
        if after != expected_snapshot:
            raise PersonalPaperExecutionRejected(
                "database snapshot changed during personal paper execution"
            )
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
