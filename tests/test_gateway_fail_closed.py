"""AI Gateway fail-closed decode tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from gateway.ai import (
    AIGateway,
    GatewayBudget,
    GatewayBudgetReservation,
    GatewayResult,
    GatewaySchemaRejected,
    OFFLINE_FIXTURE_DRAFT,
    OfflineFixtureAIGateway,
    OfflineStubProvider,
)
from selection.budget_ledger import (
    BudgetExhaustedError,
    MassResearchDisabledError,
    ResearchBudgetCapability,
)
from selection.screen import ExperimentBudget


def test_gateway_budget_is_not_edge_occupancy_authority() -> None:
    assert GatewayBudget.EDGE_OCCUPANCY_AUTHORITY is False
    doc = GatewayBudget.__doc__ or ""
    assert "Not Edge occupancy authority" in doc
    assert GatewayBudget().max_calls != 16


def test_python_gateway_is_explicitly_offline_fixture_draft() -> None:
    assert AIGateway is OfflineFixtureAIGateway
    assert OfflineFixtureAIGateway.EXECUTION_MODE == OFFLINE_FIXTURE_DRAFT
    assert OfflineFixtureAIGateway.EDGE_PRODUCTION_PROVIDER_EXIT is False
    assert OfflineFixtureAIGateway.PROMOTION_ELIGIBLE is False


def _budget(
    tmp_path: Path,
    *,
    budget_id: str = "gw-budget",
    **limit_kw: int,
) -> ResearchBudgetCapability:
    return ResearchBudgetCapability(
        budget_id,
        tmp_path / f"{budget_id}.sqlite",
        ExperimentBudget(**limit_kw) if limit_kw else ExperimentBudget(),
    )


def test_insight_returns_gateway_result(tmp_path: Path):
    cap = _budget(tmp_path)
    gw = AIGateway(research_budget=cap)
    result = gw.run(
        role="quant",
        task="research",
        prompt="hello",
        expected_schema="Insight",
    )
    assert isinstance(result, GatewayResult)
    assert result.schema_name == "Insight"
    assert result.prompt_digest.startswith("sha256:")
    assert result.budget_id == cap.budget_id
    public = result.to_public_dict()
    assert public["schema"] == "Insight"
    assert "gateway" in public
    assert public["gateway"]["budget_id"] == cap.budget_id
    assert public["gateway"]["execution_mode"] == OFFLINE_FIXTURE_DRAFT
    assert public["gateway"]["promotion_eligible"] is False
    snap = cap.snapshot()
    assert snap["input_tokens"] == result.usage.input_tokens
    assert snap.get("output_tokens", 0) == result.usage.output_tokens
    assert snap["model_calls"] == 1


def test_decode_failure_no_raw_fallback(tmp_path: Path):
    class BadMemo:
        def complete(self, *, role, task, prompt, expected_schema):
            return {
                "role": role,
                "usage": {"input_tokens": 3, "output_tokens": 4},
            }  # missing required ResearchMemo fields

    cap = _budget(tmp_path)
    volatile = GatewayBudget()
    gw = AIGateway(provider=BadMemo(), research_budget=cap, budget=volatile)
    with pytest.raises(GatewaySchemaRejected):
        gw.run(
            role="quant",
            task="memo",
            prompt="x",
            expected_schema="ResearchMemo",
        )
    snap = cap.snapshot()
    assert snap.get("input_tokens", 0) == 0
    assert snap.get("model_calls", 0) == 0
    assert volatile.reserved_calls == 0
    assert volatile.reserved_tokens == 0
    assert volatile.calls_used == 1
    assert volatile.tokens_used == 7


def test_banned_code_field_rejected(tmp_path: Path):
    class Evil:
        def complete(self, *, role, task, prompt, expected_schema):
            return {
                "role": role,
                "task": task,
                "summary": "x",
                "code": "print(1)",
                "schema_version": "insight/v1",
            }

    gw = AIGateway(provider=Evil(), research_budget=_budget(tmp_path))
    with pytest.raises(GatewaySchemaRejected, match="banned"):
        gw.run(role="q", task="t", prompt="p", expected_schema="Insight")


def test_unknown_fields_rejected(tmp_path: Path):
    class Extra:
        def complete(self, *, role, task, prompt, expected_schema):
            return {
                "role": role,
                "task": task,
                "summary": "x",
                "schema_version": "insight/v1",
                "smuggled": True,
            }

    gw = AIGateway(provider=Extra(), research_budget=_budget(tmp_path))
    with pytest.raises(GatewaySchemaRejected, match="unknown field"):
        gw.run(role="q", task="t", prompt="p", expected_schema="Insight")


def test_no_decode_false_on_public_api():
    gw = AIGateway()
    with pytest.raises(TypeError):
        gw.run(  # type: ignore[call-arg]
            role="q",
            task="t",
            prompt="p",
            expected_schema="Insight",
            decode=False,
        )


def test_offline_stub_all_schemas_strict(tmp_path: Path):
    cap = _budget(tmp_path)
    gw = AIGateway(provider=OfflineStubProvider(), research_budget=cap)
    for schema in (
        "Insight",
        "ResearchMemo",
        "FeatureProposal",
        "StrategySpec",
        "SelectionDecision",
    ):
        result = gw.run(
            role="quant", task="t", prompt="x", expected_schema=schema
        )
        assert result.schema_name == schema
    assert cap.snapshot()["model_calls"] == 5


def test_missing_research_budget_fail_closed():
    gw = AIGateway()
    with pytest.raises(MassResearchDisabledError, match="ResearchBudgetCapability"):
        gw.run(role="q", task="t", prompt="p", expected_schema="Insight")


def test_operator_override_rejected(tmp_path: Path):
    gw = AIGateway(research_budget=_budget(tmp_path))
    with pytest.raises(MassResearchDisabledError, match="operator_override"):
        gw.run(
            role="q",
            task="t",
            prompt="p",
            expected_schema="Insight",
            operator_override={"reason": "force"},
        )


def test_operator_override_in_payload_rejected(tmp_path: Path):
    class OverridePayload:
        def complete(self, *, role, task, prompt, expected_schema):
            return {
                "role": role,
                "task": task,
                "summary": "x",
                "schema_version": "insight/v1",
                "operator_override": True,
            }

    cap = _budget(tmp_path)
    gw = AIGateway(provider=OverridePayload(), research_budget=cap)
    with pytest.raises(GatewaySchemaRejected, match="operator_override"):
        gw.run(role="q", task="t", prompt="p", expected_schema="Insight")
    assert cap.snapshot().get("model_calls", 0) == 0


def test_exhausted_research_budget_fail_closed(tmp_path: Path):
    class Metered:
        def complete(self, *, role, task, prompt, expected_schema):
            return {
                "role": role,
                "task": task,
                "summary": "x",
                "schema_version": "insight/v1",
                "usage": {"input_tokens": 40, "output_tokens": 10},
            }

    cap = _budget(tmp_path, max_input_tokens=20, max_output_tokens=50)
    gw = AIGateway(provider=Metered(), research_budget=cap)
    with pytest.raises(BudgetExhaustedError):
        gw.run(role="q", task="t", prompt="p", expected_schema="Insight")
    snap = cap.snapshot()
    assert snap.get("input_tokens", 0) == 0
    assert snap.get("output_tokens", 0) == 0
    assert snap.get("model_calls", 0) == 0


def test_complete_charges_input_output_tokens(tmp_path: Path):
    class Metered:
        def complete(self, *, role, task, prompt, expected_schema):
            return {
                "role": role,
                "task": task,
                "summary": "x",
                "schema_version": "insight/v1",
                "usage": {"input_tokens": 12, "output_tokens": 7},
            }

    cap = _budget(tmp_path)
    gw = AIGateway(provider=Metered(), research_budget=cap)
    result = gw.run(role="q", task="t", prompt="p", expected_schema="Insight")
    assert result.usage.input_tokens == 12
    assert result.usage.output_tokens == 7
    snap = cap.snapshot()
    assert snap["input_tokens"] == 12
    assert snap["output_tokens"] == 7
    assert snap["model_calls"] == 1


def test_volatile_budget_releases_exact_estimate_and_charges_actual(tmp_path: Path):
    class Metered:
        def complete(self, *, role, task, prompt, expected_schema):
            return {
                "role": role,
                "task": task,
                "summary": "x",
                "schema_version": "insight/v1",
                "usage": {"input_tokens": 1, "output_tokens": 0},
            }

    volatile = GatewayBudget(max_tokens=100)
    gw = AIGateway(
        provider=Metered(),
        research_budget=_budget(tmp_path),
        budget=volatile,
    )
    gw.run(role="q", task="t", prompt="x" * 80, expected_schema="Insight")
    assert volatile.reserved_calls == 0
    assert volatile.reserved_tokens == 0
    assert volatile.calls_used == 1
    assert volatile.tokens_used == 1


def test_provider_error_releases_volatile_reservation(tmp_path: Path):
    class FailedProvider:
        def complete(self, *, role, task, prompt, expected_schema):
            raise RuntimeError("provider failed")

    cap = _budget(tmp_path)
    volatile = GatewayBudget()
    gw = AIGateway(
        provider=FailedProvider(),
        research_budget=cap,
        budget=volatile,
    )
    with pytest.raises(RuntimeError, match="provider failed"):
        gw.run(role="q", task="t", prompt="x" * 80, expected_schema="Insight")
    assert volatile.reserved_calls == 0
    assert volatile.reserved_tokens == 0
    assert volatile.calls_used == 0
    assert volatile.tokens_used == 0
    assert cap.snapshot().get("model_calls", 0) == 0


def test_invalid_usage_releases_volatile_reservation(tmp_path: Path):
    class InvalidUsage:
        def complete(self, *, role, task, prompt, expected_schema):
            return {
                "role": role,
                "task": task,
                "summary": "x",
                "schema_version": "insight/v1",
                "usage": {"input_tokens": "not-an-integer"},
            }

    volatile = GatewayBudget()
    gw = AIGateway(
        provider=InvalidUsage(),
        research_budget=_budget(tmp_path),
        budget=volatile,
    )
    with pytest.raises(ValueError):
        gw.run(role="q", task="t", prompt="x" * 80, expected_schema="Insight")
    assert volatile.reserved_calls == 0
    assert volatile.reserved_tokens == 0
    assert volatile.calls_used == 0
    assert volatile.tokens_used == 0


def test_volatile_reservation_is_exact_and_idempotently_released() -> None:
    budget = GatewayBudget(max_calls=5, max_tokens=100)
    first = budget.reserve(calls=1, tokens=20)
    second = budget.reserve(calls=1, tokens=30)
    assert isinstance(first, GatewayBudgetReservation)
    assert budget.release(first) is True
    assert budget.release(first) is False
    assert budget.reserved_calls == 1
    assert budget.reserved_tokens == 30
    budget.reconcile(second, calls=1, tokens=3)
    assert budget.reserved_calls == 0
    assert budget.reserved_tokens == 0
    assert budget.calls_used == 1
    assert budget.tokens_used == 3


def test_volatile_overage_releases_without_phantom_reservation() -> None:
    budget = GatewayBudget(max_calls=1, max_tokens=5)
    reservation = budget.reserve(calls=1, tokens=4)
    with pytest.raises(RuntimeError, match="token budget exhausted"):
        budget.reconcile(reservation, calls=1, tokens=6)
    assert budget.reserved_calls == 0
    assert budget.reserved_tokens == 0
    assert budget.calls_used == 0
    assert budget.tokens_used == 0
