"""Standardized evaluation harness metadata (Phase 7 foundation).

Does not invent performance scores — records the protocol and reason codes
for SelectionDecision. Signal vs State/Structural criteria are separated.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence


SIGNAL_METRICS = (
    "cost_before",
    "cost_after",
    "drawdown",
    "turnover",
    "stability",
    "walk_forward",
    "regime_breakdown",
)

STATE_STRUCTURAL_METRICS = (
    "stability",
    "regime_breakdown",
    "feature_contribution",
    "correlation_novelty",
    "stress_scenarios",
)

COMMON_METADATA = (
    "embargo_purge",
    "multiple_testing",
    "period",
    "universe",
    "ready_snapshot_id",
)


@dataclass(frozen=True)
class EvaluationProtocol:
    protocol_id: str
    feature_role: str  # signal | state | structural | utility
    required_metrics: tuple[str, ...]
    optional_metrics: tuple[str, ...] = ()
    version: str = "evaluation-protocol/v1"

    def __post_init__(self) -> None:
        if self.feature_role not in {"signal", "state", "structural", "utility"}:
            raise ValueError(f"unknown feature_role: {self.feature_role}")

    @classmethod
    def for_role(cls, role: str) -> "EvaluationProtocol":
        if role == "signal":
            return cls(
                protocol_id="signal-default",
                feature_role="signal",
                required_metrics=SIGNAL_METRICS,
                optional_metrics=COMMON_METADATA,
            )
        if role in {"state", "structural"}:
            return cls(
                protocol_id=f"{role}-default",
                feature_role=role,
                required_metrics=STATE_STRUCTURAL_METRICS,
                optional_metrics=COMMON_METADATA,
            )
        return cls(
            protocol_id="utility-default",
            feature_role="utility",
            required_metrics=("stability", "cost_after"),
            optional_metrics=COMMON_METADATA,
        )


@dataclass(frozen=True)
class EvaluationReport:
    plan_id: str
    protocol: EvaluationProtocol
    metrics: Mapping[str, Any]
    missing_required: tuple[str, ...]
    version: str = "evaluation-report/v1"

    @property
    def complete(self) -> bool:
        return not self.missing_required

    def to_dict(self) -> dict[str, Any]:
        return {
            "plan_id": self.plan_id,
            "protocol_id": self.protocol.protocol_id,
            "feature_role": self.protocol.feature_role,
            "metrics": dict(self.metrics),
            "missing_required": list(self.missing_required),
            "complete": self.complete,
            "version": self.version,
        }


class EvaluationHarness:
    """Builds EvaluationReport; does not auto-PROMOTE strategies."""

    def evaluate(
        self,
        *,
        plan_id: str,
        feature_role: str,
        metrics: Mapping[str, Any],
    ) -> EvaluationReport:
        protocol = EvaluationProtocol.for_role(feature_role)
        missing = tuple(m for m in protocol.required_metrics if m not in metrics)
        return EvaluationReport(
            plan_id=plan_id,
            protocol=protocol,
            metrics=dict(metrics),
            missing_required=missing,
        )

    def selection_inputs(self, report: EvaluationReport) -> dict[str, Any]:
        """Inputs for SelectionDecision — never a single scalar score alone."""
        return {
            "plan_id": report.plan_id,
            "feature_role": report.protocol.feature_role,
            "complete": report.complete,
            "missing_required": list(report.missing_required),
            "metric_keys": sorted(report.metrics),
            "reason_hint": (
                "HOLD_INCOMPLETE_METRICS"
                if not report.complete
                else "REVIEW_REQUIRED"
            ),
        }


__all__ = [
    "COMMON_METADATA",
    "EvaluationHarness",
    "EvaluationProtocol",
    "EvaluationReport",
    "SIGNAL_METRICS",
    "STATE_STRUCTURAL_METRICS",
]
