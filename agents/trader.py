"""Paper-only trader handoff; no broker or order API exists here."""

from __future__ import annotations

import hashlib
import json

from .types import AuthorizedPaperExecutionRequest, PortfolioDecision
from .roles import AgentRole, ROLE_MATRIX


class TraderAgent:
    role = "trader"
    capabilities = ROLE_MATRIX[AgentRole.TRADER].capabilities

    def prepare(self, decision: PortfolioDecision) -> AuthorizedPaperExecutionRequest:
        if not decision.approved:
            raise ValueError("trader refuses an unapproved portfolio decision")
        spec_json = json.dumps(
            decision.strategy_spec.to_dict(),
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        spec_hash = "sha256:" + hashlib.sha256(spec_json.encode("utf-8")).hexdigest()
        authorization = {
            "mode": "paper",
            "strategy_spec_hash": spec_hash,
            "max_gross_weight": decision.max_gross_weight,
        }
        authorization_id = "sha256:" + hashlib.sha256(
            json.dumps(authorization, sort_keys=True, separators=(",", ":")).encode(
                "utf-8"
            )
        ).hexdigest()
        return AuthorizedPaperExecutionRequest(
            mode="paper",
            authorization_id=authorization_id,
            strategy_id=decision.strategy_spec.strategy_id,
            strategy_spec_hash=spec_hash,
            max_gross_weight=decision.max_gross_weight,
            instructions=(
                "interpret the reviewed StrategySpec",
                "run through strategies.paper.run_paper",
                "do not contact a broker",
            ),
        )


__all__ = ["TraderAgent"]
