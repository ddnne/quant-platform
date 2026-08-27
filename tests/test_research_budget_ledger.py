import sqlite3
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from selection.budget_ledger import (
    BudgetExhaustedError,
    MassResearchDisabledError,
    ResearchBudgetCapability,
    require_budget_capability,
)
from selection.screen import ExperimentBudget


def test_require_budget_fail_closed():
    with pytest.raises(MassResearchDisabledError):
        require_budget_capability(None)


def test_atomic_consume_and_exhaust(tmp_path: Path):
    cap = ResearchBudgetCapability(
        budget_id="b1",
        ledger_path=tmp_path / "budget.sqlite",
        limits=ExperimentBudget(max_model_calls=3, max_generations=2, max_paper_runs=5),
    )
    cap.consume(model_calls=2)
    assert cap.snapshot()["model_calls"] == 2
    with pytest.raises(BudgetExhaustedError):
        cap.consume(model_calls=2)
    assert cap.snapshot()["model_calls"] == 2  # not partially applied


def test_provider_started_settlement_is_idempotent_and_records_overage(
    tmp_path: Path,
) -> None:
    cap = ResearchBudgetCapability(
        budget_id="provider-settlement",
        ledger_path=tmp_path / "provider-settlement.sqlite",
        limits=ExperimentBudget(max_input_tokens=5, max_output_tokens=5),
    )
    first_over = cap.settle_provider_usage_once(
        settlement_id="settlement-1",
        input_tokens=2,
        output_tokens=1,
        model_calls=1,
        usage_source="measured",
        charge_trigger="provider_response",
    )
    replay_over = cap.settle_provider_usage_once(
        settlement_id="settlement-1",
        input_tokens=2,
        output_tokens=1,
        model_calls=1,
        usage_source="measured",
        charge_trigger="provider_response",
    )
    assert first_over is False
    assert replay_over is False
    assert cap.snapshot()["input_tokens"] == 2
    assert cap.snapshot()["model_calls"] == 1

    with pytest.raises(ValueError, match="idempotency conflict"):
        cap.settle_provider_usage_once(
            settlement_id="settlement-1",
            input_tokens=3,
            output_tokens=1,
            model_calls=1,
            usage_source="measured",
            charge_trigger="provider_response",
        )

    with sqlite3.connect(cap.ledger_path) as conn:
        pending = conn.execute(
            "SELECT charge_trigger, terminal_outcome "
            "FROM research_provider_settlements "
            "WHERE budget_id=? AND settlement_id=?",
            (cap.budget_id, "settlement-1"),
        ).fetchone()
    assert pending == ("provider_response", None)
    cap.finalize_provider_settlement_once(
        settlement_id="settlement-1",
        terminal_outcome="success",
    )
    cap.finalize_provider_settlement_once(
        settlement_id="settlement-1",
        terminal_outcome="success",
    )
    with pytest.raises(ValueError, match="terminal outcome conflict"):
        cap.finalize_provider_settlement_once(
            settlement_id="settlement-1",
            terminal_outcome="schema_reject",
        )

    over_limit = cap.settle_provider_usage_once(
        settlement_id="settlement-2",
        input_tokens=4,
        model_calls=1,
        usage_source="reserved_estimate",
        charge_trigger="provider_error",
    )
    cap.finalize_provider_settlement_once(
        settlement_id="settlement-2",
        terminal_outcome="actual_overage",
    )
    assert over_limit is True
    snap = cap.snapshot()
    assert snap["input_tokens"] == 6
    assert snap["output_tokens"] == 1
    assert snap["model_calls"] == 2
    with pytest.raises(BudgetExhaustedError):
        cap.consume(input_tokens=1)


def test_provider_started_settlement_concurrent_replay_charges_once(
    tmp_path: Path,
) -> None:
    cap = ResearchBudgetCapability(
        budget_id="provider-concurrent",
        ledger_path=tmp_path / "provider-concurrent.sqlite",
        limits=ExperimentBudget(),
    )
    cap.snapshot()  # Create the canonical tables before concurrent settlement.

    def settle() -> bool:
        return cap.settle_provider_usage_once(
            settlement_id="same-settlement",
            input_tokens=3,
            output_tokens=2,
            model_calls=1,
            usage_source="measured",
            charge_trigger="provider_response",
        )

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda _index: settle(), range(16)))
    assert results == [False] * 16
    snap = cap.snapshot()
    assert snap["input_tokens"] == 3
    assert snap["output_tokens"] == 2
    assert snap["model_calls"] == 1


def test_provider_settlement_legacy_table_migrates_to_two_phase_audit(
    tmp_path: Path,
) -> None:
    ledger_path = tmp_path / "legacy-provider-settlement.sqlite"
    with sqlite3.connect(ledger_path) as conn:
        conn.execute(
            """
            CREATE TABLE research_provider_settlements (
                budget_id TEXT NOT NULL,
                settlement_id TEXT NOT NULL,
                input_tokens INTEGER NOT NULL,
                output_tokens INTEGER NOT NULL,
                cached_tokens INTEGER NOT NULL,
                model_calls INTEGER NOT NULL,
                estimated_cost_micros INTEGER NOT NULL,
                usage_source TEXT NOT NULL,
                outcome TEXT NOT NULL,
                over_limit INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                PRIMARY KEY (budget_id, settlement_id)
            )
            """
        )
        conn.execute(
            """
            INSERT INTO research_provider_settlements VALUES (
                'legacy-budget', 'legacy-response', 2, 1, 0, 1, 0,
                'measured', 'provider_response', 0, '2026-01-01T00:00:00+00:00'
            )
            """
        )

    cap = ResearchBudgetCapability(
        budget_id="legacy-budget",
        ledger_path=ledger_path,
        limits=ExperimentBudget(),
    )
    cap.snapshot()
    cap.settle_provider_usage_once(
        settlement_id="post-migration-response",
        input_tokens=3,
        model_calls=1,
        usage_source="measured",
        charge_trigger="provider_response",
    )
    cap.finalize_provider_settlement_once(
        settlement_id="post-migration-response",
        terminal_outcome="success",
    )
    with sqlite3.connect(ledger_path) as conn:
        columns = {
            str(row[1])
            for row in conn.execute(
                "PRAGMA table_info(research_provider_settlements)"
            ).fetchall()
        }
        migrated = conn.execute(
            "SELECT charge_trigger, terminal_outcome, finalized_at "
            "FROM research_provider_settlements WHERE settlement_id=?",
            ("legacy-response",),
        ).fetchone()
        post_migration = conn.execute(
            "SELECT charge_trigger, terminal_outcome "
            "FROM research_provider_settlements WHERE settlement_id=?",
            ("post-migration-response",),
        ).fetchone()
    assert {"charge_trigger", "terminal_outcome", "finalized_at"} <= columns
    assert migrated == ("provider_response", None, None)
    assert post_migration == ("provider_response", "success")


def test_provider_settlement_terminal_outcome_must_match_charge_trigger(
    tmp_path: Path,
) -> None:
    cap = ResearchBudgetCapability(
        budget_id="provider-terminal",
        ledger_path=tmp_path / "provider-terminal.sqlite",
        limits=ExperimentBudget(),
    )
    cap.settle_provider_usage_once(
        settlement_id="provider-failed",
        input_tokens=1,
        model_calls=1,
        usage_source="measured",
        charge_trigger="provider_error",
    )
    with pytest.raises(ValueError, match="conflicts with trigger"):
        cap.finalize_provider_settlement_once(
            settlement_id="provider-failed",
            terminal_outcome="success",
        )
