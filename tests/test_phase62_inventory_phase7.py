"""Phase 6.2 residual — inventory SoT and Phase 7 minimal modules."""

from __future__ import annotations

import json
from pathlib import Path

from data_contracts.canonical import (
    CANONICAL_REGISTRY_PATH,
    all_canonical_datasets,
    governed_datasets,
)
from data_contracts.inventory import source_inventory, collection_sla_status
from knowledge.store import KnowledgeStore


def _json_registry_id_lists() -> tuple[list[str], list[str]]:
    document = json.loads(CANONICAL_REGISTRY_PATH.read_text(encoding="utf-8"))
    rows = document["datasets"]
    json_ids = [row["dataset_id"] for row in rows]
    json_gov = [
        row["dataset_id"] for row in rows if row["governance_tier"] == "governed"
    ]
    return json_ids, json_gov


def test_canonical_registry_pins_json_id_sets():
    json_ids, json_gov = _json_registry_id_lists()
    all_ds = all_canonical_datasets()
    gov = governed_datasets()
    loaded_ids = [d.dataset_id for d in all_ds]
    gov_ids = [d.dataset_id for d in gov]
    assert loaded_ids == json_ids
    assert gov_ids == json_gov
    ids = set(loaded_ids)
    assert "jsda_corporate_bond_transactions" in ids
    assert "equities_bars_minute" in ids
    assert "td_bulk" in ids


def test_source_inventory_metadata_only_counts():
    json_ids, json_gov = _json_registry_id_lists()
    inv = source_inventory()
    assert [item["dataset"] for item in inv["datasets"]] == json_ids
    assert inv["total_known_endpoints"] == len(json_ids)
    assert inv["governed_count"] == len(json_gov)
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



