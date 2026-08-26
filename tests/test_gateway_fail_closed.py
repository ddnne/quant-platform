"""AI Gateway fail-closed decode tests."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
import gateway.ai as gateway_ai

from gateway.ai import (
    AIGateway,
    GatewayBudget,
    GatewayBudgetReservation,
    GatewayResult,
    GatewaySchemaRejected,
    OFFLINE_FIXTURE_DRAFT,
    OfflineFixture,
    OfflineFixtureAIGateway,
    OfflineFixtureMode,
    OfflineFixtureProviderError,
    OfflineFixtureUsage,
    OfflineFixtureUsageError,
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
    assert OfflineStubProvider is OfflineFixture


def test_gateway_rejects_structural_callable_and_fixture_subclass_providers(
    tmp_path: Path,
) -> None:
    class StructuralProvider:
        def complete(self, **_kwargs: object) -> dict[str, object]:
            return _insight_payload()

    class FixtureSubclass(OfflineFixture):
        pass

    candidates = [
        StructuralProvider(),
        lambda: _insight_payload(),
        FixtureSubclass(),
    ]
    for candidate in candidates:
        with pytest.raises(TypeError, match="exact data-only OfflineFixture"):
            AIGateway(provider=candidate)  # type: ignore[arg-type]

    gateway = AIGateway(research_budget=_budget(tmp_path))
    object.__setattr__(gateway, "provider", StructuralProvider())
    with pytest.raises(TypeError, match="exact data-only OfflineFixture"):
        gateway.run(role="q", task="t", prompt="p", expected_schema="Insight")


def test_gateway_rejects_virtual_budget_capability_subclass(tmp_path: Path) -> None:
    class HostileBudgetCapability(ResearchBudgetCapability):
        def settle_provider_usage_once(self, **_kwargs: object) -> bool:
            return False

        def finalize_provider_settlement_once(self, **_kwargs: object) -> None:
            return None

    hostile = HostileBudgetCapability(
        budget_id="hostile-budget",
        ledger_path=tmp_path / "hostile.sqlite",
        limits=ExperimentBudget(),
    )
    gateway = AIGateway(research_budget=hostile)
    with pytest.raises(MassResearchDisabledError, match="subclasses are not authority"):
        gateway.run(role="q", task="t", prompt="p", expected_schema="Insight")
    assert not hostile.ledger_path.exists()


def test_fixture_payload_is_strict_canonical_data() -> None:
    with pytest.raises(ValueError, match="duplicate JSON key"):
        OfflineFixture(
            mode=OfflineFixtureMode.PAYLOAD,
            payload_json='{"role":"q","role":"other"}',
        )
    with pytest.raises(ValueError, match="non-finite JSON"):
        OfflineFixture(
            mode=OfflineFixtureMode.PAYLOAD,
            payload_json='{"value":NaN}',
        )
    with pytest.raises(ValueError, match="OfflineFixtureUsage"):
        OfflineFixture.from_payload({"usage": {"input_tokens": 1}})


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


def _insight_payload(**extra: object) -> dict[str, object]:
    return {
        "role": "q",
        "task": "t",
        "summary": "x",
        "schema_version": "insight/v1",
        **extra,
    }


def _settlement_audit(
    cap: ResearchBudgetCapability,
) -> tuple[str, str | None, str, int]:
    with sqlite3.connect(cap.ledger_path) as conn:
        rows = conn.execute(
            "SELECT charge_trigger, terminal_outcome, usage_source, over_limit "
            "FROM research_provider_settlements WHERE budget_id=?",
            (cap.budget_id,),
        ).fetchall()
    assert len(rows) == 1
    trigger, terminal, usage_source, over_limit = rows[0]
    return str(trigger), terminal, str(usage_source), int(over_limit)


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
    assert _settlement_audit(cap) == (
        "provider_response",
        "success",
        "reserved_estimate",
        0,
    )


def test_decode_failure_no_raw_fallback(tmp_path: Path):
    cap = _budget(tmp_path)
    volatile = GatewayBudget()
    fixture = OfflineFixture.from_payload(
        {"role": "quant"},
        usage=OfflineFixtureUsage(input_tokens=3, output_tokens=4),
    )
    gw = AIGateway(provider=fixture, research_budget=cap, budget=volatile)
    with pytest.raises(GatewaySchemaRejected):
        gw.run(
            role="quant",
            task="memo",
            prompt="x",
            expected_schema="ResearchMemo",
        )
    snap = cap.snapshot()
    assert snap["input_tokens"] == 3
    assert snap["output_tokens"] == 4
    assert snap["model_calls"] == 1
    assert volatile.reserved_calls == 0
    assert volatile.reserved_tokens == 0
    assert volatile.calls_used == 1
    assert volatile.tokens_used == 7
    assert _settlement_audit(cap) == (
        "provider_response",
        "schema_reject",
        "measured",
        0,
    )


def test_persistent_actual_usage_is_settled_before_decode(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cap = _budget(tmp_path)
    fixture = OfflineFixture.from_payload(
        _insight_payload(),
        usage=OfflineFixtureUsage(input_tokens=5, output_tokens=2),
    )
    original_decode = gateway_ai._decode_typed

    def asserting_decode(schema: str, payload: object) -> object:
        snapshot = cap.snapshot()
        assert snapshot["input_tokens"] == 5
        assert snapshot["output_tokens"] == 2
        assert snapshot["model_calls"] == 1
        assert _settlement_audit(cap) == (
            "provider_response",
            None,
            "measured",
            0,
        )
        return original_decode(schema, payload)  # type: ignore[arg-type]

    monkeypatch.setattr(gateway_ai, "_decode_typed", asserting_decode)
    result = AIGateway(provider=fixture, research_budget=cap).run(
        role="q",
        task="t",
        prompt="p",
        expected_schema="Insight",
    )
    assert result.usage.total_tokens == 7
    assert _settlement_audit(cap)[1] == "success"


def test_terminal_finalize_commit_response_loss_retries_without_recharge(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cap = _budget(tmp_path)
    fixture = OfflineFixture.from_payload(
        _insight_payload(),
        usage=OfflineFixtureUsage(input_tokens=5, output_tokens=2),
    )
    original = ResearchBudgetCapability.finalize_provider_settlement_once
    calls = 0

    def commit_then_lose_response(
        capability: ResearchBudgetCapability,
        *,
        settlement_id: str,
        terminal_outcome: str,
    ) -> None:
        nonlocal calls
        calls += 1
        original(
            capability,
            settlement_id=settlement_id,
            terminal_outcome=terminal_outcome,
        )
        if calls == 1:
            raise RuntimeError("commit response lost")

    monkeypatch.setattr(
        ResearchBudgetCapability,
        "finalize_provider_settlement_once",
        commit_then_lose_response,
    )
    result = AIGateway(provider=fixture, research_budget=cap).run(
        role="q",
        task="t",
        prompt="p",
        expected_schema="Insight",
    )
    assert result.usage.total_tokens == 7
    assert calls == 2
    assert cap.snapshot()["model_calls"] == 1
    assert _settlement_audit(cap)[1] == "success"


def test_usage_settlement_commit_response_loss_retries_without_recharge(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cap = _budget(tmp_path)
    fixture = OfflineFixture.from_payload(
        _insight_payload(),
        usage=OfflineFixtureUsage(input_tokens=5, output_tokens=2),
    )
    original = ResearchBudgetCapability.settle_provider_usage_once
    calls = 0

    def commit_then_lose_response(
        capability: ResearchBudgetCapability,
        **kwargs: object,
    ) -> bool:
        nonlocal calls
        calls += 1
        over_limit = original(capability, **kwargs)  # type: ignore[arg-type]
        if calls == 1:
            raise RuntimeError("commit response lost")
        return over_limit

    monkeypatch.setattr(
        ResearchBudgetCapability,
        "settle_provider_usage_once",
        commit_then_lose_response,
    )
    result = AIGateway(provider=fixture, research_budget=cap).run(
        role="q",
        task="t",
        prompt="p",
        expected_schema="Insight",
    )
    assert result.usage.total_tokens == 7
    assert calls == 2
    assert cap.snapshot()["model_calls"] == 1
    assert _settlement_audit(cap)[1] == "success"


def test_banned_code_field_rejected(tmp_path: Path):
    fixture = OfflineFixture.from_payload(_insight_payload(code="print(1)"))
    gw = AIGateway(provider=fixture, research_budget=_budget(tmp_path))
    with pytest.raises(GatewaySchemaRejected, match="banned"):
        gw.run(role="q", task="t", prompt="p", expected_schema="Insight")


def test_unknown_fields_rejected(tmp_path: Path):
    fixture = OfflineFixture.from_payload(_insight_payload(smuggled=True))
    gw = AIGateway(provider=fixture, research_budget=_budget(tmp_path))
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
    cap = _budget(tmp_path)
    fixture = OfflineFixture.from_payload(
        _insight_payload(operator_override=True),
        usage=OfflineFixtureUsage(input_tokens=2, output_tokens=1),
    )
    gw = AIGateway(provider=fixture, research_budget=cap)
    with pytest.raises(GatewaySchemaRejected, match="operator_override"):
        gw.run(role="q", task="t", prompt="p", expected_schema="Insight")
    assert cap.snapshot()["model_calls"] == 1


def test_exhausted_research_budget_fail_closed(tmp_path: Path):
    cap = _budget(tmp_path, max_input_tokens=20, max_output_tokens=50)
    fixture = OfflineFixture.from_payload(
        _insight_payload(),
        usage=OfflineFixtureUsage(input_tokens=40, output_tokens=10),
    )
    gw = AIGateway(provider=fixture, research_budget=cap)
    with pytest.raises(BudgetExhaustedError):
        gw.run(role="q", task="t", prompt="p", expected_schema="Insight")
    snap = cap.snapshot()
    assert snap["input_tokens"] == 40
    assert snap["output_tokens"] == 10
    assert snap["model_calls"] == 1
    assert _settlement_audit(cap) == (
        "provider_response",
        "actual_overage",
        "measured",
        1,
    )


def test_complete_charges_input_output_tokens(tmp_path: Path):
    cap = _budget(tmp_path)
    fixture = OfflineFixture.from_payload(
        _insight_payload(),
        usage=OfflineFixtureUsage(input_tokens=12, output_tokens=7),
    )
    gw = AIGateway(provider=fixture, research_budget=cap)
    result = gw.run(role="q", task="t", prompt="p", expected_schema="Insight")
    assert result.usage.input_tokens == 12
    assert result.usage.output_tokens == 7
    snap = cap.snapshot()
    assert snap["input_tokens"] == 12
    assert snap["output_tokens"] == 7
    assert snap["model_calls"] == 1


def test_volatile_budget_releases_exact_estimate_and_charges_actual(tmp_path: Path):
    volatile = GatewayBudget(max_tokens=100)
    fixture = OfflineFixture.from_payload(
        _insight_payload(),
        usage=OfflineFixtureUsage(input_tokens=1, output_tokens=0),
    )
    gw = AIGateway(
        provider=fixture,
        research_budget=_budget(tmp_path),
        budget=volatile,
    )
    gw.run(role="q", task="t", prompt="x" * 80, expected_schema="Insight")
    assert volatile.reserved_calls == 0
    assert volatile.reserved_tokens == 0
    assert volatile.calls_used == 1
    assert volatile.tokens_used == 1


def test_actual_overage_is_recorded_in_both_ledgers_before_failure(tmp_path: Path):
    cap = _budget(tmp_path)
    volatile = GatewayBudget(max_tokens=5)
    fixture = OfflineFixture.from_payload(
        _insight_payload(),
        usage=OfflineFixtureUsage(input_tokens=6, output_tokens=2),
    )
    gw = AIGateway(provider=fixture, research_budget=cap, budget=volatile)
    with pytest.raises(RuntimeError, match="actual usage exceeded volatile budget"):
        gw.run(role="q", task="t", prompt="p", expected_schema="Insight")
    assert volatile.reserved_calls == 0
    assert volatile.reserved_tokens == 0
    assert volatile.calls_used == 1
    assert volatile.tokens_used == 8
    snap = cap.snapshot()
    assert snap["input_tokens"] == 6
    assert snap["output_tokens"] == 2
    assert snap["model_calls"] == 1
    assert _settlement_audit(cap) == (
        "provider_response",
        "actual_overage",
        "measured",
        0,
    )


def test_provider_error_conservatively_settles_estimate_once(tmp_path: Path):
    cap = _budget(tmp_path)
    volatile = GatewayBudget()
    gw = AIGateway(
        provider=OfflineFixture.provider_error("provider failed"),
        research_budget=cap,
        budget=volatile,
    )
    with pytest.raises(OfflineFixtureProviderError, match="provider failed"):
        gw.run(role="q", task="t", prompt="x" * 80, expected_schema="Insight")
    assert volatile.reserved_calls == 0
    assert volatile.reserved_tokens == 0
    assert volatile.calls_used == 1
    assert volatile.tokens_used == 20
    snap = cap.snapshot()
    assert snap["input_tokens"] == 20
    assert snap["model_calls"] == 1
    assert _settlement_audit(cap) == (
        "provider_error",
        "provider_error",
        "reserved_estimate",
        0,
    )


def test_provider_error_with_measured_usage_settles_actual(tmp_path: Path):
    cap = _budget(tmp_path)
    volatile = GatewayBudget()
    fixture = OfflineFixture.provider_error(
        "measured provider failure",
        usage=OfflineFixtureUsage(input_tokens=6, output_tokens=2),
    )
    gw = AIGateway(provider=fixture, research_budget=cap, budget=volatile)
    with pytest.raises(OfflineFixtureProviderError, match="measured provider failure"):
        gw.run(role="q", task="t", prompt="x" * 80, expected_schema="Insight")
    assert volatile.tokens_used == 8
    snap = cap.snapshot()
    assert snap["input_tokens"] == 6
    assert snap["output_tokens"] == 2
    assert snap["model_calls"] == 1
    assert _settlement_audit(cap) == (
        "provider_error",
        "provider_error",
        "measured",
        0,
    )


def test_invalid_usage_conservatively_settles_estimate_once(tmp_path: Path):
    cap = _budget(tmp_path)
    volatile = GatewayBudget()
    gw = AIGateway(
        provider=OfflineFixture.invalid_usage(),
        research_budget=cap,
        budget=volatile,
    )
    with pytest.raises(OfflineFixtureUsageError):
        gw.run(role="q", task="t", prompt="x" * 80, expected_schema="Insight")
    assert volatile.reserved_calls == 0
    assert volatile.reserved_tokens == 0
    assert volatile.calls_used == 1
    assert volatile.tokens_used == 20
    snap = cap.snapshot()
    assert snap["input_tokens"] == 20
    assert snap["model_calls"] == 1
    assert _settlement_audit(cap) == (
        "invalid_usage",
        "invalid_usage",
        "reserved_estimate",
        0,
    )


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
    with pytest.raises(RuntimeError, match="actual usage exceeded"):
        budget.reconcile(reservation, calls=1, tokens=6)
    assert budget.reserved_calls == 0
    assert budget.reserved_tokens == 0
    assert budget.calls_used == 1
    assert budget.tokens_used == 6
