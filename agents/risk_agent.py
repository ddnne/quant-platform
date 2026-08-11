"""Independent post-run risk auditor."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from strategies.paper import PaperRunResult

from .types import RiskAudit


class RiskAgent:
    role = "risk"

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
        audit_payload: dict[str, Any] = {
            "experiment_id": result.experiment_id,
            "run_id": result.run_id,
            "checks": checks,
            "max_drawdown": max_drawdown,
            "max_drawdown_limit": self.max_drawdown_limit,
        }
        canonical = json.dumps(
            audit_payload,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        audit_id = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        return RiskAudit(
            audit_id=audit_id,
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


__all__ = ["RiskAgent"]
