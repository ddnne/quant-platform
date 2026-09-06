"""Paper-runtime bind for a typed DRAFT data view.

Product never receives the sqlite path. This module is the only runtime that
may unwrap the private draft storage bind.
"""

from __future__ import annotations

import json
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from typing import Any

from paper_runtime.personal_prepared_frame import _personal_prepared_frame_scope
from paper_runtime.personal_snapshot import (
    PersonalSnapshot,
    materialize_personal_snapshot,
    verify_personal_snapshot,
)
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
from strategies.paper import PaperRunConfig, PaperRunResult
from strategies.spec import StrategySpec, iter_feature_refs


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
        db_path=draft_sqlite_path(view),
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
    )


def paper_config_fields(result_config: Mapping[str, Any] | None = None) -> dict[str, Any]:
    return dict(result_config or {})


__all__ = [
    "execute_personal_draft",
    "prepare_draft_snapshot",
    "prepared_frame_scope",
    "verify_draft_snapshot",
]
