"""Deterministic macro research stub."""

from __future__ import annotations

from .types import ResearchMemo, ResearchRequest


class MacroAgent:
    role = "macro"

    def research(self, request: ResearchRequest) -> ResearchMemo:
        return ResearchMemo(
            role=self.role,
            as_of=request.as_of,
            thesis="Use a neutral macro prior until approved state features exist.",
            evidence=("No external or raw feed is available to this role.",),
        )


__all__ = ["MacroAgent"]
