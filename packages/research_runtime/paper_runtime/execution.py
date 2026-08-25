"""Paper-runtime DTO adapter — ADR §8.2 name-collision twin.

This is an offline DRAFT compatibility adapter. ``paper_runtime`` does not
re-export this module, and it is not a controlled PAPER authority.

``PaperExecutionService.execute`` here is a DTO adapter only: it translates
:class:`AuthorizedPaperExecutionRequest` and delegates to the strong
offline service. It never imports or calls ``strategies.paper.run_paper``.

Importing this module does not arm continuous paper, declare READY, or
Mass GO. Keep all three ``execution`` modules (core fill timing / this
helper / offline paper service). See ADR §8.2.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Protocol

from strategies.paper import PaperRunConfig, PaperRunResult
from strategies.spec import StrategySpec


@dataclass(frozen=True)
class AuthorizedPaperExecutionRequest:
    """Compatibility envelope for the strong :class:`PaperExecutionService`.

    ``strategy`` must be a :class:`~strategies.spec.StrategySpec` at execute
    time. A raw strategy object is rejected; this adapter does not call
    ``run_paper``.
    """

    authorization_id: str
    mode: str
    strategy: Any
    strategy_spec_hash: str
    config: PaperRunConfig
    max_gross: float | None = None
    ready_snapshot_id: str | None = None
    feature_ref_versions: Mapping[str, str] | None = None
    ready_manifest_digest: str = ""
    readiness_attestation_id: str = ""
    plan_set_digest: str = ""
    dependency_closure_digest: str = ""
    universe: tuple[str, ...] = ()
    period_start: str = ""
    period_end: str = ""
    cost_scenario: str = "default"
    expires_at: str = ""
    profile_digest: str = ""


class PaperStore(Protocol):
    pass


class PaperExecutionService:
    """DTO adapter for the offline service in ``execution.paper_service``."""

    __slots__ = ("_store",)

    def __init_subclass__(cls, **kwargs: Any) -> None:
        raise TypeError("paper_runtime PaperExecutionService is final")

    def __init__(self, store: Any = None) -> None:
        self._store = store

    def execute(
        self,
        request: Any,
        spec: StrategySpec | None = None,
        config: PaperRunConfig | None = None,
    ) -> PaperRunResult:
        # Load agents first so agents ↔ execution (intentional cycle) can finish
        # before this adapter imports the strong service.
        import agents as _agents  # noqa: F401
        from execution.paper_service import (
            PaperExecutionRejected,
            PaperExecutionService as StrongPaperExecutionService,
        )

        strong = StrongPaperExecutionService(paper_store=self._store)
        if spec is not None and config is not None:
            return strong.execute(request, spec, config)
        if not isinstance(request, AuthorizedPaperExecutionRequest):
            raise PaperExecutionRejected(
                "paper_runtime DTO execute requires AuthorizedPaperExecutionRequest"
            )
        return strong.execute_runtime_dto(request)


__all__ = [
    "AuthorizedPaperExecutionRequest",
    "PaperExecutionService",
]
