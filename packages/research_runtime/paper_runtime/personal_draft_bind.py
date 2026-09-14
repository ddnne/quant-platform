"""Paper-runtime bind for a typed DRAFT data view.

Product never receives the sqlite path. This module is the only runtime that
may unwrap the private draft storage bind.
"""

from __future__ import annotations

import json
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import replace
from typing import Any

from paper_runtime.personal_prepared_frame import (
    _active_personal_prepared_frame,
    _personal_prepared_frame_scope,
)
from paper_runtime.personal_snapshot import (
    PersonalSnapshot,
    materialize_personal_snapshot,
    verify_personal_snapshot,
)
from paper_runtime.snapshot_identity import data_snapshot_id
from pit.personal_draft import personal_paper_read_session
from pit._draft_storage import (
    activate_prepared_sqlite,
    draft_artifact_root,
    draft_sqlite_path,
)
from pit.personal_research_view import (
    PersonalResearchDataView,
    PersonalResearchViewError,
    SnapshotIdentity,
)
from strategies.paper import Lifecycle, PaperRunConfig, PaperRunResult, run_paper
from strategies.spec import StrategySpec, interpret_strategy_spec, iter_feature_refs


def prepare_draft_snapshot(
    view: PersonalResearchDataView,
    *,
    required_datasets: Sequence[str],
    period_start: str,
    period_end: str,
    closure_digests: Sequence[str],
) -> SnapshotIdentity:
    if not isinstance(view, PersonalResearchDataView):
        raise PersonalResearchViewError("PersonalResearchDataView required")
    existing = getattr(view, "_prepared_snapshot", None)
    if isinstance(existing, PersonalSnapshot):
        verify_personal_snapshot(existing)
        return view.snapshot_identity()
    source = draft_sqlite_path(view)
    artifacts = draft_artifact_root(view)
    snapshot = materialize_personal_snapshot(
        source,
        artifacts / "snapshots",
        required_datasets=tuple(required_datasets),
        period_start=period_start,
        period_end=period_end,
        closure_digests=tuple(closure_digests),
    )
    verify_personal_snapshot(snapshot)
    activate_prepared_sqlite(view, snapshot.db_path)
    manifest = json.loads(snapshot.manifest_path.read_text(encoding="utf-8"))
    observed = str(manifest.get("observed_through") or "")
    identity = SnapshotIdentity(
        snapshot_id=snapshot.snapshot_id,
        logical_data_snapshot_id=snapshot.logical_data_snapshot_id,
        database_sha256=snapshot.database_sha256,
        required_datasets=snapshot.required_datasets,
        period_start=snapshot.period_start,
        period_end=snapshot.period_end,
        closure_digests=snapshot.closure_digests,
        manifest=manifest,
        observed_through=observed,
        observation_label="draft_bind_observation_cutoff",
        observation_promotable=False,
    )
    bind = getattr(view, "bind_snapshot_identity", None)
    if callable(bind):
        bind(identity)
    view._prepared_snapshot = snapshot  # type: ignore[attr-defined]
    return identity


def verify_draft_snapshot(view: PersonalResearchDataView) -> SnapshotIdentity:
    snapshot = getattr(view, "_prepared_snapshot", None)
    if not isinstance(snapshot, PersonalSnapshot):
        raise PersonalResearchViewError("draft snapshot has not been prepared")
    verify_personal_snapshot(snapshot)
    return view.snapshot_identity()


@contextmanager
def prepared_frame_scope(view: PersonalResearchDataView) -> Iterator[None]:
    identity = view.snapshot_identity()
    with _personal_prepared_frame_scope(
        db_path=draft_sqlite_path(view),
        snapshot_id=identity.logical_data_snapshot_id,
    ):
        yield


def _without_physical_db_path(result: PaperRunResult) -> PaperRunResult:
    reproduction = dict(result.reproducibility)
    reproduction.pop("db_path", None)
    reproduction["db_locator"] = "logical_data_snapshot_id"
    metadata = dict(result.backtest.metadata)
    metadata.pop("db_path", None)
    metadata["db_locator"] = "logical_data_snapshot_id"
    return replace(
        result,
        reproducibility=reproduction,
        backtest=replace(result.backtest, metadata=metadata),
    )


