"""Trusted paper execution boundary (Phase 7).

Sole production path for paper runs:
  PortfolioManager → Trader → AuthorizedPaperExecutionRequest
  → PaperExecutionService → run_paper

Orchestrators should not call strategies.paper.run_paper directly once
migrated; this service is the authorized choke point.
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
