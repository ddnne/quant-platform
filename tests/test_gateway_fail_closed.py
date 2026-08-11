"""AI Gateway fail-closed decode tests."""

from __future__ import annotations

import pytest

from gateway.ai import (
    AIGateway,
    GatewayResult,
    GatewaySchemaRejected,
    OfflineStubProvider,
)


def test_insight_returns_gateway_result():
    gw = AIGateway()
    result = gw.run(
        role="quant",
        task="research",
        prompt="hello",
        expected_schema="Insight",
    )
    assert isinstance(result, GatewayResult)
    assert result.schema_name == "Insight"
    assert result.prompt_digest.startswith("sha256:")
    public = result.to_public_dict()
    assert public["schema"] == "Insight"
    assert "gateway" in public


def test_decode_failure_no_raw_fallback():
    class BadMemo:
        def complete(self, *, role, task, prompt, expected_schema):
            return {"role": role}  # missing required ResearchMemo fields

    gw = AIGateway(provider=BadMemo())
    with pytest.raises(GatewaySchemaRejected):
        gw.run(
            role="quant",
            task="memo",
            prompt="x",
            expected_schema="ResearchMemo",
        )


def test_banned_code_field_rejected():
    class Evil:
        def complete(self, *, role, task, prompt, expected_schema):
            return {
                "role": role,
                "task": task,
                "summary": "x",
                "code": "print(1)",
                "schema_version": "insight/v1",
            }

    gw = AIGateway(provider=Evil())
    with pytest.raises(GatewaySchemaRejected, match="banned"):
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


def test_offline_stub_all_schemas_strict():
    gw = AIGateway(provider=OfflineStubProvider())
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
