"""Phase 7 AI gateway tests."""

from __future__ import annotations

from gateway.ai import (
    AIGateway,
    GatewayBudget,
    ALLOWED_OUTPUT_SCHEMAS,
    OfflineStubProvider,
)


def test_ai_gateway_default_offline_stub():
    """Default gateway should use OfflineStubProvider."""
    gateway = AIGateway()
    assert isinstance(gateway.provider, OfflineStubProvider)


def test_ai_gateway_default_budget():
    """Gateway should have default budget."""
    gateway = AIGateway()
    assert gateway.budget.max_calls == 20
    assert gateway.budget.max_tokens == 100_000
    assert gateway.budget.calls_used == 0
    assert gateway.budget.tokens_used == 0


def test_ai_gateway_custom_budget():
    """Gateway should accept custom budget."""
    budget = GatewayBudget(max_calls=5, max_tokens=10_000)
    gateway = AIGateway(budget=budget)
    assert gateway.budget.max_calls == 5
    assert gateway.budget.max_tokens == 10_000


def test_ai_gateway_offline_stub_run():
    """Offline stub should return deterministic response."""
    gateway = AIGateway()
    result = gateway.run(
        role="quant",
        task="research",
        prompt="test prompt",
        expected_schema="Insight",
    )
    public = result.to_public_dict()
    assert public["schema"] == "Insight"
    assert public["role"] == "quant"
    assert public["task"] == "research"
    assert public["summary"] == "offline_stub"
    assert public["prompt_chars"] == len("test prompt")


def test_ai_gateway_budget_charges():
    """Gateway should charge budget on each call."""
    budget = GatewayBudget(max_calls=2, max_tokens=1000)
    gateway = AIGateway(budget=budget)

    gateway.run(role="quant", task="research", prompt="x", expected_schema="Insight")
    assert budget.calls_used == 1
    assert budget.tokens_used > 0

    gateway.run(role="quant", task="research", prompt="x", expected_schema="Insight")
    assert budget.calls_used == 2


def test_ai_gateway_budget_exhaustion_calls():
    """Should raise error when call budget exhausted."""
    budget = GatewayBudget(max_calls=1, max_tokens=1000)
    gateway = AIGateway(budget=budget)

    gateway.run(role="quant", task="research", prompt="x", expected_schema="Insight")

    try:
        gateway.run(role="quant", task="research", prompt="x", expected_schema="Insight")
        assert False, "Should raise RuntimeError"
    except RuntimeError as e:
        assert "budget exhausted" in str(e)


def test_ai_gateway_token_budget_approximation():
    """Should estimate tokens as prompt_chars // 4."""
    gateway = AIGateway()
    gateway.run(role="quant", task="research", prompt="abcd", expected_schema="Insight")
    # 4 chars // 4 = 1 token minimum
    assert gateway.budget.tokens_used >= 1


def test_ai_gateway_unsupported_schema_raises():
    """Should raise ValueError for unsupported output schema."""
    gateway = AIGateway()
    try:
        gateway.run(
            role="quant",
            task="research",
            prompt="x",
            expected_schema="UnsupportedSchema",
        )
        assert False, "Should raise ValueError"
    except ValueError as e:
        assert "unsupported output schema" in str(e)
        assert "UnsupportedSchema" in str(e)


def test_ai_gateway_allowed_schemas_constant():
    """ALLOWED_OUTPUT_SCHEMAS should contain expected schemas."""
    assert "ResearchMemo" in ALLOWED_OUTPUT_SCHEMAS
    assert "FeatureProposal" in ALLOWED_OUTPUT_SCHEMAS
    assert "StrategySpec" in ALLOWED_OUTPUT_SCHEMAS
    assert "Insight" in ALLOWED_OUTPUT_SCHEMAS


def test_ai_gateway_rejects_non_closed_schema():
    """Should reject provider returning non-closed schema."""
    from gateway.ai import GatewaySchemaRejected

    class BadProvider:
        def complete(self, *, role: str, task: str, prompt: str, expected_schema: str):
            return {"schema": "MaliciousCode", "payload": "rm -rf /"}

    gateway = AIGateway(provider=BadProvider())
    try:
        gateway.run(role="quant", task="research", prompt="x", expected_schema="Insight")
        assert False, "Should raise GatewaySchemaRejected"
    except GatewaySchemaRejected as e:
        assert "non-closed schema" in str(e)


def test_gateway_budget_initial_state():
    """GatewayBudget should start with zero usage."""
    budget = GatewayBudget()
    assert budget.calls_used == 0
    assert budget.tokens_used == 0


def test_gateway_budget_charge_increments_calls():
    """Charging should increment calls_used."""
    budget = GatewayBudget(max_calls=10)
    budget.charge()
    assert budget.calls_used == 1
    budget.charge()
    assert budget.calls_used == 2


def test_gateway_budget_charge_increments_tokens():
    """Charging should add tokens to tokens_used."""
    budget = GatewayBudget(max_tokens=1000)
    budget.charge(tokens=100)
    assert budget.tokens_used == 100
    budget.charge(tokens=50)
    assert budget.tokens_used == 150


def test_gateway_budget_charge_negative_tokens():
    """Charging with negative tokens should be handled (clamp to 0)."""
    budget = GatewayBudget()
    budget.charge(tokens=-10)
    assert budget.tokens_used >= 0  # Should not be negative


def test_gateway_budget_zero_max_calls():
    """Should fail immediately with max_calls=0."""
    budget = GatewayBudget(max_calls=0)
    try:
        budget.charge()
        assert False, "Should raise RuntimeError"
    except RuntimeError as e:
        assert "budget exhausted" in str(e)


def test_gateway_budget_token_limit():
    """Should fail when token limit would be exceeded."""
    budget = GatewayBudget(max_calls=10, max_tokens=100)
    budget.charge(tokens=60)
    try:
        budget.charge(tokens=50)  # 60 + 50 = 110 > 100, should fail
        assert False, "Should raise RuntimeError"
    except RuntimeError as e:
        assert "token budget exhausted" in str(e)


def test_ai_gateway_includes_usage_metadata():
    """Gateway result should include usage metadata."""
    gateway = AIGateway()
    result = gateway.run(
        role="quant",
        task="research",
        prompt="test prompt",
        expected_schema="Insight",
    )
    public = result.to_public_dict()
    assert "gateway" in public
    assert "calls_used" in public["gateway"]
    assert "tokens_used" in public["gateway"]
    assert public["gateway"]["calls_used"] == 1
    assert public["gateway"]["tokens_used"] > 0


def test_ai_gateway_custom_provider():
    """Gateway should accept custom provider."""
    class CustomProvider:
        def complete(self, *, role: str, task: str, prompt: str, expected_schema: str):
            return {
                "schema": "Insight",
                "role": role,
                "task": task,
                "custom": True,
                "schema_version": "insight/v1",
            }

    gateway = AIGateway(provider=CustomProvider())
    result = gateway.run(
        role="quant",
        task="research",
        prompt="x",
        expected_schema="Insight",
    )
    public = result.to_public_dict()
    assert public["custom"] is True
    assert public["schema"] == "Insight"


def test_ai_gateway_validates_all_expected_schemas():
    """All schemas in ALLOWED_OUTPUT_SCHEMAS should strict-decode via offline stub."""
    gateway = AIGateway()
    for schema in ALLOWED_OUTPUT_SCHEMAS:
        result = gateway.run(
            role="quant",
            task="research",
            prompt="x",
            expected_schema=schema,
        )
        assert result.schema_name == schema
