"""SelectionDecision: PROMOTE | HOLD | REJECT with machine-readable reasons."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


DECISIONS = frozenset({"PROMOTE", "HOLD", "REJECT"})


@dataclass(frozen=True)
class SelectionDecision:
    decision: str
    reason_codes: tuple[str, ...]
    subject_id: str
    evidence: Mapping[str, Any] | None = None

    def __post_init__(self) -> None:
        if self.decision not in DECISIONS:
            raise ValueError(f"decision must be one of {sorted(DECISIONS)}")
        if not self.reason_codes:
            raise ValueError("reason_codes must be non-empty")

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "SelectionDecision":
        if not isinstance(payload, Mapping):
            raise ValueError("SelectionDecision must be an object")
        allowed = {"decision", "reason_codes", "subject_id", "evidence"}
        unknown = sorted(set(payload) - allowed)
        if unknown:
            raise ValueError(f"SelectionDecision unknown field(s): {unknown}")
        for req in ("decision", "reason_codes", "subject_id"):
            if req not in payload:
                raise ValueError(f"SelectionDecision missing {req}")
        codes = payload["reason_codes"]
        if not isinstance(codes, (list, tuple)) or not codes:
            raise ValueError("reason_codes must be non-empty list")
        evidence = payload.get("evidence")
        if evidence is not None and not isinstance(evidence, Mapping):
            raise ValueError("evidence must be object if present")
        return cls(
            decision=str(payload["decision"]),
            reason_codes=tuple(str(c) for c in codes),
            subject_id=str(payload["subject_id"]),
            evidence=dict(evidence) if evidence is not None else None,
        )

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "decision": self.decision,
            "reason_codes": list(self.reason_codes),
            "subject_id": self.subject_id,
        }
        if self.evidence is not None:
            out["evidence"] = dict(self.evidence)
        return out


__all__ = ["DECISIONS", "SelectionDecision"]
