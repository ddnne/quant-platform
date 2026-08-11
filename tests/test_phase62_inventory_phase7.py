"""Phase 6.2 residual — inventory SoT and Phase 7 minimal modules."""

from __future__ import annotations

from pathlib import Path

from data_contracts.canonical import all_canonical_datasets, governed_datasets
from data_contracts.inventory import source_inventory, collection_sla_status
from gateway.ai import AIGateway, ALLOWED_OUTPUT_SCHEMAS
from knowledge.store import KnowledgeStore
from selection.screen import ExperimentBudget, early_stop, screen_candidates


def test_canonical_registry_has_31_endpoints_and_26_governed():
    all_ds = all_canonical_datasets()
    gov = governed_datasets()
    assert len(all_ds) == 31
    assert len(gov) == 26
    ids = {d.dataset_id for d in all_ds}
    assert "jsda_corporate_bond_transactions" in ids
    assert "equities_bars_minute" in ids
    assert "td_bulk" in ids


def test_source_inventory_metadata_only_counts():
    inv = source_inventory()
    assert inv["total_known_endpoints"] == 31
    assert inv["governed_count"] == 26
    assert "GOVERNED" in inv["status_counts"]
    assert inv["plane"] == "ops_current"


def test_am_sla_is_present():
    rows = collection_sla_status()
    am = next(r for r in rows["datasets"] if r["dataset"] == "equities_bars_daily_am")
    assert am["sla"].get("usable_by") == "12:30"
    assert am["sla"].get("freshness_policy") == "same_trading_day_am"


def test_knowledge_store_create_if_absent(tmp_path: Path):
    store = KnowledgeStore(tmp_path / "k")
    first = store.put(
        artifact_type="Insight",
        schema_version="1",
        producer_role="quant",
        payload={"note": "a"},
    )
    second = store.put(
        artifact_type="Insight",
        schema_version="1",
        producer_role="quant",
        payload={"note": "a"},
    )
    assert first.artifact_id == second.artifact_id
    assert store.get(first.artifact_id) is not None


def test_selection_budget_and_gateway_closed_schema():
    budget = ExperimentBudget(max_generations=2, max_paper_runs=5, max_model_calls=3)
    assert early_stop(generation=2, paper_runs=0, model_calls=0, budget=budget)
    ranked = screen_candidates(
        [{"id": "a", "score": 0.1}, {"id": "b", "score": 0.9}],
        min_score=0.5,
        limit=1,
    )
    assert ranked[0]["id"] == "b"
    out = AIGateway().run(
        role="strategist", task="memo", prompt="x", expected_schema="Insight"
    )
    assert out["schema"] in ALLOWED_OUTPUT_SCHEMAS