def run_bound_personal_paper(
    spec: StrategySpec,
    config: PaperRunConfig,
    *,
    view: PersonalResearchDataView,
    expected_snapshot_id: str,
) -> PaperRunResult:
    """Pin, session, and run one DRAFT paper against a bound view."""

    if type(config) is not PaperRunConfig:
        raise RuntimeError("personal paper execution requires an exact PaperRunConfig")
    if config.lifecycle is not Lifecycle.DRAFT:
        raise PermissionError(
            "local paper runtime is DRAFT-only; controlled execution requires "
            "Cloudflare/READY evidence (PENDING: CONTROLLED_AUTHORITY_UNPROVISIONED)"
        )
    if config.db_path is not None:
        raise RuntimeError("personal paper execution does not accept a database path")
    if not isinstance(view, PersonalResearchDataView):
        raise RuntimeError(
            "personal paper execution requires a bound PersonalResearchDataView"
        )
    db_path = draft_sqlite_path(view)
    try:
        before = data_snapshot_id(db_path)
    except (FileNotFoundError, RuntimeError) as exc:
        raise RuntimeError(str(exc) or "database snapshot is unavailable") from exc
    if before != expected_snapshot_id:
        raise RuntimeError("database snapshot does not match expected_snapshot_id")
    prepared_frame = _active_personal_prepared_frame(db_path)
    if (
        prepared_frame is not None
        and prepared_frame.snapshot_id != expected_snapshot_id
    ):
        raise RuntimeError(
            "personal prepared frame snapshot does not match expected_snapshot_id"
        )
    strategy = interpret_strategy_spec(spec)
    bound = replace(config, db_path=db_path)
    with personal_paper_read_session(db_path):
        result = run_paper(strategy, bound, store=None)
    try:
        after = data_snapshot_id(db_path)
    except (FileNotFoundError, RuntimeError) as exc:
        raise RuntimeError(str(exc) or "database snapshot is unavailable") from exc
    if after != expected_snapshot_id:
        raise RuntimeError(
            "database snapshot changed during personal paper execution"
        )
    if type(result) is not PaperRunResult:
        raise RuntimeError(
            "personal paper execution returned a noncanonical DRAFT result"
        )
    return _without_physical_db_path(result)


def execute_personal_draft(
    executor: Any,
    spec: StrategySpec,
    *,
    view: PersonalResearchDataView,
    universe: Any,
    period: tuple[str, str],
    cost_bps: float,
    lookback_days: int,
    execution_mode: str,
    starting_capital: float = 1_000_000.0,
    short_financing_annual_rate: float | None = None,
    short_financing_enabled: bool = False,
    short_financing_spread_bp: float | None = None,
    short_financing_fallback_repo_annual_bp: float = 0.0,
    short_financing_auto_load_repo: bool = False,
    leverage_financing_enabled: bool = False,
    lifecycle: Any,
    price_basis: Any,
) -> PaperRunResult:
    identity = view.snapshot_identity()
    config = PaperRunConfig(
        start=period[0],
        end=period[1],
        universe=universe,
        execution_mode=execution_mode,
        cost_bps=cost_bps,
        starting_capital=starting_capital,
        lookback_days=lookback_days,
        lifecycle=lifecycle,
        price_basis=price_basis,
        short_financing_enabled=short_financing_enabled,
        short_financing_spread_bp=short_financing_spread_bp,
        short_financing_fallback_repo_annual_bp=short_financing_fallback_repo_annual_bp,
        short_financing_auto_load_repo=short_financing_auto_load_repo,
        leverage_financing_enabled=leverage_financing_enabled,
    )
    return executor.execute(
        spec,
        config,
        expected_snapshot_id=identity.logical_data_snapshot_id,
        approved_feature_refs=iter_feature_refs(spec),
        view=view,
    )


def paper_config_fields(result_config: Mapping[str, Any] | None = None) -> dict[str, Any]:
    return dict(result_config or {})


__all__ = [
    "execute_personal_draft",
    "prepare_draft_snapshot",
    "prepared_frame_scope",
    "run_bound_personal_paper",
    "verify_draft_snapshot",
]
