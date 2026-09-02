"""Container-temp DRAFT data view. Storage path is never exposed.

Cloud/container composition may only select morning_close. session_close is
legacy OfflineFixture DRAFT and is rejected here.
"""

from __future__ import annotations

from pathlib import Path

from pit.personal_research_view import (
    CONTAINER_EPHEMERAL_KIND,
    DEFAULT_DECISION_CUTOFF,
    LEGACY_SESSION_CLOSE_CUTOFF,
    PersonalResearchDataView,
    PersonalResearchViewError,
    _SqliteDraftDataView,
    _bind_draft_source,
    _require_cutoff,
    require_ephemeral_path,
    _is_ephemeral_fs,
)


class ContainerEphemeralDataView(_SqliteDraftDataView):
    """Ephemeral Container sqlite adapter. DRAFT-only, not Controlled-eligible."""

    @classmethod
    def bind(
        cls,
        source: str | Path,
        *,
        artifact_root: str | Path,
        decision_cutoff: str = DEFAULT_DECISION_CUTOFF,
    ) -> ContainerEphemeralDataView:
        cutoff = _require_cutoff(decision_cutoff)
        if cutoff == LEGACY_SESSION_CLOSE_CUTOFF:
            raise PersonalResearchViewError(
                "session_close is legacy OfflineFixture DRAFT and is not "
                "selectable by cloud or container composition"
            )
        source_path = require_ephemeral_path(Path(source))
        artifacts = require_ephemeral_path(Path(artifact_root))
        if not source_path.is_file():
            raise PersonalResearchViewError(
                f"container snapshot is missing: {source_path}"
            )
        artifacts.mkdir(parents=True, exist_ok=True)
        source_path = _bind_draft_source(source_path, artifacts)
        from pit.personal_research_view import _capture_observation

        observed, label, promotable = _capture_observation(source_path)
        return cls(
            kind=CONTAINER_EPHEMERAL_KIND,
            source=source_path,
            artifacts=artifacts,
            decision_cutoff=DEFAULT_DECISION_CUTOFF,
            allow_legacy_session_close=False,
            observed_through=observed,
            observation_label=label,
            observation_promotable=promotable,
        )


def bind_container_ephemeral(
    source: str | Path,
    *,
    artifact_root: str | Path,
    decision_cutoff: str = DEFAULT_DECISION_CUTOFF,
) -> PersonalResearchDataView:
    return ContainerEphemeralDataView.bind(
        source,
        artifact_root=artifact_root,
        decision_cutoff=decision_cutoff,
    )


__all__ = [
    "ContainerEphemeralDataView",
    "bind_container_ephemeral",
]
