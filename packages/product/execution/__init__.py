"""Phase 7 execution authority layer.

This package is the single positive capability that reaches the trusted paper
runtime. The agent orchestrator (:class:`agents.pipeline.AgentPaperPipeline`)
is capability-free; it hands an :class:`agents.types.AuthorizedPaperExecutionRequest`
plus its source :class:`strategies.spec.StrategySpec` to
:class:`PaperExecutionService`, which re-derives every authorization field,
verifies the pinned data snapshot, resolves every FeatureRef against the
governed registry, and only then delegates to :func:`strategies.paper.run_paper`.

Nothing else in the agent path may call ``run_paper`` directly.
"""

from .paper_service import (
    ControlledPilotExecutionService,
    ControlledPilotRunConfig,
    ImmutableSnapshotHandle,
    OfflineFixturePaperService,
    PaperExecutionRejected,
    PaperExecutionService,
)
from .trader_authority import (
    TraderAuthorizationPublicKeyRegistry,
    VerifiedTraderAuthorization,
    open_controlled_trader_authorization_issuer,
)

__all__ = [
    "ControlledPilotExecutionService",
    "ControlledPilotRunConfig",
    "ImmutableSnapshotHandle",
    "OfflineFixturePaperService",
    "PaperExecutionRejected",
    "PaperExecutionService",
    "TraderAuthorizationPublicKeyRegistry",
    "VerifiedTraderAuthorization",
    "open_controlled_trader_authorization_issuer",
]
