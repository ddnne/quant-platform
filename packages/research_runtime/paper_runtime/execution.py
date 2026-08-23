"""Paper-runtime exec helper — ADR §8.2 name-collision twin.

This is **not** the authorized paper choke point. The live path is
``execution.paper_service.PaperExecutionService``. ``paper_runtime`` does
not re-export this module.

Importing this module does not arm continuous paper, declare READY, or
Mass GO. Keep all three ``execution`` modules (core fill timing / this
helper / authorized paper service). See ADR §8.2.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Protocol

from strategies.paper import PaperRunConfig, PaperRunResult, run_paper


@dataclass(frozen=True)
class AuthorizedPaperExecutionRequest:
    authorization_id: str
    mode: str
    strategy: Any
    strategy_spec_hash: str
    config: PaperRunConfig
    max_gross: float | None = None
    ready_snapshot_id: str | None = None
    feature_ref_versions: Mapping[str, str] | None = None


class PaperStore(Protocol):
    pass


class PaperExecutionService:
    """Validates authorization envelope then runs paper."""

    def __init__(self, store: Any) -> None:
        self._store = store

    def execute(self, request: AuthorizedPaperExecutionRequest) -> PaperRunResult:
        if request.mode != "paper":
            raise ValueError("PaperExecutionService only accepts mode=paper")
        if not request.authorization_id:
            raise ValueError("authorization_id required")
        if not request.strategy_spec_hash:
            raise ValueError("strategy_spec_hash required")
        # Future: verify hash against StrategySpec, READY snapshot pin, FeatureRefs
        return run_paper(request.strategy, request.config, store=self._store)


__all__ = [
    "AuthorizedPaperExecutionRequest",
    "PaperExecutionService",
]
