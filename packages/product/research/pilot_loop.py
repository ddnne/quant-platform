"""Controlled Pilot one-loop types. All execution routes remain capability-off.

Human ResearchIdea → ResearchMemo → FeatureProposal → 2–8 StrategySpec →
exact READY snapshot → budgeted paper → independent risk → SelectionDecision →
Knowledge.

Does not construct MassResearchScheduler. Does not arm Phase 7, Mass, READY,
live orders, or mass fan-out. generation_count default is 1.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from agents.types import FeatureProposal, ResearchMemo, RiskAudit
from knowledge.store import KnowledgeArtifact
from research.artifacts import ResearchIdea
from research.research_capabilities import research_capabilities
from selection.budget_ledger import MassResearchDisabledError
from selection.decision import SelectionDecision
from strategies.spec import StrategySpec

PILOT_LOOP_MIN_STRATEGY_SPECS: int = 2
PILOT_LOOP_MAX_STRATEGY_SPECS: int = 8
PILOT_LOOP_DEFAULT_GENERATION_COUNT: int = 1
PILOT_LOOP_PAPER_MODE: str = "paper"

CONTROLLED_PILOT_STAGES: tuple[str, ...] = (
    "ResearchIdea",
    "ResearchMemo",
    "FeatureProposal",
    "StrategySpec",
    "READY",
    "budgeted_paper",
    "independent_risk",
    "SelectionDecision",
    "Knowledge",
)

EXECUTION_ROUTES: tuple[str, ...] = (
    "data_ready",
    "generation",
    "mass_screen",
    "promotion",
    "paper_execution",
)


def _require_execution(*, caps: Mapping[str, Any] | None = None) -> Mapping[str, Any]:
    """Refuse unless research_capabilities() grants (they never do)."""
    snap = dict(caps or research_capabilities())
    denied = tuple(name for name in EXECUTION_ROUTES if not snap.get(name))
    if denied or snap.get("go") is not True:
        raise MassResearchDisabledError(
            "controlled pilot loop remains capability-off "
            f"(denied={list(denied or EXECUTION_ROUTES)}; go={snap.get('go')})"
        )
    return snap


@dataclass(frozen=True)
class ControlledPilotLoopPlan:
    """One human-in-the-loop generation. Types only; not a runnable mass job.

    Lineage is fixed at 1 cycle:
    Human ResearchIdea → ResearchMemo → FeatureProposal → 2–8 StrategySpec
    → exact READY snapshot → budgeted paper → independent risk
    → SelectionDecision → Knowledge.
    """

    idea: ResearchIdea | None = None
    memo: ResearchMemo | None = None
    feature_proposal: FeatureProposal | None = None
    strategy_specs: tuple[StrategySpec, ...] = field(default_factory=tuple)
    ready_snapshot_id: str = ""
    paper_mode: str = PILOT_LOOP_PAPER_MODE
    risk_audit: RiskAudit | None = None
    selection: SelectionDecision | None = None
    knowledge: KnowledgeArtifact | None = None
    generation_count: int = PILOT_LOOP_DEFAULT_GENERATION_COUNT
    live_orders: bool = False
    mass_fan_out: bool = False

    def __post_init__(self) -> None:
        if int(self.generation_count) != PILOT_LOOP_DEFAULT_GENERATION_COUNT:
            raise MassResearchDisabledError(
                "controlled pilot is 1-cycle "
                f"(generation_count={PILOT_LOOP_DEFAULT_GENERATION_COUNT}); "
                f"got {self.generation_count}"
            )
        if self.live_orders:
            raise MassResearchDisabledError("live orders are not permitted")
        if self.mass_fan_out:
            raise MassResearchDisabledError("mass fan-out is not permitted")
        if str(self.paper_mode or "").strip() != PILOT_LOOP_PAPER_MODE:
            raise MassResearchDisabledError("controlled pilot is paper-only")
        n = len(self.strategy_specs)
        if n and not (
            PILOT_LOOP_MIN_STRATEGY_SPECS <= n <= PILOT_LOOP_MAX_STRATEGY_SPECS
        ):
            raise MassResearchDisabledError(
                "controlled pilot admits 2–8 StrategySpec "
                f"(got {n})"
            )

    @property
    def stages(self) -> tuple[str, ...]:
        return CONTROLLED_PILOT_STAGES

    def start(self) -> None:
        _require_execution()

    def write_research_memo(self, *args: object, **kwargs: object) -> None:
        _require_execution()

    def propose_feature(self, *args: object, **kwargs: object) -> None:
        _require_execution()

    def propose_strategy_specs(self, *args: object, **kwargs: object) -> None:
        _require_execution()

    def pin_ready_snapshot(self, *args: object, **kwargs: object) -> None:
        _require_execution()

    def run_budgeted_paper(self, *args: object, **kwargs: object) -> None:
        _require_execution()

    def independent_risk(self, *args: object, **kwargs: object) -> None:
        _require_execution()

    def select(self, *args: object, **kwargs: object) -> None:
        _require_execution()

    def record_knowledge(self, *args: object, **kwargs: object) -> None:
        _require_execution()

    def start_mass_fan_out(self, *args: object, **kwargs: object) -> None:
        raise MassResearchDisabledError("mass fan-out is not permitted")

    def place_live_order(self, *args: object, **kwargs: object) -> None:
        raise MassResearchDisabledError("live orders are not permitted")


ControlledPilotLoop = ControlledPilotLoopPlan


def start(plan: ControlledPilotLoopPlan | None = None) -> None:
    """Entry for the 1-cycle loop. Capability-off; never starts mass."""
    (plan or ControlledPilotLoopPlan()).start()


__all__ = [
    "CONTROLLED_PILOT_STAGES",
    "ControlledPilotLoop",
    "ControlledPilotLoopPlan",
    "EXECUTION_ROUTES",
    "FeatureProposal",
    "KnowledgeArtifact",
    "MassResearchDisabledError",
    "PILOT_LOOP_DEFAULT_GENERATION_COUNT",
    "PILOT_LOOP_MAX_STRATEGY_SPECS",
    "PILOT_LOOP_MIN_STRATEGY_SPECS",
    "PILOT_LOOP_PAPER_MODE",
    "ResearchIdea",
    "ResearchMemo",
    "RiskAudit",
    "SelectionDecision",
    "StrategySpec",
    "research_capabilities",
    "start",
]
