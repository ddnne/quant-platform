"""Closed-schema AI gateway — fail-closed typed boundary (Phase 6.2.2 P0).

LLM Provider → raw → strict typed decoder → GatewayResult[T] → downstream.
No raw-dict fallback on decoder failure. No production decode=False.
Generated code is never executed.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Generic, Mapping, Protocol, TypeVar
from uuid import uuid4

T = TypeVar("T")

ALLOWED_OUTPUT_SCHEMAS = frozenset(
    {
        "ResearchMemo",
        "FeatureProposal",
        "StrategySpec",
        "Insight",
        "SelectionDecision",
    }
)

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

INSIGHT_SCHEMA_VERSION = "insight/v1"


class GatewaySchemaRejected(RuntimeError):
    """Raised when provider output fails strict typed decode."""


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
    def complete(
        self,
        *,
        role: str,
        task: str,
        prompt: str,
        expected_schema: str,
    ) -> Mapping[str, Any]:
        ...


def _minimal_stub_body(schema: str, *, role: str, task: str, prompt: str) -> dict[str, Any]:
    """Valid minimal closed payloads for offline tests only."""
    if schema == "Insight":
        return {
            "role": role,
            "task": task,
            "summary": "offline_stub",
            "prompt_chars": len(prompt),
            "schema_version": INSIGHT_SCHEMA_VERSION,
        }
    if schema == "ResearchMemo":
        return {
            "role": role,
            "as_of": "1970-01-01T00:00:00+00:00",
            "thesis": "offline_stub",
            "evidence": [],
            "feature_proposals": [],
        }
    if schema == "FeatureProposal":
        return {
            "feature_id": "offline_stub_feature",
            "intended_role": "signal",
            "rationale": "offline_stub",
            "status": "candidate",
        }
    if schema == "StrategySpec":
        return {
            "version": "strategy-spec/v2",
            "strategy_id": "offline_stub_strategy",
            "rationale": "offline_stub",
            "rebalance": "daily",
            "rule": {
                "type": "threshold",
                "feature": {"id": "offline_feature", "version": "v1"},
                "threshold": 0.0,
            },
        }
    if schema == "SelectionDecision":
        return {
            "decision": "HOLD",
            "reason_codes": ["offline_stub"],
            "subject_id": "offline_subject",
        }
    raise GatewaySchemaRejected(f"no offline stub for schema {schema!r}")


class OfflineStubProvider:
    """Deterministic offline provider used when no LLM is configured."""

    def complete(
        self,
        *,
        role: str,
        task: str,
        prompt: str,
        expected_schema: str,
    ) -> Mapping[str, Any]:
        return _minimal_stub_body(
            expected_schema, role=role, task=task, prompt=prompt
        )


@dataclass(frozen=True)
class GatewayUsage:
    input_tokens: int
    output_tokens: int
    total_tokens: int
    calls: int = 1


@dataclass(frozen=True)
class GatewayResult(Generic[T]):
    """Typed gateway result — no free-form code execution path."""

    payload: T
    schema_name: str
    provider: str
    model: str
    request_id: str
    usage: GatewayUsage
    cost: float | None
    schema_version: str
    prompt_digest: str
    created_at: str

    def to_public_dict(self) -> dict[str, Any]:
        """Serialize for logs/tests; never re-introduces decode bypass."""
        if hasattr(self.payload, "to_dict"):
            body = dict(self.payload.to_dict())  # type: ignore[union-attr]
        elif isinstance(self.payload, Mapping):
            body = dict(self.payload)
        else:
            body = {"value": self.payload}
        body["schema"] = self.schema_name
        body["gateway"] = {
            "request_id": self.request_id,
            "provider": self.provider,
            "model": self.model,
            "calls_used": self.usage.calls,
            "tokens_used": self.usage.total_tokens,
            "charged_tokens": self.usage.total_tokens,
            "cost": self.cost,
            "schema_version": self.schema_version,
            "prompt_digest": self.prompt_digest,
            "created_at": self.created_at,
        }
        return body

    # Limited Mapping-style access for transitional tests / callers.
    def __getitem__(self, key: str) -> Any:
        return self.to_public_dict()[key]

    def get(self, key: str, default: Any = None) -> Any:
        return self.to_public_dict().get(key, default)


def _decode_typed(schema: str, payload: Mapping[str, Any]) -> Any:
    body = {k: v for k, v in payload.items() if k not in {"schema", "gateway"}}
    banned = sorted(set(body) & _BANNED_KEYS)
    if banned:
        raise GatewaySchemaRejected(f"banned executable field(s): {banned}")
    try:
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
            # Strict versioned insight: plain data only, banned keys already checked.
            if not isinstance(body, Mapping):
                raise GatewaySchemaRejected("Insight must be an object")
            version = str(body.get("schema_version") or INSIGHT_SCHEMA_VERSION)
            out = dict(body)
            out["schema_version"] = version
            return out
    except (ValueError, TypeError, RuntimeError) as exc:
        raise GatewaySchemaRejected(f"{schema} decode failed: {exc}") from exc
    raise GatewaySchemaRejected(f"no decoder for schema {schema!r}")


def _prompt_digest(prompt: str) -> str:
    return "sha256:" + hashlib.sha256(prompt.encode("utf-8")).hexdigest()


@dataclass
class AIGateway:
    provider: LLMProvider = field(default_factory=OfflineStubProvider)
    budget: GatewayBudget = field(default_factory=GatewayBudget)
    provider_name: str = "offline_stub"
    model_name: str = "offline-stub/v0"

    def run(
        self,
        *,
        role: str,
        task: str,
        prompt: str,
        expected_schema: str,
    ) -> GatewayResult[Any]:
        """Production API — always strict decode. No decode=False."""
        if expected_schema not in ALLOWED_OUTPUT_SCHEMAS:
            raise ValueError(
                f"unsupported output schema {expected_schema!r}; "
                f"allowed={sorted(ALLOWED_OUTPUT_SCHEMAS)}"
            )
        raw = dict(
            self.provider.complete(
                role=role,
                task=task,
                prompt=prompt,
                expected_schema=expected_schema,
            )
        )
        usage_tokens = int(raw.pop("usage_tokens", 0) or 0)
        charge = usage_tokens if usage_tokens > 0 else max(1, len(prompt) // 4)
        self.budget.charge(tokens=charge)

        if "schema" in raw:
            schema = str(raw.get("schema"))
            if schema not in ALLOWED_OUTPUT_SCHEMAS:
                raise GatewaySchemaRejected("provider returned non-closed schema")
            if schema != expected_schema:
                raise GatewaySchemaRejected(
                    f"provider schema {schema!r} != expected {expected_schema!r}"
                )
        schema = expected_schema

        try:
            typed = _decode_typed(schema, raw)
        except GatewaySchemaRejected:
            raise
        except Exception as exc:  # pragma: no cover — defensive
            raise GatewaySchemaRejected(str(exc)) from exc

        schema_version = schema
        if schema == "Insight" and isinstance(typed, Mapping):
            schema_version = str(typed.get("schema_version") or INSIGHT_SCHEMA_VERSION)
        elif schema == "StrategySpec" and hasattr(typed, "version"):
            schema_version = str(typed.version)

        usage = GatewayUsage(
            input_tokens=charge,
            output_tokens=0,
            total_tokens=charge,
            calls=1,
        )
        return GatewayResult(
            payload=typed,
            schema_name=schema,
            provider=self.provider_name,
            model=self.model_name,
            request_id=str(uuid4()),
            usage=usage,
            cost=None,
            schema_version=schema_version,
            prompt_digest=_prompt_digest(prompt),
            created_at=datetime.now(timezone.utc).isoformat(),
        )

    def _run_raw_for_tests(
        self,
        *,
        role: str,
        task: str,
        prompt: str,
        expected_schema: str,
    ) -> Mapping[str, Any]:
        """Test-only private helper — not part of production agent API.

        Still applies strict decode; returns public dict form.
        """
        return self.run(
            role=role,
            task=task,
            prompt=prompt,
            expected_schema=expected_schema,
        ).to_public_dict()


__all__ = [
    "ALLOWED_OUTPUT_SCHEMAS",
    "AIGateway",
    "GatewayBudget",
    "GatewayResult",
    "GatewaySchemaRejected",
    "GatewayUsage",
    "INSIGHT_SCHEMA_VERSION",
    "LLMProvider",
    "OfflineStubProvider",
]
