"""Offline Phase 6 role-agent → StrategySpec → paper → risk pipeline."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

from risk import JsonRiskStore
from strategies.paper import JsonPaperStore, PaperRunConfig, PaperRunResult, run_paper
from strategies.spec import StrategySpec, interpret_strategy_spec

from .composer import ComposerAgent
from .artifacts import ArtifactEnvelope
from .fundamental import FundamentalAgent
from .macro import MacroAgent
from .pm import PortfolioManagerAgent
from .quant import QuantAgent
from .risk_agent import RiskAgent
from .strategist import StrategistAgent
from .trader import TraderAgent
from .types import (
    ComposedMemo,
    PortfolioDecision,
    ResearchMemo,
    ResearchRequest,
    RiskAudit,
    AuthorizedPaperExecutionRequest,
)


@dataclass(frozen=True)
class AgentPipelineResult:
    memos: tuple[ResearchMemo, ...]
    composed_memo: ComposedMemo
    strategy_spec: StrategySpec
    portfolio_decision: PortfolioDecision
    trade_plan: AuthorizedPaperExecutionRequest
    paper_result: PaperRunResult
    paper_result_path: Path
    risk_audit: RiskAudit
    risk_audit_path: Path
    artifacts: tuple[ArtifactEnvelope, ...] = ()


def _is_within(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


class AgentPaperPipeline:
    """Compose deterministic roles without giving any role a data handle."""

    def __init__(
        self,
        *,
        paper_store: JsonPaperStore | None = None,
        risk_store: JsonRiskStore | None = None,
        strategist: StrategistAgent | None = None,
        risk_agent: RiskAgent | None = None,
    ) -> None:
        self.paper_store = paper_store or JsonPaperStore()
        self.risk_store = risk_store or JsonRiskStore()
        paper_root = self.paper_store.root.resolve()
        risk_root = self.risk_store.root.resolve()
        if _is_within(risk_root, paper_root) or _is_within(paper_root, risk_root):
            raise ValueError("paper results and risk audits require disjoint roots")
        self.researchers = (MacroAgent(), FundamentalAgent(), QuantAgent())
        self.composer = ComposerAgent()
        self.strategist = strategist or StrategistAgent()
        self.pm = PortfolioManagerAgent()
        self.trader = TraderAgent()
        self.risk_agent = risk_agent or RiskAgent()

    def run(self, config: PaperRunConfig) -> AgentPipelineResult:
        universe = tuple(config.universe or ())
        if not universe:
            raise ValueError("agent pipeline requires an explicit non-empty universe")
        request = ResearchRequest(as_of=config.end, universe=universe)
        # These roles consume the same immutable request and have no shared
        # state. Sort after collection so scheduling never affects results.
        with ThreadPoolExecutor(max_workers=len(self.researchers)) as executor:
            memos = tuple(executor.map(lambda agent: agent.research(request), self.researchers))
        memos = tuple(sorted(memos, key=lambda memo: memo.role))
        composed = self.composer.compose(memos)
        spec = self.strategist.propose(composed)
        decision = self.pm.review(spec)
        plan = self.trader.prepare(decision)
        strategy = interpret_strategy_spec(spec)

        # config.db_path is passed only to the trusted paper runtime.  None of
        # the role-agent method calls above receives it.
        paper_result = run_paper(strategy, config, store=self.paper_store)
        paper_path = self.paper_store.result_path(paper_result)
        # Audit the immutable persisted artifact rather than privileged engine
        # state. This keeps the risk role downstream and independently replayable.
        paper_result = self.paper_store.load(paper_path)
        audit = self.risk_agent.audit(paper_result)
        audit_path = self.risk_store.save(audit)
        snapshot_id = str(paper_result.reproducibility["data_snapshot_id"])
        spec_artifact = ArtifactEnvelope.create(
            type="strategy_spec",
            producer_role="strategist",
            data_snapshot_id=snapshot_id,
            payload=spec.to_dict(),
        )
        decision_artifact = ArtifactEnvelope.create(
            type="portfolio_decision",
            producer_role="portfolio_manager",
            data_snapshot_id=snapshot_id,
            parent_ids=(spec_artifact.artifact_id,),
            payload={
                "approved": decision.approved,
                "max_gross_weight": decision.max_gross_weight,
                "reasons": list(decision.reasons),
            },
        )
        execution_artifact = ArtifactEnvelope.create(
            type="authorized_paper_execution_request",
            producer_role="trader",
            data_snapshot_id=snapshot_id,
            parent_ids=(decision_artifact.artifact_id,),
            payload={
                "mode": plan.mode,
                "authorization_id": plan.authorization_id,
                "strategy_id": plan.strategy_id,
                "strategy_spec_hash": plan.strategy_spec_hash,
                "max_gross_weight": plan.max_gross_weight,
                "instructions": list(plan.instructions),
            },
        )
        paper_artifact = ArtifactEnvelope.create(
            type="paper_result",
            producer_role="paper_runtime",
            data_snapshot_id=snapshot_id,
            parent_ids=(execution_artifact.artifact_id,),
            payload={
                "experiment_id": paper_result.experiment_id,
                "run_id": paper_result.run_id,
                "result_path": paper_path.relative_to(self.paper_store.root).as_posix(),
            },
        )
        risk_artifact = ArtifactEnvelope.create(
            type="risk_audit",
            producer_role="risk",
            data_snapshot_id=snapshot_id,
            parent_ids=(paper_artifact.artifact_id,),
            payload=audit.to_dict(),
        )
        return AgentPipelineResult(
            memos=memos,
            composed_memo=composed,
            strategy_spec=spec,
            portfolio_decision=decision,
            trade_plan=plan,
            paper_result=paper_result,
            paper_result_path=paper_path,
            risk_audit=audit,
            risk_audit_path=audit_path,
            artifacts=(
                spec_artifact,
                decision_artifact,
                execution_artifact,
                paper_artifact,
                risk_artifact,
            ),
        )


__all__ = ["AgentPaperPipeline", "AgentPipelineResult"]
