"""Deterministic quant research stub."""

from __future__ import annotations

from .types import ResearchMemo, ResearchRequest


class QuantAgent:
    role = "quant"

    def research(self, request: ResearchRequest) -> ResearchMemo:
        return ResearchMemo(
            role=self.role,
            as_of=request.as_of,
            thesis="Rank the scoped universe with the approved momentum feature.",
            evidence=("momentum_n is computed only through ctx.feature.",),
        )


__all__ = ["QuantAgent"]
