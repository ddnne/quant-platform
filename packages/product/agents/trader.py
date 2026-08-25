"""Paper-only trader handoff; no broker or order API exists here."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from typing import Sequence

from .types import AuthorizedPaperExecutionRequest, PortfolioDecision
from .roles import AgentRole, ROLE_MATRIX


class TraderAgent:
    role = "trader"
    capabilities = ROLE_MATRIX[AgentRole.TRADER].capabilities

    def prepare(
        self,
        decision: PortfolioDecision,
        *,
        universe: Sequence[str] = (),
        period_start: str = "",
        period_end: str = "",
        cost_scenario: str = "default",
        ttl_seconds: int = 3600,
    ) -> AuthorizedPaperExecutionRequest:
        if not decision.approved:
            raise ValueError("trader refuses an unapproved portfolio decision")
        spec_json = json.dumps(
            decision.strategy_spec.to_dict(),
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        spec_hash = "sha256:" + hashlib.sha256(spec_json.encode("utf-8")).hexdigest()
        # This self-hash scopes an offline proposal only.  READY fields are
        # structurally empty and cannot be caller supplied; Controlled Pilot
        # accepts only the separately signed VerifiedTraderAuthorization type.
        authorization = {
            "mode": "paper",
            "strategy_spec_hash": spec_hash,
            "max_gross_weight": decision.max_gross_weight,
            "ready_snapshot_id": "",
            "ready_manifest_digest": "",
            "readiness_attestation_id": "",
            "profile_digest": "",
            "plan_set_digest": "",
            "dependency_closure_digest": "",
            "universe": list(universe),
            "period_start": period_start or "",
            "period_end": period_end or "",
            "cost_scenario": cost_scenario,
        }
        authorization_id = "sha256:" + hashlib.sha256(
            json.dumps(authorization, sort_keys=True, separators=(",", ":")).encode(
                "utf-8"
            )
        ).hexdigest()
        expires = (
            datetime.now(timezone.utc) + timedelta(seconds=max(60, ttl_seconds))
        ).isoformat()
        return AuthorizedPaperExecutionRequest(
            mode="paper",
            authorization_id=authorization_id,
            strategy_id=decision.strategy_spec.strategy_id,
            strategy_spec_hash=spec_hash,
            max_gross_weight=decision.max_gross_weight,
            instructions=(
                "interpret the reviewed StrategySpec",
                "run through OfflineFixturePaperService",
                "do not contact a broker",
                "offline fixture DRAFT only; no promotion authority",
            ),
            ready_snapshot_id="",
            ready_manifest_digest="",
            readiness_attestation_id="",
            profile_digest="",
            plan_set_digest="",
            dependency_closure_digest="",
            universe=tuple(str(u) for u in universe),
            period_start=str(period_start or ""),
            period_end=str(period_end or ""),
            cost_scenario=str(cost_scenario or "default"),
            expires_at=expires,
        )


__all__ = ["TraderAgent"]
