"""Deterministic fundamental research stub."""

from __future__ import annotations

from .types import FeatureProposal, ResearchMemo, ResearchRequest
from .roles import AgentRole, ROLE_MATRIX


class FundamentalAgent:
    role = "fundamental"
    capabilities = ROLE_MATRIX[AgentRole.FUNDAMENTAL].capabilities

    def research(self, request: ResearchRequest) -> ResearchMemo:
        return ResearchMemo(
            role=self.role,
            as_of=request.as_of,
            thesis="Keep fundamentals observational until governed features are approved.",
            evidence=(f"Universe contains {len(request.universe)} scoped code(s).",),
            feature_proposals=(
                FeatureProposal(
                    feature_id="quality_composite",
                    intended_role="signal",
                    rationale="Candidate for a later PIT disclosure-based review.",
                ),
            ),
        )


__all__ = ["FundamentalAgent"]
