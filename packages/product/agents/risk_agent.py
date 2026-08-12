"""Independent post-run risk auditor."""

from __future__ import annotations

from strategies.paper import PaperRunResult

from .types import RiskAudit
from .roles import AgentRole, ROLE_MATRIX


class RiskAgent:
    role = "risk"
    capabilities = ROLE_MATRIX[AgentRole.RISK].capabilities

    def __init__(self, *, max_drawdown_limit: float = 0.35) -> None:
        limit = float(max_drawdown_limit)
        if not 0.0 <= limit <= 1.0:
            raise ValueError("max_drawdown_limit must be between 0 and 1")
        self.max_drawdown_limit = limit

    def audit(self, result: PaperRunResult) -> RiskAudit:
        metrics = result.metrics
        max_drawdown = abs(float(metrics.get("max_drawdown", 0.0)))
        checks = {
            "paper_result_has_experiment_id": bool(result.experiment_id),
            "paper_result_has_snapshot": bool(
                result.reproducibility.get("data_snapshot_id")
            ),
            "paper_result_identity_matches": result.run_id == result.experiment_id,
            "max_drawdown_within_limit": max_drawdown <= self.max_drawdown_limit,
        }
        findings = tuple(name for name, passed in checks.items() if not passed)
        provisional = RiskAudit(
            audit_id="pending",
            experiment_id=result.experiment_id,
            run_id=result.run_id,
            status="pass" if not findings else "review",
            checks=checks,
            findings=findings,
            metrics={
                "max_drawdown": max_drawdown,
                "max_drawdown_limit": self.max_drawdown_limit,
                "num_trades": int(metrics.get("num_trades", len(result.trades))),
            },
        )
        return RiskAudit(
            audit_id=provisional.expected_audit_id(),
            experiment_id=provisional.experiment_id,
            run_id=provisional.run_id,
            status=provisional.status,
            checks=provisional.checks,
            findings=provisional.findings,
            metrics=provisional.metrics,
        )


__all__ = ["RiskAgent"]
