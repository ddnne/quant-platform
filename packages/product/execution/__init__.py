"""Offline DRAFT execution plus a fail-closed Controlled Pilot boundary.

The importable paper runtime cannot create controlled PAPER evidence.  The
dedicated execution authority is not provisioned, so its public boundary is
PENDING and has no path, store, verifier, or transport injection surface.
"""

from .paper_service import (
    CONTROLLED_AUTHORITY_UNPROVISIONED,
    ControlledPilotExecutionService,
    ControlledPilotPending,
    OfflineFixturePaperService,
    PaperExecutionRejected,
    PaperExecutionService,
)
from .controlled_artifacts import (
    CONTROLLED_ARTIFACT_AUTHORITY_UNPROVISIONED,
    ControlledArtifactAuthorityPending,
    ControlledArtifactPublicKeyRegistry,
    ControlledArtifactVerificationError,
    VerifiedControlledExecutionArtifacts,
    load_verified_controlled_execution_artifacts,
)
from .trader_authority import (
    TraderAuthorizationBinding,
    TraderAuthorizationPublicKeyRegistry,
    VerifiedTraderAuthorization,
    verify_exact_trader_authorization,
)

__all__ = [
    "CONTROLLED_AUTHORITY_UNPROVISIONED",
    "CONTROLLED_ARTIFACT_AUTHORITY_UNPROVISIONED",
    "ControlledArtifactAuthorityPending",
    "ControlledArtifactPublicKeyRegistry",
    "ControlledArtifactVerificationError",
    "ControlledPilotExecutionService",
    "ControlledPilotPending",
    "OfflineFixturePaperService",
    "PaperExecutionRejected",
    "PaperExecutionService",
    "TraderAuthorizationBinding",
    "TraderAuthorizationPublicKeyRegistry",
    "VerifiedTraderAuthorization",
    "VerifiedControlledExecutionArtifacts",
    "load_verified_controlled_execution_artifacts",
    "verify_exact_trader_authorization",
]
