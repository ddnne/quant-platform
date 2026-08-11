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
        return {
            "schema": "Insight",
            "role": role,
            "task": task,
            "summary": "offline_stub",
            "prompt_chars": len(prompt),
        }


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
    ) -> Mapping[str, Any]:
        if expected_schema not in ALLOWED_OUTPUT_SCHEMAS:
            raise ValueError(
                f"unsupported output schema {expected_schema!r}; "
                f"allowed={sorted(ALLOWED_OUTPUT_SCHEMAS)}"
            )
        self.budget.charge(tokens=max(1, len(prompt) // 4))
        result = dict(self.provider.complete(role=role, task=task, prompt=prompt))
        schema = str(result.get("schema") or expected_schema)
        if schema not in ALLOWED_OUTPUT_SCHEMAS:
            raise RuntimeError("provider returned non-closed schema")
        result["schema"] = schema
        result["gateway"] = {
            "calls_used": self.budget.calls_used,
            "tokens_used": self.budget.tokens_used,
        }
        return result
