"""Offline DRAFT execution plus a fail-closed Controlled Pilot boundary.

The importable paper runtime cannot create controlled PAPER evidence.  The
dedicated execution authority is not provisioned, so its public boundary is
PENDING and has no path, store, verifier, or transport injection surface.
"""

from __future__ import annotations

from importlib import import_module


_EXPORT_MODULES = {
    "CONTROLLED_AUTHORITY_UNPROVISIONED": ".paper_service",
    "ControlledPilotExecutionService": ".paper_service",
    "ControlledPilotPending": ".paper_service",
    "OfflineFixturePaperService": ".paper_service",
    "PaperExecutionRejected": ".paper_service",
    "PaperExecutionService": ".paper_service",
    "CONTROLLED_ARTIFACT_AUTHORITY_UNPROVISIONED": ".controlled_artifacts",
    "ControlledArtifactAuthorityPending": ".controlled_artifacts",
    "ControlledArtifactPublicKeyRegistry": ".controlled_artifacts",
    "ControlledArtifactVerificationError": ".controlled_artifacts",
    "VerifiedControlledExecutionArtifacts": ".controlled_artifacts",
    "load_verified_controlled_execution_artifacts": ".controlled_artifacts",
    "TraderAuthorizationBinding": ".trader_authority",
    "TraderAuthorizationPublicKeyRegistry": ".trader_authority",
    "VerifiedTraderAuthorization": ".trader_authority",
    "verify_exact_trader_authorization": ".trader_authority",
}


def __getattr__(name: str):
    """Preserve public imports without loading controlled authorities eagerly."""
    module_name = _EXPORT_MODULES.get(name)
    if module_name is None:
        raise AttributeError(name)
    value = getattr(import_module(module_name, __name__), name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))

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
