"""AI Gateway fail-closed decode tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from gateway.ai import (
    AIGateway,
    GatewayBudget,
    GatewayResult,
    GatewaySchemaRejected,
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
    snap = cap.snapshot()
    assert snap["input_tokens"] == result.usage.input_tokens
    assert snap.get("output_tokens", 0) == result.usage.output_tokens
    assert snap["model_calls"] == 1


def test_decode_failure_no_raw_fallback(tmp_path: Path):
    class BadMemo:
        def complete(self, *, role, task, prompt, expected_schema):
            return {"role": role}  # missing required ResearchMemo fields

    cap = _budget(tmp_path)
    gw = AIGateway(provider=BadMemo(), research_budget=cap)
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
