"""Experiment slot lease authority tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from selection.budget_ledger import (
    BudgetExhaustedError,
    ResearchBudgetCapability,
)
from selection.screen import ExperimentBudget


def test_max_parallel_leases(tmp_path: Path):
    cap = ResearchBudgetCapability(
        "lease-b",
        tmp_path / "l.sqlite",
        ExperimentBudget(max_parallel_experiments=2),
    )
    a = cap.acquire_slot(ttl_seconds=600)
    b = cap.acquire_slot(ttl_seconds=600)
    assert cap.active_lease_count() == 2
    with pytest.raises(BudgetExhaustedError):
        cap.acquire_slot(ttl_seconds=600)
    cap.release(a)
    assert cap.active_lease_count() == 1
    c = cap.acquire_slot(ttl_seconds=600)
    assert c.lease_id != a.lease_id
    cap.release(b)
    cap.release(c)
    assert cap.active_lease_count() == 0


def test_consume_rejects_concurrent_counter(tmp_path: Path):
    cap = ResearchBudgetCapability(
        "c", tmp_path / "c.sqlite", ExperimentBudget()
    )
    with pytest.raises(ValueError, match="lease-based"):
        cap.consume(concurrent_experiments=1)


def test_token_charge(tmp_path: Path):
    cap = ResearchBudgetCapability(
        "t",
        tmp_path / "t.sqlite",
        ExperimentBudget(max_input_tokens=100, max_output_tokens=50),
    )
    cap.charge_provider_usage(input_tokens=40, output_tokens=10, model_calls=1)
    snap = cap.snapshot()
    assert snap["input_tokens"] == 40
    with pytest.raises(BudgetExhaustedError):
        cap.charge_provider_usage(input_tokens=70, model_calls=1)


def test_token_charge_atomic_across_counters(tmp_path: Path):
    """Gateway uses one charge_provider_usage; any cap trip rolls back all counters."""
    cap = ResearchBudgetCapability(
        "t2",
        tmp_path / "t2.sqlite",
        ExperimentBudget(max_input_tokens=100, max_output_tokens=10),
    )
    with pytest.raises(BudgetExhaustedError):
        cap.charge_provider_usage(input_tokens=40, output_tokens=20, model_calls=1)
    snap = cap.snapshot()
    assert snap.get("input_tokens", 0) == 0
    assert snap.get("output_tokens", 0) == 0
    assert snap.get("model_calls", 0) == 0
