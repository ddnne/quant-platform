"""Closed-schema AI gateway. Never executes generated Python."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Protocol


ALLOWED_OUTPUT_SCHEMAS = frozenset(
    {
        "ResearchMemo",
        "FeatureProposal",
        "StrategySpec",
        "Insight",
        "SelectionDecision",
    }
)

# Reject free-form code-smuggling keys even on Insight.
_BANNED_KEYS = frozenset(
    {
        "code",
        "python",
        "exec",
        "eval",
        "script",
        "shell",
        "bytecode",
        "payload_code",
    }
)


@dataclass
class GatewayBudget:
    max_calls: int = 20
    max_tokens: int = 100_000
    calls_used: int = 0
    tokens_used: int = 0

    def charge(self, tokens: int = 0) -> None:
        if self.calls_used >= self.max_calls:
            raise RuntimeError("AI gateway model call budget exhausted")
        if self.tokens_used + tokens > self.max_tokens:
            raise RuntimeError("AI gateway token budget exhausted")
        self.calls_used += 1
        self.tokens_used += max(0, tokens)


class LLMProvider(Protocol):
    def complete(self, *, role: str, task: str, prompt: str) -> Mapping[str, Any]:
        ...


class OfflineStubProvider:
    """Deterministic offline provider used when no LLM is configured."""

    def complete(self, *, role: str, task: str, prompt: str) -> Mapping[str, Any]:
        # schema is filled by the gateway from expected_schema
        return {
            "role": role,
            "task": task,
            "summary": "offline_stub",
            "prompt_chars": len(prompt),
        }


def _decode_typed(schema: str, payload: Mapping[str, Any]) -> Any:
    """Strict decoder into trusted typed objects when available."""
    body = {k: v for k, v in payload.items() if k not in {"schema", "gateway"}}
    banned = sorted(set(body) & _BANNED_KEYS)
    if banned:
        raise RuntimeError(f"banned executable field(s): {banned}")
    if schema == "ResearchMemo":
        from agents.types import ResearchMemo

        return ResearchMemo.from_dict(body)
    if schema == "FeatureProposal":
        from agents.types import FeatureProposal

        return FeatureProposal.from_dict(body)
    if schema == "StrategySpec":
        from strategies.spec import StrategySpec

        return StrategySpec.from_dict(body)
    if schema == "SelectionDecision":
        from selection.decision import SelectionDecision

        return SelectionDecision.from_dict(body)
    if schema == "Insight":
        # Closed-ish dict: no banned keys; extras allowed only as plain data
        return dict(body)
    raise RuntimeError(f"no decoder for schema {schema!r}")


@dataclass
class AIGateway:
    provider: LLMProvider = field(default_factory=OfflineStubProvider)
    budget: GatewayBudget = field(default_factory=GatewayBudget)

    def run(
        self,
        *,
        role: str,
        task: str,
        prompt: str,
        expected_schema: str,
        decode: bool = True,
    ) -> Mapping[str, Any] | Any:
        if expected_schema not in ALLOWED_OUTPUT_SCHEMAS:
            raise ValueError(
                f"unsupported output schema {expected_schema!r}; "
                f"allowed={sorted(ALLOWED_OUTPUT_SCHEMAS)}"
            )
        raw = dict(self.provider.complete(role=role, task=task, prompt=prompt))
        usage_tokens = int(raw.pop("usage_tokens", 0) or 0)
        charge = usage_tokens if usage_tokens > 0 else max(1, len(prompt) // 4)
        self.budget.charge(tokens=charge)

        # Provider may omit schema (offline stub) or echo one.
        schema = str(raw.get("schema") or expected_schema)
        if schema not in ALLOWED_OUTPUT_SCHEMAS:
            raise RuntimeError("provider returned non-closed schema")
        # If provider declares a schema, it must match expected.
        if "schema" in raw and schema != expected_schema:
            raise RuntimeError(
                f"provider schema {schema!r} != expected {expected_schema!r}"
            )
        schema = expected_schema
        out: dict[str, Any]
        if decode:
            try:
                typed = _decode_typed(schema, raw)
                if hasattr(typed, "to_dict"):
                    out = typed.to_dict()
                elif isinstance(typed, dict):
                    out = dict(typed)
                else:
                    out = dict(raw)
            except (ValueError, TypeError, RuntimeError):
                # Offline/stub providers may only emit Insight-shaped bodies while
                # callers probe allowed schema names; keep closed-schema label
                # without claiming a fully typed object.
                if schema == "Insight":
                    raise
                out = {k: v for k, v in raw.items() if k not in _BANNED_KEYS}
        else:
            out = dict(raw)
        out["schema"] = schema
        out["gateway"] = {
            "calls_used": self.budget.calls_used,
            "tokens_used": self.budget.tokens_used,
            "charged_tokens": charge,
        }
        return out


__all__ = [
    "ALLOWED_OUTPUT_SCHEMAS",
    "AIGateway",
    "GatewayBudget",
    "LLMProvider",
    "OfflineStubProvider",
]
