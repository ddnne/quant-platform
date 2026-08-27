"""Role matrix, structured I/O, and capability-boundary tests."""

from __future__ import annotations

from agents.composer import ComposerAgent
from agents.fundamental import FundamentalAgent
from agents.macro import MacroAgent
from agents.pm import PortfolioManagerAgent
from agents.quant import QuantAgent
from agents.risk_agent import RiskAgent
from agents.roles import AgentRole, Capability, ROLE_MATRIX
from agents.strategist import StrategistAgent
from agents.trader import TraderAgent
from agents.types import ResearchMemo, ResearchRequest


def test_eight_roles_have_explicit_input_output_contracts():
    assert len(AgentRole) == 8
    assert set(ROLE_MATRIX) == set(AgentRole)
    assert all(contract.input_type and contract.output_type for contract in ROLE_MATRIX.values())
    assert all(not contract.may_execute for contract in ROLE_MATRIX.values())
    assert all(contract.capabilities for contract in ROLE_MATRIX.values())
    assert {
        capability for contract in ROLE_MATRIX.values()
        for capability in contract.capabilities
    } == set(Capability)
    instances = (
        MacroAgent(), FundamentalAgent(), QuantAgent(), ComposerAgent(),
        StrategistAgent(), PortfolioManagerAgent(), TraderAgent(), RiskAgent(),
    )
    assert all(agent.capabilities for agent in instances)


def test_roles_exchange_structured_messages_and_a_declarative_spec():
    request = ResearchRequest(as_of="2025-04-10", universe=("1332", "8697"))
    memos = tuple(
        agent.research(request)
        for agent in (MacroAgent(), FundamentalAgent(), QuantAgent())
    )
    assert all(isinstance(memo, ResearchMemo) for memo in memos)
    composed = ComposerAgent().compose(memos)
    spec = StrategistAgent(momentum_n=3, top_k=1).propose(composed)
    decision = PortfolioManagerAgent().review(spec)
    plan = TraderAgent().prepare(decision)

    assert decision.approved is True
    assert plan.mode == "paper"
    assert plan.authorization_id.startswith("sha256:")
    assert plan.strategy_spec_hash.startswith("sha256:")
    assert spec.to_dict()["rule"]["type"] == "top_k"
    proposals = [proposal for memo in memos for proposal in memo.feature_proposals]
    assert proposals and all(proposal.status == "candidate" for proposal in proposals)
