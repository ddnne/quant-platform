"""Research memo composer."""

from __future__ import annotations

from .types import ComposedMemo, ResearchMemo
from .roles import AgentRole, ROLE_MATRIX


class ComposerAgent:
    role = "composer"
    capabilities = ROLE_MATRIX[AgentRole.COMPOSER].capabilities

    def compose(self, memos: tuple[ResearchMemo, ...]) -> ComposedMemo:
        if not memos:
            raise ValueError("composer requires at least one research memo")
        as_of_values = {memo.as_of for memo in memos}
        if len(as_of_values) != 1:
            raise ValueError("research memos must share one as_of")
        ordered = sorted(memos, key=lambda memo: memo.role)
        return ComposedMemo(
            as_of=ordered[0].as_of,
            thesis=" ".join(memo.thesis for memo in ordered),
            source_roles=tuple(memo.role for memo in ordered),
        )


__all__ = ["ComposerAgent"]
