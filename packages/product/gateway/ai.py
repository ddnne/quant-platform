"""Offline-fixture closed-schema gateway — fail-closed typed boundary.

Fixture data → strict typed decoder → GatewayResult[T] → downstream.
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
from enum import Enum
from pathlib import Path
from typing import Any, ClassVar, Generic, Mapping, TypeVar
from uuid import uuid4

from selection.budget_ledger import (
    BudgetExhaustedError,
    MassResearchDisabledError,
    ResearchBudgetCapability,
)
from selection.screen import ExperimentBudget

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


class OfflineFixtureProviderError(RuntimeError):
    """Closed offline fixture representing a provider-side failure."""


class OfflineFixtureUsageError(RuntimeError):
    """Closed offline fixture representing unavailable/invalid usage."""


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
        """Settle usage and raise only after conservative charge is recorded."""
        over_limit = self.settle(
            reservation,
            calls=calls,
            tokens=tokens,
        )
        if over_limit:
            raise RuntimeError("AI gateway actual usage exceeded volatile budget")

    def settle(
        self,
        reservation: GatewayBudgetReservation,
        *,
        calls: int = 1,
        tokens: int = 0,
    ) -> bool:
        """Release the estimate, record usage once, and report any overage."""
        calls = max(0, int(calls))
        tokens = max(0, int(tokens))
        if not self._release_exact(reservation):
            raise RuntimeError("AI gateway budget reservation already released")
        over_limit = (
            self.calls_used + calls > self.max_calls
            or self.tokens_used + tokens > self.max_tokens
        )
        self.calls_used += calls
        self.tokens_used += tokens
        return over_limit

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


class OfflineFixtureMode(str, Enum):
    MINIMAL_SUCCESS = "MINIMAL_SUCCESS"
    PAYLOAD = "PAYLOAD"
    PROVIDER_ERROR = "PROVIDER_ERROR"
    INVALID_USAGE = "INVALID_USAGE"


@dataclass(frozen=True)
class OfflineFixtureUsage:
    input_tokens: int
    output_tokens: int
    cached_tokens: int = 0

    def __post_init__(self) -> None:
        for name in ("input_tokens", "output_tokens", "cached_tokens"):
            value = getattr(self, name)
            if type(value) is not int or value < 0:
                raise ValueError(f"{name} must be an integer >= 0")
        if self.cached_tokens > self.input_tokens:
            raise ValueError("cached_tokens must be a subset of input_tokens")
        if self.input_tokens + self.output_tokens < 1:
            raise ValueError("offline fixture usage must contain at least one token")


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"non-finite JSON number rejected: {value}")


def _strict_json_object(raw: str) -> dict[str, Any]:
    def pairs_hook(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for key, value in pairs:
            if key in out:
                raise ValueError(f"duplicate JSON key rejected: {key}")
            out[key] = value
        return out

    decoded = json.loads(
        raw,
        object_pairs_hook=pairs_hook,
        parse_constant=_reject_json_constant,
    )
    if type(decoded) is not dict:
        raise ValueError("offline fixture payload must be a JSON object")
    return decoded


@dataclass(frozen=True)
class OfflineFixture:
    """Exact data-only fixture. It owns no callable or network capability."""

    mode: OfflineFixtureMode = OfflineFixtureMode.MINIMAL_SUCCESS
    payload_json: str | None = None
    usage: OfflineFixtureUsage | None = None
    error_message: str | None = None

    def __post_init__(self) -> None:
        if type(self.mode) is not OfflineFixtureMode:
            raise TypeError("offline fixture mode must be OfflineFixtureMode")
        if self.usage is not None and type(self.usage) is not OfflineFixtureUsage:
            raise TypeError("offline fixture usage must be exact OfflineFixtureUsage")
        if self.usage is not None:
            OfflineFixtureUsage.__post_init__(self.usage)
        if self.mode is OfflineFixtureMode.PAYLOAD:
            if (
                type(self.payload_json) is not str
                or not self.payload_json
                or len(self.payload_json.encode("utf-8")) > 64 * 1024
            ):
                raise ValueError("PAYLOAD fixture requires bounded payload_json")
            payload = _strict_json_object(self.payload_json)
            if "usage" in payload or "usage_tokens" in payload:
                raise ValueError("fixture usage must use OfflineFixtureUsage")
            if self.error_message is not None:
                raise ValueError("PAYLOAD fixture cannot carry error_message")
            return
        if self.payload_json is not None:
            raise ValueError(f"{self.mode.value} fixture cannot carry payload_json")
        if self.mode is OfflineFixtureMode.PROVIDER_ERROR:
            if (
                type(self.error_message) is not str
                or not self.error_message
                or self.error_message != self.error_message.strip()
                or len(self.error_message) > 256
            ):
                raise ValueError("PROVIDER_ERROR requires bounded error_message")
            return
        if self.error_message is not None:
            raise ValueError(f"{self.mode.value} fixture cannot carry error_message")
        if self.mode is OfflineFixtureMode.INVALID_USAGE and self.usage is not None:
            raise ValueError("INVALID_USAGE cannot claim measured usage")

    @classmethod
    def from_payload(
        cls,
        payload: Mapping[str, Any],
        *,
        usage: OfflineFixtureUsage | None = None,
    ) -> OfflineFixture:
        canonical = json.dumps(
            dict(payload),
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        return cls(
            mode=OfflineFixtureMode.PAYLOAD,
            payload_json=canonical,
            usage=usage,
        )

    @classmethod
    def provider_error(
        cls,
        message: str = "offline fixture provider error",
        *,
        usage: OfflineFixtureUsage | None = None,
    ) -> OfflineFixture:
        return cls(
            mode=OfflineFixtureMode.PROVIDER_ERROR,
            usage=usage,
            error_message=message,
        )

    @classmethod
    def invalid_usage(cls) -> OfflineFixture:
        return cls(mode=OfflineFixtureMode.INVALID_USAGE)


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


# Compatibility constructor name. It resolves to the same exact data-only type;
# no structural provider protocol or callable is retained.
OfflineStubProvider = OfflineFixture


@dataclass(frozen=True)
class GatewayUsage:
    input_tokens: int
    output_tokens: int
    total_tokens: int
    cached_tokens: int = 0
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
            "cached_tokens_used": self.usage.cached_tokens,
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


def _settlement_usage(
    fixture_usage: OfflineFixtureUsage | None,
    reservation: GatewayBudgetReservation,
) -> tuple[GatewayUsage, str]:
    if fixture_usage is None:
        return (
            GatewayUsage(
                input_tokens=reservation.tokens,
                output_tokens=0,
                total_tokens=reservation.tokens,
                cached_tokens=0,
                calls=reservation.calls,
            ),
            "reserved_estimate",
        )
    # Provider total-token semantics count cached input once: cached_tokens is
    # an informational subset of input_tokens, not a third charged category.
    total = fixture_usage.input_tokens + fixture_usage.output_tokens
    return (
        GatewayUsage(
            input_tokens=fixture_usage.input_tokens,
            output_tokens=fixture_usage.output_tokens,
            total_tokens=total,
            cached_tokens=fixture_usage.cached_tokens,
            calls=reservation.calls,
        ),
        "measured",
    )


def _prompt_digest(prompt: str) -> str:
    return "sha256:" + hashlib.sha256(prompt.encode("utf-8")).hexdigest()


def _require_exact_budget_capability(
    candidate: object,
) -> ResearchBudgetCapability:
    """Reject virtual or malformed settlement capabilities at the gateway edge."""
    if type(candidate) is not ResearchBudgetCapability:
        raise MassResearchDisabledError(
            "exact ResearchBudgetCapability is required; subclasses are not authority"
        )
    try:
        if (
            type(candidate.budget_id) is not str
            or not candidate.budget_id
            or candidate.budget_id != candidate.budget_id.strip()
            or len(candidate.budget_id) > 128
        ):
            raise ValueError("budget_id invalid")
        if not isinstance(candidate.ledger_path, Path):
            raise TypeError("ledger_path must be a Path")
        if type(candidate.limits) is not ExperimentBudget:
            raise TypeError("limits must be exact ExperimentBudget")
        ExperimentBudget.__post_init__(candidate.limits)
        ResearchBudgetCapability.__post_init__(candidate)
    except (AttributeError, TypeError, ValueError) as exc:
        raise MassResearchDisabledError(
            f"ResearchBudgetCapability state invalid: {exc}"
        ) from exc
    return candidate


@dataclass
class OfflineFixtureAIGateway:
    """Offline fixture/DRAFT gateway; never a production provider exit."""

    EXECUTION_MODE: ClassVar[str] = OFFLINE_FIXTURE_DRAFT
    EDGE_PRODUCTION_PROVIDER_EXIT: ClassVar[bool] = False
    PROMOTION_ELIGIBLE: ClassVar[bool] = False
    PROVIDER_NAME: ClassVar[str] = "offline_fixture"
    MODEL_NAME: ClassVar[str] = "offline-fixture/v1"

    provider: OfflineFixture = field(default_factory=OfflineFixture)
    budget: GatewayBudget = field(default_factory=GatewayBudget)
    research_budget: ResearchBudgetCapability | None = None

    def __post_init__(self) -> None:
        self._require_exact_fixture()

    def _require_exact_fixture(self) -> OfflineFixture:
        fixture = self.provider
        if type(fixture) is not OfflineFixture:
            raise TypeError(
                "provider must be exact data-only OfflineFixture; "
                "production provider execution exits through Edge"
            )
        try:
            OfflineFixture.__post_init__(fixture)
        except (AttributeError, TypeError, ValueError) as exc:
            raise TypeError(f"offline fixture invalid: {exc}") from exc
        return fixture

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

        Once fixture execution starts, measured usage (or the reserved estimate
        when unknown) is settled exactly once to both volatile and persistent
        ledgers before strict decode. Missing capability fail-closes, and
        operator_override cannot substitute for it.
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
        cap = _require_exact_budget_capability(cap)
        fixture = self._require_exact_fixture()
        estimate = max(1, len(prompt) // 4)
        reservation = self.budget.reserve(calls=1, tokens=estimate)
        settlement_id = str(uuid4())
        provider_started = False
        volatile_settled = False
        persistent_settled = False
        persistent_over_limit = False
        usage, usage_source = _settlement_usage(fixture.usage, reservation)
        charge_trigger = "provider_error"
        terminal_finalized = False
        terminal_intent: str | None = None
        volatile_over_limit = False

        def persist_usage_once() -> bool:
            return cap.settle_provider_usage_once(
                settlement_id=settlement_id,
                input_tokens=usage.input_tokens,
                output_tokens=usage.output_tokens,
                cached_tokens=usage.cached_tokens,
                model_calls=usage.calls,
                usage_source=usage_source,
                charge_trigger=charge_trigger,
            )

        def settle_started_usage() -> None:
            nonlocal volatile_settled, persistent_settled
            nonlocal volatile_over_limit, persistent_over_limit
            if not volatile_settled:
                volatile_over_limit = self.budget.settle(
                    reservation,
                    calls=usage.calls,
                    tokens=usage.total_tokens,
                )
                volatile_settled = True
            if not persistent_settled:
                try:
                    persistent_over_limit = persist_usage_once()
                except Exception:
                    # Exact settlement IDs distinguish a committed-but-unseen
                    # response from a fresh charge and make this retry safe.
                    persistent_over_limit = persist_usage_once()
                persistent_settled = True

        def finalize_terminal(terminal_outcome: str) -> None:
            nonlocal terminal_finalized, terminal_intent
            terminal_intent = terminal_outcome
            try:
                cap.finalize_provider_settlement_once(
                    settlement_id=settlement_id,
                    terminal_outcome=terminal_outcome,
                )
            except Exception:
                # The first transaction may have committed before its response
                # was observed. An exact retry is safe and never re-charges.
                cap.finalize_provider_settlement_once(
                    settlement_id=settlement_id,
                    terminal_outcome=terminal_outcome,
                )
            terminal_finalized = True

        def raise_settlement_overage() -> None:
            if persistent_over_limit:
                finalize_terminal("actual_overage")
                raise BudgetExhaustedError(
                    "provider usage exceeded persistent budget after start; usage recorded"
                )
            if volatile_over_limit:
                finalize_terminal("actual_overage")
                raise RuntimeError("AI gateway actual usage exceeded volatile budget")

        try:
            try:
                provider_started = True
                if fixture.mode is OfflineFixtureMode.PROVIDER_ERROR:
                    charge_trigger = "provider_error"
                    settle_started_usage()
                    raise_settlement_overage()
                    finalize_terminal("provider_error")
                    raise OfflineFixtureProviderError(
                        fixture.error_message or "provider error"
                    )
                if fixture.mode is OfflineFixtureMode.INVALID_USAGE:
                    charge_trigger = "invalid_usage"
                    settle_started_usage()
                    raise_settlement_overage()
                    finalize_terminal("invalid_usage")
                    raise OfflineFixtureUsageError(
                        "offline fixture usage unavailable; reserved estimate charged"
                    )
                charge_trigger = "provider_response"
                if fixture.mode is OfflineFixtureMode.MINIMAL_SUCCESS:
                    raw = _minimal_stub_body(
                        expected_schema,
                        role=role,
                        task=task,
                        prompt=prompt,
                    )
                else:
                    raw = _strict_json_object(fixture.payload_json or "")
                settle_started_usage()
                raise_settlement_overage()
            finally:
                if provider_started:
                    settle_started_usage()
                else:
                    self.budget.release(reservation)

            try:
                if "schema" in raw:
                    schema = str(raw.get("schema"))
                    if schema not in ALLOWED_OUTPUT_SCHEMAS:
                        raise GatewaySchemaRejected(
                            "provider returned non-closed schema"
                        )
                    if schema != expected_schema:
                        raise GatewaySchemaRejected(
                            f"provider schema {schema!r} != expected {expected_schema!r}"
                        )
                schema = expected_schema
                typed = _decode_typed(schema, raw)
            except GatewaySchemaRejected:
                finalize_terminal("schema_reject")
                raise
            except Exception as exc:  # pragma: no cover — defensive
                finalize_terminal("schema_reject")
                raise GatewaySchemaRejected(str(exc)) from exc

            schema_version = schema
            if schema == "Insight" and isinstance(typed, Mapping):
                schema_version = str(
                    typed.get("schema_version") or INSIGHT_SCHEMA_VERSION
                )
            elif schema == "StrategySpec" and hasattr(typed, "version"):
                schema_version = str(typed.version)

            result = GatewayResult(
                payload=typed,
                schema_name=schema,
                provider=self.PROVIDER_NAME,
                model=self.MODEL_NAME,
                request_id=settlement_id,
                usage=usage,
                cost=None,
                schema_version=schema_version,
                prompt_digest=_prompt_digest(prompt),
                created_at=datetime.now(timezone.utc).isoformat(),
                budget_id=cap.budget_id,
                execution_mode=self.EXECUTION_MODE,
            )
            finalize_terminal("success")
            return result
        except BaseException:
            if persistent_settled and not terminal_finalized:
                if terminal_intent is not None:
                    fallback_outcome = terminal_intent
                elif persistent_over_limit or volatile_over_limit:
                    fallback_outcome = "actual_overage"
                elif charge_trigger == "provider_response":
                    fallback_outcome = "schema_reject"
                else:
                    fallback_outcome = charge_trigger
                finalize_terminal(fallback_outcome)
            raise

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
    "OFFLINE_FIXTURE_DRAFT",
    "OfflineFixture",
    "OfflineFixtureAIGateway",
    "OfflineFixtureMode",
    "OfflineFixtureProviderError",
    "OfflineFixtureUsage",
    "OfflineFixtureUsageError",
    "OfflineStubProvider",
]
