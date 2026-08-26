"""Offline-fixture closed-schema gateway — fail-closed typed boundary.

Fixture Provider → raw → strict typed decoder → GatewayResult[T] → downstream.
No raw-dict fallback on decoder failure. No production decode=False.
Generated code is never executed.

Production provider execution is owned exclusively by the Edge
research-ai-gateway Worker and its persistent BudgetLedger Durable Object.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, ClassVar, Generic, Mapping, Protocol, TypeVar
from uuid import uuid4

from selection.budget_ledger import (
    MassResearchDisabledError,
    ResearchBudgetCapability,
)

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
OFFLINE_FIXTURE_DRAFT = "OFFLINE_FIXTURE_DRAFT"
_INSIGHT_ALLOWED_KEYS = frozenset(
    {"role", "task", "summary", "prompt_chars", "schema_version"}
)


class GatewaySchemaRejected(RuntimeError):
    """Raised when provider output fails strict typed decode."""


@dataclass(frozen=True)
class GatewayBudgetReservation:
    """Opaque in-process estimate reservation for one fixture invocation."""

    reservation_id: str
    calls: int
    tokens: int


@dataclass
class GatewayBudget:
    """In-process estimate helper. Not Edge occupancy authority.

    Edge Budget DO (research-ai-gateway BudgetLedger) is occupancy authority.
    This class is not a second cap envelope, not Mass GO, and not live occupancy.
    """

    EDGE_OCCUPANCY_AUTHORITY: ClassVar[bool] = False
    max_calls: int = 20
    max_tokens: int = 100_000
    calls_used: int = 0
    tokens_used: int = 0
    reserved_tokens: int = 0
    reserved_calls: int = 0
    _reservations: dict[str, GatewayBudgetReservation] = field(
        default_factory=dict,
        init=False,
        repr=False,
    )

    def reserve(
        self, *, calls: int = 1, tokens: int = 0
    ) -> GatewayBudgetReservation:
        """Reserve capacity before provider call (fail closed pre-call)."""
        calls = max(0, int(calls))
        tokens = max(0, int(tokens))
        if self.calls_used + self.reserved_calls + calls > self.max_calls:
            raise RuntimeError("AI gateway model call budget exhausted (reserve)")
        if self.tokens_used + self.reserved_tokens + tokens > self.max_tokens:
            raise RuntimeError("AI gateway token budget exhausted (reserve)")
        reservation = GatewayBudgetReservation(
            reservation_id=str(uuid4()),
            calls=calls,
            tokens=tokens,
        )
        self.reserved_calls += calls
        self.reserved_tokens += tokens
        self._reservations[reservation.reservation_id] = reservation
        return reservation

    def _release_exact(self, reservation: GatewayBudgetReservation) -> bool:
        if not isinstance(reservation, GatewayBudgetReservation):
            raise RuntimeError("AI gateway budget reservation invalid")
        current = self._reservations.get(reservation.reservation_id)
        if current is None:
            return False
        if current != reservation:
            raise RuntimeError("AI gateway budget reservation mismatch")
        remaining_calls = self.reserved_calls - current.calls
        remaining_tokens = self.reserved_tokens - current.tokens
        if remaining_calls < 0 or remaining_tokens < 0:
            raise RuntimeError("AI gateway budget reservation state invalid")
        del self._reservations[reservation.reservation_id]
        self.reserved_calls = remaining_calls
        self.reserved_tokens = remaining_tokens
        return True

    def release(self, reservation: GatewayBudgetReservation) -> bool:
        """Release one exact estimate; retry is an idempotent no-op."""
        return self._release_exact(reservation)

    def reconcile(
        self,
        reservation: GatewayBudgetReservation,
        *,
        calls: int = 1,
        tokens: int = 0,
    ) -> None:
        """Release the full estimate, then record measured fixture usage."""
        calls = max(0, int(calls))
        tokens = max(0, int(tokens))
        if not self._release_exact(reservation):
            raise RuntimeError("AI gateway budget reservation already released")
        if self.calls_used + calls > self.max_calls:
            raise RuntimeError("AI gateway model call budget exhausted")
        if self.tokens_used + tokens > self.max_tokens:
            raise RuntimeError("AI gateway token budget exhausted")
        self.calls_used += calls
        self.tokens_used += tokens

    def charge(self, tokens: int = 0) -> None:
        """Legacy single-step charge (reserve+reconcile of 1 call)."""
        estimate = max(0, int(tokens))
        reservation = self.reserve(calls=1, tokens=estimate)
        try:
            self.reconcile(
                reservation,
                calls=1,
                tokens=estimate,
            )
        finally:
            self.release(reservation)


class OfflineFixtureProvider(Protocol):
    """Fixture-only provider protocol; not an Edge production capability."""

    def complete(
        self,
        *,
        role: str,
        task: str,
        prompt: str,
        expected_schema: str,
    ) -> Mapping[str, Any]:
        ...


# Compatibility type alias. It does not designate a production provider path.
LLMProvider = OfflineFixtureProvider


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
    budget_id: str
    execution_mode: str

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
            "budget_id": self.budget_id,
            "execution_mode": self.execution_mode,
            "promotion_eligible": False,
        }
        return body

    # Limited Mapping-style access for transitional tests / callers.
    def __getitem__(self, key: str) -> Any:
        return self.to_public_dict()[key]

    def get(self, key: str, default: Any = None) -> Any:
        return self.to_public_dict().get(key, default)


def _find_banned_keys(obj: Any, *, path: str = "") -> list[str]:
    """Reject banned executable keys at any nesting depth."""
    found: list[str] = []
    if isinstance(obj, Mapping):
        for k, v in obj.items():
            key = str(k)
            here = f"{path}.{key}" if path else key
            if key in _BANNED_KEYS:
                found.append(here)
            found.extend(_find_banned_keys(v, path=here))
    elif isinstance(obj, (list, tuple)):
        for i, v in enumerate(obj):
            found.extend(_find_banned_keys(v, path=f"{path}[{i}]"))
    return found


def _decode_typed(schema: str, payload: Mapping[str, Any]) -> Any:
    body = {k: v for k, v in payload.items() if k not in {"schema", "gateway"}}
    if "operator_override" in body:
        raise GatewaySchemaRejected("operator_override rejected")
    banned = _find_banned_keys(body)
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
            unknown = sorted(set(body) - _INSIGHT_ALLOWED_KEYS)
            if unknown:
                raise GatewaySchemaRejected(f"Insight unknown field(s): {unknown}")
            version = str(body.get("schema_version") or INSIGHT_SCHEMA_VERSION)
            out = dict(body)
            out["schema_version"] = version
            return out
    except (ValueError, TypeError, RuntimeError) as exc:
        raise GatewaySchemaRejected(f"{schema} decode failed: {exc}") from exc
    raise GatewaySchemaRejected(f"no decoder for schema {schema!r}")


def _extract_usage(raw: dict[str, Any], *, estimate: int) -> GatewayUsage:
    """Split provider usage into input/output tokens; fall back to prompt estimate."""
    usage_block = raw.pop("usage", None)
    usage_tokens = int(raw.pop("usage_tokens", 0) or 0)
    input_tokens = 0
    output_tokens = 0
    if isinstance(usage_block, Mapping):
        input_tokens = max(
            0,
            int(
                usage_block.get("input_tokens")
                or usage_block.get("prompt_tokens")
                or 0
            ),
        )
        output_tokens = max(
            0,
            int(
                usage_block.get("output_tokens")
                or usage_block.get("completion_tokens")
                or 0
            ),
        )
        total = int(usage_block.get("total_tokens") or 0)
        if usage_tokens <= 0:
            usage_tokens = total or (input_tokens + output_tokens)
    if input_tokens <= 0 and output_tokens <= 0:
        charge = usage_tokens if usage_tokens > 0 else max(1, int(estimate))
        input_tokens = charge
        output_tokens = 0
    total_tokens = input_tokens + output_tokens
    if total_tokens <= 0:
        total_tokens = max(1, int(estimate))
        input_tokens = total_tokens
    return GatewayUsage(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=total_tokens,
        calls=1,
    )


def _prompt_digest(prompt: str) -> str:
    return "sha256:" + hashlib.sha256(prompt.encode("utf-8")).hexdigest()


@dataclass
class OfflineFixtureAIGateway:
    """Offline fixture/DRAFT gateway; never a production provider exit."""

    EXECUTION_MODE: ClassVar[str] = OFFLINE_FIXTURE_DRAFT
    EDGE_PRODUCTION_PROVIDER_EXIT: ClassVar[bool] = False
    PROMOTION_ELIGIBLE: ClassVar[bool] = False

    provider: OfflineFixtureProvider = field(default_factory=OfflineStubProvider)
    budget: GatewayBudget = field(default_factory=GatewayBudget)
    research_budget: ResearchBudgetCapability | None = None
    provider_name: str = "offline_stub"
    model_name: str = "offline-stub/v0"

    def run(
        self,
        *,
        role: str,
        task: str,
        prompt: str,
        expected_schema: str,
        research_budget: ResearchBudgetCapability | None = None,
        operator_override: object | None = None,
    ) -> GatewayResult[Any]:
        """Offline fixture/DRAFT API — always strict decode. No decode=False.

        The in-process estimate is always released in ``finally``. Measured
        fixture usage is charged even when strict schema decoding later rejects
        the response. The persistent ResearchBudgetCapability retains its
        existing contract: it is charged only after successful strict decode.
        Missing/exhausted capability fail-closes, and operator_override cannot
        substitute for it.
        """
        if operator_override is not None:
            raise MassResearchDisabledError(
                "operator_override cannot substitute for ResearchBudgetCapability"
            )
        if expected_schema not in ALLOWED_OUTPUT_SCHEMAS:
            raise ValueError(
                f"unsupported output schema {expected_schema!r}; "
                f"allowed={sorted(ALLOWED_OUTPUT_SCHEMAS)}"
            )
        cap = (
            research_budget
            if research_budget is not None
            else self.research_budget
        )
        if not isinstance(cap, ResearchBudgetCapability):
            raise MassResearchDisabledError(
                "ResearchBudgetCapability is required; AI gateway complete is fail-closed"
            )
        # Pre-call reserve using prompt estimate; reconcile with provider usage.
        estimate = max(1, len(prompt) // 4)
        reservation = self.budget.reserve(calls=1, tokens=estimate)
        usage: GatewayUsage | None = None
        try:
            raw = dict(
                self.provider.complete(
                    role=role,
                    task=task,
                    prompt=prompt,
                    expected_schema=expected_schema,
                )
            )
            usage = _extract_usage(raw, estimate=estimate)
            self.budget.reconcile(
                reservation,
                calls=usage.calls,
                tokens=usage.total_tokens,
            )
        finally:
            # Idempotent after reconcile; exact on provider/usage failures.
            self.budget.release(reservation)

        if usage is None:  # pragma: no cover - finally preserves the invariant
            raise RuntimeError("AI gateway provider usage unavailable")

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

        # Charge only after successful strict decode. Single consume is atomic
        # across input_tokens/output_tokens/model_calls (ROLLBACK if any cap trips).
        cap.charge_provider_usage(
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            model_calls=usage.calls,
        )

        schema_version = schema
        if schema == "Insight" and isinstance(typed, Mapping):
            schema_version = str(typed.get("schema_version") or INSIGHT_SCHEMA_VERSION)
        elif schema == "StrategySpec" and hasattr(typed, "version"):
            schema_version = str(typed.version)

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
            budget_id=cap.budget_id,
            execution_mode=self.EXECUTION_MODE,
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


# Compatibility import only. The concrete type and public evidence remain
# explicitly OfflineFixture/DRAFT; production provider calls exit through Edge.
AIGateway = OfflineFixtureAIGateway


__all__ = [
    "ALLOWED_OUTPUT_SCHEMAS",
    "AIGateway",
    "GatewayBudget",
    "GatewayBudgetReservation",
    "GatewayResult",
    "GatewaySchemaRejected",
    "GatewayUsage",
    "INSIGHT_SCHEMA_VERSION",
    "LLMProvider",
    "OFFLINE_FIXTURE_DRAFT",
    "OfflineFixtureAIGateway",
    "OfflineFixtureProvider",
    "OfflineStubProvider",
]
